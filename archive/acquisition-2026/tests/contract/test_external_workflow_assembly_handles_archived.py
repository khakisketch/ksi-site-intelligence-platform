"""Archived assembly-handle proofs (P3 Task 5 relocation record, RB-08).

Relocated verbatim from
``tests/contract/test_external_workflow_common_assembly.py`` at base 2900214
(+ Task 5 adaptation state): both tests assert ``app.state`` handles that only
the legacy managed assembly set (``external_reconstruction_store``,
``evidence_storage``). The platform profile wires the same single graph but
does not stash those two handles on ``app.state`` (proven: the file's 14
staying tests cover the platform handle set), so these two assertions have no
platform-passing equivalent. This file is archive-internal (``archive/`` is
not a pytest testpath, import path, or workspace member) and is NOT executed.
``_assemble``/``_config`` below are imported from the staying test module;
``replace``/``pytest``/type imports mirror the source file.
"""

import pytest
from dataclasses import replace

from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionStore
from ksi_core.evidence import EvidenceStorage
from ksi_core.external_relative_volume_s3_capabilities import (
    ExternalRelativeVolumeS3InputCapabilityIssuer,
)
from test_external_workflow_common_assembly import _assemble, _config  # noqa: E402 -- archived record


def test_byte_issuer_factory_receives_final_stores(tmp_path: Path) -> None:
    """A shadow reconstruction store would not see the app's sealed DSM records."""
    opened: list[DurableJournal] = []
    trace: list[str] = []
    retained: list[ExternalRelativeVolumeS3InputCapabilityIssuer] = []

    def build_issuer(
        *, reconstruction: ExternalReconstructionStore, storage: EvidenceStorage
    ) -> ExternalRelativeVolumeS3InputCapabilityIssuer:
        issuer = ExternalRelativeVolumeS3InputCapabilityIssuer(
            reconstruction=reconstruction, storage=storage
        )
        retained.append(issuer)
        return issuer

    config = replace(
        _config(trace), input_capability_issuer=None, build_input_capability_issuer=build_issuer
    )
    try:
        app = _assemble(tmp_path, opened, trace, config=config)
        assert len(retained) == 1
        assert retained[0]._reconstruction is app.state.external_reconstruction_store
        assert retained[0]._storage is app.state.evidence_storage
        assert app.state.external_relative_volume_store is not None
    finally:
        for item in opened:
            item.close()


def test_configured_workflow_requires_complete_external_storage_graph(tmp_path: Path) -> None:
    opened: list[DurableJournal] = []
    trace: list[str] = []
    try:
        with pytest.raises(ValueError, match="external result workflow"):
            _assemble(tmp_path, opened, trace, config=_config(trace), storage=False)
        assert "mapping" not in trace
    finally:
        for item in opened:
            item.close()
