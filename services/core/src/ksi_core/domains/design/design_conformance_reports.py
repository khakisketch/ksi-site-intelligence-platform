"""설계 대비 잔량 리포트 원장 — **이 파일이 M4-A 의 신뢰 경계다** (M4-A).

``volume_reports.py`` 의 형제다(불변 결과 원장 + 참조 검증 + live·재생 공유 게이트).
다른 점 하나가 이 모듈의 존재 이유 전부다: 이 리포트는 **지도의 데이터 출처인
차분 래스터를 참조**하고, 그 참조는 워커가 만든 파일을 가리킨다.

## 워커의 "올렸다, 해시는 이거다"는 근거가 아니다

리포트가 실어 오는 ``diffRaster.digest`` 는 **워커의 주장**이다. 그 주장을 그대로
원장에 굳히면, 지도가 내려받는 바이트와 표의 숫자가 갈라져도 어느 화면에서도
보이지 않는다. 그래서 이 원장은 리포트를 받는 **그 순간** 스토리지 객체를 직접
읽어 자기 ``hashlib`` 으로 digest 를 다시 계산하고
(:func:`~ksi_core.design_conformance_requests.recompute_diff_raster_digest`),
**같을 때만** 기록한다.

지켜지는 불변식은 한 문장이다:

    **원장에 있는 모든 설계 대비 리포트에 대해, 그 ``diffRaster.digest`` 로
    스토리지 바이트를 다시 읽어 해싱하면 항상 같다.**

다르면 리포트를 기록하지 않고 요청을 ``FAILED``(사유
``DIFF_RASTER_DIGEST_MISMATCH``)로 보낸다. 그때 스토리지에 남은 래스터 객체는
**허용된다** — orphan 한 덩이는 아무에게도 거짓말을 하지 않지만, "유효한 리포트가
있는데 그 래스터가 없거나 다른 바이트"는 화면 전체를 거짓으로 만든다.

## 확인이 두 번인 이유

요청 쪽(``design-conformance-requests/{id}/diff-raster-verification``)도 같은
재해싱을 한다. 중복이 아니라 **다른 창**을 막는다:

- 그 확인은 리포트가 정직한 ``coreVerifiedDigestAt`` 을 실을 수 있게 한다(리포트를
  만들기 **전에** 필요한 사실이다).
- 이 확인은 **리포트가 durable 하게 굳는 그 순간**의 사실이다. 두 시점 사이에
  객체가 다른 바이트로 덮이면 앞의 확인만으로는 불변식이 깨진다.

## 재생은 바이트를 다시 읽지 않는다

기동이 오브젝트 스토리지 가용성에 묶이면 스토리지가 한 번 흔들릴 때 Core 가 아예
못 뜬다. 대신 journal 에 **Core 가 그때 직접 계산한 digest**(``coreRecomputedDigest``)
를 함께 남기고, 재생은 그 값이 리포트의 ``diffRaster.digest`` 와 같은지 본다 —
"확인 없이 기록된 리포트"가 원장에 손으로 심어져도 기동에서 걸린다. 참조·설계면·
기준값 대조는 재생에서도 **같은 함수**로 다시 태운다(``volume_reports`` 원칙).

## 사람은 잔량을 주장할 수 없다

수신 권한이 ``PROCESSING_WORK`` 다(어느 Role 에도 매핑되지 않는다) —
``volume_reports`` 와 같은 근거다. "이 구역에 3000m³ 더 쌓아야 한다"는 정산·공정
판단의 근거가 될 수 있고, 그럴수록 계산된 것이어야 한다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from ksi_event_contracts.design_conformance_report import DesignConformanceReport
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.processing_job import ProcessingJobStatus

from ksi_core.domains.artifacts.artifact_refs import ArtifactRefIssue, verify_artifact_ref
from ksi_core.domains.artifacts.evidence import (
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
)
from ksi_core.domains.design.design_conformance_requests import (
    DIFF_RASTER_CONTENT_TYPE,
    DesignConformanceRequestRecord,
    DesignConformanceRequestVerdict,
    build_design_conformance_raster_object_key,
    recompute_diff_raster_digest,
)
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

    from ksi_core.domains.design.design_conformance_requests import DesignConformanceRequestStore
    # P3 Task 5: retired to archive/acquisition-2026/ — no active
    # import, not even typing-only. Alias stays opaque Any.
    MissionStore = Any
    from ksi_core.domains.processing.processing_jobs import ProcessingJobStore

logger = logging.getLogger("ksi_core.design_conformance_reports")

#: ``volume_reports.DEFAULT_HISTORY_LIMIT`` 와 같은 이유 — 무제한 반환을 wire
#: 계약으로 굳히면 저장소 교체가 파괴적 변경이 된다.
DEFAULT_HISTORY_LIMIT = 50


class DesignConformanceVerdict(StrEnum):
    """수신 판정. ``RECORDED`` 만 durable 기록 성공이다."""

    RECORDED = "RECORDED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    #: 이 리포트가 가리키는 요청이 없다 — designConformanceId 는 요청에서 도출된다.
    UNKNOWN_REQUEST = "UNKNOWN_REQUEST"
    #: 요청은 있는데 다른 임무의 것이다.
    REQUEST_MISMATCH = "REQUEST_MISMATCH"
    #: 리포트가 요청과 다른 설계면(또는 다른 해시의 같은 id)을 기준으로 삼았다.
    DESIGN_SURFACE_MISMATCH = "DESIGN_SURFACE_MISMATCH"
    UNKNOWN_ARTIFACT = "UNKNOWN_ARTIFACT"
    ARTIFACT_KIND_MISMATCH = "ARTIFACT_KIND_MISMATCH"
    #: 리포트의 현재 지형 산출물이 요청이 지목한 것과 다르다.
    ARTIFACT_MISMATCH = "ARTIFACT_MISMATCH"
    #: 리포트가 요청 시점 스냅샷과 다른 기준값으로 계산됐다.
    POLICY_MISMATCH = "POLICY_MISMATCH"
    #: Core 가 확인한 적 없는 래스터를 참조한다(확인 기록 없음·확인 시각 불일치).
    DIFF_RASTER_NOT_VERIFIED = "DIFF_RASTER_NOT_VERIFIED"
    #: **Core 의 재해싱 결과가 리포트의 digest 와 다르다** — 이 모듈의 핵심 게이트.
    DIFF_RASTER_DIGEST_MISMATCH = "DIFF_RASTER_DIGEST_MISMATCH"
    #: 그 자리의 객체를 읽지 못했다 — 확인 없이 기록하지 않는다.
    DIFF_RASTER_UNREADABLE = "DIFF_RASTER_UNREADABLE"
    DUPLICATE_REPORT_ID = "DUPLICATE_REPORT_ID"
    #: 요청이 이미 종결(FAILED)됐다 — 실패로 닫힌 요청 위에 성공 리포트를 남기면
    #: 요청 생애주기와 리포트 원장이 완료 여부를 서로 다르게 말한다.
    REQUEST_ALREADY_TERMINAL = "REQUEST_ALREADY_TERMINAL"
    LEASE_REQUIRED = "LEASE_REQUIRED"
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    STALE_LEASE_ACQUISITION = "STALE_LEASE_ACQUISITION"
    STALE_LEASE_GENERATION = "STALE_LEASE_GENERATION"
    INVALID_LEASE_FENCE = "INVALID_LEASE_FENCE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[DesignConformanceVerdict, int] = {
    DesignConformanceVerdict.RECORDED: 201,
    DesignConformanceVerdict.UNKNOWN_MISSION: 404,
    DesignConformanceVerdict.UNKNOWN_REQUEST: 422,
    DesignConformanceVerdict.REQUEST_MISMATCH: 422,
    DesignConformanceVerdict.DESIGN_SURFACE_MISMATCH: 422,
    DesignConformanceVerdict.UNKNOWN_ARTIFACT: 422,
    DesignConformanceVerdict.ARTIFACT_KIND_MISMATCH: 422,
    DesignConformanceVerdict.ARTIFACT_MISMATCH: 422,
    DesignConformanceVerdict.POLICY_MISMATCH: 422,
    DesignConformanceVerdict.DIFF_RASTER_NOT_VERIFIED: 422,
    DesignConformanceVerdict.DIFF_RASTER_DIGEST_MISMATCH: 422,
    DesignConformanceVerdict.DIFF_RASTER_UNREADABLE: 503,
    DesignConformanceVerdict.DUPLICATE_REPORT_ID: 409,
    DesignConformanceVerdict.REQUEST_ALREADY_TERMINAL: 409,
    DesignConformanceVerdict.LEASE_REQUIRED: 409,
    DesignConformanceVerdict.LEASE_HELD_BY_ANOTHER: 409,
    DesignConformanceVerdict.STALE_LEASE_ACQUISITION: 409,
    DesignConformanceVerdict.STALE_LEASE_GENERATION: 409,
    DesignConformanceVerdict.INVALID_LEASE_FENCE: 422,
    DesignConformanceVerdict.STORE_UNAVAILABLE: 503,
}


class DesignConformanceRecoveryError(RuntimeError):
    """design-conformance journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


