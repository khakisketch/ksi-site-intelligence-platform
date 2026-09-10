"""Closed local UDS DTOs and exact framed-byte codec for the inspector launcher.

This module deliberately has no listener, filesystem staging, parser, Core
runtime import, or Docker operation.  Callers provide every finite transport
limit and own the lifetime of any staged bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
import select
import socket
import struct
import time
from collections.abc import Callable
from enum import StrEnum
from io import BytesIO
from typing import Annotated, Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    Digest,
    ExternalArtifactInspectionRequestV1,
    ExternalValidationPolicyV1,
    PolicyStatus,
    SealedExternalSubjectV1,
)
from pydantic import ConfigDict, Field, StrictInt, StringConstraints, model_validator

_PROTOCOL_VERSION = "inspector-launch.v1"
_BOUND_TEXT = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class ProtocolViolation(ValueError):
    """A peer supplied a malformed, unbound, short, or trailing wire value."""


class ProtocolDeadlineExceeded(ProtocolViolation):
    """The one supplied monotonic deadline elapsed during a wire operation."""


class _FrozenProtocolModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")


class InspectorOperation(StrEnum):
    INSPECT = "INSPECT"
    SANITIZE = "SANITIZE"


class InspectorFailureReason(StrEnum):
    """No backend exception, path, policy detail, or parser text crosses the UDS terminal frame."""

    INSPECTOR_UNAVAILABLE = "INSPECTOR_UNAVAILABLE"
    PROTOCOL_REJECTED = "PROTOCOL_REJECTED"
    INPUT_REJECTED = "INPUT_REJECTED"
    AUTHORITY_LOST = "AUTHORITY_LOST"


class LocalLeaseFenceV1(_FrozenProtocolModel):
    """Worker-owned mirror of Core's accepted, positive-generation lease fence."""

    worker_instance_id: _BOUND_TEXT
    lease_acquisition_id: _BOUND_TEXT
    lease_generation: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def _canonical_uuid4_ids(self) -> LocalLeaseFenceV1:
        for value in (self.worker_instance_id, self.lease_acquisition_id):
            try:
                parsed = UUID(value)
            except ValueError as exc:
                raise ValueError("lease identifiers must be canonical UUIDv4 strings") from exc
            if parsed.version != 4 or str(parsed) != value:
                raise ValueError("lease identifiers must be canonical UUIDv4 strings")
        return self


class SealedByteBindingV1(_FrozenProtocolModel):
    """The only byte identity permitted across this local boundary."""

    artifact_id: _BOUND_TEXT
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)


