"""3D 재구성 처리 작업의 발급·영속·상태전이 (ADR-KSI-012, INV-050).

``source_media.py`` 가 봉인한 번들을 받아 처리 작업 1건을 만든다. 계약 자체는
``contracts/schemas/processing-job.v1.json``(및 그 Python 표현
:mod:`ksi_event_contracts.processing_job`)이 SSOT이고, 그 계약이 명시적으로
"범위 밖"이라 미뤄둔 두 가지를 이 모듈이 정한다 — **상태 전이 규칙**과
**발급 게이트**다.

## 입력은 요청이 아니라 봉인된 번들에서 온다

``input.imageCount``·``totalMegapixels``·``sourceBundleDigest`` 를 요청이 실어
보낼 수 없다(:class:`ProcessingJobRequest` 에 필드가 없고 ``extra="forbid"``
가 위조를 거부한다). Core 가 :class:`~ksi_core.source_media.SourceMediaBundle`
에서 직접 집계한다 — ``imageCount`` 는 등록된 미디어 수, ``totalMegapixels``
는 신고 해상도의 합이다. 봉인되지 않은 번들로는 발급하지 않는다: 봉인 전에는
장수도 digest 도 아직 확정되지 않은 값이라, 그 위에서 계산한 과금 근거는
발급 직후 달라질 수 있다.

**단, totalMegapixels 는 여전히 업로더의 신고값에서 유도된다**(B1 이 해상도를
검증하지 않는다). 그래서 이 값은 과금 확정 근거가 아니라 견적이고, 발급 시점
``billing`` 은 청구하지 않은 상태로 기록한다(아래).

## 발급 시점에 과금하지 않는다

계약은 ``billing`` 을 필수로 요구하지만, 발급 시점에 크레딧을 확정하면
"아직 아무것도 처리하지 않았고 입력 화소 수도 미검증인 상태"에서 청구액이
굳는다. 그래서 발급 레코드의 billing 은 ``creditsCharged=0`` ·
``rateBasis="unmetered-at-issue"`` 다 — 0 이라는 값이 "무료"가 아니라 "아직
재지 않았다"를 뜻하고, 그 사실이 필드 이름에 적혀 있다. 실제 계측은 전
바이트를 읽어 화소를 재계산한 워커가 종료를 보고할 때(B3) 이뤄진다.

## INV-050 은 현장 값으로만 판정한다

``executionLocus=vendor_cloud`` 는 그 임무가 속한 **현장**의
``site.dataResidency.egressAllowed`` 가 참일 때만 발급된다. 요청이 아니라
``SiteRecord`` 를 읽는다(``sites.py`` "데이터 반출 허용은 현장의 속성이다").
현장이 반출을 선언하지 않았으면(``None``) 거부다 — 미선언은 미허용이다.

## 임무당 활성 작업은 1건

``QUEUED``·``RUNNING`` 인 작업이 있는 동안 같은 임무에 두 번째 작업을 만들지
않는다. 같은 사양(provider·engine·params)으로 재요청하면 기존 작업을 그대로
돌려주고(멱등 — 네트워크 재시도가 작업을 복제하지 않는다), 다른 사양이면
``ACTIVE_JOB_EXISTS`` 로 거부한다. 종료된 뒤에는 재처리를 위해 새 작업을
만들 수 있다(다른 엔진·다른 파라미터로 다시 돌리는 것이 정상 운용이다).

## 상태 전이

``QUEUED → RUNNING → SUCCEEDED|FAILED`` · ``QUEUED|RUNNING → CANCELLED``.
종료 상태(``SUCCEEDED``·``FAILED``·``CANCELLED``)에서 나가는 전이는 없다 —
끝난 작업의 결론을 나중에 고쳐 쓸 수 없다. 재생(``_replay``)도 live 와 같은
전이표를 다시 태운다(``sites._apply_transitioned`` 와 동일 원칙): journal 을
손으로 고쳐 FAILED 를 SUCCEEDED 로 바꿀 수 없다.

## ``SUCCEEDED`` 는 근거 둘이 있어야 주장된다 (INV-051)

``RUNNING → SUCCEEDED`` 는 전이표와 **별개의** 게이트를 하나 더 통과해야 한다
(:func:`assert_succeeded_is_backed`) — ①이 작업에 ``lineage.authority=source``
산출물이 최소 1건 있고 ②이 작업의 원본 번들이 실측 대조를 통과했어야 한다.

**왜 입력 검증까지 여기서 보는가.** 재구성을 실제로 돌린 워커는 정의상 전
바이트를 읽었다. 그러니 무엇을 읽었는지 보고하는 데 추가 비용이 없고, 그
보고 없이 성공을 인정하면 과금 근거(``totalMegapixels``)가 끝까지 업로더
신고값으로 남는다 — 성공 시점이 그 값을 마지막으로 바로잡을 수 있는 지점이다.
``FAILED``·``CANCELLED`` 에는 걸지 않는다: 신고값이 거짓이라 처리가 깨졌다면
그 작업은 실패로 끝나야지 검증 못 해서 못 끝내는 상태에 갇히면 안 된다.

**왜 아무 산출물이 아니라 원본(source)인가.** ADR-KSI-003 은 Point Cloud/카메라
포즈가 원본 SSOT이고 Mesh·정사영상·3D Tiles 는 거기서 재생성 가능한 파생 서빙
계층이라고 정했다. 파생물만 있는 성공은 "원본 없이 파생을 주장하는" 상태라
그 원칙이 이미 깨진 것이고, 다시 만들 수 없는 산출물을 완료 근거로 쓰게 된다.

이건 이 저장소가 커버리지 보고에서 닫았던 것과 같은 클래스다("완료 판정의
권위를 CoverageReport 로", ADR-KSI-011 D3) — 자기 완료를 자기가 선언하지
않는다. 재생도 같은 게이트를 다시 태운다.

## 산출물의 계보 앵커는 요청이 정하지 않는다

``lineage.sourceDigest`` 는 요청 필드가 아니다(:class:`ProcessingArtifactRequest`
에 없다). Core 가 그 작업의 ``input.sourceBundleDigest`` — 즉 봉인된 번들의
digest — 를 직접 채운다. 워커가 이 값을 실어 보낼 수 있으면 산출물이 자기
출처를 스스로 적는 것이고, 그 순간 계보는 검증 대상이 아니라 자기 신고가 된다.
``derivedFrom`` 도 **같은 작업에 이미 등록된** artifactId 만 가리킬 수 있다 —
계약(``processing-artifact.v1.json``)은 "비어 있지 않다"만 강제하므로, 실재하지
않는 부모를 적은 파생물은 계약만으로는 통과한다.

## 전이 권한은 대상 상태가 가른다

``RUNNING``·``SUCCEEDED``·``FAILED`` 는 **실제로 엔진을 돌린 주체만 아는
사실**이라 ``PROCESSING_WORK``(워커 전용, 어느 Role 에도 없다)를 요구한다.
``CANCELLED`` 는 사람의 결정이라 ``MISSIONS_ISSUE`` 다. 표는
``_TRANSITION_PERMISSION`` 하나가 SSOT이고, 표에 없는 대상 상태는 403 이다 —
"정의되지 않은 전이를 할 권한"은 누구에게도 없다.

## 작업 하나는 워커 하나가 쥔다 (lease)

``POST /v1/processing-jobs/{jobId}/lease`` 로 잡지 않으면 ``/input``·실행 상태
보고·산출물 등록이 전부 거부된다(:meth:`ProcessingJobStore._check_lease_locked`
하나가 그 관문이다). 이게 두 가지를 동시에 한다 — **상호배제**(두 워커가 같은
작업을 돌리지 않는다)와 **접근 범위 축소**(워커 토큰 하나로 활성 작업 전체의
원본 사진을 열람하지 못한다).

**만료는 저장된 플래그가 아니라 시각 비교다**(:class:`JobLease`). ``released``
같은 불리언을 두면 그것을 갱신해줄 사람이 필요하고, 빠뜨리면 죽은 워커가
영원히 살아 있는 것으로 보인다. 여기서는 ``expires_at`` 만 남기고 매번 ``now``
로 판정하므로, 죽은 워커의 작업은 별도 조치 없이 만료 후 회수된다. 살아 있는
워커는 같은 엔드포인트를 다시 호출해 연장한다(heartbeat).

**취소만 lease 를 요구하지 않는다.** 워커가 죽어 lease 가 아직 살아 있는 동안
사람이 작업을 접지 못하면, 정확히 취소가 필요한 상황에서 취소가 막힌다.

## 워커가 볼 수 있는 것은 자기 작업의 입력 하나뿐

``GET /v1/processing-jobs/{jobId}/input`` 이 워커의 **유일한** 읽기 경로다.
``PROCESSING_WORK`` 는 ``MISSIONS_READ`` 를 포함하지 않으므로 워커는 임무·현장·
다른 작업 목록을 볼 수 없다. 활성(``QUEUED``·``RUNNING``) 작업만 내준다 —
끝난 작업의 원본 URL 을 계속 발급하면 종료가 접근 종료를 뜻하지 않게 된다.

응답에 **업로더의 신고값이 없다**(``JobInputMediaView``). 이게 실측 대조를
형식이 아니게 만드는 지점이다 — 자세한 근거는 ``source_media.py`` 의
"워커에게 신고값을 주지 않는다".

## 이 모듈이 다루지 않는 것

- **큐에서 꺼내오기(pull).** 워커는 jobId 를 **밖에서** 받아야 한다 — "다음
  작업을 달라"는 표면이 없다. jobId 는 ``{missionId}-pj{n}`` 이라 추측 가능하지만,
  lease 를 잡지 못하면 입력을 볼 수 없으므로 열람은 한 작업당 한 워커로 좁혀진다
  (추측 자체를 막지는 못한다 — 남의 작업을 잡아 실행을 방해할 수는 있다).
- **산출물 바이트 자체.** ``digest``·``format`` 은 워커의 보고값이고 Core 가
  객체를 읽어 대조하지 않는다. 이 모듈이 강제하는 것은 **계보의 무결성**이지
  산출물 내용의 진위가 아니다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from ksi_domain.signed_payload import canonical_payload_bytes, sha256_digest
from ksi_event_contracts.processing_artifact import (
    ArtifactAccuracy,
    ArtifactLineage,
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
    processing_resource_policy_wire_dict,
)
from ksi_event_contracts.vertical_reference import VerticalReference
from pydantic import Field

from ksi_core.domains.artifacts.artifact_manifest import (
    ArtifactManifestError,
    ArtifactObjectBinding,
    AuthoritativeArtifactManifestV1,
    CandidateArtifact,
)
from ksi_core.domains.artifacts.evidence import (
    ALLOWED_CONTENT_TYPES,
    DEFAULT_UPLOAD_TTL,
    DEFAULT_VIEW_TTL,
    DigestBoundEvidenceStorage,
    EvidenceStorage,
    EvidenceStorageError,
    ObjectStorageObservationPort,
    expires_at,
    is_valid_artifact_id,
)
from ksi_core.domains.artifacts.source_media import (
    CaptureWindow,
    CaptureWindowView,
    GroundControlRecord,
    SourceBundleVerifyVerdict,
    SourceMediaMeasurement,
    SourceMediaRecord,
    SourceMediaVerifyRequest,
    SourceMediaVerifyResponse,
    VerificationResult,
    _to_bundle_view,
    capture_window_from_wire,
    capture_window_wire,
)
from ksi_core.domains.processing.processing_profiles import (
    ProcessingProfileRegistry,
    UnknownProcessingProfileError,
)
from ksi_core.domains.processing.processing_resource_policy import ProcessingResourcePolicyRegistry
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import PATH_SAFE_IDENTIFIER_PATTERN, is_path_safe_identifier
from ksi_core.foundation.leasing import (
    JobLease,
    LeaseDenialReason,
    LeaseFence,
    LeaseMode,
    check_lease,
    is_claimable,
    lease_raw_fields,
    next_lease,
)
from ksi_core.foundation.metrics import PROCESSING_JOB_TRANSITIONS, record_processing_job_admission
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    current_request_organization_id,
    principal_permissions,
    require_permission,
    require_permission_any,
    require_principal,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.artifacts.source_media import SourceMediaStore

    # SpatialModelLifecycle 의 런타임 import 는 순환이다 — spatial_model 이 이 모듈의
    # ProcessingJobRecord 를(역시 TYPE_CHECKING 으로) 참조한다. 이 방향의 의존은
    # 타입에만 존재한다.
    from ksi_core.domains.processing.spatial_model import SpatialModelLifecycle
    from ksi_core.domains.sites.sites import SiteStore

logger = logging.getLogger("ksi_core.processing_jobs")

_NOT_FOUND_DETAIL = "해당 처리 작업을 찾을 수 없다"
_STORE_UNAVAILABLE_DETAIL = JOURNAL_SEALED_DETAIL

# 발급 시점 billing 의 rateBasis. "아직 재지 않았다"를 값 자체가 말한다 —
# creditsCharged=0 만으로는 온프렘 무료 실행과 구분되지 않는다.
UNMETERED_AT_ISSUE = "unmetered-at-issue"

_ACTIVE_STATUSES = frozenset({ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING})


def _record_processing_job_admission(result: ProcessingJobResult) -> None:
    """Emit a bounded operational admission metric without tenant identifiers."""
    if result.verdict is ProcessingJobVerdict.ISSUED:
        outcome = "issued"
    elif result.verdict is ProcessingJobVerdict.ALREADY_ISSUED:
        outcome = "idempotent"
    else:
        outcome = "rejected"
    # ``reason_code`` is a fixed StrEnum value; ordinary verdict names are
    # also a closed enum.  Never label by job/site/organization/media/request.
    record_processing_job_admission(
        outcome=outcome,
        reason=result.reason_code or result.verdict.value,
    )


# lease 수명. ODM 재구성은 몇 시간이 걸리므로(ADR-KSI-012 D1 실측 3시간 27분)
# 이 값은 "작업이 끝나는 데 걸리는 시간"이 아니라 **"워커가 죽었다고 판정하기까지
# 기다리는 시간"**이다 — 살아 있는 워커는 갱신(heartbeat)으로 계속 연장한다.
# 짧을수록 죽은 워커의 작업을 빨리 회수하고, 길수록 잠깐 느려진 워커가 남에게
# 뺏길 위험이 준다. 15분은 그 사이의 운용값이다.
DEFAULT_LEASE_TTL = timedelta(minutes=15)

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


# 대상 상태별 요구 권한 — 이 표 하나가 SSOT다(엔드포인트 산재 금지, auth.py 관습).
#
# 이 표는 **누가**만 답한다. 그 전이가 적법한지는 ``_ALLOWED_TRANSITIONS`` 가
# 따로 답한다 — 둘을 섞으면 인가 오류(403)가 상태기계 오류(409)를 가려서,
# 호출자가 "권한을 받으면 되겠구나"로 잘못 읽는다. 그래서 대상이 될 수 없는
# QUEUED 도 표에 있고(권한은 정상 통과), 거부는 전이표가 409 로 한다.
# 전 상태 망라는 test_transition_permission_table_covers_every_status 가 고정한다.
_TRANSITION_PERMISSION: dict[ProcessingJobStatus, Permission] = {
    # 엔진을 실제로 돌린 주체만 아는 사실 — 사람은 이 권한을 가질 수 없다.
    ProcessingJobStatus.QUEUED: Permission.PROCESSING_WORK,
    ProcessingJobStatus.RUNNING: Permission.PROCESSING_WORK,
    ProcessingJobStatus.SUCCEEDED: Permission.PROCESSING_WORK,
    ProcessingJobStatus.FAILED: Permission.PROCESSING_WORK,
    # 사람의 결정 — 워커는 남의 작업을 취소할 수 없다.
    ProcessingJobStatus.CANCELLED: Permission.MISSIONS_ISSUE,
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
    """호출자가 정하는 것 — **무엇으로 어디서** 돌릴지.

    입력(장수·화소·digest)은 여기 없다. 그건 봉인된 번들이 정하고 Core 가
    집계한다(모듈 docstring). ``engine_version``·``engine_digest`` 는 지시이지
    자기 증명이 아니다 — 실제로 그 엔진이 돌았는지는 종료 보고 시점에
    대조한다(B3).
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
    # evidence, not a mutable organization quota setting.
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


