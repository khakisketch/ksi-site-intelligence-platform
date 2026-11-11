"""3D 재구성 처리 작업의 역사 replay·read projection (ADR-KSI-012, INV-050).

Core 는 더 이상 처리 작업을 **발급·전이·lease·산출물 등록하지 않는다**
(Task 2 retirement): ``issue``·``transition``·``acquire_lease``·
``artifact_upload_target``·``register_artifact``·``input_for``·
``verify_input``·``list_pending`` 과 실행용 constructor 옵션, 실행 profile /
resource-policy catalog 라우터는 제거됐다. 저장소 이름은 유지하되 역할은
역사 replay/read projection 으로 한정한다.

남는 표면:

- journal replay(``_replay`` + ``_replay_issued`` / ``_replay_transition`` /
  ``_replay_artifact`` / ``_replay_upload_grant`` / ``_replay_lease``) —
  오염된 원장으로 기동하지 않는다(fail-closed).
- 권한 있는 역사 조회 GET — 임무별 목록·현장별 목록·단건 상세·산출물
  다운로드. managed POST / worker mutation / pending queue / profile catalog /
  resource-policy catalog 는 존재하지 않는다.
- 읽기 전용 판정 공유 — :func:`assert_job_transition` (전이표 SSOT),
  :func:`assert_succeeded_is_backed` (INV-051), :func:`authoritative_artifacts`,
  ``spatial_model``·checkpoint 검증·비교·물량·설계 분석이 쓰는
  ``get`` / ``list_for_site`` / ``resolve_artifact`` / ``is_input_verified``.

## manifest-aware SUCCEEDED replay 는 실행용 registry 를 조회하지 않는다

과거에는 ``_assert_profile_required_artifacts`` 가 live
``ProcessingProfileRegistry`` 를 조회했다. 지금은 replay 전용 불변 사실
(:mod:`ksi_core.domains.processing.historical_processing_profiles`)만 본다 —
``(과거 profile ID, 과거 digest) -> 필수 산출물 종류``. 이미지·엔진 버전·
실행 매개변수·발급 함수는 없다. 미등록/변조 digest, 누락 산출물,
manifest·fence 불일치는 계속 fail-closed 다. profile binding 이 없는 역사
레코드(``LEGACY_UNMANAGED``)는 그대로 재생된다 — "absence is a durable
historical fact".

## ``SUCCEEDED`` 는 근거 둘이 있어야 주장된다 (INV-051, replay 에서 유지)

``RUNNING → SUCCEEDED`` 기록은 ① ``lineage.authority=source`` 산출물 최소
1건과 ② 그 작업이 고정한 digest 에 대한 원본 번들 실측 대조를 요구한다
(:func:`assert_succeeded_is_backed`). 재생도 live 와 같은 게이트를 다시
태운다 — 산출물 레코드를 지우고 ``SUCCEEDED`` 전이만 남겨 근거 없는 성공을
되살릴 수 없다.

## 전이표는 상태 기계의 모양만 정한다

``QUEUED → RUNNING → SUCCEEDED|FAILED`` · ``QUEUED|RUNNING → CANCELLED``.
종료 상태에서 나가는 전이는 없다. 재생도 같은 전이표를 다시 태운다
(``sites._apply_transitioned`` 와 동일 원칙): journal 을 손으로 고쳐 FAILED 를
SUCCEEDED 로 바꿀 수 없다.

## 이 모듈이 다루지 않는 것

- **발급·실행·워커 표면.** 전부 제거됐다 — 이 모듈에 쓰기 경로는 journal
  replay (기동 시 1회)뿐이다.
- **산출물 바이트 자체.** 다운로드 GET 은 원장에 있는 것만 내준다.
  ``digest``·``format`` 의 진위는 이 모듈이 보증하지 않는다 — 강제하는 것은
  **계보의 무결성**이다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_domain.signed_payload import canonical_payload_bytes, sha256_digest
from ksi_event_contracts.processing_artifact import (
    LineageAuthority,
    ProcessingArtifact,
    ProcessingArtifactKind,
    processing_artifact_wire_dict,
)
from ksi_event_contracts.processing_job import (
    Billing,
    DataResidency,
    ExecutionLocus,
    LicenseBasis,
    ProcessingInput,
    ProcessingJob,
    ProcessingJobStatus,
    ProcessingProvider,
    processing_job_wire_dict,
)
from ksi_event_contracts.processing_resource_policy import (
    ProcessingResourcePolicyV1,
)

from ksi_core.domains.artifacts.artifact_manifest import (
    ArtifactManifestError,
    ArtifactObjectBinding,
    AuthoritativeArtifactManifestV1,
    CandidateArtifact,
)
from ksi_core.domains.artifacts.evidence import (
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
    expires_at,
    is_valid_artifact_id,
)
from ksi_core.domains.artifacts.source_media import (
    CaptureWindow,
    CaptureWindowView,
    SourceMediaRecord,
    capture_window_from_wire,
)
from ksi_core.domains.processing.historical_processing_profiles import (
    UnknownHistoricalProcessingProfileError,
    historical_required_artifacts,
)
from ksi_core.foundation.api_base import CamelModel
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.foundation.leasing import (
    JobLease,
    LeaseFence,
    LeaseMode,
    check_lease,
    next_lease,
)
from ksi_core.identity.auth import (
    Permission,
    Principal,
    current_request_organization_id,
    require_permission,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.artifacts.source_media import SourceMediaStore
    from ksi_core.domains.sites.sites import SiteStore

logger = logging.getLogger("ksi_core.processing_jobs")

_NOT_FOUND_DETAIL = "해당 처리 작업을 찾을 수 없다"

# 발급 시점 billing 의 rateBasis. "아직 재지 않았다"를 값 자체가 말한다 —
# creditsCharged=0 만으로는 온프렘 무료 실행과 구분되지 않는다.
UNMETERED_AT_ISSUE = "unmetered-at-issue"

_ACTIVE_STATUSES = frozenset({ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING})

# 상태 전이표 — 계약(processing_job.py)이 "범위 밖"으로 미뤄둔 규칙의 SSOT.
_ALLOWED_TRANSITIONS: dict[ProcessingJobStatus, frozenset[ProcessingJobStatus]] = {
    ProcessingJobStatus.QUEUED: frozenset(
        {ProcessingJobStatus.RUNNING, ProcessingJobStatus.CANCELLED}
    ),
    ProcessingJobStatus.RUNNING: frozenset(
        {
            ProcessingJobStatus.SUCCEEDED,
            ProcessingJobStatus.FAILED,
            ProcessingJobStatus.CANCELLED,
        }
    ),
    ProcessingJobStatus.SUCCEEDED: frozenset(),
    ProcessingJobStatus.FAILED: frozenset(),
    ProcessingJobStatus.CANCELLED: frozenset(),
}


class IllegalJobTransitionError(ValueError):
    """전이표에 없는 처리 작업 상태 전이."""


class UnbackedSuccessError(ValueError):
    """산출물 없이 ``SUCCEEDED`` 를 주장했다(INV-051)."""


# INV-051 — authority=source 를 주장할 수 있는 kind 의 닫힌 집합.
#
# ``ArtifactLineage``(event-contracts, processing_artifact.py)는 의도적으로
# kind 와 authority 를 계약 레벨에서 묶지 않는다 — "향후 provider별 예외(예:
# 어떤 엔진이 point_cloud 를 다른 원본에서 재생성하는 경로)를 스키마 레벨에서
# 미리 봉인하지 않기 위해서"다(같은 모듈 docstring). 그 결과 계약만으로는
# ``kind=mesh, authority=source`` 같은 산출물도 통과한다 — 파생 산출물(메시·
# 정사영상·DSM/DTM·3D Tiles·리포트)이 원본 권위를 자칭할 수 있다는 뜻이다.
#
# ADR-KSI-003 은 Point Cloud/카메라 포즈가 원본 SSOT 라고 정했고, ODM 어댑터
# (``ksi_processing_controller.odm_assets.ODM_ASSETS``)의 실제 파이프라인
# 계보도 이 둘만 ``authority=SOURCE`` 로 등록한다 — 나머지는 전부 파생이다.
# 이 게이트는 그 사실을 Core 쪽에서도 강제한다: ``SUCCEEDED`` 를 받치는
# source 산출물은 **이 집합에 속하는 kind** 여야 한다. 지금은 이 저장소
# 로컬의 상수일 뿐이다 — provider 가 늘어나 예외가 생기면 계약 레벨 enum
# (예: ``ProcessingArtifactKind`` 에 "source-eligible" 플래그)으로 승격하는
# 편이 나을 수 있다(judgmentCallFlag 참고).
SOURCE_ELIGIBLE_ARTIFACT_KINDS: frozenset[ProcessingArtifactKind] = frozenset(
    {ProcessingArtifactKind.POINT_CLOUD, ProcessingArtifactKind.CAMERA_POSES}
)


def assert_succeeded_is_backed(
    target: ProcessingJobStatus,
    artifacts: Sequence[ProcessingArtifact],
    *,
    input_verified: bool,
) -> None:
    """``SUCCEEDED`` 는 **읽은 입력**과 **원본 산출물** 둘 다 있어야 성립한다.

    전이표(:func:`assert_job_transition`)와 **별개의** 게이트다 — 전이표는 상태
    기계의 모양을 정하고 이 함수는 그 상태를 주장할 근거가 원장에 있는지를
    본다. live 경로와 재생 경로가 같은 함수를 쓴다(전이표와 같은 이유).

    **산출물(authority=source, kind 이 source-eligible).** 파생물만 있는 성공은
    원본 없이 파생을 주장하는 상태다(ADR-KSI-003, 모듈 docstring). 계약
    (``ArtifactLineage``)은 kind 와 authority 를 의도적으로 묶지 않으므로,
    ``authority=source`` 만 보면 메시·정사영상 같은 파생 kind 가 원본을
    자칭해도 통과한다 — 그래서 여기서 kind 도 함께
    본다(:data:`SOURCE_ELIGIBLE_ARTIFACT_KINDS`, INV-051).

    **입력 검증.** 재구성을 실제로 돌린 워커는 정의상 전 바이트를 읽었으므로
    무엇을 읽었는지 보고할 수 있다. 그 보고 없이 성공을 인정하면 과금 근거
    (``totalMegapixels``)가 끝까지 업로더의 신고값으로 남는다 — 성공 시점이
    그 값이 마지막으로 고쳐질 수 있는 지점이다.

    ``FAILED``·``CANCELLED`` 에는 걸리지 않는다 — 신고값이 거짓이어서 처리가
    깨진 경우 그 작업은 실패로 끝나야지, 검증 못 해서 영구히 못 끝내는 상태에
    갇히면 안 된다.
    """
    if target is not ProcessingJobStatus.SUCCEEDED:
        return
    if not any(
        a.lineage.authority is LineageAuthority.SOURCE and a.kind in SOURCE_ELIGIBLE_ARTIFACT_KINDS
        for a in artifacts
    ):
        raise UnbackedSuccessError(
            "INV-051 — 이 작업에는 authority=source 산출물이 없다. 재구성이 "
            "성공했다면 원본(포인트클라우드·카메라 포즈 계열) 산출물이 최소 "
            "1건 등록돼 있어야 한다 — 파생물만으로는, 그리고 kind 가 원본으로 "
            "인정되지 않는 산출물(mesh·ortho·dsm·dtm·tiles_3d·report)만으로는 "
            "완료를 주장할 수 없다"
        )
    if not input_verified:
        raise UnbackedSuccessError(
            "이 작업의 원본 번들이 아직 실측 대조되지 않았다 — 전 바이트를 읽어 "
            "sha256·해상도를 신고값과 대조한 보고(POST /v1/missions/{id}/"
            "source-media/verify)가 있어야 성공으로 인정한다. 대조 없이 성공하면 "
            "과금 근거가 끝까지 업로더 신고값으로 남는다"
        )


def assert_job_transition(before: ProcessingJobStatus, after: ProcessingJobStatus) -> None:
    """전이 적법성 — live 경로와 재생 경로가 **같은 함수**를 쓴다.

    ``sites.assert_site_transition`` 과 같은 역할이다. 두 경로가 각자 조건문을
    갖고 있으면 한쪽만 고쳐지고, 그 순간 journal 이 불법 상태를 조용히
    되살리는 경로가 열린다.
    """
    if after not in _ALLOWED_TRANSITIONS[before]:
        raise IllegalJobTransitionError(
            f"처리 작업 상태를 {before.value} 에서 {after.value} 로 바꿀 수 없다"
            + (
                " — 종료된 작업의 결론은 고쳐 쓰지 않는다"
                if not _ALLOWED_TRANSITIONS[before]
                else ""
            )
        )


class ProcessingJobVerdict(StrEnum):
    """발급/전이 판정. ``ISSUED`` 와 ``ALREADY_ISSUED`` 를 나눠 재시도를 구분한다."""

    ISSUED = "ISSUED"
    # 같은 사양의 재요청 — 새 작업을 만들지 않고 기존 작업을 돌려준다.
    ALREADY_ISSUED = "ALREADY_ISSUED"
    TRANSITIONED = "TRANSITIONED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    UNKNOWN_JOB = "UNKNOWN_JOB"
    # 번들이 없거나 아직 봉인되지 않았다 — 장수·digest 가 확정되지 않은 상태.
    BUNDLE_NOT_SEALED = "BUNDLE_NOT_SEALED"
    # INV-050 — 반출 미허용 현장의 벤더 클라우드 실행.
    EGRESS_NOT_ALLOWED = "EGRESS_NOT_ALLOWED"
    UNKNOWN_PROCESSING_PROFILE = "UNKNOWN_PROCESSING_PROFILE"
    PROCESSING_PROFILE_ISSUANCE_DISABLED = "PROCESSING_PROFILE_ISSUANCE_DISABLED"
    # Core-owned resource envelope rejected this otherwise well-formed new job.
    # ``ProcessingJobResult.reason_code`` says which immutable limit applied.
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    ACTIVE_JOB_EXISTS = "ACTIVE_JOB_EXISTS"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    # 워커 입력 수신 — 끝난 작업의 원본을 다시 내주지 않는다.
    INPUT_READY = "INPUT_READY"
    JOB_NOT_ACTIVE = "JOB_NOT_ACTIVE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"

    # ── 워커 lease ───────────────────────────────────────────────────────
    LEASED = "LEASED"
    LEASE_RENEWED = "LEASE_RENEWED"
    # 다른 워커가 아직 유효한 lease 를 쥐고 있다.
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    # lease 없이(또는 만료된 lease 로) 이 작업에 손대려 했다.
    LEASE_REQUIRED = "LEASE_REQUIRED"
    LEASE_FENCE_REQUIRED = "LEASE_FENCE_REQUIRED"
    STALE_ACQUISITION = "STALE_ACQUISITION"
    STALE_LEASE_GENERATION = "STALE_LEASE_GENERATION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    # INV-051 — 원본 산출물 없이 SUCCEEDED 를 주장했다.
    UNBACKED_SUCCESS = "UNBACKED_SUCCESS"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"

    # ── 산출물 바이트 영속 ───────────────────────────────────────────────
    # 올릴 자리(객체 키)를 정했다. 아직 바이트는 없다 — 워커가 그 자리에 쓴다.
    UPLOAD_READY = "UPLOAD_READY"
    # 다운로드 요청이 가리키는 산출물이 이 작업에 등록돼 있지 않다.
    # ``INVALID_ARTIFACT_ID``(형식이 틀림, 422)와 다르다 — 형식은 맞는데 없다.
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    # 임의 MIME 을 통과시키면 열람 URL 에서 브라우저가 스크립트로 해석할 수
    # 있는 타입까지 저장소에 들어간다 — events.py/source_media.py 와 동형 방어.
    UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"

    # ── 산출물 등록 ──────────────────────────────────────────────────────
    ARTIFACT_REGISTERED = "ARTIFACT_REGISTERED"
    # 산출물은 실행 중인 작업에만 붙는다 — 시작 전에는 만들어질 수 없고,
    # 끝난 뒤에 붙이면 이미 내려진 결론에 근거를 소급하는 것이 된다.
    JOB_NOT_RUNNING = "JOB_NOT_RUNNING"
    INVALID_ARTIFACT_ID = "INVALID_ARTIFACT_ID"
    DUPLICATE_ARTIFACT = "DUPLICATE_ARTIFACT"
    # derivedFrom 이 이 작업에 없는 artifactId 를 가리킨다.
    UNKNOWN_PARENT_ARTIFACT = "UNKNOWN_PARENT_ARTIFACT"
    # kind 별 crs/gsd 필수 · derived 의 부모 필수 등 계약 위반.
    ARTIFACT_CONTRACT_VIOLATION = "ARTIFACT_CONTRACT_VIOLATION"
    ARTIFACT_MANIFEST_REQUIRED = "ARTIFACT_MANIFEST_REQUIRED"
    ARTIFACT_UPLOAD_GRANT_REQUIRED = "ARTIFACT_UPLOAD_GRANT_REQUIRED"
    ARTIFACT_STORAGE_OBJECT_MISSING = "ARTIFACT_STORAGE_OBJECT_MISSING"
    ARTIFACT_STORAGE_UNVERIFIABLE = "ARTIFACT_STORAGE_UNVERIFIABLE"
    ARTIFACT_STORAGE_SIZE_MISMATCH = "ARTIFACT_STORAGE_SIZE_MISMATCH"
    ARTIFACT_STORAGE_DIGEST_MISMATCH = "ARTIFACT_STORAGE_DIGEST_MISMATCH"
    ARTIFACT_STORAGE_CONTENT_TYPE_MISMATCH = "ARTIFACT_STORAGE_CONTENT_TYPE_MISMATCH"


class ProcessingResourceLimitReason(StrEnum):
    """Specific fail-closed reason under ``RESOURCE_LIMIT_EXCEEDED``."""

    SOURCE_MEDIA_FILES_LIMIT_EXCEEDED = "SOURCE_MEDIA_FILES_LIMIT_EXCEEDED"
    SOURCE_MEDIA_FILE_BYTES_LIMIT_EXCEEDED = "SOURCE_MEDIA_FILE_BYTES_LIMIT_EXCEEDED"
    SOURCE_BUNDLE_BYTES_LIMIT_EXCEEDED = "SOURCE_BUNDLE_BYTES_LIMIT_EXCEEDED"
    TOTAL_MEGAPIXELS_LIMIT_EXCEEDED = "TOTAL_MEGAPIXELS_LIMIT_EXCEEDED"
    ACTIVE_PROCESSING_JOBS_PER_ORGANIZATION_LIMIT_EXCEEDED = (
        "ACTIVE_PROCESSING_JOBS_PER_ORGANIZATION_LIMIT_EXCEEDED"
    )


_STATUS: dict[ProcessingJobVerdict, int] = {
    ProcessingJobVerdict.ISSUED: 201,
    ProcessingJobVerdict.ALREADY_ISSUED: 200,
    ProcessingJobVerdict.TRANSITIONED: 200,
    ProcessingJobVerdict.UNKNOWN_MISSION: 404,
    ProcessingJobVerdict.UNKNOWN_JOB: 404,
    ProcessingJobVerdict.BUNDLE_NOT_SEALED: 422,
    ProcessingJobVerdict.EGRESS_NOT_ALLOWED: 422,
    ProcessingJobVerdict.UNKNOWN_PROCESSING_PROFILE: 422,
    ProcessingJobVerdict.PROCESSING_PROFILE_ISSUANCE_DISABLED: 409,
    ProcessingJobVerdict.RESOURCE_LIMIT_EXCEEDED: 422,
    ProcessingJobVerdict.ACTIVE_JOB_EXISTS: 409,
    ProcessingJobVerdict.ILLEGAL_TRANSITION: 409,
    # 409 지 422 가 아니다 — 요청 자체는 올바르고, 지금 원장 상태가 그 주장을
    # 받쳐주지 못하는 것이다. 산출물을 등록하면 같은 요청이 통과한다.
    ProcessingJobVerdict.UNBACKED_SUCCESS: 409,
    ProcessingJobVerdict.STORE_UNAVAILABLE: 503,
    ProcessingJobVerdict.ARTIFACT_REGISTERED: 201,
    ProcessingJobVerdict.JOB_NOT_RUNNING: 409,
    ProcessingJobVerdict.INVALID_ARTIFACT_ID: 422,
    ProcessingJobVerdict.DUPLICATE_ARTIFACT: 409,
    ProcessingJobVerdict.UNKNOWN_PARENT_ARTIFACT: 422,
    ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION: 422,
    ProcessingJobVerdict.INPUT_READY: 200,
    ProcessingJobVerdict.JOB_NOT_ACTIVE: 409,
    ProcessingJobVerdict.STORAGE_UNAVAILABLE: 503,
    ProcessingJobVerdict.LEASED: 201,
    ProcessingJobVerdict.LEASE_RENEWED: 200,
    # 403 이 아니라 409 다 — 권한(PROCESSING_WORK)은 있고 **지금 이 작업을 쥔
    # 사람이 아닐** 뿐이다. 403 으로 내면 "토큰이 잘못됐나"로 읽혀 워커가 자기
    # 자격증명을 의심하게 된다. 409 는 "기다렸다가 다시 잡아라"를 뜻한다.
    ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER: 409,
    ProcessingJobVerdict.LEASE_REQUIRED: 409,
    ProcessingJobVerdict.LEASE_FENCE_REQUIRED: 409,
    ProcessingJobVerdict.STALE_ACQUISITION: 409,
    ProcessingJobVerdict.STALE_LEASE_GENERATION: 409,
    ProcessingJobVerdict.IDEMPOTENCY_CONFLICT: 409,
    # 201 이다 — 아직 바이트는 없지만 "이 자리를 이 산출물이 쓴다"는 배정이
    # 이 응답으로 생긴다(발급 계열과 같은 의미).
    ProcessingJobVerdict.UPLOAD_READY: 201,
    ProcessingJobVerdict.ARTIFACT_NOT_FOUND: 404,
    # events.py 의 EvidenceVerdict.UNSUPPORTED_CONTENT_TYPE 과 같은 415.
    ProcessingJobVerdict.UNSUPPORTED_CONTENT_TYPE: 415,
    ProcessingJobVerdict.ARTIFACT_MANIFEST_REQUIRED: 409,
    ProcessingJobVerdict.ARTIFACT_UPLOAD_GRANT_REQUIRED: 409,
    ProcessingJobVerdict.ARTIFACT_STORAGE_OBJECT_MISSING: 409,
    ProcessingJobVerdict.ARTIFACT_STORAGE_UNVERIFIABLE: 409,
    ProcessingJobVerdict.ARTIFACT_STORAGE_SIZE_MISMATCH: 409,
    ProcessingJobVerdict.ARTIFACT_STORAGE_DIGEST_MISMATCH: 409,
    ProcessingJobVerdict.ARTIFACT_STORAGE_CONTENT_TYPE_MISMATCH: 409,
}


class ProcessingJobRecoveryError(RuntimeError):
    """처리 작업 journal 재생 실패 — 오염된 원장으로 기동하지 않는다(fail-closed)."""


@dataclass(frozen=True, slots=True)
class JobSpec:
    """역사 작업의 실행 사양 기록 — **무엇으로 어디서** 돌았는지.

    Task 2 retirement 이후 새로 만들 수 없고 journal replay 와 읽기 전용
    조회가 다루는 과거형이다. 입력(장수·화소·digest)은 여기 없다 — 봉인된
    번들이 정하고 Core 가 집계한 값이다. ``engine_version``·
    ``engine_digest`` 는 자기 증명이 아니라 기록된 지시(invariant B3의 잔재)
    이며, replay 는 값을 해석하지 않고 그대로 보존한다.
    """

    provider: ProcessingProvider
    engine_version: str
    engine_digest: str
    execution_locus: ExecutionLocus
    license_basis: LicenseBasis
    processing_params: dict[str, Any]
    processing_profile_id: str | None = None
    processing_profile_digest: str | None = None

    @property
    def processing_profile_classification(self) -> str:
        """Never infer a v1 profile for a pre-profile journal record."""
        return (
            "VERSIONED"
            if self.processing_profile_id is not None and self.processing_profile_digest is not None
            else "LEGACY_UNMANAGED"
        )

    def fingerprint(self) -> str:
        """멱등 재요청 판정용 지문 — 같은 사양이면 같은 값.

        ``processing_params`` 가 중첩 dict 라 문자열 결합으로는 안정적으로
        비교되지 않는다. 이 저장소의 유일한 문서화 정규화를 재사용한다
        (``source_media.compute_source_bundle_digest`` 와 같은 근거,
        ADR-KSI-002 §2/§3).
        """
        payload = {
            "provider": self.provider.value,
            "engineVersion": self.engine_version,
            "engineDigest": self.engine_digest,
            "executionLocus": self.execution_locus.value,
            "licenseBasis": self.license_basis.model_dump(by_alias=True, mode="json"),
            "processingParams": self.processing_params,
            "processingProfileId": self.processing_profile_id,
            "processingProfileDigest": self.processing_profile_digest,
        }
        return sha256_digest(canonical_payload_bytes(payload))


@dataclass(frozen=True, slots=True)
class ProcessingJobRecord:
    """처리 작업 1건의 projection — 계약 필드 + 운영 메타(누가·언제)."""

    job_id: str
    mission_id: str
    site_id: str
    spec: JobSpec
    data_residency: DataResidency
    input: ProcessingInput
    status: ProcessingJobStatus
    issued_at: datetime
    issued_by: str
    updated_at: datetime
    # 종료 상태에서만 채워진다 — 왜 그렇게 끝났는지.
    terminal_detail: str | None = None
    # 발급 시점에는 UNMETERED_AT_ISSUE 로 고정된다(모듈 docstring).
    billing: Billing | None = None
    # 등록 순서대로. SUCCEEDED 게이트가 읽는 근거다(INV-051).
    artifacts: tuple[ProcessingArtifact, ...] = ()
    # New-format registrations are generation-owned candidates until the
    # SUCCEEDED record durably accepts their manifest.  ``artifacts`` remains
    # the accepted projection (or the honest legacy projection).
    artifact_candidates: tuple[CandidateArtifact, ...] = ()
    artifact_manifest: AuthoritativeArtifactManifestV1 | None = None
    # True only when this job has emitted generation-aware candidate/result
    # records.  It prevents a malformed new record from falling back to legacy
    # conventional key reconstruction.
    manifest_aware: bool = False
    # 마지막으로 발급된 lease. 만료 여부는 이 값이 아니라 ``now`` 가 정한다.
    lease: JobLease | None = None
    # New-format terminal mutations retain the exact fence that committed the
    # result.  This is both replay evidence and the idempotency identity for a
    # lost SUCCEEDED/FAILED response; authentication principal is not owner.
    terminal_lease_fence: LeaseFence | None = None
    # SUCCEEDED 전이 때 source-media projection에서 복사해 journal에 고정한 값.
    # legacy journal과 아직 끝나지 않은 작업은 INCOMPLETE이며 registeredAt으로
    # 추정하지 않는다(INV-020·040).
    capture_window: CaptureWindow = CaptureWindow.incomplete()
    # Current policy jobs bind the full sealed snapshot, while pre-policy
    # records remain honestly absent.  The policy is operational admission
    # evidence, not a mutable organization quota setting.  Task 2 note: this
    # snapshot is what ``_replay_issued`` validates policy-bound history
    # against — the live registry is gone, the journal fact is not.
    resource_policy: ProcessingResourcePolicyV1 | None = None

    @property
    def processing_profile_id(self) -> str | None:
        return self.spec.processing_profile_id

    @property
    def processing_profile_digest(self) -> str | None:
        return self.spec.processing_profile_digest

    @property
    def processing_profile_classification(self) -> str:
        return self.spec.processing_profile_classification

    @property
    def resource_policy_id(self) -> str | None:
        return self.resource_policy.resource_policy_id if self.resource_policy is not None else None

    @property
    def resource_policy_digest(self) -> str | None:
        return (
            self.resource_policy.resource_policy_digest
            if self.resource_policy is not None
            else None
        )

    def to_contract(self) -> ProcessingJob:
        """계약 모델로 투영한다 — 어댑터로 나가는 payload 의 SSOT.

        여기서 :class:`ProcessingJob` 의 validator 가 INV-050 을 한 번 더
        태운다. 이 저장소의 게이트와 중복이지만, 중복이 요점이다 — 계약을
        구성하는 모든 경로가 같은 규칙에 걸린다.
        """
        return ProcessingJob(
            job_id=self.job_id,
            mission_id=self.mission_id,
            provider=self.spec.provider,
            engine_version=self.spec.engine_version,
            engine_digest=self.spec.engine_digest,
            execution_locus=self.spec.execution_locus,
            data_residency=self.data_residency,
            license_basis=self.spec.license_basis,
            input=self.input,
            processing_params=self.spec.processing_params,
            processing_profile_id=self.spec.processing_profile_id,
            processing_profile_digest=self.spec.processing_profile_digest,
            resource_policy_id=self.resource_policy_id,
            resource_policy_digest=self.resource_policy_digest,
            billing=(
                self.billing
                if self.billing is not None
                else Billing(
                    credits_charged=0.0,
                    rate_basis=UNMETERED_AT_ISSUE,
                    metered_at=self.issued_at,
                )
            ),
            status=self.status,
        )


def build_processing_artifact_object_key(
    *,
    site_id: str,
    job_id: str,
    artifact_id: str,
    filename: str | None = None,
    lease_generation: int | None = None,
) -> str:
    """산출물 바이트가 놓이는 자리 — **저장하지 않고 유도한다**.

    ``build_mission_kmz_object_key`` 와 같은 관습이다. 키를 레코드에 넣으면
    계약(``processing-artifact.v1.2.json``, ``additionalProperties: false``)의
    버전을 올려야 하는데, 그 값은 이미 레코드에 있는 식별자들의 함수라
    중복이다. 유도하면 계약이 그대로고, "같은 산출물(또는 그 부속 파일)은
    항상 같은 자리"가 저장 상태가 아니라 **정의**로 보장된다.

    **``filename`` 이 없으면 산출물 1건 = 파일 1개**(주 파일)의 기존 키다.
    Mesh 의 텍스처(.mtl·map_Kd.png)처럼 한 산출물이 여러 파일이면, 주 파일은
    이 함수를 그대로 쓰고 나머지는 ``filename`` 을 채워 부른다 — 결과 키가
    주 파일 키 아래 그 이름으로 놓인다(mesh-multi-file-artifact-persistence,
    ``ProcessingArtifact.auxiliaryFiles`` 가 이 이름들을 그대로 기록한다).

    구성요소를 전부 재검증한다 — 호출부가 이미 검증했더라도, 이 함수가
    경로 탈출을 막는 마지막 지점이기 때문이다(``build_source_media_object_key``
    와 같은 이유). ``filename`` 도 ``is_path_safe_identifier`` 로 본다 — 주
    식별자들과 같은 규칙(첫 글자 영숫자, ``/`` 불허)이면 basename 이 아닌
    값(``../escape``·``sub/dir.mtl``)을 걸러내기에 충분하다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_path_safe_identifier(job_id):
        raise ValueError(f"경로-안전하지 않은 jobId: {job_id!r}")
    if not is_valid_artifact_id(artifact_id):
        raise ValueError(f"경로-안전하지 않은 artifactId: {artifact_id!r}")
    if lease_generation is not None and lease_generation < 1:
        raise ValueError("leaseGeneration must be >= 1 for a fenced artifact key")
    generation_segment = f"/attempts/{lease_generation}" if lease_generation is not None else ""
    base = f"sites/{site_id}/processing-jobs/{job_id}{generation_segment}/artifacts/{artifact_id}"
    if filename is None:
        return base
    if not is_path_safe_identifier(filename):
        raise ValueError(f"경로-안전하지 않은 filename: {filename!r}")
    return f"{base}/{filename}"


