"""Closed local rootless-Docker transport and cgroup-v2 primitives.

The module deliberately has no Docker CLI, environment discovery, image pull,
container listing, label search, or configurable Engine route.  A production
assembly must supply a Task 5 host proof and offline OCI-pair resolver before
it may use these concrete I/O implementations.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import socket
import stat
import struct
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import quote

from ksi_processing_controller.external_inspector_attempts import (
    RuntimeParentReceiptV1,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
)
from ksi_processing_controller.external_inspector_operator_artifacts import BoundedOperatorArtifact
from ksi_processing_controller.external_inspector_protocol import ProtocolViolation
from ksi_processing_controller.external_inspector_runtime import (
    AggregateCpuCounterV1,
    CpuAccountingSession,
    CpuCounterUnitV1,
    FixedRuntimeMeasurementV1,
    RuntimeControlDispositionV1,
    RuntimeControlUnavailable,
)
from ksi_processing_controller.external_inspector_staging import (
    InspectorBorrowedSourcePort,
    InspectorStagingUnavailable,
)
from ksi_processing_controller.external_runtime_binding import ExactRuntimeBindingPort

_DOCKER_API_PREFIX = "/v1.44"
_DOCKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,254}\.slice$")
_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,254}\.scope$")
_OCI_IMAGE_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
_OCI_IMAGE_CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
_OCI_LAYER_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.layer.v1.tar",
        "application/vnd.oci.image.layer.v1.tar+gzip",
        "application/vnd.oci.image.layer.v1.tar+zstd",
        "application/vnd.docker.image.rootfs.diff.tar.gzip",
    }
)
_MAXIMUM_OCI_MANIFEST_BYTES = 64 * 1024
_MAXIMUM_OCI_MANIFEST_BASE64_BYTES = 4 * ((_MAXIMUM_OCI_MANIFEST_BYTES + 2) // 3)
_MAXIMUM_OCI_LAYER_COUNT = 128


class DockerRuntimeUnavailable(RuntimeError):
    """A required closed Docker, OCI, cgroup, or proc-FD fact is unavailable."""


class DockerRuntimeMissing(DockerRuntimeUnavailable):
    """Only an exact recorded Engine object was absent; no broad lookup is permitted."""


@dataclass(frozen=True, slots=True)
class DockerApiResponseV1:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if type(self.status) is not int or not 100 <= self.status <= 599:
            raise ValueError("Docker API response status is invalid")
        if not isinstance(self.body, bytes):
            raise ValueError("Docker API response body is invalid")


class DockerEngineWirePort(Protocol):
    """Private wire seam; Engine client exposes no caller-selected endpoint."""

    def request(
        self, *, method: str, target: str, body: bytes | None, deadline_monotonic: float
    ) -> DockerApiResponseV1: ...


class DockerMultiplexSessionPort(Protocol):
    """One attached container's bounded stdin/stdout/stderr stream."""

    def send_stdin(self, payload: bytes, *, deadline_monotonic: float) -> None: ...

    def finish_stdin(self, *, deadline_monotonic: float) -> None: ...

    def read_frame(
        self, *, maximum_stdout_bytes: int, maximum_stderr_bytes: int, deadline_monotonic: float
    ) -> tuple[int, bytes] | None: ...

    def close(self) -> None: ...


class DockerEngineAttachWirePort(Protocol):
    def attach(self, *, target: str, deadline_monotonic: float) -> DockerMultiplexSessionPort: ...


@dataclass(frozen=True, slots=True)
class RootlessDockerSocketConfigV1:
    """Operator-provided socket identity; no environment or Docker default is read."""

    socket_path: Path
    expected_owner_uid: int
    expected_mode: int
    maximum_response_bytes: int

    def __post_init__(self) -> None:
        if not self.socket_path.is_absolute():
            raise ValueError("rootless Docker socket path must be absolute")
        if type(self.expected_owner_uid) is not int or self.expected_owner_uid < 0:
            raise ValueError("rootless Docker socket owner is invalid")
        if (self.expected_mode & 0o777) != 0o600:
            raise ValueError("rootless Docker socket mode must be exactly 0600")
        if type(self.maximum_response_bytes) is not int or self.maximum_response_bytes <= 0:
            raise ValueError("Docker response cap is required")


class DockerConnectedPeerVerifierPort(Protocol):
    def verify_connected(
        self,
        connection: socket.socket,
        *,
        deadline_monotonic: float,
    ) -> None: ...


