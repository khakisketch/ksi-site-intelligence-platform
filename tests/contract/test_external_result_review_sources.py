"""Actual report/decision stores with explicit synthetic use-history authority."""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_relative_volume_use_history import ClosedExternalRelativeVolumeUseHistory
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeExecutionAuthority,
    ExternalRelativeVolumeObservedReportInput,
    ExternalRelativeVolumeStore,
)
from ksi_core.external_result_review_sources import CoreExternalResultReviewSourceAdapter
from ksi_core.external_use_decisions import ExternalDecisionIntent, ExternalUseDecisionStore
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalPairUseDecisionV1,
)
from ksi_event_contracts.external_relative_volume import ExternalRelativeVolumeReportV1
from test_external_relative_volumes import _NOW, _authority, _fence, _payload, _principal, _store
from test_external_use_decisions import _SyntheticHistoryVerifier


class _UseHistory:
    def __init__(self, authority: ExternalRelativeVolumeExecutionAuthority) -> None:
        self.authority = authority
        self.revoked_at = _NOW + timedelta(seconds=20)
        self.times: list[datetime] = []

    def resolve_historical_for_use(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        evaluated_at: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        self.times.append(evaluated_at)
        authority = self.authority
        if (
            historical_authority_digest != authority.historical_authority_digest
            or decision_id != authority.decision_id
            or decision_digest != authority.decision_digest
            or evaluated_at >= self.revoked_at
        ):
            return None
        return authority


def _graph(
    tmp_path: Path,
) -> tuple[
    ExternalRelativeVolumeStore,
    ExternalUseDecisionStore,
    _UseHistory,
    CoreExternalResultReviewSourceAdapter,
    ExternalRelativeVolumeReportV1,
]:
    authority = _authority()
    decision = ExternalPairUseDecisionV1(
        decision_id=authority.decision_id,
        baseline_subject=authority.baseline.subject,
        baseline_subject_digest=authority.baseline.subject.canonical_digest(),
        current_subject=authority.current.subject,
        current_subject_digest=authority.current.subject.canonical_digest(),
        use="RELATIVE_VOLUME",
        policy_digest=authority.validation_policy_digest,
        baseline_inspection_report_digest=authority.baseline.inspection_report_digest,
        current_inspection_report_digest=authority.current.inspection_report_digest,
        evidence_record_digests=authority.evidence_record_digests,
        zone=authority.zone_snapshot.to_zone_reference(),
        compatibility_mapping_digest=authority.compatibility_mapping_digest,
        verdict=DecisionVerdict.ELIGIBLE,
        reasons=("ELIGIBLE",),
        remediations=("NONE",),
        decided_at=_NOW,
    ).sealed()
    assert decision.decision_digest is not None
    authority = replace(authority, decision_digest=decision.decision_digest)
    volumes = _store(tmp_path, authority)
    decisions = ExternalUseDecisionStore(
        DurableJournal(tmp_path / "decisions.jsonl"),
        coordinator=volumes.coordinator,
        history_verifier=_SyntheticHistoryVerifier(),
    )
    decisions.stage_evaluated(
        decision,
        intent=ExternalDecisionIntent.from_candidate(decision),
        principal=_principal(),
        idempotency_key="decision-fixture",
    )
    decisions.reconcile_pending()
    issued = volumes.issue(
        principal=_principal(),
        current_work_order_id=authority.current_work_order_id,
        decision_ref=authority.decision_id,
        idempotency_key="volume-fixture",
        now=_NOW,
    )
    assert issued.record is not None
    request = issued.record.request
    assert request.request_digest is not None
    fence = _fence()
    volumes.claim(
        request.request_id, organization_id="org-a", principal_id="worker", fence=fence, now=_NOW
    )
    terminal = volumes.record_observed_report(
        request.request_id,
        organization_id="org-a",
        principal_id="worker",
        fence=fence,
        observed=ExternalRelativeVolumeObservedReportInput(
            payload=_payload(request.request_digest, authority), computed_at=_NOW
        ),
        now=_NOW,
    )
    assert terminal.record is not None and terminal.record.report is not None
    assert terminal.record.report.report_digest is not None
    history = _UseHistory(authority)
    adapter = CoreExternalResultReviewSourceAdapter(
        volume_store=volumes,
        decisions=decisions,
        historical_use_authority=history,
        coordinator=volumes.coordinator,
    )
    return volumes, decisions, history, adapter, terminal.record.report


def test_historical_provenance_does_not_grant_permission_after_revocation(tmp_path: Path) -> None:
    volumes, _, history, adapter, report = _graph(tmp_path)
    assert report.report_digest is not None
    args = ("org-a", report.report_id, report.report_digest)
    assert adapter.resolve_historical(
        organization_id=args[0],
        report_ref=args[1],
        report_digest=args[2],
        evaluated_at=_NOW - timedelta(seconds=1),
    ) is None
    before = adapter.resolve_historical(
        organization_id=args[0], report_ref=args[1], report_digest=args[2], evaluated_at=_NOW
    )
    assert before is not None and before.report == report
    assert adapter.resolve_historical(
        organization_id=args[0],
        report_ref=args[1],
        report_digest=args[2],
        evaluated_at=history.revoked_at,
    ) is None
    assert (
        volumes.resolve_historical_report_ref(
            report.report_id, organization_id="org-a", now=history.revoked_at
        )
        is not None
    )
    assert history.times == [_NOW, history.revoked_at]
    assert (
        adapter.resolve_historical(
            organization_id="org-a",
            report_ref=report.request_id,
            report_digest=report.report_digest,
            evaluated_at=_NOW,
        )
        is None
    )
    assert (
        adapter.resolve_historical(
            organization_id="org-a",
            report_ref=report.report_id,
            report_digest="sha256:" + "0" * 64,
            evaluated_at=_NOW,
        )
        is None
    )


def test_current_join_requires_exact_principal_and_local_guard(tmp_path: Path) -> None:
    volumes, _, history, adapter, report = _graph(tmp_path)
    principal = _principal()
    source = adapter.resolve_current(
        organization_id="org-a", report_ref=report.report_id, principal=principal, evaluated_at=_NOW
    )
    assert source is not None
    with volumes.coordinator.mutation():
        assert adapter.is_current(source, principal=principal, evaluated_at=_NOW)
        assert not adapter.is_current(
            source, principal=_principal(principal_id="other"), evaluated_at=_NOW
        )
        assert not adapter.is_current(
            source, principal=_principal(organization_id="other"), evaluated_at=_NOW
        )
    assert history.times == [_NOW]  # Independent history ran only during preflight.
    assert (
        adapter.resolve_current(
            organization_id="org-a",
            report_ref=report.report_id,
            principal=principal,
            evaluated_at=_NOW - timedelta(seconds=1),
        )
        is None
    )
    cast(Any, volumes._authority_port).authority = replace(history.authority, valid_until=_NOW)
    with volumes.coordinator.mutation():
        assert not adapter.is_current(source, principal=principal, evaluated_at=_NOW)
    assert not adapter.is_current(
        source, principal=principal, evaluated_at=source.authority.valid_until
    )


def test_missing_use_history_stays_closed_and_coordinators_must_match(tmp_path: Path) -> None:
    volumes, decisions, _, _, report = _graph(tmp_path)
    adapter = CoreExternalResultReviewSourceAdapter(
        volume_store=volumes,
        decisions=decisions,
        historical_use_authority=ClosedExternalRelativeVolumeUseHistory(),
        coordinator=volumes.coordinator,
    )
    assert report.report_digest is not None
    assert (
        adapter.resolve_historical(
            organization_id="org-a",
            report_ref=report.report_id,
            report_digest=report.report_digest,
            evaluated_at=_NOW,
        )
        is None
    )
    assert (
        adapter.resolve_current(
            organization_id="org-a",
            report_ref=report.report_id,
            principal=_principal(),
            evaluated_at=_NOW,
        )
        is None
    )
    with pytest.raises(ValueError, match="coordinator"):
        CoreExternalResultReviewSourceAdapter(
            volume_store=volumes,
            decisions=decisions,
            historical_use_authority=ClosedExternalRelativeVolumeUseHistory(),
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )
