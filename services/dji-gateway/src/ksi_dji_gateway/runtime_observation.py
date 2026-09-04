"""Production-facing route observation producer seams.

The first adapter probes a local PSDK companion over Unix domain socket. An
AVAILABLE observation requires three explicit facts from that companion:
PSDK initialized, MOP connected, and the exact EDGE_BUNDLE_UPLOAD handler
registered. Process/socket/config presence alone is never sufficient.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from ksi_dji_gateway.adapters.transport import PsdkRouteStatus
from ksi_dji_gateway.errors import GatewayTransportError

_SIGNAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")


class RuntimeObservationPublisher(Protocol):
    def publish(self, observation: Mapping[str, Any]) -> Mapping[str, Any]: ...


class PsdkRouteStatusClient(Protocol):
    def route_status(self, *, subject_port_id: str, edge_device_id: str) -> PsdkRouteStatus: ...


@dataclass(frozen=True, slots=True)
class PsdkMopObservationConfig:
    organization_id: str
    site_id: str
    edge_device_id: str
    subject_port_id: str
    configured_deployment_digest: str
    equipment_scope_digest: str
    runtime_build_digest: str
    freshness_policy_id: str
    freshness_policy_digest: str
    producer_principal_id: str
    freshness_ttl_s: int
    minimum_refresh_margin_s: float

    def __post_init__(self) -> None:
        identifiers = (
            self.organization_id,
            self.site_id,
            self.edge_device_id,
            self.subject_port_id,
            self.freshness_policy_id,
            self.producer_principal_id,
        )
        if any(not value or value != value.strip() for value in identifiers):
            raise ValueError("PSDK observation scope 식별자는 exact non-empty여야 한다")
        if self.organization_id == "legacy":
            raise ValueError("legacy organization은 runtime observation을 만들 수 없다")
        for digest in (
            self.configured_deployment_digest,
            self.equipment_scope_digest,
            self.runtime_build_digest,
            self.freshness_policy_digest,
        ):
            if (
                len(digest) != 71
                or not digest.startswith("sha256:")
                or any(c not in "0123456789abcdef" for c in digest[7:])
            ):
                raise ValueError("observation digest는 sha256:<64 lowercase hex>여야 한다")
        if type(self.freshness_ttl_s) is not int or not 0 < self.freshness_ttl_s <= 300:
            raise ValueError("PSDK freshness TTL은 명시적으로 1..300초여야 한다")
        if (
            type(self.minimum_refresh_margin_s) not in {int, float}
            or not 0 < float(self.minimum_refresh_margin_s) < self.freshness_ttl_s
        ):
            raise ValueError("PSDK refresh margin은 TTL 안의 명시적 양수여야 한다")
        policy_payload = {
            "schemaVersion": "1.0",
            "freshnessPolicyId": self.freshness_policy_id,
            "observationTtlSeconds": self.freshness_ttl_s,
            "minimumRefreshMarginSeconds": float(self.minimum_refresh_margin_s),
        }
        expected_policy_digest = "sha256:" + hashlib.sha256(
            json.dumps(policy_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.freshness_policy_digest != expected_policy_digest:
            raise ValueError(
                "PSDK freshness policy digest가 TTL/refresh margin canonical content와 다르다"
            )


class PsdkMopRuntimeObservationProducer:
    """Probe one exact PSDK/MOP EDGE_UPLINK route and publish its observation."""

    def __init__(
        self,
        config: PsdkMopObservationConfig,
        *,
        client: PsdkRouteStatusClient,
        publisher: RuntimeObservationPublisher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._client = client
        self._publisher = publisher
        self._clock = clock
        self._shutdown = threading.Event()

    def prepare_start(self) -> None:
        """Open a new publication epoch after an explicit runner start."""

        self._shutdown.clear()

    def request_shutdown(self) -> None:
        """Fence every publication that has not crossed the publisher boundary."""

        self._shutdown.set()

    def observe_once(self) -> Mapping[str, Any]:
        try:
            signal = self._client.route_status(
                subject_port_id=self._config.subject_port_id,
                edge_device_id=self._config.edge_device_id,
            )
            if _SIGNAL_ID.fullmatch(signal.signal_id) is None:
                raise GatewayTransportError("PSDK route-status signalId가 유효하지 않다")
            observed_at = self._parse_signal_time(signal.observed_at)
        except GatewayTransportError as exc:
            observed_at = self._utc(self._clock())
            signal_id = f"probe-error-{uuid.uuid4().hex}"
            observation = self._observation(
                signal_id=signal_id,
                observed_at=observed_at,
                available=False,
                source=f"psdk-mop-probe-error:{type(exc).__name__}:{signal_id}",
            )
        else:
            available = (
                signal.psdk_initialized and signal.mop_connected and signal.handler_registered
            )
            observation = self._observation(
                signal_id=signal.signal_id,
                observed_at=observed_at,
                available=available,
                source=f"psdk-mop-route-signal:{signal.signal_id}",
            )
        # A route probe may have been in flight when shutdown began.  Do not
        # let its stale AVAILABLE result cross the authoritative Core ingress
        # after the runner has established its shutdown boundary.
        if self._shutdown.is_set():
            raise GatewayTransportError("runtime observation shutdown is in progress")
        self._publisher.publish(observation)
        return observation

    def _observation(
        self,
        *,
        signal_id: str,
        observed_at: datetime,
        available: bool,
        source: str,
    ) -> dict[str, Any]:
        digest = hashlib.sha256(signal_id.encode()).hexdigest()[:24]
        return {
            "observationId": f"psdk-mop-{digest}",
            "organizationId": self._config.organization_id,
            "siteId": self._config.site_id,
            "configuredDeploymentDigest": self._config.configured_deployment_digest,
            "subjectKind": "EDGE_ROUTE_PORT",
            "subjectDeviceIds": [self._config.edge_device_id],
            "subjectPortId": self._config.subject_port_id,
            "integrationPath": "PSDK_MANIFOLD",
            "canonicalCapabilityId": "EDGE_UPLINK",
            "equipmentScopeDigest": self._config.equipment_scope_digest,
            "runtimeBuildDigest": self._config.runtime_build_digest,
            "availability": ("REPORTED_AVAILABLE" if available else "REPORTED_UNAVAILABLE"),
            "observedAt": observed_at.isoformat().replace("+00:00", "Z"),
            "expiresAt": (observed_at + timedelta(seconds=self._config.freshness_ttl_s))
            .isoformat()
            .replace("+00:00", "Z"),
            "freshnessPolicyId": self._config.freshness_policy_id,
            "freshnessPolicyDigest": self._config.freshness_policy_digest,
            "producerPrincipalId": self._config.producer_principal_id,
            "producerPrincipalKind": "EDGE_DEVICE",
            "sourceObservationRef": source,
        }

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise GatewayTransportError("observation clock은 UTC tz-aware여야 한다")
        return value.astimezone(UTC)

    @classmethod
    def _parse_signal_time(cls, value: Any) -> datetime:
        if not isinstance(value, str):
            raise GatewayTransportError("PSDK signal observedAt이 문자열이 아니다")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GatewayTransportError("PSDK signal observedAt이 RFC3339가 아니다") from exc
        return cls._utc(parsed)


__all__ = [
    "PsdkMopObservationConfig",
    "PsdkMopRuntimeObservationProducer",
    "PsdkRouteStatusClient",
    "RuntimeObservationPublisher",
]
