"""Synthetic child protocol and trusted generated raster tests; not host containment proof."""

import json
import subprocess
import sys
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from spatial_data_fixture import (
    NOW,
    make_grant,
    make_job,
    make_policy,
    make_receipt,
    make_request,
    make_source,
)
from test_external_native_window import _envelope, _inspection, _write_dsm, _write_ortho


class SyntheticLauncher:
    """A controllable test child, never selected by production config or default."""

    def __init__(self, mode: str = "good", *, proof: bool = True) -> None:
        self.mode, self.proof = mode, proof
        self.process: subprocess.Popen[bytes] | None = None

    def launch(self, *, workspace: Path, job: Any) -> Any:
        receipt = make_receipt(
            prepared_at=NOW,
            output_sha256="sha256:" + sha256(b"candidate").hexdigest(),
            output_size_bytes=9,
        )
        script = """
import json, os, struct, sys, time
mode, directory, encoded = sys.argv[1:]
def emit(body):
    data = json.dumps(body, separators=(',', ':')).encode()
    sys.stdout.buffer.write(struct.pack('>I', len(data)) + data)
    sys.stdout.buffer.flush()
emit({'version':'spatial-data-sandbox-ready.v1','pid':os.getpid(),'ready':True})
head = sys.stdin.buffer.read(4)
if not head: sys.exit(0)
request = json.loads(sys.stdin.buffer.read(struct.unpack('>I', head)[0]))
if mode == 'hang': time.sleep(10)
if mode == 'crash': sys.exit(7)
with open(directory + '/candidate.tif', 'wb') as f: f.write(b'candidate')
os.chmod(directory + '/candidate.tif', 0o600)
if mode == 'oversize':
    sys.stdout.buffer.write(struct.pack('>I', 2000000)); sys.stdout.buffer.flush(); time.sleep(10)
elif mode == 'log':
    print('unframed private child log', flush=True)
elif mode == 'duplicate':
    raw = b'{"version":"spatial-data-sandbox-result.v1","version":"other"}'
    sys.stdout.buffer.write(struct.pack('>I', len(raw)) + raw); sys.stdout.buffer.flush()
else:
    emit({'version':'spatial-data-sandbox-result.v1','receipt':json.loads(encoded),'reason':None})
    if mode == 'trailing': sys.stdout.buffer.write(b'x'); sys.stdout.buffer.flush()
"""
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                self.mode,
                str(workspace),
                receipt.model_dump_json(by_alias=True),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env={},
        )
        return self.process

    def verify_containment(self, *, process: Any, job: Any) -> Any:
        return self.proof


def test_sandbox_requires_launcher_proof_before_sending_work(tmp_path: Path) -> None:
    from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox
    from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError

    launcher = SyntheticLauncher(proof=False)
    sandbox = SpatialDataSandbox(
        launcher=launcher, clock=lambda: NOW, wall_timeout_seconds=0.2, heartbeat_interval_millis=20
    )
    with pytest.raises(SpatialDataWorkerError, match="ACTIVATION_UNAVAILABLE"):
        sandbox.prepare(
            job=make_job(),
            source_path=tmp_path / "source.tif",
            output_parent=tmp_path,
            is_current=lambda: True,
        )
    assert launcher.process is not None and launcher.process.poll() is not None
    assert not (tmp_path / "candidate.tif").exists()


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("hang", "DEADLINE_EXCEEDED"),
        ("crash", "RASTER_PREPARATION_FAILED"),
        ("oversize", "RESOURCE_LIMIT_EXCEEDED"),
        ("log", "RESOURCE_LIMIT_EXCEEDED"),
        ("duplicate", "OUTPUT_VERIFICATION_FAILED"),
        ("trailing", "OUTPUT_VERIFICATION_FAILED"),
    ],
)
def test_sandbox_bounds_control_frames_and_reaps_failed_children(
    tmp_path: Path, mode: str, reason: str
) -> None:
    from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox
    from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError

    launcher = SyntheticLauncher(mode)
    sandbox = SpatialDataSandbox(
        launcher=launcher,
        clock=lambda: NOW,
        wall_timeout_seconds=0.25,
        heartbeat_interval_millis=20,
    )
    with pytest.raises(SpatialDataWorkerError, match=reason):
        sandbox.prepare(
            job=make_job(),
            source_path=tmp_path / "source.tif",
            output_parent=tmp_path,
            is_current=lambda: True,
        )
    assert launcher.process is not None and launcher.process.poll() is not None
    assert not (tmp_path / "candidate.tif").exists()