class InspectorLaunchRequestV1(_FrozenProtocolModel):
    """One immutable launch header, followed by exactly its sealed raw bytes."""

    protocol_version: Literal["inspector-launch.v1"] = "inspector-launch.v1"
    operation: InspectorOperation
    request: ExternalArtifactInspectionRequestV1
    fence: LocalLeaseFenceV1
    subject: SealedExternalSubjectV1
    sealed_byte_binding: SealedByteBindingV1
    policy: ExternalValidationPolicyV1
    attempt_nonce: _BOUND_TEXT
    canonical_input_digest: Digest

    @classmethod
    def seal(
        cls,
        *,
        operation: InspectorOperation,
        request: ExternalArtifactInspectionRequestV1,
        fence: LocalLeaseFenceV1,
        subject: SealedExternalSubjectV1,
        sealed_byte_binding: SealedByteBindingV1,
        policy: ExternalValidationPolicyV1,
        attempt_nonce: str,
    ) -> InspectorLaunchRequestV1:
        body = {
            "protocolVersion": _PROTOCOL_VERSION,
            "operation": operation.value,
            "request": request.model_dump(by_alias=True, mode="json"),
            "fence": fence.model_dump(by_alias=True, mode="json"),
            "subject": subject.model_dump(by_alias=True, mode="json"),
            "sealedByteBinding": sealed_byte_binding.model_dump(by_alias=True, mode="json"),
            "policy": policy.model_dump(by_alias=True, mode="json"),
            "attemptNonce": attempt_nonce,
        }
        return cls(
            operation=operation,
            request=request,
            fence=fence,
            subject=subject,
            sealed_byte_binding=sealed_byte_binding,
            policy=policy,
            attempt_nonce=attempt_nonce,
            canonical_input_digest=_sha256_digest(canonical_json_bytes(body)),
        )

    @model_validator(mode="after")
    def _binds_exact_core_authority(self) -> InspectorLaunchRequestV1:
        # Re-validate nested objects even if a caller handed over a constructed instance.
        request = ExternalArtifactInspectionRequestV1.model_validate(self.request.__dict__)
        subject = SealedExternalSubjectV1.model_validate(self.subject.__dict__)
        policy = ExternalValidationPolicyV1.model_validate(self.policy.__dict__)
        LocalLeaseFenceV1.model_validate(self.fence.__dict__)
        SealedByteBindingV1.model_validate(self.sealed_byte_binding.__dict__)
        if request.subject != subject:
            raise ValueError("subject must equal request subject")
        if (
            policy.status is not PolicyStatus.ACTIVE
            or policy.policy_digest is None
            or policy.resource_envelope is None
            or policy.resource_envelope_digest is None
        ):
            raise ValueError("launch policy must be sealed ACTIVE policy with resource envelope")
        if (
            request.inspection_policy_id != policy.policy_id
            or request.inspection_policy_version != policy.version
            or request.inspection_policy_digest != policy.policy_digest
        ):
            raise ValueError("request must bind the exact sealed policy id, version, and digest")
        if self.canonical_input_digest != _sha256_digest(
            canonical_json_bytes(self.canonical_body_payload())
        ):
            raise ValueError("canonicalInputDigest must bind the exact canonical launch body")
        return self

    def canonical_body_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"canonical_input_digest"})

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(by_alias=True, mode="json"))

    def wire_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class InspectorLaunchResultV1(_FrozenProtocolModel):
    """Closed acknowledgement or terminal launcher frame; raw output follows only completion."""

    protocol_version: Literal["inspector-launch.v1"] = "inspector-launch.v1"
    result: Literal["ACCEPTED", "FAILED", "COMPLETED"]
    attempt_nonce: _BOUND_TEXT
    canonical_input_digest: Digest | None = None
    inspector_build_digest: Digest | None = None
    outcome: ArtifactInspectionOutcomeV1 | Literal["SANITIZED"] | None = None
    output_size_bytes: StrictInt | None = None
    output_sha256: Digest | None = None
    reason: InspectorFailureReason | None = None

    @classmethod
    def accepted(cls, attempt_nonce: str) -> InspectorLaunchResultV1:
        return cls(result="ACCEPTED", attempt_nonce=attempt_nonce)

    @classmethod
    def failed(cls, attempt_nonce: str, reason: InspectorFailureReason) -> InspectorLaunchResultV1:
        return cls(result="FAILED", attempt_nonce=attempt_nonce, reason=reason)

    @classmethod
    def completed_inspection(
        cls,
        attempt_nonce: str,
        canonical_input_digest: str,
        inspector_build_digest: str,
        outcome: ArtifactInspectionOutcomeV1,
    ) -> InspectorLaunchResultV1:
        return cls(
            result="COMPLETED",
            attempt_nonce=attempt_nonce,
            canonical_input_digest=canonical_input_digest,
            inspector_build_digest=inspector_build_digest,
            outcome=outcome,
            output_size_bytes=0,
        )

    @classmethod
    def completed_sanitized(
        cls,
        attempt_nonce: str,
        canonical_input_digest: str,
        inspector_build_digest: str,
        output_size_bytes: int,
        output_sha256: str,
    ) -> InspectorLaunchResultV1:
        return cls(
            result="COMPLETED",
            attempt_nonce=attempt_nonce,
            canonical_input_digest=canonical_input_digest,
            inspector_build_digest=inspector_build_digest,
            outcome="SANITIZED",
            output_size_bytes=output_size_bytes,
            output_sha256=output_sha256,
        )

    @model_validator(mode="after")
    def _has_exact_variant_shape(self) -> InspectorLaunchResultV1:
        terminal_fields = (
            self.canonical_input_digest,
            self.inspector_build_digest,
            self.outcome,
            self.output_size_bytes,
            self.output_sha256,
            self.reason,
        )
        if self.result == "ACCEPTED":
            if any(value is not None for value in terminal_fields):
                raise ValueError(
                    "ACCEPTED may contain only protocolVersion, result, and attemptNonce"
                )
            return self
        if self.result == "FAILED":
            if self.reason is None or any(value is not None for value in terminal_fields[:-1]):
                raise ValueError("FAILED requires only attemptNonce and typed reason")
            return self
        if (
            self.canonical_input_digest is None
            or self.inspector_build_digest is None
            or self.outcome is None
            or self.reason is not None
        ):
            raise ValueError("COMPLETED requires exact input/build digests and outcome")
        if isinstance(self.outcome, ArtifactInspectionOutcomeV1):
            if self.output_size_bytes != 0 or self.output_sha256 is not None:
                raise ValueError("INSPECT completion has zero output bytes and no output hash")
        elif (
            self.outcome != "SANITIZED"
            or self.output_size_bytes is None
            or self.output_size_bytes <= 0
            or self.output_sha256 is None
        ):
            raise ValueError("SANITIZE completion requires SANITIZED and a positive bound output")
        return self

    def validate_for(self, request: InspectorLaunchRequestV1) -> None:
        if self.attempt_nonce != request.attempt_nonce:
            raise ProtocolViolation("result nonce does not match launch request")
        if self.result == "ACCEPTED":
            return
        if self.result == "FAILED":
            return
        if (
            self.canonical_input_digest != request.canonical_input_digest
            or self.inspector_build_digest != request.policy.parser_build_digest
        ):
            raise ProtocolViolation("completed result does not bind request input/build digest")
        if request.operation is InspectorOperation.INSPECT:
            if not isinstance(self.outcome, ArtifactInspectionOutcomeV1):
                raise ProtocolViolation("INSPECT completion requires typed inspection outcome")
            if (
                self.outcome.artifact_id != request.sealed_byte_binding.artifact_id
                or self.outcome.observed_sha256 != request.sealed_byte_binding.observed_sha256
            ):
                raise ProtocolViolation("inspection outcome does not bind sealed artifact")
        elif self.outcome != "SANITIZED":
            raise ProtocolViolation("SANITIZE completion requires SANITIZED outcome")

    def wire_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude_none=True)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.wire_dict())


