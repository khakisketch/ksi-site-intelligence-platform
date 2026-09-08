"""Pure canonical capability identities and pinned CAP-1/CAP-5 interpreters.

This module deliberately contains no evidence, approval, activation, journal,
configuration, or runtime routing state.  It describes *requirements* only:
which PRD spike sources a canonical capability/path would require under an
explicit mapping version, which current runtime observation subject a mapped
route requires, and which gate-version identity later authority records must
pin.

Legacy ``VERIFIED`` values remain wire compatibility input.  They are never a
canonical authority state here (REQ-ACQ-103, INV-040, INV-041).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ksi_domain.canonical_json import canonical_json_bytes


class CapabilityContractError(ValueError):
    """Base class for fail-closed capability identity/version failures."""


class InvalidCapabilityIdentityError(CapabilityContractError):
    """An identifier is not in the closed canonical/source/path vocabulary."""


class UnsupportedCapabilityMappingVersionError(CapabilityContractError):
    """No exact mapping interpreter exists for the requested version."""


class UnsupportedCapabilityGateVersionError(CapabilityContractError):
    """No exact gate interpreter exists for the requested version."""


class UnsupportedCapabilityRouteError(CapabilityContractError):
    """A canonical capability/path pair is not approvable by this mapping."""


class SourceRequirementMismatchError(CapabilityContractError):
    """A supplied source set is not exactly the route's pinned requirement."""


class DeclaredCapabilitySupport(StrEnum):
    """What a document or manifest declares; never operational authority.

    Wire values are domain-qualified so equal status words in another semantic
    domain cannot compare or hash as the same Python value.
    """

    DECLARED_SUPPORTED = "DECLARED_CAPABILITY_SUPPORT:DECLARED_SUPPORTED"
    DECLARED_PARTIAL = "DECLARED_CAPABILITY_SUPPORT:DECLARED_PARTIAL"
    DECLARED_UNSUPPORTED = "DECLARED_CAPABILITY_SUPPORT:DECLARED_UNSUPPORTED"
    UNKNOWN = "DECLARED_CAPABILITY_SUPPORT:UNKNOWN"
    CONFLICTING = "DECLARED_CAPABILITY_SUPPORT:CONFLICTING"


class GatewayCapabilityObservation(StrEnum):
    """A short-lived gateway report; never product or route approval."""

    REPORTED_AVAILABLE = "GATEWAY_CAPABILITY_OBSERVATION:REPORTED_AVAILABLE"
    REPORTED_UNAVAILABLE = "GATEWAY_CAPABILITY_OBSERVATION:REPORTED_UNAVAILABLE"
    UNKNOWN = "GATEWAY_CAPABILITY_OBSERVATION:UNKNOWN"


class RouteEvidenceQualification(StrEnum):
    """An exact route/equipment evidence verdict, not activation."""

    QUALIFIED = "ROUTE_EVIDENCE_QUALIFICATION:QUALIFIED"
    NOT_QUALIFIED = "ROUTE_EVIDENCE_QUALIFICATION:NOT_QUALIFIED"
    BLOCKED = "ROUTE_EVIDENCE_QUALIFICATION:BLOCKED"
    REVOKED = "ROUTE_EVIDENCE_QUALIFICATION:REVOKED"


class ProductCapabilityApproval(StrEnum):
    """A CAP-3 product/HIL approval state; never operational activation."""

    APPROVAL_REQUIRED = "PRODUCT_CAPABILITY_APPROVAL:APPROVAL_REQUIRED"
    APPROVED = "PRODUCT_CAPABILITY_APPROVAL:APPROVED"
    BLOCKED = "PRODUCT_CAPABILITY_APPROVAL:BLOCKED"
    REVOKED = "PRODUCT_CAPABILITY_APPROVAL:REVOKED"


class OperationalCapabilityActivation(StrEnum):
    """A CAP-4 durable deployment authority state, never runtime readiness."""

    INACTIVE = "OPERATIONAL_CAPABILITY_ACTIVATION:INACTIVE"
    ACTIVE = "OPERATIONAL_CAPABILITY_ACTIVATION:ACTIVE"
    SUSPENDED = "OPERATIONAL_CAPABILITY_ACTIVATION:SUSPENDED"
    REVOKED = "OPERATIONAL_CAPABILITY_ACTIVATION:REVOKED"


