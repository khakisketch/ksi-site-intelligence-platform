"""변화 탐지 결과 수신·조회 — PRD §15.2 ⑤ "변화 후보 영역은 추가 시점 수집"의 폐쇄 지점.

## 이 모듈이 채우는 자리

``needs_change_candidate_revisit`` 는 정확하게 구현돼 있었지만 **호출부가 0건**이었다
(risk ``phase2-change-candidate-revisit``). 권고를 계산할 수는 있는데 그 권고가 도달할
표면이 없었다 — Coverage Recovery 는 ``recoveryRecommended`` 로 운영자가 실제로 보는
반면, 변화 탐지 쪽은 결과를 노출하는 엔드포인트 자체가 없었다. 이 모듈이 그 표면이고,
조회 응답의 ``revisitRecommended`` 가 그 신호다.

**권고일 뿐 재비행을 트리거하지 않는다.** 실제 추가 수집은 운영자가 기존
``POST /v1/missions/plans``(SPATIAL_REFRESH, 원본 site AOI)로 발급한다 —
``coverage_reports.py`` 의 Coverage Recovery 와 정확히 같은 관계다.

## 임계값은 요청이 정하고, 서버는 그 값을 응답에 함께 싣는다

"변화 후보 비율이 얼마면 재방문이 필요한가"는 사이트·자산 종류에 따라 달라질 정책
값이라 서버가 지어내지 않는다(``exceeds_revisit_threshold`` docstring). 조회 시
``revisitRatioThreshold`` 쿼리로 받고, 응답에 **그 값을 그대로 되돌려준다** — 권고
불리언만 주면 화면이 "무슨 기준으로 켜졌나"를 표시할 수 없고, 그러면 운영자는 그
신호를 신뢰할 근거가 없다.

## 서버가 검증하는 것

1. 미지 ``missionId`` → ``UNKNOWN_MISSION``. 계약 없이 관찰 결과만 원장에 남으면
   "무슨 근거로 날았나"에 답할 수 없다(``coverage_reports.py`` 와 동일 원칙).
2. ``baseline``/``current`` 가 실제로 등록된 ``point_cloud`` 산출물인가 →
   ``UNKNOWN_ARTIFACT``/``ARTIFACT_KIND_MISMATCH``. 무엇과 무엇을 비교했는지가
   해석 불가능하면 "변화가 있었다"는 결과 자체가 검증 불가능한 주장이다.
   ``artifactId`` 는 작업 단위로만 고유하므로(``processing_jobs.py``) ``jobId`` 와
   짝으로 해석한다.
3. ``baseline`` 과 ``current`` 가 같은 산출물 → ``SELF_COMPARISON``. 자기 자신과의
   C2C 는 전 점 거리 0 이라 어떤 문턱에서도 후보가 0 이다 — 결과가 "변화 없음"으로
   정직해 보이지만 실제로는 아무것도 비교하지 않은 것이다.

카운트·비율의 자기모순(후보 0건인데 비율 0.9 같은 것)은 계약 모델
(:class:`ChangeDetectionResult`)이 파싱 시점에 거부한다 — 서버 게이트를 두 겹으로
쌓지 않고 계약이 볼 수 있는 것은 계약이 본다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from ksi_event_contracts.change_detection_result import ChangeDetectionResult
from ksi_event_contracts.comparison_policy import (
    DEFAULT_REVISIT_RATIO_THRESHOLD as _POLICY_REVISIT_RATIO_THRESHOLD,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_core.domains.artifacts.artifact_refs import ArtifactRefIssue, verify_artifact_pair
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

    from ksi_core.domains.missions.mission_records import MissionStore
    from ksi_core.domains.processing.processing_jobs import ProcessingJobStore

logger = logging.getLogger("ksi_core.change_detection")

# 조회 시 임계값을 주지 않았을 때 쓰는 값. **정책 기본값이 아니라 화면 초기값**이다
# — 서버는 이 값으로 어떤 결정도 내리지 않고, 응답에 자기가 무슨 값을 썼는지
# (revisitRatioThreshold) 반드시 함께 싣는다. 사이트별 정책값이 정해지면 요청이
# 그 값을 준다.
#
# **정본은 계약 패키지**다(``ksi_event_contracts.comparison_policy``) — 화면이
# "이 값을 쓴다"고 표시하려면 계산 쪽(packages/change-detection)과 이 조회 쪽이
# 같은 자리를 읽어야 하고, 그 공통 자리는 양쪽이 이미 의존하는 계약 패키지뿐이다
# (Core 가 계산 서비스를 import 하면 scipy 가 control plane 으로 딸려온다).
DEFAULT_REVISIT_RATIO_THRESHOLD = _POLICY_REVISIT_RATIO_THRESHOLD


class ChangeDetectionVerdict(StrEnum):
    """결과 수신 판정. ``RECORDED`` 만 durable 기록 성공이다."""

    RECORDED = "RECORDED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    UNKNOWN_ARTIFACT = "UNKNOWN_ARTIFACT"
    ARTIFACT_KIND_MISMATCH = "ARTIFACT_KIND_MISMATCH"
    SELF_COMPARISON = "SELF_COMPARISON"
    UNKNOWN_REQUEST = "UNKNOWN_REQUEST"
    REQUEST_MISMATCH = "REQUEST_MISMATCH"
    REQUEST_INELIGIBLE = "REQUEST_INELIGIBLE"
    LEASE_REQUIRED = "LEASE_REQUIRED"
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    STALE_LEASE_ACQUISITION = "STALE_LEASE_ACQUISITION"
    STALE_LEASE_GENERATION = "STALE_LEASE_GENERATION"
    INVALID_LEASE_FENCE = "INVALID_LEASE_FENCE"
    DUPLICATE_RESULT_ID = "DUPLICATE_RESULT_ID"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[ChangeDetectionVerdict, int] = {
    ChangeDetectionVerdict.RECORDED: 201,
    ChangeDetectionVerdict.UNKNOWN_MISSION: 404,
    ChangeDetectionVerdict.UNKNOWN_ARTIFACT: 422,
    ChangeDetectionVerdict.ARTIFACT_KIND_MISMATCH: 422,
    ChangeDetectionVerdict.SELF_COMPARISON: 422,
    ChangeDetectionVerdict.UNKNOWN_REQUEST: 422,
    ChangeDetectionVerdict.REQUEST_MISMATCH: 422,
    ChangeDetectionVerdict.REQUEST_INELIGIBLE: 422,
    ChangeDetectionVerdict.LEASE_REQUIRED: 409,
    ChangeDetectionVerdict.LEASE_HELD_BY_ANOTHER: 409,
    ChangeDetectionVerdict.STALE_LEASE_ACQUISITION: 409,
    ChangeDetectionVerdict.STALE_LEASE_GENERATION: 409,
    ChangeDetectionVerdict.INVALID_LEASE_FENCE: 422,
    ChangeDetectionVerdict.DUPLICATE_RESULT_ID: 409,
    ChangeDetectionVerdict.STORE_UNAVAILABLE: 503,
}


_UNKNOWN_MISSION_DETAIL = "발급된 적 없는 임무의 변화 탐지 결과는 받지 않는다"


class ChangeDetectionRecoveryError(RuntimeError):
    """change-detection journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


