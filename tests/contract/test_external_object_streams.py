"""Loopback contract tests for the deliberately narrow object byte transport."""

from __future__ import annotations

import hashlib
import io
import socket
import ssl
import subprocess
import threading
import time
from collections.abc import Callable, Generator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_artifact_inspection_worker import ExternalArtifactInputV1
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteReaderPort,
    DeadlineBoundedBytesReader,
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityV1,
    ExternalObjectHttpByteSource,
    ExternalObjectTransportError,
    ExternalObjectTransportPolicyV1,
    SealedObjectByteSourceV1,
    TrustedObjectEndpointV1,
)

_ServerHandler = Callable[[socket.socket, "_LoopbackServer"], None]
_ServerFactory = Callable[[_ServerHandler], "_LoopbackServer"]


@dataclass(frozen=True)
class _TlsMaterial:
    ca_certificate: Path
    certificate: Path
    private_key: Path


def _artifact(payload: bytes) -> ExternalArtifactInputV1:
    return ExternalArtifactInputV1(
        entry_id="sealed-ortho",
        kind=ProcessingArtifactKind.ORTHO,
        observed_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        observed_size_bytes=len(payload),
        content_type="image/tiff",
    )


def _deadline(milliseconds: int = 800) -> ProtocolDeadline:
    return ProtocolDeadline(milliseconds, time.monotonic)


def _read_request(connection: socket.socket) -> bytes:
    received = bytearray()
    connection.settimeout(1.0)
    while b"\r\n\r\n" not in received:
        piece = connection.recv(4096)
        if not piece:
            break
        received.extend(piece)
    return bytes(received)


class _LoopbackServer:
    """One deterministic test-only listener; close joins its one owned thread."""

    def __init__(self, handler: _ServerHandler) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(1.0)
        self.port = self._listener.getsockname()[1]
        self.requests: list[bytes] = []
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._serve, args=(handler,), daemon=False)
        self._thread.start()

    def _serve(self, handler: _ServerHandler) -> None:
        try:
            connection, _ = self._listener.accept()
            with connection:
                handler(connection, self)
        except BaseException as exc:  # surfaced by close, never silently orphaned
            self.error = exc
        finally:
            self._listener.close()

    def close(self) -> None:
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise AssertionError("loopback server did not stop")
        if self.error is not None:
            raise self.error


@pytest.fixture
def server() -> Generator[_ServerFactory, None, None]:
    servers: list[_LoopbackServer] = []

    def start(handler: _ServerHandler) -> _LoopbackServer:
        result = _LoopbackServer(handler)
        servers.append(result)
        return result

    yield start
    for item in servers:
        item.close()


def _policy(port: int, *, scheme: str = "http") -> ExternalObjectTransportPolicyV1:
    return ExternalObjectTransportPolicyV1(
        endpoints=(
            TrustedObjectEndpointV1(
                origin=f"{scheme}://127.0.0.1:{port}", addresses=("127.0.0.1",)
            ),
        ),
        max_header_bytes=4096,
        max_object_bytes=1024 * 1024,
        max_chunk_bytes=1024,
    )


def _capability(
    port: int,
    artifact: ExternalArtifactInputV1,
    *,
    scheme: str = "http",
    headers: dict[str, str] | None = None,
) -> ExternalObjectCapabilityV1:
    return ExternalObjectCapabilityV1(
        artifact=artifact,
        url=f"{scheme}://127.0.0.1:{port}/sealed/object?version=1",
        required_headers=headers or {"X-Storage-Capability": "signed-value"},
    )


def _source(
    capability: ExternalObjectCapabilityV1, policy: ExternalObjectTransportPolicyV1
) -> ExternalObjectHttpByteSource:
    return ExternalObjectHttpByteSource((capability,), policy=policy)


