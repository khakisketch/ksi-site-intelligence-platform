"""Blocker catalog: every emitted code is explained once and the dashboard copy is identical."""

from __future__ import annotations

import json
from pathlib import Path

from ksi_core.domains.external.quantity.external_use_blockers import (
    CATALOG_PATH,
    load_external_use_blocker_catalog,
)
from ksi_core.domains.external.quantity.external_use_evaluator import PAIR_REASON_REMEDIATIONS

_REPO = Path(__file__).resolve().parents[2]
_DASHBOARD_COPY = _REPO / "apps/dashboard/src/lib/external-use-blockers.generated.json"
_OWNERS = {"OPERATOR", "ADMIN", "CUSTOMER"}
_TARGETS = {
    "SUBJECT",
    "INSPECTION",
    "DISPLAY",
    "POLICY",
    "EVIDENCE",
    "MAPPING",
    "ZONE",
    "HEIGHT",
    "GENERAL",
}


def test_catalog_covers_every_evaluator_reason_and_remediation() -> None:
    catalog = load_external_use_blocker_catalog()
    assert catalog.contract_version == "external-use-blockers.v1"
    missing_reasons = set(PAIR_REASON_REMEDIATIONS) - set(catalog.reasons)
    missing_remediations = set(PAIR_REASON_REMEDIATIONS.values()) - set(catalog.remediations)
    assert not missing_reasons, missing_reasons
    assert not missing_remediations, missing_remediations
    assert "RESOLVE_EXTERNAL_USE_BLOCKER" in catalog.remediations


def test_catalog_entries_are_complete_korean_guidance() -> None:
    catalog = load_external_use_blocker_catalog()
    for code, reason in catalog.reasons.items():
        assert code.isupper() and reason.title.strip() and reason.explanation.strip(), code
        assert reason.owner in _OWNERS and reason.target in _TARGETS, code
    for code, remediation in catalog.remediations.items():
        assert code.isupper() and remediation.step.strip(), code
        assert remediation.owner in _OWNERS and remediation.target in _TARGETS, code


def test_dashboard_copy_is_byte_identical_to_the_contract() -> None:
    assert _DASHBOARD_COPY.read_bytes() == CATALOG_PATH.read_bytes()
    assert json.loads(_DASHBOARD_COPY.read_text())["contractVersion"] == "external-use-blockers.v1"
