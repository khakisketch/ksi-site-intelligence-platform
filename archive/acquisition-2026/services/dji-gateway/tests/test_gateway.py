"""DJI Gateway capability, idempotency, recovery gates (REQ-ACQ-101/INV-041)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ksi_dji_gateway import (
    Capability,
    CapabilityEvidence,
    CapabilityRegistry,
    CapabilityRoute,
    CapabilityRouter,
    CapabilityStatus,
    CapabilityUnavailableError,
    GatewayJournal,
    GatewayTransport,
    IdempotencyConflictError,
    IntegrationPath,
    IntegrationReceipt,
    MediaSyncRequest,
    OperationKind,
    ProviderReceipt,
    VendorDocumentationStatus,
    WaylineDispatchRequest,
    ZeroTouchGateway,
)

_NOW = datetime(2026, 8, 20, 4, 0, tzinfo=UTC).isoformat()


class RecordingProvider:
    integration_path = IntegrationPath.PSDK_MANIFOLD

    def __init__(self) -> None:
        self.wayline_calls = 0
        self.media_calls = 0

    def push_wayline(self, request: WaylineDispatchRequest) -> ProviderReceipt:
        self.wayline_calls += 1
        return ProviderReceipt(
            provider_operation_id=f"wayline-{request.mission_id}",
            accepted_at=_NOW,
            item_count=1,
        )

    def sync_media(self, request: MediaSyncRequest) -> ProviderReceipt:
        self.media_calls += 1
        return ProviderReceipt(
            provider_operation_id=f"media-{request.mission_id}",
            accepted_at=_NOW,
            item_count=24,
            manifest_ref="objects/manifests/mission-1.json",
        )


def _evidence(*capabilities: Capability) -> CapabilityRegistry:
    return CapabilityRegistry(
        [
            CapabilityEvidence(
                path=IntegrationPath.PSDK_MANIFOLD,
                capability=capability,
                status=CapabilityStatus.VERIFIED,
                checked_at=_NOW,
                evidence_ref=f"hil/session-1#{capability.value}",
            )
            for capability in capabilities
        ]
    )


def _wayline() -> WaylineDispatchRequest:
    return WaylineDispatchRequest(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-1",
        mission_id="mission-1",
        wayline_object_ref="objects/waylines/mission-1.kmz",
        wayline_sha256="a" * 64,
        idempotency_key="dispatch-work-1-cycle-1",
    )


def test_feature_flag_and_unverified_capability_fail_closed(tmp_path: Path) -> None:
    provider = RecordingProvider()
    journal = GatewayJournal(tmp_path / "gateway.jsonl")
    disabled = ZeroTouchGateway(
        provider=provider,
        capabilities=CapabilityRegistry([]),
        journal=journal,
    )
    with pytest.raises(CapabilityUnavailableError, match="feature flag"):
        disabled.dispatch_wayline(_wayline())

    enabled_but_unverified = ZeroTouchGateway(
        provider=provider,
        capabilities=CapabilityRegistry([]),
        journal=journal,
        wayline_dispatch_enabled=True,
    )
    with pytest.raises(CapabilityUnavailableError, match="NOT_VERIFIED"):
        enabled_but_unverified.dispatch_wayline(_wayline())
    assert provider.wayline_calls == 0
    journal.close()


def test_same_request_replays_receipt_without_provider_side_effect(tmp_path: Path) -> None:
    provider = RecordingProvider()
    journal = GatewayJournal(tmp_path / "gateway.jsonl")
    gateway = ZeroTouchGateway(
        provider=provider,
        capabilities=_evidence(Capability.WAYLINE_PUSH, Capability.TASK_STATUS),
        journal=journal,
        wayline_dispatch_enabled=True,
    )
    first = gateway.dispatch_wayline(_wayline())
    second = gateway.dispatch_wayline(_wayline())
    assert first == second
    assert provider.wayline_calls == 1

    with pytest.raises(IdempotencyConflictError):
        gateway.dispatch_wayline(replace(_wayline(), mission_id="mission-2"))
    assert provider.wayline_calls == 1
    journal.close()

    replay_journal = GatewayJournal(tmp_path / "gateway.jsonl")
    replay_gateway = ZeroTouchGateway(
        provider=provider,
        capabilities=_evidence(Capability.WAYLINE_PUSH, Capability.TASK_STATUS),
        journal=replay_journal,
        wayline_dispatch_enabled=True,
    )
    assert replay_gateway.dispatch_wayline(_wayline()) == first
    assert provider.wayline_calls == 1
    replay_journal.close()


def test_media_sync_requires_both_pull_and_upload_capabilities(tmp_path: Path) -> None:
    provider = RecordingProvider()
    journal = GatewayJournal(tmp_path / "gateway.jsonl")
    request = MediaSyncRequest(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-1",
        mission_id="mission-1",
        destination_prefix="objects/raw/site-a/mission-1",
        idempotency_key="media-work-1-cycle-1",
    )
    missing_upload = ZeroTouchGateway(
        provider=provider,
        capabilities=_evidence(Capability.CAMERA_MEDIA_PULL),
        journal=journal,
        media_sync_enabled=True,
    )
    with pytest.raises(CapabilityUnavailableError, match="MEDIA_UPLOAD"):
        missing_upload.sync_media(request)

    ready = ZeroTouchGateway(
        provider=provider,
        capabilities=_evidence(Capability.CAMERA_MEDIA_PULL, Capability.MEDIA_UPLOAD),
        journal=journal,
        media_sync_enabled=True,
    )
    receipt = ready.sync_media(request)
    assert receipt.item_count == 24
    assert receipt.manifest_ref == "objects/manifests/mission-1.json"
    assert provider.media_calls == 1
    journal.close()


def test_verified_capability_requires_evidence_and_object_refs_cannot_embed_queries() -> None:
    with pytest.raises(ValueError, match="evidence_ref"):
        CapabilityEvidence(
            path=IntegrationPath.DJI_CLOUD,
            capability=Capability.WAYLINE_PUSH,
            status=CapabilityStatus.VERIFIED,
            checked_at=_NOW,
        )
    with pytest.raises(ValueError, match="query"):
        replace(_wayline(), wayline_object_ref="https://storage/item?token=secret")


def test_vendor_documentation_is_a_separate_evidence_axis() -> None:
    evidence = CapabilityEvidence(
        path=IntegrationPath.DJI_CLOUD,
        capability=Capability.WAYLINE_DELIVERY,
        status=CapabilityStatus.NOT_VERIFIED,
        checked_at=_NOW,
        vendor_documentation_status=VendorDocumentationStatus.DOCUMENTED_PARTIAL,
        vendor_documentation_ref="dji/cloud-api/release-notes#wayline",
    )

    assert evidence.field_status is CapabilityStatus.NOT_VERIFIED
    assert evidence.field_evidence_ref is None
    assert evidence.vendor_documentation_status is VendorDocumentationStatus.DOCUMENTED_PARTIAL
    assert evidence.vendor_documentation_ref == "dji/cloud-api/release-notes#wayline"

    with pytest.raises(ValueError, match="vendor_documentation_ref"):
        CapabilityEvidence(
            path=IntegrationPath.DJI_CLOUD,
            capability=Capability.WAYLINE_DELIVERY,
            status=CapabilityStatus.NOT_VERIFIED,
            checked_at=_NOW,
            vendor_documentation_status=VendorDocumentationStatus.DOCUMENTED_SUPPORTED,
        )


class _RoutePort:
    def __init__(
        self,
        port_id: str,
        path: IntegrationPath,
        transport: GatewayTransport,
        capabilities: frozenset[Capability],
    ) -> None:
        self.port_id = port_id
        self.integration_path = path
        self.transport = transport
        self.capabilities = capabilities
        self.configuration_ready = True
        self.organization_id = "org-a"
        self.site_id = "site-a"
        self.gateway_device_id = "gateway-a"
        self.edge_device_id = "edge-a"


def test_capability_router_selects_per_feature_not_provider() -> None:
    hardware = "M4D-RC-PLUS-2-M3"
    firmware = "rc-psdk-hil-1"
    rc = _RoutePort(
        "rc-cloud",
        IntegrationPath.DJI_CLOUD,
        GatewayTransport.RC_WIFI,
        frozenset({Capability.WAYLINE_DELIVERY, Capability.EDGE_UPLINK}),
    )
    direct = _RoutePort(
        "manifold-direct",
        IntegrationPath.MANIFOLD_DIRECT,
        GatewayTransport.MANIFOLD_CELLULAR,
        frozenset({Capability.EDGE_UPLINK, Capability.MEDIA_UPLOAD}),
    )
    registry = CapabilityRegistry(
        [
            CapabilityEvidence(
                path=IntegrationPath.DJI_CLOUD,
                capability=Capability.WAYLINE_DELIVERY,
                status=CapabilityStatus.VERIFIED,
                checked_at="2026-08-21T09:00:00+00:00",
                evidence_ref="hil/wayline",
                hardware_model=hardware,
                firmware_version=firmware,
            ),
            CapabilityEvidence(
                path=IntegrationPath.MANIFOLD_DIRECT,
                capability=Capability.EDGE_UPLINK,
                status=CapabilityStatus.VERIFIED,
                checked_at="2026-08-21T09:00:00+00:00",
                evidence_ref="hil/direct-uplink",
                hardware_model=hardware,
                firmware_version=firmware,
            ),
        ]
    )
    router = CapabilityRouter(
        routes=(CapabilityRoute(direct, 0), CapabilityRoute(rc, 10)),
        registry=registry,
        feature_flags={
            Capability.WAYLINE_DELIVERY: True,
            Capability.EDGE_UPLINK: True,
        },
    )
    allowed = frozenset({GatewayTransport.RC_WIFI, GatewayTransport.MANIFOLD_CELLULAR})

    selected, _evidence = router.select(
        Capability.WAYLINE_DELIVERY,
        organization_id="org-a",
        site_id="site-a",
        gateway_device_id="gateway-a",
        edge_device_id="edge-a",
        hardware_model=hardware,
        firmware_version=firmware,
        allowed_transports=allowed,
    )
    assert selected.port_id == "rc-cloud"
    selected, _evidence = router.select(
        Capability.EDGE_UPLINK,
        organization_id="org-a",
        site_id="site-a",
        gateway_device_id="gateway-a",
        edge_device_id="edge-a",
        hardware_model=hardware,
        firmware_version=firmware,
        allowed_transports=allowed,
    )
    assert selected.port_id == "manifold-direct"


def test_capability_router_defaults_every_feature_flag_off() -> None:
    port = _RoutePort(
        "rc-cloud",
        IntegrationPath.DJI_CLOUD,
        GatewayTransport.RC_WIFI,
        frozenset({Capability.WAYLINE_DELIVERY}),
    )
    router = CapabilityRouter(routes=(CapabilityRoute(port, 0),), registry=CapabilityRegistry([]))
    with pytest.raises(CapabilityUnavailableError, match="feature flag"):
        router.select(
            Capability.WAYLINE_DELIVERY,
            organization_id="org-a",
            site_id="site-a",
            gateway_device_id="gateway-a",
            edge_device_id="edge-a",
            hardware_model="M4D",
            firmware_version="unknown",
            allowed_transports=frozenset({GatewayTransport.RC_WIFI}),
        )


def test_capability_router_rejects_documented_but_field_unverified_capability() -> None:
    hardware = "M4D-RC-PLUS-2-M3"
    firmware = "rc-cloud-1"
    port = _RoutePort(
        "rc-cloud",
        IntegrationPath.DJI_CLOUD,
        GatewayTransport.RC_WIFI,
        frozenset({Capability.WAYLINE_DELIVERY}),
    )
    router = CapabilityRouter(
        routes=(CapabilityRoute(port, 0),),
        registry=CapabilityRegistry(
            [
                CapabilityEvidence(
                    path=IntegrationPath.DJI_CLOUD,
                    capability=Capability.WAYLINE_DELIVERY,
                    status=CapabilityStatus.NOT_VERIFIED,
                    checked_at=_NOW,
                    hardware_model=hardware,
                    firmware_version=firmware,
                    vendor_documentation_status=VendorDocumentationStatus.DOCUMENTED_SUPPORTED,
                    vendor_documentation_ref="dji/cloud-api/support-matrix#m4d",
                )
            ]
        ),
        feature_flags={Capability.WAYLINE_DELIVERY: True},
    )

    with pytest.raises(CapabilityUnavailableError, match="NOT_VERIFIED"):
        router.select(
            Capability.WAYLINE_DELIVERY,
            organization_id="org-a",
            site_id="site-a",
            gateway_device_id="gateway-a",
            edge_device_id="edge-a",
            hardware_model=hardware,
            firmware_version=firmware,
            allowed_transports=frozenset({GatewayTransport.RC_WIFI}),
        )


def test_gateway_journal_reads_v12_receipts_without_guessing_v13_fields(tmp_path: Path) -> None:
    path = tmp_path / "gateway.jsonl"
    path.write_text(
        '{"accepted_at":"2026-08-21T09:00:00+00:00","idempotency_key":"legacy-1",'
        '"item_count":1,"manifest_ref":null,"operation":"WAYLINE_DISPATCH",'
        '"path":"DJI_CLOUD","provider_operation_id":"provider-1",'
        '"request_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}\n'
    )
    journal = GatewayJournal(path)
    legacy = journal.find(OperationKind.WAYLINE_DISPATCH, "legacy-1")
    assert legacy is not None and legacy.journal_schema_version == "1.2"
    assert legacy.capability is None and legacy.transport is None
    journal.close()


def test_gateway_journal_v13_requires_and_preserves_exact_route_evidence(tmp_path: Path) -> None:
    path = tmp_path / "gateway.jsonl"
    journal = GatewayJournal(path)
    with pytest.raises(ValueError, match="capability와 transport"):
        IntegrationReceipt(
            operation=OperationKind.EDGE_UPLINK,
            path=IntegrationPath.MANIFOLD_DIRECT,
            idempotency_key="uplink-1",
            request_sha256="b" * 64,
            provider_operation_id="provider-1",
            accepted_at=_NOW,
            item_count=1,
            manifest_ref=None,
            journal_schema_version="1.3",
        )

    receipt = IntegrationReceipt(
        operation=OperationKind.EDGE_UPLINK,
        path=IntegrationPath.MANIFOLD_DIRECT,
        idempotency_key="uplink-1",
        request_sha256="b" * 64,
        provider_operation_id="provider-1",
        accepted_at=_NOW,
        item_count=1,
        manifest_ref=None,
        capability=Capability.EDGE_UPLINK,
        transport=GatewayTransport.MANIFOLD_CELLULAR,
        journal_schema_version="1.3",
    )
    journal.append(receipt)
    journal.close()

    replay = GatewayJournal(path)
    assert replay.find(OperationKind.EDGE_UPLINK, "uplink-1") == receipt
    replay.close()
