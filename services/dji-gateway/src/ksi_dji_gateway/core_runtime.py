"""Authenticated, fail-closed Core transport for CAP-5 runtime operations.

Production endpoints require HTTPS plus a certificate SHA-256 pin. Plain HTTP
exists only for an explicitly enabled loopback software-seam test and can never
address a non-loopback host.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import ssl
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import SplitResult, urlsplit

from ksi_dji_gateway.errors import CapabilityUnavailableError, GatewayTransportError
from ksi_dji_gateway.routing.capability_router import (
    RuntimeRoutePreflightDecision,
    RuntimeRoutePreflightRequest,
)

_MAX_RESPONSE_BYTES = 64 * 1024
_PREFLIGHT_PATH = "/v1/capability-runtime/preflight"
_OBSERVATION_PATH = "/v1/capability-runtime/observations"
_DECISION_FIELDS = {
    "durableAuthorityValid",
    "currentRuntimeReady",
    "currentMissionPolicyAllows",
    "operationallyUsable",
    "newRouteInvocationAllowed",
    "reason",
    "existingSignedMissionContractEffect",
}


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _validate_token_file(path: Path) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Core token file symlink는 허용하지 않는다")
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("Core token file을 확인할 수 없다") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Core token file은 현재 사용자 소유의 0600 일반 파일이어야 한다")


@dataclass(frozen=True, slots=True)
class CoreRuntimeTransportConfig:
    core_url: str
    token_file: Path
    tls_certificate_sha256: str | None = None
    timeout_s: float = 5.0
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.core_url)
        if (
            parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or not parsed.hostname
        ):
            raise ValueError("Core URL은 userinfo/query/path 없는 origin이어야 한다")
        if not 0 < self.timeout_s <= 30:
            raise ValueError("Core timeout은 0초 초과 30초 이하여야 한다")
        if parsed.scheme == "https":
            if (
                self.tls_certificate_sha256 is None
                or len(self.tls_certificate_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.tls_certificate_sha256)
            ):
                raise ValueError("production Core HTTPS에는 lowercase certificate pin이 필요하다")
        elif not (
            parsed.scheme == "http"
            and self.allow_loopback_http
            and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
            and self.tls_certificate_sha256 is None
        ):
            raise ValueError("Core transport는 pinned HTTPS여야 한다 (명시적 loopback test 제외)")
        _validate_token_file(self.token_file)

    def token(self) -> str:
        _validate_token_file(self.token_file)
        token = self.token_file.read_text(encoding="utf-8").strip()
        if not token or any(character.isspace() for character in token):
            raise GatewayTransportError("Core token file은 단일 비공백 token이어야 한다")
        return token


class _CoreJsonClient:
    def __init__(self, config: CoreRuntimeTransportConfig) -> None:
        self._config = config
        self._origin = urlsplit(config.core_url)

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        connection = self._connection(self._origin)
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        try:
            connection.connect()
            if self._origin.scheme == "https":
                sock = connection.sock
                certificate = (
                    cast(ssl.SSLSocket, sock).getpeercert(binary_form=True)
                    if sock is not None
                    else None
                )
                if certificate is None:
                    raise GatewayTransportError("Core TLS certificate를 읽지 못했다")
                if hashlib.sha256(certificate).hexdigest() != self._config.tls_certificate_sha256:
                    raise GatewayTransportError("Core TLS certificate pin이 다르다")
            connection.request(
                "POST",
                path,
                body=body,
                headers={
                    "Authorization": f"Bearer {self._config.token()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            response_body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(response_body) > _MAX_RESPONSE_BYTES:
                raise GatewayTransportError("Core response가 64 KiB를 넘었다")
            if not 200 <= response.status < 300:
                raise GatewayTransportError(f"Core가 HTTP {response.status}를 반환했다")
            return json.loads(
                response_body,
                object_pairs_hook=_reject_duplicate_json_fields,
                parse_constant=_reject_non_finite_json,
            )
        except (
            OSError,
            ssl.SSLError,
            http.client.HTTPException,
            ValueError,
        ) as exc:
            raise GatewayTransportError(f"Core runtime transport 실패: {exc}") from exc
        finally:
            connection.close()

    def _connection(self, parsed: SplitResult) -> http.client.HTTPConnection:
        hostname = parsed.hostname
        if hostname is None:
            raise GatewayTransportError("Core runtime host가 없다")
        if parsed.scheme == "https":
            return http.client.HTTPSConnection(
                hostname,
                parsed.port,
                timeout=self._config.timeout_s,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(hostname, parsed.port, timeout=self._config.timeout_s)


class HttpCoreRuntimeRoutePreflight:
    """Real network implementation of the Gateway's CAP-5 preflight port."""

    def __init__(self, config: CoreRuntimeTransportConfig) -> None:
        self._client = _CoreJsonClient(config)

    def evaluate(self, request: RuntimeRoutePreflightRequest) -> RuntimeRoutePreflightDecision:
        payload = {
            "organizationId": request.organization_id,
            "siteId": request.site_id,
            "gatewayDeviceId": request.gateway_device_id,
            "edgeDeviceId": request.edge_device_id,
            "canonicalCapability": request.canonical_capability.value,
            "integrationPath": request.integration_path.value,
            "subjectPortId": request.subject_port_id,
            "transport": request.transport.value,
            "hardwareModel": request.hardware_model,
            "firmwareVersion": request.firmware_version,
            "missionId": request.mission_id,
            "operation": request.operation.value,
            "idempotencyKey": request.idempotency_key,
            "activationAuthorizationId": request.activation_authorization_id,
        }
        try:
            raw = self._client.post(_PREFLIGHT_PATH, payload)
            if not isinstance(raw, Mapping) or set(raw) != _DECISION_FIELDS:
                raise GatewayTransportError("Core preflight response schema가 exact하지 않다")
            bool_fields = tuple(
                raw[name]
                for name in (
                    "durableAuthorityValid",
                    "currentRuntimeReady",
                    "currentMissionPolicyAllows",
                    "operationallyUsable",
                    "newRouteInvocationAllowed",
                )
            )
            if not all(type(value) is bool for value in bool_fields):
                raise GatewayTransportError("Core preflight boolean field가 유효하지 않다")
            if bool_fields[3] is not bool_fields[4]:
                raise GatewayTransportError("Core preflight invocation decision이 모순이다")
            return RuntimeRoutePreflightDecision(
                durable_authority_valid=bool_fields[0],
                current_runtime_ready=bool_fields[1],
                current_mission_policy_allows=bool_fields[2],
                operationally_usable=bool_fields[3],
            )
        except (GatewayTransportError, TypeError, ValueError, KeyError) as exc:
            raise CapabilityUnavailableError(
                "Core runtime preflight가 fail-closed로 실패했다"
            ) from exc


class HttpCoreRuntimeObservationPublisher:
    """Publish one canonical CAP-5 observation payload; Core remains validator."""

    def __init__(self, config: CoreRuntimeTransportConfig) -> None:
        self._client = _CoreJsonClient(config)

    def publish(self, observation: Mapping[str, Any]) -> Mapping[str, Any]:
        raw = self._client.post(_OBSERVATION_PATH, observation)
        if (
            not isinstance(raw, Mapping)
            or set(raw) != {"disposition", "observation"}
            or raw["disposition"] not in {"RECORDED", "EXACT_RETRY"}
            or not isinstance(raw["observation"], Mapping)
        ):
            raise GatewayTransportError("Core observation response schema가 exact하지 않다")
        return raw


__all__ = [
    "CoreRuntimeTransportConfig",
    "HttpCoreRuntimeObservationPublisher",
    "HttpCoreRuntimeRoutePreflight",
]
