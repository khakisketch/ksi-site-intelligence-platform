"""Select one enabled, independently VERIFIED port for a single capability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ksi_dji_gateway.domain.capabilities import (
    Capability,
    CapabilityEvidence,
    CapabilityRegistry,
    GatewayTransport,
)
from ksi_dji_gateway.errors import CapabilityUnavailableError
from ksi_dji_gateway.ports import RoutablePort


@dataclass(frozen=True, slots=True)
class CapabilityRoute:
    port: RoutablePort
    priority: int

    def __post_init__(self) -> None:
        if self.priority < 0:
            raise ValueError("route priority는 0 이상이어야 한다")


class CapabilityRouter:
    """Provider 전체 선택을 금지하고 기능 하나마다 fail-closed로 선택한다."""

    def __init__(
        self,
        *,
        routes: tuple[CapabilityRoute, ...],
        registry: CapabilityRegistry,
        feature_flags: Mapping[Capability, bool] | None = None,
    ) -> None:
        ids = [route.port.port_id for route in routes]
        if len(ids) != len(set(ids)):
            raise ValueError("port_id는 중복될 수 없다")
        self._routes = tuple(sorted(routes, key=lambda route: route.priority))
        self._registry = registry
        # 누락된 flag는 OFF다. HIL 증거가 생겨도 운영자가 기능을 별도로 열어야 한다.
        self._feature_flags = dict(feature_flags or {})

    def select(
        self,
        capability: Capability,
        *,
        organization_id: str,
        site_id: str,
        gateway_device_id: str,
        edge_device_id: str,
        hardware_model: str,
        firmware_version: str,
        allowed_transports: frozenset[GatewayTransport],
    ) -> tuple[RoutablePort, CapabilityEvidence]:
        if not self._feature_flags.get(capability, False):
            raise CapabilityUnavailableError(f"{capability.value} feature flag가 꺼져 있다")

        rejected: list[str] = []
        for route in self._routes:
            port = route.port
            if capability not in port.capabilities or port.transport not in allowed_transports:
                continue
            if not port.configuration_ready:
                rejected.append(f"{port.port_id} runtime configuration이 준비되지 않았다")
                continue
            if (
                port.organization_id != organization_id
                or port.site_id != site_id
                or port.gateway_device_id != gateway_device_id
                or port.edge_device_id != edge_device_id
            ):
                rejected.append(f"{port.port_id} organization/site/device binding이 다르다")
                continue
            try:
                evidence = self._registry.require_verified_for(
                    port.integration_path,
                    capability,
                    hardware_model=hardware_model,
                    firmware_version=firmware_version,
                )
            except CapabilityUnavailableError as exc:
                rejected.append(str(exc))
                continue
            return port, evidence
        detail = "; ".join(rejected) if rejected else "허용 transport의 등록 port가 없다"
        raise CapabilityUnavailableError(f"{capability.value} route를 선택할 수 없다: {detail}")


__all__ = ["CapabilityRoute", "CapabilityRouter"]
