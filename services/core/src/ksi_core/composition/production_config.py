"""Pure, fail-closed production environment parsing helpers."""

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

from ksi_core.auth import (
    HumanAuthMode,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    TokenStatus,
)
from ksi_core.capability.runtime_projection import (
    RuntimeRouteFreshnessPolicyV1,
    TrustedRuntimeRouteConfigurationV1,
)
from ksi_core.composition.assembly import cli_optional_positive
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.oidc import OidcVerifierConfig

if TYPE_CHECKING:
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


def _processing_profile_issuance_env() -> bool:
    """Independent rollback gate; reads/replay remain available when false."""
    raw = os.environ.get("KSI_CORE_PROCESSING_PROFILE_ISSUANCE_ENABLED", "true").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise RuntimeError(
        "KSI_CORE_PROCESSING_PROFILE_ISSUANCE_ENABLED="
        f"{raw!r} 는 'true' 또는 'false' 여야 한다"
    )


def _landxml_ingress_env() -> bool:
    """Independent LandXML conversion rollout gate; existing assets stay readable."""
    raw = os.environ.get("KSI_CORE_LANDXML_INGRESS_ENABLED", "false").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise RuntimeError(
        "KSI_CORE_LANDXML_INGRESS_ENABLED="
        f"{raw!r} 는 'true' 또는 'false' 여야 한다"
    )


def _checkpoint_validation_registration_env() -> bool:
    """Independent rollout gate; completed validation evidence remains readable."""
    raw = os.environ.get("KSI_CORE_CHECKPOINT_VALIDATION_ENABLED", "false").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise RuntimeError(
        "KSI_CORE_CHECKPOINT_VALIDATION_ENABLED="
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
    subject_registry_file = Path(_require_env("KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE"))
    if not subject_registry_file.is_absolute() or ".." in subject_registry_file.parts:
        raise RuntimeError(
            "KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE은 정규화된 절대 경로여야 한다"
        )
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
        subject_registry_file=subject_registry_file,
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
        if kind is PrincipalKind.ANALYSIS_MCP_CLIENT:
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
                "for ANALYSIS_MCP_CLIENT"
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


def _optional_capability_freshness_policies() -> dict[
    str, RuntimeRouteFreshnessPolicyV1
]:
    """Read Core-owned CAP-5 validity windows and refresh-margin identities."""

    raw = os.environ.get("KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON")
    if raw is None:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(
            "KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON 이 유효한 JSON 이 아니다"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            "KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON 은 object 여야 한다"
        )
    policies: dict[str, RuntimeRouteFreshnessPolicyV1] = {}
    for policy_id, raw_policy in payload.items():
        if not isinstance(policy_id, str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*", policy_id
        ) is None:
            raise RuntimeError(
                "KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON 은 "
                "path-safe policy ID key만 허용한다"
            )
        try:
            policy = RuntimeRouteFreshnessPolicyV1.model_validate(raw_policy)
        except Exception as exc:  # noqa: BLE001 -- environment config fails closed
            raise RuntimeError(
                "KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON policy가 exact "
                "RuntimeRouteFreshnessPolicyV1이 아니다"
            ) from exc
        if policy.freshness_policy_id != policy_id:
            raise RuntimeError(
                "KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON key와 policy ID가 다르다"
            )
        policies[policy_id] = policy
    return policies


def _optional_runtime_route_configurations(
    *, freshness_policies: dict[str, RuntimeRouteFreshnessPolicyV1]
) -> tuple[TrustedRuntimeRouteConfigurationV1, ...]:
    """Read operator/Core-controlled exact route/port deployment configuration."""

    raw = os.environ.get("KSI_CORE_RUNTIME_ROUTE_CONFIGURATIONS_JSON")
    if raw is None:
        return ()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(
            "KSI_CORE_RUNTIME_ROUTE_CONFIGURATIONS_JSON 이 유효한 JSON 이 아니다"
        ) from exc
    if not isinstance(payload, list):
        raise RuntimeError("KSI_CORE_RUNTIME_ROUTE_CONFIGURATIONS_JSON 은 배열이어야 한다")
    configurations: list[TrustedRuntimeRouteConfigurationV1] = []
    for index, item in enumerate(payload):
        try:
            configuration = TrustedRuntimeRouteConfigurationV1.model_validate(item)
        except Exception as exc:  # noqa: BLE001 -- environment config fails closed
            raise RuntimeError(
                f"KSI_CORE_RUNTIME_ROUTE_CONFIGURATIONS_JSON[{index}]가 exact CAP-5 config가 아니다"
            ) from exc
        expected_policy = freshness_policies.get(configuration.freshness_policy_id)
        if (
            expected_policy is None
            or expected_policy.freshness_policy_digest
            != configuration.freshness_policy_digest
        ):
            raise RuntimeError(
                f"KSI_CORE_RUNTIME_ROUTE_CONFIGURATIONS_JSON[{index}] freshness policy가 "
                "Core registry와 exact-match하지 않는다"
            )
        configurations.append(configuration)
    return tuple(configurations)


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