@dataclass(frozen=True, slots=True)
class ChangeDetectionRecordResult:
    verdict: ChangeDetectionVerdict
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedChangeDetection:
    result: ChangeDetectionResult
    reported_by: str | None
    recorded_at: datetime
    request_id: str | None = None
    accepted_lease_fence: LeaseFence | None = None


class ChangeDetectionStore:
    """``DurableJournal`` 위의 변화 탐지 결과 원장 — append-only, 덮어쓰지 않는다.

    같은 임무에 결과가 여러 번 올 수 있다(다른 baseline 과의 비교, 재계산) — 전부
    남기고 조회는 최신을 낸다(``coverage_reports.py`` 와 동일).
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        processing_job_store: ProcessingJobStore,
        comparison_request_store: Any | None = None,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._processing_job_store = processing_job_store
        # Optional only for direct legacy unit fixtures.  Every assembled Core
        # app supplies it; fence-bearing result submissions require it.
        self._comparison_request_store = comparison_request_store
        self._lock = threading.Lock()
        self._by_mission: dict[str, list[RecordedChangeDetection]] = {}
        self._ids_by_mission: dict[str, dict[str, ChangeDetectionResult]] = {}
        try:
            self._replay(journal)
        except ChangeDetectionRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise ChangeDetectionRecoveryError(
                f"change-detection journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def mission_is_visible(self, mission_id: str) -> bool:
        return self._mission_store.get(mission_id) is not None

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "change-detection-rejected":
                continue
            if kind not in (None, "change-detection-recorded"):
                raise ChangeDetectionRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")
            mission_id = raw["missionId"]
            result = ChangeDetectionResult.model_validate(raw["result"])
            # 재생도 live 와 같은 게이트를 태운다 — journal 조작으로 해석 불가능한
            # 비교 결과가 되살아나는 경로를 막는다. live record() 는 임무 존재부터
            # 검사한다(UNKNOWN_MISSION) — 재생이 그 검사를 건너뛰면, 임무가 삭제되거나
            # 애초에 발급된 적 없는 채로 기록된 레코드가 재기동마다 조용히 되살아난다.
            if self._mission_store.get(mission_id) is None:
                raise ChangeDetectionRecoveryError(
                    f"재생: 기록될 수 없는 결과(UNKNOWN_MISSION: {_UNKNOWN_MISSION_DETAIL}) — "
                    f"missionId={mission_id} changeDetectionId={result.change_detection_id}"
                )
            verdict, detail = self._judge_references(result)
            if verdict is not ChangeDetectionVerdict.RECORDED:
                raise ChangeDetectionRecoveryError(
                    f"재생: 기록될 수 없는 결과({verdict.value}: {detail}) — "
                    f"missionId={mission_id} changeDetectionId={result.change_detection_id}"
                )
            request_id, fence = self._replay_authority(raw, result)
            if (
                fence is not None
                and (
                    self._comparison_request_store is None
                    or not self._comparison_request_store.has_recorded_lease_fence(
                        result.change_detection_id,
                        fence,
                        authenticated_actor_id=raw.get("reportedBy"),
                    )
                )
            ):
                raise ChangeDetectionRecoveryError(
                    "재생: result authority가 durable request lease history에 없다"
                )
            self._project(
                mission_id,
                result,
                raw.get("reportedBy"),
                datetime.fromisoformat(raw["ts"]),
                request_id=request_id,
                accepted_lease_fence=fence,
            )

    @staticmethod
    def _replay_authority(
        raw: dict[str, Any], result: ChangeDetectionResult
    ) -> tuple[str | None, LeaseFence | None]:
        if raw.get("authorityVersion") is None:
            return None, None
        if raw.get("authorityVersion") != 1 or raw.get("requestId") != result.change_detection_id:
            raise ChangeDetectionRecoveryError("재생: malformed result authority")
        fields = raw.get("acceptedLeaseFence")
        if not isinstance(fields, dict):
            raise ChangeDetectionRecoveryError("재생: missing accepted lease fence")
        try:
            fence = LeaseFence(
                str(fields["workerInstanceId"]),
                str(fields["leaseAcquisitionId"]),
                int(fields["leaseGeneration"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ChangeDetectionRecoveryError("재생: malformed accepted lease fence") from exc
        if not fence.is_well_formed():
            raise ChangeDetectionRecoveryError("재생: invalid accepted lease fence")
        return result.change_detection_id, fence

    def _project(
        self,
        mission_id: str,
        result: ChangeDetectionResult,
        reported_by: str | None,
        recorded_at: datetime,
        *,
        request_id: str | None = None,
        accepted_lease_fence: LeaseFence | None = None,
    ) -> None:
        self._by_mission.setdefault(mission_id, []).append(
            RecordedChangeDetection(
                result=result,
                reported_by=reported_by,
                recorded_at=recorded_at,
                request_id=request_id,
                accepted_lease_fence=accepted_lease_fence,
            )
        )
        self._ids_by_mission.setdefault(mission_id, {})[result.change_detection_id] = result

    def _judge_references(
        self, result: ChangeDetectionResult
    ) -> tuple[ChangeDetectionVerdict, str | None]:
        """``baseline``/``current`` 가 실제 등록된 point_cloud 산출물인가.

        live 수신과 journal 재생이 같은 함수를 쓴다 — 각자 조건문을 들고 있으면
        한쪽만 고쳐지는 순간 원장이 거짓 검증을 되살린다. self-comparison 검사는
        change-detection 고유 로직이다(volume 쪽은 계약 모델이 대신 한다) — 여기
        그대로 두고, 산출물 존재·kind 검증만 ``artifact_refs.verify_artifact_pair``
        로 공유한다.
        """
        if (result.baseline.job_id, result.baseline.artifact_id) == (
            result.current.job_id,
            result.current.artifact_id,
        ):
            return (
                ChangeDetectionVerdict.SELF_COMPARISON,
                "baseline 과 current 가 같은 산출물이다 — 자기 자신과의 C2C 는 전 점"
                " 거리 0 이라 '변화 없음'으로 정직해 보이지만 아무것도 비교하지 않은 것이다",
            )
        issue = verify_artifact_pair(
            self._processing_job_store,
            result.baseline,
            result.current,
            required_kind=ProcessingArtifactKind.POINT_CLOUD,
            kind_mismatch_detail=lambda label, kind: (
                f"{label} 산출물의 kind 가 {kind.value!r} 다 — C2C 비교의"
                " 입력은 point_cloud 여야 한다"
            ),
        )
        if issue is None:
            return ChangeDetectionVerdict.RECORDED, None
        reason, detail = issue
        verdict = (
            ChangeDetectionVerdict.UNKNOWN_ARTIFACT
            if reason is ArtifactRefIssue.UNKNOWN_ARTIFACT
            else ChangeDetectionVerdict.ARTIFACT_KIND_MISMATCH
        )
        return verdict, detail

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def record(
        self,
        mission_id: str,
        result: ChangeDetectionResult,
        *,
        now: datetime,
        reported_by: str | None = None,
        lease_fence: LeaseFence | None = None,
    ) -> ChangeDetectionRecordResult:
        # Legacy direct-store callers remain readable/testable, but any
        # fence-bearing (therefore new worker) publication must be bound to a
        # comparison request and its current authoritative fence.
        if self._comparison_request_store is not None:
            return self._record_fenced(
                mission_id, result, now=now, reported_by=reported_by, lease_fence=lease_fence
            )
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ChangeDetectionRecordResult(
                    ChangeDetectionVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            if self._mission_store.get(mission_id) is None:
                return self._reject(
                    mission_id,
                    result,
                    now,
                    reported_by,
                    ChangeDetectionVerdict.UNKNOWN_MISSION,
                    _UNKNOWN_MISSION_DETAIL,
                )
            existing = self._ids_by_mission.get(mission_id, {}).get(result.change_detection_id)
            if existing is not None:
                if existing == result:
                    return ChangeDetectionRecordResult(
                        ChangeDetectionVerdict.RECORDED,
                        detail="이미 같은 내용으로 기록돼 있다(멱등 재전송)",
                    )
                return self._reject(
                    mission_id,
                    result,
                    now,
                    reported_by,
                    ChangeDetectionVerdict.DUPLICATE_RESULT_ID,
                    f"changeDetectionId={result.change_detection_id!r} 는 이미 다른"
                    " 내용으로 기록됐다 — 같은 id 로 다른 결과를 덮어쓸 수 없다",
                )
            verdict, detail = self._judge_references(result)
            if verdict is not ChangeDetectionVerdict.RECORDED:
                return self._reject(mission_id, result, now, reported_by, verdict, detail)

            record = {
                "kind": "change-detection-recorded",
                "ts": iso_utc(now),
                "missionId": mission_id,
                "reportedBy": reported_by,
                "result": result.model_dump(by_alias=True, mode="json", exclude_none=False),
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return ChangeDetectionRecordResult(
                    ChangeDetectionVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_APPEND_FAILED_DETAIL,
                )
            self._project(mission_id, result, reported_by, now)
            return ChangeDetectionRecordResult(ChangeDetectionVerdict.RECORDED)

    def _record_fenced(
        self,
        mission_id: str,
        result: ChangeDetectionResult,
        *,
        now: datetime,
        reported_by: str | None,
        lease_fence: LeaseFence | None,
    ) -> ChangeDetectionRecordResult:
        request_id = result.change_detection_id
        request_store = self._comparison_request_store
        assert request_store is not None  # noqa: S101 -- selected by record() branch
        with request_store.result_commit_guard(
            request_id, lease_fence=lease_fence, authenticated_actor_id=reported_by, now=now
        ) as authorization:
            if not authorization.authorized:
                return self._lease_denial(authorization.verdict, authorization.detail)
            request = authorization.record
            assert request is not None  # noqa: S101 -- authorization invariant
            if request.mission_id != mission_id:
                return ChangeDetectionRecordResult(
                    ChangeDetectionVerdict.REQUEST_MISMATCH,
                    "comparison request missionId 가 결과 경로와 다르다",
                )
            if not request.change_detection_eligible:
                return ChangeDetectionRecordResult(
                    ChangeDetectionVerdict.REQUEST_INELIGIBLE,
                    request.change_detection_ineligible_reason,
                )
            with self._lock:
                if self._journal.sealed_reason is not None:
                    return ChangeDetectionRecordResult(
                        ChangeDetectionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                    )
                existing = self._ids_by_mission.get(mission_id, {}).get(result.change_detection_id)
                if existing is not None:
                    if existing == result:
                        return ChangeDetectionRecordResult(
                            ChangeDetectionVerdict.RECORDED,
                            detail="이미 같은 내용으로 기록돼 있다(멱등 재전송)",
                        )
                    return ChangeDetectionRecordResult(
                        ChangeDetectionVerdict.DUPLICATE_RESULT_ID,
                        f"changeDetectionId={result.change_detection_id!r} 는 이미 다른 "
                        "내용으로 기록됐다",
                    )
                verdict, detail = self._judge_references(result)
                if verdict is not ChangeDetectionVerdict.RECORDED:
                    return ChangeDetectionRecordResult(verdict, detail=detail)
                assert lease_fence is not None  # noqa: S101 -- guard authorized only for a fence
                raw = {
                    "kind": "change-detection-recorded",
                    "authorityVersion": 1,
                    "ts": iso_utc(now),
                    "missionId": mission_id,
                    "requestId": request_id,
                    "acceptedLeaseFence": {
                        "workerInstanceId": lease_fence.worker_instance_id,
                        "leaseAcquisitionId": lease_fence.lease_acquisition_id,
                        "leaseGeneration": lease_fence.lease_generation,
                    },
                    "reportedBy": reported_by,
                    "result": result.model_dump(by_alias=True, mode="json", exclude_none=False),
                }
                try:
                    self._journal.append(raw)
                except JournalSealedError:
                    return ChangeDetectionRecordResult(
                        ChangeDetectionVerdict.STORE_UNAVAILABLE,
                        detail=JOURNAL_APPEND_FAILED_DETAIL,
                    )
                self._project(
                    mission_id, result, reported_by, now,
                    request_id=request_id, accepted_lease_fence=lease_fence,
                )
                return ChangeDetectionRecordResult(ChangeDetectionVerdict.RECORDED)

    @staticmethod
    def _lease_denial(verdict: Any, detail: str | None) -> ChangeDetectionRecordResult:
        mapping = {
            "UNKNOWN_REQUEST": ChangeDetectionVerdict.UNKNOWN_REQUEST,
            "LEASE_REQUIRED": ChangeDetectionVerdict.LEASE_REQUIRED,
            "LEASE_HELD_BY_ANOTHER": ChangeDetectionVerdict.LEASE_HELD_BY_ANOTHER,
            "STALE_LEASE_ACQUISITION": ChangeDetectionVerdict.STALE_LEASE_ACQUISITION,
            "STALE_LEASE_GENERATION": ChangeDetectionVerdict.STALE_LEASE_GENERATION,
            "INVALID_LEASE_FENCE": ChangeDetectionVerdict.INVALID_LEASE_FENCE,
            "STORE_UNAVAILABLE": ChangeDetectionVerdict.STORE_UNAVAILABLE,
        }
        return ChangeDetectionRecordResult(
            mapping.get(str(verdict), ChangeDetectionVerdict.LEASE_REQUIRED), detail
        )

    def _reject(
        self,
        mission_id: str,
        result: ChangeDetectionResult,
        now: datetime,
        reported_by: str | None,
        verdict: ChangeDetectionVerdict,
        detail: str | None,
    ) -> ChangeDetectionRecordResult:
        record = {
            "kind": "change-detection-rejected",
            "ts": iso_utc(now),
            "missionId": mission_id,
            "changeDetectionId": result.change_detection_id,
            "verdict": verdict.value,
            "detail": detail,
            "reportedBy": reported_by,
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return ChangeDetectionRecordResult(
                ChangeDetectionVerdict.STORE_UNAVAILABLE,
                detail=JOURNAL_APPEND_FAILED_DETAIL,
            )
        return ChangeDetectionRecordResult(verdict, detail=detail)

    def latest(self, mission_id: str) -> RecordedChangeDetection | None:
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return None
        with self._lock:
            recorded = self._by_mission.get(mission_id)
            return recorded[-1] if recorded else None

    def history(self, mission_id: str) -> list[RecordedChangeDetection]:
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return []
        with self._lock:
            return list(self._by_mission.get(mission_id, ()))


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class ChangeDetectionResponse(CamelModel):
    verdict: str
    detail: str | None


class ChangeDetectionView(CamelModel):
    """그 임무의 최신 변화 탐지 결과 + 재방문 권고.

    ``revisitRatioThreshold`` 를 함께 싣는 이유는 모듈 docstring 참고 — 권고
    불리언만 주면 화면이 "무슨 기준으로 켜졌나"를 표시할 수 없다.
    """

    mission_id: str
    result_count: int
    latest: dict[str, Any]
    reported_by: str | None
    recorded_at: datetime
    revisit_ratio_threshold: float
    revisit_recommended: bool


def build_change_detection_router(store: ChangeDetectionStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["change-detection"])

    @router.post("/{mission_id}/change-detection", status_code=201)
    def submit_change_detection(
        mission_id: str,
        result: ChangeDetectionResult,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ChangeDetectionResponse:
        """변화 탐지 결과 접수 — **처리 워커만** 올린다.

        사람이 손으로 "변화가 이만큼 있었다"를 원장에 주장할 수 없다
        (``defect_candidates.py`` 와 동일 원칙, PROCESSING_WORK 는 어느 Role 에도
        매핑되지 않는다).
        """
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
            result,
            now=datetime.now(UTC),
            reported_by=principal.principal_id,
            lease_fence=fence,
        )
        response.status_code = _STATUS[outcome.verdict]
        if outcome.verdict is ChangeDetectionVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ChangeDetectionResponse(verdict=outcome.verdict.value, detail=outcome.detail)

    @router.get("/{mission_id}/change-detection", response_model=ChangeDetectionView)
    def get_change_detection(
        mission_id: str,
        revisit_ratio_threshold: float = Query(  # noqa: B008
            default=DEFAULT_REVISIT_RATIO_THRESHOLD,
            alias="revisitRatioThreshold",
            ge=0.0,
            le=1.0,
        ),
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ChangeDetectionView:
        """그 임무의 **최신** 결과 + 재방문 권고(PRD §15.2 ⑤).

        ``revisitRecommended`` 는 권고일 뿐 재비행을 트리거하지 않는다 — 운영자가
        이 신호를 보고 원본 site AOI 로 SPATIAL_REFRESH 임무를
        ``POST /v1/missions/plans`` 에 발급한다.
        """
        if not store.mission_is_visible(mission_id):
            raise HTTPException(
                status_code=404, detail="해당 임무의 변화 탐지 결과를 찾을 수 없다"
            )
        recorded = store.latest(mission_id)
        if recorded is None:
            raise HTTPException(
                status_code=404, detail="해당 임무의 변화 탐지 결과를 찾을 수 없다"
            )
        return ChangeDetectionView(
            mission_id=mission_id,
            result_count=len(store.history(mission_id)),
            latest=recorded.result.model_dump(by_alias=True, mode="json", exclude_none=False),
            reported_by=recorded.reported_by,
            recorded_at=recorded.recorded_at,
            revisit_ratio_threshold=revisit_ratio_threshold,
            revisit_recommended=recorded.result.needs_revisit(
                candidate_ratio_threshold=revisit_ratio_threshold
            ),
        )

    return router


def mount_change_detection(app: FastAPI, store: ChangeDetectionStore) -> None:
    app.include_router(build_change_detection_router(store))


__all__ = [
    "DEFAULT_REVISIT_RATIO_THRESHOLD",
    "ChangeDetectionRecordResult",
    "ChangeDetectionRecoveryError",
    "ChangeDetectionStore",
    "ChangeDetectionVerdict",
    "ChangeDetectionView",
    "build_change_detection_router",
    "mount_change_detection",
]
