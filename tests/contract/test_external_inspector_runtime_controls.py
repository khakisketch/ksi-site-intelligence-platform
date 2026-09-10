"""Pure fixed-runtime and aggregate CPU accounting contracts for Task 4A."""

from __future__ import annotations

import os
import time
from hashlib import sha256

import pytest
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionHardCeilingsV1,
    InspectorExecutionManifestBodyV1,
    InspectorExecutionManifestSignatureV1,
    InspectorExecutionManifestV1,
    InspectorImageIdentityV1,
    InspectorSecurityProfileV1,
)
from ksi_processing_controller.external_inspector_attempts import (
    PrivateStagingRootV1,
    StagingAllocationPlanV1,
)
from ksi_processing_controller.external_inspector_file_io import FileIoSealReceiptV1
from ksi_processing_controller.external_inspector_runtime import (
    AggregateCpuCounterV1,
    CpuAccountingError,
    CpuAccountingSession,
    CpuCounterUnitV1,
    FixedRuntimeControlSession,
    RuntimeControlDispositionV1,
    RuntimeControlUnavailable,
    cpu_seconds_to_counter_budget,
)
from ksi_processing_controller.external_inspector_staging import (
    FileSystemInputStaging,
    InspectorBorrowedSourcePort,
    InspectorReadOnlyBindV1,
    InspectorStagingUnavailable,
    MappedInspectorReaderV1,
)


class _BorrowedSource(InspectorBorrowedSourcePort):
    def verify_readback(self, *, deadline_monotonic: float) -> FileIoSealReceiptV1:
        del deadline_monotonic
        raise AssertionError("runtime-control test source does not verify bytes")

    def read_at(self, *, offset: int, maximum_bytes: int, deadline_monotonic: float) -> bytes:
        del offset, maximum_bytes, deadline_monotonic
        return b""

    def consume_fd(self, consumer, *, deadline_monotonic: float):  # type: ignore[no-untyped-def]
        del deadline_monotonic
        return consumer(42)


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _counter(value: int, *, descendants: bool = True) -> AggregateCpuCounterV1:
    return AggregateCpuCounterV1(
        value=value,
        unit=CpuCounterUnitV1.CPU_USEC,
        complete_process_tree=descendants,
    )


def _manifest() -> InspectorExecutionManifestV1:
    body = InspectorExecutionManifestBodyV1(
        image_identity=InspectorImageIdentityV1(
            oci_manifest_digest=_digest("a"), oci_config_digest=_digest("b")
        ),
        source_tree_digest=_digest("c"),
        build_provenance_digest=_digest("d"),
        sbom_digest=_digest("e"),
        inspector_protocol_digest=_digest("f"),
        backend_profile_digest=_digest("1"),
        security_profile_digest=_digest("2"),
        resource_envelope_digest=_digest("3"),
        backend="DEDICATED_ROOTLESS_DOCKER_V1",
        runtime_uid=10_001,
        runtime_gid=10_002,
        runtime_environment=(
            ("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"),
            ("GDAL_DRIVER_PATH", "disable"),
            ("GDAL_PAM_ENABLED", "NO"),
            ("PROJ_NETWORK", "OFF"),
            ("PYTHONDONTWRITEBYTECODE", "1"),
        ),
        security_profile=InspectorSecurityProfileV1(),
        hard_ceilings=InspectorExecutionHardCeilingsV1(
            max_input_bytes=100,
            max_memory_bytes=200,
            max_tmpfs_bytes=300,
            max_pids=4,
            cpu_period_micros=100_000,
            cpu_quota_micros=50_000,
            max_wall_time_millis=5_000,
            max_log_bytes=50,
            max_output_bytes=75,
        ),
    )
    return InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="key-1",
            digest=body.canonical_body_digest(),
            signature="A" * 86 + "==",
        ),
    )


def _runtime_limits():
    from ksi_processing_controller.external_inspector_container_protocol import (
        FixedRuntimeLimitsV1,
    )

    return FixedRuntimeLimitsV1(
        max_memory_bytes=200,
        max_workspace_bytes=300,
        max_output_bytes=75,
        max_wall_time_millis=5_000,
        max_pids=4,
        cpu_period_micros=100_000,
        cpu_quota_micros=50_000,
        max_log_bytes=50,
        max_cpu_seconds=2.0,
    )


