"""KSI Core 프로덕션 조립 지점 — 유일한 실행 가능한 운영 배선(ADR-KSI-008).

``scripts/run_core_dev.py`` 는 그 스크립트 자체가 명시하듯 프로덕션 조립이
아니다 — 고정 dev 토큰 5개를 하드코딩해 ``AuthRegistry`` 를 구성한다. 이
모듈은 dev 스크립트를 전혀 import 하지 않는다(``run_core_dev`` 에 대한 어떤
의존도 없다) — 이 파일만 읽어서는 dev 토큰의 존재조차 알 수 없어야, "운영
빌드가 실수로 dev 자격증명을 끌고 들어온다"는 사고 클래스 자체가 성립하지
않는다.

## 전부 환경변수로만 조립한다 — fail-closed

필수 환경변수가 하나라도 없거나 형식이 틀리면 :class:`RuntimeError` 로 즉시
거부한다. 무엇도 조용히 기본값·빈 값으로 대체하지 않는다 — 조용한 기본값은
"인증 없이 뜬 프로덕션 서버"라는, 이 작업이 막으려는 바로 그 사고다. 검증은
무거운 부수효과(S3 client 생성, journal 파일 열기 등)를 만들기 **전에** 전부
끝낸다 — 잘못된 배포가 부분적으로 조립되다 알 수 없는 지점에서 죽는 대신,
어느 환경변수가 왜 문제인지 첫 실패에서 명확히 말한다.

## 서명키는 여기서 부트스트랩하지 않는다

``scripts/run_core_dev.py`` 의 ``_bootstrap_key_set`` 은 dev 편의로 키가 없으면
새로 만든다. 이 모듈은 :func:`ksi_core.signing_keys.load_signing_keys` 를 직접
호출한다 — **이미 있는 키만 로드**하고 새로 만들지 않는다. 컨테이너는
재생성될 수 있는 존재다(오케스트레이터 재스케줄·롤링 배포). 재생성마다 새
서명키가 생기면, 그 이전 키로 서명된 Mission Contract 는 재검증 시 새 키
registry 에 없는 keyId 를 참조하게 되어 전부 검증 실패한다 — 이미 현장에
발급된 계약이 서버 재시작 한 번으로 무효가 되는 것은 이 제품의 근본 전제
(server loss must not invalidate a locally valid Mission Contract)를 정면으로
어긴다. 키 파일은 컨테이너 밖(영속 볼륨)에 살아야 하고, 회전은 운영 절차
(``docs/security/SIGNING_KEY_LIFECYCLE.md``)로 명시적으로 한다.

## evidence storage 는 선택이 아니라 필수다

dev 조립은 ``--s3-endpoint``/``--s3-bucket`` 없이도 뜬다(증거·3D 파이프라인
표면이 그냥 장착되지 않을 뿐) — 로컬 UI 개발에는 그걸로 충분하다. 프로덕션은
그 타협을 허용하지 않는다: evidence storage 없는 운영 배포는 증거·3D 파이프라인
전체가 조용히 404 인 서버이고, 그 상태를 "정상 기동"으로 보고하면 안 된다.
그래서 ``KSI_CORE_S3_ENDPOINT``/``KSI_CORE_S3_BUCKET`` 을 둘 다 필수로 둔다.

## 원문 토큰은 이 프로세스 어디에도 없다

``KSI_CORE_PRINCIPAL_TOKENS_JSON`` 은 토큰 원문이 아니라 sha256 **digest** 만
싣는다(``AuthRegistry`` 자체가 이미 그 규약이다, ``auth.py`` 모듈 docstring
참조). 배포자가 토큰을 만들고 digest 를 미리 계산해 이 JSON 에 실으므로,
프로세스 메모리·로그·환경변수 어디에도 원문 토큰이 존재하지 않는다 — dev
스크립트처럼 콘솔에 토큰을 찍어 보여주는 경로도 여기 없다(그 경로 자체가
원문을 프로세스가 알고 있어야만 가능하다).

각 항목은 선택 필드 ``status``("ACTIVE"/"REVOKED", 기본 ACTIVE)와
``notAfter``(ISO 8601 tz-aware, 기본 없음=만료 없음)를 가질 수 있다 — 회전
중에는 같은 ``principalId`` 로 이전 digest(``notAfter`` 로 유예기간 종료
시각)와 새 digest(``notAfter`` 없음) 두 항목을 함께 배포한다(``docs/security/
AUTH_TOKEN_ROTATION.md``).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from ksi_mission_contracts.risk_policy import RiskPolicyPackV1, risk_policy_pack_wire_dict
from ksi_mission_contracts.runtime_profile import (
    EdgeRuntimeProfileV1,
    edge_runtime_profile_wire_dict,
)

from ksi_core.app_assembly import assemble_app, cli_optional_positive
from ksi_core.auth import (
    AuthRegistry,
    HumanAuthMode,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    TokenStatus,
)
from ksi_core.device_attestation import load_device_attestation_registry
from ksi_core.durable_journal import DurableJournal
from ksi_core.observability import configure_structured_logging
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from ksi_core.signing_keys import load_signing_keys

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.copilot_openai import CopilotRuntimeConfig

_JOURNAL_SEGMENT_BYTES_DEFAULT = 64 * 1024 * 1024
_EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT = 500

_KIND_VALUES = {kind.value: kind for kind in PrincipalKind}
_ROLE_VALUES = {role.value: role for role in Role}
_STATUS_VALUES = {status.value: status for status in TokenStatus}
# auth.py 의 AuthRegistry 가 강제하는 것과 동일한 규약(소문자 64자리 hex) —
# 형식이 틀린 digest 를 여기서 먼저 거부해야 "무거운 부수효과 이전에 검증을
# 전부 끝낸다"(모듈 docstring)는 약속이 이 필드에 대해서도 실제로 성립한다.
_TOKEN_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISSUER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_OIDC_ALLOWED_ALGORITHMS = frozenset({"RS256", "ES256"})


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} 환경변수가 필요하다 — 프로덕션 조립은 기본값으로 넘어가지 않는다"
        )
    return value


def _require_dir(name: str) -> Path:
    raw = _require_env(name)
    path = Path(raw)
    if not path.is_dir():
        raise RuntimeError(f"{name}={raw!r} 는 존재하는 디렉터리가 아니다")
    return path


def _optional_positive_env(name: str, *, default: int) -> int | None:
    if (raw := os.environ.get(name)) is None:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name}={raw!r} 는 정수여야 한다") from exc
    try:
        return cli_optional_positive(value, name=name)
    except ValueError as exc:
        # cli_optional_positive 는 라이브러리 계약(dev CLI 도 공유)이라 ValueError 를
        # 던진다 — 이 함수는 환경변수 검증 경계이므로 모듈 docstring 이 약속하는
        # "형식이 틀리면 RuntimeError" 를 이 실패에 대해서도 지킨다(음수 입력 등).
        raise RuntimeError(str(exc)) from exc


def _expose_docs_env() -> bool:
    """``KSI_CORE_EXPOSE_DOCS`` — 기본 ``False``(dev 는 기본 True 와 대칭적으로 반대).

    운영 배포는 명시적으로 켜지 않는 한 계약 문서 표면(``/docs`` 등)을 닫는다.
    """
    raw = os.environ.get("KSI_CORE_EXPOSE_DOCS", "false").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise RuntimeError(f"KSI_CORE_EXPOSE_DOCS={raw!r} 는 'true' 또는 'false' 여야 한다")


def _acquisition_issue_gate_env() -> bool:
    """실장비 receipt와 Site profile migration 뒤에만 명시적으로 활성화한다."""
    raw = os.environ.get("KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED", "false").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise RuntimeError(
        "KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED="
        f"{raw!r} 는 'true' 또는 'false' 여야 한다"
    )


def _acquisition_coordination_env() -> bool:
    """Acquisition coordinator의 독립 rollback flag — 기본은 활성화다."""
    raw = os.environ.get("KSI_CORE_ACQUISITION_COORDINATION_ENABLED", "true").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise RuntimeError(
        "KSI_CORE_ACQUISITION_COORDINATION_ENABLED="
        f"{raw!r} 는 'true' 또는 'false' 여야 한다"
    )


def _copilot_runtime_config_env() -> CopilotRuntimeConfig | None:
    """External Copilot is opt-in; an enabled but partial configuration is fatal."""
    raw = os.environ.get("KSI_COPILOT_ENABLED", "false").strip().lower()
    if raw in ("false", "0", "no"):
        return None
    if raw not in ("true", "1", "yes"):
        raise RuntimeError("KSI_COPILOT_ENABLED는 true 또는 false여야 한다")
    from ksi_core.copilot_openai import CopilotRuntimeConfig

    api_key_file = Path(_require_env("KSI_COPILOT_API_KEY_FILE"))
    if not api_key_file.is_file():
        raise RuntimeError("KSI_COPILOT_API_KEY_FILE은 존재하는 파일이어야 한다")
    timeout_raw = os.environ.get("KSI_COPILOT_REQUEST_TIMEOUT_SECONDS", "30")
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise RuntimeError("KSI_COPILOT_REQUEST_TIMEOUT_SECONDS는 숫자여야 한다") from exc
    if timeout <= 0 or timeout > 300:
        raise RuntimeError("KSI_COPILOT_REQUEST_TIMEOUT_SECONDS는 0초 초과 300초 이하여야 한다")
    base_url = _require_env("KSI_COPILOT_BASE_URL")
    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError("KSI_COPILOT_BASE_URL은 http(s) URL이어야 한다")
    provider_name = os.environ.get("KSI_COPILOT_PROVIDER_NAME", "openai-compatible")
    if not provider_name.strip():
        raise RuntimeError("KSI_COPILOT_PROVIDER_NAME은 비어 있을 수 없다")
    return CopilotRuntimeConfig(
        base_url=base_url,
        model=_require_env("KSI_COPILOT_MODEL"),
        api_key_file=api_key_file,
        timeout_seconds=timeout,
        planner_version=_require_env("KSI_COPILOT_PLANNER_VERSION"),
        provider_name=provider_name,
    )


def _human_auth_config_env() -> tuple[HumanAuthMode, OidcVerifierConfig | None]:
    """사람 인증 mode와 vendor-neutral OIDC 검증 입력을 fail-closed로 파싱한다."""
    raw_mode = os.environ.get("KSI_CORE_HUMAN_AUTH_MODE", HumanAuthMode.OPAQUE.value)
    try:
        mode = HumanAuthMode(raw_mode)
    except ValueError as exc:
        raise RuntimeError(
            "KSI_CORE_HUMAN_AUTH_MODE은 OPAQUE, DUAL, OIDC 중 하나여야 한다"
        ) from exc
    if mode is HumanAuthMode.OPAQUE:
        return mode, None

    issuer = _require_env("KSI_CORE_OIDC_ISSUER")
    audience = _require_env("KSI_CORE_OIDC_AUDIENCE")
    jwks_url = _require_env("KSI_CORE_OIDC_JWKS_URL")
    algorithms = tuple(
        item.strip()
        for item in os.environ.get("KSI_CORE_OIDC_ALLOWED_ALGORITHMS", "RS256").split(",")
        if item.strip()
    )
    if not algorithms or any(item not in _OIDC_ALLOWED_ALGORITHMS for item in algorithms):
        raise RuntimeError(
            "KSI_CORE_OIDC_ALLOWED_ALGORITHMS는 RS256, ES256만 허용한다"
        )
    ttl_raw = os.environ.get("KSI_CORE_OIDC_JWKS_TTL_SECONDS", "300")
    try:
        ttl = int(ttl_raw)
    except ValueError as exc:
        raise RuntimeError("KSI_CORE_OIDC_JWKS_TTL_SECONDS는 양수 정수여야 한다") from exc
    if ttl <= 0:
        raise RuntimeError("KSI_CORE_OIDC_JWKS_TTL_SECONDS는 양수 정수여야 한다")
    return mode, OidcVerifierConfig(
        issuer=issuer,
        audience=audience,
        jwks_url=jwks_url,
        allowed_algorithms=algorithms,
        jwks_ttl_seconds=ttl,
    )


def _mission_contract_writer_config() -> tuple[Literal["1.2", "1.3"], str | None]:
    """v1.3 writer는 HIL 뒤 명시적으로 켠다. 기본은 dual-reader + v1.2 writer다."""
    raw = os.environ.get("KSI_CORE_MISSION_CONTRACT_WRITER_VERSION", "1.2")
    if raw not in ("1.2", "1.3"):
        raise RuntimeError(
            "KSI_CORE_MISSION_CONTRACT_WRITER_VERSION은 '1.2' 또는 '1.3'이어야 한다"
        )
    issuer_id = os.environ.get("KSI_CORE_MISSION_CONTRACT_ISSUER_ID")
    if raw == "1.3" and not issuer_id:
        raise RuntimeError(
            "v1.3 writer에는 KSI_CORE_MISSION_CONTRACT_ISSUER_ID가 필요하다"
        )
    if issuer_id is not None and _ISSUER_ID_RE.fullmatch(issuer_id) is None:
        raise RuntimeError(
            "KSI_CORE_MISSION_CONTRACT_ISSUER_ID는 경로-안전 식별자여야 한다"
        )
    return cast(Literal["1.2", "1.3"], raw), issuer_id


def _parse_principal_tokens(raw: str) -> list[PrincipalTokenRecord]:
    """``KSI_CORE_PRINCIPAL_TOKENS_JSON`` 을 파싱한다 — 원문 토큰은 여기 없다(digest 만).

    형식이 조금이라도 어긋나면 :class:`RuntimeError` — ``AuthRegistry`` 생성자
    자체도 불변식을 검증하지만(``AuthRegistryError``), 이 함수는 그보다 앞서
    "환경변수 자체가 잘못된 형식이다"를 배포자에게 명확히 알린다.
    """
    try:
        entries = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"KSI_CORE_PRINCIPAL_TOKENS_JSON 이 유효한 JSON 이 아니다 — {exc}"
        ) from exc
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("KSI_CORE_PRINCIPAL_TOKENS_JSON 은 비어 있지 않은 배열이어야 한다")

    records: list[PrincipalTokenRecord] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}] 는 object 여야 한다")

        token_sha256 = entry.get("tokenSha256")
        principal_id = entry.get("principalId")
        kind_raw = entry.get("kind")
        role_raw = entry.get("role")
        device_id = entry.get("deviceId")
        organization_id = entry.get("organizationId", "legacy")
        status_raw = entry.get("status", TokenStatus.ACTIVE.value)
        not_after_raw = entry.get("notAfter")

        if not isinstance(token_sha256, str) or not token_sha256:
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].tokenSha256 이 없거나 비어 있다"
            )
        if not _TOKEN_SHA256_RE.fullmatch(token_sha256):
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].tokenSha256 은 소문자 64자리 hex "
                f"여야 한다 (got {token_sha256!r}) — 원문 토큰·대문자는 거부된다"
            )
        if not isinstance(principal_id, str) or not principal_id:
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].principalId 가 없거나 비어 있다"
            )
        if kind_raw not in _KIND_VALUES:
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].kind={kind_raw!r} 는 "
                f"{sorted(_KIND_VALUES)} 중 하나여야 한다"
            )
        kind = _KIND_VALUES[kind_raw]

        role: Role | None = None
        if role_raw is not None:
            if role_raw not in _ROLE_VALUES:
                raise RuntimeError(
                    f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].role={role_raw!r} 는 "
                    f"null 이거나 {sorted(_ROLE_VALUES)} 중 하나여야 한다"
                )
            role = _ROLE_VALUES[role_raw]

        if device_id is not None and not isinstance(device_id, str):
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].deviceId 는 문자열이거나 null 이어야 한다"
            )
        if not isinstance(organization_id, str) or not organization_id:
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].organizationId 는 "
                "비공백 문자열이어야 한다"
            )
        if status_raw not in _STATUS_VALUES:
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].status={status_raw!r} 는 "
                f"{sorted(_STATUS_VALUES)} 중 하나여야 한다"
            )
        status = _STATUS_VALUES[status_raw]

        not_after: datetime | None = None
        if not_after_raw is not None:
            if not isinstance(not_after_raw, str):
                raise RuntimeError(
                    f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].notAfter 는 ISO 문자열이거나 "
                    "null 이어야 한다"
                )
            try:
                not_after = datetime.fromisoformat(not_after_raw)
            except ValueError as exc:
                raise RuntimeError(
                    f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].notAfter 를 파싱할 수 없다 — "
                    f"{not_after_raw!r}"
                ) from exc
            if not_after.tzinfo is None:
                raise RuntimeError(
                    f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].notAfter 는 tz-aware 여야 한다"
                )

        records.append(
            PrincipalTokenRecord(
                token_sha256=token_sha256,
                status=status,
                not_after=not_after,
                principal=Principal(
                    principal_id=principal_id,
                    kind=kind,
                    role=role,
                    device_id=device_id,
                    organization_id=organization_id,
                ),
            )
        )
    return records


def _optional_risk_policy_packs() -> tuple[dict[str, Any], ...]:
    """``KSI_CORE_RISK_POLICY_PACKS_JSON``을 typed로 읽는다.

    설정이 없으면 Edge mission pull은 안전하게 빈 큐(204)다. 즉시 운영을 막는
    전역 필수 환경변수로 만들지 않되, pack 없이 형상·공분산 기본값을 발명해
    dispatch하는 경로는 만들지 않는다.
    """
    raw = os.environ.get("KSI_CORE_RISK_POLICY_PACKS_JSON")
    if raw is None:
        return ()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("KSI_CORE_RISK_POLICY_PACKS_JSON 이 유효한 JSON 이 아니다") from exc
    if not isinstance(payload, list):
        raise RuntimeError("KSI_CORE_RISK_POLICY_PACKS_JSON 은 배열이어야 한다")
    packs: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise RuntimeError(f"KSI_CORE_RISK_POLICY_PACKS_JSON[{index}] 는 object 여야 한다")
        try:
            packs.append(risk_policy_pack_wire_dict(RiskPolicyPackV1.model_validate(item)))
        except Exception as exc:  # noqa: BLE001 -- 환경 설정은 전부 fail-closed
            raise RuntimeError(
                f"KSI_CORE_RISK_POLICY_PACKS_JSON[{index}] 가 RiskPolicyPack v1.0이 아니다"
            ) from exc
    return tuple(packs)


def _optional_edge_runtime_profiles() -> tuple[dict[str, Any], ...]:
    """``KSI_CORE_EDGE_RUNTIME_PROFILES_JSON``을 typed로 읽는다.

    profile이 없으면 Edge dispatch는 risk pack이 있어도 204다. 모델/보정의
    식별자만으로 DPK가 경로·카메라값·장비 크기를 추정하게 두지 않는다.
    """
    raw = os.environ.get("KSI_CORE_EDGE_RUNTIME_PROFILES_JSON")
    if raw is None:
        return ()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(
            "KSI_CORE_EDGE_RUNTIME_PROFILES_JSON 이 유효한 JSON 이 아니다"
        ) from exc
    if not isinstance(payload, list):
        raise RuntimeError("KSI_CORE_EDGE_RUNTIME_PROFILES_JSON 은 배열이어야 한다")
    profiles: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"KSI_CORE_EDGE_RUNTIME_PROFILES_JSON[{index}] 는 object 여야 한다"
            )
        try:
            profiles.append(edge_runtime_profile_wire_dict(EdgeRuntimeProfileV1.model_validate(item)))
        except Exception as exc:  # noqa: BLE001 -- 환경 설정은 전부 fail-closed
            raise RuntimeError(
                f"KSI_CORE_EDGE_RUNTIME_PROFILES_JSON[{index}] 가 EdgeRuntimeProfile v1.0이 아니다"
            ) from exc
    return tuple(profiles)


def build_production_app() -> FastAPI:
    """환경변수만으로 프로덕션 Core 앱을 조립한다 — 실패는 전부 fail-closed.

    uvicorn 팩토리 진입점(``--factory``)으로 쓰인다:
    ``uvicorn ksi_core.production:build_production_app --factory``.
    """
    # 검증보다도 먼저다 — 검증 실패 메시지 자체도 구조화 로그로 남아야
    # 배포 사고 조사에서 "그때 무슨 환경변수가 문제였는지"가 로그 수집기에서
    # 검색 가능하다. correlation id 는 아직 없다(요청 밖이므로 "-"로 찍힌다).
    configure_structured_logging(
        level=os.environ.get("KSI_CORE_LOG_LEVEL", "INFO"), json_format=True
    )

    # ── 1단계: 검증(가벼운 것부터) — 무거운 부수효과(S3 client·journal open) 이전에
    # 전부 끝낸다. 잘못된 배포는 어느 환경변수가 문제인지 즉시 알아야 한다.
    data_dir = _require_dir("KSI_CORE_DATA_DIR")
    signing_keys_dir = _require_dir("KSI_CORE_SIGNING_KEYS_DIR")
    s3_endpoint = _require_env("KSI_CORE_S3_ENDPOINT")
    s3_public_endpoint = os.environ.get("KSI_CORE_S3_PUBLIC_ENDPOINT", s3_endpoint)
    s3_bucket = _require_env("KSI_CORE_S3_BUCKET")
    principal_tokens_raw = _require_env("KSI_CORE_PRINCIPAL_TOKENS_JSON")
    device_attestation_keys_file = Path(_require_env("KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE"))
    if not device_attestation_keys_file.is_file():
        raise RuntimeError(
            "KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE은 존재하는 파일이어야 한다"
        )

    journal_segment_bytes = _optional_positive_env(
        "KSI_CORE_JOURNAL_SEGMENT_BYTES", default=_JOURNAL_SEGMENT_BYTES_DEFAULT
    )
    edge_sync_snapshot_every = _optional_positive_env(
        "KSI_CORE_EDGE_SYNC_SNAPSHOT_EVERY", default=_EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT
    )
    expose_docs = _expose_docs_env()
    acquisition_coordination_enabled = _acquisition_coordination_env()
    acquisition_issue_gate_enabled = _acquisition_issue_gate_env()
    copilot_runtime_config = _copilot_runtime_config_env()
    human_auth_mode, oidc_config = _human_auth_config_env()
    mission_contract_writer_version, mission_contract_issuer_id = (
        _mission_contract_writer_config()
    )

    principal_records = _parse_principal_tokens(principal_tokens_raw)
    risk_policy_packs = _optional_risk_policy_packs()
    edge_runtime_profiles = _optional_edge_runtime_profiles()
    device_attestation_registry = load_device_attestation_registry(
        device_attestation_keys_file
    )

    # ── 2단계: 무거운 조립 — 여기부터는 검증을 통과한 입력만 다룬다.

    # 서명키는 **로드만** 한다(부트스트랩 없음) — 모듈 docstring 참조.
    key_set = load_signing_keys(signing_keys_dir)

    # AWS 자격증명은 boto3 기본 체인(환경변수/IAM role)에 맡긴다 — 이 함수는
    # endpoint_url·bucket 만 넘긴다(evidence_s3.py 어댑터가 이미 이 관습이다).
    from ksi_core.evidence_s3 import S3EvidenceStorage  # noqa: PLC0415 -- 지연 import(boto3)

    evidence_storage = S3EvidenceStorage(
        bucket=s3_bucket,
        endpoint_url=s3_endpoint,
        public_endpoint_url=s3_public_endpoint,
    )

    auth_registry = AuthRegistry(principal_records)
    oidc_verifier = OidcJwtVerifier(oidc_config) if oidc_config is not None else None

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(data_dir / name, max_segment_bytes=journal_segment_bytes)
        opened.append(journal)
        return journal

    try:
        return assemble_app(
            data_dir,
            journal=_journal,
            opened=opened,
            edge_sync_snapshot_every=edge_sync_snapshot_every,
            auth_registry=auth_registry,
            human_auth_mode=human_auth_mode,
            oidc_verifier=oidc_verifier,
            evidence_storage=evidence_storage,
            mission_signing_key=key_set.active_private_key,
            mission_signing_key_id=key_set.active_key_id,
            mission_contract_writer_version=mission_contract_writer_version,
            mission_contract_issuer_id=mission_contract_issuer_id,
            risk_policy_packs=risk_policy_packs,
            edge_runtime_profiles=edge_runtime_profiles,
            device_attestation_registry=device_attestation_registry,
            acquisition_coordination_enabled=acquisition_coordination_enabled,
            acquisition_issue_gate_enabled=acquisition_issue_gate_enabled,
            copilot_runtime_config=copilot_runtime_config,
            expose_docs=expose_docs,
        )
    except BaseException:
        # dev 조립(build_dev_app)과 같은 이유 — 안 닫으면 재시도가 flock 에 막혀
        # 진짜 실패 원인이 "다른 프로세스가 journal 을 소유 중"으로 덮인다.
        for journal in opened:
            journal.close()
        raise


__all__ = ["build_production_app"]
