"""Opaque V2 UDS transport: two exact inputs, one deadline, terminal input EOF."""

from __future__ import annotations

import hashlib
import socket
import time
from collections.abc import Callable
from io import BytesIO
from threading import Lock

from ksi_processing_controller.external_inspector_protocol import (
    BoundByteReceiptV1,
    DeadlineBoundedByteReaderPort,
    DeadlineBoundedByteSinkPort,
    ProtocolDeadline,
    ProtocolLimitsV1,
    ProtocolViolation,
    _read_frame_payload,
    _recv_exact,
    _require_current_upload_authority,
    _require_deadline_bounded_reader,
    _require_deadline_bounded_sink,
    _require_eof,
    _validate_wait_guard,
    _write_all,
    _write_frame,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementLaunchRequestV2,
    decode_measurement_header,
)


class MeasurementRequestReceiverV2:
    """Connection-scoped header -> primary -> secondary/EOF grammar.

    The launcher may stage primary and start the runtime between input reads.
    That time consumes this same receiver-owned deadline. Failed or out-of-order
    operations poison the transaction; no method can reset its phase or budget.
    Secondary bytes are streamed to the supplied bounded runtime sink, never a
    second host staging allocation here.
    """

    def __init__(
        self,
        connection: socket.socket,
        limits: ProtocolLimitsV1,
        *,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        _validate_wait_guard(wait_is_current, heartbeat_interval_millis)
        self._limits = ProtocolLimitsV1.model_validate(limits.__dict__)
        self._deadline = ProtocolDeadline(self._limits.max_wire_duration_millis, monotonic)
        self._origin_monotonic = (
            self._deadline.expires_at - self._limits.max_wire_duration_millis / 1000
        )
        self._connection = connection
        self._wait_is_current = wait_is_current
        self._heartbeat_interval_millis = heartbeat_interval_millis
        self._request: MeasurementLaunchRequestV2 | None = None
        self._phase = "HEADER"
        self._lock = Lock()

    @property
    def deadline(self) -> ProtocolDeadline:
        """The same budget is passed to staging/runtime work between reads."""
        return self._deadline

    @property
    def complete(self) -> bool:
        with self._lock:
            return self._phase == "COMPLETE"

    def restrict_total_duration_millis(self, duration_millis: int) -> None:
        """Apply an admitted signed ceiling from the original pre-header origin."""
        if type(duration_millis) is not int or duration_millis <= 0:
            raise ValueError("total measurement duration must be a positive integer")
        self._deadline.cap_expires_at(self._origin_monotonic + duration_millis / 1000)

    def _begin(self, expected: str) -> None:
        with self._lock:
            if self._phase != expected:
                self._phase = "FAILED"
                raise ProtocolViolation("measurement receive sequence differs")
            self._phase = "READING"

    def _finish(self, next_phase: str) -> None:
        _require_current_upload_authority(self._wait_is_current)
        self._deadline.remaining()
        with self._lock:
            if self._phase != "READING":
                self._phase = "FAILED"
                raise ProtocolViolation("measurement receive sequence was interrupted")
            self._phase = next_phase

    def _fail(self) -> None:
        with self._lock:
            self._phase = "FAILED"

    def read_header(self) -> MeasurementLaunchRequestV2:
        self._begin("HEADER")
        try:
            self._request = _read_measurement_request_header(
                self._connection,
                self._limits,
                deadline=self._deadline,
                wait_is_current=self._wait_is_current,
                heartbeat_interval_millis=self._heartbeat_interval_millis,
            )
            self._finish("PRIMARY")
            return self._request
        except BaseException:
            self._fail()
            raise

    def read_primary(self, sink: DeadlineBoundedByteSinkPort) -> BoundByteReceiptV1:
        return self._read_input(sink, index=0, expected="PRIMARY", next_phase="SECONDARY")

    def read_secondary(self, sink: DeadlineBoundedByteSinkPort) -> BoundByteReceiptV1:
        return self._read_input(sink, index=1, expected="SECONDARY", next_phase="COMPLETE")

    def _read_input(
        self, sink: DeadlineBoundedByteSinkPort, *, index: int, expected: str, next_phase: str
    ) -> BoundByteReceiptV1:
        self._begin(expected)
        try:
            assert self._request is not None
            receipt = _read_measurement_input(
                self._connection,
                self._request,
                index,
                self._limits,
                sink,
                deadline=self._deadline,
                wait_is_current=self._wait_is_current,
                heartbeat_interval_millis=self._heartbeat_interval_millis,
            )
            self._finish(next_phase)
            return receipt
        except BaseException:
            self._fail()
            raise


def _read_measurement_request_header(
    connection: socket.socket,
    limits: ProtocolLimitsV1,
    *,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool],
    heartbeat_interval_millis: int,
) -> MeasurementLaunchRequestV2:
    payload = _read_frame_payload(
        connection,
        limits,
        deadline,
        wait_is_current=wait_is_current,
        heartbeat_interval_millis=heartbeat_interval_millis,
    )
    return decode_measurement_header(payload, limits)