def test_sandbox_returns_only_sealed_framed_receipt_and_no_child_logs(tmp_path: Path) -> None:
    from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox

    launcher = SyntheticLauncher()
    sandbox = SpatialDataSandbox(
        launcher=launcher, clock=lambda: NOW, wall_timeout_seconds=1.0, heartbeat_interval_millis=20
    )
    receipt = sandbox.prepare(
        job=make_job(),
        source_path=tmp_path / "source.tif",
        output_parent=tmp_path,
        is_current=lambda: True,
    )
    assert (
        receipt.output_sha256
        == "sha256:" + sha256((tmp_path / "candidate.tif").read_bytes()).hexdigest()
    )
    assert receipt.accuracy_assessed is False
    assert launcher.process is not None and launcher.process.poll() == 0


def test_sandbox_lease_loss_interrupts_wait_and_reaps_process_group(tmp_path: Path) -> None:
    from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox
    from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError

    launcher = SyntheticLauncher("hang")
    calls = 0

    def current() -> bool:
        nonlocal calls
        calls += 1
        return calls < 5

    sandbox = SpatialDataSandbox(
        launcher=launcher, clock=lambda: NOW, wall_timeout_seconds=1.0, heartbeat_interval_millis=20
    )
    with pytest.raises(SpatialDataWorkerError, match="CURRENTNESS_UNAVAILABLE"):
        sandbox.prepare(
            job=make_job(),
            source_path=tmp_path / "source.tif",
            output_parent=tmp_path,
            is_current=current,
        )
    assert launcher.process is not None and launcher.process.poll() is not None
    assert not (tmp_path / "candidate.tif").exists()


def native_job(path: Path, *, kind: str = "dsm") -> Any:
    inspection = _inspection(path, artifact_kind=ProcessingArtifactKind(kind))
    assert inspection.measurements is not None
    source = make_source(
        artifact_id=inspection.artifact_id,
        artifact_kind=kind,
        observed_sha256=inspection.observed_sha256,
        observed_size_bytes=path.stat().st_size,
        inspection=inspection,
    )
    policy = make_policy(
        resource_envelope=_envelope(max_workspace_bytes=6000000),
        max_output_bytes=1000000,
        max_output_pixels=100,
        max_stream_bytes=1000000,
        max_attempts=1,
        max_active_jobs_per_organization=1,
        max_pending_records=1,
        max_active_downloads_per_organization=1,
    )
    request = make_request(
        requested_bounds=(102.1, 183.9, 108.1, 193.9),
        observed_crs_digest=inspection.measurements.observed_crs_digest,
    )
    grant = make_grant(
        allowed_bounds=(100, 180, 120, 200),
        observed_crs_digest=request.observed_crs_digest,
        policy_digest=policy.policy_digest,
        attribution="Generated raster; fixture attribution",
    )
    return make_job(
        source=source,
        request=request,
        request_fingerprint=request.canonical_digest(),
        policy=policy,
        grant=grant,
    )


