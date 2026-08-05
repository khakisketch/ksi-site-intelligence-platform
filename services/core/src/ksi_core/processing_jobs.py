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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
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
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ksi_core.auth import (
    Permission,
    Principal,
    principal_permissions,
    require_permission,
    require_principal,
)
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import (
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
    expires_at,
)
from ksi_core.identifiers import is_path_safe_identifier
from ksi_core.source_media import SourceMediaRecord

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.sites import SiteStore
    from ksi_core.source_media import SourceMediaStore

logger = logging.getLogger(__name__)

_NOT_FOUND_DETAIL = "해당 처리 작업을 찾을 수 없다"
_STORE_UNAVAILABLE_DETAIL = "journal 봉인됨 — 재시작 필요"

# 발급 시점 billing 의 rateBasis. "아직 재지 않았다"를 값 자체가 말한다 —
# creditsCharged=0 만으로는 온프렘 무료 실행과 구분되지 않는다.
UNMETERED_AT_ISSUE = "unmetered-at-issue"

_ACTIVE_STATUSES = frozenset({ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING})

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

    **산출물(authority=source).** 파생물만 있는 성공은 원본 없이 파생을 주장하는
    상태다(ADR-KSI-003, 모듈 docstring).

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
    if not any(a.lineage.authority is LineageAuthority.SOURCE for a in artifacts):
        raise UnbackedSuccessError(
            "INV-051 — 이 작업에는 authority=source 산출물이 없다. 재구성이 "
            "성공했다면 원본(포인트클라우드·카메라 포즈 계열) 산출물이 최소 "
            "1건 등록돼 있어야 한다 — 파생물만으로는 완료를 주장할 수 없다"
        )
    if not input_verified:
        raise UnbackedSuccessError(
            "이 작업의 원본 번들이 아직 실측 대조되지 않았다 — 전 바이트를 읽어 "
            "sha256·해상도를 신고값과 대조한 보고(POST /v1/missions/{id}/"
            "source-media/verify)가 있어야 성공으로 인정한다. 대조 없이 성공하면 "
            "과금 근거가 끝까지 업로더 신고값으로 남는다"
        )


def assert_job_transition(
    before: ProcessingJobStatus, after: ProcessingJobStatus
) -> None:
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
    # INV-051 — 원본 산출물 없이 SUCCEEDED 를 주장했다.
    UNBACKED_SUCCESS = "UNBACKED_SUCCESS"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"

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


_STATUS: dict[ProcessingJobVerdict, int] = {
    ProcessingJobVerdict.ISSUED: 201,
    ProcessingJobVerdict.ALREADY_ISSUED: 200,
    ProcessingJobVerdict.TRANSITIONED: 200,
    ProcessingJobVerdict.UNKNOWN_MISSION: 404,
    ProcessingJobVerdict.UNKNOWN_JOB: 404,
    ProcessingJobVerdict.BUNDLE_NOT_SEALED: 422,
    ProcessingJobVerdict.EGRESS_NOT_ALLOWED: 422,
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
        }
        return sha256_digest(canonical_payload_bytes(payload))


@dataclass(frozen=True, slots=True)
class JobLease:
    """작업 하나를 쥔 워커 — **만료는 저장된 플래그가 아니라 시각 비교다.**

    ``released``/``expired`` 같은 불리언을 두지 않는 것이 의도다. 그런 필드는
    누군가 갱신해줘야 참이 되고, 그 갱신을 빠뜨리면 죽은 워커가 영원히 살아
    있는 것으로 보인다 — 시간축 상태를 실체화한 불리언으로 들고 있으면 그
    불리언과 시계가 어긋나는 순간이 반드시 온다. 여기서는 ``expires_at`` 만
    남기고 :meth:`is_active` 가 매번 ``now`` 로 판정한다.

    재생에도 같은 성질이 필요하다 — journal 을 며칠 뒤에 재생하면 그때의
    ``now`` 로 판정되어 자동으로 만료된 상태가 된다(재생 시점에 별도 만료 처리를
    할 필요가 없다).
    """

    worker_id: str
    granted_at: datetime
    expires_at: datetime

    def is_active(self, now: datetime) -> bool:
        return now < self.expires_at

    def held_by(self, worker_id: str, now: datetime) -> bool:
        return self.is_active(now) and self.worker_id == worker_id


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
    # 마지막으로 발급된 lease. 만료 여부는 이 값이 아니라 ``now`` 가 정한다.
    lease: JobLease | None = None

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


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    verdict: ProcessingJobVerdict
    artifact: ProcessingArtifact | None = None
    detail: str | None = None


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
    detail: str | None = None