def _read_only_bind(*, target_path: str = "/input/artifact.tif", read_only: bool = True):
    return InspectorReadOnlyBindV1(
        source=_BorrowedSource(),
        target_path=target_path,
        read_only=read_only,
        observed_sha256=_digest("4"),
        observed_size_bytes=12,
        source_device=10,
        source_inode=11,
        source_owner_uid=12,
        source_owner_gid=13,
        source_link_count=1,
        reader_mapping_witness="mapping-v1",
    )


def test_fixed_runtime_configuration_uses_only_manifest_literals_and_one_borrowed_mount() -> None:
    """No caller-selected image, environment, socket, mount, or privilege survives."""
    from ksi_processing_controller.external_inspector_container_protocol import (
        FixedContainerConfigurationV1,
        build_fixed_container_configuration,
    )

    configuration = build_fixed_container_configuration(
        manifest=_manifest(), limits=_runtime_limits(), input_bind=_read_only_bind()
    )

    assert isinstance(configuration, FixedContainerConfigurationV1)
    assert configuration.image_manifest_digest == _digest("a")
    assert configuration.image_config_digest == _digest("b")
    assert configuration.runtime_uid == 10_001
    assert configuration.runtime_gid == 10_002
    assert configuration.runtime_environment == _manifest().body.runtime_environment
    assert configuration.input_mount.target_path == "/input/artifact.tif"
    assert configuration.input_mount.read_only is True
    assert configuration.input_mount.source is not None
    assert configuration.extra_mounts == ()
    assert configuration.socket_mounts == ()
    assert configuration.network_disabled is True
    assert configuration.read_only_root_filesystem is True
    assert configuration.privileged is False
    assert configuration.no_new_privileges is True
    assert configuration.drop_all_capabilities is True
    assert configuration.credentials_injected is False
    assert configuration.memory_bytes == 200
    assert configuration.tmpfs_bytes == 300
    assert configuration.pids == 4
    assert configuration.cpu_budget_counter == 2_000_000


@pytest.mark.parametrize(
    ("target_path", "read_only"),
    [("/tmp/input.tif", True), ("/input/artifact.tif", False)],
)
def test_fixed_runtime_configuration_rejects_any_nonfixed_input_mount(
    target_path: str, read_only: bool
) -> None:
    """A path or writable-mount substitution must fail before a controller can create a runtime."""
    from ksi_processing_controller.external_inspector_container_protocol import (
        ContainerProtocolUnavailable,
        build_fixed_container_configuration,
    )

    with pytest.raises(ContainerProtocolUnavailable, match="input mount"):
        build_fixed_container_configuration(
            manifest=_manifest(),
            limits=_runtime_limits(),
            input_bind=_read_only_bind(target_path=target_path, read_only=read_only),
        )


def test_cpu_budget_conversion_uses_one_exact_integer_counter_unit() -> None:
    """A policy float cannot introduce an ambiguous counter threshold or a zero budget."""
    assert cpu_seconds_to_counter_budget(2.0, CpuCounterUnitV1.CPU_USEC) == 2_000_000
    assert cpu_seconds_to_counter_budget(0.000001, CpuCounterUnitV1.CPU_USEC) == 1
    with pytest.raises(RuntimeControlUnavailable, match="integer"):
        cpu_seconds_to_counter_budget(0.0000001, CpuCounterUnitV1.CPU_USEC)
    with pytest.raises(RuntimeControlUnavailable, match="positive"):
        cpu_seconds_to_counter_budget(0.0, CpuCounterUnitV1.CPU_USEC)


