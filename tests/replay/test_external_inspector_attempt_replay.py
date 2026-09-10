"""Replay tests for processing-controller-local external inspector attempts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_processing_controller.external_inspector_attempts import (
    AttemptBindingV1,
    AttemptJournalError,
    AttemptPhaseV1,
    AttemptRecoveryUnavailable,
    InspectorAttemptJournal,
    InspectorAttemptRecovery,
    PrivateStagingRootV1,
    RuntimeParentReceiptV1,
    StagingAllocationPlanV1,
    StagingAllocationReceiptV1,
    StagingFileIdentityV1,
)


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _root() -> PrivateStagingRootV1:
    return PrivateStagingRootV1(device=11, inode=22, mode=0o700, owner_uid=1000, owner_gid=1000)


def _plan() -> StagingAllocationPlanV1:
    return StagingAllocationPlanV1(
        attempt_nonce="attempt-nonce-1",
        binding_digest=_digest("a"),
        owner="worker-1",
        allocation_nonce="allocation-nonce-1",
        root=_root(),
        staging_name="attempt-0123456789abcdef",
        artifact_leaf="artifact",
        provisional_marker_name=".attempt-0123456789abcdef.provisional",
        committed_marker_name=".attempt-0123456789abcdef.committed",
    )


def _binding() -> AttemptBindingV1:
    return AttemptBindingV1(
        attempt_nonce="attempt-nonce-1",
        canonical_input_digest=_digest("b"),
        operation="INSPECT",
        owner="worker-1",
        container_name="external-inspector-attempt-0123456789abcdef",
        systemd_slice_name="ksi-inspector-a0123456789abcdef.slice",
        systemd_base_slice="ksi-inspector.slice",
        execution_manifest_digest=_digest("c"),
        parser_build_digest=_digest("c"),
        oci_manifest_digest=_digest("d"),
        oci_config_digest=_digest("e"),
        backend_profile_digest=_digest("f"),
        security_profile_digest=_digest("1"),
        resource_envelope_digest=_digest("2"),
        inspector_protocol_digest=_digest("3"),
        cpu_budget_counter=1_000_000,
        staging=_plan(),
    )


def _identity(inode: int, *, mode: int = 0o600, size: int = 0) -> StagingFileIdentityV1:
    return StagingFileIdentityV1(
        device=11,
        inode=inode,
        mode=mode,
        owner_uid=1000,
        owner_gid=1000,
        link_count=1,
        size=size,
    )


def _receipt() -> StagingAllocationReceiptV1:
    return StagingAllocationReceiptV1(
        marker=_identity(31),
        directory=_identity(32, mode=0o700),
        artifact=_identity(33),
    )


def _runtime_parent_receipt(binding: AttemptBindingV1) -> RuntimeParentReceiptV1:
    return RuntimeParentReceiptV1(
        unit_name=binding.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/ksi_2dinspector.slice",
        description="ksi-external-inspector-attempt.v1:" + binding.digest,
        slice_name=binding.systemd_base_slice,
        control_group="/base.slice/" + binding.systemd_slice_name,
        invocation_id="a" * 32,
        device=11,
        inode=44,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=7,
        cpu_budget_counter=100,
    )


class _NoRuntimeParent:
    def adopt_if_prebound(self, *, binding: AttemptBindingV1) -> None:
        del binding
        return None

    def stop_exact(self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1) -> bool:
        del binding, receipt
        return True

    def verify_before_quiesce(
        self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool:
        del binding, receipt, runtime_id
        return True

    def verify_final_before_remove(
        self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool:
        del binding, receipt, runtime_id
        return True


def test_journal_fsyncs_closed_canonical_lifecycle_and_reopens(tmp_path: Path) -> None:
    """A completed attempt has one immutable chain and no pre-cleanup acceptance state."""
    journal_path = tmp_path / "attempts.jsonl"
    journal = InspectorAttemptJournal(journal_path, clock=lambda: datetime(2026, 9, 8, tzinfo=UTC))
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())
    journal.input_bound(
        binding.attempt_nonce,
        artifact=_identity(33, size=12),
        observed_size_bytes=12,
        observed_sha256=_digest("4"),
        reader_mapping_witness="mapping-v1",
    )
    journal.runtime_parent_creating(binding.attempt_nonce)
    journal.runtime_parent_bound(
        binding.attempt_nonce,
        _runtime_parent_receipt(binding),
    )
    journal.container_creating(binding.attempt_nonce)
    journal.container_bound(binding.attempt_nonce, "runtime-id-1")
    journal.cleanup_required(binding.attempt_nonce, disposition="BACKEND_COMPLETED")
    journal.cleaned(binding.attempt_nonce)

    restarted = InspectorAttemptJournal(
        journal_path, clock=lambda: datetime(2026, 9, 8, tzinfo=UTC)
    )
    assert restarted.phase_of(binding.attempt_nonce) is AttemptPhaseV1.CLEANED
    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert [event["phase"] for event in events] == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "RUNTIME_PARENT_BOUND",
        "CONTAINER_CREATING",
        "CONTAINER_BOUND",
        "CLEANUP_REQUIRED",
        "CLEANED",
    ]
    assert (
        events[0]["eventDigest"]
        == "sha256:"
        + sha256(
            canonical_json_bytes(
                {key: value for key, value in events[0].items() if key != "eventDigest"}
            )
        ).hexdigest()
    )
    with pytest.raises(AttemptJournalError, match="retired"):
        restarted.intend(binding)


def test_input_bound_requires_the_recorded_staged_inode(tmp_path: Path) -> None:
    """A seal cannot bind a substituted inode after allocation is durable."""
    journal = InspectorAttemptJournal(tmp_path / "attempts.jsonl")
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())

    with pytest.raises(AttemptJournalError, match="inode"):
        journal.input_bound(
            binding.attempt_nonce,
            artifact=_identity(34, size=12),
            observed_size_bytes=12,
            observed_sha256=_digest("4"),
            reader_mapping_witness="mapping-v1",
        )


def test_replay_rejects_reordered_or_digest_tampered_attempt_events(tmp_path: Path) -> None:
    """Syntax-valid event JSON cannot skip lifecycle ordering or rewrite the chain."""
    journal_path = tmp_path / "attempts.jsonl"
    journal = InspectorAttemptJournal(journal_path)
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())
    journal.close()

    records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    journal_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in reversed(records)) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AttemptJournalError):
        InspectorAttemptJournal(journal_path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda event: event.__setitem__("version", "external-inspector-attempt.v2"),
        lambda event: event.__setitem__("timestamp", "2026-09-08T00:00:00+00:00"),
        lambda event: event.__setitem__("unexpected", "accepted-before-review"),
        lambda event: event["sealedInput"].__setitem__("extra", "accepted-before-review"),
    ],
)
def test_replay_rejects_noncanonical_versions_times_and_closed_event_fields(
    tmp_path: Path, mutation
) -> None:  # type: ignore[no-untyped-def]
    """A valid hash chain cannot smuggle a new version, field, or timestamp spelling."""
    journal_path = tmp_path / "attempts.jsonl"
    journal = InspectorAttemptJournal(journal_path, clock=lambda: datetime(2026, 9, 8, tzinfo=UTC))
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())
    journal.input_bound(
        binding.attempt_nonce,
        artifact=_identity(33, size=12),
        observed_size_bytes=12,
        observed_sha256=_digest("4"),
        reader_mapping_witness="mapping-v1",
    )
    journal.close()
    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    target = events[-1] if "sealedInput" in mutation.__code__.co_consts else events[0]
    mutation(target)
    previous: str | None = None
    for event in events:
        event["previousEventDigest"] = previous
        event["eventDigest"] = (
            "sha256:"
            + sha256(
                canonical_json_bytes(
                    {key: value for key, value in event.items() if key != "eventDigest"}
                )
            ).hexdigest()
        )
        previous = event["eventDigest"]
    journal_path.write_text(
        "".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events
        ),
        encoding="utf-8",
    )

    with pytest.raises(AttemptJournalError):
        InspectorAttemptJournal(journal_path)


def test_marker_payload_is_closed_and_binds_the_plan_exactly() -> None:
    """Marker identity cannot be reconstructed from a pathname or an omitted nonce field."""
    plan = _plan()
    payload = plan.marker_payload()
    assert payload == {
        "version": "external-inspector-staging-marker.v1",
        "attemptNonce": "attempt-nonce-1",
        "bindingDigest": _digest("a"),
        "stagingName": "attempt-0123456789abcdef",
        "owner": "worker-1",
        "allocationNonce": "allocation-nonce-1",
    }
    assert plan.marker_sha256 == "sha256:" + sha256(canonical_json_bytes(payload)).hexdigest()


def test_startup_recovery_closes_only_a_recorded_allocation(tmp_path: Path) -> None:
    """Recovery writes CLEANED only after one exact plan/receipt recovery succeeds."""

    class _RecoveryStaging:
        def __init__(self) -> None:
            self.calls: list[tuple[StagingAllocationPlanV1, StagingAllocationReceiptV1 | None]] = []

        def recover_registered(
            self,
            *,
            plan: StagingAllocationPlanV1,
            receipt: StagingAllocationReceiptV1 | None,
        ) -> str:
            self.calls.append((plan, receipt))
            return "CLEANED"

    class _RuntimeRegistry:
        def resolve_exact(self, binding: AttemptBindingV1) -> None:
            del binding
            return None

        def remove_exact(self, *, binding: AttemptBindingV1, runtime_id: str) -> bool:
            del binding, runtime_id
            return True

    journal = InspectorAttemptJournal(tmp_path / "attempts.jsonl")
    binding = _binding()
    journal.intend(binding)
    staging = _RecoveryStaging()

    InspectorAttemptRecovery(
        journal=journal,
        staging=staging,
        runtime_registry=_RuntimeRegistry(),
        runtime_parent=_NoRuntimeParent(),
    ).recover_startup()

    assert staging.calls == [(binding.staging, None)]
    assert journal.phase_of(binding.attempt_nonce) is AttemptPhaseV1.CLEANED


def test_startup_recovery_records_uncertain_ownership_and_closes_admission(tmp_path: Path) -> None:
    """An unknown node is retained, written as uncertainty, and prevents a later admission."""

    class _UncertainStaging:
        def recover_registered(
            self,
            *,
            plan: StagingAllocationPlanV1,
            receipt: StagingAllocationReceiptV1 | None,
        ) -> str:
            del plan, receipt
            return "OWNERSHIP_UNCERTAIN"

    class _RuntimeRegistry:
        def resolve_exact(self, binding: AttemptBindingV1) -> None:
            del binding
            return None

        def remove_exact(self, *, binding: AttemptBindingV1, runtime_id: str) -> bool:
            del binding, runtime_id
            return True

    journal = InspectorAttemptJournal(tmp_path / "attempts.jsonl")
    binding = _binding()
    journal.intend(binding)

    with pytest.raises(AttemptRecoveryUnavailable, match="ownership"):
        InspectorAttemptRecovery(
            journal=journal,
            staging=_UncertainStaging(),
            runtime_registry=_RuntimeRegistry(),
            runtime_parent=_NoRuntimeParent(),
        ).recover_startup()

    assert journal.phase_of(binding.attempt_nonce) is AttemptPhaseV1.CLEANUP_FAILED


def test_startup_recovery_removes_only_an_exact_runtime_resolved_from_input_bound(
    tmp_path: Path,
) -> None:
    """The pre-ID crash window can recover one matching runtime without a label inventory."""

    class _RecoveryStaging:
        def recover_registered(
            self,
            *,
            plan: StagingAllocationPlanV1,
            receipt: StagingAllocationReceiptV1 | None,
        ) -> str:
            del plan, receipt
            return "CLEANED"

    class _RuntimeRegistry:
        def __init__(self) -> None:
            self.bindings: list[AttemptBindingV1] = []
            self.removed: list[str] = []

        def resolve_exact(self, binding: AttemptBindingV1) -> str:
            self.bindings.append(binding)
            return "runtime-1"

        def remove_exact(self, *, binding: AttemptBindingV1, runtime_id: str) -> bool:
            assert binding == _binding()
            self.removed.append(runtime_id)
            return True

        def quiesce_exact(self, *, binding: AttemptBindingV1, runtime_id: str) -> bool:
            assert binding == _binding()
            assert runtime_id == "runtime-1"
            return True

    journal = InspectorAttemptJournal(tmp_path / "attempts.jsonl")
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())
    journal.input_bound(
        binding.attempt_nonce,
        artifact=_identity(33, size=12),
        observed_size_bytes=12,
        observed_sha256=_digest("4"),
        reader_mapping_witness="mapping-v1",
    )
    journal.runtime_parent_creating(binding.attempt_nonce)
    journal.runtime_parent_bound(binding.attempt_nonce, _runtime_parent_receipt(binding))
    journal.container_creating(binding.attempt_nonce)
    runtime_registry = _RuntimeRegistry()

    InspectorAttemptRecovery(
        journal=journal,
        staging=_RecoveryStaging(),
        runtime_registry=runtime_registry,
        runtime_parent=_NoRuntimeParent(),
    ).recover_startup()

    assert runtime_registry.bindings == [binding]
    assert runtime_registry.removed == ["runtime-1"]
    assert journal.phase_of(binding.attempt_nonce) is AttemptPhaseV1.CLEANED


def test_startup_recovery_adopts_only_input_bound_parent_before_runtime_lookup(
    tmp_path: Path,
) -> None:
    """A slice created before its receipt is journaled is adopted once, before Engine lookup."""

    class _RecoveryStaging:
        def recover_registered(self, **kwargs: object) -> str:
            del kwargs
            return "CLEANED"

    class _RuntimeRegistry:
        def __init__(self, order: list[str]) -> None:
            self._order = order

        def resolve_exact(self, binding: AttemptBindingV1) -> None:
            del binding
            self._order.append("resolve")
            return None

        def remove_exact(self, **kwargs: object) -> bool:
            del kwargs
            self._order.append("remove")
            return True

        def quiesce_exact(self, **kwargs: object) -> bool:
            del kwargs
            self._order.append("quiesce")
            return True

    class _RuntimeParent:
        def __init__(self, order: list[str]) -> None:
            self._order = order

        def adopt_if_prebound(self, *, binding: AttemptBindingV1) -> RuntimeParentReceiptV1 | None:
            self._order.append("adopt")
            return RuntimeParentReceiptV1(
                unit_name=binding.systemd_slice_name,
                object_path="/org/freedesktop/systemd1/unit/adopted",
                description="ksi-external-inspector-attempt.v1:" + binding.digest,
                slice_name=binding.systemd_base_slice,
                control_group="/base.slice/" + binding.systemd_slice_name,
                invocation_id="a" * 32,
                device=11,
                inode=44,
                controllers=("cpu", "memory", "pids"),
                cpu_counter_unit="CPU_USEC",
                baseline_cpu_counter=7,
                cpu_budget_counter=100,
            )

        def stop_exact(self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1) -> bool:
            assert receipt.unit_name == binding.systemd_slice_name
            self._order.append("stop")
            return True

        def verify_final_before_remove(
            self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
        ) -> bool:
            assert receipt.unit_name == binding.systemd_slice_name
            assert runtime_id == ""
            self._order.append("final")
            return True

    journal = InspectorAttemptJournal(tmp_path / "attempts.jsonl")
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())
    journal.input_bound(
        binding.attempt_nonce,
        artifact=_identity(33, size=12),
        observed_size_bytes=12,
        observed_sha256=_digest("4"),
        reader_mapping_witness="mapping-v1",
    )
    journal.runtime_parent_creating(binding.attempt_nonce)
    order: list[str] = []

    InspectorAttemptRecovery(
        journal=journal,
        staging=_RecoveryStaging(),
        runtime_registry=_RuntimeRegistry(order),
        runtime_parent=_RuntimeParent(order),
    ).recover_startup()

    assert order == ["adopt", "resolve", "stop"]
    assert journal.phase_of(binding.attempt_nonce) is AttemptPhaseV1.CLEANED


def test_startup_recovery_retains_unresolved_parent_create_intent(tmp_path: Path) -> None:
    """A missing post-crash slice observation cannot turn a pre-receipt create into CLEANED."""

    class _Staging:
        def recover_registered(self, **kwargs: object) -> str:
            del kwargs
            raise AssertionError("uncertain parent creation must retain registered staging")

    journal = InspectorAttemptJournal(tmp_path / "attempts.jsonl")
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())
    journal.input_bound(
        binding.attempt_nonce,
        artifact=_identity(33, size=12),
        observed_size_bytes=12,
        observed_sha256=_digest("4"),
        reader_mapping_witness="mapping-v1",
    )
    journal.runtime_parent_creating(binding.attempt_nonce)

    with pytest.raises(AttemptRecoveryUnavailable, match="creation outcome"):
        InspectorAttemptRecovery(
            journal=journal,
            staging=_Staging(),
            runtime_registry=object(),  # type: ignore[arg-type]
            runtime_parent=_NoRuntimeParent(),
        ).recover_startup()

    assert journal.phase_of(binding.attempt_nonce) is AttemptPhaseV1.CLEANUP_FAILED


def test_startup_recovery_resolves_a_lost_create_id_after_cleanup_failed(
    tmp_path: Path,
) -> None:
    """A post-create interruption remains recoverable after the journal enters cleanup."""

    class _Staging:
        def recover_registered(self, **kwargs: object) -> str:
            del kwargs
            return "CLEANED"

    class _Registry:
        def __init__(self, order: list[str]) -> None:
            self._order = order

        def resolve_exact(self, binding: AttemptBindingV1) -> str:
            assert binding == _binding()
            self._order.append("resolve")
            return "runtime-1"

        def quiesce_exact(self, *, binding: AttemptBindingV1, runtime_id: str) -> bool:
            assert binding == _binding()
            assert runtime_id == "runtime-1"
            self._order.append("quiesce")
            return True

        def remove_exact(self, *, binding: AttemptBindingV1, runtime_id: str) -> bool:
            assert binding == _binding()
            assert runtime_id == "runtime-1"
            self._order.append("remove")
            return True

    class _Parent(_NoRuntimeParent):
        def __init__(self, order: list[str]) -> None:
            self._order = order

        def verify_before_quiesce(
            self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
        ) -> bool:
            assert binding == _binding()
            assert receipt == _runtime_parent_receipt(binding)
            assert runtime_id == "runtime-1"
            self._order.append("pre")
            return True

        def verify_final_before_remove(
            self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
        ) -> bool:
            assert binding == _binding()
            assert receipt == _runtime_parent_receipt(binding)
            assert runtime_id == "runtime-1"
            self._order.append("final")
            return True

        def stop_exact(self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1) -> bool:
            assert binding == _binding()
            assert receipt == _runtime_parent_receipt(binding)
            self._order.append("stop")
            return True

    journal = InspectorAttemptJournal(tmp_path / "attempts.jsonl")
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())
    journal.input_bound(
        binding.attempt_nonce,
        artifact=_identity(33, size=12),
        observed_size_bytes=12,
        observed_sha256=_digest("4"),
        reader_mapping_witness="mapping-v1",
    )
    journal.runtime_parent_creating(binding.attempt_nonce)
    journal.runtime_parent_bound(binding.attempt_nonce, _runtime_parent_receipt(binding))
    journal.container_creating(binding.attempt_nonce)
    journal.cleanup_required(binding.attempt_nonce, disposition="POST_CREATE_INTERRUPTED")
    journal.cleanup_failed(binding.attempt_nonce, reason="EXACT_RUNTIME_CLEANUP_UNAVAILABLE")
    order: list[str] = []

    InspectorAttemptRecovery(
        journal=journal,
        staging=_Staging(),
        runtime_registry=_Registry(order),
        runtime_parent=_Parent(order),
    ).recover_startup()

    assert order == ["resolve", "pre", "quiesce", "final", "remove", "stop"]
    assert journal.phase_of(binding.attempt_nonce) is AttemptPhaseV1.CLEANED


def test_restart_retains_parent_creation_origin_until_exact_receipt_is_recovered(
    tmp_path: Path,
) -> None:
    """A failed pre-receipt parent create cannot silently degrade into staging-only cleanup."""

    class _Staging:
        def __init__(self, calls: list[str]) -> None:
            self._calls = calls

        def recover_registered(self, **kwargs: object) -> str:
            del kwargs
            self._calls.append("staging")
            return "CLEANED"

    class _Registry:
        def resolve_exact(self, binding: AttemptBindingV1) -> None:
            del binding
            return None

        def quiesce_exact(self, **kwargs: object) -> bool:
            del kwargs
            return True

        def remove_exact(self, **kwargs: object) -> bool:
            del kwargs
            return True

    class _Parent:
        def __init__(self, calls: list[str], receipts: list[RuntimeParentReceiptV1 | None]) -> None:
            self._calls = calls
            self._receipts = receipts

        def adopt_if_prebound(self, *, binding: AttemptBindingV1) -> RuntimeParentReceiptV1 | None:
            self._calls.append("adopt")
            receipt = self._receipts.pop(0)
            if receipt is not None:
                assert receipt == _runtime_parent_receipt(binding)
            return receipt

        def stop_exact(self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1) -> bool:
            assert receipt == _runtime_parent_receipt(binding)
            self._calls.append("stop")
            return True

        def verify_before_quiesce(self, **kwargs: object) -> bool:
            del kwargs
            return True

        def verify_final_before_remove(self, **kwargs: object) -> bool:
            del kwargs
            return True

    journal_path = tmp_path / "attempts.jsonl"
    journal = InspectorAttemptJournal(journal_path)
    binding = _binding()
    journal.intend(binding)
    journal.staging_allocated(binding.attempt_nonce, _receipt())
    journal.input_bound(
        binding.attempt_nonce,
        artifact=_identity(33, size=12),
        observed_size_bytes=12,
        observed_sha256=_digest("4"),
        reader_mapping_witness="mapping-v1",
    )
    journal.runtime_parent_creating(binding.attempt_nonce)
    journal.cleanup_required(binding.attempt_nonce, disposition="RUNTIME_PARENT_CREATE_AMBIGUOUS")
    journal.cleanup_failed(binding.attempt_nonce, reason="EXACT_CREATE_OUTCOME_UNAVAILABLE")
    journal.close()

    first_calls: list[str] = []
    with pytest.raises(AttemptRecoveryUnavailable, match="creation outcome"):
        InspectorAttemptRecovery(
            journal=InspectorAttemptJournal(journal_path),
            staging=_Staging(first_calls),
            runtime_registry=_Registry(),
            runtime_parent=_Parent(first_calls, [None]),
        ).recover_startup()
    assert first_calls == ["adopt"]

    second_calls: list[str] = []
    restarted = InspectorAttemptJournal(journal_path)
    InspectorAttemptRecovery(
        journal=restarted,
        staging=_Staging(second_calls),
        runtime_registry=_Registry(),
        runtime_parent=_Parent(second_calls, [_runtime_parent_receipt(binding)]),
    ).recover_startup()

    assert second_calls == ["adopt", "stop", "staging"]
    assert restarted.phase_of(binding.attempt_nonce) is AttemptPhaseV1.CLEANED
