"""비교 요청 원장 — "이 두 작업을 비교하라"는 지시의 수신·발견·lease·전이 (W2, ADR-KSI-016 D3).

## change_detection.py/volume_reports.py 를 확장하지 않고 형제로 둔 이유

세 모듈은 검증 대상이 다르다 — 저 둘은 이미 **계산된 결과**를 받아 baseline/
current 산출물이 실재하는지만 본다. 이 모듈은 그 계산을 **해 달라는 지시**를
받아 durable하게 남기고, 워커가 찾아 실행할 수 있는 표면을 연다. 형태가 다른
것을 한 저장소에 얹으면 조건분기가 섞인다(``volume_reports.py`` 자신의 표현을
빌리면 "복제한 것은 구조지 판단이 아니다") — 골격(journal 위 append-only +
참조 검증 + live·재생 공유 게이트)은 복제하되 판단 로직은 이 모듈만의 것이다.

## ProcessingJobStore 를 확장하지 않고 별도 store 를 둔 이유

두 가지 구조적 충돌 때문이다. ① ``ProcessingJobStore.issue()`` 의 "임무당
활성 작업 1건" 게이트는 재구성 재처리와 과거 결과 비교를 같은 슬롯으로 묶는데,
의미상 서로 막을 이유가 없다. ② ``assert_succeeded_is_backed``(INV-051)는
SUCCEEDED 전이에 ``authority=source`` 산출물 등록을 요구하는데, 비교 요청은
산출물을 등록하지 않고 ``ChangeDetectionStore``/``VolumeChangeStore`` 에 결과를
남긴다. 이미 여러 차례 독립검토를 통과한 INV-051 핵심 게이트에 무관한 관심사를
섞는 리스크가, store 하나를 더 두는 비용보다 크다.

## lease 는 발명하지 않고 재사용한다

:class:`~ksi_core.processing_jobs.JobLease` 를 그대로 import 해서 쓴다 —
``worker_id``·``granted_at``·``expires_at``·``is_active``·``held_by`` 뿐인
순수 데이터클래스라 재구성 특유 필드가 없다. 원자적 획득(``threading.Lock``
기반 확인-후-기록)과 ``list_pending`` 의 "QUEUED + lease 만료된 RUNNING"
필터도 ``ProcessingJobStore`` 의 것과 같은 알고리즘을 다시 구현한다(레코드
타입이 달라 제네릭화는 하지 않는다 — 그 자체가 별도 리팩터 리스크다).

## 워커가 baseline/current 원본을 읽는 유일한 경로

``GET /v1/processing-jobs/{jobId}/artifacts/{artifactId}/download`` 는 명시적으로
``MISSIONS_READ``(사람) 전용이고 ``PROCESSING_WORK`` 는 포함하지 않는다("워커는
남의 산출물을 다시 읽을 이유가 없다") — 비교 워커는 태생적으로 남의(자기가 안
만든) 두 작업의 산출물을 읽어야 하므로 이 경계와 충돌한다. 그래서
``GET /v1/comparison-requests/{id}/input`` 을 이 모듈이 새로 연다 — **그 요청이
가리키는 baseline/current 산출물에 한해서만** presigned GET 을 내준다(다른
임의 작업의 산출물은 여전히 못 본다, 최소권한 유지).

## 구역(zones)은 참조가 아니라 값이다

요청 레코드는 ``site.aoi`` 를 참조(foreign key)하지 않고 폴리곤 값 자체를
갖는다(대표자 확정, 2026-08-10) — 나중에 현장 경계가 바뀌어도 이미 만든 요청·
결과는 그대로 유지된다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy, current_comparison_policy
from ksi_event_contracts.comparison_request import ComparisonRequest
from ksi_event_contracts.processing_artifact import ProcessingArtifact, ProcessingArtifactKind
from ksi_event_contracts.processing_job import ProcessingJobStatus
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import DEFAULT_VIEW_TTL, EvidenceStorage, EvidenceStorageError
from ksi_core.processing_jobs import (
    DEFAULT_LEASE_TTL,
    JobLease,
    ProcessingJobRecord,
    ProcessingJobStore,
    build_processing_artifact_object_key,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_records import MissionStore

logger = logging.getLogger(__name__)

_NOT_FOUND_DETAIL = "해당 비교 요청을 찾을 수 없다"
_STORE_UNAVAILABLE_DETAIL = "journal 봉인됨 — 재시작 필요"

_ACTIVE_STATUSES = frozenset({ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING})

# 상태 전이표 — CANCELLED 는 W2 범위에 없다(대표자 확정 §4 W2-1 비범위). QUEUED→
# RUNNING→{SUCCEEDED,FAILED} 만 있으면 되는 이유: 정체된 RUNNING 은 lease 만료로
# 회수되고(list_pending), 사람이 수동 취소할 긴급성이 재구성만큼 크지 않다
# (비교 계산은 시간 단위가 아니라 분 단위다).
_ALLOWED_TRANSITIONS: dict[ProcessingJobStatus, frozenset[ProcessingJobStatus]] = {
    ProcessingJobStatus.QUEUED: frozenset({ProcessingJobStatus.RUNNING}),
    ProcessingJobStatus.RUNNING: frozenset(
        {ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.FAILED}
    ),
    ProcessingJobStatus.SUCCEEDED: frozenset(),
    ProcessingJobStatus.FAILED: frozenset(),
}


class IllegalComparisonTransitionError(ValueError):
    """전이표에 없는 비교 요청 상태 전이."""


def assert_comparison_transition(before: ProcessingJobStatus, after: ProcessingJobStatus) -> None:
    """전이 적법성 — live 경로와 재생 경로가 같은 함수를 쓴다(processing_jobs.py 와 동형)."""
    if after not in _ALLOWED_TRANSITIONS[before]:
        suffix = (
            " — 종료된 요청의 결론은 고쳐 쓰지 않는다" if not _ALLOWED_TRANSITIONS[before] else ""
        )
        raise IllegalComparisonTransitionError(
            f"비교 요청 상태를 {before.value} 에서 {after.value} 로 바꿀 수 없다{suffix}"
        )


class ComparisonRequestVerdict(StrEnum):
    """생성/조회/lease/전이 판정."""

    CREATED = "CREATED"
    # baselineJobId+currentJobId 조합이 이미 요청된 적 있다 — 새로 만들지 않고
    # 기존 요청을 그대로 돌려준다(멱등, 네트워크 재시도가 요청을 복제하지 않는다).
    ALREADY_REQUESTED = "ALREADY_REQUESTED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    UNKNOWN_JOB = "UNKNOWN_JOB"
    JOB_NOT_SUCCEEDED = "JOB_NOT_SUCCEEDED"
    SELF_COMPARISON = "SELF_COMPARISON"
    SITE_MISMATCH = "SITE_MISMATCH"
    MISSION_MISMATCH = "MISSION_MISMATCH"
    # 두 작업 어느 쪽도 point_cloud+dsm(+구역) 조합을 갖추지 못했다 — 계산할 것이 없다.
    NOTHING_TO_COMPARE = "NOTHING_TO_COMPARE"
    UNKNOWN_REQUEST = "UNKNOWN_REQUEST"
    REQUEST_NOT_ACTIVE = "REQUEST_NOT_ACTIVE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"

    # ── lease ────────────────────────────────────────────────────────────
    LEASED = "LEASED"
    LEASE_RENEWED = "LEASE_RENEWED"
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    LEASE_REQUIRED = "LEASE_REQUIRED"

    # ── 전이 ─────────────────────────────────────────────────────────────
    TRANSITIONED = "TRANSITIONED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"

    # ── 입력 조회 ────────────────────────────────────────────────────────
    INPUT_READY = "INPUT_READY"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


_STATUS: dict[ComparisonRequestVerdict, int] = {
    ComparisonRequestVerdict.CREATED: 201,
    ComparisonRequestVerdict.ALREADY_REQUESTED: 200,
    ComparisonRequestVerdict.UNKNOWN_MISSION: 404,
    ComparisonRequestVerdict.UNKNOWN_JOB: 422,
    ComparisonRequestVerdict.JOB_NOT_SUCCEEDED: 422,
    ComparisonRequestVerdict.SELF_COMPARISON: 422,
    ComparisonRequestVerdict.SITE_MISMATCH: 422,
    ComparisonRequestVerdict.MISSION_MISMATCH: 422,
    ComparisonRequestVerdict.NOTHING_TO_COMPARE: 422,
    ComparisonRequestVerdict.UNKNOWN_REQUEST: 404,
    ComparisonRequestVerdict.REQUEST_NOT_ACTIVE: 409,
    ComparisonRequestVerdict.STORE_UNAVAILABLE: 503,
    ComparisonRequestVerdict.LEASED: 201,
    ComparisonRequestVerdict.LEASE_RENEWED: 200,
    ComparisonRequestVerdict.LEASE_HELD_BY_ANOTHER: 409,
    ComparisonRequestVerdict.LEASE_REQUIRED: 409,
    ComparisonRequestVerdict.TRANSITIONED: 200,
    ComparisonRequestVerdict.ILLEGAL_TRANSITION: 409,
    ComparisonRequestVerdict.INPUT_READY: 200,
    ComparisonRequestVerdict.STORAGE_UNAVAILABLE: 503,
}


class ComparisonRequestRecoveryError(RuntimeError):
    """comparison-requests journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