@dataclass(frozen=True, slots=True)
class ArtifactUploadGrant:
    """Durable authorization to publish one exact generation-owned object."""

    job_id: str
    artifact_id: str
    filename: str | None
    lease_fence: LeaseFence
    granted_by: str | None
    binding: ArtifactObjectBinding

    def to_wire(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "artifactId": self.artifact_id,
            "filename": self.filename,
            "leaseGeneration": self.lease_fence.lease_generation,
            "leaseFence": {
                "workerInstanceId": self.lease_fence.worker_instance_id,
                "leaseAcquisitionId": self.lease_fence.lease_acquisition_id,
                "leaseGeneration": self.lease_fence.lease_generation,
            },
            "grantedBy": self.granted_by,
            "binding": self.binding.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: dict[str, Any]) -> ArtifactUploadGrant:
        return cls(
            job_id=str(raw["jobId"]),
            artifact_id=str(raw["artifactId"]),
            filename=raw.get("filename"),
            lease_fence=LeaseFence(
                worker_instance_id=str(raw["leaseFence"]["workerInstanceId"]),
                lease_acquisition_id=str(raw["leaseFence"]["leaseAcquisitionId"]),
                lease_generation=int(raw["leaseFence"]["leaseGeneration"]),
            ),
            granted_by=raw.get("grantedBy"),
            binding=ArtifactObjectBinding.from_wire(raw["binding"]),
        )