class ProtocolLimitsV1(_FrozenProtocolModel):
    """All finite local UDS framing limits; no production values are supplied here."""

    max_header_bytes: StrictInt = Field(gt=0)
    max_chunk_bytes: StrictInt = Field(gt=0)
    max_input_bytes: StrictInt = Field(gt=0)
    max_output_bytes: StrictInt = Field(gt=0)
    max_wire_duration_millis: StrictInt = Field(gt=0)


class BoundByteReceiptV1(_FrozenProtocolModel):
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)


class ProtocolDeadline:
    """One absolute monotonic deadline shared by headers, chunks, terminal frame, and EOF."""

    def __init__(self, duration_millis: int, monotonic: Callable[[], float]) -> None:
        if type(duration_millis) is not int or duration_millis <= 0:
            raise ValueError("duration_millis must be a positive integer")
        self._monotonic = monotonic
        start = monotonic()
        if not math.isfinite(start):
            raise ValueError("monotonic clock must be finite")
        self._expires_at = start + duration_millis / 1_000

    @classmethod
    def at_expires_at(
        cls, expires_at: float, monotonic: Callable[[], float] = time.monotonic
    ) -> ProtocolDeadline:
        """Construct a view of an existing absolute deadline without resetting it."""
        if not isinstance(expires_at, (int, float)) or not math.isfinite(expires_at):
            raise ValueError("deadline expiry must be finite")
        instance = cls.__new__(cls)
        instance._monotonic = monotonic
        instance._expires_at = float(expires_at)
        instance.remaining()
        return instance

    def remaining(self) -> float:
        now = self._monotonic()
        if not math.isfinite(now):
            raise ProtocolDeadlineExceeded("monotonic clock became non-finite")
        remaining = self._expires_at - now
        if remaining <= 0:
            raise ProtocolDeadlineExceeded("global wire deadline exceeded")
        return remaining

    @property
    def expires_at(self) -> float:
        return self._expires_at

    def cap_duration_millis(self, duration_millis: int) -> None:
        """Only shorten this deadline from the current instant; never start a new clock."""
        if type(duration_millis) is not int or duration_millis <= 0:
            raise ValueError("duration_millis must be a positive integer")
        now = self._monotonic()
        if not math.isfinite(now):
            raise ProtocolDeadlineExceeded("monotonic clock became non-finite")
        self._expires_at = min(self._expires_at, now + duration_millis / 1_000)

    def cap_expires_at(self, expires_at: float) -> None:
        """Only shorten the existing absolute budget, including already elapsed work."""
        if type(expires_at) not in (int, float) or not math.isfinite(expires_at):
            raise ValueError("absolute deadline cap must be finite")
        self._expires_at = min(self._expires_at, float(expires_at))
        self.remaining()


@runtime_checkable
class DeadlineBoundedByteReaderPort(Protocol):
    """A byte reader that owns a cancellable read operation for every protocol chunk."""

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes: ...

    def close(self) -> None:
        """Release only resources owned by this reader without waiting for foreign work."""


