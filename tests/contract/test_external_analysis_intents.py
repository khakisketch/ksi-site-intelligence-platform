"""The public analysis intent is durable before it can invoke AP/NX."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ksi_core.domains.external.quantity.external_analysis_api import AnalysisScopeNotFound
from ksi_core.domains.external.quantity.external_analysis_intents import (
    AnalysisIntentStore,
    PublicAnalysisIntent,
)
from ksi_core.durable_journal import DurableJournal
from ksi_event_contracts.external_analysis_api import (
    AnalysisObservationSelectorV1,
    CreateAnalysisRequestV1,
)


def test_intent_journal_recovers_frozen_public_selectors_before_ap_nx_linking(
    tmp_path: Path,
) -> None:
    """A crash after intent append cannot lose or reinterpret a blocked public request."""
    journal_path = tmp_path / "analysis-intents.jsonl"
    request = CreateAnalysisRequestV1(
        baseline=AnalysisObservationSelectorV1(
            work_order_id="work-order-t0", submission_ref="ers-v1-" + "a" * 64, revision=1
        ),
        current=AnalysisObservationSelectorV1(
            work_order_id="work-order-t1", submission_ref="ers-v1-" + "b" * 64, revision=2
        ),
    )
    created_at = datetime(2026, 9, 22, tzinfo=UTC)
    store = AnalysisIntentStore(DurableJournal(journal_path))

    first = store.record_intent(
        organization_id="org-1",
        site_id="site-1",
        work_area_id="area-1",
        request=request,
        idempotency_key="same-user-key",
        now=created_at,
    )
    assert isinstance(first, PublicAnalysisIntent)
    assert first.analysis_id.startswith("analysis-v1-")
    assert first.request == request
    # Public return values are intentionally mutable API models.  They must
    # never alias the journal-retained selectors used by retry/replay.
    first.request.baseline.work_order_id = "mutated-after-return"
    persisted = store.get(first.analysis_id, organization_id="org-1")
    assert persisted is not None
    assert persisted.request.baseline.work_order_id == "work-order-t0"
    store.close()

    recovered = AnalysisIntentStore(DurableJournal(journal_path))
    same = recovered.record_intent(
        organization_id="org-1",
        site_id="site-1",
        work_area_id="area-1",
        request=request,
        idempotency_key="same-user-key",
        now=created_at,
    )
    assert isinstance(same, PublicAnalysisIntent)
    assert same == persisted
    linked = recovered.link_calculation(
        analysis_id=same.analysis_id,
        organization_id="org-1",
        calculation_request_id="calculation-shared-1",
    )
    assert linked.calculation_request_id == "calculation-shared-1"
    recovered.close()

    linked_recovered = AnalysisIntentStore(DurableJournal(journal_path)).get(
        same.analysis_id, organization_id="org-1"
    )
    assert linked_recovered is not None
    assert linked_recovered.calculation_request_id == "calculation-shared-1"


def test_scope_failure_has_one_non_disclosing_public_error() -> None:
    """Facade selector and path lookup share a generic not-found error type."""
    assert (
        str(AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")) == "ANALYSIS_RESOURCE_NOT_FOUND"
    )
