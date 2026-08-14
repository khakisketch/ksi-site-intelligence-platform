"""Pinned Core dispatch pull → verified local activation → receipt companion.

This module is deliberately an **activation-time** control-plane companion.
It does not run in a PSDK callback or the native frame/safety loop.  The
existing :mod:`edge_activation` module remains the only owner of signed
``MissionDispatchEnvelope`` verification and Mission Contract activation;
this module only obtains exact Core bytes and returns that verifier's exact
receipt to Core.

The production transport uses a supplied CA bundle plus an exact SPKI pin,
does not follow redirects, and validates the pin before it sends a bearer.
All network failures leave an already valid local activation intact.  Core
will continue returning its unacknowledged dispatch, so the next invocation
can replay the same activation and receipt idempotently.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import ssl
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ksi_mission_contracts.consumer import (
    ContractInputError,
    MissionContractConsumer,
    VerificationKeyError,
    load_verification_keys,
)
from ksi_mission_contracts.dispatch import ActivationReceiptV1, DispatchVerdict
from ksi_mission_contracts.edge_activation import activate_mission_dispatch_file
from ksi_mission_contracts.signing import KeyRegistry

_MAX_DISPATCH_RESPONSE_BYTES = 1024 * 1024
_MAX_RECEIPT_RESPONSE_BYTES = 64 * 1024
_MAX_BEARER_TOKEN_BYTES = 4096
_SAFE_DISPATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PrivateBearerTokenVerdict(StrEnum):
    LOADED = "LOADED"
    NOT_FOUND = "NOT_FOUND"
    UNSAFE_FILE = "UNSAFE_FILE"
    TOO_LARGE = "TOO_LARGE"
    INVALID_TOKEN = "INVALID_TOKEN"
    READ_FAILED = "READ_FAILED"


@dataclass(frozen=True, slots=True)
class PrivateBearerTokenLoadResult:
    verdict: PrivateBearerTokenVerdict
    # Present only for LOADED.  Never log or serialize this value.
    bearer_token: str | None = None


def _is_valid_bearer_token(value: str) -> bool:
    if not value or len(value.encode("ascii", errors="ignore")) > _MAX_BEARER_TOKEN_BYTES:
        return False
    return all(
        character.isascii()
        and (character.isalnum() or character in "-._~+/=")
        for character in value
    )


def load_private_bearer_token_file(path: Path) -> PrivateBearerTokenLoadResult:
    """Load a short bearer from an owner-only regular file without following links."""

    try:
        before = path.lstat()
    except FileNotFoundError:
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.NOT_FOUND)
    except OSError:
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.READ_FAILED)
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) & 0o077
    ):
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.UNSAFE_FILE)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.NOT_FOUND)
    except OSError:
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.UNSAFE_FILE)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) & 0o077
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.UNSAFE_FILE)
        if opened.st_size > _MAX_BEARER_TOKEN_BYTES + 2:
            return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.TOO_LARGE)
        chunks = bytearray()
        while len(chunks) <= _MAX_BEARER_TOKEN_BYTES + 2:
            chunk = os.read(descriptor, _MAX_BEARER_TOKEN_BYTES + 3 - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        raw = bytes(chunks)
    except OSError:
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.READ_FAILED)
    finally:
        os.close(descriptor)
    if len(raw) > _MAX_BEARER_TOKEN_BYTES + 2:
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.TOO_LARGE)
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    if b"\r" in raw or b"\n" in raw:
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.INVALID_TOKEN)
    try:
        token = raw.decode("ascii")
    except UnicodeDecodeError:
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.INVALID_TOKEN)
    if not _is_valid_bearer_token(token):
        return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.INVALID_TOKEN)
    return PrivateBearerTokenLoadResult(PrivateBearerTokenVerdict.LOADED, token)


@dataclass(frozen=True, slots=True)
class CoreDispatchHttpResponse:
    status_code: int
    body: bytes = b""
    content_type: str = ""


class CoreDispatchTransportError(RuntimeError):
    """A transport failure whose retryability does not reveal secret state."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__("Core dispatch transport failed")
        self.retryable = retryable


class EdgeDispatchCoreTransport(Protocol):
    def pull_next(self) -> CoreDispatchHttpResponse: ...

    def record_activation(
        self, dispatch_id: str, receipt: ActivationReceiptV1
    ) -> CoreDispatchHttpResponse: ...


@dataclass(frozen=True, slots=True)
class _HttpsOrigin:
    host: str
    port: int
    host_header: str


