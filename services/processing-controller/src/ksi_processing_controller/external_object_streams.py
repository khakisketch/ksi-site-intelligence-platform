"""Bounded raw HTTP object bytes for an already-authorized external artifact.

The module deliberately owns only object-storage wire I/O.  It neither obtains
Core authority nor starts a worker.  Callers provide an immutable capability
tuple and an operator-validated hostname-to-address mapping; no request path
performs DNS, proxy discovery, cookie handling, or redirect following.
"""

from __future__ import annotations

import errno
import hashlib
import ipaddress
import re
import select
import socket
import ssl
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from urllib.parse import SplitResult, urlsplit

from ksi_processing_controller.external_artifact_inspection_worker import (
    ExternalArtifactByteSourcePort,
    ExternalArtifactInputV1,
)
from ksi_processing_controller.external_inspector_protocol import (
    BoundByteReceiptV1,
    DeadlineBoundedByteReaderPort,
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_protocol import MeasurementInputV2

# Closed identities retain their domain: an inspection artifact or a V2 role.
ExternalObjectInputV1 = ExternalArtifactInputV1 | MeasurementInputV2


def _validated_object_input(value: object) -> ExternalObjectInputV1:
    if isinstance(value, ExternalArtifactInputV1):
        return ExternalArtifactInputV1.model_validate(value.__dict__)
    if isinstance(value, MeasurementInputV2):
        return MeasurementInputV2.model_validate(value.__dict__)
    raise ValueError("object input must be a closed inspection or measurement identity")


_MAX_URL_BYTES = 16_384
_MAX_REQUIRED_HEADERS = 32
_MAX_REQUIRED_HEADER_VALUE_BYTES = 8_192
_HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}\Z")
_FORBIDDEN_CAPABILITY_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "host",
        "connection",
        "content-length",
        "content-encoding",
        "transfer-encoding",
    }
)
_CONNECT_PENDING = frozenset({errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EINTR})


