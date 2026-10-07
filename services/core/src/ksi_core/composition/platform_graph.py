"""Explicit external-only platform Core graph (platform Core assembly plan, Task 2).

This graph builds only Site/WorkArea/roster/WorkOrder stores plus the existing
external graphs around the exact constructed WorkOrder instance. It reuses the
same external builders, callbacks and shared currentness coordinator as the
legacy managed assembly, but it never calls ``assemble_app`` or
``build_base_graph`` — the base graph always opens Mission/Edge journals and
the legacy assembly additionally requires a Mission signing key, device
attestation and acquisition stores, none of which this profile owns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ksi_event_contracts.external_analysis_activation import AnalysisActivationV1
from ksi_event_contracts.work_area import WorkAreaStatus

from ksi_core.composition.external_graph import (
    ExternalAnalysisLocalGraphConfig,
    ExternalAnalysisWiring,
    ExternalCompletedGraph,
    ExternalPreWorkOrderGraph,
    build_external_analysis_wiring,
    build_external_pre_work_order_graph,
    complete_external_graph,
)
from ksi_core.composition.spatial_data_graph import (
    SpatialDataLocalAssemblyConfig,
    SpatialDataWiring,
    build_spatial_data_wiring,
)
from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
from ksi_core.domains.sites.observation_work_orders import ObservationWorkOrderStore
from ksi_core.domains.sites.organization_work_roster import OrganizationWorkRosterStore
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.domains.sites.work_areas import WorkAreaStore
from ksi_core.domains.sites.work_inbox import WorkInboxStore
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_result_workflow_assembly import ExternalResultWorkflowAssemblyConfig

if TYPE_CHECKING:
    from collections.abc import Callable

    from ksi_core.durable_journal import DurableJournal
    from ksi_core.evidence import EvidenceStorage


@dataclass(frozen=True)
class PlatformGraph:
    """Exact platform participants handed unchanged to the platform app factory."""

    sites: SiteStore
    work_areas: WorkAreaStore
    work_orders: ObservationWorkOrderStore
    roster: OrganizationWorkRosterStore
    inbox: WorkInboxStore
    external: ExternalPreWorkOrderGraph
    workflow: ExternalCompletedGraph
    analysis: ExternalAnalysisWiring | None
    data: SpatialDataWiring | None
    coordinator: ExternalAuthorityCurrentnessCoordinator
    storage: Any


def build_platform_graph(
    *,
    data_dir: Path,
    journal: Callable[[str], DurableJournal],
    opened: list[Any],
    evidence_storage: EvidenceStorage,
    external_result_workflow: ExternalResultWorkflowAssemblyConfig | None = None,
    external_analysis_local_graph: ExternalAnalysisLocalGraphConfig | None = None,
    analysis_activation: AnalysisActivationV1 | None = None,
    spatial_data: SpatialDataLocalAssemblyConfig | None = None,
) -> PlatformGraph:
    """Build the external-only graph; never synthesize a missing participant.

    ``data_dir`` is retained for legacy-assembly signature parity — journal
    paths remain owned by the caller's ``journal`` closure, and this profile
    opens no journal outside that closure.
    """
    del data_dir
    if evidence_storage is None:
        raise ValueError(
            "platform Core requires evidence_storage — "
            "external ingress cannot issue byte grants without it"
        )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    policy_authority_currentness = None
    evidence_context_authority = None
    if external_result_workflow is not None:
        build_policy_currentness = external_result_workflow.build_policy_authority_currentness
        if build_policy_currentness is not None:
            policy_authority_currentness = build_policy_currentness(coordinator)
            if (
                policy_authority_currentness is None
                or policy_authority_currentness.coordinator is not coordinator
            ):
                raise ValueError(
                    "external result workflow policy currentness must share the Core coordinator"
                )
        build_context_authority = external_result_workflow.build_evidence_context_authority
        if build_context_authority is not None:
            evidence_context_authority = build_context_authority(coordinator)
            if (
                evidence_context_authority is None
                or evidence_context_authority.coordinator is not coordinator
            ):
                raise ValueError(
                    "external result workflow context authority must share the Core coordinator"
                )
    site_store = SiteStore(journal("sites.jsonl"), coordinator=coordinator)
    work_area_store = WorkAreaStore(
        journal("work-areas.jsonl"),
        site_exists=lambda site_id: site_store.get(site_id) is not None,
        coordinator=coordinator,
    )
    external_pre_work_order = build_external_pre_work_order_graph(
        journal=journal,
        evidence_storage=evidence_storage,
        external_result_workflow=external_result_workflow,
        work_area_store=work_area_store,
        site_store=site_store,
        coordinator=coordinator,
        policy_authority_currentness=policy_authority_currentness,
        evidence_context_authority=evidence_context_authority,
    )
    organization_work_roster_store = OrganizationWorkRosterStore(
        journal("organization-work-roster.jsonl"), coordinator=coordinator
    )
    observation_work_order_store = ObservationWorkOrderStore(
        journal("observation-work-orders.jsonl"),
        external_reobservation_authority_port=external_pre_work_order.proposal_authority,
        operations_coordinator=coordinator,
        assignment_member_is_active=organization_work_roster_store.is_assignable_member,
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
        work_areas_exist=lambda site_id, work_area_ids: all(
            (area := work_area_store.get(work_area_id)) is not None
            and area.site_id == site_id
            and area.status is WorkAreaStatus.ACTIVE
            for work_area_id in work_area_ids
        ),
    )
    external_completed = complete_external_graph(
        pre_work_order=external_pre_work_order,
        observation_work_order_store=observation_work_order_store,
        site_store=site_store,
        work_area_store=work_area_store,
        coordinator=coordinator,
    )
    # The work inbox shares reports of either external-volume family through one
    # resolver — the same shape the workspace graph builds, without the
    # acquisition/copilot stores that graph also assembles.
    external_volume_report_resolver = (
        ExternalVolumeReportResolver(
            relative=external_pre_work_order.relative_volume_store,
            single=(
                external_pre_work_order.single_volume.store
                if external_pre_work_order.single_volume is not None
                else None
            ),
        )
        if external_pre_work_order.relative_volume_store is not None
        else None
    )
    work_inbox_store = WorkInboxStore(
        journal("work-inbox.jsonl"),
        work_orders=observation_work_order_store,
        roster=organization_work_roster_store,
        report_resolver=external_volume_report_resolver,
        coordinator=coordinator,
    )
    if analysis_activation is not None and external_analysis_local_graph is None:
        raise ValueError(
            "analysis activation without an explicit local analysis graph is closed — "
            "it would silently mount no Analysis route"
        )
    external_analysis_wiring = (
        build_external_analysis_wiring(
            journal=journal,
            config=external_analysis_local_graph,
            reconstruction=external_pre_work_order.reconstruction_store,
            inspections=external_pre_work_order.artifact_inspection_store,
            work_areas=work_area_store,
            evidence=external_pre_work_order.evidence_store,
            validations=external_pre_work_order.evidence_validation_store,
            storage=evidence_storage,
            sites=site_store,
            work_orders=observation_work_order_store,
            coordinator=coordinator,
            activation=analysis_activation,
        )
        if external_analysis_local_graph is not None
        else None
    )
    data_lane = None
    if spatial_data is not None:
        if (
            not isinstance(spatial_data, SpatialDataLocalAssemblyConfig)
            or external_pre_work_order.reconstruction_store is None
            or external_pre_work_order.artifact_inspection_store is None
        ):
            raise ValueError(
                "spatial data requires complete local config and actual ingress/inspection"
            )
        data_lane = build_spatial_data_wiring(
            journal=journal,
            config=spatial_data.config,
            reconstruction=external_pre_work_order.reconstruction_store,
            inspections=external_pre_work_order.artifact_inspection_store,
            sites=site_store,
            work_areas=work_area_store,
            work_orders=observation_work_order_store,
            coordinator=coordinator,
            storage=spatial_data.build_storage(external_pre_work_order.reconstruction_store),
            currentness=spatial_data.build_currentness(coordinator),
            spool_root=spatial_data.spool_root,
        )
    return PlatformGraph(
        sites=site_store,
        work_areas=work_area_store,
        work_orders=observation_work_order_store,
        roster=organization_work_roster_store,
        inbox=work_inbox_store,
        external=external_pre_work_order,
        workflow=external_completed,
        analysis=external_analysis_wiring,
        data=data_lane,
        coordinator=coordinator,
        storage=evidence_storage,
    )


__all__ = ["PlatformGraph", "build_platform_graph"]
