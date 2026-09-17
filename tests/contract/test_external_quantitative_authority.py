"""Contract boundary for the two-stage external quantitative authority."""

import hashlib
import importlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_quantitative_authority import (
    ExternalQuantitativeAuthorityCatalog,
    ExternalQuantitativeAuthorityParticipants,
    ExternalQuantitativeAuthorityRecoveryError,
    ExternalQuantitativeCatalogAuthorityBinding,
    ExternalQuantitativeCatalogAuthorityRecord,
    ExternalQuantitativeCompatibilityRecord,
    ExternalQuantitativeExecutionTemplate,
)
from ksi_core.external_validation_policy import PolicySelectionStatus
from ksi_core.work_areas import WorkAreaStatus
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

_NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _subject(work_order_id: str, label: str, *, site_id: str = "site-a") -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id=site_id,
        work_order_id=work_order_id,
        submission_id=f"submission-{label}",
        revision=1,
        submission_digest=_digest(f"submission-{label}"),
        manifest_digest=_digest(f"manifest-{label}"),
    )


def _binding(
    work_order_id: str, label: str, hour: int, *, site_id: str = "site-a"
) -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=_subject(work_order_id, label, site_id=site_id),
        inspection_report_digest=_digest(f"inspection-{label}"),
        dsm_artifact_id=f"dsm-{label}",
        observed_sha256=_digest(f"dsm-bytes-{label}"),
        observed_size_bytes=16,
        observed_crs_digest=_digest("crs"),
        observed_vertical_reference_digest=_digest("vertical"),
        captured_from=_NOW + timedelta(hours=hour),
        captured_to=_NOW + timedelta(hours=hour + 1),
    )


def _mapping(*, site_id: str = "site-a") -> ExternalQuantitativeCompatibilityRecord:
    return ExternalQuantitativeCompatibilityRecord(
        organization_id="org-a",
        site_id=site_id,
        baseline=_binding("work-baseline", "baseline", 0, site_id=site_id),
        current=_binding("work-current", "current", 2, site_id=site_id),
        zone_snapshot=ExternalVolumeZoneSnapshotV1(
            organization_id="org-a",
            site_id=site_id,
            work_area_id="work-area-a",
            polygon={
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]],
            },
            crs="EPSG:5186",
            observed_crs_digest=_digest("crs"),
            analysis_vertical_reference_digest=_digest("vertical"),
        ).sealed(),
        validation_policy_digest=_digest("validation-policy"),
        external_profile="external-geotiff-profile.v1",
        grammar_digest=_digest("grammar"),
        inspector_build_digest=_digest("inspector-build"),
        evidence_record_digests=(_digest("evidence-baseline"), _digest("evidence-current")),
        execution_policy_ref=_digest("execution-policy-authority"),
        valid_from=_NOW - timedelta(minutes=1),
        valid_until=_NOW + timedelta(minutes=10),
    ).sealed()


def _template() -> ExternalQuantitativeExecutionTemplate:
    policy = ExternalRelativeVolumeExecutionPolicyV1(
        policy_id="execution-policy-a",
        version=1,
        algorithm_build_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        threshold_m=0.1,
        minimum_common_valid_fraction=0.8,
        uncertainty_method="INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
        resource_envelope_digest=_digest("resources"),
        authority_record_digest=_digest("execution-policy-authority"),
        synthetic_test_only=False,
    ).sealed()
    return ExternalQuantitativeExecutionTemplate(
        execution_policy=policy,
        authorized_actor_ids=frozenset({"operator-a"}),
        valid_from=_NOW - timedelta(minutes=1),
        valid_until=_NOW + timedelta(minutes=5),
        maximum_zone_cell_count=1000,
        maximum_zone_area_m2=1000.0,
    )