@dataclass(frozen=True, slots=True)
class ProcessingJobResult:
    verdict: ProcessingJobVerdict
    record: ProcessingJobRecord | None = None
    detail: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """워커가 보고하는 산출물 1건 — **계보 앵커는 여기 없다**.

    ``lineage.sourceDigest`` 와 ``jobId`` 는 Core 가 작업 원장에서 채운다
    (모듈 docstring). ``derived_from`` 은 같은 작업 안의 artifactId 만 가리킬 수
    있고, 그 실재 여부는 :meth:`ProcessingJobStore.register_artifact` 가 본다.
    """

    artifact_id: str
    kind: ProcessingArtifactKind
    authority: LineageAuthority
    derived_from: tuple[str, ...]
    digest: str
    format: str
    crs: str | None
    gsd: float | None
    accuracy: ArtifactAccuracy | None
    auxiliary_files: tuple[str, ...] = ()
    # 이 산출물 높이의 수직기준 — **생산자가 선언하고 Core 는 기록만 한다**.
    # Core 는 산출물 바이트를 읽지 않으므로(모듈 docstring) 이 값을 확인할
    # 방법이 없고, 확인할 수 없는 값을 기본값으로 채우지도 않는다: None 이면
    # "수직기준이 기록되지 않은 산출물"로 그대로 남는다(processing_artifact.py).
    vertical_reference: VerticalReference | None = None
    primary: ArtifactObjectBinding | None = None
    auxiliary_objects: tuple[tuple[str, ArtifactObjectBinding], ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    verdict: ProcessingJobVerdict
    artifact: ProcessingArtifact | None = None
    detail: str | None = None
    candidate: CandidateArtifact | None = None


@dataclass(frozen=True, slots=True)
class JobInputResult:
    """워커가 받아갈 작업 입력 — 무엇을 돌리고 어떤 파일을 읽을지.

    ``media`` 는 원장 레코드 그대로지만, **응답으로 나갈 때 신고값은 빠진다**
    (:func:`_to_input_view`) — 워커가 정답을 모른 채 실측해야 대조가 의미를
    갖는다(``source_media.py`` "워커에게 신고값을 주지 않는다").
    """

    verdict: ProcessingJobVerdict
    record: ProcessingJobRecord | None = None
    media: tuple[SourceMediaRecord, ...] = ()
    # 현장 등록 시점에 확정된 CRS — 워커가 처리 산출물에 실을 좌표계.
    # None 이면 현장이 없거나 site_frame 이 비어 있다(원장 이상 상태).
    site_crs: str | None = None
    # 이 조사에 붙은 기준점 파일(있으면). 워커는 이걸 재구성 엔진에 함께 넘겨
    # 성과가 선언된 좌표계로 나오게 한다 — 없으면 엔진이 EXIF 만 보고 UTM 을
    # 고르고, 그 성과는 두 시점 비교 단계에서 거부된다(2026-08-18 실측).
    ground_control: GroundControlRecord | None = None
    detail: str | None = None


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
class ArtifactUploadTargetResult:
    """산출물 바이트를 올릴 자리 — 객체 키 하나.

    presigned URL 은 여기 없다. 이 결과는 **원장이 아는 것**(어느 작업의 어느
    산출물이 어디에 놓이는가)만 담고, 실제 URL 발급은 스토리지 포트를 쥔
    라우터의 몫이다(``input_for`` 가 media 레코드만 주고 라우터가 presign 하는
    것과 같은 분리).
    """

    verdict: ProcessingJobVerdict
    object_key: str | None = None
    detail: str | None = None
    lease_generation: int | None = None


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


def build_job_id(mission_id: str, sequence: int) -> str:
    """``{missionId}-pj{n}`` — 임무 안에서 결정적이고 사람이 읽을 수 있다.

    ``mission_id`` 는 이미 경로-안전이 강제된 값이므로(mission_records
    ``validate_mission_identifiers``) 여기서 만들어진 jobId 도 경로-안전이다.
    """
    return f"{mission_id}-pj{sequence}"


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


def _compute_input(*, media: tuple[Any, ...], source_bundle_digest: str) -> ProcessingInput:
    """봉인된 번들에서 계약 ``input`` 을 집계한다 — 요청은 이 값에 관여하지 않는다.

    ``total_megapixels`` 는 등록 시 **신고된** 해상도의 합이다(B1 은 검증하지
    않는다). 그래서 이 값은 과금 확정이 아니라 견적이고, 재계산·대조는 전
    바이트를 읽는 워커의 몫이다.
    """
    total_pixels = sum(record.width * record.height for record in media)
    return ProcessingInput(
        image_count=len(media),
        total_megapixels=total_pixels / 1_000_000,
        source_bundle_digest=source_bundle_digest,
    )


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
    """``DurableJournal`` 위의 처리 작업 저장소(``source_media.py`` 형태 대칭).

    동시성: 판정+append+projection 을 한 임계구역으로 묶는다 — "활성 작업 1건"
    은 이 잠금 안에서만 성립하는 불변식이다.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        source_media_store: SourceMediaStore,
        site_store: SiteStore,
        processing_profile_registry: ProcessingProfileRegistry | None = None,
        processing_resource_policy_registry: ProcessingResourcePolicyRegistry | None = None,
        processing_profile_issuance_enabled: bool = True,
        artifact_storage_observer: ObjectStorageObservationPort | None = None,
    ) -> None:
        self._journal = journal
        self._source_media = source_media_store
        self._sites = site_store
        self._processing_profiles = processing_profile_registry or ProcessingProfileRegistry()
        self._resource_policies = (
            processing_resource_policy_registry or ProcessingResourcePolicyRegistry()
        )
        self._processing_profile_issuance_enabled = processing_profile_issuance_enabled
        self._artifact_storage_observer = artifact_storage_observer
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

    def set_artifact_storage_observer(self, observer: ObjectStorageObservationPort) -> None:
        """Bind the assembled runtime's metadata-only observer before serving writes."""
        self._artifact_storage_observer = observer

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
                self._assert_profile_required_artifacts(current, accepted_artifacts)
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

    def artifact_upload_target(
        self,
        job_id: str,
        *,
        artifact_id: str,
        now: datetime,
        worker_id: str | None = None,
        lease_fence: LeaseFence | None = None,
        authenticated_actor_id: str | None = None,
        filename: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
        content_type: str | None = None,
    ) -> ArtifactUploadTargetResult:
        """산출물 바이트를 올릴 자리를 정한다 — ``input_for`` 와 같은 관문을 통과한다.

        **활성 작업 + lease 보유**를 요구하는 이유는 읽기 쪽과 같다. 이게
        없으면 워커 토큰 하나로 남의 작업 경로에 바이트를 쓸 수 있고,
        jobId 는 추측 가능하다.

        키는 저장하지 않고 유도한다 — ``build_processing_artifact_object_key``
        의 docstring 참조. ``filename`` 은 다중 파일 산출물의 부속 파일 자리를
        받을 때만 채운다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if not self._record_is_visible_locked(record):
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if record.status not in _ACTIVE_STATUSES:
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.JOB_NOT_ACTIVE,
                    detail=(
                        f"작업이 {record.status.value} 상태다 — 끝난 작업에 산출물 "
                        "바이트를 더 쓰지 않는다"
                    ),
                )
            denied = self._check_lease_locked(
                record, worker_id=worker_id, lease_fence=lease_fence,
                authenticated_actor_id=authenticated_actor_id, now=now
            )
            if denied is not None:
                return ArtifactUploadTargetResult(denied[0], detail=denied[1])
            lease_generation = lease_fence.lease_generation if lease_fence is not None else None
            try:
                object_key = build_processing_artifact_object_key(
                    site_id=record.site_id,
                    job_id=job_id,
                    artifact_id=artifact_id,
                    filename=filename,
                    lease_generation=lease_generation,
                )
            except ValueError as exc:
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.INVALID_ARTIFACT_ID, detail=str(exc)
                )
            if lease_generation is None:
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.UPLOAD_READY,
                    object_key=object_key,
                    lease_generation=None,
                )
            if sha256 is None or size_bytes is None or content_type is None:
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.ARTIFACT_MANIFEST_REQUIRED,
                    detail="fenced upload grant requires sha256, sizeBytes, and contentType",
                )
            try:
                binding = ArtifactObjectBinding(
                    object_key=object_key,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    content_type=content_type,
                )
            except ArtifactManifestError as exc:
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION, detail=str(exc)
                )
            assert lease_fence is not None
            grant = ArtifactUploadGrant(
                job_id, artifact_id, filename, lease_fence, authenticated_actor_id, binding
            )
            key = (job_id, lease_generation, artifact_id, filename)
            existing = self._artifact_upload_grants.get(key)
            if existing is not None:
                if existing != grant:
                    return ArtifactUploadTargetResult(
                        ProcessingJobVerdict.IDEMPOTENCY_CONFLICT,
                        detail="conflicting upload grant reissue for the same artifact identity",
                    )
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.UPLOAD_READY, object_key=object_key,
                    lease_generation=lease_generation,
                )
            try:
                self._journal.append({
                    "kind": "processing-artifact-upload-granted", "ts": iso_utc(now),
                    **grant.to_wire(),
                })
            except JournalSealedError:
                return ArtifactUploadTargetResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            self._artifact_upload_grants[key] = grant
        return ArtifactUploadTargetResult(
            ProcessingJobVerdict.UPLOAD_READY, object_key=object_key,
            lease_generation=lease_generation,
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

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    # ── 공개 API ────────────────────────────────────────────────────────
    def issue(
        self,
        mission_id: str,
        spec: JobSpec,
        *,
        issued_by: str,
        now: datetime,
        caller_device_id: str | None = None,
    ) -> ProcessingJobResult:
        """봉인된 번들 위에 처리 작업을 발급한다.

        게이트 순서는 **싼 것부터**다 — 번들 존재/봉인 → INV-050 → 활성 작업
        중복. 반출 위반을 활성 작업 검사보다 먼저 보는 이유는, 두 번째 요청이
        409 를 받아 "중복만 아니면 통과할 것"으로 오해되지 않게 하기 위해서다.

        ``caller_device_id`` 는 Edge 장비 호출일 때만 넘긴다(사람 호출은
        ``None``). 값이 있는데 그 mission 의 배정 장비와 다르면
        ``source_media.py`` 의 ``register_batch``/``seal`` 과 동일하게
        ``UNKNOWN_MISSION`` 과 같은 판정으로 접는다(열거 오라클 방지).
        """
        _require_tz_aware(now, param="now")
        if (spec.processing_profile_id is None) != (spec.processing_profile_digest is None):
            return ProcessingJobResult(
                ProcessingJobVerdict.UNKNOWN_PROCESSING_PROFILE,
                detail="processing profile binding은 id와 digest가 함께 있어야 한다",
            )
        if spec.processing_profile_id is not None:
            try:
                canonical_spec = self.resolve_processing_profile(spec.processing_profile_id)
            except UnknownProcessingProfileError:
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_PROCESSING_PROFILE,
                    detail="Core registry에서 발급되지 않은 processing profile이다",
                )
            if spec.fingerprint() != canonical_spec.fingerprint():
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_PROCESSING_PROFILE,
                    detail=(
                        "processing profile id와 실제 snapshot이 다르다 — "
                        "Core registry 사양만 발급할 수 있다"
                    ),
                )
            spec = canonical_spec
        else:
            # Legacy internal callers remain readable/issuable for the
            # migration boundary, but the record must not retain a mutable
            # dictionary owned by its caller.
            spec = JobSpec(
                provider=spec.provider,
                engine_version=spec.engine_version,
                engine_digest=spec.engine_digest,
                execution_locus=spec.execution_locus,
                license_basis=spec.license_basis.model_copy(deep=True),
                processing_params=deepcopy(spec.processing_params),
            )
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            bundle = self._source_media.get(mission_id)
            if bundle is None or (
                caller_device_id is not None
                and self._source_media.assigned_device_id(mission_id) != caller_device_id
            ):
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_MISSION,
                    detail="해당 임무의 원본 미디어 번들이 없다 — 사진을 먼저 올린다",
                )
            if not bundle.is_sealed or bundle.source_bundle_digest is None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.BUNDLE_NOT_SEALED,
                    detail=(
                        "번들이 아직 봉인되지 않았다 — 봉인 전에는 장수·digest 가 "
                        "확정되지 않아 처리 입력이 성립하지 않는다"
                    ),
                )

            site = self._sites.get(bundle.site_id)
            residency = _residency_of(site)
            if spec.execution_locus is ExecutionLocus.VENDOR_CLOUD and not residency.egress_allowed:
                return ProcessingJobResult(
                    ProcessingJobVerdict.EGRESS_NOT_ALLOWED,
                    detail=(
                        f"INV-050 — 현장 {bundle.site_id} 은 데이터 반출이 허용되지 "
                        "않았다(미선언 포함). 벤더 클라우드 처리 작업을 만들 수 없다"
                    ),
                )

            active = self._active_job_locked(mission_id)
            if active is not None:
                if active.spec.fingerprint() == spec.fingerprint():
                    # All identity, sealed-bundle, and INV-050 checks above
                    # still apply.  Only today's resource policy must not
                    # reinterpret a pre-existing idempotent active job.
                    return ProcessingJobResult(ProcessingJobVerdict.ALREADY_ISSUED, record=active)
                return ProcessingJobResult(
                    ProcessingJobVerdict.ACTIVE_JOB_EXISTS,
                    detail=(
                        f"이 임무에 진행 중인 처리 작업이 있다({active.job_id}, "
                        f"{active.status.value}) — 끝나거나 취소된 뒤에 새 작업을 만든다"
                    ),
                )

            job_input = _compute_input(
                media=bundle.media, source_bundle_digest=bundle.source_bundle_digest
            )
            resource_policy = self._resource_policies.current()
            organization_id = self._organization_id_for_mission(mission_id)
            if organization_id is None:
                # A sealed source bundle without the mission ownership
                # authority is an inconsistent projection, not an opportunity
                # to count it as a global/anonymous customer.
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_MISSION,
                    detail="해당 임무의 조직 소유권을 확인할 수 없다",
                )
            violation = _resource_policy_violation(
                media=bundle.media,
                policy=resource_policy,
                active_jobs_for_organization=self._active_job_count_for_organization_locked(
                    organization_id
                ),
            )
            if violation is not None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.RESOURCE_LIMIT_EXCEEDED,
                    detail=violation[1],
                    reason_code=violation[0].value,
                )
            sequence = self._sequence.get(mission_id, 0) + 1
            job_id = build_job_id(mission_id, sequence)
            raw: dict[str, Any] = {
                "kind": "processing-job-issued",
                "ts": iso_utc(now),
                "jobId": job_id,
                "sequence": sequence,
                "missionId": mission_id,
                "siteId": bundle.site_id,
                "provider": spec.provider.value,
                "engineVersion": spec.engine_version,
                "engineDigest": spec.engine_digest,
                "executionLocus": spec.execution_locus.value,
                "dataResidency": residency.model_dump(by_alias=True, mode="json"),
                "licenseBasis": spec.license_basis.model_dump(by_alias=True, mode="json"),
                "input": job_input.model_dump(by_alias=True, mode="json"),
                "processingParams": spec.processing_params,
                "resourcePolicy": processing_resource_policy_wire_dict(resource_policy),
                "resourcePolicyDigest": resource_policy.resource_policy_digest,
                "issuedBy": issued_by,
            }
            if spec.processing_profile_id is not None:
                # Both fields are guaranteed together by profile resolution;
                # omitting both preserves exact legacy journal replay.
                raw["processingProfileId"] = spec.processing_profile_id
                raw["processingProfileDigest"] = spec.processing_profile_digest
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            record = ProcessingJobRecord(
                job_id=job_id,
                mission_id=mission_id,
                site_id=bundle.site_id,
                spec=spec,
                data_residency=residency,
                input=job_input,
                status=ProcessingJobStatus.QUEUED,
                issued_at=now,
                issued_by=issued_by,
                updated_at=now,
                resource_policy=resource_policy,
            )
            self._jobs[job_id] = record
            self._sequence[mission_id] = sequence
            return ProcessingJobResult(ProcessingJobVerdict.ISSUED, record=record)

    @property
    def processing_profiles(self) -> ProcessingProfileRegistry:
        """The issued recipes available to authenticated callers (read-only)."""
        return self._processing_profiles

    @property
    def processing_resource_policies(self) -> ProcessingResourcePolicyRegistry:
        """Core-issued admission-policy snapshots, exposed read-only."""
        return self._resource_policies

    @property
    def processing_profile_issuance_enabled(self) -> bool:
        return self._processing_profile_issuance_enabled

    def resolve_processing_profile(self, processing_profile_id: str) -> JobSpec:
        """Expand a public id to an immutable Core-owned JobSpec.

        No client controlled parameter survives this boundary.  A disabled flag
        is intentionally handled by the router so legacy replay/read paths
        retain their normal behaviour.
        """
        profile = self._processing_profiles.get(processing_profile_id)
        return JobSpec(
            provider=profile.provider,
            engine_version=profile.engine_version,
            engine_digest=profile.oci_image_digest,
            execution_locus=profile.execution_locus,
            license_basis=profile.license_basis.model_copy(deep=True),
            processing_params=profile.model_copy(deep=True).processing_params,
            processing_profile_id=profile.processing_profile_id,
            processing_profile_digest=profile.profile_digest,
        )

    def _assert_profile_required_artifacts(
        self,
        job: ProcessingJobRecord,
        artifacts: Sequence[ProcessingArtifact],
    ) -> None:
        """Require the exact immutable profile outputs for versioned success."""

        if job.processing_profile_id is None:
            return
        try:
            profile = self._processing_profiles.get(job.processing_profile_id)
        except UnknownProcessingProfileError as exc:
            raise ArtifactManifestError(
                "versioned success references a processing profile unavailable to Core"
            ) from exc
        if profile.profile_digest != job.processing_profile_digest:
            raise ArtifactManifestError(
                "versioned success processing profile digest differs from the Core registry"
            )
        present = {artifact.kind.value for artifact in artifacts}
        missing = sorted(set(profile.required_artifacts) - present)
        if missing:
            raise ArtifactManifestError(
                "authoritative artifact manifest is missing profile-required artifacts: "
                + ", ".join(missing)
            )

    def transition(
        self,
        job_id: str,
        target: ProcessingJobStatus,
        *,
        detail: str | None,
        actor: str,
        now: datetime,
        requires_lease: bool = True,
        lease_fence: LeaseFence | None = None,
    ) -> ProcessingJobResult:
        """작업 상태를 전이한다 — 전이표는 :func:`assert_job_transition` SSOT.

        ``requires_lease=False`` 는 **사람의 취소**만을 위한 것이다(라우터가 대상
        상태로 판정한다). 사람이 작업을 접는 데 lease 를 요구하면, 워커가 죽어
        lease 가 살아 있는 동안 아무도 그 작업을 취소할 수 없게 된다 — 정확히
        취소가 필요한 상황에서 취소가 막힌다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            current = self._jobs.get(job_id)
            if current is None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if not self._record_is_visible_locked(current):
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if (
                requires_lease
                and target in {ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.FAILED}
                and current.status is target
                and current.terminal_lease_fence is not None
            ):
                # A terminal response can be lost after the append.  The exact
                # generation/payload retry returns the already durable result
                # without requiring the now-terminal lease to remain active.
                if lease_fence != current.terminal_lease_fence:
                    return ProcessingJobResult(
                        ProcessingJobVerdict.STALE_LEASE_GENERATION,
                        record=current,
                        detail="terminal mutation belongs to another lease generation",
                    )
                if (
                    current.lease is not None
                    and current.lease.authenticated_actor_id is not None
                    and actor != current.lease.authenticated_actor_id
                ):
                    return ProcessingJobResult(
                        ProcessingJobVerdict.STALE_LEASE_GENERATION,
                        record=current,
                        detail="terminal mutation belongs to another authenticated principal",
                    )
                if detail != current.terminal_detail:
                    return ProcessingJobResult(
                        ProcessingJobVerdict.IDEMPOTENCY_CONFLICT,
                        record=current,
                        detail="terminal mutation retry changed its payload",
                    )
                return ProcessingJobResult(ProcessingJobVerdict.TRANSITIONED, record=current)
            if requires_lease:
                denied = self._check_lease_locked(
                    current,
                    worker_id=(actor if lease_fence is None else None),
                    lease_fence=lease_fence,
                    authenticated_actor_id=actor if lease_fence is not None else None,
                    now=now,
                )
                if denied is not None:
                    return ProcessingJobResult(denied[0], record=current, detail=denied[1])
            try:
                assert_job_transition(current.status, target)
            except IllegalJobTransitionError as exc:
                return ProcessingJobResult(ProcessingJobVerdict.ILLEGAL_TRANSITION, detail=str(exc))
            manifest: AuthoritativeArtifactManifestV1 | None = None
            completion_artifacts = current.artifacts
            if target is ProcessingJobStatus.SUCCEEDED and lease_fence is not None:
                candidates = tuple(
                    candidate
                    for candidate in current.artifact_candidates
                    if candidate.lease_generation == lease_fence.lease_generation
                )
                completion_artifacts = tuple(candidate.artifact for candidate in candidates)
                try:
                    manifest = AuthoritativeArtifactManifestV1.create(
                        job_id=job_id,
                        producing_worker_instance_id=lease_fence.worker_instance_id,
                        lease_acquisition_id=lease_fence.lease_acquisition_id,
                        lease_generation=lease_fence.lease_generation,
                        entries=candidates,
                    )
                except ArtifactManifestError as exc:
                    return ProcessingJobResult(
                        ProcessingJobVerdict.ARTIFACT_MANIFEST_REQUIRED, detail=str(exc)
                    )
            try:
                assert_succeeded_is_backed(
                    target,
                    completion_artifacts,
                    input_verified=self.is_input_verified(current),
                )
            except UnbackedSuccessError as exc:
                return ProcessingJobResult(ProcessingJobVerdict.UNBACKED_SUCCESS, detail=str(exc))
            if target is ProcessingJobStatus.SUCCEEDED and lease_fence is not None:
                try:
                    self._assert_profile_required_artifacts(current, completion_artifacts)
                except ArtifactManifestError as exc:
                    return ProcessingJobResult(
                        ProcessingJobVerdict.ARTIFACT_MANIFEST_REQUIRED,
                        detail=str(exc),
                    )
            raw: dict[str, Any] = {
                "kind": "processing-job-transitioned",
                "ts": iso_utc(now),
                "jobId": job_id,
                "before": current.status.value,
                "after": target.value,
                "detail": detail,
                "actor": actor,
            }
            if requires_lease and lease_fence is not None:
                raw["leaseFence"] = {
                    "workerInstanceId": lease_fence.worker_instance_id,
                    "leaseAcquisitionId": lease_fence.lease_acquisition_id,
                    "leaseGeneration": lease_fence.lease_generation,
                }
            capture_window = current.capture_window
            if target is ProcessingJobStatus.SUCCEEDED:
                bundle = self._source_media.get(current.mission_id)
                if bundle is None or not bundle.is_verified:
                    # assert_succeeded_is_backed가 먼저 막아야 하며 이 분기는 방어적이다.
                    return ProcessingJobResult(
                        ProcessingJobVerdict.UNBACKED_SUCCESS,
                        detail="검증된 source-media bundle이 없어 captureWindow를 고정할 수 없다",
                    )
                capture_window = bundle.capture_window
                raw["captureWindow"] = capture_window_wire(capture_window)
                if lease_fence is not None:
                    if manifest is None:
                        return ProcessingJobResult(
                            ProcessingJobVerdict.ARTIFACT_MANIFEST_REQUIRED,
                            detail="new-format success requires an authoritative artifact manifest",
                        )
                    raw["acceptedLeaseGeneration"] = lease_fence.lease_generation
                    raw["artifactManifestDigest"] = manifest.manifest_digest
                    raw["artifactManifest"] = manifest.to_wire()
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            updated = replace(
                current,
                status=target,
                updated_at=now,
                terminal_detail=detail,
                capture_window=capture_window,
                artifacts=(
                    completion_artifacts
                    if target is ProcessingJobStatus.SUCCEEDED
                    else current.artifacts
                ),
                artifact_manifest=(
                    manifest
                    if target is ProcessingJobStatus.SUCCEEDED
                    else current.artifact_manifest
                ),
                manifest_aware=current.manifest_aware or lease_fence is not None,
                terminal_lease_fence=(
                    lease_fence
                    if target in {ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.FAILED}
                    else current.terminal_lease_fence
                ),
            )
            self._jobs[job_id] = updated
            # journal.append 가 성공한 뒤에만 센다 — 실패(STORE_UNAVAILABLE)까지
            # 세면 "일어난 전이 수"가 아니라 "시도 수"가 되어 이름이 거짓말한다.
            PROCESSING_JOB_TRANSITIONS.inc(target_status=target.value)
            return ProcessingJobResult(ProcessingJobVerdict.TRANSITIONED, record=updated)

    def register_artifact(
        self,
        job_id: str,
        spec: ArtifactSpec,
        *,
        registered_by: str,
        now: datetime,
        lease_fence: LeaseFence | None = None,
    ) -> ArtifactResult:
        """실행 중인 작업에 산출물 1건을 등록한다.

        ``jobId`` 와 ``lineage.sourceDigest`` 는 여기서 **작업 원장에서** 채운다
        — 워커가 실어 보낸 값을 쓰지 않는다(모듈 docstring). 계약 위반은
        ``ProcessingArtifact`` 생성 시점에 걸리고, 계약이 볼 수 없는 것(부모의
        실재)은 :meth:`_check_artifact_identity_locked` 가 본다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ArtifactResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            job = self._jobs.get(job_id)
            if job is None:
                return ArtifactResult(ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL)
            if not self._record_is_visible_locked(job):
                return ArtifactResult(ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL)
            if job.status is not ProcessingJobStatus.RUNNING:
                return ArtifactResult(
                    ProcessingJobVerdict.JOB_NOT_RUNNING,
                    detail=(
                        f"작업이 {job.status.value} 상태다 — 산출물은 실행 중인 "
                        "작업에만 등록된다(끝난 작업에 근거를 소급하지 않는다)"
                    ),
                )
            denied = self._check_lease_locked(
                job,
                worker_id=(registered_by if lease_fence is None else None),
                lease_fence=lease_fence,
                authenticated_actor_id=registered_by if lease_fence is not None else None,
                now=now,
            )
            if denied is not None:
                return ArtifactResult(denied[0], detail=denied[1])
            try:
                artifact = ProcessingArtifact(
                    artifact_id=spec.artifact_id,
                    job_id=job_id,
                    kind=spec.kind,
                    lineage=ArtifactLineage(
                        authority=spec.authority,
                        derived_from=list(spec.derived_from),
                        # 계보 앵커는 요청이 아니라 봉인된 번들에서 온다.
                        source_digest=job.input.source_bundle_digest,
                    ),
                    digest=spec.digest,
                    format=spec.format,
                    crs=spec.crs,
                    gsd=spec.gsd,
                    accuracy=spec.accuracy,
                    auxiliary_files=spec.auxiliary_files,
                    vertical_reference=spec.vertical_reference,
                )
            except ValueError as exc:
                return ArtifactResult(
                    ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION, detail=str(exc)
                )
            verdict, detail = self._check_artifact_identity_locked(
                job,
                artifact,
                lease_generation=(
                    lease_fence.lease_generation if lease_fence is not None else None
                ),
            )
            candidate: CandidateArtifact | None = None
            if lease_fence is not None:
                if spec.primary is None:
                    return ArtifactResult(
                        ProcessingJobVerdict.ARTIFACT_MANIFEST_REQUIRED,
                        detail="primary object binding is required for fenced artifacts",
                    )
                expected_primary = build_processing_artifact_object_key(
                    site_id=job.site_id,
                    job_id=job_id,
                    artifact_id=artifact.artifact_id,
                    lease_generation=lease_fence.lease_generation,
                )
                if spec.primary.object_key != expected_primary:
                    return ArtifactResult(
                        ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION,
                        detail="primary objectKey is not the current generation upload target",
                    )
                if spec.primary.content_type not in ALLOWED_CONTENT_TYPES:
                    return ArtifactResult(
                        ProcessingJobVerdict.UNSUPPORTED_CONTENT_TYPE,
                        detail=f"허용되지 않는 contentType: {spec.primary.content_type!r}",
                    )
                auxiliary_objects = tuple(sorted(spec.auxiliary_objects))
                if tuple(name for name, _ in auxiliary_objects) != tuple(
                    sorted(artifact.auxiliary_files)
                ):
                    return ArtifactResult(
                        ProcessingJobVerdict.ARTIFACT_MANIFEST_REQUIRED,
                        detail="auxiliary object bindings must exactly match auxiliaryFiles",
                    )
                for name, binding in auxiliary_objects:
                    expected = build_processing_artifact_object_key(
                        site_id=job.site_id,
                        job_id=job_id,
                        artifact_id=artifact.artifact_id,
                        filename=name,
                        lease_generation=lease_fence.lease_generation,
                    )
                    if binding.object_key != expected:
                        return ArtifactResult(
                            ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION,
                            detail=(
                                f"auxiliary objectKey for {name!r} is not the current "
                                "generation upload target"
                            ),
                        )
                    if binding.content_type not in ALLOWED_CONTENT_TYPES:
                        return ArtifactResult(
                            ProcessingJobVerdict.UNSUPPORTED_CONTENT_TYPE,
                            detail=f"허용되지 않는 contentType: {binding.content_type!r}",
                        )
                try:
                    candidate = CandidateArtifact(
                        artifact=artifact,
                        worker_instance_id=lease_fence.worker_instance_id,
                        lease_acquisition_id=lease_fence.lease_acquisition_id,
                        lease_generation=lease_fence.lease_generation,
                        primary=spec.primary,
                        auxiliary_files=auxiliary_objects,
                    )
                except ArtifactManifestError as exc:
                    return ArtifactResult(
                        ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION, detail=str(exc)
                    )
                existing = next(
                    (
                        item
                        for item in job.artifact_candidates
                        if item.lease_generation == lease_fence.lease_generation
                        and item.artifact.artifact_id == artifact.artifact_id
                    ),
                    None,
                )
                if existing is not None:
                    if existing == candidate:
                        return ArtifactResult(
                            ProcessingJobVerdict.ARTIFACT_REGISTERED,
                            artifact=artifact,
                            candidate=existing,
                        )
                    return ArtifactResult(
                        ProcessingJobVerdict.DUPLICATE_ARTIFACT,
                        detail=(
                            "같은 generation/artifactId가 다른 provenance 또는 digest로 재등록됐다"
                        ),
                    )
                if verdict is not None:
                    return ArtifactResult(verdict, detail=detail)
                if self._artifact_storage_observer is None:
                    return ArtifactResult(ProcessingJobVerdict.STORAGE_UNAVAILABLE)
                accepted_observations = []
                for filename, binding in ((None, spec.primary), *auxiliary_objects):
                    grant = self._artifact_upload_grants.get(
                        (job_id, lease_fence.lease_generation, artifact.artifact_id, filename)
                    )
                    if grant is None or grant.binding != binding:
                        return ArtifactResult(
                            ProcessingJobVerdict.ARTIFACT_UPLOAD_GRANT_REQUIRED,
                            detail="object has no exact durable upload grant",
                        )
                    try:
                        observed = self._artifact_storage_observer.observe_object(
                            binding.object_key
                        )
                    except EvidenceStorageError:
                        return ArtifactResult(ProcessingJobVerdict.STORAGE_UNAVAILABLE)
                    if not observed.exists:
                        return ArtifactResult(ProcessingJobVerdict.ARTIFACT_STORAGE_OBJECT_MISSING)
                    if (
                        observed.object_key != binding.object_key
                        or observed.sha256 is None
                        or observed.size_bytes is None
                        or observed.content_type is None
                    ):
                        return ArtifactResult(ProcessingJobVerdict.ARTIFACT_STORAGE_UNVERIFIABLE)
                    if observed.sha256 != binding.sha256:
                        return ArtifactResult(ProcessingJobVerdict.ARTIFACT_STORAGE_DIGEST_MISMATCH)
                    if observed.size_bytes != binding.size_bytes:
                        return ArtifactResult(ProcessingJobVerdict.ARTIFACT_STORAGE_SIZE_MISMATCH)
                    if observed.content_type != binding.content_type:
                        return ArtifactResult(
                            ProcessingJobVerdict.ARTIFACT_STORAGE_CONTENT_TYPE_MISMATCH
                        )
                    accepted_observations.append(
                        AcceptedArtifactObjectObservation(filename=filename, binding=binding)
                    )
            if verdict is not None:
                return ArtifactResult(verdict, detail=detail)

            raw: dict[str, Any] = {
                "kind": "processing-artifact-registered",
                "ts": iso_utc(now),
                "jobId": job_id,
                "artifactId": artifact.artifact_id,
                "artifact": processing_artifact_wire_dict(artifact),
                "registeredBy": registered_by,
            }
            if candidate is not None:
                raw["candidate"] = candidate.to_wire()
                raw["acceptedObjectObservations"] = [
                    observation.to_wire() for observation in accepted_observations
                ]
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ArtifactResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            if candidate is None:
                updated = replace(job, artifacts=(*job.artifacts, artifact), updated_at=now)
            else:
                updated = replace(
                    job,
                    artifact_candidates=(*job.artifact_candidates, candidate),
                    manifest_aware=True,
                    updated_at=now,
                )
            self._jobs[job_id] = updated
            return ArtifactResult(
                ProcessingJobVerdict.ARTIFACT_REGISTERED,
                artifact=artifact,
                candidate=candidate,
            )

    def acquire_lease(
        self,
        job_id: str,
        *,
        now: datetime,
        worker_instance_id: str | None = None,
        lease_acquisition_id: str | None = None,
        mode: LeaseMode = LeaseMode.CLAIM,
        lease_generation: int | None = None,
        authenticated_actor_id: str | None = None,
        worker_id: str | None = None,
        ttl: timedelta = DEFAULT_LEASE_TTL,
    ) -> ProcessingJobResult:
        """CLAIM idempotently or RENEW the exact current generation.

        ``worker_id`` is a temporary in-process compatibility path for legacy
        generation-zero tests/readers.  HTTP and all production workers use the
        explicit instance/acquisition/mode fields.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            job = self._jobs.get(job_id)
            if job is None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if not self._record_is_visible_locked(job):
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if job.status not in _ACTIVE_STATUSES:
                return ProcessingJobResult(
                    ProcessingJobVerdict.JOB_NOT_ACTIVE,
                    detail=f"작업이 {job.status.value} 상태다 — 끝난 작업은 잡을 수 없다",
                )
            current = job.lease
            if worker_instance_id is None:
                if worker_id is None:
                    return ProcessingJobResult(
                        ProcessingJobVerdict.LEASE_FENCE_REQUIRED,
                        record=job,
                        detail="worker instance/acquisition identity is required",
                    )
                denial = check_lease(current, worker_id=worker_id, now=now)
                renewing = current is not None and denial is None
                if denial is LeaseDenialReason.HELD_BY_ANOTHER:
                    assert current is not None
                    return ProcessingJobResult(
                        ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER,
                        record=job,
                        detail=f"다른 legacy 워커({current.worker_id})가 이 작업을 쥐고 있다",
                    )
                new_lease = next_lease(
                    worker_id=worker_id,
                    now=now,
                    ttl=ttl,
                    granted_at=current.granted_at if renewing and current else None,
                )
                raw: dict[str, Any] = {
                    "kind": "processing-job-leased",
                    "ts": iso_utc(now),
                    "jobId": job_id,
                    "workerId": worker_id,
                    "expiresAt": iso_utc(new_lease.expires_at),
                    "renewal": renewing,
                }
                verdict = (
                    ProcessingJobVerdict.LEASE_RENEWED if renewing else ProcessingJobVerdict.LEASED
                )
            else:
                if lease_acquisition_id is None:
                    return ProcessingJobResult(
                        ProcessingJobVerdict.LEASE_FENCE_REQUIRED,
                        record=job,
                        detail="leaseAcquisitionId is required",
                    )
                requested_generation = lease_generation if lease_generation is not None else 1
                requested_fence = LeaseFence(
                    worker_instance_id,
                    lease_acquisition_id,
                    requested_generation,
                )
                if not requested_fence.is_well_formed():
                    return ProcessingJobResult(
                        ProcessingJobVerdict.LEASE_FENCE_REQUIRED,
                        record=job,
                        detail="worker/acquisition IDs must be UUIDv4 and generation positive",
                    )
                binding = self._lease_acquisitions.get(lease_acquisition_id)
                if binding is not None and binding[:3] != (
                    job_id,
                    worker_instance_id,
                    authenticated_actor_id,
                ):
                    if mode is LeaseMode.RENEW and binding[0:2] == (
                        job_id,
                        worker_instance_id,
                    ):
                        return ProcessingJobResult(
                            ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER,
                            record=job,
                            detail="lease fence is bound to another authenticated principal",
                        )
                    return ProcessingJobResult(
                        ProcessingJobVerdict.IDEMPOTENCY_CONFLICT,
                        record=job,
                        detail="leaseAcquisitionId is already bound to another operation",
                    )
                if mode is LeaseMode.CLAIM:
                    if lease_generation is not None:
                        return ProcessingJobResult(
                            ProcessingJobVerdict.LEASE_FENCE_REQUIRED,
                            record=job,
                            detail="CLAIM must not submit a server lease generation",
                        )
                    if binding is not None:
                        claimed = binding[3]
                        if (
                            current is not None
                            and current.lease_acquisition_id == lease_acquisition_id
                            and current.worker_instance_id == worker_instance_id
                            and current.lease_generation == claimed.lease_generation
                            and current.is_active(now)
                        ):
                            # Lost response / concurrent duplicate: exact durable
                            # acquisition result, no append and no self-fence.
                            return ProcessingJobResult(ProcessingJobVerdict.LEASED, record=job)
                        return ProcessingJobResult(
                            ProcessingJobVerdict.STALE_ACQUISITION,
                            record=job,
                            detail="이 acquisition은 만료됐거나 더 높은 generation으로 대체됐다",
                        )
                    if current is not None and current.is_active(now):
                        return ProcessingJobResult(
                            ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER,
                            record=job,
                            detail=(
                                f"다른 worker instance가 {iso_utc(current.expires_at)}까지 "
                                "이 작업을 쥐고 있다"
                            ),
                        )
                    generation = self._lease_generation_highwater.get(job_id, 0) + 1
                    new_lease = next_lease(
                        worker_instance_id=worker_instance_id,
                        lease_acquisition_id=lease_acquisition_id,
                        lease_generation=generation,
                        authenticated_actor_id=authenticated_actor_id,
                        now=now,
                        ttl=ttl,
                    )
                    raw = {
                        "kind": "processing-job-leased",
                        "ts": iso_utc(now),
                        "jobId": job_id,
                        "expiresAt": iso_utc(new_lease.expires_at),
                        **lease_raw_fields(lease=new_lease, mode=LeaseMode.CLAIM),
                    }
                    verdict = ProcessingJobVerdict.LEASED
                else:
                    if lease_generation is None:
                        return ProcessingJobResult(
                            ProcessingJobVerdict.LEASE_FENCE_REQUIRED,
                            record=job,
                            detail="RENEW requires leaseGeneration",
                        )
                    denial = check_lease(
                        current,
                        fence=requested_fence,
                        authenticated_actor_id=authenticated_actor_id,
                        now=now,
                    )
                    if denial is not None:
                        return ProcessingJobResult(
                            ProcessingJobVerdict.STALE_LEASE_GENERATION,
                            record=job,
                            detail="RENEW fence is stale, expired, or not current",
                        )
                    assert current is not None
                    new_lease = next_lease(
                        worker_instance_id=current.worker_instance_id,
                        lease_acquisition_id=current.lease_acquisition_id,
                        lease_generation=current.lease_generation,
                        authenticated_actor_id=current.authenticated_actor_id,
                        now=now,
                        ttl=ttl,
                        granted_at=current.granted_at,
                    )
                    raw = {
                        "kind": "processing-job-leased",
                        "ts": iso_utc(now),
                        "jobId": job_id,
                        "expiresAt": iso_utc(new_lease.expires_at),
                        **lease_raw_fields(lease=new_lease, mode=LeaseMode.RENEW),
                    }
                    verdict = ProcessingJobVerdict.LEASE_RENEWED
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            if new_lease.lease_generation > 0 and mode is LeaseMode.CLAIM:
                self._lease_generation_highwater[job_id] = new_lease.lease_generation
                assert new_lease.lease_acquisition_id is not None
                self._lease_acquisitions[new_lease.lease_acquisition_id] = (
                    job_id,
                    new_lease.worker_instance_id,
                    new_lease.authenticated_actor_id,
                    new_lease,
                )
            updated = replace(
                job,
                lease=new_lease,
                manifest_aware=job.manifest_aware or new_lease.lease_generation > 0,
            )
            self._jobs[job_id] = updated
            return ProcessingJobResult(verdict, record=updated)

    @staticmethod
    def _check_lease_locked(
        job: ProcessingJobRecord,
        *,
        now: datetime,
        worker_id: str | None = None,
        lease_fence: LeaseFence | None = None,
        authenticated_actor_id: str | None = None,
    ) -> tuple[ProcessingJobVerdict, str] | None:
        """이 워커가 지금 이 작업을 쥐고 있는가 — 워커 행위의 공통 관문.

        ``/input``·실행 상태 보고·산출물 등록이 전부 이 함수를 지난다. 각 경로가
        자기 조건문을 갖고 있으면 새 경로가 생길 때 빠뜨리기 쉽다.
        """
        denial = check_lease(
            job.lease,
            worker_id=worker_id,
            fence=lease_fence,
            authenticated_actor_id=authenticated_actor_id,
            now=now,
        )
        if denial is LeaseDenialReason.MISSING_OR_EXPIRED:
            if lease_fence is not None and job.lease is not None:
                return (
                    ProcessingJobVerdict.STALE_LEASE_GENERATION,
                    "lease generation이 만료되어 더 이상 authoritative하지 않다",
                )
            return (
                ProcessingJobVerdict.LEASE_REQUIRED,
                "이 작업을 쥐고 있지 않다 — POST /v1/processing-jobs/{jobId}/lease 로 "
                "먼저 잡는다(만료됐다면 다시 잡는다)",
            )
        if denial is LeaseDenialReason.HELD_BY_ANOTHER:
            assert job.lease is not None  # HELD_BY_ANOTHER only when a lease exists
            if lease_fence is not None:
                return (
                    ProcessingJobVerdict.STALE_LEASE_GENERATION,
                    "lease fence가 현재 authoritative owner와 다르다",
                )
            return (
                ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER,
                f"다른 워커({job.lease.worker_id})가 이 작업을 쥐고 있다",
            )
        if denial is LeaseDenialReason.STALE_ACQUISITION:
            return (
                ProcessingJobVerdict.STALE_ACQUISITION,
                "lease acquisition identity가 현재 owner와 다르다",
            )
        if denial in {
            LeaseDenialReason.STALE_GENERATION,
            LeaseDenialReason.INVALID_FENCE,
        }:
            return (
                ProcessingJobVerdict.STALE_LEASE_GENERATION,
                "lease generation이 현재 owner와 다르거나 fence가 유효하지 않다",
            )
        return None

    def input_for(
        self,
        job_id: str,
        *,
        now: datetime,
        worker_id: str | None = None,
        lease_fence: LeaseFence | None = None,
        authenticated_actor_id: str | None = None,
    ) -> JobInputResult:
        """워커가 실행에 필요한 것 — 사양 + 읽어야 할 파일 목록.

        **활성(QUEUED·RUNNING) 작업만** 내준다. 끝난 작업의 원본 다운로드 URL 을
        계속 발급하면 종료가 접근 종료를 뜻하지 않게 된다.

        번들은 봉인돼 있으므로 여기서 다시 digest 를 대조하지 않는다 — 봉인 후
        미디어 집합은 바뀌지 않고(``source_media._replay_registration`` 이
        봉인 후 등록 자체를 거부한다), 발급 시점 digest 가 그대로 유효하다.

        **lease 를 쥔 워커만** 받을 수 있다 — 이게 없으면 워커 토큰 하나로 활성
        작업 전체의 원본 사진을 열람할 수 있다(jobId 가 추측 가능하다).
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return JobInputResult(ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL)
            if not self._record_is_visible_locked(record):
                return JobInputResult(ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL)
            if record.status not in _ACTIVE_STATUSES:
                return JobInputResult(
                    ProcessingJobVerdict.JOB_NOT_ACTIVE,
                    detail=(
                        f"작업이 {record.status.value} 상태다 — 끝난 작업의 원본은 "
                        "다시 내주지 않는다"
                    ),
                )
            denied = self._check_lease_locked(
                record, worker_id=worker_id, lease_fence=lease_fence,
                authenticated_actor_id=authenticated_actor_id, now=now
            )
            if denied is not None:
                return JobInputResult(denied[0], detail=denied[1])
            bundle = self._source_media.get(record.mission_id)
        if bundle is None:  # pragma: no cover - 발급이 번들 존재를 이미 강제한다
            return JobInputResult(
                ProcessingJobVerdict.UNKNOWN_MISSION,
                detail="이 작업의 원본 번들을 찾을 수 없다",
            )
        # 산출물의 crs 는 워커가 지어내거나 processing_params 로 자기 신고하지
        # 않는다 — 현장 등록 시점에 이미 확정된 값을 Core 가 읽어 준다(발급
        # 시점 반출 판정이 site_store 를 읽는 것과 같은 원칙, _residency_of).
        site = self._sites.get(record.site_id)
        site_crs = str(site.site_frame.get("crs")) if site is not None and site.site_frame else None
        return JobInputResult(
            ProcessingJobVerdict.INPUT_READY,
            record=record,
            media=bundle.media,
            site_crs=site_crs,
            ground_control=bundle.ground_control,
        )

    def verify_input(
        self,
        job_id: str,
        measurements: Sequence[SourceMediaMeasurement],
        *,
        verified_by: str,
        lease_fence: LeaseFence,
        now: datetime,
    ) -> VerificationResult | ProcessingJobResult:
        """Verify this job's sealed input under its current lease fence.

        The processing-store lock remains held through the source journal
        append, so an expiry claimant cannot install generation N+1 between
        fence validation and the durable measurement record.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or not self._record_is_visible_locked(job):
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if job.status not in _ACTIVE_STATUSES:
                return ProcessingJobResult(
                    ProcessingJobVerdict.JOB_NOT_ACTIVE,
                    detail=f"작업이 {job.status.value} 상태다",
                )
            denied = self._check_lease_locked(
                job,
                lease_fence=lease_fence,
                authenticated_actor_id=verified_by,
                now=now,
            )
            if denied is not None:
                return ProcessingJobResult(denied[0], record=job, detail=denied[1])
            return self._source_media.verify(
                job.mission_id,
                measurements,
                verified_by=verified_by,
                now=now,
            )

    def _active_job_locked(self, mission_id: str) -> ProcessingJobRecord | None:
        for record in self._jobs.values():
            if record.mission_id == mission_id and record.status in _ACTIVE_STATUSES:
                return record
        return None

    def _organization_id_for_mission(self, mission_id: str) -> str | None:
        """Read organization ownership from the Mission authority, never a job claim.

        ProcessingJob intentionally does not duplicate ``organizationId`` in
        its journal (INV-060).  SourceMediaStore owns the MissionStore through
        which every source bundle was admitted; this narrow read keeps that
        existing authority boundary while the resource gate needs a same-org
        count.
        """
        mission = self._source_media._mission_store.get(mission_id)  # noqa: SLF001
        return mission.organization_id if mission is not None else None

    def _active_job_count_for_organization_locked(self, organization_id: str) -> int:
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

    def list_pending(self, *, now: datetime, limit: int = 50) -> list[ProcessingJobRecord]:
        """``QUEUED`` + **lease 가 만료된 ``RUNNING``** 작업, 오래된 것부터(FIFO) —
        워커가 다음에 잡을 후보를 고르는 표면(모듈 docstring "이 모듈이 하지
        않는 것 — 큐에서 작업을 꺼내오지 않는다" 의 그 pull 표면을 여기서
        만든다, ``processing-controller`` 패키지의 ``worker.py``/``runner.py``).

        **왜 만료된 ``RUNNING`` 도 후보다**: ``acquire_lease`` 자체는 이미
        "만료된 lease 는 없는 것과 같다 — 죽은 워커의 작업은 별도 조치 없이
        만료 후 회수된다"고 설계돼 있다(이 클래스 docstring, ``JobLease.
        is_active``). 그런데 이 표면이 처음엔 ``QUEUED`` 로만 좁혀져 있었다 —
        그러면 워커를 죽인 뒤 아무도 그 jobId 를 다시 ``acquire_lease`` 하도록
        시키지 않으므로, 이미 있는 회수 메커니즘이 후보 목록에서 걸러져
        무의미해진다. 워커 하나가 재구성 도중 죽으면 그 임무는 lease 가
        영원히 살아 있는 것처럼 보여, 재처리 작업 발급마저 막힌다(``issue()``
        의 "임무당 활성 작업 1건" 게이트) — 첫 유료 파일럿처럼 장시간
        무인 운영에서 반드시 만날 상황이다.

        활성 lease 를 쥔 ``RUNNING``(다른 워커가 지금 살아서 돌리는 중)은
        여전히 제외한다 — 살아있는 lease 를 밀어내는 것은 이 함수의 일이
        아니고, ``acquire_lease`` 가 그 경우 ``LEASE_HELD_BY_ANOTHER`` 로
        정확히 거부한다. ``SUCCEEDED``·``FAILED``·``CANCELLED`` 는 여전히
        나오지 않는다.

        재등록 시 중복(``DUPLICATE_ARTIFACT``)의 여지는 남는다 — 죽은
        워커가 산출물 등록 도중(드문 창) 죽었다면 회수한 워커가 그 몇 건에서
        막혀 ``FAILED`` 로 재수렴할 수 있다. 그래도 그 결과는 "영원히 멈춤"
        보다 낫다 — 사유가 로그·``detail`` 에 남고, 사람이 개입할 신호가
        생긴다. 산출물 등록을 재개 가능하게 만드는 것(부분 성공 이어받기)은
        별도 결정 사안이다.
        """
        if limit < 0:
            raise ValueError(f"limit 은 음수일 수 없다: {limit}")
        with self._lock:
            records = [
                r
                for r in self._jobs.values()
                if is_claimable(r.status, r.lease, now) and self._record_is_visible_locked(r)
            ]
        ordered = sorted(records, key=lambda r: (r.issued_at, r.job_id))
        return ordered[:limit]

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


def _residency_of(site: Any) -> DataResidency:
    """현장의 반출 선언 — 미선언은 **반출 불가**로 읽는다(fail-closed).

    현장 자체가 조회되지 않는 경우도 같다. 임무 번들이 site_id 를 갖고 있는데
    그 현장이 없다면 원장이 이상한 것이고, 그 상태에서 반출을 허용할 근거는
    어디에도 없다.
    """
    if site is None or site.data_residency is None:
        return DataResidency(egress_allowed=False, jurisdiction="UNDECLARED")
    return DataResidency.model_validate(site.data_residency)


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class ProcessingJobRequest(CamelModel):
    """새 발급 요청 — Core가 소유한 처리 프로필 ID만 담는다.

    ``input``·``dataResidency``·``billing``·``status`` 필드가 의도적으로 없다.
    입력은 봉인된 번들이, 반출 허용은 현장이, 과금은 종료 보고가 정한다 —
    ``extra="forbid"`` 가 body 에 실어 보낸 위조를 거부한다(``sites.py``
    ``SiteTransitionRequest`` 의 ``actor`` 와 같은 관용구).

    과거 raw provider/engine 원장은 Store가 ``LEGACY_UNMANAGED``로 계속 재생한다.
    하지만 HTTP에서 새 unmanaged 작업을 만드는 것은 그 마이그레이션 경계가
    아니다. 새 작업은 반드시 versioned profile snapshot과 digest를 갖는다.
    """

    processing_profile_id: str = Field(min_length=1)


class ProcessingJobTransitionRequest(CamelModel):
    """상태 전이 요청 — ``actor`` 는 Principal 에서만 취득한다."""

    target_status: ProcessingJobStatus
    detail: str | None = None


class ArtifactUploadUrlRequest(CamelModel):
    """산출물 바이트를 올릴 자리 요청 — **객체 키를 담을 자리가 없다**.

    ``ProcessingArtifactRequest`` 가 계보 앵커를 못 싣게 한 것과 같은 관용구다.
    키를 요청이 정하면 워커가 버킷의 임의 경로를 지정할 수 있고, 그러면
    "서버가 정한 자리에만 쓴다"를 코드가 매번 기억해야 한다 — 자리를 없애면
    기억할 것이 없다.
    """

    artifact_id: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    # 다중 파일 산출물(mesh 등)의 부속 파일 자리를 받을 때만 채운다 — None 이면
    # 주 파일 자리(기존 동작과 동일, mesh-multi-file-artifact-persistence).
    filename: str | None = None


class ArtifactUploadUrlResponse(CamelModel):
    verdict: str
    object_key: str | None = None
    upload_url: str | None = None
    expires_at: datetime | None = None
    required_headers: dict[str, str] | None = None
    detail: str | None = None


class ArtifactObjectBindingRequest(CamelModel):
    """Exact object identity returned by Core's fenced upload authority."""

    object_key: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    content_type: str = Field(min_length=1)

    def to_domain(self) -> ArtifactObjectBinding:
        return ArtifactObjectBinding(
            object_key=self.object_key,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            content_type=self.content_type,
        )


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


class ProcessingArtifactRequest(CamelModel):
    """산출물 등록 요청 — **계보 앵커를 담을 자리가 없다**.

    계약의 ``lineage`` 를 중첩 객체로 받지 않고 ``authority``·``derivedFrom``
    두 필드로 펼친 이유가 이것이다. 중첩으로 받으면 ``sourceDigest`` 를 실을
    자리가 생기고, 그러면 "무시한다"는 규칙을 코드가 기억해야 한다 — 자리를
    없애면 기억할 것이 없다(``ProcessingJobRequest`` 와 같은 관용구).
    ``jobId`` 도 경로에서만 온다.
    """

    artifact_id: str = Field(min_length=1)
    kind: ProcessingArtifactKind
    authority: LineageAuthority
    derived_from: list[str] = Field(default_factory=list)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    format: str = Field(min_length=1)
    # nullable 필수 — 생략과 명시적 null 을 구분한다(processing_artifact.py).
    crs: str | None = None
    gsd: float | None = Field(default=None, gt=0)
    # 계약 모델을 그대로 쓴다 — 아래 ``vertical_reference`` 주석과 같은 이유다.
    # 예전에는 ``ArtifactAccuracyRequest`` 라는 요청 전용 사본이 있었고, 그 사본이
    # 정확히 예고된 대로 정본과 갈라졌다(2026-08-18 적대적 검증): ``checkpointRmseM``
    # 에 ``ge=0`` 이 빠져 음수가 통과했고, 무엇보다 핸들러 본문에서 계약 모델을
    # 만들다 ``ValueError`` 가 나 **422 가 아니라 500** 이 나갔다 — 워커의
    # ``core_client`` 는 비-JSON 응답을 ``NON_JSON_RESPONSE`` 로 싸므로 운영자가
    # "생산자의 영구 계약 위반"과 "Core 장애"를 구분할 수 없었다. 계약 모델을
    # 요청 자리에 두면 FastAPI 가 요청 검증 단계에서 422 를 내고, 같은 validator 가
    # journal 재생에서도 다시 돈다.
    accuracy: ArtifactAccuracy | None = None
    # PATH_SAFE_IDENTIFIER_PATTERN 재사용(SSOT) — 등록 시점에 여기서 거부되지
    # 않으면 build_processing_artifact_object_key 가 다운로드 시점에만 거부해
    # "등록은 됐는데 영구히 다운로드 불가한 산출물"이 durable 하게 남는다
    # (reviewer 지적 C1, 2026-08-08 — 이전엔 검증이 없으면서 다운로드 핸들러
    # 주석만 "등록 시점에 이미 검증됐다"고 잘못 단언했다).
    auxiliary_files: list[Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN.pattern)]] = (
        Field(default_factory=list)
    )
    # 선택 입력(v1.2). 요청 전용 사본을 두지 않고 계약 모델을 그대로 쓴다 — 이 값은
    # 요청이 덜어낼 필드가 하나도 없는 순수 값 객체라, 사본을 두면 정본과 갈라질
    # 자리만 생긴다(계약 패키지가 VerticalReference 를 SSOT 로 세운 이유 그대로).
    #
    # 안 주면 None 이고, Core 는 그것을 어떤 기본값으로도 채우지 않는다.
    # "옛 워커가 안 실어 보냈다"와 "이 산출물은 타원체고다"는 다른 사실이고,
    # 후자를 Core 가 대신 주장하면 설계 대비 비교가 그 가정 위에서 숫자를 낸다.
    vertical_reference: VerticalReference | None = None
    primary_object: ArtifactObjectBindingRequest
    auxiliary_objects: dict[
        Annotated[str, Field(pattern=PATH_SAFE_IDENTIFIER_PATTERN.pattern)],
        ArtifactObjectBindingRequest,
    ] = Field(default_factory=dict)


