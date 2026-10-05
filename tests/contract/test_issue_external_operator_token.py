"""Unit tests for tools/issue_external_operator_token.py (no secrets, no network)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from issue_external_operator_token import issue_operator_token, prove_with_core_loader

_EXISTING = json.dumps(
    [
        {
            "tokenSha256": "4efd42ddd872b0d8ee75c1afd3005981df9f8d5df5e5347ca35a4f0a37dccfb7",
            "principalId": "external-validation-worker",
            "kind": "PROCESSING_WORKER",
            "organizationId": "org-a",
        }
    ],
    separators=(",", ":"),
)


def test_issue_appends_operator_row_and_proves_with_real_loader() -> None:
    raw_token, updated = issue_operator_token(
        principal_id="external-operator-step4",
        organization_id="org-a",
        role="ADMIN",
        existing_json=_EXISTING,
    )
    assert hashlib.sha256(raw_token.encode()).hexdigest() in updated
    facts = prove_with_core_loader(raw_token=raw_token, updated_json=updated)
    assert facts == {
        "principalId": "external-operator-step4",
        "kind": "OPERATOR",
        "role": "ADMIN",
        "organizationId": "org-a",
    }


def test_issue_rejects_scope_grants_for_operator_proof() -> None:
    # The Core loader only accepts scope grants for ANALYSIS_MCP_CLIENT; an
    # OPERATOR row carrying them must fail the real loader proof.
    raw_token, updated = issue_operator_token(
        principal_id="external-operator-step4",
        organization_id="org-a",
        role="ADMIN",
        existing_json=_EXISTING,
    )
    entries = json.loads(updated)
    entries[-1]["allowedSiteIds"] = ["site-a"]
    with pytest.raises(RuntimeError):
        prove_with_core_loader(
            raw_token=raw_token, updated_json=json.dumps(entries, separators=(",", ":"))
        )