@dataclass(frozen=True, slots=True)
class DesignConformanceRecordResult:
    verdict: DesignConformanceVerdict
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedDesignConformance:
    report: DesignConformanceReport
    reported_by: str | None
    recorded_at: datetime
    #: **Core 가 기록 시점에 스토리지 바이트에서 직접 계산한** digest.
    #: ``report.diff_raster.digest`` 와 항상 같다(같지 않으면 기록되지 않았다) —
    #: 그 사실을 별도 필드로 남겨야 재생이 "확인이 있었는가"를 볼 수 있다.
    core_recomputed_digest: str
    request_id: str | None = None
    accepted_lease_fence: LeaseFence | None = None
    diff_raster_object_key: str | None = None
    diff_raster_content_type: str | None = None
    authority_version: int | None = None


class DesignConformanceStore:
    """``DurableJournal`` 위의 설계 대비 잔량 원장 — append-only, 덮어쓰지 않는다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        processing_job_store: ProcessingJobStore,
        request_store: DesignConformanceRequestStore,
        storage: EvidenceStorage,
    ) -> None:
        """``storage`` 를 라우터가 아니라 **store 가** 받는다.

        다른 원장들은 스토리지 포트를 라우터에만 준다. 여기서 뒤집는 이유는,
        바이트 재해싱이 표현 계층의 편의가 아니라 **기록 판정 자체**이기
        때문이다 — 라우터에 두면 ``record()`` 를 직접 부르는 두 번째 호출자가
        생기는 날 그 게이트를 통째로 건너뛴다.
        """
        self._journal = journal
        self._mission_store = mission_store
        self._processing_job_store = processing_job_store
        self._request_store = request_store
        self._storage = storage
        self._lock = threading.Lock()
        self._by_mission: dict[str, list[RecordedDesignConformance]] = {}
        self._ids_by_mission: dict[str, dict[str, RecordedDesignConformance]] = {}
        # 진척(M4-C)은 **현장 단위**로 읽는다 — 리포트는 임무에 매달려 기록되지만,
        # "A공구가 계획 대비 얼마나 됐나"는 임무 경계를 넘는 질문이다(기준 시점과
        # 최신 시점은 서로 다른 임무다). site 는 요청 레코드가 이미 알고 있으므로
        # 새로 저장하지 않고 투영 시점에 얻는다.
        self._by_site: dict[str, list[RecordedDesignConformance]] = {}
        # (siteId, designSurfaceId) → 원지형 기준으로 지정된 리포트 id.
        # 사람이 명시적으로 지정한다 — 가장 오래된 것을 자동으로 고르지 않는다.
        # 첫 비행이 이미 시공 중이었으면 그 자동 추측이 계획 물량을 조용히 깎는다.
        self._progress_baselines: dict[tuple[str, str], str] = {}
        try:
            self._replay(journal)
        except DesignConformanceRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise DesignConformanceRecoveryError(
                f"design-conformance journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def mission_is_visible(self, mission_id: str) -> bool:
        """Mission 원장 scope를 설계 대비 결과에도 그대로 적용한다(INV-060)."""

        return self._mission_store.get(mission_id) is not None

    # ── 재생 ─────────────────────────────────────────────────────────────

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "design-conformance-rejected":
                continue
            if kind == "design-conformance-progress-baseline-set":
                self._apply_progress_baseline(raw)
                continue
            if kind != "design-conformance-recorded":
                raise DesignConformanceRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")
            mission_id = raw["missionId"]
            report = DesignConformanceReport.model_validate(raw["report"])
            recomputed = raw.get("coreRecomputedDigest")
            if recomputed != report.diff_raster.digest:
                # 바이트는 다시 읽지 않지만(모듈 docstring §재생), "Core 가 확인해
                # 같았다"는 사실 자체가 원장에 있어야 한다 — 손으로 심은 리포트는
                # 이 대조에서 걸린다.
                raise DesignConformanceRecoveryError(
                    f"재생: Core 재해싱 digest 가 리포트와 다르다(기록={recomputed!r}, "
                    f"리포트={report.diff_raster.digest!r}) — missionId={mission_id} "
                    f"designConformanceId={report.design_conformance_id}"
                )
            verdict, detail = self._judge(report, mission_id)
            if verdict is not DesignConformanceVerdict.RECORDED:
                raise DesignConformanceRecoveryError(
                    f"재생: 기록될 수 없는 리포트({verdict.value}: {detail}) — "
                    f"missionId={mission_id} designConformanceId={report.design_conformance_id}"
                )
            authority_version = raw.get("authorityVersion")
            accepted_fence: LeaseFence | None = None
            object_key: str | None = None
            content_type: str | None = None
            request_id: str | None = raw.get("requestId")
            if authority_version is not None:
                if authority_version != 1:
                    raise DesignConformanceRecoveryError(
                        f"재생: 지원하지 않는 authorityVersion — {authority_version!r}"
                    )
                try:
                    fence_raw = raw["acceptedLeaseFence"]
                    accepted_fence = LeaseFence(
                        fence_raw["workerInstanceId"],
                        fence_raw["leaseAcquisitionId"],
                        int(fence_raw["leaseGeneration"]),
                    )
                    object_raw = raw["diffRasterObject"]
                    object_key = object_raw["objectKey"]
                    content_type = object_raw["contentType"]
                except (KeyError, TypeError, ValueError) as exc:
                    raise DesignConformanceRecoveryError(
                        "재생: generation-aware authoritative report binding이 불완전하다"
                    ) from exc
                request = self._request_store.get_by_design_conformance_id(
                    report.design_conformance_id
                )
                if (
                    request is None
                    or request_id != request.request_id
                    or not accepted_fence.is_well_formed()
                    or not self._request_store.has_recorded_lease_fence(
                        report.design_conformance_id,
                        accepted_fence,
                        authenticated_actor_id=raw.get("reportedBy"),
                    )
                    or request.diff_raster is None
                    or request.diff_raster.fence != accepted_fence
                    or request.diff_raster.object_key != object_key
                    or object_raw.get("sha256") != report.diff_raster.digest
                    or int(object_raw.get("sizeBytes", -1)) != report.diff_raster.size_bytes
                    or content_type != DIFF_RASTER_CONTENT_TYPE
                ):
                    raise DesignConformanceRecoveryError(
                        "재생: authoritative diff raster provenance가 request/report와 다르다"
                    )
            elif any(
                key in raw for key in ("acceptedLeaseFence", "diffRasterObject")
            ):
                raise DesignConformanceRecoveryError(
                    "재생: authorityVersion 없는 부분적 authoritative report binding"
                )
            self._project(
                mission_id,
                report,
                raw.get("reportedBy"),
                datetime.fromisoformat(raw["ts"]),
                str(recomputed),
                request_id=request_id,
                accepted_lease_fence=accepted_fence,
                diff_raster_object_key=object_key,
                diff_raster_content_type=content_type,
                authority_version=authority_version,
            )

    def _project(
        self,
        mission_id: str,
        report: DesignConformanceReport,
        reported_by: str | None,
        recorded_at: datetime,
        core_recomputed_digest: str,
        *,
        request_id: str | None = None,
        accepted_lease_fence: LeaseFence | None = None,
        diff_raster_object_key: str | None = None,
        diff_raster_content_type: str | None = None,
        authority_version: int | None = None,
    ) -> None:
        recorded = RecordedDesignConformance(
            report=report,
            reported_by=reported_by,
            recorded_at=recorded_at,
            core_recomputed_digest=core_recomputed_digest,
            request_id=request_id,
            accepted_lease_fence=accepted_lease_fence,
            diff_raster_object_key=diff_raster_object_key,
            diff_raster_content_type=diff_raster_content_type,
            authority_version=authority_version,
        )
        self._by_mission.setdefault(mission_id, []).append(recorded)
        self._ids_by_mission.setdefault(mission_id, {})[
            report.design_conformance_id
        ] = recorded
        request = self._request_store.get_by_design_conformance_id(
            report.design_conformance_id
        )
        if request is not None:
            # 요청이 없는 리포트는 ``_judge`` 가 이미 거부하므로 여기 오지 않는다.
            # 그래도 None 을 견디는 이유는, 이 색인이 없다고 기록 자체를 잃으면
            # 안 되기 때문이다(진척은 부가 조회지 원장이 아니다).
            self._by_site.setdefault(request.site_id, []).append(recorded)

    # ── 진척 기준 시점 (M4-C) ────────────────────────────────────────────

    def _apply_progress_baseline(self, raw: dict[str, Any]) -> None:
        """기준 지정 레코드를 projection 에 반영 — 재생도 live 와 같은 강도로 검증한다."""
        site_id = raw["siteId"]
        design_surface_id = raw["designSurfaceId"]
        design_conformance_id = raw["designConformanceId"]
        if not (
            isinstance(site_id, str)
            and isinstance(design_surface_id, str)
            and isinstance(design_conformance_id, str)
        ):
            raise DesignConformanceRecoveryError(
                "재생: 진척 기준 레코드의 식별자가 문자열이 아니다"
            )
        # 지정 대상 리포트가 실제로 기록돼 있어야 한다 — 없는 리포트를 기준으로
        # 삼으면 조회가 500 으로 죽거나 조용히 빈 표를 낸다.
        if not any(
            recorded.report.design_conformance_id == design_conformance_id
            for recorded in self._by_site.get(site_id, ())
        ):
            raise DesignConformanceRecoveryError(
                f"재생: 진척 기준으로 지정된 리포트가 원장에 없다 — "
                f"siteId={site_id} designConformanceId={design_conformance_id}"
            )
        self._progress_baselines[site_id, design_surface_id] = design_conformance_id

    def progress_baseline_id(self, site_id: str, design_surface_id: str) -> str | None:
        with self._lock:
            return self._progress_baselines.get((site_id, design_surface_id))

    def set_progress_baseline(
        self,
        *,
        site_id: str,
        design_surface_id: str,
        design_conformance_id: str,
        actor: str,
        now: datetime,
    ) -> tuple[bool, str | None]:
        """이 리포트를 '원지형 기준'으로 지정한다 — ``(성공, 사유)``.

        덮어쓰기를 허용한다(잘못 지정하는 일이 실제로 있다). 이전 지정도 저널에
        남으므로 "언제 무엇을 기준으로 봤는가"는 되짚어진다.
        """
        with self._lock:
            if self._journal.sealed_reason is not None:
                return False, JOURNAL_SEALED_DETAIL
            match = next(
                (
                    recorded
                    for recorded in self._by_site.get(site_id, ())
                    if recorded.report.design_conformance_id == design_conformance_id
                ),
                None,
            )
            if match is None:
                return False, (
                    f"현장 {site_id!r} 에 designConformanceId={design_conformance_id!r} "
                    "인 리포트가 없다"
                )
            if match.report.design_surface_ref.design_surface_id != design_surface_id:
                return False, (
                    f"그 리포트는 설계면 "
                    f"{match.report.design_surface_ref.design_surface_id!r} 로 낸 것인데 "
                    f"요청은 {design_surface_id!r} 다 — 다른 설계면의 잔량을 계획 물량으로 "
                    "쓸 수 없다"
                )
            raw: dict[str, Any] = {
                "kind": "design-conformance-progress-baseline-set",
                "ts": iso_utc(now),
                "actor": actor,
                "siteId": site_id,
                "designSurfaceId": design_surface_id,
                "designConformanceId": design_conformance_id,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return False, JOURNAL_SEALED_DETAIL
            self._progress_baselines[site_id, design_surface_id] = design_conformance_id
            return True, None

    def site_history(self, site_id: str) -> list[RecordedDesignConformance]:
        """현장의 리포트 전부 — 기록 순서(오래된 것 먼저). 진척 조회의 입력이다."""
        with self._lock:
            return list(self._by_site.get(site_id, ()))

    def has_report_for(self, design_conformance_id: str) -> bool:
        """이 id 로 기록된 리포트가 있나 — 요청 원장 쪽 두 게이트의 입력이다.

        요청 저장소가 "리포트 없는 SUCCEEDED"와 "기록 후 래스터 재작성"을 막을 때
        이 술어를 주입받아 쓴다(:class:`~ksi_core.design_conformance_requests.
        DesignConformanceRequestStore` 의 ``report_exists``). 임무를 모른 채 물어야
        하므로 임무별 색인을 가로질러 본다 — id 는 요청에서 결정적으로 도출돼
        전역 유일하다(``design_conformance_id_of``).
        """
        with self._lock:
            return any(
                design_conformance_id in ids for ids in self._ids_by_mission.values()
            )

    def site_of(self, design_conformance_id: str) -> str | None:
        """그 리포트가 어느 현장의 것인가 — 요청 레코드에서 얻는다(저장하지 않는다).

        ``diff_raster_object_key`` 가 객체 키를 요청에서 유도하는 것과 같은 자리다.
        """
        request = self._request_store.get_by_design_conformance_id(design_conformance_id)
        return None if request is None else request.site_id

    def mission_of(self, design_conformance_id: str) -> str | None:
        """그 리포트가 어느 임무의 것인가 — 진척 화면이 히트맵(임무 스코프)으로
        건너뛸 때만 쓰는 UI 편의값이다. 저장하지 않고 요청 레코드에서 얻는다."""
        request = self._request_store.get_by_design_conformance_id(design_conformance_id)
        return None if request is None else request.mission_id

    def request_of(
        self, design_conformance_id: str
    ) -> DesignConformanceRequestRecord | None:
        """Return the immutable request snapshot behind a recorded result.

        Civil progress uses this to compare processing/design lineage anchors;
        it must not reconstruct those facts from the report payload.
        """

        return self._request_store.get_by_design_conformance_id(design_conformance_id)

    # ── 판정 (live·재생 공유, 스토리지 없이) ─────────────────────────────

    def _judge(
        self,
        report: DesignConformanceReport,
        mission_id: str,
        request: DesignConformanceRequestRecord | None = None,
    ) -> tuple[DesignConformanceVerdict, str | None]:
        """리포트가 **그 요청의 결과로 성립하는가** — 바이트를 읽지 않는 대조 전부.

        live 수신과 재생이 같은 함수를 쓴다 — 각자 조건문을 들고 있으면 한쪽만
        고쳐지는 순간 원장이 거짓 검증을 되살린다(``volume_reports.
        _judge_references`` 와 같은 원칙). 바이트 재해싱만 live 전용이다(모듈
        docstring §재생).
        """
        if request is None:
            request = self._request_store.get_by_design_conformance_id(
                report.design_conformance_id
            )
        if request is None:
            return (
                DesignConformanceVerdict.UNKNOWN_REQUEST,
                f"designConformanceId={report.design_conformance_id!r} 에 해당하는 설계 "
                "대비 요청이 없다 — 지시 없이 만들어진 결과는 받지 않는다",
            )
        if request.mission_id != mission_id:
            return (
                DesignConformanceVerdict.REQUEST_MISMATCH,
                f"그 요청은 임무 {request.mission_id!r} 소속인데 경로의 missionId 는 "
                f"{mission_id!r} 다",
            )
        return self._judge_against_request(report, request)

    def _judge_against_request(
        self, report: DesignConformanceReport, request: DesignConformanceRequestRecord
    ) -> tuple[DesignConformanceVerdict, str | None]:
        ref = report.design_surface_ref
        if (
            ref.design_surface_id != request.design_surface_id
            or ref.sha256 != request.design_surface_sha256
        ):
            return (
                DesignConformanceVerdict.DESIGN_SURFACE_MISMATCH,
                f"리포트의 설계면({ref.design_surface_id}/{ref.sha256[:12]}…) 이 요청이 "
                f"지목한 것({request.design_surface_id}/{request.design_surface_sha256[:12]}…) "
                "과 다르다 — '어느 판 기준의 잔량인가'가 되짚어지지 않는다",
            )
        if report.current != request.current:
            return (
                DesignConformanceVerdict.ARTIFACT_MISMATCH,
                f"리포트의 현재 지형 산출물({report.current.job_id}/"
                f"{report.current.artifact_id}) 이 요청이 지목한 것"
                f"({request.current.job_id}/{request.current.artifact_id}) 과 다르다",
            )
        issue = verify_artifact_ref(
            self._processing_job_store,
            report.current,
            label="current",
            required_kind=ProcessingArtifactKind.DSM,
            kind_mismatch_detail=lambda label, kind: (
                f"{label} 산출물의 kind 가 {kind.value!r} 다 — 설계 대비 잔량의 입력은"
                " dsm 이어야 한다(표면 함수 z=f(x,y) 의 적분이다)"
            ),
        )
        if issue is not None:
            reason, detail = issue
            return (
                DesignConformanceVerdict.UNKNOWN_ARTIFACT
                if reason is ArtifactRefIssue.UNKNOWN_ARTIFACT
                else DesignConformanceVerdict.ARTIFACT_KIND_MISMATCH,
                detail,
            )
        if report.policy != request.policy:
            return (
                DesignConformanceVerdict.POLICY_MISMATCH,
                "리포트가 요청 시점에 굳어진 기준값이 아닌 다른 값으로 계산됐다 — "
                "화면이 표시하는 기준과 실제로 쓴 기준이 갈린다",
            )
        verification = request.diff_raster
        if verification is None:
            return (
                DesignConformanceVerdict.DIFF_RASTER_NOT_VERIFIED,
                "Core 가 이 요청의 차분 래스터를 확인한 적이 없다 — 먼저 "
                "diff-raster-verification 을 거쳐야 한다",
            )
        if report.diff_raster.core_verified_digest_at != verification.verified_at:
            return (
                DesignConformanceVerdict.DIFF_RASTER_NOT_VERIFIED,
                "리포트의 coreVerifiedDigestAt 이 Core 가 실제로 확인한 시각과 다르다 — "
                "그 필드는 워커가 적어 넣는 값이 아니다",
            )
        if (
            report.diff_raster.digest != verification.digest
            or report.diff_raster.size_bytes != verification.size_bytes
        ):
            return (
                DesignConformanceVerdict.DIFF_RASTER_DIGEST_MISMATCH,
                f"리포트의 래스터 참조({report.diff_raster.digest}, "
                f"{report.diff_raster.size_bytes}B) 가 Core 가 확인한 것"
                f"({verification.digest}, {verification.size_bytes}B) 과 다르다",
            )
        return DesignConformanceVerdict.RECORDED, None

    # ── live 경로 ────────────────────────────────────────────────────────

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def record(
        self,
        mission_id: str,
        report: DesignConformanceReport,
        *,
        now: datetime,
        reported_by: str | None = None,
        lease_fence: LeaseFence | None = None,
    ) -> DesignConformanceRecordResult:
        """Finalize one report under the owning request's current lease fence."""
        with self._request_store.authoritative_result_guard(
            report.design_conformance_id,
            now=now,
            lease_fence=lease_fence,
            legacy_worker_id=reported_by,
            authenticated_actor_id=reported_by,
        ) as authority:
            if authority.verdict is not DesignConformanceRequestVerdict.INPUT_READY:
                mapped = {
                    DesignConformanceRequestVerdict.UNKNOWN_REQUEST: (
                        DesignConformanceVerdict.UNKNOWN_REQUEST
                    ),
                    DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE: (
                        DesignConformanceVerdict.REQUEST_ALREADY_TERMINAL
                    ),
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE: (
                        DesignConformanceVerdict.STORE_UNAVAILABLE
                    ),
                    DesignConformanceRequestVerdict.LEASE_REQUIRED: (
                        DesignConformanceVerdict.LEASE_REQUIRED
                    ),
                    DesignConformanceRequestVerdict.LEASE_HELD_BY_ANOTHER: (
                        DesignConformanceVerdict.LEASE_HELD_BY_ANOTHER
                    ),
                    DesignConformanceRequestVerdict.STALE_LEASE_ACQUISITION: (
                        DesignConformanceVerdict.STALE_LEASE_ACQUISITION
                    ),
                    DesignConformanceRequestVerdict.STALE_LEASE_GENERATION: (
                        DesignConformanceVerdict.STALE_LEASE_GENERATION
                    ),
                    DesignConformanceRequestVerdict.INVALID_LEASE_FENCE: (
                        DesignConformanceVerdict.INVALID_LEASE_FENCE
                    ),
                }.get(authority.verdict, DesignConformanceVerdict.INVALID_LEASE_FENCE)
                return DesignConformanceRecordResult(mapped, detail=authority.detail)
            request = authority.record
            assert request is not None  # noqa: S101 -- INPUT_READY always includes it
            with self._lock:
                return self._record_authoritative_locked(
                    mission_id,
                    report,
                    request=request,
                    now=now,
                    reported_by=reported_by,
                    lease_fence=lease_fence,
                )

    def _record_authoritative_locked(
        self,
        mission_id: str,
        report: DesignConformanceReport,
        *,
        request: DesignConformanceRequestRecord,
        now: datetime,
        reported_by: str | None,
        lease_fence: LeaseFence | None,
    ) -> DesignConformanceRecordResult:
        """Report lock is held; request-store authority lock is held by caller."""
        if self._journal.sealed_reason is not None:
            return DesignConformanceRecordResult(
                DesignConformanceVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
            )
        if self._mission_store.get(mission_id) is None:
            return self._reject(
                mission_id,
                report,
                now,
                reported_by,
                DesignConformanceVerdict.UNKNOWN_MISSION,
                "발급된 적 없는 임무의 설계 대비 리포트는 받지 않는다",
            )
        existing = self._ids_by_mission.get(mission_id, {}).get(
            report.design_conformance_id
        )
        if existing is not None:
            same_authority = (
                existing.authority_version is None
                or existing.accepted_lease_fence == lease_fence
            )
            if existing.report == report and same_authority:
                return DesignConformanceRecordResult(
                    DesignConformanceVerdict.RECORDED,
                    detail="이미 같은 내용과 lease generation으로 기록돼 있다(멱등 재전송)",
                )
            return self._reject(
                mission_id,
                report,
                now,
                reported_by,
                DesignConformanceVerdict.DUPLICATE_REPORT_ID,
                f"designConformanceId={report.design_conformance_id!r} 는 이미 다른"
                " 내용 또는 generation으로 기록됐다 — 같은 id를 덮어쓸 수 없다",
            )
        verdict, detail = self._judge(report, mission_id, request=request)
        if verdict is not DesignConformanceVerdict.RECORDED:
            return self._reject(mission_id, report, now, reported_by, verdict, detail)

        verification = request.diff_raster
        assert verification is not None  # noqa: S101 -- _judge checked it
        if lease_fence is not None:
            if verification.fence != lease_fence or verification.object_key is None:
                return self._reject(
                    mission_id,
                    report,
                    now,
                    reported_by,
                    DesignConformanceVerdict.DIFF_RASTER_NOT_VERIFIED,
                    "current lease generation이 확인한 diff raster candidate가 아니다",
                )
            object_key = verification.object_key
            content_type = verification.content_type
        else:
            # Historical generation-zero workers retain only the conventional
            # key.  New fenced records never enter this branch.
            object_key = build_design_conformance_raster_object_key(
                site_id=request.site_id,
                design_conformance_id=request.design_conformance_id,
            )
            content_type = DIFF_RASTER_CONTENT_TYPE

        try:
            recomputed_digest, recomputed_size = recompute_diff_raster_digest(
                self._storage, object_key
            )
        except EvidenceStorageError:
            logger.warning(
                "차분 래스터를 읽지 못해 리포트를 기록하지 않는다: objectKey=%s", object_key
            )
            return self._reject(
                mission_id,
                report,
                now,
                reported_by,
                DesignConformanceVerdict.DIFF_RASTER_UNREADABLE,
                "리포트가 가리키는 차분 래스터를 읽지 못했다 — 지도가 없는 잔량"
                " 리포트를 원장에 남기지 않는다",
            )
        if (
            recomputed_digest != report.diff_raster.digest
            or recomputed_size != report.diff_raster.size_bytes
        ):
            return self._reject(
                mission_id,
                report,
                now,
                reported_by,
                DesignConformanceVerdict.DIFF_RASTER_DIGEST_MISMATCH,
                "워커가 신고한 차분 래스터 digest와 Core가 직접 다시 해싱한 결과가 다르다 — "
                f"리포트 {report.diff_raster.digest}({report.diff_raster.size_bytes}B), "
                f"실제 {recomputed_digest}({recomputed_size}B)",
                lease_fence=lease_fence,
            )

        record = {
            "kind": "design-conformance-recorded",
            "ts": iso_utc(now),
            "missionId": mission_id,
            "requestId": request.request_id,
            "reportedBy": reported_by,
            "report": report.model_dump(by_alias=True, mode="json", exclude_none=False),
            "coreRecomputedDigest": recomputed_digest,
            "coreRecomputedSizeBytes": recomputed_size,
            **(
                {
                    "authorityVersion": 1,
                    "acceptedLeaseFence": {
                        "workerInstanceId": lease_fence.worker_instance_id,
                        "leaseAcquisitionId": lease_fence.lease_acquisition_id,
                        "leaseGeneration": lease_fence.lease_generation,
                    },
                    "diffRasterObject": {
                        "objectKey": object_key,
                        "sha256": recomputed_digest,
                        "sizeBytes": recomputed_size,
                        "contentType": content_type,
                    },
                }
                if lease_fence is not None
                else {}
            ),
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return DesignConformanceRecordResult(
                DesignConformanceVerdict.STORE_UNAVAILABLE,
                detail=JOURNAL_APPEND_FAILED_DETAIL,
            )
        self._project(
            mission_id,
            report,
            reported_by,
            now,
            recomputed_digest,
            request_id=request.request_id,
            accepted_lease_fence=lease_fence,
            diff_raster_object_key=(object_key if lease_fence is not None else None),
            diff_raster_content_type=(content_type if lease_fence is not None else None),
            authority_version=(1 if lease_fence is not None else None),
        )
        return DesignConformanceRecordResult(DesignConformanceVerdict.RECORDED)

    def _reject(
        self,
        mission_id: str,
        report: DesignConformanceReport,
        now: datetime,
        reported_by: str | None,
        verdict: DesignConformanceVerdict,
        detail: str | None,
        *,
        lease_fence: LeaseFence | None = None,
    ) -> DesignConformanceRecordResult:
        """거부도 원장에 남긴다 — 신뢰 경계에서 튕겨 나간 제출은 특히 남아야 한다.

        digest 불일치는 **요청까지 ``FAILED`` 로 끝낸다**(아래 :meth:`_fail_request`).
        어느 경로로 어긋났든(리포트가 Core 의 확인 기록과 다르다 / 바이트가 그
        사이 바뀌었다) 결론은 하나다 — 이 시도로는 유효한 리포트를 만들 수 없다.
        """
        record = {
            "kind": "design-conformance-rejected",
            "ts": iso_utc(now),
            "missionId": mission_id,
            "designConformanceId": report.design_conformance_id,
            "verdict": verdict.value,
            "detail": detail,
            "reportedBy": reported_by,
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return DesignConformanceRecordResult(
                DesignConformanceVerdict.STORE_UNAVAILABLE, detail=JOURNAL_APPEND_FAILED_DETAIL
            )
        if verdict is DesignConformanceVerdict.DIFF_RASTER_DIGEST_MISMATCH:
            self._fail_request(report, now, reported_by, detail, lease_fence=lease_fence)
        return DesignConformanceRecordResult(verdict, detail=detail)

    def _fail_request(
        self,
        report: DesignConformanceReport,
        now: datetime,
        reported_by: str | None,
        detail: str | None,
        *,
        lease_fence: LeaseFence | None = None,
    ) -> None:
        """digest 불일치 요청을 ``FAILED`` 로 보낸다 — 리포트는 기록되지 않았다.

        여기서 요청까지 끝내는 이유: 이 실패는 워커가 스스로 알아채고 보고할 수
        있는 종류가 아니다(워커는 자기가 옳다고 믿고 제출했다). Core 가 반박한
        이상 그 요청은 이 시도로는 끝난 것이고, ``RUNNING`` 으로 남겨 두면 lease
        가 만료될 때까지 아무도 못 건드리는 채로 화면에 "계산 중"으로 보인다.

        전이가 거부될 수 있다(그 사이 lease 를 잃었다면) — 그래도 **리포트가
        기록되지 않았다**는 사실은 변하지 않으므로 로그만 남긴다.
        """
        request = self._request_store.get_by_design_conformance_id(
            report.design_conformance_id
        )
        if request is None:  # pragma: no cover - digest 판정은 요청을 찾은 뒤에만 난다
            return
        transition = self._request_store.transition(
            request.request_id,
            ProcessingJobStatus.FAILED,
            detail=(
                f"{DesignConformanceVerdict.DIFF_RASTER_DIGEST_MISMATCH.value}: {detail}"
            )[:500],
            actor=reported_by or "core",
            now=now,
            lease_fence=lease_fence,
        )
        if transition.verdict.value != "TRANSITIONED":
            logger.warning(
                "digest 불일치 요청을 FAILED 로 보내지 못했다(리포트는 기록되지 않았다): "
                "requestId=%s verdict=%s",
                request.request_id,
                transition.verdict.value,
            )

    def latest(self, mission_id: str) -> RecordedDesignConformance | None:
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return None
        with self._lock:
            recorded = self._by_mission.get(mission_id)
            return recorded[-1] if recorded else None

    def history(
        self, mission_id: str, *, limit: int | None = None
    ) -> list[RecordedDesignConformance]:
        """최신이 먼저. ``limit`` 은 위쪽(최신)부터 센다."""
        if limit is not None and limit < 0:
            raise ValueError(f"limit 은 음수일 수 없다: {limit}")
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return []
        with self._lock:
            recorded = list(reversed(self._by_mission.get(mission_id, ())))
        return recorded if limit is None else recorded[:limit]

    def get(
        self, mission_id: str, design_conformance_id: str
    ) -> RecordedDesignConformance | None:
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return None
        with self._lock:
            for entry in reversed(self._by_mission.get(mission_id, ())):
                if entry.report.design_conformance_id == design_conformance_id:
                    return entry
        return None

    def diff_raster_object_key(self, entry: RecordedDesignConformance) -> str | None:
        """Return the exact durable authority; derive only true legacy keys."""
        if entry.authority_version is not None:
            # New-format replay rejects a missing binding, so None here is a
            # fail-closed signal rather than permission to guess a path.
            return entry.diff_raster_object_key
        request = self._request_store.get_by_design_conformance_id(
            entry.report.design_conformance_id
        )
        if request is None:  # pragma: no cover - 기록된 리포트는 항상 요청을 갖는다
            return None
        return build_design_conformance_raster_object_key(
            site_id=request.site_id, design_conformance_id=request.design_conformance_id
        )


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class DesignConformanceResponse(CamelModel):
    verdict: str
    detail: str | None


class DesignConformanceEntry(CamelModel):
    report: dict[str, Any]
    reported_by: str | None
    recorded_at: datetime
    #: Core 가 기록 시점에 직접 재계산한 digest — 화면이 "확인된 사실"임을 말할 근거.
    core_recomputed_digest: str


class DesignConformanceListView(CamelModel):
    """그 임무의 설계 대비 잔량 리포트 이력 — 최신이 먼저.

    ``latestTotalNetM3`` 는 **최신 리포트의** 전 구역 순 성토 필요량이다. 화면이
    구역 배열을 직접 합산하지 않게 서버가 계산해 준다(``volume_reports`` 와 같은
    이유 — 합산 규칙이 두 곳에 있으면 한쪽만 고쳐진다).
    """

    mission_id: str
    report_count: int
    latest_total_net_m3: float | None
    reports: list[DesignConformanceEntry]


class DiffRasterViewResponse(CamelModel):
    """지도가 차분 래스터를 얻는 **유일한** 경로의 응답."""

    design_conformance_id: str
    diff_raster_id: str
    digest: str
    size_bytes: int
    download_url: str
    expires_at: datetime


def _entry_view(entry: RecordedDesignConformance) -> DesignConformanceEntry:
    return DesignConformanceEntry(
        report=entry.report.model_dump(by_alias=True, mode="json", exclude_none=False),
        reported_by=entry.reported_by,
        recorded_at=entry.recorded_at,
        core_recomputed_digest=entry.core_recomputed_digest,
    )


def build_design_conformance_reports_router(
    store: DesignConformanceStore, storage: EvidenceStorage
) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["design-conformance"])

    @router.post("/{mission_id}/design-conformance", status_code=201)
    def submit_design_conformance(
        mission_id: str,
        report: DesignConformanceReport,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DesignConformanceResponse:
        """설계 대비 잔량 리포트 접수 — **처리 워커만** 올리고, Core 가 래스터를 재해싱한다."""
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
        outcome = store.record(
            mission_id,
            report,
            now=datetime.now(UTC),
            reported_by=principal.principal_id,
            lease_fence=fence,
        )
        response.status_code = _STATUS[outcome.verdict]
        if outcome.verdict in (
            DesignConformanceVerdict.STORE_UNAVAILABLE,
            DesignConformanceVerdict.DIFF_RASTER_UNREADABLE,
        ):
            response.headers["Retry-After"] = "30"
        return DesignConformanceResponse(verdict=outcome.verdict.value, detail=outcome.detail)

    @router.get("/{mission_id}/design-conformance", response_model=DesignConformanceListView)
    def list_design_conformance(
        mission_id: str,
        limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1, le=200),  # noqa: B008
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> DesignConformanceListView:
        """그 임무의 설계 대비 잔량 이력(최신 우선).

        결과가 없으면 404 다 — 빈 목록을 주면 "아직 계산 안 됨"과 "잔량이 0"을
        소비자가 구분할 수 없다(``volume_reports``·``change_detection`` 과 동일).
        """
        if not store.mission_is_visible(mission_id):
            raise HTTPException(
                status_code=404, detail="해당 설계 대비 잔량 리포트를 찾을 수 없다"
            )
        entries = store.history(mission_id, limit=limit)
        if not entries:
            raise HTTPException(
                status_code=404, detail="해당 임무의 설계 대비 잔량 리포트를 찾을 수 없다"
            )
        return DesignConformanceListView(
            mission_id=mission_id,
            report_count=len(store.history(mission_id)),
            latest_total_net_m3=entries[0].report.total_net_m3,
            reports=[_entry_view(entry) for entry in entries],
        )

    @router.get(
        "/{mission_id}/design-conformance/{design_conformance_id}/diff-raster",
        response_model=DiffRasterViewResponse,
    )
    def get_diff_raster(
        mission_id: str,
        design_conformance_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> DiffRasterViewResponse:
        """저장된 차분 래스터의 열람 URL — **지도는 반드시 이 경로로만** 얻는다.

        브라우저가 원본 두 장을 받아 다시 차분하는 경로를 만들지 않는 이유가 이
        엔드포인트의 존재 이유다: 그러면 지도와 표가 서로 다른 두 진실을 갖게
        되고, 그 어긋남은 어느 화면에서도 보이지 않는다. 여기서 내려주는 것은
        체적 집계에 **실제로 쓴 그 격자**다.
        """
        entry = store.get(mission_id, design_conformance_id)
        if entry is None:
            raise HTTPException(
                status_code=404, detail="해당 설계 대비 잔량 리포트를 찾을 수 없다"
            )
        object_key = store.diff_raster_object_key(entry)
        if object_key is None:  # pragma: no cover - 기록된 리포트는 항상 요청을 갖는다
            raise HTTPException(status_code=404, detail="차분 래스터의 자리를 찾을 수 없다")
        try:
            download_url = storage.presigned_get(object_key, ttl=DEFAULT_VIEW_TTL)
        except EvidenceStorageError as exc:
            logger.warning("차분 래스터 열람 URL 발급 실패: %s", object_key)
            raise HTTPException(
                status_code=503, detail="차분 래스터 열람 URL 발급에 실패했다 — 잠시 후 재시도"
            ) from exc
        return DiffRasterViewResponse(
            design_conformance_id=design_conformance_id,
            diff_raster_id=entry.report.diff_raster.diff_raster_id,
            digest=entry.report.diff_raster.digest,
            size_bytes=entry.report.diff_raster.size_bytes,
            download_url=download_url,
            expires_at=datetime.now(UTC) + DEFAULT_VIEW_TTL,
        )

    return router


def mount_design_conformance_reports(
    app: FastAPI, store: DesignConformanceStore, storage: EvidenceStorage
) -> None:
    app.include_router(build_design_conformance_reports_router(store, storage))


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "DesignConformanceEntry",
    "DesignConformanceListView",
    "DesignConformanceRecordResult",
    "DesignConformanceRecoveryError",
    "DesignConformanceResponse",
    "DesignConformanceStore",
    "DesignConformanceVerdict",
    "DiffRasterViewResponse",
    "RecordedDesignConformance",
    "build_design_conformance_reports_router",
    "mount_design_conformance_reports",
]
