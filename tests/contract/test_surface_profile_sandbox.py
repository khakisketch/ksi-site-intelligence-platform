"""Finite surface-profile child protocol tests, not an OS containment proof."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, tzinfo
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.surface_profile import SurfaceProfileResultV1
from ksi_event_contracts.surface_profile_job import SurfaceProfileFrozenJobV1
from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox
from ksi_processing_controller.surface_profile_worker import SurfaceProfileWorkerError
from surface_profile_job_fixture import write_raster
from test_surface_profile_runner import issue, lane, object_server


class ProfileProtocolLauncher:
    """A synthetic protocol peer for exercising the parent reader and reaper."""

    def __init__(
        self,
        response: dict[str, Any],
        *,
        mode: str = "normal",
        launch_delay_seconds: float = 0.0,
    ) -> None:
        self.response = response
        self.mode = mode
        self.launch_delay_seconds = launch_delay_seconds
        self.process: subprocess.Popen[bytes] | None = None
        self.request_path: Path | None = None
        self.launch_count = 0
        self.proof = True

    def launch_surface_profile(
        self, *, workspace: Path, job: SurfaceProfileFrozenJobV1
    ) -> subprocess.Popen[bytes]:
        self.launch_count += 1
        if self.launch_delay_seconds:
            time.sleep(self.launch_delay_seconds)
        self.request_path = workspace / "child-request.json"
        script = r"""
import json, struct, sys, time
mode, response, request_path = sys.argv[1:]
response = json.loads(response)
def emit(raw):
    sys.stdout.buffer.write(struct.pack(">I", len(raw)) + raw)
    sys.stdout.buffer.flush()
emit(json.dumps({"version":"surface-profile-sandbox-ready.v1","pid":__import__("os").getpid(),"ready":True},separators=(",",":")).encode())
prefix = sys.stdin.buffer.read(4)
if len(prefix) != 4: raise SystemExit(2)
size = struct.unpack(">I", prefix)[0]
raw = sys.stdin.buffer.read(size)
if len(raw) != size or sys.stdin.buffer.read(1): raise SystemExit(2)
open(request_path, "wb").write(raw)
if mode == "sleep": time.sleep(30)
if mode == "oversized":
    sys.stdout.buffer.write(struct.pack(">I", response["max_bytes"] + 1))
    sys.stdout.buffer.flush()
    time.sleep(30)
else:
    emit(json.dumps(response,separators=(",",":")).encode())
    if mode == "nonzero-after-response": raise SystemExit(1)
    if mode == "trailing":
        sys.stdout.buffer.write(b"x")
        sys.stdout.buffer.flush()
    if mode == "sleep-after-response": time.sleep(30)
