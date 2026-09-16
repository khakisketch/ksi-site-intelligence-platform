"""Current Core evaluation tests with synthetic, explicit authority snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_artifact_inspections import PublicInspectionSnapshot
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_evidence_validations import ExternalEvidenceValidationStore
from ksi_core.external_relative_volume_authorities import ExternalRelativeVolumeAuthority
from ksi_core.external_use_decisions import ExternalUseDecisionStore
from ksi_core.external_use_evaluator import ExternalUseEvaluator, _PairSnapshot
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    DecisionVerdict,
    ExternalArtifactInspectionReportV1,
    ExternalPairUseDecisionV1,
    ExternalValidationPolicyV1,
    SealedArtifactBindingV1,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
)
from ksi_event_contracts.external_display_artifact import SanitizedDisplayReceiptV1
from support.external_artifact_inspection_fixtures import (
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
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

    def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> _PolicyAuthority:
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        assert self._coordinator is not None
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        del now
        return self._record if authority_record_digest == self._record.digest else None

    def resolve_historical(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        return (
            self._record
            if authority_record_digest == self._record.digest and self._record.is_active_at(at)
            else None
        )

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        return authority == self._record and authority.is_active_at(now)


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

    def historical_report(
        self, value: SealedExternalSubjectV1, *, report_digest: str, policy_digest: str
    ) -> ExternalArtifactInspectionReportV1 | None:
        del policy_digest
        if value == self._subject and report_digest == self._report.report_digest:
            return self._report
        return None

    def historical_display_receipt(
        self,
        value: SealedExternalSubjectV1,
        *,
        report_digest: str,
        receipt_digest: str,
        policy_digest: str,
    ) -> SanitizedDisplayReceiptV1 | None:
        del policy_digest
        return (
            self._receipt
            if value == self._subject
            and self._receipt is not None
            and report_digest == self._report.report_digest
            and receipt_digest == self._receipt.receipt_digest
            else None
        )


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

    def historical_report(
        self, value: SealedExternalSubjectV1, *, report_digest: str, policy_digest: str
    ) -> ExternalArtifactInspectionReportV1 | None:
        del policy_digest
        report_value = self._reports.get(value)
        if report_value is not None and report_value.report_digest == report_digest:
            return report_value
        return None

    def historical_display_receipt(
        self,
        value: SealedExternalSubjectV1,
        *,
        report_digest: str,
        receipt_digest: str,
        policy_digest: str,
    ) -> SanitizedDisplayReceiptV1 | None:
        del policy_digest
        receipt = self._receipts.get(value)
        report_value = self._reports.get(value)
        return (
            receipt
            if receipt is not None
            and report_value is not None
            and report_value.report_digest == report_digest
            and receipt.receipt_digest == receipt_digest
            else None
        )


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
        active_until=NOW + timedelta(days=14),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
    policy_authority = _PolicyAuthority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=policy_authority,
        authority_currentness_port=policy_authority.bind(coordinator),
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
        active_until=datetime.now(UTC) + timedelta(days=14),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    policy_authority = _PolicyAuthority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=policy_authority,
        authority_currentness_port=policy_authority.bind(coordinator),
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
    cast(Any, evaluator)._evidence_validations = _EvidenceProjection()
    cast(Any, evaluator)._report_measures_dsm = lambda *args: True
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
    policy = cast(ExternalValidationPolicyV1, SimpleNamespace(policy_digest=digest("c")))
    snapshot = SimpleNamespace(
        baseline=SimpleNamespace(inspection=SimpleNamespace(report=SimpleNamespace(report_digest=digest("a")))),
        current=SimpleNamespace(inspection=SimpleNamespace(report=SimpleNamespace(report_digest=digest("b")))),
    )

    assert evaluator._candidate_evidence_remains_locally_current(
        candidate, policy, cast(_PairSnapshot, snapshot)
    )


class _VolumeAuthority:
    """Fixture port: a resolvable, current relative-volume authority for the pair."""

    def __init__(
        self,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        authority: ExternalRelativeVolumeAuthority,
    ) -> None:
        self.currentness_coordinator = coordinator
        self.authority = authority
        self.resolve_calls = 0

    def resolve_for_use(self, **kwargs: object) -> ExternalRelativeVolumeAuthority:
        del kwargs
        self.resolve_calls += 1
        return self.authority

    def is_current_for_use(
        self, authority: ExternalRelativeVolumeAuthority, *, now: datetime
    ) -> bool:
        del now
        return authority == self.authority

    def resolve_historical_for_decision(
        self, decision: ExternalPairUseDecisionV1
    ) -> ExternalRelativeVolumeAuthority | None:
        del decision
        return None


class _EvidenceProjection:
    """Fixture evidence store exposing exact-digest lookups only."""

    def __init__(
        self,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        records: dict[tuple[SealedExternalSubjectV1, str], tuple[tuple[str, object, object], ...]],
    ) -> None:
        self.coordinator = coordinator
        self._records = records

    def validated_record_digests_for(
        self, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[str, ...]:
        return tuple(item[0] for item in self._records.get((subject, policy_digest), ()))

    def _lookup(
        self, digest: str, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[object, object] | None:
        for item in self._records.get((subject, policy_digest), ()):
            if item[0] == digest:
                return (item[1], item[2])
        return None

    def record_for_current_use(
        self, digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[object, object] | None:
        return self._lookup(digest, subject, policy_digest)

    def record_for_locally_current_use(
        self, digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[object, object] | None:
        return self._lookup(digest, subject, policy_digest)


def _report_with_measured_dsm(
    original: ExternalArtifactInspectionReportV1,
) -> ExternalArtifactInspectionReportV1:
    ortho = original.measurement_payload.outcomes[0]
    dsm_binding = SealedArtifactBindingV1(artifact_id="dsm", observed_sha256=digest("d"))
    payload = original.measurement_payload.model_copy(
        update={
            "artifact_bindings": (*original.measurement_payload.artifact_bindings, dsm_binding),
            "outcomes": (
                *original.measurement_payload.outcomes,
                ArtifactInspectionOutcomeV1(
                    artifact_id="dsm",
                    observed_sha256=dsm_binding.observed_sha256,
                    outcome=ArtifactOutcome.MEASURED,
                    measurements=ortho.measurements,
                ),
            ),
        },
        deep=True,
    )
    return original.model_copy(
        update={
            "measurement_payload": payload,
            "measurement_payload_digest": None,
            "report_digest": None,
        },
        deep=True,
    ).sealed()


def _volume_pair_evaluator(
    tmp_path: Path, *, attested: bool | None
) -> tuple[
    ExternalUseEvaluator, SealedExternalSubjectV1, SealedExternalSubjectV1, _VolumeAuthority
]:
    """``attested`` None files no validated evidence; False files unattested evidence."""
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
        permitted_uses=("VISUAL_COMPARISON", "RELATIVE_VOLUME"),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=datetime.now(UTC) + timedelta(days=14),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    assert policy.policy_digest is not None
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    policy_authority = _PolicyAuthority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=policy_authority,
        authority_currentness_port=policy_authority.bind(coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)
    reports = {
        baseline: _report_with_measured_dsm(
            _report_for_subject(baseline, policy, request_id="pair-baseline")
        ),
        current: _report_with_measured_dsm(
            _report_for_subject(current, policy, request_id="pair-current")
        ),
    }
    records: dict[tuple[SealedExternalSubjectV1, str], tuple[tuple[str, object, object], ...]] = {}
    if attested is not None:
        for marker, value in (("e", baseline), ("f", current)):
            records[(value, policy.policy_digest)] = (
                (
                    digest(marker),
                    SimpleNamespace(evidence_record_digest=digest(marker)),
                    SimpleNamespace(
                        independent_attestation=object() if attested else None,
                        target_dsm_artifact_id="dsm",
                        target_dsm_observed_sha256=digest("d"),
                    ),
                ),
            )
    volume = _VolumeAuthority(
        coordinator,
        ExternalRelativeVolumeAuthority(
            zone=SealedZoneReferenceV1(
                zone_id="zone-1",
                revision=1,
                definition_digest=digest("1"),
                observed_crs_digest=digest("2"),
                observed_vertical_reference_digest=digest("3"),
            ),
            compatibility_mapping_digest=digest("4"),
            historical_authority_digest=digest("4"),
            synthetic_test_only=False,
        ),
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
            reports,
            {
                baseline: _receipt(reports[baseline], policy),
                current: _receipt(reports[current], policy),
            },
            coordinator,
        ),
        policy_registry=registry,
        evidence_validations=cast(
            ExternalEvidenceValidationStore, _EvidenceProjection(coordinator, records)
        ),
        coordinator=coordinator,
        relative_volume_authority=volume,
    )
    return evaluator, baseline, current, volume


def test_relative_volume_pair_names_unattested_evidence_not_missing_volume_authority(
    tmp_path: Path,
) -> None:
    """A resolvable mapping with unattested evidence must not claim the mapping is missing."""
    evaluator, baseline, current, volume = _volume_pair_evaluator(tmp_path, attested=False)

    decision = evaluator.request_pair(
        baseline,
        current,
        use="RELATIVE_VOLUME",
        zone_id="zone-1",
        idempotency_key="volume-unattested",
        principal=_principal(),
        now=NOW,
    )

    assert volume.resolve_calls == 1
    assert decision.verdict is DecisionVerdict.BLOCKED
    assert decision.reasons == ("EVIDENCE_INDEPENDENCE_UNATTESTED",)
    assert decision.remediations == ("ATTEST_INDEPENDENT_EVIDENCE",)
    assert decision.zone is None
    assert decision.compatibility_mapping_digest is None
    assert decision.evidence_record_digests == ()


def test_relative_volume_pair_without_validated_evidence_reports_binding_invalid(
    tmp_path: Path,
) -> None:
    evaluator, baseline, current, _volume = _volume_pair_evaluator(tmp_path, attested=None)

    decision = evaluator.request_pair(
        baseline,
        current,
        use="RELATIVE_VOLUME",
        zone_id="zone-1",
        idempotency_key="volume-no-evidence",
        principal=_principal(),
        now=NOW,
    )

    assert decision.verdict is DecisionVerdict.BLOCKED
    assert decision.reasons == ("EVIDENCE_RECORD_BINDING_INVALID",)
    assert decision.remediations == ("VALIDATE_INDEPENDENT_EVIDENCE",)


def test_relative_volume_pair_is_eligible_with_attested_current_evidence(tmp_path: Path) -> None:
    evaluator, baseline, current, volume = _volume_pair_evaluator(tmp_path, attested=True)

    decision = evaluator.request_pair(
        baseline,
        current,
        use="RELATIVE_VOLUME",
        zone_id="zone-1",
        idempotency_key="volume-attested",
        principal=_principal(),
        now=NOW,
    )

    assert decision.verdict is DecisionVerdict.ELIGIBLE
    assert decision.reasons == ("USE_ELIGIBLE",)
    assert decision.evidence_record_digests == (digest("e"), digest("f"))
    assert decision.zone == volume.authority.zone
    assert decision.compatibility_mapping_digest == digest("4")
