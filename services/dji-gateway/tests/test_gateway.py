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
    CapabilityStatus,
    CapabilityUnavailableError,
    GatewayJournal,
    IdempotencyConflictError,
    IntegrationPath,
    MediaSyncRequest,
    ProviderReceipt,
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