def _parse_https_origin(value: str) -> _HttpsOrigin:
    """Accept only an HTTPS origin, never a route or credential-bearing URL."""

    if not value or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value):
        raise ValueError("Core base URL must be printable ASCII")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or not parsed.netloc
        or parsed.hostname is None
    ):
        raise ValueError("Core base URL must be an HTTPS origin")
    try:
        port = parsed.port or 443
    except ValueError as error:
        raise ValueError("Core base URL port is invalid") from error
    host = parsed.hostname
    if not host or any(character.isspace() for character in host):
        raise ValueError("Core base URL host is invalid")
    try:
        host.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("Core base URL host must be ASCII") from error
    host_header = parsed.netloc
    return _HttpsOrigin(host=host, port=port, host_header=host_header)


def _parse_spki_pin(value: str) -> bytes:
    prefix = "sha256//"
    if not value.startswith(prefix):
        raise ValueError("Core SPKI pin must use sha256// base64 form")
    try:
        digest = base64.b64decode(value.removeprefix(prefix), validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError("Core SPKI pin is not canonical base64") from error
    if len(digest) != hashlib.sha256().digest_size:
        raise ValueError("Core SPKI pin must contain a SHA-256 digest")
    return digest


def _private_state_directory(path: Path) -> None:
    try:
        observed = path.lstat()
    except OSError as error:
        raise ContractInputError("dispatch state directory is unavailable") from error
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISDIR(observed.st_mode)
        or observed.st_uid != os.geteuid()
        or stat.S_IMODE(observed.st_mode) & 0o077
    ):
        raise ContractInputError("dispatch state directory is not private to the current user")


def _write_private_dispatch_candidate(state_directory: Path, body: bytes) -> Path:
    if not body or len(body) > _MAX_DISPATCH_RESPONSE_BYTES:
        raise ContractInputError("MissionDispatchEnvelope response is outside its byte limit")
    _private_state_directory(state_directory)
    descriptor: int | None = None
    path: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            dir=state_directory, prefix=".mission-dispatch-", suffix=".json"
        )
        path = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        return path
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        if path is not None:
            with suppress(OSError):
                path.unlink(missing_ok=True)
        raise ContractInputError("cannot persist MissionDispatchEnvelope candidate") from error