def build_comparison_request_id(mission_id: str, sequence: int) -> str:
    """``{missionId}-cmp{n}`` — ``build_job_id`` 와 동형. 결정적이고 사람이 읽을 수 있다."""
    return f"{mission_id}-cmp{sequence}"


@dataclass(frozen=True, slots=True)
class ComparisonRequestRecord:
    """비교 요청 1건의 projection — 계약 필드 + 운영 메타(lease)."""

    request_id: str
    mission_id: str
    site_id: str
    baseline_job_id: str
    current_job_id: str
    point_cloud_baseline: ArtifactRef | None
    point_cloud_current: ArtifactRef | None
    change_detection_eligible: bool
    change_detection_ineligible_reason: str | None
    dsm_baseline: ArtifactRef | None
    dsm_current: ArtifactRef | None
    volume_change_eligible: bool
    volume_change_ineligible_reason: str | None
    zones: dict[str, dict[str, Any]] | None
    zone_crs: str | None
    # 요청 생성 시점의 기준값을 **값으로** 복사해 둔 것(zones 와 같은 원칙) —
    # 나중에 시스템 기준값이 바뀌어도 이미 만들어진 요청·결과는 "그때 무슨
    # 기준으로 쟀는지"를 스스로 답한다. 워커가 계산할 때 실제로 이 값을 쓴다.
    policy: ComparisonPolicy
    status: ProcessingJobStatus
    requested_at: datetime
    requested_by: str
    updated_at: datetime
    detail: str | None = None
    lease: JobLease | None = None

    def to_contract(self) -> ComparisonRequest:
        return ComparisonRequest(
            request_id=self.request_id,
            mission_id=self.mission_id,
            site_id=self.site_id,
            baseline_job_id=self.baseline_job_id,
            current_job_id=self.current_job_id,
            point_cloud_baseline=self.point_cloud_baseline,
            point_cloud_current=self.point_cloud_current,
            change_detection_eligible=self.change_detection_eligible,
            change_detection_ineligible_reason=self.change_detection_ineligible_reason,
            dsm_baseline=self.dsm_baseline,
            dsm_current=self.dsm_current,
            volume_change_eligible=self.volume_change_eligible,
            volume_change_ineligible_reason=self.volume_change_ineligible_reason,
            zones=self.zones,
            zone_crs=self.zone_crs,
            policy=self.policy,
            status=self.status,
            requested_at=self.requested_at,
            requested_by=self.requested_by,
            updated_at=self.updated_at,
            detail=self.detail,
        )


