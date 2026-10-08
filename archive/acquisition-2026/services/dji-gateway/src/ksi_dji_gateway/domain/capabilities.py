"""Capability evidence scoped by integration path, hardware, and firmware."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ksi_dji_gateway.domain.validation import aware_datetime
from ksi_dji_gateway.errors import CapabilityUnavailableError


class IntegrationPath(StrEnum):
    DJI_CLOUD = "DJI_CLOUD"
    PSDK_MANIFOLD = "PSDK_MANIFOLD"
    MANIFOLD_DIRECT = "MANIFOLD_DIRECT"
    MSDK_FIELD = "MSDK_FIELD"
    DJI_DOCK = "DJI_DOCK"


class GatewayTransport(StrEnum):
    RC_WIFI = "RC_WIFI"
    RC_CELLULAR = "RC_CELLULAR"
    MANIFOLD_CELLULAR = "MANIFOLD_CELLULAR"
    DOCK_ETHERNET = "DOCK_ETHERNET"
    DOCK_CELLULAR = "DOCK_CELLULAR"
    MOP = "MOP"


class Capability(StrEnum):
    # v1.3 semantic capabilities.
    WAYLINE_DELIVERY = "WAYLINE_DELIVERY"
    EDGE_DOWNLINK = "EDGE_DOWNLINK"
    EDGE_UPLINK = "EDGE_UPLINK"
    MEDIA_PULL = "MEDIA_PULL"
    MEDIA_UPLOAD = "MEDIA_UPLOAD"
    # v1.2 reader/API compatibility. New routers must use the semantic names above.
    WAYLINE_PUSH = "WAYLINE_PUSH"
    TASK_STATUS = "TASK_STATUS"
    CAMERA_MEDIA_PULL = "CAMERA_MEDIA_PULL"


class CapabilityStatus(StrEnum):
    """Field/HIL verification status for a capability route.

    This status is deliberately the only evidence axis that may enable a
    runtime route. The legacy name is retained for reader and constructor
    compatibility.
    """

    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"


class VendorDocumentationStatus(StrEnum):
    """What vendor documentation says, independently of field evidence."""

    UNKNOWN = "UNKNOWN"
    DOCUMENTED_SUPPORTED = "DOCUMENTED_SUPPORTED"
    DOCUMENTED_PARTIAL = "DOCUMENTED_PARTIAL"
    NOT_LISTED = "NOT_LISTED"
    CONFLICTING = "CONFLICTING"
    DOCUMENTED_UNSUPPORTED = "DOCUMENTED_UNSUPPORTED"


_LEGACY_SCOPE = "LEGACY_UNSCOPED"


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    path: IntegrationPath
    capability: Capability
    status: CapabilityStatus
    checked_at: str
    evidence_ref: str | None = None
    reason: str | None = None
    hardware_model: str = _LEGACY_SCOPE
    firmware_version: str = _LEGACY_SCOPE
    vendor_documentation_status: VendorDocumentationStatus = VendorDocumentationStatus.UNKNOWN
    vendor_documentation_ref: str | None = None

    def __post_init__(self) -> None:
        aware_datetime(self.checked_at, field="checked_at")
        if not self.hardware_model.strip() or not self.firmware_version.strip():
            raise ValueError("hardware_model/firmware_version은 비어 있을 수 없다")
        if self.status is CapabilityStatus.VERIFIED and not self.evidence_ref:
            raise ValueError("VERIFIED capability에는 evidence_ref가 필수다")
        if (
            self.vendor_documentation_status is not VendorDocumentationStatus.UNKNOWN
            and not self.vendor_documentation_ref
        ):
            raise ValueError(
                "UNKNOWN이 아닌 vendor_documentation_status에는 "
                "vendor_documentation_ref가 필수다"
            )

    @property
    def field_status(self) -> CapabilityStatus:
        """Explicit name for the legacy ``status`` field's field-evidence role."""

        return self.status

    @property
    def field_evidence_ref(self) -> str | None:
        """Explicit name for the legacy ``evidence_ref`` field's field-evidence role."""

        return self.evidence_ref


class CapabilityRegistry:
    def __init__(self, evidence: list[CapabilityEvidence]) -> None:
        self._evidence: dict[tuple[IntegrationPath, Capability, str, str], CapabilityEvidence] = {}
        for item in evidence:
            key = (item.path, item.capability, item.hardware_model, item.firmware_version)
            if key in self._evidence:
                raise ValueError(f"capability evidence 중복: {key}")
            self._evidence[key] = item

    def require_verified(self, path: IntegrationPath, *capabilities: Capability) -> None:
        """v1.2 compatibility lookup for legacy provider facade."""
        for capability in capabilities:
            matches = [
                item
                for (
                    candidate_path,
                    candidate_capability,
                    _hardware,
                    _firmware,
                ), item in self._evidence.items()
                if candidate_path is path and candidate_capability is capability
            ]
            if not any(item.field_status is CapabilityStatus.VERIFIED for item in matches):
                status = matches[0].field_status if matches else CapabilityStatus.NOT_VERIFIED
                raise CapabilityUnavailableError(
                    f"{path.value}/{capability.value} capability는 {status.value}다"
                )

    def require_verified_for(
        self,
        path: IntegrationPath,
        capability: Capability,
        *,
        hardware_model: str,
        firmware_version: str,
    ) -> CapabilityEvidence:
        item = self._evidence.get((path, capability, hardware_model, firmware_version))
        if item is None or item.field_status is not CapabilityStatus.VERIFIED:
            status = item.field_status if item is not None else CapabilityStatus.NOT_VERIFIED
            raise CapabilityUnavailableError(
                f"{path.value}/{hardware_model}/{firmware_version}/{capability.value} "
                f"capability는 {status.value}다"
            )
        return item


__all__ = [
    "Capability",
    "CapabilityEvidence",
    "CapabilityRegistry",
    "CapabilityStatus",
    "GatewayTransport",
    "IntegrationPath",
    "VendorDocumentationStatus",
]
