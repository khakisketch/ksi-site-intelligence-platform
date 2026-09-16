"""Bearer 인증·역할 권한 (ADR-KSI-008, ADR-KSI-024).

## 토큰 원문은 저장하지 않는다

:class:`AuthRegistry` 는 ``sha256(token)`` digest → :class:`Principal` 매핑만
보유한다(조립 시 digest 레코드 주입) — 서버 어디에도 토큰 원문이 남지 않는다.
외부 Operations Console 사람은 OIDC JWT를, 장비·워커는 이 opaque registry를 사용한다.

## Principal 5종 (2-enum 분리 관습)

- ``OPERATOR``(사람): :class:`Role` 필수, ``device_id`` 는 가질 수 없다. 권한은
  모듈 상수 ``_ROLE_PERMISSIONS`` 표 하나로만 결정된다(엔드포인트 산재 금지).
- ``GATEWAY_DEVICE``(RC/Dock): role 없음, ``device_id`` 필수. 짧은 TTL의 연결·
  capability snapshot만 보고하며 Edge ingest 권한을 받지 않는다.
- ``EDGE_DEVICE``(장비): role 없음, ``device_id`` 필수. 권한은 항상 Edge 전용
  최소 집합(ingest·자기 mission pull·자기 evidence write)으로 고정 — role 표와
  무관하다(edge-sync 장착부에서 이 Principal 을 소비한다).
- ``EDGE_ROUTE_OBSERVER``(route health collector): role 없음, ``device_id`` 필수.
  권한은 ``{CAPABILITY_RUNTIME_OBSERVE}`` 하나이며, Core CAP-5 ingress가 자기
  ``EDGE_ROUTE_PORT`` scope와 다시 exact-match한다.
- ``PROCESSING_WORKER``(3D 재구성 워커): role 없음, ``device_id`` 도 없음. 권한은
  항상 ``{PROCESSING_WORK}`` 고정.

## 왜 워커가 별도 종류인가 — ``EDGE_DEVICE`` 재사용 금지

재구성 워커는 비행 장비가 아니다. ``EDGE_DEVICE`` 를 재사용하면 ①워커가
``EDGE_SYNC_INGEST`` 를 얻어 관측 번들을 밀어넣을 수 있고 ②``device_id`` 가
필수라 존재하지 않는 기체 식별자를 지어내야 하며 그 값이 ``eventKey`` 의 경로
세그먼트로 흘러든다. 신원 모델이 다르면 종류를 나눈다.

``PROCESSING_WORK`` 는 어느 :class:`Role` 에도 매핑되지 않는다 — **사람은 이
권한을 가질 수 없다.** 처리 작업의 ``RUNNING``·``SUCCEEDED``·``FAILED`` 는
실제로 엔진을 돌린 주체만 보고할 수 있는 사실이고, 사람이 손으로 찍을 수
있으면 그 상태는 근거가 아니라 주장이 된다(``processing_jobs.py`` 전이 권한표).

## 실패는 fail-closed

- 레지스트리 조립 시 불변식 위반은 :class:`AuthRegistryError` 로 **즉시** 거부한다
  (오염된 레지스트리로 기동하지 않는다).
- 인증 실패(부재/형식오류/미지 토큰/만료/폐기)는 사유를 가리지 않고 **동일한
  일반 문구**의 401 을 반환한다 — detail 로 "토큰이 존재하지만 만료됐다" 같은
  힌트를 주면 토큰 존재 여부를 추정할 수 있는 열거 오라클이 된다(edge_sync.py
  감사 #8 관습).
- 보호 라우트가 ``app.state.auth_registry`` 없이 장착되면 그 자체가 조립 결함이다
  — 조용히 인증을 우회시키지 않고 :class:`RuntimeError` 로 즉시 드러낸다.

## 토큰 만료·회전 — 서명키 회전과 같은 모양(``signing_keys.py`` 참조)

digest 하나가 아니라 ``(digest, status, not_after)`` **레코드 세트**를 받는다 —
회전이 성립하려면 새로 발급한 토큰과, 아직 기기·운영자 손에 남아 있는 이전
토큰이 **겹치는 구간** 동안 함께 유효해야 한다(서명키의 ``ACTIVE`` + 유예기간
``notAfter`` 와 동일한 이유). 그래서 같은 ``principal_id`` 에 대해 서로 다른
digest 여러 개가 동시에 등록될 수 있다 — 단, 가리키는 신원(kind/role/device_id)
이 완전히 같을 때만이다. 신원이 다른데 ``principal_id`` 만 같으면 설정 오사고
(오타로 다른 사람을 같은 id 로 재등록)로 보고 거부한다.

``resolve()`` 는 조회 시점(``now``)에 다음 순서로 판정한다: 미지 digest → 401,
``status=REVOKED`` → 401, ``not_after`` 가 지났으면 → 401(둘 다 "만료됐다"는
힌트 없이 동일 401 문구로 접힌다). 폐기는 :class:`KeyRegistry` 와 같은 이유로
단조 방향이다 — 이 모듈 자체에는 되돌리는 API 를 두지 않는다(회전 절차 문서:
``docs/security/AUTH_TOKEN_ROTATION.md``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator, Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ksi_core.foundation.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from fastapi import FastAPI


class Role(StrEnum):
    """OPERATOR(사람) Principal 의 역할 — 권한은 ``_ROLE_PERMISSIONS`` 표 SSOT.

    3역할(ADR-KSI-015 D1) — 구 5역할 중 현장관리·안전관리·드론운영 3개를
    ``FIELD_OPERATOR`` 하나로 합쳤다. 대시보드가 이미 역할이 아니라 권한으로
    분기하므로 역할 수를 유지할 이득이 없었다(9개 분기 지점 전부 permission
    기반, ADR 본문 참조).
    """

    ADMIN = "ADMIN"
    FIELD_OPERATOR = "FIELD_OPERATOR"
    VIEWER = "VIEWER"


class PrincipalKind(StrEnum):
    """Principal 종류 — 사람·gateway·Edge·route observer·처리 워커는 분리한다."""

    OPERATOR = "OPERATOR"
    GATEWAY_DEVICE = "GATEWAY_DEVICE"
    EDGE_DEVICE = "EDGE_DEVICE"
    EDGE_ROUTE_OBSERVER = "EDGE_ROUTE_OBSERVER"
    PROCESSING_WORKER = "PROCESSING_WORKER"


class TokenStatus(StrEnum):
    """토큰 레코드 상태(``ksi_mission_contracts.signing.KeyStatus`` 와 같은 모양).

    ``REVOKED`` 는 발급 중단이 아니라 검증 거부다 — 이미 배포된 토큰을 무효로
    만드는 유일한 장치(모듈 docstring "토큰 만료·회전" 절 참조).
    """

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class HumanAuthMode(StrEnum):
    """사람 인증 migration 모드. 장비 opaque 자격에는 영향을 주지 않는다."""

    OPAQUE = "OPAQUE"
    DUAL = "DUAL"
    OIDC = "OIDC"


class OidcVerifier(Protocol):
    def verify(self, token: str) -> Principal | None: ...


class Permission(StrEnum):
    """엔드포인트가 요구하는 개별 권한 — role→permission 매핑의 코드셋."""

    SITES_READ = "SITES_READ"
    SITES_WRITE = "SITES_WRITE"
    MISSIONS_READ = "MISSIONS_READ"
    MISSIONS_ISSUE = "MISSIONS_ISSUE"
    EVENTS_READ = "EVENTS_READ"
    EVENTS_TRIAGE = "EVENTS_TRIAGE"
    EDGE_SYNC_INGEST = "EDGE_SYNC_INGEST"
    # Edge device 전용: 서명된 자기 MissionDispatchEnvelope만 pull하고, 자신이
    # projection한 event에만 증거 등록 URL을 받는다. 사람 Role에는 절대 넣지 않는다.
    EDGE_MISSION_PULL = "EDGE_MISSION_PULL"
    EDGE_EVIDENCE_WRITE = "EDGE_EVIDENCE_WRITE"
    # Edge device 전용: 자기 mission_id 범위에서만 원본 사진 배치 등록/봉인 및
    # 재구성 작업 발행. MISSIONS_ISSUE(사람, 아무 mission)보다 좁다 — 라우터가
    # mission.assigned_device_id != principal.device_id 를 UNKNOWN_MISSION 과
    # 같은 404 로 접어 자기 것이 아닌 mission 의 존재 여부를 노출하지 않는다
    # (edge_dispatch.py 의 event 소유권 판정과 동일 관습). 사람 Role 에는 넣지
    # 않는다(자동화 장비 최소권한 원칙, 2026-08-14 risk
    # edge-device-cannot-call-source-media-ingest 해소).
    EDGE_SOURCE_MEDIA_WRITE = "EDGE_SOURCE_MEDIA_WRITE"
    # Edge device 전용: **자기에게 배정된** mission 의 KMZ 바이트 하나만 받는다.
    # ``MISSIONS_READ`` 를 주지 않는 이유가 이 권한의 존재 이유다 — 그 권한은 전
    # 현장의 임무 목록·상세·원본 미디어를 함께 연다. 장비 하나가 뚫리면 그 순간
    # 전 현장 좌표가 새는 것과, 그 장비에 이미 배정된 경로 하나가 새는 것은 다른
    # 크기의 사고다. ``EDGE_SOURCE_MEDIA_WRITE`` 를 ``MISSIONS_ISSUE`` 와 따로
    # 만든 것과 정확히 같은 판단(자동화 장비 최소권한). 범위 좁히기(자기 mission
    # 인가)는 이 권한이 아니라 라우터가 하고, 불일치는 403 이 아니라 404 로 접는다
    # — 403 은 "그 임무는 존재한다"를 알려주는 존재 오라클이다.
    EDGE_MISSION_KMZ_READ = "EDGE_MISSION_KMZ_READ"
    # RC Plus 2 / Dock gateway 전용. Edge ingest 권한과 분리해 Gateway 자격이
    # Manifold EventBundle·원본 미디어를 가장할 수 없게 한다(REQ-SEC-101).
    GATEWAY_CONNECTIVITY_WRITE = "GATEWAY_CONNECTIVITY_WRITE"
    # CAP-5 exact route-port liveness report. Existing Gateway/Edge producers와
    # dedicated Edge route observer만 받으며, evidence/approval/activation을 만들
    # 권한은 전혀 포함하지 않는다. 실제 organization/site/device/route/port 범위는
    # runtime ingress가 trusted Core configuration과 다시 exact-match한다
    # (REQ-ACQ-103, INV-060).
    CAPABILITY_RUNTIME_OBSERVE = "CAPABILITY_RUNTIME_OBSERVE"
    # Gateway 전용: 새 route invocation 직전 CAP-5 projection을 질의한다. 관찰
    # 쓰기와 분리해 observation producer credential이 실행 preflight까지 호출하는
    # 권한 확장을 막는다. 최종 허용은 Core의 Mission scope 대조를 다시 통과한다.
    CAPABILITY_RUNTIME_PREFLIGHT = "CAPABILITY_RUNTIME_PREFLIGHT"
    # 3D 재구성 워커 전용 — 처리 작업의 실행 사실 보고(RUNNING/SUCCEEDED/FAILED)와
    # 산출물 등록. 어느 Role 에도 매핑되지 않는다(모듈 docstring).
    PROCESSING_WORK = "PROCESSING_WORK"
    # blast radius 가 큰 site 전이만 가른다(ADR-KSI-015 D2) — 자율비행 개시
    # (MODEL_VALIDATION→PROVISIONAL_AUTONOMY)·정식 순찰 승인(PROVISIONAL_
    # AUTONOMY→PATROL_READY)·운영중단 진입/복귀(↔SUSPENDED). 대상 전이 집합
    # 자체는 도메인 개념이라 ``ksi_domain.enums.requires_autonomy_approval``
    # 이 SSOT — 이 권한은 그 판정에 매핑되는 권한 코드일 뿐이다(강제 지점은
    # ``ksi_core.sites`` 라우트).
    SITES_AUTONOMY_APPROVE = "SITES_AUTONOMY_APPROVE"
    # 장비 클래스 지원단계 승급(INV-041, MASTER_PRD §23.3/§26.7). SITES_AUTONOMY_
    # APPROVE 와 같은 사유로 ADMIN 에게만 준다 — "이 장비를 상용으로 지원한다"는
    # 선언은 고객 UI 와 계약에 그대로 실리는 안전 주장이고(REQ-MODEL-101,
    # 00_READ_FIRST 구현금지 "미검증 장비를 상용지원으로 표시"), 그 선언을 되돌려도
    # 이미 그 표시를 보고 내린 운용 결정은 되돌아오지 않는다. 강등은 이 권한이
    # 필요하지만(같은 표면) 증거를 요구하지 않는다 — 재검증 실패에 즉시 대응해야
    # 하는 방향에 마찰을 넣지 않는다(capability.assert_support_level_transition).
    EQUIPMENT_SUPPORT_APPROVE = "EQUIPMENT_SUPPORT_APPROVE"
    # Product/HIL capability approval is a durable product authority decision,
    # not evidence verification and not operational activation.  Only ADMIN
    # operators receive it; device/gateway/worker fixed permission sets remain
    # unchanged (REQ-ACQ-103, REQ-SEC-101).
    CAPABILITY_PRODUCT_APPROVE = "CAPABILITY_PRODUCT_APPROVE"
    # Exact deployment activation/suspension/revocation is a separate CAP-4
    # operations authority.  It is intentionally distinct from product/HIL
    # approval even though ADMIN currently receives both permissions.
    CAPABILITY_ACTIVATE = "CAPABILITY_ACTIVATE"
    EXTERNAL_AUTHORITY_MANAGE = "EXTERNAL_AUTHORITY_MANAGE"
    # Durable work roster metadata is deliberately separate from OIDC/AuthRegistry
    # identity provisioning and grants no permission to the roster subject.
    ORGANIZATION_MEMBERS_MANAGE = "ORGANIZATION_MEMBERS_MANAGE"
    WORK_ORDERS_WRITE = "WORK_ORDERS_WRITE"
    REOBSERVATION_APPROVE = "REOBSERVATION_APPROVE"
    COPILOT_QUERY = "COPILOT_QUERY"


@dataclass(frozen=True, slots=True)
class Principal:
    """인증 신원 — OPERATOR만 role, device principal만 device_id를 가진다."""

    principal_id: str
    kind: PrincipalKind
    role: Role | None
    device_id: str | None
    # 기존 단일조직 journal/fixture는 ``legacy``로 replay한다. 신규 production
    # provisioning은 명시적 organizationId를 공급해야 한다(INV-060).
    organization_id: str = "legacy"


@dataclass(frozen=True, slots=True)
class PrincipalTokenRecord:
    """조립 시 주입되는 (digest, Principal, 상태) 레코드 — 토큰 원문은 여기 없다.

    ``status``/``not_after`` 기본값은 "만료·회전 없는 고정 토큰" — 기존 배포
    형식과 완전히 호환된다. 회전 중에는 같은 ``principal_id`` 에 대해 이전
    digest(``not_after`` 로 유예기간 종료 예정) + 새 digest(``not_after=None``)
    두 레코드가 동시에 존재한다(모듈 docstring "토큰 만료·회전" 절).
    """

    token_sha256: str
    principal: Principal
    status: TokenStatus = TokenStatus.ACTIVE
    not_after: datetime | None = None


class AuthRegistryError(ValueError):
    """레지스트리 조립 시 불변식 위반 — 오염된 레지스트리로 기동하지 않는다."""


_TOKEN_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_record(record: PrincipalTokenRecord) -> None:
    """한 레코드의 불변식을 전부 확인한다 — 위반은 :class:`AuthRegistryError`."""
    if not record.token_sha256:
        raise AuthRegistryError("token_sha256 은 빈 문자열일 수 없다")
    if not _TOKEN_SHA256_RE.fullmatch(record.token_sha256):
        raise AuthRegistryError(
            f"token_sha256 은 소문자 64자리 hex 여야 한다 (got {record.token_sha256!r}) — "
            "원문 토큰·대문자·경로 형태는 거부된다"
        )
    if record.not_after is not None and record.not_after.tzinfo is None:
        # naive datetime 은 resolve() 의 만료 비교에서 TypeError 를 유발해
        # fail-closed 보장을 깬다(signing_keys.py 의 같은 검증과 동일 이유).
        raise AuthRegistryError(
            f"{record.principal.principal_id}: not_after 는 tz-aware(UTC) 여야 한다"
        )

    principal = record.principal
    if not principal.principal_id:
        raise AuthRegistryError("principal_id 는 빈 문자열일 수 없다")
    if not principal.organization_id or not is_path_safe_identifier(principal.organization_id):
        raise AuthRegistryError(
            f"{principal.principal_id}: organization_id 는 경로-안전 비공백 식별자여야 한다"
        )
    # lone surrogate 를 조립 시점에 거부한다(2026-08-18). `principal_id` 는 요청으로
    # 조작할 수 없고 `KSI_CORE_PRINCIPAL_TOKENS_JSON` 으로만 들어오는데, `json.loads`
    # 는 `\ud800` 이스케이프를 그대로 살려 넘긴다. 그런 값이 들어오면 그 principal 로
    # 인증한 요청의 **응답 직렬화**가 UnicodeEncodeError 로 터져 500 이 된다(실측:
    # `GET /v1/auth/whoami`). 요청 표면이 아니라 배포 설정 경계의 문제라, 막을 자리도
    # 요청이 아니라 여기다 — 잘못된 설정으로 뜬 서버는 뜨는 순간 실패해야 한다.
    try:
        principal.principal_id.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AuthRegistryError(
            f"principal_id 에 UTF-8 로 표현할 수 없는 문자가 있다 "
            f"({principal.principal_id!r}) — 이 신원으로 인증한 응답이 직렬화되지 않는다"
        ) from exc

    # EDGE_ROUTE_OBSERVER의 principal_id는 CAP-5 observation payload의 exact
    # producer identity이며, 새 dedicated credential을 provisioning하는 경계에서
    # path-safe하게 고정한다. 기존 principal identifier 형식은 호환을 위해 바꾸지
    # 않는다.
    if principal.kind is PrincipalKind.EDGE_ROUTE_OBSERVER and not is_path_safe_identifier(
        principal.principal_id
    ):
        raise AuthRegistryError(
            f"{principal.principal_id}: EDGE_ROUTE_OBSERVER principal_id는 "
            "경로-안전 문자만 허용한다"
        )

    if principal.kind is PrincipalKind.OPERATOR:
        if principal.role is None:
            raise AuthRegistryError(f"{principal.principal_id}: OPERATOR 는 role 이 필수다")
        if principal.device_id is not None:
            raise AuthRegistryError(
                f"{principal.principal_id}: OPERATOR 는 device_id 를 가질 수 없다"
            )
    elif principal.kind in (
        PrincipalKind.GATEWAY_DEVICE,
        PrincipalKind.EDGE_DEVICE,
        PrincipalKind.EDGE_ROUTE_OBSERVER,
    ):
        if principal.role is not None:
            raise AuthRegistryError(
                f"{principal.principal_id}: {principal.kind.value} 는 role 을 가질 수 없다"
            )
        if not principal.device_id:
            raise AuthRegistryError(
                f"{principal.principal_id}: {principal.kind.value} 는 device_id 가 필수다"
            )
        if not is_path_safe_identifier(principal.device_id):
            # device_id 는 그대로 event_key(="{deviceId}::{eventId}")의 절반이
            # 되어 /v1/events/{event_key} 경로 세그먼트로 쓰인다(3차 최종검토
            # P3) — 여기서 막지 않으면 provisioning 은 성공하지만 그 장비의
            # 모든 ingest 가 classify_edge_bundle 의 INVALID_EVENT_IDENTITY
            # 로 영구 거부되는(ACK 불가→큐 포화) 잘못된 경계의 fail-closed 가
            # 만들어진다. 검증은 provisioning 시점(여기)이 옳다.
            raise AuthRegistryError(
                f"{principal.principal_id}: device_id 는 경로-안전 문자만 허용한다"
                " (eventKey 의 경로 세그먼트 절반이 된다)"
            )
    elif principal.kind is PrincipalKind.PROCESSING_WORKER:
        if principal.role is not None:
            raise AuthRegistryError(
                f"{principal.principal_id}: PROCESSING_WORKER 는 role 을 가질 수 없다"
            )
        if principal.device_id is not None:
            # 재구성 워커는 기체가 아니다 — device_id 를 허용하면 존재하지 않는
            # 기체 식별자가 원장에 흘러든다(모듈 docstring).
            raise AuthRegistryError(
                f"{principal.principal_id}: PROCESSING_WORKER 는 device_id 를 가질 수 없다"
            )


class AuthRegistry:
    """sha256(token) digest → (Principal, 상태) 매핑. 토큰 원문은 보유하지 않는다.

    같은 ``principal_id`` 가 여러 digest 로 등록될 수 있다 — **단 가리키는
    신원(``Principal`` 전체)이 완전히 같을 때만이다.** 그게 회전 중 겹침
    구간의 정상 형태다(모듈 docstring). 신원이 다른데 id 만 같으면 설정
    오사고로 보고 거부한다 — 그렇지 않으면 같은 id 아래 서로 다른 권한이
    조용히 뒤섞인다.
    """

    def __init__(self, records: Iterable[PrincipalTokenRecord]) -> None:
        by_digest: dict[str, PrincipalTokenRecord] = {}
        principal_by_id: dict[str, Principal] = {}
        for record in records:
            _validate_record(record)
            if record.token_sha256 in by_digest:
                raise AuthRegistryError(f"token_sha256 중복: {record.token_sha256}")
            principal_id = record.principal.principal_id
            existing = principal_by_id.get(principal_id)
            if existing is not None and existing != record.principal:
                raise AuthRegistryError(
                    f"principal_id {principal_id!r} 가 서로 다른 신원으로 중복 등록됐다 — "
                    "같은 id 는 회전 중인 토큰이라도 kind/role/deviceId 가 완전히 같아야 한다"
                )
            by_digest[record.token_sha256] = record
            principal_by_id[principal_id] = record.principal
        self._by_digest = by_digest

    def resolve(self, token: str, *, now: datetime | None = None) -> Principal | None:
        """제시된 토큰 원문의 sha256 digest 로 조회한다.

        미지 토큰·폐기된(``REVOKED``) 토큰·``not_after`` 가 지난 토큰은 전부
        같은 ``None`` 이다 — 호출부(``_resolve_principal``)가 이를 사유 구분
        없는 동일 401 로 접는다(열거 오라클 방지, 모듈 docstring).
        """
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        record = self._by_digest.get(digest)
        if record is None:
            return None
        if record.status is TokenStatus.REVOKED:
            return None
        check_time = now if now is not None else datetime.now(UTC)
        if record.not_after is not None and check_time > record.not_after:
            return None
        return record.principal


# role → permission 표 하나가 SSOT(ADR-KSI-008 §2, ADR-KSI-015 D1/D2) —
# 엔드포인트별 권한 산재 금지. ADMIN 은 EDGE_SYNC_INGEST 를 제외한 OPERATOR
# 권한 전부(사람은 edge ingest 불가) + SITES_AUTONOMY_APPROVE — 이 권한이
# 없으면 ADMIN 의 권한집합이 FIELD_OPERATOR 와 글자 하나까지 같아져 관리자
# 역할이 라벨로 전락한다(ADR-KSI-015 D2, tests/contract/test_auth.py 구조
# 불변식이 이를 고정한다).
_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(
        {
            Permission.SITES_READ,
            Permission.SITES_WRITE,
            Permission.MISSIONS_READ,
            Permission.MISSIONS_ISSUE,
            Permission.EVENTS_READ,
            Permission.EVENTS_TRIAGE,
            Permission.SITES_AUTONOMY_APPROVE,
            Permission.EQUIPMENT_SUPPORT_APPROVE,
            Permission.CAPABILITY_PRODUCT_APPROVE,
            Permission.CAPABILITY_ACTIVATE,
            Permission.EXTERNAL_AUTHORITY_MANAGE,
            Permission.ORGANIZATION_MEMBERS_MANAGE,
            Permission.WORK_ORDERS_WRITE,
            Permission.REOBSERVATION_APPROVE,
            Permission.COPILOT_QUERY,
        }
    ),
    Role.FIELD_OPERATOR: frozenset(
        {
            Permission.SITES_READ,
            Permission.SITES_WRITE,
            Permission.MISSIONS_READ,
            Permission.MISSIONS_ISSUE,
            Permission.EVENTS_READ,
            Permission.EVENTS_TRIAGE,
            Permission.WORK_ORDERS_WRITE,
            Permission.REOBSERVATION_APPROVE,
            Permission.COPILOT_QUERY,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.SITES_READ,
            Permission.MISSIONS_READ,
            Permission.EVENTS_READ,
            Permission.COPILOT_QUERY,
        }
    ),
}

# EDGE_DEVICE 는 role 표와 무관하게 항상 이 고정 집합이다(ADR-KSI-008 §2).
# CAP-5 existing producer 호환은 유지한다. Gateway runner의 PSDK route collector는
# 이 broad Edge credential을 재사용하지 않고 EDGE_ROUTE_OBSERVER를 쓴다.
_EDGE_DEVICE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.EDGE_SYNC_INGEST,
        Permission.EDGE_MISSION_PULL,
        Permission.EDGE_EVIDENCE_WRITE,
        Permission.EDGE_SOURCE_MEDIA_WRITE,
        Permission.EDGE_MISSION_KMZ_READ,
        Permission.CAPABILITY_RUNTIME_OBSERVE,
    }
)

_GATEWAY_DEVICE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.GATEWAY_CONNECTIVITY_WRITE,
        Permission.CAPABILITY_RUNTIME_OBSERVE,
        Permission.CAPABILITY_RUNTIME_PREFLIGHT,
    }
)

_EDGE_ROUTE_OBSERVER_PERMISSIONS: frozenset[Permission] = frozenset(
    {Permission.CAPABILITY_RUNTIME_OBSERVE}
)

# PROCESSING_WORKER 도 고정 집합이다. 워커는 처리 작업만 만진다 — 현장·임무
# 발급·사건 분류에 손댈 이유가 없고, 손댈 수 있으면 처리 파이프라인 하나가
# 뚫렸을 때 blast radius 가 제품 전체가 된다.
_PROCESSING_WORKER_PERMISSIONS: frozenset[Permission] = frozenset({Permission.PROCESSING_WORK})


def principal_permissions(principal: Principal) -> frozenset[Permission]:
    """Principal 의 유효 권한 집합. 장비·워커는 고정, OPERATOR 는 role 표 조회."""
    if principal.kind is PrincipalKind.GATEWAY_DEVICE:
        return _GATEWAY_DEVICE_PERMISSIONS
    if principal.kind is PrincipalKind.EDGE_DEVICE:
        return _EDGE_DEVICE_PERMISSIONS
    if principal.kind is PrincipalKind.EDGE_ROUTE_OBSERVER:
        return _EDGE_ROUTE_OBSERVER_PERMISSIONS
    if principal.kind is PrincipalKind.PROCESSING_WORKER:
        return _PROCESSING_WORKER_PERMISSIONS
    if principal.role is None:
        # AuthRegistry 를 거친 Principal 은 이 분기에 도달하지 않는다(생성 시
        # role 필수를 거부) — 레지스트리 밖에서 직접 구성된 불변식 위반 객체가
        # 들어와도 조용히 권한을 내주지 않는다(fail-closed 방어).
        return frozenset()
    return _ROLE_PERMISSIONS[principal.role]


# 인증 실패 사유(부재/형식오류/미지 토큰)를 가리지 않는 단일 문구 — 존재 여부
# 힌트를 주지 않는다(edge_sync.py 감사 #8 열거 오라클 방지 관습과 동일 원칙).
_UNAUTHENTICATED_DETAIL = "인증이 필요하다 — 유효한 Bearer 토큰을 제시하라"
_BEARER_SCHEME = HTTPBearer(
    auto_error=False,
    scheme_name="KsiBearer",
    bearerFormat="OIDC operator JWT 또는 opaque device credential",
    description=(
        "사람 OPERATOR는 배포 mode에 따라 OIDC JWT를 사용하고, "
        "GATEWAY_DEVICE·EDGE_DEVICE·EDGE_ROUTE_OBSERVER·PROCESSING_WORKER는 "
        "별도 opaque 장비 자격을 사용한다. EDGE_ROUTE_OBSERVER는 dedicated credential로 "
        "CAPABILITY_RUNTIME_OBSERVE 하나와 자기 EDGE_ROUTE_PORT scope만 가진다."
    ),
)


# API 요청 안에서만 살아 있는 조직 문맥이다. 오래된 분석/미디어 store 중 일부는
# MissionStore만 주입받아 호출되므로, 각 라우터가 매번 같은 scope 검사를 잊지 않게
# MissionStore가 이 문맥을 읽어 교차 조직 mission을 존재하지 않는 것처럼 취급한다.
#
# 이는 인가를 대체하지 않는다. 이 값은 ``require_principal``/``require_permission``
# 가 인증한 Principal에서만 설정되고, 요청 밖의 원장 재생·배치 작업에는 설정되지
# 않는다. 따라서 내부 조정 코드는 명시적 ``get_scoped``를 쓸 수 있고, 공개 API의
# legacy mission consumer는 중앙 경계를 자동으로 상속한다(INV-060).
_REQUEST_PRINCIPAL: ContextVar[Principal | None] = ContextVar(
    "ksi_request_principal", default=None
)


def current_request_organization_id() -> str | None:
    """현재 인증된 API 요청의 organizationId. 요청 밖이면 ``None``.

    MissionStore의 read filter 전용 공개 함수다. 호출자가 이 값이 없다는 이유로
    인가를 생략해서는 안 된다 — 그 경우는 HTTP 요청 밖의 trusted 내부 흐름이다.
    """

    principal = _REQUEST_PRINCIPAL.get()
    return principal.organization_id if principal is not None else None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=_UNAUTHENTICATED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_BEARER_SCHEME),  # noqa: B008
) -> Principal:
    """Authorization 헤더에서 Bearer 토큰을 파싱·해석한다.

    scheme 비교는 RFC 7235 대소문자 관용을 따른다("bearer"/"Bearer"/"BEARER" 모두
    허용). registry 가 ``app.state.auth_registry`` 에 없으면 조립 결함이므로
    :class:`RuntimeError` 로 즉시 드러낸다(인증 우회를 조용히 통과시키지 않는다).
    """
    registry = getattr(request.app.state, "auth_registry", None)
    if registry is None:
        raise RuntimeError(
            "request.app.state.auth_registry 가 설정되지 않았다 — "
            "mount_auth() 없이 보호 라우트를 장착한 조립 결함이다"
        )

    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized()
    token = credentials.credentials

    mode = getattr(request.app.state, "human_auth_mode", HumanAuthMode.OPAQUE)
    opaque_principal = registry.resolve(token, now=datetime.now(UTC))

    # 장비·워커는 사람 migration mode와 무관하게 기존 자격을 유지한다.
    if opaque_principal is not None and opaque_principal.kind is not PrincipalKind.OPERATOR:
        return opaque_principal
    if mode in (HumanAuthMode.OPAQUE, HumanAuthMode.DUAL) and opaque_principal is not None:
        return opaque_principal
    if mode in (HumanAuthMode.DUAL, HumanAuthMode.OIDC):
        verifier: OidcVerifier | None = getattr(request.app.state, "oidc_verifier", None)
        if verifier is None:
            raise RuntimeError("OIDC/DUAL auth mode에 oidc_verifier가 없는 조립 결함이다")
        principal = verifier.verify(token)
        if principal is not None:
            return principal
    raise _unauthorized()


async def _principal_request_scope(
    principal: Principal = Depends(_resolve_principal),  # noqa: B008
) -> AsyncIterator[Principal]:
    """인증된 Principal을 요청 수명 동안 ContextVar로 제공한다.

    FastAPI의 generator dependency를 사용해 sync endpoint/threadpool에도 context가
    복사되고, 응답 완료 후에는 반드시 reset된다. 단순히 ``_resolve_principal`` 안에서
    ``set``하면 sync dependency thread의 context가 endpoint까지 전달되지 않을 수
    있고, reset하지 않으면 요청 간 문맥 오염 위험이 생긴다.
    """

    token = _REQUEST_PRINCIPAL.set(principal)
    try:
        yield principal
    finally:
        _REQUEST_PRINCIPAL.reset(token)


def require_principal() -> Callable[..., Any]:
    """인증만 확인하는 FastAPI 의존성 팩토리. 사용: ``Depends(require_principal())``."""
    return _principal_request_scope


def require_permission(perm: Permission) -> Callable[[Principal], Principal]:
    """``perm`` 을 가진 Principal 만 통과시키는 의존성 팩토리(인증 401 + 인가 403)."""

    def _check(principal: Principal = Depends(_principal_request_scope)) -> Principal:  # noqa: B008
        if perm not in principal_permissions(principal):
            raise HTTPException(status_code=403, detail="권한이 부족하다")
        return principal

    return _check


def require_permission_any(*perms: Permission) -> Callable[[Principal], Principal]:
    """``perms`` 중 하나라도 가진 Principal 을 통과시킨다.

    같은 엔드포인트를 사람(``MISSIONS_ISSUE``, 아무 mission)과 Edge 장비
    (``EDGE_SOURCE_MEDIA_WRITE``, 자기 mission 만)가 서로 다른 범위로 함께
    쓸 때만 쓴다 — 범위 좁히기(자기 mission 검증)는 이 의존성이 아니라
    핸들러/store 가 한다(``require_permission`` 과 달리 여기서는 "권한 있음"
    만 보장하지 "그 mission 이 자기 것" 까지는 보장하지 않는다).
    """
    if not perms:
        raise ValueError("require_permission_any 는 최소 1개의 Permission 이 필요하다")

    def _check(principal: Principal = Depends(_principal_request_scope)) -> Principal:  # noqa: B008
        granted = principal_permissions(principal)
        if not any(p in granted for p in perms):
            raise HTTPException(status_code=403, detail="권한이 부족하다")
        return principal

    return _check


class WhoAmIResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    principal_id: str
    organization_id: str
    kind: str
    role: str | None
    device_id: str | None
    permissions: list[str]


def build_auth_router() -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["auth"])

    @router.get("/whoami", response_model=WhoAmIResponse)
    def whoami(
        principal: Principal = Depends(require_principal()),  # noqa: B008
    ) -> WhoAmIResponse:
        """현재 Principal 신원·권한을 반환한다(인증만 요구, 인가 없음).

        EDGE_ROUTE_OBSERVER는 role 없이 dedicated credential의 singleton runtime
        observation permission만 반환하며, 이 응답이 route scope 권한을 넓히지 않는다.
        """
        return WhoAmIResponse(
            principal_id=principal.principal_id,
            organization_id=principal.organization_id,
            kind=principal.kind.value,
            role=principal.role.value if principal.role is not None else None,
            device_id=principal.device_id,
            permissions=sorted(p.value for p in principal_permissions(principal)),
        )

    return router


def mount_auth(
    app: FastAPI,
    registry: AuthRegistry,
    *,
    human_auth_mode: HumanAuthMode = HumanAuthMode.OPAQUE,
    oidc_verifier: OidcVerifier | None = None,
) -> None:
    """사람 OIDC와 장비 opaque registry를 한 Bearer 표면에 장착한다."""
    if human_auth_mode in (HumanAuthMode.DUAL, HumanAuthMode.OIDC) and oidc_verifier is None:
        raise AuthRegistryError("OIDC/DUAL auth mode에는 oidc_verifier가 필요하다")
    app.state.auth_registry = registry
    app.state.human_auth_mode = human_auth_mode
    app.state.oidc_verifier = oidc_verifier
    app.include_router(build_auth_router())
