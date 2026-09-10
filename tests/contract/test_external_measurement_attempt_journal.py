"""Fixed V1/V2 journal wrappers preserve wire and isolate declared secondary authority."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_processing_controller.external_inspector_attempts import (
    AttemptJournalError,
    AttemptPhaseV1,
    InspectorAttemptJournal,
)
from ksi_processing_controller.external_measurement_attempts import (
    MeasurementAttemptBindingV2,
    MeasurementAttemptJournalV2,
)
from test_external_inspector_docker import _binding
from test_external_measurement_attempt_binding import binding


def test_v1_binding_and_first_journal_event_keep_exact_pre_extraction_bytes(tmp_path: Path) -> None:
    value = _binding()
    assert (
        hashlib.sha256(canonical_json_bytes(value.wire())).hexdigest()
        == "40dc0e91f5cdf00a8dd3c8538e548f46398a6a2a5bdc11a304cd3d03a0704717"
    )
    path = tmp_path / "v1.jsonl"
    journal = InspectorAttemptJournal(path, clock=lambda: datetime(2026, 9, 9, tzinfo=UTC))
    journal.intend(value)
    journal.close()
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest()
        == "8afe6e462de0adcc3889bf99f535923643b74042d27d1bd62494cb12aff673ed"
    )


def test_v2_journal_restarts_with_declared_secondary_but_no_host_secondary(tmp_path: Path) -> None:
    path = tmp_path / "v2.jsonl"
    value = binding()
    journal = MeasurementAttemptJournalV2(path)
    journal.intend(value)
    journal.close()
    restarted = MeasurementAttemptJournalV2(path)
    assert restarted.phase_of(value.attempt_nonce) is AttemptPhaseV1.INTENDED
    records = restarted.recoverable_attempts()
    assert len(records) == 1
    assert records[0].binding == value
    assert records[0].receipt is None
    assert records[0].binding.secondary_input == value.secondary_input
    assert b'"version":"external-measurement-attempt.v2"' in path.read_bytes()
    with pytest.raises(AttemptJournalError):
        InspectorAttemptJournal(path)
    restarted.close()


def test_v2_journal_rejects_v1_records_and_binding(tmp_path: Path) -> None:
    path = tmp_path / "v1.jsonl"
    v1 = InspectorAttemptJournal(path)
    v1.intend(_binding())
    v1.close()
    with pytest.raises(AttemptJournalError):
        MeasurementAttemptJournalV2(path)
    v2 = MeasurementAttemptJournalV2(tmp_path / "v2.jsonl")
    with pytest.raises((AttemptJournalError, ValueError, TypeError)):
        v2.intend(cast(MeasurementAttemptBindingV2, _binding()))
    v2.close()


def primary_receipt(size: int = 0) -> Any:
    from ksi_processing_controller.external_inspector_attempts import (
        StagingAllocationReceiptV1,
        StagingFileIdentityV1,
    )

    def node(inode: int, mode: int, size: int = 0) -> Any:
        return StagingFileIdentityV1(1, inode, mode, 1000, 1000, 1, size)

    return StagingAllocationReceiptV1(
        marker=node(3, 0o600), directory=node(4, 0o700), artifact=node(5, 0o600, size)
    )


def parent_receipt(value: MeasurementAttemptBindingV2) -> Any:
    from ksi_processing_controller.external_measurement_attempts import (
        MeasurementRuntimeParentReceiptV2,
    )

    return MeasurementRuntimeParentReceiptV2(
        unit_name=value.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/fixture",
        description=value.runtime_description,
        slice_name=value.systemd_base_slice,
        control_group="/base.slice/" + value.systemd_slice_name,
        invocation_id="a" * 32,
        device=1,
        inode=6,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=0,
        cpu_budget_counter=value.cpu_budget_counter,
    )


@pytest.mark.parametrize("phase_index", range(7))
def test_v2_recovery_cleans_only_primary_and_exact_runtime_at_each_crash_phase(
    tmp_path: Path, phase_index: int
) -> None:
    from ksi_processing_controller.external_measurement_attempts import MeasurementAttemptRecoveryV2

    value = binding()
    journal = MeasurementAttemptJournalV2(tmp_path / "v2.jsonl")
    journal.intend(value)
    allocation = primary_receipt()
    parent = parent_receipt(value)
    if phase_index >= 1:
        journal.staging_allocated(value.attempt_nonce, allocation)
    if phase_index >= 2:
        journal.input_bound(
            value.attempt_nonce,
            artifact=primary_receipt(value.primary_input.observed_size_bytes).artifact,
            observed_size_bytes=value.primary_input.observed_size_bytes,
            observed_sha256=value.primary_input.observed_sha256,
            reader_mapping_witness="fixture-witness",
        )
    if phase_index >= 3:
        journal.runtime_parent_creating(value.attempt_nonce)
    if phase_index >= 4:
        journal.runtime_parent_bound(value.attempt_nonce, parent)
    if phase_index >= 5:
        journal.container_creating(value.attempt_nonce)
    if phase_index >= 6:
        journal.container_bound(value.attempt_nonce, "runtime-v2")
    events: list[str] = []

    class Staging:
        def recover_registered(self, *, plan: Any, receipt: Any) -> str:
            assert plan == value.staging
            assert receipt == (allocation if phase_index >= 1 else None)
            events.append("primary-cleaned")
            return "CLEANED"

    class Runtime:
        def resolve_exact(self, supplied: Any) -> str | None:
            assert supplied == value
            return "runtime-v2" if phase_index >= 5 else None

        def quiesce_exact(self, *, binding: Any, runtime_id: str) -> bool:
            assert binding == value and runtime_id == "runtime-v2"
            events.append("quiesced")
            return True

        def remove_exact(self, *, binding: Any, runtime_id: str) -> bool:
            assert binding == value and runtime_id == "runtime-v2"
            events.append("container-removed")
            return True

    class Parent:
        def adopt_if_prebound(self, *, binding: Any) -> Any:
            assert binding == value
            return parent if phase_index >= 3 else None

        def stop_exact(self, *, binding: Any, receipt: Any) -> bool:
            assert binding == value and receipt == parent
            events.append("parent-stopped")
            return True

        def verify_before_quiesce(self, **kwargs: Any) -> bool:
            return True

        def verify_final_before_remove(self, **kwargs: Any) -> bool:
            return True

    MeasurementAttemptRecoveryV2(
        journal=journal, staging=Staging(), runtime_registry=Runtime(), runtime_parent=Parent()
    ).recover_startup()
    assert journal.phase_of(value.attempt_nonce) is AttemptPhaseV1.CLEANED
    assert events[-1] == "primary-cleaned"
    if phase_index >= 5:
        assert events == ["quiesced", "container-removed", "parent-stopped", "primary-cleaned"]
    assert not any("secondary" in name for name in events)


def test_v2_receipt_rejects_v1_description_and_wrong_observed_primary(tmp_path: Path) -> None:
    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    value = binding()
    with pytest.raises(AttemptJournalError):
        RuntimeParentReceiptV1.from_wire(parent_receipt(value).wire())
    journal = MeasurementAttemptJournalV2(tmp_path / "v2.jsonl")
    journal.intend(value)
    journal.staging_allocated(value.attempt_nonce, primary_receipt())
    with pytest.raises(AttemptJournalError):
        journal.input_bound(
            value.attempt_nonce,
            artifact=primary_receipt(value.primary_input.observed_size_bytes).artifact,
            observed_size_bytes=value.primary_input.observed_size_bytes,
            observed_sha256="sha256:" + "0" * 64,
            reader_mapping_witness="fixture-witness",
        )