def test_mapping_is_durable_before_decision_and_execution_is_durable_after_decision(
    tmp_path: Path,
) -> None:
    """Removing the post-decision snapshot must deny a fresh numeric request."""
    mapping = _mapping(site_id="site-b")
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=coordinator,
        mapping_admission_validator=lambda _record, _now: True,
        execution_template_resolver=lambda _record, _now: _template(),
    )
    catalog.admit_mapping(mapping, actor="authority-a", now=_NOW)

    resolved = catalog.resolve_for_use(
        baseline=mapping.baseline.subject,
        current=mapping.current.subject,
        zone_id="work-area-a",
        policy=cast(
            ExternalValidationPolicyV1,
            SimpleNamespace(policy_digest=mapping.validation_policy_digest),
        ),
        now=_NOW,
    )
    assert resolved is not None
    assert resolved.compatibility_mapping_digest == mapping.mapping_digest

    principal = Principal(
        principal_id="operator-a",
        kind=PrincipalKind.OPERATOR,
        organization_id="org-a",
        role=Role.ADMIN,
        device_id=None,
    )
    assert (
        catalog.activate_execution(
            decision_ref="decision-a",
            principal=principal,
            current_work_order_id="work-current",
            now=_NOW,
        )
        is None
    )

    catalog.bind_decision_resolver(
        lambda decision_id, principal, current_work_order_id: (
            {
                "decisionId": "decision-a",
                "decisionDigest": _digest("decision-a"),
                "organizationId": "org-a",
                "siteId": "site-b",
                "baseline": mapping.baseline.subject,
                "current": mapping.current.subject,
                "zoneDigest": mapping.zone_snapshot.definition_digest,
                "policyDigest": mapping.validation_policy_digest,
                "compatibilityMappingDigest": mapping.mapping_digest,
                "decisionUse": "RELATIVE_VOLUME",
                "decisionVerdict": "ELIGIBLE",
                "decidedAt": _NOW,
            }
            if (
                decision_id,
                principal.organization_id,
                current_work_order_id,
            )
            == ("decision-a", "org-a", "work-current")
            else None
        )
    )
    execution = catalog.activate_execution(
        decision_ref="decision-a",
        principal=principal,
        current_work_order_id="work-current",
        now=_NOW,
    )
    assert execution is not None
    assert (
        catalog.resolve_for_issue(
            principal=principal,
            current_work_order_id="work-current",
            decision_ref="decision-a",
            now=_NOW,
        )
        == execution
    )

    catalog.revoke_execution(
        execution.historical_authority_digest,
        actor="authority-a",
        now=_NOW + timedelta(minutes=1),
    )
    assert (
        catalog.resolve_for_issue(
            principal=principal,
            current_work_order_id="work-current",
            decision_ref="decision-a",
            now=_NOW + timedelta(minutes=1),
        )
        is None
    )


def test_replay_preserves_pre_revocation_execution_without_recreating_it(tmp_path: Path) -> None:
    """Replacing historical replay with current state would erase a valid issue."""
    path = tmp_path / "quantitative-authority.jsonl"
    mapping = _mapping()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=coordinator,
        mapping_admission_validator=lambda _record, _now: True,
        execution_template_resolver=lambda _record, _now: _template(),
    )
    catalog.admit_mapping(mapping, actor="authority-a", now=_NOW)
    principal = Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")
    catalog.bind_decision_resolver(
        lambda _decision_id, _principal, _current_work_order_id: {
            "decisionId": "decision-a",
            "decisionDigest": _digest("decision-a"),
            "organizationId": "org-a",
            "siteId": "site-a",
            "baseline": mapping.baseline.subject,
            "current": mapping.current.subject,
            "zoneDigest": mapping.zone_snapshot.definition_digest,
            "policyDigest": mapping.validation_policy_digest,
            "compatibilityMappingDigest": mapping.mapping_digest,
            "decisionUse": "RELATIVE_VOLUME",
            "decisionVerdict": "ELIGIBLE",
            "decidedAt": _NOW,
        }
    )
    execution = catalog.activate_execution(
        decision_ref="decision-a",
        principal=principal,
        current_work_order_id="work-current",
        now=_NOW,
    )
    assert execution is not None
    assert catalog.revoke_mapping(
        mapping.mapping_digest or "", actor="authority-a", now=_NOW + timedelta(minutes=1)
    )
    catalog._journal.close()

    recovered = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    assert (
        recovered.resolve_historical(
            historical_authority_digest=execution.historical_authority_digest,
            decision_id="decision-a",
            decision_digest=_digest("decision-a"),
            issued_at=_NOW,
            now=_NOW + timedelta(minutes=2),
        )
        == execution
    )
    assert (
        recovered.resolve_historical(
            historical_authority_digest=execution.historical_authority_digest,
            decision_id="decision-a",
            decision_digest=_digest("decision-a"),
            issued_at=_NOW + timedelta(minutes=2),
            now=_NOW + timedelta(minutes=2),
        )
        is None
    )