class ExternalObjectTransportError(ProtocolViolation):
    """A safe, bounded transport failure code without endpoint or secret detail."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@runtime_checkable
class ExternalObjectCapabilityPort(Protocol):
    """The exact private capability shape accepted from a Core-facing adapter."""

    artifact: ExternalObjectInputV1
    required_headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ExternalObjectCapabilityV1:
    """Capability tuple only; its URL and headers are never represented in receipts."""

    artifact: ExternalObjectInputV1
    url: str = field(repr=False)
    required_headers: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _validated_object_input(self.artifact))
        _parse_object_url(self.url)
        object.__setattr__(self, "required_headers", MappingProxyType(dict(self.required_headers)))
        _validate_required_headers(self.required_headers)


@dataclass(frozen=True, slots=True)
class TrustedObjectEndpointV1:
    """Operator-validated origin and finite dial addresses, with no runtime resolver."""

    origin: str
    addresses: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed = _parse_object_url(self.origin)
        if parsed.path not in {"", "/"} or parsed.query:
            raise ValueError("trusted origin cannot contain path or query")
        if not isinstance(self.addresses, tuple) or not self.addresses:
            raise ValueError("trusted endpoint requires one or more static addresses")
        normalized: list[str] = []
        for address in self.addresses:
            if not isinstance(address, str):
                raise ValueError("trusted endpoint address must be text")
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as exc:
                raise ValueError("trusted endpoint address must be an IP literal") from exc
            if str(parsed_address) not in normalized:
                normalized.append(str(parsed_address))
        if parsed.scheme == "http":
            try:
                origin_address = ipaddress.ip_address(parsed.hostname or "")
            except ValueError as exc:
                raise ValueError(
                    "insecure HTTP requires an explicit loopback origin literal"
                ) from exc
            if not origin_address.is_loopback or any(
                not ipaddress.ip_address(address).is_loopback for address in normalized
            ):
                raise ValueError(
                    "insecure HTTP is permitted only for an explicit loopback endpoint"
                )
        object.__setattr__(self, "addresses", tuple(normalized))
        object.__setattr__(self, "origin", _origin_key(parsed))


@dataclass(frozen=True, slots=True)
class ExternalObjectTransportPolicyV1:
    """Finite wire limits plus the sole operator-owned network allow-list."""

    endpoints: tuple[TrustedObjectEndpointV1, ...]
    max_header_bytes: int
    max_object_bytes: int
    max_chunk_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.endpoints, tuple) or not self.endpoints:
            raise ValueError("object transport policy requires trusted endpoints")
        if len({endpoint.origin for endpoint in self.endpoints}) != len(self.endpoints):
            raise ValueError("trusted object origins must be unique")
        for value in (self.max_header_bytes, self.max_object_bytes, self.max_chunk_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError("object transport limits must be positive integers")
        if self.max_chunk_bytes > self.max_object_bytes:
            raise ValueError("object chunk cap cannot exceed object cap")

    def target_for(self, url: str) -> _ObjectTarget:
        parsed = _parse_object_url(url)
        origin = _origin_key(parsed)
        matching = tuple(endpoint for endpoint in self.endpoints if endpoint.origin == origin)
        if len(matching) != 1:
            raise ExternalObjectTransportError("ORIGIN_NOT_ALLOWED")
        endpoint = matching[0]
        return _ObjectTarget(
            parsed=parsed,
            hostname=parsed.hostname or "",
            port=_url_port(parsed),
            addresses=endpoint.addresses,
        )


@dataclass(frozen=True, slots=True)
class SealedObjectByteSourceV1:
    """An opaque reader bound to exactly one already-sealed artifact identity."""

    artifact: ExternalObjectInputV1
    reader: DeadlineBoundedByteReaderPort

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _validated_object_input(self.artifact))
        if not isinstance(self.reader, DeadlineBoundedByteReaderPort):
            raise TypeError("sealed source must provide deadline-bounded reads")


@dataclass(frozen=True, slots=True)
class _ObjectTarget:
    parsed: SplitResult
    hostname: str
    port: int
    addresses: tuple[str, ...]

    @property
    def request_target(self) -> str:
        path = self.parsed.path or "/"
        return path + ("?" + self.parsed.query if self.parsed.query else "")

    @property
    def host_header(self) -> str:
        default_port = 443 if self.parsed.scheme == "https" else 80
        host = self.hostname
        if ":" in host:
            host = f"[{host}]"
        return host if self.port == default_port else f"{host}:{self.port}"


class ExternalObjectHttpByteSource(ExternalArtifactByteSourcePort):
    """A finite in-memory capability set and an owned raw HTTP/1.1 connection path."""

    def __init__(
        self,
        capabilities: Iterable[object],
        *,
        policy: ExternalObjectTransportPolicyV1,
    ) -> None:
        if not isinstance(policy, ExternalObjectTransportPolicyV1):
            raise TypeError("policy must be an ExternalObjectTransportPolicyV1")
        frozen: dict[ExternalObjectInputV1, ExternalObjectCapabilityV1] = {}
        for raw in capabilities:
            capability = _freeze_capability(raw)
            if capability.artifact in frozen:
                raise ValueError("object capability artifacts must be unique")
            frozen[capability.artifact] = capability
        if not frozen:
            raise ValueError("object byte source requires one or more capabilities")
        self._capabilities = MappingProxyType(frozen)
        self._policy = policy

    def open_bound_bytes(
        self,
        artifact: ExternalObjectInputV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> DeadlineBoundedByteReaderPort:
        _validate_operation_guard(deadline, wait_is_current, heartbeat_interval_millis)
        artifact = _validated_object_input(artifact)
        capability = self._capabilities.get(artifact)
        if capability is None:
            raise ExternalObjectTransportError("INPUT_CAPABILITY_UNAVAILABLE")
        target = self._policy.target_for(capability.url)
        connection = _connect_target(target, deadline, wait_is_current, heartbeat_interval_millis)
        try:
            connection = _secure_connection_if_needed(
                connection, target, deadline, wait_is_current, heartbeat_interval_millis
            )
            _send_all(
                connection,
                _request_bytes(
                    "GET",
                    target,
                    capability.required_headers,
                    max_header_bytes=self._policy.max_header_bytes,
                ),
                deadline,
                wait_is_current,
                heartbeat_interval_millis,
            )
            initial, content_length = _read_success_header(
                connection,
                deadline,
                wait_is_current,
                heartbeat_interval_millis,
                self._policy.max_header_bytes,
            )
            if content_length != artifact.observed_size_bytes:
                raise ExternalObjectTransportError("CONTENT_LENGTH_ARTIFACT_MISMATCH")
            if content_length > self._policy.max_object_bytes:
                raise ExternalObjectTransportError("OBJECT_SIZE_CAP_EXCEEDED")
            return _BoundHttpReader(
                connection=connection,
                initial=initial,
                expected_size=artifact.observed_size_bytes,
                expected_sha256=artifact.observed_sha256,
                max_object_bytes=self._policy.max_object_bytes,
                max_chunk_bytes=self._policy.max_chunk_bytes,
                opening_deadline_expires_at=deadline.expires_at,
            )
        except Exception:
            with _suppress_socket_error():
                connection.close()
            raise

    def put_bound_bytes(
        self,
        capability: object,
        sealed_source: SealedObjectByteSourceV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> BoundByteReceiptV1:
        """PUT exact opaque source bytes and return only an observed 2xx/EOF receipt."""
        _validate_operation_guard(deadline, wait_is_current, heartbeat_interval_millis)
        capability = _freeze_capability(capability)
        if self._capabilities.get(capability.artifact) != capability:
            raise ExternalObjectTransportError("INPUT_CAPABILITY_UNAVAILABLE")
        if not isinstance(sealed_source, SealedObjectByteSourceV1):
            raise TypeError("upload requires a typed sealed source")
        if sealed_source.artifact != capability.artifact:
            raise ExternalObjectTransportError("SEALED_SOURCE_ARTIFACT_MISMATCH")
        if capability.artifact.observed_size_bytes > self._policy.max_object_bytes:
            raise ExternalObjectTransportError("OBJECT_SIZE_CAP_EXCEEDED")
        target = self._policy.target_for(capability.url)
        connection = _connect_target(target, deadline, wait_is_current, heartbeat_interval_millis)
        try:
            connection = _secure_connection_if_needed(
                connection, target, deadline, wait_is_current, heartbeat_interval_millis
            )
            _send_all(
                connection,
                _request_bytes(
                    "PUT",
                    target,
                    capability.required_headers,
                    content_length=capability.artifact.observed_size_bytes,
                    max_header_bytes=self._policy.max_header_bytes,
                ),
                deadline,
                wait_is_current,
                heartbeat_interval_millis,
            )
            digest = hashlib.sha256()
            sent = 0
            while sent < capability.artifact.observed_size_bytes:
                _require_current(wait_is_current)
                deadline.remaining()
                chunk = sealed_source.reader.read_chunk(
                    min(
                        self._policy.max_chunk_bytes, capability.artifact.observed_size_bytes - sent
                    ),
                    deadline=deadline,
                    wait_is_current=wait_is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
                if not chunk:
                    raise ExternalObjectTransportError("SEALED_SOURCE_SHORT_EOF")
                if len(chunk) > self._policy.max_chunk_bytes:
                    raise ExternalObjectTransportError("SEALED_SOURCE_CHUNK_CAP_EXCEEDED")
                if sent + len(chunk) > self._policy.max_object_bytes:
                    raise ExternalObjectTransportError("OBJECT_SIZE_CAP_EXCEEDED")
                if len(chunk) > capability.artifact.observed_size_bytes - sent:
                    raise ExternalObjectTransportError("SEALED_SOURCE_SIZE_EXCEEDED")
                _send_all(connection, chunk, deadline, wait_is_current, heartbeat_interval_millis)
                digest.update(chunk)
                sent += len(chunk)
            if sealed_source.reader.read_chunk(
                1,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            ):
                raise ExternalObjectTransportError("SEALED_SOURCE_SIZE_EXCEEDED")
            if "sha256:" + digest.hexdigest() != capability.artifact.observed_sha256:
                raise ExternalObjectTransportError("SEALED_SOURCE_DIGEST_MISMATCH")
            initial, response_length = _read_success_header(
                connection,
                deadline,
                wait_is_current,
                heartbeat_interval_millis,
                self._policy.max_header_bytes,
            )
            if response_length != 0 or initial:
                raise ExternalObjectTransportError("UPLOAD_RESPONSE_BODY_REJECTED")
            _require_eof(connection, deadline, wait_is_current, heartbeat_interval_millis)
            return BoundByteReceiptV1(
                observed_sha256=capability.artifact.observed_sha256,
                observed_size_bytes=capability.artifact.observed_size_bytes,
            )
        finally:
            with _suppress_socket_error():
                connection.close()


class _BoundHttpReader:
    """One response body whose digest, size, and terminal EOF remain mandatory."""

    def __init__(
        self,
        *,
        connection: socket.socket | ssl.SSLSocket,
        initial: bytes,
        expected_size: int,
        expected_sha256: str,
        max_object_bytes: int,
        max_chunk_bytes: int,
        opening_deadline_expires_at: float,
    ) -> None:
        self._connection: socket.socket | ssl.SSLSocket | None = connection
        self._buffer = bytearray(initial)
        self._expected_size = expected_size
        self._expected_sha256 = expected_sha256
        self._max_object_bytes = max_object_bytes
        self._max_chunk_bytes = max_chunk_bytes
        self._opening_deadline_expires_at = opening_deadline_expires_at
        self._received = 0
        self._digest = hashlib.sha256()
        self._hash_checked = False

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise ProtocolViolation("object reader maximum must be a positive integer")
        if maximum_bytes > self._max_chunk_bytes:
            raise ExternalObjectTransportError("CHUNK_CAP_EXCEEDED")
        if deadline.expires_at > self._opening_deadline_expires_at:
            self.close()
            raise ExternalObjectTransportError("DEADLINE_EXTENSION_REJECTED")
        _validate_operation_guard(deadline, wait_is_current, heartbeat_interval_millis)
        connection = self._require_connection()
        if self._received == self._expected_size:
            try:
                if self._buffer:
                    raise ExternalObjectTransportError("TRAILING_RESPONSE_BYTES")
                _require_eof(connection, deadline, wait_is_current, heartbeat_interval_millis)
                return b""
            except Exception:
                self.close()
                raise
        requested = min(maximum_bytes, self._expected_size - self._received)
        try:
            if self._buffer:
                chunk = bytes(self._buffer[:requested])
                del self._buffer[: len(chunk)]
            else:
                chunk = _recv_some(
                    connection,
                    requested,
                    deadline,
                    wait_is_current,
                    heartbeat_interval_millis,
                )
            if not chunk:
                raise ExternalObjectTransportError("UNEXPECTED_BODY_EOF")
            if len(chunk) > requested:
                raise ExternalObjectTransportError("OBJECT_SIZE_CAP_EXCEEDED")
            self._received += len(chunk)
            if self._received > self._max_object_bytes:
                raise ExternalObjectTransportError("OBJECT_SIZE_CAP_EXCEEDED")
            self._digest.update(chunk)
            if self._received == self._expected_size:
                self._hash_checked = True
                if "sha256:" + self._digest.hexdigest() != self._expected_sha256:
                    raise ExternalObjectTransportError("OBJECT_DIGEST_MISMATCH")
            _require_current(wait_is_current)
            deadline.remaining()
            return chunk
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        connection, self._connection = self._connection, None
        self._buffer.clear()
        if connection is not None:
            with _suppress_socket_error():
                connection.close()

    def _require_connection(self) -> socket.socket | ssl.SSLSocket:
        if self._connection is None:
            raise ProtocolViolation("object response reader is closed")
        return self._connection


def _freeze_capability(value: object) -> ExternalObjectCapabilityV1:
    artifact = getattr(value, "artifact", None)
    url = getattr(value, "url", None)
    if url is None:
        url = getattr(value, "download_url", None)
    headers = getattr(value, "required_headers", None)
    if (
        not isinstance(artifact, (ExternalArtifactInputV1, MeasurementInputV2))
        or not isinstance(url, str)
        or not isinstance(headers, Mapping)
    ):
        raise ExternalObjectTransportError("INVALID_CAPABILITY_TUPLE")
    try:
        return ExternalObjectCapabilityV1(artifact=artifact, url=url, required_headers=headers)
    except (TypeError, ValueError, ExternalObjectTransportError) as exc:
        raise ExternalObjectTransportError("INVALID_CAPABILITY_TUPLE") from exc


def _parse_object_url(value: object) -> SplitResult:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > _MAX_URL_BYTES:
        raise ExternalObjectTransportError("INVALID_OBJECT_URL")
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ExternalObjectTransportError("INVALID_OBJECT_URL")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError
        parsed.hostname.encode("ascii")
        if parsed.port == 0:
            raise ValueError
    except (UnicodeEncodeError, ValueError):
        raise ExternalObjectTransportError("INVALID_OBJECT_URL") from None
    return parsed


def _origin_key(parsed: SplitResult) -> str:
    hostname = parsed.hostname
    if hostname is None:
        raise ExternalObjectTransportError("INVALID_OBJECT_URL")
    host = f"[{hostname}]" if ":" in hostname else hostname
    port = _url_port(parsed)
    default_port = 443 if parsed.scheme == "https" else 80
    return f"{parsed.scheme}://{host}" + ("" if port == default_port else f":{port}")


def _url_port(parsed: SplitResult) -> int:
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def _validate_required_headers(headers: Mapping[str, str]) -> None:
    if len(headers) > _MAX_REQUIRED_HEADERS:
        raise ExternalObjectTransportError("INVALID_REQUIRED_HEADERS")
    names: set[str] = set()
    for name, value in headers.items():
        lowered = name.lower() if isinstance(name, str) else ""
        try:
            value_size = len(value.encode("ascii")) if isinstance(value, str) else -1
        except UnicodeEncodeError:
            value_size = -1
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or _HEADER_NAME.fullmatch(name) is None
            or lowered in _FORBIDDEN_CAPABILITY_HEADERS
            or lowered in names
            or value_size < 0
            or value_size > _MAX_REQUIRED_HEADER_VALUE_BYTES
            or any(ord(char) < 32 or ord(char) > 126 for char in value)
        ):
            raise ExternalObjectTransportError("INVALID_REQUIRED_HEADERS")
        names.add(lowered)


def _request_bytes(
    method: str,
    target: _ObjectTarget,
    required_headers: Mapping[str, str],
    *,
    content_length: int | None = None,
    max_header_bytes: int,
) -> bytes:
    _validate_required_headers(required_headers)
    if method not in {"GET", "PUT"}:
        raise ValueError("only GET and PUT object methods are supported")
    lines = [
        f"{method} {target.request_target} HTTP/1.1",
        f"Host: {target.host_header}",
        "Connection: close",
    ]
    if content_length is not None:
        lines.append(f"Content-Length: {content_length}")
    lines.extend(f"{name}: {value}" for name, value in required_headers.items())
    try:
        payload = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    except UnicodeEncodeError as exc:
        raise ExternalObjectTransportError("INVALID_REQUIRED_HEADERS") from exc
    if len(payload) > max_header_bytes:
        raise ExternalObjectTransportError("HEADER_CAP_EXCEEDED")
    return payload


def _connect_target(
    target: _ObjectTarget,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> socket.socket:
    _validate_operation_guard(deadline, wait_is_current, heartbeat_interval_millis)
    for address in target.addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        connection = socket.socket(family, socket.SOCK_STREAM)
        connection.setblocking(False)
        try:
            result = connection.connect_ex((address, target.port))
            if result not in {0, errno.EISCONN}:
                if result not in _CONNECT_PENDING:
                    with _suppress_socket_error():
                        connection.close()
                    continue
                _wait_for_socket(
                    connection,
                    readable=False,
                    deadline=deadline,
                    wait_is_current=wait_is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
                if connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) != 0:
                    continue
            _require_current(wait_is_current)
            deadline.remaining()
            return connection
        except (ExternalObjectTransportError, ProtocolDeadlineExceeded):
            with _suppress_socket_error():
                connection.close()
            raise
        except OSError:
            with _suppress_socket_error():
                connection.close()
            continue
    raise ExternalObjectTransportError("CONNECT_FAILED")


def _secure_connection_if_needed(
    connection: socket.socket,
    target: _ObjectTarget,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> socket.socket | ssl.SSLSocket:
    if target.parsed.scheme == "http":
        return connection
    secure: ssl.SSLSocket | None = None
    try:
        secure = ssl.create_default_context().wrap_socket(
            connection,
            server_hostname=target.hostname,
            do_handshake_on_connect=False,
        )
        secure.setblocking(False)
        while True:
            _require_current(wait_is_current)
            try:
                secure.do_handshake()
                deadline.remaining()
                _require_current(wait_is_current)
                return secure
            except ssl.SSLWantReadError:
                _wait_for_socket(
                    secure,
                    readable=True,
                    deadline=deadline,
                    wait_is_current=wait_is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
            except ssl.SSLWantWriteError:
                _wait_for_socket(
                    secure,
                    readable=False,
                    deadline=deadline,
                    wait_is_current=wait_is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
    except (OSError, ssl.SSLError) as exc:
        _close_unsuccessful_tls_socket(secure, connection)
        raise ExternalObjectTransportError("TLS_HANDSHAKE_FAILED") from exc
    except BaseException:
        _close_unsuccessful_tls_socket(secure, connection)
        raise


def _close_unsuccessful_tls_socket(secure: ssl.SSLSocket | None, connection: socket.socket) -> None:
    """Close the current descriptor owner until TLS setup transfers it to a caller."""
    with _suppress_socket_error():
        (secure if secure is not None else connection).close()


def _send_all(
    connection: socket.socket | ssl.SSLSocket,
    payload: bytes,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> None:
    remaining = memoryview(payload)
    while remaining:
        _require_current(wait_is_current)
        try:
            written = connection.send(remaining)
        except ssl.SSLWantReadError:
            _wait_for_socket(
                connection,
                readable=True,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            continue
        except (BlockingIOError, ssl.SSLWantWriteError):
            _wait_for_socket(
                connection,
                readable=False,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            continue
        except OSError as exc:
            raise ExternalObjectTransportError("SOCKET_WRITE_FAILED") from exc
        if written <= 0:
            raise ExternalObjectTransportError("SOCKET_WRITE_FAILED")
        remaining = remaining[written:]
        deadline.remaining()
        _require_current(wait_is_current)


def _read_success_header(
    connection: socket.socket | ssl.SSLSocket,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
    max_header_bytes: int,
) -> tuple[bytes, int]:
    received = bytearray()
    while True:
        marker = received.find(b"\r\n\r\n")
        if marker >= 0:
            raw_header = bytes(received[:marker])
            return bytes(received[marker + 4 :]), _validate_success_header(raw_header)
        if len(received) >= max_header_bytes:
            raise ExternalObjectTransportError("HEADER_CAP_EXCEEDED")
        piece = _recv_some(
            connection,
            min(1024, max_header_bytes - len(received)),
            deadline,
            wait_is_current,
            heartbeat_interval_millis,
        )
        if not piece:
            raise ExternalObjectTransportError("UNEXPECTED_HEADER_EOF")
        received.extend(piece)


def _validate_success_header(raw_header: bytes) -> int:
    try:
        lines = raw_header.decode("ascii").split("\r\n")
    except UnicodeDecodeError as exc:
        raise ExternalObjectTransportError("INVALID_RESPONSE_HEADER") from exc
    if not lines or re.fullmatch(r"HTTP/1\.[01] [0-9]{3}(?: .*)?", lines[0]) is None:
        raise ExternalObjectTransportError("INVALID_RESPONSE_HEADER")
    status = int(lines[0][9:12])
    if status < 200 or status >= 300:
        raise ExternalObjectTransportError("HTTP_STATUS_REJECTED")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            raise ExternalObjectTransportError("INVALID_RESPONSE_HEADER")
        name, value = line.split(":", 1)
        lowered = name.lower()
        if _HEADER_NAME.fullmatch(name) is None:
            raise ExternalObjectTransportError("INVALID_RESPONSE_HEADER")
        if any(ord(character) < 32 or ord(character) > 126 for character in value):
            raise ExternalObjectTransportError("INVALID_RESPONSE_HEADER")
        if lowered in headers:
            if lowered != "vary":
                raise ExternalObjectTransportError("INVALID_RESPONSE_HEADER")
            headers[lowered] += ", " + value.strip(" ")
        else:
            headers[lowered] = value.strip(" ")
    if "transfer-encoding" in headers:
        raise ExternalObjectTransportError("TRANSFER_ENCODING_REJECTED")
    if "content-encoding" in headers:
        raise ExternalObjectTransportError("CONTENT_ENCODING_REJECTED")
    length = headers.get("content-length")
    if length is None or re.fullmatch(r"(?:0|[1-9][0-9]*)", length) is None:
        raise ExternalObjectTransportError("INVALID_CONTENT_LENGTH")
    return int(length)


def _recv_some(
    connection: socket.socket | ssl.SSLSocket,
    maximum_bytes: int,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> bytes:
    while True:
        _require_current(wait_is_current)
        deadline.remaining()
        try:
            received = connection.recv(maximum_bytes)
        except ssl.SSLWantReadError:
            _wait_for_socket(
                connection,
                readable=True,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
        except ssl.SSLWantWriteError:
            _wait_for_socket(
                connection,
                readable=False,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
        except BlockingIOError:
            _wait_for_socket(
                connection,
                readable=True,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
        except OSError as exc:
            raise ExternalObjectTransportError("SOCKET_READ_FAILED") from exc
        else:
            deadline.remaining()
            _require_current(wait_is_current)
            return received


def _require_eof(
    connection: socket.socket | ssl.SSLSocket,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> None:
    if _recv_some(connection, 1, deadline, wait_is_current, heartbeat_interval_millis):
        raise ExternalObjectTransportError("TRAILING_RESPONSE_BYTES")


def _wait_for_socket(
    connection: socket.socket | ssl.SSLSocket,
    *,
    readable: bool,
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> None:
    _validate_operation_guard(deadline, wait_is_current, heartbeat_interval_millis)
    if heartbeat_interval_millis is None:  # narrowed after the shared guard above
        raise AssertionError("validated heartbeat interval disappeared")
    while True:
        _require_current(wait_is_current)
        timeout = min(deadline.remaining(), heartbeat_interval_millis / 1_000)
        ready_read, ready_write, _ = select.select(
            [connection] if readable else [], [] if readable else [connection], [], timeout
        )
        deadline.remaining()
        _require_current(wait_is_current)
        if ready_read or ready_write:
            return


def _validate_operation_guard(
    deadline: ProtocolDeadline,
    wait_is_current: Callable[[], bool] | None,
    heartbeat_interval_millis: int | None,
) -> None:
    if not isinstance(deadline, ProtocolDeadline):
        raise TypeError("object transport requires a ProtocolDeadline")
    if wait_is_current is None or not callable(wait_is_current):
        raise TypeError("object transport requires an authority guard")
    if type(heartbeat_interval_millis) is not int or heartbeat_interval_millis <= 0:
        raise ValueError("object transport requires a positive heartbeat interval")
    _require_current(wait_is_current)
    deadline.remaining()


def _require_current(wait_is_current: Callable[[], bool] | None) -> None:
    if wait_is_current is None or not wait_is_current():
        raise ExternalObjectTransportError("AUTHORITY_LOST")


class _suppress_socket_error:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, traceback) -> bool:  # type: ignore[no-untyped-def]
        return exc_type is not None and issubclass(exc_type, OSError)


__all__ = [
    "ExternalObjectCapabilityPort",
    "ExternalObjectCapabilityV1",
    "ExternalObjectHttpByteSource",
    "ExternalObjectTransportError",
    "ExternalObjectTransportPolicyV1",
    "SealedObjectByteSourceV1",
    "TrustedObjectEndpointV1",
]
