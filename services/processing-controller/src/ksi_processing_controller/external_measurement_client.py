"""Fixed local UDS connector and aggregate-only V2 client, with one total budget.

The provisioned socket pathname is operator configuration. No listener, directory,
identity or permission is created here. Input-reader ownership stays with caller.
"""

from __future__ import annotations

import errno
import select
import socket
import stat
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1

from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteReaderPort,
    ProtocolDeadline,
    ProtocolLimitsV1,
    ProtocolViolation,
    _read_frame_payload,
    _require_eof,
    _validate_wait_guard,
)
from ksi_processing_controller.external_measurement_protocol import MeasurementLaunchRequestV2
from ksi_processing_controller.external_measurement_result import (
    MeasurementResultV2,
    decode_measurement_result,
)
from ksi_processing_controller.external_measurement_transport import write_measurement_request


@dataclass(frozen=True, slots=True)
class MeasurementSocketIdentityV2:
    path: Path
    owner_uid: int
    owner_gid: int
    mode: int
    launcher_uid: int

    def __post_init__(self) -> None:
        if (
            not self.path.is_absolute()
            or ".." in self.path.parts
            or len(str(self.path).encode()) > 107
        ):
            raise ValueError("fixed absolute UDS path required")
        if (
            any(
                type(v) is not int or v < 0
                for v in (self.owner_uid, self.owner_gid, self.launcher_uid)
            )
            or type(self.mode) is not int
            or self.mode not in {0o600, 0o660}
        ):
            raise ValueError("fixed private socket ownership required")


class MeasurementConnectorPort(Protocol):
    def connect(
        self,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> socket.socket: ...


class FixedMeasurementUdsConnector:
    def __init__(self, identity: MeasurementSocketIdentityV2) -> None:
        self._identity = identity

    def _socket_identity(self) -> tuple[int, int]:
        try:
            observed = self._identity.path.lstat()
            if (
                not stat.S_ISSOCK(observed.st_mode)
                or stat.S_IMODE(observed.st_mode) != self._identity.mode
                or observed.st_uid != self._identity.owner_uid
                or observed.st_gid != self._identity.owner_gid
            ):
                raise ProtocolViolation("measurement socket identity differs")
            return observed.st_dev, observed.st_ino
        except OSError as exc:
            raise ProtocolViolation("measurement socket unavailable") from exc

    def connect(
        self,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> socket.socket:
        _validate_wait_guard(wait_is_current, heartbeat_interval_millis)

        def guard() -> float:
            if wait_is_current() is not True:
                raise ProtocolViolation("measurement authority lost")
            return min(deadline.remaining(), heartbeat_interval_millis / 1000)

        guard()
        before = self._socket_identity()
        guard()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.setblocking(False)
            while True:
                delay = guard()
                code = connection.connect_ex(str(self._identity.path))
                if code in {0, errno.EISCONN}:
                    break
                if code in {errno.EAGAIN, errno.EWOULDBLOCK}:
                    select.select([], [], [], delay)
                    continue
                if code not in {errno.EINPROGRESS, errno.EALREADY, errno.EINTR}:
                    raise ProtocolViolation("measurement connection unavailable")
                _, ready, errors = select.select([], [connection], [connection], delay)
                guard()
                if errors:
                    raise ProtocolViolation("measurement connection failed")
                if ready:
                    if connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
                        raise ProtocolViolation("measurement connection failed")
                    connection.getpeername()
                    break
            guard()
            credentials = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            if (
                struct.unpack("3i", credentials)[1] != self._identity.launcher_uid
                or self._socket_identity() != before
            ):
                raise ProtocolViolation("measurement peer identity differs")
            guard()
            return connection
        except Exception as exc:
            connection.close()
            if isinstance(exc, ProtocolViolation):
                raise
            raise ProtocolViolation("measurement connection unavailable") from exc


class ExternalMeasurementUdsClient:
    def __init__(
        self,
        *,
        connector: MeasurementConnectorPort,
        protocol_limits: ProtocolLimitsV1,
        heartbeat_interval_millis: int,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        _validate_wait_guard(lambda: True, heartbeat_interval_millis)
        self._connector = connector
        self._limits = ProtocolLimitsV1.model_validate(protocol_limits.__dict__)
        self._heartbeat = heartbeat_interval_millis
        self._monotonic = monotonic

    def execute(
        self,
        *,
        request: MeasurementLaunchRequestV2,
        manifest: InspectorExecutionManifestV1,
        sources: tuple[DeadlineBoundedByteReaderPort, DeadlineBoundedByteReaderPort],
        deadline_monotonic: float,
        authority_is_current: Callable[[], bool],
    ) -> MeasurementResultV2:
        def current() -> bool:
            return authority_is_current() is True

        request.canonical_bytes()
        deadline = ProtocolDeadline(self._limits.max_wire_duration_millis, self._monotonic)
        deadline.cap_expires_at(deadline_monotonic)
        if authority_is_current() is not True:
            raise ProtocolViolation("measurement authority lost")
        connection = self._connector.connect(
            deadline=deadline,
            wait_is_current=current,
            heartbeat_interval_millis=self._heartbeat,
        )
        try:
            write_measurement_request(
                connection,
                request,
                sources,
                self._limits,
                deadline=deadline,
                wait_is_current=current,
                heartbeat_interval_millis=self._heartbeat,
            )
            payload = _read_frame_payload(
                connection,
                self._limits,
                deadline,
                wait_is_current=current,
                heartbeat_interval_millis=self._heartbeat,
            )
            result = decode_measurement_result(
                payload, request=request, manifest=manifest, limits=self._limits
            )
            _require_eof(
                connection,
                self._limits,
                deadline,
                wait_is_current=current,
                heartbeat_interval_millis=self._heartbeat,
            )
            deadline.remaining()
            if authority_is_current() is not True:
                raise ProtocolViolation("measurement authority lost")
            return result
        except (OSError, ValueError) as exc:
            raise ProtocolViolation("measurement exchange unavailable") from exc
        finally:
            connection.close()