def test_execution_uses_its_exact_decision_mapping_when_another_mapping_shares_work_order(
    tmp_path: Path,
) -> None:
    """A WorkOrder-only mapping lookup could issue under another pair's authority."""
    first = _mapping()
    second = replace(
        _mapping(),
        baseline=_binding("work-baseline", "baseline-other", 0),
        zone_snapshot=ExternalVolumeZoneSnapshotV1(
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-b",
            polygon={
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]],
            },
            crs="EPSG:5186",
            observed_crs_digest=_digest("crs"),
            analysis_vertical_reference_digest=_digest("vertical"),
        ).sealed(),
        evidence_record_digests=(_digest("evidence-baseline-other"), _digest("evidence-current")),
        compatibility_rule_digest=None,
        mapping_record_digest=None,
    ).sealed()
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
        execution_template_resolver=lambda _record, _now: _template(),
    )
    catalog.admit_mapping(first, actor="authority-a", now=_NOW)
    catalog.admit_mapping(second, actor="authority-a", now=_NOW)
    principal = Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")
    catalog.bind_decision_resolver(
        lambda _decision_id, _principal, _current_work_order_id: {
            "decisionId": "decision-a",
            "decisionDigest": _digest("decision-a"),
            "organizationId": "org-a",
            "siteId": "site-a",
            "baseline": first.baseline.subject,
            "current": first.current.subject,
            "zoneDigest": first.zone_snapshot.definition_digest,
            "policyDigest": first.validation_policy_digest,
            "compatibilityMappingDigest": first.mapping_digest,
            "decisionUse": "RELATIVE_VOLUME",
            "decisionVerdict": "ELIGIBLE",
            "decidedAt": _NOW,
        }
    )

    execution = catalog.activate_execution(
        decision_ref="decision-a",
        principal=principal,
        current_work_order_id="work-current",
        now=_NOW,
    )
    assert execution is not None
    assert execution.compatibility_mapping_digest == first.mapping_digest

    catalog.bind_decision_resolver(
        lambda _decision_id, _principal, _current_work_order_id: {
            "decisionId": "decision-a",
            "decisionDigest": _digest("decision-a"),
            "organizationId": "org-a",
            "siteId": "site-a",
            "baseline": second.baseline.subject,
            "current": second.current.subject,
            "zoneDigest": second.zone_snapshot.definition_digest,
            "policyDigest": second.validation_policy_digest,
            "compatibilityMappingDigest": second.mapping_digest,
            "decisionUse": "RELATIVE_VOLUME",
            "decisionVerdict": "ELIGIBLE",
            "decidedAt": _NOW,
        }
    )
    assert (
        catalog.resolve_for_issue(
            principal=principal,
            current_work_order_id="work-current",
            decision_ref="decision-a",
            now=_NOW,
        )
        is None
    )


def test_mapping_is_not_usable_before_its_durable_activation(tmp_path: Path) -> None:
    """A pre-activation decision cannot borrow a record's wider validity interval."""
    mapping = _mapping()
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
    )
    assert catalog.admit_mapping(mapping, actor="authority-a", now=_NOW) is not None

    assert (
        catalog.resolve_for_use(
            baseline=mapping.baseline.subject,
            current=mapping.current.subject,
            zone_id="work-area-a",
            policy=cast(
                ExternalValidationPolicyV1,
                SimpleNamespace(policy_digest=mapping.validation_policy_digest),
            ),
            now=_NOW - timedelta(seconds=30),
        )
        is None
    )


def test_execution_rejects_decision_created_after_activation_time(tmp_path: Path) -> None:
    """A future exact decision cannot backdate a numeric execution authority."""
    mapping = _mapping()
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
        execution_template_resolver=lambda _record, _now: _template(),
    )
    assert catalog.admit_mapping(mapping, actor="authority-a", now=_NOW) is not None
    principal = Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")
    catalog.bind_decision_resolver(
        lambda _decision_id, _principal, _current_work_order_id: {
            "decisionId": "decision-a",
            "decisionDigest": _digest("decision-a"),
            "organizationId": mapping.organization_id,
            "siteId": mapping.site_id,
            "baseline": mapping.baseline.subject,
            "current": mapping.current.subject,
            "zoneDigest": mapping.zone_snapshot.definition_digest,
            "policyDigest": mapping.validation_policy_digest,
            "compatibilityMappingDigest": mapping.mapping_digest,
            "decisionUse": "RELATIVE_VOLUME",
            "decisionVerdict": "ELIGIBLE",
            "decidedAt": _NOW + timedelta(seconds=1),
        }
    )

    assert (
        catalog.activate_execution(
            decision_ref="decision-a",
            principal=principal,
            current_work_order_id="work-current",
            now=_NOW,
        )
        is None
    )