class LegacyCapabilitySemantic(StrEnum):
    """Safe internal meanings for legacy Core capability state strings."""

    LEGACY_UNATTESTED = "LEGACY_UNATTESTED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BLOCKED_LEGACY = "BLOCKED_LEGACY"


@dataclass(frozen=True, slots=True)
class LegacyCapabilityCompatibility:
    """Lossless legacy envelope with explicitly zero authority.

    Serializing this object reproduces the legacy source value for a legacy
    reader.  It cannot manufacture evidence, approval, activation, or scope.
    """

    source_value: str
    semantic: LegacyCapabilitySemantic

    def __post_init__(self) -> None:
        if _LEGACY_CORE_SEMANTICS.get(self.source_value) is not self.semantic:
            raise InvalidCapabilityIdentityError(
                "legacy source value and safe semantic do not match"
            )

    @property
    def has_evidence_authority(self) -> bool:
        return False

    @property
    def has_approval_authority(self) -> bool:
        return False

    @property
    def has_activation_authority(self) -> bool:
        return False

    def serialize_legacy(self) -> str:
        return self.source_value


_LEGACY_CORE_SEMANTICS: dict[str, LegacyCapabilitySemantic] = {
    "VERIFIED": LegacyCapabilitySemantic.LEGACY_UNATTESTED,
    "SPIKE_REQUIRED": LegacyCapabilitySemantic.APPROVAL_REQUIRED,
    "BLOCKED": LegacyCapabilitySemantic.BLOCKED_LEGACY,
}


def parse_legacy_core_capability_state(value: str) -> LegacyCapabilityCompatibility:
    """Parse a current Core wire value without strengthening its authority."""

    try:
        semantic = _LEGACY_CORE_SEMANTICS[value]
    except (KeyError, TypeError) as exc:
        raise InvalidCapabilityIdentityError(f"unknown legacy capability state: {value!r}") from exc
    return LegacyCapabilityCompatibility(source_value=value, semantic=semantic)


class CanonicalTransportCapability(StrEnum):
    """The five canonical v1 transport capability identities."""

    WAYLINE_DELIVERY = "WAYLINE_DELIVERY"
    EDGE_DOWNLINK = "EDGE_DOWNLINK"
    EDGE_UPLINK = "EDGE_UPLINK"
    MEDIA_PULL = "MEDIA_PULL"
    MEDIA_UPLOAD = "MEDIA_UPLOAD"


class LegacyTransportCapabilityAlias(StrEnum):
    """Known pre-v1.3 gateway identifiers, accepted only by an explicit adapter."""

    WAYLINE_PUSH = "WAYLINE_PUSH"
    TASK_STATUS = "TASK_STATUS"
    CAMERA_MEDIA_PULL = "CAMERA_MEDIA_PULL"


_LEGACY_TRANSPORT_ALIASES: dict[
    LegacyTransportCapabilityAlias, CanonicalTransportCapability
] = {
    LegacyTransportCapabilityAlias.WAYLINE_PUSH: CanonicalTransportCapability.WAYLINE_DELIVERY,
    LegacyTransportCapabilityAlias.TASK_STATUS: CanonicalTransportCapability.EDGE_UPLINK,
    LegacyTransportCapabilityAlias.CAMERA_MEDIA_PULL: CanonicalTransportCapability.MEDIA_PULL,
}