class PinnedHttpsEdgeDispatchTransport:
    """Core-only HTTPS transport with CA verification, SPKI pin, and no redirects."""

    def __init__(
        self,
        *,
        core_base_url: str,
        ca_bundle: Path,
        core_spki_pin: str,
        bearer_token: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not _is_valid_bearer_token(bearer_token):
            raise ValueError("bearer token is invalid")
        self._origin = _parse_https_origin(core_base_url)
        self._expected_spki_digest = _parse_spki_pin(core_spki_pin)
        try:
            self._context = ssl.create_default_context(cafile=str(ca_bundle))
        except (OSError, ssl.SSLError) as error:
            raise ValueError("Core CA bundle is unavailable") from error
        self._bearer_token = bearer_token
        self._timeout_seconds = timeout_seconds

    def _request(
        self, *, method: str, route: str, body: bytes | None, maximum_response_bytes: int
    ) -> CoreDispatchHttpResponse:
        if method not in {"GET", "POST"} or not route.startswith("/") or "#" in route:
            raise CoreDispatchTransportError(retryable=False)
        connection = http.client.HTTPSConnection(
            self._origin.host,
            self._origin.port,
            context=self._context,
            timeout=self._timeout_seconds,
        )
        try:
            # Connect and validate the SPKI before HTTP headers can carry the bearer.
            connection.connect()
            socket = connection.sock
            if socket is None:
                raise CoreDispatchTransportError(retryable=True)
            certificate_bytes = socket.getpeercert(binary_form=True)
            if not isinstance(certificate_bytes, bytes) or not certificate_bytes:
                raise CoreDispatchTransportError(retryable=True)
            try:
                certificate = x509.load_der_x509_certificate(certificate_bytes)
            except ValueError:
                raise CoreDispatchTransportError(retryable=False) from None
            subject_public_key_info = certificate.public_key().public_bytes(
                Encoding.DER, PublicFormat.SubjectPublicKeyInfo
            )
            actual_spki_digest = hashlib.sha256(subject_public_key_info).digest()
            if not hmac.compare_digest(actual_spki_digest, self._expected_spki_digest):
                raise CoreDispatchTransportError(retryable=False)
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._bearer_token}",
                "Host": self._origin.host_header,
            }
            if body is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(body))
            connection.request(method, route, body=body, headers=headers)
            response = connection.getresponse()
            payload = _read_bounded_http_response(response, maximum_response_bytes)
            return CoreDispatchHttpResponse(
                response.status,
                payload,
                response.getheader("Content-Type", ""),
            )
        except CoreDispatchTransportError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
            raise CoreDispatchTransportError(retryable=True) from None
        finally:
            connection.close()

    def pull_next(self) -> CoreDispatchHttpResponse:
        return self._request(
            method="GET",
            route="/v1/edge-sync/missions/next",
            body=None,
            maximum_response_bytes=_MAX_DISPATCH_RESPONSE_BYTES,
        )

    def record_activation(
        self, dispatch_id: str, receipt: ActivationReceiptV1
    ) -> CoreDispatchHttpResponse:
        if not _SAFE_DISPATCH_ID.fullmatch(dispatch_id) or receipt.dispatch_id != dispatch_id:
            raise CoreDispatchTransportError(retryable=False)
        body = json.dumps(
            receipt.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self._request(
            method="POST",
            route=f"/v1/edge-sync/missions/{dispatch_id}/activation-receipts",
            body=body,
            maximum_response_bytes=_MAX_RECEIPT_RESPONSE_BYTES,
        )


def _read_bounded_http_response(
    response: http.client.HTTPResponse, maximum_response_bytes: int
) -> bytes:
    """Read through EOF while retaining at most one byte beyond a strict cap.

    ``HTTPResponse.read(n)`` callers must not assume that one read always
    returns the full request size.  Continue after short reads, including one
    final single-byte probe at the cap, so a peer cannot hide an oversized
    response behind fragmented TCP/TLS delivery.
    """

    if maximum_response_bytes < 0:
        raise CoreDispatchTransportError(retryable=False)
    chunks: list[bytes] = []
    total = 0
    while True:
        requested = min(64 * 1024, maximum_response_bytes + 1 - total)
        # At the exact cap, request one more byte solely to distinguish EOF
        # from an oversized response.  The requested value is always positive
        # because an oversized response exits below.
        chunk = response.read(requested)
        if not chunk:
            return b"".join(chunks)
        if not isinstance(chunk, bytes):
            raise CoreDispatchTransportError(retryable=False)
        total += len(chunk)
        if total > maximum_response_bytes:
            raise CoreDispatchTransportError(retryable=False)
        chunks.append(chunk)


class EdgeDispatchSyncVerdict(StrEnum):
    NO_MISSION = "NO_MISSION"
    PULL_RETRYABLE_FAILURE = "PULL_RETRYABLE_FAILURE"
    PULL_REJECTED = "PULL_REJECTED"
    ACTIVATION_REJECTED = "ACTIVATION_REJECTED"
    ACTIVATED_AND_RECORDED = "ACTIVATED_AND_RECORDED"
    ACTIVATED_RECEIPT_PENDING = "ACTIVATED_RECEIPT_PENDING"
    ACTIVATED_RECEIPT_REJECTED = "ACTIVATED_RECEIPT_REJECTED"


@dataclass(frozen=True, slots=True)
class EdgeDispatchSyncResult:
    verdict: EdgeDispatchSyncVerdict
    dispatch_verdict: DispatchVerdict | None = None
    activation_reused: bool = False
    http_status: int | None = None


def _is_json_content_type(value: str) -> bool:
    return value.split(";", 1)[0].strip().lower() == "application/json"


def synchronize_edge_dispatch_once(
    *,
    transport: EdgeDispatchCoreTransport,
    registry: KeyRegistry,
    state_directory: Path,
    edge_device_id: str,
    runtime_version: str,
    now: datetime | None = None,
) -> EdgeDispatchSyncResult:
    """Perform one pull/activate/receipt attempt without a frame-loop dependency."""

    try:
        pulled = transport.pull_next()
    except CoreDispatchTransportError as error:
        return EdgeDispatchSyncResult(
            EdgeDispatchSyncVerdict.PULL_RETRYABLE_FAILURE
            if error.retryable
            else EdgeDispatchSyncVerdict.PULL_REJECTED
        )
    if pulled.status_code == 204:
        return EdgeDispatchSyncResult(EdgeDispatchSyncVerdict.NO_MISSION, http_status=204)
    if pulled.status_code != 200:
        return EdgeDispatchSyncResult(
            EdgeDispatchSyncVerdict.PULL_RETRYABLE_FAILURE
            if pulled.status_code >= 500
            else EdgeDispatchSyncVerdict.PULL_REJECTED,
            http_status=pulled.status_code,
        )
    if not _is_json_content_type(pulled.content_type) or not pulled.body:
        return EdgeDispatchSyncResult(EdgeDispatchSyncVerdict.PULL_REJECTED, http_status=200)
    if len(pulled.body) > _MAX_DISPATCH_RESPONSE_BYTES:
        return EdgeDispatchSyncResult(EdgeDispatchSyncVerdict.PULL_REJECTED, http_status=200)
    candidate_path: Path | None = None
    try:
        candidate_path = _write_private_dispatch_candidate(state_directory, pulled.body)
        activation = activate_mission_dispatch_file(
            candidate_path,
            consumer=MissionContractConsumer(registry=registry, state_dir=state_directory),
            registry=registry,
            expected_edge_device_id=edge_device_id,
            runtime_version=runtime_version,
            now=now,
        )
    except (ContractInputError, VerificationKeyError, ValueError):
        return EdgeDispatchSyncResult(EdgeDispatchSyncVerdict.ACTIVATION_REJECTED)
    finally:
        if candidate_path is not None:
            # The candidate has already been consumed; a leftover private temp
            # file is not a reason to revoke the local activation.
            with suppress(OSError):
                candidate_path.unlink(missing_ok=True)
    if not activation.activated or activation.activation_receipt is None:
        return EdgeDispatchSyncResult(
            EdgeDispatchSyncVerdict.ACTIVATION_REJECTED,
            dispatch_verdict=activation.dispatch_verdict,
            activation_reused=activation.reused_activation,
        )
    try:
        recorded = transport.record_activation(
            activation.activation_receipt.dispatch_id, activation.activation_receipt
        )
    except CoreDispatchTransportError as error:
        return EdgeDispatchSyncResult(
            EdgeDispatchSyncVerdict.ACTIVATED_RECEIPT_PENDING
            if error.retryable
            else EdgeDispatchSyncVerdict.ACTIVATED_RECEIPT_REJECTED,
            dispatch_verdict=activation.dispatch_verdict,
            activation_reused=activation.reused_activation,
        )
    if recorded.status_code in {200, 201}:
        return EdgeDispatchSyncResult(
            EdgeDispatchSyncVerdict.ACTIVATED_AND_RECORDED,
            dispatch_verdict=activation.dispatch_verdict,
            activation_reused=activation.reused_activation,
            http_status=recorded.status_code,
        )
    return EdgeDispatchSyncResult(
        EdgeDispatchSyncVerdict.ACTIVATED_RECEIPT_PENDING
        if recorded.status_code >= 500
        else EdgeDispatchSyncVerdict.ACTIVATED_RECEIPT_REJECTED,
        dispatch_verdict=activation.dispatch_verdict,
        activation_reused=activation.reused_activation,
        http_status=recorded.status_code,
    )


def _parse_now(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must be tz-aware RFC3339")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """CLI for an activation-time Edge control-plane worker or HIL operator."""

    parser = argparse.ArgumentParser(
        description="Pull, verify, activate, and acknowledge one Edge MissionDispatchEnvelope"
    )
    parser.add_argument("--core-base-url", required=True)
    parser.add_argument("--tls-ca-bundle", type=Path, required=True)
    parser.add_argument("--core-spki-pin", required=True)
    parser.add_argument("--bearer-token-file", type=Path, required=True)
    parser.add_argument("--keys-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--edge-device-id", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--now", help="RFC3339 replay/HIL verification time")
    args = parser.parse_args(argv)

    token = load_private_bearer_token_file(args.bearer_token_file)
    if token.verdict is not PrivateBearerTokenVerdict.LOADED or token.bearer_token is None:
        print(json.dumps({"verdict": "TOKEN_LOAD_FAILED", "tokenVerdict": token.verdict.value}))
        return 3
    try:
        registry = load_verification_keys(args.keys_dir)
        transport = PinnedHttpsEdgeDispatchTransport(
            core_base_url=args.core_base_url,
            ca_bundle=args.tls_ca_bundle,
            core_spki_pin=args.core_spki_pin,
            bearer_token=token.bearer_token,
        )
        result = synchronize_edge_dispatch_once(
            transport=transport,
            registry=registry,
            state_directory=args.state_dir,
            edge_device_id=args.edge_device_id,
            runtime_version=args.runtime_version,
            now=_parse_now(args.now),
        )
    except (ContractInputError, VerificationKeyError, ValueError):
        print(json.dumps({"verdict": "CONFIGURATION_ERROR"}))
        return 3
    print(
        json.dumps(
            {
                "verdict": result.verdict.value,
                "dispatchVerdict": result.dispatch_verdict.value
                if result.dispatch_verdict is not None
                else None,
                "activationReused": result.activation_reused,
                "httpStatus": result.http_status,
            },
            sort_keys=True,
        )
    )
    return (
        0
        if result.verdict
        in {EdgeDispatchSyncVerdict.NO_MISSION, EdgeDispatchSyncVerdict.ACTIVATED_AND_RECORDED}
        else 2
    )


__all__ = [
    "CoreDispatchHttpResponse",
    "CoreDispatchTransportError",
    "EdgeDispatchCoreTransport",
    "EdgeDispatchSyncResult",
    "EdgeDispatchSyncVerdict",
    "PinnedHttpsEdgeDispatchTransport",
    "PrivateBearerTokenLoadResult",
    "PrivateBearerTokenVerdict",
    "load_private_bearer_token_file",
    "main",
    "synchronize_edge_dispatch_once",
]
