"""CAP-5 authenticated ingress and scoped diagnostic API boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.capability.runtime_api import (
    MissionPolicyDecision,
    RuntimeRoutePreflightRequestV1,
    _mission_policy_for_new_route,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_domain.capability_contract import (
    CanonicalTransportCapability,
    CapabilityIntegrationPath,
)
from ksi_domain.enums import MissionExecutionStatus
from test_capability_runtime_projection import (
    ACTIVE_NOW,
    FRESHNESS_POLICY_ID,
    RUNTIME_FRESHNESS_POLICY,
    _legacy_cloud_configuration,
    _observation,
    _runtime,
)
from test_mission_contract_roundtrip import _valid_contract_dict

_EDGE_TOKEN = "cap5-edge-token"
_VIEWER_TOKEN = "cap5-viewer-token"
_OTHER_TOKEN = "cap5-other-token"
_GATEWAY_TOKEN = "cap5-gateway-token"
_EDGE_ROUTE_OBSERVER_TOKEN = "cap5-edge-route-observer-token"

RuntimeOperation = Literal[
    "WAYLINE_DISPATCH", "EDGE_DISPATCH", "EDGE_UPLINK", "MEDIA_SYNC"
]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_EDGE_TOKEN),
                principal=Principal(
                    principal_id="edge-runtime-1",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id="edge-1",
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_GATEWAY_TOKEN),
                principal=Principal(
                    principal_id="gateway-runtime-1",
                    kind=PrincipalKind.GATEWAY_DEVICE,
                    role=None,
                    device_id="gateway-1",
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_EDGE_ROUTE_OBSERVER_TOKEN),
                principal=Principal(
                    principal_id="route-observer-1",
                    kind=PrincipalKind.EDGE_ROUTE_OBSERVER,
                    role=None,
                    device_id="edge-1",
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="viewer-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id="org-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_TOKEN),
                principal=Principal(
                    principal_id="viewer-other",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id="org-other",
                ),
            ),
        ]
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_runtime_observation_ingress_is_authenticated_and_exact(tmp_path: Path) -> None:
    _authority, _activation, config, _observations, projector = _runtime(tmp_path)
    app = create_app(auth_registry=_registry(), runtime_capability_projector=projector)
    client = TestClient(app)
    now = datetime.now(UTC)
    observation = _observation(
        config,
        observed_at=now - timedelta(seconds=1),
        expires_at=now - timedelta(seconds=1) + timedelta(minutes=5),
    )

    unauthenticated = client.post(
        "/v1/capability-runtime/observations",
        json=observation.model_dump(mode="json", by_alias=True),
    )
    assert unauthenticated.status_code == 401

    created = client.post(
        "/v1/capability-runtime/observations",
        headers=_headers(_EDGE_TOKEN),
        json=observation.model_dump(mode="json", by_alias=True),
    )
    assert created.status_code == 201
    assert created.json()["disposition"] == "RECORDED"
    assert created.json()["observation"]["subjectPortId"] == config.subject_port_id

    retried = client.post(
        "/v1/capability-runtime/observations",
        headers=_headers(_EDGE_TOKEN),
        json=observation.model_dump(mode="json", by_alias=True),
    )
    assert retried.status_code == 201
    assert retried.json()["disposition"] == "EXACT_RETRY"


def test_edge_route_observer_ingress_has_exact_edge_subject_scope(tmp_path: Path) -> None:
    _authority, _activation, config, _observations, projector = _runtime(
        tmp_path, edge_route=True
    )
    client = TestClient(
        create_app(auth_registry=_registry(), runtime_capability_projector=projector)
    )
    now = datetime.now(UTC)
    observation = _observation(
        config,
        observed_at=now - timedelta(seconds=1),
        expires_at=now - timedelta(seconds=1) + timedelta(minutes=5),
    ).model_copy(
        update={
            "producer_principal_id": "route-observer-1",
            "producer_principal_kind": PrincipalKind.EDGE_ROUTE_OBSERVER,
        }
    )

    created = client.post(
        "/v1/capability-runtime/observations",
        headers=_headers(_EDGE_ROUTE_OBSERVER_TOKEN),
        json=observation.model_dump(mode="json", by_alias=True),
    )
    assert created.status_code == 201

    legacy_edge = observation.model_copy(
        update={
            "observation_id": "legacy-edge-observation",
            "observed_at": now,
            "expires_at": now + timedelta(minutes=5),
            "producer_principal_id": "edge-runtime-1",
            "producer_principal_kind": PrincipalKind.EDGE_DEVICE,
        }
    )
    assert (
        client.post(
            "/v1/capability-runtime/observations",
            headers=_headers(_EDGE_TOKEN),
            json=legacy_edge.model_dump(mode="json", by_alias=True),
        ).status_code
        == 201
    )

    gateway_claim = observation.model_copy(
        update={
            "observation_id": "gateway-claim-observation",
            "producer_principal_id": "gateway-runtime-1",
            "producer_principal_kind": PrincipalKind.GATEWAY_DEVICE,
        }
    )
    assert (
        client.post(
            "/v1/capability-runtime/observations",
            headers=_headers(_GATEWAY_TOKEN),
            json=gateway_claim.model_dump(mode="json", by_alias=True),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/capability-runtime/observations",
            headers=_headers(_VIEWER_TOKEN),
            json=observation.model_dump(mode="json", by_alias=True),
        ).status_code
        == 403
    )


def test_scoped_runtime_view_never_becomes_http_authorization_token(tmp_path: Path) -> None:
    _authority, activation, _config, _observations, projector = _runtime(tmp_path)
    app = create_app(auth_registry=_registry(), runtime_capability_projector=projector)
    client = TestClient(app)
    path = (
        "/v1/sites/site-1/capability-runtime/activations/"
        f"{activation.activation_authorization_id}"
    )

    response = client.get(path, headers=_headers(_VIEWER_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["authorizationPurpose"] == "DIAGNOSTIC_ONLY"
    assert body["currentMissionPolicyAllows"] is False
    assert body["operationallyUsable"] is False
    assert body["newRouteInvocationAllowed"] is False
    assert "does not authorize" in body["warning"]

    assert client.get(path, headers=_headers(_OTHER_TOKEN)).status_code == 404
    wrong_site = path.replace("site-1", "site-other")
    assert client.get(wrong_site, headers=_headers(_VIEWER_TOKEN)).status_code == 404


def test_public_capabilities_remains_unscoped_catalog_only(tmp_path: Path) -> None:
    _authority, _activation, _config, _observations, projector = _runtime(tmp_path)
    app = create_app(auth_registry=_registry(), runtime_capability_projector=projector)
    response = TestClient(app).get("/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"capabilities", "count"}
    assert "operationallyUsable" not in response.text
    assert "currentRuntimeReady" not in response.text


def test_authenticated_gateway_preflight_uses_independent_mission_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ksi_core.capability.runtime_api._utc_now", lambda: ACTIVE_NOW)
    _authority, activation, config, _observations, projector = _runtime(tmp_path)
    now = ACTIVE_NOW
    projector.ingest_observation(
        _observation(
            config,
            observed_at=now - timedelta(seconds=1),
            expires_at=now - timedelta(seconds=1) + timedelta(minutes=5),
        ),
        principal=Principal(
            principal_id="edge-runtime-1",
            kind=PrincipalKind.EDGE_DEVICE,
            role=None,
            device_id="edge-1",
            organization_id="org-1",
        ),
        received_at=now,
    )
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    contract = _valid_contract_dict("1.2")
    contract["missionId"] = "mission-1"
    contract["siteId"] = "site-1"
    contract["validity"] = {
        "notBefore": (now - timedelta(minutes=1)).isoformat(),
        "notAfter": (now + timedelta(minutes=5)).isoformat(),
    }
    assert mission_store.record_issuance(
        MissionRecord(
            mission_id="mission-1",
            site_id="site-1",
            mission_type="UNIFIED_SITE_SURVEY",
            artifact_kind="contract",
            contract=contract,
            kmz_sha256=None,
            route_pattern=None,
            waypoint_count=None,
            planned_coverage_ratio=None,
            issued_at=now,
            issued_by="operator-1",
            organization_id="org-1",
            assigned_device_id="edge-1",
        )
    ).value == "RECORDED"
    execution_store = MissionExecutionStore(
        DurableJournal(tmp_path / "mission-execution.jsonl"),
        mission_store=mission_store,
    )
    app = create_app(
        auth_registry=_registry(),
        runtime_capability_projector=projector,
        mission_store=mission_store,
        mission_execution_store=execution_store,
    )
    client = TestClient(app)
    gateway_component = next(
        component
        for component in activation.configured_deployment.equipment_scope.components
        if component.role.value == "GATEWAY"
    )
    request = {
        "organizationId": "org-1",
        "siteId": "site-1",
        "gatewayDeviceId": "gateway-1",
        "edgeDeviceId": "edge-1",
        "canonicalCapability": "EDGE_DOWNLINK",
        "integrationPath": "MSDK_FIELD",
        "subjectPortId": config.subject_port_id,
        "transport": "MOP",
        "hardwareModel": gateway_component.hardware_model,
        "firmwareVersion": gateway_component.firmware_or_image_version,
        "missionId": "mission-1",
        "operation": "EDGE_DISPATCH",
        "idempotencyKey": "preflight-1",
        "activationAuthorizationId": activation.activation_authorization_id,
    }

    assert client.post("/v1/capability-runtime/preflight", json=request).status_code == 401
    assert client.post(
        "/v1/capability-runtime/preflight",
        headers=_headers(_EDGE_TOKEN),
        json=request,
    ).status_code == 403
    allowed = client.post(
        "/v1/capability-runtime/preflight",
        headers=_headers(_GATEWAY_TOKEN),
        json=request,
    )
    assert allowed.status_code == 200
    assert allowed.json()["operationallyUsable"] is True
    assert allowed.json()["currentMissionPolicyAllows"] is True

    wrong_gateway = dict(request, gatewayDeviceId="gateway-other")
    denied = client.post(
        "/v1/capability-runtime/preflight",
        headers=_headers(_GATEWAY_TOKEN),
        json=wrong_gateway,
    )
    assert denied.status_code == 200
    assert denied.json()["operationallyUsable"] is False
    assert denied.json()["currentMissionPolicyAllows"] is False


@pytest.mark.parametrize(
    ("terminal_state", "operation", "expected"),
    [
        *[
            (state, operation, MissionPolicyDecision.DENY)
            for state in (
                MissionExecutionStatus.CANCELLED,
                MissionExecutionStatus.COMPLETED,
                MissionExecutionStatus.ENDED_INCOMPLETE,
            )
            for operation in ("WAYLINE_DISPATCH", "EDGE_DISPATCH")
        ],
        *[
            (state, operation, MissionPolicyDecision.ALLOW)
            for state in (
                MissionExecutionStatus.CANCELLED,
                MissionExecutionStatus.COMPLETED,
                MissionExecutionStatus.ENDED_INCOMPLETE,
            )
            for operation in ("EDGE_UPLINK", "MEDIA_SYNC")
        ],
        (MissionExecutionStatus.ISSUED, "EDGE_DISPATCH", MissionPolicyDecision.ALLOW),
    ],
)
def test_runtime_preflight_terminal_execution_policy_is_operation_specific(
    tmp_path: Path,
    terminal_state: MissionExecutionStatus,
    operation: RuntimeOperation,
    expected: MissionPolicyDecision,
) -> None:
    _authority, activation, config, _observations, _projector = _runtime(tmp_path)
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    contract = _valid_contract_dict("1.2")
    contract["missionId"] = "mission-terminal"
    contract["siteId"] = "site-1"
    contract["validity"] = {
        "notBefore": (ACTIVE_NOW - timedelta(minutes=1)).isoformat(),
        "notAfter": (ACTIVE_NOW + timedelta(minutes=5)).isoformat(),
    }
    assert mission_store.record_issuance(
        MissionRecord(
            mission_id="mission-terminal",
            site_id="site-1",
            mission_type="UNIFIED_SITE_SURVEY",
            artifact_kind="contract",
            contract=contract,
            kmz_sha256=None,
            route_pattern=None,
            waypoint_count=None,
            planned_coverage_ratio=None,
            issued_at=ACTIVE_NOW,
            issued_by="operator-1",
            organization_id="org-1",
            assigned_device_id="edge-1",
        )
    ).value == "RECORDED"
    execution_store = MissionExecutionStore(
        DurableJournal(tmp_path / "mission-execution.jsonl"), mission_store=mission_store
    )
    if terminal_state is not MissionExecutionStatus.ISSUED:
        assert execution_store.transition(
            "mission-terminal",
            terminal_state,
            detail=None,
            actor="test",
            now=ACTIVE_NOW,
        ).verdict.value == "TRANSITIONED"
    capability: CanonicalTransportCapability = {
        "WAYLINE_DISPATCH": CanonicalTransportCapability.WAYLINE_DELIVERY,
        "EDGE_DISPATCH": CanonicalTransportCapability.EDGE_DOWNLINK,
        "EDGE_UPLINK": CanonicalTransportCapability.EDGE_UPLINK,
        "MEDIA_SYNC": CanonicalTransportCapability.MEDIA_PULL,
    }[operation]
    request = RuntimeRoutePreflightRequestV1(
        organization_id="org-1",
        site_id="site-1",
        gateway_device_id="gateway-1",
        edge_device_id="edge-1",
        canonical_capability=capability,
        integration_path=CapabilityIntegrationPath.MSDK_FIELD,
        subject_port_id=config.subject_port_id,
        transport="MOP",
        hardware_model="gateway",
        firmware_version="1",
        mission_id="mission-terminal",
        operation=operation,
        idempotency_key="terminal-policy",
        activation_authorization_id=activation.activation_authorization_id,
    )
    assert _mission_policy_for_new_route(
        request,
        mission_store=mission_store,
        mission_execution_store=execution_store,
        now=ACTIVE_NOW,
    ) is expected


def test_runtime_surface_cannot_be_assembled_without_authentication(tmp_path: Path) -> None:
    _authority, _activation, _config, _observations, projector = _runtime(tmp_path)
    try:
        create_app(runtime_capability_projector=projector)
    except ValueError as exc:
        assert "auth_registry" in str(exc)
    else:  # pragma: no cover - fail-closed assertion branch
        raise AssertionError("runtime surface assembled without auth_registry")


@pytest.mark.parametrize(
    "field",
    [
        "organizationId", "siteId", "gatewayDeviceId", "edgeDeviceId", "subjectPortId",
        "transport", "hardwareModel", "firmwareVersion", "missionId", "idempotencyKey",
        "activationAuthorizationId",
    ],
)
@pytest.mark.parametrize("invalid", ["bad/id", "bad\n"])
def test_runtime_preflight_rejects_path_unsafe_identifiers_with_422(
    tmp_path: Path, field: str, invalid: str
) -> None:
    _authority, activation, config, _observations, projector = _runtime(tmp_path)
    app = create_app(auth_registry=_registry(), runtime_capability_projector=projector)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/capability-runtime/preflight",
        headers=_headers(_GATEWAY_TOKEN),
        json=dict({
            "organizationId": "org-1",
            "siteId": "site-1",
            "gatewayDeviceId": "gateway-1",
            "edgeDeviceId": "edge-1",
            "canonicalCapability": "EDGE_DOWNLINK",
            "integrationPath": "MSDK_FIELD",
            "subjectPortId": config.subject_port_id,
            "transport": "MOP",
            "hardwareModel": "gateway",
            "firmwareVersion": "1",
            "missionId": "mission-1",
            "operation": "EDGE_DISPATCH",
            "idempotencyKey": "retry",
            "activationAuthorizationId": activation.activation_authorization_id,
        }, **{field: invalid}),
    )
    assert response.status_code == 422


def test_production_runtime_configuration_is_typed_and_policy_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import (
        _optional_capability_freshness_policies,
        _optional_runtime_route_configurations,
    )

    config = _legacy_cloud_configuration()
    monkeypatch.setenv(
        "KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON",
        json.dumps(
            {
                FRESHNESS_POLICY_ID: RUNTIME_FRESHNESS_POLICY.model_dump(
                    mode="json", by_alias=True
                )
            }
        ),
    )
    monkeypatch.setenv(
        "KSI_CORE_RUNTIME_ROUTE_CONFIGURATIONS_JSON",
        json.dumps([config.model_dump(mode="json", by_alias=True)]),
    )
    policies = _optional_capability_freshness_policies()
    configurations = _optional_runtime_route_configurations(
        freshness_policies=policies
    )
    assert policies == {FRESHNESS_POLICY_ID: RUNTIME_FRESHNESS_POLICY}
    assert configurations == (config,)

    changed_policy = RUNTIME_FRESHNESS_POLICY.model_dump(mode="json", by_alias=True)
    changed_policy["observationTtlSeconds"] = 299
    monkeypatch.setenv(
        "KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON",
        json.dumps({FRESHNESS_POLICY_ID: changed_policy}),
    )
    with pytest.raises(RuntimeError, match="exact RuntimeRouteFreshnessPolicyV1"):
        _optional_capability_freshness_policies()

    monkeypatch.setenv("KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON", "{}")
    with pytest.raises(RuntimeError, match="exact-match"):
        _optional_runtime_route_configurations(freshness_policies={})


def test_production_runtime_configuration_defaults_fail_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import (
        _optional_capability_freshness_policies,
        _optional_runtime_route_configurations,
    )

    monkeypatch.delenv("KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON", raising=False)
    monkeypatch.delenv("KSI_CORE_RUNTIME_ROUTE_CONFIGURATIONS_JSON", raising=False)
    assert _optional_capability_freshness_policies() == {}
    assert _optional_runtime_route_configurations(freshness_policies={}) == ()
