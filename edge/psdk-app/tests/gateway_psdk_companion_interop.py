"""Real Unix and CAP-5 interoperability for the PSDK route companion.

The C++ fixture injects only the unavailable physical MOP peer. The companion
process, Unix transport, Gateway parser/producer, Core observation journal, and
runtime projector are production implementations.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import select
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.capability.authority_store import (
    ActivationApplicabilityScopeV1,
    CapabilityAuthorityStore,
    CapabilityEvidenceRecordV1,
    CapabilityEvidenceType,
    ConfiguredDeploymentSnapshotV1,
    EquipmentComponentV1,
    EquipmentRole,
    EquipmentScopeV1,
    OperationalCapabilityActivationRecordV1,
    ProductCapabilityApprovalRecordV1,
    ProductSupportMatrixEntryV1,
    ProductSupportMatrixV1,
    QualificationReferenceV1,
    capability_evidence_record_digest,
    product_capability_approval_record_digest,
)
from ksi_core.capability.runtime_projection import (
    MissionPolicyDecision,
    RuntimeCapabilityProjector,
    RuntimeProjectionReason,
    RuntimeRouteFreshnessPolicyV1,
    RuntimeRouteObservationStore,
    RuntimeRouteObservationV1,
    TrustedRuntimeRouteConfigurationRegistry,
    TrustedRuntimeRouteConfigurationV1,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_dji_gateway.adapters.catalog import build_candidate_ports
from ksi_dji_gateway.adapters.transport import (
    AdapterRuntimeConfig,
    UnixJsonBridgeClient,
)
from ksi_dji_gateway.coordinator import (
    CapabilityGateway,
    RouteActivationAuthorization,
    RoutingContext,
)
from ksi_dji_gateway.core_runtime import (
    CoreRuntimeTransportConfig,
    HttpCoreRuntimeObservationPublisher,
    HttpCoreRuntimeRoutePreflight,
)
from ksi_dji_gateway.domain.capabilities import (
    Capability,
    CapabilityEvidence,
    CapabilityRegistry,
    CapabilityStatus,
    GatewayTransport,
    IntegrationPath,
)
from ksi_dji_gateway.domain.models import EdgeUplinkRequest
from ksi_dji_gateway.errors import CapabilityUnavailableError
from ksi_dji_gateway.persistence.journal import GatewayJournal
from ksi_dji_gateway.routing.capability_router import CapabilityRoute, CapabilityRouter
from ksi_dji_gateway.runtime_observation import (
    PsdkMopObservationConfig,
    PsdkMopRuntimeObservationProducer,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_domain.capability_contract import (
    CanonicalTransportCapability,
    CapabilityGateVersion,
    CapabilityIntegrationPath,
    CapabilityMappingVersion,
    OperationalCapabilityActivation,
    ProductCapabilityApproval,
    RouteEvidenceQualification,
    RuntimeRouteSubjectKind,
    resolve_capability_mapping,
)

_ACTIVATION_ID = "activation-psdk-hil1s"
_FRESHNESS_POLICY_ID = "psdk-fast-v1"
_FRESHNESS_POLICY_DIGEST = (
    "sha256:a3d807243912f3e7532fae0f890e16a6e46e4821e392e1d3f3fad552a82dc431"
)
_FRESHNESS_POLICY = RuntimeRouteFreshnessPolicyV1(
    schemaVersion="1.0",
    freshnessPolicyId=_FRESHNESS_POLICY_ID,
    observationTtlSeconds=1,
    minimumRefreshMarginSeconds=0.2,
    freshnessPolicyDigest=_FRESHNESS_POLICY_DIGEST,
)
_RUNTIME_BUILD_DIGEST = "sha256:" + "c" * 64
_PRODUCT_BUILD_DIGEST = _RUNTIME_BUILD_DIGEST
_POLICY_SCOPE_ID = "policy-hil1p-software-fixture"


def _canonical_digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _admin(principal_id: str, *, organization_id: str) -> Principal:
    return Principal(
        principal_id=principal_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id=organization_id,
    )


def _wait_ready(process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 5.0)
    if not ready:
        raise RuntimeError("C++ PSDK companion fixture did not become ready")
    line = process.stdout.readline().strip()
    if line != "READY":
        raise RuntimeError(f"unexpected fixture readiness line: {line!r}")


def _launch(fixture: Path, socket_path: Path, state: str) -> subprocess.Popen[str]:
    command = [str(fixture), "--gateway-interop-fixture", str(socket_path), state]
    setarch = os.environ.get("KSI_PSDK_TSAN_SETARCH")
    if setarch:
        command = [setarch, platform.machine(), "-R", *command]
    process = subprocess.Popen(  # noqa: S603 -- exact CMake-built fixture path
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_ready(process)
    return process


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)


def _signal_id(observation: Mapping[str, Any]) -> str:
    prefix = "psdk-mop-route-signal:"
    source = observation["sourceObservationRef"]
    if not isinstance(source, str) or not source.startswith(prefix):
        raise RuntimeError(f"unexpected observation source: {source!r}")
    return source.removeprefix(prefix)


def _equipment() -> EquipmentScopeV1:
    return EquipmentScopeV1(
        components=tuple(
            EquipmentComponentV1(
                role=role,
                product_family="DJI-Matrice",
                hardware_model=f"model-{role.value.lower()}",
                hardware_revision="rev-a",
                firmware_or_image_version="firmware-1.0",
            )
            for role in (
                EquipmentRole.AIRCRAFT,
                EquipmentRole.EDGE,
                EquipmentRole.GATEWAY,
            )
        )
    )


def _seed_authority(
    journal_path: Path,
) -> tuple[
    CapabilityAuthorityStore,
    OperationalCapabilityActivationRecordV1,
]:
    """Create isolated, fully journaled CAP-2/3/4 fixture authority."""

    now = datetime.now(UTC)
    authority = CapabilityAuthorityStore(
        DurableJournal(journal_path),
        supported_freshness_policies={_FRESHNESS_POLICY_ID: _FRESHNESS_POLICY_DIGEST},
    )
    equipment = _equipment()
    requirement = resolve_capability_mapping(CapabilityMappingVersion.V1).requirement_for(
        CanonicalTransportCapability.EDGE_UPLINK,
        CapabilityIntegrationPath.PSDK_MANIFOLD,
    )
    evidence_records: list[CapabilityEvidenceRecordV1] = []
    for index, source in enumerate(requirement.required_sources, start=1):
        record = CapabilityEvidenceRecordV1(
            evidence_record_id=f"hil1p-evidence-{source.value.lower()}",
            canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
            source_capability_id=source,
            mapping_version=CapabilityMappingVersion.V1.value,
            integration_path=CapabilityIntegrationPath.PSDK_MANIFOLD,
            equipment_scope=equipment,
            equipment_scope_digest=equipment.canonical_digest,
            test_build_digest=_PRODUCT_BUILD_DIGEST,
            policy_scope_id=_POLICY_SCOPE_ID,
            evidence_type=CapabilityEvidenceType.HIL,
            evidence_artifact_ref=f"fixture://hil1p/{source.value}",
            evidence_digest="sha256:" + "e" * 64,
            procedure_ref="fixture://hil1p/software-seam",
            procedure_digest="sha256:" + "d" * 64,
            performer_principal_id=f"performer-{source.value.lower()}",
            verifier_principal_id=f"verifier-{source.value.lower()}",
            performed_at=now - timedelta(minutes=5),
            verified_at=now - timedelta(minutes=4),
            verification_result=RouteEvidenceQualification.QUALIFIED,
            valid_until=now + timedelta(days=1),
        )
        authority.record_evidence(
            record,
            operation_id=f"hil1p-evidence-operation-{index}",
            event_id=f"hil1p-evidence-event-{index}",
            actor_principal_id=record.verifier_principal_id,
            occurred_at=record.verified_at,
        )
        evidence_records.append(record)
    references = tuple(
        QualificationReferenceV1(
            qualification_record_id=record.evidence_record_id,
            qualification_record_digest=capability_evidence_record_digest(record),
        )
        for record in sorted(evidence_records, key=lambda item: item.evidence_record_id)
    )
    matrix = ProductSupportMatrixV1(
        entries=(
            ProductSupportMatrixEntryV1(
                integration_path=CapabilityIntegrationPath.PSDK_MANIFOLD,
                equipment_scope=equipment,
                equipment_scope_digest=equipment.canonical_digest,
                qualification_references=references,
            ),
        )
    )
    approval = ProductCapabilityApprovalRecordV1(
        approval_record_id="hil1p-approval",
        operation_id="hil1p-approval-operation",
        canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
        mapping_version=CapabilityMappingVersion.V1.value,
        gate_version=CapabilityGateVersion.V1.value,
        support_matrix=matrix,
        support_matrix_digest=matrix.canonical_digest,
        evidence_set_digest=matrix.evidence_set_digest,
        product_build_digest=_PRODUCT_BUILD_DIGEST,
        policy_scope_id=_POLICY_SCOPE_ID,
        approver_principal_id="hil1p-product-approver",
        approved_at=now - timedelta(minutes=3),
        valid_until=now + timedelta(days=1),
        decision=ProductCapabilityApproval.APPROVED,
    )
    authority.approve_product_capability(
        approval,
        principal=_admin(approval.approver_principal_id, organization_id="ksi-product"),
        operation_id=approval.operation_id,
        event_id="hil1p-approval-event",
        occurred_at=approval.approved_at,
    )
    scope = ActivationApplicabilityScopeV1(
        organization_id="org-1",
        site_id="site-1",
        gateway_device_id="gateway-1",
        edge_device_id="edge-1",
        integration_path=CapabilityIntegrationPath.PSDK_MANIFOLD,
        canonical_capability_id=CanonicalTransportCapability.EDGE_UPLINK,
        equipment_scope_digest=equipment.canonical_digest,
        runtime_build_digest=_RUNTIME_BUILD_DIGEST,
        policy_scope_id=_POLICY_SCOPE_ID,
        mapping_version=CapabilityMappingVersion.V1.value,
        gate_version=CapabilityGateVersion.V1.value,
    )
    deployment = ConfiguredDeploymentSnapshotV1(
        configuration_record_id="deployment-psdk-hil1p",
        configuration_revision=1,
        organization_id=scope.organization_id,
        site_id=scope.site_id,
        gateway_device_id=scope.gateway_device_id,
        edge_device_id=scope.edge_device_id,
        integration_path=scope.integration_path,
        canonical_capability_id=scope.canonical_capability_id,
        equipment_scope=equipment,
        equipment_scope_digest=scope.equipment_scope_digest,
        runtime_build_digest=scope.runtime_build_digest,
        policy_scope_id=scope.policy_scope_id,
        mapping_version=scope.mapping_version,
        gate_version=scope.gate_version,
    )
    prerequisite = {
        "activationScope": scope.model_dump(mode="json", by_alias=True),
        "activationScopeDigest": scope.canonical_digest,
        "approvalRecordId": approval.approval_record_id,
        "approvalRecordDigest": product_capability_approval_record_digest(approval),
        "supportMatrixDigest": approval.support_matrix_digest,
        "evidenceSetDigest": approval.evidence_set_digest,
        "qualificationReferences": [
            item.model_dump(mode="json", by_alias=True) for item in references
        ],
        "configuredDeploymentDigest": deployment.canonical_digest,
        "freshnessPolicyId": _FRESHNESS_POLICY_ID,
        "freshnessPolicyDigest": _FRESHNESS_POLICY_DIGEST,
    }
    activation = OperationalCapabilityActivationRecordV1(
        activation_authorization_id=_ACTIVATION_ID,
        operation_id="hil1p-activation-operation",
        activation_scope=scope,
        activation_scope_digest=scope.canonical_digest,
        approval_record_id=approval.approval_record_id,
        approval_record_digest=product_capability_approval_record_digest(approval),
        support_matrix_digest=approval.support_matrix_digest,
        evidence_set_digest=approval.evidence_set_digest,
        qualification_references=references,
        configured_deployment=deployment,
        configured_deployment_digest=deployment.canonical_digest,
        freshness_policy_id=_FRESHNESS_POLICY_ID,
        freshness_policy_digest=_FRESHNESS_POLICY_DIGEST,
        prerequisite_set_digest=_canonical_digest(prerequisite),
        activating_principal_id="hil1p-ops-activator",
        activated_at=now - timedelta(minutes=2),
        valid_until=now + timedelta(days=1),
        effective_state=OperationalCapabilityActivation.ACTIVE,
    )
    authority.authorize_operational_capability(
        activation,
        principal=_admin(activation.activating_principal_id, organization_id="org-1"),
        operation_id=activation.operation_id,
        event_id="hil1p-activation-event",
        occurred_at=activation.activated_at,
    )
    return authority, activation


def _runtime(
    journal_path: Path,
) -> tuple[
    CapabilityAuthorityStore,
    RuntimeRouteObservationStore,
    RuntimeCapabilityProjector,
    TrustedRuntimeRouteConfigurationV1,
    Principal,
    OperationalCapabilityActivationRecordV1,
]:
    authority, activation = _seed_authority(journal_path.with_name("authority.jsonl"))
    deployment = activation.configured_deployment
    configuration = TrustedRuntimeRouteConfigurationV1(
        configured_deployment=deployment,
        configured_deployment_digest=deployment.canonical_digest,
        subject_kind=RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
        subject_device_ids=("edge-1",),
        subject_port_id="psdk.edge_uplink",
        selected_transport="MOP",
        allowed_transports=("MOP",),
        feature_flag_enabled=True,
        port_configuration_ready=True,
        freshness_policy_id=_FRESHNESS_POLICY_ID,
        freshness_policy_digest=_FRESHNESS_POLICY_DIGEST,
    )
    store = RuntimeRouteObservationStore(DurableJournal(journal_path))
    projector = RuntimeCapabilityProjector(
        authority_store=authority,
        configuration_registry=TrustedRuntimeRouteConfigurationRegistry((configuration,)),
        observation_store=store,
        supported_freshness_policies={_FRESHNESS_POLICY_ID: _FRESHNESS_POLICY},
    )
    principal = Principal(
        principal_id="edge-runtime-1",
        kind=PrincipalKind.EDGE_DEVICE,
        role=None,
        device_id="edge-1",
        organization_id="org-1",
    )
    return authority, store, projector, configuration, principal, activation


def _producer(
    client: UnixJsonBridgeClient,
    configuration: TrustedRuntimeRouteConfigurationV1,
    publisher: HttpCoreRuntimeObservationPublisher,
) -> PsdkMopRuntimeObservationProducer:
    return PsdkMopRuntimeObservationProducer(
        PsdkMopObservationConfig(
            organization_id="org-1",
            site_id="site-1",
            edge_device_id="edge-1",
            subject_port_id="psdk.edge_uplink",
            configured_deployment_digest=configuration.configured_deployment_digest,
            equipment_scope_digest=(configuration.configured_deployment.equipment_scope_digest),
            runtime_build_digest=_RUNTIME_BUILD_DIGEST,
            freshness_policy_id=_FRESHNESS_POLICY_ID,
            freshness_policy_digest=_FRESHNESS_POLICY_DIGEST,
            producer_principal_id="edge-runtime-1",
            freshness_ttl_s=1,
            minimum_refresh_margin_s=0.2,
        ),
        client=client,
        publisher=publisher,
    )


def _free_port() -> int:
    import socket

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def _mission_contract(now: datetime) -> dict[str, object]:
    return {
        "schemaVersion": "1.2",
        "missionId": "mission-1",
        "siteId": "site-1",
        "missionType": "UNIFIED_SITE_SURVEY",
        "validity": {
            "notBefore": (now - timedelta(minutes=1)).isoformat(),
            "notAfter": (now + timedelta(minutes=5)).isoformat(),
        },
        "siteFrame": {
            "crs": "EPSG:5186",
            "verticalDatum": "KNGeoid2018",
            "unit": "meter",
            "transformVersion": "1.0.0",
        },
        "flightEnvelope": {
            "allowedVolumes": ["vol-1"],
            "excludedVolumes": [],
            "minAltitudeM": 5.0,
            "maxAltitudeM": 120.0,
            "minimumStructureStandoffM": 3.0,
            "minimumPersonStandoffM": 5.0,
            "altitudeReference": "relativeToStartPoint",
        },
        "objectives": ["software seam only"],
        "policies": {
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
            "coveragePolicy": {
                "mandatoryHazardCoverage": 1.0,
                "mandatoryAssetCoverage": 1.0,
                "accessibleGeneralCoverage": 0.97,
            },
            "communicationLossPolicy": {
                "serverLink": "CONTINUE_WHILE_CONTRACT_AND_SAFETY_VALID",
                "rcCommandLink": "DELEGATE_TO_DJI_FLIGHT_CONTROLLER",
            },
            "batteryPolicy": {
                "mode": "RETURN_ENERGY_PLUS_RESERVE",
                "defaultReservePercent": 30,
                "siteOverrideAllowed": True,
            },
            "unknownObstaclePolicy": {
                "initialAction": "SLOW",
                "unresolvedAction": "RETREAT",
            },
            "evidencePolicy": {
                "candidatePrePostSeconds": 3,
                "highPrePostSeconds": 5,
                "criticalPrePostSeconds": 10,
            },
        },
        "artifacts": {
            "worldModelManifestId": "wm-1",
            "modelPackId": "mp-1",
            "calibrationProfileId": "cal-1",
        },
        "signature": {
            "algorithm": "Ed25519",
            "keyId": "key-001",
            "digest": "sha256:" + "cd" * 32,
            "signature": "c2lnbmF0dXJlLWJ5dGVzLXBsYWNlaG9sZGVy",
        },
    }


def _start_core(
    root: Path,
    projector: RuntimeCapabilityProjector,
    principal: Principal,
) -> tuple[
    uvicorn.Server,
    threading.Thread,
    HttpCoreRuntimeObservationPublisher,
    HttpCoreRuntimeRoutePreflight,
    MissionStore,
    MissionExecutionStore,
]:
    edge_token = "hil1p-edge-observation-token"
    gateway_token = "hil1p-gateway-preflight-token"
    gateway_principal = Principal(
        principal_id="gateway-runtime-1",
        kind=PrincipalKind.GATEWAY_DEVICE,
        role=None,
        device_id="gateway-1",
        organization_id="org-1",
    )
    now = datetime.now(UTC)
    mission_store = MissionStore(DurableJournal(root / "missions.jsonl"))
    mission_store.record_issuance(
        MissionRecord(
            mission_id="mission-1",
            site_id="site-1",
            mission_type="UNIFIED_SITE_SURVEY",
            artifact_kind="contract",
            contract=_mission_contract(now),
            kmz_sha256=None,
            route_pattern=None,
            waypoint_count=None,
            planned_coverage_ratio=None,
            issued_at=now,
            issued_by="operator-1",
            organization_id="org-1",
            assigned_device_id="edge-1",
        )
    )
    execution_store = MissionExecutionStore(
        DurableJournal(root / "mission-execution.jsonl"),
        mission_store=mission_store,
    )
    app = create_app(
        auth_registry=AuthRegistry(
            (
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(edge_token.encode()).hexdigest(),
                    principal=principal,
                ),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(gateway_token.encode()).hexdigest(),
                    principal=gateway_principal,
                ),
            )
        ),
        runtime_capability_projector=projector,
        mission_store=mission_store,
        mission_execution_store=execution_store,
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("Core runtime observation seam did not start")
    edge_token_file = root / "edge-observation-token"
    edge_token_file.write_text(edge_token, encoding="utf-8")
    edge_token_file.chmod(0o600)
    gateway_token_file = root / "gateway-preflight-token"
    gateway_token_file.write_text(gateway_token, encoding="utf-8")
    gateway_token_file.chmod(0o600)
    publisher = HttpCoreRuntimeObservationPublisher(
        CoreRuntimeTransportConfig(
            core_url=f"http://127.0.0.1:{port}",
            token_file=edge_token_file,
            allow_loopback_http=True,
        )
    )
    preflight = HttpCoreRuntimeRoutePreflight(
        CoreRuntimeTransportConfig(
            core_url=f"http://127.0.0.1:{port}",
            token_file=gateway_token_file,
            allow_loopback_http=True,
        )
    )
    return server, thread, publisher, preflight, mission_store, execution_store


def _bridge(socket_path: Path) -> UnixJsonBridgeClient:
    return UnixJsonBridgeClient(
        AdapterRuntimeConfig(
            adapter_id="psdk",
            integration_path=IntegrationPath.PSDK_MANIFOLD,
            transport=GatewayTransport.MOP,
            organization_id="org-1",
            site_id="site-1",
            gateway_device_id="gateway-1",
            edge_device_id="edge-1",
            endpoint=f"unix://{socket_path}",
            timeout_s=2,
        )
    )


def _gateway(
    root: Path,
    socket_path: Path,
    client: UnixJsonBridgeClient,
    preflight: HttpCoreRuntimeRoutePreflight,
    activation: OperationalCapabilityActivationRecordV1,
) -> tuple[CapabilityGateway, GatewayJournal]:
    adapter = AdapterRuntimeConfig(
        adapter_id="psdk",
        integration_path=IntegrationPath.PSDK_MANIFOLD,
        transport=GatewayTransport.MOP,
        organization_id="org-1",
        site_id="site-1",
        gateway_device_id="gateway-1",
        edge_device_id="edge-1",
        endpoint=f"unix://{socket_path}",
        timeout_s=2,
    )
    ports = build_candidate_ports(adapter, client)
    gateway_component = next(
        item
        for item in activation.configured_deployment.equipment_scope.components
        if item.role is EquipmentRole.GATEWAY
    )
    journal = GatewayJournal(root / "gateway.jsonl")
    gateway = CapabilityGateway(
        router=CapabilityRouter(
            routes=tuple(
                CapabilityRoute(port=port, priority=index)
                for index, port in enumerate(ports)
            ),
            registry=CapabilityRegistry(
                (
                    CapabilityEvidence(
                        path=IntegrationPath.PSDK_MANIFOLD,
                        capability=Capability.EDGE_UPLINK,
                        status=CapabilityStatus.VERIFIED,
                        checked_at=datetime.now(UTC).isoformat(),
                        evidence_ref="fixture://hil1p/software-seam",
                        hardware_model=gateway_component.hardware_model,
                        firmware_version=gateway_component.firmware_or_image_version,
                    ),
                )
            ),
            feature_flags={Capability.EDGE_UPLINK: True},
        ),
        journal=journal,
        context=RoutingContext(
            organization_id="org-1",
            site_id="site-1",
            gateway_device_id="gateway-1",
            edge_device_id="edge-1",
            hardware_model=gateway_component.hardware_model,
            firmware_version=gateway_component.firmware_or_image_version,
            allowed_transports=frozenset({GatewayTransport.MOP}),
            activation_authorizations=(
                RouteActivationAuthorization(
                    canonical_capability=Capability.EDGE_UPLINK,
                    integration_path=IntegrationPath.PSDK_MANIFOLD,
                    activation_authorization_id=activation.activation_authorization_id,
                ),
            ),
        ),
        runtime_preflight=preflight,
    )
    return gateway, journal


def _complete_available_fixture(
    process: subprocess.Popen[str],
    gateway: CapabilityGateway,
    *,
    idempotency_key: str,
) -> None:
    request = EdgeUplinkRequest(
        organization_id="org-1",
        site_id="site-1",
        mission_id="mission-1",
        edge_device_id="edge-1",
        bundle_object_ref=f"objects/{idempotency_key}.json",
        bundle_sha256="a" * 64,
        idempotency_key=idempotency_key,
    )
    denied = EdgeUplinkRequest(
        organization_id=request.organization_id,
        site_id=request.site_id,
        mission_id="unknown-mission",
        edge_device_id=request.edge_device_id,
        bundle_object_ref=request.bundle_object_ref,
        bundle_sha256=request.bundle_sha256,
        idempotency_key=f"{idempotency_key}-denied",
    )
    try:
        gateway.upload_edge_bundle(denied)
    except CapabilityUnavailableError:
        pass
    else:
        raise RuntimeError("Mission DENY reached the PSDK provider")
    receipt = gateway.upload_edge_bundle(request)
    expected_operation_id = f"psdk-mop-{idempotency_key}"
    if receipt.provider_operation_id != expected_operation_id or receipt.item_count != 1:
        raise RuntimeError(f"unexpected PSDK companion receipt: {receipt}")
    return_code = process.wait(timeout=5)
    if return_code != 0:
        assert process.stderr is not None
        raise RuntimeError(f"C++ fixture failed: {process.stderr.read()}")


def run(fixture: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ksi-psdk-gateway-") as directory:
        root = Path(directory)
        socket_path = root / "psdk.sock"
        authority, store, projector, configuration, principal, activation = _runtime(
            root / "runtime.jsonl"
        )
        activation_count = authority.activation_count
        (
            core,
            core_thread,
            publisher,
            preflight,
            mission_store,
            execution_store,
        ) = _start_core(root, projector, principal)
        client = _bridge(socket_path)
        producer = _producer(client, configuration, publisher)
        gateway, gateway_journal = _gateway(
            root, socket_path, client, preflight, activation
        )

        process_a = _launch(fixture, socket_path, "available")
        try:
            first = producer.observe_once()
            time.sleep(0.002)
            second_same_process = producer.observe_once()
            if first["availability"] != "REPORTED_AVAILABLE":
                raise RuntimeError(f"AVAILABLE did not cross the real Unix seam: {first}")
            if _signal_id(first) == _signal_id(second_same_process):
                raise RuntimeError("same-process ROUTE_STATUS_V1 signalId was reused")
            if first["observationId"] == second_same_process["observationId"]:
                raise RuntimeError("same-process Gateway observationId was reused")
            _complete_available_fixture(
                process_a, gateway, idempotency_key="bundle-a"
            )
        finally:
            _stop(process_a)

        latest_a = RuntimeRouteObservationV1.model_validate(second_same_process)
        stale = projector.project(
            _ACTIVATION_ID,
            trusted_organization_id="org-1",
            mission_policy=MissionPolicyDecision.ALLOW,
            now=latest_a.expires_at,
        )
        if stale.reason is not RuntimeProjectionReason.OBSERVATION_STALE:
            raise RuntimeError(f"old process observation did not become stale: {stale}")
        time.sleep(1.01)

        process_b = _launch(fixture, socket_path, "available")
        try:
            after_restart = producer.observe_once()
            latest_a_dict = latest_a.model_dump(mode="json", by_alias=True)
            if _signal_id(latest_a_dict) == _signal_id(after_restart):
                raise RuntimeError("companion restart reused signalId")
            if latest_a.observation_id == after_restart["observationId"]:
                raise RuntimeError("companion restart reused Gateway observationId")
            current = store.current_for(configuration.key)
            if current is None or current.observation_id != after_restart["observationId"]:
                raise RuntimeError("post-restart observation did not become current route state")
            if store.record_count != 3:
                raise RuntimeError("pre-restart observations were not retained for audit")
            if authority.activation_count != activation_count:
                raise RuntimeError("runner/companion restart recreated CAP-4 authority")
            recovered = projector.project(
                _ACTIVATION_ID,
                trusted_organization_id="org-1",
                mission_policy=MissionPolicyDecision.ALLOW,
                now=current.observed_at,
            )
            if not recovered.current_runtime_ready or not recovered.operationally_usable:
                raise RuntimeError(f"fresh post-restart observation did not recover: {recovered}")
            _complete_available_fixture(
                process_b, gateway, idempotency_key="bundle-b"
            )
        finally:
            _stop(process_b)

        unavailable_process = _launch(fixture, socket_path, "unavailable")
        try:
            unavailable = producer.observe_once()
            if unavailable["availability"] != "REPORTED_UNAVAILABLE":
                raise RuntimeError(f"UNAVAILABLE did not cross the real Unix seam: {unavailable}")
            unavailable_model = RuntimeRouteObservationV1.model_validate(unavailable)
            denied = projector.project(
                _ACTIVATION_ID,
                trusted_organization_id="org-1",
                mission_policy=MissionPolicyDecision.ALLOW,
                now=unavailable_model.observed_at,
            )
            if (
                denied.current_runtime_ready
                or denied.reason is not RuntimeProjectionReason.OBSERVATION_UNAVAILABLE
            ):
                raise RuntimeError(f"UNAVAILABLE unexpectedly became runtime-ready: {denied}")
        finally:
            _stop(unavailable_process)
            gateway_journal.close()
            store.close()
            authority.close()
            core.should_exit = True
            core_thread.join(timeout=5)
            # These stores intentionally expose no public close method; keep
            # them alive until the server has fully stopped.
            del mission_store, execution_store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    run(args.fixture)


if __name__ == "__main__":
    main()
