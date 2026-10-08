"""Concrete fail-closed bridge transports for candidate DJI adapters.

These transports only move provider-neutral, typed gateway operations. They do not expose
flight, gimbal, capture, delete, format, or Waypoint Action surfaces.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from ksi_dji_gateway.domain.capabilities import GatewayTransport, IntegrationPath
from ksi_dji_gateway.domain.models import ProviderReceipt
from ksi_dji_gateway.domain.validation import IDENTIFIER, SHA256, validate_identifiers
from ksi_dji_gateway.errors import GatewayTransportError

_MAX_HTTPS_RESPONSE_BYTES = 1024 * 1024
_MAX_UNIX_MESSAGE_BYTES = 64 * 1024
_SIGNAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
_ROUTE_STATUS_FIELDS = {
    "schemaVersion",
    "signalId",
    "observedAt",
    "integrationPath",
    "canonicalCapabilityId",
    "subjectPortId",
    "edgeDeviceId",
    "psdkInitialized",
    "mopConnected",
    "handlerRegistered",
}


class BridgeOperation(StrEnum):
    WAYLINE_UPLOAD_NO_START = "WAYLINE_UPLOAD_NO_START"
    SIGNED_CONTRACT_TRANSFER = "SIGNED_CONTRACT_TRANSFER"
    EDGE_BUNDLE_UPLOAD = "EDGE_BUNDLE_UPLOAD"
    MEDIA_READ_ONE = "MEDIA_READ_ONE"
    MEDIA_UPLOAD_SYNTHETIC = "MEDIA_UPLOAD_SYNTHETIC"


@dataclass(frozen=True, slots=True)
class PsdkRouteStatus:
    """Exact status facts returned by the local PSDK companion.

    This type intentionally has no final availability field.  Callers must
    derive availability from all three facts.
    """

    signal_id: str
    observed_at: str
    psdk_initialized: bool
    mop_connected: bool
    handler_registered: bool


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _exact_json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        raw = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_json_fields,
            parse_constant=_reject_non_finite_json,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise GatewayTransportError("PSDK unix bridge response가 exact JSON이 아니다") from exc
    if not isinstance(raw, Mapping):
        raise GatewayTransportError("PSDK unix bridge response 최상위는 object여야 한다")
    return raw


@dataclass(frozen=True, slots=True)
class AdapterRuntimeConfig:
    adapter_id: str
    integration_path: IntegrationPath
    transport: GatewayTransport
    organization_id: str
    site_id: str
    gateway_device_id: str
    edge_device_id: str
    endpoint: str
    tls_certificate_sha256: str | None = None
    credential_file: Path | None = None
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if IDENTIFIER.fullmatch(self.adapter_id) is None:
            raise ValueError("adapter_id는 경로-안전 식별자여야 한다")
        validate_identifiers(
            self.organization_id,
            self.site_id,
            self.gateway_device_id,
            self.edge_device_id,
        )
        if self.gateway_device_id == self.edge_device_id:
            raise ValueError("Gateway와 Edge 장치 신원은 달라야 한다")
        if not (0 < self.timeout_s <= 60):
            raise ValueError("adapter timeout은 0초 초과 60초 이하여야 한다")
        parsed = urlsplit(self.endpoint)
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("adapter endpoint에 query/fragment/userinfo를 넣을 수 없다")
        if parsed.scheme == "https":
            if not parsed.hostname:
                raise ValueError("HTTPS adapter endpoint에는 host가 필요하다")
            if (
                self.tls_certificate_sha256 is None
                or SHA256.fullmatch(self.tls_certificate_sha256) is None
            ):
                raise ValueError("HTTPS adapter에는 certificate SHA-256 pin이 필요하다")
        elif parsed.scheme == "unix":
            if self.integration_path is not IntegrationPath.PSDK_MANIFOLD:
                raise ValueError("unix bridge는 PSDK_MANIFOLD에서만 허용한다")
            if not parsed.path.startswith("/") or parsed.netloc:
                raise ValueError("unix endpoint는 unix:///absolute/path 형식이어야 한다")
            if self.tls_certificate_sha256 is not None or self.credential_file is not None:
                raise ValueError("unix bridge는 TLS pin이나 credential file을 받지 않는다")
        else:
            raise ValueError("adapter endpoint는 https 또는 unix scheme이어야 한다")
        if self.credential_file is not None:
            _validate_secret_file(self.credential_file)

    @property
    def configuration_ready(self) -> bool:
        return True

    def credential(self) -> str | None:
        if self.credential_file is None:
            return None
        _validate_secret_file(self.credential_file)
        value = self.credential_file.read_text(encoding="utf-8").strip()
        if not value or any(character.isspace() for character in value):
            raise GatewayTransportError("credential file은 단일 비공백 token이어야 한다")
        return value


def _validate_secret_file(path: Path) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("credential file symlink는 허용하지 않는다")
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("credential file을 확인할 수 없다") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("credential file은 현재 사용자 소유의 0600 일반 파일이어야 한다")


class BridgeClient(Protocol):
    def invoke(
        self,
        *,
        operation: BridgeOperation,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> ProviderReceipt: ...


def _receipt_from_payload(payload: Any) -> ProviderReceipt:
    if not isinstance(payload, Mapping):
        raise GatewayTransportError("bridge response 최상위는 object여야 한다")
    allowed = {"provider_operation_id", "accepted_at", "item_count", "manifest_ref"}
    if set(payload) != allowed:
        raise GatewayTransportError("bridge response 필드가 provider receipt와 다르다")
    try:
        return ProviderReceipt(
            provider_operation_id=payload["provider_operation_id"],
            accepted_at=payload["accepted_at"],
            item_count=payload["item_count"],
            manifest_ref=payload["manifest_ref"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GatewayTransportError(f"bridge receipt가 유효하지 않다: {exc}") from exc


class HttpsJsonBridgeClient:
    """POST one typed operation over pinned-certificate HTTPS."""

    def __init__(self, config: AdapterRuntimeConfig) -> None:
        if urlsplit(config.endpoint).scheme != "https":
            raise ValueError("HttpsJsonBridgeClient에는 https endpoint가 필요하다")
        self._config = config

    def invoke(
        self,
        *,
        operation: BridgeOperation,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> ProviderReceipt:
        parsed = urlsplit(self._config.endpoint)
        hostname = parsed.hostname
        if hostname is None:  # constructor validation makes this unreachable
            raise GatewayTransportError("HTTPS bridge host가 없다")
        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(
            hostname,
            port=parsed.port,
            timeout=self._config.timeout_s,
            context=context,
        )
        body = json.dumps(
            {"operation": operation.value, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        path = f"{parsed.path.rstrip('/')}/{operation.value.lower()}"
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        credential = self._config.credential()
        if credential is not None:
            headers["Authorization"] = f"Bearer {credential}"
        try:
            connection.connect()
            sock = connection.sock
            if sock is None:
                raise GatewayTransportError("HTTPS bridge socket을 열지 못했다")
            certificate = sock.getpeercert(binary_form=True)
            if certificate is None:
                raise GatewayTransportError("HTTPS bridge certificate를 읽지 못했다")
            actual_pin = hashlib.sha256(certificate).hexdigest()
            if actual_pin != self._config.tls_certificate_sha256:
                raise GatewayTransportError("HTTPS bridge certificate pin이 다르다")
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read(_MAX_HTTPS_RESPONSE_BYTES + 1)
            if len(response_body) > _MAX_HTTPS_RESPONSE_BYTES:
                raise GatewayTransportError("HTTPS bridge response가 1 MiB를 넘었다")
            if not 200 <= response.status < 300:
                raise GatewayTransportError(f"HTTPS bridge가 HTTP {response.status}를 반환했다")
            return _receipt_from_payload(json.loads(response_body))
        except (OSError, ssl.SSLError, json.JSONDecodeError) as exc:
            raise GatewayTransportError(f"HTTPS bridge 호출 실패: {exc}") from exc
        finally:
            connection.close()


class UnixJsonBridgeClient:
    """Exchange one bounded JSON line with the local Manifold PSDK companion."""

    def __init__(self, config: AdapterRuntimeConfig) -> None:
        parsed = urlsplit(config.endpoint)
        if parsed.scheme != "unix":
            raise ValueError("UnixJsonBridgeClient에는 unix endpoint가 필요하다")
        self._config = config
        self._socket_path = parsed.path

    def invoke(
        self,
        *,
        operation: BridgeOperation,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> ProviderReceipt:
        return _receipt_from_payload(
            self._exchange(
                {
                    "operation": operation.value,
                    "idempotency_key": idempotency_key,
                    "payload": payload,
                }
            )
        )

    def route_status(
        self,
        *,
        subject_port_id: str,
        edge_device_id: str,
    ) -> PsdkRouteStatus:
        """Read and validate one exact PSDK_MANIFOLD/EDGE_UPLINK status."""

        raw = self._exchange(
            {
                "operation": "ROUTE_STATUS_V1",
                "integrationPath": "PSDK_MANIFOLD",
                "canonicalCapabilityId": "EDGE_UPLINK",
                "subjectPortId": subject_port_id,
                "edgeDeviceId": edge_device_id,
                "requiredHandler": "EDGE_BUNDLE_UPLOAD",
            }
        )
        if set(raw) != _ROUTE_STATUS_FIELDS:
            raise GatewayTransportError("PSDK route-status response schema가 exact하지 않다")
        bool_names = ("psdkInitialized", "mopConnected", "handlerRegistered")
        if (
            raw["schemaVersion"] != "1.0"
            or raw["integrationPath"] != "PSDK_MANIFOLD"
            or raw["canonicalCapabilityId"] != "EDGE_UPLINK"
            or raw["subjectPortId"] != subject_port_id
            or raw["edgeDeviceId"] != edge_device_id
            or not isinstance(raw["signalId"], str)
            or _SIGNAL_ID.fullmatch(raw["signalId"]) is None
            or not isinstance(raw["observedAt"], str)
            or not all(type(raw[name]) is bool for name in bool_names)
        ):
            raise GatewayTransportError("PSDK route-status identity/state가 일치하지 않는다")
        try:
            observed_at = datetime.fromisoformat(raw["observedAt"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise GatewayTransportError("PSDK route-status observedAt이 RFC3339가 아니다") from exc
        if observed_at.tzinfo is None or observed_at.utcoffset() != timedelta(0):
            raise GatewayTransportError("PSDK route-status observedAt이 UTC가 아니다")
        return PsdkRouteStatus(
            signal_id=raw["signalId"],
            observed_at=raw["observedAt"],
            psdk_initialized=raw["psdkInitialized"],
            mop_connected=raw["mopConnected"],
            handler_registered=raw["handlerRegistered"],
        )

    def _exchange(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Own all production Unix socket, framing, bounds and JSON parsing."""

        request = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if len(request) > _MAX_UNIX_MESSAGE_BYTES:
            raise GatewayTransportError("PSDK unix bridge request가 64 KiB를 넘었다")
        response = bytearray()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self._config.timeout_s)
                client.connect(self._socket_path)
                client.sendall(request)
                client.shutdown(socket.SHUT_WR)
                while len(response) <= _MAX_UNIX_MESSAGE_BYTES:
                    chunk = client.recv(min(65536, _MAX_UNIX_MESSAGE_BYTES + 1 - len(response)))
                    if not chunk:
                        break
                    response.extend(chunk)
        except OSError as exc:
            raise GatewayTransportError(f"PSDK unix bridge 호출 실패: {exc}") from exc
        if len(response) > _MAX_UNIX_MESSAGE_BYTES:
            raise GatewayTransportError("PSDK unix bridge response가 64 KiB를 넘었다")
        if not response:
            raise GatewayTransportError("PSDK unix bridge response가 비어 있다")
        return _exact_json_object(bytes(response))


__all__ = [
    "AdapterRuntimeConfig",
    "BridgeClient",
    "BridgeOperation",
    "HttpsJsonBridgeClient",
    "PsdkRouteStatus",
    "UnixJsonBridgeClient",
]
