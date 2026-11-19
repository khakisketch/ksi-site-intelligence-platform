"""Default-closed compatibility authority for profile differences.

This authority is independent of volume zones and binds both ordered subjects
to the parser-observed CRS and vertical reference for their measured DSMs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ksi_event_contracts.external_artifact_validation import (
    ExternalPairUseDecisionV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)

from ksi_core.domains.external.quantity.external_quantitative_common import _required_digest, _utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator


@dataclass(frozen=True, slots=True)
class ExternalProfileDifferenceAuthority:
    baseline_subject_digest: str
    current_subject_digest: str
    baseline_artifact_id: str
    baseline_source_sha256: str
    current_artifact_id: str
    current_source_sha256: str
    baseline_capture_started_at: datetime
    baseline_capture_ended_at: datetime
    current_capture_started_at: datetime
    current_capture_ended_at: datetime
    observed_crs_digest: str
    observed_vertical_reference_digest: str
    policy_digest: str
    compatibility_mapping_digest: str
    historical_authority_digest: str
    valid_from: datetime
    valid_until: datetime
    synthetic_test_only: bool
    compatibility_rule_digest: str | None = None
    work_area_id: str | None = None
    evidence_record_digests: tuple[str, ...] = ()
    baseline_inspection_report_digest: str | None = None
    current_inspection_report_digest: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "baseline_capture_started_at",
            "baseline_capture_ended_at",
            "current_capture_started_at",
            "current_capture_ended_at",
            "valid_from",
            "valid_until",
        ):
            _utc(getattr(self, name), name=name)
        if self.baseline_capture_started_at >= self.baseline_capture_ended_at:
            raise ValueError("baseline profile-difference capture interval must be positive")
        if self.current_capture_started_at >= self.current_capture_ended_at:
            raise ValueError("current profile-difference capture interval must be positive")
        if self.baseline_capture_ended_at > self.current_capture_started_at:
            raise ValueError("profile-difference captures must be ordered and non-overlapping")
        if self.valid_from >= self.valid_until:
            raise ValueError("profile-difference authority validity interval must be positive")
        if self.evidence_record_digests and (
            len(self.evidence_record_digests) != 2 or len(set(self.evidence_record_digests)) != 2
        ):
            raise ValueError("profile mapping must bind one distinct evidence record per epoch")
        if not self.synthetic_test_only and (
            not self.work_area_id
            or self.work_area_id != self.work_area_id.strip()
            or self.compatibility_rule_digest is None
            or self.baseline_inspection_report_digest is None
            or self.current_inspection_report_digest is None
            or not self.evidence_record_digests
            or self.historical_authority_digest != self.compatibility_mapping_digest
        ):
            raise ValueError("profile mapping requires exact WorkArea, rule, reports and evidence")
        for name, value in (
            ("baseline subject digest", self.baseline_subject_digest),
            ("current subject digest", self.current_subject_digest),
            ("baseline source sha256", self.baseline_source_sha256),
            ("current source sha256", self.current_source_sha256),
            ("observed CRS digest", self.observed_crs_digest),
            ("observed vertical reference digest", self.observed_vertical_reference_digest),
            ("policy digest", self.policy_digest),
            ("compatibility mapping digest", self.compatibility_mapping_digest),
            ("historical authority digest", self.historical_authority_digest),
        ):
            _required_digest(value, name=name)
        for name, digest in (
            ("rule digest", self.compatibility_rule_digest),
            ("baseline inspection report digest", self.baseline_inspection_report_digest),
            ("current inspection report digest", self.current_inspection_report_digest),
            *(("evidence digest", digest) for digest in self.evidence_record_digests),
        ):
            if digest is not None:
                _required_digest(digest, name=name)

    def authorized_by(self, policy: ExternalValidationPolicyV1) -> bool:
        # Only legacy fixtures pre-authorize their made-up mapping identity.
        # A production policy can name the rule before the full record exists.
        rule = self.compatibility_rule_digest
        if rule is None and self.synthetic_test_only:
            rule = self.compatibility_mapping_digest
        return (
            self.policy_digest == policy.policy_digest
            and (self.synthetic_test_only or not policy.synthetic_test_only)
            and rule in policy.compatibility_mapping_digests
        )

    def binds(
        self,
        *,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        baseline_artifact_id: str,
        baseline_source_sha256: str,
        current_artifact_id: str,
        current_source_sha256: str,
        baseline_capture_started_at: datetime,
        baseline_capture_ended_at: datetime,
        current_capture_started_at: datetime,
        current_capture_ended_at: datetime,
        observed_crs_digest: str,
        observed_vertical_reference_digest: str,
        policy_digest: str,
    ) -> bool:
        return (
            self.baseline_subject_digest == baseline.canonical_digest()
            and self.current_subject_digest == current.canonical_digest()
            and self.baseline_artifact_id == baseline_artifact_id
            and self.baseline_source_sha256 == baseline_source_sha256
            and self.current_artifact_id == current_artifact_id
            and self.current_source_sha256 == current_source_sha256
            and self.baseline_capture_started_at == baseline_capture_started_at
            and self.baseline_capture_ended_at == baseline_capture_ended_at
            and self.current_capture_started_at == current_capture_started_at
            and self.current_capture_ended_at == current_capture_ended_at
            and self.observed_crs_digest == observed_crs_digest
            and self.observed_vertical_reference_digest == observed_vertical_reference_digest
            and self.policy_digest == policy_digest
        )

    def is_current_at(self, now: datetime) -> bool:
        return self.valid_from <= now < self.valid_until


class ExternalProfileDifferenceAuthorityPort(Protocol):
    currentness_coordinator: ExternalAuthorityCurrentnessCoordinator

    def resolve_for_use(
        self,
        *,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        baseline_artifact_id: str,
        baseline_source_sha256: str,
        current_artifact_id: str,
        current_source_sha256: str,
        policy: ExternalValidationPolicyV1,
        baseline_capture_started_at: datetime,
        baseline_capture_ended_at: datetime,
        current_capture_started_at: datetime,
        current_capture_ended_at: datetime,
        observed_crs_digest: str,
        observed_vertical_reference_digest: str,
        now: datetime,
        work_area_id: str | None = None,
    ) -> ExternalProfileDifferenceAuthority | None: ...

    def is_current_for_use(
        self, authority: ExternalProfileDifferenceAuthority, *, now: datetime
    ) -> bool: ...

    def resolve_historical_for_decision(
        self, decision: ExternalPairUseDecisionV1
    ) -> ExternalProfileDifferenceAuthority | None: ...


class DefaultClosedExternalProfileDifferenceAuthorityPort:
    """Production stays blocked until an independently approved mapping exists."""

    def __init__(self, *, currentness_coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self.currentness_coordinator = currentness_coordinator

    def resolve_for_use(self, **kwargs: object) -> ExternalProfileDifferenceAuthority | None:
        del kwargs
        return None

    def is_current_for_use(
        self, authority: ExternalProfileDifferenceAuthority, *, now: datetime
    ) -> bool:
        del authority, now
        return False

    def resolve_historical_for_decision(
        self, decision: ExternalPairUseDecisionV1
    ) -> ExternalProfileDifferenceAuthority | None:
        del decision
        return None


class SyntheticExternalProfileDifferenceAuthorityPort:
    """Explicit fixture-only authority for ordered, exact profile-difference pairs.

    A fixture must supply a complete mapping for the exact sealed subjects,
    DSMs, parser observations, policy, and capture intervals. No digest is
    inferred from policy or subject identity.
    """

    def __init__(
        self,
        authorities: tuple[ExternalProfileDifferenceAuthority, ...],
        *,
        currentness_coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.currentness_coordinator = currentness_coordinator
        self._authorities = {
            authority.historical_authority_digest: authority for authority in authorities
        }
        if len(self._authorities) != len(authorities):
            raise ValueError(
                "synthetic profile-difference authorities require unique history identities"
            )
        if any(not authority.synthetic_test_only for authority in authorities):
            raise ValueError("synthetic authority registry refuses production mapping records")

    def resolve_for_use(
        self,
        *,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        baseline_artifact_id: str,
        baseline_source_sha256: str,
        current_artifact_id: str,
        current_source_sha256: str,
        policy: ExternalValidationPolicyV1,
        baseline_capture_started_at: datetime,
        baseline_capture_ended_at: datetime,
        current_capture_started_at: datetime,
        current_capture_ended_at: datetime,
        observed_crs_digest: str,
        observed_vertical_reference_digest: str,
        now: datetime,
        work_area_id: str | None = None,
    ) -> ExternalProfileDifferenceAuthority | None:
        for authority in self._authorities.values():
            if (
                authority.is_current_at(now)
                and (authority.work_area_id is None or authority.work_area_id == work_area_id)
                and authority.binds(
                    baseline=baseline,
                    current=current,
                    baseline_artifact_id=baseline_artifact_id,
                    baseline_source_sha256=baseline_source_sha256,
                    current_artifact_id=current_artifact_id,
                    current_source_sha256=current_source_sha256,
                    baseline_capture_started_at=baseline_capture_started_at,
                    baseline_capture_ended_at=baseline_capture_ended_at,
                    current_capture_started_at=current_capture_started_at,
                    current_capture_ended_at=current_capture_ended_at,
                    observed_crs_digest=observed_crs_digest,
                    observed_vertical_reference_digest=observed_vertical_reference_digest,
                    policy_digest=policy.policy_digest or "",
                )
                and authority.authorized_by(policy)
            ):
                return authority
        return None

    def is_current_for_use(
        self, authority: ExternalProfileDifferenceAuthority, *, now: datetime
    ) -> bool:
        current = self._authorities.get(authority.historical_authority_digest)
        return current == authority and authority.is_current_at(now)

    def resolve_historical_for_decision(
        self, decision: ExternalPairUseDecisionV1
    ) -> ExternalProfileDifferenceAuthority | None:
        if (
            decision.use != "PROFILE_DIFFERENCE"
            or decision.verdict.value == "BLOCKED"
            or decision.policy_digest is None
            or decision.compatibility_mapping_digest is None
        ):
            return None
        for authority in self._authorities.values():
            if (
                authority.baseline_subject_digest == decision.baseline_subject_digest
                and authority.current_subject_digest == decision.current_subject_digest
                and authority.baseline_artifact_id == decision.baseline_artifact_id
                and authority.baseline_source_sha256 == decision.baseline_source_sha256
                and authority.current_artifact_id == decision.current_artifact_id
                and authority.current_source_sha256 == decision.current_source_sha256
                and authority.policy_digest == decision.policy_digest
                and authority.compatibility_mapping_digest == decision.compatibility_mapping_digest
                and authority.is_current_at(decision.decided_at)
            ):
                return authority
        return None


__all__ = [
    "DefaultClosedExternalProfileDifferenceAuthorityPort",
    "ExternalProfileDifferenceAuthority",
    "ExternalProfileDifferenceAuthorityPort",
    "SyntheticExternalProfileDifferenceAuthorityPort",
]
