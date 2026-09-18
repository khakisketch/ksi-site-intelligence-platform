"""Workspace, acquisition, readiness, and Copilot composition graph."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ksi_core.acquisition import (
    AcquisitionConnectivityStore,
    AcquisitionCoordinationStore,
    AnalysisReadinessProjector,
)
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.capture_quality_reports import CaptureQualityReportStore
from ksi_core.civil_readiness import CivilReadinessProjector
from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver
from ksi_core.events import EventStore
from ksi_core.work_inbox import WorkInboxStore


@dataclass(frozen=True)
class WorkspaceGraph:
    """Shared graph objects passed unchanged to routes and analysis stores."""

    work_inbox_store: Any
    acquisition_connectivity_store: Any
    acquisition_coordination_store: Any
    capture_quality_report_store: Any
    analysis_readiness_check: Any
    event_store: Any
    site_workspace_projector: Any
    civil_readiness_projector: Any
    copilot_service: Any
    copilot_conversation_service: Any
    site_briefing_service: Any
    site_briefing_store: Any


def build_workspace_graph(
    *,
    journal: Callable[[str], Any],
    coordinator: Any,
    observation_work_order_store: Any,
    organization_work_roster_store: Any,
    site_store: Any,
    mission_store: Any,
    coverage_report_store: Any,
    source_media_store: Any,
    processing_job_store: Any,
    design_surface_store: Any,
    external_result_read_projector: Any,
    external_relative_volume_store: Any,
    acquisition_coordination_enabled: bool,
    copilot_runtime_config: Any,
    event_journal: Any,
    external_single_volume_store: Any = None,
) -> WorkspaceGraph:
    # The work inbox shares reports of either external-volume family with
    # teammates through one resolver.  A ref's family is only decidable by
    # its own identity prefix, so the resolver must dispatch on that prefix
    # rather than being bound to one family's store — see
    # ``ExternalVolumeReportResolver``.  ``single`` stays ``None`` (today's
    # behavior) when single volume is not configured.
    #
    # The composite is built only when a relative store exists.  Wrapping a
    # missing relative store in a composite that is never ``None`` would
    # silently defeat ``WorkInboxStore``'s own
    # ``if self._report_resolver is None: raise RuntimeError(...)`` guard,
    # turning today's 503 EXTERNAL_REPORT_SHARING_UNAVAILABLE for an
    # unconfigured relative family into a 404.  Single volume can only be
    # configured alongside relative volume (``external_graph.py`` builds it
    # nested inside the relative-volume branch), so this never leaves a
    # configured single store unreachable.
    external_volume_report_resolver = (
        ExternalVolumeReportResolver(
            relative=external_relative_volume_store,
            single=external_single_volume_store,
        )
        if external_relative_volume_store is not None
        else None
    )
    work_inbox_store = WorkInboxStore(
        journal("work-inbox.jsonl"),
        work_orders=observation_work_order_store,
        roster=organization_work_roster_store,
        report_resolver=external_volume_report_resolver,
        coordinator=coordinator,
    )
    acquisition_connectivity_store = AcquisitionConnectivityStore(
        journal("acquisition-connectivity.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    acquisition_coordination_store = (
        AcquisitionCoordinationStore(
            journal("acquisition-runs.jsonl"),
            work_order_execution_guard=observation_work_order_store.assert_execution_allowed,
        )
        if acquisition_coordination_enabled
        else None
    )
    # Edge 품질 측정은 새로운 완료 상태가 아니라, WorkOrder 회차와 Mission에
    # 결속된 evidence다. coordinator가 없는 축소 조립에서는 이 원장도 열지 않아
    # "어느 회차의 품질인가"를 추측하는 표면을 만들지 않는다.
    capture_quality_report_store = (
        CaptureQualityReportStore(
            journal("capture-quality-reports.jsonl"),
            mission_store=mission_store,
            work_order_store=observation_work_order_store,
            coordination_store=acquisition_coordination_store,
        )
        if acquisition_coordination_store is not None
        else None
    )
    # Quantitative work consumes the same derived readiness used by the
    # acquisition view.  The callback keeps comparison stores independent of
    # WorkOrder/Coverage/Quality journal internals while still failing closed.
    analysis_readiness_check = None
    if (
        acquisition_coordination_store is not None
        and capture_quality_report_store is not None
        and processing_job_store is not None
    ):
        analysis_readiness_projector = AnalysisReadinessProjector(
            coverage_report_store=coverage_report_store,
            capture_quality_report_store=capture_quality_report_store,
            source_media_store=source_media_store,
            processing_job_store=processing_job_store,
        )

        def _analysis_readiness_check(mission_id: str) -> tuple[bool, str | None]:
            mission = mission_store.get(mission_id)
            if mission is None:
                return False, "Mission 원장으로 Analysis Readiness 범위를 확인할 수 없다"
            run = acquisition_coordination_store.run_for_mission(
                mission_id, organization_id=mission.organization_id
            )
            if run is None:
                return False, "Mission에 연결된 AcquisitionRun이 없다"
            work_order = observation_work_order_store.get(
                run.work_order_id, organization_id=mission.organization_id
            )
            if work_order is None:
                return False, "AcquisitionRun의 WorkOrder를 찾을 수 없다"
            readiness = analysis_readiness_projector.project(
                work_order,
                mission_id=mission_id,
                now=datetime.now(UTC),
            )
            return readiness.ready, readiness.detail

        analysis_readiness_check = _analysis_readiness_check
    # Site workspace reuses the exact EventStore instance mounted on the public API;
    # opening a second writer for the same journal would violate DurableJournal locking.
    event_store = EventStore(event_journal)
    from ksi_core.site_workspace import (
        SiteWorkspaceProjector,
        build_workspace_copilot_handlers,
    )

    site_workspace_projector = SiteWorkspaceProjector(
        site_store=site_store,
        work_order_store=observation_work_order_store,
        processing_job_store=processing_job_store,
        event_store=event_store,
        external_results=external_result_read_projector,
    )
    # This is a read-only navigation projection.  It reuses the exact
    # AnalysisReadiness callback wired into comparison/design request stores;
    # it must not invent a second policy or make missing evidence look ready.
    civil_readiness_projector = (
        CivilReadinessProjector(
            site_store=site_store,
            processing_job_store=processing_job_store,
            design_surface_store=design_surface_store,
            analysis_readiness=analysis_readiness_check,
        )
        if processing_job_store is not None
        else None
    )
    from ksi_core.site_workspace import SiteBriefingStore

    # Briefings are durable records independent of the copilot: deterministic
    # projections (external results) write them even when external AI is OFF.
    site_briefing_store = SiteBriefingStore(journal("site-briefings.jsonl"), site_store=site_store)
    copilot_service = None
    copilot_conversation_service = None
    site_briefing_service = None
    if copilot_runtime_config is not None:
        from ksi_core.copilot import CopilotService, CoreCopilotToolBackend
        from ksi_core.copilot_conversations import (
            CopilotConversationService,
            CopilotConversationStore,
        )
        from ksi_core.copilot_openai import OpenAiCompatibleModelAdapter
        from ksi_core.site_workspace import SiteBriefingService

        def _capture_policy_for_work_order(organization_id: str, work_order_id: str) -> str | None:
            order = observation_work_order_store.get(work_order_id, organization_id=organization_id)
            if order is None or order.schedule_id is None:
                return None
            schedules = observation_work_order_store.list_schedules(
                order.site_id, organization_id=organization_id
            )
            schedule = next(
                (item for item in schedules if item.schedule_id == order.schedule_id),
                None,
            )
            return schedule.approved_policy_version if schedule is not None else None

        backend = CoreCopilotToolBackend(
            site_store=site_store,
            observation_work_order_store=observation_work_order_store,
            query_handlers=build_workspace_copilot_handlers(
                site_workspace_projector, observation_work_order_store
            ),
            ai_egress_policy=lambda organization_id, site_id: bool(
                (site := site_store.get_scoped(site_id, organization_id)) is not None
                and site.ai_egress_allowed
            ),
            capture_policy_for_work_order=_capture_policy_for_work_order,
        )
        copilot_service = CopilotService(
            model=OpenAiCompatibleModelAdapter(
                base_url=copilot_runtime_config.base_url,
                model=copilot_runtime_config.model,
                api_key_file=copilot_runtime_config.api_key_file,
                timeout_seconds=copilot_runtime_config.timeout_seconds,
            ),
            backend=backend,
            planner_version=copilot_runtime_config.planner_version,
        )
        conversation_store = CopilotConversationStore(
            journal("copilot-conversations.jsonl"),
            site_exists=lambda site_id, organization_id: (
                site_store.get_scoped(site_id, organization_id) is not None
            ),
            work_order_matches=lambda work_order_id, organization_id, site_id: (
                (
                    order := observation_work_order_store.get(
                        work_order_id, organization_id=organization_id
                    )
                )
                is not None
                and order.site_id == site_id
            ),
        )
        copilot_conversation_service = CopilotConversationService(
            store=conversation_store,
            copilot=copilot_service,
            provider=copilot_runtime_config.provider_name,
            model=copilot_runtime_config.model,
            planner_version=copilot_runtime_config.planner_version,
        )
        site_briefing_service = SiteBriefingService(
            store=site_briefing_store,
            copilot=copilot_service,
            workspace=site_workspace_projector,
        )

        def _create_review_ready_briefing(order: Any) -> None:
            from ksi_event_contracts.observation_work_order import ObservationWorkOrderStatus

            if order.status is not ObservationWorkOrderStatus.REVIEW_READY:
                return
            site_briefing_service.refresh(
                order.site_id,
                principal=Principal(
                    principal_id="system-site-briefing",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id=order.organization_id,
                ),
            )

        observation_work_order_store.bind_status_listener(_create_review_ready_briefing)
    return WorkspaceGraph(
        work_inbox_store=work_inbox_store,
        acquisition_connectivity_store=acquisition_connectivity_store,
        acquisition_coordination_store=acquisition_coordination_store,
        capture_quality_report_store=capture_quality_report_store,
        analysis_readiness_check=analysis_readiness_check,
        event_store=event_store,
        site_workspace_projector=site_workspace_projector,
        civil_readiness_projector=civil_readiness_projector,
        copilot_service=copilot_service,
        copilot_conversation_service=copilot_conversation_service,
        site_briefing_service=site_briefing_service,
        site_briefing_store=site_briefing_store,
    )
