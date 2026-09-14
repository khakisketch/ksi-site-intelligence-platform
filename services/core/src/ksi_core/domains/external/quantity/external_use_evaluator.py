"""Core-resolved, current per-use decisions for sealed external artifacts.

The request surface contains only a requested use and a caller selection.  This
module resolves every policy, report, receipt, evidence record, and volume-zone
authority reference itself.  It never accepts a caller-provided digest, worker
observation, verdict, storage key, or numeric result.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    DecisionVerdict,
    ExternalArtifactInspectionReportV1,
    ExternalPairUseDecisionV1,
    ExternalUseDecisionV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_display_artifact import SanitizedDisplayReceiptV1
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pydantic import Field

from ksi_core.domains.external.ingress.external_artifact_inspections import PublicInspectionSnapshot
from ksi_core.domains.external.ingress.external_evidence_validations import (
    ExternalEvidenceValidationStore,
)
from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionRevision,
    ExternalReconstructionStore,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicySelectionStatus,
)
from ksi_core.domains.external.quantity.external_relative_volume_authorities import (
    DefaultClosedExternalRelativeVolumeAuthorityPort,
    ExternalRelativeVolumeAuthority,
    ExternalRelativeVolumeAuthorityPort,
)
from ksi_core.domains.external.quantity.external_use_decisions import (
    DecisionCandidate,
    ExternalDecisionIntent,
    ExternalUseDecisionConflictError,
    ExternalUseDecisionHistoryVerifier,
    ExternalUseDecisionStore,
)
from ksi_core.foundation.api_base import CamelModel
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Principal


def _digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class ExternalInspectionDecisionPort(Protocol):
    def public_snapshot(self, subject: SealedExternalSubjectV1) -> PublicInspectionSnapshot: ...

    def public_display_state(
        self, subject: SealedExternalSubjectV1
    ) -> tuple[str, SanitizedDisplayReceiptV1 | None]: ...

    def historical_report(
        self,
        subject: SealedExternalSubjectV1,
        *,
        report_digest: str,
        policy_digest: str,
    ) -> ExternalArtifactInspectionReportV1 | None: ...

    def historical_display_receipt(
        self,
        subject: SealedExternalSubjectV1,
        *,
        report_digest: str,
        receipt_digest: str,
        policy_digest: str,
    ) -> SanitizedDisplayReceiptV1 | None: ...


class CoreExternalUseDecisionHistoryVerifier(ExternalUseDecisionHistoryVerifier):
    """Replay verifier for independently retained Core source journals.

    Relative-volume history remains closed until its later authority adapter
    supplies immutable mapping history; no policy digest list is treated as a
    substitute for the mapping content.
    """

    def __init__(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalInspectionDecisionPort,
        policy_registry: ExternalValidationPolicyRegistry,
        evidence_validations: ExternalEvidenceValidationStore,
        relative_volume_authority: ExternalRelativeVolumeAuthorityPort | None = None,
    ) -> None:
        self._reconstruction = reconstruction
        self._inspections = inspections
        self._policy_registry = policy_registry
        self._evidence_validations = evidence_validations
        self._relative_volume_authority = relative_volume_authority

    def verify(self, candidate: DecisionCandidate) -> bool:
        if isinstance(candidate, ExternalUseDecisionV1):
            return self._verify_single(candidate)
        return self._verify_pair(candidate)

    def _verify_single(self, candidate: ExternalUseDecisionV1) -> bool:
        policy_digest, report_digest = candidate.policy_digest, candidate.inspection_report_digest
        if policy_digest is None or report_digest is None:
            return False
        if not self._policy_registry.historical_use_permitted(
            policy_digest,
            use=candidate.use,
            subjects=(candidate.subject,),
            at=candidate.decided_at,
        ):
            return False
        policy = self._policy_registry.resolve(policy_digest).policy
        if policy is None:
            return False
        revision = self._reconstruction.resolve_sealed_subject(candidate.subject)
        report = self._inspections.historical_report(
            candidate.subject, report_digest=report_digest, policy_digest=policy_digest
        )
        if (
            revision is None
            or not ExternalUseEvaluator._report_binds(
                candidate.subject,
                report,
                policy,
            )
            or not ExternalUseEvaluator._measured_kind(
                revision, report, ProcessingArtifactKind.ORTHO
            )
            or candidate.sanitized_display_receipt_digest is None
        ):
            return False
        return (
            self._inspections.historical_display_receipt(
                candidate.subject,
                report_digest=report_digest,
                receipt_digest=candidate.sanitized_display_receipt_digest,
                policy_digest=policy_digest,
            )
            is not None
        )

    def _verify_pair(self, candidate: ExternalPairUseDecisionV1) -> bool:
        policy_digest = candidate.policy_digest
        if policy_digest is None or not self._policy_registry.historical_use_permitted(
            policy_digest,
            use=candidate.use,
            subjects=(candidate.baseline_subject, candidate.current_subject),
            at=candidate.decided_at,
        ):
            return False
        reports = (
            (candidate.baseline_subject, candidate.baseline_inspection_report_digest),
            (candidate.current_subject, candidate.current_inspection_report_digest),
        )
        resolved_reports: list[
            tuple[SealedExternalSubjectV1, ExternalArtifactInspectionReportV1]
        ] = []
        policy = self._policy_registry.resolve(policy_digest).policy
        if policy is None:
            return False
        for subject, digest in reports:
            report = (
                self._inspections.historical_report(
                    subject, report_digest=digest, policy_digest=policy_digest
                )
                if digest is not None
                else None
            )
            if (
                self._reconstruction.resolve_sealed_subject(subject) is None
                or not ExternalUseEvaluator._report_binds(subject, report, policy)
            ):
                return False
            assert report is not None
            resolved_reports.append((subject, report))
        if candidate.use == "VISUAL_COMPARISON":
            receipts = (
                candidate.baseline_sanitized_display_receipt_digest,
                candidate.current_sanitized_display_receipt_digest,
            )
            return all(
                receipt is not None
                and self._inspections.historical_display_receipt(
                    subject,
                    report_digest=report.report_digest or "",
                    receipt_digest=receipt,
                    policy_digest=policy_digest,
                )
                is not None
                for (subject, report), receipt in zip(resolved_reports, receipts, strict=True)
            ) and not candidate.evidence_record_digests
        if candidate.use != "RELATIVE_VOLUME" or self._relative_volume_authority is None:
            return False
        authority = self._relative_volume_authority.resolve_historical_for_decision(candidate)
        if (
            authority is None
            or candidate.compatibility_mapping_digest != authority.compatibility_mapping_digest
            or candidate.zone != authority.zone
            or len(candidate.evidence_record_digests) != 2
        ):
            return False
        for digest, (subject, report) in zip(
            candidate.evidence_record_digests, resolved_reports, strict=True
        ):
            evidence = self._evidence_validations.record_for_use(
                digest, subject=subject, policy_digest=policy_digest
            )
            if evidence is None:
                return False
            _record, context = evidence
            if (
                context.independent_attestation is None
                or not ExternalUseEvaluator._report_measures_dsm(
                    report, context.target_dsm_artifact_id, context.target_dsm_observed_sha256
                )
            ):
                return False
        return True


@dataclass(frozen=True, slots=True)
class _SingleSnapshot:
    policy: ExternalValidationPolicyV1 | None
    inspection: PublicInspectionSnapshot
    display: SanitizedDisplayReceiptV1 | None
    revision: ExternalReconstructionRevision | None


@dataclass(frozen=True, slots=True)
class _PairSnapshot:
    policy: ExternalValidationPolicyV1 | None
    baseline: _SingleSnapshot
    current: _SingleSnapshot


class ExternalSingleUseDecisionRequest(CamelModel):
    use: Literal["DISPLAY", "HEIGHT"]


class ExternalPairUseDecisionRequest(CamelModel):
    use: Literal["VISUAL_COMPARISON", "RELATIVE_VOLUME"]
    baseline_work_order_id: str = Field(min_length=1, max_length=255)
    baseline_submission_ref: str = Field(pattern=r"^ers-v1-[0-9a-f]{64}$")
    baseline_revision: int = Field(ge=1)
    zone_id: str | None = Field(default=None, min_length=1, max_length=255)


class ExternalUseDecisionResponse(CamelModel):
    decision: dict[str, Any]


class ExternalUseEvaluator:
    """Build and persist immutable use decisions from Core-owned authority.

    Remote/trusted authority calls occur before ``guarded_read``.  The final
    guard only compares the resolved snapshots with local current policy and
    source state, then appends the decision while all participating Core
    mutation paths are excluded by the shared coordinator.
    """

    def __init__(
        self,
        *,
        decisions: ExternalUseDecisionStore,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalInspectionDecisionPort,
        policy_registry: ExternalValidationPolicyRegistry,
        evidence_validations: ExternalEvidenceValidationStore,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        relative_volume_authority: ExternalRelativeVolumeAuthorityPort | None = None,
    ) -> None:
        for name, dependency in (
            ("external decision store", decisions),
            ("external reconstruction store", reconstruction),
            ("external inspection store", inspections),
            ("validation policy registry", policy_registry),
            ("evidence validation store", evidence_validations),
        ):
            if getattr(dependency, "coordinator", None) is not coordinator:
                raise ValueError(f"{name} must share currentness coordinator")
        if (
            relative_volume_authority is not None
            and relative_volume_authority.currentness_coordinator is not coordinator
        ):
            raise ValueError("relative-volume authority must share currentness coordinator")
        self._decisions = decisions
        self._reconstruction = reconstruction
        self._inspections = inspections
        self._policy_registry = policy_registry
        self._evidence_validations = evidence_validations
        self._coordinator = coordinator
        self._relative_volume_authority = relative_volume_authority or (
            DefaultClosedExternalRelativeVolumeAuthorityPort(
                currentness_coordinator=coordinator
            )
        )

    def request_single(
        self,
        subject: SealedExternalSubjectV1,
        *,
        use: str,
        idempotency_key: str,
        principal: Principal,
        now: datetime,
    ) -> ExternalUseDecisionV1:
        self._require_scope(principal, subject)
        if use not in {"DISPLAY", "HEIGHT"}:
            raise ValueError("single external use is invalid")
        intent = ExternalDecisionIntent(requested_use=use, subject=subject)
        existing = self._decisions.existing_for_intent(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        if existing is not None:
            if not isinstance(existing, ExternalUseDecisionV1):
                raise ValueError("idempotency decision operation conflicts")
            self._decisions.reconcile_pending()
            return existing
        evaluation_identity = self._decisions.evaluation_identity(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        snapshot = self._single_snapshot(subject, use)
        with self._coordinator.guarded_read():
            # Re-resolve immutable local source and local lifecycle status
            # under the commit guard.  No storage/presign or authority-port I/O
            # is performed here.
            current = self._single_still_current(subject, use, snapshot, now=now)
            candidate = self._single_candidate(subject, use, current, evaluation_identity, now)
            return cast(
                ExternalUseDecisionV1,
                self._record(candidate, intent, principal, idempotency_key),
            )

    def existing_single_retry(
        self,
        subject: SealedExternalSubjectV1,
        *,
        use: str,
        principal: Principal,
        idempotency_key: str,
    ) -> ExternalUseDecisionV1 | None:
        """Read an exact retained single-use retry without evaluating live authority."""

        intent = ExternalDecisionIntent(requested_use=use, subject=subject)
        existing = self._decisions.existing_for_intent(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        return existing if isinstance(existing, ExternalUseDecisionV1) else None

    def request_pair(
        self,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        *,
        use: str,
        zone_id: str | None,
        idempotency_key: str,
        principal: Principal,
        now: datetime,
    ) -> ExternalPairUseDecisionV1:
        self._require_pair_scope(principal, baseline, current)
        if use not in {"VISUAL_COMPARISON", "RELATIVE_VOLUME"}:
            raise ValueError("pair external use is invalid")
        if use == "VISUAL_COMPARISON" and zone_id is not None:
            raise ValueError("visual comparison cannot select a volume zone")
        if use == "RELATIVE_VOLUME" and not zone_id:
            raise ValueError("relative volume requires a zone selection")
        intent = ExternalDecisionIntent(
            requested_use=use,
            baseline_subject=baseline,
            current_subject=current,
            requested_zone_id=zone_id,
        )
        existing = self._decisions.existing_for_intent(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        if existing is not None:
            if not isinstance(existing, ExternalPairUseDecisionV1):
                raise ValueError("idempotency decision operation conflicts")
            self._decisions.reconcile_pending()
            return existing
        evaluation_identity = self._decisions.evaluation_identity(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        snapshot = self._pair_snapshot(baseline, current, use)
        volume = (
            self._relative_volume_authority.resolve_for_use(
                baseline=baseline,
                current=current,
                zone_id=zone_id or "",
                policy=snapshot.policy,
                now=now,
            )
            if use == "RELATIVE_VOLUME" and snapshot.policy is not None
            else None
        )
        evidence_current = (
            self._pair_evidence_remains_current(baseline, current, snapshot)
            if use == "RELATIVE_VOLUME" and snapshot.policy is not None
            else False
        )
        with self._coordinator.guarded_read():
            current_snapshot = self._pair_still_current(
                baseline, current, use, snapshot, now=now
            )
            if (
                use == "RELATIVE_VOLUME"
                and (
                    volume is None
                    or not evidence_current
                    or not self._relative_volume_authority.is_current_for_use(volume, now=now)
                )
            ):
                volume = None
            candidate = self._pair_candidate(
                baseline,
                current,
                use,
                zone_id,
                current_snapshot,
                volume,
                evaluation_identity,
                now,
            )
            return cast(
                ExternalPairUseDecisionV1,
                self._record(candidate, intent, principal, idempotency_key),
            )

    def existing_pair_retry(
        self,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        *,
        use: str,
        zone_id: str | None,
        principal: Principal,
        idempotency_key: str,
    ) -> ExternalPairUseDecisionV1 | None:
        """Read an exact retained pair-use retry without evaluating live authority."""

        intent = ExternalDecisionIntent(
            requested_use=use,
            baseline_subject=baseline,
            current_subject=current,
            requested_zone_id=zone_id,
        )
        existing = self._decisions.existing_for_intent(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        return existing if isinstance(existing, ExternalPairUseDecisionV1) else None

    def resolve_eligible_pair_for_execution(
        self, decision_id: str, *, principal: Principal, site_id: str
    ) -> ExternalPairUseDecisionV1 | None:
        """Private handoff for the later volume request issuer.

        A retained ELIGIBLE journal row is not execution authority.  This
        method rechecks current policy and all exact source chains before it
        returns a candidate to a later, separately authorized execution path.
        """
        candidate = self._decisions.get_scoped(decision_id, principal=principal, site_id=site_id)
        if (
            not isinstance(candidate, ExternalPairUseDecisionV1)
            or candidate.verdict is not DecisionVerdict.ELIGIBLE
        ):
            return None
        snapshot = self._pair_snapshot(
            candidate.baseline_subject, candidate.current_subject, candidate.use
        )
        now = datetime.now(UTC)
        volume = (
            self._relative_volume_authority.resolve_for_use(
                baseline=candidate.baseline_subject,
                current=candidate.current_subject,
                zone_id=candidate.zone.zone_id,
                policy=snapshot.policy,
                now=now,
            )
            if candidate.use == "RELATIVE_VOLUME"
            and candidate.zone is not None
            and snapshot.policy is not None
            else None
        )
        evidence_current = (
            self._evidence_digests_remain_current(candidate, snapshot.policy)
            if candidate.use == "RELATIVE_VOLUME" and snapshot.policy is not None
            else False
        )
        with self._coordinator.guarded_read():
            current_snapshot = self._pair_still_current(
                candidate.baseline_subject,
                candidate.current_subject,
                candidate.use,
                snapshot,
                now=now,
            )
            if (
                current_snapshot.policy is None
                or current_snapshot.policy.policy_digest != candidate.policy_digest
            ):
                return None
            if candidate.use == "RELATIVE_VOLUME":
                if candidate.zone is None:
                    return None
                if (
                    volume is None
                    or volume.zone != candidate.zone
                    or volume.compatibility_mapping_digest
                    != candidate.compatibility_mapping_digest
                    or not self._relative_volume_authority.is_current_for_use(
                        volume, now=now
                    )
                ):
                    return None
                if not evidence_current:
                    return None
                if not self._candidate_evidence_remains_locally_current(
                    candidate, current_snapshot.policy, current_snapshot
                ):
                    return None
            return candidate

    def get_scoped(
        self, decision_id: str, *, principal: Principal, site_id: str
    ) -> DecisionCandidate | None:
        """Return a scoped historic decision without creating any new authority."""
        return self._decisions.get_scoped(decision_id, principal=principal, site_id=site_id)

    def _single_snapshot(self, subject: SealedExternalSubjectV1, use: str) -> _SingleSnapshot:
        selected = self._policy_registry.select_for_use(use, (subject,))
        policy = selected.policy if selected.status is PolicySelectionStatus.ACTIVE else None
        inspection = self._inspections.public_snapshot(subject)
        _state, receipt = self._inspections.public_display_state(subject)
        return _SingleSnapshot(
            policy=policy,
            inspection=inspection,
            display=receipt,
            revision=self._reconstruction.resolve_sealed_subject(subject),
        )

    def _pair_snapshot(
        self,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        use: str,
    ) -> _PairSnapshot:
        selected = self._policy_registry.select_for_use(use, (baseline, current))
        policy = selected.policy if selected.status is PolicySelectionStatus.ACTIVE else None
        return _PairSnapshot(
            policy=policy,
            baseline=self._single_snapshot_for_pair(baseline),
            current=self._single_snapshot_for_pair(current),
        )

    def _single_snapshot_for_pair(self, subject: SealedExternalSubjectV1) -> _SingleSnapshot:
        inspection = self._inspections.public_snapshot(subject)
        _state, receipt = self._inspections.public_display_state(subject)
        return _SingleSnapshot(
            policy=None,
            inspection=inspection,
            display=receipt,
            revision=self._reconstruction.resolve_sealed_subject(subject),
        )

    def _single_still_current(
        self,
        subject: SealedExternalSubjectV1,
        use: str,
        snapshot: _SingleSnapshot,
        *,
        now: datetime,
    ) -> _SingleSnapshot:
        # ``resolve`` is local retained lifecycle state, deliberately not a
        # second authority-port call while the coordinator is held.
        policy = snapshot.policy
        if policy is not None:
            resolved = self._policy_registry.resolve(policy.policy_digest or "")
            if (
                resolved.status is not PolicySelectionStatus.ACTIVE
                or resolved.policy != policy
                or policy.policy_digest is None
                or not self._policy_registry.locally_current_use_permitted(
                    policy.policy_digest, use=use, subjects=(subject,), at=now
                )
            ):
                policy = None
        revision = self._reconstruction.resolve_sealed_subject(subject)
        inspection = self._inspections.public_snapshot(subject)
        _state, display = self._inspections.public_display_state(subject)
        return _SingleSnapshot(policy, inspection, display, revision)

    def _pair_still_current(
        self,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        use: str,
        snapshot: _PairSnapshot,
        *,
        now: datetime,
    ) -> _PairSnapshot:
        policy = snapshot.policy
        if policy is not None:
            resolved = self._policy_registry.resolve(policy.policy_digest or "")
            if (
                resolved.status is not PolicySelectionStatus.ACTIVE
                or resolved.policy != policy
                or policy.policy_digest is None
                or not self._policy_registry.locally_current_use_permitted(
                    policy.policy_digest, use=use, subjects=(baseline, current), at=now
                )
            ):
                policy = None
        baseline_inspection = self._inspections.public_snapshot(baseline)
        _baseline_state, baseline_display = self._inspections.public_display_state(baseline)
        current_inspection = self._inspections.public_snapshot(current)
        _current_state, current_display = self._inspections.public_display_state(current)
        return _PairSnapshot(
            policy,
            _SingleSnapshot(
                None,
                baseline_inspection,
                baseline_display,
                self._reconstruction.resolve_sealed_subject(baseline),
            ),
            _SingleSnapshot(
                None,
                current_inspection,
                current_display,
                self._reconstruction.resolve_sealed_subject(current),
            ),
        )

    def _single_candidate(
        self,
        subject: SealedExternalSubjectV1,
        use: str,
        snapshot: _SingleSnapshot,
        evaluation_identity: str,
        now: datetime,
    ) -> ExternalUseDecisionV1:
        policy, report = snapshot.policy, snapshot.inspection.report
        reason = self._single_reason(subject, use, snapshot)
        receipt = snapshot.display
        eligible = reason is None and use == "DISPLAY"
        decision_id = self._decision_id(
            {
                "intent": ExternalDecisionIntent(requested_use=use, subject=subject).payload(),
                "policy": policy.policy_digest if policy else None,
                "evaluationIdentity": evaluation_identity,
            }
        )
        return ExternalUseDecisionV1(
            decision_id=decision_id,
            subject=subject,
            subject_digest=subject.canonical_digest(),
            use=cast(Literal["DISPLAY", "HEIGHT"], use),
            policy_digest=policy.policy_digest if eligible and policy else None,
            inspection_report_digest=report.report_digest if eligible and report else None,
            evidence_record_digests=(),
            sanitized_display_receipt_digest=(
                receipt.receipt_digest if eligible and receipt is not None else None
            ),
            verdict=DecisionVerdict.ELIGIBLE if eligible else DecisionVerdict.BLOCKED,
            reasons=("DISPLAY_ELIGIBLE",)
            if eligible
            else (reason or "HEIGHT_PRODUCT_DEFINITION_UNRESOLVED",),
            remediations=("DISPLAY_RECEIPT_RETAINED",)
            if eligible
            else (self._remediation(reason),),
            decided_at=now,
        ).sealed()

    def _pair_candidate(
        self,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        use: str,
        requested_zone_id: str | None,
        snapshot: _PairSnapshot,
        volume: ExternalRelativeVolumeAuthority | None,
        evaluation_identity: str,
        now: datetime,
    ) -> ExternalPairUseDecisionV1:
        reason, evidence_digests = self._pair_reason(baseline, current, use, snapshot, volume)
        eligible = reason is None
        policy = snapshot.policy
        baseline_report = snapshot.baseline.inspection.report
        current_report = snapshot.current.inspection.report
        decision_id = self._decision_id(
            {
                "intent": ExternalDecisionIntent(
                    requested_use=use,
                    baseline_subject=baseline,
                    current_subject=current,
                    requested_zone_id=requested_zone_id,
                ).payload(),
                "policy": policy.policy_digest if policy else None,
                "zone": volume.zone.model_dump(by_alias=True, mode="json") if volume else None,
                "compatibilityMapping": volume.compatibility_mapping_digest if volume else None,
                "evaluationIdentity": evaluation_identity,
            }
        )
        return ExternalPairUseDecisionV1(
            decision_id=decision_id,
            baseline_subject=baseline,
            baseline_subject_digest=baseline.canonical_digest(),
            current_subject=current,
            current_subject_digest=current.canonical_digest(),
            use=cast(Literal["VISUAL_COMPARISON", "RELATIVE_VOLUME"], use),
            policy_digest=policy.policy_digest if eligible and policy else None,
            baseline_inspection_report_digest=(
                baseline_report.report_digest if eligible and baseline_report else None
            ),
            current_inspection_report_digest=(
                current_report.report_digest if eligible and current_report else None
            ),
            baseline_sanitized_display_receipt_digest=(
                snapshot.baseline.display.receipt_digest
                if eligible and use == "VISUAL_COMPARISON" and snapshot.baseline.display
                else None
            ),
            current_sanitized_display_receipt_digest=(
                snapshot.current.display.receipt_digest
                if eligible and use == "VISUAL_COMPARISON" and snapshot.current.display
                else None
            ),
            evidence_record_digests=evidence_digests if eligible else (),
            zone=volume.zone if eligible and use == "RELATIVE_VOLUME" and volume else None,
            compatibility_mapping_digest=(
                volume.compatibility_mapping_digest
                if eligible and use == "RELATIVE_VOLUME" and volume
                else None
            ),
            verdict=DecisionVerdict.ELIGIBLE if eligible else DecisionVerdict.BLOCKED,
            reasons=("USE_ELIGIBLE",) if eligible else (reason or "POLICY_UNAVAILABLE",),
            remediations=("CURRENT_DEPENDENCIES_RETAINED",)
            if eligible
            else (self._remediation(reason),),
            decided_at=now,
        ).sealed()

    def _single_reason(
        self,
        subject: SealedExternalSubjectV1,
        use: str,
        snapshot: _SingleSnapshot,
    ) -> str | None:
        if use == "HEIGHT":
            return "HEIGHT_PRODUCT_DEFINITION_UNRESOLVED"
        if snapshot.revision is None:
            return "SUBJECT_NOT_SEALED"
        if snapshot.policy is None:
            return "POLICY_UNAVAILABLE"
        report = snapshot.inspection.report
        if not self._report_binds(subject, report, snapshot.policy):
            return "INSPECTION_REPORT_BINDING_INVALID"
        if not self._measured_kind(snapshot.revision, report, ProcessingArtifactKind.ORTHO):
            return "ORTHO_MEASUREMENT_UNAVAILABLE"
        receipt = snapshot.display
        if not self._receipt_binds(receipt, subject, report, snapshot.policy):
            return "DISPLAY_RECEIPT_BINDING_INVALID"
        return None

    def _pair_reason(
        self,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        use: str,
        snapshot: _PairSnapshot,
        volume: ExternalRelativeVolumeAuthority | None,
    ) -> tuple[str | None, tuple[str, ...]]:
        if baseline.canonical_digest() == current.canonical_digest():
            return "PAIR_SUBJECTS_NOT_DISTINCT", ()
        if snapshot.policy is None:
            return "POLICY_UNAVAILABLE", ()
        for subject, item in ((baseline, snapshot.baseline), (current, snapshot.current)):
            if item.revision is None:
                return "SUBJECT_NOT_SEALED", ()
            if not self._report_binds(subject, item.inspection.report, snapshot.policy):
                return "INSPECTION_REPORT_BINDING_INVALID", ()
        if use == "VISUAL_COMPARISON":
            for subject, item in ((baseline, snapshot.baseline), (current, snapshot.current)):
                if not self._receipt_binds(
                    item.display, subject, item.inspection.report, snapshot.policy
                ):
                    return "DISPLAY_RECEIPT_BINDING_INVALID", ()
            return None, ()
        if volume is None:
            return "VOLUME_AUTHORITY_UNAVAILABLE", ()
        if volume.zone.zone_id == "" or volume.zone.revision != 1:
            return "VOLUME_ZONE_BINDING_INVALID", ()
        evidence: list[str] = []
        for subject, item in ((baseline, snapshot.baseline), (current, snapshot.current)):
            report = item.inspection.report
            assert report is not None
            # One currently validated record for the precise measured DSM is
            # required per ordered epoch.  This port does not accept display
            # receipts or arbitrary digest lists as substitutes.
            matching = self._validated_evidence_for(subject, snapshot.policy, report)
            if matching is None:
                return "EVIDENCE_RECORD_BINDING_INVALID", ()
            evidence.append(matching)
        return None, tuple(evidence)

    def _validated_evidence_for(
        self,
        subject: SealedExternalSubjectV1,
        policy: ExternalValidationPolicyV1,
        report: ExternalArtifactInspectionReportV1,
        *,
        locally_current: bool = True,
    ) -> str | None:
        # The evidence store intentionally exposes only exact digest lookup.
        # Querying its private projection would turn a broad list into authority.
        for digest in self._evidence_validations.validated_record_digests_for(
            subject=subject, policy_digest=policy.policy_digest or ""
        ):
            if locally_current:
                resolved = self._evidence_validations.record_for_locally_current_use(
                    digest, subject=subject, policy_digest=policy.policy_digest or ""
                )
            else:
                resolved = self._evidence_validations.record_for_current_use(
                    digest, subject=subject, policy_digest=policy.policy_digest or ""
                )
            if resolved is None:
                continue
            record, context = resolved
            if (
                context.independent_attestation is not None
                and self._report_measures_dsm(
                    report, context.target_dsm_artifact_id, context.target_dsm_observed_sha256
                )
                and record.evidence_record_digest == digest
            ):
                return digest
        return None

    def _evidence_digests_remain_current(
        self, candidate: ExternalPairUseDecisionV1, policy: ExternalValidationPolicyV1
    ) -> bool:
        """Retained evidence is usable only while exact current authority remains."""
        if len(candidate.evidence_record_digests) != 2:
            return False
        return all(
            self._evidence_validations.record_for_current_use(
                digest, subject=subject, policy_digest=policy.policy_digest or ""
            )
            is not None
            for digest, subject in zip(
                candidate.evidence_record_digests,
                (candidate.baseline_subject, candidate.current_subject),
                strict=True,
            )
        )

    def _pair_evidence_remains_current(
        self,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        snapshot: _PairSnapshot,
    ) -> bool:
        """Resolve evidence authority before the final local-currentness guard."""
        policy = snapshot.policy
        if policy is None:
            return False
        for subject, item in ((baseline, snapshot.baseline), (current, snapshot.current)):
            report = item.inspection.report
            if report is None or self._validated_evidence_for(
                subject, policy, report, locally_current=False
            ) is None:
                return False
        return True

    def _candidate_evidence_remains_locally_current(
        self,
        candidate: ExternalPairUseDecisionV1,
        policy: ExternalValidationPolicyV1,
        snapshot: _PairSnapshot,
    ) -> bool:
        """Recheck exact retained evidence without an authority callback under the guard."""
        if len(candidate.evidence_record_digests) != 2:
            return False
        for digest, subject, item, report_digest in zip(
            candidate.evidence_record_digests,
            (candidate.baseline_subject, candidate.current_subject),
            (snapshot.baseline, snapshot.current),
            (
                candidate.baseline_inspection_report_digest,
                candidate.current_inspection_report_digest,
            ),
            strict=True,
        ):
            report = item.inspection.report
            if report is None or report_digest != report.report_digest:
                return False
            resolved = self._evidence_validations.record_for_locally_current_use(
                digest, subject=subject, policy_digest=policy.policy_digest or ""
            )
            if resolved is None:
                return False
            record, context = resolved
            if (
                context.independent_attestation is None
                or record.evidence_record_digest != digest
                or not self._report_measures_dsm(
                    report, context.target_dsm_artifact_id, context.target_dsm_observed_sha256
                )
            ):
                return False
        return True

    @staticmethod
    def _report_binds(
        subject: SealedExternalSubjectV1,
        report: ExternalArtifactInspectionReportV1 | None,
        policy: ExternalValidationPolicyV1,
    ) -> bool:
        return bool(
            report
            and report.report_digest
            and report.subject == subject
            and report.subject_digest == subject.canonical_digest()
            and report.inspection_policy_digest == policy.policy_digest
        )

    @staticmethod
    def _receipt_binds(
        receipt: SanitizedDisplayReceiptV1 | None,
        subject: SealedExternalSubjectV1,
        report: ExternalArtifactInspectionReportV1 | None,
        policy: ExternalValidationPolicyV1,
    ) -> bool:
        return bool(
            receipt
            and receipt.receipt_digest
            and report
            and report.report_digest
            and receipt.source_subject_digest == subject.canonical_digest()
            and receipt.source_report_digest == report.report_digest
            and receipt.policy_digest == policy.policy_digest
        )

    @staticmethod
    def _measured_kind(
        revision: ExternalReconstructionRevision,
        report: ExternalArtifactInspectionReportV1 | None,
        kind: ProcessingArtifactKind,
    ) -> bool:
        if report is None or revision.manifest is None:
            return False
        required = {
            entry.artifact_id: "sha256:" + entry.observed_sha256
            for entry in revision.manifest.entries
            if entry.kind is kind
        }
        return any(
            outcome.outcome is ArtifactOutcome.MEASURED
            and required.get(outcome.artifact_id) == outcome.observed_sha256
            for outcome in report.measurement_payload.outcomes
        )

    @staticmethod
    def _report_measures_dsm(
        report: ExternalArtifactInspectionReportV1,
        artifact_id: str,
        observed_sha256: str,
    ) -> bool:
        return any(
            outcome.artifact_id == artifact_id
            and outcome.observed_sha256 == observed_sha256
            and outcome.outcome is ArtifactOutcome.MEASURED
            for outcome in report.measurement_payload.outcomes
        )

    def _record(
        self,
        candidate: DecisionCandidate,
        intent: ExternalDecisionIntent,
        principal: Principal,
        idempotency_key: str,
    ) -> DecisionCandidate:
        existing = self._decisions.existing_for_intent(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        if existing is not None:
            self._decisions.reconcile_pending()
            return existing
        self._decisions.stage_evaluated(
            candidate,
            intent=intent,
            principal=principal,
            idempotency_key=idempotency_key,
        )
        self._decisions.reconcile_pending()
        return candidate

    @staticmethod
    def _decision_id(value: Mapping[str, Any]) -> str:
        return "external-use-decision-" + _digest(value).removeprefix("sha256:")[:32]

    @staticmethod
    def _remediation(reason: str | None) -> str:
        if reason is None:
            return "RESOLVE_EXTERNAL_USE_BLOCKER"
        return {
            "HEIGHT_PRODUCT_DEFINITION_UNRESOLVED": "DEFINE_HEIGHT_PRODUCT",
            "SUBJECT_NOT_SEALED": "SEAL_EXTERNAL_RECONSTRUCTION",
            "POLICY_UNAVAILABLE": "AUTHORIZE_POLICY",
            "INSPECTION_REPORT_BINDING_INVALID": "COMPLETE_CURRENT_INSPECTION",
            "ORTHO_MEASUREMENT_UNAVAILABLE": "MEASURE_DECLARED_ORTHO",
            "DISPLAY_RECEIPT_BINDING_INVALID": "SEAL_SANITIZED_DISPLAY",
            "VOLUME_AUTHORITY_UNAVAILABLE": "AUTHORIZE_VOLUME_ZONE_AND_MAPPING",
            "COMPATIBILITY_MAPPING_MISSING": "AUTHORIZE_COMPATIBILITY_MAPPING",
            "VOLUME_ZONE_BINDING_INVALID": "SELECT_ACTIVE_VOLUME_ZONE",
            "EVIDENCE_RECORD_BINDING_INVALID": "VALIDATE_INDEPENDENT_EVIDENCE",
            "PAIR_SUBJECTS_NOT_DISTINCT": "SELECT_DISTINCT_EPOCHS",
        }.get(reason, "RESOLVE_EXTERNAL_USE_BLOCKER")

    @staticmethod
    def _require_scope(principal: Principal, subject: SealedExternalSubjectV1) -> None:
        if principal.organization_id != subject.organization_id:
            raise ValueError("principal organization does not match external subject")

    @classmethod
    def _require_pair_scope(
        cls,
        principal: Principal,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
    ) -> None:
        cls._require_scope(principal, baseline)
        cls._require_scope(principal, current)
        if (
            baseline.organization_id != current.organization_id
            or baseline.site_id != current.site_id
        ):
            raise ValueError("external pair must share organization and site")


def _sealed_subject_from_revision(
    revision: ExternalReconstructionRevision,
) -> SealedExternalSubjectV1 | None:
    submission, manifest = revision.submission, revision.manifest
    if submission.submission_digest is None or manifest is None or manifest.manifest_digest is None:
        return None
    return SealedExternalSubjectV1(
        organization_id=submission.organization_id,
        site_id=submission.site_id,
        work_order_id=revision.work_order_id,
        submission_id=submission.submission_id,
        revision=submission.revision,
        submission_digest=submission.submission_digest,
        manifest_digest=manifest.manifest_digest,
    )


def mount_external_use_evaluator(
    app: FastAPI,
    evaluator: ExternalUseEvaluator,
    *,
    reconstruction: ExternalReconstructionStore,
    work_orders: Any,
) -> None:
    """Mount human selection routes with no client authority fields."""
    router = APIRouter(prefix="/v1/observation-work-orders", tags=["external-use-decisions"])
    from ksi_core.identity.auth import Permission, PrincipalKind, require_permission

    read = require_permission(Permission.SITES_READ)
    write = require_permission(Permission.SITES_WRITE)
    base = (
        "/{work_order_id}/external-reconstruction-submissions/{submission_ref}"
        "/revisions/{revision}/use-decisions"
    )

    def idempotency_header(
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=1, max_length=255, pattern=r".*\S.*"
        ),
    ) -> str:
        return idempotency_key.strip()

    def revision_for(
        work_order_id: str, submission_ref: str, revision: int, principal: Principal
    ) -> ExternalReconstructionRevision:
        order = work_orders.get(work_order_id, organization_id=principal.organization_id)
        if order is None:
            raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
        submission_id = reconstruction.resolve_submission_ref(
            work_order_id,
            submission_ref,
            organization_id=principal.organization_id,
            site_id=order.site_id,
        )
        record = (
            reconstruction.get(
                work_order_id,
                submission_id,
                revision,
                organization_id=principal.organization_id,
                site_id=order.site_id,
            )
            if submission_id is not None
            else None
        )
        if record is None:
            raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
        return record

    def subject_for(
        work_order_id: str, submission_ref: str, revision: int, principal: Principal
    ) -> SealedExternalSubjectV1:
        subject = _sealed_subject_from_revision(
            revision_for(work_order_id, submission_ref, revision, principal)
        )
        if subject is None:
            raise HTTPException(409, "EXTERNAL_RECONSTRUCTION_NOT_SEALED")
        return subject

    def human(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(403, "HUMAN_AUTHORITY_REQUIRED")

    def write_result(candidate: DecisionCandidate) -> ExternalUseDecisionResponse:
        return ExternalUseDecisionResponse(
            decision=candidate.model_dump(by_alias=True, mode="json")
        )

    @router.post(base + "/single", response_model=ExternalUseDecisionResponse, status_code=201)
    def request_single(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        request: ExternalSingleUseDecisionRequest,
        idempotency_key: str = Depends(idempotency_header),  # noqa: B008
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalUseDecisionResponse:
        human(principal)
        subject = subject_for(work_order_id, submission_ref, revision, principal)
        try:
            with work_orders.guard_new_external_intent(
                work_order_id,
                organization_id=principal.organization_id,
                is_durable_retry=lambda: evaluator.existing_single_retry(
                    subject,
                    use=request.use,
                    principal=principal,
                    idempotency_key=idempotency_key,
                )
                is not None,
            ):
                return write_result(
                    evaluator.request_single(
                        subject,
                        use=request.use,
                        idempotency_key=idempotency_key,
                        principal=principal,
                        now=datetime.now(UTC),
                    )
                )
        except ExternalUseDecisionConflictError as exc:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT") from exc
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(409, str(exc)) from exc
            raise

    @router.post(base + "/pair", response_model=ExternalUseDecisionResponse, status_code=201)
    def request_pair(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        request: ExternalPairUseDecisionRequest,
        idempotency_key: str = Depends(idempotency_header),  # noqa: B008
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalUseDecisionResponse:
        human(principal)
        current = subject_for(work_order_id, submission_ref, revision, principal)
        baseline = subject_for(
            request.baseline_work_order_id,
            request.baseline_submission_ref,
            request.baseline_revision,
            principal,
        )
        try:
            with work_orders.guard_new_external_intent(
                work_order_id,
                organization_id=principal.organization_id,
                is_durable_retry=lambda: evaluator.existing_pair_retry(
                    baseline,
                    current,
                    use=request.use,
                    zone_id=request.zone_id,
                    principal=principal,
                    idempotency_key=idempotency_key,
                )
                is not None,
            ):
                return write_result(
                    evaluator.request_pair(
                        baseline,
                        current,
                        use=request.use,
                        zone_id=request.zone_id,
                        idempotency_key=idempotency_key,
                        principal=principal,
                        now=datetime.now(UTC),
                    )
                )
        except ExternalUseDecisionConflictError as exc:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT") from exc
        except ValueError as exc:
            raise HTTPException(422, "EXTERNAL_USE_SELECTION_INVALID") from exc
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(409, str(exc)) from exc
            raise

    @router.get(base + "/{decision_id}", response_model=ExternalUseDecisionResponse)
    def get_decision(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        decision_id: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> ExternalUseDecisionResponse:
        human(principal)
        subject = subject_for(work_order_id, submission_ref, revision, principal)
        candidate = evaluator.get_scoped(decision_id, principal=principal, site_id=subject.site_id)
        if candidate is None:
            raise HTTPException(404, "EXTERNAL_USE_DECISION_NOT_FOUND")
        if isinstance(candidate, ExternalUseDecisionV1):
            if candidate.subject != subject:
                raise HTTPException(404, "EXTERNAL_USE_DECISION_NOT_FOUND")
        elif candidate.current_subject != subject:
            raise HTTPException(404, "EXTERNAL_USE_DECISION_NOT_FOUND")
        return write_result(candidate)

    app.include_router(router)


__all__ = [
    "CoreExternalUseDecisionHistoryVerifier",
    "ExternalRelativeVolumeAuthority",
    "ExternalRelativeVolumeAuthorityPort",
    "ExternalUseEvaluator",
    "mount_external_use_evaluator",
]
