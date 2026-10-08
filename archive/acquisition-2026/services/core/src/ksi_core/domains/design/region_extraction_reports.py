"""변화 영역 추출 리포트 원장 + 재관찰 초안 핸드오프 (M4-E).

``design_conformance_reports.py`` 의 형제이되 **바이트 재해싱이 없다**. 이
리포트가 참조하는 diffRaster 는 이미 ``design_conformance_reports.py`` 가
기록 시점에 재해싱을 확인한 바이트이고, RECORDED 된 설계 대비 잔량 리포트는
종료 후 불변이다 — 그 바이트를 다시 읽어 다시 해싱할 이유가 없다. 그래서
이 원장의 판정은 순수 값 대조뿐이다.

## 판정 — 순수 값 대조

1. 리포트가 가리키는 요청이 있는가, 그 요청이 이 임무 소속인가.
2. ``report.designConformanceId`` 가 요청이 지목한 것과 같은가.
3. ``report.crs``/``report.thresholdM`` 이 원본 설계 대비 잔량 리포트의
   ``crs``/``diffRaster.thresholdM`` 과 같은가 — 다르면 화면의 범례와 이
   결과가 다른 기준을 말한다.
4. ``report.extractionPolicy`` 가 ``current_region_extraction_policy()`` 와
   같은가 — ``design_conformance_reports.py`` 의 ``POLICY_MISMATCH`` 패턴을
   그대로 재사용하되, 대조 대상이 **요청 시점 스냅샷이 아니라 지금 이 순간의
   정책**이다(policy-owned 기반안, ``region_extraction_requests.py`` 모듈
   docstring).

## 재관찰 초안 핸드오프 — "발급됨" 상태는 없다

``/regions/{regionId}/spatial-refresh-draft`` 는 영역의 볼록 껍질(WGS84)을
실제 :class:`~ksi_mission_planning.geometry.AreaOfInterest` 로 구성·검증해
돌려준다. Core 는 이미 ``mission_plans.py`` 에서 이 패키지에 의존하므로 새
결합이 아니다. 극지·10km 초과·자기교차는 여기서 typed 오류로 걸려 422 로
나간다 — **이 엔드포인트는 임무 발급 절차를 대신하지 않는다.** 실제
``POST /v1/missions/plans`` 호출·``MISSIONS_ISSUE``·``mission_gating``
(INV-052)·``lawnmower_route`` 의 ``NON_CONVEX_AOI`` 는 사람이 그 AOI 를
복사해 발급을 부를 때 독립적으로 다시 돈다.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from ksi_event_contracts.change_region_report import ChangeRegion, ChangeRegionSetReport
from ksi_event_contracts.region_extraction_policy import current_region_extraction_policy
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_planning import (
    DEFAULT_FRONT_OVERLAP,
    DEFAULT_SIDE_OVERLAP,
    BaselineCapture,
    CameraSpec,
    CameraSpecError,
    ChangeSignals,
    ReobservationCapturePlan,
    derive_reobservation_capture,
)
from ksi_mission_planning.geometry import AreaOfInterest, GeoPoint
from pydantic import ValidationError

from ksi_core.domains.design.region_extraction_requests import RegionExtractionRequestRecord
from ksi_core.foundation.api_base import (
    JOURNAL_APPEND_FAILED_DETAIL,
    JOURNAL_SEALED_DETAIL,
    CamelModel,
    iso_utc,
)
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.leasing import LeaseFence
from ksi_core.identity.auth import (
    Permission,
    Principal,
    current_request_organization_id,
    require_permission,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.design.design_conformance_reports import DesignConformanceStore
    from ksi_core.domains.design.region_extraction_requests import RegionExtractionRequestStore
    from ksi_core.domains.missions.mission_records import MissionRecord, MissionStore

logger = logging.getLogger("ksi_core.region_extraction_reports")

#: 세 곳의 문턱값이 같은지 볼 때의 허용 오차 — ``design_conformance_report.
#: _THRESHOLD_TOLERANCE_M`` 과 같은 자릿수.
_THRESHOLD_TOLERANCE_M = 1e-12

#: 직전 촬영 조건을 알 수 없을 때의 사유 코드. ``ChangeRegion.
#: aoi_draft_unavailable_reason`` 과 같은 관용구다 — 모르는 값을 기본값으로
#: 채우지 않고 "모른다"를 코드로 낸다.
_BASELINE_UNKNOWN = "BASELINE_CAPTURE_UNKNOWN"
_CAPTURE_DERIVATION_FAILED = "CAPTURE_DERIVATION_FAILED"


class RegionExtractionVerdict(StrEnum):
    """수신 판정. ``RECORDED`` 만 durable 기록 성공이다."""

    RECORDED = "RECORDED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    #: 이 리포트가 가리키는 요청이 없다 — changeRegionSetId 는 요청에서 도출된다.
    UNKNOWN_REQUEST = "UNKNOWN_REQUEST"
    #: 요청은 있는데 다른 임무의 것이다.
    REQUEST_MISMATCH = "REQUEST_MISMATCH"
    #: 리포트의 designConformanceId 가 요청이 지목한 것과 다르다.
    DESIGN_CONFORMANCE_MISMATCH = "DESIGN_CONFORMANCE_MISMATCH"
    #: 참조하는 설계 대비 잔량 리포트를 더 이상 찾을 수 없다(불변 원장에서는
    #: 발생해선 안 되지만, 방어적으로 typed 사유를 둔다).
    UNKNOWN_DESIGN_CONFORMANCE = "UNKNOWN_DESIGN_CONFORMANCE"
    CRS_MISMATCH = "CRS_MISMATCH"
    THRESHOLD_MISMATCH = "THRESHOLD_MISMATCH"
    #: 리포트가 지금 이 순간의 ``current_region_extraction_policy()`` 와 다른
    #: 기준값으로 계산됐다(policy-owned — 모듈 docstring).
    EXTRACTION_POLICY_MISMATCH = "EXTRACTION_POLICY_MISMATCH"
    LEASE_REQUIRED = "LEASE_REQUIRED"
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    STALE_LEASE_ACQUISITION = "STALE_LEASE_ACQUISITION"
    STALE_LEASE_GENERATION = "STALE_LEASE_GENERATION"
    INVALID_LEASE_FENCE = "INVALID_LEASE_FENCE"
    DUPLICATE_REPORT_ID = "DUPLICATE_REPORT_ID"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[RegionExtractionVerdict, int] = {
    RegionExtractionVerdict.RECORDED: 201,
    RegionExtractionVerdict.UNKNOWN_MISSION: 404,
    RegionExtractionVerdict.UNKNOWN_REQUEST: 422,
    RegionExtractionVerdict.REQUEST_MISMATCH: 422,
    RegionExtractionVerdict.DESIGN_CONFORMANCE_MISMATCH: 422,
    RegionExtractionVerdict.UNKNOWN_DESIGN_CONFORMANCE: 422,
    RegionExtractionVerdict.CRS_MISMATCH: 422,
    RegionExtractionVerdict.THRESHOLD_MISMATCH: 422,
    RegionExtractionVerdict.EXTRACTION_POLICY_MISMATCH: 422,
    RegionExtractionVerdict.LEASE_REQUIRED: 409,
    RegionExtractionVerdict.LEASE_HELD_BY_ANOTHER: 409,
    RegionExtractionVerdict.STALE_LEASE_ACQUISITION: 409,
    RegionExtractionVerdict.STALE_LEASE_GENERATION: 409,
    RegionExtractionVerdict.INVALID_LEASE_FENCE: 422,
    RegionExtractionVerdict.DUPLICATE_REPORT_ID: 409,
    RegionExtractionVerdict.STORE_UNAVAILABLE: 503,
}


class RegionExtractionRecoveryError(RuntimeError):
    """region-extraction journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


