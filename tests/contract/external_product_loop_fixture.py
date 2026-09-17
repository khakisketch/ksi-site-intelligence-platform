"""Actual durable Core graph; only independent authority providers are synthetic."""

from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ksi_core.domains.external.quantity.external_single_volume_use_history import (
    ExternalSingleVolumeHistoricalUseAuthorityPort,
)
from ksi_core.domains.external.quantity.external_single_volumes import ExternalSingleVolumeStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeExecutionAuthority,
    ExternalRelativeVolumeObservedReportInput,
    ExternalRelativeVolumeQueuePolicy,
    ExternalRelativeVolumeStore,
)
from ksi_core.external_reobservation_proposals import (
    CoreExternalReobservationProposalAuthorityPort,
    ExternalReobservationProposalService,
    ExternalReobservationProposalStore,
    verify_external_reobservation_organization_graph,
)
from ksi_core.external_result_review_sources import CoreExternalResultReviewSourceAdapter
from ksi_core.external_result_reviews import ExternalResultReviewSourceV1, ExternalResultReviewStore
from ksi_core.external_use_decisions import ExternalDecisionIntent, ExternalUseDecisionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_core.work_areas import WorkAreaStore
from ksi_event_contracts.external_relative_volume import ExternalRelativeVolumeReportV1
from ksi_mission_contracts.models import SiteFrame
from test_external_relative_volumes import _AuthorityPort, _fence, _payload
from test_external_result_review_proposals import _NOW, _principal, _sealed_source
from test_external_use_decisions import _SyntheticHistoryVerifier

POLYGON: dict[str, object] = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [0.0, 0.0]]],
}


def seed_original(path: Path) -> ExternalResultReviewSourceV1:
    sites = SiteStore(DurableJournal(path / "sites.jsonl"))
    sites.register(
        "site-a",
        "Synthetic site",
        SiteFrame(crs="EPSG:5186", vertical_datum="LOCAL", unit="meter", transform_version="v1"),
        organization_id="org-a",
        actor="operator-a",
        now=_NOW - timedelta(hours=1),
    )
    areas = WorkAreaStore(DurableJournal(path / "areas.jsonl"), site_exists=lambda _: True)
    area = areas.register(
        "site-a",
        name="Measured zone",
        polygon=POLYGON,
        crs="EPSG:5186",
        supersedes=None,
        actor="operator-a",
        now=_NOW - timedelta(minutes=50),
    ).work_area
    assert area is not None
    orders = ObservationWorkOrderStore(
        DurableJournal(path / "orders.jsonl"),
        site_exists=lambda *_: True,
        work_areas_exist=lambda *_: True,
    )
    original = orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="Original survey",
        work_area_ids=[area.work_area_id],
        schedule_id=None,
        actor="operator-a",
        now=_NOW - timedelta(minutes=40),
    )
    for store in (sites, areas, orders):
        store._journal.close()
    return _sealed_source(
        source_work_order_id=original.work_order_id, work_area_id=area.work_area_id, polygon=POLYGON
    )