def test_compatibility_rule_digest_is_stable_before_evidence_but_record_digest_is_not() -> None:
    """Policy approves predicates before any result-specific evidence exists."""
    mapping = _mapping()
    changed_policy = replace(
        mapping,
        validation_policy_digest=_digest("validation-policy-successor"),
        mapping_record_digest=None,
    ).sealed()
    changed_evidence = replace(
        mapping,
        evidence_record_digests=(_digest("evidence-baseline-other"), _digest("evidence-current")),
        compatibility_rule_digest=None,
        mapping_record_digest=None,
    ).sealed()

    assert mapping.compatibility_rule_digest == changed_policy.compatibility_rule_digest
    assert mapping.mapping_record_digest != changed_policy.mapping_record_digest
    assert mapping.compatibility_rule_digest == changed_evidence.compatibility_rule_digest
    assert mapping.mapping_record_digest != changed_evidence.mapping_record_digest


def test_default_compatibility_rule_descriptor_is_callable_before_any_mapping_exists() -> None:
    """Policy can pre-authorize stable predicates without inventing result facts."""
    module = importlib.import_module("ksi_core.external_quantitative_authority")
    descriptor_type = getattr(module, "CompatibilityRuleDescriptorV1", None)

    assert descriptor_type is not None
    descriptor = descriptor_type()
    payload = descriptor.canonical_payload()

    assert descriptor.canonical_digest() == _mapping().compatibility_rule_digest
    assert set(payload) == {
        "externalProfile",
        "requiresSameGrammarDigest",
        "requiresSameInspectorBuildDigest",
        "requiresSameObservedCrsDigest",
        "requiresSameObservedVerticalReferenceDigest",
        "requiresIndependentMeasuredCheckpointPerEpoch",
        "requiresOrderedNonOverlappingCaptureIntervals",
        "requiresExactWorkAreaMatch",
    }


def test_catalog_authority_port_type_failure_closes_mapping_admission() -> None:
    """An invalid trust-port response cannot turn into a positive mapping authority."""

    class _InvalidCatalogAuthorityPort:
        def resolve(self, _digest: str, _now: datetime) -> object:
            return object()

    mapping = _mapping()
    catalog_binding = ExternalQuantitativeCatalogAuthorityBinding(
        authority_port=cast(Any, _InvalidCatalogAuthorityPort()),
        catalog_body_digest=_digest("catalog"),
        organization_id="org-a",
        administration_actor_id="catalog-admin",
    )

    assert not catalog_binding.permits(mapping, _NOW)


