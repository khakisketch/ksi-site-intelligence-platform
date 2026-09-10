"""Current Core evaluation tests with synthetic, explicit authority snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_artifact_inspections import PublicInspectionSnapshot
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_evidence_validations import ExternalEvidenceValidationStore
from ksi_core.external_use_decisions import ExternalUseDecisionStore
from ksi_core.external_use_evaluator import ExternalUseEvaluator
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalArtifactInspectionReportV1,
    ExternalPairUseDecisionV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_display_artifact import SanitizedDisplayReceiptV1
from support.external_artifact_inspection_fixtures import (  # type: ignore[import-not-found]
    NOW,
    digest,
    policy_template,
    report,
    sealed_manifest,
    subject,
)


class _PolicyAuthority(PolicyAuthorityPort):
    def __init__(self, record: PolicyAuthorityRecord) -> None:
        self._record = record

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        del now
        return self._record if authority_record_digest == self._record.digest else None


class _Reconstruction:
    def __init__(
        self,
        sealed_subject: SealedExternalSubjectV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.coordinator = coordinator
        self._subject = sealed_subject
        self._revision = SimpleNamespace(manifest=sealed_manifest())

    def resolve_sealed_subject(self, value: SealedExternalSubjectV1) -> object | None:
        return self._revision if value == self._subject else None


class _Inspections:
    def __init__(
        self,
        sealed_subject: SealedExternalSubjectV1,
        accepted_report: ExternalArtifactInspectionReportV1,
        receipt: SanitizedDisplayReceiptV1 | None,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        *,
        withdraw_after_initial_snapshot: bool = False,
    ) -> None:
        self.coordinator = coordinator
        self._subject = sealed_subject
        self._report = accepted_report
        self._receipt = receipt
        self._withdraw_after_initial_snapshot = withdraw_after_initial_snapshot
        self._snapshot_reads = 0

    def public_snapshot(self, value: SealedExternalSubjectV1) -> PublicInspectionSnapshot:
        self._snapshot_reads += 1
        if self._withdraw_after_initial_snapshot and self._snapshot_reads > 1:
            return PublicInspectionSnapshot("INSPECTION_PENDING", None, None, None)
        return PublicInspectionSnapshot(
            "INSPECTION_REPORTED" if value == self._subject else "INSPECTION_PENDING",
            None,
            None,
            self._report if value == self._subject else None,
        )

    def public_display_state(
        self, value: SealedExternalSubjectV1
    ) -> tuple[str, SanitizedDisplayReceiptV1 | None]:
        return ("SEALED", self._receipt) if value == self._subject else ("PENDING", None)


class _Evidence:
    def __init__(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self.coordinator = coordinator

    def resolve_for_validation(self, evidence_ref: str) -> None:
        del evidence_ref
        return None


class _SyntheticHistoryVerifier:
    """Fixture-only source verifier; production assembly uses Core resolvers."""

    def verify(self, candidate: object) -> bool:
        del candidate
        return True


class _PairReconstruction:
    def __init__(
        self,
        *subjects: SealedExternalSubjectV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.coordinator = coordinator
        self._revisions = {
            value: SimpleNamespace(manifest=sealed_manifest()) for value in subjects
        }

    def resolve_sealed_subject(self, value: SealedExternalSubjectV1) -> object | None:
        return self._revisions.get(value)


class _PairInspections:
    def __init__(
        self,
        reports: dict[SealedExternalSubjectV1, ExternalArtifactInspectionReportV1],
        receipts: dict[SealedExternalSubjectV1, SanitizedDisplayReceiptV1],
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.coordinator = coordinator
        self._reports = reports
        self._receipts = receipts

    def public_snapshot(self, value: SealedExternalSubjectV1) -> PublicInspectionSnapshot:
        accepted = self._reports.get(value)
        return PublicInspectionSnapshot(
            "INSPECTION_REPORTED" if accepted is not None else "INSPECTION_PENDING",
            None,
            None,
            accepted,
        )

    def public_display_state(
        self, value: SealedExternalSubjectV1
    ) -> tuple[str, SanitizedDisplayReceiptV1 | None]:
        receipt = self._receipts.get(value)
        return ("SEALED", receipt) if receipt is not None else ("PENDING", None)


def _principal() -> Principal:
    return Principal("operator-1", PrincipalKind.OPERATOR, Role.ADMIN, None, "organization-1")


def _registry(
    tmp_path: Path,
    sealed_subject: SealedExternalSubjectV1,
    *,
    coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
) -> tuple[ExternalValidationPolicyRegistry, ExternalValidationPolicyV1]:
    template = policy_template()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(sealed_subject,),
        permitted_uses=("DISPLAY", "HEIGHT"),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=_PolicyAuthority(authority),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)
    return registry, policy


def _receipt(
    accepted_report: ExternalArtifactInspectionReportV1, policy: ExternalValidationPolicyV1
) -> SanitizedDisplayReceiptV1:
    report_digest = accepted_report.report_digest
    subject_digest = accepted_report.subject_digest
    assert report_digest is not None and policy.policy_digest is not None
    return SanitizedDisplayReceiptV1(
        display_id="display-1",
        request_id="request-1",
        declaration_digest=digest("8"),
        source_subject_digest=subject_digest,
        source_report_digest=report_digest,
        policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        observed_derivative_sha256=digest("9"),
        observed_derivative_size_bytes=12,
        observed_derivative_content_type="image/tiff",
        sanitized_display_ref="sda-v1-display-1",
        sealed_at=NOW,
    ).sealed()


def _evaluator(
    tmp_path: Path,
    *,
    receipt: SanitizedDisplayReceiptV1 | None,
    withdraw_after_initial_snapshot: bool = False,
) -> ExternalUseEvaluator:
    sealed_subject = subject()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    registry, policy = _registry(tmp_path, sealed_subject, coordinator=coordinator)
    accepted_report = report(request_id="request-1", policy=policy)
    validations = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validations.jsonl"),
        evidence=_Evidence(coordinator),
        policy_registry=registry,
        coordinator=coordinator,
        clock=lambda: NOW,
    )
    return ExternalUseEvaluator(
        decisions=ExternalUseDecisionStore(
            DurableJournal(tmp_path / "decisions.jsonl"),
            coordinator=coordinator,
            history_verifier=_SyntheticHistoryVerifier(),
        ),
        reconstruction=_Reconstruction(sealed_subject, coordinator),  # type: ignore[arg-type]
        inspections=_Inspections(
            sealed_subject,
            accepted_report,
            receipt,
            coordinator,
            withdraw_after_initial_snapshot=withdraw_after_initial_snapshot,
        ),
        policy_registry=registry,
        evidence_validations=validations,
        coordinator=coordinator,
    )


def _report_for_subject(
    value: SealedExternalSubjectV1,
    policy: ExternalValidationPolicyV1,
    *,
    request_id: str,
) -> ExternalArtifactInspectionReportV1:
    original = report(request_id=request_id, policy=policy)
    payload = original.measurement_payload.model_copy(
        update={
            "subject_digest": value.canonical_digest(),
            "sealed_manifest_digest": value.manifest_digest,
        },
        deep=True,
    )
    return original.model_copy(
        update={
            "subject": value,
            "subject_digest": value.canonical_digest(),
            "sealed_manifest_digest": value.manifest_digest,
            "measurement_payload": payload,
            "measurement_payload_digest": None,
            "report_digest": None,
        },
        deep=True,
    ).sealed()


def _pair_evaluator(
    tmp_path: Path,
) -> tuple[
    ExternalUseEvaluator,
    SealedExternalSubjectV1,
    SealedExternalSubjectV1,
    ExternalValidationPolicyRegistry,
    ExternalValidationPolicyV1,
]:
    baseline = subject()
    current = baseline.model_copy(
        update={
            "submission_id": "submission-2",
            "submission_digest": digest("a"),
            "manifest_digest": digest("b"),
        },
        deep=True,
    )
    template = policy_template()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(baseline, current),
        permitted_uses=("VISUAL_COMPARISON",),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=_PolicyAuthority(authority),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)
    baseline_report = _report_for_subject(baseline, policy, request_id="pair-baseline")
    current_report = _report_for_subject(current, policy, request_id="pair-current")
    validations = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validations.jsonl"),
        evidence=_Evidence(coordinator),
        policy_registry=registry,
        coordinator=coordinator,
        clock=lambda: NOW,
    )
    evaluator = ExternalUseEvaluator(
        decisions=ExternalUseDecisionStore(
            DurableJournal(tmp_path / "decisions.jsonl"),
            coordinator=coordinator,
            history_verifier=_SyntheticHistoryVerifier(),
        ),
        reconstruction=_PairReconstruction(  # type: ignore[arg-type]
            baseline, current, coordinator=coordinator
        ),
        inspections=_PairInspections(
            {baseline: baseline_report, current: current_report},
            {
                baseline: _receipt(baseline_report, policy),
                current: _receipt(current_report, policy),
            },
            coordinator,
        ),
        policy_registry=registry,
        evidence_validations=validations,
        coordinator=coordinator,
    )
    return evaluator, baseline, current, registry, policy


def test_display_is_core_resolved_and_does_not_require_a_valid_dsm(tmp_path: Path) -> None:
    sealed_subject = subject()
    registry, policy = _registry(tmp_path, sealed_subject)
    accepted_report = report(request_id="request-1", policy=policy)
    evaluator = _evaluator(tmp_path / "evaluator", receipt=_receipt(accepted_report, policy))

    decision = evaluator.request_single(
        sealed_subject,
        use="DISPLAY",
        idempotency_key="display-1",
        principal=_principal(),
        now=NOW,
    )

    assert decision.verdict is DecisionVerdict.ELIGIBLE
    assert decision.evidence_record_digests == ()
    assert decision.sanitized_display_receipt_digest is not None


def test_display_evaluation_rechecks_the_current_inspection_snapshot_before_append(
    tmp_path: Path,
) -> None:
    """Reusing the pre-guard report would make a withdrawn inspection eligible."""
    sealed_subject = subject()
    registry, policy = _registry(tmp_path, sealed_subject)
    accepted_report = report(request_id="request-1", policy=policy)
    evaluator = _evaluator(
        tmp_path / "evaluator",
        receipt=_receipt(accepted_report, policy),
        withdraw_after_initial_snapshot=True,
    )

    decision = evaluator.request_single(
        sealed_subject,
        use="DISPLAY",
        idempotency_key="display-withdrawn-inspection",
        principal=_principal(),
        now=NOW,
    )

    assert decision.verdict is DecisionVerdict.BLOCKED


def test_height_is_explicitly_blocked_and_exact_retry_reads_history(tmp_path: Path) -> None:
    evaluator = _evaluator(tmp_path, receipt=None)
    sealed_subject = subject()

    first = evaluator.request_single(
        sealed_subject,
        use="HEIGHT",
        idempotency_key="height-1",
        principal=_principal(),
        now=NOW,
    )
    retried = evaluator.request_single(
        sealed_subject,
        use="HEIGHT",
        idempotency_key="height-1",
        principal=_principal(),
        now=NOW + timedelta(minutes=1),
    )

    assert first.verdict is DecisionVerdict.BLOCKED
    assert first.reasons == ("HEIGHT_PRODUCT_DEFINITION_UNRESOLVED",)
    assert retried == first


def test_visual_pair_is_core_resolved_and_reordered_retry_conflicts(tmp_path: Path) -> None:
    evaluator, baseline, current, registry, policy = _pair_evaluator(tmp_path)

    decision = evaluator.request_pair(
        baseline,
        current,
        use="VISUAL_COMPARISON",
        zone_id=None,
        idempotency_key="visual-1",
        principal=_principal(),
        now=NOW,
    )

    assert decision.verdict is DecisionVerdict.ELIGIBLE
    assert decision.evidence_record_digests == ()
    assert decision.baseline_sanitized_display_receipt_digest is not None
    assert decision.current_sanitized_display_receipt_digest is not None
    assert (
        evaluator.resolve_eligible_pair_for_execution(
            decision.decision_id, principal=_principal(), site_id=baseline.site_id
        )
        == decision
    )
    revoked = registry.revoke(policy.policy_id, policy.version, actor="authority", now=NOW)
    assert revoked.status.value == "REVOKED"
    assert (
        evaluator.resolve_eligible_pair_for_execution(
            decision.decision_id, principal=_principal(), site_id=baseline.site_id
        )
        is None
    )
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        evaluator.request_pair(
            current,
            baseline,
            use="VISUAL_COMPARISON",
            zone_id=None,
            idempotency_key="visual-1",
            principal=_principal(),
            now=NOW + timedelta(minutes=1),
        )


def test_evaluator_rejects_an_uncoordinated_source_store(tmp_path: Path) -> None:
    sealed_subject = subject()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    registry, policy = _registry(tmp_path, sealed_subject, coordinator=coordinator)
    accepted_report = report(request_id="request-1", policy=policy)
    validations = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validations.jsonl"),
        evidence=_Evidence(coordinator),
        policy_registry=registry,
        coordinator=coordinator,
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError, match="external reconstruction store must share"):
        ExternalUseEvaluator(
            decisions=ExternalUseDecisionStore(
                DurableJournal(tmp_path / "decisions.jsonl"),
                coordinator=coordinator,
                history_verifier=_SyntheticHistoryVerifier(),
            ),
            reconstruction=_Reconstruction(  # type: ignore[arg-type]
                sealed_subject, ExternalAuthorityCurrentnessCoordinator()
            ),
            inspections=_Inspections(sealed_subject, accepted_report, None, coordinator),
            policy_registry=registry,
            evidence_validations=validations,
            coordinator=coordinator,
        )


def test_execution_recheck_uses_retained_local_evidence_projection() -> None:
    """The final coordinator guard cannot call an external currentness authority."""

    class _EvidenceProjection:
        def record_for_current_use(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise AssertionError("external evidence authority was called under the guard")

        def record_for_locally_current_use(
            self, *args: object, **kwargs: object
        ) -> tuple[object, SimpleNamespace]:
            del kwargs
            return (
                SimpleNamespace(evidence_record_digest=args[0]),
                SimpleNamespace(
                    independent_attestation=object(),
                    target_dsm_artifact_id="dsm-a",
                    target_dsm_observed_sha256=digest("d"),
                ),
            )

    evaluator = object.__new__(ExternalUseEvaluator)
    evaluator._evidence_validations = _EvidenceProjection()  # type: ignore[assignment]
    evaluator._report_measures_dsm = lambda *args: True  # type: ignore[method-assign]
    baseline = subject()
    current = baseline.model_copy(
        update={
            "submission_id": "local-current",
            "submission_digest": digest("a"),
            "manifest_digest": digest("b"),
        },
        deep=True,
    )
    candidate = ExternalPairUseDecisionV1(
        decision_id="local-evidence-projection",
        baseline_subject=baseline,
        baseline_subject_digest=baseline.canonical_digest(),
        current_subject=current,
        current_subject_digest=current.canonical_digest(),
        use="VISUAL_COMPARISON",
        baseline_inspection_report_digest=digest("a"),
        current_inspection_report_digest=digest("b"),
        evidence_record_digests=(digest("e"), digest("f")),
        verdict=DecisionVerdict.BLOCKED,
        reasons=("SYNTHETIC",),
        remediations=("SYNTHETIC",),
        decided_at=NOW,
    )
    policy = SimpleNamespace(policy_digest=digest("c"))
    snapshot = SimpleNamespace(
        baseline=SimpleNamespace(inspection=SimpleNamespace(report=SimpleNamespace(report_digest=digest("a")))),
        current=SimpleNamespace(inspection=SimpleNamespace(report=SimpleNamespace(report_digest=digest("b")))),
    )

    assert evaluator._candidate_evidence_remains_locally_current(candidate, policy, snapshot)
