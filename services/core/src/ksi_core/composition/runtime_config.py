"""Neutral, fail-closed production environment parsing helpers.

These are the exact pure helpers previously owned by
``ksi_core.composition.production_config``: no Mission/Edge/capability,
Copilot, acquisition or device imports live here, so the external-only
platform profile can reuse them without inheriting the managed assembly's
flight coupling. The legacy module re-exports the same function objects.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import cast

from ksi_core.auth import (
    HumanAuthMode,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    TokenStatus,
)
from ksi_core.domains.sites.sites import _DEFAULT_MAX_BOOTSTRAP_SITES_PER_ORG
from ksi_core.foundation.config_values import cli_optional_positive
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.oidc import OidcVerifierConfig

_JOURNAL_SEGMENT_BYTES_DEFAULT = 64 * 1024 * 1024
_EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT = 500

_KIND_VALUES = {kind.value: kind for kind in PrincipalKind}
_ROLE_VALUES = {role.value: role for role in Role}
_STATUS_VALUES = {status.value: status for status in TokenStatus}
# auth.py 의 AuthRegistry 가 강제하는 것과 동일한 규약(소문자 64자리 hex) —
# 형식이 틀린 digest 를 여기서 먼저 거부해야 "무거운 부수효과 이전에 검증을
# 전부 끝낸다"(모듈 docstring)는 약속이 이 필드에 대해서도 실제로 성립한다.
_TOKEN_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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


def _analysis_activation_paths_env() -> tuple[Path, Path, Path] | None:
    """Read the explicit runtime, activation and verification-key file paths.

    An entirely absent trio preserves the existing closed production surface;
    a partial trio is a configuration error rather than an ambient fallback.
    """
    names = (
        "KSI_CORE_ANALYSIS_RUNTIME_CONFIG_FILE",
        "KSI_CORE_ANALYSIS_ACTIVATION_FILE",
        "KSI_CORE_ANALYSIS_ACTIVATION_KEYS_FILE",
    )
    values = tuple(os.environ.get(name) for name in names)
    if all(value is None for value in values):
        return None
    if any(not value for value in values):
        raise RuntimeError("Analysis activation requires all three explicit file paths")
    paths = tuple(Path(cast(str, value)) for value in values)
    if any(not path.is_absolute() for path in paths):
        raise RuntimeError("Analysis activation file paths must be absolute")
    return cast(tuple[Path, Path, Path], paths)


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


def _spatial_data_config_path_env() -> Path | None:
    """``KSI_CORE_SPATIAL_DATA_CONFIG_FILE`` — 부재는 데이터 레인 미장착을 뜻한다.

    값이 있으면 정규화된 절대 경로여야 한다. 부분 구성·잘못된 경로는 조용한
    기본값이 아니라 부팅 실패다 — 이 레인은 어떤 환경변수만으로도 열리지 않는다.
    """
    raw = os.environ.get("KSI_CORE_SPATIAL_DATA_CONFIG_FILE")
    if raw is None:
        return None
    path = Path(raw)
    if not raw or not path.is_absolute() or ".." in path.parts:
        raise RuntimeError(
            "KSI_CORE_SPATIAL_DATA_CONFIG_FILE은 정규화된 절대 경로여야 한다"
        )
    return path


def _audit_working_set_path_env() -> Path | None:
    """``KSI_CORE_AUDIT_WORKING_SET_CONFIG`` — 부재는 레거시 감사 투영을 뜻한다.

    값이 있으면 소유자-전용 작업집합 바인딩 파일의 정규화된 절대 경로여야
    한다. 잘못된 경로는 조용한 레거시 대체가 아니라 부팅 실패다.
    """
    raw = os.environ.get("KSI_CORE_AUDIT_WORKING_SET_CONFIG")
    if raw is None:
        return None
    path = Path(raw)
    if not raw or not path.is_absolute() or ".." in path.parts:
        raise RuntimeError("KSI_CORE_AUDIT_WORKING_SET_CONFIG은 정규화된 절대 경로여야 한다")
    return path


def _site_bootstrap_max_sites_per_org_env() -> int:
    """``KSI_CORE_SITE_BOOTSTRAP_MAX_SITES_PER_ORG`` — F-01 bootstrap 조직 상한.

    미설정은 기본 상한(1,000)이다. 0·음수·비정수는 **부팅 실패**다 — 여기서
    0 은 "상한 없음"을 뜻하지 않는다(``_optional_positive_env`` 의 "0 = 없음"
    규약과 다른 이유: 상한 해제는 조용한 기본값이 아니라 별도 결정이어야 한다).
    """
    name = "KSI_CORE_SITE_BOOTSTRAP_MAX_SITES_PER_ORG"
    raw = os.environ.get(name)
    if raw is None:
        return _DEFAULT_MAX_BOOTSTRAP_SITES_PER_ORG
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name}={raw!r} 는 1 이상 정수여야 한다") from exc
    if value < 1:
        raise RuntimeError(f"{name}={raw!r} 는 1 이상 정수여야 한다")
    return value


def _registration_stopped_env() -> bool:
    """Restart-only stop; absent/false preserves ordinary registration."""
    name = "KSI_CORE_REGISTRATION_STOPPED"
    raw = os.environ.get(name)
    if raw is None or raw == "false":
        return False
    if raw == "true":
        return True
    raise RuntimeError(f"{name} must be exactly 'true' or 'false'")


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
    subject_registry_file = Path(_require_env("KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE"))
    if not subject_registry_file.is_absolute() or ".." in subject_registry_file.parts:
        raise RuntimeError("KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE은 정규화된 절대 경로여야 한다")
    algorithms = tuple(
        item.strip()
        for item in os.environ.get("KSI_CORE_OIDC_ALLOWED_ALGORITHMS", "RS256").split(",")
        if item.strip()
    )
    if not algorithms or any(item not in _OIDC_ALLOWED_ALGORITHMS for item in algorithms):
        raise RuntimeError("KSI_CORE_OIDC_ALLOWED_ALGORITHMS는 RS256, ES256만 허용한다")
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
        subject_registry_file=subject_registry_file,
        allowed_algorithms=algorithms,
        jwks_ttl_seconds=ttl,
    )


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
        allowed_site_ids: frozenset[str] | None = None
        allowed_work_area_ids: frozenset[str] | None = None
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

        scope_fields = ("allowedSiteIds", "allowedWorkAreaIds")
        if kind in (PrincipalKind.ANALYSIS_MCP_CLIENT, PrincipalKind.SPATIAL_DATA_MCP_CLIENT):
            parsed_grants: list[frozenset[str]] = []
            for field_name in scope_fields:
                values = entry.get(field_name)
                if not isinstance(values, list) or not values:
                    raise RuntimeError(
                        f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].{field_name} "
                        "은 비어 있지 않은 문자열 배열이어야 한다"
                    )
                if any(
                    not isinstance(value, str) or not is_path_safe_identifier(value)
                    for value in values
                ):
                    raise RuntimeError(
                        f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].{field_name} "
                        "에는 경로-안전 비공백 식별자만 허용된다"
                    )
                if len(values) != len(set(values)):
                    raise RuntimeError(
                        f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].{field_name} "
                        "에는 중복 식별자가 있을 수 없다"
                    )
                parsed_grants.append(frozenset(values))
            allowed_site_ids, allowed_work_area_ids = parsed_grants
        elif any(field_name in entry for field_name in scope_fields):
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}] scope grants are only valid "
                "for MCP client identities"
            )
        # F-01: registry 자원 scope/capability 는 보호 OIDC subject registry 전용
        # 발급 표면이다. opaque 토큰 설정에 이 이름을 실어 capability 를 얻는
        # 경로를 만들지 않는다 — 조용히 무시하지 않고 부팅 실패로 드러낸다.
        for reserved in ("registryScoped", "capabilities"):
            if reserved in entry:
                raise RuntimeError(
                    f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].{reserved} 는 예약 필드다 — "
                    "scope/capability 발급은 보호 OIDC subject registry 로만 한다"
                )

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
                    allowed_site_ids=allowed_site_ids,
                    allowed_work_area_ids=allowed_work_area_ids,
                ),
            )
        )
    return records


def _external_authority_paths_env() -> tuple[Path, Path] | None:
    names = (
        "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG",
        "KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG",
    )
    values = tuple(os.environ.get(name) for name in names)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise RuntimeError("external workflow and authority provider must be configured together")
    paths: list[Path] = []
    for name, value in zip(names, values, strict=True):
        assert value is not None
        path = Path(value)
        if (
            not value
            or value != value.strip()
            or not path.is_absolute()
            or ".." in path.parts
            or "\x00" in value
        ):
            raise RuntimeError(f"{name} requires an absolute protected configuration path")
        paths.append(path)
    return paths[0], paths[1]