class ProcessingArtifactMutationResponse(CamelModel):
    verdict: str
    artifact: dict[str, Any] | None = None
    detail: str | None = None


class JobInputMediaView(CamelModel):
    """워커가 읽어야 할 파일 1건 — **신고값(sha256·해상도)이 없다.**

    없는 것이 이 모델의 요점이다. 워커가 정답을 알면 읽지 않고 되읊을 수 있고,
    그러면 실측 대조가 형식이 된다(``source_media.py`` "워커에게 신고값을 주지
    않는다"). 워커는 URL 로 바이트를 받아 스스로 재고, Core 가 대조한다.
    """

    media_id: str
    object_key: str
    download_url: str
    expires_at: datetime


class JobInputGroundControlView(CamelModel):
    """워커가 기준점 파일을 받아갈 자리 — 사진과 같은 방식(presigned GET)."""

    crs: str
    sha256: str
    download_url: str
    expires_at: datetime


class JobInputView(CamelModel):
    """작업 입력 전체 — 무엇으로 돌릴지 + 어떤 파일을 읽을지."""

    job_id: str
    mission_id: str
    site_id: str
    status: str
    provider: str
    engine_version: str
    engine_digest: str
    execution_locus: str
    processing_params: dict[str, Any]
    processing_profile_id: str | None
    processing_profile_digest: str | None
    processing_profile_classification: str
    source_bundle_digest: str
    image_count: int
    media: list[JobInputMediaView]
    # 현장 등록 시점의 CRS — 산출물 등록 시 그대로 싣는다. null 이면 현장
    # 원장이 이상 상태다(발급이 이미 site 존재를 강제하므로 정상 경로에서는
    # 나타나지 않는다).
    site_crs: str | None
    # 기준점 파일이 붙어 있으면 그 좌표계와 다운로드 URL. null 이면 안 붙은
    # 조사이고, 워커는 엔진에 아무것도 넘기지 않는다(기존 동작 그대로).
    ground_control: JobInputGroundControlView | None = None


