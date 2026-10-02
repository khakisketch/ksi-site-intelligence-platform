"""Fixed finite child protocol. A timeout is not a containment proof.

The production launcher requires owner-pinned external namespace/mount proof and
rechecks actual kernel process state before sending a job. Nothing is provisioned.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import select
import signal
import stat
import struct
import subprocess
import threading
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any, Literal, Protocol

from ksi_event_contracts._spatial_data import Digest, PositiveInt, SpatialDataModel, UtcTimestamp
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.spatial_data import SpatialDataFrozenJobV1, SpatialDataReceiptV1
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1, SpatialDataRuntimeV1
from pydantic import Field

from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError
from ksi_processing_controller.spatial_data_worker_config import (
    SpatialDataSandboxSettingsV1,
    SpatialDataWorkerConfigError,
    parse_strict_json,
    read_owner_private_file,
)


class SpatialDataContainmentProofV1(SpatialDataModel):
    version: Literal["spatial-data-containment-proof.v1"]
    runtime_digest: Digest
    policy_digest: Digest
    launcher_sha256: Digest
    resource_envelope: ResourceEnvelopeV1
    max_output_bytes: PositiveInt
    network_namespace_inode: PositiveInt
    mount_namespace_inode: PositiveInt
    user_namespace_inode: PositiveInt
    mountinfo_sha256: Digest
    child_uid: int = Field(strict=True, ge=1)
    child_gid: int = Field(strict=True, ge=1)
    valid_until: UtcTimestamp


def _kernel_file(path: str, maximum: int) -> bytes:
    with open(path, "rb", buffering=0) as source:
        result = source.read(maximum + 1)
    if len(result) > maximum:
        raise ValueError("kernel observation over budget")
    return result


def verify_process_containment(
    *,
    pid: int,
    job: SpatialDataFrozenJobV1,
    proof: SpatialDataContainmentProofV1,
    now: datetime,
    authority_pid: int,
) -> bool:
    """Observed namespaces + pinned mount inventory + privilege/rlimit facts, fail closed.

    This is a software proof checker. Suitability of the operator's pinned mounts,
    launcher image and host remains an independent deployment acceptance gate.
    """
    try:
        if (
            proof.runtime_digest != job.runtime.runtime_digest
            or proof.policy_digest != job.policy.policy_digest
            or proof.resource_envelope != job.policy.resource_envelope
            or proof.max_output_bytes != job.policy.max_output_bytes
            or now >= proof.valid_until
            or os.getpgid(pid) != pid
        ):
            return False
        for name, expected in (
            ("net", proof.network_namespace_inode),
            ("mnt", proof.mount_namespace_inode),
            ("user", proof.user_namespace_inode),
        ):
            observed = os.stat(f"/proc/{pid}/ns/{name}").st_ino
            if (
                observed != expected
                or observed == os.stat(f"/proc/{authority_pid}/ns/{name}").st_ino
            ):
                return False
        status = dict(
            line.split(":", 1)
            for line in _kernel_file(f"/proc/{pid}/status", 65536).decode("ascii").splitlines()
            if ":" in line
        )
        if (
            status["Uid"].split() != [str(proof.child_uid)] * 4
            or status["Gid"].split() != [str(proof.child_gid)] * 4
            or any(
                int(status[key].strip(), 16) != 0
                for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
            )
            or status["NoNewPrivs"].strip() != "1"
            or status["Seccomp"].strip() != "2"
        ):
            return False
        if (
            "sha256:" + hashlib.sha256(_kernel_file(f"/proc/{pid}/mountinfo", 262144)).hexdigest()
            != proof.mountinfo_sha256
        ):
            return False
        routes = _kernel_file(f"/proc/{pid}/net/route", 65536).decode("ascii").strip().splitlines()
        devices = _kernel_file(f"/proc/{pid}/net/dev", 65536).decode("ascii").splitlines()[2:]
        if len(routes) > 1 or any(line.split(":", 1)[0].strip() != "lo" for line in devices):
            return False
        env = job.policy.resource_envelope
        for limit, maximum in (
            (resource.RLIMIT_AS, env.max_memory_bytes),
            (resource.RLIMIT_CPU, math.ceil(env.max_cpu_seconds)),
            (resource.RLIMIT_FSIZE, max(env.max_input_bytes, job.policy.max_output_bytes)),
            (resource.RLIMIT_NOFILE, 64),
            (resource.RLIMIT_NPROC, 1),
        ):
            soft, hard = resource.prlimit(pid, limit)
            if not 0 < soft <= hard <= maximum:
                return False
        return resource.prlimit(pid, resource.RLIMIT_CORE) == (0, 0)
    except (OSError, ValueError, KeyError, UnicodeError):
        return False


def apply_spatial_data_rlimits(envelope: ResourceEnvelopeV1, *, max_output_bytes: int) -> None:
    """Irreversible child-only restrictions, never applied to Core or worker parent."""
    if (
        envelope.resource_envelope_digest != envelope.canonical_digest()
        or not 0 < max_output_bytes <= envelope.max_output_bytes
    ):
        raise ValueError("explicit sealed finite child limits required")
    for key, bound in (
        (resource.RLIMIT_AS, envelope.max_memory_bytes),
        (resource.RLIMIT_CPU, math.ceil(envelope.max_cpu_seconds)),
        # The native primitive copies the sealed source in the child; its separate
        # candidate/output check remains bounded by the smaller output policy.
        (resource.RLIMIT_FSIZE, max(envelope.max_input_bytes, max_output_bytes)),
        (resource.RLIMIT_NOFILE, 64),
        (resource.RLIMIT_NPROC, 1),
        (resource.RLIMIT_CORE, 0),
    ):
        resource.setrlimit(key, (bound, bound))


class SpatialDataSandboxLauncherPort(Protocol):
    def launch(
        self, *, workspace: Path, job: SpatialDataFrozenJobV1
    ) -> subprocess.Popen[bytes]: ...
    def verify_containment(
        self, *, process: subprocess.Popen[bytes], job: SpatialDataFrozenJobV1
    ) -> bool: ...


class PinnedSpatialDataLauncher:
    def __init__(self, settings: SpatialDataSandboxSettingsV1, *, clock: Callable[[], datetime]):
        self.settings, self.clock = settings, clock
        self._proofs: dict[int, SpatialDataContainmentProofV1] = {}

    def verify_material(
        self, *, policy: SpatialDataPolicyV1, runtime: SpatialDataRuntimeV1
    ) -> SpatialDataContainmentProofV1:
        """Verify explicit artifacts before polling, without creating a child or host state."""
        try:
            raw = read_owner_private_file(
                Path(self.settings.containment_proof_path), maximum_bytes=262144
            )
            if (
                "sha256:" + hashlib.sha256(raw).hexdigest()
                != self.settings.containment_proof_sha256
            ):
                raise ValueError("proof differs")
            proof = SpatialDataContainmentProofV1.model_validate(parse_strict_json(raw))
            if (
                proof.runtime_digest != runtime.runtime_digest
                or proof.policy_digest != policy.policy_digest
                or proof.resource_envelope != policy.resource_envelope
                or proof.max_output_bytes != policy.max_output_bytes
                or proof.launcher_sha256 != self.settings.launcher_sha256
                or self.clock() >= proof.valid_until
            ):
                raise ValueError("proof not current")
            launcher = read_owner_private_file(
                Path(self.settings.launcher_path),
                maximum_bytes=16777216,
                allowed_modes=(0o500, 0o700),
            )
            if "sha256:" + hashlib.sha256(launcher).hexdigest() != self.settings.launcher_sha256:
                raise ValueError("launcher differs")
            return proof
        except (OSError, ValueError, SpatialDataWorkerConfigError) as exc:
            raise SpatialDataWorkerError("ACTIVATION_UNAVAILABLE") from exc

    def launch(self, *, workspace: Path, job: SpatialDataFrozenJobV1) -> subprocess.Popen[bytes]:
        fd = proof_fd = -1
        try:
            proof = self.verify_material(policy=job.policy, runtime=job.runtime)
            # Preserve the exact operator-pinned proof bytes, not a reserialization.
            raw = read_owner_private_file(
                Path(self.settings.containment_proof_path), maximum_bytes=262144
            )
            if (
                "sha256:" + hashlib.sha256(raw).hexdigest()
                != self.settings.containment_proof_sha256
            ):
                raise ValueError("proof changed")
            path = Path(self.settings.launcher_path)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            node = os.fstat(fd)
            if (
                not stat.S_ISREG(node.st_mode)
                or node.st_uid != os.geteuid()
                or node.st_nlink != 1
                or stat.S_IMODE(node.st_mode) not in (0o500, 0o700)
                or not 0 < node.st_size <= 16777216
            ):
                raise ValueError("launcher not pinned private executable")
            hashed = hashlib.sha256()
            while piece := os.read(fd, 65536):
                hashed.update(piece)
            if "sha256:" + hashed.hexdigest() != self.settings.launcher_sha256:
                raise ValueError("launcher differs")
            # Anonymous read-only proof descriptor: the child gets no token, config,
            # credentials or default environment. The exact launcher must exec the
            # fixed entrypoint, preserving its PID/session and this one proof fd.
            proof_fd = os.memfd_create("ksi-data-proof", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            os.write(proof_fd, raw)
            os.lseek(proof_fd, 0, os.SEEK_SET)
            import fcntl

            fcntl.fcntl(
                proof_fd,
                fcntl.F_ADD_SEALS,
                fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL,
            )
            process = subprocess.Popen(
                [
                    f"/proc/self/fd/{fd}",
                    "--workspace",
                    str(workspace),
                    "--containment-proof-fd",
                    str(proof_fd),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=(fd, proof_fd),
                start_new_session=True,
                env={
                    "PATH": "/usr/bin:/bin",
                    "PROJ_NETWORK": "OFF",
                    "GDAL_PAM_ENABLED": "NO",
                    "GDAL_DRIVER_PATH": "disable",
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                },
            )
            self._proofs[process.pid] = proof
            return process
        except (OSError, ValueError, SpatialDataWorkerConfigError) as exc:
            raise SpatialDataWorkerError("ACTIVATION_UNAVAILABLE") from exc
        finally:
            for descriptor in (fd, proof_fd):
                if descriptor >= 0:
                    os.close(descriptor)

    def verify_containment(
        self, *, process: subprocess.Popen[bytes], job: SpatialDataFrozenJobV1
    ) -> bool:
        proof = self._proofs.pop(process.pid, None)
        return proof is not None and verify_process_containment(
            pid=process.pid, job=job, proof=proof, now=self.clock(), authority_pid=os.getpid()
        )


class SpatialDataSandbox:
    def __init__(
        self,
        *,
        launcher: SpatialDataSandboxLauncherPort,
        clock: Callable[[], datetime],
        wall_timeout_seconds: float,
        heartbeat_interval_millis: int,
    ):
        if (
            not math.isfinite(wall_timeout_seconds)
            or wall_timeout_seconds <= 0
            or type(heartbeat_interval_millis) is not int
            or heartbeat_interval_millis <= 0
        ):
            raise ValueError("explicit finite sandbox limits required")
        self.launcher, self.clock, self.wall, self.heartbeat = (
            launcher,
            clock,
            wall_timeout_seconds,
            heartbeat_interval_millis / 1000,
        )
        self._owned: list[subprocess.Popen[bytes]] = []
        self._pending_launch: threading.Event | None = None

    def _reap(self, process: subprocess.Popen[bytes]) -> None:
        try:
            # Ownership is the new session/process group; kill remaining descendants
            # even if the leader already exited. Never signal a foreign process group.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=0.5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            if process in self._owned:
                self._owned.remove(process)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SpatialDataWorkerError("PRIVATE_WORKSPACE_CLEANUP_FAILED") from exc

    def close(self) -> None:
        for owned in tuple(self._owned):
            self._reap(owned)
        if self._pending_launch is not None and not self._pending_launch.is_set():
            raise SpatialDataWorkerError("PRIVATE_WORKSPACE_CLEANUP_FAILED")

    def prepare(
        self,
        *,
        job: SpatialDataFrozenJobV1,
        source_path: Path,
        output_parent: Path,
        is_current: Callable[[], bool],
    ) -> SpatialDataReceiptV1:
        if source_path != output_parent / "source.tif":
            raise SpatialDataWorkerError("INVALID_REQUEST_BOUNDS")
        for owned in tuple(self._owned):
            self._reap(owned)
        if self._pending_launch is not None and not self._pending_launch.is_set():
            raise SpatialDataWorkerError("CONCURRENCY_LIMIT_EXCEEDED")
        deadline = monotonic() + min(
            self.wall,
            job.policy.resource_envelope.max_deadline_seconds,
            max(0, (job.deadline - self.clock()).total_seconds()),
        )
        process: subprocess.Popen[bytes] | None = None
        success = False
        done, abandoned = threading.Event(), threading.Event()
        handoff = threading.Lock()
        result: list[Any] = []

        def guard() -> float:
            if is_current() is not True:
                raise SpatialDataWorkerError("CURRENTNESS_UNAVAILABLE")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise SpatialDataWorkerError("DEADLINE_EXCEEDED")
            return min(remaining, self.heartbeat)

        def launch() -> None:
            try:
                child = self.launcher.launch(workspace=output_parent, job=job)
                with handoff:
                    self._owned.append(child)
                    late = abandoned.is_set()
                    if not late:
                        result.append(child)
                if late:
                    self._reap(child)
            except Exception as exc:
                result.append(exc)
            finally:
                done.set()

        def read_exact(length: int) -> bytes:
            assert process is not None and process.stdout is not None
            payload = bytearray()
            while len(payload) < length:
                ready, _, _ = select.select([process.stdout], [], [], guard())
                if not ready:
                    continue
                chunk = os.read(process.stdout.fileno(), length - len(payload))
                if not chunk:
                    raise SpatialDataWorkerError("RASTER_PREPARATION_FAILED")
                payload.extend(chunk)
            return bytes(payload)

        def read_frame(maximum: int) -> Any:
            length = struct.unpack(">I", read_exact(4))[0]
            if not 0 < length <= maximum:
                raise SpatialDataWorkerError("RESOURCE_LIMIT_EXCEEDED")
            try:
                return parse_strict_json(read_exact(length))
            except (ValueError, RecursionError) as exc:
                raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED") from exc

        try:
            guard()
            self._pending_launch = done
            threading.Thread(target=launch, name="ksi-data-launch", daemon=True).start()
            while not done.wait(guard()):
                pass
            if not result or not isinstance(result[0], subprocess.Popen):
                if result and isinstance(result[0], SpatialDataWorkerError):
                    raise result[0]
                raise SpatialDataWorkerError("RASTER_PREPARATION_FAILED")
            process = result[0]
            ready = read_frame(256)
            if (
                ready
                != {"version": "spatial-data-sandbox-ready.v1", "pid": process.pid, "ready": True}
                or self.launcher.verify_containment(process=process, job=job) is not True
            ):
                raise SpatialDataWorkerError("ACTIVATION_UNAVAILABLE")
            guard()
            request = {
                "version": "spatial-data-sandbox-request.v1",
                "job": job.model_dump(by_alias=True, mode="json"),
                "preparedAt": self.clock().isoformat(),
            }
            if isinstance(self.launcher, PinnedSpatialDataLauncher):
                request["containmentProofSha256"] = self.launcher.settings.containment_proof_sha256
            raw = json.dumps(
                request, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
            if len(raw) > job.policy.max_snapshot_bytes:
                raise SpatialDataWorkerError("RESOURCE_LIMIT_EXCEEDED")
            assert process.stdin is not None
            os.set_blocking(process.stdin.fileno(), False)
            wire = memoryview(struct.pack(">I", len(raw)) + raw)
            while wire:
                _, writable, _ = select.select([], [process.stdin], [], guard())
                if writable:
                    sent = os.write(process.stdin.fileno(), wire)
                    if not sent:
                        raise SpatialDataWorkerError("RASTER_PREPARATION_FAILED")
                    wire = wire[sent:]
            process.stdin.close()
            response = read_frame(job.policy.max_json_bytes)
            if (
                not isinstance(response, dict)
                or set(response) != {"version", "receipt", "reason"}
                or response["version"] != "spatial-data-sandbox-result.v1"
            ):
                raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED")
            if response["reason"] is not None:
                from typing import get_args

                from ksi_event_contracts.spatial_data import SpatialDataReasonV1

                if response["receipt"] is not None or response["reason"] not in get_args(
                    SpatialDataReasonV1
                ):
                    raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED")
                raise SpatialDataWorkerError(response["reason"])
            receipt = SpatialDataReceiptV1.model_validate(response["receipt"])
            assert process.stdout is not None
            while True:
                readable, _, _ = select.select([process.stdout], [], [], guard())
                if readable:
                    if os.read(process.stdout.fileno(), 1):
                        raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED")
                    break
            while process.poll() is None:
                threading.Event().wait(guard())
            if process.returncode != 0:
                raise SpatialDataWorkerError("RASTER_PREPARATION_FAILED")
            guard()
            success = True
            return receipt
        except (OSError, ValueError) as exc:
            if isinstance(exc, SpatialDataWorkerError):
                raise
            raise SpatialDataWorkerError("OUTPUT_VERIFICATION_FAILED") from exc
        finally:
            with handoff:
                abandoned.set()
                if process is None and result and isinstance(result[0], subprocess.Popen):
                    process = result[0]
            if process is not None:
                self._reap(process)
            if not success:
                (output_parent / "candidate.tif").unlink(missing_ok=True)
