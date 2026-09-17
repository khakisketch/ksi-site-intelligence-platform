"""Single-volume mapping authority value and default-closed port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
)
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeDecisionV1

from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator


@dataclass(frozen=True, slots=True)
class ExternalSingleVolumeAuthority:
    zone: SealedZoneReferenceV1
    compatibility_mapping_digest: str
    historical_authority_digest: str
    synthetic_test_only: bool


class ExternalSingleVolumeAuthorityPort(Protocol):
    currentness_coordinator: ExternalAuthorityCurrentnessCoordinator

    def resolve_for_use(
        self,
        *,
        subject: SealedExternalSubjectV1,
        zone_id: str,
        policy: ExternalValidationPolicyV1,
        now: datetime,
    ) -> ExternalSingleVolumeAuthority | None: ...

    def is_current_for_use(
        self, authority: ExternalSingleVolumeAuthority, *, now: datetime
    ) -> bool: ...

    def resolve_historical_for_decision(
        self, decision: ExternalSingleVolumeDecisionV1
    ) -> ExternalSingleVolumeAuthority | None: ...


class DefaultClosedExternalSingleVolumeAuthorityPort:
    def __init__(self, *, currentness_coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self.currentness_coordinator = currentness_coordinator

    def resolve_for_use(
        self,
        *,
        subject: SealedExternalSubjectV1,
        zone_id: str,
        policy: ExternalValidationPolicyV1,
        now: datetime,
    ) -> ExternalSingleVolumeAuthority | None:
        del subject, zone_id, policy, now
        return None

    def is_current_for_use(
        self, authority: ExternalSingleVolumeAuthority, *, now: datetime
    ) -> bool:
        del authority, now
        return False

    def resolve_historical_for_decision(
        self, decision: ExternalSingleVolumeDecisionV1
    ) -> ExternalSingleVolumeAuthority | None:
        del decision
        return None


__all__ = [
    "DefaultClosedExternalSingleVolumeAuthorityPort",
    "ExternalSingleVolumeAuthority",
    "ExternalSingleVolumeAuthorityPort",
]