class JobInputResponse(CamelModel):
    verdict: str
    input: JobInputView | None = None
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


class PendingProcessingJobView(CamelModel):
    """워커가 다음에 잡을 후보 1건 — **최소 노출**이다.

    ``PROCESSING_WORK`` 는 ``MISSIONS_READ`` 를 포함하지 않는다(``auth.py``) —
    워커가 이 표면에서 임무·현장·계약 내용까지 보게 하면 그 경계가 여기서
    새 나간다. ``jobId`` 로 lease 를 잡은 **다음**에야 ``/input`` 이 그 작업의
    전체 사양을 준다(``get_processing_job_input`` 과 동일 원칙).
    """

    job_id: str
    issued_at: datetime


class PendingProcessingJobListResponse(CamelModel):
    jobs: list[PendingProcessingJobView]


class ProcessingJobMutationResponse(CamelModel):
    verdict: str
    job: ProcessingJobView | None = None
    detail: str | None = None
    reason_code: str | None = None


class ProcessingProfileListResponse(CamelModel):
    """Issued profiles, never an editable configuration surface."""

    profiles: list[dict[str, Any]]


class ProcessingResourcePolicyListResponse(CamelModel):
    """Global Core policy discovery; authentication is required, not site access."""

    current_policy_id: str
    policies: list[dict[str, Any]]