class _History:
    def __init__(self, authority: ExternalRelativeVolumeExecutionAuthority) -> None:
        self.authority = authority
        self.revoked_at = _NOW + timedelta(seconds=20)

    def resolve_historical_for_use(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        evaluated_at: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        a = self.authority
        return (
            a
            if (
                evaluated_at < self.revoked_at
                and historical_authority_digest == a.historical_authority_digest
                and decision_id == a.decision_id
                and decision_digest == a.decision_digest
            )
            else None
        )


@dataclass
class LoopGraph:
    service: ExternalReobservationProposalService
    volumes: ExternalRelativeVolumeStore
    decisions: ExternalUseDecisionStore
    history: _History
    authority_port: _AuthorityPort
    journals: list[DurableJournal]
    source: ExternalResultReviewSourceV1
    single_volumes: ExternalSingleVolumeStore | None = None
    single_history: Any = None

    def close(self) -> None:
        for journal in reversed(self.journals):
            journal.close()


SingleFamilyFactory = Callable[
    [ExternalAuthorityCurrentnessCoordinator],
    tuple[ExternalSingleVolumeStore, ExternalSingleVolumeHistoricalUseAuthorityPort],
]


def build_graph(
    path: Path,
    source: ExternalResultReviewSourceV1,
    *,
    single: SingleFamilyFactory | None = None,
) -> LoopGraph:
    """Build the loop graph; ``single`` also configures the single-volume review family."""
    journals: list[DurableJournal] = []

    def journal(name: str) -> DurableJournal:
        item = DurableJournal(path / name)
        journals.append(item)
        return item

    coordinator = ExternalAuthorityCurrentnessCoordinator()
    sites = SiteStore(journal("sites.jsonl"), coordinator=coordinator)
    areas = WorkAreaStore(
        journal("areas.jsonl"),
        site_exists=lambda site: sites.get(site) is not None,
        coordinator=coordinator,
    )
    values = {
        f.name: getattr(source.authority, f.name)
        for f in fields(ExternalRelativeVolumeExecutionAuthority)
    }
    values["authorized_actor_ids"] = frozenset(values["authorized_actor_ids"])
    authority = ExternalRelativeVolumeExecutionAuthority(**values)
    port = _AuthorityPort(authority)
    port.currentness_coordinator = coordinator
    decisions = ExternalUseDecisionStore(
        journal("decisions.jsonl"),
        coordinator=coordinator,
        history_verifier=_SyntheticHistoryVerifier(),
    )
    volumes = ExternalRelativeVolumeStore(
        journal("volumes.jsonl"),
        authority_port=port,
        currentness_coordinator=coordinator,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(minutes=5),
            deadline_after_issue=timedelta(hours=1),
            max_attempts=3,
            max_active_requests_per_organization=8,
        ),
        clock=lambda: _NOW,
    )
    history = _History(authority)
    single_volumes: ExternalSingleVolumeStore | None = None
    single_history: ExternalSingleVolumeHistoricalUseAuthorityPort | None = None
    if single is not None:
        single_volumes, single_history = single(coordinator)
        journals.append(single_volumes._journal)  # noqa: SLF001 - close with the graph.
    adapter = CoreExternalResultReviewSourceAdapter(
        volume_store=volumes,
        decisions=decisions,
        historical_use_authority=history,
        coordinator=coordinator,
        single_volume_store=single_volumes,
        single_historical_use_authority=single_history,
    )
    reviews = ExternalResultReviewStore(
        journal("reviews.jsonl"), source_port=adapter, coordinator=coordinator
    )
    proposals = ExternalReobservationProposalStore(
        journal("proposals.jsonl"), coordinator=coordinator
    )
    proposal_authority = CoreExternalReobservationProposalAuthorityPort(
        reviews=reviews, proposals=proposals, sites=sites, work_areas=areas, coordinator=coordinator
    )
    orders = ObservationWorkOrderStore(
        journal("orders.jsonl"),
        site_exists=lambda site, org: sites.get_scoped(site, org) is not None,
        work_areas_exist=lambda site, ids: all(areas.get(i) is not None for i in ids),
        external_reobservation_authority_port=proposal_authority,
    )
    service = ExternalReobservationProposalService(
        reviews=reviews,
        proposals=proposals,
        sites=sites,
        work_areas=areas,
        work_orders=orders,
        authority_port=proposal_authority,
        coordinator=coordinator,
    )
    verify_external_reobservation_organization_graph(
        organization_id="org-a", work_orders=orders, authority_port=proposal_authority
    )
    return LoopGraph(
        service,
        volumes,
        decisions,
        history,
        port,
        journals,
        source,
        single_volumes=single_volumes,
        single_history=single_history,
    )


def record_measurement(graph: LoopGraph) -> ExternalRelativeVolumeReportV1:
    source = graph.source
    graph.decisions.stage_evaluated(
        source.decision,
        intent=ExternalDecisionIntent.from_candidate(source.decision),
        principal=_principal(),
        idempotency_key="fixture-decision",
    )
    graph.decisions.reconcile_pending()
    issued = graph.volumes.issue(
        principal=_principal(),
        current_work_order_id=source.authority.current_work_order_id,
        decision_ref=source.decision.decision_id,
        idempotency_key="fixture-volume",
        now=_NOW,
    )
    assert issued.record is not None
    request = issued.record.request
    assert request.request_digest is not None
    fence = _fence()
    graph.volumes.claim(
        request.request_id, organization_id="org-a", principal_id="worker", fence=fence, now=_NOW
    )
    result = graph.volumes.record_observed_report(
        request.request_id,
        organization_id="org-a",
        principal_id="worker",
        fence=fence,
        observed=ExternalRelativeVolumeObservedReportInput(
            payload=_payload(request.request_digest, graph.history.authority),
            computed_at=_NOW,
        ),
        now=_NOW,
    )
    assert result.record is not None and result.record.report is not None
    return result.record.report