"""
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                self.mode,
                json.dumps(self.response, separators=(",", ":")),
                str(self.request_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env={},
        )
        return self.process

    def verify_containment(
        self, *, process: subprocess.Popen[bytes], job: SurfaceProfileFrozenJobV1
    ) -> bool:
        return self.proof


def _profile_job_and_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, SurfaceProfileFrozenJobV1, Path, SurfaceProfileResultV1]:
    import ksi_processing_controller.spatial_data_sandbox as sandbox_module
    from ksi_event_contracts.surface_profile import SurfaceProfileRefusalV1
    from ksi_geo_spatial.surface_profile import SurfaceProfilePolicy
    from ksi_processing_controller.surface_profile_worker import read_surface_profile

    monkeypatch.setattr(
        sandbox_module,
        "_authority_namespace_inodes",
        lambda: {"net": 101, "mnt": 102, "user": 103},
    )
    raster = write_raster(tmp_path / "profile.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster)
        job_id = issue(graph)
        job = graph.lane.store._records[job_id].job
        workspace = tmp_path / "private-profile"
        workspace.mkdir(mode=0o700)
        source_path = workspace / "source.tif"
        source_path.write_bytes(raster.read_bytes())
        source_path.chmod(0o600)
        outcome = read_surface_profile(
            job.profile_request,
            source_path,
            policy=SurfaceProfilePolicy(
                maximum_vertices=job.policy.maximum_vertices,
                maximum_samples=job.policy.maximum_samples,
                maximum_line_length_m=job.policy.maximum_line_length_m,
                maximum_window_cells=job.policy.maximum_window_cells,
                maximum_source_block_cells=job.policy.maximum_source_block_cells,
            ),
        )
        assert not isinstance(outcome, SurfaceProfileRefusalV1)
        return graph, job, source_path, outcome


def _sandbox(
    launcher: ProfileProtocolLauncher, *, now: datetime, wall: float = 2.0
) -> SpatialDataSandbox:
    return SpatialDataSandbox(
        launcher=launcher,
        clock=lambda: now,
        wall_timeout_seconds=wall,
        heartbeat_interval_millis=20,
    )


def _job_with_result_limit(job: SurfaceProfileFrozenJobV1, limit: int) -> SurfaceProfileFrozenJobV1:
    policy = job.policy.model_copy(
        update={"max_result_bytes": limit, "policy_digest": None}
    ).sealed()
    return job.model_copy(update={"policy": policy, "job_digest": None}).sealed()


def test_surface_profile_child_request_and_result_are_bounded_and_fenced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, job, source, expected = _profile_job_and_result(tmp_path, monkeypatch)
    launcher = ProfileProtocolLauncher(
        {
            "version": "surface-profile-sandbox-result.v1",
            "result": expected.model_dump(mode="json", by_alias=True),
            "reason": None,
        }
    )
    sandbox = _sandbox(launcher, now=graph.now)
    try:
        actual = sandbox.compute_surface_profile(
            job=job, source_path=source, is_current=lambda: True
        )
        sandbox.require_idle()
    finally:
        sandbox.close()
    assert actual == expected
    assert launcher.launch_count == 1
    assert launcher.process is not None and launcher.process.poll() is not None
    assert launcher.request_path is not None
    request = json.loads(launcher.request_path.read_text())
    assert request["version"] == "surface-profile-sandbox-request.v1"
    assert request["job"]["jobDigest"] == job.job_digest
    assert request["authorityNamespaceInodes"].keys() == {"net", "mnt", "user"}
    assert not any("token" in key.lower() or "downloadUrl" in key for key in request)


def test_surface_profile_require_idle_waits_for_delayed_launch_to_reap_late_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError

    graph, job, source, _ = _profile_job_and_result(tmp_path, monkeypatch)
    launcher = ProfileProtocolLauncher({}, launch_delay_seconds=0.25)
    sandbox = _sandbox(launcher, now=graph.now, wall=0.06)
    try:
        with pytest.raises(SurfaceProfileWorkerError, match="DEADLINE_EXCEEDED"):
            sandbox.compute_surface_profile(job=job, source_path=source, is_current=lambda: True)
        with pytest.raises(SpatialDataWorkerError, match="PRIVATE_WORKSPACE_CLEANUP_FAILED"):
            sandbox.require_idle()

        reap_deadline = time.monotonic() + 2
        while True:
            try:
                sandbox.require_idle()
                break
            except SpatialDataWorkerError:
                if time.monotonic() >= reap_deadline:
                    raise
                time.sleep(0.01)
        assert launcher.process is not None and launcher.process.poll() is not None
        assert not sandbox._owned
    finally:
        sandbox.close()


def test_surface_profile_result_limit_counts_canonical_body_not_frame_overhead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, original_job, source, expected = _profile_job_and_result(tmp_path, monkeypatch)
    body_bytes = len(canonical_json_bytes(expected.model_dump(mode="json", by_alias=True)))
    exact_job = _job_with_result_limit(original_job, body_bytes)
    exact_launcher = ProfileProtocolLauncher(
        {
            "version": "surface-profile-sandbox-result.v1",
            "result": expected.model_dump(mode="json", by_alias=True),
            "reason": None,
        }
    )
    exact_sandbox = _sandbox(exact_launcher, now=graph.now)
    try:
        assert (
            exact_sandbox.compute_surface_profile(
                job=exact_job, source_path=source, is_current=lambda: True
            )
            == expected
        )
    finally:
        exact_sandbox.close()

    over_job = _job_with_result_limit(original_job, body_bytes - 1)
    over_launcher = ProfileProtocolLauncher(
        {
            "version": "surface-profile-sandbox-result.v1",
            "result": expected.model_dump(mode="json", by_alias=True),
            "reason": None,
        }
    )
    over_sandbox = _sandbox(over_launcher, now=graph.now)
    try:
        with pytest.raises(SurfaceProfileWorkerError, match="RESOURCE_LIMIT_EXCEEDED"):
            over_sandbox.compute_surface_profile(
                job=over_job, source_path=source, is_current=lambda: True
            )
    finally:
        over_sandbox.close()


def test_surface_profile_child_rejects_unsealed_result_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, job, source, expected = _profile_job_and_result(tmp_path, monkeypatch)
    unsigned = expected.model_copy(update={"result_digest": None})
    launcher = ProfileProtocolLauncher(
        {
            "version": "surface-profile-sandbox-result.v1",
            "result": unsigned.model_dump(mode="json", by_alias=True),
            "reason": None,
        }
    )
    sandbox = _sandbox(launcher, now=graph.now)
    try:
        with pytest.raises(SurfaceProfileWorkerError, match="INTEGRITY_MISMATCH"):
            sandbox.compute_surface_profile(job=job, source_path=source, is_current=lambda: True)
    finally:
        sandbox.close()


def test_surface_profile_child_refusal_keeps_its_typed_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, job, source, _ = _profile_job_and_result(tmp_path, monkeypatch)
    job = _job_with_result_limit(job, 1)
    launcher = ProfileProtocolLauncher(
        {"version": "surface-profile-sandbox-result.v1", "result": None, "reason": "LINE_TOO_LONG"}
    )
    sandbox = _sandbox(launcher, now=graph.now)
    try:
        with pytest.raises(SurfaceProfileWorkerError, match="LINE_TOO_LONG"):
            sandbox.compute_surface_profile(job=job, source_path=source, is_current=lambda: True)
    finally:
        sandbox.close()
    assert launcher.process is not None and launcher.process.poll() is not None
    assert launcher.process.returncode == 0


@pytest.mark.parametrize("limit_mode", ["exact", "one-under", "one-byte", "unsealed", "deadline"])
def test_surface_profile_entrypoint_enforces_canonical_result_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit_mode: str
) -> None:
    import ksi_processing_controller.spatial_data_entrypoint as entrypoint
    import ksi_processing_controller.spatial_data_sandbox as sandbox_module
    from ksi_processing_controller.spatial_data_sandbox import SpatialDataContainmentProofV1

    graph, job, source, expected = _profile_job_and_result(tmp_path, monkeypatch)
    body_bytes = len(canonical_json_bytes(expected.model_dump(mode="json", by_alias=True)))
    result_limit = {
        "exact": body_bytes,
        "one-under": body_bytes - 1,
        "one-byte": 1,
        "unsealed": body_bytes,
        "deadline": body_bytes,
    }[limit_mode]
    job = _job_with_result_limit(job, result_limit)
    if limit_mode == "unsealed":
        import ksi_processing_controller.surface_profile_worker as profile_worker

        monkeypatch.setattr(
            profile_worker,
            "compute_verified_surface_profile",
            lambda *_: expected.model_copy(update={"result_digest": None}),
        )

    class FrozenDateTime:
        calls = 0

        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            cls.calls += 1
            if limit_mode == "deadline" and cls.calls >= 3:
                return job.deadline
            return graph.now

    monkeypatch.setattr(entrypoint, "datetime", FrozenDateTime)
    digest = "sha256:" + "a" * 64
    assert job.runtime.runtime_digest is not None
    assert job.policy.policy_digest is not None
    proof = SpatialDataContainmentProofV1(
        version="spatial-data-containment-proof.v1",
        runtime_digest=job.runtime.runtime_digest,
        policy_digest=job.policy.policy_digest,
        launcher_sha256=digest,
        resource_envelope=job.policy.resource_envelope,
        max_output_bytes=job.policy.max_result_bytes,
        network_namespace_inode=101,
        mount_namespace_inode=102,
        user_namespace_inode=103,
        mountinfo_sha256=digest,
        child_uid=max(1, os.geteuid()),
        child_gid=max(1, os.getegid()),
        valid_until=job.deadline,
    )
    proof_bytes = proof.model_dump_json(by_alias=True).encode("utf-8")
    proof_path = tmp_path / "containment-proof.json"
    proof_path.write_bytes(proof_bytes)
    proof_fd = os.open(proof_path, os.O_RDONLY)
    request = {
        "version": "surface-profile-sandbox-request.v1",
        "job": job.model_dump(mode="json", by_alias=True),
        "containmentProofSha256": "sha256:" + hashlib.sha256(proof_bytes).hexdigest(),
        "authorityNamespaceInodes": {"net": 201, "mnt": 202, "user": 203},
    }
    encoded = json.dumps(request, separators=(",", ":")).encode("utf-8")
    framed = len(encoded).to_bytes(4, "big") + encoded
    output = BytesIO()
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": BytesIO(framed)})())
    monkeypatch.setattr(sys, "stdout", type("Output", (), {"buffer": output})())
    monkeypatch.setattr(sandbox_module, "apply_spatial_data_rlimits", lambda *args, **kwargs: None)
    monkeypatch.setattr(sandbox_module, "verify_process_containment", lambda **kwargs: True)

    assert (
        entrypoint.main(
            [
                "--workspace",
                str(source.parent),
                "--containment-proof-fd",
                str(proof_fd),
                "--operation",
                "surface-profile",
            ]
        )
        == 0
    )
    frames = []
    raw_output = output.getvalue()
    offset = 0
    while offset < len(raw_output):
        size = int.from_bytes(raw_output[offset : offset + 4], "big")
        offset += 4
        frames.append(json.loads(raw_output[offset : offset + size]))
        offset += size
    assert frames[0] == {
        "version": "surface-profile-sandbox-ready.v1",
        "pid": os.getpid(),
        "ready": True,
    }
    if limit_mode == "exact":
        assert frames[1] == {
            "version": "surface-profile-sandbox-result.v1",
            "result": expected.model_dump(mode="json", by_alias=True),
            "reason": None,
        }
    else:
        assert frames[1] == {
            "version": "surface-profile-sandbox-result.v1",
            "result": None,
            "reason": (
                {
                    "unsealed": "INTEGRITY_MISMATCH",
                    "deadline": "DEADLINE_EXCEEDED",
                }.get(limit_mode, "RESOURCE_LIMIT_EXCEEDED")
            ),
        }


def test_surface_profile_child_frame_over_limit_is_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, job, source, _ = _profile_job_and_result(tmp_path, monkeypatch)
    launcher = ProfileProtocolLauncher(
        {"max_bytes": job.policy.max_result_bytes + 256},
        mode="oversized",
    )
    sandbox = _sandbox(launcher, now=graph.now)
    try:
        with pytest.raises(SurfaceProfileWorkerError, match="RESOURCE_LIMIT_EXCEEDED"):
            sandbox.compute_surface_profile(job=job, source_path=source, is_current=lambda: True)
    finally:
        sandbox.close()
    assert launcher.process is not None and launcher.process.poll() is not None


@pytest.mark.parametrize("stop_reason", ["cancel", "deadline"])
def test_surface_profile_child_is_killed_when_currentness_or_wall_limit_ends(
    tmp_path: Path, stop_reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, job, source, _ = _profile_job_and_result(tmp_path, monkeypatch)
    launcher = ProfileProtocolLauncher({}, mode="sleep")
    sandbox = _sandbox(
        launcher,
        now=graph.now,
        wall=0.14 if stop_reason == "deadline" else 2.0,
    )
    started = time.monotonic()

    def current() -> bool:
        return stop_reason != "cancel" or time.monotonic() - started < 0.12

    expected = "CURRENTNESS_UNAVAILABLE" if stop_reason == "cancel" else "DEADLINE_EXCEEDED"
    try:
        with pytest.raises(SurfaceProfileWorkerError, match=expected):
            sandbox.compute_surface_profile(job=job, source_path=source, is_current=current)
    finally:
        sandbox.close()
    assert launcher.process is not None and launcher.process.poll() is not None
    assert not sandbox._owned


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("nonzero-after-response", "WORKER_FAILED"), ("trailing", "INTEGRITY_MISMATCH")],
)
def test_surface_profile_refusal_requires_clean_eof_and_successful_child_exit(
    tmp_path: Path,
    mode: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph, job, source, _ = _profile_job_and_result(tmp_path, monkeypatch)
    job = _job_with_result_limit(job, 1)
    launcher = ProfileProtocolLauncher(
        {"version": "surface-profile-sandbox-result.v1", "result": None, "reason": "LINE_TOO_LONG"},
        mode=mode,
    )
    sandbox = _sandbox(launcher, now=graph.now)
    try:
        with pytest.raises(SurfaceProfileWorkerError, match=expected):
            sandbox.compute_surface_profile(job=job, source_path=source, is_current=lambda: True)
    finally:
        sandbox.close()
    assert launcher.process is not None and launcher.process.poll() is not None


def test_surface_profile_refusal_is_not_trusted_after_currentness_is_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, job, source, _ = _profile_job_and_result(tmp_path, monkeypatch)
    job = _job_with_result_limit(job, 1)
    launcher = ProfileProtocolLauncher(
        {"version": "surface-profile-sandbox-result.v1", "result": None, "reason": "LINE_TOO_LONG"},
        mode="sleep-after-response",
    )
    sandbox = _sandbox(launcher, now=graph.now)
    started = time.monotonic()
    try:
        with pytest.raises(SurfaceProfileWorkerError, match="CURRENTNESS_UNAVAILABLE"):
            sandbox.compute_surface_profile(
                job=job,
                source_path=source,
                is_current=lambda: time.monotonic() - started < 0.12,
            )
    finally:
        sandbox.close()
    assert launcher.process is not None and launcher.process.poll() is not None
