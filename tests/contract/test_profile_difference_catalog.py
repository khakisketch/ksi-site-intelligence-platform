"""Production profile authority records stay isolated from volume mappings."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ksi_core.domains.external.quantity.external_profile_difference_authorities import (
    ExternalProfileDifferenceAuthority,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_quantitative_authority import (
    DuplicateActiveMappingError,
    ExternalQuantitativeAuthorityCatalog,
)
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalPairUseDecisionV1,
)
from test_external_quantitative_authority import _NOW, _digest, _mapping


class _Participants:
    """A narrow Core participant double for exercising catalog lifecycle semantics."""

    def __init__(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self.catalog_authority = SimpleNamespace(
            organization_id="org-a",
            administration_actor_id="catalog-admin",
            currentness_port=SimpleNamespace(coordinator=coordinator),
        )
        self.allowed = True
        self.selections: list[str] = []

    def current_snapshot(self, record: object, now: object, *, use: str) -> object | None:
        del now
        self.selections.append(use)
        return record if self.allowed and use == "PROFILE_DIFFERENCE" else None

    def locally_current(
        self, record: object, snapshot: object, now: object, *, use: str
    ) -> bool:
        del now
        return self.allowed and use == "PROFILE_DIFFERENCE" and record == snapshot


def _profile_decision(record: Any) -> ExternalPairUseDecisionV1:
    return ExternalPairUseDecisionV1(
        decision_id="profile-decision-1",
        baseline_subject=record.baseline.subject,
        baseline_subject_digest=record.baseline.subject.canonical_digest(),
        current_subject=record.current.subject,
        current_subject_digest=record.current.subject.canonical_digest(),
        use="PROFILE_DIFFERENCE",
        policy_digest=record.validation_policy_digest,
        baseline_inspection_report_digest=record.baseline.inspection_report_digest,
        current_inspection_report_digest=record.current.inspection_report_digest,
        baseline_artifact_id=record.baseline.dsm_artifact_id,
        baseline_source_sha256=record.baseline.observed_sha256,
        current_artifact_id=record.current.dsm_artifact_id,
        current_source_sha256=record.current.observed_sha256,
        profile_comparison_binding_digest=_digest("saved-profile-comparison-binding"),
        profile_work_area_id=record.zone_snapshot.work_area_id,
        evidence_record_digests=record.evidence_record_digests,
        compatibility_mapping_digest=record.mapping_digest,
        verdict=DecisionVerdict.ELIGIBLE,
        reasons=("PROFILE_DIFFERENCE_ELIGIBLE",),
        remediations=("RETAIN_PROFILE_DIFFERENCE_EVIDENCE",),
        decided_at=_NOW,
    ).sealed()


def _select(port: Any, record: Any, *, now: object, work_area_id: str | None = None) -> Any:
    return port.resolve_for_use(
        baseline=record.baseline.subject,
        current=record.current.subject,
        baseline_artifact_id=record.baseline.dsm_artifact_id,
        baseline_source_sha256=record.baseline.observed_sha256,
        current_artifact_id=record.current.dsm_artifact_id,
        current_source_sha256=record.current.observed_sha256,
        policy=SimpleNamespace(
            policy_digest=record.validation_policy_digest,
            synthetic_test_only=False,
            compatibility_mapping_digests=(record.compatibility_rule_digest,),
        ),
        baseline_capture_started_at=record.baseline.captured_from,
        baseline_capture_ended_at=record.baseline.captured_to,
        current_capture_started_at=record.current.captured_from,
        current_capture_ended_at=record.current.captured_to,
        observed_crs_digest=record.baseline.observed_crs_digest,
        observed_vertical_reference_digest=(
            record.baseline.observed_vertical_reference_digest
        ),
        now=now,
        work_area_id=work_area_id,
    )


def test_profile_mapping_is_independently_admitted_current_and_revocable(
    tmp_path: Path,
) -> None:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    participants = _Participants(coordinator)
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=coordinator,
        participants=cast(Any, participants),
    )
    record = _mapping()
    port = catalog.profile_difference_port()

    assert _select(port, record, now=_NOW, work_area_id="work-area-a") is None
    assert catalog.admit_profile_mapping(record, actor="wrong-actor", now=_NOW) is None
    admitted = catalog.admit_profile_mapping(record, actor="catalog-admin", now=_NOW)
    assert admitted == record
    participants.allowed = False
    assert catalog.admit_profile_mapping(record, actor="catalog-admin", now=_NOW) == record
    assert participants.selections == ["PROFILE_DIFFERENCE"]
    participants.allowed = True

    authority = _select(port, record, now=_NOW, work_area_id="work-area-a")
    assert isinstance(authority, ExternalProfileDifferenceAuthority)
    assert authority.synthetic_test_only is False
    assert authority.compatibility_mapping_digest == record.mapping_digest
    assert authority.historical_authority_digest == record.mapping_digest
    assert authority.compatibility_rule_digest == record.compatibility_rule_digest
    assert authority.evidence_record_digests == record.evidence_record_digests
    assert _select(port, record, now=_NOW, work_area_id="different-area") is None
    assert _select(port, record, now=_NOW, work_area_id=None) is None
    assert port.is_current_for_use(authority, now=_NOW)
    participants.allowed = False
    assert not port.is_current_for_use(authority, now=_NOW)
    participants.allowed = True

    conflicting_record = replace(
        record,
        valid_until=record.valid_until + timedelta(minutes=1),
        mapping_record_digest=None,
    ).sealed()
    with pytest.raises(DuplicateActiveMappingError, match="profile mapping"):
        catalog.admit_profile_mapping(conflicting_record, actor="catalog-admin", now=_NOW)

    decision = _profile_decision(record)
    wrong_evidence_decision = decision.model_copy(
        update={
            "evidence_record_digests": (_digest("wrong-a"), _digest("wrong-b")),
            "decision_digest": None,
        },
        deep=True,
    ).sealed()
    assert port.resolve_historical_for_decision(wrong_evidence_decision) is None
    revoked_at = record.valid_until + timedelta(seconds=1)
    assert not catalog.revoke_profile_mapping(
        record.mapping_digest or "", actor="wrong-actor", now=revoked_at
    )
    assert catalog.revoke_profile_mapping(
        record.mapping_digest or "", actor="catalog-admin", now=revoked_at
    )
    assert (
        _select(port, record, now=revoked_at + timedelta(seconds=1), work_area_id="work-area-a")
        is None
    )
    assert not port.is_current_for_use(authority, now=revoked_at + timedelta(seconds=1))
    # A decision made while the signed mapping was current remains verifiable
    # after a later revocation.
    assert port.resolve_historical_for_decision(decision) == authority

    catalog._journal.close()  # noqa: SLF001 - reopen to verify retained lifecycle history.
    recovered = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=coordinator,
        participants=cast(Any, participants),
    )
    recovered_port = recovered.profile_difference_port()
    assert recovered_port.resolve_historical_for_decision(decision) == authority
    assert not recovered_port.is_current_for_use(authority, now=revoked_at + timedelta(seconds=1))
    assert recovered.revoke_profile_mapping(
        record.mapping_digest or "", actor="catalog-admin", now=revoked_at
    )
    assert [event["kind"] for event in recovered._journal.replay()] == [  # noqa: SLF001
        "external-quantitative-profile-mapping-activated",
        "external-quantitative-profile-mapping-revoked",
    ]
    recovered._journal.close()  # noqa: SLF001


def test_profile_mapping_port_stays_closed_without_production_participants(
    tmp_path: Path,
) -> None:
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
    )
    record = _mapping()
    assert catalog.admit_profile_mapping(record, actor="catalog-admin", now=_NOW) is None
    assert _select(
        catalog.profile_difference_port(), record, now=_NOW, work_area_id="work-area-a"
    ) is None
    catalog._journal.close()  # noqa: SLF001