class UnixSocketDockerEngineWire:
    """Concrete stdlib HTTP/1.1 transport over one trusted AF_UNIX socket."""

    def __init__(
        self,
        config: RootlessDockerSocketConfigV1,
        *,
        peer_verifier: DockerConnectedPeerVerifierPort,
    ) -> None:
        self._config = config
        self._peer_verifier = peer_verifier

    def request(
        self, *, method: str, target: str, body: bytes | None, deadline_monotonic: float
    ) -> DockerApiResponseV1:
        self._verify_socket()
        payload = b"" if body is None else body
        request = (
            f"{method} {target} HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Connection: close\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("ascii") + payload
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            _set_socket_deadline_or_raise(connection, deadline_monotonic)
            connection.connect(os.fspath(self._config.socket_path))
            self._peer_verifier.verify_connected(connection, deadline_monotonic=deadline_monotonic)
            _send_all_socket(connection, request, deadline_monotonic=deadline_monotonic)
            raw = self._read_all(connection, deadline_monotonic=deadline_monotonic)
        except (OSError, TimeoutError) as exc:
            raise DockerRuntimeUnavailable(
                "rootless Docker Engine transport is unavailable"
            ) from exc
        finally:
            connection.close()
        return _parse_http_response(raw)

    def _verify_socket(self) -> None:
        try:
            node = os.lstat(self._config.socket_path)
        except OSError as exc:
            raise DockerRuntimeUnavailable("rootless Docker socket is unavailable") from exc
        if (
            not stat.S_ISSOCK(node.st_mode)
            or node.st_uid != self._config.expected_owner_uid
            or (node.st_mode & 0o777) != self._config.expected_mode
        ):
            raise DockerRuntimeUnavailable("rootless Docker socket identity is invalid")

    def _read_all(self, connection: socket.socket, *, deadline_monotonic: float) -> bytes:
        chunks: list[bytes] = []
        observed = 0
        while True:
            _set_socket_deadline_or_raise(connection, deadline_monotonic)
            chunk = connection.recv(
                min(64 * 1024, self._config.maximum_response_bytes - observed + 1)
            )
            if not chunk:
                return b"".join(chunks)
            observed += len(chunk)
            if observed > self._config.maximum_response_bytes:
                raise DockerRuntimeUnavailable("Docker response exceeds configured cap")
            chunks.append(chunk)

    def attach(self, *, target: str, deadline_monotonic: float) -> DockerMultiplexSessionPort:
        """Open only Docker's hijacked attach endpoint; no arbitrary stream route exists."""
        self._verify_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            _set_socket_deadline_or_raise(connection, deadline_monotonic)
            connection.connect(os.fspath(self._config.socket_path))
            self._peer_verifier.verify_connected(connection, deadline_monotonic=deadline_monotonic)
            request = (
                f"POST {target} HTTP/1.1\r\n"
                "Host: localhost\r\n"
                "Connection: Upgrade\r\n"
                "Upgrade: tcp\r\n"
                "Content-Length: 0\r\n\r\n"
            ).encode("ascii")
            _send_all_socket(connection, request, deadline_monotonic=deadline_monotonic)
            response = _read_http_header(
                connection,
                maximum_bytes=self._config.maximum_response_bytes,
                deadline_monotonic=deadline_monotonic,
            )
            if not response.startswith(b"HTTP/1.1 101 "):
                raise DockerRuntimeUnavailable("Docker attach did not upgrade the exact stream")
            return UnixSocketDockerMultiplexSession(connection)
        except Exception:
            connection.close()
            raise


class UnixSocketDockerMultiplexSession:
    """Docker's eight-byte multiplex framing with explicit per-frame caps."""

    def __init__(self, connection: socket.socket) -> None:
        self._connection: socket.socket | None = connection
        self._stdin_finished = False

    def send_stdin(self, payload: bytes, *, deadline_monotonic: float) -> None:
        if self._stdin_finished:
            raise DockerRuntimeUnavailable("Docker attach stdin is already finished")
        if not isinstance(payload, bytes):
            raise DockerRuntimeUnavailable("Docker attach stdin payload is invalid")
        connection = self._connection_or_raise()
        try:
            # Docker's attach stream multiplexes container stdout/stderr only;
            # client stdin is copied raw into the container input stream.
            _send_all_socket(connection, payload, deadline_monotonic=deadline_monotonic)
        except (OSError, TimeoutError) as exc:
            raise DockerRuntimeUnavailable("Docker attach stdin is unavailable") from exc

    def finish_stdin(self, *, deadline_monotonic: float) -> None:
        """Signal fixed input EOF while retaining the attached stdout/stderr stream."""
        connection = self._connection_or_raise()
        try:
            _set_socket_deadline_or_raise(connection, deadline_monotonic)
            if self._stdin_finished:
                return
            connection.shutdown(socket.SHUT_WR)
            self._stdin_finished = True
        except (OSError, TimeoutError) as exc:
            raise DockerRuntimeUnavailable("Docker attach stdin finish is unavailable") from exc

    def read_frame(
        self, *, maximum_stdout_bytes: int, maximum_stderr_bytes: int, deadline_monotonic: float
    ) -> tuple[int, bytes] | None:
        if maximum_stdout_bytes <= 0 or maximum_stderr_bytes < 0:
            raise DockerRuntimeUnavailable("Docker attach frame bounds are invalid")
        connection = self._connection_or_raise()
        header = _read_exact_socket(connection, 8, deadline_monotonic=deadline_monotonic)
        if header is None:
            return None
        stream = header[0]
        if header[1:4] != b"\x00\x00\x00" or stream not in {1, 2}:
            raise DockerRuntimeUnavailable("Docker attach multiplex frame is malformed")
        length = struct.unpack(">I", header[4:])[0]
        maximum = maximum_stdout_bytes if stream == 1 else maximum_stderr_bytes
        if length > maximum:
            raise DockerRuntimeUnavailable("Docker attach multiplex frame exceeds its cap")
        payload = _read_exact_socket(connection, length, deadline_monotonic=deadline_monotonic)
        if payload is None:
            raise DockerRuntimeUnavailable("Docker attach multiplex frame is truncated")
        return stream, payload

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()

    def _connection_or_raise(self) -> socket.socket:
        if self._connection is None:
            raise DockerRuntimeUnavailable("Docker attach session is closed")
        return self._connection


class DockerEngineClientV1:
    """Pinned Engine API 1.44 with only exact lifecycle operations."""

    def __init__(self, wire: DockerEngineWirePort) -> None:
        self._wire = wire

    def ping(self, *, deadline_monotonic: float) -> None:
        response = self._request("GET", "/_ping", None, deadline_monotonic)
        if response.status != 200 or response.body != b"OK":
            raise DockerRuntimeUnavailable("rootless Docker Engine ping failed")

    def version(self, *, deadline_monotonic: float) -> dict[str, Any]:
        return self._json_exact("GET", "/version", None, deadline_monotonic, expected={200})

    def info(self, *, deadline_monotonic: float) -> dict[str, Any]:
        return self._json_exact("GET", "/info", None, deadline_monotonic, expected={200})

    def inspect_local_image(self, image_id: str, *, deadline_monotonic: float) -> dict[str, Any]:
        _require_identifier(image_id, "Docker image ID")
        return self._json_exact(
            "GET",
            f"/images/{quote(image_id, safe=':')}/json",
            None,
            deadline_monotonic,
            expected={200},
        )

    def create_exact(self, *, name: str, payload: dict[str, Any], deadline_monotonic: float) -> str:
        _require_identifier(name, "Docker container name")
        result = self._json_exact(
            "POST",
            f"/containers/create?name={quote(name, safe='')}",
            _canonical_payload(payload),
            deadline_monotonic,
            expected={201},
        )
        runtime_id = result.get("Id")
        if not isinstance(runtime_id, str):
            raise DockerRuntimeUnavailable("Docker create runtime ID is invalid")
        _require_identifier(runtime_id, "Docker create runtime ID")
        return runtime_id

    def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, Any]:
        _require_identifier(runtime_id, "Docker runtime ID")
        response = self._request(
            "GET",
            f"/containers/{quote(runtime_id, safe='')}/json",
            None,
            deadline_monotonic,
        )
        if response.status == 404:
            raise DockerRuntimeMissing("exact Docker runtime is absent")
        if response.status != 200:
            raise DockerRuntimeUnavailable("Docker Engine endpoint returned an unexpected status")
        return _decode_json_object(response.body)

    def attach_exact(
        self, runtime_id: str, *, deadline_monotonic: float
    ) -> DockerMultiplexSessionPort:
        _require_identifier(runtime_id, "Docker runtime ID")
        attach = getattr(self._wire, "attach", None)
        if not callable(attach):
            raise DockerRuntimeUnavailable("Docker attach transport is unavailable")
        escaped_runtime_id = quote(runtime_id, safe="")
        target = (
            _DOCKER_API_PREFIX
            + f"/containers/{escaped_runtime_id}/attach?stream=1&stdin=1&stdout=1&stderr=1"
        )
        session = attach(
            target=target,
            deadline_monotonic=deadline_monotonic,
        )
        if not all(
            callable(getattr(session, name, None)) for name in ("send_stdin", "read_frame", "close")
        ):
            raise DockerRuntimeUnavailable("Docker attach transport is invalid")
        return cast(DockerMultiplexSessionPort, session)

    def start_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
        self._expect_no_body(
            "POST",
            f"/containers/{quote(_checked_id(runtime_id), safe='')}/start",
            deadline_monotonic,
            {204},
        )

    def wait_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, Any]:
        return self._json_exact(
            "POST",
            f"/containers/{quote(_checked_id(runtime_id), safe='')}/wait",
            None,
            deadline_monotonic,
            expected={200},
        )

    def kill_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
        self._expect_no_body(
            "POST",
            f"/containers/{quote(_checked_id(runtime_id), safe='')}/kill",
            deadline_monotonic,
            {204},
        )

    def remove_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
        self._expect_no_body(
            "DELETE",
            f"/containers/{quote(_checked_id(runtime_id), safe='')}?v=1&force=1",
            deadline_monotonic,
            {204},
        )

    def _expect_no_body(
        self, method: str, route: str, deadline_monotonic: float, expected: set[int]
    ) -> None:
        response = self._request(method, route, None, deadline_monotonic)
        if response.status not in expected or response.body:
            raise DockerRuntimeUnavailable(
                "Docker lifecycle endpoint returned an unexpected response"
            )

    def _json_exact(
        self,
        method: str,
        route: str,
        body: bytes | None,
        deadline_monotonic: float,
        *,
        expected: set[int],
    ) -> dict[str, Any]:
        response = self._request(method, route, body, deadline_monotonic)
        if response.status not in expected:
            raise DockerRuntimeUnavailable("Docker Engine endpoint returned an unexpected status")
        try:
            parsed = json.loads(response.body)
        except (TypeError, ValueError) as exc:
            raise DockerRuntimeUnavailable("Docker Engine response is not JSON") from exc
        if not isinstance(parsed, dict):
            raise DockerRuntimeUnavailable("Docker Engine response is not an object")
        return parsed

    def _request(
        self, method: str, route: str, body: bytes | None, deadline_monotonic: float
    ) -> DockerApiResponseV1:
        return self._wire.request(
            method=method,
            target=_DOCKER_API_PREFIX + route,
            body=body,
            deadline_monotonic=deadline_monotonic,
        )


@dataclass(frozen=True, slots=True)
class LocalOciImageProofV1:
    """Offline proof that the local Engine image ID equals the signed config digest."""

    manifest_digest: str
    config_digest: str
    docker_image_id: str

    def __post_init__(self) -> None:
        for value in (self.manifest_digest, self.config_digest, self.docker_image_id):
            if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
                raise DockerRuntimeUnavailable("offline OCI image proof has an invalid digest")
        if self.docker_image_id != self.config_digest:
            raise DockerRuntimeUnavailable(
                "Docker image ID must equal the proven OCI config digest"
            )


@dataclass(frozen=True, slots=True)
class LocalOciImageProofV2:
    """Offline proof for Engine/containerd installations whose `.Id` is the manifest."""

    manifest_digest: str
    config_digest: str
    oci_manifest_bytes: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest_digest, str)
            or _DIGEST.fullmatch(self.manifest_digest) is None
            or not isinstance(self.config_digest, str)
            or _DIGEST.fullmatch(self.config_digest) is None
            or not isinstance(self.oci_manifest_bytes, bytes)
            or not 0 < len(self.oci_manifest_bytes) <= _MAXIMUM_OCI_MANIFEST_BYTES
        ):
            raise DockerRuntimeUnavailable("offline OCI image proof has an invalid digest")
        if "sha256:" + hashlib.sha256(self.oci_manifest_bytes).hexdigest() != self.manifest_digest:
            raise DockerRuntimeUnavailable("OCI manifest bytes do not match the proven digest")
        _validate_oci_image_manifest_v2(self.oci_manifest_bytes, self.config_digest)

    @property
    def docker_image_id(self) -> str:
        """Docker 29 rootless/containerd reports the OCI manifest digest as `.Id`."""
        return self.manifest_digest


type LocalOciImageProof = LocalOciImageProofV1 | LocalOciImageProofV2


class LocalOciImageResolverPort(Protocol):
    def resolve_exact(
        self, *, manifest_digest: str, config_digest: str
    ) -> LocalOciImageProof: ...


@dataclass(frozen=True, slots=True)
class FileOciPairResolverConfigV1:
    proof_path: Path
    expected_sha256: str
    artifact: BoundedOperatorArtifact = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.proof_path.is_absolute() or _DIGEST.fullmatch(self.expected_sha256) is None:
            raise ValueError("offline OCI pair proof path and digest are required")
        object.__setattr__(
            self, "artifact", BoundedOperatorArtifact(self.proof_path, maximum_bytes=1024 * 1024)
        )


