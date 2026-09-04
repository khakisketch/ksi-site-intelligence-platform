"""CAP-5 exact runtime observation and three-conjunct projection contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from ksi_core.acquisition.models import (
    AcquisitionCapability,
    AcquisitionDeploymentProfileV1,
    CapabilityReceiptV1,
    CapabilityStatus,
    ConnectionState,
    ConnectivitySnapshotV1,
    DirectEdgeState,
    GatewayKind,
    GatewayTransport,
    InternetGate,
    ManifoldDirectMode,
    MediaPolicy,
    MsdkBridgeMode,
    OperatingMode,
    RoutingPolicy,
    SyncState,
)
from ksi_core.acquisition.store import AcquisitionConnectivityStore
from ksi_core.auth import Principal, PrincipalKind
from ksi_core.capability.authority_store import (
    ActivationLifecycleStatus,
    CapabilityAuthorityStore,
    ConfiguredDeploymentSnapshotV1,
    OperationalCapabilityActivationRecordV1,
)
from ksi_core.capability.runtime_projection import (
    ExistingMissionContractEffect,
    LegacyConnectivityAdaptationError,
    LegacyConnectivitySnapshotAdapter,
    MissionPolicyDecision,
    ObservationIngestDisposition,
    RuntimeCapabilityProjection,
    RuntimeCapabilityProjector,
    RuntimeCapabilityValidationError,
    RuntimeEffectClassification,
    RuntimeObservationConflict,
    RuntimeObservationRecoveryError,
    RuntimeProjectionReason,
    RuntimeRouteAvailability,
    RuntimeRouteFreshnessPolicyV1,
    RuntimeRouteInvocationRequest,
    RuntimeRouteObservationStore,
    RuntimeRouteObservationV1,
    TrustedRuntimeRouteConfigurationRegistry,
    TrustedRuntimeRouteConfigurationV1,
)
from ksi_core.durable_journal import DurableJournal
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_domain.capability_contract import (
    CanonicalTransportCapability,
    CapabilityIntegrationPath,
    RuntimeRouteSubjectKind,
)
from pydantic import ValidationError

# Reuse the independently closed CAP-4 authority fixture instead of creating a
# fake activation model in CAP-5 tests.
from test_capability_activation_authority import (
    ACTIVE_NOW,
    BUILD,
    FRESHNESS_POLICY_DIGEST,
    FRESHNESS_POLICY_ID,
    NOW,
    POLICY,
    _activation_revocation,
    _admin,
    _approval,
    _approval_revocation,
    _approve,
    _equipment,
    _evidence_revocation,
    _open,
    _seed_activation,
    _seed_evidence,
    _suspension,
)


def _freshness_policy(
    policy_id: str = FRESHNESS_POLICY_ID,
    *,
    ttl_seconds: int = 300,
    minimum_margin_seconds: float = 30.0,
) -> RuntimeRouteFreshnessPolicyV1:
    payload = {
        "schemaVersion": "1.0",
        "freshnessPolicyId": policy_id,
        "observationTtlSeconds": ttl_seconds,
        "minimumRefreshMarginSeconds": minimum_margin_seconds,
    }
    return RuntimeRouteFreshnessPolicyV1(
        schema_version="1.0",
        freshness_policy_id=policy_id,
        observation_ttl_seconds=ttl_seconds,
        minimum_refresh_margin_seconds=minimum_margin_seconds,
        freshness_policy_digest=(
            "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        ),
    )


RUNTIME_FRESHNESS_POLICY = _freshness_policy()
RUNTIME_FRESHNESS_POLICIES = {
    FRESHNESS_POLICY_ID: RUNTIME_FRESHNESS_POLICY,
}


def _configuration(
    activation: OperationalCapabilityActivationRecordV1,
    *,
    flag: bool = True,
    ready: bool = True,
    port: str = "msdk.edge_downlink",
    policy_id: str = FRESHNESS_POLICY_ID,
    policy_digest: str = FRESHNESS_POLICY_DIGEST,
) -> TrustedRuntimeRouteConfigurationV1:
    configured = activation.configured_deployment
    return TrustedRuntimeRouteConfigurationV1(
        configured_deployment=configured,
        configured_deployment_digest=configured.canonical_digest,
        subject_kind=RuntimeRouteSubjectKind.GATEWAY_EDGE_ROUTE_PORT,
        subject_device_ids=(configured.gateway_device_id, configured.edge_device_id),
        subject_port_id=port,
        selected_transport="MOP",
        allowed_transports=("MOP",),
        feature_flag_enabled=flag,
        port_configuration_ready=ready,
        freshness_policy_id=policy_id,
        freshness_policy_digest=policy_digest,
    )


def _observation(
    config: TrustedRuntimeRouteConfigurationV1,
    *,
    observation_id: str = "runtime-observation-1",
    availability: RuntimeRouteAvailability = RuntimeRouteAvailability.REPORTED_AVAILABLE,
    observed_at: datetime = ACTIVE_NOW,
    expires_at: datetime | None = None,
    policy_id: str | None = None,
    policy_digest: str | None = None,
) -> RuntimeRouteObservationV1:
    configured = config.configured_deployment
    return RuntimeRouteObservationV1(
        observation_id=observation_id,
        organization_id=configured.organization_id,
        site_id=configured.site_id,
        configured_deployment_digest=config.configured_deployment_digest,
        subject_kind=config.subject_kind,
        subject_device_ids=config.subject_device_ids,
        subject_port_id=config.subject_port_id,
        integration_path=configured.integration_path,
        canonical_capability_id=configured.canonical_capability_id,
        equipment_scope_digest=configured.equipment_scope_digest,
        runtime_build_digest=configured.runtime_build_digest,
        availability=availability,
        observed_at=observed_at,
        expires_at=expires_at or observed_at + timedelta(minutes=5),
        freshness_policy_id=policy_id or config.freshness_policy_id,
        freshness_policy_digest=policy_digest or config.freshness_policy_digest,
        producer_principal_id="edge-runtime-1",
        producer_principal_kind=PrincipalKind.EDGE_DEVICE,
        source_observation_ref=f"runtime-event:{observation_id}",
    )


def _edge(organization_id: str = "org-1", device_id: str = "edge-1") -> Principal:
    return Principal(
        principal_id="edge-runtime-1",
        kind=PrincipalKind.EDGE_DEVICE,
        role=None,
        device_id=device_id,
        organization_id=organization_id,
    )


def _runtime(
    tmp_path: Path,
    *,
    flag: bool = True,
    ready: bool = True,
    policies: dict[str, RuntimeRouteFreshnessPolicyV1] | None = None,
) -> tuple[
    CapabilityAuthorityStore,
    OperationalCapabilityActivationRecordV1,
    TrustedRuntimeRouteConfigurationV1,
    RuntimeRouteObservationStore,
    RuntimeCapabilityProjector,
]:
    authority = _open(tmp_path / "authority.jsonl")
    _, _, activation = _seed_activation(authority)
    config = _configuration(activation, flag=flag, ready=ready)
    observations = RuntimeRouteObservationStore(
        DurableJournal(tmp_path / "runtime-observations.jsonl")
    )
    projector = RuntimeCapabilityProjector(
        authority_store=authority,
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry((config,)),
        observation_store=observations,
        supported_freshness_policies=(
            RUNTIME_FRESHNESS_POLICIES if policies is None else policies
        ),
    )
    return authority, activation, config, observations, projector


def _project(
    projector: RuntimeCapabilityProjector,
    activation: OperationalCapabilityActivationRecordV1,
    *,
    now: datetime = ACTIVE_NOW,
    mission: MissionPolicyDecision = MissionPolicyDecision.ALLOW,
    organization_id: str = "org-1",
) -> RuntimeCapabilityProjection:
    return projector.project(
        activation.activation_authorization_id,
        trusted_organization_id=organization_id,
        mission_policy=mission,
        now=now,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("availability", "REPORTED_UNAVAILABLE"),
        ("observedAt", "2026-08-31T01:00:01Z"),
        ("expiresAt", "2026-08-31T01:06:00Z"),
        ("subjectPortId", "tampered-port"),
        ("payloadSha256", "sha256:" + "0" * 64),
    ],
)
def test_observation_journal_tamper_fails_closed_on_recovery(
    tmp_path: Path, field: str, value: str
) -> None:
    path = tmp_path / "tamper-observations.jsonl"
    store = RuntimeRouteObservationStore(DurableJournal(path))
    _authority, _activation, config, _other_store, _projector = _runtime(
        tmp_path / "fixture"
    )
    store.ingest(_observation(config), received_at=ACTIVE_NOW)
    store.close()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if field == "payloadSha256":
        raw[field] = value
    else:
        raw["payload"]["observation"][field] = value
    path.write_text(json.dumps(raw, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeObservationRecoveryError):
        RuntimeRouteObservationStore(DurableJournal(path))


def _invocation(
    activation: OperationalCapabilityActivationRecordV1,
    config: TrustedRuntimeRouteConfigurationV1,
    **updates: object,
) -> RuntimeRouteInvocationRequest:
    scope = activation.activation_scope
    gateway_component = next(
        component
        for component in activation.configured_deployment.equipment_scope.components
        if component.role.value == "GATEWAY"
    )
    values: dict[str, object] = {
        "activation_authorization_id": activation.activation_authorization_id,
        "organization_id": scope.organization_id,
        "site_id": scope.site_id,
        "gateway_device_id": scope.gateway_device_id,
        "edge_device_id": scope.edge_device_id,
        "canonical_capability_id": scope.canonical_capability_id,
        "integration_path": scope.integration_path,
        "subject_port_id": config.subject_port_id,
        "selected_transport": config.selected_transport,
        "hardware_model": gateway_component.hardware_model,
        "firmware_version": gateway_component.firmware_or_image_version,
    }
    values.update(updates)
    return RuntimeRouteInvocationRequest(**values)  # type: ignore[arg-type]


def test_all_three_conjuncts_are_separate_and_required(tmp_path: Path) -> None:
    _authority, activation, config, _store, projector = _runtime(tmp_path)
    projector.ingest_observation(
        _observation(config), principal=_edge(), received_at=ACTIVE_NOW
    )
    allowed = _project(projector, activation)
    assert (
        allowed.durable_authority_valid,
        allowed.current_runtime_ready,
        allowed.current_mission_policy_allows,
        allowed.operationally_usable,
    ) == (True, True, True, True)
    assert allowed.reason is RuntimeProjectionReason.OPERATIONALLY_USABLE
    assert allowed.classification is RuntimeEffectClassification.OPERATIONALLY_USABLE
    assert allowed.new_route_invocation_allowed is True

    denied = _project(projector, activation, mission=MissionPolicyDecision.DENY)
    assert denied.durable_authority_valid is True
    assert denied.current_runtime_ready is True
    assert denied.current_mission_policy_allows is False
    assert denied.operationally_usable is False
    assert denied.reason is RuntimeProjectionReason.MISSION_POLICY_DENIED


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        (
            {"integration_path": CapabilityIntegrationPath.PSDK_MANIFOLD},
            RuntimeProjectionReason.OBSERVATION_WRONG_ROUTE,
        ),
        (
            {"subject_port_id": "wrong.route-port"},
            RuntimeProjectionReason.OBSERVATION_WRONG_ROUTE,
        ),
        (
            {"gateway_device_id": "gateway-other"},
            RuntimeProjectionReason.OBSERVATION_WRONG_COMPONENT,
        ),
        (
            {"edge_device_id": "edge-other"},
            RuntimeProjectionReason.OBSERVATION_WRONG_COMPONENT,
        ),
        (
            {"selected_transport": "RC_WIFI"},
            RuntimeProjectionReason.TRANSPORT_NOT_ALLOWED,
        ),
    ],
)
def test_new_route_consumer_must_match_exact_activation_and_port(
    tmp_path: Path,
    updates: dict[str, object],
    reason: RuntimeProjectionReason,
) -> None:
    _authority, activation, config, _store, projector = _runtime(tmp_path)
    projector.ingest_observation(
        _observation(config), principal=_edge(), received_at=ACTIVE_NOW
    )
    projection = projector.project_new_route_invocation(
        _invocation(activation, config, **updates),
        mission_policy=MissionPolicyDecision.ALLOW,
        now=ACTIVE_NOW,
    )
    assert projection.current_runtime_ready is False
    assert projection.operationally_usable is False
    assert projection.reason is reason


def test_exact_new_route_invocation_still_requires_mission_policy(tmp_path: Path) -> None:
    _authority, activation, config, _store, projector = _runtime(tmp_path)
    projector.ingest_observation(
        _observation(config), principal=_edge(), received_at=ACTIVE_NOW
    )
    request = _invocation(activation, config)
    denied = projector.project_new_route_invocation(
        request, mission_policy=MissionPolicyDecision.DENY, now=ACTIVE_NOW
    )
    assert denied.current_runtime_ready is True
    assert denied.reason is RuntimeProjectionReason.MISSION_POLICY_DENIED
    assert denied.new_route_invocation_allowed is False

    allowed = projector.project_new_route_invocation(
        request, mission_policy=MissionPolicyDecision.ALLOW, now=ACTIVE_NOW
    )
    assert allowed.operationally_usable is True


def test_active_activation_alone_does_not_bypass_runtime_or_flag(tmp_path: Path) -> None:
    _authority, activation, _config, _store, projector = _runtime(tmp_path)
    missing = _project(projector, activation)
    assert missing.durable_authority_valid is True
    assert missing.current_runtime_ready is False
    assert missing.reason is RuntimeProjectionReason.OBSERVATION_MISSING

    other = tmp_path / "flag-off"
    other.mkdir()
    _authority2, activation2, config2, _store2, projector2 = _runtime(other, flag=False)
    projector2.ingest_observation(
        _observation(config2), principal=_edge(), received_at=ACTIVE_NOW
    )
    flag_off = _project(projector2, activation2)
    assert flag_off.reason is RuntimeProjectionReason.FEATURE_FLAG_OFF
    assert flag_off.current_runtime_ready is False
    assert flag_off.operationally_usable is False


@pytest.mark.parametrize(
    ("now_offset", "expected", "reason"),
    [
        (timedelta(seconds=-1), False, RuntimeProjectionReason.OBSERVATION_FUTURE_DATED),
        (timedelta(0), True, RuntimeProjectionReason.OPERATIONALLY_USABLE),
        (timedelta(minutes=4, seconds=59), True, RuntimeProjectionReason.OPERATIONALLY_USABLE),
        (timedelta(minutes=5), False, RuntimeProjectionReason.OBSERVATION_STALE),
        (timedelta(minutes=5, seconds=1), False, RuntimeProjectionReason.OBSERVATION_STALE),
    ],
)
def test_observation_interval_is_closed_open(
    tmp_path: Path,
    now_offset: timedelta,
    expected: bool,
    reason: RuntimeProjectionReason,
) -> None:
    _authority, activation, config, observations, projector = _runtime(tmp_path)
    # Store replay can legitimately contain a record whose observedAt is later
    # than a historical evaluation point; ingest itself rejects future reports.
    observations.ingest(_observation(config), received_at=ACTIVE_NOW)
    projection = _project(projector, activation, now=ACTIVE_NOW + now_offset)
    assert projection.current_runtime_ready is expected
    assert projection.reason is reason


def test_live_ingress_rejects_future_dated_observation(tmp_path: Path) -> None:
    _authority, _activation, config, _store, projector = _runtime(tmp_path)
    with pytest.raises(RuntimeCapabilityValidationError, match="future-dated"):
        projector.ingest_observation(
            _observation(config, observed_at=ACTIVE_NOW + timedelta(seconds=1)),
            principal=_edge(),
            received_at=ACTIVE_NOW,
        )


@pytest.mark.parametrize(
    ("availability", "reason"),
    [
        (
            RuntimeRouteAvailability.REPORTED_UNAVAILABLE,
            RuntimeProjectionReason.OBSERVATION_UNAVAILABLE,
        ),
        (RuntimeRouteAvailability.UNKNOWN, RuntimeProjectionReason.OBSERVATION_UNKNOWN),
    ],
)
def test_only_explicit_reported_available_is_usable(
    tmp_path: Path,
    availability: RuntimeRouteAvailability,
    reason: RuntimeProjectionReason,
) -> None:
    _authority, activation, config, _store, projector = _runtime(tmp_path)
    projector.ingest_observation(
        _observation(config, availability=availability),
        principal=_edge(),
        received_at=ACTIVE_NOW,
    )
    projection = _project(projector, activation)
    assert projection.current_runtime_ready is False
    assert projection.reason is reason


def test_freshness_policy_requires_exact_activation_pair(tmp_path: Path) -> None:
    _authority, activation, config, observations, projector = _runtime(tmp_path)
    wrong_digest = _observation(config).model_copy(
        update={"freshness_policy_digest": "sha256:" + "8" * 64}
    )
    observations.ingest(wrong_digest, received_at=ACTIVE_NOW)
    mismatch = _project(projector, activation)
    assert mismatch.reason is RuntimeProjectionReason.FRESHNESS_POLICY_MISMATCH

    missing_policy_dir = tmp_path / "missing-policy"
    missing_policy_dir.mkdir()
    _a2, activation2, config2, store2, projector2 = _runtime(
        missing_policy_dir, policies={}
    )
    store2.ingest(_observation(config2), received_at=ACTIVE_NOW)
    unknown = _project(projector2, activation2)
    assert unknown.reason is RuntimeProjectionReason.FRESHNESS_POLICY_UNKNOWN


@pytest.mark.parametrize("ttl_seconds", [299, 301])
def test_core_ingress_rejects_policy_inconsistent_validity_window(
    tmp_path: Path, ttl_seconds: int
) -> None:
    _authority, _activation, config, _observations, projector = _runtime(tmp_path)
    observation = _observation(
        config,
        expires_at=ACTIVE_NOW + timedelta(seconds=ttl_seconds),
    )
    with pytest.raises(RuntimeCapabilityValidationError, match="validity interval"):
        projector.ingest_observation(
            observation,
            principal=_edge(),
            received_at=ACTIVE_NOW,
        )


def test_projection_rejects_replayed_policy_inconsistent_validity_window(
    tmp_path: Path,
) -> None:
    _authority, activation, config, observations, projector = _runtime(tmp_path)
    observations.ingest(
        _observation(config, expires_at=ACTIVE_NOW + timedelta(seconds=299)),
        received_at=ACTIVE_NOW,
    )

    projection = _project(projector, activation)

    assert projection.current_runtime_ready is False
    assert projection.reason is RuntimeProjectionReason.FRESHNESS_POLICY_MISMATCH


def test_freshness_policy_content_is_bound_to_its_digest() -> None:
    raw = RUNTIME_FRESHNESS_POLICY.model_dump(mode="json", by_alias=True)
    raw["observationTtlSeconds"] = 299
    with pytest.raises(ValidationError, match="canonical policy content"):
        RuntimeRouteFreshnessPolicyV1.model_validate(raw)


@pytest.mark.parametrize(
    ("policy_id", "policy_digest", "supported"),
    [
        (
            FRESHNESS_POLICY_ID,
            "sha256:" + "8" * 64,
            RUNTIME_FRESHNESS_POLICIES,
        ),
        (
            "ksi-route-observation-freshness-v2",
            _freshness_policy("ksi-route-observation-freshness-v2").freshness_policy_digest,
            RUNTIME_FRESHNESS_POLICIES
            | {
                "ksi-route-observation-freshness-v2": _freshness_policy(
                    "ksi-route-observation-freshness-v2"
                )
            },
        ),
    ],
)
def test_supported_but_not_activation_pinned_policy_is_not_substitutable(
    tmp_path: Path,
    policy_id: str,
    policy_digest: str,
    supported: dict[str, RuntimeRouteFreshnessPolicyV1],
) -> None:
    _authority, activation, config, observations, projector = _runtime(
        tmp_path, policies=supported
    )
    observations.ingest(
        _observation(
            config,
            policy_id=policy_id,
            policy_digest=policy_digest,
        ),
        received_at=ACTIVE_NOW,
    )
    projection = _project(projector, activation)
    assert projection.reason is RuntimeProjectionReason.FRESHNESS_POLICY_MISMATCH
    assert projection.current_runtime_ready is False


def test_exact_retry_conflicting_id_and_out_of_order_are_fail_closed(tmp_path: Path) -> None:
    _authority, _activation, config, observations, _projector = _runtime(tmp_path)
    first = _observation(config)
    recorded = observations.ingest(first, received_at=ACTIVE_NOW)
    retried = observations.ingest(first, received_at=ACTIVE_NOW + timedelta(seconds=1))
    assert recorded.disposition is ObservationIngestDisposition.RECORDED
    assert retried.disposition is ObservationIngestDisposition.EXACT_RETRY
    assert observations.record_count == 1

    changed = first.model_copy(
        update={"availability": RuntimeRouteAvailability.REPORTED_UNAVAILABLE}
    )
    with pytest.raises(RuntimeObservationConflict, match="reused"):
        observations.ingest(changed, received_at=ACTIVE_NOW + timedelta(seconds=1))
    older = _observation(
        config,
        observation_id="older-observation",
        observed_at=ACTIVE_NOW - timedelta(seconds=1),
    )
    with pytest.raises(RuntimeObservationConflict, match="out-of-order"):
        observations.ingest(older, received_at=ACTIVE_NOW + timedelta(seconds=1))
    assert observations.current_for(config.key) == first


def test_equal_timestamp_ambiguity_blocks_until_strictly_newer_report(tmp_path: Path) -> None:
    _authority, activation, config, observations, projector = _runtime(tmp_path)
    observations.ingest(_observation(config), received_at=ACTIVE_NOW)
    same_time = _observation(
        config,
        observation_id="same-time-unavailable",
        availability=RuntimeRouteAvailability.REPORTED_UNAVAILABLE,
    )
    with pytest.raises(RuntimeObservationConflict, match="ordering-ambiguous"):
        observations.ingest(same_time, received_at=ACTIVE_NOW + timedelta(seconds=1))
    blocked = _project(projector, activation, now=ACTIVE_NOW + timedelta(seconds=1))
    assert blocked.reason is RuntimeProjectionReason.OBSERVATION_ORDERING_AMBIGUOUS

    newer = _observation(
        config,
        observation_id="newer-unavailable",
        availability=RuntimeRouteAvailability.REPORTED_UNAVAILABLE,
        observed_at=ACTIVE_NOW + timedelta(seconds=2),
    )
    observations.ingest(newer, received_at=ACTIVE_NOW + timedelta(seconds=2))
    restored_order = _project(projector, activation, now=ACTIVE_NOW + timedelta(seconds=2))
    assert restored_order.reason is RuntimeProjectionReason.OBSERVATION_UNAVAILABLE


def test_ordering_ambiguity_survives_restart_without_ttl_rebase(tmp_path: Path) -> None:
    path = tmp_path / "runtime-observations.jsonl"
    _authority, activation, config, observations, _projector = _runtime(tmp_path)
    observations.ingest(_observation(config), received_at=ACTIVE_NOW)
    with pytest.raises(RuntimeObservationConflict):
        observations.ingest(
            _observation(config, observation_id="ambiguous-restart"),
            received_at=ACTIVE_NOW + timedelta(seconds=1),
        )
    observations.close()
    replayed = RuntimeRouteObservationStore(DurableJournal(path))
    projector = RuntimeCapabilityProjector(
        authority_store=_authority,
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry((config,)),
        observation_store=replayed,
        supported_freshness_policies=RUNTIME_FRESHNESS_POLICIES,
    )
    projection = _project(projector, activation, now=ACTIVE_NOW + timedelta(seconds=2))
    assert projection.reason is RuntimeProjectionReason.OBSERVATION_ORDERING_AMBIGUOUS


def test_replay_preserves_expiry_and_does_not_synthesize_or_extend(tmp_path: Path) -> None:
    path = tmp_path / "runtime-observations.jsonl"
    _authority, activation, config, observations, projector = _runtime(tmp_path)
    original = _observation(config)
    observations.ingest(original, received_at=ACTIVE_NOW)
    observations.close()

    replayed = RuntimeRouteObservationStore(DurableJournal(path))
    replayed_observation = replayed.current_for(config.key)
    assert replayed_observation is not None
    assert replayed_observation.observed_at == original.observed_at
    assert replayed_observation.expires_at == original.expires_at
    replayed_projector = RuntimeCapabilityProjector(
        authority_store=_authority,
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry((config,)),
        observation_store=replayed,
        supported_freshness_policies=RUNTIME_FRESHNESS_POLICIES,
    )
    stale = _project(
        replayed_projector, activation, now=original.expires_at + timedelta(hours=1)
    )
    assert stale.reason is RuntimeProjectionReason.OBSERVATION_STALE

    empty = RuntimeRouteObservationStore(DurableJournal(tmp_path / "empty.jsonl"))
    assert empty.current_for(config.key) is None


def test_temporary_loss_and_reconnect_never_suspend_activation(tmp_path: Path) -> None:
    authority, activation, config, observations, projector = _runtime(tmp_path)
    missing = _project(projector, activation)
    assert missing.classification is RuntimeEffectClassification.TEMPORARY_RUNTIME_INEFFECTIVE
    before = authority.get_activation_projection(
        activation.activation_authorization_id, now=ACTIVE_NOW
    )
    assert before is not None
    assert before.lifecycle_status is ActivationLifecycleStatus.ACTIVE

    observations.ingest(_observation(config), received_at=ACTIVE_NOW)
    restored = _project(projector, activation)
    assert restored.operationally_usable is True
    after = authority.get_activation_projection(
        activation.activation_authorization_id, now=ACTIVE_NOW
    )
    assert after is not None
    assert after.lifecycle_status is ActivationLifecycleStatus.ACTIVE


def test_durable_suspension_dominates_fresh_reconnect(tmp_path: Path) -> None:
    authority, activation, config, observations, projector = _runtime(tmp_path)
    observations.ingest(_observation(config), received_at=ACTIVE_NOW)
    suspension = _suspension(activation)
    authority.suspend_operational_capability(
        suspension,
        principal=_admin(),
        operation_id=suspension.operation_id,
        event_id="cap5-suspend-event",
        occurred_at=suspension.suspended_at,
    )
    projection = _project(projector, activation, now=suspension.suspended_at)
    assert projection.reason is RuntimeProjectionReason.ACTIVATION_SUSPENDED
    assert projection.durable_authority_valid is False
    assert projection.operationally_usable is False


def test_revoked_and_expired_activations_have_distinct_diagnostics(tmp_path: Path) -> None:
    authority, activation, config, observations, projector = _runtime(tmp_path)
    observations.ingest(_observation(config), received_at=ACTIVE_NOW)
    revocation = _activation_revocation(activation)
    authority.revoke_operational_capability(
        revocation,
        principal=_admin(),
        operation_id=revocation.operation_id,
        event_id="cap5-activation-revoke-event",
        occurred_at=revocation.revoked_at,
    )
    revoked = _project(projector, activation, now=revocation.revoked_at)
    assert revoked.reason is RuntimeProjectionReason.ACTIVATION_REVOKED

    expiry_dir = tmp_path / "expiry"
    expiry_dir.mkdir()
    _a2, activation2, _config2, _store2, projector2 = _runtime(expiry_dir)
    expired = _project(projector2, activation2, now=activation2.valid_until)
    assert expired.reason is RuntimeProjectionReason.ACTIVATION_EXPIRED


@pytest.mark.parametrize("revocation", ["evidence", "approval"])
def test_prerequisite_revocation_dominates_fresh_observation(
    tmp_path: Path, revocation: str
) -> None:
    authority, activation, config, observations, projector = _runtime(tmp_path)
    observations.ingest(_observation(config), received_at=ACTIVE_NOW)
    evidence = tuple(authority._records.values())  # noqa: SLF001 - exact CAP-4 test fixture
    approval = next(iter(authority._approval_records.values()))  # noqa: SLF001
    revoked_at = NOW + timedelta(minutes=6)
    if revocation == "evidence":
        target = evidence[0]
        authority.revoke_evidence(
            _evidence_revocation(target),
            operation_id="cap5-evidence-revoke",
            event_id="cap5-evidence-revoke-event",
            actor_principal_id=target.verifier_principal_id,
            occurred_at=revoked_at,
        )
    else:
        authority.revoke_product_approval(
            _approval_revocation(approval),
            principal=_admin("product-revoker-cap5"),
            operation_id="cap5-approval-revoke",
            event_id="cap5-approval-revoke-event",
            occurred_at=revoked_at,
        )
    projection = _project(projector, activation, now=revoked_at)
    assert projection.reason is RuntimeProjectionReason.ACTIVATION_SUSPENDED
    assert projection.operationally_usable is False


def test_restored_prerequisites_do_not_revive_old_suspended_activation(
    tmp_path: Path,
) -> None:
    authority = _open(tmp_path / "authority.jsonl")
    evidence, _approval_record, activation = _seed_activation(authority)
    config = _configuration(activation)
    observations = RuntimeRouteObservationStore(
        DurableJournal(tmp_path / "runtime-observations.jsonl")
    )
    projector = RuntimeCapabilityProjector(
        authority_store=authority,
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry((config,)),
        observation_store=observations,
        supported_freshness_policies=RUNTIME_FRESHNESS_POLICIES,
    )
    observations.ingest(_observation(config), received_at=ACTIVE_NOW)
    revoked = evidence[0]
    authority.revoke_evidence(
        _evidence_revocation(revoked),
        operation_id="cap5-restore-revoke-operation",
        event_id="cap5-restore-revoke-event",
        actor_principal_id=revoked.verifier_principal_id,
        occurred_at=NOW + timedelta(minutes=6),
    )
    restored = _seed_evidence(authority, suffix="-cap5-restored", supersedes=evidence)
    restored_approval = _approval(
        restored,
        approval_id="approval-cap5-restored",
        operation_id="approval-operation-cap5-restored",
        approved_at=NOW + timedelta(minutes=7),
    )
    _approve(authority, restored_approval)
    projection = _project(projector, activation, now=NOW + timedelta(minutes=9))
    assert projection.reason is RuntimeProjectionReason.ACTIVATION_SUSPENDED
    assert projection.durable_authority_valid is False
    assert projection.operationally_usable is False


def test_trusted_organization_and_exact_observation_binding(tmp_path: Path) -> None:
    _authority, activation, config, observations, projector = _runtime(tmp_path)
    with pytest.raises(RuntimeCapabilityValidationError, match="organization"):
        projector.ingest_observation(
            _observation(config), principal=_edge("other-org"), received_at=ACTIVE_NOW
        )
    with pytest.raises(RuntimeCapabilityValidationError, match="organization"):
        projector.ingest_observation(
            _observation(config), principal=_edge("legacy"), received_at=ACTIVE_NOW
        )
    mismatch = _project(projector, activation, organization_id="other-org")
    assert mismatch.reason is RuntimeProjectionReason.TRUSTED_ORGANIZATION_MISMATCH
    legacy = _project(projector, activation, organization_id="legacy")
    assert legacy.reason is RuntimeProjectionReason.UNTRUSTED_LEGACY_ORGANIZATION

    wrong_port = _observation(config).model_copy(update={"subject_port_id": "wrong-port"})
    with pytest.raises(RuntimeCapabilityValidationError, match="trusted configured"):
        projector.ingest_observation(
            wrong_port, principal=_edge(), received_at=ACTIVE_NOW
        )
    wrong_device = _observation(config).model_copy(
        update={"subject_device_ids": ("gateway-1", "edge-other")}
    )
    with pytest.raises(RuntimeCapabilityValidationError, match="trusted configured"):
        projector.ingest_observation(
            wrong_device, principal=_edge(device_id="edge-other"), received_at=ACTIVE_NOW
        )


@pytest.mark.parametrize(
    ("updates", "principal"),
    [
        ({"site_id": "site-other"}, _edge()),
        (
            {"subject_device_ids": ("gateway-other", "edge-1")},
            _edge(),
        ),
        (
            {"subject_device_ids": ("gateway-1", "edge-other")},
            _edge(device_id="edge-other"),
        ),
    ],
)
def test_wrong_site_gateway_or_edge_observation_is_temporary_only(
    tmp_path: Path,
    updates: dict[str, object],
    principal: Principal,
) -> None:
    authority, activation, config, _observations, projector = _runtime(tmp_path)
    mismatch = _observation(config).model_copy(update=updates)
    with pytest.raises(RuntimeCapabilityValidationError):
        projector.ingest_observation(
            mismatch, principal=principal, received_at=ACTIVE_NOW
        )
    durable = authority.get_activation_projection(
        activation.activation_authorization_id, now=ACTIVE_NOW
    )
    assert durable is not None
    assert durable.lifecycle_status is ActivationLifecycleStatus.ACTIVE


def test_operator_managed_deployment_change_uses_cap4_durable_fence(
    tmp_path: Path,
) -> None:
    authority, activation, config, observations, _projector = _runtime(tmp_path)
    registry = TrustedRuntimeRouteConfigurationRegistry((config,))
    raw = activation.configured_deployment.model_dump(mode="json", by_alias=True)
    raw.update(
        {
            "configurationRecordId": "deployment-config-2",
            "configurationRevision": 2,
            "gatewayDeviceId": "gateway-2",
        }
    )
    changed_deployment = ConfiguredDeploymentSnapshotV1.model_validate(raw)
    changed = TrustedRuntimeRouteConfigurationV1(
        configured_deployment=changed_deployment,
        configured_deployment_digest=changed_deployment.canonical_digest,
        subject_kind=RuntimeRouteSubjectKind.GATEWAY_EDGE_ROUTE_PORT,
        subject_device_ids=("gateway-2", "edge-1"),
        subject_port_id=config.subject_port_id,
        selected_transport="MOP",
        allowed_transports=("MOP",),
        feature_flag_enabled=True,
        port_configuration_ready=True,
        freshness_policy_id=FRESHNESS_POLICY_ID,
        freshness_policy_digest=FRESHNESS_POLICY_DIGEST,
    )
    changed_at = NOW + timedelta(minutes=6)
    registry.replace_with_authority_fence(
        changed,
        authority_store=authority,
        principal=_admin(),
        operation_id="deployment-change-operation-1",
        event_id="deployment-change-event-1",
        occurred_at=changed_at,
        cause_record_id="deployment-config-2",
        cause_record_digest=changed_deployment.canonical_digest,
    )
    durable = authority.get_activation_projection(
        activation.activation_authorization_id, now=changed_at
    )
    assert durable is not None
    assert durable.lifecycle_status is ActivationLifecycleStatus.SUSPENDED
    assert observations.record_count == 0


def test_direct_and_psdk_same_edge_capability_cannot_satisfy_each_other(
    tmp_path: Path,
) -> None:
    digest = "sha256:" + "a" * 64
    base = RuntimeRouteObservationV1(
        observation_id="direct-uplink",
        organization_id="org-1",
        site_id="site-1",
        configured_deployment_digest=digest,
        subject_kind=RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
        subject_device_ids=("edge-1",),
        subject_port_id="manifold-direct.edge-uplink",
        integration_path=CapabilityIntegrationPath.MANIFOLD_DIRECT,
        canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
        equipment_scope_digest="sha256:" + "b" * 64,
        runtime_build_digest="sha256:" + "c" * 64,
        availability=RuntimeRouteAvailability.REPORTED_AVAILABLE,
        observed_at=ACTIVE_NOW,
        expires_at=ACTIVE_NOW + timedelta(minutes=1),
        freshness_policy_id=FRESHNESS_POLICY_ID,
        freshness_policy_digest=FRESHNESS_POLICY_DIGEST,
        producer_principal_id="edge-runtime-1",
        producer_principal_kind=PrincipalKind.EDGE_DEVICE,
        source_observation_ref="runtime-event:direct",
    )
    psdk = RuntimeRouteObservationV1.model_validate(
        base.model_dump(mode="python")
        | {
            "observation_id": "psdk-uplink",
            "integration_path": CapabilityIntegrationPath.PSDK_MANIFOLD,
            "subject_kind": RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
            "subject_device_ids": ("edge-1",),
            "subject_port_id": "psdk-manifold.edge-uplink",
        }
    )
    assert base.key != psdk.key
    assert base.key.integration_path != psdk.key.integration_path
    assert base.key.subject_port_id != psdk.key.subject_port_id

    direct_store = RuntimeRouteObservationStore(
        DurableJournal(tmp_path / "direct-observations.jsonl")
    )
    direct_store.ingest(base, received_at=ACTIVE_NOW)
    assert direct_store.current_for(psdk.key) is None

    psdk_store = RuntimeRouteObservationStore(
        DurableJournal(tmp_path / "psdk-observations.jsonl")
    )
    psdk_store.ingest(psdk, received_at=ACTIVE_NOW)
    assert psdk_store.current_for(base.key) is None


def test_model_rejects_unmapped_or_wrong_subject_kind() -> None:
    with pytest.raises(ValidationError, match="unmapped runtime"):
        RuntimeRouteObservationV1(
            observation_id="unmapped",
            organization_id="org-1",
            site_id="site-1",
            configured_deployment_digest="sha256:" + "a" * 64,
            subject_kind=RuntimeRouteSubjectKind.GATEWAY_ROUTE_PORT,
            subject_device_ids=("gateway-1",),
            subject_port_id="cloud.wayline",
            integration_path=CapabilityIntegrationPath.DJI_CLOUD,
            canonical_capability_id=CanonicalTransportCapability.WAYLINE_DELIVERY,
            equipment_scope_digest="sha256:" + "b" * 64,
            runtime_build_digest="sha256:" + "c" * 64,
            availability=RuntimeRouteAvailability.REPORTED_AVAILABLE,
            observed_at=ACTIVE_NOW,
            expires_at=ACTIVE_NOW + timedelta(minutes=1),
            freshness_policy_id=FRESHNESS_POLICY_ID,
            freshness_policy_digest=FRESHNESS_POLICY_DIGEST,
            producer_principal_id="gateway-runtime-1",
            producer_principal_kind=PrincipalKind.GATEWAY_DEVICE,
            source_observation_ref="runtime-event:unmapped",
        )


def test_observation_loss_only_blocks_new_invocation_not_existing_contract(
    tmp_path: Path,
) -> None:
    _authority, activation, _config, _store, projector = _runtime(tmp_path)
    projection = _project(projector, activation)
    assert projection.new_route_invocation_allowed is False
    assert (
        projection.existing_signed_mission_contract_effect
        is ExistingMissionContractEffect.UNCHANGED
    )


def test_observation_model_requires_explicit_policy_and_valid_interval() -> None:
    # Missing policy is rejected structurally; zero-length TTL is rejected.
    now = datetime(2026, 9, 3, 4, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        RuntimeRouteObservationV1.model_validate(
            {
                "observationId": "missing-policy",
                "organizationId": "org-1",
                "siteId": "site-1",
                "configuredDeploymentDigest": "sha256:" + "a" * 64,
                "subjectKind": "EDGE_ROUTE_PORT",
                "subjectDeviceIds": ["edge-1"],
                "subjectPortId": "direct.uplink",
                "integrationPath": "MANIFOLD_DIRECT",
                "canonicalCapabilityId": "EDGE_UPLINK",
                "equipmentScopeDigest": "sha256:" + "b" * 64,
                "runtimeBuildDigest": "sha256:" + "c" * 64,
                "availability": "REPORTED_AVAILABLE",
                "observedAt": now.isoformat(),
                "expiresAt": now.isoformat(),
                "producerPrincipalId": "edge-runtime-1",
                "producerPrincipalKind": "EDGE_DEVICE",
                "sourceObservationRef": "runtime-event:x",
            }
        )


def _legacy_connectivity_store(tmp_path: Path) -> AcquisitionConnectivityStore:
    store = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "acquisition-connectivity.jsonl"),
        site_exists=lambda _site_id, _organization_id: True,
    )
    profile = AcquisitionDeploymentProfileV1(
        schema_version="1.0",
        site_id="site-1",
        operating_mode=OperatingMode.RC_ATTENDED,
        gateway_kind=GatewayKind.RC_PLUS_2,
        gateway_transports=(GatewayTransport.WIFI,),
        internet_gate=InternetGate.REQUIRED_FOR_MISSION_ISSUE,
        manifold_direct_mode=ManifoldDirectMode.DISABLED,
        routing_policy=RoutingPolicy.RC_STANDARD,
        media_policy=MediaPolicy.RESULTS_IMMEDIATE_RAW_POSTFLIGHT,
        msdk_bridge_mode=MsdkBridgeMode.DISABLED,
        edge_device_id="edge-1",
        gateway_device_id="gateway-1",
    )
    store.upsert_profile(
        profile,
        organization_id="org-1",
        actor="ops-config-1",
        now=ACTIVE_NOW - timedelta(minutes=1),
    )
    snapshot = ConnectivitySnapshotV1(
        schema_version="1.0",
        snapshot_id="snapshot-1",
        site_id="site-1",
        gateway_device_id="gateway-1",
        edge_device_id="edge-1",
        observed_at=ACTIVE_NOW,
        expires_at=ACTIVE_NOW + timedelta(minutes=5),
        transport=GatewayTransport.WIFI,
        internet_reachable=True,
        gateway_state=ConnectionState.CONNECTED,
        edge_state=ConnectionState.CONNECTED,
        direct_edge_state=DirectEdgeState.DISABLED,
        queued_event_count=0,
        queued_media_count=0,
        last_success_receipt_id=None,
        mission_contract_sync=SyncState.COMPLETE,
        raw_media_sync=SyncState.COMPLETE,
        capabilities=(
            CapabilityReceiptV1(
                capability=AcquisitionCapability.EDGE_UPLINK,
                hardware_model="rc-plus-2",
                firmware_version="firmware-1",
                status=CapabilityStatus.VERIFIED,
                checked_at=ACTIVE_NOW,
                evidence_ref="legacy-receipt:snapshot-1",
            ),
        ),
    )
    store.observe(
        snapshot,
        organization_id="org-1",
        actor="gateway-runtime-1",
        now=ACTIVE_NOW,
    )
    return store


def _legacy_cloud_configuration() -> TrustedRuntimeRouteConfigurationV1:
    equipment = _equipment(CapabilityIntegrationPath.DJI_CLOUD)
    configured = ConfiguredDeploymentSnapshotV1(
        configuration_record_id="legacy-cloud-config-1",
        configuration_revision=1,
        organization_id="org-1",
        site_id="site-1",
        gateway_device_id="gateway-1",
        edge_device_id="edge-1",
        integration_path=CapabilityIntegrationPath.DJI_CLOUD,
        canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
        equipment_scope=equipment,
        equipment_scope_digest=equipment.canonical_digest,
        runtime_build_digest=BUILD,
        policy_scope_id=POLICY,
        mapping_version="ksi-dji-capability-map-v1",
        gate_version="ksi-capability-gate-v1",
    )
    return TrustedRuntimeRouteConfigurationV1(
        configured_deployment=configured,
        configured_deployment_digest=configured.canonical_digest,
        subject_kind=RuntimeRouteSubjectKind.GATEWAY_ROUTE_PORT,
        subject_device_ids=("gateway-1",),
        subject_port_id="dji-cloud.edge-uplink",
        selected_transport="RC_WIFI",
        allowed_transports=("RC_CELLULAR", "RC_WIFI"),
        feature_flag_enabled=True,
        port_configuration_ready=True,
        freshness_policy_id=FRESHNESS_POLICY_ID,
        freshness_policy_digest=FRESHNESS_POLICY_DIGEST,
        legacy_connectivity_adapter_enabled=True,
    )


def test_legacy_snapshot_adapter_derives_one_exact_route_and_preserves_ttl(
    tmp_path: Path,
) -> None:
    connectivity = _legacy_connectivity_store(tmp_path)
    config = _legacy_cloud_configuration()
    adapter = LegacyConnectivitySnapshotAdapter(
        connectivity_store=connectivity,
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry((config,)),
    )
    adapted = adapter.adapt(
        organization_id="org-1",
        site_id="site-1",
        canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
    )
    assert adapted.integration_path is CapabilityIntegrationPath.DJI_CLOUD
    assert adapted.subject_port_id == "dji-cloud.edge-uplink"
    assert adapted.availability is RuntimeRouteAvailability.REPORTED_AVAILABLE
    assert adapted.observed_at == ACTIVE_NOW
    assert adapted.expires_at == ACTIVE_NOW + timedelta(minutes=5)
    assert adapted.source_observation_ref == "acquisition-connectivity:snapshot-1"


def test_legacy_snapshot_adapter_zero_or_multiple_derivations_fail_closed(
    tmp_path: Path,
) -> None:
    connectivity = _legacy_connectivity_store(tmp_path)
    empty = LegacyConnectivitySnapshotAdapter(
        connectivity_store=connectivity,
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry(),
    )
    with pytest.raises(LegacyConnectivityAdaptationError, match="exactly one"):
        empty.adapt(
            organization_id="org-1",
            site_id="site-1",
            canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
        )

    config = _legacy_cloud_configuration()

    class _AmbiguousRegistry:
        def all(self) -> tuple[TrustedRuntimeRouteConfigurationV1, ...]:
            return config, config.model_copy(deep=True)

    ambiguous = LegacyConnectivitySnapshotAdapter(
        connectivity_store=connectivity,
        configuration_registry=cast(
            TrustedRuntimeRouteConfigurationRegistry, _AmbiguousRegistry()
        ),
    )
    with pytest.raises(LegacyConnectivityAdaptationError, match="exactly one"):
        ambiguous.adapt(
            organization_id="org-1",
            site_id="site-1",
            canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
        )


def test_legacy_snapshot_cannot_infer_non_gateway_route_from_capability(
    tmp_path: Path,
) -> None:
    connectivity = _legacy_connectivity_store(tmp_path)
    authority = _open(tmp_path / "authority-for-msdk.jsonl")
    _, _, activation = _seed_activation(authority)
    msdk = _configuration(activation).model_copy(
        update={"legacy_connectivity_adapter_enabled": True}
    )
    adapter = LegacyConnectivitySnapshotAdapter(
        connectivity_store=connectivity,
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry((msdk,)),
    )
    with pytest.raises(LegacyConnectivityAdaptationError, match="exactly one"):
        adapter.adapt(
            organization_id="org-1",
            site_id="site-1",
            canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
        )
