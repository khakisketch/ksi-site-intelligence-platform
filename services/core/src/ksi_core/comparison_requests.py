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

:class:`~ksi_core.leasing.JobLease` 와 그 판정 순수 함수(``check_lease``·
``is_claimable``·``next_lease``)를 그대로 import 해서 쓴다 —
``ProcessingJobStore`` 와 동일한 lease 프로토콜이라, 소유권 검사와
``list_pending`` 의 "QUEUED + lease 만료된 RUNNING" 필터를 여기서 다시
구현하지 않는다(P1-2). store 클래스 자체는 합치지 않는다 — 레코드 타입·
전이표(``CANCELLED`` 유무)가 다르고, journal append·verdict 번역은 각
store 의 도메인 책임으로 남는다.

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

## 즉석 폴리곤도 등록된 작업구역과 같은 검사를 받는다

``zones`` 는 등록을 거치지 않고 요청에 직접 실리는 값이라, 작업구역
(``WorkArea``) 계약이 강제하는 기하 검사가 이 경로엔 저절로 따라오지 않는다.
:func:`assert_zones_are_usable` 이 그 검사를 여기서도 강제한다(2026-08-13
프로젝트 두뇌 재감사 확정 발견 — 이 검사 없이는 Point·안 닫힌 고리·글자
좌표까지 그대로 durable 저널에 실려, 실패 사유를 워커가 몇 분 뒤 이해할 수
없는 예외로 대신 말했다). ``design_conformance_requests.py`` 가 이 함수를
그대로 재사용한다 — 두 경로가 각자 검사를 복제하면 한쪽만 고쳐지는 순간
갈라진다.
"""

from __future__ import annotations

import json
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
from ksi_event_contracts.vertical_reference import VerticalReference
from ksi_event_contracts.work_area import assert_polygon_is_usable
from pydantic import Field

from ksi_core.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.auth import (
    Permission,
    Principal,
    current_request_organization_id,
    require_permission,
)
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import DEFAULT_VIEW_TTL, EvidenceStorage, EvidenceStorageError
from ksi_core.leasing import JobLease, LeaseDenialReason, check_lease, is_claimable, next_lease
from ksi_core.metrics import COMPARISON_REQUEST_TRANSITIONS
from ksi_core.processing_jobs import (
    DEFAULT_LEASE_TTL,
    ProcessingJobRecord,
    ProcessingJobStore,
    build_processing_artifact_object_key,
)
from ksi_core.work_areas import MAX_ACTIVE_WORK_AREAS

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_records import MissionStore

logger = logging.getLogger(__name__)

_NOT_FOUND_DETAIL = "해당 비교 요청을 찾을 수 없다"
_STORE_UNAVAILABLE_DETAIL = JOURNAL_SEALED_DETAIL

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
    #: 즉석 구역(zones)의 폴리곤을 쓸 수 없다 — 타입·닫힘·좌표·개수 상한 중 하나를
    #: 어겼다. 워커까지 보내지 않고 여기서 사람 말로 거부한다.
    ZONES_INVALID = "ZONES_INVALID"
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
    ComparisonRequestVerdict.ZONES_INVALID: 422,
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


def zone_fingerprint(
    zones: dict[str, dict[str, Any]] | None, zone_crs: str | None
) -> str:
    """구역 한 벌을 멱등 판정용 문자열 하나로 — 같은 구역이면 같은 값이 나온다.

    ``design_conformance_requests`` 도 같은 멱등 규칙을 쓴다(구역이 지시의
    일부라는 판단이 두 요청 종류에서 동일하다) — 그래서 private 이 아니다.
    복제하면 한쪽 정규화만 바뀌는 날 같은 재전송이 한쪽에서만 중복 요청을 만든다.

    ``json.dumps(sort_keys=True)`` 를 쓰는 이유는 dict 순서가 요청마다 달라질 수
    있어서다(브라우저·프록시가 키 순서를 보장하지 않는다). 좌표는 float 이라
    표현이 흔들릴 수 있지만, 같은 화면이 만든 같은 폴리곤이면 같은 바이트로
    직렬화된다 — 여기서 재시도 멱등을 판단하는 데는 그 정도면 충분하다(다르게
    나오면 새 요청이 생길 뿐, 잘못된 결과가 나오지는 않는다).
    """
    if not zones:
        return "-"
    return json.dumps([zone_crs, zones], sort_keys=True, ensure_ascii=False)


#: 즉석(zones) 요청 한 건이 한 번에 실을 수 있는 구역 수 상한. 등록된 작업구역의
#: ``MAX_ACTIVE_WORK_AREAS``(work_areas.py)를 그대로 재사용한다 — 리터럴을
#: 복제하면 한쪽만 바뀌는 날 두 상한이 말없이 갈린다. 값이 같은 이유도 하나다 —
#: 구역마다 워커가 래스터 마스킹을 한 번씩 돌므로, 상한 없이 두면 요청 하나가
#: 워커를 임의로 오래 붙잡는다.
MAX_AD_HOC_ZONES = MAX_ACTIVE_WORK_AREAS


def assert_zones_are_usable(zones: dict[str, dict[str, Any]], *, zone_crs: str) -> str | None:
    """즉석 폴리곤이 래스터 마스킹까지 살아남을 수 있는가 — 아니면 사람이 읽는 사유.

    ``design_conformance_requests`` 도 이 함수를 그대로 쓴다(``zone_fingerprint``
    와 같은 이유로 private 이 아니다). 등록된 작업구역은 ``WorkArea`` 계약이
    ``assert_polygon_is_usable`` 을 이미 강제하는데, 즉석 경로는 등록을 거치지
    않아 그 검사가 저절로 따라오지 않는다 — 여기서 같은 검사를 명시적으로
    적용하지 않으면 "등록된 구역은 안전하고 즉석 구역은 아니다"라는 갈라진
    보장이 생긴다.
    """
    if len(zones) > MAX_AD_HOC_ZONES:
        return (
            f"구역이 {len(zones)}개다 — 즉석 구역은 한 번에 {MAX_AD_HOC_ZONES}개까지만 "
            "받는다(구역마다 워커가 래스터 마스킹을 한 번씩 돈다). 반복해서 재는 범위는 "
            "작업구역으로 등록하면 상한 없이 여러 시점에 쓸 수 있다"
        )
    for zone_id, polygon in zones.items():
        try:
            assert_polygon_is_usable(polygon, crs=zone_crs)
        except ValueError as exc:
            return f"구역 {zone_id!r} 의 폴리곤을 쓸 수 없다 — {exc}"
    return None


def _request_shape(record: ComparisonRequestRecord) -> tuple[str, str, str]:
    """멱등 판정 키 — **무엇을 어느 범위로 비교하라는 지시인가**.

    예전에는 ``(baselineJobId, currentJobId)`` 뿐이었다. 그러면 구역 없이 한 번
    요청한 조합은 나중에 구역을 확정해 다시 제출해도 옛 요청(구역 없음, 이미
    SUCCEEDED)이 그대로 돌아와 **그 두 시점의 부피 비교를 영영 받을 수 없었다**
    — 화면이 "구역이나 시점을 바꿔 다시 요청할 수 있다"고 안내하는 것과도
    어긋났다. 구역이 지시의 일부이므로 키에 넣는다.

    임무·현장은 넣지 않는다 — jobId 가 이미 그것들을 결정한다(``_resolve`` 가
    같은 현장·같은 임무를 강제한다).
    """
    return (
        record.baseline_job_id,
        record.current_job_id,
        zone_fingerprint(record.zones, record.zone_crs),
    )


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


_iso = iso_utc


def _find_artifact(
    job: ProcessingJobRecord, kind: ProcessingArtifactKind
) -> ProcessingArtifact | None:
    return next((a for a in job.artifacts if a.kind is kind), None)


def _ref_or_none(job_id: str, artifact: ProcessingArtifact | None) -> ArtifactRef | None:
    """산출물이 있으면 그 (작업, 산출물) 참조를, 없으면 None을 만든다."""
    return ArtifactRef(job_id=job_id, artifact_id=artifact.artifact_id) if artifact else None


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
        self._by_request_shape: dict[tuple[str, str, str], str] = {}
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

    def _visible_in_request(self, record: ComparisonRequestRecord) -> bool:
        """HTTP 조직 문맥에서만 Mission lineage로 이 요청을 숨긴다.

        비교 요청은 자체 organizationId를 복제하지 않는다. Mission 원장이 사실의
        권위이므로, 기존 MissionStore의 request scope를 재사용한다(INV-060).
        재생·신뢰된 내부 작업에는 문맥이 없어 기존 전체 원장 동작을 유지한다.
        """

        return (
            current_request_organization_id() is None
            or self._mission_store.get(record.mission_id) is not None
        )

    def mission_is_visible(self, mission_id: str) -> bool:
        """라우터가 foreign/unknown mission을 같은 404로 다룰 공개 관문."""

        return self._mission_store.get(mission_id) is not None

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
        self._by_request_shape[_request_shape(record)] = record.request_id

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

        if zones and zone_crs is not None:
            zones_error = assert_zones_are_usable(zones, zone_crs=zone_crs)
            if zones_error is not None:
                return (ComparisonRequestVerdict.ZONES_INVALID, zones_error, None)

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
                point_cloud_baseline=_ref_or_none(baseline_job_id, pc_baseline),
                point_cloud_current=_ref_or_none(current_job_id, pc_current),
                change_detection_eligible=cd_eligible,
                change_detection_ineligible_reason=cd_reason,
                dsm_baseline=_ref_or_none(baseline_job_id, dsm_baseline),
                dsm_current=_ref_or_none(current_job_id, dsm_current),
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

            verdict, detail, resolved = self._resolve(
                mission_id=mission_id,
                baseline_job_id=baseline_job_id,
                current_job_id=current_job_id,
                zones=zones,
                zone_crs=zone_crs,
            )
            if verdict is not ComparisonRequestVerdict.CREATED or resolved is None:
                return ComparisonRequestResult(verdict, detail=detail)

            # 멱등 판정은 **_resolve 뒤**다. _resolve 가 zones 를 정규화하기
            # 때문이다(부피가 비적격이면 zones 를 떨군다) — 요청 원문으로 키를
            # 만들면 그 키가 레코드에 저장될 모양과 달라져, 재기동 후 _project
            # 가 만든 키와 어긋나고 같은 재전송이 중복 요청을 만든다.
            #
            # 순서를 뒤로 미룬 대가: 이미 요청된 조합인데 그 사이 작업이 사라진
            # 경우 ALREADY_REQUESTED 대신 UNKNOWN_JOB 이 나온다. 그게 더 사실에
            # 가깝다 — 지금 그 조합은 실제로 비교할 수 없다.
            existing_id = self._by_request_shape.get(
                (
                    baseline_job_id,
                    current_job_id,
                    zone_fingerprint(resolved.zones, resolved.zone_crs),
                )
            )
            if existing_id is not None:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.ALREADY_REQUESTED,
                    detail="같은 조합(baselineJobId+currentJobId+구역)의 요청이 이미 있다",
                    record=self._requests[existing_id],
                )

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
                "ts": iso_utc(now),
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
            record = self._requests.get(request_id)
        return record if record is not None and self._visible_in_request(record) else None

    def vertical_reference_of(self, ref: ArtifactRef | None) -> VerticalReference | None:
        """그 산출물이 등록 시 선언한 수직기준 — 없으면 ``None``.

        요청 레코드에 복사해 두지 않고 **입력 발급 시점에 조회**한다(presigned
        URL 과 같은 자리·같은 이유): 요청 계약(``ComparisonRequest``)은 "무엇을
        비교하라"는 지시이고 수직기준은 그 지시가 아니라 **산출물의 성질**이다.
        지시에 복사해 두면 산출물 쪽 사실과 두 벌이 되고, 옛 요청은 필드가
        없어 계약이 또 한 세대 갈라진다.

        ``None`` 인 경우는 둘이다 — 수직기준이 기록되기 전에 등록된 산출물,
        그리고 v1.2 를 아는 생산자가 명시적으로 "모른다"고 밝힌 경우. 여기서
        둘을 가르지 않는다(소비자는 어느 쪽이든 '미상'으로 다뤄야 한다).
        어떤 기본값도 채우지 않는다 — Core 는 산출물 바이트를 읽지 않아 이
        값을 확인할 수 없고, 대신 주장하면 그 가정 위에서 숫자가 나온다.
        """
        if ref is None:
            return None
        job = self._processing_job_store.get(ref.job_id)
        if job is None:
            return None
        artifact = next((a for a in job.artifacts if a.artifact_id == ref.artifact_id), None)
        return artifact.vertical_reference if artifact is not None else None

    def checkpoint_rmse_of(self, ref: ArtifactRef | None) -> float | None:
        """그 산출물이 등록 시 신고한 **독립 검사점 잔차**(m) — 없으면 ``None``.

        ``vertical_reference_of`` 와 같은 관례(요청 레코드에 복사하지 않고 입력
        발급 시점에 조회, 기본값을 채우지 않음)다.

        **``accuracy.rmse`` 는 절대 반환하지 않는다** — 그것은 GCP 피팅 잔차이지
        절대정확도가 아니다(INV-024). 여기서 그 값을 흘리면 "검증 없는 수치가
        진짜 오차한계처럼 실리는" 위반을 이 배선이 그대로 재도입한다. 워커의
        오차한계 계산(``dsm_diff._uncertainty_m3``)이 받을 자격이 있는 값은
        ``checkpoint_rmse_m`` 하나뿐이다.
        """
        if ref is None:
            return None
        job = self._processing_job_store.get(ref.job_id)
        if job is None:
            return None
        artifact = next((a for a in job.artifacts if a.artifact_id == ref.artifact_id), None)
        if artifact is None or artifact.accuracy is None:
            return None
        return artifact.accuracy.checkpoint_rmse_m

    def list_for_mission(self, mission_id: str) -> list[ComparisonRequestRecord]:
        if (
            current_request_organization_id() is not None
            and self._mission_store.get(mission_id) is None
        ):
            return []
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
                r for r in self._requests.values() if is_claimable(r.status, r.lease, now)
            ]
        if current_request_organization_id() is not None:
            records = [r for r in records if self._visible_in_request(r)]
        ordered = sorted(records, key=lambda r: (r.requested_at, r.request_id))
        return ordered[:limit]

    @staticmethod
    def _check_lease_locked(
        record: ComparisonRequestRecord, *, worker_id: str, now: datetime
    ) -> tuple[ComparisonRequestVerdict, str] | None:
        denial = check_lease(record.lease, worker_id=worker_id, now=now)
        if denial is LeaseDenialReason.MISSING_OR_EXPIRED:
            return (
                ComparisonRequestVerdict.LEASE_REQUIRED,
                "이 요청의 lease 를 먼저 잡아야 한다",
            )
        if denial is LeaseDenialReason.HELD_BY_ANOTHER:
            assert record.lease is not None  # HELD_BY_ANOTHER only when a lease exists
            return (
                ComparisonRequestVerdict.LEASE_HELD_BY_ANOTHER,
                f"다른 워커({record.lease.worker_id})가 {iso_utc(record.lease.expires_at)} 까지 "
                "이 요청을 쥐고 있다 — 만료 후 다시 시도한다",
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
            if record is None or not self._visible_in_request(record):
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            if record.status not in _ACTIVE_STATUSES:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.REQUEST_NOT_ACTIVE,
                    detail=f"요청이 {record.status.value} 상태다 — 끝난 요청은 잡을 수 없다",
                )
            current = record.lease
            denial = check_lease(current, worker_id=worker_id, now=now)
            renewing = current is not None and denial is None
            if denial is LeaseDenialReason.HELD_BY_ANOTHER:
                assert current is not None  # HELD_BY_ANOTHER only when a lease exists
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.LEASE_HELD_BY_ANOTHER,
                    detail=(
                        f"다른 워커({current.worker_id})가 {iso_utc(current.expires_at)} 까지 "
                        "이 요청을 쥐고 있다 — 만료 후 다시 시도한다"
                    ),
                    record=record,
                )
            new_lease = next_lease(
                worker_id=worker_id,
                now=now,
                ttl=ttl,
                granted_at=current.granted_at if renewing and current else None,
            )
            raw = {
                "kind": "comparison-request-leased",
                "ts": iso_utc(now),
                "requestId": request_id,
                "workerId": worker_id,
                "expiresAt": iso_utc(new_lease.expires_at),
                "renewal": renewing,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ComparisonRequestResult(
                    ComparisonRequestVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            updated = replace(record, lease=new_lease)
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
            if record is None or not self._visible_in_request(record):
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
                "ts": iso_utc(now),
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
            # processing_jobs.py 의 같은 위치와 동일 근거 — 성공한 전이만 센다.
            COMPARISON_REQUEST_TRANSITIONS.inc(target_status=target.value)
            return ComparisonRequestResult(ComparisonRequestVerdict.TRANSITIONED, record=updated)


def _require_aware_iso(raw: Any, field_name: str, request_id: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ComparisonRequestRecoveryError(
            f"재생: {field_name} 이 tz-naive 다 — requestId={request_id}"
        )
    return value


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class ComparisonRequestCreateInput(CamelModel):
    """요청 생성 본문 — **무엇을 비교할지**만 정한다.

    구역은 site.aoi 를 자동으로 쓰지 않는다(모듈 docstring) — 대시보드가
    사용자 확인을 거친 폴리곤 값을 여기 싣는다. 생략하면(None) 체적 비교는
    시도되지 않는다(점군 비교는 zones 없이도 가능하면 시도된다).
    """

    baseline_job_id: str = Field(min_length=1)
    current_job_id: str = Field(min_length=1)
    zones: dict[str, dict[str, Any]] | None = None
    zone_crs: str | None = None


class ComparisonRequestView(CamelModel):
    """비교 요청 1건의 조회 표현 — 계약 payload + 운영 메타."""

    request: dict[str, Any]
    lease_worker_id: str | None
    lease_expires_at: datetime | None


class ComparisonRequestMutationResponse(CamelModel):
    verdict: str
    request: dict[str, Any] | None = None
    detail: str | None = None


class ComparisonRequestListResponse(CamelModel):
    requests: list[dict[str, Any]]


class PendingComparisonRequestView(CamelModel):
    """워커가 다음에 잡을 후보 1건 — 최소 노출(``PendingProcessingJobView`` 와 동형).

    ``PROCESSING_WORK`` 는 ``MISSIONS_READ`` 를 포함하지 않으므로 임무·현장·
    비교 대상까지 여기서 드러내지 않는다. requestId 로 lease 를 잡은 다음에야
    ``/input`` 이 전체 사양을 준다.
    """

    request_id: str
    requested_at: datetime


class PendingComparisonRequestListResponse(CamelModel):
    requests: list[PendingComparisonRequestView]


class ComparisonRequestTransitionRequest(CamelModel):
    target_status: ProcessingJobStatus
    detail: str | None = None


class ComparisonRequestInputView(CamelModel):
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
    #: 두 DSM 산출물이 등록 시 선언한 수직기준 — ``VolumeChangeReport.
    #: verticalDatum`` 에 실릴 값의 **출처**다. 워커가 상수를 가정하던 자리를
    #: 산출물의 사실로 바꾼다. ``None`` 은 '미상'이고(수직기준이 기록되기 전에
    #: 등록된 산출물 등) Core 는 그 자리를 채우지 않는다 —
    #: :meth:`ComparisonRequestStore.vertical_reference_of` docstring 참조.
    #: 점군 쪽에 같은 필드가 없는 이유는 ``ChangeDetectionResult`` 에 수직기준
    #: 필드가 없어서다(쓰이지 않을 값을 워커까지 실어 나르지 않는다).
    #: 기본값을 두지 않는다 — 이 뷰의 다른 nullable 필드와 같은 관례이고, 새
    #: 응답 경로가 생겼을 때 "안 채우면 조용히 null" 이 되지 않게 한다.
    dsm_baseline_vertical_reference: VerticalReference | None
    dsm_current_vertical_reference: VerticalReference | None
    #: 각 DSM 이 등록 시 신고한 독립 검사점 잔차(m) — ``checkpoint_rmse_of`` 참조.
    #: ``None`` 이면 그 epoch 은 검증되지 않았고, 워커의 오차한계도 ``None`` 이
    #: 된다(INV-024 — 한쪽만 알면 차분의 오차를 말할 수 없다).
    dsm_baseline_checkpoint_rmse_m: float | None
    dsm_current_checkpoint_rmse_m: float | None


class ComparisonRequestInputResponse(CamelModel):
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


def _presigned_url_or_none(
    storage: EvidenceStorage, *, site_id: str, ref: ArtifactRef | None
) -> str | None:
    """참조가 있으면 그 산출물의 열람 URL을, 없으면 None을 만든다."""
    if ref is None:
        return None
    return _presigned_url(storage, site_id=site_id, job_id=ref.job_id, artifact_id=ref.artifact_id)


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
        if not store.mission_is_visible(mission_id):
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
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
            pc_baseline_url = _presigned_url_or_none(
                storage, site_id=record.site_id, ref=record.point_cloud_baseline
            )
            pc_current_url = _presigned_url_or_none(
                storage, site_id=record.site_id, ref=record.point_cloud_current
            )
            dsm_baseline_url = _presigned_url_or_none(
                storage, site_id=record.site_id, ref=record.dsm_baseline
            )
            dsm_current_url = _presigned_url_or_none(
                storage, site_id=record.site_id, ref=record.dsm_current
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
                dsm_baseline_vertical_reference=store.vertical_reference_of(record.dsm_baseline),
                dsm_current_vertical_reference=store.vertical_reference_of(record.dsm_current),
                dsm_baseline_checkpoint_rmse_m=store.checkpoint_rmse_of(record.dsm_baseline),
                dsm_current_checkpoint_rmse_m=store.checkpoint_rmse_of(record.dsm_current),
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
    "zone_fingerprint",
]