@dataclass(frozen=True, slots=True)
class RegionExtractionRecordResult:
    verdict: RegionExtractionVerdict
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedRegionExtraction:
    report: ChangeRegionSetReport
    reported_by: str | None
    recorded_at: datetime
    request_id: str | None = None
    accepted_lease_fence: LeaseFence | None = None


class RegionExtractionStore:
    """``DurableJournal`` 위의 변화 영역 추출 리포트 원장 — append-only, 덮어쓰지 않는다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        request_store: RegionExtractionRequestStore,
        design_conformance_report_store: DesignConformanceStore,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._request_store = request_store
        self._design_conformance_report_store = design_conformance_report_store
        self._lock = threading.Lock()
        self._by_mission: dict[str, list[RecordedRegionExtraction]] = {}
        self._ids_by_mission: dict[str, dict[str, ChangeRegionSetReport]] = {}
        try:
            self._replay(journal)
        except RegionExtractionRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise RegionExtractionRecoveryError(
                f"region-extraction journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def mission_is_visible(self, mission_id: str) -> bool:
        """Mission 원장 scope 밖의 변화 영역 결과는 존재하지 않는 것으로 취급한다."""

        return self._mission_store.get(mission_id) is not None

    # ── 재생 ─────────────────────────────────────────────────────────────

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "region-extraction-rejected":
                continue
            if kind != "region-extraction-recorded":
                raise RegionExtractionRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")
            mission_id = raw["missionId"]
            report = ChangeRegionSetReport.model_validate(raw["report"])
            verdict, detail = self._judge(report, mission_id)
            if verdict is not RegionExtractionVerdict.RECORDED:
                raise RegionExtractionRecoveryError(
                    f"재생: 기록될 수 없는 리포트({verdict.value}: {detail}) — "
                    f"missionId={mission_id} changeRegionSetId={report.change_region_set_id}"
                )
            request_id, fence = self._replay_authority(raw, report)
            if fence is not None and not self._request_store.has_recorded_lease_fence(
                report.change_region_set_id,
                fence,
                authenticated_actor_id=raw.get("reportedBy"),
            ):
                raise RegionExtractionRecoveryError(
                    "재생: result authority가 durable request lease history에 없다"
                )
            self._project(
                mission_id,
                report,
                raw.get("reportedBy"),
                datetime.fromisoformat(raw["ts"]),
                request_id=request_id,
                accepted_lease_fence=fence,
            )

    @staticmethod
    def _replay_authority(
        raw: dict[str, Any], report: ChangeRegionSetReport
    ) -> tuple[str | None, LeaseFence | None]:
        if raw.get("authorityVersion") is None:
            return None, None
        if raw.get("authorityVersion") != 1 or raw.get("requestId") != report.change_region_set_id:
            raise RegionExtractionRecoveryError("재생: malformed result authority")
        fields = raw.get("acceptedLeaseFence")
        if not isinstance(fields, dict):
            raise RegionExtractionRecoveryError("재생: missing accepted lease fence")
        try:
            fence = LeaseFence(
                str(fields["workerInstanceId"]),
                str(fields["leaseAcquisitionId"]),
                int(fields["leaseGeneration"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RegionExtractionRecoveryError("재생: malformed accepted lease fence") from exc
        if not fence.is_well_formed():
            raise RegionExtractionRecoveryError("재생: invalid accepted lease fence")
        return report.change_region_set_id, fence

    def _project(
        self,
        mission_id: str,
        report: ChangeRegionSetReport,
        reported_by: str | None,
        recorded_at: datetime,
        *,
        request_id: str | None = None,
        accepted_lease_fence: LeaseFence | None = None,
    ) -> None:
        recorded = RecordedRegionExtraction(
            report=report,
            reported_by=reported_by,
            recorded_at=recorded_at,
            request_id=request_id,
            accepted_lease_fence=accepted_lease_fence,
        )
        self._by_mission.setdefault(mission_id, []).append(recorded)
        self._ids_by_mission.setdefault(mission_id, {})[report.change_region_set_id] = report

    # ── 판정 (live·재생 공유) ─────────────────────────────────────────────

    def _judge(
        self, report: ChangeRegionSetReport, mission_id: str
    ) -> tuple[RegionExtractionVerdict, str | None]:
        """리포트가 **그 요청의 결과로 성립하는가** — live 수신과 재생이 같은 함수를 쓴다."""
        request = self._request_store.get_by_change_region_set_id(report.change_region_set_id)
        if request is None:
            return (
                RegionExtractionVerdict.UNKNOWN_REQUEST,
                f"changeRegionSetId={report.change_region_set_id!r} 에 해당하는 변화 영역 "
                "추출 요청이 없다 — 지시 없이 만들어진 결과는 받지 않는다",
            )
        if request.mission_id != mission_id:
            return (
                RegionExtractionVerdict.REQUEST_MISMATCH,
                f"그 요청은 임무 {request.mission_id!r} 소속인데 경로의 missionId 는 "
                f"{mission_id!r} 다",
            )
        return self._judge_against_request(report, request)

    def _judge_against_request(
        self, report: ChangeRegionSetReport, request: RegionExtractionRequestRecord
    ) -> tuple[RegionExtractionVerdict, str | None]:
        if report.design_conformance_id != request.design_conformance_id:
            return (
                RegionExtractionVerdict.DESIGN_CONFORMANCE_MISMATCH,
                f"리포트의 designConformanceId({report.design_conformance_id}) 가 요청이 "
                f"지목한 것({request.design_conformance_id}) 과 다르다",
            )
        entry = self._design_conformance_report_store.get(
            request.mission_id, request.design_conformance_id
        )
        if entry is None:  # pragma: no cover -- 생성 게이트가 이미 존재를 보장했다(불변 원장)
            return (
                RegionExtractionVerdict.UNKNOWN_DESIGN_CONFORMANCE,
                "참조하는 설계 대비 잔량 리포트를 더 이상 찾을 수 없다",
            )
        if report.crs != entry.report.crs:
            return (
                RegionExtractionVerdict.CRS_MISMATCH,
                f"리포트의 crs({report.crs}) 가 원본 설계 대비 잔량 리포트의 "
                f"crs({entry.report.crs}) 와 다르다",
            )
        if not math.isclose(
            report.threshold_m, entry.report.diff_raster.threshold_m, abs_tol=_THRESHOLD_TOLERANCE_M
        ):
            return (
                RegionExtractionVerdict.THRESHOLD_MISMATCH,
                f"리포트의 thresholdM({report.threshold_m}) 이 원본 diffRaster 의 "
                f"thresholdM({entry.report.diff_raster.threshold_m}) 과 다르다",
            )
        if report.extraction_policy != current_region_extraction_policy():
            return (
                RegionExtractionVerdict.EXTRACTION_POLICY_MISMATCH,
                "리포트가 지금 이 배포의 추출 기준값이 아닌 다른 값으로 계산됐다 — "
                "화면이 표시하는 기준과 실제로 쓴 기준이 갈린다",
            )
        return RegionExtractionVerdict.RECORDED, None

    # ── live 경로 ────────────────────────────────────────────────────────

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def record(
        self,
        mission_id: str,
        report: ChangeRegionSetReport,
        *,
        now: datetime,
        reported_by: str | None = None,
        lease_fence: LeaseFence | None = None,
    ) -> RegionExtractionRecordResult:
        if lease_fence is None:
            # Compatibility only for direct in-process legacy fixtures and
            # old journal tooling.  The HTTP worker route below always
            # requires a complete fence before it can reach this branch.
            return self._record_legacy(mission_id, report, now=now, reported_by=reported_by)
        request_id = report.change_region_set_id
        # Lock ordering is fixed: request-store -> report-store.  Do not call
        # request-store getters inside the report lock; use the yielded
        # snapshot so a takeover cannot slip between lease check and append.
        with self._request_store.result_commit_guard(
            request_id, lease_fence=lease_fence, authenticated_actor_id=reported_by, now=now
        ) as authorization:
            if not authorization.authorized:
                return self._lease_denial(authorization.verdict, authorization.detail)
            request = authorization.record
            assert request is not None  # noqa: S101 -- guard invariant
            return self._record_authorized(
                mission_id,
                report,
                request=request,
                lease_fence=lease_fence,
                now=now,
                reported_by=reported_by,
            )

    def _record_legacy(
        self,
        mission_id: str,
        report: ChangeRegionSetReport,
        *,
        now: datetime,
        reported_by: str | None,
    ) -> RegionExtractionRecordResult:
        with self._lock:
            if self._journal.sealed_reason is not None:
                return RegionExtractionRecordResult(
                    RegionExtractionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            if self._mission_store.get(mission_id) is None:
                return self._reject(
                    mission_id, report, now, reported_by, RegionExtractionVerdict.UNKNOWN_MISSION,
                    "발급된 적 없는 임무의 변화 영역 추출 리포트는 받지 않는다",
                )
            existing = self._ids_by_mission.get(mission_id, {}).get(report.change_region_set_id)
            if existing is not None:
                if existing == report:
                    return RegionExtractionRecordResult(
                        RegionExtractionVerdict.RECORDED,
                        detail="이미 같은 내용으로 기록돼 있다(멱등 재전송)",
                    )
                return self._reject(
                    mission_id, report, now, reported_by,
                    RegionExtractionVerdict.DUPLICATE_REPORT_ID,
                    f"changeRegionSetId={report.change_region_set_id!r} 는 이미 다른 "
                    "내용으로 기록됐다",
                )
            verdict, detail = self._judge(report, mission_id)
            if verdict is not RegionExtractionVerdict.RECORDED:
                return self._reject(mission_id, report, now, reported_by, verdict, detail)
            raw = {
                "kind": "region-extraction-recorded",
                "ts": iso_utc(now),
                "missionId": mission_id,
                "reportedBy": reported_by,
                "report": report.model_dump(by_alias=True, mode="json", exclude_none=False),
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return RegionExtractionRecordResult(
                    RegionExtractionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_APPEND_FAILED_DETAIL
                )
            self._project(mission_id, report, reported_by, now)
            return RegionExtractionRecordResult(RegionExtractionVerdict.RECORDED)

    def _record_authorized(
        self,
        mission_id: str,
        report: ChangeRegionSetReport,
        *,
        request: RegionExtractionRequestRecord,
        lease_fence: LeaseFence | None,
        now: datetime,
        reported_by: str | None,
    ) -> RegionExtractionRecordResult:
        with self._lock:
            if self._journal.sealed_reason is not None:
                return RegionExtractionRecordResult(
                    RegionExtractionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            if self._mission_store.get(mission_id) is None:
                return self._reject(
                    mission_id,
                    report,
                    now,
                    reported_by,
                    RegionExtractionVerdict.UNKNOWN_MISSION,
                    "발급된 적 없는 임무의 변화 영역 추출 리포트는 받지 않는다",
                )
            if request.mission_id != mission_id:
                return RegionExtractionRecordResult(
                    RegionExtractionVerdict.REQUEST_MISMATCH,
                    "변화 영역 추출 요청의 missionId 가 결과 경로와 다르다",
                )
            existing = self._ids_by_mission.get(mission_id, {}).get(report.change_region_set_id)
            if existing is not None:
                if existing == report:
                    return RegionExtractionRecordResult(
                        RegionExtractionVerdict.RECORDED,
                        detail="이미 같은 내용으로 기록돼 있다(멱등 재전송)",
                    )
                return self._reject(
                    mission_id,
                    report,
                    now,
                    reported_by,
                    RegionExtractionVerdict.DUPLICATE_REPORT_ID,
                    f"changeRegionSetId={report.change_region_set_id!r} 는 이미 다른 내용으로 "
                    "기록됐다 — 같은 id 로 다른 결과를 덮어쓸 수 없다",
                )
            # ``_judge`` would call back into the request store while its lock
            # is held.  The guard snapshot is the exact request observed at
            # the authority boundary.
            verdict, detail = self._judge_against_request(report, request)
            if verdict is not RegionExtractionVerdict.RECORDED:
                return RegionExtractionRecordResult(verdict, detail=detail)

            assert lease_fence is not None  # noqa: S101 -- guard only authorizes full fence
            record = {
                "kind": "region-extraction-recorded",
                "authorityVersion": 1,
                "ts": iso_utc(now),
                "missionId": mission_id,
                "requestId": request.request_id,
                "acceptedLeaseFence": {
                    "workerInstanceId": lease_fence.worker_instance_id,
                    "leaseAcquisitionId": lease_fence.lease_acquisition_id,
                    "leaseGeneration": lease_fence.lease_generation,
                },
                "reportedBy": reported_by,
                "report": report.model_dump(by_alias=True, mode="json", exclude_none=False),
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return RegionExtractionRecordResult(
                    RegionExtractionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_APPEND_FAILED_DETAIL
                )
            self._project(
                mission_id,
                report,
                reported_by,
                now,
                request_id=request.request_id,
                accepted_lease_fence=lease_fence,
            )
            return RegionExtractionRecordResult(RegionExtractionVerdict.RECORDED)

    @staticmethod
    def _lease_denial(verdict: Any, detail: str | None) -> RegionExtractionRecordResult:
        mapping = {
            "UNKNOWN_REQUEST": RegionExtractionVerdict.UNKNOWN_REQUEST,
            "LEASE_REQUIRED": RegionExtractionVerdict.LEASE_REQUIRED,
            "LEASE_HELD_BY_ANOTHER": RegionExtractionVerdict.LEASE_HELD_BY_ANOTHER,
            "STALE_LEASE_ACQUISITION": RegionExtractionVerdict.STALE_LEASE_ACQUISITION,
            "STALE_LEASE_GENERATION": RegionExtractionVerdict.STALE_LEASE_GENERATION,
            "INVALID_LEASE_FENCE": RegionExtractionVerdict.INVALID_LEASE_FENCE,
            "STORE_UNAVAILABLE": RegionExtractionVerdict.STORE_UNAVAILABLE,
        }
        return RegionExtractionRecordResult(
            mapping.get(str(verdict), RegionExtractionVerdict.LEASE_REQUIRED), detail
        )

    def _reject(
        self,
        mission_id: str,
        report: ChangeRegionSetReport,
        now: datetime,
        reported_by: str | None,
        verdict: RegionExtractionVerdict,
        detail: str | None,
    ) -> RegionExtractionRecordResult:
        """거부도 원장에 남긴다 — 신뢰 경계에서 튕겨 나간 제출은 특히 남아야 한다."""
        record = {
            "kind": "region-extraction-rejected",
            "ts": iso_utc(now),
            "missionId": mission_id,
            "changeRegionSetId": report.change_region_set_id,
            "verdict": verdict.value,
            "detail": detail,
            "reportedBy": reported_by,
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return RegionExtractionRecordResult(
                RegionExtractionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_APPEND_FAILED_DETAIL
            )
        return RegionExtractionRecordResult(verdict, detail=detail)

    def list_for_mission(
        self, mission_id: str
    ) -> list[RecordedRegionExtraction]:
        """최신이 먼저."""
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return []
        with self._lock:
            return list(reversed(self._by_mission.get(mission_id, ())))

    def get(
        self, mission_id: str, change_region_set_id: str
    ) -> RecordedRegionExtraction | None:
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return None
        with self._lock:
            for entry in reversed(self._by_mission.get(mission_id, ())):
                if entry.report.change_region_set_id == change_region_set_id:
                    return entry
        return None

    def mission_of(self, mission_id: str) -> MissionRecord | None:
        """그 임무의 발급 기록 — 재관찰 초안이 직전 촬영 조건을 읽는 유일한 통로.

        이 저장소가 이미 물고 있는 ``mission_store`` 를 라우터에 노출하는 좁은
        접근자다(``sealed_reason`` 과 같은 관용구) — 라우터가 사설 속성
        (``store._mission_store``)에 직접 닿지 않게 한다.
        """
        return self._mission_store.get(mission_id)


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class RegionExtractionResponse(CamelModel):
    verdict: str
    detail: str | None


class RegionExtractionEntry(CamelModel):
    report: dict[str, Any]
    reported_by: str | None
    recorded_at: datetime


class RegionExtractionListView(CamelModel):
    mission_id: str
    report_count: int
    reports: list[RegionExtractionEntry]


class SpatialRefreshDraftVerdict(StrEnum):
    DRAFT_READY = "DRAFT_READY"


class SpatialRefreshDraftResponse(CamelModel):
    """재관찰 초안 — "발급됨" 이 아니다(모듈 docstring). AOI + 촬영 계획 초안을 준다.

    촬영 계획 필드(``capture*``)는 :func:`~ksi_mission_planning.
    derive_reobservation_capture` 의 순수 도출 결과다(ADR-KSI-019 G5) — 최종
    게이트가 아니라 **제안**이다. 직전 촬영 조건을 알 수 없으면(계약 단독 발급
    등) ``captureUnavailableReason`` 만 채우고 나머지 ``capture*`` 는 null 이다.
    """

    verdict: str
    aoi: dict[str, Any] | None = None
    hull_overcapture_ratio: float | None = None
    region_area_m2: float | None = None
    net_m3: float | None = None
    cut_m3: float | None = None
    fill_m3: float | None = None
    unmeasurable_ratio: float | None = None
    site_unmeasurable_cell_ratio: float | None = None
    capture_grade: str | None = None
    capture_altitude_m: float | None = None
    capture_front_overlap: float | None = None
    capture_side_overlap: float | None = None
    capture_interval_m: float | None = None
    capture_gsd_m: float | None = None
    baseline_gsd_m: float | None = None
    capture_signal_to_noise: float | None = None
    #: 왜 이 등급인지 사람이 읽는 근거 문장들. 도출이 성립했으면 절대 비지 않는다.
    capture_rationale: list[str] = []
    #: 도출이 성립하지 않은 사유. ``BASELINE_CAPTURE_UNKNOWN``(직전 촬영 조건을
    #: 모른다) 또는 ``CAPTURE_DERIVATION_FAILED``(조건은 있으나 도출이 실패했다).
    capture_unavailable_reason: str | None = None
    detail: str | None = None


def _entry_view(entry: RecordedRegionExtraction) -> RegionExtractionEntry:
    return RegionExtractionEntry(
        report=entry.report.model_dump(by_alias=True, mode="json", exclude_none=False),
        reported_by=entry.reported_by,
        recorded_at=entry.recorded_at,
    )


def _find_region(report: ChangeRegionSetReport, region_id: str) -> ChangeRegion | None:
    return next((r for r in report.regions if r.region_id == region_id), None)


def _baseline_capture_of(record: MissionRecord) -> BaselineCapture | None:
    """그 임무의 발급 요청에서 직전 촬영 조건을 읽는다 — 없으면 ``None``.

    ``plan_request`` 는 짝 발급(``artifact_kind="pair"``)에만 있다. 계약 단독
    발급은 경로가 없으므로 고도·카메라도 없다. 요청이 카메라를 직접 지정하지
    않고 간격(spacing/captureInterval)을 직접 준 경로(INV-015 의 "직접 지정
    경로")도 GSD 를 계산할 근거가 없으므로 모른다고 답한다 — 기본값을 지어내지
    않는다.
    """
    plan_request = record.plan_request
    if not isinstance(plan_request, dict):
        return None
    route = plan_request.get("route")
    if not isinstance(route, dict):
        return None
    camera = route.get("camera")
    if not isinstance(camera, dict):
        return None
    try:
        return BaselineCapture(
            altitude_m=float(route["altitudeM"]),
            front_overlap=float(camera.get("frontOverlap", DEFAULT_FRONT_OVERLAP)),
            side_overlap=float(camera.get("sideOverlap", DEFAULT_SIDE_OVERLAP)),
            camera=CameraSpec(
                sensor_width_mm=float(camera["sensorWidthMm"]),
                focal_length_mm=float(camera["focalLengthMm"]),
                image_width_px=int(camera["imageWidthPx"]),
                image_height_px=int(camera["imageHeightPx"]),
            ),
        )
    except (KeyError, TypeError, ValueError, CameraSpecError):
        return None


def _aoi_from_hull_wgs84(hull_polygon_wgs84: dict[str, Any]) -> AreaOfInterest:
    """볼록 껍질(WGS84 GeoJSON Polygon) → :class:`AreaOfInterest`.

    GeoJSON 링은 닫혀 있다(첫 점 = 마지막 점) — ``AreaOfInterest`` 는 마지막→첫
    변을 암묵적으로 닫으므로, 닫는 중복 꼭짓점을 빼지 않으면 "중복 꼭짓점"으로
    거부된다.

    ``hull_polygon_wgs84`` 는 구조 검증 없는 ``dict[str, Any]`` 다(저장 시점의
    hull 계산 결과를 그대로 실은 것) — ``coordinates``/링/좌표 쌍 중 하나라도
    어긋나면 ``KeyError``/``IndexError``/``TypeError`` 대신 ``ValueError`` 로
    바꿔 던진다. 호출부가 typed 422 로 잡는 예외가 ``(ValidationError,
    ValueError)`` 뿐이라, 여기서 잡지 않으면 잘못된 hull 이 500 으로 샌다.
    """
    try:
        ring = hull_polygon_wgs84["coordinates"][0]
        vertices = [GeoPoint(lon_deg=float(lon), lat_deg=float(lat)) for lon, lat in ring]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"hull GeoJSON 구조가 올바르지 않다: {exc}") from exc
    if len(vertices) >= 2 and vertices[0] == vertices[-1]:
        vertices = vertices[:-1]
    return AreaOfInterest(vertices=vertices)


def build_region_extraction_router(store: RegionExtractionStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["region-extraction"])

    @router.post("/{mission_id}/region-extraction", status_code=201)
    def submit_region_extraction(
        mission_id: str,
        report: ChangeRegionSetReport,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> RegionExtractionResponse:
        """변화 영역 추출 리포트 접수 — **처리 워커만** 올린다."""
        try:
            fence = (
                LeaseFence(worker_instance_id, lease_acquisition_id, int(lease_generation))
                if worker_instance_id is not None
                and lease_acquisition_id is not None
                and lease_generation is not None
                else None
            )
        except ValueError:
            fence = None
        if fence is None:
            outcome = RegionExtractionRecordResult(
                RegionExtractionVerdict.INVALID_LEASE_FENCE,
                "worker instance, acquisition id, generation 이 유효한 lease fence 가 아니다",
            )
        else:
            outcome = store.record(
                mission_id,
                report,
                now=datetime.now(UTC),
                reported_by=principal.principal_id,
                lease_fence=fence,
            )
        response.status_code = _STATUS[outcome.verdict]
        if outcome.verdict is RegionExtractionVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return RegionExtractionResponse(verdict=outcome.verdict.value, detail=outcome.detail)

    @router.get("/{mission_id}/region-extraction", response_model=RegionExtractionListView)
    def list_region_extraction(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> RegionExtractionListView:
        """그 임무의 변화 영역 추출 이력(최신 우선). 없으면 404."""
        if not store.mission_is_visible(mission_id):
            raise HTTPException(
                status_code=404, detail="해당 변화 영역 추출 리포트를 찾을 수 없다"
            )
        entries = store.list_for_mission(mission_id)
        if not entries:
            raise HTTPException(
                status_code=404, detail="해당 임무의 변화 영역 추출 리포트를 찾을 수 없다"
            )
        return RegionExtractionListView(
            mission_id=mission_id,
            report_count=len(entries),
            reports=[_entry_view(entry) for entry in entries],
        )

    @router.get(
        "/{mission_id}/region-extraction/{change_region_set_id}",
        response_model=RegionExtractionEntry,
    )
    def get_region_extraction(
        mission_id: str,
        change_region_set_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> RegionExtractionEntry:
        entry = store.get(mission_id, change_region_set_id)
        if entry is None:
            raise HTTPException(
                status_code=404, detail="해당 변화 영역 추출 리포트를 찾을 수 없다"
            )
        return _entry_view(entry)

    @router.get(
        "/{mission_id}/region-extraction/{change_region_set_id}/regions/{region_id}"
        "/spatial-refresh-draft",
        response_model=SpatialRefreshDraftResponse,
    )
    def get_spatial_refresh_draft(
        mission_id: str,
        change_region_set_id: str,
        region_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> SpatialRefreshDraftResponse:
        """이 영역의 볼록 껍질(WGS84)을 재관찰 AOI 초안으로 준다 — "발급됨" 은 아니다."""
        entry = store.get(mission_id, change_region_set_id)
        if entry is None:
            raise HTTPException(
                status_code=404, detail="해당 변화 영역 추출 리포트를 찾을 수 없다"
            )
        region = _find_region(entry.report, region_id)
        if region is None:
            raise HTTPException(status_code=404, detail="해당 영역을 찾을 수 없다")
        if region.convex_hull_polygon_wgs84 is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "이 영역은 재관찰 초안을 만들 수 없다 — hull 계산이 실패했다"
                    + (
                        f"({region.aoi_draft_unavailable_reason})"
                        if region.aoi_draft_unavailable_reason
                        else ""
                    )
                ),
            )
        try:
            aoi = _aoi_from_hull_wgs84(region.convex_hull_polygon_wgs84)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"이 영역의 hull 이 유효한 재관찰 구역을 만들지 못한다: {exc}",
            ) from exc

        capture: ReobservationCapturePlan | None = None
        capture_unavailable: str | None = None
        mission = store.mission_of(mission_id)
        baseline = _baseline_capture_of(mission) if mission is not None else None
        if baseline is None or mission is None:
            capture_unavailable = _BASELINE_UNKNOWN
        else:
            try:
                envelope_raw = (mission.contract or {}).get("flightEnvelope")
                if not isinstance(envelope_raw, dict):
                    raise ValueError("계약에 flightEnvelope 이 없다")  # noqa: TRY301
                capture = derive_reobservation_capture(
                    baseline=baseline,
                    signals=ChangeSignals(
                        area_m2=region.volume.area_m2,
                        cut_m3=region.volume.cut_m3,
                        fill_m3=region.volume.fill_m3,
                        volume_threshold_m=region.volume.threshold_m,
                        unmeasurable_ratio=region.unmeasurable_ratio,
                    ),
                    envelope=FlightEnvelope.model_validate(envelope_raw),
                )
            except (ValueError, ValidationError) as exc:
                # 도출 실패가 AOI 초안까지 죽이지 않는다 — AOI 는 그 자체로 유용하다.
                capture_unavailable = _CAPTURE_DERIVATION_FAILED
                logger.warning(
                    "재관측 촬영 계획 도출 실패 mission=%s changeRegionSetId=%s "
                    "regionId=%s: %s",
                    mission_id,
                    change_region_set_id,
                    region_id,
                    exc,
                )

        return SpatialRefreshDraftResponse(
            verdict=SpatialRefreshDraftVerdict.DRAFT_READY.value,
            aoi=aoi.model_dump(by_alias=True, mode="json"),
            hull_overcapture_ratio=region.hull_overcapture_ratio,
            region_area_m2=region.volume.area_m2,
            net_m3=region.volume.net_m3,
            cut_m3=region.volume.cut_m3,
            fill_m3=region.volume.fill_m3,
            unmeasurable_ratio=region.unmeasurable_ratio,
            site_unmeasurable_cell_ratio=entry.report.unmeasurable_cell_ratio,
            capture_grade=capture.grade.value if capture is not None else None,
            capture_altitude_m=capture.altitude_m if capture is not None else None,
            capture_front_overlap=capture.front_overlap if capture is not None else None,
            capture_side_overlap=capture.side_overlap if capture is not None else None,
            capture_interval_m=capture.capture_interval_m if capture is not None else None,
            capture_gsd_m=capture.gsd_m if capture is not None else None,
            baseline_gsd_m=capture.baseline_gsd_m if capture is not None else None,
            capture_signal_to_noise=capture.signal_to_noise if capture is not None else None,
            capture_rationale=list(capture.rationale) if capture is not None else [],
            capture_unavailable_reason=capture_unavailable,
        )

    return router


def mount_region_extraction(app: FastAPI, store: RegionExtractionStore) -> None:
    app.include_router(build_region_extraction_router(store))


__all__ = [
    "RecordedRegionExtraction",
    "RegionExtractionEntry",
    "RegionExtractionListView",
    "RegionExtractionRecordResult",
    "RegionExtractionRecoveryError",
    "RegionExtractionResponse",
    "RegionExtractionStore",
    "RegionExtractionVerdict",
    "SpatialRefreshDraftResponse",
    "SpatialRefreshDraftVerdict",
    "build_region_extraction_router",
    "mount_region_extraction",
]