def canonicalize_legacy_transport_capability(
    value: LegacyTransportCapabilityAlias | str,
) -> CanonicalTransportCapability:
    """Explicit gateway boundary adapter; never used by strict mapping lookup."""

    try:
        alias = LegacyTransportCapabilityAlias(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCapabilityIdentityError(
            f"unknown legacy transport capability alias: {value!r}"
        ) from exc
    return _LEGACY_TRANSPORT_ALIASES[alias]


class CapabilityIntegrationPath(StrEnum):
    """Closed integration-path vocabulary shared by the approved mapping."""

    DJI_CLOUD = "DJI_CLOUD"
    PSDK_MANIFOLD = "PSDK_MANIFOLD"
    MANIFOLD_DIRECT = "MANIFOLD_DIRECT"
    MSDK_FIELD = "MSDK_FIELD"
    DJI_DOCK = "DJI_DOCK"


class RuntimeRouteSubjectKind(StrEnum):
    """Closed v1 vocabulary for the trusted observer of one route port.

    The corresponding ``subjectPortId`` is deliberately absent here: it is a
    trusted runtime-config value selected by the configured deployment, never
    a value this pure registry may derive or guess.
    """

    GATEWAY_ROUTE_PORT = "GATEWAY_ROUTE_PORT"
    DOCK_ROUTE_PORT = "DOCK_ROUTE_PORT"
    EDGE_ROUTE_PORT = "EDGE_ROUTE_PORT"
    GATEWAY_EDGE_ROUTE_PORT = "GATEWAY_EDGE_ROUTE_PORT"


class SourceCapabilityId(StrEnum):
    """The nine PRD §20.3 source capability identities."""

    SPIKE_DJI_01 = "SPIKE-DJI-01"
    SPIKE_DJI_02 = "SPIKE-DJI-02"
    SPIKE_DJI_03 = "SPIKE-DJI-03"
    SPIKE_DJI_04 = "SPIKE-DJI-04"
    SPIKE_DJI_05 = "SPIKE-DJI-05"
    SPIKE_DJI_06 = "SPIKE-DJI-06"
    SPIKE_DJI_07 = "SPIKE-DJI-07"
    SPIKE_DJI_08 = "SPIKE-DJI-08"
    SPIKE_DJI_09 = "SPIKE-DJI-09"


class CapabilityMappingVersion(StrEnum):
    V1 = "ksi-dji-capability-map-v1"


class CapabilityGateVersion(StrEnum):
    V1 = "ksi-capability-gate-v1"


def _canonical_capability(
    value: CanonicalTransportCapability | str,
) -> CanonicalTransportCapability:
    try:
        return CanonicalTransportCapability(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCapabilityIdentityError(f"unknown canonical capability: {value!r}") from exc


def _integration_path(value: CapabilityIntegrationPath | str) -> CapabilityIntegrationPath:
    try:
        return CapabilityIntegrationPath(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCapabilityIdentityError(f"unknown integration path: {value!r}") from exc


def _source_capability(value: SourceCapabilityId | str) -> SourceCapabilityId:
    try:
        return SourceCapabilityId(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCapabilityIdentityError(f"unknown source capability: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class CanonicalCapabilityRequirement:
    """Deterministic, provenance-preserving requirement description.

    ``required_sources`` is a sorted tuple, never a set.  Construction is kept
    private to the pinned interpreter so callers cannot produce an apparently
    valid requirement for an unmapped route.
    """

    canonical_capability: CanonicalTransportCapability
    integration_path: CapabilityIntegrationPath
    required_sources: tuple[SourceCapabilityId, ...]
    mapping_version: CapabilityMappingVersion

    def __post_init__(self) -> None:
        if self.mapping_version is not CapabilityMappingVersion.V1:
            raise UnsupportedCapabilityMappingVersionError(
                f"unsupported capability mapping version: {self.mapping_version!r}"
            )
        expected = _V1_REQUIREMENTS.get((self.canonical_capability, self.integration_path))
        if expected is None or self.required_sources != expected:
            raise UnsupportedCapabilityRouteError(
                "canonical requirement must come from the exact pinned mapping"
            )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "canonicalCapabilityId": self.canonical_capability.value,
            "integrationPath": self.integration_path.value,
            "mappingVersion": self.mapping_version.value,
            "requiredSourceCapabilityIds": [source.value for source in self.required_sources],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class CapabilityGateInterpreter:
    """Pinned gate identity only; CAP-1 makes no authorization decision."""

    version: CapabilityGateVersion

    def __post_init__(self) -> None:
        if self.version is not CapabilityGateVersion.V1:
            raise UnsupportedCapabilityGateVersionError(
                f"unsupported capability gate version: {self.version!r}"
            )

    def canonical_payload(self) -> dict[str, str]:
        return {"gateVersion": self.version.value}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_payload())

    def bind(
        self, requirement: CanonicalCapabilityRequirement
    ) -> CanonicalCapabilityGateRequirement:
        return CanonicalCapabilityGateRequirement(
            requirement=requirement,
            gate_version=self.version,
        )


@dataclass(frozen=True, slots=True)
class CanonicalCapabilityGateRequirement:
    """Digest input binding one exact mapping result to one exact gate version."""

    requirement: CanonicalCapabilityRequirement
    gate_version: CapabilityGateVersion

    def canonical_payload(self) -> dict[str, object]:
        return self.requirement.canonical_payload() | {"gateVersion": self.gate_version.value}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_payload())


_C = CanonicalTransportCapability
_P = CapabilityIntegrationPath
_S = SourceCapabilityId

_V1_REQUIREMENTS: dict[
    tuple[CanonicalTransportCapability, CapabilityIntegrationPath],
    tuple[SourceCapabilityId, ...],
] = {
    (_C.WAYLINE_DELIVERY, _P.PSDK_MANIFOLD): (
        _S.SPIKE_DJI_04,
        _S.SPIKE_DJI_06,
        _S.SPIKE_DJI_07,
    ),
    (_C.WAYLINE_DELIVERY, _P.DJI_DOCK): (_S.SPIKE_DJI_04, _S.SPIKE_DJI_08),
    (_C.EDGE_DOWNLINK, _P.MANIFOLD_DIRECT): (_S.SPIKE_DJI_07,),
    (_C.EDGE_DOWNLINK, _P.MSDK_FIELD): (_S.SPIKE_DJI_06, _S.SPIKE_DJI_07),
    (_C.EDGE_UPLINK, _P.DJI_CLOUD): (_S.SPIKE_DJI_06,),
    (_C.EDGE_UPLINK, _P.PSDK_MANIFOLD): (_S.SPIKE_DJI_07,),
    (_C.EDGE_UPLINK, _P.MANIFOLD_DIRECT): (_S.SPIKE_DJI_07,),
    (_C.MEDIA_PULL, _P.PSDK_MANIFOLD): (_S.SPIKE_DJI_02, _S.SPIKE_DJI_07),
    (_C.MEDIA_PULL, _P.MSDK_FIELD): (_S.SPIKE_DJI_02, _S.SPIKE_DJI_06),
    (_C.MEDIA_PULL, _P.DJI_DOCK): (_S.SPIKE_DJI_02, _S.SPIKE_DJI_08),
    (_C.MEDIA_UPLOAD, _P.MANIFOLD_DIRECT): (_S.SPIKE_DJI_07,),
    (_C.MEDIA_UPLOAD, _P.DJI_DOCK): (_S.SPIKE_DJI_08,),
}

_V1_RUNTIME_ROUTE_SUBJECT_KINDS: dict[
    tuple[CanonicalTransportCapability, CapabilityIntegrationPath],
    RuntimeRouteSubjectKind,
] = {
    (_C.EDGE_UPLINK, _P.DJI_CLOUD): RuntimeRouteSubjectKind.GATEWAY_ROUTE_PORT,
    (_C.MEDIA_PULL, _P.DJI_DOCK): RuntimeRouteSubjectKind.DOCK_ROUTE_PORT,
    (_C.MEDIA_UPLOAD, _P.DJI_DOCK): RuntimeRouteSubjectKind.DOCK_ROUTE_PORT,
    (_C.WAYLINE_DELIVERY, _P.DJI_DOCK): RuntimeRouteSubjectKind.DOCK_ROUTE_PORT,
    (_C.EDGE_DOWNLINK, _P.MANIFOLD_DIRECT): RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
    (_C.EDGE_UPLINK, _P.MANIFOLD_DIRECT): RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
    (_C.MEDIA_UPLOAD, _P.MANIFOLD_DIRECT): RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
    (_C.EDGE_DOWNLINK, _P.MSDK_FIELD): RuntimeRouteSubjectKind.GATEWAY_EDGE_ROUTE_PORT,
    (_C.MEDIA_PULL, _P.MSDK_FIELD): RuntimeRouteSubjectKind.GATEWAY_EDGE_ROUTE_PORT,
    (_C.EDGE_UPLINK, _P.PSDK_MANIFOLD): RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
    (_C.MEDIA_PULL, _P.PSDK_MANIFOLD): RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
    (_C.WAYLINE_DELIVERY, _P.PSDK_MANIFOLD): RuntimeRouteSubjectKind.EDGE_ROUTE_PORT,
}


@dataclass(frozen=True, slots=True)
class RuntimeRouteRequirement:
    """Pinned current-observation requirement for one exact v1 route.

    ``integration_path`` is part of the requirement identity, so matching
    capability/device routes on different paths cannot be substituted.
    """

    canonical_capability: CanonicalTransportCapability
    integration_path: CapabilityIntegrationPath
    subject_kind: RuntimeRouteSubjectKind
    requires_current_observation: bool

    def __post_init__(self) -> None:
        expected_subject_kind = _V1_RUNTIME_ROUTE_SUBJECT_KINDS.get(
            (self.canonical_capability, self.integration_path)
        )
        if (
            expected_subject_kind is None
            or self.subject_kind is not expected_subject_kind
            or self.requires_current_observation is not True
        ):
            raise UnsupportedCapabilityRouteError(
                "runtime route requirement must come from the exact pinned v1 registry"
            )


@dataclass(frozen=True, slots=True)
class RuntimeRouteRegistry:
    """Exact v1 registry for current runtime observation requirements only."""

    def all_requirements(self) -> tuple[RuntimeRouteRequirement, ...]:
        items = sorted(
            _V1_RUNTIME_ROUTE_SUBJECT_KINDS.items(),
            key=lambda item: (item[0][1].value, item[0][0].value),
        )
        return tuple(
            RuntimeRouteRequirement(
                canonical_capability=capability,
                integration_path=path,
                subject_kind=subject_kind,
                requires_current_observation=True,
            )
            for (capability, path), subject_kind in items
        )

    def requirement_for(
        self,
        canonical_capability: CanonicalTransportCapability | str,
        integration_path: CapabilityIntegrationPath | str,
    ) -> RuntimeRouteRequirement:
        capability = _canonical_capability(canonical_capability)
        path = _integration_path(integration_path)
        try:
            subject_kind = _V1_RUNTIME_ROUTE_SUBJECT_KINDS[(capability, path)]
        except KeyError as exc:
            raise UnsupportedCapabilityRouteError(
                f"unmapped runtime capability/path: {capability.value}/{path.value}"
            ) from exc
        return RuntimeRouteRequirement(
            canonical_capability=capability,
            integration_path=path,
            subject_kind=subject_kind,
            requires_current_observation=True,
        )

_INTENTIONALLY_UNMAPPED_SOURCES = (
    _S.SPIKE_DJI_01,
    _S.SPIKE_DJI_03,
    _S.SPIKE_DJI_05,
    _S.SPIKE_DJI_09,
)


@dataclass(frozen=True, slots=True)
class CapabilityMappingInterpreter:
    """Exact interpreter for one stored mapping version."""

    version: CapabilityMappingVersion

    def __post_init__(self) -> None:
        if self.version is not CapabilityMappingVersion.V1:
            raise UnsupportedCapabilityMappingVersionError(
                f"unsupported capability mapping version: {self.version!r}"
            )

    def all_requirements(self) -> tuple[CanonicalCapabilityRequirement, ...]:
        items = sorted(
            _V1_REQUIREMENTS.items(),
            key=lambda item: (item[0][1].value, item[0][0].value),
        )
        return tuple(
            CanonicalCapabilityRequirement(
                canonical_capability=capability,
                integration_path=path,
                required_sources=sources,
                mapping_version=self.version,
            )
            for (capability, path), sources in items
        )

    def requirement_for(
        self,
        canonical_capability: CanonicalTransportCapability | str,
        integration_path: CapabilityIntegrationPath | str,
    ) -> CanonicalCapabilityRequirement:
        capability = _canonical_capability(canonical_capability)
        path = _integration_path(integration_path)
        try:
            sources = _V1_REQUIREMENTS[(capability, path)]
        except KeyError as exc:
            raise UnsupportedCapabilityRouteError(
                f"unmapped capability/path for {self.version.value}: "
                f"{capability.value}/{path.value}"
            ) from exc
        return CanonicalCapabilityRequirement(
            canonical_capability=capability,
            integration_path=path,
            required_sources=sources,
            mapping_version=self.version,
        )

    def requirements_for_source_path(
        self,
        source_capability: SourceCapabilityId | str,
        integration_path: CapabilityIntegrationPath | str,
    ) -> tuple[CanonicalCapabilityRequirement, ...]:
        source = _source_capability(source_capability)
        path = _integration_path(integration_path)
        matches = tuple(
            requirement
            for requirement in self.all_requirements()
            if requirement.integration_path is path and source in requirement.required_sources
        )
        if not matches:
            raise UnsupportedCapabilityRouteError(
                f"source/path has no mapping in {self.version.value}: "
                f"{source.value}/{path.value}"
            )
        return matches

    def validate_required_sources(
        self,
        canonical_capability: CanonicalTransportCapability | str,
        integration_path: CapabilityIntegrationPath | str,
        provided_sources: tuple[SourceCapabilityId | str, ...],
    ) -> CanonicalCapabilityRequirement:
        requirement = self.requirement_for(canonical_capability, integration_path)
        normalized = tuple(
            sorted(
                {_source_capability(item) for item in provided_sources},
                key=lambda item: item.value,
            )
        )
        if len(normalized) != len(provided_sources) or normalized != requirement.required_sources:
            expected = tuple(source.value for source in requirement.required_sources)
            actual = tuple(source.value for source in normalized)
            raise SourceRequirementMismatchError(
                f"source requirements differ for "
                f"{requirement.canonical_capability.value}/{requirement.integration_path.value}: "
                f"expected={expected!r}, actual={actual!r}"
            )
        return requirement

    def is_source_mapped(self, source_capability: SourceCapabilityId | str) -> bool:
        source = _source_capability(source_capability)
        return any(
            source in requirement.required_sources for requirement in self.all_requirements()
        )

    @property
    def intentionally_unmapped_sources(self) -> tuple[SourceCapabilityId, ...]:
        return _INTENTIONALLY_UNMAPPED_SOURCES


_MAPPING_V1 = CapabilityMappingInterpreter(CapabilityMappingVersion.V1)
_GATE_V1 = CapabilityGateInterpreter(CapabilityGateVersion.V1)
RUNTIME_ROUTE_REGISTRY_V1 = RuntimeRouteRegistry()


def resolve_capability_mapping(
    version: CapabilityMappingVersion | str | None,
) -> CapabilityMappingInterpreter:
    """Resolve an explicitly stored version; missing/unknown never means latest."""

    if version != CapabilityMappingVersion.V1:
        raise UnsupportedCapabilityMappingVersionError(
            f"unsupported capability mapping version: {version!r}"
        )
    return _MAPPING_V1


def resolve_capability_gate(
    version: CapabilityGateVersion | str | None,
) -> CapabilityGateInterpreter:
    """Resolve an explicitly stored gate version without default substitution."""

    if version != CapabilityGateVersion.V1:
        raise UnsupportedCapabilityGateVersionError(
            f"unsupported capability gate version: {version!r}"
        )
    return _GATE_V1


__all__ = [
    "CanonicalCapabilityGateRequirement",
    "CanonicalCapabilityRequirement",
    "CanonicalTransportCapability",
    "CapabilityContractError",
    "CapabilityGateInterpreter",
    "CapabilityGateVersion",
    "CapabilityIntegrationPath",
    "CapabilityMappingInterpreter",
    "CapabilityMappingVersion",
    "DeclaredCapabilitySupport",
    "GatewayCapabilityObservation",
    "InvalidCapabilityIdentityError",
    "LegacyCapabilityCompatibility",
    "LegacyCapabilitySemantic",
    "LegacyTransportCapabilityAlias",
    "OperationalCapabilityActivation",
    "ProductCapabilityApproval",
    "RouteEvidenceQualification",
    "RUNTIME_ROUTE_REGISTRY_V1",
    "RuntimeRouteRegistry",
    "RuntimeRouteRequirement",
    "RuntimeRouteSubjectKind",
    "SourceCapabilityId",
    "SourceRequirementMismatchError",
    "UnsupportedCapabilityGateVersionError",
    "UnsupportedCapabilityMappingVersionError",
    "UnsupportedCapabilityRouteError",
    "canonicalize_legacy_transport_capability",
    "parse_legacy_core_capability_state",
    "resolve_capability_gate",
    "resolve_capability_mapping",
]