def _required_worker_fence(
    worker_instance_id: Annotated[
        str | None, Header(alias="X-KSI-Worker-Instance-Id")
    ] = None,
    lease_acquisition_id: Annotated[
        str | None, Header(alias="X-KSI-Lease-Acquisition-Id")
    ] = None,
    lease_generation: Annotated[
        int | None, Header(alias="X-KSI-Lease-Generation", ge=1)
    ] = None,
) -> LeaseFence:
    if (
        worker_instance_id is None
        or lease_acquisition_id is None
        or lease_generation is None
    ):
        raise HTTPException(status_code=409, detail="LEASE_FENCE_REQUIRED")
    fence = LeaseFence(worker_instance_id, lease_acquisition_id, lease_generation)
    if not fence.is_well_formed():
        raise HTTPException(
            status_code=409,
            detail=(
                "LEASE_FENCE_REQUIRED: UUIDv4 worker/acquisition and positive generation required"
            ),
        )
    return fence


def _optional_worker_fence(
    worker_instance_id: str | None,
    lease_acquisition_id: str | None,
    lease_generation: int | None,
) -> LeaseFence | None:
    if worker_instance_id is None and lease_acquisition_id is None and lease_generation is None:
        return None
    if worker_instance_id is None or lease_acquisition_id is None or lease_generation is None:
        raise HTTPException(status_code=409, detail="LEASE_FENCE_REQUIRED")
    fence = LeaseFence(worker_instance_id, lease_acquisition_id, lease_generation)
    if not fence.is_well_formed():
        raise HTTPException(status_code=409, detail="LEASE_FENCE_REQUIRED")
    return fence


