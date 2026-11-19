"""Core-resolved, current per-use decisions for sealed external artifacts.

The request surface contains only a requested use and a caller selection.  This
module resolves every policy, report, receipt, evidence record, and volume-zone
authority reference itself.  It never accepts a caller-provided digest, worker
observation, verdict, storage key, or numeric result.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    DecisionVerdict,
    ExternalArtifactInspectionReportV1,
    ExternalPairUseDecisionV1,
    ExternalUseDecisionV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_display_artifact import SanitizedDisplayReceiptV1
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeDecisionV1
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
from ksi_core.domains.external.ingress.spatial_asset_catalog import asset_ref_for_subject
from ksi_core.domains.external.quantity.external_profile_difference_authorities import (
    DefaultClosedExternalProfileDifferenceAuthorityPort,
    ExternalProfileDifferenceAuthority,
    ExternalProfileDifferenceAuthorityPort,
)
from ksi_core.domains.external.quantity.external_relative_volume_authorities import (
    DefaultClosedExternalRelativeVolumeAuthorityPort,
    ExternalRelativeVolumeAuthority,
    ExternalRelativeVolumeAuthorityPort,
)
from ksi_core.domains.external.quantity.external_single_volume_authorities import (
    DefaultClosedExternalSingleVolumeAuthorityPort,
    ExternalSingleVolumeAuthority,
    ExternalSingleVolumeAuthorityPort,
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


class DeclaredVerticalReferencePort(Protocol):
    """사용자가 선언한 DSM 수직 기준. 선언은 주장이며, 읽기(HEIGHT)만 이것을 근거로 삼는다.

    비교·체적·준비도는 이 포트를 받지 않는다. 파일에서 관측한 수직 기준이 있으면 포트는 묻지 않는다.
    """

    def active_declaration(
        self, *, organization_id: str, site_id: str, asset_ref: str, at: datetime | None = None
    ) -> object | None: ...


def declared_vertical_checker(
    port: DeclaredVerticalReferencePort | None,
    subject: SealedExternalSubjectV1,
    *,
    at: datetime | None = None,
) -> Callable[[str], bool] | None:
    """DSM 산출물 id → 그 시점에 유효한 선언이 있는가. 포트가 없으면 선언을 쓰지 않는다."""
    if port is None:
        return None

    def declared(artifact_id: str) -> bool:
        return (
            port.active_declaration(
                organization_id=subject.organization_id,
                site_id=subject.site_id,
                asset_ref=asset_ref_for_subject(subject, artifact_id),
                at=at,
            )
            is not None
        )

    return declared


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
        profile_difference_authority: ExternalProfileDifferenceAuthorityPort | None = None,
        single_volume_authority: ExternalSingleVolumeAuthorityPort | None = None,
        declared_vertical: DeclaredVerticalReferencePort | None = None,
    ) -> None:
        self._reconstruction = reconstruction
        self._inspections = inspections
        self._policy_registry = policy_registry
        self._evidence_validations = evidence_validations
        self._relative_volume_authority = relative_volume_authority
        self._profile_difference_authority = profile_difference_authority
        self._single_volume_authority = single_volume_authority
        self._declared_vertical = declared_vertical

    def verify(self, candidate: DecisionCandidate) -> bool:
        if isinstance(candidate, ExternalUseDecisionV1):
            return self._verify_single(candidate)
        if isinstance(candidate, ExternalSingleVolumeDecisionV1):
            return self._verify_single_volume(candidate)
        return self._verify_pair(candidate)

    def _verify_single_volume(self, candidate: ExternalSingleVolumeDecisionV1) -> bool:
        policy_digest = candidate.policy_digest
        report_digest = candidate.inspection_report_digest
        if (
            policy_digest is None
            or report_digest is None
            or self._single_volume_authority is None
            or not self._policy_registry.historical_use_permitted(
                policy_digest,
                use="SINGLE_VOLUME",
                subjects=(candidate.subject,),
                at=candidate.decided_at,
            )
        ):
            return False
        policy = self._policy_registry.resolve(policy_digest).policy
        report = self._inspections.historical_report(
            candidate.subject, report_digest=report_digest, policy_digest=policy_digest
        )
        if (
            policy is None
            or report is None
            or self._reconstruction.resolve_sealed_subject(candidate.subject) is None
            or not ExternalUseEvaluator._report_binds(candidate.subject, report, policy)
        ):
            return False
        authority = self._single_volume_authority.resolve_historical_for_decision(candidate)
        if (
            authority is None
            or candidate.compatibility_mapping_digest != authority.compatibility_mapping_digest
            or candidate.zone != authority.zone
            or len(candidate.evidence_record_digests) != 1
        ):
            return False
        evidence = self._evidence_validations.record_for_use(
            candidate.evidence_record_digests[0],
            subject=candidate.subject,
            policy_digest=policy_digest,
        )
        if evidence is None:
            return False
        _record, context = evidence
        return (
            context.independent_attestation is not None
            and ExternalUseEvaluator._report_measures_dsm(
                report, context.target_dsm_artifact_id, context.target_dsm_observed_sha256
            )
        )

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
        if revision is None or not ExternalUseEvaluator._report_binds(
            candidate.subject, report, policy
        ):
            return False
        if candidate.use == "HEIGHT":
            # A height read binds the measured DSM's own facts and never a display receipt.
            return (
                candidate.sanitized_display_receipt_digest is None
                and ExternalUseEvaluator._height_blocker(
                    revision,
                    report,
                    declared=declared_vertical_checker(
                        self._declared_vertical, candidate.subject, at=candidate.decided_at
                    ),
                )
                is None
            )
        if (
            not ExternalUseEvaluator._measured_kind(revision, report, ProcessingArtifactKind.ORTHO)
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
            if self._reconstruction.resolve_sealed_subject(
                subject
            ) is None or not ExternalUseEvaluator._report_binds(subject, report, policy):
                return False
            assert report is not None
            resolved_reports.append((subject, report))
        if candidate.use == "VISUAL_COMPARISON":
            receipts = (
                candidate.baseline_sanitized_display_receipt_digest,
                candidate.current_sanitized_display_receipt_digest,
            )
            return (
                all(
                    receipt is not None
                    and self._inspections.historical_display_receipt(
                        subject,
                        report_digest=report.report_digest or "",
                        receipt_digest=receipt,
                        policy_digest=policy_digest,
                    )
                    is not None
                    for (subject, report), receipt in zip(resolved_reports, receipts, strict=True)
                )
                and not candidate.evidence_record_digests
            )
        if candidate.use == "PROFILE_DIFFERENCE":
            if self._profile_difference_authority is None:
                return False
            profile_authority = self._profile_difference_authority.resolve_historical_for_decision(
                candidate
            )
            if (
                profile_authority is None
                or candidate.zone is not None
                or candidate.compatibility_mapping_digest
                != profile_authority.compatibility_mapping_digest
                or not profile_authority.authorized_by(policy)
                or candidate.profile_work_area_id != profile_authority.work_area_id
                or (
                    profile_authority.evidence_record_digests
                    and candidate.evidence_record_digests
                    != profile_authority.evidence_record_digests
                )
                or len(candidate.evidence_record_digests) != 2
            ):
                return False
            return self._verify_profile_difference_pair(
                candidate, resolved_reports, policy, profile_authority
            )
        if candidate.use != "RELATIVE_VOLUME" or self._relative_volume_authority is None:
            return False
        volume_authority = self._relative_volume_authority.resolve_historical_for_decision(
            candidate
        )
        if (
            volume_authority is None
            or candidate.compatibility_mapping_digest
            != volume_authority.compatibility_mapping_digest
            or candidate.zone != volume_authority.zone
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

    def _verify_profile_difference_pair(
        self,
        candidate: ExternalPairUseDecisionV1,
        resolved_reports: list[tuple[SealedExternalSubjectV1, ExternalArtifactInspectionReportV1]],
        policy: ExternalValidationPolicyV1,
        authority: ExternalProfileDifferenceAuthority,
    ) -> bool:
        if (
            candidate.baseline_artifact_id is None
            or candidate.baseline_source_sha256 is None
            or candidate.current_artifact_id is None
            or candidate.current_source_sha256 is None
        ):
            return False
        revisions = tuple(
            self._reconstruction.resolve_sealed_subject(subject)
            for subject, _report in resolved_reports
        )
        if any(revision is None for revision in revisions):
            return False
        baseline_revision, current_revision = revisions
        baseline_report, current_report = resolved_reports[0][1], resolved_reports[1][1]
        profile_snapshot = _PairSnapshot(
            policy=policy,
            baseline=_SingleSnapshot(
                policy=policy,
                inspection=PublicInspectionSnapshot("READY", None, None, baseline_report),
                display=None,
                revision=baseline_revision,
            ),
            current=_SingleSnapshot(
                policy=policy,
                inspection=PublicInspectionSnapshot("READY", None, None, current_report),
                display=None,
                revision=current_revision,
            ),
        )
        reason, facts = ExternalUseEvaluator._profile_difference_facts(
            profile_snapshot,
            baseline_artifact_id=candidate.baseline_artifact_id,
            baseline_source_sha256=candidate.baseline_source_sha256,
            current_artifact_id=candidate.current_artifact_id,
            current_source_sha256=candidate.current_source_sha256,
            expected_crs_digest=authority.observed_crs_digest,
            expected_vertical_reference_digest=authority.observed_vertical_reference_digest,
            work_area_id=candidate.profile_work_area_id,
        )
        if reason is not None or facts is None:
            return False
        if not ExternalUseEvaluator._profile_authority_binds(
            authority,
            baseline=candidate.baseline_subject,
            current=candidate.current_subject,
            policy=policy,
            facts=facts,
        ):
            return False
        for evidence_digest, (subject, report), artifact_id, source_sha256 in zip(
            candidate.evidence_record_digests,
            resolved_reports,
            (facts.baseline_artifact_id, facts.current_artifact_id),
            (facts.baseline_source_sha256, facts.current_source_sha256),
            strict=True,
        ):
            resolved_evidence = self._evidence_validations.record_for_use(
                evidence_digest, subject=subject, policy_digest=policy.policy_digest or ""
            )
            if resolved_evidence is None:
                return False
            record, context = resolved_evidence
            if (
                record.evidence_record_digest != evidence_digest
                or context.independent_attestation is None
                or context.target_dsm_artifact_id != artifact_id
                or context.target_dsm_observed_sha256 != source_sha256
                or not ExternalUseEvaluator._report_measures_dsm(report, artifact_id, source_sha256)
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


@dataclass(frozen=True, slots=True)
class _ProfileCaptureIntervals:
    baseline_started_at: datetime
    baseline_ended_at: datetime
    current_started_at: datetime
    current_ended_at: datetime


@dataclass(frozen=True, slots=True)
class _ProfileDifferenceFacts:
    work_area_id: str | None
    baseline_report_digest: str
    current_report_digest: str
    baseline_artifact_id: str
    baseline_source_sha256: str
    current_artifact_id: str
    current_source_sha256: str
    observed_crs_digest: str
    observed_vertical_reference_digest: str
    capture: _ProfileCaptureIntervals

    def matches_reports(self, snapshot: _PairSnapshot) -> bool:
        before, after = snapshot.baseline.inspection.report, snapshot.current.inspection.report
        return (
            before is not None
            and before.report_digest == self.baseline_report_digest
            and after is not None
            and after.report_digest == self.current_report_digest
        )


class ExternalSingleUseDecisionRequest(CamelModel):
    use: Literal["DISPLAY", "HEIGHT"]


class ExternalPairUseDecisionRequest(CamelModel):
    use: Literal["VISUAL_COMPARISON", "RELATIVE_VOLUME"]
    baseline_work_order_id: str = Field(min_length=1, max_length=255)
    baseline_submission_ref: str = Field(pattern=r"^ers-v1-[0-9a-f]{64}$")
    baseline_revision: int = Field(ge=1)
    zone_id: str | None = Field(default=None, min_length=1, max_length=255)


class ExternalSingleVolumeDecisionRequest(CamelModel):
    zone_id: str = Field(min_length=1, max_length=255)


class ExternalUseDecisionResponse(CamelModel):
    decision: dict[str, Any]


# Reason -> remediation for single and pair use decisions. The catalog under
# ``contracts/catalogs/external-use-blockers.v1.json`` must explain every code
# here (contract test ``test_external_use_blockers.py``).
PAIR_REASON_REMEDIATIONS: dict[str, str] = {
    "HEIGHT_PRODUCT_DEFINITION_UNRESOLVED": "DEFINE_HEIGHT_PRODUCT",
    "DSM_MEASUREMENT_UNAVAILABLE": "MEASURE_DECLARED_DSM",
    "VERTICAL_REFERENCE_UNKNOWN": "OBSERVE_VERTICAL_REFERENCE",
    "SUBJECT_NOT_SEALED": "SEAL_EXTERNAL_RECONSTRUCTION",
    "POLICY_UNAVAILABLE": "AUTHORIZE_POLICY",
    "INSPECTION_REPORT_BINDING_INVALID": "COMPLETE_CURRENT_INSPECTION",
    "ORTHO_MEASUREMENT_UNAVAILABLE": "MEASURE_DECLARED_ORTHO",
    "DISPLAY_RECEIPT_BINDING_INVALID": "SEAL_SANITIZED_DISPLAY",
    "VOLUME_AUTHORITY_UNAVAILABLE": "AUTHORIZE_VOLUME_ZONE_AND_MAPPING",
    "COMPATIBILITY_MAPPING_MISSING": "AUTHORIZE_COMPATIBILITY_MAPPING",
    "VOLUME_ZONE_BINDING_INVALID": "SELECT_ACTIVE_VOLUME_ZONE",
    "EVIDENCE_RECORD_BINDING_INVALID": "VALIDATE_INDEPENDENT_EVIDENCE",
    "EVIDENCE_INDEPENDENCE_UNATTESTED": "ATTEST_INDEPENDENT_EVIDENCE",
    "PAIR_SUBJECTS_NOT_DISTINCT": "SELECT_DISTINCT_EPOCHS",
    "SINGLE_VOLUME_MAPPING_UNAVAILABLE": "AUTHORIZE_SINGLE_VOLUME_MAPPING",
    "PROFILE_DIFFERENCE_CRS_MISMATCH": "SELECT_MATCHING_OBSERVED_CRS",
    "PROFILE_DIFFERENCE_VERTICAL_REFERENCE_MISMATCH": "SELECT_MATCHING_OBSERVED_VERTICAL_REFERENCE",
    "PROFILE_DIFFERENCE_RECEIPT_REFERENCE_MISMATCH": (
        "REGENERATE_PROFILE_RECEIPTS_FROM_OBSERVED_REFERENCES"
    ),
    "PROFILE_DIFFERENCE_CAPTURE_ORDER_INVALID": "SELECT_STRICTLY_ORDERED_CAPTURE_EPOCHS",
}


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
        profile_difference_authority: ExternalProfileDifferenceAuthorityPort | None = None,
        single_volume_authority: ExternalSingleVolumeAuthorityPort | None = None,
        declared_vertical: DeclaredVerticalReferencePort | None = None,
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
        if (
            profile_difference_authority is not None
            and profile_difference_authority.currentness_coordinator is not coordinator
        ):
            raise ValueError("profile-difference authority must share currentness coordinator")
        if (
            single_volume_authority is not None
            and single_volume_authority.currentness_coordinator is not coordinator
        ):
            raise ValueError("single-volume authority must share currentness coordinator")
        self._decisions = decisions
        self._reconstruction = reconstruction
        self._inspections = inspections
        self._policy_registry = policy_registry
        self._evidence_validations = evidence_validations
        self._coordinator = coordinator
        self._declared_vertical = declared_vertical
        self._relative_volume_authority = relative_volume_authority or (
            DefaultClosedExternalRelativeVolumeAuthorityPort(currentness_coordinator=coordinator)
        )
        self._profile_difference_authority = profile_difference_authority or (
            DefaultClosedExternalProfileDifferenceAuthorityPort(currentness_coordinator=coordinator)
        )
        self._single_volume_authority: ExternalSingleVolumeAuthorityPort = (
            single_volume_authority
            or DefaultClosedExternalSingleVolumeAuthorityPort(currentness_coordinator=coordinator)
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

    def has_declared_vertical(self, subject: SealedExternalSubjectV1, artifact_id: str) -> bool:
        """Does this DSM artifact have a current user declaration?  False without a ledger."""
        checker = declared_vertical_checker(self._declared_vertical, subject)
        return checker is not None and checker(artifact_id)

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
        observed_crs_digest: str | None = None,
        observed_vertical_reference_digest: str | None = None,
        baseline_artifact_id: str | None = None,
        baseline_source_sha256: str | None = None,
        current_artifact_id: str | None = None,
        current_source_sha256: str | None = None,
        profile_comparison_binding_digest: str | None = None,
        profile_work_area_id: str | None = None,
    ) -> ExternalPairUseDecisionV1:
        self._require_pair_scope(principal, baseline, current)
        if use not in {"VISUAL_COMPARISON", "RELATIVE_VOLUME", "PROFILE_DIFFERENCE"}:
            raise ValueError("pair external use is invalid")
        if use == "VISUAL_COMPARISON" and zone_id is not None:
            raise ValueError("visual comparison cannot select a volume zone")
        if use == "PROFILE_DIFFERENCE" and zone_id is not None:
            raise ValueError("profile difference is zone-free")
        if use == "PROFILE_DIFFERENCE" and not all(
            (
                baseline_artifact_id,
                baseline_source_sha256,
                current_artifact_id,
                current_source_sha256,
                profile_comparison_binding_digest,
            )
        ):
            raise ValueError("profile difference requires exact DSM and profile-pair identities")
        if use == "RELATIVE_VOLUME" and not zone_id:
            raise ValueError("relative volume requires a zone selection")
        intent = ExternalDecisionIntent(
            requested_use=use,
            baseline_subject=baseline,
            current_subject=current,
            requested_zone_id=zone_id,
            baseline_artifact_id=baseline_artifact_id if use == "PROFILE_DIFFERENCE" else None,
            baseline_source_sha256=baseline_source_sha256 if use == "PROFILE_DIFFERENCE" else None,
            current_artifact_id=current_artifact_id if use == "PROFILE_DIFFERENCE" else None,
            current_source_sha256=current_source_sha256 if use == "PROFILE_DIFFERENCE" else None,
            profile_comparison_binding_digest=(
                profile_comparison_binding_digest if use == "PROFILE_DIFFERENCE" else None
            ),
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
        profile_reason: str | None = None
        profile_facts: _ProfileDifferenceFacts | None = None
        if use == "PROFILE_DIFFERENCE":
            profile_reason, profile_facts = self._profile_difference_facts(
                snapshot,
                work_area_id=profile_work_area_id,
                baseline_artifact_id=baseline_artifact_id,
                baseline_source_sha256=baseline_source_sha256,
                current_artifact_id=current_artifact_id,
                current_source_sha256=current_source_sha256,
                expected_crs_digest=observed_crs_digest,
                expected_vertical_reference_digest=observed_vertical_reference_digest,
            )
        profile_authority = None
        if use == "PROFILE_DIFFERENCE" and profile_facts is not None and snapshot.policy:
            profile_authority = self._profile_difference_authority.resolve_for_use(
                baseline=baseline,
                current=current,
                work_area_id=profile_work_area_id,
                baseline_artifact_id=profile_facts.baseline_artifact_id,
                baseline_source_sha256=profile_facts.baseline_source_sha256,
                current_artifact_id=profile_facts.current_artifact_id,
                current_source_sha256=profile_facts.current_source_sha256,
                policy=snapshot.policy,
                baseline_capture_started_at=profile_facts.capture.baseline_started_at,
                baseline_capture_ended_at=profile_facts.capture.baseline_ended_at,
                current_capture_started_at=profile_facts.capture.current_started_at,
                current_capture_ended_at=profile_facts.capture.current_ended_at,
                observed_crs_digest=profile_facts.observed_crs_digest,
                observed_vertical_reference_digest=profile_facts.observed_vertical_reference_digest,
                now=now,
            )
        # Evidence authority is resolved through its port before the guard; the
        # exact blocker is retained so the decision names the missing evidence
        # rather than a mapping that is in fact resolvable.
        evidence_reason = None
        if use in {"RELATIVE_VOLUME", "PROFILE_DIFFERENCE"} and snapshot.policy is not None:
            expected_targets = (
                (
                    (baseline_artifact_id or "", baseline_source_sha256 or ""),
                    (current_artifact_id or "", current_source_sha256 or ""),
                )
                if use == "PROFILE_DIFFERENCE"
                else None
            )
            evidence_reason = self._pair_evidence_block_reason(
                baseline,
                current,
                snapshot,
                expected_targets=expected_targets,
                expected_digests=profile_authority.evidence_record_digests
                if profile_authority
                else (),
            )
        with self._coordinator.guarded_read():
            current_snapshot = self._pair_still_current(baseline, current, use, snapshot, now=now)
            if use == "RELATIVE_VOLUME" and (
                volume is None
                or not self._relative_volume_authority.is_current_for_use(volume, now=now)
            ):
                volume = None
            if (
                use == "PROFILE_DIFFERENCE"
                and profile_authority is not None
                and (
                    profile_facts is None
                    or current_snapshot.policy is None
                    or not self._profile_authority_binds(
                        profile_authority,
                        baseline=baseline,
                        current=current,
                        policy=current_snapshot.policy,
                        facts=profile_facts,
                    )
                    or not self._profile_difference_authority.is_current_for_use(
                        profile_authority, now=now
                    )
                )
            ):
                profile_authority = None
            candidate = self._pair_candidate(
                baseline,
                current,
                use,
                zone_id,
                current_snapshot,
                volume,
                profile_authority,
                baseline_artifact_id,
                baseline_source_sha256,
                current_artifact_id,
                current_source_sha256,
                profile_comparison_binding_digest,
                evaluation_identity,
                now,
                profile_reason=profile_reason,
                profile_facts=profile_facts,
                evidence_reason=evidence_reason,
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
        baseline_artifact_id: str | None = None,
        baseline_source_sha256: str | None = None,
        current_artifact_id: str | None = None,
        current_source_sha256: str | None = None,
        profile_comparison_binding_digest: str | None = None,
    ) -> ExternalPairUseDecisionV1 | None:
        """Read an exact retained pair-use retry without evaluating live authority."""
        if use == "PROFILE_DIFFERENCE" and not all(
            (
                baseline_artifact_id,
                baseline_source_sha256,
                current_artifact_id,
                current_source_sha256,
                profile_comparison_binding_digest,
            )
        ):
            return None
        intent = ExternalDecisionIntent(
            requested_use=use,
            baseline_subject=baseline,
            current_subject=current,
            requested_zone_id=zone_id,
            baseline_artifact_id=baseline_artifact_id if use == "PROFILE_DIFFERENCE" else None,
            baseline_source_sha256=baseline_source_sha256 if use == "PROFILE_DIFFERENCE" else None,
            current_artifact_id=current_artifact_id if use == "PROFILE_DIFFERENCE" else None,
            current_source_sha256=current_source_sha256 if use == "PROFILE_DIFFERENCE" else None,
            profile_comparison_binding_digest=(
                profile_comparison_binding_digest if use == "PROFILE_DIFFERENCE" else None
            ),
        )
        existing = self._decisions.existing_for_intent(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        return existing if isinstance(existing, ExternalPairUseDecisionV1) else None

    def request_single_volume(
        self,
        subject: SealedExternalSubjectV1,
        *,
        zone_id: str,
        idempotency_key: str,
        principal: Principal,
        now: datetime,
    ) -> ExternalSingleVolumeDecisionV1:
        """Resolve one sealed DSM epoch, attested evidence, zone and single mapping."""
        self._require_scope(principal, subject)
        if not zone_id or zone_id != zone_id.strip() or len(zone_id) > 255:
            raise ValueError("single volume requires a zone selection")
        intent = ExternalDecisionIntent(
            requested_use="SINGLE_VOLUME", subject=subject, requested_zone_id=zone_id
        )
        existing = self._decisions.existing_for_intent(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        if existing is not None:
            if not isinstance(existing, ExternalSingleVolumeDecisionV1):
                raise ValueError("idempotency decision operation conflicts")
            self._decisions.reconcile_pending()
            return existing
        evaluation_identity = self._decisions.evaluation_identity(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        snapshot = self._single_snapshot(subject, "SINGLE_VOLUME")
        # Authority ports are resolved before the guard, exactly like the pair path.
        volume = (
            self._single_volume_authority.resolve_for_use(
                subject=subject, zone_id=zone_id, policy=snapshot.policy, now=now
            )
            if snapshot.policy is not None
            else None
        )
        evidence_reason = (
            self._single_volume_evidence_block_reason(subject, snapshot)
            if snapshot.policy is not None
            else None
        )
        with self._coordinator.guarded_read():
            current = self._single_still_current(subject, "SINGLE_VOLUME", snapshot, now=now)
            if volume is not None and not self._single_volume_authority.is_current_for_use(
                volume, now=now
            ):
                volume = None
            candidate = self._single_volume_candidate(
                subject,
                zone_id,
                current,
                volume,
                evaluation_identity,
                now,
                evidence_reason=evidence_reason,
            )
            return cast(
                ExternalSingleVolumeDecisionV1,
                self._record(candidate, intent, principal, idempotency_key),
            )

    def existing_single_volume_retry(
        self,
        subject: SealedExternalSubjectV1,
        *,
        zone_id: str,
        principal: Principal,
        idempotency_key: str,
    ) -> ExternalSingleVolumeDecisionV1 | None:
        """Read an exact retained single-volume retry without evaluating live authority."""
        intent = ExternalDecisionIntent(
            requested_use="SINGLE_VOLUME", subject=subject, requested_zone_id=zone_id
        )
        existing = self._decisions.existing_for_intent(
            intent=intent, principal=principal, idempotency_key=idempotency_key
        )
        return existing if isinstance(existing, ExternalSingleVolumeDecisionV1) else None

    def _single_volume_evidence_block_reason(
        self, subject: SealedExternalSubjectV1, snapshot: _SingleSnapshot
    ) -> str | None:
        policy, report = snapshot.policy, snapshot.inspection.report
        if policy is None:
            return "POLICY_UNAVAILABLE"
        if report is None:
            return "INSPECTION_REPORT_BINDING_INVALID"
        matching, blocker = self._evidence_binding(subject, policy, report, locally_current=False)
        return None if matching is not None else blocker

    def _single_volume_reason(
        self,
        subject: SealedExternalSubjectV1,
        snapshot: _SingleSnapshot,
        volume: ExternalSingleVolumeAuthority | None,
        *,
        evidence_reason: str | None,
    ) -> tuple[str | None, tuple[str, ...]]:
        if snapshot.revision is None:
            return "SUBJECT_NOT_SEALED", ()
        if snapshot.policy is None:
            return "POLICY_UNAVAILABLE", ()
        report = snapshot.inspection.report
        if report is None or not self._report_binds(subject, report, snapshot.policy):
            return "INSPECTION_REPORT_BINDING_INVALID", ()
        # Attested evidence is a prerequisite of any admitted mapping, so an
        # evidence blocker is named before the mapping itself.
        if evidence_reason is not None:
            return evidence_reason, ()
        if volume is None:
            return "SINGLE_VOLUME_MAPPING_UNAVAILABLE", ()
        if volume.zone.zone_id == "" or volume.zone.revision != 1:
            return "VOLUME_ZONE_BINDING_INVALID", ()
        matching, blocker = self._evidence_binding(subject, snapshot.policy, report)
        if matching is None:
            return blocker, ()
        return None, (matching,)

    def _single_volume_candidate(
        self,
        subject: SealedExternalSubjectV1,
        requested_zone_id: str,
        snapshot: _SingleSnapshot,
        volume: ExternalSingleVolumeAuthority | None,
        evaluation_identity: str,
        now: datetime,
        *,
        evidence_reason: str | None,
    ) -> ExternalSingleVolumeDecisionV1:
        reason, evidence = self._single_volume_reason(
            subject, snapshot, volume, evidence_reason=evidence_reason
        )
        eligible = reason is None
        policy, report = snapshot.policy, snapshot.inspection.report
        decision_id = self._decision_id(
            {
                "intent": ExternalDecisionIntent(
                    requested_use="SINGLE_VOLUME",
                    subject=subject,
                    requested_zone_id=requested_zone_id,
                ).payload(),
                "policy": policy.policy_digest if policy else None,
                "zone": volume.zone.model_dump(by_alias=True, mode="json") if volume else None,
                "compatibilityMapping": volume.compatibility_mapping_digest if volume else None,
                "evaluationIdentity": evaluation_identity,
            }
        )
        return ExternalSingleVolumeDecisionV1(
            decision_id=decision_id,
            subject=subject,
            subject_digest=subject.canonical_digest(),
            policy_digest=policy.policy_digest if eligible and policy else None,
            inspection_report_digest=report.report_digest if eligible and report else None,
            evidence_record_digests=evidence if eligible else (),
            zone=volume.zone if eligible and volume else None,
            compatibility_mapping_digest=(
                volume.compatibility_mapping_digest if eligible and volume else None
            ),
            verdict=DecisionVerdict.ELIGIBLE if eligible else DecisionVerdict.BLOCKED,
            reasons=("USE_ELIGIBLE",) if eligible else (reason or "POLICY_UNAVAILABLE",),
            remediations=("CURRENT_DEPENDENCIES_RETAINED",)
            if eligible
            else (self._remediation(reason),),
            decided_at=now,
        ).sealed()

    def resolve_eligible_pair_for_execution(
        self,
        decision_id: str,
        *,
        principal: Principal,
        site_id: str,
        observed_crs_digest: str | None = None,
        observed_vertical_reference_digest: str | None = None,
        baseline_artifact_id: str | None = None,
        baseline_source_sha256: str | None = None,
        current_artifact_id: str | None = None,
        current_source_sha256: str | None = None,
        profile_comparison_binding_digest: str | None = None,
        profile_work_area_id: str | None = None,
        before_return: Callable[[ExternalPairUseDecisionV1], bool] | None = None,
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
        if before_return is not None and candidate.use != "PROFILE_DIFFERENCE":
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
        if candidate.use == "PROFILE_DIFFERENCE" and not all(
            (
                observed_crs_digest,
                observed_vertical_reference_digest,
                baseline_artifact_id,
                baseline_source_sha256,
                current_artifact_id,
                current_source_sha256,
                profile_comparison_binding_digest,
            )
        ):
            return None
        if candidate.use == "PROFILE_DIFFERENCE" and (
            candidate.baseline_artifact_id != baseline_artifact_id
            or candidate.baseline_source_sha256 != baseline_source_sha256
            or candidate.current_artifact_id != current_artifact_id
            or candidate.current_source_sha256 != current_source_sha256
            or candidate.profile_comparison_binding_digest != profile_comparison_binding_digest
            or (
                candidate.profile_work_area_id is not None
                and candidate.profile_work_area_id != profile_work_area_id
            )
        ):
            return None
        profile_reason: str | None = None
        profile_facts: _ProfileDifferenceFacts | None = None
        if candidate.use == "PROFILE_DIFFERENCE":
            profile_reason, profile_facts = self._profile_difference_facts(
                snapshot,
                work_area_id=profile_work_area_id,
                baseline_artifact_id=baseline_artifact_id,
                baseline_source_sha256=baseline_source_sha256,
                current_artifact_id=current_artifact_id,
                current_source_sha256=current_source_sha256,
                expected_crs_digest=observed_crs_digest,
                expected_vertical_reference_digest=observed_vertical_reference_digest,
            )
        profile_authority = None
        if (
            candidate.use == "PROFILE_DIFFERENCE"
            and profile_reason is None
            and profile_facts is not None
            and snapshot.policy
        ):
            profile_authority = self._profile_difference_authority.resolve_for_use(
                baseline=candidate.baseline_subject,
                current=candidate.current_subject,
                work_area_id=profile_work_area_id,
                baseline_artifact_id=profile_facts.baseline_artifact_id,
                baseline_source_sha256=profile_facts.baseline_source_sha256,
                current_artifact_id=profile_facts.current_artifact_id,
                current_source_sha256=profile_facts.current_source_sha256,
                policy=snapshot.policy,
                baseline_capture_started_at=profile_facts.capture.baseline_started_at,
                baseline_capture_ended_at=profile_facts.capture.baseline_ended_at,
                current_capture_started_at=profile_facts.capture.current_started_at,
                current_capture_ended_at=profile_facts.capture.current_ended_at,
                observed_crs_digest=profile_facts.observed_crs_digest,
                observed_vertical_reference_digest=profile_facts.observed_vertical_reference_digest,
                now=now,
            )
        evidence_current = (
            self._evidence_digests_remain_current(candidate, snapshot.policy)
            if candidate.use == "RELATIVE_VOLUME" and snapshot.policy is not None
            else False
        )
        profile_evidence_current = (
            self._profile_pair_evidence_remains_current(candidate, snapshot)
            if candidate.use == "PROFILE_DIFFERENCE" and snapshot.policy is not None
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
                    or volume.compatibility_mapping_digest != candidate.compatibility_mapping_digest
                    or not self._relative_volume_authority.is_current_for_use(volume, now=now)
                ):
                    return None
                if not evidence_current:
                    return None
                if not self._candidate_evidence_remains_locally_current(
                    candidate, current_snapshot.policy, current_snapshot
                ):
                    return None
            if candidate.use == "PROFILE_DIFFERENCE":
                if (
                    profile_facts is None
                    or profile_reason is not None
                    or not profile_facts.matches_reports(current_snapshot)
                    or profile_facts.baseline_report_digest
                    != candidate.baseline_inspection_report_digest
                    or profile_facts.current_report_digest
                    != candidate.current_inspection_report_digest
                    or profile_authority is None
                    or candidate.zone is not None
                    or candidate.compatibility_mapping_digest
                    != profile_authority.compatibility_mapping_digest
                    or candidate.profile_work_area_id != profile_authority.work_area_id
                    or (
                        profile_authority.evidence_record_digests
                        and profile_authority.evidence_record_digests
                        != candidate.evidence_record_digests
                    )
                    or current_snapshot.policy is None
                    or not self._profile_authority_binds(
                        profile_authority,
                        baseline=candidate.baseline_subject,
                        current=candidate.current_subject,
                        policy=current_snapshot.policy,
                        facts=profile_facts,
                    )
                    or not self._profile_difference_authority.is_current_for_use(
                        profile_authority, now=now
                    )
                    or not profile_evidence_current
                    or not self._profile_evidence_locally_current(
                        candidate, current_snapshot, profile_facts
                    )
                ):
                    return None
                if before_return is not None and not before_return(candidate):
                    return None
            elif before_return is not None:
                return None
            return candidate

    def get_scoped(
        self, decision_id: str, *, principal: Principal, site_id: str
    ) -> DecisionCandidate | None:
        """Return a scoped historic decision without creating any new authority."""
        return self._decisions.get_scoped(decision_id, principal=principal, site_id=site_id)

    def height_blocker_now(self, decision: ExternalUseDecisionV1, *, now: datetime) -> str | None:
        """Why a recorded HEIGHT decision no longer licenses a read, or ``None`` if it still does.

        A decision is history: it proves what was true when it was made.  Anything that *acts* on
        it (a profile job) must ask this again — policy still permits HEIGHT for exactly this
        subject, the inspection report is still the one the decision bound, and the DSM is still a
        measured single-band float grid with an observed vertical reference.  Local retained state
        only, so it is safe under the commit guard.
        """
        if (
            decision.use != "HEIGHT"
            or decision.verdict is not DecisionVerdict.ELIGIBLE
            or decision.policy_digest is None
            or decision.inspection_report_digest is None
        ):
            return "HEIGHT_NOT_ELIGIBLE"
        subject = decision.subject
        with self._coordinator.guarded_read():
            resolved = self._policy_registry.resolve(decision.policy_digest)
            if (
                resolved.status is not PolicySelectionStatus.ACTIVE
                or resolved.policy is None
                or not self._policy_registry.locally_current_use_permitted(
                    decision.policy_digest, use="HEIGHT", subjects=(subject,), at=now
                )
            ):
                return "POLICY_UNAVAILABLE"
            revision = self._reconstruction.resolve_sealed_subject(subject)
            if revision is None:
                return "SUBJECT_NOT_SEALED"
            report = self._inspections.public_snapshot(subject).report
            if (
                report is None
                or report.report_digest != decision.inspection_report_digest
                or not self._report_binds(subject, report, resolved.policy)
            ):
                return "INSPECTION_REPORT_BINDING_INVALID"
            return self._height_blocker(
                revision,
                report,
                declared=declared_vertical_checker(self._declared_vertical, subject),
            )

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
        reason = self._single_reason(subject, use, snapshot, at=now)
        receipt = snapshot.display
        eligible = reason is None
        display = use == "DISPLAY"
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
                receipt.receipt_digest if eligible and display and receipt is not None else None
            ),
            verdict=DecisionVerdict.ELIGIBLE if eligible else DecisionVerdict.BLOCKED,
            reasons=(("DISPLAY_ELIGIBLE" if display else "HEIGHT_ELIGIBLE"),)
            if eligible
            else (reason or "POLICY_UNAVAILABLE",),
            remediations=(
                ("DISPLAY_RECEIPT_RETAINED" if display else "CURRENT_DEPENDENCIES_RETAINED"),
            )
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
        profile_authority: ExternalProfileDifferenceAuthority | None,
        baseline_artifact_id: str | None,
        baseline_source_sha256: str | None,
        current_artifact_id: str | None,
        current_source_sha256: str | None,
        profile_comparison_binding_digest: str | None,
        evaluation_identity: str,
        now: datetime,
        *,
        profile_reason: str | None = None,
        profile_facts: _ProfileDifferenceFacts | None = None,
        evidence_reason: str | None = None,
    ) -> ExternalPairUseDecisionV1:
        reason, evidence_digests = self._pair_reason(
            baseline,
            current,
            use,
            snapshot,
            volume,
            profile_authority,
            profile_reason=profile_reason,
            profile_facts=profile_facts,
            evidence_reason=evidence_reason,
        )
        eligible = reason is None
        policy = snapshot.policy
        baseline_report = snapshot.baseline.inspection.report
        current_report = snapshot.current.inspection.report
        decision_intent = ExternalDecisionIntent(
            requested_use=use,
            baseline_subject=baseline,
            current_subject=current,
            requested_zone_id=requested_zone_id,
            baseline_artifact_id=baseline_artifact_id if use == "PROFILE_DIFFERENCE" else None,
            baseline_source_sha256=baseline_source_sha256 if use == "PROFILE_DIFFERENCE" else None,
            current_artifact_id=current_artifact_id if use == "PROFILE_DIFFERENCE" else None,
            current_source_sha256=current_source_sha256 if use == "PROFILE_DIFFERENCE" else None,
            profile_comparison_binding_digest=(
                profile_comparison_binding_digest if use == "PROFILE_DIFFERENCE" else None
            ),
        )
        decision_id = self._decision_id(
            {
                "intent": decision_intent.payload(),
                "policy": policy.policy_digest if policy else None,
                "zone": volume.zone.model_dump(by_alias=True, mode="json") if volume else None,
                "compatibilityMapping": (
                    volume.compatibility_mapping_digest
                    if use == "RELATIVE_VOLUME" and volume
                    else profile_authority.compatibility_mapping_digest
                    if use == "PROFILE_DIFFERENCE" and profile_authority
                    else None
                ),
                "evaluationIdentity": evaluation_identity,
            }
        )
        return ExternalPairUseDecisionV1(
            decision_id=decision_id,
            baseline_subject=baseline,
            baseline_subject_digest=baseline.canonical_digest(),
            current_subject=current,
            current_subject_digest=current.canonical_digest(),
            use=cast(Literal["VISUAL_COMPARISON", "RELATIVE_VOLUME", "PROFILE_DIFFERENCE"], use),
            policy_digest=policy.policy_digest if eligible and policy else None,
            baseline_inspection_report_digest=(
                baseline_report.report_digest if eligible and baseline_report else None
            ),
            current_inspection_report_digest=(
                current_report.report_digest if eligible and current_report else None
            ),
            profile_work_area_id=(
                profile_authority.work_area_id if eligible and profile_authority else None
            ),
            baseline_artifact_id=baseline_artifact_id if use == "PROFILE_DIFFERENCE" else None,
            baseline_source_sha256=baseline_source_sha256 if use == "PROFILE_DIFFERENCE" else None,
            current_artifact_id=current_artifact_id if use == "PROFILE_DIFFERENCE" else None,
            current_source_sha256=current_source_sha256 if use == "PROFILE_DIFFERENCE" else None,
            profile_comparison_binding_digest=(
                profile_comparison_binding_digest if use == "PROFILE_DIFFERENCE" else None
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
                else profile_authority.compatibility_mapping_digest
                if eligible and use == "PROFILE_DIFFERENCE" and profile_authority
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
        *,
        at: datetime,
    ) -> str | None:
        if snapshot.revision is None:
            return "SUBJECT_NOT_SEALED"
        if snapshot.policy is None:
            return "POLICY_UNAVAILABLE"
        report = snapshot.inspection.report
        if not self._report_binds(subject, report, snapshot.policy):
            return "INSPECTION_REPORT_BINDING_INVALID"
        if use == "HEIGHT":
            # 선언은 판정 시각(``at``) 기준으로 본다. 이력 검증이 같은 시각 기준으로 다시 묻기
            # 때문에, 요청 시각을 잡은 뒤 락을 얻기 전에 기록된 선언이 판정에 들어가 재생할 수
            # 없는 ELIGIBLE이 저널에 남는 일이 없다. 그 선언은 다음 요청(새 시각)부터 근거가 된다.
            return self._height_blocker(
                snapshot.revision,
                report,
                declared=declared_vertical_checker(self._declared_vertical, subject, at=at),
            )
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
        profile_authority: ExternalProfileDifferenceAuthority | None,
        *,
        profile_reason: str | None = None,
        profile_facts: _ProfileDifferenceFacts | None = None,
        evidence_reason: str | None = None,
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
        if use == "PROFILE_DIFFERENCE":
            if profile_reason is not None:
                return profile_reason, ()
            if profile_facts is None:
                return "DSM_MEASUREMENT_UNAVAILABLE", ()
            if not profile_facts.matches_reports(snapshot):
                return "INSPECTION_REPORT_BINDING_INVALID", ()
            if evidence_reason is not None:
                return evidence_reason, ()
            if profile_authority is None:
                return "COMPATIBILITY_MAPPING_MISSING", ()
            if not self._profile_authority_binds(
                profile_authority,
                baseline=baseline,
                current=current,
                policy=snapshot.policy,
                facts=profile_facts,
            ):
                return "COMPATIBILITY_MAPPING_MISSING", ()
            profile_evidence: list[str] = []
            for subject, item, artifact_id, source_sha256, approved_digest in zip(
                (baseline, current),
                (snapshot.baseline, snapshot.current),
                (profile_facts.baseline_artifact_id, profile_facts.current_artifact_id),
                (profile_facts.baseline_source_sha256, profile_facts.current_source_sha256),
                profile_authority.evidence_record_digests or (None, None),
                strict=True,
            ):
                report = item.inspection.report
                assert report is not None
                matching, blocker = self._evidence_binding(
                    subject,
                    snapshot.policy,
                    report,
                    expected_target=(artifact_id, source_sha256),
                    expected_digest=approved_digest,
                )
                if matching is None:
                    return blocker, ()
                profile_evidence.append(matching)
            return None, tuple(profile_evidence)
        # Independently attested evidence is a prerequisite of any admitted
        # mapping, so an evidence blocker is named before the mapping itself.
        if evidence_reason is not None:
            return evidence_reason, ()
        if volume is None:
            return "VOLUME_AUTHORITY_UNAVAILABLE", ()
        if volume.zone.zone_id == "" or volume.zone.revision != 1:
            return "VOLUME_ZONE_BINDING_INVALID", ()
        volume_evidence: list[str] = []
        for subject, item in ((baseline, snapshot.baseline), (current, snapshot.current)):
            report = item.inspection.report
            assert report is not None
            # One currently validated, independently attested record for the
            # precise measured DSM is required per ordered epoch.  This port does
            # not accept display receipts or arbitrary digest lists as substitutes.
            matching, blocker = self._evidence_binding(subject, snapshot.policy, report)
            if matching is None:
                return blocker, ()
            volume_evidence.append(matching)
        return None, tuple(volume_evidence)

    def _validated_evidence_for(
        self,
        subject: SealedExternalSubjectV1,
        policy: ExternalValidationPolicyV1,
        report: ExternalArtifactInspectionReportV1,
        *,
        locally_current: bool = True,
    ) -> str | None:
        return self._evidence_binding(subject, policy, report, locally_current=locally_current)[0]

    def _evidence_binding(
        self,
        subject: SealedExternalSubjectV1,
        policy: ExternalValidationPolicyV1,
        report: ExternalArtifactInspectionReportV1,
        *,
        locally_current: bool = True,
        expected_target: tuple[str, str] | None = None,
        expected_digest: str | None = None,
    ) -> tuple[str | None, str]:
        """Return the usable evidence digest, or ``None`` with the exact typed blocker.

        ``EVIDENCE_RECORD_BINDING_INVALID`` means no currently validated record
        binds the measured DSM.  ``EVIDENCE_INDEPENDENCE_UNATTESTED`` means such a
        record exists but its measurement context carries no separately
        authorized independence attestation, which the relative-volume V1 rule
        requires per epoch.
        """
        blocker = "EVIDENCE_RECORD_BINDING_INVALID"
        # The evidence store intentionally exposes only exact digest lookup.
        # Querying its private projection would turn a broad list into authority.
        digests = (
            (expected_digest,)
            if expected_digest is not None
            else self._evidence_validations.validated_record_digests_for(
                subject=subject, policy_digest=policy.policy_digest or ""
            )
        )
        for digest in digests:
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
            if expected_target is not None and (
                context.target_dsm_artifact_id != expected_target[0]
                or context.target_dsm_observed_sha256 != expected_target[1]
            ):
                continue
            if record.evidence_record_digest != digest or not self._report_measures_dsm(
                report, context.target_dsm_artifact_id, context.target_dsm_observed_sha256
            ):
                continue
            if context.independent_attestation is None:
                blocker = "EVIDENCE_INDEPENDENCE_UNATTESTED"
                continue
            return digest, blocker
        return None, blocker

    @classmethod
    def _profile_difference_facts(
        cls,
        snapshot: _PairSnapshot,
        *,
        baseline_artifact_id: str | None,
        baseline_source_sha256: str | None,
        current_artifact_id: str | None,
        current_source_sha256: str | None,
        expected_crs_digest: str | None,
        expected_vertical_reference_digest: str | None,
        work_area_id: str | None,
    ) -> tuple[str | None, _ProfileDifferenceFacts | None]:
        """Bind parser facts to the exact selected DSM in both frozen reports."""
        if (
            baseline_artifact_id is None
            or baseline_source_sha256 is None
            or current_artifact_id is None
            or current_source_sha256 is None
        ):
            return "DSM_MEASUREMENT_UNAVAILABLE", None
        epoch_facts: list[tuple[str, str, str]] = []
        for item, artifact_id, source_sha256 in (
            (snapshot.baseline, baseline_artifact_id, baseline_source_sha256),
            (snapshot.current, current_artifact_id, current_source_sha256),
        ):
            report = item.inspection.report
            if report is None or not report.report_digest:
                return "INSPECTION_REPORT_BINDING_INVALID", None
            outcomes = (
                cls._measured_outcomes(item.revision, report, ProcessingArtifactKind.DSM)
                if item.revision is not None
                else ()
            )
            selected = tuple(
                outcome
                for outcome in outcomes
                if outcome.artifact_id == artifact_id and outcome.observed_sha256 == source_sha256
            )
            if len(selected) != 1:
                return "DSM_MEASUREMENT_UNAVAILABLE", None
            outcome = selected[0]
            measurements = outcome.measurements
            if (
                measurements is None
                or measurements.band_count != 1
                or measurements.dtype not in {"float32", "float64"}
            ):
                return "DSM_MEASUREMENT_UNAVAILABLE", None
            vertical = measurements.observed_vertical_reference
            if vertical is None:
                return "VERTICAL_REFERENCE_UNKNOWN", None
            epoch_facts.append(
                (
                    measurements.observed_crs_digest,
                    vertical.canonical_digest(),
                    report.report_digest,
                )
            )
        baseline_fact, current_fact = epoch_facts
        if baseline_fact[0] != current_fact[0]:
            return "PROFILE_DIFFERENCE_CRS_MISMATCH", None
        if baseline_fact[1] != current_fact[1]:
            return "PROFILE_DIFFERENCE_VERTICAL_REFERENCE_MISMATCH", None
        capture_reason, capture = cls._profile_difference_capture_intervals(snapshot)
        if capture_reason is not None or capture is None:
            return capture_reason or "PROFILE_DIFFERENCE_CAPTURE_ORDER_INVALID", None
        if (
            expected_crs_digest is None
            or expected_vertical_reference_digest is None
            or baseline_fact[0] != expected_crs_digest
            or baseline_fact[1] != expected_vertical_reference_digest
        ):
            return "PROFILE_DIFFERENCE_RECEIPT_REFERENCE_MISMATCH", None
        return None, _ProfileDifferenceFacts(
            work_area_id=work_area_id,
            baseline_report_digest=baseline_fact[2],
            current_report_digest=current_fact[2],
            baseline_artifact_id=baseline_artifact_id,
            baseline_source_sha256=baseline_source_sha256,
            current_artifact_id=current_artifact_id,
            current_source_sha256=current_source_sha256,
            observed_crs_digest=baseline_fact[0],
            observed_vertical_reference_digest=baseline_fact[1],
            capture=capture,
        )

    @staticmethod
    def _profile_difference_capture_intervals(
        snapshot: _PairSnapshot,
    ) -> tuple[str | None, _ProfileCaptureIntervals | None]:
        """Use only the sealed submission capture intervals for epoch ordering."""
        revisions = (snapshot.baseline.revision, snapshot.current.revision)
        intervals: list[tuple[datetime, datetime]] = []
        epoch_ids: list[str] = []
        for revision in revisions:
            if revision is None:
                return "SUBJECT_NOT_SEALED", None
            epoch_id = getattr(revision, "observation_epoch_id", None)
            if not isinstance(epoch_id, str) or not epoch_id:
                return "PROFILE_DIFFERENCE_CAPTURE_ORDER_INVALID", None
            epoch_ids.append(epoch_id)
            declaration = revision.submission.input_declaration
            started = getattr(declaration, "capture_started_at", None)
            ended = getattr(declaration, "capture_ended_at", None)
            if (
                not isinstance(started, datetime)
                or not isinstance(ended, datetime)
                or started.tzinfo is None
                or ended.tzinfo is None
                or started.utcoffset() != UTC.utcoffset(started)
                or ended.utcoffset() != UTC.utcoffset(ended)
                or started >= ended
            ):
                return "PROFILE_DIFFERENCE_CAPTURE_ORDER_INVALID", None
            intervals.append((started, ended))
        (baseline_start, baseline_end), (current_start, current_end) = intervals
        if (
            epoch_ids[0] == epoch_ids[1]
            or baseline_start >= current_start
            or baseline_end > current_start
        ):
            return "PROFILE_DIFFERENCE_CAPTURE_ORDER_INVALID", None
        return None, _ProfileCaptureIntervals(
            baseline_started_at=baseline_start,
            baseline_ended_at=baseline_end,
            current_started_at=current_start,
            current_ended_at=current_end,
        )

    @staticmethod
    def _profile_authority_binds(
        authority: ExternalProfileDifferenceAuthority,
        *,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        policy: ExternalValidationPolicyV1,
        facts: _ProfileDifferenceFacts,
    ) -> bool:
        if not authority.authorized_by(policy):
            return False
        if authority.work_area_id is not None and (
            authority.work_area_id != facts.work_area_id
            or authority.baseline_inspection_report_digest != facts.baseline_report_digest
            or authority.current_inspection_report_digest != facts.current_report_digest
        ):
            return False
        return authority.binds(
            baseline=baseline,
            current=current,
            baseline_artifact_id=facts.baseline_artifact_id,
            baseline_source_sha256=facts.baseline_source_sha256,
            current_artifact_id=facts.current_artifact_id,
            current_source_sha256=facts.current_source_sha256,
            baseline_capture_started_at=facts.capture.baseline_started_at,
            baseline_capture_ended_at=facts.capture.baseline_ended_at,
            current_capture_started_at=facts.capture.current_started_at,
            current_capture_ended_at=facts.capture.current_ended_at,
            observed_crs_digest=facts.observed_crs_digest,
            observed_vertical_reference_digest=facts.observed_vertical_reference_digest,
            policy_digest=policy.policy_digest or "",
        )

    def _profile_pair_evidence_remains_current(
        self, candidate: ExternalPairUseDecisionV1, snapshot: _PairSnapshot
    ) -> bool:
        if snapshot.policy is None or len(candidate.evidence_record_digests) != 2:
            return False
        for subject, item, artifact_id, source_sha256, digest in zip(
            (candidate.baseline_subject, candidate.current_subject),
            (snapshot.baseline, snapshot.current),
            (candidate.baseline_artifact_id, candidate.current_artifact_id),
            (candidate.baseline_source_sha256, candidate.current_source_sha256),
            candidate.evidence_record_digests,
            strict=True,
        ):
            report = item.inspection.report
            if (
                report is None
                or self._evidence_binding(
                    subject,
                    snapshot.policy,
                    report,
                    locally_current=False,
                    expected_target=(artifact_id or "", source_sha256 or ""),
                    expected_digest=digest,
                )[0]
                is None
            ):
                return False
        return True

    def _profile_evidence_locally_current(
        self,
        candidate: ExternalPairUseDecisionV1,
        snapshot: _PairSnapshot,
        facts: _ProfileDifferenceFacts,
    ) -> bool:
        if len(candidate.evidence_record_digests) != 2 or snapshot.policy is None:
            return False
        for evidence_digest, subject, item, artifact_id, source_sha256 in zip(
            candidate.evidence_record_digests,
            (candidate.baseline_subject, candidate.current_subject),
            (snapshot.baseline, snapshot.current),
            (candidate.baseline_artifact_id, candidate.current_artifact_id),
            (candidate.baseline_source_sha256, candidate.current_source_sha256),
            strict=True,
        ):
            report = item.inspection.report
            if report is None:
                return False
            resolved = self._evidence_validations.record_for_locally_current_use(
                evidence_digest, subject=subject, policy_digest=snapshot.policy.policy_digest or ""
            )
            if resolved is None:
                return False
            record, context = resolved
            outcomes = (
                self._measured_outcomes(item.revision, report, ProcessingArtifactKind.DSM)
                if item.revision
                else ()
            )
            selected = tuple(
                outcome
                for outcome in outcomes
                if outcome.artifact_id == artifact_id and outcome.observed_sha256 == source_sha256
            )
            if (
                len(selected) != 1
                or context.independent_attestation is None
                or record.evidence_record_digest != evidence_digest
                or context.target_dsm_artifact_id != artifact_id
                or context.target_dsm_observed_sha256 != source_sha256
                or selected[0].measurements is None
                or selected[0].measurements.observed_crs_digest != facts.observed_crs_digest
                or selected[0].measurements.observed_vertical_reference is None
                or selected[0].measurements.observed_vertical_reference.canonical_digest()
                != facts.observed_vertical_reference_digest
            ):
                return False
        return True

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
        return self._pair_evidence_block_reason(baseline, current, snapshot) is None

    def _pair_evidence_block_reason(
        self,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        snapshot: _PairSnapshot,
        *,
        expected_targets: tuple[tuple[str, str], tuple[str, str]] | None = None,
        expected_digests: tuple[str, ...] = (),
    ) -> str | None:
        """Resolve evidence through its authority port and name the first epoch blocker."""
        policy = snapshot.policy
        if policy is None:
            return "POLICY_UNAVAILABLE"
        for (subject, item), expected_target, expected_digest in zip(
            ((baseline, snapshot.baseline), (current, snapshot.current)),
            expected_targets or (None, None),
            expected_digests or (None, None),
            strict=True,
        ):
            report = item.inspection.report
            if report is None:
                return "INSPECTION_REPORT_BINDING_INVALID"
            matching, blocker = self._evidence_binding(
                subject,
                policy,
                report,
                locally_current=False,
                expected_target=expected_target,
                expected_digest=expected_digest,
            )
            if matching is None:
                return blocker
        return None

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
    def _measured_outcomes(
        revision: ExternalReconstructionRevision,
        report: ExternalArtifactInspectionReportV1 | None,
        kind: ProcessingArtifactKind,
    ) -> tuple[ArtifactInspectionOutcomeV1, ...]:
        """MEASURED outcomes whose id and sha256 are exactly a sealed manifest entry of ``kind``."""
        if report is None or revision.manifest is None:
            return ()
        required = {
            entry.artifact_id: "sha256:" + entry.observed_sha256
            for entry in revision.manifest.entries
            if entry.kind is kind
        }
        return tuple(
            outcome
            for outcome in report.measurement_payload.outcomes
            if outcome.outcome is ArtifactOutcome.MEASURED
            and required.get(outcome.artifact_id) == outcome.observed_sha256
        )

    @staticmethod
    def _measured_kind(
        revision: ExternalReconstructionRevision,
        report: ExternalArtifactInspectionReportV1 | None,
        kind: ProcessingArtifactKind,
    ) -> bool:
        return bool(ExternalUseEvaluator._measured_outcomes(revision, report, kind))

    @staticmethod
    def _height_blocker(
        revision: ExternalReconstructionRevision,
        report: ExternalArtifactInspectionReportV1 | None,
        *,
        declared: Callable[[str], bool] | None = None,
    ) -> str | None:
        """Why a measured DSM cannot be read for heights, or ``None``.

        Reading heights from one grid needs the grid itself (a measured single-band float
        DSM) and a vertical reference — the horizontal axis being metres says nothing about the
        elevation unit.  The reference is the parser-observed one; only when the file carries none,
        a user declaration (a claim, recorded apart from the observation) may stand in, and only
        for this read.  It does not need a zone, a second epoch or a compatibility mapping: those
        belong to quantitative comparison, not to reading, and they never see a declaration.
        """
        dsms = tuple(
            outcome
            for outcome in ExternalUseEvaluator._measured_outcomes(
                revision, report, ProcessingArtifactKind.DSM
            )
            if outcome.measurements is not None
            and outcome.measurements.band_count == 1
            and outcome.measurements.dtype in {"float32", "float64"}
        )
        if not dsms:
            return "DSM_MEASUREMENT_UNAVAILABLE"
        if any(
            outcome.measurements is not None
            and outcome.measurements.observed_vertical_reference is not None
            for outcome in dsms
        ):
            return None
        if declared is not None and any(declared(outcome.artifact_id) for outcome in dsms):
            return None
        return "VERTICAL_REFERENCE_UNKNOWN"

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
        return PAIR_REASON_REMEDIATIONS.get(reason, "RESOLVE_EXTERNAL_USE_BLOCKER")

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
                is_durable_retry=lambda: (
                    evaluator.existing_single_retry(
                        subject,
                        use=request.use,
                        principal=principal,
                        idempotency_key=idempotency_key,
                    )
                    is not None
                ),
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
                is_durable_retry=lambda: (
                    evaluator.existing_pair_retry(
                        baseline,
                        current,
                        use=request.use,
                        zone_id=request.zone_id,
                        principal=principal,
                        idempotency_key=idempotency_key,
                    )
                    is not None
                ),
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

    @router.post(
        base + "/single-volume", response_model=ExternalUseDecisionResponse, status_code=201
    )
    def request_single_volume(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        request: ExternalSingleVolumeDecisionRequest,
        idempotency_key: str = Depends(idempotency_header),  # noqa: B008
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalUseDecisionResponse:
        human(principal)
        subject = subject_for(work_order_id, submission_ref, revision, principal)
        try:
            with work_orders.guard_new_external_intent(
                work_order_id,
                organization_id=principal.organization_id,
                is_durable_retry=lambda: (
                    evaluator.existing_single_volume_retry(
                        subject,
                        zone_id=request.zone_id,
                        principal=principal,
                        idempotency_key=idempotency_key,
                    )
                    is not None
                ),
            ):
                return write_result(
                    evaluator.request_single_volume(
                        subject,
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
        if isinstance(candidate, ExternalUseDecisionV1 | ExternalSingleVolumeDecisionV1):
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