def test_concrete_participant_witnesses_pre_authorize_rule_not_full_mapping_record(
    tmp_path: Path,
) -> None:
    """Production admission reads immutable observed witnesses and the policy's rule digest."""

    @dataclass(frozen=True)
    class _Vertical:
        digest: str

        def canonical_digest(self) -> str:
            return self.digest

    @dataclass(frozen=True)
    class _Measurements:
        observed_crs_digest: str
        observed_vertical_reference: _Vertical

    @dataclass(frozen=True)
    class _Outcome:
        artifact_id: str
        observed_sha256: str
        outcome: ArtifactOutcome
        measurements: _Measurements

    @dataclass(frozen=True)
    class _Report:
        inspector_build_digest: str
        inspection_policy_digest: str
        measurement_payload: object

    @dataclass(frozen=True)
    class _Entry:
        artifact_id: str
        kind: ProcessingArtifactKind
        observed_sha256: str
        observed_size_bytes: int

    @dataclass(frozen=True)
    class _Manifest:
        entries: tuple[_Entry, ...]

    @dataclass(frozen=True)
    class _Revision:
        manifest: _Manifest
        submission: object

    @dataclass(frozen=True)
    class _InputDeclaration:
        capture_started_at: datetime
        capture_ended_at: datetime

    @dataclass(frozen=True)
    class _Submission:
        input_declaration: _InputDeclaration

    @dataclass(frozen=True)
    class _Area:
        site_id: str
        polygon: object
        crs: str
        status: WorkAreaStatus

    @dataclass(frozen=True)
    class _EvidenceRecord:
        measurement_payload: object
        target_dsm_observed_sha256: str

    @dataclass(frozen=True)
    class _EvidenceContext:
        target_dsm_artifact_id: str
        target_dsm_observed_sha256: str
        synthetic_test_only: bool
        independent_attestation: object | None

    class _Reconstruction:
        coordinator = ExternalAuthorityCurrentnessCoordinator()

        def __init__(self, revisions: dict[Any, Any]) -> None:
            self._revisions = revisions

        def resolve_sealed_subject(self, subject: Any) -> Any:
            return self._revisions.get(subject)

    class _Inspections:
        coordinator = ExternalAuthorityCurrentnessCoordinator()

        def __init__(self, reports: dict[Any, Any]) -> None:
            self._reports = reports

        def historical_report(self, subject: Any, *, report_digest: str, policy_digest: str) -> Any:
            return self._reports.get((subject, report_digest, policy_digest))

    class _PolicyRegistry:
        coordinator = ExternalAuthorityCurrentnessCoordinator()

        def __init__(self, policy: Any) -> None:
            self._policy = policy

        def select_for_use(self, use: str, subjects: tuple[Any, Any]) -> Any:
            assert use == "RELATIVE_VOLUME"
            assert subjects == (mapping.baseline.subject, mapping.current.subject)
            return SimpleNamespace(status=PolicySelectionStatus.ACTIVE, policy=self._policy)

        def locally_current_use_permitted(
            self, digest: str, *, use: str, subjects: tuple[Any, Any], at: datetime
        ) -> bool:
            del at
            return (
                digest == self._policy.policy_digest
                and use == "RELATIVE_VOLUME"
                and subjects == (mapping.baseline.subject, mapping.current.subject)
            )

        def resolve(self, digest: str) -> Any:
            return SimpleNamespace(
                status=(
                    PolicySelectionStatus.ACTIVE if digest == self._policy.policy_digest else None
                ),
                policy=self._policy if digest == self._policy.policy_digest else None,
            )

    class _EvidenceValidations:
        coordinator = ExternalAuthorityCurrentnessCoordinator()

        def __init__(self, records: dict[Any, Any]) -> None:
            self._records = records

        def record_for_current_use(self, digest: str, *, subject: Any, policy_digest: str) -> Any:
            return self._records.get((digest, subject, policy_digest))

        def record_for_locally_current_use(
            self, digest: str, *, subject: Any, policy_digest: str
        ) -> Any:
            return self._records.get((digest, subject, policy_digest))

    class _WorkAreas:
        coordinator = ExternalAuthorityCurrentnessCoordinator()

        def get(self, work_area_id: str) -> Any:
            return area if work_area_id == mapping.zone_snapshot.work_area_id else None

    class _CatalogAuthorityPort:
        def __init__(self, record: Any) -> None:
            self._record = record

        def resolve(self, digest: str, now: datetime) -> Any:
            del now
            return self._record if digest == self._record.digest else None

    class _CatalogCurrentness:
        def __init__(self, coordinator: Any, record: Any) -> None:
            self.coordinator = coordinator
            self._record = record

        def is_current(self, record: Any, now: datetime) -> bool:
            return record == self._record and record.is_active_at(now)

    catalog_record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=_digest("approved-catalog"),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=_NOW - timedelta(minutes=1),
        active_until=_NOW + timedelta(minutes=1),
        synthetic_test_only=False,
    ).sealed()
    assert catalog_record.digest is not None
    mapping = replace(
        _mapping(),
        execution_policy_ref=catalog_record.digest,
        compatibility_rule_digest=None,
        mapping_record_digest=None,
    ).sealed()
    vertical = _Vertical(mapping.baseline.observed_vertical_reference_digest)
    revisions = {}
    reports = {}
    evidence_records = {}
    for binding, evidence_digest in zip(
        (mapping.baseline, mapping.current), mapping.evidence_record_digests, strict=True
    ):
        revisions[binding.subject] = _Revision(
            _Manifest(
                (
                    _Entry(
                        binding.dsm_artifact_id,
                        ProcessingArtifactKind.DSM,
                        binding.observed_sha256.removeprefix("sha256:"),
                        binding.observed_size_bytes,
                    ),
                )
            ),
            _Submission(
                _InputDeclaration(
                    capture_started_at=binding.captured_from,
                    capture_ended_at=binding.captured_to,
                )
            ),
        )
        reports[
            (binding.subject, binding.inspection_report_digest, mapping.validation_policy_digest)
        ] = _Report(
            mapping.inspector_build_digest,
            mapping.validation_policy_digest,
            SimpleNamespace(
                outcomes=(
                    _Outcome(
                        binding.dsm_artifact_id,
                        binding.observed_sha256,
                        ArtifactOutcome.MEASURED,
                        _Measurements(binding.observed_crs_digest, vertical),
                    ),
                )
            ),
        )
        evidence_records[(evidence_digest, binding.subject, mapping.validation_policy_digest)] = (
            _EvidenceRecord(object(), binding.observed_sha256),
            _EvidenceContext(binding.dsm_artifact_id, binding.observed_sha256, False, object()),
        )
    area = _Area(
        mapping.site_id,
        mapping.zone_snapshot.polygon,
        mapping.zone_snapshot.crs,
        WorkAreaStatus.ACTIVE,
    )
    policy = SimpleNamespace(
        policy_digest=mapping.validation_policy_digest,
        synthetic_test_only=False,
        grammar_digest=mapping.grammar_digest,
        parser_build_digest=mapping.inspector_build_digest,
        resource_envelope=object(),
        resource_envelope_digest=_digest("resource-envelope"),
        compatibility_mapping_digests=(mapping.compatibility_rule_digest,),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    catalog_binding = ExternalQuantitativeCatalogAuthorityBinding(
        authority_port=_CatalogAuthorityPort(catalog_record),
        catalog_body_digest=catalog_record.catalog_body_digest,
        organization_id=mapping.organization_id,
        administration_actor_id="catalog-admin",
        currentness_port=_CatalogCurrentness(coordinator, catalog_record),
    )
    for witness in (
        reconstruction := _Reconstruction(revisions),
        inspections := _Inspections(reports),
        policies := _PolicyRegistry(policy),
        validations := _EvidenceValidations(evidence_records),
        areas := _WorkAreas(),
    ):
        witness.coordinator = coordinator
    participants = ExternalQuantitativeAuthorityParticipants(
        reconstruction=cast(Any, reconstruction),
        inspections=cast(Any, inspections),
        policy_registry=cast(Any, policies),
        evidence_validations=cast(Any, validations),
        work_areas=cast(Any, areas),
        catalog_authority=catalog_binding,
    )
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=coordinator,
        participants=participants,
    )

    assert catalog.admit_mapping(mapping, actor="authority-a", now=_NOW) == mapping
    assert catalog.admit_mapping(mapping, actor="authority-a", now=_NOW) == mapping
    revisions[mapping.baseline.subject] = replace(
        revisions[mapping.baseline.subject],
        submission=_Submission(
            _InputDeclaration(
                capture_started_at=mapping.baseline.captured_from + timedelta(minutes=1),
                capture_ended_at=mapping.baseline.captured_to,
            )
        ),
    )
    capture_mismatch = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "capture-mismatch-quantitative-authority.jsonl"),
        currentness_coordinator=coordinator,
        participants=participants,
    )
    assert capture_mismatch.admit_mapping(mapping, actor="authority-a", now=_NOW) is None
    policy.compatibility_mapping_digests = (mapping.mapping_record_digest,)
    rejected = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "rejected-quantitative-authority.jsonl"),
        currentness_coordinator=coordinator,
        participants=participants,
    )
    assert rejected.admit_mapping(mapping, actor="authority-a", now=_NOW) is None