def _set_lease_response_headers(response: Response, lease: JobLease | None) -> None:
    if lease is None or lease.fence is None:
        return
    response.headers["X-KSI-Worker-Instance-Id"] = lease.worker_instance_id
    response.headers["X-KSI-Lease-Acquisition-Id"] = lease.lease_acquisition_id or ""
    response.headers["X-KSI-Lease-Generation"] = str(lease.lease_generation)
    response.headers["X-KSI-Lease-Expires-At"] = iso_utc(lease.expires_at)


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


# 모듈 수준 싱글턴 — B008 회피(source_media.py 의 동일 관습).
_require_processing_job_issue = require_permission_any(
    Permission.MISSIONS_ISSUE, Permission.EDGE_SOURCE_MEDIA_WRITE
)


def build_processing_jobs_router(
    store: ProcessingJobStore,
    storage: EvidenceStorage,
    site_lifecycle: SpatialModelLifecycle | None = None,
) -> APIRouter:
    """``site_lifecycle`` 이 주어지면 재구성 신호가 현장 상태를 전진시킨다(ADR-KSI-019 G1).

    선택 인자인 이유는 하위호환이 아니라 조립의 정직성이다 — ``SiteStore`` 없이
    조립된 앱에서는 전진시킬 대상이 없다. 그리고 **전진 결과는 이 라우터의 응답을
    절대 바꾸지 않는다**: 현장 상태가 어긋났다는 이유로 워커의 재구성 성공 보고가
    실패하면 되돌릴 수 없는 계산 결과가 유실된다(``SpatialModelLifecycle`` docstring).
    """
    if isinstance(storage, ObjectStorageObservationPort):
        store.set_artifact_storage_observer(storage)
    router = APIRouter(tags=["processing-jobs"])

    @router.post(
        "/v1/missions/{mission_id}/processing-jobs",
        response_model=ProcessingJobMutationResponse,
        status_code=201,
    )
    def issue_processing_job(
        mission_id: str,
        request: ProcessingJobRequest,
        response: Response,
        principal: Principal = Depends(_require_processing_job_issue),  # noqa: B008
    ) -> ProcessingJobMutationResponse:
        if not store.processing_profile_issuance_enabled:
            _record_processing_job_admission(
                ProcessingJobResult(ProcessingJobVerdict.PROCESSING_PROFILE_ISSUANCE_DISABLED)
            )
            response.status_code = _STATUS[
                ProcessingJobVerdict.PROCESSING_PROFILE_ISSUANCE_DISABLED
            ]
            return ProcessingJobMutationResponse(
                verdict=ProcessingJobVerdict.PROCESSING_PROFILE_ISSUANCE_DISABLED.value,
                detail="KSI 표준 처리 프로필 발급은 현재 read-only rollback 상태다",
            )
        try:
            spec = store.resolve_processing_profile(request.processing_profile_id)
        except UnknownProcessingProfileError:
            _record_processing_job_admission(
                ProcessingJobResult(ProcessingJobVerdict.UNKNOWN_PROCESSING_PROFILE)
            )
            response.status_code = _STATUS[ProcessingJobVerdict.UNKNOWN_PROCESSING_PROFILE]
            return ProcessingJobMutationResponse(
                verdict=ProcessingJobVerdict.UNKNOWN_PROCESSING_PROFILE.value,
                detail="알 수 없는 processingProfileId다 — Core registry에서 발급된 값만 쓴다",
            )
        result = store.issue(
            mission_id,
            spec,
            issued_by=principal.principal_id,
            now=datetime.now(UTC),
            caller_device_id=(
                principal.device_id if principal.kind is PrincipalKind.EDGE_DEVICE else None
            ),
        )
        _record_processing_job_admission(result)
        if (
            site_lifecycle is not None
            and result.verdict is ProcessingJobVerdict.ISSUED
            and result.record is not None
        ):
            # 재구성 작업이 만들어졌다 = 처리가 시작됐다 → BASELINE_MAPPING →
            # MODEL_PROCESSING. **반환값을 의도적으로 무시한다** — 전진 실패가 이
            # 응답을 바꾸면 안 된다(결과는 SITE_AUTO_ADVANCES metric 과 로그에 남는다).
            site_lifecycle.advance_for_job_status(
                result.record.site_id,
                ProcessingJobStatus.QUEUED,
                job_id=result.record.job_id,
                now=datetime.now(UTC),
            )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ProcessingJobVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ProcessingJobMutationResponse(
            verdict=result.verdict.value,
            job=_to_view(result.record, input_verified=store.is_input_verified(result.record))
            if result.record is not None
            else None,
            detail=result.detail,
            reason_code=result.reason_code,
        )

    @router.get(
        "/v1/processing-jobs",
        response_model=PendingProcessingJobListResponse,
    )
    def list_pending_processing_jobs(
        limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
        _principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> PendingProcessingJobListResponse:
        """워커가 다음에 잡을 후보 목록 — ``QUEUED`` + lease 만료된 ``RUNNING``,
        오래된 것부터(FIFO). 후자는 죽은 워커가 쥐고 있던 작업을 다른 워커가
        회수하는 경로다(``ProcessingJobStore.list_pending`` docstring 참조).

        경로가 ``/v1/processing-jobs/{job_id}`` 와 겹치지 않는다 — 이건 뒤에
        segment 가 없는 컬렉션 경로다. **사람은 이 표면을 쓰지 않는다**
        (``PROCESSING_WORK`` 게이트, ``list_for_mission`` 과 달리
        ``MISSIONS_READ`` 가 아니다) — 워커가 어떤 임무·현장의 작업인지까지
        알 필요가 없고, 알면 그 자체가 최소권한을 벗어난다.
        """
        return PendingProcessingJobListResponse(
            jobs=[
                PendingProcessingJobView(job_id=r.job_id, issued_at=r.issued_at)
                for r in store.list_pending(now=datetime.now(UTC), limit=limit)
            ]
        )

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

    @router.post(
        "/v1/processing-jobs/{job_id}/transitions",
        response_model=ProcessingJobMutationResponse,
    )
    def transition_processing_job(
        job_id: str,
        request: ProcessingJobTransitionRequest,
        response: Response,
        worker_instance_id: Annotated[str | None, Header(alias="X-KSI-Worker-Instance-Id")] = None,
        lease_acquisition_id: Annotated[
            str | None, Header(alias="X-KSI-Lease-Acquisition-Id")
        ] = None,
        lease_generation: Annotated[
            int | None, Header(alias="X-KSI-Lease-Generation", ge=1)
        ] = None,
        principal: Principal = Depends(require_principal()),  # noqa: B008
    ) -> ProcessingJobMutationResponse:
        # 요구 권한이 **대상 상태마다 다르다**(모듈 docstring) — 문 앞의
        # require_permission 하나로 표현할 수 없어 여기서 표를 조회한다.
        required = _TRANSITION_PERMISSION[request.target_status]
        if required not in principal_permissions(principal):
            raise HTTPException(
                status_code=403,
                detail=f"{request.target_status.value} 로의 전이 권한이 없다",
            )
        requires_lease = request.target_status is not ProcessingJobStatus.CANCELLED
        lease_fence = _optional_worker_fence(
            worker_instance_id, lease_acquisition_id, lease_generation
        )
        if requires_lease and lease_fence is None:
            raise HTTPException(status_code=409, detail="LEASE_FENCE_REQUIRED")
        result = store.transition(
            job_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
            now=datetime.now(UTC),
            # 사람의 취소만 lease 를 요구하지 않는다 — 워커가 죽어 lease 가 살아
            # 있는 동안 취소가 막히면, 정확히 취소가 필요한 상황에서 막힌다.
            requires_lease=requires_lease,
            lease_fence=lease_fence,
        )
        if (
            site_lifecycle is not None
            and result.verdict is ProcessingJobVerdict.TRANSITIONED
            and result.record is not None
        ):
            # 원본 산출물을 가진 SUCCEEDED = 공간모델이 생겼다 → MODEL_PROCESSING →
            # MODEL_VALIDATION. 발급 훅과 같은 이유로 반환값을 무시한다.
            site_lifecycle.advance_for_job_status(
                result.record.site_id,
                request.target_status,
                job_id=result.record.job_id,
                now=datetime.now(UTC),
            )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ProcessingJobVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ProcessingJobMutationResponse(
            verdict=result.verdict.value,
            job=_to_view(result.record, input_verified=store.is_input_verified(result.record))
            if result.record is not None
            else None,
            detail=result.detail,
        )

    @router.post(
        "/v1/processing-jobs/{job_id}/lease",
        response_model=ProcessingJobMutationResponse,
        status_code=201,
    )
    def acquire_processing_job_lease(
        job_id: str,
        response: Response,
        worker_instance_id: Annotated[str, Header(alias="X-KSI-Worker-Instance-Id")],
        lease_acquisition_id: Annotated[str, Header(alias="X-KSI-Lease-Acquisition-Id")],
        lease_mode: Annotated[LeaseMode, Header(alias="X-KSI-Lease-Mode")] = LeaseMode.CLAIM,
        lease_generation: Annotated[
            int | None, Header(alias="X-KSI-Lease-Generation", ge=1)
        ] = None,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ProcessingJobMutationResponse:
        """작업 하나를 잡는다(같은 워커의 재호출은 갱신 = heartbeat).

        이 표면이 워커 행위의 관문이다 — ``/input``·실행 상태 보고·산출물 등록은
        전부 lease 를 쥔 워커만 할 수 있다.
        """
        result = store.acquire_lease(
            job_id,
            worker_instance_id=worker_instance_id,
            lease_acquisition_id=lease_acquisition_id,
            mode=lease_mode,
            lease_generation=lease_generation,
            authenticated_actor_id=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ProcessingJobVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        if result.record is not None:
            _set_lease_response_headers(response, result.record.lease)
        return ProcessingJobMutationResponse(
            verdict=result.verdict.value,
            job=(
                _to_view(result.record, input_verified=store.is_input_verified(result.record))
                if result.record is not None
                else None
            ),
            detail=result.detail,
        )

    @router.get("/v1/processing-jobs/{job_id}/input", response_model=JobInputResponse)
    def get_processing_job_input(
        job_id: str,
        response: Response,
        lease_fence: LeaseFence = Depends(_required_worker_fence),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> JobInputResponse:
        """워커가 자기 작업의 사양과 원본 다운로드 URL 을 받아간다.

        이 표면이 워커의 **유일한** 읽기 경로다 — ``PROCESSING_WORK`` 는
        ``MISSIONS_READ`` 를 포함하지 않으므로 워커는 임무·현장·다른 작업을
        볼 수 없다. 여기서 주는 것도 그 작업이 가리키는 번들 하나뿐이다.

        presign 실패는 ``STORAGE_UNAVAILABLE`` 로 격하한다 — 일부 URL 만 담긴
        응답을 주면 워커가 그 부분집합만 읽고 검증을 시도해 ``COVERAGE_
        INCOMPLETE`` 로 도는 낭비가 생긴다(``source_media`` 의 항목별 격하와
        다른 선택인 이유: 저긴 등록이 이미 durable 하지만 여긴 전부 아니면
        의미가 없다).
        """
        result = store.input_for(
            job_id, lease_fence=lease_fence,
            authenticated_actor_id=principal.principal_id, now=datetime.now(UTC)
        )
        if result.verdict is not ProcessingJobVerdict.INPUT_READY or result.record is None:
            response.status_code = _STATUS[result.verdict]
            return JobInputResponse(verdict=result.verdict.value, detail=result.detail)

        record = result.record
        now = datetime.now(UTC)
        try:
            media = [
                JobInputMediaView(
                    media_id=item.media_id,
                    object_key=item.object_key,
                    download_url=storage.presigned_get(item.object_key, ttl=DEFAULT_VIEW_TTL),
                    expires_at=expires_at(now, DEFAULT_VIEW_TTL),
                )
                for item in result.media
            ]
            # 기준점 파일도 같은 try 안에서 발급한다 — 사진만 받고 기준점을 못
            # 받은 채로 돌리면 엔진이 UTM 성과를 내고, 그 실패는 몇 분 뒤
            # 비교 단계에서야 드러난다. 전부 아니면 의미가 없다(위 docstring).
            ground_control = (
                JobInputGroundControlView(
                    crs=result.ground_control.crs,
                    sha256=result.ground_control.sha256,
                    download_url=storage.presigned_get(
                        result.ground_control.object_key, ttl=DEFAULT_VIEW_TTL
                    ),
                    expires_at=expires_at(now, DEFAULT_VIEW_TTL),
                )
                if result.ground_control is not None
                else None
            )
        except EvidenceStorageError:
            logger.warning("처리 작업 입력 URL 발급 실패: jobId=%s", job_id)
            response.status_code = _STATUS[ProcessingJobVerdict.STORAGE_UNAVAILABLE]
            response.headers["Retry-After"] = "30"
            return JobInputResponse(
                verdict=ProcessingJobVerdict.STORAGE_UNAVAILABLE.value,
                detail="원본 다운로드 URL 발급에 실패했다 — 잠시 후 재시도한다",
            )

        return JobInputResponse(
            verdict=result.verdict.value,
            input=JobInputView(
                job_id=record.job_id,
                mission_id=record.mission_id,
                site_id=record.site_id,
                status=record.status.value,
                provider=record.spec.provider.value,
                engine_version=record.spec.engine_version,
                engine_digest=record.spec.engine_digest,
                execution_locus=record.spec.execution_locus.value,
                processing_params=record.spec.processing_params,
                processing_profile_id=record.processing_profile_id,
                processing_profile_digest=record.processing_profile_digest,
                processing_profile_classification=record.processing_profile_classification,
                source_bundle_digest=record.input.source_bundle_digest,
                image_count=record.input.image_count,
                media=media,
                site_crs=result.site_crs,
                ground_control=ground_control,
            ),
        )

    @router.post(
        "/v1/processing-jobs/{job_id}/verify-input",
        response_model=SourceMediaVerifyResponse,
        status_code=201,
    )
    def verify_processing_job_input(
        job_id: str,
        request: SourceMediaVerifyRequest,
        response: Response,
        lease_fence: LeaseFence = Depends(_required_worker_fence),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> SourceMediaVerifyResponse:
        result = store.verify_input(
            job_id,
            [
                SourceMediaMeasurement(
                    media_id=item.media_id,
                    sha256=item.sha256,
                    size_bytes=item.bytes,
                    width=item.width,
                    height=item.height,
                    capture_time=item.capture_time.to_domain(),
                )
                for item in request.measurements
            ],
            verified_by=principal.principal_id,
            lease_fence=lease_fence,
            now=datetime.now(UTC),
        )
        if isinstance(result, ProcessingJobResult):
            response.status_code = _STATUS[result.verdict]
            return SourceMediaVerifyResponse(verdict=result.verdict.value, detail=result.detail)
        verify_status = {
            SourceBundleVerifyVerdict.VERIFIED: 201,
            SourceBundleVerifyVerdict.ALREADY_VERIFIED: 200,
            SourceBundleVerifyVerdict.MISMATCH: 422,
            SourceBundleVerifyVerdict.COVERAGE_INCOMPLETE: 422,
            SourceBundleVerifyVerdict.UNKNOWN_MISSION: 404,
            SourceBundleVerifyVerdict.BUNDLE_NOT_SEALED: 409,
            SourceBundleVerifyVerdict.STORE_UNAVAILABLE: 503,
        }
        response.status_code = verify_status[result.verdict]
        if result.verdict is SourceBundleVerifyVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        comparison = result.comparison
        return SourceMediaVerifyResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            bundle=_to_bundle_view(result.bundle) if result.bundle is not None else None,
            mismatched=list(comparison.mismatched) if comparison else [],
            missing=list(comparison.missing) if comparison else [],
            unexpected=list(comparison.unexpected) if comparison else [],
        )

    @router.post(
        "/v1/processing-jobs/{job_id}/artifacts/upload-url",
        response_model=ArtifactUploadUrlResponse,
        status_code=201,
    )
    def issue_artifact_upload_url(
        job_id: str,
        request: ArtifactUploadUrlRequest,
        response: Response,
        lease_fence: LeaseFence = Depends(_required_worker_fence),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ArtifactUploadUrlResponse:
        """워커가 산출물 바이트 업로드를 위한 자격을 받는다.

        **바이트는 Core 를 통과하지 않는다.** 워커가 presigned PUT 으로 스토리지에
        직접 쓴다. 이 API는 업로드할 바이트를 검사하거나 재해시하지 않으며,
        ``source_media`` 업로드처럼 바이트 위치·권한만 정한다.

        **grant의 영속 경계**: 1) journal append 실패면 durable grant는 만들지 못하고
        ``STORE_UNAVAILABLE`` 를 돌려준다. 2) journal append는 됐으나 presign URL
        생성이 실패하면 결과는 ``STORAGE_UNAVAILABLE`` 이며, 동일 바인딩은 후속 재요청에서
        다시 쓰면 재사용되고 바인딩 충돌은 거부된다. 3) 이후 업로드 직후의 직접 PUT
        실패/끊김은 Core 가 모니터링하지 않으며, 등록 단계에서만 신뢰할 수 있는
        객체 메타데이터(객체키·sha256·크기·content-type) 대조로 누락/불일치를 거부한다.
        반환되는 ``uploadUrl`` 자체는 원장에 저장되지 않는 만료성 capability이며,
        만료 뒤 동일 바인딩으로 재요청하면 기존 durable grant에 새 URL을 발급한다.

        **등록(``POST .../artifacts``)과 분리한 이유**: 등록은 계보/lineage를 durable로
        수락하는 단계다. 업로드는 원장에 바이트를 쓰지 않고, 실제 수락 시에는
        스토리지 HEAD/메타데이터를 통해 grant 바인딩(객체키·sha256·크기·content-type)을
        대조해 맞는지 확인한다. Core는 바이트를 읽거나 재해시하지 않는다.
        """
        if request.content_type not in ALLOWED_CONTENT_TYPES:
            response.status_code = _STATUS[ProcessingJobVerdict.UNSUPPORTED_CONTENT_TYPE]
            return ArtifactUploadUrlResponse(
                verdict=ProcessingJobVerdict.UNSUPPORTED_CONTENT_TYPE.value,
                detail=f"허용되지 않는 contentType: {request.content_type!r}",
            )

        result = store.artifact_upload_target(
            job_id,
            artifact_id=request.artifact_id,
            lease_fence=lease_fence,
            authenticated_actor_id=principal.principal_id,
            now=datetime.now(UTC),
            filename=request.filename,
            sha256=request.sha256,
            size_bytes=request.size_bytes,
            content_type=request.content_type,
        )
        if result.verdict is not ProcessingJobVerdict.UPLOAD_READY or result.object_key is None:
            response.status_code = _STATUS[result.verdict]
            return ArtifactUploadUrlResponse(verdict=result.verdict.value, detail=result.detail)

        now = datetime.now(UTC)
        try:
            if not isinstance(storage, DigestBoundEvidenceStorage):
                raise EvidenceStorageError(
                    "processing artifact storage lacks digest-bound PUT support"
                )
            capability = storage.presigned_put_bound_digest(
                result.object_key,
                content_type=request.content_type,
                content_digest=request.sha256,
                ttl=DEFAULT_UPLOAD_TTL,
            )
        except EvidenceStorageError:
            logger.warning(
                "산출물 업로드 URL 발급 실패: jobId=%s artifactId=%s",
                job_id,
                request.artifact_id,
            )
            response.status_code = _STATUS[ProcessingJobVerdict.STORAGE_UNAVAILABLE]
            response.headers["Retry-After"] = "30"
            return ArtifactUploadUrlResponse(
                verdict=ProcessingJobVerdict.STORAGE_UNAVAILABLE.value,
                detail="산출물 업로드 URL 발급에 실패했다 — 잠시 후 재시도한다",
            )

        return ArtifactUploadUrlResponse(
            verdict=result.verdict.value,
            object_key=result.object_key,
            upload_url=capability.upload_url,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
            required_headers=capability.required_headers,
        )

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

    @router.post(
        "/v1/processing-jobs/{job_id}/artifacts",
        response_model=ProcessingArtifactMutationResponse,
        status_code=201,
    )
    def register_processing_artifact(
        job_id: str,
        request: ProcessingArtifactRequest,
        response: Response,
        lease_fence: LeaseFence = Depends(_required_worker_fence),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ProcessingArtifactMutationResponse:
        spec = ArtifactSpec(
            artifact_id=request.artifact_id,
            kind=request.kind,
            authority=request.authority,
            derived_from=tuple(request.derived_from),
            digest=request.digest,
            format=request.format,
            crs=request.crs,
            gsd=request.gsd,
            auxiliary_files=tuple(request.auxiliary_files),
            vertical_reference=request.vertical_reference,
            accuracy=request.accuracy,
            primary=request.primary_object.to_domain(),
            auxiliary_objects=tuple(
                (name, binding.to_domain())
                for name, binding in sorted(request.auxiliary_objects.items())
            ),
        )
        result = store.register_artifact(
            job_id,
            spec,
            registered_by=principal.principal_id,
            lease_fence=lease_fence,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ProcessingJobVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ProcessingArtifactMutationResponse(
            verdict=result.verdict.value,
            artifact=(
                processing_artifact_wire_dict(result.artifact)
                if result.artifact is not None
                else None
            ),
            detail=result.detail,
        )

    return router


def build_processing_profiles_router(store: ProcessingJobStore) -> APIRouter:
    """Expose Core-owned profile snapshots for UI and local uploader discovery."""
    router = APIRouter(tags=["processing-profiles"])

    @router.get("/v1/processing-profiles", response_model=ProcessingProfileListResponse)
    def list_processing_profiles(
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ProcessingProfileListResponse:
        del principal
        return ProcessingProfileListResponse(profiles=store.processing_profiles.wire_list())

    return router


def build_processing_resource_policies_router(
    registry: ProcessingResourcePolicyRegistry,
) -> APIRouter:
    """Expose global Core-owned admission policies without an edit surface."""
    router = APIRouter(tags=["processing-resource-policies"])

    @router.get(
        "/v1/processing-resource-policies",
        response_model=ProcessingResourcePolicyListResponse,
    )
    def list_processing_resource_policies(
        _principal: Principal = Depends(require_principal()),  # noqa: B008
    ) -> ProcessingResourcePolicyListResponse:
        # Policies contain no tenant-owned input, job, site, media, or location
        # data. Any authenticated principal may discover the fixed envelope.
        return ProcessingResourcePolicyListResponse(
            current_policy_id=registry.current_policy_id,
            policies=registry.wire_list(),
        )

    return router


def mount_processing_jobs(
    app: FastAPI,
    store: ProcessingJobStore,
    storage: EvidenceStorage,
    site_lifecycle: SpatialModelLifecycle | None = None,
) -> None:
    """앱에 처리 작업 라우터를 장착한다.

    ``storage`` 가 필요해진 것은 워커 입력 수신(``GET .../input``)이 원본
    다운로드 URL 을 발급하기 때문이다 — B2 시점에는 이 표면이 presigned URL 을
    전혀 내주지 않아 스토리지를 몰라도 됐다.

    ``site_lifecycle`` 을 주면 재구성 발급·성공이 현장 상태를 자동 전진시킨다
    (ADR-KSI-019 G1). 안 주면 예전과 같이 아무것도 전진시키지 않는다.
    """
    app.state.processing_job_store = store
    app.include_router(build_processing_jobs_router(store, storage, site_lifecycle))
    app.include_router(build_processing_profiles_router(store))
    app.include_router(
        build_processing_resource_policies_router(store.processing_resource_policies)
    )


__all__ = [
    "DEFAULT_LEASE_TTL",
    "UNMETERED_AT_ISSUE",
    "ArtifactResult",
    "ArtifactSpec",
    "IllegalJobTransitionError",
    "JobLease",
    "JobSpec",
    "PendingProcessingJobListResponse",
    "PendingProcessingJobView",
    "ProcessingArtifactMutationResponse",
    "ProcessingArtifactRequest",
    "ProcessingJobListResponse",
    "ProcessingJobMutationResponse",
    "ProcessingProfileListResponse",
    "ProcessingResourceLimitReason",
    "ProcessingResourcePolicyListResponse",
    "ProcessingJobRecord",
    "ProcessingJobRecoveryError",
    "ProcessingJobRequest",
    "ProcessingJobResult",
    "ProcessingJobStore",
    "ProcessingJobTransitionRequest",
    "ProcessingJobVerdict",
    "ProcessingJobView",
    "UnbackedSuccessError",
    "assert_job_transition",
    "assert_succeeded_is_backed",
    "build_job_id",
    "build_processing_jobs_router",
    "build_processing_profiles_router",
    "build_processing_resource_policies_router",
    "mount_processing_jobs",
]
