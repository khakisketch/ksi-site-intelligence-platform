"""Runtime surfaces whose identity must survive Core module relocation."""

from __future__ import annotations

import importlib
import logging
import os
import subprocess
import sys

import pytest

LOGGER_MODULES = (
    # P3 Task 5: managed logger rows retired to archive/acquisition-2026/
    # (defect_candidates; region_extraction_reports; coverage_reports; edge_*;
    # equipment_*; events; mission_plans; copilot_conversations; site_workspace).
    ("ksi_core.durable_journal", "ksi_core.foundation.durable_journal"),
    ("ksi_core.metrics", "ksi_core.foundation.metrics"),
    ("ksi_core.retention", "ksi_core.foundation.retention"),
    ("ksi_core.change_detection", "ksi_core.domains.analytics.change_detection"),
    ("ksi_core.volume_reports", "ksi_core.domains.analytics.volume_reports"),
    ("ksi_core.comparison_requests", "ksi_core.domains.analytics.comparison_requests"),
    ("ksi_core.checkpoint_validations", "ksi_core.domains.artifacts.checkpoint_validations"),
    ("ksi_core.source_media", "ksi_core.domains.artifacts.source_media"),
    ("ksi_core.design_conformance_reports", "ksi_core.domains.design.design_conformance_reports"),
    ("ksi_core.design_surfaces", "ksi_core.domains.design.design_surfaces"),
    ("ksi_core.design_conformance_requests", "ksi_core.domains.design.design_conformance_requests"),
    ("ksi_core.processing_jobs", "ksi_core.domains.processing.processing_jobs"),
    ("ksi_core.spatial_model", "ksi_core.domains.processing.spatial_model"),
    ("ksi_core.observation_work_orders", "ksi_core.domains.sites.observation_work_orders"),
)


@pytest.mark.parametrize("legacy, canonical", LOGGER_MODULES)
def test_relocated_module_keeps_its_operational_logger_name(legacy: str, canonical: str) -> None:
    module = importlib.import_module(canonical)
    assert importlib.import_module(legacy) is module
    logger = getattr(module, "logger", getattr(module, "_LOGGER", None))
    assert isinstance(logger, logging.Logger)
    assert logger.name == legacy
    assert logger is logging.getLogger(legacy)


@pytest.mark.parametrize(
    "module",
    (
        "ksi_core.external_authority_preflight",
        "ksi_core.domains.external.authority.external_authority_preflight",
    ),
)
def test_preflight_module_cli_fails_closed_before_any_operator_file_read(module: str) -> None:
    environment = os.environ.copy()
    environment["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = "/not-the-fixed-operator-mount.json"
    result = subprocess.run(
        [sys.executable, "-m", module],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr.startswith("BLOCKED_EXTERNAL_AUTHORITY_CONFIG:")
    assert "fixed operator mount" in result.stderr
