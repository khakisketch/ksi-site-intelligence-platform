"""Local-only conformance tests for the closed rootless Docker adapter."""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest
from ksi_processing_controller.external_inspector_attempts import AttemptBindingV1
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
)
from ksi_processing_controller.external_inspector_docker import (
    CgroupV2CpuStatReader,
    CgroupV2RootConfigV1,
    CgroupV2RootV1,
    DockerApiResponseV1,
    DockerCgroupMeasurementConfigV1,
    DockerCgroupRuntimeMeasurement,
    DockerEngineClientV1,
    DockerExactRuntimeRegistry,
    DockerMultiplexSessionPort,
    DockerRuntimeUnavailable,
    DockerStartedScopeVerifier,
    FileLocalOciPairResolver,
    FileOciPairResolverConfigV1,
    LocalOciImageProofV1,
    RootlessDockerHostProofPort,
    RootlessDockerRuntimeAdapter,
    RootlessDockerSocketConfigV1,
    UnixSocketDockerEngineWire,
    UnixSocketDockerMultiplexSession,
)
from ksi_processing_controller.external_inspector_file_io import FileIoSealReceiptV1
from ksi_processing_controller.external_inspector_launcher import InspectorEffectiveLimitsV1
from ksi_processing_controller.external_inspector_runtime import CpuCounterUnitV1
from ksi_processing_controller.external_inspector_staging import (
    MappedInspectorReaderV1,
    NamedReaderAclPort,
    ReaderMappingPort,
)


def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


@dataclass
class _Wire:
    responses: dict[tuple[str, str], DockerApiResponseV1]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, bytes | None]] = []

    def request(
        self, *, method: str, target: str, body: bytes | None, deadline_monotonic: float
    ) -> DockerApiResponseV1:
        del deadline_monotonic
        self.calls.append((method, target, body))
        try:
            return self.responses[(method, target)]
        except KeyError as exc:
            raise AssertionError(f"unexpected engine request {method} {target}") from exc


def _response(status: int, body: dict[str, Any] | None = None) -> DockerApiResponseV1:
    return DockerApiResponseV1(
        status=status,
        headers={"content-type": "application/json"},
        body=b"" if body is None else json.dumps(body, separators=(",", ":")).encode(),
    )


def test_engine_client_uses_only_the_pinned_exact_lifecycle_endpoints() -> None:
    """No caller-controlled Engine route or broad inventory is available."""
    wire = _Wire(
        {
            ("GET", "/v1.44/_ping"): DockerApiResponseV1(200, {}, b"OK"),
            ("POST", "/v1.44/containers/create?name=external-inspector-a"): _response(
                201, {"Id": "runtime-a"}
            ),
            ("POST", "/v1.44/containers/runtime-a/start"): _response(204),
            ("POST", "/v1.44/containers/runtime-a/kill"): _response(204),
            ("DELETE", "/v1.44/containers/runtime-a?v=1&force=1"): _response(204),
        }
    )
    client = DockerEngineClientV1(wire)

    client.ping(deadline_monotonic=10.0)
    assert (
        client.create_exact(
            name="external-inspector-a", payload={"Image": _digest("a")}, deadline_monotonic=10.0
        )
        == "runtime-a"
    )
    client.start_exact("runtime-a", deadline_monotonic=10.0)
    client.kill_exact("runtime-a", deadline_monotonic=10.0)
    client.remove_exact("runtime-a", deadline_monotonic=10.0)

    assert [(method, target) for method, target, _body in wire.calls] == [
        ("GET", "/v1.44/_ping"),
        ("POST", "/v1.44/containers/create?name=external-inspector-a"),
        ("POST", "/v1.44/containers/runtime-a/start"),
        ("POST", "/v1.44/containers/runtime-a/kill"),
        ("DELETE", "/v1.44/containers/runtime-a?v=1&force=1"),
    ]


def test_concrete_attach_writes_raw_stdin_and_rejects_partial_multiplex_headers() -> None:
    """Docker receives raw stdin; only its stdout/stderr direction is multiplexed."""
    client, engine = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    session = UnixSocketDockerMultiplexSession(client)
    payload = b"\x00\x00\x00\x03abc"
    try:
        session.send_stdin(payload, deadline_monotonic=time.monotonic() + 1.0)
        assert engine.recv(64) == payload
        engine.sendall(b"\x01\x00\x00")
        engine.shutdown(socket.SHUT_WR)
        with pytest.raises(DockerRuntimeUnavailable, match="truncated"):
            session.read_frame(
                maximum_stdout_bytes=16,
                maximum_stderr_bytes=16,
                deadline_monotonic=time.monotonic() + 1.0,
            )
    finally:
        session.close()
        engine.close()


