"""Managed Core canonical imports preserve the legacy module objects."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "services/core/src"
ALIASES = (
    ("ksi_core.capture_quality_reports", "ksi_core.acquisition.capture_quality_reports"),
    ("ksi_core.sites", "ksi_core.domains.sites.sites"),
    ("ksi_core.work_areas", "ksi_core.domains.sites.work_areas"),
    ("ksi_core.observation_work_orders", "ksi_core.domains.sites.observation_work_orders"),
    ("ksi_core.organization_work_roster", "ksi_core.domains.sites.organization_work_roster"),
    ("ksi_core.work_inbox", "ksi_core.domains.sites.work_inbox"),
    ("ksi_core.mission_atomicity", "ksi_core.domains.missions.mission_atomicity"),
    ("ksi_core.mission_execution", "ksi_core.domains.missions.mission_execution"),
    ("ksi_core.mission_issuance", "ksi_core.domains.missions.mission_issuance"),
    ("ksi_core.mission_plans", "ksi_core.domains.missions.mission_plans"),
    ("ksi_core.mission_records", "ksi_core.domains.missions.mission_records"),
    ("ksi_core.flight_artifacts", "ksi_core.domains.missions.flight_artifacts"),
    ("ksi_core.coverage_reports", "ksi_core.domains.missions.coverage_reports"),
    ("ksi_core.edge_dispatch", "ksi_core.domains.edge_transport.edge_dispatch"),
    ("ksi_core.edge_sync", "ksi_core.domains.edge_transport.edge_sync"),
    ("ksi_core.artifact_manifest", "ksi_core.domains.artifacts.artifact_manifest"),
    ("ksi_core.artifact_refs", "ksi_core.domains.artifacts.artifact_refs"),
    ("ksi_core.evidence", "ksi_core.domains.artifacts.evidence"),
    ("ksi_core.evidence_s3", "ksi_core.domains.artifacts.evidence_s3"),
    ("ksi_core.source_media", "ksi_core.domains.artifacts.source_media"),
    ("ksi_core.checkpoint_validations", "ksi_core.domains.artifacts.checkpoint_validations"),
    ("ksi_core.processing_jobs", "ksi_core.domains.processing.processing_jobs"),
    ("ksi_core.processing_profiles", "ksi_core.domains.processing.processing_profiles"),
    (
        "ksi_core.processing_resource_policy",
        "ksi_core.domains.processing.processing_resource_policy",
    ),
    ("ksi_core.civil_preflight", "ksi_core.domains.processing.civil_preflight"),
    ("ksi_core.civil_readiness", "ksi_core.domains.processing.civil_readiness"),
    ("ksi_core.spatial_model", "ksi_core.domains.processing.spatial_model"),
    ("ksi_core.comparison_requests", "ksi_core.domains.analytics.comparison_requests"),
    ("ksi_core.change_detection", "ksi_core.domains.analytics.change_detection"),
    ("ksi_core.volume_reports", "ksi_core.domains.analytics.volume_reports"),
    ("ksi_core.defect_candidates", "ksi_core.domains.analytics.defect_candidates"),
    ("ksi_core.design_surfaces", "ksi_core.domains.design.design_surfaces"),
    ("ksi_core.design_conformance_requests", "ksi_core.domains.design.design_conformance_requests"),
    ("ksi_core.design_conformance_reports", "ksi_core.domains.design.design_conformance_reports"),
    ("ksi_core.design_progress", "ksi_core.domains.design.design_progress"),
    ("ksi_core.region_extraction_requests", "ksi_core.domains.design.region_extraction_requests"),
    ("ksi_core.region_extraction_reports", "ksi_core.domains.design.region_extraction_reports"),
    ("ksi_core.report_exports", "ksi_core.domains.design.report_exports"),
    ("ksi_core.events", "ksi_core.domains.observations.events"),
    ("ksi_core.equipment_states", "ksi_core.domains.observations.equipment_states"),
    ("ksi_core.equipment_support", "ksi_core.domains.observations.equipment_support"),
    ("ksi_core.site_workspace", "ksi_core.domains.workspace.site_workspace"),
    ("ksi_core.copilot", "ksi_core.domains.workspace.copilot"),
    ("ksi_core.copilot_conversations", "ksi_core.domains.workspace.copilot_conversations"),
    ("ksi_core.copilot_openai", "ksi_core.domains.workspace.copilot_openai"),
)


@pytest.mark.parametrize(("legacy", "canonical"), ALIASES)
@pytest.mark.parametrize("canonical_first", (False, True))
def test_managed_alias_identity_in_fresh_interpreter(
    legacy: str, canonical: str, canonical_first: bool
) -> None:
    expected = SOURCE.joinpath(*canonical.split(".")).with_suffix(".py")
    assert expected.is_file(), f"canonical implementation absent: {expected}"
    order = (canonical, legacy) if canonical_first else (legacy, canonical)
    script = f"""
import importlib
from pathlib import Path
first = importlib.import_module({order[0]!r})
second = importlib.import_module({order[1]!r})
assert first is second
assert Path(first.__file__).resolve() == Path({str(expected)!r}).resolve()
parent = importlib.import_module("ksi_core")
assert getattr(parent, {legacy.rsplit(".", 1)[1]!r}) is first
sentinel = object()
setattr(first, "_ksi_r1_identity_probe", sentinel)
assert getattr(second, "_ksi_r1_identity_probe") is sentinel
delattr(first, "_ksi_r1_identity_probe")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