@dataclass(frozen=True, slots=True)
class AcceptedArtifactObjectObservation:
    """Bounded HEAD facts accepted before one fenced object was published."""

    filename: str | None
    binding: ArtifactObjectBinding

    def to_wire(self) -> dict[str, Any]:
        return {"filename": self.filename, "binding": self.binding.to_wire()}

    @classmethod
    def from_wire(cls, raw: dict[str, Any]) -> AcceptedArtifactObjectObservation:
        return cls(
            filename=raw.get("filename"),
            binding=ArtifactObjectBinding.from_wire(raw["binding"]),
        )

@dataclass(frozen=True, slots=True)
class ResolvedProcessingArtifact:
    """Accepted artifact metadata plus its authoritative byte bindings.

    ``legacy=True`` is the only state allowed to derive conventional keys.  A
    manifest-aware record with a missing/incomplete manifest is never returned.
    """

    record: ProcessingJobRecord
    artifact: ProcessingArtifact
    primary: ArtifactObjectBinding | None
    auxiliary_files: tuple[tuple[str, ArtifactObjectBinding], ...]
    legacy: bool

    @property
    def object_key(self) -> str:
        if self.primary is not None:
            return self.primary.object_key
        if not self.legacy:
            raise ArtifactManifestError("new-format artifact has no primary object binding")
        return build_processing_artifact_object_key(
            site_id=self.record.site_id,
            job_id=self.record.job_id,
            artifact_id=self.artifact.artifact_id,
        )

    def auxiliary_object_keys(self) -> dict[str, str]:
        if self.primary is not None:
            return {name: binding.object_key for name, binding in self.auxiliary_files}
        if not self.legacy:
            raise ArtifactManifestError("new-format artifact has no auxiliary bindings")
        return {
            name: build_processing_artifact_object_key(
                site_id=self.record.site_id,
                job_id=self.record.job_id,
                artifact_id=self.artifact.artifact_id,
                filename=name,
            )
            for name in self.artifact.auxiliary_files
        }