@runtime_checkable
class DeadlineBoundedByteSinkPort(Protocol):
    """A byte sink that owns a cancellable write operation for every protocol chunk."""

    def write_chunk(
        self,
        chunk: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None: ...


class DeadlineBoundedBytesReader:
    """Concrete finite-memory reader retained for synthetic callers only."""

    def __init__(self, source: BytesIO) -> None:
        if type(source) is not BytesIO:
            raise TypeError("only the built-in BytesIO implementation is a finite-memory reader")
        self._source: BytesIO | None = source

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        _validate_bounded_chunk_operation(
            maximum_bytes, deadline, wait_is_current, heartbeat_interval_millis
        )
        source = self._source
        if source is None:
            raise ProtocolViolation("deadline-bounded source is closed")
        chunk = source.read(maximum_bytes)
        _finish_bounded_chunk_operation(deadline, wait_is_current)
        return chunk

    def close(self) -> None:
        source, self._source = self._source, None
        if source is not None:
            source.close()

    @property
    def is_closed(self) -> bool:
        return self._source is None


class DeadlineBoundedMemorySink:
    """Concrete finite-memory sink for tests and in-process bounded results."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write_chunk(
        self,
        chunk: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        if not isinstance(chunk, bytes):
            raise ProtocolViolation("deadline-bounded sink received non-bytes")
        _validate_bounded_chunk_operation(
            len(chunk), deadline, wait_is_current, heartbeat_interval_millis
        )
        self.chunks.append(chunk)
        _finish_bounded_chunk_operation(deadline, wait_is_current)


class DeadlineBoundedDiscardingSink:
    """Concrete no-op sink for framing paths that intentionally discard verified bytes."""

    def write_chunk(
        self,
        chunk: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        if not isinstance(chunk, bytes):
            raise ProtocolViolation("deadline-bounded sink received non-bytes")
        _validate_bounded_chunk_operation(
            len(chunk), deadline, wait_is_current, heartbeat_interval_millis
        )
        _finish_bounded_chunk_operation(deadline, wait_is_current)


class DeadlineBoundedSocketReader:
    """A resource-owning nonblocking socket reader with one caller-supplied deadline."""

    def __init__(self, connection: socket.socket) -> None:
        self._connection: socket.socket | None = connection
        connection.setblocking(False)

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise ProtocolViolation("deadline-bounded source maximum must be positive")
        connection = self._require_connection()
        while True:
            _wait_for_socket(
                connection,
                readable=True,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
                authority_message="authority lost while waiting for deadline-bounded source bytes",
            )
            try:
                chunk = connection.recv(maximum_bytes)
            except BlockingIOError:
                continue
            _finish_bounded_chunk_operation(deadline, wait_is_current)
            return chunk

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()

    def _require_connection(self) -> socket.socket:
        if self._connection is None:
            raise ProtocolViolation("deadline-bounded source is closed")
        return self._connection


class DeadlineBoundedSocketSink:
    """A resource-owning nonblocking socket sink with one caller-supplied deadline."""

    def __init__(self, connection: socket.socket) -> None:
        self._connection: socket.socket | None = connection
        connection.setblocking(False)

    def write_chunk(
        self,
        chunk: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        if not isinstance(chunk, bytes) or not chunk:
            raise ProtocolViolation("deadline-bounded sink requires non-empty bytes")
        connection = self._require_connection()
        remaining = memoryview(chunk)
        while remaining:
            _wait_for_socket(
                connection,
                readable=False,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
                authority_message="authority lost while waiting for deadline-bounded sink bytes",
            )
            try:
                written = connection.send(remaining)
            except BlockingIOError:
                continue
            if written <= 0:
                raise ProtocolViolation("deadline-bounded sink write made no progress")
            _finish_bounded_chunk_operation(deadline, wait_is_current)
            remaining = remaining[written:]

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()

    def _require_connection(self) -> socket.socket:
        if self._connection is None:
            raise ProtocolViolation("deadline-bounded sink is closed")
        return self._connection


def _validate_bounded_chunk_operation(
    maximum_bytes: int,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> None:
    if type(maximum_bytes) is not int or maximum_bytes < 0:
        raise ProtocolViolation("deadline-bounded chunk maximum is invalid")
    _validate_wait_guard(wait_is_current, heartbeat_interval_millis)
    _require_current_upload_authority(wait_is_current)
    deadline.remaining()


def _finish_bounded_chunk_operation(
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
) -> None:
    _require_current_upload_authority(wait_is_current)
    deadline.remaining()


def _wait_for_socket(
    connection: socket.socket,
    *,
    readable: bool,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
    authority_message: str,
) -> None:
    _validate_wait_guard(wait_is_current, heartbeat_interval_millis)
    while True:
        if wait_is_current is not None and not wait_is_current():
            raise ProtocolViolation(authority_message)
        timeout = deadline.remaining()
        if heartbeat_interval_millis is not None:
            timeout = min(timeout, heartbeat_interval_millis / 1_000)
        ready_read, ready_write, _ = select.select(
            [connection] if readable else [],
            [] if readable else [connection],
            [],
            timeout,
        )
        deadline.remaining()
        if wait_is_current is not None and not wait_is_current():
            raise ProtocolViolation(authority_message)
        if ready_read or ready_write:
            return


def _require_deadline_bounded_reader(
    source: DeadlineBoundedByteReaderPort | BytesIO,
) -> DeadlineBoundedByteReaderPort:
    if type(source) is BytesIO:
        return DeadlineBoundedBytesReader(source)
    if not isinstance(source, DeadlineBoundedByteReaderPort):
        raise ProtocolViolation("source must provide deadline-bounded reads")
    return source


def _require_deadline_bounded_sink(sink: DeadlineBoundedByteSinkPort) -> None:
    if not isinstance(sink, DeadlineBoundedByteSinkPort):
        raise ProtocolViolation("sink must provide deadline-bounded writes")


def _sha256_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _deadline(
    limits: ProtocolLimitsV1,
    deadline: ProtocolDeadline | None,
    monotonic: Callable[[], float],
) -> ProtocolDeadline:
    return deadline or ProtocolDeadline(limits.max_wire_duration_millis, monotonic)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolViolation("duplicate JSON object key")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> None:
    raise ProtocolViolation("non-finite JSON value is forbidden")


def _reject_nonfinite_numbers(value: Any) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolViolation("non-finite JSON value is forbidden")
        return
    if isinstance(value, dict):
        for nested in value.values():
            _reject_nonfinite_numbers(nested)
        return
    if isinstance(value, list):
        for nested in value:
            _reject_nonfinite_numbers(nested)


def decode_json_frame(payload: bytes, limits: ProtocolLimitsV1) -> dict[str, Any]:
    """Decode a bounded JSON object without duplicate keys or nonfinite literals."""
    if len(payload) > limits.max_header_bytes:
        raise ProtocolViolation("JSON frame exceeds configured header cap")
    try:
        parsed = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("invalid UTF-8 JSON frame") from exc
    if not isinstance(parsed, dict):
        raise ProtocolViolation("JSON frame must be an object")
    _reject_nonfinite_numbers(parsed)
    return parsed


def _recv_exact(
    connection: socket.socket,
    size: int,
    limits: ProtocolLimitsV1,
    deadline: ProtocolDeadline,
    *,
    eof_message: str,
    wait_is_current: Callable[[], bool] | None = None,
    heartbeat_interval_millis: int | None = None,
) -> bytes:
    if size < 0:
        raise ProtocolViolation("negative wire size")
    chunks: list[bytes] = []
    remaining = size
    if wait_is_current is not None and (
        type(heartbeat_interval_millis) is not int or heartbeat_interval_millis <= 0
    ):
        raise ValueError("heartbeat_interval_millis must be positive when a wait guard is supplied")
    while remaining:
        try:
            if wait_is_current is not None and not wait_is_current():
                raise ProtocolViolation("authority lost while waiting for UDS frame")
            timeout = deadline.remaining()
            if heartbeat_interval_millis is not None:
                timeout = min(timeout, heartbeat_interval_millis / 1_000)
            connection.settimeout(timeout)
            chunk = connection.recv(min(remaining, limits.max_chunk_bytes))
        except TimeoutError as exc:
            if wait_is_current is not None:
                if not wait_is_current():
                    raise ProtocolViolation("authority lost while waiting for UDS frame") from exc
                continue
            raise ProtocolDeadlineExceeded("global wire deadline exceeded") from exc
        deadline.remaining()
        if not chunk:
            raise ProtocolViolation(eof_message)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_frame_payload(
    connection: socket.socket,
    limits: ProtocolLimitsV1,
    deadline: ProtocolDeadline,
    *,
    wait_is_current: Callable[[], bool] | None = None,
    heartbeat_interval_millis: int | None = None,
) -> bytes:
    prefix = _recv_exact(
        connection,
        4,
        limits,
        deadline,
        eof_message="unexpected EOF before frame length",
        wait_is_current=wait_is_current,
        heartbeat_interval_millis=heartbeat_interval_millis,
    )
    size = struct.unpack(">I", prefix)[0]
    if size == 0 or size > limits.max_header_bytes:
        raise ProtocolViolation("frame length exceeds configured header cap")
    return _recv_exact(
        connection,
        size,
        limits,
        deadline,
        eof_message="unexpected EOF in JSON frame",
        wait_is_current=wait_is_current,
        heartbeat_interval_millis=heartbeat_interval_millis,
    )


def _validate_wait_guard(
    wait_is_current: Callable[[], bool] | None, heartbeat_interval_millis: int | None
) -> None:
    if wait_is_current is not None and (
        type(heartbeat_interval_millis) is not int or heartbeat_interval_millis <= 0
    ):
        raise ValueError("heartbeat_interval_millis must be positive when a wait guard is supplied")


def _require_current_upload_authority(wait_is_current: Callable[[], bool] | None) -> None:
    if wait_is_current is not None and not wait_is_current():
        raise ProtocolViolation("authority lost while uploading UDS launch request")


def _validate_launch_result_wire_shape(raw: dict[str, Any]) -> None:
    base = {"protocolVersion", "result", "attemptNonce"}
    result = raw.get("result")
    if result == "ACCEPTED":
        expected = base
    elif result == "FAILED":
        expected = base | {"reason"}
    elif result == "COMPLETED":
        expected = base | {
            "canonicalInputDigest",
            "inspectorBuildDigest",
            "outcome",
            "outputSizeBytes",
        }
        if raw.get("outcome") == "SANITIZED":
            expected.add("outputSha256")
    else:
        return
    if set(raw) != expected:
        raise ProtocolViolation("launch result frame does not have an exact variant key set")


def _write_all(
    connection: socket.socket,
    payload: bytes,
    deadline: ProtocolDeadline,
    *,
    wait_is_current: Callable[[], bool] | None = None,
    heartbeat_interval_millis: int | None = None,
) -> None:
    _validate_wait_guard(wait_is_current, heartbeat_interval_millis)
    remaining = memoryview(payload)
    while remaining:
        _require_current_upload_authority(wait_is_current)
        try:
            timeout = deadline.remaining()
            if heartbeat_interval_millis is not None:
                timeout = min(timeout, heartbeat_interval_millis / 1_000)
            connection.settimeout(timeout)
            sent = connection.send(remaining)
        except TimeoutError as exc:
            if wait_is_current is not None:
                _require_current_upload_authority(wait_is_current)
                continue
            raise ProtocolDeadlineExceeded("global wire deadline exceeded") from exc
        if sent <= 0:
            raise ProtocolViolation("UDS launch request write made no progress")
        deadline.remaining()
        remaining = remaining[sent:]


def _write_frame(
    connection: socket.socket,
    payload: bytes,
    limits: ProtocolLimitsV1,
    deadline: ProtocolDeadline,
    *,
    wait_is_current: Callable[[], bool] | None = None,
    heartbeat_interval_millis: int | None = None,
) -> None:
    if not payload or len(payload) > limits.max_header_bytes:
        raise ProtocolViolation("frame exceeds configured header cap")
    _write_all(
        connection,
        struct.pack(">I", len(payload)) + payload,
        deadline,
        wait_is_current=wait_is_current,
        heartbeat_interval_millis=heartbeat_interval_millis,
    )


def read_launch_request_header(
    connection: socket.socket,
    limits: ProtocolLimitsV1,
    *,
    deadline: ProtocolDeadline | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> InspectorLaunchRequestV1:
    active_deadline = _deadline(limits, deadline, monotonic)
    raw = decode_json_frame(_read_frame_payload(connection, limits, active_deadline), limits)
    try:
        return InspectorLaunchRequestV1.model_validate(raw)
    except Exception as exc:
        raise ProtocolViolation("invalid launch request header") from exc


def read_launch_result(
    connection: socket.socket,
    limits: ProtocolLimitsV1,
    *,
    deadline: ProtocolDeadline | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wait_is_current: Callable[[], bool] | None = None,
    heartbeat_interval_millis: int | None = None,
) -> InspectorLaunchResultV1:
    active_deadline = _deadline(limits, deadline, monotonic)
    raw = decode_json_frame(
        _read_frame_payload(
            connection,
            limits,
            active_deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        ),
        limits,
    )
    _validate_launch_result_wire_shape(raw)
    try:
        return InspectorLaunchResultV1.model_validate(raw)
    except Exception as exc:
        raise ProtocolViolation("invalid launch result frame") from exc


def read_bound_bytes(
    connection: socket.socket,
    binding: SealedByteBindingV1,
    limits: ProtocolLimitsV1,
    sink: DeadlineBoundedByteSinkPort,
    *,
    maximum_bytes: int | None = None,
    deadline: ProtocolDeadline | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wait_is_current: Callable[[], bool] | None = None,
    heartbeat_interval_millis: int | None = None,
) -> BoundByteReceiptV1:
    """Stream one exact raw payload, then require peer EOF without resetting the deadline."""
    active_deadline = _deadline(limits, deadline, monotonic)
    _require_deadline_bounded_sink(sink)
    cap = limits.max_input_bytes if maximum_bytes is None else maximum_bytes
    if type(cap) is not int or cap <= 0 or binding.observed_size_bytes > cap:
        raise ProtocolViolation("input bytes exceed configured admission cap")
    if wait_is_current is not None and (
        type(heartbeat_interval_millis) is not int or heartbeat_interval_millis <= 0
    ):
        raise ValueError("heartbeat_interval_millis must be positive when a wait guard is supplied")
    digest = hashlib.sha256()
    remaining = binding.observed_size_bytes
    while remaining:
        try:
            if wait_is_current is not None and not wait_is_current():
                raise ProtocolViolation("authority lost while waiting for bound raw bytes")
            timeout = active_deadline.remaining()
            if heartbeat_interval_millis is not None:
                timeout = min(timeout, heartbeat_interval_millis / 1_000)
            connection.settimeout(timeout)
            chunk = connection.recv(min(remaining, limits.max_chunk_bytes))
        except TimeoutError as exc:
            if wait_is_current is not None:
                if not wait_is_current():
                    raise ProtocolViolation(
                        "authority lost while waiting for bound raw bytes"
                    ) from exc
                continue
            raise ProtocolDeadlineExceeded("global wire deadline exceeded") from exc
        active_deadline.remaining()
        if not chunk:
            raise ProtocolViolation("unexpected EOF in bound raw input")
        digest.update(chunk)
        sink.write_chunk(
            chunk,
            deadline=active_deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        remaining -= len(chunk)
    while True:
        try:
            if wait_is_current is not None and not wait_is_current():
                raise ProtocolViolation("authority lost while waiting for bound raw EOF")
            timeout = active_deadline.remaining()
            if heartbeat_interval_millis is not None:
                timeout = min(timeout, heartbeat_interval_millis / 1_000)
            connection.settimeout(timeout)
            trailing = connection.recv(1)
        except TimeoutError as exc:
            if wait_is_current is not None:
                if not wait_is_current():
                    raise ProtocolViolation(
                        "authority lost while waiting for bound raw EOF"
                    ) from exc
                continue
            raise ProtocolDeadlineExceeded("global wire deadline exceeded") from exc
        active_deadline.remaining()
        if trailing:
            raise ProtocolViolation("trailing bytes after bound raw input")
        break
    observed_sha256 = "sha256:" + digest.hexdigest()
    if observed_sha256 != binding.observed_sha256:
        raise ProtocolViolation("bound raw input SHA-256 mismatch")
    return BoundByteReceiptV1(
        observed_sha256=observed_sha256, observed_size_bytes=binding.observed_size_bytes
    )


def _require_eof(
    connection: socket.socket,
    limits: ProtocolLimitsV1,
    deadline: ProtocolDeadline,
    *,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> None:
    if wait_is_current is not None and (
        type(heartbeat_interval_millis) is not int or heartbeat_interval_millis <= 0
    ):
        raise ValueError("heartbeat_interval_millis must be positive when a wait guard is supplied")
    while True:
        try:
            if wait_is_current is not None and not wait_is_current():
                raise ProtocolViolation("authority lost while waiting for UDS EOF")
            timeout = deadline.remaining()
            if heartbeat_interval_millis is not None:
                timeout = min(timeout, heartbeat_interval_millis / 1_000)
            connection.settimeout(timeout)
            trailing = connection.recv(min(1, limits.max_chunk_bytes))
        except TimeoutError as exc:
            if wait_is_current is not None:
                if not wait_is_current():
                    raise ProtocolViolation("authority lost while waiting for UDS EOF") from exc
                continue
            raise ProtocolDeadlineExceeded("global wire deadline exceeded") from exc
        deadline.remaining()
        if trailing:
            raise ProtocolViolation("trailing bytes after terminal result")
        return


def read_completed_output(
    connection: socket.socket,
    result: InspectorLaunchResultV1,
    limits: ProtocolLimitsV1,
    sink: DeadlineBoundedByteSinkPort,
    *,
    deadline: ProtocolDeadline | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wait_is_current: Callable[[], bool] | None = None,
    heartbeat_interval_millis: int | None = None,
) -> BoundByteReceiptV1 | None:
    """Consume only the terminal result's exact sanitized bytes and then EOF.

    The synthetic artifact id below remains local to byte framing; it is never
    a second artifact identity or a UDS field.
    """
    active_deadline = _deadline(limits, deadline, monotonic)
    if result.result != "COMPLETED" or result.output_size_bytes is None:
        raise ProtocolViolation("terminal output requires a completed result")
    if result.output_size_bytes == 0:
        _require_eof(
            connection,
            limits,
            active_deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        return None
    if result.output_sha256 is None:
        raise ProtocolViolation("positive terminal output requires a SHA-256 binding")
    return read_bound_bytes(
        connection,
        SealedByteBindingV1(
            artifact_id="sanitized-output",
            observed_sha256=result.output_sha256,
            observed_size_bytes=result.output_size_bytes,
        ),
        limits,
        sink,
        maximum_bytes=limits.max_output_bytes,
        deadline=active_deadline,
        monotonic=monotonic,
        wait_is_current=wait_is_current,
        heartbeat_interval_millis=heartbeat_interval_millis,
    )


def write_launch_request(
    connection: socket.socket,
    request: InspectorLaunchRequestV1,
    source: DeadlineBoundedByteReaderPort | BytesIO,
    limits: ProtocolLimitsV1,
    *,
    deadline: ProtocolDeadline | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wait_is_current: Callable[[], bool] | None = None,
    heartbeat_interval_millis: int | None = None,
) -> None:
    """Write header plus one hash-bound byte stream, then half-close the sender direction."""
    active_deadline = _deadline(limits, deadline, monotonic)
    _validate_wait_guard(wait_is_current, heartbeat_interval_millis)
    bounded_source = _require_deadline_bounded_reader(source)
    if request.sealed_byte_binding.observed_size_bytes > limits.max_input_bytes:
        raise ProtocolViolation("request input exceeds configured client framing cap")
    _write_frame(
        connection,
        request.canonical_bytes(),
        limits,
        active_deadline,
        wait_is_current=wait_is_current,
        heartbeat_interval_millis=heartbeat_interval_millis,
    )
    remaining = request.sealed_byte_binding.observed_size_bytes
    digest = hashlib.sha256()
    while remaining:
        _require_current_upload_authority(wait_is_current)
        active_deadline.remaining()
        chunk = bounded_source.read_chunk(
            min(remaining, limits.max_chunk_bytes),
            deadline=active_deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        _require_current_upload_authority(wait_is_current)
        active_deadline.remaining()
        if not isinstance(chunk, bytes) or not chunk:
            raise ProtocolViolation("source ended before sealed byte binding")
        if len(chunk) > remaining:
            raise ProtocolViolation("source exceeded sealed byte binding")
        digest.update(chunk)
        _write_all(
            connection,
            chunk,
            active_deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        remaining -= len(chunk)
    _require_current_upload_authority(wait_is_current)
    active_deadline.remaining()
    if bounded_source.read_chunk(
        1,
        deadline=active_deadline,
        wait_is_current=wait_is_current,
        heartbeat_interval_millis=heartbeat_interval_millis,
    ):
        raise ProtocolViolation("source has trailing bytes beyond sealed byte binding")
    _require_current_upload_authority(wait_is_current)
    active_deadline.remaining()
    if "sha256:" + digest.hexdigest() != request.sealed_byte_binding.observed_sha256:
        raise ProtocolViolation("source SHA-256 does not match sealed byte binding")
    _require_current_upload_authority(wait_is_current)
    active_deadline.remaining()
    connection.shutdown(socket.SHUT_WR)


def write_launch_result(
    connection: socket.socket,
    result: InspectorLaunchResultV1,
    limits: ProtocolLimitsV1,
    *,
    deadline: ProtocolDeadline | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    active_deadline = _deadline(limits, deadline, monotonic)
    _write_frame(connection, result.canonical_bytes(), limits, active_deadline)


__all__ = [
    "BoundByteReceiptV1",
    "DeadlineBoundedByteReaderPort",
    "DeadlineBoundedByteSinkPort",
    "DeadlineBoundedBytesReader",
    "DeadlineBoundedDiscardingSink",
    "DeadlineBoundedMemorySink",
    "DeadlineBoundedSocketReader",
    "DeadlineBoundedSocketSink",
    "InspectorLaunchRequestV1",
    "InspectorLaunchResultV1",
    "InspectorFailureReason",
    "InspectorOperation",
    "LocalLeaseFenceV1",
    "ProtocolDeadline",
    "ProtocolDeadlineExceeded",
    "ProtocolLimitsV1",
    "ProtocolViolation",
    "SealedByteBindingV1",
    "decode_json_frame",
    "read_bound_bytes",
    "read_completed_output",
    "read_launch_request_header",
    "read_launch_result",
    "write_launch_request",
    "write_launch_result",
]
