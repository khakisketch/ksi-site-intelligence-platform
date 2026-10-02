"""Strict protected local configuration for the standalone Analysis worker."""

from __future__ import annotations

import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ksi_processing_controller.external_analysis_core_client import _trusted_base_url
from ksi_processing_controller.external_analysis_worker import ProcessingWorkerRuntimeIdentityV1
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)

_VERSION = "analysis-worker-config.v1"
_MAX_CONFIG_BYTES = 64 * 1024
_MAX_ENDPOINTS = 32
_MAX_ADDRESSES_PER_ENDPOINT = 16
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z")


class AnalysisWorkerConfigUnavailable(RuntimeError):
    """A fixed, non-sensitive error for untrusted or invalid local configuration."""

    def __init__(self) -> None:
        super().__init__("analysis worker configuration is invalid")


@dataclass(frozen=True, slots=True)
class AnalysisWorkerConfigV1:
    core_base_url: str
    maximum_response_bytes: int
    request_timeout_seconds: float
    worker_instance_id: str
    runtime: ProcessingWorkerRuntimeIdentityV1
    object_transport: ExternalObjectTransportPolicyV1
    poll_interval_seconds: float


def load_analysis_worker_config(path: str) -> AnalysisWorkerConfigV1:
    """Load one bounded private file; never create files or perform network I/O."""
    try:
        wire = json.loads(
            _read_private_config(path).decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        root = _mapping(wire, {"version", "core", "worker", "runtime", "objectTransport", "runner"})
        if _text(root["version"], maximum=64) != _VERSION:
            raise ValueError

        core = _mapping(root["core"], {"baseUrl", "maximumResponseBytes", "requestTimeoutSeconds"})
        base_url = _trusted_base_url(core["baseUrl"])
        maximum_response_bytes = _bounded_int(core["maximumResponseBytes"], 128, 4_194_304)
        request_timeout_seconds = _bounded_float(core["requestTimeoutSeconds"], 0, 120)

        worker = _mapping(root["worker"], {"instanceId"})
        worker_instance_id = _text(worker["instanceId"], maximum=255)
        if _SAFE_ID.fullmatch(worker_instance_id) is None:
            raise ValueError

        runtime_wire = _mapping(
            root["runtime"],
            {
                "workerExecutableDigest",
                "workerBuildDigest",
                "runtimeImageVersion",
                "runtimeImageOciDigest",
                "dependencyLockDigest",
            },
        )
        runtime = ProcessingWorkerRuntimeIdentityV1(
            worker_executable_digest=_text(runtime_wire["workerExecutableDigest"], maximum=80),
            worker_build_digest=_text(runtime_wire["workerBuildDigest"], maximum=80),
            runtime_image_version=_text(runtime_wire["runtimeImageVersion"], maximum=255),
            runtime_image_oci_digest=_text(runtime_wire["runtimeImageOciDigest"], maximum=80),
            dependency_lock_digest=_text(runtime_wire["dependencyLockDigest"], maximum=80),
        )

        transport_wire = _mapping(
            root["objectTransport"],
            {"endpoints", "maxHeaderBytes", "maxObjectBytes", "maxChunkBytes"},
        )
        raw_endpoints = transport_wire["endpoints"]
        if type(raw_endpoints) is not list or not 1 <= len(raw_endpoints) <= _MAX_ENDPOINTS:
            raise ValueError
        endpoints: list[TrustedObjectEndpointV1] = []
        for raw_endpoint in raw_endpoints:
            endpoint = _mapping(raw_endpoint, {"origin", "addresses"})
            raw_addresses = endpoint["addresses"]
            if (
                type(raw_addresses) is not list
                or not 1 <= len(raw_addresses) <= _MAX_ADDRESSES_PER_ENDPOINT
            ):
                raise ValueError
            addresses = tuple(_text(value, maximum=64) for value in raw_addresses)
            endpoints.append(
                TrustedObjectEndpointV1(
                    origin=_text(endpoint["origin"], maximum=16_384),
                    addresses=addresses,
                )
            )
        transport = ExternalObjectTransportPolicyV1(
            endpoints=tuple(endpoints),
            max_header_bytes=_bounded_int(transport_wire["maxHeaderBytes"], 1, 1_048_576),
            max_object_bytes=_bounded_int(transport_wire["maxObjectBytes"], 1, 1_073_741_824),
            max_chunk_bytes=_bounded_int(transport_wire["maxChunkBytes"], 1, 67_108_864),
        )
        if transport.max_chunk_bytes > transport.max_object_bytes:
            raise ValueError

        runner = _mapping(root["runner"], {"pollIntervalSeconds"})
        poll_interval_seconds = _bounded_float(runner["pollIntervalSeconds"], 0, 3600)
        return AnalysisWorkerConfigV1(
            core_base_url=base_url,
            maximum_response_bytes=maximum_response_bytes,
            request_timeout_seconds=request_timeout_seconds,
            worker_instance_id=worker_instance_id,
            runtime=runtime,
            object_transport=transport,
            poll_interval_seconds=poll_interval_seconds,
        )
    except AnalysisWorkerConfigUnavailable:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise AnalysisWorkerConfigUnavailable() from exc


def _read_private_config(path_value: object) -> bytes:
    if type(path_value) is not str:
        raise ValueError
    path = Path(path_value)
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise ValueError
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(
            path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        parent = os.fstat(directory_fd)
        for component in path.parts[1:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            try:
                child = os.fstat(next_fd)
                _validate_ancestor(parent, child)
            except BaseException:
                os.close(next_fd)
                raise
            os.close(directory_fd)
            directory_fd = next_fd
            parent = child
        file_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        before = os.fstat(file_fd)
        _validate_ancestor(parent, before)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_CONFIG_BYTES
        ):
            raise ValueError
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(file_fd, min(8192, _MAX_CONFIG_BYTES - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > _MAX_CONFIG_BYTES:
                raise ValueError
            chunks.append(chunk)
        after = os.fstat(file_fd)
        if len(b"".join(chunks)) != before.st_size or _file_metadata(after) != _file_metadata(
            before
        ):
            raise ValueError
        return b"".join(chunks)
    except OSError as exc:
        raise ValueError from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _validate_ancestor(parent: os.stat_result, child: os.stat_result) -> None:
    mode = parent.st_mode
    sticky_safe = bool(stat.S_ISVTX & mode) and (
        parent.st_uid == os.geteuid() or child.st_uid == os.geteuid()
    )
    if (
        not stat.S_ISDIR(mode)
        or parent.st_uid not in {0, os.geteuid()}
        or (stat.S_IMODE(mode) & 0o022 and not sticky_safe)
        or child.st_uid not in {0, os.geteuid()}
    ):
        raise ValueError


def _file_metadata(node: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        node.st_size,
        node.st_mtime_ns,
        node.st_ctime_ns,
        node.st_mode,
        node.st_uid,
        node.st_gid,
        node.st_nlink,
    )


def _mapping(value: object, fields: set[str]) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) != fields
        or any(type(key) is not str for key in value)
    ):
        raise ValueError
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError


def _text(value: object, *, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum or value.strip() != value:
        raise ValueError
    return value


def _bounded_int(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError
    return value


def _bounded_float(value: object, minimum_exclusive: float, maximum: float) -> float:
    if type(value) is int:
        if not minimum_exclusive < value <= maximum:
            raise ValueError
        return float(value)
    if type(value) is not float:
        raise ValueError
    if not math.isfinite(value) or not minimum_exclusive < value <= maximum:
        raise ValueError
    return value
