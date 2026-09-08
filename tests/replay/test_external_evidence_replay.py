"""External evidence journals fail closed before their human routes can mount."""

from __future__ import annotations

from pathlib import Path

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_evidence import ExternalEvidenceRecoveryError, ExternalEvidenceStore


def test_malformed_external_evidence_journal_fails_closed(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "external-evidence.jsonl")
    journal.append({"kind": "external-evidence-declared", "version": 1})
    journal.close()
    with pytest.raises(ExternalEvidenceRecoveryError):
        ExternalEvidenceStore(DurableJournal(tmp_path / "external-evidence.jsonl"))
