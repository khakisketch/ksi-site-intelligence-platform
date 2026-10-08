"""Archived workspace-graph wiring pins (P3 Task 5 relocation record, RB-08).

Relocated verbatim from
``tests/contract/test_organization_work_roster_and_inbox.py`` (+ its exclusive
``_minimal_workspace_graph_dependencies`` helper): they pin
``build_workspace_graph`` (archived with the managed set) resolver shapes and
harness ``MissionStore``/mission-linked ``SourceMediaStore`` (both archived).
The platform profile builds the same ``ExternalVolumeReportResolver`` shapes
in ``build_platform_graph``; the None-resolver guard stays proven actively by
``test_relative_share_route_stays_unavailable_without_a_relative_store`` in
the active file. This file is archive-internal (``archive/`` is not a pytest
testpath, import path, or workspace member) and is NOT executed.
"""


def _minimal_workspace_graph_dependencies(tmp_path: Path) -> dict[str, Any]:
    """Real, minimally-wired dependencies for ``build_workspace_graph`` — enough
    to exercise its ``external_relative_volume_store``/``external_single_volume_store``
    conditional wiring without needing the full ``assemble_app`` surface."""
    from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
    from ksi_core.mission_plans import MissionStore
    from ksi_core.sites import SiteStore
    from ksi_core.source_media import SourceMediaStore

    coordinator = ExternalAuthorityCurrentnessCoordinator()
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"), coordinator=coordinator)
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    roster = OrganizationWorkRosterStore(
        DurableJournal(tmp_path / "roster.jsonl"), coordinator=coordinator
    )
    work_orders = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
        operations_coordinator=coordinator,
        assignment_member_is_active=roster.is_assignable_member,
    )
    return {
        "journal": lambda name: DurableJournal(tmp_path / name),
        "coordinator": coordinator,
        "observation_work_order_store": work_orders,
        "organization_work_roster_store": roster,
        "site_store": site_store,
        "mission_store": mission_store,
        "coverage_report_store": None,
        "source_media_store": source_media_store,
        "processing_job_store": None,
        "design_surface_store": None,
        "external_result_read_projector": None,
        "acquisition_coordination_enabled": False,
        "copilot_runtime_config": None,
        "event_journal": DurableJournal(tmp_path / "events.jsonl"),
    }


def test_workspace_graph_report_resolver_wiring_matches_configured_stores(tmp_path: Path) -> None:
    """Fix round 1 (Critical): pin ``build_workspace_graph``'s exact resolver
    shape for every relative/single configuration, directly (not through the
    heavier full-app assembly above)."""
    from ksi_core.composition.workspace_graph import build_workspace_graph
    from ksi_core.domains.sites.external_report_resolver import ExternalVolumeReportResolver

    relative_store = object()
    single_store = object()

    none_dir = tmp_path / "none"
    none_dir.mkdir()
    none_workspace = build_workspace_graph(
        **_minimal_workspace_graph_dependencies(none_dir),
        external_relative_volume_store=None,
    )
    assert none_workspace.work_inbox_store._report_resolver is None  # noqa: SLF001

    relative_only_dir = tmp_path / "relative-only"
    relative_only_dir.mkdir()
    relative_only_workspace = build_workspace_graph(
        **_minimal_workspace_graph_dependencies(relative_only_dir),
        external_relative_volume_store=relative_store,
    )
    relative_only_resolver = relative_only_workspace.work_inbox_store._report_resolver  # noqa: SLF001
    assert isinstance(relative_only_resolver, ExternalVolumeReportResolver)
    assert relative_only_resolver.uses(relative_store, None)

    composite_dir = tmp_path / "composite"
    composite_dir.mkdir()
    composite_workspace = build_workspace_graph(
        **_minimal_workspace_graph_dependencies(composite_dir),
        external_relative_volume_store=relative_store,
        external_single_volume_store=single_store,
    )
    composite_resolver = composite_workspace.work_inbox_store._report_resolver  # noqa: SLF001
    assert isinstance(composite_resolver, ExternalVolumeReportResolver)
    assert composite_resolver.uses(relative_store, single_store)