def test_mapping_evidence_binding_requires_an_independent_attestation() -> None:
    """Admission applies the same independence rule as the pair decision (spec V1)."""
    binding = _mapping().baseline
    record = SimpleNamespace(
        measurement_payload=object(), target_dsm_observed_sha256=binding.observed_sha256
    )

    def context(attestation: object | None) -> SimpleNamespace:
        return SimpleNamespace(
            target_dsm_artifact_id=binding.dsm_artifact_id,
            target_dsm_observed_sha256=binding.observed_sha256,
            synthetic_test_only=False,
            independent_attestation=attestation,
        )

    matches = ExternalQuantitativeAuthorityParticipants._evidence_matches_binding
    assert matches(binding, (record, context(object())))
    assert not matches(binding, (record, context(None)))
    assert not matches(binding, None)


def test_single_mapping_is_durable_and_resolves_only_for_its_subject_and_zone(
    tmp_path: Path,
) -> None:
    """Single-epoch mappings live beside pair mappings without leaking into them."""
    from test_external_single_volume_authority import _NOW as _SV_NOW
    from test_external_single_volume_authority import single_mapping

    mapping = single_mapping()
    assert mapping.mapping_digest is not None
    path = tmp_path / "quantitative-authority.jsonl"
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
    )
    assert catalog.admit_single_mapping(mapping, actor="authority-a", now=_SV_NOW) == mapping
    assert catalog.admit_single_mapping(mapping, actor="authority-a", now=_SV_NOW) == mapping
    policy = cast(
        ExternalValidationPolicyV1,
        SimpleNamespace(policy_digest=mapping.validation_policy_digest),
    )

    resolved = catalog.resolve_single_for_use(
        subject=mapping.target.subject, zone_id="work-area-a", policy=policy, now=_SV_NOW
    )
    assert resolved is not None
    assert resolved.compatibility_mapping_digest == mapping.mapping_digest
    assert resolved.zone == mapping.zone_snapshot.to_zone_reference()
    assert catalog.is_current_for_single_use(resolved, now=_SV_NOW)
    port = catalog.single_mapping_port
    assert port.currentness_coordinator is catalog.currentness_coordinator
    assert port.is_current_for_use(resolved, now=_SV_NOW)
    assert (
        catalog.resolve_single_for_use(
            subject=mapping.target.subject, zone_id="work-area-other", policy=policy, now=_SV_NOW
        )
        is None
    )
    assert (
        catalog.resolve_for_use(
            baseline=mapping.target.subject,
            current=mapping.target.subject,
            zone_id="work-area-a",
            policy=policy,
            now=_SV_NOW,
        )
        is None
    )

    revoked_at = _SV_NOW + timedelta(seconds=1)
    assert catalog.revoke_single_mapping(
        mapping.mapping_digest, actor="authority-a", now=revoked_at
    )
    assert not catalog.is_current_for_single_use(resolved, now=revoked_at)
    assert not catalog.revoke_mapping(mapping.mapping_digest, actor="authority-a", now=revoked_at)
    catalog._journal.close()  # noqa: SLF001 - reopen the same durable journal.

    reopened = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
    )
    assert [event["kind"] for event in reopened._journal.replay()] == [  # noqa: SLF001
        "external-quantitative-single-mapping-activated",
        "external-quantitative-single-mapping-revoked",
    ]
    assert (
        reopened.resolve_single_for_use(
            subject=mapping.target.subject, zone_id="work-area-a", policy=policy, now=revoked_at
        )
        is None
    )
    assert (
        reopened.resolve_single_for_use(
            subject=mapping.target.subject, zone_id="work-area-a", policy=policy, now=_SV_NOW
        )
        is not None
    )