def build_job_id(mission_id: str, sequence: int) -> str:
    """``{missionId}-pj{n}`` — 임무 안에서 결정적이고 사람이 읽을 수 있다.

    ``mission_id`` 는 이미 경로-안전이 강제된 값이므로(mission_records
    ``validate_mission_identifiers``) 여기서 만들어진 jobId 도 경로-안전이다.
    """
    return f"{mission_id}-pj{sequence}"


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


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
        raise ProcessingJobRecoveryError(
            f"재생: {field_name} 가 naive datetime — jobId={job_id}"
        )
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
    ) -> None:
        self._journal = journal
        self._source_media = source_media_store
        self._sites = site_store
        self._lock = threading.Lock()
        self._jobs: dict[str, ProcessingJobRecord] = {}
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
            elif kind == "processing-job-leased":
                self._replay_lease(raw)
            else:  # pragma: no cover - 방어적, journal 오염이 아닌 이상 도달 불가
                raise ProcessingJobRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")

    def _replay_issued(self, raw: dict[str, Any]) -> None:
        job_id = raw["jobId"]
        if job_id in self._jobs:
            raise ProcessingJobRecoveryError(f"재생: jobId 중복 발급 레코드 — jobId={job_id}")
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
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ProcessingJobRecoveryError(
                f"재생: 발급 레코드가 계약을 만족하지 않는다 — jobId={job_id}: {exc}"
            ) from exc
        if (
            spec.execution_locus is ExecutionLocus.VENDOR_CLOUD
            and not residency.egress_allowed
        ):
            # live 는 이 조합을 절대 발급하지 않는다 — 있다면 journal 조작이거나
            # 발급 게이트가 깨진 것이다(source_media._replay_seal 과 같은 원칙).
            raise ProcessingJobRecoveryError(
                f"재생: INV-050 위반 레코드 — 반출 미허용 현장의 vendor_cloud 작업: jobId={job_id}"
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
        try:
            # 재생이 live 와 같은 게이트를 다시 태운다 — 산출물 레코드를 지우고
            # SUCCEEDED 전이만 남겨 근거 없는 성공을 되살릴 수 없다.
            assert_succeeded_is_backed(
                after, current.artifacts, input_verified=self.is_input_verified(current)
            )
        except UnbackedSuccessError as exc:
            raise ProcessingJobRecoveryError(
                f"재생: 근거 없는 SUCCEEDED 레코드 — jobId={job_id}: {exc}"
            ) from exc
        self._jobs[job_id] = replace(
            current,
            status=after,
            updated_at=_require_aware_iso(raw["ts"], "ts", job_id),
            terminal_detail=raw.get("detail"),
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
        try:
            artifact = ProcessingArtifact.model_validate(raw["artifact"])
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
        verdict, detail = self._check_artifact_identity_locked(job, artifact)
        if verdict is not None:
            raise ProcessingJobRecoveryError(
                f"재생: 산출물 레코드가 등록 게이트를 통과하지 못한다 "
                f"({verdict.value}) — jobId={job_id}: {detail}"
            )
        self._jobs[job_id] = replace(job, artifacts=(*job.artifacts, artifact))

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
        self._jobs[job_id] = replace(
            job,
            lease=JobLease(
                worker_id=raw["workerId"],
                granted_at=_require_aware_iso(raw["ts"], "ts", job_id),
                expires_at=_require_aware_iso(raw["expiresAt"], "expiresAt", job_id),
            ),
        )

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

    @staticmethod
    def _check_artifact_identity_locked(
        job: ProcessingJobRecord, artifact: ProcessingArtifact
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
        known = {a.artifact_id for a in job.artifacts}
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
        self, mission_id: str, spec: JobSpec, *, issued_by: str, now: datetime
    ) -> ProcessingJobResult:
        """봉인된 번들 위에 처리 작업을 발급한다.

        게이트 순서는 **싼 것부터**다 — 번들 존재/봉인 → INV-050 → 활성 작업
        중복. 반출 위반을 활성 작업 검사보다 먼저 보는 이유는, 두 번째 요청이
        409 를 받아 "중복만 아니면 통과할 것"으로 오해되지 않게 하기 위해서다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            bundle = self._source_media.get(mission_id)
            if bundle is None:
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
            if (
                spec.execution_locus is ExecutionLocus.VENDOR_CLOUD
                and not residency.egress_allowed
            ):
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
                    # 같은 사양 재요청 — 네트워크 재시도가 작업을 복제하지 않는다.
                    # journal 에 다시 쓰지 않는다(새로 기록할 사실이 없다).
                    return ProcessingJobResult(
                        ProcessingJobVerdict.ALREADY_ISSUED, record=active
                    )
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
            sequence = self._sequence.get(mission_id, 0) + 1
            job_id = build_job_id(mission_id, sequence)
            raw: dict[str, Any] = {
                "kind": "processing-job-issued",
                "ts": _iso(now),
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
                "issuedBy": issued_by,
            }
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
            )
            self._jobs[job_id] = record
            self._sequence[mission_id] = sequence
            return ProcessingJobResult(ProcessingJobVerdict.ISSUED, record=record)

    def transition(
        self,
        job_id: str,
        target: ProcessingJobStatus,
        *,
        detail: str | None,
        actor: str,
        now: datetime,
        requires_lease: bool = True,
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
            if requires_lease:
                denied = self._check_lease_locked(current, worker_id=actor, now=now)
                if denied is not None:
                    return ProcessingJobResult(denied[0], record=current, detail=denied[1])
            try:
                assert_job_transition(current.status, target)
            except IllegalJobTransitionError as exc:
                return ProcessingJobResult(
                    ProcessingJobVerdict.ILLEGAL_TRANSITION, detail=str(exc)
                )
            try:
                assert_succeeded_is_backed(
                    target, current.artifacts, input_verified=self.is_input_verified(current)
                )
            except UnbackedSuccessError as exc:
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNBACKED_SUCCESS, detail=str(exc)
                )
            raw: dict[str, Any] = {
                "kind": "processing-job-transitioned",
                "ts": _iso(now),
                "jobId": job_id,
                "before": current.status.value,
                "after": target.value,
                "detail": detail,
                "actor": actor,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            updated = replace(current, status=target, updated_at=now, terminal_detail=detail)
            self._jobs[job_id] = updated
            return ProcessingJobResult(ProcessingJobVerdict.TRANSITIONED, record=updated)

    def register_artifact(
        self, job_id: str, spec: ArtifactSpec, *, registered_by: str, now: datetime
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
                return ArtifactResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if job.status is not ProcessingJobStatus.RUNNING:
                return ArtifactResult(
                    ProcessingJobVerdict.JOB_NOT_RUNNING,
                    detail=(
                        f"작업이 {job.status.value} 상태다 — 산출물은 실행 중인 "
                        "작업에만 등록된다(끝난 작업에 근거를 소급하지 않는다)"
                    ),
                )
            denied = self._check_lease_locked(job, worker_id=registered_by, now=now)
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
                )
            except ValueError as exc:
                return ArtifactResult(
                    ProcessingJobVerdict.ARTIFACT_CONTRACT_VIOLATION, detail=str(exc)
                )
            verdict, detail = self._check_artifact_identity_locked(job, artifact)
            if verdict is not None:
                return ArtifactResult(verdict, detail=detail)

            raw: dict[str, Any] = {
                "kind": "processing-artifact-registered",
                "ts": _iso(now),
                "jobId": job_id,
                "artifactId": artifact.artifact_id,
                "artifact": processing_artifact_wire_dict(artifact),
                "registeredBy": registered_by,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ArtifactResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            self._jobs[job_id] = replace(job, artifacts=(*job.artifacts, artifact), updated_at=now)
            return ArtifactResult(ProcessingJobVerdict.ARTIFACT_REGISTERED, artifact=artifact)

    def acquire_lease(
        self, job_id: str, *, worker_id: str, now: datetime, ttl: timedelta = DEFAULT_LEASE_TTL
    ) -> ProcessingJobResult:
        """작업 하나를 쥔다. 같은 워커의 재호출은 갱신(heartbeat)이다.

        게이트: 활성(QUEUED·RUNNING) 작업만, 그리고 **다른 워커의 유효한 lease 가
        없을 때만**. 만료된 lease 는 없는 것과 같다 — 죽은 워커가 쥔 작업을 회수
        하는 경로가 이것 하나뿐이라, 만료를 별도 명령으로 풀게 하면 아무도 안
        푼 채 작업이 영구히 묶인다.

        갱신도 journal 에 적는다. 다른 append 와 달리 "새로 기록할 사실이 없는
        멱등 재호출"이 아니기 때문이다 — 만료 시각이 실제로 옮겨간다.
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
            if job.status not in _ACTIVE_STATUSES:
                return ProcessingJobResult(
                    ProcessingJobVerdict.JOB_NOT_ACTIVE,
                    detail=f"작업이 {job.status.value} 상태다 — 끝난 작업은 잡을 수 없다",
                )
            current = job.lease
            renewing = current is not None and current.held_by(worker_id, now)
            if current is not None and current.is_active(now) and not renewing:
                return ProcessingJobResult(
                    ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER,
                    record=job,
                    detail=(
                        f"다른 워커({current.worker_id})가 {_iso(current.expires_at)} 까지 "
                        "이 작업을 쥐고 있다 — 만료 후 다시 시도한다"
                    ),
                )
            expires_at = now + ttl
            raw: dict[str, Any] = {
                "kind": "processing-job-leased",
                "ts": _iso(now),
                "jobId": job_id,
                "workerId": worker_id,
                "expiresAt": _iso(expires_at),
                "renewal": renewing,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            updated = replace(
                job,
                lease=JobLease(
                    worker_id=worker_id,
                    granted_at=current.granted_at if renewing and current else now,
                    expires_at=expires_at,
                ),
            )
            self._jobs[job_id] = updated
            return ProcessingJobResult(
                ProcessingJobVerdict.LEASE_RENEWED if renewing else ProcessingJobVerdict.LEASED,
                record=updated,
            )

    @staticmethod
    def _check_lease_locked(
        job: ProcessingJobRecord, *, worker_id: str, now: datetime
    ) -> tuple[ProcessingJobVerdict, str] | None:
        """이 워커가 지금 이 작업을 쥐고 있는가 — 워커 행위의 공통 관문.

        ``/input``·실행 상태 보고·산출물 등록이 전부 이 함수를 지난다. 각 경로가
        자기 조건문을 갖고 있으면 새 경로가 생길 때 빠뜨리기 쉽다.
        """
        lease = job.lease
        if lease is None or not lease.is_active(now):
            return (
                ProcessingJobVerdict.LEASE_REQUIRED,
                "이 작업을 쥐고 있지 않다 — POST /v1/processing-jobs/{jobId}/lease 로 "
                "먼저 잡는다(만료됐다면 다시 잡는다)",
            )
        if lease.worker_id != worker_id:
            return (
                ProcessingJobVerdict.LEASE_HELD_BY_ANOTHER,
                f"다른 워커({lease.worker_id})가 이 작업을 쥐고 있다",
            )
        return None

    def input_for(self, job_id: str, *, worker_id: str, now: datetime) -> JobInputResult:
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
                return JobInputResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            if record.status not in _ACTIVE_STATUSES:
                return JobInputResult(
                    ProcessingJobVerdict.JOB_NOT_ACTIVE,
                    detail=(
                        f"작업이 {record.status.value} 상태다 — 끝난 작업의 원본은 "
                        "다시 내주지 않는다"
                    ),
                )
            denied = self._check_lease_locked(record, worker_id=worker_id, now=now)
            if denied is not None:
                return JobInputResult(denied[0], detail=denied[1])
            bundle = self._source_media.get(record.mission_id)
        if bundle is None:  # pragma: no cover - 발급이 번들 존재를 이미 강제한다
            return JobInputResult(
                ProcessingJobVerdict.UNKNOWN_MISSION,
                detail="이 작업의 원본 번들을 찾을 수 없다",
            )
        return JobInputResult(
            ProcessingJobVerdict.INPUT_READY, record=record, media=bundle.media
        )

    def _active_job_locked(self, mission_id: str) -> ProcessingJobRecord | None:
        for record in self._jobs.values():
            if record.mission_id == mission_id and record.status in _ACTIVE_STATUSES:
                return record
        return None

    def get(self, job_id: str) -> ProcessingJobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_for_mission(self, mission_id: str) -> list[ProcessingJobRecord]:
        """``(issued_at, job_id)`` 결정적 정렬 — 목록 순서가 재기동마다 흔들리지 않는다."""
        with self._lock:
            records = [r for r in self._jobs.values() if r.mission_id == mission_id]
        return sorted(records, key=lambda r: (r.issued_at, r.job_id))


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


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class LicenseBasisRequest(_CamelModel):
    license_id: str = Field(min_length=1)
    tier: str = Field(min_length=1)
    attribution_required: bool


class ProcessingJobRequest(_CamelModel):
    """발급 요청 — **무엇으로 어디서** 돌릴지만 담는다.

    ``input``·``dataResidency``·``billing``·``status`` 필드가 의도적으로 없다.
    입력은 봉인된 번들이, 반출 허용은 현장이, 과금은 종료 보고가 정한다 —
    ``extra="forbid"`` 가 body 에 실어 보낸 위조를 거부한다(``sites.py``
    ``SiteTransitionRequest`` 의 ``actor`` 와 같은 관용구).
    """

    provider: ProcessingProvider
    engine_version: str = Field(min_length=1)
    engine_digest: str = Field(min_length=1)
    execution_locus: ExecutionLocus
    license_basis: LicenseBasisRequest
    processing_params: dict[str, Any] = Field(default_factory=dict)


class ProcessingJobTransitionRequest(_CamelModel):
    """상태 전이 요청 — ``actor`` 는 Principal 에서만 취득한다."""

    target_status: ProcessingJobStatus
    detail: str | None = None


class ArtifactAccuracyRequest(_CamelModel):
    gcp_count: int = Field(ge=0)
    rmse: float = Field(ge=0)
    report_uri: str = Field(min_length=1)


class ProcessingArtifactRequest(_CamelModel):
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
    accuracy: ArtifactAccuracyRequest | None = None


class ProcessingArtifactMutationResponse(_CamelModel):
    verdict: str
    artifact: dict[str, Any] | None = None
    detail: str | None = None


class JobInputMediaView(_CamelModel):
    """워커가 읽어야 할 파일 1건 — **신고값(sha256·해상도)이 없다.**

    없는 것이 이 모델의 요점이다. 워커가 정답을 알면 읽지 않고 되읊을 수 있고,
    그러면 실측 대조가 형식이 된다(``source_media.py`` "워커에게 신고값을 주지
    않는다"). 워커는 URL 로 바이트를 받아 스스로 재고, Core 가 대조한다.
    """

    media_id: str
    object_key: str
    download_url: str
    expires_at: datetime


class JobInputView(_CamelModel):
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
    source_bundle_digest: str
    image_count: int
    media: list[JobInputMediaView]


class JobInputResponse(_CamelModel):
    verdict: str
    input: JobInputView | None = None
    detail: str | None = None


class ProcessingJobView(_CamelModel):
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
    contract: dict[str, Any]
    # 등록된 산출물의 계약 payload 그대로(등록 순). SUCCEEDED 를 받쳐주는 근거가
    # 무엇인지 화면이 상태값 하나가 아니라 계보로 볼 수 있게 한다(INV-051).
    artifacts: list[dict[str, Any]]
    # 지금 이 작업을 쥔 워커와 만료 시각. **만료 여부를 불리언으로 싣지 않는다** —
    # 응답을 만든 순간과 화면이 읽는 순간 사이에 만료될 수 있어서, 그 판정은
    # 시각을 받은 쪽이 자기 시계로 해야 한다(JobLease 와 같은 이유).
    lease_worker_id: str | None
    lease_expires_at: datetime | None


class ProcessingJobListResponse(_CamelModel):
    jobs: list[ProcessingJobView]


class ProcessingJobMutationResponse(_CamelModel):
    verdict: str
    job: ProcessingJobView | None = None
    detail: str | None = None


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
        contract=processing_job_wire_dict(record.to_contract()),
        artifacts=[processing_artifact_wire_dict(a) for a in record.artifacts],
        lease_worker_id=record.lease.worker_id if record.lease is not None else None,
        lease_expires_at=record.lease.expires_at if record.lease is not None else None,
    )


def build_processing_jobs_router(
    store: ProcessingJobStore, storage: EvidenceStorage
) -> APIRouter:
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
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> ProcessingJobMutationResponse:
        spec = JobSpec(
            provider=request.provider,
            engine_version=request.engine_version,
            engine_digest=request.engine_digest,
            execution_locus=request.execution_locus,
            license_basis=LicenseBasis(
                license_id=request.license_basis.license_id,
                tier=request.license_basis.tier,
                attribution_required=request.license_basis.attribution_required,
            ),
            processing_params=request.processing_params,
        )
        result = store.issue(
            mission_id, spec, issued_by=principal.principal_id, now=datetime.now(UTC)
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
        result = store.transition(
            job_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
            now=datetime.now(UTC),
            # 사람의 취소만 lease 를 요구하지 않는다 — 워커가 죽어 lease 가 살아
            # 있는 동안 취소가 막히면, 정확히 취소가 필요한 상황에서 막힌다.
            requires_lease=request.target_status is not ProcessingJobStatus.CANCELLED,
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
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ProcessingJobMutationResponse:
        """작업 하나를 잡는다(같은 워커의 재호출은 갱신 = heartbeat).

        이 표면이 워커 행위의 관문이다 — ``/input``·실행 상태 보고·산출물 등록은
        전부 lease 를 쥔 워커만 할 수 있다.
        """
        result = store.acquire_lease(
            job_id, worker_id=principal.principal_id, now=datetime.now(UTC)
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ProcessingJobVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
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
            job_id, worker_id=principal.principal_id, now=datetime.now(UTC)
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
                    download_url=storage.presigned_get(
                        item.object_key, ttl=DEFAULT_VIEW_TTL
                    ),
                    expires_at=expires_at(now, DEFAULT_VIEW_TTL),
                )
                for item in result.media
            ]
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
                source_bundle_digest=record.input.source_bundle_digest,
                image_count=record.input.image_count,
                media=media,
            ),
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
            accuracy=(
                ArtifactAccuracy(
                    gcp_count=request.accuracy.gcp_count,
                    rmse=request.accuracy.rmse,
                    report_uri=request.accuracy.report_uri,
                )
                if request.accuracy is not None
                else None
            ),
        )
        result = store.register_artifact(
            job_id, spec, registered_by=principal.principal_id, now=datetime.now(UTC)
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


def mount_processing_jobs(
    app: FastAPI, store: ProcessingJobStore, storage: EvidenceStorage
) -> None:
    """앱에 처리 작업 라우터를 장착한다.

    ``storage`` 가 필요해진 것은 워커 입력 수신(``GET .../input``)이 원본
    다운로드 URL 을 발급하기 때문이다 — B2 시점에는 이 표면이 presigned URL 을
    전혀 내주지 않아 스토리지를 몰라도 됐다.
    """
    app.state.processing_job_store = store
    app.include_router(build_processing_jobs_router(store, storage))


__all__ = [
    "DEFAULT_LEASE_TTL",
    "UNMETERED_AT_ISSUE",
    "ArtifactResult",
    "ArtifactSpec",
    "IllegalJobTransitionError",
    "JobLease",
    "JobSpec",
    "ProcessingArtifactMutationResponse",
    "ProcessingArtifactRequest",
    "ProcessingJobListResponse",
    "ProcessingJobMutationResponse",
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
    "mount_processing_jobs",
]
