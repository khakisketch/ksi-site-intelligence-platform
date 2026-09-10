"""Typed, default-closed authority adapters for external relative-volume work.

The production port intentionally contains no compatibility profile, execution
limit, or mapping admission data.  A local synthetic fixture can register fully
formed, explicitly synthetic Core authority records for contract tests only.
Those records are never synthesized from a validation-policy digest list.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ksi_event_contracts.external_artifact_validation import (
    ExternalPairUseDecisionV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
)

from ksi_core.auth import Principal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_relative_volumes import ExternalRelativeVolumeExecutionAuthority


@dataclass(frozen=True, slots=True)
class ExternalRelativeVolumeAuthority:
    """Exact mapping/zone identity resolved independently of a caller request."""

    zone: SealedZoneReferenceV1
    compatibility_mapping_digest: str
    historical_authority_digest: str
    synthetic_test_only: bool


class ExternalRelativeVolumeAuthorityPort(Protocol):
    """Pair-decision mapping authority; implementations default closed."""

    currentness_coordinator: ExternalAuthorityCurrentnessCoordinator

    def resolve_for_use(
        self,
        *,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        zone_id: str,
        policy: ExternalValidationPolicyV1,
        now: datetime,
    ) -> ExternalRelativeVolumeAuthority | None: ...

    def is_current_for_use(
        self, authority: ExternalRelativeVolumeAuthority, *, now: datetime
    ) -> bool: ...

    def resolve_historical_for_decision(
        self, decision: ExternalPairUseDecisionV1
    ) -> ExternalRelativeVolumeAuthority | None: ...


class DefaultClosedExternalRelativeVolumeAuthorityPort:
    """Production-safe placeholder until a separately approved mapping source exists."""

    def __init__(self, *, currentness_coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self.currentness_coordinator = currentness_coordinator

    def resolve_for_use(
        self,
        *,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        zone_id: str,
        policy: ExternalValidationPolicyV1,
        now: datetime,
    ) -> ExternalRelativeVolumeAuthority | None:
        del baseline, current, zone_id, policy, now
        return None

    def is_current_for_use(
        self, authority: ExternalRelativeVolumeAuthority, *, now: datetime
    ) -> bool:
        del authority, now
        return False

    def resolve_historical_for_decision(
        self, decision: ExternalPairUseDecisionV1
    ) -> ExternalRelativeVolumeAuthority | None:
        del decision
        return None

    def resolve_for_issue(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        del principal, current_work_order_id, decision_ref, now
        return None

    @contextmanager
    def guard_current(
        self,
        *,
        authority: ExternalRelativeVolumeExecutionAuthority,
        principal: Principal,
        now: datetime,
    ) -> Iterator[ExternalRelativeVolumeExecutionAuthority | None]:
        del authority, principal, now
        yield None

    def resolve_historical(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        issued_at: datetime,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        del historical_authority_digest, decision_id, decision_digest, issued_at, now
        return None


class SyntheticExternalRelativeVolumeAuthorityPort:
    """Explicit test-only authority registry, with no production profile fallback.

    The complete execution record is the authority source.  The policy's
    compatibility digest list remains an admission constraint elsewhere and is
    never promoted into mapping truth here.
    """

    def __init__(
        self,
        authorities: tuple[ExternalRelativeVolumeExecutionAuthority, ...],
        *,
        currentness_coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.currentness_coordinator = currentness_coordinator
        self._authorities = {
            authority.historical_authority_digest: authority for authority in authorities
        }
        if len(self._authorities) != len(authorities):
            raise ValueError(
                "synthetic relative-volume authorities require unique history identities"
            )
        if any(
            not authority.synthetic_test_only or not authority.execution_policy.synthetic_test_only
            for authority in authorities
        ):
            raise ValueError("synthetic authority registry refuses production authority records")

    @staticmethod
    def _pair_authority(
        authority: ExternalRelativeVolumeExecutionAuthority,
    ) -> ExternalRelativeVolumeAuthority:
        return ExternalRelativeVolumeAuthority(
            zone=authority.zone_snapshot.to_zone_reference(),
            compatibility_mapping_digest=authority.compatibility_mapping_digest,
            historical_authority_digest=authority.historical_authority_digest,
            synthetic_test_only=True,
        )

    def resolve_for_use(
        self,
        *,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        zone_id: str,
        policy: ExternalValidationPolicyV1,
        now: datetime,
    ) -> ExternalRelativeVolumeAuthority | None:
        for authority in self._authorities.values():
            if (
                authority.is_current_at(now)
                and authority.baseline.subject == baseline
                and authority.current.subject == current
                and authority.zone_snapshot.work_area_id == zone_id
                and authority.validation_policy_digest == policy.policy_digest
            ):
                return self._pair_authority(authority)
        return None

    def is_current_for_use(
        self, authority: ExternalRelativeVolumeAuthority, *, now: datetime
    ) -> bool:
        candidate = self._authorities.get(authority.historical_authority_digest)
        return bool(
            candidate
            and candidate.is_current_at(now)
            and self._pair_authority(candidate) == authority
        )

    def resolve_historical_for_decision(
        self, decision: ExternalPairUseDecisionV1
    ) -> ExternalRelativeVolumeAuthority | None:
        if (
            decision.use != "RELATIVE_VOLUME"
            or decision.compatibility_mapping_digest is None
            or decision.zone is None
            or decision.policy_digest is None
        ):
            return None
        for authority in self._authorities.values():
            resolved = self._pair_authority(authority)
            if (
                authority.decision_id == decision.decision_id
                and authority.decision_digest == decision.decision_digest
                and authority.validation_policy_digest == decision.policy_digest
                and authority.baseline.subject == decision.baseline_subject
                and authority.current.subject == decision.current_subject
                and resolved.zone == decision.zone
                and resolved.compatibility_mapping_digest == decision.compatibility_mapping_digest
                and authority.is_current_at(decision.decided_at)
            ):
                return resolved
        return None

    def resolve_for_issue(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        for authority in self._authorities.values():
            if (
                authority.is_current_at(now)
                and authority.current_work_order_id == current_work_order_id
                and authority.decision_id == decision_ref
                and principal.organization_id == authority.organization_id
                and principal.principal_id in authority.authorized_actor_ids
            ):
                return authority
        return None

    @contextmanager
    def guard_current(
        self,
        *,
        authority: ExternalRelativeVolumeExecutionAuthority,
        principal: Principal,
        now: datetime,
    ) -> Iterator[ExternalRelativeVolumeExecutionAuthority | None]:
        current = self._authorities.get(authority.historical_authority_digest)
        if (
            current != authority
            or not authority.is_current_at(now)
            or principal.organization_id != authority.organization_id
            or principal.principal_id not in authority.authorized_actor_ids
        ):
            yield None
            return
        yield authority

    def resolve_historical(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        issued_at: datetime,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        del now
        authority = self._authorities.get(historical_authority_digest)
        if (
            authority is None
            or authority.decision_id != decision_id
            or authority.decision_digest != decision_digest
            or not authority.is_current_at(issued_at)
        ):
            return None
        return authority


__all__ = [
    "DefaultClosedExternalRelativeVolumeAuthorityPort",
    "ExternalRelativeVolumeAuthority",
    "ExternalRelativeVolumeAuthorityPort",
    "SyntheticExternalRelativeVolumeAuthorityPort",
]