def test_single_mapping_admission_fails_closed_without_validator_approval(
    tmp_path: Path,
) -> None:
    from test_external_single_volume_authority import _NOW as _SV_NOW
    from test_external_single_volume_authority import single_mapping

    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: False,
    )
    assert catalog.admit_single_mapping(single_mapping(), actor="authority-a", now=_SV_NOW) is None
    assert list(catalog._journal.replay()) == []  # noqa: SLF001


def _single_execution_fixture() -> tuple[Any, Any, Any]:
    from ksi_core.domains.external.quantity.external_quantitative_authority import (
        ExternalQuantitativeSingleExecutionTemplate,
    )
    from ksi_event_contracts.external_artifact_validation import DecisionVerdict
    from ksi_event_contracts.external_single_volume import (
        ExternalSingleVolumeDecisionV1,
        ExternalSingleVolumeExecutionPolicyV1,
    )
    from test_external_single_volume_authority import _NOW as SV_NOW
    from test_external_single_volume_authority import single_mapping

    mapping = single_mapping()
    decision = ExternalSingleVolumeDecisionV1(
        decision_id="single-decision-a",
        subject=mapping.target.subject,
        subject_digest=mapping.target.subject.canonical_digest(),
        policy_digest=mapping.validation_policy_digest,
        inspection_report_digest=mapping.target.inspection_report_digest,
        evidence_record_digests=mapping.evidence_record_digests,
        zone=mapping.zone_snapshot.to_zone_reference(),
        compatibility_mapping_digest=mapping.mapping_digest,
        verdict=DecisionVerdict.ELIGIBLE,
        reasons=("USE_ELIGIBLE",),
        remediations=("CURRENT_DEPENDENCIES_RETAINED",),
        decided_at=SV_NOW,
    ).sealed()
    policy = ExternalSingleVolumeExecutionPolicyV1(
        policy_id="single-execution-policy-a",
        version=1,
        algorithm_build_digest=_digest("single-algorithm"),
        config_digest=_digest("single-config"),
        threshold_m=0.0,
        minimum_common_valid_fraction=0.8,
        minimum_boundary_valid_fraction=0.5,
        uncertainty_method="SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1",
        base_surface_method="BOUNDARY_LINEAR_INTERPOLATION_V1",
        resource_envelope_digest=_digest("resources"),
        authority_record_digest=mapping.execution_policy_ref,
        synthetic_test_only=False,
    ).sealed()
    template = ExternalQuantitativeSingleExecutionTemplate(
        execution_policy=policy,
        authorized_actor_ids=frozenset({"operator-a"}),
        valid_from=SV_NOW - timedelta(minutes=1),
        valid_until=SV_NOW + timedelta(minutes=5),
        maximum_zone_cell_count=1000,
        maximum_zone_area_m2=1000.0,
    )
    return mapping, decision, template


def _operator() -> Principal:
    return Principal(
        principal_id="operator-a",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
    )