def test_concrete_admission_accounting_holds_and_releases_exact_capacity() -> None:
    """The production assembly has no successful unbounded accounting fallback."""
    from ksi_processing_controller.external_inspector_daemon import (
        BoundedInspectorAdmissionAccounting,
        InspectorAdmissionCapacityV1,
    )

    accounting = BoundedInspectorAdmissionAccounting(
        InspectorAdmissionCapacityV1(
            maximum_request_units=1,
            maximum_concurrency_units=1,
            maximum_spool_bytes=10,
        )
    )
    first = accounting.reserve(
        request_units=1,
        concurrency_units=1,
        spool_bytes=6,
        deadline_monotonic=time.monotonic() + 1.0,
    )
    assert first is not None
    assert (
        accounting.reserve(
            request_units=0,
            concurrency_units=0,
            spool_bytes=5,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        is None
    )
    first.release()
    assert (
        accounting.reserve(
            request_units=0,
            concurrency_units=0,
            spool_bytes=10,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        is not None
    )


@pytest.mark.parametrize(
    ("request_units", "concurrency_units", "spool_bytes"),
    ((0, 0, 101), (0, 2, 0), (1, 1, 101)),
)
def test_concrete_admission_accounting_rejects_each_dimension_independently(
    request_units: int, concurrency_units: int, spool_bytes: int
) -> None:
    """A spare request slot cannot permit excess spool or concurrency capacity."""
    from ksi_processing_controller.external_inspector_daemon import (
        BoundedInspectorAdmissionAccounting,
        InspectorAdmissionCapacityV1,
    )

    accounting = BoundedInspectorAdmissionAccounting(
        InspectorAdmissionCapacityV1(
            maximum_request_units=10,
            maximum_concurrency_units=1,
            maximum_spool_bytes=100,
        )
    )

    assert (
        accounting.reserve(
            request_units=request_units,
            concurrency_units=concurrency_units,
            spool_bytes=spool_bytes,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        is None
    )


def test_fixed_operation_profile_accepts_only_the_closed_geotiff_digest_and_literals() -> None:
    from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
    from ksi_processing_controller.external_geotiff_profile import (
        external_geotiff_profile_digest_v1,
    )
    from ksi_processing_controller.external_inspector_daemon import FixedInspectorOperationProfile
    from ksi_processing_controller.external_inspector_launcher import (
        InspectorOperationProfileDecision,
    )
    from ksi_processing_controller.external_inspector_protocol import InspectorOperation

    profile = FixedInspectorOperationProfile()
    assert (
        profile.allows(
            parser_build_digest=_digest("a"),
            grammar_digest=external_geotiff_profile_digest_v1(),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="image/tiff",
            operation=InspectorOperation.INSPECT,
        )
        is InspectorOperationProfileDecision.ALLOW
    )
    assert (
        profile.allows(
            parser_build_digest=_digest("a"),
            grammar_digest=_digest("b"),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="image/tiff",
            operation=InspectorOperation.INSPECT,
        )
        is InspectorOperationProfileDecision.DENY
    )


def test_nonzero_baseline_monitor_and_final_share_the_same_counter_facts() -> None:
    """Both checks use current minus baseline, so a pre-existing cgroup value is not charged."""
    accounting = CpuAccountingSession.start(_counter(500), budget=100)
    assert accounting.monitor(_counter(600)).consumed == 100
    final = accounting.final(_counter(600))
    assert final.baseline == 500
    assert final.final == 600
    assert final.consumed == 100
    assert final.within_budget is True


def test_cpu_excess_rollback_or_nonaggregate_counter_fails_closed() -> None:
    """A controller cannot conceal descendants, counter rollback, or an over-budget execution."""
    accounting = CpuAccountingSession.start(_counter(10), budget=5)
    assert accounting.monitor(_counter(16)).exceeded is True
    with pytest.raises(CpuAccountingError, match="rolled back"):
        accounting.final(_counter(9))
    with pytest.raises(RuntimeControlUnavailable, match="process tree"):
        CpuAccountingSession.start(_counter(1, descendants=False), budget=5)


def test_fixed_runtime_control_records_one_baseline_monitor_kill_and_final_measurement() -> None:
    """A fixed runtime reuses one controller unit and reports the measured kill latency only."""

    class _Counter:
        def __init__(self) -> None:
            self.values = iter((_counter(500), _counter(506), _counter(507)))

        def read_aggregate_cpu(self) -> AggregateCpuCounterV1:
            return next(self.values)

    class _Terminator:
        def __init__(self) -> None:
            self.runtime_ids: list[str] = []

        def terminate_exact(self, runtime_id: str) -> float:
            self.runtime_ids.append(runtime_id)
            return 0.125

    counter = _Counter()
    terminator = _Terminator()
    control = FixedRuntimeControlSession.start(
        runtime_id="runtime-1", counter=counter, terminator=terminator, budget=5
    )

    monitor = control.monitor()
    measurement = control.final(RuntimeControlDispositionV1.CPU_LIMIT_EXCEEDED)

    assert monitor.consumed == 6
    assert monitor.exceeded is True
    assert terminator.runtime_ids == ["runtime-1"]
    assert measurement.baseline_counter == 500
    assert measurement.final_counter == 507
    assert measurement.consumed_counter == 7
    assert measurement.budget_counter == 5
    assert measurement.kill_latency_seconds == 0.125


def test_registered_staging_allocation_uses_exact_marker_then_exact_cleanup(tmp_path) -> None:
    """The journaled deterministic allocation has no random-name fallback or broad cleanup."""

    class _Mapping:
        def resolve_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return MappedInspectorReaderV1(1, 1, 1, 1, "mapping")

    class _Acl:
        def grant_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

        def verifies_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

    root = tmp_path / "private"
    staging = FileSystemInputStaging(private_root=root, reader_mapping=_Mapping(), acl=_Acl())
    identity = staging.private_root_identity()
    assert isinstance(identity, PrivateStagingRootV1)
    plan = StagingAllocationPlanV1(
        attempt_nonce="attempt-1",
        binding_digest=_digest("a"),
        owner="worker-1",
        allocation_nonce="allocation-1",
        root=identity,
        staging_name="attempt-1",
        artifact_leaf="artifact",
        provisional_marker_name=".attempt-1.provisional",
        committed_marker_name=".attempt-1.committed",
    )

    mutable, receipt = staging.begin_registered(
        plan=plan, maximum_bytes=8, deadline_monotonic=time.monotonic() + 1.0
    )

    assert (root / plan.committed_marker_name).read_bytes() == plan.marker_bytes
    assert not (root / plan.provisional_marker_name).exists()
    assert (root / plan.staging_name / plan.artifact_leaf).exists()
    mutable.abort()
    staging.finalize_registered_cleanup(plan=plan, receipt=receipt)
    assert not (root / plan.committed_marker_name).exists()
    assert not (root / plan.staging_name).exists()


def test_registered_sealed_abort_retains_a_substituted_artifact(tmp_path) -> None:
    """Exact cleanup must fail closed instead of deleting a replacement under the recorded name."""

    class _Mapping:
        def resolve_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return MappedInspectorReaderV1(1, 1, 1, 1, "mapping")

    class _Acl:
        def grant_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

        def verifies_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

        def revoke_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

    root = tmp_path / "private"
    staging = FileSystemInputStaging(private_root=root, reader_mapping=_Mapping(), acl=_Acl())
    identity = staging.private_root_identity()
    plan = StagingAllocationPlanV1(
        attempt_nonce="attempt-substitute-1",
        binding_digest=_digest("d"),
        owner="worker-1",
        allocation_nonce="allocation-substitute-1",
        root=identity,
        staging_name="attempt-substitute-1",
        artifact_leaf="artifact",
        provisional_marker_name=".attempt-substitute-1.provisional",
        committed_marker_name=".attempt-substitute-1.committed",
    )
    mutable, _receipt = staging.begin_registered(
        plan=plan, maximum_bytes=8, deadline_monotonic=time.monotonic() + 1.0
    )
    payload = b"sealed"
    mutable.write(payload)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        reader=MappedInspectorReaderV1(1, 1, 1, 1, "mapping"),
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )
    artifact = root / plan.staging_name / plan.artifact_leaf
    artifact.unlink()
    artifact.write_bytes(b"replacement")
    os.chmod(artifact, 0o600)

    with pytest.raises(InspectorStagingUnavailable, match="identity"):
        sealed.abort()

    assert artifact.read_bytes() == b"replacement"
    assert (root / plan.committed_marker_name).exists()


def test_registered_staging_recovery_removes_only_an_exact_committed_marker(tmp_path) -> None:
    """The committed-only crash window is recoverable only from the recorded marker bytes."""
    from ksi_processing_controller.external_inspector_staging import (
        RegisteredStagingRecoveryDispositionV1,
    )

    class _Mapping:
        def resolve_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return MappedInspectorReaderV1(1, 1, 1, 1, "mapping")

    class _Acl:
        def grant_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

        def verifies_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

    root = tmp_path / "private"
    staging = FileSystemInputStaging(private_root=root, reader_mapping=_Mapping(), acl=_Acl())
    identity = staging.private_root_identity()
    plan = StagingAllocationPlanV1(
        attempt_nonce="attempt-recover-1",
        binding_digest=_digest("b"),
        owner="worker-1",
        allocation_nonce="allocation-recover-1",
        root=identity,
        staging_name="attempt-recover-1",
        artifact_leaf="artifact",
        provisional_marker_name=".attempt-recover-1.provisional",
        committed_marker_name=".attempt-recover-1.committed",
    )
    marker_fd = os.open(
        root / plan.committed_marker_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    try:
        os.write(marker_fd, plan.marker_bytes)
        os.fsync(marker_fd)
    finally:
        os.close(marker_fd)

    disposition = staging.recover_registered(plan=plan, receipt=None)

    assert disposition is RegisteredStagingRecoveryDispositionV1.CLEANED
    assert not (root / plan.committed_marker_name).exists()


@pytest.mark.parametrize(
    "crash_window", ["intended", "provisional", "both", "directory", "artifact"]
)
def test_registered_staging_recovery_cleans_each_recorded_prejournal_window(
    tmp_path, crash_window: str
) -> None:
    """Every allocation syscall boundary has an exact recorded-name cleanup path."""
    from ksi_processing_controller.external_inspector_staging import (
        RegisteredStagingRecoveryDispositionV1,
    )

    class _Mapping:
        def resolve_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return MappedInspectorReaderV1(1, 1, 1, 1, "mapping")

    class _Acl:
        def grant_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

        def verifies_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

    root = tmp_path / "private"
    staging = FileSystemInputStaging(private_root=root, reader_mapping=_Mapping(), acl=_Acl())
    identity = staging.private_root_identity()
    plan = StagingAllocationPlanV1(
        attempt_nonce=f"attempt-window-{crash_window}",
        binding_digest=_digest("c"),
        owner="worker-1",
        allocation_nonce=f"allocation-window-{crash_window}",
        root=identity,
        staging_name=f"attempt-window-{crash_window}",
        artifact_leaf="artifact",
        provisional_marker_name=f".attempt-window-{crash_window}.provisional",
        committed_marker_name=f".attempt-window-{crash_window}.committed",
    )

    if crash_window in {"provisional", "both"}:
        provisional = root / plan.provisional_marker_name
        provisional.write_bytes(plan.marker_bytes)
        os.chmod(provisional, 0o600)
    if crash_window in {"both", "directory", "artifact"}:
        committed = root / plan.committed_marker_name
        if crash_window == "both":
            os.link(root / plan.provisional_marker_name, committed)
        else:
            committed.write_bytes(plan.marker_bytes)
            os.chmod(committed, 0o600)
    if crash_window in {"directory", "artifact"}:
        directory = root / plan.staging_name
        directory.mkdir(mode=0o700)
        if crash_window == "artifact":
            artifact = directory / plan.artifact_leaf
            artifact.write_bytes(b"")
            os.chmod(artifact, 0o600)

    disposition = staging.recover_registered(plan=plan, receipt=None)

    assert disposition is RegisteredStagingRecoveryDispositionV1.CLEANED
    assert not (root / plan.provisional_marker_name).exists()
    assert not (root / plan.committed_marker_name).exists()
    assert not (root / plan.staging_name).exists()


def test_registered_staging_recovery_retains_an_unexpected_child(tmp_path) -> None:
    """A pathname is never enough authority to delete an allocation with an unknown child."""
    from ksi_processing_controller.external_inspector_staging import (
        RegisteredStagingRecoveryDispositionV1,
    )

    class _Mapping:
        def resolve_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return MappedInspectorReaderV1(1, 1, 1, 1, "mapping")

    class _Acl:
        def grant_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

        def verifies_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

    root = tmp_path / "private"
    staging = FileSystemInputStaging(private_root=root, reader_mapping=_Mapping(), acl=_Acl())
    identity = staging.private_root_identity()
    plan = StagingAllocationPlanV1(
        attempt_nonce="attempt-uncertain-1",
        binding_digest=_digest("c"),
        owner="worker-1",
        allocation_nonce="allocation-uncertain-1",
        root=identity,
        staging_name="attempt-uncertain-1",
        artifact_leaf="artifact",
        provisional_marker_name=".attempt-uncertain-1.provisional",
        committed_marker_name=".attempt-uncertain-1.committed",
    )
    (root / plan.committed_marker_name).write_bytes(plan.marker_bytes)
    os.chmod(root / plan.committed_marker_name, 0o600)
    os.mkdir(root / plan.staging_name, 0o700)
    (root / plan.staging_name / "unexpected").write_bytes(b"retain")
    os.chmod(root / plan.staging_name / "unexpected", 0o600)

    disposition = staging.recover_registered(plan=plan, receipt=None)

    assert disposition is RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
    assert (root / plan.committed_marker_name).exists()
    assert (root / plan.staging_name / "unexpected").exists()


def test_registered_staging_recovery_retains_a_malformed_recorded_marker(tmp_path) -> None:
    """A corrupt marker is an ownership uncertainty, never equivalent to an absent allocation."""
    from ksi_processing_controller.external_inspector_staging import (
        RegisteredStagingRecoveryDispositionV1,
    )

    class _Mapping:
        def resolve_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return MappedInspectorReaderV1(1, 1, 1, 1, "mapping")

    class _Acl:
        def grant_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

        def verifies_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return True

    root = tmp_path / "private"
    staging = FileSystemInputStaging(private_root=root, reader_mapping=_Mapping(), acl=_Acl())
    identity = staging.private_root_identity()
    plan = StagingAllocationPlanV1(
        attempt_nonce="attempt-corrupt-1",
        binding_digest=_digest("e"),
        owner="worker-1",
        allocation_nonce="allocation-corrupt-1",
        root=identity,
        staging_name="attempt-corrupt-1",
        artifact_leaf="artifact",
        provisional_marker_name=".attempt-corrupt-1.provisional",
        committed_marker_name=".attempt-corrupt-1.committed",
    )
    marker = root / plan.committed_marker_name
    marker.write_bytes(b"corrupt")
    os.chmod(marker, 0o600)

    disposition = staging.recover_registered(plan=plan, receipt=None)

    assert disposition is RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
    assert marker.read_bytes() == b"corrupt"


def test_private_output_spool_is_bounded_retained_and_exactly_retired(tmp_path) -> None:
    """A sanitizer spool is a launcher-owned 0600 file, never a reader bind."""
    from ksi_processing_controller.external_inspector_staging import FileSystemOutputStaging

    root = tmp_path / "output-private"
    root.mkdir(mode=0o700)
    staging = FileSystemOutputStaging(private_root=root)
    spool = staging.begin(maximum_bytes=5, deadline_monotonic=time.monotonic() + 1.0)

    spool.write(b"abc")
    with pytest.raises(InspectorStagingUnavailable, match="bound"):
        spool.write(b"def")
    spool.finish()

    assert spool.read() == b"abc"
    spool.abort()
    assert list(root.iterdir()) == []


def test_private_output_spool_is_unnamed_and_transfers_only_a_sealed_response_fd(tmp_path) -> None:
    """No pathname is available for a sanitizer result or for crash recovery."""
    from ksi_processing_controller.external_inspector_staging import (
        FileSystemOutputStaging,
        OutputSpoolStateV1,
    )

    root = tmp_path / "output-private"
    root.mkdir(mode=0o700)
    spool = FileSystemOutputStaging(private_root=root).begin(
        maximum_bytes=5, deadline_monotonic=time.monotonic() + 1.0
    )
    assert os.fstat(spool._descriptor).st_nlink == 0  # type: ignore[arg-type,attr-defined]
    assert list(root.iterdir()) == []
    spool.write(b"abc")
    spool.finish()
    response = spool.retain_for_response()

    assert response.state is OutputSpoolStateV1.RESPONSE_OWNED
    assert response.sha256 == "sha256:" + sha256(b"abc").hexdigest()
    response.abort()
    assert response.state is OutputSpoolStateV1.CLOSED
    assert list(root.iterdir()) == []


def test_concrete_namespace_mapping_and_fd_acl_prove_only_the_exact_reader(tmp_path) -> None:
    """The production adapters read explicit maps and grant no group/world fallback."""
    from ksi_processing_controller.external_inspector_access import (
        LibaclNamedReaderAcl,
        ProcUserNamespaceReaderMapping,
        UserNamespaceMappingConfigV1,
    )

    uid_map = tmp_path / "uid_map"
    gid_map = tmp_path / "gid_map"
    uid_map.write_text("10001 20001 1\n", encoding="ascii")
    gid_map.write_text("10002 20002 1\n", encoding="ascii")
    os.chmod(uid_map, 0o600)
    os.chmod(gid_map, 0o600)
    mapping = ProcUserNamespaceReaderMapping(
        UserNamespaceMappingConfigV1(
            uid_map_path=uid_map, gid_map_path=gid_map, maximum_map_bytes=1024
        )
    ).resolve_exact(
        runtime_uid=10001,
        runtime_gid=10002,
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )
    assert mapping is not None
    assert (mapping.host_uid, mapping.host_gid) == (20001, 20002)
    assert mapping.mapping_witness.startswith("sha256:")

    root = tmp_path / "private"
    attempt = root / "attempt"
    root.mkdir(mode=0o700)
    attempt.mkdir(mode=0o700)
    artifact = attempt / "artifact"
    artifact.write_bytes(b"sealed")
    os.chmod(artifact, 0o600)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    attempt_fd = os.open(attempt, os.O_RDONLY | os.O_DIRECTORY)
    artifact_fd = os.open(artifact, os.O_RDONLY)
    try:
        acl = LibaclNamedReaderAcl()
        assert acl.grant_exact(
            source_fd=artifact_fd,
            traversal_fds=(root_fd, attempt_fd),
            reader=mapping,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        assert acl.verifies_exact(
            source_fd=artifact_fd,
            traversal_fds=(root_fd, attempt_fd),
            reader=mapping,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        assert os.fstat(artifact_fd).st_mode & 0o007 == 0
        assert os.fstat(artifact_fd).st_mode & 0o070 == 0o040
        assert os.fstat(root_fd).st_mode & 0o777 == 0o710
        # The shared root remains usable only because libacl can prove the
        # single named traversal entry; a bare 0710 directory is rejected.
        staging = FileSystemInputStaging(private_root=root, reader_mapping=None, acl=acl)
        assert staging.private_root_identity().mode == 0o700
        assert acl.grant_exact(
            source_fd=artifact_fd,
            traversal_fds=(root_fd, attempt_fd),
            reader=mapping,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        assert acl.revoke_exact(
            source_fd=artifact_fd,
            traversal_fds=(root_fd, attempt_fd),
            reader=mapping,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        assert os.fstat(root_fd).st_mode & 0o777 == 0o700
        assert staging.private_root_identity().mode == 0o700
    finally:
        os.close(artifact_fd)
        os.close(attempt_fd)
        os.close(root_fd)


def test_exact_reader_acl_leases_share_one_reader_until_last_abort_and_recovery(
    tmp_path,
) -> None:
    """Concurrent sealed inputs share only one exact reader traversal ACL."""
    from ksi_processing_controller.external_inspector_access import LibaclNamedReaderAcl
    from ksi_processing_controller.external_inspector_staging import (
        RegisteredStagingRecoveryDispositionV1,
    )

    reader = MappedInspectorReaderV1(10_001, 10_002, 20_001, 20_002, "mapping")

    class _Mapping:
        def resolve_exact(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return reader

    root = tmp_path / "private"
    staging = FileSystemInputStaging(
        private_root=root, reader_mapping=_Mapping(), acl=LibaclNamedReaderAcl()
    )
    # Separate staging instances model two live launcher attempts which share
    # the provisioned private root, rather than relying on one object-local
    # cache.
    second_staging = FileSystemInputStaging(
        private_root=root, reader_mapping=_Mapping(), acl=LibaclNamedReaderAcl()
    )
    payload = b"sealed"
    digest = "sha256:" + sha256(payload).hexdigest()

    def plan_for(label: str) -> StagingAllocationPlanV1:
        return StagingAllocationPlanV1(
            attempt_nonce=f"attempt-{label}",
            binding_digest="sha256:" + sha256(label.encode("ascii")).hexdigest(),
            owner="worker-1",
            allocation_nonce=f"allocation-{label}",
            root=staging.private_root_identity(),
            staging_name=f"attempt-{label}",
            artifact_leaf="artifact",
            provisional_marker_name=f".attempt-{label}.provisional",
            committed_marker_name=f".attempt-{label}.committed",
        )

    def seal_for(current_staging, plan: StagingAllocationPlanV1):  # type: ignore[no-untyped-def]
        mutable, receipt = current_staging.begin_registered(
            plan=plan, maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0
        )
        mutable.write(payload)
        sealed = mutable.seal_for_reader(
            expected_sha256=digest,
            expected_size_bytes=len(payload),
            reader=reader,
            supplementary_groups=(),
            deadline_monotonic=time.monotonic() + 1.0,
        )
        return sealed, receipt

    first_plan = plan_for("one")
    first, first_receipt = seal_for(staging, first_plan)
    assert root.stat().st_mode & 0o777 == 0o710

    second_plan = plan_for("two")
    second, second_receipt = seal_for(second_staging, second_plan)
    assert (
        first.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0).observed_sha256
        == digest
    )
    first.abort()
    staging.finalize_registered_cleanup(plan=first_plan, receipt=first_receipt)
    # First cleanup does not revoke traversal that the second live reader needs.
    assert root.stat().st_mode & 0o777 == 0o710
    assert (
        second.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0).observed_sha256
        == digest
    )
    second.abort()
    second_staging.finalize_registered_cleanup(plan=second_plan, receipt=second_receipt)
    assert root.stat().st_mode & 0o777 == 0o700

    recovered_plan = plan_for("recovery")
    recovered, recovered_receipt = seal_for(staging, recovered_plan)
    recovered.relinquish_for_recovery()
    assert (
        staging.recover_registered(plan=recovered_plan, receipt=recovered_receipt)
        is RegisteredStagingRecoveryDispositionV1.CLEANED
    )
    # Recovery holds the root ACL until the coordinator finishes every record.
    assert root.stat().st_mode & 0o777 == 0o710
    staging.finish_recovery()
    assert root.stat().st_mode & 0o777 == 0o700


def test_failed_second_leaf_acl_transition_keeps_the_first_shared_root_lease(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial second leaf grant may not revoke the first reader's root traversal ACL."""
    from ksi_processing_controller.external_inspector_access import (
        InspectorAccessUnavailable,
        LibaclNamedReaderAcl,
    )

    reader = MappedInspectorReaderV1(10_001, 10_002, 20_001, 20_002, "mapping")
    root = tmp_path / "private"
    first_attempt = root / "first"
    second_attempt = root / "second"
    root.mkdir(mode=0o700)
    first_attempt.mkdir(mode=0o700)
    second_attempt.mkdir(mode=0o700)
    first_file = first_attempt / "artifact"
    second_file = second_attempt / "artifact"
    first_file.write_bytes(b"first")
    second_file.write_bytes(b"second")
    os.chmod(first_file, 0o600)
    os.chmod(second_file, 0o600)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    first_fd = os.open(first_attempt, os.O_RDONLY | os.O_DIRECTORY)
    second_fd = os.open(second_attempt, os.O_RDONLY | os.O_DIRECTORY)
    first_file_fd = os.open(first_file, os.O_RDONLY)
    second_file_fd = os.open(second_file, os.O_RDONLY)
    try:
        acl = LibaclNamedReaderAcl()
        assert acl.grant_exact(
            source_fd=first_file_fd,
            traversal_fds=(root_fd, first_fd),
            reader=reader,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        original_grant = acl._grant_fd  # noqa: SLF001 - partial real ACL transaction probe
        calls = 0

        def fail_second_grant(
            descriptor: int, uid: int, permission: int, *, is_directory: bool
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise InspectorAccessUnavailable("injected second leaf ACL failure")
            original_grant(descriptor, uid, permission, is_directory=is_directory)

        monkeypatch.setattr(acl, "_grant_fd", fail_second_grant)
        assert not acl.grant_leaf_exact(
            source_fd=second_file_fd,
            attempt_fd=second_fd,
            reader=reader,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        assert acl.verifies_exact(
            source_fd=first_file_fd,
            traversal_fds=(root_fd, first_fd),
            reader=reader,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        assert os.fstat(root_fd).st_mode & 0o777 == 0o710
        assert os.fstat(second_file_fd).st_mode & 0o777 == 0o600
        assert os.fstat(second_fd).st_mode & 0o777 == 0o700
        assert acl.revoke_exact(
            source_fd=first_file_fd,
            traversal_fds=(root_fd, first_fd),
            reader=reader,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        assert os.fstat(root_fd).st_mode & 0o777 == 0o700
    finally:
        os.close(second_file_fd)
        os.close(first_file_fd)
        os.close(second_fd)
        os.close(first_fd)
        os.close(root_fd)
