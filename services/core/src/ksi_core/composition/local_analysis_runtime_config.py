"""Protected local-only material for the opt-in Analysis development graph.

This module reads operator-provided facts; it neither creates authority nor
selects a calculation profile.  The common Core assembly remains the only
place that builds the graph from these already sealed snapshots.
"""

from __future__ import annotations

import json
import os
import stat
from enum import StrEnum
from pathlib import Path
from typing import Any, Never

from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_relative_volume_analysis import AnalysisPolicyV2
from pydantic import ValidationError

from ksi_core.composition.external_graph import ExternalAnalysisLocalGraphConfig
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisRuntimeIdentityV2,
)

_VERSION = "local-analysis-runtime.v1"
_MAX_CONFIG_BYTES = 64 * 1024
_MAX_TEXT = 4_096
_TOP_LEVEL_FIELDS = {"version", "policy", "runtime", "resourceEnvelope"}
_RUNTIME_FIELDS = {
    "workerExecutableDigest",
    "workerBuildDigest",
    "runtimeImageVersion",
    "runtimeImageOciDigest",
    "dependencyLockDigest",
}


class LocalAnalysisRuntimeConfigBlockedCode(StrEnum):
    CONFIG_FILE = "CONFIG_FILE"
    CONFIG_SYNTAX = "CONFIG_SYNTAX"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    CONFIG_VALUE = "CONFIG_VALUE"


class LocalAnalysisRuntimeConfigUnavailable(RuntimeError):
    """The explicitly provisioned local Analysis graph facts are not trustworthy."""

    def __init__(self, code: LocalAnalysisRuntimeConfigBlockedCode) -> None:
        self.code = code
        super().__init__("local Analysis runtime configuration blocked: " + code.value)


def load_local_analysis_runtime_config(path: Path) -> ExternalAnalysisLocalGraphConfig:
    """Load one private sealed configuration file without ambient fallbacks."""

    raw = _read_private_config(path)
    try:
        wire = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise LocalAnalysisRuntimeConfigUnavailable(
            LocalAnalysisRuntimeConfigBlockedCode.CONFIG_SYNTAX
        ) from exc

    try:
        body = _mapping(wire, _TOP_LEVEL_FIELDS)
        if _text(body["version"]) != _VERSION:
            raise ValueError("unsupported local Analysis runtime config version")
        policy = AnalysisPolicyV2.model_validate(body["policy"])
        resource_envelope = ResourceEnvelopeV1.model_validate(body["resourceEnvelope"])
        runtime = _runtime_identity(_mapping(body["runtime"], _RUNTIME_FIELDS))
        if (
            policy.policy_digest is None
            or policy.policy_digest != policy.canonical_digest()
            or resource_envelope.resource_envelope_digest is None
            or resource_envelope.resource_envelope_digest
            != resource_envelope.canonical_digest()
        ):
            raise ValueError("local Analysis material must already be sealed")
        return ExternalAnalysisLocalGraphConfig(
            policy=policy,
            runtime=runtime,
            resource_envelope=resource_envelope,
        )
    except LocalAnalysisRuntimeConfigUnavailable:
        raise
    except (KeyError, TypeError, ValueError, ValidationError, AttributeError) as exc:
        raise LocalAnalysisRuntimeConfigUnavailable(
            LocalAnalysisRuntimeConfigBlockedCode.CONFIG_VALUE
        ) from exc


def _runtime_identity(value: dict[str, object]) -> AnalysisRuntimeIdentityV2:
    return AnalysisRuntimeIdentityV2(
        worker_executable_digest=_text(value["workerExecutableDigest"]),
        worker_build_digest=_text(value["workerBuildDigest"]),
        runtime_image_version=_text(value["runtimeImageVersion"]),
        runtime_image_oci_digest=_text(value["runtimeImageOciDigest"]),
        dependency_lock_digest=_text(value["dependencyLockDigest"]),
    )


def _read_private_config(path: Path) -> bytes:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 2
    ):
        raise LocalAnalysisRuntimeConfigUnavailable(
            LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE
        )

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(path.anchor, directory_flags)
        parent = os.fstat(directory_fd)
        for component in path.parts[1:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            try:
                child = os.fstat(next_fd)
                _validate_private_ancestor(parent, child)
            except BaseException:
                os.close(next_fd)
                raise
            os.close(directory_fd)
            directory_fd = next_fd
            parent = child

        file_fd = os.open(path.name, file_flags, dir_fd=directory_fd)
        before = os.fstat(file_fd)
        _validate_private_ancestor(parent, before)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_CONFIG_BYTES
        ):
            raise LocalAnalysisRuntimeConfigUnavailable(
                LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE
            )
        content = _read_bounded(file_fd, _MAX_CONFIG_BYTES, expected_bytes=before.st_size)
        after = os.fstat(file_fd)
        if len(content) != before.st_size or _stable_file_metadata(
            after
        ) != _stable_file_metadata(before):
            raise LocalAnalysisRuntimeConfigUnavailable(
                LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE
            )
        return content
    except (OSError, ValueError) as exc:
        raise LocalAnalysisRuntimeConfigUnavailable(
            LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE
        ) from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _validate_private_ancestor(parent: os.stat_result, child: os.stat_result) -> None:
    mode = parent.st_mode
    writable_by_group_or_other = bool(stat.S_IMODE(mode) & 0o022)
    sticky_protects_child = bool(stat.S_ISVTX & mode) and (
        parent.st_uid == os.geteuid() or child.st_uid == os.geteuid()
    )
    if (
        not stat.S_ISDIR(mode)
        or parent.st_uid not in {0, os.geteuid()}
        or (writable_by_group_or_other and not sticky_protects_child)
    ):
        raise LocalAnalysisRuntimeConfigUnavailable(
            LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE
        )


def _stable_file_metadata(node: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        node.st_size,
        node.st_mtime_ns,
        node.st_ctime_ns,
        node.st_mode,
        node.st_uid,
        node.st_gid,
        node.st_nlink,
    )


def _read_bounded(descriptor: int, maximum_bytes: int, *, expected_bytes: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = os.read(descriptor, min(8_192, maximum_bytes - observed + 1))
        if not chunk:
            content = b"".join(chunks)
            if len(content) != expected_bytes:
                raise LocalAnalysisRuntimeConfigUnavailable(
                    LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE
                )
            return content
        observed += len(chunk)
        if observed > maximum_bytes:
            raise LocalAnalysisRuntimeConfigUnavailable(
                LocalAnalysisRuntimeConfigBlockedCode.CONFIG_FILE
            )
        chunks.append(chunk)


def _mapping(value: object, expected: set[str]) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError("configuration object is invalid")
    keys = set(value)
    if keys - expected:
        raise LocalAnalysisRuntimeConfigUnavailable(
            LocalAnalysisRuntimeConfigBlockedCode.UNKNOWN_FIELD
        )
    if keys != expected:
        raise ValueError("configuration object has missing fields")
    return value


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_TEXT
        or any(ord(character) < 0x20 for character in value)
    ):
        raise ValueError("configuration text is invalid")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for key, value in pairs:
        if key in body:
            raise ValueError("duplicate JSON field")
        body[key] = value
    return body


def _reject_json_constant(value: str) -> Never:
    raise ValueError("non-finite JSON value is forbidden")