def test_single_execution_is_activated_after_decision_and_revocable(tmp_path: Path) -> None:
    from test_external_single_volume_authority import _NOW as SV_NOW

    mapping, decision, template = _single_execution_fixture()
    path = tmp_path / "quantitative-authority.jsonl"
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
        single_execution_template_resolver=lambda _record, _now: template,
    )
    assert catalog.admit_single_mapping(mapping, actor="authority-a", now=SV_NOW) == mapping
    work_order_id = mapping.target.subject.work_order_id
    assert (
        catalog.resolve_single_for_issue(
            principal=_operator(),
            current_work_order_id=work_order_id,
            decision_ref=decision.decision_id,
            now=SV_NOW,
        )
        is None
    )
    catalog.bind_single_decision_resolver(
        lambda decision_id, _principal, _order: (
            decision if decision_id == decision.decision_id else None
        )
    )
    authority = catalog.activate_single_execution(
        decision_ref=decision.decision_id,
        principal=_operator(),
        current_work_order_id=work_order_id,
        now=SV_NOW,
    )
    assert authority is not None
    assert authority.target == mapping.target
    assert authority.target_rmse_m is None  # the test validator carries no evidence record
    assert authority.execution_policy == template.execution_policy
    port = catalog.single_execution_port
    assert (
        port.resolve_for_issue(
            principal=_operator(),
            current_work_order_id=work_order_id,
            decision_ref=decision.decision_id,
            now=SV_NOW,
        )
        == authority
    )
    with port.guard_current(authority=authority, principal=_operator(), now=SV_NOW) as guarded:
        assert guarded == authority
    assert (
        port.resolve_historical(
            historical_authority_digest=authority.historical_authority_digest,
            decision_id=decision.decision_id,
            decision_digest=decision.decision_digest or "",
            issued_at=SV_NOW,
            now=SV_NOW,
        )
        == authority
    )
    later = SV_NOW + timedelta(seconds=1)
    assert catalog.revoke_single_execution(
        authority.historical_authority_digest, actor="authority-a", now=later
    )
    with port.guard_current(authority=authority, principal=_operator(), now=later) as guarded:
        assert guarded is None
    catalog._journal.close()  # noqa: SLF001 - reopen the same durable journal.

    reopened = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
    )
    assert [event["kind"] for event in reopened._journal.replay()] == [  # noqa: SLF001
        "external-quantitative-single-mapping-activated",
        "external-quantitative-single-execution-activated",
        "external-quantitative-single-execution-revoked",
    ]

    class _Decisions:
        def resolve_current_pair_for_issue(self, *_a: Any, **_k: Any) -> None:
            return None

        def resolve_historical_pair(self, **_k: Any) -> None:
            return None

        def resolve_current_single_volume_for_issue(self, *_a: Any, **_k: Any) -> Any:
            return decision

        def resolve_historical_single_volume(self, **_k: Any) -> Any:
            return decision

    reopened.bind_decision_store(_Decisions())

    class _NoSingleDecision(_Decisions):
        def resolve_historical_single_volume(self, **_k: Any) -> Any:
            return None

    with pytest.raises(ExternalQuantitativeAuthorityRecoveryError, match="single execution"):
        reopened.bind_decision_store(_NoSingleDecision())
    reopened._journal.close()  # noqa: SLF001


def test_single_execution_refuses_a_decision_that_does_not_bind_the_mapping(
    tmp_path: Path,
) -> None:
    from test_external_single_volume_authority import _NOW as SV_NOW

    mapping, decision, template = _single_execution_fixture()
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
        single_execution_template_resolver=lambda _record, _now: template,
    )
    catalog.admit_single_mapping(mapping, actor="authority-a", now=SV_NOW)
    wrong_zone = decision.model_copy(
        update={
            "zone": decision.zone.model_copy(update={"zone_id": "other-zone"})
            if decision.zone
            else None,
            "decision_digest": None,
        },
        deep=True,
    ).sealed()
    catalog.bind_single_decision_resolver(lambda *_args: wrong_zone)
    assert (
        catalog.activate_single_execution(
            decision_ref=decision.decision_id,
            principal=_operator(),
            current_work_order_id=mapping.target.subject.work_order_id,
            now=SV_NOW,
        )
        is None
    )
    unauthorized = Principal(
        principal_id="someone-else",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
    )
    catalog.bind_single_decision_resolver(lambda *_args: decision)
    assert (
        catalog.activate_single_execution(
            decision_ref=decision.decision_id,
            principal=unauthorized,
            current_work_order_id=mapping.target.subject.work_order_id,
            now=SV_NOW,
        )
        is None
    )
    assert [e["kind"] for e in catalog._journal.replay()] == [  # noqa: SLF001
        "external-quantitative-single-mapping-activated"
    ]