class FileLocalOciPairResolver:
    """Digest-pinned local offline OCI mapping; it cannot select an image by name."""

    def __init__(self, config: FileOciPairResolverConfigV1) -> None:
        self._config = config

    def resolve_exact(self, *, manifest_digest: str, config_digest: str) -> LocalOciImageProof:
        try:
            contents = self._config.artifact.read()
        except (OSError, ValueError) as exc:
            raise DockerRuntimeUnavailable("offline OCI pair proof is unavailable") from exc
        if "sha256:" + hashlib.sha256(contents).hexdigest() != self._config.expected_sha256:
            raise DockerRuntimeUnavailable("offline OCI pair proof digest changed")
        try:
            proofs: Sequence[LocalOciImageProof]
            raw = json.loads(contents)
            if not isinstance(raw, dict):
                raise ValueError
            version = raw.get("version")
            if version == "external-inspector-oci-pairs.v1":
                proofs = self._parse_v1(raw)
            elif version == "external-inspector-oci-pairs.v2":
                proofs = self._parse_v2(contents)
            else:
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DockerRuntimeUnavailable("offline OCI pair proof is malformed") from exc
        matches = [
            proof
            for proof in proofs
            if proof.manifest_digest == manifest_digest and proof.config_digest == config_digest
        ]
        if len(matches) != 1:
            raise DockerRuntimeUnavailable("offline OCI pair proof lacks exact signed image")
        return matches[0]

    @staticmethod
    def _parse_v1(raw: dict[str, Any]) -> list[LocalOciImageProofV1]:
        try:
            pairs = raw["pairs"]
            if not isinstance(pairs, list):
                raise ValueError
            proofs = [
                LocalOciImageProofV1(
                    manifest_digest=item["ociManifestDigest"],
                    config_digest=item["ociConfigDigest"],
                    docker_image_id=item["dockerImageId"],
                )
                for item in pairs
                if isinstance(item, dict)
            ]
            if len(proofs) != len(pairs) or pairs != sorted(
                pairs,
                key=lambda item: (item["ociManifestDigest"], item["ociConfigDigest"]),
            ):
                raise ValueError
            return proofs
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid V1 OCI pair proof") from exc

    @staticmethod
    def _parse_v2(contents: bytes) -> list[LocalOciImageProofV2]:
        raw = _strict_json_object(contents)
        if set(raw) != {"version", "pairs"} or raw["version"] != "external-inspector-oci-pairs.v2":
            raise ValueError("invalid V2 OCI pair proof")
        pairs = raw["pairs"]
        if not isinstance(pairs, list):
            raise ValueError("invalid V2 OCI pairs")
        proofs: list[LocalOciImageProofV2] = []
        for item in pairs:
            if not isinstance(item, dict) or set(item) != {
                "ociManifestDigest",
                "ociConfigDigest",
                "ociManifestBytesBase64",
            }:
                raise ValueError("invalid V2 OCI pair")
            manifest_digest = item["ociManifestDigest"]
            config_digest = item["ociConfigDigest"]
            encoded_manifest = item["ociManifestBytesBase64"]
            if not all(
                isinstance(value, str)
                for value in (manifest_digest, config_digest, encoded_manifest)
            ) or len(encoded_manifest) > _MAXIMUM_OCI_MANIFEST_BASE64_BYTES:
                raise ValueError("invalid V2 OCI pair value")
            try:
                manifest_bytes = base64.b64decode(encoded_manifest.encode("ascii"), validate=True)
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError("invalid V2 OCI manifest encoding") from exc
            proofs.append(
                LocalOciImageProofV2(
                    manifest_digest=manifest_digest,
                    config_digest=config_digest,
                    oci_manifest_bytes=manifest_bytes,
                )
            )
        if not proofs or pairs != sorted(
            pairs, key=lambda item: (item["ociManifestDigest"], item["ociConfigDigest"])
        ):
            raise ValueError("V2 OCI pairs must be ordered and non-empty")
        return proofs


