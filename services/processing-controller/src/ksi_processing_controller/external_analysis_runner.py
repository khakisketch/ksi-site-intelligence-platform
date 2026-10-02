"""Local-only V1 worker; Core URL must use an unscoped literal IP address."""

from __future__ import annotations

import argparse
import os
import stat
from collections.abc import Sequence
from pathlib import Path

from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
from ksi_processing_controller.external_analysis_worker import (
    ProcessingWorkerRuntimeIdentityV1,
    poll,
    run_once,
)
from ksi_processing_controller.external_analysis_worker_config import (
    AnalysisWorkerConfigUnavailable,
    AnalysisWorkerConfigV1,
    load_analysis_worker_config,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)

_MAX_TOKEN_BYTES = 4096


def _endpoint(value: str) -> TrustedObjectEndpointV1:
    origin, separator, addresses = value.partition("=")
    if not separator or not origin or not addresses:
        raise argparse.ArgumentTypeError("endpoint must be ORIGIN=IP[,IP]")
    try:
        return TrustedObjectEndpointV1(
            origin=origin, addresses=tuple(address.strip() for address in addresses.split(","))
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError("endpoint is not a trusted static origin") from exc


def _worker_token_file(value: object) -> str:
    """Read one local bearer secret without retaining it in process arguments."""
    if type(value) is not str:
        raise ValueError("worker token file is invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise ValueError("worker token file is invalid")
    directory_fd = -1
    descriptor = -1
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
                _validate_token_parent(parent, child)
            except BaseException:
                os.close(next_fd)
                raise
            os.close(directory_fd)
            directory_fd = next_fd
            parent = child
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        node = os.fstat(descriptor)
        _validate_token_parent(parent, node)
        if (
            not stat.S_ISREG(node.st_mode)
            or node.st_uid != os.geteuid()
            or node.st_gid != os.getegid()
            or stat.S_IMODE(node.st_mode) != 0o600
            or node.st_nlink != 1
            or not 0 < node.st_size <= _MAX_TOKEN_BYTES
        ):
            raise ValueError("worker token file is invalid")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(1024, _MAX_TOKEN_BYTES - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > _MAX_TOKEN_BYTES:
                raise ValueError("worker token file is invalid")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        raw = b"".join(chunks)
        if len(raw) != node.st_size or _token_file_metadata(after) != _token_file_metadata(node):
            raise ValueError("worker token file is invalid")
    except (OSError, ValueError):
        raise ValueError("worker token file is invalid") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory_fd >= 0:
            os.close(directory_fd)
    if len(raw) > _MAX_TOKEN_BYTES:
        raise ValueError("worker token file is invalid")
    try:
        token = raw.decode("ascii").removesuffix("\n")
    except UnicodeDecodeError:
        raise ValueError("worker token file is invalid") from None
    if (
        not token
        or token.strip() != token
        or "\n" in token
        or "\r" in token
        or any(ord(character) <= 32 or ord(character) > 126 for character in token)
    ):
        raise ValueError("worker token file is invalid")
    return token


def _validate_token_parent(parent: os.stat_result, child: os.stat_result) -> None:
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
        raise ValueError("worker token file is invalid")


def _token_file_metadata(node: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        node.st_size,
        node.st_mtime_ns,
        node.st_ctime_ns,
        node.st_mode,
        node.st_uid,
        node.st_gid,
        node.st_nlink,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--core-url",
        help="trusted unscoped literal-IP HTTP(S) Core origin; HTTP must be loopback",
    )
    parser.add_argument(
        "--config", help="absolute owner-protected analysis-worker-config.v1 JSON file"
    )
    parser.add_argument("--worker-token-file", required=True)
    parser.add_argument("--worker-instance-id")
    parser.add_argument("--worker-executable-digest")
    parser.add_argument("--worker-build-digest")
    parser.add_argument("--runtime-image-version")
    parser.add_argument("--runtime-image-oci-digest")
    parser.add_argument("--dependency-lock-digest")
    parser.add_argument("--trusted-object-endpoint", action="append", type=_endpoint)
    parser.add_argument("--max-header-bytes", type=int)
    parser.add_argument("--max-object-bytes", type=int)
    parser.add_argument("--max-chunk-bytes", type=int)
    parser.add_argument("--request-timeout-seconds", type=float)
    parser.add_argument("--poll-interval-seconds", type=float)
    parser.add_argument("--once", action="store_true")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    values = _parser().parse_args(arguments)
    try:
        if values.config is not None:
            if any(
                value is not None
                for value in (
                    values.core_url,
                    values.worker_instance_id,
                    values.worker_executable_digest,
                    values.worker_build_digest,
                    values.runtime_image_version,
                    values.runtime_image_oci_digest,
                    values.dependency_lock_digest,
                    values.trusted_object_endpoint,
                    values.max_header_bytes,
                    values.max_object_bytes,
                    values.max_chunk_bytes,
                    values.request_timeout_seconds,
                    values.poll_interval_seconds,
                )
            ):
                return 2
            config = load_analysis_worker_config(values.config)
        else:
            config = _legacy_config(values)
        token = _worker_token_file(values.worker_token_file)
    except (AnalysisWorkerConfigUnavailable, TypeError, ValueError):
        return 2
    with ExternalAnalysisCoreClient(
        base_url=config.core_base_url,
        worker_token=token,
        worker_instance_id=config.worker_instance_id,
        maximum_response_bytes=config.maximum_response_bytes,
        request_timeout_seconds=config.request_timeout_seconds,
    ) as client:
        if values.once:
            return 0 if run_once(client, config.runtime, config.object_transport) else 1
        poll(
            client,
            config.runtime,
            config.object_transport,
            poll_interval_seconds=config.poll_interval_seconds,
        )
    return 0


def _legacy_config(values: argparse.Namespace) -> AnalysisWorkerConfigV1:
    required = (
        values.core_url,
        values.worker_instance_id,
        values.worker_executable_digest,
        values.worker_build_digest,
        values.runtime_image_version,
        values.runtime_image_oci_digest,
        values.dependency_lock_digest,
        values.trusted_object_endpoint,
        values.max_header_bytes,
        values.max_object_bytes,
        values.max_chunk_bytes,
        values.request_timeout_seconds,
        values.poll_interval_seconds,
    )
    if any(value is None for value in required):
        raise ValueError("legacy Analysis worker arguments are incomplete")
    runtime = ProcessingWorkerRuntimeIdentityV1(
        worker_executable_digest=values.worker_executable_digest,
        worker_build_digest=values.worker_build_digest,
        runtime_image_version=values.runtime_image_version,
        runtime_image_oci_digest=values.runtime_image_oci_digest,
        dependency_lock_digest=values.dependency_lock_digest,
    )
    transport = ExternalObjectTransportPolicyV1(
        endpoints=tuple(values.trusted_object_endpoint),
        max_header_bytes=values.max_header_bytes,
        max_object_bytes=values.max_object_bytes,
        max_chunk_bytes=values.max_chunk_bytes,
    )
    if not 128 <= values.max_object_bytes <= 1_073_741_824:
        raise ValueError("legacy Analysis worker limit is invalid")
    if not 1 <= values.max_chunk_bytes <= min(values.max_object_bytes, 67_108_864):
        raise ValueError("legacy Analysis worker limit is invalid")
    if not 1 <= values.max_header_bytes <= 1_048_576:
        raise ValueError("legacy Analysis worker limit is invalid")
    if (
        not 0 < values.request_timeout_seconds <= 120
        or not 0 < values.poll_interval_seconds <= 3600
    ):
        raise ValueError("legacy Analysis worker timeout is invalid")
    from ksi_processing_controller.external_analysis_core_client import _trusted_base_url

    return AnalysisWorkerConfigV1(
        core_base_url=_trusted_base_url(values.core_url),
        maximum_response_bytes=262_144,
        request_timeout_seconds=values.request_timeout_seconds,
        worker_instance_id=values.worker_instance_id,
        runtime=runtime,
        object_transport=transport,
        poll_interval_seconds=values.poll_interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