@pytest.mark.parametrize("kind", ["dsm", "ortho"])
def test_trusted_synthetic_native_preparation_preserves_grid_pixels_mask_receipt(
    tmp_path: Path, kind: str
) -> None:
    """Real raster primitive plus data receipt adaptation, not synthetic measurement arithmetic."""
    from ksi_processing_controller.spatial_data_entrypoint import prepare_native_candidate

    source = tmp_path / "source.tif"
    pixels = _write_dsm(source)[0] if kind == "dsm" else _write_ortho(source)
    job = native_job(source, kind=kind)
    receipt = prepare_native_candidate(
        job=job,
        source_path=source,
        output_parent=tmp_path,
        prepared_at=NOW,
        is_current=lambda: True,
    )
    output = tmp_path / "candidate.tif"
    assert receipt.pixel_window == (1, 5, 3, 9)
    assert receipt.actual_bounds == (102, 182, 110, 194)
    assert receipt.transform == (2, 0, 102, 0, -2, 194)
    assert receipt.output_sha256 == "sha256:" + sha256(output.read_bytes()).hexdigest()
    assert receipt.attribution == "Generated raster; fixture attribution"
    assert (
        receipt.accuracy_assessed is False and "UNKNOWN_VERTICAL_REFERENCE" in receipt.limitations
    )
    with rasterio.open(output) as dataset:
        assert "PRODUCER_NOTE" not in dataset.tags()
        expected = pixels[3:9, 1:5] if kind == "dsm" else pixels[:, 3:9, 1:5]
        actual = dataset.read(1) if kind == "dsm" else dataset.read()
        np.testing.assert_array_equal(actual, expected)


def test_trusted_synthetic_native_failure_preserves_typed_reason_and_removes_partial(
    tmp_path: Path,
) -> None:
    from ksi_geo_spatial.external_native_window_geometry import NativeWindowError
    from ksi_processing_controller.spatial_data_entrypoint import prepare_native_candidate

    source = tmp_path / "source.tif"
    _write_dsm(source)
    job = native_job(source)
    source.write_bytes(b"changed-source")
    with pytest.raises(NativeWindowError, match="source size differs") as error:
        prepare_native_candidate(
            job=job,
            source_path=source,
            output_parent=tmp_path,
            prepared_at=NOW,
            is_current=lambda: True,
        )
    assert error.value.reason == "SOURCE_BYTES_MISMATCH"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.tif"]


def test_pinned_launcher_refuses_missing_proof_without_starting_raster(tmp_path: Path) -> None:
    from ksi_processing_controller.spatial_data_sandbox import PinnedSpatialDataLauncher
    from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError
    from ksi_processing_controller.spatial_data_worker_config import SpatialDataSandboxSettingsV1
    from spatial_data_fixture import DIGEST

    launcher = PinnedSpatialDataLauncher(
        SpatialDataSandboxSettingsV1(
            launcher_path=str(tmp_path / "absent"),
            launcher_sha256=DIGEST,
            containment_proof_path=str(tmp_path / "absent-proof"),
            containment_proof_sha256=DIGEST,
        ),
        clock=lambda: NOW,
    )
    with pytest.raises(SpatialDataWorkerError, match="ACTIVATION_UNAVAILABLE"):
        launcher.launch(workspace=tmp_path, job=make_job())


def test_child_resource_limits_are_applied_to_actual_process_not_only_declared(
    tmp_path: Path,
) -> None:
    """Removing setrlimit must leave the real child unbounded and fail this test."""
    script = """
import json, resource, sys
sys.path[:0] = json.loads(sys.argv[1])
from ksi_processing_controller.spatial_data_sandbox import apply_spatial_data_rlimits
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
apply_spatial_data_rlimits(
    ResourceEnvelopeV1.model_validate(json.loads(sys.argv[2])), max_output_bytes=4096)
limits = (resource.RLIMIT_AS, resource.RLIMIT_CPU, resource.RLIMIT_FSIZE,
          resource.RLIMIT_NOFILE, resource.RLIMIT_NPROC, resource.RLIMIT_CORE)
print(json.dumps([resource.getrlimit(k) for k in limits]))
"""
    envelope = _envelope(max_memory_bytes=1073741824)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            json.dumps(sys.path),
            envelope.model_dump_json(by_alias=True),
        ],
        capture_output=True,
        timeout=5,
        check=True,
        env={},
    )
    assert json.loads(result.stdout) == [
        [1073741824, 1073741824],
        [10, 10],
        [1000000, 1000000],
        [64, 64],
        [1, 1],
        [0, 0],
    ]


