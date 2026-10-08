"""Pure, fail-closed production environment parsing helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from ksi_mission_contracts.risk_policy import RiskPolicyPackV1, risk_policy_pack_wire_dict
from ksi_mission_contracts.runtime_profile import (
    EdgeRuntimeProfileV1,
    edge_runtime_profile_wire_dict,
)

from ksi_core.capability.runtime_projection import (
    RuntimeRouteFreshnessPolicyV1,
    TrustedRuntimeRouteConfigurationV1,
)
from ksi_core.composition.runtime_config import (
    _EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT as _EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT,
)
from ksi_core.composition.runtime_config import (
    _JOURNAL_SEGMENT_BYTES_DEFAULT as _JOURNAL_SEGMENT_BYTES_DEFAULT,
)
from ksi_core.composition.runtime_config import (
    _analysis_activation_paths_env as _analysis_activation_paths_env,
)
from ksi_core.composition.runtime_config import _expose_docs_env as _expose_docs_env
from ksi_core.composition.runtime_config import (
    _external_authority_paths_env as _external_authority_paths_env,
)
from ksi_core.composition.runtime_config import (
    _human_auth_config_env as _human_auth_config_env,
)
from ksi_core.composition.runtime_config import (
    _optional_positive_env as _optional_positive_env,
)
from ksi_core.composition.runtime_config import (
    _parse_principal_tokens as _parse_principal_tokens,
)
from ksi_core.composition.runtime_config import _require_dir as _require_dir
from ksi_core.composition.runtime_config import _require_env as _require_env

if TYPE_CHECKING:
    from ksi_core.copilot_openai import CopilotRuntimeConfig

_ISSUER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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