@pytest.fixture(scope="session")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> _TlsMaterial:
    """A private CA and server key created only for the owned loopback tests."""
    root = tmp_path_factory.mktemp("task7b1-tls")
    ca_key = root / "ca-key.pem"
    ca_certificate = root / "ca-cert.pem"
    private_key = root / "server-key.pem"
    request = root / "server.csr"
    certificate = root / "server-cert.pem"
    extensions = root / "server.ext"
    extensions.write_text("subjectAltName=DNS:good.test\nbasicConstraints=critical,CA:FALSE\n")
    commands = (
        (
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_certificate),
            "-days",
            "1",
            "-subj",
            "/CN=Task7B1 Loopback CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
        ),
        (
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(request),
            "-subj",
            "/CN=good.test",
        ),
        (
            "x509",
            "-req",
            "-in",
            str(request),
            "-CA",
            str(ca_certificate),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(certificate),
            "-days",
            "1",
            "-extfile",
            str(extensions),
        ),
    )
    for command in commands:
        subprocess.run(
            ("openssl", *command),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return _TlsMaterial(ca_certificate, certificate, private_key)


def _tls_server_context(material: _TlsMaterial, sni_names: list[str | None]) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(material.certificate, material.private_key)
    context.set_servername_callback(lambda _secure, name, _context: sni_names.append(name))
    return context


def _tls_source(
    port: int,
    artifact: ExternalArtifactInputV1,
    *,
    hostname: str,
    max_object_bytes: int = 1024 * 1024,
    max_chunk_bytes: int = 1024,
) -> tuple[ExternalObjectCapabilityV1, ExternalObjectHttpByteSource]:
    origin = f"https://{hostname}:{port}"
    capability = ExternalObjectCapabilityV1(
        artifact=artifact,
        url=origin + "/sealed/object?version=1",
        required_headers={"X-Storage-Capability": "signed-value"},
    )
    policy = ExternalObjectTransportPolicyV1(
        endpoints=(TrustedObjectEndpointV1(origin=origin, addresses=("127.0.0.1",)),),
        max_header_bytes=4096,
        max_object_bytes=max_object_bytes,
        max_chunk_bytes=max_chunk_bytes,
    )
    return capability, ExternalObjectHttpByteSource((capability,), policy=policy)


def _retained_tls_socket(error: BaseException) -> ssl.SSLSocket:
    pending: list[BaseException] = [error]
    if error.__cause__ is not None:
        pending.append(error.__cause__)
    for current in pending:
        traceback = current.__traceback__
        while traceback is not None:
            secure = traceback.tb_frame.f_locals.get("secure")
            if isinstance(secure, ssl.SSLSocket):
                return secure
            traceback = traceback.tb_next
    raise AssertionError("failed TLS setup did not retain its wrapped socket for inspection")


class _OverproducingReader:
    def __init__(self, chunk: bytes) -> None:
        self.chunk = chunk
        self.calls = 0

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        del maximum_bytes, deadline, wait_is_current, heartbeat_interval_millis
        self.calls += 1
        return self.chunk

    def close(self) -> None:
        return None


def _drain(reader: DeadlineBoundedByteReaderPort, deadline: ProtocolDeadline) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = reader.read_chunk(
            3,
            deadline=deadline,
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def test_get_uses_only_bound_capability_static_address_and_verified_eof(
    server: _ServerFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"sealed loopback bytes"

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\n\r\n"
            + payload
        )

    listener = server(handler)
    artifact = _artifact(payload)
    capability = _capability(listener.port, artifact)
    # A request-time resolver would now fail.  The configured mapping is the only dial source.
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())
    )
    read_deadline = _deadline()
    reader = _source(capability, _policy(listener.port)).open_bound_bytes(
        artifact,
        deadline=read_deadline,
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    try:
        assert _drain(reader, read_deadline) == payload
    finally:
        reader.close()
    assert listener.requests == [
        b"GET /sealed/object?version=1 HTTP/1.1\r\n"
        + f"Host: 127.0.0.1:{listener.port}\r\n".encode()
        + b"Connection: close\r\nX-Storage-Capability: signed-value\r\n\r\n"
    ]


def test_get_rejects_redirect_header_injection_content_encoding_and_trailing_bytes(
    server: _ServerFactory,
) -> None:
    payload = b"bound"

    def redirect(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(
            b"HTTP/1.1 302 Found\r\nLocation: http://example.invalid/\r\nContent-Length: 0\r\n\r\n"
        )

    redirect_server = server(redirect)
    artifact = _artifact(payload)
    with pytest.raises(ExternalObjectTransportError, match="HTTP_STATUS_REJECTED"):
        _source(
            _capability(redirect_server.port, artifact), _policy(redirect_server.port)
        ).open_bound_bytes(
            artifact,
            deadline=_deadline(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )
    assert len(redirect_server.requests) == 1

    with pytest.raises(ExternalObjectTransportError, match="INVALID_REQUIRED_HEADERS"):
        _capability(redirect_server.port, artifact, headers={"X-Valid": "ok\r\nInjected: nope"})

    def encoded_and_trailed(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nContent-Encoding: gzip\r\n\r\nbound"
        )

    encoded_server = server(encoded_and_trailed)
    with pytest.raises(ExternalObjectTransportError, match="CONTENT_ENCODING_REJECTED"):
        _source(
            _capability(encoded_server.port, artifact), _policy(encoded_server.port)
        ).open_bound_bytes(
            artifact,
            deadline=_deadline(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )

    def trailed(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nboundtrailing")

    trailing_server = server(trailed)
    trailing_deadline = _deadline()
    reader = _source(
        _capability(trailing_server.port, artifact), _policy(trailing_server.port)
    ).open_bound_bytes(
        artifact,
        deadline=trailing_deadline,
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    try:
        with pytest.raises(ExternalObjectTransportError, match="TRAILING_RESPONSE_BYTES"):
            _drain(reader, trailing_deadline)
    finally:
        reader.close()

    def wrong_digest(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nother")

    digest_server = server(wrong_digest)
    digest_deadline = _deadline()
    reader = _source(
        _capability(digest_server.port, artifact), _policy(digest_server.port)
    ).open_bound_bytes(
        artifact,
        deadline=digest_deadline,
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    try:
        with pytest.raises(ExternalObjectTransportError, match="OBJECT_DIGEST_MISMATCH"):
            _drain(reader, digest_deadline)
    finally:
        reader.close()

    def short_body(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nbo")

    short_server = server(short_body)
    short_deadline = _deadline()
    reader = _source(
        _capability(short_server.port, artifact), _policy(short_server.port)
    ).open_bound_bytes(
        artifact,
        deadline=short_deadline,
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    try:
        with pytest.raises(ExternalObjectTransportError, match="UNEXPECTED_BODY_EOF"):
            _drain(reader, short_deadline)
    finally:
        reader.close()


def test_get_accepts_repeated_vary_response_fields(server: _ServerFactory) -> None:
    payload = b"bound"

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n"
            b"Vary: Origin\r\nVary: Access-Control-Request-Headers\r\n\r\nbound"
        )

    listener = server(handler)
    artifact = _artifact(payload)
    deadline = _deadline()
    reader = _source(_capability(listener.port, artifact), _policy(listener.port)).open_bound_bytes(
        artifact,
        deadline=deadline,
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    try:
        assert _drain(reader, deadline) == payload
    finally:
        reader.close()


@pytest.mark.parametrize(
    "duplicate",
    (
        b"Content-Length: 5",
        b"Transfer-Encoding: identity",
        b"Content-Encoding: identity",
        b"ETag: opaque",
    ),
)
def test_get_rejects_duplicate_framing_or_singleton_response_fields(
    server: _ServerFactory, duplicate: bytes
) -> None:
    payload = b"bound"

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n"
            + duplicate
            + b"\r\n"
            + duplicate
            + b"\r\n\r\n"
            + payload
        )

    listener = server(handler)
    artifact = _artifact(payload)
    with pytest.raises(ExternalObjectTransportError, match="INVALID_RESPONSE_HEADER"):
        _source(_capability(listener.port, artifact), _policy(listener.port)).open_bound_bytes(
            artifact,
            deadline=_deadline(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


def test_get_header_body_deadline_and_authority_cancellation_are_not_reset_per_read(
    server: _ServerFactory,
) -> None:
    payload = b"slow!"

    def slow_header(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(b"HTTP/1.1 200")
        time.sleep(0.12)
        with suppress(OSError):
            connection.sendall(b" OK\r\nContent-Length: 5\r\n\r\nslow!")

    header_server = server(slow_header)
    artifact = _artifact(payload)
    with pytest.raises(ProtocolDeadlineExceeded):
        _source(
            _capability(header_server.port, artifact), _policy(header_server.port)
        ).open_bound_bytes(
            artifact,
            deadline=_deadline(40),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )

    def slow_body(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\ns")
        time.sleep(0.12)
        with suppress(OSError):
            connection.sendall(b"low!")

    body_server = server(slow_body)
    body_deadline = _deadline(80)
    reader = _source(
        _capability(body_server.port, artifact), _policy(body_server.port)
    ).open_bound_bytes(
        artifact,
        deadline=body_deadline,
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    try:
        assert (
            reader.read_chunk(
                1,
                deadline=body_deadline,
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
            == b"s"
        )
        with pytest.raises(ProtocolDeadlineExceeded):
            reader.read_chunk(
                4,
                deadline=body_deadline,
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
    finally:
        reader.close()

    def blocked_body(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n")
        time.sleep(0.12)

    cancelled_server = server(blocked_body)
    reader = _source(
        _capability(cancelled_server.port, artifact), _policy(cancelled_server.port)
    ).open_bound_bytes(
        artifact,
        deadline=_deadline(300),
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    cutoff = time.monotonic() + 0.03
    try:
        with pytest.raises(ExternalObjectTransportError, match="AUTHORITY_LOST"):
            reader.read_chunk(
                1,
                deadline=_deadline(250),
                wait_is_current=lambda: time.monotonic() < cutoff,
                heartbeat_interval_millis=10,
            )
    finally:
        reader.close()


def test_get_reader_refuses_chunk_or_deadline_cap_extensions(server: _ServerFactory) -> None:
    payload = b"bound"

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nbound")

    listener = server(handler)
    artifact = _artifact(payload)
    opening_deadline = _deadline(200)
    reader = _source(_capability(listener.port, artifact), _policy(listener.port)).open_bound_bytes(
        artifact,
        deadline=opening_deadline,
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    try:
        with pytest.raises(ExternalObjectTransportError, match="CHUNK_CAP_EXCEEDED"):
            reader.read_chunk(
                1025,
                deadline=opening_deadline,
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
        with pytest.raises(ExternalObjectTransportError, match="DEADLINE_EXTENSION_REJECTED"):
            reader.read_chunk(
                1,
                deadline=_deadline(500),
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
    finally:
        reader.close()


def test_get_refuses_plaintext_for_https_and_never_falls_back_to_unverified_tls(
    server: _ServerFactory,
) -> None:
    payload = b"tls!!"

    def plaintext(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(connection.recv(32))
        with suppress(OSError):
            connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\ntls!!")

    listener = server(plaintext)
    artifact = _artifact(payload)
    with pytest.raises(ExternalObjectTransportError, match="TLS_HANDSHAKE_FAILED"):
        _source(
            _capability(listener.port, artifact, scheme="https"),
            _policy(listener.port, scheme="https"),
        ).open_bound_bytes(
            artifact,
            deadline=_deadline(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


def test_https_streams_pending_tls_body_before_waiting_for_terminal_eof(
    server: _ServerFactory,
    tls_material: _TlsMaterial,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"t" * 4096
    release = threading.Event()
    sni_names: list[str | None] = []
    context = _tls_server_context(tls_material, sni_names)

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        with context.wrap_socket(connection, server_side=True) as secure:
            listener.requests.append(_read_request(secure))
            secure.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(len(payload)).encode()
                + b"\r\n\r\n"
                + payload
            )
            assert release.wait(1.0)

    listener = server(handler)
    monkeypatch.setenv("SSL_CERT_FILE", str(tls_material.ca_certificate))
    artifact = _artifact(payload)
    _, transport = _tls_source(listener.port, artifact, hostname="good.test", max_chunk_bytes=128)
    opening_deadline = _deadline(400)
    reader = transport.open_bound_bytes(
        artifact,
        deadline=opening_deadline,
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    try:
        body = bytearray()
        while len(body) < len(payload):
            body.extend(
                reader.read_chunk(
                    128,
                    deadline=opening_deadline,
                    wait_is_current=lambda: True,
                    heartbeat_interval_millis=10,
                )
            )
        assert bytes(body) == payload
        assert sni_names == ["good.test"]
        with pytest.raises(ProtocolDeadlineExceeded):
            reader.read_chunk(
                1,
                deadline=_deadline(30),
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
    finally:
        reader.close()
        release.set()


@pytest.mark.parametrize("failure", ("hostname", "timeout", "authority"))
def test_failed_tls_setup_closes_wrapped_socket_even_if_exception_is_retained(
    server: _ServerFactory,
    tls_material: _TlsMaterial,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    sni_names: list[str | None] = []
    context = _tls_server_context(tls_material, sni_names)

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        if failure == "hostname":
            with (
                suppress(ssl.SSLError),
                context.wrap_socket(connection, server_side=True) as secure,
            ):
                listener.requests.append(_read_request(secure))
            return
        time.sleep(0.12)

    listener = server(handler)
    monkeypatch.setenv("SSL_CERT_FILE", str(tls_material.ca_certificate))
    artifact = _artifact(b"tls!!")
    hostname = "wrong.test" if failure == "hostname" else "good.test"
    _, transport = _tls_source(listener.port, artifact, hostname=hostname)
    cutoff = time.monotonic() + 0.03
    deadline = _deadline(50 if failure == "timeout" else 300)
    wait_is_current = (
        (lambda: time.monotonic() < cutoff) if failure == "authority" else (lambda: True)
    )
    with pytest.raises((ExternalObjectTransportError, ProtocolDeadlineExceeded)) as caught:
        transport.open_bound_bytes(
            artifact,
            deadline=deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=10,
        )
    assert _retained_tls_socket(caught.value).fileno() == -1
    if failure == "hostname":
        assert sni_names == ["wrong.test"]


def test_put_enforces_object_cap_before_connect_and_for_each_source_chunk(
    server: _ServerFactory,
) -> None:
    oversized_payload = b"oversized"
    passive_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    passive_listener.bind(("127.0.0.1", 0))
    passive_listener.listen(1)
    passive_listener.settimeout(0.05)
    try:
        artifact = _artifact(oversized_payload)
        capability = _capability(passive_listener.getsockname()[1], artifact)
        policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin=f"http://127.0.0.1:{passive_listener.getsockname()[1]}",
                    addresses=("127.0.0.1",),
                ),
            ),
            max_header_bytes=4096,
            max_object_bytes=4,
            max_chunk_bytes=4,
        )
        reader = _OverproducingReader(oversized_payload)
        with pytest.raises(ExternalObjectTransportError, match="OBJECT_SIZE_CAP_EXCEEDED"):
            ExternalObjectHttpByteSource((capability,), policy=policy).put_bound_bytes(
                capability,
                SealedObjectByteSourceV1(artifact=artifact, reader=reader),
                deadline=_deadline(),
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
        assert reader.calls == 0
        with pytest.raises(TimeoutError):
            passive_listener.accept()
    finally:
        passive_listener.close()

    payload = b"exact-cap"

    def exact_cap_handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        request = _read_request(connection)
        listener.requests.append(request)
        remaining = len(payload) - len(request.split(b"\r\n\r\n", 1)[1])
        while remaining:
            remaining -= len(connection.recv(remaining))
        connection.sendall(b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n")

    listener = server(exact_cap_handler)
    artifact = _artifact(payload)
    capability = _capability(listener.port, artifact)
    exact_policy = ExternalObjectTransportPolicyV1(
        endpoints=(
            TrustedObjectEndpointV1(
                origin=f"http://127.0.0.1:{listener.port}", addresses=("127.0.0.1",)
            ),
        ),
        max_header_bytes=4096,
        max_object_bytes=len(payload),
        max_chunk_bytes=4,
    )
    receipt = ExternalObjectHttpByteSource((capability,), policy=exact_policy).put_bound_bytes(
        capability,
        SealedObjectByteSourceV1(
            artifact=artifact, reader=DeadlineBoundedBytesReader(io.BytesIO(payload))
        ),
        deadline=_deadline(),
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    assert receipt.observed_size_bytes == len(payload)

    def chunk_cap_handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        time.sleep(0.05)

    chunk_listener = server(chunk_cap_handler)
    chunk_capability = _capability(chunk_listener.port, artifact)
    chunk_policy = ExternalObjectTransportPolicyV1(
        endpoints=(
            TrustedObjectEndpointV1(
                origin=f"http://127.0.0.1:{chunk_listener.port}", addresses=("127.0.0.1",)
            ),
        ),
        max_header_bytes=4096,
        max_object_bytes=len(payload),
        max_chunk_bytes=4,
    )
    oversized_chunk = _OverproducingReader(b"12345")
    with pytest.raises(ExternalObjectTransportError, match="SEALED_SOURCE_CHUNK_CAP_EXCEEDED"):
        ExternalObjectHttpByteSource((chunk_capability,), policy=chunk_policy).put_bound_bytes(
            chunk_capability,
            SealedObjectByteSourceV1(artifact=artifact, reader=oversized_chunk),
            deadline=_deadline(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )
    assert oversized_chunk.calls == 1


def test_put_streams_only_exact_sealed_source_then_observes_empty_success_response(
    server: _ServerFactory,
) -> None:
    payload = b"opaque sealed upload"

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        request = _read_request(connection)
        length = int(
            next(
                line
                for line in request.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            ).split(b":", 1)[1]
        )
        body = bytearray(request.split(b"\r\n\r\n", 1)[1])
        while len(body) < length:
            body.extend(connection.recv(length - len(body)))
        listener.requests.append(request.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n" + bytes(body))
        connection.sendall(b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n")

    listener = server(handler)
    artifact = _artifact(payload)
    capability = _capability(listener.port, artifact, headers={"X-Upload-Capability": "opaque"})
    transport = _source(capability, _policy(listener.port))
    receipt = transport.put_bound_bytes(
        capability,
        SealedObjectByteSourceV1(
            artifact=artifact, reader=DeadlineBoundedBytesReader(io.BytesIO(payload))
        ),
        deadline=_deadline(),
        wait_is_current=lambda: True,
        heartbeat_interval_millis=10,
    )
    assert receipt.observed_sha256 == artifact.observed_sha256
    assert receipt.observed_size_bytes == len(payload)
    assert b"PUT /sealed/object?version=1 HTTP/1.1" in listener.requests[0]
    assert listener.requests[0].endswith(payload)


def test_put_rejects_wrong_sealed_bytes_before_any_success_receipt(server: _ServerFactory) -> None:
    payload = b"expected"

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        request = _read_request(connection)
        listener.requests.append(request)
        # The client must close on source mismatch rather than accept this response.
        time.sleep(0.04)

    listener = server(handler)
    artifact = _artifact(payload)
    capability = _capability(listener.port, artifact)
    with pytest.raises(ExternalObjectTransportError, match="SEALED_SOURCE_DIGEST_MISMATCH"):
        _source(capability, _policy(listener.port)).put_bound_bytes(
            capability,
            SealedObjectByteSourceV1(
                artifact=artifact, reader=DeadlineBoundedBytesReader(io.BytesIO(b"mismatch"))
            ),
            deadline=_deadline(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


@pytest.mark.parametrize("role", ["CHECKPOINT_CSV", "TARGET_DSM", "BASELINE_DSM", "CURRENT_DSM"])
def test_measurement_object_bytes_preserve_exact_role_without_managed_kind(
    server: _ServerFactory,
    role: Literal["CHECKPOINT_CSV", "TARGET_DSM", "BASELINE_DSM", "CURRENT_DSM"],
) -> None:
    from ksi_processing_controller.external_measurement_protocol import MeasurementInputV2

    payload = b"x,y,z\n1,2,3\n"
    identity = MeasurementInputV2(
        role=role,
        artifact_id="sealed-measurement-input",
        observed_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        observed_size_bytes=len(payload),
    )

    def handler(connection: socket.socket, listener: _LoopbackServer) -> None:
        listener.requests.append(_read_request(connection))
        connection.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\n\r\n"
            + payload
        )

    listener = server(handler)
    capability = ExternalObjectCapabilityV1(
        artifact=identity,
        url=f"http://127.0.0.1:{listener.port}/sealed/measurement",
        required_headers={},
    )
    transport = ExternalObjectHttpByteSource((capability,), policy=_policy(listener.port))
    different_role = "TARGET_DSM" if role != "TARGET_DSM" else "CHECKPOINT_CSV"
    with pytest.raises(ExternalObjectTransportError, match="INPUT_CAPABILITY_UNAVAILABLE"):
        transport.open_bound_bytes(
            identity.model_copy(update={"role": different_role}),
            deadline=_deadline(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )
    assert not listener.requests
    deadline = _deadline()
    reader = transport.open_bound_bytes(
        identity, deadline=deadline, wait_is_current=lambda: True, heartbeat_interval_millis=10
    )
    received = bytearray()
    try:
        while chunk := reader.read_chunk(
            3, deadline=deadline, wait_is_current=lambda: True, heartbeat_interval_millis=10
        ):
            received.extend(chunk)
    finally:
        reader.close()
    assert bytes(received) == payload
    assert len(listener.requests) == 1
    assert not hasattr(identity, "kind")


@pytest.mark.parametrize(
    "update", [{"role": "DSM"}, {"observed_size_bytes": True}, {"observed_sha256": "unsealed"}]
)
def test_measurement_capability_revalidates_unsafe_identity_before_effects(
    update: dict[str, object],
) -> None:
    from ksi_processing_controller.external_measurement_protocol import MeasurementInputV2

    identity = MeasurementInputV2(
        role="CHECKPOINT_CSV",
        artifact_id="csv",
        observed_sha256="sha256:" + "a" * 64,
        observed_size_bytes=1,
    )
    with pytest.raises(ValueError):
        ExternalObjectCapabilityV1(
            artifact=identity.model_copy(update=update),
            url="http://127.0.0.1:9/uncontacted",
            required_headers={},
        )