def _strict_json_object(contents: bytes) -> dict[str, Any]:
    """Parse untrusted local V2 proof JSON without duplicate or non-finite values."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        decoded = contents.decode("utf-8")
        parsed = json.loads(
            decoded,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeDecodeError, RecursionError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid strict JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("strict JSON root must be an object")
    return parsed


def _validate_oci_image_manifest_v2(manifest_bytes: bytes, config_digest: str) -> None:
    manifest = _strict_json_object(manifest_bytes)
    if set(manifest) != {"schemaVersion", "mediaType", "config", "layers"}:
        raise DockerRuntimeUnavailable("OCI manifest fields are invalid")
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 2:
        raise DockerRuntimeUnavailable("OCI manifest schema version is invalid")
    if manifest["mediaType"] != _OCI_IMAGE_MANIFEST_MEDIA_TYPE:
        raise DockerRuntimeUnavailable("OCI manifest media type is invalid")
    config = manifest["config"]
    if not isinstance(config, dict) or set(config) != {"mediaType", "digest", "size"}:
        raise DockerRuntimeUnavailable("OCI config descriptor is invalid")
    if (
        config["mediaType"] != _OCI_IMAGE_CONFIG_MEDIA_TYPE
        or config["digest"] != config_digest
        or type(config["size"]) is not int
        or config["size"] <= 0
    ):
        raise DockerRuntimeUnavailable("OCI config descriptor does not match the signed config")
    layers = manifest["layers"]
    if not isinstance(layers, list) or not 1 <= len(layers) <= _MAXIMUM_OCI_LAYER_COUNT:
        raise DockerRuntimeUnavailable("OCI layer descriptors are invalid")
    for layer in layers:
        if not isinstance(layer, dict) or set(layer) != {"mediaType", "digest", "size"}:
            raise DockerRuntimeUnavailable("OCI layer descriptor is invalid")
        if (
            not isinstance(layer["mediaType"], str)
            or layer["mediaType"] not in _OCI_LAYER_MEDIA_TYPES
            or not isinstance(layer["digest"], str)
            or _DIGEST.fullmatch(layer["digest"]) is None
            or type(layer["size"]) is not int
            or layer["size"] <= 0
        ):
            raise DockerRuntimeUnavailable("OCI layer descriptor is invalid")


class RootlessDockerHostFactsPort(Protocol):
    launcher_pid: int

    def verify_slice(self, *, binding: ExactRuntimeBindingPort) -> bool: ...

    def verify_proc_fd(
        self, *, fd: int, candidate: str, configuration: FixedContainerConfigurationV1
    ) -> bool: ...


class RootlessDockerHostProofPort(DockerConnectedPeerVerifierPort, Protocol):
    def prove(
        self, *, configuration: FixedContainerConfigurationV1
    ) -> RootlessDockerHostFactsPort: ...


class CgroupV2CpuStatReader:
    """Read aggregate cgroup-v2 `usage_usec` only through a retained directory FD."""

    def __init__(self, directory_fd: int, *, maximum_control_bytes: int) -> None:
        if type(directory_fd) is not int or directory_fd < 0:
            raise DockerRuntimeUnavailable("cgroup directory descriptor is unavailable")
        if type(maximum_control_bytes) is not int or maximum_control_bytes <= 0:
            raise DockerRuntimeUnavailable("cgroup control read cap is required")
        self._directory_fd = os.dup(directory_fd)
        self._maximum_control_bytes = maximum_control_bytes

    def close(self) -> None:
        descriptor, self._directory_fd = self._directory_fd, -1
        if descriptor >= 0:
            os.close(descriptor)

    def read_aggregate_cpu(self) -> AggregateCpuCounterV1:
        if self._directory_fd < 0:
            raise DockerRuntimeUnavailable("cgroup reader is closed")
        controllers = set(
            _read_at(self._directory_fd, "cgroup.controllers", self._maximum_control_bytes).split()
        )
        if not {"cpu", "memory", "pids"}.issubset(controllers):
            raise DockerRuntimeUnavailable(
                "cgroup-v2 cpu, memory, and pids controllers are required"
            )
        values: dict[str, int] = {}
        for line in _read_at(
            self._directory_fd, "cpu.stat", self._maximum_control_bytes
        ).splitlines():
            parts = line.split()
            if len(parts) != 2:
                raise DockerRuntimeUnavailable("cgroup cpu.stat is malformed")
            key, raw = parts
            if key in values or not raw.isascii() or not raw.isdecimal():
                raise DockerRuntimeUnavailable("cgroup cpu.stat is malformed")
            values[key] = int(raw)
        try:
            usage_usec = values["usage_usec"]
        except KeyError as exc:
            raise DockerRuntimeUnavailable("cgroup cpu.stat lacks usage_usec") from exc
        return AggregateCpuCounterV1(
            value=usage_usec,
            unit=CpuCounterUnitV1.CPU_USEC,
            complete_process_tree=True,
        )


@dataclass(frozen=True, slots=True)
class CgroupV2RootConfigV1:
    """Provisioned cgroup-v2 root and base ControlGroup identity, with no defaults."""

    root: Path
    base_control_group: str
    maximum_control_bytes: int

    def __post_init__(self) -> None:
        if not self.root.is_absolute():
            raise ValueError("cgroup-v2 root must be absolute")
        if (
            not isinstance(self.base_control_group, str)
            or not self.base_control_group.startswith("/")
            or self.base_control_group.endswith("/")
            or "//" in self.base_control_group
            or "/../" in self.base_control_group
            or self.base_control_group in {"/", "/.."}
        ):
            raise ValueError("base ControlGroup must be an absolute strict cgroup name")
        if type(self.maximum_control_bytes) is not int or self.maximum_control_bytes <= 0:
            raise ValueError("cgroup control read cap is required")


class CgroupV2AttemptSlice:
    """One retained, exact attempt-slice descriptor under the configured base."""

    def __init__(self, directory_fd: int, *, maximum_control_bytes: int) -> None:
        self._directory_fd = directory_fd
        self._maximum_control_bytes = maximum_control_bytes
        self._cpu = CgroupV2CpuStatReader(directory_fd, maximum_control_bytes=maximum_control_bytes)

    def close(self) -> None:
        self._cpu.close()
        descriptor, self._directory_fd = self._directory_fd, -1
        if descriptor >= 0:
            os.close(descriptor)

    def read_aggregate_cpu(self) -> AggregateCpuCounterV1:
        return self._cpu.read_aggregate_cpu()

    def identity(self) -> os.stat_result:
        if self._directory_fd < 0:
            raise DockerRuntimeUnavailable("attempt cgroup slice is closed")
        return os.fstat(self._directory_fd)

    def verify_exact_limits(self, configuration: FixedContainerConfigurationV1) -> None:
        if self._directory_fd < 0:
            raise DockerRuntimeUnavailable("attempt cgroup slice is closed")
        expected = {
            "cpu.max": f"{configuration.cpu_quota_micros} {configuration.cpu_period_micros}",
            "memory.max": str(configuration.memory_bytes),
            "memory.swap.max": "0",
            "pids.max": str(configuration.pids),
        }
        for control, value in expected.items():
            observed = _read_at(self._directory_fd, control, self._maximum_control_bytes).strip()
            if observed != value:
                raise DockerRuntimeUnavailable("attempt cgroup controller readback is not exact")
        # cpu.stat also proves the complete aggregate controller exists now.
        self._cpu.read_aggregate_cpu()

    def verify_required_controllers(self) -> None:
        if self._directory_fd < 0:
            raise DockerRuntimeUnavailable("attempt cgroup slice is closed")
        controllers = set(
            _read_at(self._directory_fd, "cgroup.controllers", self._maximum_control_bytes).split()
        )
        if not {"cpu", "memory", "pids"}.issubset(controllers):
            raise DockerRuntimeUnavailable("attempt cgroup controllers are unavailable")
        self._cpu.read_aggregate_cpu()

    def is_unpopulated(self) -> bool:
        values = _single_value_controls(
            _read_at(self._directory_fd, "cgroup.events", self._maximum_control_bytes)
        )
        try:
            populated = values["populated"]
        except KeyError as exc:
            raise DockerRuntimeUnavailable("attempt cgroup populated state is unavailable") from exc
        if populated not in {"0", "1"}:
            raise DockerRuntimeUnavailable("attempt cgroup populated state is invalid")
        return populated == "0"

    def has_no_child_cgroups(self) -> bool:
        if self._directory_fd < 0:
            raise DockerRuntimeUnavailable("attempt cgroup slice is closed")
        try:
            for name in os.listdir(self._directory_fd):
                node = os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False)
                if stat.S_ISDIR(node.st_mode):
                    return False
        except OSError as exc:
            raise DockerRuntimeUnavailable("attempt cgroup child inventory is unavailable") from exc
        return True

    def open_only_scope(self, *, expected_scope_name: str) -> CgroupV2AttemptSlice:
        """Open the only direct cgroup child, never an inferred or broad scope."""
        if self._directory_fd < 0:
            raise DockerRuntimeUnavailable("attempt cgroup slice is closed")
        if _SAFE_SCOPE.fullmatch(expected_scope_name) is None:
            raise DockerRuntimeUnavailable("Docker cgroup scope name is invalid")
        try:
            children = [
                name
                for name in os.listdir(self._directory_fd)
                if stat.S_ISDIR(
                    os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False).st_mode
                )
            ]
        except OSError as exc:
            raise DockerRuntimeUnavailable("attempt cgroup child inventory is unavailable") from exc
        if children != [expected_scope_name]:
            raise DockerRuntimeUnavailable("attempt cgroup does not contain one exact Docker scope")
        try:
            descriptor = os.open(
                expected_scope_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=self._directory_fd,
            )
        except OSError as exc:
            raise DockerRuntimeUnavailable("exact Docker cgroup scope is unavailable") from exc
        return CgroupV2AttemptSlice(descriptor, maximum_control_bytes=self._maximum_control_bytes)


class CgroupV2RootV1:
    """Descriptor-relative cgroup root. It never creates or maps a cgroup itself."""

    def __init__(self, config: CgroupV2RootConfigV1) -> None:
        self._config = config
        try:
            self._root_fd = os.open(config.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise DockerRuntimeUnavailable("provisioned cgroup-v2 root is unavailable") from exc

    def close(self) -> None:
        descriptor, self._root_fd = self._root_fd, -1
        if descriptor >= 0:
            os.close(descriptor)

    def open_attempt_slice(
        self, *, control_group: str, expected_slice_name: str
    ) -> CgroupV2AttemptSlice:
        if self._root_fd < 0:
            raise DockerRuntimeUnavailable("cgroup-v2 root is closed")
        if _SAFE_UNIT.fullmatch(expected_slice_name) is None:
            raise DockerRuntimeUnavailable("attempt systemd slice name is invalid")
        prefix = self._config.base_control_group + "/"
        if (
            not isinstance(control_group, str)
            or not control_group.startswith(prefix)
            or control_group.endswith("/")
            or "//" in control_group
            or "/../" in control_group
            or control_group.split("/")[-1] != expected_slice_name
        ):
            raise DockerRuntimeUnavailable(
                "ControlGroup is not a strict descendant of configured base"
            )
        components = [component for component in control_group.split("/") if component]
        descriptor = os.dup(self._root_fd)
        try:
            for component in components:
                if component in {".", ".."}:
                    raise DockerRuntimeUnavailable("ControlGroup component is invalid")
                next_descriptor = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            return CgroupV2AttemptSlice(
                descriptor, maximum_control_bytes=self._config.maximum_control_bytes
            )
        except OSError as exc:
            os.close(descriptor)
            raise DockerRuntimeUnavailable("recorded systemd ControlGroup is unavailable") from exc
        except Exception:
            os.close(descriptor)
            raise


class ProcCgroupReaderPort(Protocol):
    """Read the one cgroup-v2 path for an exact Engine-reported init PID."""

    def read_cgroup_path(self, pid: int) -> str: ...


class ProcCgroupReader:
    """Closed `/proc/<pid>/cgroup` reader; it accepts only the unified v2 path."""

    def __init__(self, *, maximum_bytes: int) -> None:
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise ValueError("proc cgroup read cap is required")
        self._maximum_bytes = maximum_bytes

    def read_cgroup_path(self, pid: int) -> str:
        if type(pid) is not int or pid <= 0:
            raise DockerRuntimeUnavailable("Docker init PID is unavailable")
        path = f"/proc/{pid}/cgroup"
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as exc:
            raise DockerRuntimeUnavailable("Docker init cgroup is unavailable") from exc
        try:
            node = os.fstat(descriptor)
            if not stat.S_ISREG(node.st_mode):
                raise DockerRuntimeUnavailable("Docker init cgroup node is invalid")
            contents = _read_descriptor(descriptor, self._maximum_bytes)
        finally:
            os.close(descriptor)
        try:
            records = [line.split(":", 2) for line in contents.decode("ascii").splitlines()]
        except UnicodeDecodeError as exc:
            raise DockerRuntimeUnavailable("Docker init cgroup is not ASCII") from exc
        unified = [record for record in records if len(record) == 3 and record[:2] == ["0", ""]]
        if len(unified) != 1 or len(records) != 1:
            raise DockerRuntimeUnavailable("Docker init cgroup hierarchy is not exact")
        value = unified[0][2]
        if (
            not value.startswith("/")
            or value.endswith("/")
            or "//" in value
            or "/../" in value
            or value in {"/", "/.."}
        ):
            raise DockerRuntimeUnavailable("Docker init cgroup path is invalid")
        return value


class DockerStartedRuntimeVerifierPort(Protocol):
    """Required post-start runtime proof before the entrypoint may execute."""

    def verify_exact(
        self,
        *,
        runtime_id: str,
        runtime_parent: RuntimeParentReceiptV1,
        configuration: FixedContainerConfigurationV1,
        deadline_monotonic: float,
    ) -> None: ...


class DockerStartedScopeVerifier:
    """Prove one Docker scope and its admitted limits from retained cgroup FDs."""

    def __init__(
        self,
        *,
        client: DockerEngineClientV1,
        cgroups: CgroupV2RootV1,
        proc_cgroups: ProcCgroupReaderPort,
    ) -> None:
        self._client = client
        self._cgroups = cgroups
        self._proc_cgroups = proc_cgroups

    def verify_exact(
        self,
        *,
        runtime_id: str,
        runtime_parent: RuntimeParentReceiptV1,
        configuration: FixedContainerConfigurationV1,
        deadline_monotonic: float,
    ) -> None:
        _checked_id(runtime_id)
        if runtime_parent.cpu_counter_unit != CpuCounterUnitV1.CPU_USEC.value:
            raise DockerRuntimeUnavailable("runtime parent CPU unit is unavailable")
        parent = self._cgroups.open_attempt_slice(
            control_group=runtime_parent.control_group,
            expected_slice_name=runtime_parent.unit_name,
        )
        try:
            identity = parent.identity()
            if identity.st_dev != runtime_parent.device or identity.st_ino != runtime_parent.inode:
                raise DockerRuntimeUnavailable("runtime parent cgroup identity changed")
            parent.verify_required_controllers()
            scope_name = f"docker-{runtime_id}.scope"
            scope = parent.open_only_scope(expected_scope_name=scope_name)
            try:
                scope.verify_exact_limits(configuration)
            finally:
                scope.close()
        finally:
            parent.close()
        inspected = self._client.inspect_exact(runtime_id, deadline_monotonic=deadline_monotonic)
        state = inspected.get("State")
        if not isinstance(state, dict) or type(state.get("Pid")) is not int:
            raise DockerRuntimeUnavailable("Docker inspect lacks an exact init PID")
        observed_path = self._proc_cgroups.read_cgroup_path(state["Pid"])
        expected_path = runtime_parent.control_group + "/" + f"docker-{runtime_id}.scope"
        if observed_path != expected_path:
            raise DockerRuntimeUnavailable(
                "Docker init PID cgroup differs from the exact attempt scope"
            )


@dataclass(frozen=True, slots=True)
class DockerCgroupMeasurementConfigV1:
    """Operator-selected monitor cadence and final stability sampling; no defaults."""

    monitor_interval_millis: int
    stable_final_samples: int
    cleanup_timeout_millis: int

    def __post_init__(self) -> None:
        if type(self.monitor_interval_millis) is not int or self.monitor_interval_millis <= 0:
            raise ValueError("runtime monitor cadence is required")
        if type(self.stable_final_samples) is not int or self.stable_final_samples < 2:
            raise ValueError("runtime final stability samples are required")
        if type(self.cleanup_timeout_millis) is not int or self.cleanup_timeout_millis <= 0:
            raise ValueError("runtime cleanup deadline is required")


class _DockerExactTerminator:
    """Legacy test seam intentionally unavailable: only the launcher coordinator may terminate."""

    def __init__(self, client: DockerEngineClientV1, *, cleanup_timeout_millis: int) -> None:
        del client, cleanup_timeout_millis

    def terminate_exact(self, runtime_id: str) -> float:
        del runtime_id
        raise DockerRuntimeUnavailable("runtime termination must use launcher cleanup coordination")


class DockerActiveCgroupMeasurement:
    """One retained parent cgroup monitor, stopped and finalized before runtime removal."""

    def __init__(
        self,
        *,
        runtime_id: str,
        parent: CgroupV2AttemptSlice,
        baseline: AggregateCpuCounterV1,
        budget_counter: int,
        monitor_termination: Callable[[str], float],
        monitor_interval_millis: int,
        stable_final_samples: int,
        cleanup_timeout_millis: int,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
    ) -> None:
        self._runtime_id = runtime_id
        self._parent = parent
        self._accounting = CpuAccountingSession.start(baseline, budget=budget_counter)
        self._monitor_termination = monitor_termination
        self._interval_seconds = monitor_interval_millis / 1_000.0
        self._stable_final_samples = stable_final_samples
        self._cleanup_timeout_seconds = cleanup_timeout_millis / 1_000.0
        self._deadline_monotonic = deadline_monotonic
        self._is_cancelled = is_cancelled
        self._stop = threading.Event()
        self._failed: Exception | None = None
        self._exceeded = False
        self._kill_latency_seconds: float | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._monitor, name="external-inspector-cgroup-monitor", daemon=True
        )
        self._thread.start()

    def finalized_measurement(self) -> FixedRuntimeMeasurementV1:
        self._stop.set()
        self._thread.join(timeout=self._cleanup_timeout_seconds)
        if self._thread.is_alive():
            self.close()
            raise DockerRuntimeUnavailable("runtime cgroup monitor did not stop")
        if self._failed is not None:
            self.close()
            raise DockerRuntimeUnavailable(
                "runtime cgroup monitoring is unavailable"
            ) from self._failed
        if self._is_cancelled():
            self.close()
            raise DockerRuntimeUnavailable("runtime execution was cancelled")
        try:
            if not self._parent.is_unpopulated():
                raise DockerRuntimeUnavailable("runtime parent remains populated before cleanup")
            finals = [self._parent.read_aggregate_cpu() for _ in range(self._stable_final_samples)]
            if any(sample != finals[0] for sample in finals[1:]):
                raise DockerRuntimeUnavailable("runtime final aggregate CPU counter is unstable")
            final = self._accounting.final(finals[0])
            if final.consumed > final.budget and not self._exceeded:
                raise DockerRuntimeUnavailable(
                    "runtime CPU cap was exceeded without a measured termination"
                )
            disposition = (
                RuntimeControlDispositionV1.CPU_LIMIT_EXCEEDED
                if self._exceeded
                else RuntimeControlDispositionV1.COMPLETED
            )
            return FixedRuntimeMeasurementV1(
                runtime_id=self._runtime_id,
                counter_unit=CpuCounterUnitV1.CPU_USEC,
                baseline_counter=final.baseline,
                final_counter=final.final,
                consumed_counter=final.consumed,
                budget_counter=final.budget,
                threshold_exceeded=self._exceeded,
                disposition=disposition,
                kill_latency_seconds=self._kill_latency_seconds,
            )
        except RuntimeControlUnavailable as exc:
            raise DockerRuntimeUnavailable("runtime CPU final measurement is unavailable") from exc
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._stop.set()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=self._cleanup_timeout_seconds)
            if self._thread.is_alive():
                raise DockerRuntimeUnavailable("runtime cgroup monitor did not stop for cleanup")
        self._closed = True
        self._parent.close()

    def _monitor(self) -> None:
        try:
            while not self._stop.wait(self._interval_seconds):
                if time.monotonic() >= self._deadline_monotonic or self._is_cancelled():
                    reason = (
                        "DEADLINE_EXCEEDED"
                        if time.monotonic() >= self._deadline_monotonic
                        else "CANCELLED"
                    )
                    self._kill_latency_seconds = self._monitor_termination(reason)
                    raise DockerRuntimeUnavailable("runtime monitor deadline or authority was lost")
                observed = self._accounting.monitor(self._parent.read_aggregate_cpu())
                if observed.exceeded and self._kill_latency_seconds is None:
                    self._kill_latency_seconds = self._monitor_termination("CPU_LIMIT_EXCEEDED")
                    self._exceeded = True
                    raise DockerRuntimeUnavailable("runtime CPU cap was exceeded")
        except Exception as exc:
            self._failed = exc


class DockerCgroupRuntimeMeasurement:
    """Concrete aggregate parent-slice accounting using its durable pre-create baseline."""

    def __init__(
        self,
        *,
        client: DockerEngineClientV1,
        cgroups: CgroupV2RootV1,
        config: DockerCgroupMeasurementConfigV1,
    ) -> None:
        # Termination is launcher-owned; this retained parameter keeps the
        # concrete assembly's single Engine identity explicit without exposing
        # a monitor-side mutation route.
        del client
        self._cgroups = cgroups
        self._config = config

    def start(
        self,
        *,
        runtime_id: str,
        attempt: ExactRuntimeBindingPort,
        runtime_parent: RuntimeParentReceiptV1,
        configuration: FixedContainerConfigurationV1,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
        monitor_termination: Callable[[str], float],
    ) -> DockerActiveCgroupMeasurement:
        del attempt
        if configuration.cpu_counter_unit is not CpuCounterUnitV1.CPU_USEC:
            raise DockerRuntimeUnavailable("runtime CPU counter unit is unavailable")
        if runtime_parent.cpu_counter_unit != CpuCounterUnitV1.CPU_USEC.value:
            raise DockerRuntimeUnavailable("runtime parent CPU counter unit differs")
        parent = self._cgroups.open_attempt_slice(
            control_group=runtime_parent.control_group,
            expected_slice_name=runtime_parent.unit_name,
        )
        try:
            identity = parent.identity()
            if identity.st_dev != runtime_parent.device or identity.st_ino != runtime_parent.inode:
                raise DockerRuntimeUnavailable("runtime parent cgroup identity changed")
            parent.verify_required_controllers()
            current = parent.read_aggregate_cpu()
            if current.value < runtime_parent.baseline_cpu_counter:
                raise DockerRuntimeUnavailable("runtime parent CPU counter rolled back")
            return DockerActiveCgroupMeasurement(
                runtime_id=runtime_id,
                parent=parent,
                baseline=AggregateCpuCounterV1(
                    value=runtime_parent.baseline_cpu_counter,
                    unit=CpuCounterUnitV1.CPU_USEC,
                    complete_process_tree=True,
                ),
                budget_counter=configuration.cpu_budget_counter,
                monitor_termination=monitor_termination,
                monitor_interval_millis=self._config.monitor_interval_millis,
                stable_final_samples=self._config.stable_final_samples,
                cleanup_timeout_millis=self._config.cleanup_timeout_millis,
                deadline_monotonic=deadline_monotonic,
                is_cancelled=is_cancelled,
            )
        except Exception:
            parent.close()
            raise


class DockerExactRuntimeRegistry:
    """Exact deterministic-name recovery and removal with no Engine inventory endpoint."""

    def __init__(
        self,
        *,
        client: DockerEngineClientV1,
        recovery_timeout_millis: int,
        monotonic: Callable[[], float],
    ) -> None:
        if type(recovery_timeout_millis) is not int or recovery_timeout_millis <= 0:
            raise ValueError("runtime recovery deadline is required")
        if not callable(monotonic):
            raise ValueError("runtime recovery clock is required")
        self._client = client
        self._recovery_timeout_millis = recovery_timeout_millis
        self._monotonic = monotonic

    def resolve_exact(self, binding: ExactRuntimeBindingPort) -> str | None:
        deadline = self._recovery_deadline()
        try:
            inspected = self._client.inspect_exact(
                binding.container_name, deadline_monotonic=deadline
            )
        except DockerRuntimeMissing:
            return None
        return _verified_cleanup_runtime_id(inspected, binding)

    def quiesce_exact(
        self,
        *,
        runtime_id: str,
        binding: ExactRuntimeBindingPort | None = None,
        attempt: ExactRuntimeBindingPort | None = None,
        deadline_monotonic: float | None = None,
    ) -> bool:
        if binding is not None and attempt is not None:
            return False
        expected = binding if binding is not None else attempt
        if expected is None:
            return False
        if deadline_monotonic is not None and (
            type(deadline_monotonic) is not float or not math.isfinite(deadline_monotonic)
        ):
            return False
        # Cleanup has its own bounded operator-configured lifetime.  An
        # execution deadline may already be expired when a kill is mandatory.
        deadline = self._recovery_deadline()
        try:
            inspected = self._client.inspect_exact(runtime_id, deadline_monotonic=deadline)
            if _verified_cleanup_runtime_id(inspected, expected) != runtime_id:
                return False
            state = inspected.get("State")
            if not isinstance(state, dict) or type(state.get("Running")) is not bool:
                return False
            if state["Running"]:
                self._client.kill_exact(runtime_id, deadline_monotonic=deadline)
                self._client.wait_exact(runtime_id, deadline_monotonic=deadline)
                return True
            # Docker has not created a process or a systemd scope for a
            # container that is exactly ``created`` with PID 0.  Waiting for
            # it is both semantically wrong and can stall recovery forever.
            # It is nevertheless still bound by the re-read identity above
            # and is eligible for the exact remove step that follows.
            if state.get("Status") == "created" and state.get("Pid") == 0:
                return True
            # A known exited runtime has had a process.  Require Docker's
            # bounded wait receipt before parent accounting and removal.
            if state.get("Status") == "exited" and state.get("Pid") == 0:
                self._client.wait_exact(runtime_id, deadline_monotonic=deadline)
                return True
            return False
        except DockerRuntimeUnavailable:
            return False

    def remove_exact(
        self,
        *,
        runtime_id: str,
        binding: ExactRuntimeBindingPort | None = None,
        attempt: ExactRuntimeBindingPort | None = None,
        deadline_monotonic: float | None = None,
    ) -> bool:
        """Remove only an already-quiesced, identity-proved container."""
        if binding is not None and attempt is not None:
            return False
        expected = binding if binding is not None else attempt
        if expected is None:
            return False
        if deadline_monotonic is not None and (
            type(deadline_monotonic) is not float or not math.isfinite(deadline_monotonic)
        ):
            return False
        deadline = self._recovery_deadline()
        try:
            inspected = self._client.inspect_exact(runtime_id, deadline_monotonic=deadline)
            if _verified_cleanup_runtime_id(inspected, expected) != runtime_id:
                return False
            state = inspected.get("State")
            if not isinstance(state, dict) or state.get("Running") is not False:
                return False
            self._client.remove_exact(runtime_id, deadline_monotonic=deadline)
            return True
        except DockerRuntimeUnavailable:
            return False

    def _recovery_deadline(self) -> float:
        current = self._monotonic()
        if type(current) is not float or not math.isfinite(current):
            raise DockerRuntimeUnavailable("runtime recovery clock is unavailable")
        return current + self._recovery_timeout_millis / 1_000.0


class RootlessDockerRuntimeAdapter:
    """Create payloads and exact lifecycle calls from sealed facts only.

    It deliberately does not execute an image entrypoint or parse output; Task
    4B supplies that container-side protocol.  The adapter remains unavailable
    until an injected Task 5 proof establishes the host facts it consumes.
    """

    def __init__(
        self,
        *,
        client: DockerEngineClientV1,
        host_proof: RootlessDockerHostProofPort,
        images: LocalOciImageResolverPort,
    ) -> None:
        self._client = client
        self._host_proof = host_proof
        self._images = images

    def create_payload(
        self,
        *,
        configuration: FixedContainerConfigurationV1,
        binding: ExactRuntimeBindingPort,
        deadline_monotonic: float,
    ) -> dict[str, Any]:
        facts = self._host_proof.prove(configuration=configuration)
        if (
            facts.launcher_pid != os.getpid()
            or _SAFE_UNIT.fullmatch(binding.systemd_slice_name) is None
            or facts.verify_slice(binding=binding) is not True
        ):
            raise DockerRuntimeUnavailable("rootless Docker host facts are unavailable")
        image = self._images.resolve_exact(
            manifest_digest=configuration.image_manifest_digest,
            config_digest=configuration.image_config_digest,
        )
        if (
            image.manifest_digest != configuration.image_manifest_digest
            or image.config_digest != configuration.image_config_digest
        ):
            raise DockerRuntimeUnavailable(
                "offline OCI image proof does not match signed configuration"
            )
        payload = configuration.input_mount.source.consume_fd(
            lambda fd: self._create_payload_with_borrowed_fd(
                fd=fd,
                source=configuration.input_mount.source,
                facts=facts,
                image=image,
                configuration=configuration,
                binding=binding,
                deadline_monotonic=deadline_monotonic,
            ),
            deadline_monotonic=deadline_monotonic,
        )
        if not isinstance(payload, dict):
            raise DockerRuntimeUnavailable("borrowed source did not produce a Docker payload")
        return payload

    def create_exact(
        self,
        *,
        configuration: FixedContainerConfigurationV1,
        binding: ExactRuntimeBindingPort,
        deadline_monotonic: float,
    ) -> str:
        facts, image = self._prepare_host_and_image(
            configuration, binding, deadline_monotonic=deadline_monotonic
        )
        runtime_id = configuration.input_mount.source.consume_fd(
            lambda fd: self._create_with_borrowed_fd(
                fd=fd,
                source=configuration.input_mount.source,
                facts=facts,
                image=image,
                configuration=configuration,
                binding=binding,
                deadline_monotonic=deadline_monotonic,
            ),
            deadline_monotonic=deadline_monotonic,
        )
        if not isinstance(runtime_id, str):
            raise DockerRuntimeUnavailable("Docker create did not return an exact runtime ID")
        return runtime_id

    def start_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
        self._client.start_exact(runtime_id, deadline_monotonic=deadline_monotonic)

    def attach_exact(
        self, runtime_id: str, *, deadline_monotonic: float
    ) -> DockerMultiplexSessionPort:
        return self._client.attach_exact(runtime_id, deadline_monotonic=deadline_monotonic)

    def start_after_container_bound(
        self,
        *,
        runtime_id: str,
        configuration: FixedContainerConfigurationV1,
        binding: ExactRuntimeBindingPort,
        deadline_monotonic: float,
    ) -> None:
        """Reprove the borrowed bind immediately before and after the Engine start."""
        facts, image = self._prepare_host_and_image(
            configuration, binding, deadline_monotonic=deadline_monotonic
        )

        def start_with_fd(fd: int) -> None:
            _verify_borrowed_source(
                source=configuration.input_mount.source,
                configuration=configuration,
                deadline_monotonic=deadline_monotonic,
            )
            source = f"/proc/{facts.launcher_pid}/fd/{fd}"
            inspected = self._client.inspect_exact(
                runtime_id, deadline_monotonic=deadline_monotonic
            )
            _verify_created_inspection(
                inspected=inspected,
                runtime_id=runtime_id,
                binding=binding,
                configuration=configuration,
                image_id=image.docker_image_id,
                source=source,
            )
            self._client.start_exact(runtime_id, deadline_monotonic=deadline_monotonic)
            inspected = self._client.inspect_exact(
                runtime_id, deadline_monotonic=deadline_monotonic
            )
            _verify_created_inspection(
                inspected=inspected,
                runtime_id=runtime_id,
                binding=binding,
                configuration=configuration,
                image_id=image.docker_image_id,
                source=source,
            )
            state = inspected.get("State")
            if not isinstance(state, dict) or state.get("Running") is not True:
                raise DockerRuntimeUnavailable("Docker runtime did not enter running state")
            _verify_borrowed_source(
                source=configuration.input_mount.source,
                configuration=configuration,
                deadline_monotonic=deadline_monotonic,
            )

        result = configuration.input_mount.source.consume_fd(
            start_with_fd, deadline_monotonic=deadline_monotonic
        )
        if result is not None:
            raise DockerRuntimeUnavailable("borrowed source callback changed runtime start result")

    def kill_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
        self._client.kill_exact(runtime_id, deadline_monotonic=deadline_monotonic)

    def remove_exact(self, runtime_id: str, *, deadline_monotonic: float) -> None:
        self._client.remove_exact(runtime_id, deadline_monotonic=deadline_monotonic)

    def wait_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, Any]:
        return self._client.wait_exact(runtime_id, deadline_monotonic=deadline_monotonic)

    @staticmethod
    def _create_payload_with_borrowed_fd(
        *,
        fd: int,
        source: InspectorBorrowedSourcePort,
        facts: RootlessDockerHostFactsPort,
        image: LocalOciImageProof,
        configuration: FixedContainerConfigurationV1,
        binding: ExactRuntimeBindingPort,
        deadline_monotonic: float,
    ) -> dict[str, Any]:
        _verify_borrowed_source(
            source=source,
            configuration=configuration,
            deadline_monotonic=deadline_monotonic,
        )
        candidate = f"/proc/{facts.launcher_pid}/fd/{fd}"
        if (
            facts.verify_proc_fd(fd=fd, candidate=candidate, configuration=configuration)
            is not True
        ):
            raise DockerRuntimeUnavailable("rootless Docker proc-FD proof is unavailable")
        payload = _fixed_create_payload(
            configuration=configuration,
            binding=binding,
            image_id=image.docker_image_id,
            cgroup_parent=binding.systemd_slice_name,
            source=candidate,
        )
        _verify_borrowed_source(
            source=source,
            configuration=configuration,
            deadline_monotonic=deadline_monotonic,
        )
        return payload

    def _create_with_borrowed_fd(
        self,
        *,
        fd: int,
        source: InspectorBorrowedSourcePort,
        facts: RootlessDockerHostFactsPort,
        image: LocalOciImageProof,
        configuration: FixedContainerConfigurationV1,
        binding: ExactRuntimeBindingPort,
        deadline_monotonic: float,
    ) -> str:
        payload = self._create_payload_with_borrowed_fd(
            fd=fd,
            source=source,
            facts=facts,
            image=image,
            configuration=configuration,
            binding=binding,
            deadline_monotonic=deadline_monotonic,
        )
        runtime_id = self._client.create_exact(
            name=binding.container_name,
            payload=payload,
            deadline_monotonic=deadline_monotonic,
        )
        _verify_borrowed_source(
            source=source,
            configuration=configuration,
            deadline_monotonic=deadline_monotonic,
        )
        return runtime_id

    def _prepare_host_and_image(
        self,
        configuration: FixedContainerConfigurationV1,
        binding: ExactRuntimeBindingPort,
        *,
        deadline_monotonic: float,
    ) -> tuple[RootlessDockerHostFactsPort, LocalOciImageProof]:
        facts = self._host_proof.prove(configuration=configuration)
        if (
            facts.launcher_pid != os.getpid()
            or _SAFE_UNIT.fullmatch(binding.systemd_slice_name) is None
            or facts.verify_slice(binding=binding) is not True
        ):
            raise DockerRuntimeUnavailable("rootless Docker host facts are unavailable")
        image = self._images.resolve_exact(
            manifest_digest=configuration.image_manifest_digest,
            config_digest=configuration.image_config_digest,
        )
        if (
            image.manifest_digest != configuration.image_manifest_digest
            or image.config_digest != configuration.image_config_digest
        ):
            raise DockerRuntimeUnavailable(
                "offline OCI image proof does not match signed configuration"
            )
        inspected = self._client.inspect_local_image(
            image.docker_image_id, deadline_monotonic=deadline_monotonic
        )
        repository_digests = inspected.get("RepoDigests")
        image_config = inspected.get("Config")
        if (
            inspected.get("Id") != image.docker_image_id
            or not isinstance(repository_digests, list)
            or not any(
                isinstance(value, str) and value.endswith("@" + configuration.image_manifest_digest)
                for value in repository_digests
            )
            or not isinstance(image_config, dict)
            or image_config.get("Volumes") not in (None, {})
        ):
            raise DockerRuntimeUnavailable("local Docker image differs from offline OCI proof")
        return facts, image


def _fixed_create_payload(
    *,
    configuration: FixedContainerConfigurationV1,
    binding: ExactRuntimeBindingPort,
    image_id: str,
    cgroup_parent: str,
    source: str,
) -> dict[str, Any]:
    environment = [f"{key}={value}" for key, value in configuration.runtime_environment]
    labels = {
        "io.ksi.external-inspector.owner": binding.owner,
        "io.ksi.external-inspector.attempt-nonce": binding.attempt_nonce,
        "io.ksi.external-inspector.execution-manifest": binding.execution_manifest_digest,
        "io.ksi.external-inspector.oci-manifest": binding.oci_manifest_digest,
        "io.ksi.external-inspector.oci-config": binding.oci_config_digest,
        "io.ksi.external-inspector.backend-profile": binding.backend_profile_digest,
        "io.ksi.external-inspector.security-profile": binding.security_profile_digest,
        "io.ksi.external-inspector.resource-envelope": binding.resource_envelope_digest,
        "io.ksi.external-inspector.protocol": binding.inspector_protocol_digest,
    }
    return {
        "Image": image_id,
        "User": f"{configuration.runtime_uid}:{configuration.runtime_gid}",
        "Env": environment,
        "Tty": False,
        "OpenStdin": True,
        "StdinOnce": True,
        "AttachStdin": True,
        "AttachStdout": True,
        "AttachStderr": True,
        "Labels": labels,
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "AutoRemove": False,
            "GroupAdd": [],
            "CapAdd": [],
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "LogConfig": {"Type": "none", "Config": {}},
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": source,
                    "Target": "/input/artifact.tif",
                    "ReadOnly": True,
                    "BindOptions": {"NonRecursive": True},
                },
            ],
            # API 1.44 represents tmpfs options in HostConfig.Tmpfs, not in
            # MountPoint/TmpfsOptions.  Host proof later verifies mounted
            # flags because Docker inspect cannot report them faithfully.
            "Tmpfs": {
                "/work": (f"rw,nodev,nosuid,noexec,size={configuration.tmpfs_bytes},mode=0700")
            },
            "Memory": configuration.memory_bytes,
            "MemorySwap": configuration.memory_bytes,
            "PidsLimit": configuration.pids,
            "CpuPeriod": configuration.cpu_period_micros,
            "CpuQuota": configuration.cpu_quota_micros,
            "CgroupParent": cgroup_parent,
        },
    }


def _verify_created_inspection(
    *,
    inspected: dict[str, Any],
    runtime_id: str,
    binding: ExactRuntimeBindingPort,
    configuration: FixedContainerConfigurationV1,
    image_id: str,
    source: str,
) -> None:
    """Accept an Engine object only when every create-critical literal survived."""
    config = inspected.get("Config")
    host = inspected.get("HostConfig")
    mounts = inspected.get("Mounts")
    if not isinstance(config, dict) or not isinstance(host, dict) or not isinstance(mounts, list):
        raise DockerRuntimeUnavailable("Docker inspect response lacks fixed runtime fields")
    if (
        inspected.get("Id") != runtime_id
        or inspected.get("Name") != "/" + binding.container_name
        or inspected.get("Image") != image_id
        or config.get("Image") != image_id
        or config.get("User") != f"{configuration.runtime_uid}:{configuration.runtime_gid}"
        or config.get("Tty") is not False
        or config.get("OpenStdin") is not True
        or config.get("StdinOnce") is not True
        or config.get("AttachStdin") is not True
        or config.get("AttachStdout") is not True
        or config.get("AttachStderr") is not True
        or config.get("Env")
        != [f"{key}={value}" for key, value in configuration.runtime_environment]
        or config.get("Volumes") not in (None, {})
        or host.get("NetworkMode") != "none"
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("AutoRemove") is not False
        or host.get("GroupAdd") not in (None, [])
        or host.get("CapAdd") not in (None, [])
        or host.get("CapDrop") != ["ALL"]
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or host.get("LogConfig") != {"Type": "none", "Config": {}}
        or host.get("Binds") not in (None, [])
        or host.get("Tmpfs")
        != {"/work": (f"rw,nodev,nosuid,noexec,size={configuration.tmpfs_bytes},mode=0700")}
        or host.get("CgroupParent") != binding.systemd_slice_name
        or host.get("Memory") != configuration.memory_bytes
        or host.get("MemorySwap") != configuration.memory_bytes
        or host.get("PidsLimit") != configuration.pids
        or host.get("CpuPeriod") != configuration.cpu_period_micros
        or host.get("CpuQuota") != configuration.cpu_quota_micros
    ):
        raise DockerRuntimeUnavailable(
            "Docker inspect response changed fixed runtime configuration"
        )
    labels = config.get("Labels")
    required_labels = {
        "io.ksi.external-inspector.owner": binding.owner,
        "io.ksi.external-inspector.attempt-nonce": binding.attempt_nonce,
        "io.ksi.external-inspector.execution-manifest": binding.execution_manifest_digest,
        "io.ksi.external-inspector.oci-manifest": binding.oci_manifest_digest,
        "io.ksi.external-inspector.oci-config": binding.oci_config_digest,
        "io.ksi.external-inspector.backend-profile": binding.backend_profile_digest,
        "io.ksi.external-inspector.security-profile": binding.security_profile_digest,
        "io.ksi.external-inspector.resource-envelope": binding.resource_envelope_digest,
        "io.ksi.external-inspector.protocol": binding.inspector_protocol_digest,
    }
    if not isinstance(labels, dict) or any(
        labels.get(key) != value for key, value in required_labels.items()
    ):
        raise DockerRuntimeUnavailable(
            "Docker inspect response changed exact runtime binding labels"
        )
    input_mounts = [
        mount
        for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == "/input/artifact.tif"
    ]
    workspace_mounts = [
        mount for mount in mounts if isinstance(mount, dict) and mount.get("Destination") == "/work"
    ]
    if (
        len(mounts) != 2
        or len(input_mounts) != 1
        or len(workspace_mounts) != 1
        or input_mounts[0].get("Type") != "bind"
        or input_mounts[0].get("Source") != source
        or input_mounts[0].get("RW") is not False
        or workspace_mounts[0].get("Type") != "tmpfs"
        or workspace_mounts[0].get("RW") is not True
    ):
        raise DockerRuntimeUnavailable(
            "Docker inspect response did not prove one read-only input mount"
        )


def _verified_cleanup_runtime_id(
    inspected: dict[str, Any], binding: ExactRuntimeBindingPort
) -> str:
    """A known container may be removed only after its durable binding is reread exactly."""
    runtime_id = inspected.get("Id")
    config = inspected.get("Config")
    if (
        not isinstance(runtime_id, str)
        or _DOCKER_ID.fullmatch(runtime_id) is None
        or inspected.get("Name") != "/" + binding.container_name
        or not isinstance(config, dict)
        or not isinstance(config.get("Labels"), dict)
    ):
        raise DockerRuntimeUnavailable("Docker recovery inspect is not the recorded runtime")
    labels = config["Labels"]
    required = {
        "io.ksi.external-inspector.owner": binding.owner,
        "io.ksi.external-inspector.attempt-nonce": binding.attempt_nonce,
        "io.ksi.external-inspector.execution-manifest": binding.execution_manifest_digest,
        "io.ksi.external-inspector.oci-manifest": binding.oci_manifest_digest,
        "io.ksi.external-inspector.oci-config": binding.oci_config_digest,
        "io.ksi.external-inspector.backend-profile": binding.backend_profile_digest,
        "io.ksi.external-inspector.security-profile": binding.security_profile_digest,
        "io.ksi.external-inspector.resource-envelope": binding.resource_envelope_digest,
        "io.ksi.external-inspector.protocol": binding.inspector_protocol_digest,
    }
    if any(labels.get(key) != value for key, value in required.items()):
        raise DockerRuntimeUnavailable("Docker recovery labels differ from the recorded binding")
    return runtime_id


def _verify_borrowed_source(
    *,
    source: InspectorBorrowedSourcePort,
    configuration: FixedContainerConfigurationV1,
    deadline_monotonic: float,
) -> None:
    try:
        observed = source.verify_readback(deadline_monotonic=deadline_monotonic)
    except (InspectorStagingUnavailable, ProtocolViolation) as exc:
        raise DockerRuntimeUnavailable("borrowed source bounded readback is unavailable") from exc
    mount = configuration.input_mount
    if (
        not stat.S_ISREG(observed.mode)
        or observed.device != mount.source_device
        or observed.inode != mount.source_inode
        or observed.size_bytes != mount.observed_size_bytes
        or observed.sha256 != mount.observed_sha256
    ):
        raise DockerRuntimeUnavailable("borrowed source identity changed before Docker create")


def _read_at(directory_fd: int, name: str, maximum_bytes: int) -> str:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as exc:
        raise DockerRuntimeUnavailable("cgroup control file is unavailable") from exc
    try:
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(4096, maximum_bytes - observed + 1))
            if not chunk:
                break
            observed += len(chunk)
            if observed > maximum_bytes:
                raise DockerRuntimeUnavailable("cgroup control file exceeds configured cap")
            chunks.append(chunk)
    except OSError as exc:
        raise DockerRuntimeUnavailable("cgroup control file cannot be read") from exc
    finally:
        os.close(descriptor)
    try:
        return b"".join(chunks).decode("ascii")
    except UnicodeDecodeError as exc:
        raise DockerRuntimeUnavailable("cgroup control file is not ASCII") from exc


def _read_descriptor(descriptor: int, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    try:
        while True:
            chunk = os.read(descriptor, min(4096, maximum_bytes - observed + 1))
            if not chunk:
                return b"".join(chunks)
            observed += len(chunk)
            if observed > maximum_bytes:
                raise DockerRuntimeUnavailable("descriptor read exceeds configured cap")
            chunks.append(chunk)
    except OSError as exc:
        raise DockerRuntimeUnavailable("descriptor read is unavailable") from exc


def _single_value_controls(contents: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in contents.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] in values:
            raise DockerRuntimeUnavailable("cgroup control file is malformed")
        values[parts[0]] = parts[1]
    return values


def _parse_http_response(raw: bytes) -> DockerApiResponseV1:
    try:
        head, body = raw.split(b"\r\n\r\n", 1)
        lines = head.split(b"\r\n")
        version, status, _reason = lines[0].decode("ascii").split(" ", 2)
        status_code = int(status)
        if version != "HTTP/1.1" or not 100 <= status_code <= 599:
            raise ValueError
        headers: dict[str, str] = {}
        for line in lines[1:]:
            name, value = line.decode("ascii").split(":", 1)
            lowered = name.lower()
            if lowered in headers:
                raise ValueError
            headers[lowered] = value.strip()
        has_length = "content-length" in headers
        transfer_encoding = headers.get("transfer-encoding")
        if has_length and transfer_encoding is not None:
            raise ValueError
        if transfer_encoding is not None:
            if transfer_encoding.lower() != "chunked":
                raise ValueError
            body = _decode_chunked_http_body(body)
        elif has_length:
            length_text = headers["content-length"]
            if not length_text.isdecimal():
                raise ValueError
            length = int(length_text)
            if len(body) != length:
                raise ValueError
        elif status_code in {204, 304} or 100 <= status_code < 200:
            if body:
                raise ValueError
        elif headers.get("connection", "").lower() != "close":
            raise ValueError
        return DockerApiResponseV1(status=status_code, headers=headers, body=body)
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise DockerRuntimeUnavailable("Docker Engine HTTP response is malformed") from exc


def _decode_json_object(value: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise DockerRuntimeUnavailable("Docker Engine response is not JSON") from exc
    if not isinstance(parsed, dict):
        raise DockerRuntimeUnavailable("Docker Engine response is not an object")
    return parsed


def _read_http_header(
    connection: socket.socket, *, maximum_bytes: int, deadline_monotonic: float
) -> bytes:
    chunks = bytearray()
    try:
        while b"\r\n\r\n" not in chunks:
            if len(chunks) >= maximum_bytes:
                raise DockerRuntimeUnavailable("Docker attach response header exceeds its cap")
            # Do not consume the first multiplex byte while parsing the upgraded header.
            _set_socket_deadline_or_raise(connection, deadline_monotonic)
            chunk = connection.recv(1)
            if not chunk:
                raise DockerRuntimeUnavailable("Docker attach response header is truncated")
            chunks.extend(chunk)
    except (OSError, TimeoutError) as exc:
        raise DockerRuntimeUnavailable("Docker attach response header is unavailable") from exc
    return bytes(chunks)


def _read_exact_socket(
    connection: socket.socket, size: int, *, deadline_monotonic: float
) -> bytes | None:
    if size == 0:
        return b""
    chunks: list[bytes] = []
    remaining = size
    try:
        while remaining:
            _set_socket_deadline_or_raise(connection, deadline_monotonic)
            chunk = connection.recv(remaining)
            if not chunk:
                if not chunks:
                    return None
                raise DockerRuntimeUnavailable("Docker attach stream is truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
    except (OSError, TimeoutError) as exc:
        raise DockerRuntimeUnavailable("Docker attach stream is unavailable") from exc
    return b"".join(chunks)


def _set_socket_deadline_or_raise(connection: socket.socket, deadline_monotonic: float) -> None:
    remaining = deadline_monotonic - _monotonic()
    if not math.isfinite(remaining) or remaining <= 0.0:
        raise DockerRuntimeUnavailable("Docker attach deadline expired")
    connection.settimeout(remaining)


def _send_all_socket(
    connection: socket.socket, payload: bytes, *, deadline_monotonic: float
) -> None:
    view = memoryview(payload)
    while view:
        _set_socket_deadline_or_raise(connection, deadline_monotonic)
        sent = connection.send(view)
        if sent <= 0:
            raise DockerRuntimeUnavailable("Docker socket write did not advance")
        view = view[sent:]


def _decode_chunked_http_body(raw: bytes) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while True:
        ending = raw.find(b"\r\n", offset)
        if ending < 0:
            raise ValueError
        length_text = raw[offset:ending]
        if not length_text or b";" in length_text:
            raise ValueError
        try:
            length = int(length_text, 16)
        except ValueError as exc:
            raise ValueError from exc
        offset = ending + 2
        if length < 0 or len(raw) < offset + length + 2:
            raise ValueError
        chunks.append(raw[offset : offset + length])
        offset += length
        if raw[offset : offset + 2] != b"\r\n":
            raise ValueError
        offset += 2
        if length == 0:
            if offset != len(raw):
                raise ValueError
            return b"".join(chunks[:-1])


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise DockerRuntimeUnavailable("Docker create payload is invalid") from exc


def _require_identifier(value: object, description: str) -> None:
    if not isinstance(value, str) or _DOCKER_ID.fullmatch(value) is None:
        raise DockerRuntimeUnavailable(f"{description} is invalid")


def _checked_id(value: str) -> str:
    _require_identifier(value, "Docker runtime ID")
    return value


def _monotonic() -> float:
    import time

    return time.monotonic()


__all__ = [
    "CgroupV2CpuStatReader",
    "CgroupV2AttemptSlice",
    "CgroupV2RootConfigV1",
    "CgroupV2RootV1",
    "DockerActiveCgroupMeasurement",
    "DockerApiResponseV1",
    "DockerEngineClientV1",
    "DockerCgroupMeasurementConfigV1",
    "DockerCgroupRuntimeMeasurement",
    "DockerExactRuntimeRegistry",
    "DockerStartedRuntimeVerifierPort",
    "DockerStartedScopeVerifier",
    "DockerMultiplexSessionPort",
    "DockerRuntimeUnavailable",
    "DockerRuntimeMissing",
    "FileLocalOciPairResolver",
    "FileOciPairResolverConfigV1",
    "LocalOciImageProofV1",
    "LocalOciImageProofV2",
    "RootlessDockerRuntimeAdapter",
    "RootlessDockerSocketConfigV1",
    "ProcCgroupReader",
    "ProcCgroupReaderPort",
    "UnixSocketDockerEngineWire",
    "UnixSocketDockerMultiplexSession",
]