def test_kernel_checker_refuses_parent_namespace_even_if_owner_proof_claims_it(
    tmp_path: Path,
) -> None:
    import os

    from ksi_processing_controller.spatial_data_sandbox import (
        SpatialDataContainmentProofV1,
        verify_process_containment,
    )
    from spatial_data_fixture import DIGEST

    job = make_job()
    assert job.runtime.runtime_digest is not None and job.policy.policy_digest is not None
    proof = SpatialDataContainmentProofV1(
        version="spatial-data-containment-proof.v1",
        runtime_digest=job.runtime.runtime_digest,
        policy_digest=job.policy.policy_digest,
        launcher_sha256=DIGEST,
        resource_envelope=job.policy.resource_envelope,
        max_output_bytes=job.policy.max_output_bytes,
        network_namespace_inode=os.stat("/proc/self/ns/net").st_ino,
        mount_namespace_inode=os.stat("/proc/self/ns/mnt").st_ino,
        user_namespace_inode=os.stat("/proc/self/ns/user").st_ino,
        mountinfo_sha256=DIGEST,
        child_uid=os.geteuid(),
        child_gid=os.getegid(),
        valid_until=NOW + timedelta(hours=1),
    )
    assert (
        verify_process_containment(
            pid=os.getpid(), job=job, proof=proof, now=NOW, authority_pid=os.getpid()
        )
        is False
    )


def test_sandbox_late_launch_keeps_capacity_until_child_is_actually_reaped(tmp_path: Path) -> None:
    import threading

    from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox
    from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError

    entered, release, reaped = threading.Event(), threading.Event(), threading.Event()

    class Delayed(SyntheticLauncher):
        calls = 0

        def launch(self, **kwargs: Any) -> Any:
            self.calls += 1
            entered.set()
            assert release.wait(2)
            return super().launch(**kwargs)

    class ObservedSandbox(SpatialDataSandbox):
        def _reap(self, process: Any) -> None:
            super()._reap(process)
            reaped.set()

    launcher = Delayed()
    sandbox = ObservedSandbox(
        launcher=launcher,
        clock=lambda: NOW,
        wall_timeout_seconds=0.05,
        heartbeat_interval_millis=10,
    )
    try:
        with pytest.raises(SpatialDataWorkerError, match="DEADLINE_EXCEEDED"):
            sandbox.prepare(
                job=make_job(),
                source_path=tmp_path / "source.tif",
                output_parent=tmp_path,
                is_current=lambda: True,
            )
        assert entered.is_set()
        with pytest.raises(SpatialDataWorkerError, match="CONCURRENCY_LIMIT_EXCEEDED"):
            sandbox.prepare(
                job=make_job(),
                source_path=tmp_path / "source.tif",
                output_parent=tmp_path,
                is_current=lambda: True,
            )
        assert launcher.calls == 1
    finally:
        release.set()
        assert reaped.wait(2)
        assert launcher.process is not None and launcher.process.poll() is not None


def test_sandbox_failed_reap_retains_owned_process_and_blocks_next_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox
    from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError

    launcher = SyntheticLauncher(proof=False)
    sandbox = SpatialDataSandbox(
        launcher=launcher, clock=lambda: NOW, wall_timeout_seconds=0.2, heartbeat_interval_millis=10
    )
    original = sandbox._reap

    def failed(process: Any) -> None:
        raise SpatialDataWorkerError("PRIVATE_WORKSPACE_CLEANUP_FAILED")

    monkeypatch.setattr(sandbox, "_reap", failed)
    try:
        with pytest.raises(SpatialDataWorkerError, match="PRIVATE_WORKSPACE_CLEANUP_FAILED"):
            sandbox.prepare(
                job=make_job(),
                source_path=tmp_path / "source.tif",
                output_parent=tmp_path,
                is_current=lambda: True,
            )
        process = launcher.process
        with pytest.raises(SpatialDataWorkerError, match="PRIVATE_WORKSPACE_CLEANUP_FAILED"):
            sandbox.prepare(
                job=make_job(),
                source_path=tmp_path / "source.tif",
                output_parent=tmp_path,
                is_current=lambda: True,
            )
        assert launcher.process is process
    finally:
        monkeypatch.setattr(sandbox, "_reap", original)
        sandbox.close()
        assert launcher.process is not None and launcher.process.poll() is not None