def test_concrete_unix_wire_accepts_fragmented_engine_204_and_chunked_json(tmp_path: Path) -> None:
    """The real AF_UNIX transport parses normal Engine framing, not a fake response object."""
    socket_path = tmp_path / "docker.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(socket_path))
    os.chmod(socket_path, 0o600)
    listener.listen(2)
    received: list[bytes] = []

    def serve() -> None:
        try:
            for response in (
                (b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n",),
                (
                    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n",
                    b'6\r\n{"ok":\r\n',
                    b"5\r\ntrue}\r\n0\r\n\r\n",
                ),
            ):
                connection, _address = listener.accept()
                with connection:
                    received.append(connection.recv(4096))
                    for chunk in response:
                        connection.sendall(chunk)
        finally:
            listener.close()

    thread = threading.Thread(target=serve)
    thread.start()

    class PeerVerifier:
        def verify_connected(self, connection: socket.socket, *, deadline_monotonic: float) -> None:
            assert time.monotonic() < deadline_monotonic
            assert struct.unpack(
                "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            ) == (os.getpid(), os.geteuid(), os.getegid())

    wire = UnixSocketDockerEngineWire(
        RootlessDockerSocketConfigV1(
            socket_path=socket_path,
            expected_owner_uid=os.geteuid(),
            expected_mode=0o600,
            maximum_response_bytes=4096,
        ),
        peer_verifier=PeerVerifier(),
    )
    deadline = time.monotonic() + 1.0
    first = wire.request(
        method="POST",
        target="/v1.44/containers/a/start",
        body=None,
        deadline_monotonic=deadline,
    )
    second = wire.request(
        method="GET", target="/v1.44/info", body=None, deadline_monotonic=deadline
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert first.status == 204 and first.body == b""
    assert second.status == 200 and second.body == b'{"ok":true}'
    assert received[0].startswith(b"POST /v1.44/containers/a/start HTTP/1.1\r\n")
    assert received[1].startswith(b"GET /v1.44/info HTTP/1.1\r\n")


def test_http_parser_accepts_engine_no_body_and_chunked_json_but_rejects_ambiguous_framing() -> (
    None
):
    """The concrete Engine wire accepts legal response framing without widening HTTP."""
    from ksi_processing_controller.external_inspector_docker import _parse_http_response

    assert _parse_http_response(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n").body == b""
    assert (
        _parse_http_response(
            b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n8\r\n{"ok":1}\r\n0\r\n\r\n'
        ).body
        == b'{"ok":1}'
    )
    with pytest.raises(DockerRuntimeUnavailable, match="HTTP"):
        _parse_http_response(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
        )


def test_multiplex_read_honors_one_absolute_deadline_across_slow_partial_header() -> None:
    """Each recv recomputes the caller's deadline instead of resetting a per-read timeout."""
    client, engine = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    session = UnixSocketDockerMultiplexSession(client)

    def drip() -> None:
        try:
            for byte in b"\x01\x00\x00\x00\x00\x00\x00\x01x":
                time.sleep(0.025)
                engine.sendall(bytes((byte,)))
        except OSError:
            pass
        finally:
            engine.close()

    sender = threading.Thread(target=drip)
    sender.start()
    started = time.monotonic()
    try:
        with pytest.raises(DockerRuntimeUnavailable, match="deadline|stream"):
            session.read_frame(
                maximum_stdout_bytes=16,
                maximum_stderr_bytes=16,
                deadline_monotonic=started + 0.06,
            )
        assert time.monotonic() - started < 0.15
    finally:
        session.close()
        sender.join(timeout=2)


def test_backend_stream_reader_reassembles_fragmented_and_coalesced_inner_frames() -> None:
    """Container control bytes are a stream even when Docker chunks split or join them."""
    from ksi_processing_controller.external_inspector_container_protocol import (
        ContainerInnerFrameLimitsV1,
        encode_inner_frame,
    )
    from ksi_processing_controller.external_inspector_docker_backend import _AttachedProtocolReader

    limits = ContainerInnerFrameLimitsV1(maximum_frame_bytes=1024, maximum_stderr_bytes=32)
    first = encode_inner_frame({"frame": "MOUNT_VERIFIED"}, limits=limits)
    second = encode_inner_frame({"frame": "COMPLETED"}, limits=limits)

    class _Session:
        def __init__(self, chunks: list[bytes]) -> None:
            self._chunks = chunks

        def send_stdin(self, payload: bytes, *, deadline_monotonic: float) -> None:
            del payload, deadline_monotonic

        def finish_stdin(self, *, deadline_monotonic: float) -> None:
            del deadline_monotonic

        def read_frame(
            self,
            *,
            maximum_stdout_bytes: int,
            maximum_stderr_bytes: int,
            deadline_monotonic: float,
        ) -> tuple[int, bytes] | None:
            del maximum_stdout_bytes, maximum_stderr_bytes, deadline_monotonic
            return (1, self._chunks.pop(0)) if self._chunks else None

        def close(self) -> None:
            return None

    fragmented = _AttachedProtocolReader(
        cast(DockerMultiplexSessionPort, _Session([first[:2], first[2:]])), limits=limits
    )
    assert fragmented.read_control(deadline_monotonic=1.0) == {"frame": "MOUNT_VERIFIED"}
    coalesced = _AttachedProtocolReader(
        cast(DockerMultiplexSessionPort, _Session([first + second])), limits=limits
    )
    assert coalesced.read_control(deadline_monotonic=1.0) == {"frame": "MOUNT_VERIFIED"}
    assert coalesced.read_control(deadline_monotonic=1.0) == {"frame": "COMPLETED"}


def test_backend_terminal_is_closed_and_checks_sanitize_cap_before_streaming() -> None:
    """Unknown terminal fields and peer-declared oversized output never reach a spool read."""
    from ksi_processing_controller.external_inspector_docker_backend import (
        DockerBackendUnavailable,
        _validate_terminal,
    )
    from test_external_inspector_launcher import _manifest

    manifest = _manifest()
    prepare: dict[str, object] = {
        "attemptNonce": "attempt-1",
        "outerCanonicalInputDigest": _digest("a"),
        "prepareDigest": _digest("b"),
        "operation": "SANITIZE",
    }
    terminal = {
        **prepare,
        "protocolVersion": "inspector-container.v1",
        "frame": "COMPLETED",
        "inspectorBuildDigest": manifest.parser_build_digest,
        "outcome": "SANITIZED",
        "outputSizeBytes": 1_000_001,
        "outputSha256": _digest("c"),
    }
    with pytest.raises(DockerBackendUnavailable, match="SANITIZE"):
        _validate_terminal(
            terminal=terminal,
            prepare=prepare,
            manifest=manifest,
            operation="SANITIZE",
            maximum_output_bytes=1_000_000,
        )
    terminal["outputSizeBytes"] = 1
    terminal["unknown"] = "forbidden"
    with pytest.raises(DockerBackendUnavailable, match="terminal"):
        _validate_terminal(
            terminal=terminal,
            prepare=prepare,
            manifest=manifest,
            operation="SANITIZE",
            maximum_output_bytes=1_000_000,
        )


@pytest.mark.parametrize("trailing_kind", ("coalesced_stdout", "late_stderr"))
def test_sanitize_backend_requires_same_stream_eof_before_spool_seal(trailing_kind: str) -> None:
    """Declared output bytes cannot hide coalesced stdout or later stderr frames."""
    from types import SimpleNamespace

    from ksi_processing_controller.external_inspector_container_protocol import (
        ContainerInnerFrameLimitsV1,
        decode_inner_frame,
        encode_inner_frame,
    )
    from ksi_processing_controller.external_inspector_docker_backend import (
        DockerBackendUnavailable,
        DockerInspectorBackend,
    )
    from ksi_processing_controller.external_inspector_launcher import InspectorBackendCreatedV1
    from ksi_processing_controller.external_inspector_protocol import InspectorOperation
    from test_external_inspector_launcher import _manifest, _policy, _request, _runtime_measurement

    manifest = _manifest()
    request = _request(_policy(manifest), operation=InspectorOperation.SANITIZE)
    frame_limits = ContainerInnerFrameLimitsV1(maximum_frame_bytes=32_768, maximum_stderr_bytes=2)

    class _Session:
        def __init__(self) -> None:
            self.writes: list[bytes] = []
            self.reads = 0

        def send_stdin(self, payload: bytes, *, deadline_monotonic: float) -> None:
            del deadline_monotonic
            self.writes.append(payload)

        def read_frame(self, **kwargs: object) -> tuple[int, bytes] | None:
            del kwargs
            self.reads += 1
            prepare = decode_inner_frame(self.writes[0], limits=frame_limits)
            common = {
                key: prepare[key]
                for key in (
                    "protocolVersion",
                    "attemptNonce",
                    "outerCanonicalInputDigest",
                    "prepareDigest",
                )
            }
            if self.reads == 1:
                return 1, encode_inner_frame(
                    {
                        **common,
                        "frame": "MOUNT_VERIFIED",
                        "artifactId": request.sealed_byte_binding.artifact_id,
                        "actualSizeBytes": request.sealed_byte_binding.observed_size_bytes,
                        "actualSha256": request.sealed_byte_binding.observed_sha256,
                    },
                    limits=frame_limits,
                )
            if self.reads == 2:
                return 1, encode_inner_frame(
                    {
                        **common,
                        "frame": "COMPLETED",
                        "operation": "SANITIZE",
                        "inspectorBuildDigest": manifest.parser_build_digest,
                        "outcome": "SANITIZED",
                        "outputSizeBytes": 1,
                        "outputSha256": "sha256:" + sha256(b"x").hexdigest(),
                    },
                    limits=frame_limits,
                ) + (b"xTRAILING" if trailing_kind == "coalesced_stdout" else b"x")
            if self.reads == 3:
                if trailing_kind == "late_stderr":
                    return 2, b"late-stderr"
                return None
            return None

        def close(self) -> None:
            pass

    class _Runtime:
        def __init__(self) -> None:
            self.session = _Session()

        def attach_exact(self, runtime_id: str, **kwargs: object) -> _Session:
            assert runtime_id == "runtime-a"
            del kwargs
            return self.session

        def start_after_container_bound(self, **kwargs: object) -> None:
            del kwargs

        def wait_exact(self, **kwargs: object) -> dict[str, int]:
            del kwargs
            return {"StatusCode": 0}

    class _Spool:
        def __init__(self) -> None:
            self.finished = False

        def write(self, chunk: bytes) -> None:
            assert chunk == b"x"

        def write_chunk(self, chunk: bytes, **kwargs: object) -> None:
            del kwargs
            self.write(chunk)

        def finish(self) -> None:
            self.finished = True

        def finish_bounded(self, **kwargs: object) -> None:
            del kwargs
            self.finish()

        def retain_for_response(self) -> None:
            raise AssertionError("trailing transport data must prevent response ownership")

    active = SimpleNamespace(
        finalized_measurement=lambda: _runtime_measurement(runtime_id="runtime-a"),
        close=lambda: None,
    )
    runtime = _Runtime()
    spool = _Spool()
    attempt = SimpleNamespace(
        backend_profile_digest=manifest.body.backend_profile_digest,
        security_profile_digest=manifest.body.security_profile_digest,
        inspector_protocol_digest=manifest.body.inspector_protocol_digest,
    )
    backend = DockerInspectorBackend(
        runtime=runtime,  # type: ignore[arg-type]
        started_runtime=SimpleNamespace(verify_exact=lambda **kwargs: None),
        measurements=SimpleNamespace(start=lambda **kwargs: active),
        frame_limits=frame_limits,
        monotonic=lambda: 0.0,
    )

    with pytest.raises(DockerBackendUnavailable, match="trailing|stderr"):
        backend.execute(
            created=InspectorBackendCreatedV1(runtime_id="runtime-a"),
            attempt=attempt,  # type: ignore[arg-type]
            manifest=manifest,
            runtime_parent=object(),  # type: ignore[arg-type]
            output_staging=spool,  # type: ignore[arg-type]
            request=request,
            sealed_input=object(),  # type: ignore[arg-type]
            limits=cast("InspectorEffectiveLimitsV1", SimpleNamespace(max_output_bytes=32)),
            configuration=_configuration(_UnreachableSource()),
            deadline_monotonic=10.0,
            is_cancelled=lambda: False,
            monitor_termination=lambda _reason: 0.0,
        )
    assert spool.finished is False


def test_offline_oci_pair_proof_requires_exact_signed_pair_and_file_digest(
    tmp_path: Path,
) -> None:
    """A local image can never be selected by a tag or an unpinned pair evidence file."""
    proof = tmp_path / "oci-pairs.json"
    contents = json.dumps(
        {
            "version": "external-inspector-oci-pairs.v1",
            "pairs": [
                {
                    "ociManifestDigest": _digest("a"),
                    "ociConfigDigest": _digest("b"),
                    "dockerImageId": _digest("b"),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    proof.write_bytes(contents)
    proof.chmod(0o600)
    resolver = FileLocalOciPairResolver(
        FileOciPairResolverConfigV1(
            proof_path=proof,
            expected_sha256="sha256:" + sha256(contents).hexdigest(),
        )
    )

    resolved = resolver.resolve_exact(manifest_digest=_digest("a"), config_digest=_digest("b"))
    assert resolved.docker_image_id == _digest("b")
    with pytest.raises(DockerRuntimeUnavailable, match="lacks exact"):
        resolver.resolve_exact(manifest_digest=_digest("a"), config_digest=_digest("c"))
    proof.write_bytes(contents + b"\n")
    with pytest.raises(DockerRuntimeUnavailable, match="unavailable"):
        resolver.resolve_exact(manifest_digest=_digest("a"), config_digest=_digest("b"))


def test_cgroup_reader_reads_only_usage_usec_from_a_preopened_v2_directory(tmp_path: Path) -> None:
    """Counter collection is descriptor-relative and rejects a non-v2 or malformed fact."""
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    (cgroup / "cpu.stat").write_text("usage_usec 123\nuser_usec 12\n", encoding="ascii")
    directory_fd = os.open(cgroup, os.O_RDONLY | os.O_DIRECTORY)
    try:
        reader = CgroupV2CpuStatReader(directory_fd, maximum_control_bytes=4096)
        observed = reader.read_aggregate_cpu()
    finally:
        os.close(directory_fd)

    assert observed.value == 123
    assert observed.unit is CpuCounterUnitV1.CPU_USEC
    assert observed.complete_process_tree is True


def test_cgroup_reader_rejects_missing_or_duplicate_usage_usec(tmp_path: Path) -> None:
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    (cgroup / "cpu.stat").write_text("usage_usec 1\nusage_usec 2\n", encoding="ascii")
    directory_fd = os.open(cgroup, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(DockerRuntimeUnavailable, match="cpu.stat"):
            CgroupV2CpuStatReader(directory_fd, maximum_control_bytes=4096).read_aggregate_cpu()
    finally:
        os.close(directory_fd)


def test_cgroup_root_opens_only_a_strict_recorded_descendant_and_reads_back_controls(
    tmp_path: Path,
) -> None:
    """The systemd ControlGroup is never translated into a host path by concatenation."""
    root = tmp_path / "cgroup2"
    attempt = root / "base.slice" / "ksi-inspector-a0123456789abcdef.slice"
    attempt.mkdir(parents=True)
    (attempt / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    (attempt / "cpu.stat").write_text("usage_usec 8\n", encoding="ascii")
    (attempt / "cpu.max").write_text("1000 1000\n", encoding="ascii")
    (attempt / "memory.max").write_text("1000\n", encoding="ascii")
    (attempt / "memory.swap.max").write_text("0\n", encoding="ascii")
    (attempt / "pids.max").write_text("10\n", encoding="ascii")
    (attempt / "cgroup.events").write_text("populated 0\n", encoding="ascii")
    cgroups = CgroupV2RootV1(
        CgroupV2RootConfigV1(
            root=root,
            base_control_group="/base.slice",
            maximum_control_bytes=4096,
        )
    )
    configuration = _configuration(_UnreachableSource())

    slice_reader = cgroups.open_attempt_slice(
        control_group="/base.slice/ksi-inspector-a0123456789abcdef.slice",
        expected_slice_name="ksi-inspector-a0123456789abcdef.slice",
    )
    try:
        slice_reader.verify_exact_limits(configuration)
        assert slice_reader.is_unpopulated() is True
        assert slice_reader.read_aggregate_cpu().value == 8
    finally:
        slice_reader.close()
        cgroups.close()

    with pytest.raises(DockerRuntimeUnavailable, match="strict descendant"):
        CgroupV2RootV1(
            CgroupV2RootConfigV1(
                root=root,
                base_control_group="/base.slice",
                maximum_control_bytes=4096,
            )
        ).open_attempt_slice(
            control_group="/outside.slice/ksi-inspector-a0123456789abcdef.slice",
            expected_slice_name="ksi-inspector-a0123456789abcdef.slice",
        )


def test_started_container_must_occupy_the_one_exact_scope_with_read_back_limits(
    tmp_path: Path,
) -> None:
    """EXECUTE needs an exact init-PID and cgroup scope proof after Engine start."""
    root = tmp_path / "cgroup2"
    control_group = "/base.slice/ksi-inspector-a0123456789abcdef.slice"
    attempt = root / control_group.removeprefix("/")
    scope = attempt / "docker-runtime-a.scope"
    scope.mkdir(parents=True)
    for directory in (attempt, scope):
        (directory / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
        (directory / "cpu.stat").write_text("usage_usec 8\n", encoding="ascii")
        (directory / "cgroup.events").write_text("populated 1\n", encoding="ascii")
    (scope / "cpu.max").write_text("1000 1000\n", encoding="ascii")
    (scope / "memory.max").write_text("1000\n", encoding="ascii")
    (scope / "memory.swap.max").write_text("0\n", encoding="ascii")
    (scope / "pids.max").write_text("10\n", encoding="ascii")

    class _Client:
        def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            assert runtime_id == "runtime-a"
            assert deadline_monotonic == 10.0
            return {"State": {"Pid": 123}}

    class _Proc:
        def read_cgroup_path(self, pid: int) -> str:
            assert pid == 123
            return control_group + "/docker-runtime-a.scope"

    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    receipt = RuntimeParentReceiptV1(
        unit_name="ksi-inspector-a0123456789abcdef.slice",
        object_path="/org/freedesktop/systemd1/unit/a",
        description="ksi-external-inspector-attempt.v1:" + _binding().digest,
        slice_name="ksi-inspector.slice",
        control_group=control_group,
        invocation_id="a" * 32,
        device=attempt.stat().st_dev,
        inode=attempt.stat().st_ino,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=8,
        cpu_budget_counter=1_000_000,
    )
    cgroups = CgroupV2RootV1(
        CgroupV2RootConfigV1(
            root=root,
            base_control_group="/base.slice",
            maximum_control_bytes=4096,
        )
    )
    try:
        DockerStartedScopeVerifier(
            client=cast(DockerEngineClientV1, _Client()), cgroups=cgroups, proc_cgroups=_Proc()
        ).verify_exact(
            runtime_id="runtime-a",
            runtime_parent=receipt,
            configuration=_configuration(_UnreachableSource()),
            deadline_monotonic=10.0,
        )
    finally:
        cgroups.close()


def test_cgroup_measurement_uses_the_durable_parent_baseline_before_runtime_cleanup(
    tmp_path: Path,
) -> None:
    """A nonzero aggregate baseline is retained and completion requires an exact final fact."""
    root = tmp_path / "cgroup2"
    control_group = "/base.slice/ksi-inspector-a0123456789abcdef.slice"
    attempt = root / control_group.removeprefix("/")
    attempt.mkdir(parents=True)
    (attempt / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    (attempt / "cpu.stat").write_text("usage_usec 107\n", encoding="ascii")
    (attempt / "cgroup.events").write_text("populated 0\n", encoding="ascii")

    class _Client:
        def __init__(self) -> None:
            self.killed: list[str] = []

        def kill_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
            self.killed.append(runtime_id)
            assert deadline_monotonic == 10.0

    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    receipt = RuntimeParentReceiptV1(
        unit_name="ksi-inspector-a0123456789abcdef.slice",
        object_path="/org/freedesktop/systemd1/unit/a",
        description="ksi-external-inspector-attempt.v1:" + _binding().digest,
        slice_name="ksi-inspector.slice",
        control_group=control_group,
        invocation_id="a" * 32,
        device=attempt.stat().st_dev,
        inode=attempt.stat().st_ino,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=100,
        cpu_budget_counter=1_000_000,
    )
    cgroups = CgroupV2RootV1(
        CgroupV2RootConfigV1(
            root=root,
            base_control_group="/base.slice",
            maximum_control_bytes=4096,
        )
    )
    try:
        measurement = DockerCgroupRuntimeMeasurement(
            client=cast(DockerEngineClientV1, _Client()),
            cgroups=cgroups,
            config=DockerCgroupMeasurementConfigV1(
                monitor_interval_millis=1,
                stable_final_samples=2,
                cleanup_timeout_millis=1_000,
            ),
        )
        active = measurement.start(
            runtime_id="runtime-a",
            attempt=_binding(),
            runtime_parent=receipt,
            configuration=_configuration(_UnreachableSource()),
            deadline_monotonic=10.0,
            is_cancelled=lambda: False,
            monitor_termination=lambda _reason: 0.0,
        )
        final = active.finalized_measurement()
    finally:
        cgroups.close()

    assert final.baseline_counter == 100
    assert final.final_counter == 107
    assert final.consumed_counter == 7
    assert final.threshold_exceeded is False


def test_runtime_registry_recovers_only_the_durable_name_with_exact_recorded_labels() -> None:
    """Cleanup has a fresh bound even after execution expiry and removes only its exact ID."""

    class _Client:
        def __init__(self) -> None:
            self.removed: list[str] = []
            self.calls: list[tuple[str, float]] = []
            self.running = True

        def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            assert runtime_id in {_binding().container_name, "runtime-a"}
            self.calls.append(("inspect", deadline_monotonic))
            return {
                "Id": "runtime-a",
                "Name": "/" + _binding().container_name,
                "Config": {
                    "Labels": {
                        "io.ksi.external-inspector.owner": _binding().owner,
                        "io.ksi.external-inspector.attempt-nonce": _binding().attempt_nonce,
                        "io.ksi.external-inspector.execution-manifest": (
                            _binding().execution_manifest_digest
                        ),
                        "io.ksi.external-inspector.oci-manifest": _binding().oci_manifest_digest,
                        "io.ksi.external-inspector.oci-config": _binding().oci_config_digest,
                        "io.ksi.external-inspector.backend-profile": (
                            _binding().backend_profile_digest
                        ),
                        "io.ksi.external-inspector.security-profile": (
                            _binding().security_profile_digest
                        ),
                        "io.ksi.external-inspector.resource-envelope": (
                            _binding().resource_envelope_digest
                        ),
                        "io.ksi.external-inspector.protocol": _binding().inspector_protocol_digest,
                    }
                },
                "State": {"Running": self.running},
            }

        def kill_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
            assert runtime_id == "runtime-a"
            self.calls.append(("kill", deadline_monotonic))
            self.running = False

        def wait_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            assert runtime_id == "runtime-a"
            self.calls.append(("wait", deadline_monotonic))
            return {"StatusCode": 1}

        def remove_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
            assert runtime_id == "runtime-a"
            assert self.running is False
            self.calls.append(("remove", deadline_monotonic))
            self.removed.append(runtime_id)

    client = _Client()
    registry = DockerExactRuntimeRegistry(
        client=cast(DockerEngineClientV1, client),
        recovery_timeout_millis=1_000,
        monotonic=lambda: 5.0,
    )

    assert registry.resolve_exact(_binding()) == "runtime-a"
    # The execution deadline has expired.  Required cleanup still uses the
    # separately configured bounded cleanup lifetime.
    assert registry.quiesce_exact(
        binding=_binding(), runtime_id="runtime-a", deadline_monotonic=0.0
    )
    assert registry.remove_exact(binding=_binding(), runtime_id="runtime-a", deadline_monotonic=0.0)
    assert client.removed == ["runtime-a"]
    assert client.calls == [
        ("inspect", 6.0),
        ("inspect", 6.0),
        ("kill", 6.0),
        ("wait", 6.0),
        ("inspect", 6.0),
        ("remove", 6.0),
    ]


def test_docker_backend_attaches_then_gates_execute_on_scope_measurement_and_eof() -> None:
    """The concrete backend cannot send EXECUTE before post-start scope and monitor proof."""

    from ksi_event_contracts.external_artifact_validation import (
        ArtifactInspectionOutcomeV1,
        ArtifactOutcome,
    )
    from ksi_processing_controller.external_inspector_attempts import (
        PrivateStagingRootV1,
        RuntimeParentReceiptV1,
        StagingAllocationPlanV1,
    )
    from ksi_processing_controller.external_inspector_container_protocol import (
        ContainerInnerFrameLimitsV1,
        decode_inner_frame,
        encode_inner_frame,
    )
    from ksi_processing_controller.external_inspector_docker_backend import DockerInspectorBackend
    from ksi_processing_controller.external_inspector_launcher import InspectorBackendCreatedV1
    from test_external_inspector_launcher import _manifest, _policy, _request, _runtime_measurement

    manifest = _manifest()
    request = _request(_policy(manifest))
    plan = StagingAllocationPlanV1(
        attempt_nonce=request.attempt_nonce,
        binding_digest=_digest("a"),
        owner=request.fence.worker_instance_id,
        allocation_nonce="allocation-a",
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        staging_name="attempt-a",
        artifact_leaf="artifact",
        provisional_marker_name=".attempt-a.provisional",
        committed_marker_name=".attempt-a.committed",
    )
    attempt = AttemptBindingV1(
        attempt_nonce=request.attempt_nonce,
        canonical_input_digest=request.canonical_input_digest,
        operation="INSPECT",
        owner=request.fence.worker_instance_id,
        container_name="external-inspector-a",
        systemd_slice_name="ksi-inspector-a0123456789abcdef.slice",
        systemd_base_slice="ksi-inspector.slice",
        execution_manifest_digest=manifest.canonical_body_digest(),
        parser_build_digest=manifest.parser_build_digest,
        oci_manifest_digest=manifest.body.image_identity.oci_manifest_digest,
        oci_config_digest=manifest.body.image_identity.oci_config_digest,
        backend_profile_digest=manifest.body.backend_profile_digest,
        security_profile_digest=manifest.body.security_profile_digest,
        resource_envelope_digest=manifest.body.resource_envelope_digest,
        inspector_protocol_digest=manifest.body.inspector_protocol_digest,
        cpu_budget_counter=1_000_000,
        staging=plan,
    )
    parent = RuntimeParentReceiptV1(
        unit_name=attempt.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/a",
        description="ksi-external-inspector-attempt.v1:" + attempt.digest,
        slice_name=attempt.systemd_base_slice,
        control_group="/base.slice/" + attempt.systemd_slice_name,
        invocation_id="a" * 32,
        device=1,
        inode=2,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=5,
        cpu_budget_counter=1_000_000,
    )
    events: list[str] = []
    limits = ContainerInnerFrameLimitsV1(maximum_frame_bytes=32_768, maximum_stderr_bytes=512)

    class _Session:
        def __init__(self) -> None:
            self.writes: list[bytes] = []
            self.reads = 0

        def send_stdin(self, payload: bytes, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0
            self.writes.append(payload)
            events.append("prepare" if len(self.writes) == 1 else "execute")

        def read_frame(self, **kwargs: object) -> tuple[int, bytes] | None:
            del kwargs
            self.reads += 1
            prepare = decode_inner_frame(self.writes[0], limits=limits)
            if self.reads == 1:
                events.append("mount")
                return 1, encode_inner_frame(
                    {
                        "protocolVersion": "inspector-container.v1",
                        "frame": "MOUNT_VERIFIED",
                        "attemptNonce": prepare["attemptNonce"],
                        "outerCanonicalInputDigest": prepare["outerCanonicalInputDigest"],
                        "prepareDigest": prepare["prepareDigest"],
                        "artifactId": request.sealed_byte_binding.artifact_id,
                        "actualSizeBytes": request.sealed_byte_binding.observed_size_bytes,
                        "actualSha256": request.sealed_byte_binding.observed_sha256,
                    },
                    limits=limits,
                )
            if self.reads == 2:
                events.append("terminal")
                return 1, encode_inner_frame(
                    {
                        "protocolVersion": "inspector-container.v1",
                        "frame": "COMPLETED",
                        "attemptNonce": prepare["attemptNonce"],
                        "outerCanonicalInputDigest": prepare["outerCanonicalInputDigest"],
                        "prepareDigest": prepare["prepareDigest"],
                        "operation": "INSPECT",
                        "inspectorBuildDigest": manifest.parser_build_digest,
                        "outcome": ArtifactInspectionOutcomeV1(
                            artifact_id=request.sealed_byte_binding.artifact_id,
                            observed_sha256=request.sealed_byte_binding.observed_sha256,
                            outcome=ArtifactOutcome.REJECTED,
                            reason="SYNTHETIC_REJECTED",
                        ).model_dump(mode="json"),
                        "outputSizeBytes": 0,
                    },
                    limits=limits,
                )
            events.append("eof")
            return None

        def close(self) -> None:
            events.append("close")

    session = _Session()

    class _Runtime:
        def attach_exact(self, runtime_id: str, *, deadline_monotonic: float) -> _Session:
            assert runtime_id == "runtime-a" and deadline_monotonic == 10.0
            events.append("attach")
            return session

        def start_after_container_bound(self, **kwargs: object) -> None:
            assert events == ["attach", "prepare"]
            events.append("start")

        def wait_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, int]:
            assert runtime_id == "runtime-a" and deadline_monotonic == 10.0
            events.append("wait")
            return {"StatusCode": 0}

    class _Scope:
        def verify_exact(self, **kwargs: object) -> None:
            assert events == ["attach", "prepare", "start"]
            events.append("scope")

    class _Active:
        def finalized_measurement(self) -> Any:
            events.append("final")
            return _runtime_measurement(runtime_id="runtime-a")

        def close(self) -> None:
            events.append("measurement-close")

    class _Measurements:
        def start(self, **kwargs: object) -> _Active:
            assert events == ["attach", "prepare", "start", "scope"]
            events.append("measurement")
            return _Active()

    result = DockerInspectorBackend(
        runtime=cast(RootlessDockerRuntimeAdapter, _Runtime()),
        started_runtime=_Scope(),
        measurements=_Measurements(),
        frame_limits=limits,
        monotonic=lambda: 0.0,
    ).execute(
        created=InspectorBackendCreatedV1(runtime_id="runtime-a"),
        attempt=attempt,
        manifest=manifest,
        runtime_parent=parent,
        output_staging=None,
        request=request,
        sealed_input=_UnreachableSource(),  # type: ignore[arg-type]
        limits=object(),  # type: ignore[arg-type]
        configuration=_configuration(_UnreachableSource()),
        deadline_monotonic=10.0,
        is_cancelled=lambda: False,
        monitor_termination=lambda _reason: 0.0,
    )

    assert result.runtime_id == "runtime-a"
    from ksi_processing_controller.external_inspector_protocol import DeadlineBoundedByteReaderPort

    assert isinstance(result.output, DeadlineBoundedByteReaderPort)
    assert events == [
        "attach",
        "prepare",
        "start",
        "scope",
        "measurement",
        "mount",
        "execute",
        "terminal",
        "eof",
        "wait",
        "final",
        "close",
    ]


def test_backend_returns_verified_created_id_when_cancellation_arrives_after_create() -> None:
    """The launcher must journal CONTAINER_BOUND before it turns a late cancel into cleanup."""
    from ksi_processing_controller.external_inspector_container_protocol import (
        ContainerInnerFrameLimitsV1,
    )
    from ksi_processing_controller.external_inspector_docker_backend import DockerInspectorBackend

    class _Runtime:
        def create_exact(self, **kwargs: object) -> str:
            del kwargs
            return "runtime-a"

    cancelled = iter((False, True))
    backend = DockerInspectorBackend(
        runtime=_Runtime(),  # type: ignore[arg-type]
        started_runtime=object(),  # type: ignore[arg-type]
        measurements=object(),  # type: ignore[arg-type]
        frame_limits=ContainerInnerFrameLimitsV1(
            maximum_frame_bytes=32_768,
            maximum_stderr_bytes=512,
        ),
        monotonic=lambda: 0.0,
    )

    created = backend.create(
        attempt=_binding(),
        request=object(),  # type: ignore[arg-type]
        sealed_input=object(),  # type: ignore[arg-type]
        limits=object(),  # type: ignore[arg-type]
        configuration=_configuration(_UnreachableSource()),
        deadline_monotonic=10.0,
        is_cancelled=lambda: next(cancelled),
    )

    assert created.runtime_id == "runtime-a"


def test_runtime_adapter_builds_only_proc_launcher_fd_mounts_and_never_persists_a_fd(
    tmp_path: Path,
) -> None:
    """The one bind source is derived inside consume_fd after host proof, never from a path."""

    payload_bytes = b"abc"
    artifact = tmp_path / "artifact"
    artifact.write_bytes(payload_bytes)
    artifact_fd = os.open(artifact, os.O_RDONLY)

    class _Source:
        def verify_readback(self, *, deadline_monotonic: float) -> FileIoSealReceiptV1:
            del deadline_monotonic
            observed = os.fstat(artifact_fd)
            return FileIoSealReceiptV1(
                device=observed.st_dev,
                inode=observed.st_ino,
                mode=observed.st_mode,
                owner_uid=observed.st_uid,
                owner_gid=observed.st_gid,
                link_count=observed.st_nlink,
                size_bytes=observed.st_size,
                sha256="sha256:" + sha256(payload_bytes).hexdigest(),
            )

        def read_at(self, *, offset: int, maximum_bytes: int, deadline_monotonic: float) -> bytes:
            del offset, maximum_bytes, deadline_monotonic
            return b""

        def consume_fd(self, consumer: Any, *, deadline_monotonic: float) -> object:
            del deadline_monotonic
            return consumer(artifact_fd)

    class _Proof:
        def prove(self, *, configuration: FixedContainerConfigurationV1) -> object:
            del configuration
            return _HostFacts()

    class _HostFacts:
        launcher_pid = os.getpid()

        def verify_slice(self, *, binding: AttemptBindingV1) -> bool:
            return binding.systemd_slice_name == "ksi-inspector-a0123456789abcdef.slice"

        def verify_proc_fd(
            self, *, fd: int, candidate: str, configuration: FixedContainerConfigurationV1
        ) -> bool:
            del configuration
            return fd == artifact_fd and candidate == f"/proc/{os.getpid()}/fd/{artifact_fd}"

    class _Images:
        def resolve_exact(
            self, *, manifest_digest: str, config_digest: str
        ) -> LocalOciImageProofV1:
            return LocalOciImageProofV1(
                manifest_digest=manifest_digest,
                config_digest=config_digest,
                docker_image_id=config_digest,
            )

    configuration = _configuration(_Source(), payload_bytes, source_stat=os.fstat(artifact_fd))
    adapter = RootlessDockerRuntimeAdapter(
        client=DockerEngineClientV1(_Wire({})),
        host_proof=cast(RootlessDockerHostProofPort, _Proof()),
        images=_Images(),
    )

    try:
        payload = adapter.create_payload(
            configuration=configuration, binding=_binding(), deadline_monotonic=10.0
        )
    finally:
        os.close(artifact_fd)

    assert payload["HostConfig"]["Mounts"][0] == {
        "Type": "bind",
        "Source": f"/proc/{os.getpid()}/fd/{artifact_fd}",
        "Target": "/input/artifact.tif",
        "ReadOnly": True,
        "BindOptions": {"NonRecursive": True},
    }
    assert payload["HostConfig"]["Tmpfs"] == {"/work": "rw,nodev,nosuid,noexec,size=2000,mode=0700"}
    assert payload["OpenStdin"] is True
    assert payload["StdinOnce"] is True
    assert payload["AttachStdin"] is True
    assert payload["AttachStdout"] is True
    assert payload["AttachStderr"] is True
    assert payload["HostConfig"]["AutoRemove"] is False
    assert payload["HostConfig"]["GroupAdd"] == []
    assert payload["HostConfig"]["CapAdd"] == []
    assert "/proc/self/fd" not in json.dumps(payload)
    assert "Binds" not in payload["HostConfig"]


def test_runtime_adapter_never_rereads_borrowed_bytes_in_the_parent_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parent process never reads borrowed artifact bytes with ``pread``."""
    import ksi_processing_controller.external_inspector_docker as docker_module
    from ksi_processing_controller.external_inspector_staging import FileSystemInputStaging

    class _Mapping:
        def __init__(self, reader: MappedInspectorReaderV1) -> None:
            self._reader = reader

        def resolve_exact(self, **kwargs: object) -> MappedInspectorReaderV1:
            del kwargs
            return self._reader

    class _Acl:
        def grant_exact(self, **kwargs: object) -> bool:
            del kwargs
            return True

        def verifies_exact(self, **kwargs: object) -> bool:
            del kwargs
            return True

        def revoke_exact(self, **kwargs: object) -> bool:
            del kwargs
            return True

    class _Facts:
        launcher_pid = os.getpid()

        def verify_slice(self, *, binding: AttemptBindingV1) -> bool:
            return binding.systemd_slice_name == "ksi-inspector-a0123456789abcdef.slice"

        def verify_proc_fd(
            self, *, fd: int, candidate: str, configuration: FixedContainerConfigurationV1
        ) -> bool:
            del configuration
            return candidate == f"/proc/{os.getpid()}/fd/{fd}"

    class _Proof:
        def prove(self, *, configuration: FixedContainerConfigurationV1) -> _Facts:
            del configuration
            return _Facts()

    class _Images:
        def resolve_exact(
            self, *, manifest_digest: str, config_digest: str
        ) -> LocalOciImageProofV1:
            return LocalOciImageProofV1(
                manifest_digest=manifest_digest,
                config_digest=config_digest,
                docker_image_id=config_digest,
            )

    payload_bytes = b"actual-retained-bytes"
    reader = MappedInspectorReaderV1(
        container_uid=10_001,
        container_gid=10_001,
        host_uid=os.geteuid(),
        host_gid=os.getegid(),
        mapping_witness="parent-pread-stall-reader",
    )
    staging = FileSystemInputStaging(
        private_root=tmp_path / "private",
        reader_mapping=cast(ReaderMappingPort, _Mapping(reader)),
        acl=cast(NamedReaderAclPort, _Acl()),
    )
    mutable = staging.begin(
        maximum_bytes=len(payload_bytes), deadline_monotonic=time.monotonic() + 1.0
    )
    mutable.write(payload_bytes)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + sha256(payload_bytes).hexdigest(),
        expected_size_bytes=len(payload_bytes),
        reader=reader,
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )
    bind = sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)
    source_path = next((tmp_path / "private").glob("*/artifact"))
    configuration = _configuration(bind.source, payload_bytes, source_stat=source_path.stat())
    adapter = RootlessDockerRuntimeAdapter(
        client=DockerEngineClientV1(_Wire({})),
        host_proof=cast(RootlessDockerHostProofPort, _Proof()),
        images=_Images(),
    )
    parent_pread_calls: list[tuple[int, int]] = []

    def forbidden_parent_pread(descriptor: int, count: int, offset: int) -> bytes:
        del descriptor
        parent_pread_calls.append((count, offset))
        raise AssertionError("parent process must not pread borrowed artifact bytes")

    monkeypatch.setattr(docker_module.os, "pread", forbidden_parent_pread)
    try:
        payload = adapter.create_payload(
            configuration=configuration,
            binding=_binding(),
            deadline_monotonic=time.monotonic() + 5.0,
        )
    finally:
        sealed.abort()

    assert payload["HostConfig"]["Mounts"][0]["Target"] == "/input/artifact.tif"
    assert parent_pread_calls == []


def test_runtime_adapter_rechecks_the_bounded_source_after_engine_create(
    tmp_path: Path,
) -> None:
    """A byte mutation after payload construction cannot survive the create guard."""
    payload_bytes = b"sealed-source"
    artifact = tmp_path / "artifact"
    artifact.write_bytes(payload_bytes)
    artifact_fd = os.open(artifact, os.O_RDWR)

    class _Source:
        def __init__(self) -> None:
            self.readback_deadlines: list[float] = []

        def verify_readback(self, *, deadline_monotonic: float) -> FileIoSealReceiptV1:
            self.readback_deadlines.append(deadline_monotonic)
            observed = os.fstat(artifact_fd)
            return FileIoSealReceiptV1(
                device=observed.st_dev,
                inode=observed.st_ino,
                mode=observed.st_mode,
                owner_uid=observed.st_uid,
                owner_gid=observed.st_gid,
                link_count=observed.st_nlink,
                size_bytes=observed.st_size,
                sha256=("sha256:" + sha256(os.pread(artifact_fd, observed.st_size, 0)).hexdigest()),
            )

        def read_at(self, *, offset: int, maximum_bytes: int, deadline_monotonic: float) -> bytes:
            del deadline_monotonic
            return os.pread(artifact_fd, maximum_bytes, offset)

        def consume_fd(self, consumer: Any, *, deadline_monotonic: float) -> object:
            del deadline_monotonic
            return consumer(artifact_fd)

    class _Facts:
        launcher_pid = os.getpid()

        def verify_slice(self, *, binding: AttemptBindingV1) -> bool:
            return binding.systemd_slice_name == "ksi-inspector-a0123456789abcdef.slice"

        def verify_proc_fd(
            self, *, fd: int, candidate: str, configuration: FixedContainerConfigurationV1
        ) -> bool:
            del configuration
            return fd == artifact_fd and candidate == f"/proc/{os.getpid()}/fd/{fd}"

    class _Proof:
        def prove(self, *, configuration: FixedContainerConfigurationV1) -> _Facts:
            del configuration
            return _Facts()

    class _Images:
        def resolve_exact(
            self, *, manifest_digest: str, config_digest: str
        ) -> LocalOciImageProofV1:
            return LocalOciImageProofV1(
                manifest_digest=manifest_digest,
                config_digest=config_digest,
                docker_image_id=config_digest,
            )

    class _Client:
        def __init__(self) -> None:
            self.create_calls = 0

        def inspect_local_image(
            self, image_id: str, *, deadline_monotonic: float
        ) -> dict[str, object]:
            del deadline_monotonic
            return {
                "Id": image_id,
                "RepoDigests": ["local@" + _digest("a")],
                "Config": {},
            }

        def create_exact(
            self, *, name: str, payload: dict[str, object], deadline_monotonic: float
        ) -> str:
            del name, payload, deadline_monotonic
            self.create_calls += 1
            os.pwrite(artifact_fd, b"changed-source", 0)
            return "runtime-a"

    source = _Source()
    client = _Client()
    configuration = _configuration(source, payload_bytes, source_stat=os.fstat(artifact_fd))
    adapter = RootlessDockerRuntimeAdapter(
        client=cast(DockerEngineClientV1, client),
        host_proof=cast(RootlessDockerHostProofPort, _Proof()),
        images=_Images(),
    )

    try:
        with pytest.raises(DockerRuntimeUnavailable, match="borrowed source identity changed"):
            adapter.create_exact(
                configuration=configuration,
                binding=_binding(),
                deadline_monotonic=10.0,
            )
    finally:
        os.close(artifact_fd)

    assert client.create_calls == 1
    assert source.readback_deadlines == [10.0, 10.0, 10.0]


def test_runtime_adapter_rechecks_the_bounded_source_after_engine_start() -> None:
    """The post-start guard rejects bytes changed after the pre-start receipt."""
    from ksi_processing_controller.external_inspector_docker import _fixed_create_payload

    payload_bytes = b"abc"
    valid = FileIoSealReceiptV1(
        device=1,
        inode=2,
        mode=0o100600,
        owner_uid=0,
        owner_gid=0,
        link_count=1,
        size_bytes=len(payload_bytes),
        sha256="sha256:" + sha256(payload_bytes).hexdigest(),
    )
    changed = FileIoSealReceiptV1(
        device=valid.device,
        inode=valid.inode,
        mode=valid.mode,
        owner_uid=valid.owner_uid,
        owner_gid=valid.owner_gid,
        link_count=valid.link_count,
        size_bytes=valid.size_bytes,
        sha256="sha256:" + "f" * 64,
    )

    class _Source:
        def __init__(self) -> None:
            self.changed = False
            self.readback_deadlines: list[float] = []

        def verify_readback(self, *, deadline_monotonic: float) -> FileIoSealReceiptV1:
            self.readback_deadlines.append(deadline_monotonic)
            return changed if self.changed else valid

        def read_at(self, *, offset: int, maximum_bytes: int, deadline_monotonic: float) -> bytes:
            del offset, maximum_bytes, deadline_monotonic
            return b""

        def consume_fd(self, consumer: Any, *, deadline_monotonic: float) -> object:
            del deadline_monotonic
            return consumer(9)

    class _Facts:
        launcher_pid = os.getpid()

        def verify_slice(self, *, binding: AttemptBindingV1) -> bool:
            return binding.systemd_slice_name == "ksi-inspector-a0123456789abcdef.slice"

        def verify_proc_fd(
            self, *, fd: int, candidate: str, configuration: FixedContainerConfigurationV1
        ) -> bool:
            del configuration
            return fd == 9 and candidate == f"/proc/{os.getpid()}/fd/9"

    class _Proof:
        def prove(self, *, configuration: FixedContainerConfigurationV1) -> _Facts:
            del configuration
            return _Facts()

    class _Images:
        def resolve_exact(
            self, *, manifest_digest: str, config_digest: str
        ) -> LocalOciImageProofV1:
            return LocalOciImageProofV1(
                manifest_digest=manifest_digest,
                config_digest=config_digest,
                docker_image_id=config_digest,
            )

    class _Client:
        def __init__(self, source: _Source, configuration: FixedContainerConfigurationV1) -> None:
            self._source = source
            self._configuration = configuration
            self.start_calls = 0
            self.inspect_calls = 0

        def inspect_local_image(
            self, image_id: str, *, deadline_monotonic: float
        ) -> dict[str, object]:
            del deadline_monotonic
            return {
                "Id": image_id,
                "RepoDigests": ["local@" + _digest("a")],
                "Config": {},
            }

        def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            del deadline_monotonic
            self.inspect_calls += 1
            binding = _binding()
            source = f"/proc/{os.getpid()}/fd/9"
            payload = _fixed_create_payload(
                configuration=self._configuration,
                binding=binding,
                image_id=self._configuration.image_config_digest,
                cgroup_parent=binding.systemd_slice_name,
                source=source,
            )
            return {
                "Id": runtime_id,
                "Name": "/" + binding.container_name,
                "Image": self._configuration.image_config_digest,
                "Config": {
                    key: value
                    for key, value in payload.items()
                    if key
                    in {
                        "Image",
                        "User",
                        "Env",
                        "Tty",
                        "OpenStdin",
                        "StdinOnce",
                        "AttachStdin",
                        "AttachStdout",
                        "AttachStderr",
                        "Labels",
                    }
                },
                "HostConfig": payload["HostConfig"],
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": source,
                        "Destination": "/input/artifact.tif",
                        "RW": False,
                    },
                    {"Type": "tmpfs", "Destination": "/work", "RW": True},
                ],
                "State": {"Running": self.start_calls == 1},
            }

        def start_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
            del runtime_id, deadline_monotonic
            self.start_calls += 1
            self._source.changed = True

    source = _Source()
    configuration = _configuration(source, payload_bytes)
    client = _Client(source, configuration)
    adapter = RootlessDockerRuntimeAdapter(
        client=cast(DockerEngineClientV1, client),
        host_proof=cast(RootlessDockerHostProofPort, _Proof()),
        images=_Images(),
    )

    with pytest.raises(DockerRuntimeUnavailable, match="borrowed source identity changed"):
        adapter.start_after_container_bound(
            runtime_id="runtime-a",
            configuration=configuration,
            binding=_binding(),
            deadline_monotonic=10.0,
        )

    assert client.inspect_calls == 2
    assert client.start_calls == 1
    assert source.readback_deadlines == [10.0, 10.0]


def test_runtime_adapter_rejects_an_unproven_oci_pair_before_constructing_a_create_payload() -> (
    None
):
    class _UnavailableProof:
        def prove(self, *, configuration: FixedContainerConfigurationV1) -> object:
            del configuration
            raise DockerRuntimeUnavailable("host proof unavailable")

    class _Images:
        def resolve_exact(
            self, *, manifest_digest: str, config_digest: str
        ) -> LocalOciImageProofV1:
            return LocalOciImageProofV1(
                manifest_digest=manifest_digest,
                config_digest=config_digest,
                docker_image_id=_digest("f"),
            )

    adapter = RootlessDockerRuntimeAdapter(
        client=DockerEngineClientV1(_Wire({})),
        host_proof=cast(RootlessDockerHostProofPort, _UnavailableProof()),
        images=_Images(),
    )
    with pytest.raises(DockerRuntimeUnavailable, match="host proof"):
        adapter.create_payload(
            configuration=_configuration(_UnreachableSource()),
            binding=_binding(),
            deadline_monotonic=10.0,
        )


def test_created_runtime_inspection_requires_the_exact_stdin_and_hardened_mount_contract() -> None:
    """A Docker-shaped response cannot relax a fixed literal or add a mount."""
    from copy import deepcopy

    from ksi_processing_controller.external_inspector_docker import (
        _fixed_create_payload,
        _verify_created_inspection,
    )

    configuration = _configuration(_UnreachableSource())
    binding = _binding()
    source = "/proc/123/fd/4"
    payload = _fixed_create_payload(
        configuration=configuration,
        binding=binding,
        image_id=configuration.image_config_digest,
        cgroup_parent=binding.systemd_slice_name,
        source=source,
    )
    inspected = {
        "Id": "runtime-a",
        "Name": "/" + binding.container_name,
        "Image": configuration.image_config_digest,
        "Config": {
            key: value
            for key, value in payload.items()
            if key
            in {
                "Image",
                "User",
                "Env",
                "Tty",
                "OpenStdin",
                "StdinOnce",
                "AttachStdin",
                "AttachStdout",
                "AttachStderr",
                "Labels",
            }
        },
        "HostConfig": payload["HostConfig"],
        "Mounts": [
            {
                "Type": "bind",
                "Source": source,
                "Destination": "/input/artifact.tif",
                "RW": False,
            },
            {
                "Type": "tmpfs",
                "Destination": "/work",
                "RW": True,
            },
        ],
    }
    _verify_created_inspection(
        inspected=inspected,
        runtime_id="runtime-a",
        binding=binding,
        configuration=configuration,
        image_id=configuration.image_config_digest,
        source=source,
    )

    changed_stdin = deepcopy(inspected)
    changed_stdin["Config"]["OpenStdin"] = False
    with pytest.raises(DockerRuntimeUnavailable, match="fixed runtime"):
        _verify_created_inspection(
            inspected=changed_stdin,
            runtime_id="runtime-a",
            binding=binding,
            configuration=configuration,
            image_id=configuration.image_config_digest,
            source=source,
        )
    extra_mount = deepcopy(inspected)
    extra_mount["Mounts"].append(
        {"Type": "bind", "Source": "/forbidden", "Destination": "/extra", "RW": False}
    )
    with pytest.raises(DockerRuntimeUnavailable, match="read-only input mount"):
        _verify_created_inspection(
            inspected=extra_mount,
            runtime_id="runtime-a",
            binding=binding,
            configuration=configuration,
            image_id=configuration.image_config_digest,
            source=source,
        )


class _UnreachableSource:
    def verify_readback(self, *, deadline_monotonic: float) -> FileIoSealReceiptV1:
        del deadline_monotonic
        raise AssertionError("host proof must precede source access")

    def read_at(self, *, offset: int, maximum_bytes: int, deadline_monotonic: float) -> bytes:
        del offset, maximum_bytes, deadline_monotonic
        return b""

    def consume_fd(self, consumer: Any, *, deadline_monotonic: float) -> object:
        del deadline_monotonic
        raise AssertionError("host proof must precede source access")


def _configuration(
    source: object, payload: bytes = b"abc", *, source_stat: os.stat_result | None = None
) -> FixedContainerConfigurationV1:
    from ksi_processing_controller.external_inspector_container_protocol import FixedInputMountV1

    return FixedContainerConfigurationV1(
        image_manifest_digest=_digest("a"),
        image_config_digest=_digest("b"),
        runtime_uid=10001,
        runtime_gid=10001,
        supplementary_groups=(),
        runtime_environment=(
            ("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"),
            ("GDAL_DRIVER_PATH", "disable"),
            ("GDAL_PAM_ENABLED", "NO"),
            ("PROJ_NETWORK", "OFF"),
            ("PYTHONDONTWRITEBYTECODE", "1"),
        ),
        allowed_grid_digests=(),
        input_mount=FixedInputMountV1(
            source=source,  # type: ignore[arg-type]
            target_path="/input/artifact.tif",
            read_only=True,
            observed_sha256="sha256:" + sha256(payload).hexdigest(),
            observed_size_bytes=len(payload),
            source_device=1 if source_stat is None else source_stat.st_dev,
            source_inode=2 if source_stat is None else source_stat.st_ino,
            reader_mapping_witness="mapping-v1",
        ),
        memory_bytes=1000,
        tmpfs_bytes=2000,
        swap_bytes=0,
        pids=10,
        cpu_period_micros=1000,
        cpu_quota_micros=1000,
        wall_time_millis=1000,
        log_bytes=1000,
        output_bytes=1000,
        cpu_counter_unit=CpuCounterUnitV1.CPU_USEC,
        cpu_budget_counter=1_000_000,
    )


def _binding() -> AttemptBindingV1:
    from ksi_processing_controller.external_inspector_attempts import (
        PrivateStagingRootV1,
        StagingAllocationPlanV1,
    )

    plan = StagingAllocationPlanV1(
        attempt_nonce="attempt-1",
        binding_digest=_digest("d"),
        owner="worker-1",
        allocation_nonce="allocation-1",
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        staging_name="attempt-a",
        artifact_leaf="artifact",
        provisional_marker_name=".attempt-a.provisional",
        committed_marker_name=".attempt-a.committed",
    )
    return AttemptBindingV1(
        attempt_nonce="attempt-1",
        canonical_input_digest=_digest("e"),
        operation="INSPECT",
        owner="worker-1",
        container_name="external-inspector-a",
        systemd_slice_name="ksi-inspector-a0123456789abcdef.slice",
        systemd_base_slice="ksi-inspector.slice",
        execution_manifest_digest=_digest("f"),
        parser_build_digest=_digest("1"),
        oci_manifest_digest=_digest("a"),
        oci_config_digest=_digest("b"),
        backend_profile_digest=_digest("2"),
        security_profile_digest=_digest("3"),
        resource_envelope_digest=_digest("4"),
        inspector_protocol_digest=_digest("5"),
        cpu_budget_counter=1_000_000,
        staging=plan,
    )


def test_engine_client_opens_only_the_pinned_hijacked_attach_route() -> None:
    """Attach is a closed endpoint with explicit stdin/stdout/stderr flags."""

    class _Session:
        def send_stdin(self, **kwargs: object) -> None:
            del kwargs

        def read_frame(self, **kwargs: object) -> None:
            del kwargs
            return None

        def close(self) -> None:
            pass

    class _AttachWire(_Wire):
        def __post_init__(self) -> None:
            super().__post_init__()
            self.attached: list[str] = []

        def attach(self, *, target: str, deadline_monotonic: float) -> _Session:
            del deadline_monotonic
            self.attached.append(target)
            return _Session()

    wire = _AttachWire({})
    session = DockerEngineClientV1(wire).attach_exact("runtime-a", deadline_monotonic=10.0)

    assert session is not None
    assert wire.attached == [
        "/v1.44/containers/runtime-a/attach?stream=1&stdin=1&stdout=1&stderr=1"
    ]


@pytest.mark.parametrize(
    ("reason", "deadline", "cancelled", "exceeded"),
    [
        ("CPU_LIMIT_EXCEEDED", float("inf"), False, True),
        ("DEADLINE_EXCEEDED", 0.0, False, False),
        ("CANCELLED", float("inf"), True, False),
    ],
)
def test_actual_cgroup_monitor_routes_every_termination_reason_to_launcher_callback(
    reason: str, deadline: float, cancelled: bool, exceeded: bool
) -> None:
    """The monitor has no Engine kill path; all CPU, wall, and cancel effects use one callback."""
    from types import SimpleNamespace

    from ksi_processing_controller.external_inspector_docker import DockerActiveCgroupMeasurement

    class _Stop:
        def __init__(self) -> None:
            self.calls = 0

        def wait(self, delay: float) -> bool:
            assert delay > 0.0
            self.calls += 1
            return self.calls > 1

    calls: list[str] = []
    monitor = cast(Any, object.__new__(DockerActiveCgroupMeasurement))
    monitor._stop = _Stop()
    monitor._interval_seconds = 0.001
    monitor._deadline_monotonic = deadline
    monitor._is_cancelled = lambda: cancelled

    def monitor_termination(observed: str) -> float:
        calls.append(observed)
        return 0.01

    monitor._monitor_termination = monitor_termination
    monitor._runtime_id = "runtime-a"
    monitor._kill_latency_seconds = None
    monitor._exceeded = False
    monitor._failed = None
    monitor._accounting = SimpleNamespace(
        monitor=lambda _counter: SimpleNamespace(exceeded=exceeded)
    )
    monitor._parent = SimpleNamespace(read_aggregate_cpu=lambda: object())

    monitor._monitor()

    assert calls == [reason]
    assert monitor._failed is not None
    assert monitor._kill_latency_seconds == 0.01


def test_exact_registry_does_not_wait_on_a_known_created_unstarted_container() -> None:
    """A created container has no process to kill or wait for, but it remains exact-removable."""

    class _Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            assert runtime_id == "runtime-a"
            assert deadline_monotonic == 6.0
            binding = _binding()
            return {
                "Id": "runtime-a",
                "Name": "/external-inspector-a",
                "Config": {
                    "Labels": {
                        "io.ksi.external-inspector.owner": binding.owner,
                        "io.ksi.external-inspector.attempt-nonce": binding.attempt_nonce,
                        "io.ksi.external-inspector.execution-manifest": (
                            binding.execution_manifest_digest
                        ),
                        "io.ksi.external-inspector.oci-manifest": binding.oci_manifest_digest,
                        "io.ksi.external-inspector.oci-config": binding.oci_config_digest,
                        "io.ksi.external-inspector.backend-profile": binding.backend_profile_digest,
                        "io.ksi.external-inspector.security-profile": (
                            binding.security_profile_digest
                        ),
                        "io.ksi.external-inspector.resource-envelope": (
                            binding.resource_envelope_digest
                        ),
                        "io.ksi.external-inspector.protocol": binding.inspector_protocol_digest,
                    }
                },
                "State": {"Running": False, "Status": "created", "Pid": 0},
            }

        def kill_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
            del runtime_id, deadline_monotonic
            raise AssertionError("unstarted runtime has no kill effect")

        def wait_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            del runtime_id, deadline_monotonic
            raise AssertionError("unstarted runtime has no process to wait for")

    registry = DockerExactRuntimeRegistry(
        client=cast(DockerEngineClientV1, _Client()),
        recovery_timeout_millis=1_000,
        monotonic=lambda: 5.0,
    )

    assert registry.quiesce_exact(
        binding=_binding(), runtime_id="runtime-a", deadline_monotonic=0.0
    )


@pytest.mark.parametrize("operation", ["request", "attach"])
def test_actual_wire_checks_connected_peer_before_any_request_bytes(
    tmp_path: Path,
    operation: str,
) -> None:
    path = tmp_path / "docker.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(1)
        path.chmod(0o600)

        class RejectPeer:
            def verify_connected(
                self, connection: socket.socket, *, deadline_monotonic: float
            ) -> None:
                assert connection.getpeername() == str(path)
                raise DockerRuntimeUnavailable("peer rejected")

        wire = UnixSocketDockerEngineWire(
            RootlessDockerSocketConfigV1(path, os.geteuid(), 0o600, 4096),
            peer_verifier=RejectPeer(),
        )
        with pytest.raises(DockerRuntimeUnavailable, match="peer rejected"):
            if operation == "attach":
                wire.attach(
                    target="/v1.44/containers/test/attach", deadline_monotonic=time.monotonic() + 1
                )
            else:
                wire.request(
                    method="GET",
                    target="/v1.44/info",
                    body=None,
                    deadline_monotonic=time.monotonic() + 1,
                )
        listener.settimeout(0.1)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(0.1)
            assert connection.recv(1) == b""
