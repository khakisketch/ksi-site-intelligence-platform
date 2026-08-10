"""Bearer 토큰 인증·역할 권한 (ADR-KSI-008 §2).

## 토큰 원문은 저장하지 않는다

:class:`AuthRegistry` 는 ``sha256(token)`` digest → :class:`Principal` 매핑만
보유한다(조립 시 digest 레코드 주입) — 서버 어디에도 토큰 원문이 남지 않는다.
JWT/OAuth·사용자 관리 API 는 도입하지 않는다(외부 IdP 없는 파일럿 규모에 과잉).

## Principal 3종 (2-enum 분리 관습)

- ``OPERATOR``(사람): :class:`Role` 필수, ``device_id`` 는 가질 수 없다. 권한은
  모듈 상수 ``_ROLE_PERMISSIONS`` 표 하나로만 결정된다(엔드포인트 산재 금지).
- ``EDGE_DEVICE``(장비): role 없음, ``device_id`` 필수. 권한은 항상
  ``{EDGE_SYNC_INGEST}`` 고정 — role 표와 무관하다(edge-sync 수신 인증 장비
  바인딩은 :mod:`ksi_core.edge_sync` 장착부에서 이 Principal 을 소비한다).
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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ksi_core.identifiers import is_path_safe_identifier

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
    """Principal 종류 — 사람·비행 장비·처리 워커는 신원 모델이 서로 다르다."""

    OPERATOR = "OPERATOR"
    EDGE_DEVICE = "EDGE_DEVICE"
    PROCESSING_WORKER = "PROCESSING_WORKER"


class TokenStatus(StrEnum):
    """토큰 레코드 상태(``ksi_mission_contracts.signing.KeyStatus`` 와 같은 모양).

    ``REVOKED`` 는 발급 중단이 아니라 검증 거부다 — 이미 배포된 토큰을 무효로
    만드는 유일한 장치(모듈 docstring "토큰 만료·회전" 절 참조).
    """

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class Permission(StrEnum):
    """엔드포인트가 요구하는 개별 권한 — role→permission 매핑의 코드셋."""

    SITES_READ = "SITES_READ"
    SITES_WRITE = "SITES_WRITE"
    MISSIONS_READ = "MISSIONS_READ"
    MISSIONS_ISSUE = "MISSIONS_ISSUE"
    EVENTS_READ = "EVENTS_READ"
    EVENTS_TRIAGE = "EVENTS_TRIAGE"
    EDGE_SYNC_INGEST = "EDGE_SYNC_INGEST"
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


@dataclass(frozen=True, slots=True)
class Principal:
    """인증된 신원 — OPERATOR 는 ``role`` 필수·``device_id`` 없음, 그 역."""

    principal_id: str
    kind: PrincipalKind
    role: Role | None
    device_id: str | None


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

    if principal.kind is PrincipalKind.OPERATOR:
        if principal.role is None:
            raise AuthRegistryError(f"{principal.principal_id}: OPERATOR 는 role 이 필수다")
        if principal.device_id is not None:
            raise AuthRegistryError(
                f"{principal.principal_id}: OPERATOR 는 device_id 를 가질 수 없다"
            )
    elif principal.kind is PrincipalKind.EDGE_DEVICE:
        if principal.role is not None:
            raise AuthRegistryError(
                f"{principal.principal_id}: EDGE_DEVICE 는 role 을 가질 수 없다"
            )
        if not principal.device_id:
            raise AuthRegistryError(f"{principal.principal_id}: EDGE_DEVICE 는 device_id 가 필수다")
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
        }
    ),
    Role.VIEWER: frozenset(
        {Permission.SITES_READ, Permission.MISSIONS_READ, Permission.EVENTS_READ}
    ),
}

# EDGE_DEVICE 는 role 표와 무관하게 항상 이 고정 집합이다(ADR-KSI-008 §2).
_EDGE_DEVICE_PERMISSIONS: frozenset[Permission] = frozenset({Permission.EDGE_SYNC_INGEST})

# PROCESSING_WORKER 도 고정 집합이다. 워커는 처리 작업만 만진다 — 현장·임무
# 발급·사건 분류에 손댈 이유가 없고, 손댈 수 있으면 처리 파이프라인 하나가
# 뚫렸을 때 blast radius 가 제품 전체가 된다.
_PROCESSING_WORKER_PERMISSIONS: frozenset[Permission] = frozenset(
    {Permission.PROCESSING_WORK}
)


def principal_permissions(principal: Principal) -> frozenset[Permission]:
    """Principal 의 유효 권한 집합. 장비·워커는 고정, OPERATOR 는 role 표 조회."""
    if principal.kind is PrincipalKind.EDGE_DEVICE:
        return _EDGE_DEVICE_PERMISSIONS
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


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=_UNAUTHENTICATED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve_principal(request: Request) -> Principal:
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

    header = request.headers.get("Authorization")
    if header is None:
        raise _unauthorized()

    scheme, sep, token = header.partition(" ")
    if not sep or scheme.lower() != "bearer" or not token:
        raise _unauthorized()

    principal = registry.resolve(token, now=datetime.now(UTC))
    if principal is None:
        raise _unauthorized()
    return principal


def require_principal() -> Callable[[Request], Principal]:
    """인증만 확인하는 FastAPI 의존성 팩토리. 사용: ``Depends(require_principal())``."""
    return _resolve_principal


def require_permission(perm: Permission) -> Callable[[Principal], Principal]:
    """``perm`` 을 가진 Principal 만 통과시키는 의존성 팩토리(인증 401 + 인가 403)."""

    def _check(principal: Principal = Depends(_resolve_principal)) -> Principal:  # noqa: B008
        if perm not in principal_permissions(principal):
            raise HTTPException(status_code=403, detail="권한이 부족하다")
        return principal

    return _check


class WhoAmIResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    principal_id: str
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
        """현재 Principal 신원·권한을 반환한다(인증만 요구, 인가 없음)."""
        return WhoAmIResponse(
            principal_id=principal.principal_id,
            kind=principal.kind.value,
            role=principal.role.value if principal.role is not None else None,
            device_id=principal.device_id,
            permissions=sorted(p.value for p in principal_permissions(principal)),
        )

    return router


def mount_auth(app: FastAPI, registry: AuthRegistry) -> None:
    """앱에 AuthRegistry 를 장착하고 ``/v1/auth/whoami`` 를 등록한다."""
    app.state.auth_registry = registry
    app.include_router(build_auth_router())