def _validate_request(request: MeasurementLaunchRequestV2, limits: ProtocolLimitsV1) -> None:
    if request.combined_input_bytes > limits.max_input_bytes:
        raise ProtocolViolation("combined measurement input exceeds local ceiling")
    request.canonical_bytes()  # revalidate sealed nested authority before consuming any bytes


def _read_measurement_input(
    connection: socket.socket,
    request: MeasurementLaunchRequestV2,
    index: int,
    limits: ProtocolLimitsV1,
    sink: DeadlineBoundedByteSinkPort,
    *,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool],
    heartbeat_interval_millis: int,
) -> BoundByteReceiptV1:
    """Read the launcher-selected input; only secondary completion requires outer EOF."""
    _validate_request(request, limits)
    _validate_wait_guard(wait_is_current, heartbeat_interval_millis)
    _require_deadline_bounded_sink(sink)
    if type(index) is not int or index not in (0, 1):
        raise ProtocolViolation("measurement input index must be primary or secondary")
    binding = request.inputs[index]
    remaining = binding.observed_size_bytes
    digest = hashlib.sha256()
    while remaining:
        chunk = _recv_exact(
            connection,
            min(remaining, limits.max_chunk_bytes),
            limits,
            deadline,
            eof_message="unexpected EOF in ordered measurement input",
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        _require_current_upload_authority(wait_is_current)
        deadline.remaining()
        sink.write_chunk(
            chunk,
            deadline=deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        _require_current_upload_authority(wait_is_current)
        deadline.remaining()
        remaining -= len(chunk)
        digest.update(chunk)
    observed = "sha256:" + digest.hexdigest()
    if observed != binding.observed_sha256:
        raise ProtocolViolation("ordered measurement input SHA-256 differs")
    if index == 1:
        _require_eof(
            connection,
            limits,
            deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
    return BoundByteReceiptV1(
        observed_sha256=observed, observed_size_bytes=binding.observed_size_bytes
    )


def write_measurement_request(
    connection: socket.socket,
    request: MeasurementLaunchRequestV2,
    sources: tuple[
        DeadlineBoundedByteReaderPort | BytesIO, DeadlineBoundedByteReaderPort | BytesIO
    ],
    limits: ProtocolLimitsV1,
    *,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool],
    heartbeat_interval_millis: int,
) -> None:
    """Stream independent source EOFs and exact hashes, then half-close the UDS."""
    _validate_request(request, limits)
    _validate_wait_guard(wait_is_current, heartbeat_interval_millis)
    if len(sources) != 2:
        raise ProtocolViolation("exactly two ordered measurement sources required")
    readers = tuple(_require_deadline_bounded_reader(source) for source in sources)
    _write_frame(
        connection,
        request.canonical_bytes(),
        limits,
        deadline,
        wait_is_current=wait_is_current,
        heartbeat_interval_millis=heartbeat_interval_millis,
    )
    for binding, source in zip(request.inputs, readers, strict=True):
        remaining = binding.observed_size_bytes
        digest = hashlib.sha256()
        while remaining:
            _require_current_upload_authority(wait_is_current)
            deadline.remaining()
            maximum = min(remaining, limits.max_chunk_bytes)
            chunk = source.read_chunk(
                maximum,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            _require_current_upload_authority(wait_is_current)
            deadline.remaining()
            if not isinstance(chunk, bytes) or not chunk or len(chunk) > maximum:
                raise ProtocolViolation("measurement source violated its exact chunk bound")
            _write_all(
                connection,
                chunk,
                deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            remaining -= len(chunk)
            digest.update(chunk)
        trailing = source.read_chunk(
            1,
            deadline=deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        _require_current_upload_authority(wait_is_current)
        deadline.remaining()
        if not isinstance(trailing, bytes) or trailing:
            raise ProtocolViolation("measurement source has invalid EOF or trailing bytes")
        if "sha256:" + digest.hexdigest() != binding.observed_sha256:
            raise ProtocolViolation("measurement source SHA-256 differs")
    _require_current_upload_authority(wait_is_current)
    deadline.remaining()
    connection.shutdown(socket.SHUT_WR)