def authoritative_artifacts(record: ProcessingJobRecord) -> tuple[ProcessingArtifact, ...]:
    """Return the only artifact set allowed to influence product projections."""
    if record.artifact_manifest is not None:
        return tuple(entry.artifact for entry in record.artifact_manifest.entries)
    if record.manifest_aware:
        return ()
    return record.artifacts


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _require_aware_iso(raw: Any, field_name: str, job_id: str) -> datetime:
    if not isinstance(raw, str):
        raise ProcessingJobRecoveryError(
            f"재생: {field_name} 가 문자열이 아니다({type(raw).__name__}) — jobId={job_id}"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ProcessingJobRecoveryError(
            f"재생: {field_name} 가 ISO 시각이 아니다({raw!r}) — jobId={job_id}"
        ) from exc
    if parsed.tzinfo is None:
        raise ProcessingJobRecoveryError(f"재생: {field_name} 가 naive datetime — jobId={job_id}")
    return parsed


def _resource_policy_violation(
    *,
    media: tuple[SourceMediaRecord, ...],
    policy: ProcessingResourcePolicyV1,
    active_jobs_for_organization: int,
) -> tuple[ProcessingResourceLimitReason, str] | None:
    """Return the first deterministic admission violation, otherwise ``None``.

    All values come from sealed SourceMedia claims or Core projections.  This
    is deliberately not a client-facing quota calculator: it is the shared
    live/replay fail-closed policy gate.

    Task 2 note: the live issuer is gone, but this gate is NOT dead code —
    ``_replay_issued`` re-applies it to historical journals that carry a
    resource-policy snapshot, against that snapshot (never a live registry).
    Removing it would either reject genuine history or silently accept
    journals the live gate could never have written.
    """
    if len(media) > policy.max_source_media_files:
        return (
            ProcessingResourceLimitReason.SOURCE_MEDIA_FILES_LIMIT_EXCEEDED,
            f"source media files={len(media)} exceeds policy maximum "
            f"{policy.max_source_media_files}",
        )
    largest_file = max((record.size_bytes for record in media), default=0)
    if largest_file > policy.max_source_media_file_bytes:
        return (
            ProcessingResourceLimitReason.SOURCE_MEDIA_FILE_BYTES_LIMIT_EXCEEDED,
            f"largest source media bytes={largest_file} exceeds policy maximum "
            f"{policy.max_source_media_file_bytes}",
        )
    bundle_bytes = sum(record.size_bytes for record in media)
    if bundle_bytes > policy.max_source_bundle_bytes:
        return (
            ProcessingResourceLimitReason.SOURCE_BUNDLE_BYTES_LIMIT_EXCEEDED,
            f"source bundle bytes={bundle_bytes} exceeds policy maximum "
            f"{policy.max_source_bundle_bytes}",
        )
    total_megapixels = sum(record.width * record.height for record in media) / 1_000_000
    if total_megapixels > policy.max_total_megapixels:
        return (
            ProcessingResourceLimitReason.TOTAL_MEGAPIXELS_LIMIT_EXCEEDED,
            f"source total megapixels={total_megapixels} exceeds policy maximum "
            f"{policy.max_total_megapixels}",
        )
    if active_jobs_for_organization >= policy.max_active_processing_jobs_per_organization:
        return (
            ProcessingResourceLimitReason.ACTIVE_PROCESSING_JOBS_PER_ORGANIZATION_LIMIT_EXCEEDED,
            f"active processing jobs for organization={active_jobs_for_organization} "
            f"reaches policy maximum {policy.max_active_processing_jobs_per_organization}",
        )
    return None


class ProcessingJobStore:
    """``DurableJournal`` 위의 처리 작업 역사 저장소(``source_media.py`` 형태 대칭).

    쓰기 경로는 journal replay (기동 시 1회)뿐이다 — 발급·전이·lease·산출물
    등록은 Task 2 에서 제거됐다. 남은 역할은 역사 replay/read projection 이다.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        source_media_store: SourceMediaStore,
        site_store: SiteStore,
    ) -> None:
        self._journal = journal
        self._source_media = source_media_store
        self._sites = site_store
        self._lock = threading.Lock()
        self._jobs: dict[str, ProcessingJobRecord] = {}
        self._lease_generation_highwater: dict[str, int] = {}
        self._lease_acquisitions: dict[str, tuple[str, str, str | None, JobLease]] = {}
        self._artifact_upload_grants: dict[
            tuple[str, int, str, str | None], ArtifactUploadGrant
        ] = {}
        # missionId → 발급된 작업 수(다음 jobId 순번의 근거)
        self._sequence: dict[str, int] = {}
        try:
            self._replay(journal)
        except ProcessingJobRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise ProcessingJobRecoveryError(
                f"processing-job journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    # ── 재생 ────────────────────────────────────────────────────────────
    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw["kind"]
            if kind == "processing-job-issued":
                self._replay_issued(raw)
            elif kind == "processing-job-transitioned":
                self._replay_transition(raw)
            elif kind == "processing-artifact-registered":
                self._replay_artifact(raw)
            elif kind == "processing-artifact-upload-granted":
                self._replay_upload_grant(raw)
            elif kind == "processing-job-leased":
                self._replay_lease(raw)
            else:  # pragma: no cover - 방어적, journal 오염이 아닌 이상 도달 불가
                raise ProcessingJobRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")

    def _replay_upload_grant(self, raw: dict[str, Any]) -> None:
        try:
            grant = ArtifactUploadGrant.from_wire(raw)
        except (KeyError, TypeError, ValueError, ArtifactManifestError) as exc:
            raise ProcessingJobRecoveryError(f"재생: upload grant가 잘못됐다: {exc}") from exc
        job = self._jobs.get(grant.job_id)
        if job is None or grant.lease_fence.lease_generation < 1:
            raise ProcessingJobRecoveryError(
                "재생: upload grant가 미지 job 또는 generation을 가리킨다"
            )
        granted_at = _require_aware_iso(raw["ts"], "ts", grant.job_id)
        if (
            job.lease is None
            or check_lease(
                job.lease,
                fence=grant.lease_fence,
                authenticated_actor_id=grant.granted_by,
                now=granted_at,
            )
            is not None
        ):
            raise ProcessingJobRecoveryError(
                "재생: upload grant가 당시 authoritative lease fence에 속하지 않는다"
            )
        key = (grant.job_id, grant.lease_fence.lease_generation, grant.artifact_id, grant.filename)
        existing = self._artifact_upload_grants.get(key)
        if existing is not None and existing != grant:
            raise ProcessingJobRecoveryError("재생: 동일 artifact upload grant가 충돌한다")
        self._artifact_upload_grants[key] = grant

    def _replay_issued(self, raw: dict[str, Any]) -> None:
        job_id = raw["jobId"]
        if job_id in self._jobs:
            raise ProcessingJobRecoveryError(f"재생: jobId 중복 발급 레코드 — jobId={job_id}")
        policy_raw = raw.get("resourcePolicy")
        policy_digest_raw = raw.get("resourcePolicyDigest")
        if (policy_raw is None) != (policy_digest_raw is None):
            raise ProcessingJobRecoveryError(
                "재생: resource policy binding이 반쪽이다 — jobId=" + job_id
            )
        try:
            residency = DataResidency.model_validate(raw["dataResidency"])
            license_basis = LicenseBasis.model_validate(raw["licenseBasis"])
            job_input = ProcessingInput.model_validate(raw["input"])
            spec = JobSpec(
                provider=ProcessingProvider(raw["provider"]),
                engine_version=raw["engineVersion"],
                engine_digest=raw["engineDigest"],
                execution_locus=ExecutionLocus(raw["executionLocus"]),
                license_basis=license_basis,
                processing_params=raw["processingParams"],
                # Absence is a durable historical fact.  Do not retroactively
                # label a prior job with today's default profile.
                processing_profile_id=raw.get("processingProfileId"),
                processing_profile_digest=raw.get("processingProfileDigest"),
            )
            resource_policy = (
                ProcessingResourcePolicyV1.model_validate(policy_raw)
                if policy_raw is not None
                else None
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ProcessingJobRecoveryError(
                f"재생: 발급 레코드가 계약을 만족하지 않는다 — jobId={job_id}: {exc}"
            ) from exc
        if spec.execution_locus is ExecutionLocus.VENDOR_CLOUD and not residency.egress_allowed:
            # live 는 이 조합을 절대 발급하지 않는다 — 있다면 journal 조작이거나
            # 발급 게이트가 깨진 것이다(source_media._replay_seal 과 같은 원칙).
            raise ProcessingJobRecoveryError(
                f"재생: INV-050 위반 레코드 — 반출 미허용 현장의 vendor_cloud 작업: jobId={job_id}"
            )
        if (spec.processing_profile_id is None) != (spec.processing_profile_digest is None):
            raise ProcessingJobRecoveryError(
                "재생: processing profile binding이 반쪽이다 — jobId=" + job_id
            )
        if resource_policy is not None and (
            resource_policy.resource_policy_digest != policy_digest_raw
        ):
            raise ProcessingJobRecoveryError(
                "재생: resource policy snapshot digest가 journal binding과 다르다 — jobId=" + job_id
            )
        if resource_policy is not None:
            bundle = self._source_media.get(raw["missionId"])
            organization_id = self._organization_id_for_mission(raw["missionId"])
            if bundle is None or organization_id is None:
                raise ProcessingJobRecoveryError(
                    "재생: resource policy가 있는 작업의 mission/source bundle 권위를 찾을 수 없다 "
                    f"— jobId={job_id}"
                )
            if (
                not bundle.is_sealed
                or bundle.source_bundle_digest != job_input.source_bundle_digest
            ):
                raise ProcessingJobRecoveryError(
                    "재생: resource policy가 있는 작업의 sealed source bundle이 발급 입력과 다르다 "
                    f"— jobId={job_id}"
                )
            violation = _resource_policy_violation(
                media=bundle.media,
                policy=resource_policy,
                active_jobs_for_organization=self._active_job_count_for_organization_locked(
                    organization_id
                ),
            )
            if violation is not None:
                raise ProcessingJobRecoveryError(
                    "재생: resource policy 위반 발급 레코드 — "
                    f"jobId={job_id} reason={violation[0].value}: {violation[1]}"
                )
        record = ProcessingJobRecord(
            job_id=job_id,
            mission_id=raw["missionId"],
            site_id=raw["siteId"],
            spec=spec,
            data_residency=residency,
            input=job_input,
            status=ProcessingJobStatus.QUEUED,
            issued_at=_require_aware_iso(raw["ts"], "ts", job_id),
            issued_by=raw["issuedBy"],
            updated_at=_require_aware_iso(raw["ts"], "ts", job_id),
            resource_policy=resource_policy,
        )
        self._jobs[job_id] = record
        self._sequence[record.mission_id] = max(
            self._sequence.get(record.mission_id, 0), raw["sequence"]
        )

    def _replay_transition(self, raw: dict[str, Any]) -> None:
        job_id = raw["jobId"]
        current = self._jobs.get(job_id)
        if current is None:
            raise ProcessingJobRecoveryError(f"재생: 미지 jobId 전이 레코드 — jobId={job_id}")
        before = ProcessingJobStatus(raw["before"])
        if before is not current.status:
            raise ProcessingJobRecoveryError(
                f"재생 상태 불일치 — jobId={job_id} before={before.value} "
                f"projection={current.status.value}"
            )
        after = ProcessingJobStatus(raw["after"])
        try:
            assert_job_transition(before, after)
        except IllegalJobTransitionError as exc:
            raise ProcessingJobRecoveryError(
                f"재생: 불법 전이 레코드 — jobId={job_id}: {exc}"
            ) from exc
        terminal_fence = current.terminal_lease_fence
        transition_fence: LeaseFence | None = None
        if current.manifest_aware and after is not ProcessingJobStatus.CANCELLED:
            fence_raw = raw.get("leaseFence")
            if not isinstance(fence_raw, dict):
                raise ProcessingJobRecoveryError(
                    f"재생: generation-aware worker 전이에 leaseFence가 없다 — jobId={job_id}"
                )
            try:
                transition_fence = LeaseFence(
                    worker_instance_id=str(fence_raw["workerInstanceId"]),
                    lease_acquisition_id=str(fence_raw["leaseAcquisitionId"]),
                    lease_generation=int(fence_raw["leaseGeneration"]),
                )
                transitioned_at = _require_aware_iso(raw["ts"], "ts", job_id)
            except (KeyError, TypeError, ValueError) as exc:
                raise ProcessingJobRecoveryError(
                    f"재생: worker 전이 leaseFence가 잘못됐다 — jobId={job_id}: {exc}"
                ) from exc
            if (
                current.lease is None
                or check_lease(
                    current.lease,
                    fence=transition_fence,
                    authenticated_actor_id=raw.get("actor"),
                    now=transitioned_at,
                )
                is not None
            ):
                raise ProcessingJobRecoveryError(
                    f"재생: worker 전이가 당시 authoritative lease fence와 다르다 — jobId={job_id}"
                )
            if (
                current.lease.authenticated_actor_id is not None
                and raw.get("actor") != current.lease.authenticated_actor_id
            ):
                raise ProcessingJobRecoveryError(
                    f"재생: worker 전이 actor가 lease audit principal과 다르다 — jobId={job_id}"
                )
            if after in {ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.FAILED}:
                terminal_fence = transition_fence
        accepted_artifacts = current.artifacts
        accepted_manifest = current.artifact_manifest
        try:
            if after is ProcessingJobStatus.SUCCEEDED and current.manifest_aware:
                manifest_raw = raw.get("artifactManifest")
                if not isinstance(manifest_raw, dict):
                    raise ArtifactManifestError(
                        "manifest-aware success record is missing artifactManifest"
                    )
                accepted_manifest = AuthoritativeArtifactManifestV1.from_wire(manifest_raw)
                if accepted_manifest.job_id != job_id:
                    raise ArtifactManifestError("artifact manifest jobId mismatch")
                if (
                    transition_fence is None
                    or accepted_manifest.producing_worker_instance_id
                    != transition_fence.worker_instance_id
                    or accepted_manifest.lease_acquisition_id
                    != transition_fence.lease_acquisition_id
                    or accepted_manifest.lease_generation
                    != transition_fence.lease_generation
                    or raw.get("acceptedLeaseGeneration")
                    != transition_fence.lease_generation
                ):
                    raise ArtifactManifestError(
                        "success manifest does not belong to the committing lease fence"
                    )
                if raw.get("artifactManifestDigest") != accepted_manifest.manifest_digest:
                    raise ArtifactManifestError("success record manifest digest mismatch")
                candidates = tuple(
                    sorted(
                        (
                            candidate
                            for candidate in current.artifact_candidates
                            if candidate.lease_generation == accepted_manifest.lease_generation
                        ),
                        key=lambda item: item.artifact.artifact_id,
                    )
                )
                if tuple(candidate.to_wire() for candidate in candidates) != tuple(
                    candidate.to_wire() for candidate in accepted_manifest.entries
                ):
                    raise ArtifactManifestError(
                        "success manifest does not exactly bind its generation candidates"
                    )
                accepted_artifacts = tuple(
                    candidate.artifact for candidate in accepted_manifest.entries
                )
            elif after is ProcessingJobStatus.SUCCEEDED and "artifactManifest" in raw:
                raise ArtifactManifestError(
                    "legacy success cannot contain an unclassified artifact manifest"
                )
            # 재생이 live 와 같은 게이트를 다시 태운다 — 산출물 레코드를 지우고
            # SUCCEEDED 전이만 남겨 근거 없는 성공을 되살릴 수 없다.
            assert_succeeded_is_backed(
                after, accepted_artifacts, input_verified=self.is_input_verified(current)
            )
            if after is ProcessingJobStatus.SUCCEEDED and current.manifest_aware:
                self._assert_historical_profile_required_artifacts(current, accepted_artifacts)
        except (UnbackedSuccessError, ArtifactManifestError) as exc:
            raise ProcessingJobRecoveryError(
                f"재생: 근거 없는 SUCCEEDED 레코드 — jobId={job_id}: {exc}"
            ) from exc
        capture_window = current.capture_window
        if after is ProcessingJobStatus.SUCCEEDED:
            try:
                capture_window = capture_window_from_wire(
                    raw.get("captureWindow"), context=f"jobId={job_id}"
                )
            except (TypeError, ValueError) as exc:
                raise ProcessingJobRecoveryError(
                    f"재생: captureWindow 형식이 잘못됐다 — jobId={job_id}: {exc}"
                ) from exc
            # 새 레코드는 source-media 파일별 판정과 정확히 같아야 한다. 필드가 없던
            # legacy 레코드는 위에서 INCOMPLETE로 읽고 절대 현재 번들에서 추정하지 않는다.
            if "captureWindow" in raw:
                bundle = self._source_media.get(current.mission_id)
                if bundle is None or capture_window != bundle.capture_window:
                    raise ProcessingJobRecoveryError(
                        "재생: processing job captureWindow가 source-media 계보와 불일치"
                        f" — jobId={job_id}"
                    )
        self._jobs[job_id] = replace(
            current,
            status=after,
            updated_at=_require_aware_iso(raw["ts"], "ts", job_id),
            terminal_detail=raw.get("detail"),
            capture_window=capture_window,
            artifacts=accepted_artifacts,
            artifact_manifest=accepted_manifest,
            terminal_lease_fence=terminal_fence,
        )

    def _replay_artifact(self, raw: dict[str, Any]) -> None:
        """산출물 레코드 재생 — live 등록과 **같은 게이트 전부**를 다시 태운다.

        특히 ``lineage.sourceDigest`` 가 그 작업의 봉인 digest 와 같은지 재확인
        한다. 이게 없으면 journal 을 손으로 고쳐 다른 번들에서 나온 산출물을
        이 작업의 계보에 이식할 수 있다(``source_media._replay_seal`` 대칭).
        """
        job_id = raw["jobId"]
        job = self._jobs.get(job_id)
        if job is None:
            raise ProcessingJobRecoveryError(f"재생: 미지 jobId 산출물 레코드 — jobId={job_id}")
        candidate_raw = raw.get("candidate")
        try:
            candidate = (
                CandidateArtifact.from_wire(candidate_raw)
                if isinstance(candidate_raw, dict)
                else None
            )
            artifact = (
                candidate.artifact
                if candidate is not None
                else ProcessingArtifact.model_validate(raw["artifact"])
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ProcessingJobRecoveryError(
                f"재생: 산출물 레코드가 계약을 만족하지 않는다 — jobId={job_id}: {exc}"
            ) from exc
        if artifact.job_id != job_id:
            raise ProcessingJobRecoveryError(
                f"재생: 산출물의 jobId 가 레코드와 다르다 — {artifact.job_id!r} != {job_id!r}"
            )
        if artifact.lineage.source_digest != job.input.source_bundle_digest:
            raise ProcessingJobRecoveryError(
                f"재생: 산출물 계보 앵커가 작업의 봉인 digest 와 불일치 — jobId={job_id} "
                f"(기록={artifact.lineage.source_digest!r}, "
                f"작업={job.input.source_bundle_digest!r})"
            )
        if job.status is not ProcessingJobStatus.RUNNING:
            raise ProcessingJobRecoveryError(
                f"재생: 실행 중이 아닌 작업({job.status.value})에 산출물 레코드가 있다 "
                f"— jobId={job_id} artifactId={artifact.artifact_id}"
            )
        if candidate is not None:
            if candidate.lease_generation < 1:
                raise ProcessingJobRecoveryError(
                    f"재생: candidate generation이 유효하지 않다 — jobId={job_id}"
                )
            candidate_fence = LeaseFence(
                candidate.worker_instance_id,
                candidate.lease_acquisition_id,
                candidate.lease_generation,
            )
            registered_at = _require_aware_iso(raw["ts"], "ts", job_id)
            if (
                job.lease is None
                or check_lease(
                    job.lease,
                    fence=candidate_fence,
                    authenticated_actor_id=raw.get("registeredBy"),
                    now=registered_at,
                )
                is not None
            ):
                raise ProcessingJobRecoveryError(
                    "재생: candidate가 당시 authoritative lease fence에 속하지 않는다 "
                    f"— jobId={job_id}"
                )
            if (
                job.lease.authenticated_actor_id is not None
                and raw.get("registeredBy") != job.lease.authenticated_actor_id
            ):
                raise ProcessingJobRecoveryError(
                    f"재생: candidate 등록 actor가 lease audit principal과 다르다 — jobId={job_id}"
                )
            if raw.get("artifact") is not None:
                try:
                    legacy_copy = ProcessingArtifact.model_validate(raw["artifact"])
                except ValueError as exc:
                    raise ProcessingJobRecoveryError(
                        f"재생: candidate artifact 사본이 잘못됐다 — jobId={job_id}: {exc}"
                    ) from exc
                if legacy_copy != artifact:
                    raise ProcessingJobRecoveryError(
                        f"재생: candidate와 artifact 사본이 다르다 — jobId={job_id}"
                    )
            observations_raw = raw.get("acceptedObjectObservations")
            if not isinstance(observations_raw, list):
                raise ProcessingJobRecoveryError(
                    f"재생: fenced candidate observation evidence가 없다 — jobId={job_id}"
                )
            try:
                observations = tuple(
                    AcceptedArtifactObjectObservation.from_wire(item)
                    for item in observations_raw
                    if isinstance(item, dict)
                )
            except (KeyError, TypeError, ValueError, ArtifactManifestError) as exc:
                raise ProcessingJobRecoveryError(
                    f"재생: fenced candidate observation evidence가 잘못됐다: {exc}"
                ) from exc
            expected_bindings = ((None, candidate.primary), *candidate.auxiliary_files)
            if len(observations) != len(observations_raw) or tuple(
                (item.filename, item.binding) for item in observations
            ) != expected_bindings:
                raise ProcessingJobRecoveryError(
                    "재생: candidate observation evidence가 exact binding과 다르다 "
                    f"— jobId={job_id}"
                )
            for filename, binding in expected_bindings:
                grant = self._artifact_upload_grants.get(
                    (job_id, candidate.lease_generation, artifact.artifact_id, filename)
                )
                if grant is None or grant.binding != binding:
                    raise ProcessingJobRecoveryError(
                        f"재생: candidate에 exact durable upload grant가 없다 — jobId={job_id}"
                    )
        verdict, detail = self._check_artifact_identity_locked(
            job, artifact, lease_generation=(candidate.lease_generation if candidate else None)
        )
        if verdict is not None:
            raise ProcessingJobRecoveryError(
                f"재생: 산출물 레코드가 등록 게이트를 통과하지 못한다 "
                f"({verdict.value}) — jobId={job_id}: {detail}"
            )
        if candidate is None:
            # Genuine pre-manifest record: retain the legacy projection and its
            # explicitly limited conventional-key compatibility.
            self._jobs[job_id] = replace(job, artifacts=(*job.artifacts, artifact))
        else:
            self._jobs[job_id] = replace(
                job,
                artifact_candidates=(*job.artifact_candidates, candidate),
                manifest_aware=True,
            )

    def _replay_lease(self, raw: dict[str, Any]) -> None:
        """lease 레코드 재생 — **만료 재판정을 하지 않는다.**

        만료는 저장된 상태가 아니라 ``expires_at`` 대 ``now`` 비교라서
        (:class:`JobLease`), 재생은 마지막 lease 를 그대로 복원하기만 하면 된다.
        며칠 뒤에 재생하면 그 lease 는 읽는 순간 자동으로 만료 상태다.

        live 게이트(다른 워커가 유효 lease 를 쥐고 있으면 발급 거부)를 재생이
        다시 태우지 **못한다** — 그 판정에는 발급 당시의 ``now`` 가 필요한데
        재생 시점에는 그 시각이 지나 있어 어떤 lease 든 만료로 보인다. 시간축
        판정은 재생으로 재현되지 않는 부류이고, 그 사실을 여기 적어 둔다.
        """
        job_id = raw["jobId"]
        job = self._jobs.get(job_id)
        if job is None:
            raise ProcessingJobRecoveryError(f"재생: 미지 jobId lease 레코드 — jobId={job_id}")
        if job.status not in _ACTIVE_STATUSES:
            # live 는 종료된 작업에 lease 를 발급하지 않는다 — 있으면 조작이다.
            raise ProcessingJobRecoveryError(
                f"재생: 종료된 작업({job.status.value})에 lease 레코드가 있다 — jobId={job_id}"
            )
        generation_raw = raw.get("leaseGeneration")
        if generation_raw is None:
            # Genuine historical lease.  It remains readable as generation 0
            # but cannot satisfy a new fenced mutation.
            self._jobs[job_id] = replace(
                job,
                lease=JobLease(
                    worker_id=raw["workerId"],
                    granted_at=_require_aware_iso(raw["ts"], "ts", job_id),
                    expires_at=_require_aware_iso(raw["expiresAt"], "expiresAt", job_id),
                ),
            )
            return
        try:
            generation = int(generation_raw)
            acquisition_id = str(raw["leaseAcquisitionId"])
            instance_id = str(raw["workerInstanceId"])
            actor_id = raw.get("authenticatedActorId")
            mode = LeaseMode(str(raw["leaseMode"]))
            leased_at = _require_aware_iso(raw["ts"], "ts", job_id)
            expires_at = _require_aware_iso(raw["expiresAt"], "expiresAt", job_id)
            if raw.get("workerId") != instance_id:
                raise ValueError("workerId alias differs from workerInstanceId")
            if raw.get("renewal") is not (mode is LeaseMode.RENEW):
                raise ValueError("renewal flag differs from leaseMode")
            if expires_at <= leased_at:
                raise ValueError("expiresAt must be after lease event time")
            lease = next_lease(
                worker_instance_id=instance_id,
                lease_acquisition_id=acquisition_id,
                lease_generation=generation,
                authenticated_actor_id=(str(actor_id) if actor_id is not None else None),
                now=leased_at,
                ttl=expires_at - leased_at,
                granted_at=(
                    job.lease.granted_at if mode is LeaseMode.RENEW and job.lease else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProcessingJobRecoveryError(
                f"재생: generation-aware lease가 잘못됐다 — jobId={job_id}: {exc}"
            ) from exc
        fence = lease.fence
        if fence is None or not fence.is_well_formed():
            raise ProcessingJobRecoveryError(f"재생: lease fence가 유효하지 않다 — jobId={job_id}")
        highwater = self._lease_generation_highwater.get(job_id, 0)
        existing_binding = self._lease_acquisitions.get(acquisition_id)
        binding = (job_id, instance_id, lease.authenticated_actor_id, lease)
        if mode is LeaseMode.CLAIM:
            if generation != highwater + 1:
                raise ProcessingJobRecoveryError(
                    f"재생: CLAIM generation이 단조 증가하지 않는다 — jobId={job_id}"
                )
            if existing_binding is not None:
                raise ProcessingJobRecoveryError(
                    f"재생: leaseAcquisitionId가 재사용됐다 — jobId={job_id}"
                )
            self._lease_generation_highwater[job_id] = generation
            self._lease_acquisitions[acquisition_id] = binding
        else:
            current = job.lease
            if (
                current is None
                or current.worker_instance_id != instance_id
                or current.lease_acquisition_id != acquisition_id
                or current.lease_generation != generation
                or highwater != generation
                or existing_binding is None
                or current.authenticated_actor_id != lease.authenticated_actor_id
                or existing_binding[2] != lease.authenticated_actor_id
            ):
                raise ProcessingJobRecoveryError(
                    f"재생: RENEW가 현재 CLAIM fence/principal과 일치하지 않는다 — jobId={job_id}"
                )
        self._jobs[job_id] = replace(job, lease=lease, manifest_aware=True)

    def is_input_verified(self, record: ProcessingJobRecord) -> bool:
        """이 작업의 입력 번들이 실측 대조를 통과했는가.

        **digest 를 함께 본다.** 번들이 검증됐다는 것만으로는 부족하고, 그
        검증이 이 작업이 발급될 때 고정한 바로 그 내용(``input.
        sourceBundleDigest``)에 대한 것이어야 한다.

        재생에서도 같은 함수를 쓰지만, 재생은 **순서를 재구성하지 않는다** —
        source-media 와 processing-jobs 는 별도 journal 이고 서로의 시간축을
        복원할 방법이 없다. 그래서 재생이 확인하는 것은 "성공 시점에 이미
        검증돼 있었나"가 아니라 "이 digest 의 검증된 번들이 존재하나"다.
        검증은 단조(한 번 서면 취소되지 않는다)라 재생이 live 보다 관대할 뿐
        엄격해지지 않는다 — 정상 기록을 재생이 거부하는 일은 없다.
        """
        bundle = self._source_media.get(record.mission_id)
        return (
            bundle is not None
            and bundle.is_verified
            and bundle.source_bundle_digest == record.input.source_bundle_digest
        )

    def _record_is_visible_locked(
        self,
        record: ProcessingJobRecord,
        *,
        organization_id: str | None = None,
    ) -> bool:
        """종속 Artifact도 Mission 조직 범위를 물려받게 한다(INV-060).

        ProcessingJob journal에는 organizationId를 중복 기록하지 않는다. Mission이
        그 사실의 권위이고 SourceMediaStore가 같은 MissionStore를 소유하므로,
        HTTP request scope와 호출자가 명시한 조직 범위를 모두 적용한다. replay와
        trusted internal orchestration은 둘 다 없으면 기존 동작을 유지한다.
        """
        if (
            current_request_organization_id() is not None
            and not self._source_media.mission_is_visible(record.mission_id)
        ):
            return False
        return organization_id is None or (
            self._source_media.mission_is_visible_for_organization(
                record.mission_id, organization_id=organization_id
            )
        )

    @staticmethod
    def _check_artifact_identity_locked(
        job: ProcessingJobRecord,
        artifact: ProcessingArtifact,
        *,
        lease_generation: int | None = None,
    ) -> tuple[ProcessingJobVerdict | None, str | None]:
        """artifactId 유효성·중복·부모 실재 — live 와 재생이 공유하는 판정.

        계약 자체(``ProcessingArtifact``)는 ``derivedFrom`` 이 비어 있지 않은지만
        본다. 그 안의 id 가 **실재하는지**는 원장을 아는 이 저장소만 알 수 있다.
        """
        if not is_path_safe_identifier(artifact.artifact_id):
            return (
                ProcessingJobVerdict.INVALID_ARTIFACT_ID,
                f"artifactId 가 경로-안전하지 않다: {artifact.artifact_id!r}",
            )
        if lease_generation is None:
            known = {a.artifact_id for a in job.artifacts}
        else:
            known = {
                candidate.artifact.artifact_id
                for candidate in job.artifact_candidates
                if candidate.lease_generation == lease_generation
            }
        if artifact.artifact_id in known:
            return (
                ProcessingJobVerdict.DUPLICATE_ARTIFACT,
                f"이 작업에 같은 artifactId 가 이미 등록돼 있다: {artifact.artifact_id}",
            )
        missing = [p for p in artifact.lineage.derived_from if p not in known]
        if missing:
            return (
                ProcessingJobVerdict.UNKNOWN_PARENT_ARTIFACT,
                f"derivedFrom 이 이 작업에 없는 산출물을 가리킨다: {sorted(missing)} — "
                "부모는 같은 작업에 먼저 등록돼 있어야 한다",
            )
        return None, None

    def _assert_historical_profile_required_artifacts(
        self,
        job: ProcessingJobRecord,
        artifacts: Sequence[ProcessingArtifact],
    ) -> None:
        """Require the recorded historical profile outputs for versioned success.

        The live ``ProcessingProfileRegistry`` is gone — this checks the
        replay-only immutable facts
        (:mod:`ksi_core.domains.processing.historical_processing_profiles`).
        Unknown profile IDs and tampered digests fail closed. A job without a
        profile binding (``LEGACY_UNMANAGED``) is not subject to this gate —
        absence is a durable historical fact.
        """

        if job.processing_profile_id is None:
            return
        try:
            required = historical_required_artifacts(
                job.processing_profile_id, job.processing_profile_digest or ""
            )
        except UnknownHistoricalProcessingProfileError as exc:
            raise ArtifactManifestError(
                "versioned success references an unrecorded historical processing profile binding"
            ) from exc
        present = {artifact.kind.value for artifact in artifacts}
        missing = sorted(set(required) - present)
        if missing:
            raise ArtifactManifestError(
                "authoritative artifact manifest is missing profile-required artifacts: "
                + ", ".join(missing)
            )

    def _organization_id_for_mission(self, mission_id: str) -> str | None:
        """Read organization ownership from the Mission authority, never a job claim.

        ProcessingJob intentionally does not duplicate ``organizationId`` in
        its journal (INV-060).  SourceMediaStore owns the MissionStore through
        which every source bundle was admitted; this narrow read keeps that
        existing authority boundary while the resource gate needs a same-org
        count.

        Task 2 note: retained for ``_replay_issued`` — policy-bound history
        replays against the mission/source-bundle authority, not a live store.
        """
        mission = self._source_media._mission_store.get(mission_id)  # noqa: SLF001
        return mission.organization_id if mission is not None else None

    def _active_job_count_for_organization_locked(self, organization_id: str) -> int:
        """Active-job count for the replay-time policy gate (see Task 2 note above)."""
        return sum(
            1
            for record in self._jobs.values()
            if record.status in _ACTIVE_STATUSES
            and self._organization_id_for_mission(record.mission_id) == organization_id
        )

    def get(self, job_id: str) -> ProcessingJobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or not self._record_is_visible_locked(record):
                return None
            return record

    def list_for_mission(self, mission_id: str) -> list[ProcessingJobRecord]:
        """``(issued_at, job_id)`` 결정적 정렬 — 목록 순서가 재기동마다 흔들리지 않는다."""
        with self._lock:
            records = [
                r
                for r in self._jobs.values()
                if r.mission_id == mission_id and self._record_is_visible_locked(r)
            ]
        return sorted(records, key=lambda r: (r.issued_at, r.job_id))

    def list_for_site(
        self,
        site_id: str,
        *,
        organization_id: str | None = None,
        limit: int | None = None,
    ) -> list[ProcessingJobRecord]:
        """이 현장의 재구성 epoch 목록 — **최신이 먼저**.

        ``ProcessingJobRecord`` 가 곧 reconstruction epoch 이다(ADR-KSI-016 D3).
        별도 ``SpatialEpoch`` 집계를 만들지 않은 이유는 그것이 job 과 1:1
        그림자 관계인 두 번째 원장이 되고, 그 순간 "둘 중 뭐가 진실이냐"가
        생기기 때문이다. 시계열 비교(변화·체적)는 이 목록 위에서 이뤄진다.

        ``list_for_mission`` 과 정렬 방향이 반대인 것은 의도다 — 저기는 한
        임무의 처리 이력을 순서대로 읽는 용도고, 여기는 "가장 최근 epoch 부터
        N 개"가 기본 질문이다.

        ``limit`` 은 구현이 아직 in-memory 전량 스캔이어도 **시그니처에 지금
        둔다** — 무제한 반환을 계약으로 굳히면 저장소를 바꿀 때 그게 파괴적
        변경이 된다.
        """
        if limit is not None and limit < 0:
            raise ValueError(f"limit 은 음수일 수 없다: {limit}")
        with self._lock:
            records = [
                r
                for r in self._jobs.values()
                if r.site_id == site_id
                and self._record_is_visible_locked(r, organization_id=organization_id)
            ]
        ordered = sorted(records, key=lambda r: (r.issued_at, r.job_id), reverse=True)
        return ordered if limit is None else ordered[:limit]

    def artifact_of(
        self, job_id: str, artifact_id: str
    ) -> tuple[ProcessingJobRecord, ProcessingArtifact] | None:
        """Accepted artifact metadata compatibility view.

        New-format authority is resolved by :meth:`resolve_artifact`; this
        method deliberately drops only the byte binding for metadata-only
        consumers.  It never exposes a candidate from an unaccepted generation.
        """
        resolved = self.resolve_artifact(job_id, artifact_id)
        if resolved is None:
            return None
        return resolved.record, resolved.artifact

    def resolve_artifact(self, job_id: str, artifact_id: str) -> ResolvedProcessingArtifact | None:
        """Resolve accepted metadata and bytes through the durable authority.

        Conventional path derivation is restricted to genuine historical jobs
        that never emitted a manifest-aware record.  A malformed new-format
        job fails closed rather than impersonating a legacy record.
        """
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or not self._record_is_visible_locked(record):
                return None
            if record.artifact_manifest is not None:
                entry = record.artifact_manifest.entry(artifact_id)
                if entry is None:
                    return None
                return ResolvedProcessingArtifact(
                    record=record,
                    artifact=entry.artifact,
                    primary=entry.primary,
                    auxiliary_files=entry.auxiliary_files,
                    legacy=False,
                )
            if record.manifest_aware:
                # Candidate/new success records without their durable manifest
                # are not legacy and therefore have no readable authority.
                return None
            for artifact in record.artifacts:
                if artifact.artifact_id == artifact_id:
                    return ResolvedProcessingArtifact(
                        record=record,
                        artifact=artifact,
                        primary=None,
                        auxiliary_files=(),
                        legacy=True,
                    )
        return None

    def accepted_artifacts(self, job_id: str) -> tuple[ProcessingArtifact, ...]:
        """Return only the accepted set used by authoritative projections."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or not self._record_is_visible_locked(record):
                return ()
            if record.artifact_manifest is not None:
                return tuple(entry.artifact for entry in record.artifact_manifest.entries)
            if record.manifest_aware:
                return ()
            return record.artifacts


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class ArtifactFileView(CamelModel):
    """다운로드 가능한 파일 1건 — 주 파일이든 부속 파일이든 같은 모양."""

    name: str
    object_key: str
    download_url: str


class ArtifactDownloadResponse(CamelModel):
    verdict: str
    object_key: str | None = None
    download_url: str | None = None
    expires_at: datetime | None = None
    # 주 파일(object_key/download_url) 외 부속 파일들 — 산출물이 파일 하나면
    # 항상 None(생략), 여러 개면 **주 파일을 포함해 전부** 나열한다(소비자가
    # object_key/download_url 과 files 를 겹쳐 특수 케이스하지 않게 하려는
    # 선택 — mesh-multi-file-artifact-persistence).
    files: list[ArtifactFileView] | None = None
    detail: str | None = None


class ProcessingJobView(CamelModel):
    """작업 1건의 조회 표현 — 계약 payload + 운영 메타.

    ``contract`` 는 어댑터로 나가는 payload 그대로다(``processing_job_wire_dict``).
    화면이 계약 필드를 다시 조립하지 않게 한 벌로 싣는다 — 재조립하는 순간
    화면이 계약과 갈린다.
    """

    job_id: str
    mission_id: str
    site_id: str
    status: str
    issued_at: datetime
    issued_by: str
    updated_at: datetime
    detail: str | None
    # 발급 시점 화소 합은 업로더 **신고값**의 합이다(B1 은 검증하지 않는다).
    # 이 사실을 필드로 노출해 화면이 "검증된 과금 근거"로 읽지 않게 한다.
    # 이 작업의 원본 번들이 실측 대조를 통과했는가 —  **그 작업이 고정한
    # digest 에 대한** 검증이어야 참이다(ProcessingJobStore.is_input_verified).
    # false 면 input.totalMegapixels 는 업로더 신고값의 합이고 과금 근거가 아니다.
    input_verified: bool
    processing_profile_id: str | None
    processing_profile_digest: str | None
    processing_profile_classification: str
    resource_policy_id: str | None
    resource_policy_digest: str | None
    contract: dict[str, Any]
    # 등록된 산출물의 계약 payload 그대로(등록 순). SUCCEEDED 를 받쳐주는 근거가
    # 무엇인지 화면이 상태값 하나가 아니라 계보로 볼 수 있게 한다(INV-051).
    artifacts: list[dict[str, Any]]
    # 지금 이 작업을 쥔 워커와 만료 시각. **만료 여부를 불리언으로 싣지 않는다** —
    # 응답을 만든 순간과 화면이 읽는 순간 사이에 만료될 수 있어서, 그 판정은
    # 시각을 받은 쪽이 자기 시계로 해야 한다(JobLease 와 같은 이유).
    lease_worker_id: str | None
    lease_acquisition_id: str | None = None
    lease_generation: int | None = None
    lease_expires_at: datetime | None = None
    capture_window: CaptureWindowView


class ProcessingJobListResponse(CamelModel):
    jobs: list[ProcessingJobView]


def _to_view(record: ProcessingJobRecord, *, input_verified: bool) -> ProcessingJobView:
    return ProcessingJobView(
        job_id=record.job_id,
        mission_id=record.mission_id,
        site_id=record.site_id,
        status=record.status.value,
        issued_at=record.issued_at,
        issued_by=record.issued_by,
        updated_at=record.updated_at,
        detail=record.terminal_detail,
        input_verified=input_verified,
        processing_profile_id=record.processing_profile_id,
        processing_profile_digest=record.processing_profile_digest,
        processing_profile_classification=record.processing_profile_classification,
        resource_policy_id=record.resource_policy_id,
        resource_policy_digest=record.resource_policy_digest,
        contract=processing_job_wire_dict(record.to_contract()),
        artifacts=[processing_artifact_wire_dict(a) for a in authoritative_artifacts(record)],
        lease_worker_id=(record.lease.worker_instance_id if record.lease is not None else None),
        lease_acquisition_id=(
            record.lease.lease_acquisition_id if record.lease is not None else None
        ),
        lease_generation=(
            record.lease.lease_generation
            if record.lease is not None and record.lease.lease_generation > 0
            else None
        ),
        lease_expires_at=record.lease.expires_at if record.lease is not None else None,
        capture_window=CaptureWindowView(
            status=record.capture_window.status,
            captured_from=record.capture_window.captured_from,
            captured_to=record.capture_window.captured_to,
        ),
    )


def build_processing_jobs_router(
    store: ProcessingJobStore,
    storage: EvidenceStorage,
) -> APIRouter:
    """역사 조회 전용 라우터 — 임무별·현장별 목록, 단건 상세, 산출물 다운로드.

    발급·전이·lease·입력·검증·업로드·등록·pending queue·profile catalog·
    resource-policy catalog 은 Task 2 에서 제거됐다. ``storage`` 는 산출물
    다운로드 URL 발급에 필요하다 — 스토리지가 없으면 이 표면을 장착하지
    않는다.
    """
    router = APIRouter(tags=["processing-jobs"])

    @router.get(
        "/v1/missions/{mission_id}/processing-jobs",
        response_model=ProcessingJobListResponse,
    )
    def list_processing_jobs(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ProcessingJobListResponse:
        del principal
        return ProcessingJobListResponse(
            jobs=[
                _to_view(r, input_verified=store.is_input_verified(r))
                for r in store.list_for_mission(mission_id)
            ]
        )

    @router.get(
        "/v1/sites/{site_id}/processing-jobs",
        response_model=ProcessingJobListResponse,
    )
    def list_site_processing_jobs(
        site_id: str,
        limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ProcessingJobListResponse:
        """이 현장의 재구성 epoch 목록 — **최신이 먼저**(``list_for_site`` 정렬 그대로).

        두 시점 비교(W2)의 후보를 고르는 화면이 이 표면을 쓴다.
        ``ProcessingJobRecord`` 가 곧 reconstruction epoch 이고 시계열 비교는 이
        목록 위에서 이뤄진다는 것은 ``list_for_site`` docstring 이 이미 말하는데,
        그 메서드에 HTTP 경로가 없어 화면이 임무마다 따로 물어봐야 했다(N+1).
        판정 로직을 새로 만들지 않고 그 메서드를 그대로 부른다.

        임무별 목록(``list_processing_jobs``)과 **같은 응답 모델**이라 산출물
        (``artifacts``)이 이미 실린다 — 화면이 "이 epoch 에 point_cloud·dsm 이
        있는가"를 추가 조회 없이 판단한다(비교 가능 여부 사전 표시).
        """
        del principal
        return ProcessingJobListResponse(
            jobs=[
                _to_view(r, input_verified=store.is_input_verified(r))
                for r in store.list_for_site(site_id, limit=limit)
            ]
        )

    @router.get("/v1/processing-jobs/{job_id}", response_model=ProcessingJobView)
    def get_processing_job(
        job_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ProcessingJobView:
        del principal
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return _to_view(record, input_verified=store.is_input_verified(record))

    @router.get(
        "/v1/processing-jobs/{job_id}/artifacts/{artifact_id}/download",
        response_model=ArtifactDownloadResponse,
    )
    def download_processing_artifact(
        job_id: str,
        artifact_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ArtifactDownloadResponse:
        """등록된 산출물의 바이트를 꺼낼 URL — **원장에 있는 것만 내준다**.

        M1 이전에는 재구성이 성공해도 digest 만 남고 바이트가 버려져서 이
        엔드포인트가 성립하지 않았다. 이제 워커가 실제로 올리므로, 여기가
        "사람이 정사영상을 본다"의 유일한 경로다.

        권한이 ``MISSIONS_READ`` 인 것은 산출물이 임무의 결과물이기 때문이다.
        워커의 ``PROCESSING_WORK`` 는 이를 포함하지 않는다 — 워커는 자기가
        올릴 자리만 받고, 남의(또는 자기) 산출물을 다시 읽을 이유가 없다.
        """
        del principal
        resolved = store.resolve_artifact(job_id, artifact_id)
        if resolved is None:
            response.status_code = _STATUS[ProcessingJobVerdict.ARTIFACT_NOT_FOUND]
            return ArtifactDownloadResponse(
                verdict=ProcessingJobVerdict.ARTIFACT_NOT_FOUND.value,
                detail="이 작업에 그 산출물이 등록돼 있지 않다",
            )

        artifact = resolved.artifact
        try:
            object_key = resolved.object_key
            auxiliary_keys = resolved.auxiliary_object_keys()
        except (ValueError, ArtifactManifestError) as exc:
            # 등록 시점에 이미 검증된 값이라 도달하지 않아야 한다 — 도달하면
            # 원장이 이상한 것이므로 조용히 URL 을 만들지 않는다.
            response.status_code = _STATUS[ProcessingJobVerdict.INVALID_ARTIFACT_ID]
            return ArtifactDownloadResponse(
                verdict=ProcessingJobVerdict.INVALID_ARTIFACT_ID.value, detail=str(exc)
            )

        now = datetime.now(UTC)
        try:
            download_url = storage.presigned_get(object_key, ttl=DEFAULT_VIEW_TTL)
            auxiliary_urls = {
                name: storage.presigned_get(key, ttl=DEFAULT_VIEW_TTL)
                for name, key in auxiliary_keys.items()
            }
        except EvidenceStorageError:
            logger.warning(
                "산출물 다운로드 URL 발급 실패: jobId=%s artifactId=%s", job_id, artifact_id
            )
            response.status_code = _STATUS[ProcessingJobVerdict.STORAGE_UNAVAILABLE]
            response.headers["Retry-After"] = "30"
            return ArtifactDownloadResponse(
                verdict=ProcessingJobVerdict.STORAGE_UNAVAILABLE.value,
                detail="산출물 다운로드 URL 발급에 실패했다 — 잠시 후 재시도한다",
            )

        files = None
        if artifact.auxiliary_files:
            # 주 파일을 포함해 전부 나열한다 — 소비자(mesh 뷰어 등)가
            # object_key/download_url 과 files 를 겹쳐 특수 케이스하지 않게
            # 한다(ArtifactDownloadResponse.files 문서 참고). 주 파일은
            # 원장에 원본 파일명이 없다(objectKey 자체가 artifactId 로 끝나지
            # 실제 파일명이 아니다) — kind.format 으로 사람이 읽을 이름을
            # 짓는다(예: "mesh.obj").
            primary_name = f"{artifact.kind.value}.{artifact.format}"
            files = [
                ArtifactFileView(
                    name=primary_name, object_key=object_key, download_url=download_url
                ),
                *(
                    ArtifactFileView(
                        name=name,
                        object_key=auxiliary_keys[name],
                        download_url=auxiliary_urls[name],
                    )
                    for name in artifact.auxiliary_files
                ),
            ]

        return ArtifactDownloadResponse(
            verdict="ARTIFACT_READY",
            object_key=object_key,
            download_url=download_url,
            files=files,
            expires_at=expires_at(now, DEFAULT_VIEW_TTL),
        )

    return router


def mount_processing_jobs(
    app: FastAPI,
    store: ProcessingJobStore,
    storage: EvidenceStorage,
) -> None:
    """앱에 처리 작업 역사 조회 라우터를 장착한다.

    ``storage`` 는 산출물 다운로드(``GET .../artifacts/{id}/download``)가
    presigned URL 을 발급하기 때문에 필요하다 — 스토리지가 없으면 다운로드
    표면을 열지 않는다.
    """
    app.state.processing_job_store = store
    app.include_router(build_processing_jobs_router(store, storage))


__all__ = [
    "UNMETERED_AT_ISSUE",
    "IllegalJobTransitionError",
    "JobLease",
    "JobSpec",
    "ProcessingJobListResponse",
    "ProcessingResourceLimitReason",
    "ProcessingJobRecord",
    "ProcessingJobRecoveryError",
    "ProcessingJobStore",
    "ProcessingJobVerdict",
    "ProcessingJobView",
    "UnbackedSuccessError",
    "assert_job_transition",
    "assert_succeeded_is_backed",
    "build_processing_jobs_router",
    "mount_processing_jobs",
]