@dataclass(frozen=True, slots=True)
class ComparisonRequestResult:
    verdict: ComparisonRequestVerdict
    detail: str | None = None
    record: ComparisonRequestRecord | None = None


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _find_artifact(
    job: ProcessingJobRecord, kind: ProcessingArtifactKind
) -> ProcessingArtifact | None:
    return next((a for a in job.artifacts if a.kind is kind), None)


@dataclass(frozen=True, slots=True)
class _Resolved:
    """검증을 통과한 요청의 파생값 — live 생성과 재생이 공유한다."""

    site_id: str
    point_cloud_baseline: ArtifactRef | None
    point_cloud_current: ArtifactRef | None
    change_detection_eligible: bool
    change_detection_ineligible_reason: str | None
    dsm_baseline: ArtifactRef | None
    dsm_current: ArtifactRef | None
    volume_change_eligible: bool
    volume_change_ineligible_reason: str | None
    zones: dict[str, dict[str, Any]] | None
    zone_crs: str | None


class ComparisonRequestStore:
    """``DurableJournal`` 위의 비교 요청 원장 — append-only, 덮어쓰지 않는다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        processing_job_store: ProcessingJobStore,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._processing_job_store = processing_job_store
        self._lock = threading.Lock()
        self._requests: dict[str, ComparisonRequestRecord] = {}
        self._by_pair: dict[tuple[str, str], str] = {}
        self._sequence: dict[str, int] = {}
        try:
            self._replay(journal)
        except ComparisonRequestRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise ComparisonRequestRecoveryError(
                f"comparison-requests journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    # ── 재생 ─────────────────────────────────────────────────────────────

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "comparison-request-created":
                self._replay_created(raw)
            elif kind == "comparison-request-leased":
                self._replay_lease(raw)
            elif kind == "comparison-request-transitioned":
                self._replay_transition(raw)
            else:
                raise ComparisonRequestRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")

    def _replay_created(self, raw: dict[str, Any]) -> None:
        contract = ComparisonRequest.model_validate(raw["request"])
        # 재생도 live 와 같은 게이트를 태운다 — journal 조작으로 해석 불가능한
        # 요청이 되살아나는 경로를 막는다(change_detection.py 와 동일 원칙).
        verdict, detail, resolved = self._resolve(
            mission_id=contract.mission_id,
            baseline_job_id=contract.baseline_job_id,
            current_job_id=contract.current_job_id,
            zones=contract.zones,
            zone_crs=contract.zone_crs,
        )
        if verdict is not ComparisonRequestVerdict.CREATED or resolved is None:
            raise ComparisonRequestRecoveryError(
                f"재생: 기록될 수 없는 요청({verdict.value}: {detail}) — "
                f"requestId={contract.request_id}"
            )
        record = ComparisonRequestRecord(
            request_id=contract.request_id,
            mission_id=contract.mission_id,
            site_id=resolved.site_id,
            baseline_job_id=contract.baseline_job_id,
            current_job_id=contract.current_job_id,
            point_cloud_baseline=resolved.point_cloud_baseline,
            point_cloud_current=resolved.point_cloud_current,
            change_detection_eligible=resolved.change_detection_eligible,
            change_detection_ineligible_reason=resolved.change_detection_ineligible_reason,
            dsm_baseline=resolved.dsm_baseline,
            dsm_current=resolved.dsm_current,
            volume_change_eligible=resolved.volume_change_eligible,
            volume_change_ineligible_reason=resolved.volume_change_ineligible_reason,
            zones=resolved.zones,
            zone_crs=resolved.zone_crs,
            # **원장에 적힌 그 값**을 그대로 되살린다 — 여기서
            # current_comparison_policy() 를 부르면 기준값을 바꾼 배포가 과거
            # 요청의 기준까지 소급해 고쳐 쓰게 되고, 그건 "그때 무슨 기준으로
            # 쟀나"에 답할 수 없게 만든다(zones 를 값으로 저장하는 것과 같은 이유).
            policy=contract.policy,
            status=ProcessingJobStatus.QUEUED,
            requested_at=contract.requested_at,
            requested_by=contract.requested_by,
            updated_at=contract.requested_at,
        )
        self._project(record)
        sequence = int(contract.request_id.rsplit("-cmp", 1)[-1])
        self._sequence[contract.mission_id] = max(
            self._sequence.get(contract.mission_id, 0), sequence
        )

    def _replay_lease(self, raw: dict[str, Any]) -> None:
        """lease 레코드 재생 — 만료 재판정을 하지 않는다(processing_jobs.py 와 동일 원칙)."""
        request_id = raw["requestId"]
        record = self._requests.get(request_id)
        if record is None:
            raise ComparisonRequestRecoveryError(
                f"재생: 미지 requestId lease 레코드 — {request_id}"
            )
        if record.status not in _ACTIVE_STATUSES:
            raise ComparisonRequestRecoveryError(
                f"재생: 종료된 요청({record.status.value})에 lease 레코드가 있다 — {request_id}"
            )
        self._requests[request_id] = replace(
            record,
            lease=JobLease(
                worker_id=raw["workerId"],
                granted_at=_require_aware_iso(raw["ts"], "ts", request_id),
                expires_at=_require_aware_iso(raw["expiresAt"], "expiresAt", request_id),
            ),
        )

    def _replay_transition(self, raw: dict[str, Any]) -> None:
        request_id = raw["requestId"]
        record = self._requests.get(request_id)
        if record is None:
            raise ComparisonRequestRecoveryError(
                f"재생: 미지 requestId 전이 레코드 — {request_id}"
            )
        before = record.status
        after = ProcessingJobStatus(raw["targetStatus"])
        assert_comparison_transition(before, after)
        self._requests[request_id] = replace(
            record,
            status=after,
            detail=raw.get("detail"),
            updated_at=_require_aware_iso(raw["ts"], "ts", request_id),
        )

    def _project(self, record: ComparisonRequestRecord) -> None:
        self._requests[record.request_id] = record
        self._by_pair[(record.baseline_job_id, record.current_job_id)] = record.request_id

    # ── 생성 게이트 (live·재생 공유) ─────────────────────────────────────

    def _resolve(
        self,
        *,
        mission_id: str,
        baseline_job_id: str,
        current_job_id: str,
        zones: dict[str, dict[str, Any]] | None,
        zone_crs: str | None,
    ) -> tuple[ComparisonRequestVerdict, str | None, _Resolved | None]:
        if self._mission_store.get(mission_id) is None:
            return (
                ComparisonRequestVerdict.UNKNOWN_MISSION,
                "발급된 적 없는 임무에는 비교 요청을 만들 수 없다",
                None,
            )
        if baseline_job_id == current_job_id:
            return (
                ComparisonRequestVerdict.SELF_COMPARISON,
                "baselineJobId 와 currentJobId 가 같다 — 자기 자신과의 비교는 "
                "'변화 없음'으로 정직해 보이지만 아무것도 비교하지 않은 것이다",
                None,
            )
        baseline_job = self._processing_job_store.get(baseline_job_id)
        if baseline_job is None:
            return (
                ComparisonRequestVerdict.UNKNOWN_JOB,
                f"baselineJobId={baseline_job_id!r} 인 처리 작업이 없다",
                None,
            )
        current_job = self._processing_job_store.get(current_job_id)
        if current_job is None:
            return (
                ComparisonRequestVerdict.UNKNOWN_JOB,
                f"currentJobId={current_job_id!r} 인 처리 작업이 없다",
                None,
            )
        if baseline_job.status is not ProcessingJobStatus.SUCCEEDED:
            return (
                ComparisonRequestVerdict.JOB_NOT_SUCCEEDED,
                f"baseline 작업이 {baseline_job.status.value} 다 — SUCCEEDED 작업만 "
                "비교 후보다",
                None,
            )
        if current_job.status is not ProcessingJobStatus.SUCCEEDED:
            return (
                ComparisonRequestVerdict.JOB_NOT_SUCCEEDED,
                f"current 작업이 {current_job.status.value} 다 — SUCCEEDED 작업만 "
                "비교 후보다",
                None,
            )
        if baseline_job.site_id != current_job.site_id:
            return (
                ComparisonRequestVerdict.SITE_MISMATCH,
                f"baseline 은 현장 {baseline_job.site_id!r}, current 는 현장 "
                f"{current_job.site_id!r} 다 — 같은 현장의 작업만 비교할 수 있다",
                None,
            )
        if current_job.mission_id != mission_id:
            return (
                ComparisonRequestVerdict.MISSION_MISMATCH,
                f"currentJobId 는 임무 {current_job.mission_id!r} 소속인데 경로의 "
                f"missionId 는 {mission_id!r} 다",
                None,
            )

        pc_baseline = _find_artifact(baseline_job, ProcessingArtifactKind.POINT_CLOUD)
        pc_current = _find_artifact(current_job, ProcessingArtifactKind.POINT_CLOUD)
        cd_eligible = pc_baseline is not None and pc_current is not None
        cd_reason = None
        if not cd_eligible:
            missing = [
                label
                for label, artifact in (("baseline", pc_baseline), ("current", pc_current))
                if artifact is None
            ]
            cd_reason = f"{'·'.join(missing)} 작업에 point_cloud 산출물이 없다"

        dsm_baseline = _find_artifact(baseline_job, ProcessingArtifactKind.DSM)
        dsm_current = _find_artifact(current_job, ProcessingArtifactKind.DSM)
        has_zones = bool(zones) and zone_crs is not None
        vol_eligible = dsm_baseline is not None and dsm_current is not None and has_zones
        vol_reason = None
        if not vol_eligible:
            missing = [
                label
                for label, artifact in (("baseline", dsm_baseline), ("current", dsm_current))
                if artifact is None
            ]
            if missing:
                vol_reason = f"{'·'.join(missing)} 작업에 dsm 산출물이 없다"
            else:
                vol_reason = "비교 구역(zones)이 확정되지 않았다"

        if not cd_eligible and not vol_eligible:
            return (
                ComparisonRequestVerdict.NOTHING_TO_COMPARE,
                f"비교할 것이 없다 — 변화탐지: {cd_reason} / 체적: {vol_reason}",
                None,
            )

        return (
            ComparisonRequestVerdict.CREATED,
            None,
            _Resolved(
                site_id=baseline_job.site_id,
                point_cloud_baseline=(
                    ArtifactRef(job_id=baseline_job_id, artifact_id=pc_baseline.artifact_id)
                    if pc_baseline
                    else None
                ),
                point_cloud_current=(
                    ArtifactRef(job_id=current_job_id, artifact_id=pc_current.artifact_id)
                    if pc_current
                    else None
                ),
                change_detection_eligible=cd_eligible,
                change_detection_ineligible_reason=cd_reason,
                dsm_baseline=(
                    ArtifactRef(job_id=baseline_job_id, artifact_id=dsm_baseline.artifact_id)
                    if dsm_baseline
                    else None
                ),
                dsm_current=(
                    ArtifactRef(job_id=current_job_id, artifact_id=dsm_current.artifact_id)
                    if dsm_current
                    else None
                ),
                volume_change_eligible=vol_eligible,
                volume_change_ineligible_reason=vol_reason,
                zones=zones if vol_eligible else None,
                zone_crs=zone_crs if vol_eligible else None,
            ),
        )

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def create(
        self,
        mission_id: str,
        *,
        baseline_job_id: str,
        current_job_id: str,
        zones: dict[str, dict[str, Any]] | None,
        zone_crs: str | None,
        requested_by: str,
        now: datetime,
    ) -> ComparisonRequestResult:
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )

            existing_id = self._by_pair.get((baseline_job_id, current_job_id))
            if existing_id is not None:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.ALREADY_REQUESTED,
                    detail="같은 조합(baselineJobId+currentJobId)의 요청이 이미 있다",
                    record=self._requests[existing_id],
                )

            verdict, detail, resolved = self._resolve(
                mission_id=mission_id,
                baseline_job_id=baseline_job_id,
                current_job_id=current_job_id,
                zones=zones,
                zone_crs=zone_crs,
            )
            if verdict is not ComparisonRequestVerdict.CREATED or resolved is None:
                return ComparisonRequestResult(verdict, detail=detail)

            sequence = self._sequence.get(mission_id, 0) + 1
            request_id = build_comparison_request_id(mission_id, sequence)
            record = ComparisonRequestRecord(
                request_id=request_id,
                mission_id=mission_id,
                site_id=resolved.site_id,
                baseline_job_id=baseline_job_id,
                current_job_id=current_job_id,
                point_cloud_baseline=resolved.point_cloud_baseline,
                point_cloud_current=resolved.point_cloud_current,
                change_detection_eligible=resolved.change_detection_eligible,
                change_detection_ineligible_reason=resolved.change_detection_ineligible_reason,
                dsm_baseline=resolved.dsm_baseline,
                dsm_current=resolved.dsm_current,
                volume_change_eligible=resolved.volume_change_eligible,
                volume_change_ineligible_reason=resolved.volume_change_ineligible_reason,
                zones=resolved.zones,
                zone_crs=resolved.zone_crs,
                # 지금 이 배포가 쓰는 기준값을 값으로 굳힌다 — 이후 이 요청은
                # 시스템 기준이 바뀌어도 자기 스냅샷으로만 계산된다.
                policy=current_comparison_policy(),
                status=ProcessingJobStatus.QUEUED,
                requested_at=now,
                requested_by=requested_by,
                updated_at=now,
            )
            raw = {
                "kind": "comparison-request-created",
                "ts": _iso(now),
                "request": record.to_contract().model_dump(
                    by_alias=True, mode="json", exclude_none=False
                ),
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            self._project(record)
            self._sequence[mission_id] = sequence
            return ComparisonRequestResult(ComparisonRequestVerdict.CREATED, record=record)

    def get(self, request_id: str) -> ComparisonRequestRecord | None:
        with self._lock:
            return self._requests.get(request_id)

    def list_for_mission(self, mission_id: str) -> list[ComparisonRequestRecord]:
        with self._lock:
            records = [r for r in self._requests.values() if r.mission_id == mission_id]
        return sorted(records, key=lambda r: (r.requested_at, r.request_id), reverse=True)

    def list_pending(self, *, now: datetime, limit: int = 50) -> list[ComparisonRequestRecord]:
        """``QUEUED`` + lease 만료된 ``RUNNING`` — ``ProcessingJobStore.list_pending``
        과 동형 로직(W1 정체작업회수와 같은 이유, 모듈 docstring 참조)."""
        if limit < 0:
            raise ValueError(f"limit 은 음수일 수 없다: {limit}")
        with self._lock:
            records = [
                r
                for r in self._requests.values()
                if r.status is ProcessingJobStatus.QUEUED
                or (
                    r.status is ProcessingJobStatus.RUNNING
                    and (r.lease is None or not r.lease.is_active(now))
                )
            ]
        ordered = sorted(records, key=lambda r: (r.requested_at, r.request_id))
        return ordered[:limit]

    @staticmethod
    def _check_lease_locked(
        record: ComparisonRequestRecord, *, worker_id: str, now: datetime
    ) -> tuple[ComparisonRequestVerdict, str] | None:
        lease = record.lease
        if lease is None or not lease.is_active(now):
            return (
                ComparisonRequestVerdict.LEASE_REQUIRED,
                "이 요청의 lease 를 먼저 잡아야 한다",
            )
        if lease.worker_id != worker_id:
            return (
                ComparisonRequestVerdict.LEASE_HELD_BY_ANOTHER,
                f"다른 워커({lease.worker_id})가 {_iso(lease.expires_at)} 까지 이 요청을 "
                "쥐고 있다 — 만료 후 다시 시도한다",
            )
        return None

    def acquire_lease(
        self, request_id: str, *, worker_id: str, now: datetime, ttl: timedelta = DEFAULT_LEASE_TTL
    ) -> ComparisonRequestResult:
        """요청 하나를 쥔다. 같은 워커의 재호출은 갱신(heartbeat) —
        ``ProcessingJobStore.acquire_lease`` 와 동형(모듈 docstring)."""
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            record = self._requests.get(request_id)
            if record is None:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            if record.status not in _ACTIVE_STATUSES:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.REQUEST_NOT_ACTIVE,
                    detail=f"요청이 {record.status.value} 상태다 — 끝난 요청은 잡을 수 없다",
                )
            current = record.lease
            renewing = current is not None and current.held_by(worker_id, now)
            if current is not None and current.is_active(now) and not renewing:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.LEASE_HELD_BY_ANOTHER,
                    detail=(
                        f"다른 워커({current.worker_id})가 {_iso(current.expires_at)} 까지 "
                        "이 요청을 쥐고 있다 — 만료 후 다시 시도한다"
                    ),
                    record=record,
                )
            expires_at_ts = now + ttl
            raw = {
                "kind": "comparison-request-leased",
                "ts": _iso(now),
                "requestId": request_id,
                "workerId": worker_id,
                "expiresAt": _iso(expires_at_ts),
                "renewal": renewing,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            updated = replace(
                record,
                lease=JobLease(
                    worker_id=worker_id,
                    granted_at=current.granted_at if renewing and current else now,
                    expires_at=expires_at_ts,
                ),
            )
            self._requests[request_id] = updated
            return ComparisonRequestResult(
                ComparisonRequestVerdict.LEASE_RENEWED
                if renewing
                else ComparisonRequestVerdict.LEASED,
                record=updated,
            )

    def transition(
        self,
        request_id: str,
        target: ProcessingJobStatus,
        *,
        detail: str | None,
        actor: str,
        now: datetime,
    ) -> ComparisonRequestResult:
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            record = self._requests.get(request_id)
            if record is None:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            denied = self._check_lease_locked(record, worker_id=actor, now=now)
            if denied is not None:
                verdict, detail_msg = denied
                return ComparisonRequestResult(verdict, detail=detail_msg, record=record)
            try:
                assert_comparison_transition(record.status, target)
            except IllegalComparisonTransitionError as exc:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.ILLEGAL_TRANSITION, detail=str(exc), record=record
                )
            raw = {
                "kind": "comparison-request-transitioned",
                "ts": _iso(now),
                "requestId": request_id,
                "targetStatus": target.value,
                "detail": detail,
                "actor": actor,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            updated = replace(record, status=target, detail=detail, updated_at=now)
            self._requests[request_id] = updated
            return ComparisonRequestResult(ComparisonRequestVerdict.TRANSITIONED, record=updated)


def _require_aware_iso(raw: Any, field_name: str, request_id: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ComparisonRequestRecoveryError(
            f"재생: {field_name} 이 tz-naive 다 — requestId={request_id}"
        )
    return value


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ComparisonRequestCreateInput(_CamelModel):
    """요청 생성 본문 — **무엇을 비교할지**만 정한다.

    구역은 site.aoi 를 자동으로 쓰지 않는다(모듈 docstring) — 대시보드가
    사용자 확인을 거친 폴리곤 값을 여기 싣는다. 생략하면(None) 체적 비교는
    시도되지 않는다(점군 비교는 zones 없이도 가능하면 시도된다).
    """

    baseline_job_id: str = Field(min_length=1)
    current_job_id: str = Field(min_length=1)
    zones: dict[str, dict[str, Any]] | None = None
    zone_crs: str | None = None


class ComparisonRequestView(_CamelModel):
    """비교 요청 1건의 조회 표현 — 계약 payload + 운영 메타."""

    request: dict[str, Any]
    lease_worker_id: str | None
    lease_expires_at: datetime | None


class ComparisonRequestMutationResponse(_CamelModel):
    verdict: str
    request: dict[str, Any] | None = None
    detail: str | None = None


class ComparisonRequestListResponse(_CamelModel):
    requests: list[dict[str, Any]]


class PendingComparisonRequestView(_CamelModel):
    """워커가 다음에 잡을 후보 1건 — 최소 노출(``PendingProcessingJobView`` 와 동형).

    ``PROCESSING_WORK`` 는 ``MISSIONS_READ`` 를 포함하지 않으므로 임무·현장·
    비교 대상까지 여기서 드러내지 않는다. requestId 로 lease 를 잡은 다음에야
    ``/input`` 이 전체 사양을 준다.
    """

    request_id: str
    requested_at: datetime


class PendingComparisonRequestListResponse(_CamelModel):
    requests: list[PendingComparisonRequestView]


class ComparisonRequestTransitionRequest(_CamelModel):
    target_status: ProcessingJobStatus
    detail: str | None = None


class ComparisonRequestInputView(_CamelModel):
    """워커가 실제로 계산하는 데 필요한 것 — presigned GET URL + 그 산출물의 참조
    (모듈 docstring "워커가 원본을 읽는 유일한 경로").

    ``missionId`` 는 예외다 — ``PROCESSING_WORK`` 는 ``MISSIONS_READ`` 를 포함하지
    않지만, 워커가 계산 결과를 ``POST /v1/missions/{missionId}/change-detection``·
    ``/volume-changes`` 에 제출하려면 그 경로 파라미터가 필요하다.
    ``ProcessingJobStore`` 의 ``JobInput.mission_id``(재구성 워커가
    ``verify_source_media`` 를 부를 때 쓰는 것과 동일한 자리)와 같은 이유다 — "자기
    lease 를 쥔 이 요청 하나의" missionId 노출은 임의 임무 열람과 다르다.

    ``*Ref``(jobId+artifactId) 도 URL 과 함께 싣는다 — ``ChangeDetectionResult.
    baseline``/``current``, ``VolumeChangeReport.baseline``/``current`` 가
    ``ArtifactRef`` 타입이라, 워커가 계산 결과를 제출하려면 바이트뿐 아니라 그
    바이트가 **어느 (작업, 산출물)** 인지도 알아야 한다. 이 요청이 이미 가리키는
    산출물의 참조를 그대로 돌려주는 것이라 새로운 열람 범위가 아니다.

    ``status`` 도 싣는다 — ``ProcessingJobStore`` 의 ``JobInput.status`` 와 같은
    이유다: 워커가 ``QUEUED``→``RUNNING`` 전이를 시도해도 되는지(재개된 작업이면
    이미 ``RUNNING`` 이라 그 전이가 ``ILLEGAL_TRANSITION``)를 이 값으로만 안다.

    ``policy`` 는 이 요청이 생성될 때 굳어진 기준값이다 — 워커는 계산 함수의
    기본값이 아니라 **이 값**을 써야 한다. 그래야 원장에 적힌 스냅샷이 "실제로
    쓴 값"이 되고, 화면이 그 값을 표시하는 것이 거짓말이 아니게 된다.
    """

    request_id: str
    mission_id: str
    status: ProcessingJobStatus
    policy: ComparisonPolicy
    point_cloud_baseline: ArtifactRef | None
    point_cloud_baseline_url: str | None
    point_cloud_current: ArtifactRef | None
    point_cloud_current_url: str | None
    dsm_baseline: ArtifactRef | None
    dsm_baseline_url: str | None
    dsm_current: ArtifactRef | None
    dsm_current_url: str | None
    zones: dict[str, dict[str, Any]] | None
    zone_crs: str | None


class ComparisonRequestInputResponse(_CamelModel):
    verdict: str
    input: ComparisonRequestInputView | None = None
    detail: str | None = None


def _to_view(record: ComparisonRequestRecord) -> ComparisonRequestView:
    return ComparisonRequestView(
        request=record.to_contract().model_dump(by_alias=True, mode="json", exclude_none=False),
        lease_worker_id=record.lease.worker_id if record.lease is not None else None,
        lease_expires_at=record.lease.expires_at if record.lease is not None else None,
    )


def _presigned_url(
    storage: EvidenceStorage, *, site_id: str, job_id: str, artifact_id: str
) -> str:
    object_key = build_processing_artifact_object_key(
        site_id=site_id, job_id=job_id, artifact_id=artifact_id
    )
    return storage.presigned_get(object_key, ttl=DEFAULT_VIEW_TTL)


def build_comparison_requests_router(
    store: ComparisonRequestStore, storage: EvidenceStorage
) -> APIRouter:
    router = APIRouter(tags=["comparison-requests"])

    @router.get("/v1/comparison-policy", response_model=ComparisonPolicy)
    def get_comparison_policy(
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ComparisonPolicy:
        """이 배포가 실제 계산에 쓰는 기준값 — **읽기 전용**.

        화면이 제출 전에 "이 값으로 계산됩니다"를 보여주기 위한 표면이다. 화면에
        숫자를 복제하지 않는 이유는, 복제하는 순간 계산 쪽이 바뀌어도 화면은 옛
        숫자를 계속 말하고 **그 거짓말이 어느 화면에서도 보이지 않기** 때문이다.
        여기서 내려주는 값과 워커가 실제로 쓰는 값은 같은 모듈
        (``ksi_event_contracts.comparison_policy``)에서 나온다.

        바꾸는 표면은 없다(대표자 확정: 사용자가 화면에서 임계값을 입력하지
        않는다). 값 자체를 바꾸려면 그 모듈의 상수와 ``policyVersion`` 을 함께
        올리는 배포가 필요하다.
        """
        return current_comparison_policy()

    @router.post(
        "/v1/missions/{mission_id}/comparison-requests",
        response_model=ComparisonRequestMutationResponse,
        status_code=201,
    )
    def create_comparison_request(
        mission_id: str,
        request: ComparisonRequestCreateInput,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> ComparisonRequestMutationResponse:
        """"이 두 작업을 비교하라"는 지시 접수 — **사람이 발급**한다.

        결과(변화탐지·체적)를 계산해 제출하는 것은 워커(``PROCESSING_WORK``)의
        일이지만, "무엇과 무엇을 비교할지"를 지목하는 것은 재구성 발급과 같은
        사람의 결정이다(``MISSIONS_ISSUE`` — 재구성 작업 발급과 동일 권한).
        """
        result = store.create(
            mission_id,
            baseline_job_id=request.baseline_job_id,
            current_job_id=request.current_job_id,
            zones=request.zones,
            zone_crs=request.zone_crs,
            requested_by=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ComparisonRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ComparisonRequestMutationResponse(
            verdict=result.verdict.value,
            request=(
                result.record.to_contract().model_dump(
                    by_alias=True, mode="json", exclude_none=False
                )
                if result.record is not None
                else None
            ),
            detail=result.detail,
        )

    @router.get(
        "/v1/missions/{mission_id}/comparison-requests",
        response_model=ComparisonRequestListResponse,
    )
    def list_comparison_requests(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ComparisonRequestListResponse:
        """그 임무의 비교 요청 이력(최신 우선)."""
        return ComparisonRequestListResponse(
            requests=[
                r.to_contract().model_dump(by_alias=True, mode="json", exclude_none=False)
                for r in store.list_for_mission(mission_id)
            ]
        )

    @router.get(
        "/v1/comparison-requests",
        response_model=PendingComparisonRequestListResponse,
    )
    def list_pending_comparison_requests(
        limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
        _principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> PendingComparisonRequestListResponse:
        """워커가 다음에 잡을 후보 목록 — ``QUEUED`` + lease 만료된 ``RUNNING``,
        오래된 것부터(FIFO). ``GET /v1/processing-jobs`` 와 동형(최소권한 — 사람은
        이 표면을 쓰지 않는다)."""
        return PendingComparisonRequestListResponse(
            requests=[
                PendingComparisonRequestView(
                    request_id=r.request_id, requested_at=r.requested_at
                )
                for r in store.list_pending(now=datetime.now(UTC), limit=limit)
            ]
        )

    @router.get(
        "/v1/comparison-requests/{request_id}",
        response_model=ComparisonRequestView,
    )
    def get_comparison_request(
        request_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ComparisonRequestView:
        record = store.get(request_id)
        if record is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return _to_view(record)

    @router.post(
        "/v1/comparison-requests/{request_id}/lease",
        response_model=ComparisonRequestMutationResponse,
        status_code=201,
    )
    def acquire_comparison_request_lease(
        request_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ComparisonRequestMutationResponse:
        result = store.acquire_lease(
            request_id, worker_id=principal.principal_id, now=datetime.now(UTC)
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ComparisonRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ComparisonRequestMutationResponse(
            verdict=result.verdict.value,
            request=(
                result.record.to_contract().model_dump(
                    by_alias=True, mode="json", exclude_none=False
                )
                if result.record is not None
                else None
            ),
            detail=result.detail,
        )

    @router.get(
        "/v1/comparison-requests/{request_id}/input",
        response_model=ComparisonRequestInputResponse,
    )
    def get_comparison_request_input(
        request_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ComparisonRequestInputResponse:
        """워커가 baseline/current 산출물을 읽는 유일한 경로(모듈 docstring).

        lease 를 쥔 워커만 통과한다 — 상호배제와 접근범위 축소를 동시에 한다
        (``processing_jobs.get_processing_job_input`` 과 동일 원칙).
        """
        record = store.get(request_id)
        if record is None:
            response.status_code = 404
            return ComparisonRequestInputResponse(
                verdict=ComparisonRequestVerdict.UNKNOWN_REQUEST.value, detail=_NOT_FOUND_DETAIL
            )
        denied = ComparisonRequestStore._check_lease_locked(
            record, worker_id=principal.principal_id, now=datetime.now(UTC)
        )
        if denied is not None:
            verdict, detail = denied
            response.status_code = _STATUS[verdict]
            return ComparisonRequestInputResponse(verdict=verdict.value, detail=detail)

        try:
            pc_baseline_url = (
                _presigned_url(
                    storage,
                    site_id=record.site_id,
                    job_id=record.point_cloud_baseline.job_id,
                    artifact_id=record.point_cloud_baseline.artifact_id,
                )
                if record.point_cloud_baseline is not None
                else None
            )
            pc_current_url = (
                _presigned_url(
                    storage,
                    site_id=record.site_id,
                    job_id=record.point_cloud_current.job_id,
                    artifact_id=record.point_cloud_current.artifact_id,
                )
                if record.point_cloud_current is not None
                else None
            )
            dsm_baseline_url = (
                _presigned_url(
                    storage,
                    site_id=record.site_id,
                    job_id=record.dsm_baseline.job_id,
                    artifact_id=record.dsm_baseline.artifact_id,
                )
                if record.dsm_baseline is not None
                else None
            )
            dsm_current_url = (
                _presigned_url(
                    storage,
                    site_id=record.site_id,
                    job_id=record.dsm_current.job_id,
                    artifact_id=record.dsm_current.artifact_id,
                )
                if record.dsm_current is not None
                else None
            )
        except EvidenceStorageError:
            logger.warning("비교 입력 URL 발급 실패: requestId=%s", request_id)
            response.status_code = _STATUS[ComparisonRequestVerdict.STORAGE_UNAVAILABLE]
            response.headers["Retry-After"] = "30"
            return ComparisonRequestInputResponse(
                verdict=ComparisonRequestVerdict.STORAGE_UNAVAILABLE.value,
                detail="산출물 다운로드 URL 발급에 실패했다 — 잠시 후 재시도한다",
            )

        return ComparisonRequestInputResponse(
            verdict=ComparisonRequestVerdict.INPUT_READY.value,
            input=ComparisonRequestInputView(
                request_id=request_id,
                mission_id=record.mission_id,
                status=record.status,
                policy=record.policy,
                point_cloud_baseline=record.point_cloud_baseline,
                point_cloud_baseline_url=pc_baseline_url,
                point_cloud_current=record.point_cloud_current,
                point_cloud_current_url=pc_current_url,
                dsm_baseline=record.dsm_baseline,
                dsm_baseline_url=dsm_baseline_url,
                dsm_current=record.dsm_current,
                dsm_current_url=dsm_current_url,
                zones=record.zones,
                zone_crs=record.zone_crs,
            ),
        )

    @router.post(
        "/v1/comparison-requests/{request_id}/transitions",
        response_model=ComparisonRequestMutationResponse,
    )
    def transition_comparison_request(
        request_id: str,
        request: ComparisonRequestTransitionRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ComparisonRequestMutationResponse:
        """워커만 전이한다 — RUNNING/SUCCEEDED/FAILED 는 계산을 실제로 돌린 주체만
        아는 사실이다(사람이 손으로 결과를 주장할 수 없다는 것과 같은 원칙,
        모듈 docstring). W2 는 CANCELLED 를 다루지 않는다."""
        result = store.transition(
            request_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ComparisonRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ComparisonRequestMutationResponse(
            verdict=result.verdict.value,
            request=(
                result.record.to_contract().model_dump(
                    by_alias=True, mode="json", exclude_none=False
                )
                if result.record is not None
                else None
            ),
            detail=result.detail,
        )

    return router


def mount_comparison_requests(
    app: FastAPI, store: ComparisonRequestStore, storage: EvidenceStorage
) -> None:
    app.include_router(build_comparison_requests_router(store, storage))


__all__ = [
    "ComparisonRequestCreateInput",
    "ComparisonRequestInputResponse",
    "ComparisonRequestInputView",
    "ComparisonRequestListResponse",
    "ComparisonRequestMutationResponse",
    "ComparisonRequestRecord",
    "ComparisonRequestRecoveryError",
    "ComparisonRequestResult",
    "ComparisonRequestStore",
    "ComparisonRequestTransitionRequest",
    "ComparisonRequestVerdict",
    "ComparisonRequestView",
    "IllegalComparisonTransitionError",
    "PendingComparisonRequestListResponse",
    "PendingComparisonRequestView",
    "assert_comparison_transition",
    "build_comparison_request_id",
    "build_comparison_requests_router",
    "mount_comparison_requests",
]
