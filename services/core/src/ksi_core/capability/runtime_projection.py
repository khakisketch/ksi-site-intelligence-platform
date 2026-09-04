"""CAP-5 current runtime observation and operational capability projection.

This module deliberately consumes, but never recreates, CAP-4 durable
activation authority.  Its canonical conjunction is kept as three explicit
predicates::

    OperationallyUsable = DurableAuthorityValid
                          AND CurrentRuntimeReady
                          AND CurrentMissionPolicyAllows

Runtime observations live in their own audit journal.  They cannot create
evidence, product approval, or operational activation records and replay never
rebases their explicit ``observedAt``/``expiresAt`` interval.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_domain.capability_contract import (
    RUNTIME_ROUTE_REGISTRY_V1,
    CanonicalTransportCapability,
    CapabilityContractError,
    CapabilityIntegrationPath,
    RuntimeRouteSubjectKind,
)
from pydantic import Field, ValidationError, field_validator, model_validator

from ksi_core.acquisition.models import CapabilityStatus
from ksi_core.acquisition.store import AcquisitionConnectivityStore
from ksi_core.api_base import CamelModel, iso_utc
from ksi_core.auth import Principal, PrincipalKind
from ksi_core.capability.authority_store import (
    ActivationAuthorityCause,
    ActivationLifecycleStatus,
    CapabilityActivationSuspendedV1,
    CapabilityAuthorityStore,
    ConfiguredDeploymentSnapshotV1,
    OperationalCapabilityActivationProjection,
    operational_capability_activation_record_digest,
)
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

RUNTIME_ROUTE_OBSERVATION_JOURNAL_NAME = "capability-runtime-observations.jsonl"
RUNTIME_ROUTE_OBSERVATION_SCHEMA_VERSION = "1.0"

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_PATH_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"

_ALLOWED_RUNTIME_TRANSPORTS: dict[CapabilityIntegrationPath, frozenset[str]] = {
    CapabilityIntegrationPath.DJI_CLOUD: frozenset({"RC_WIFI", "RC_CELLULAR"}),
    CapabilityIntegrationPath.PSDK_MANIFOLD: frozenset({"MOP"}),
    CapabilityIntegrationPath.MANIFOLD_DIRECT: frozenset({"MANIFOLD_CELLULAR"}),
    CapabilityIntegrationPath.MSDK_FIELD: frozenset({"MOP"}),
    CapabilityIntegrationPath.DJI_DOCK: frozenset({"DOCK_ETHERNET", "DOCK_CELLULAR"}),
}

_LEGACY_GATEWAY_TRANSPORT: dict[tuple[CapabilityIntegrationPath, str], str] = {
    (CapabilityIntegrationPath.DJI_CLOUD, "WIFI"): "RC_WIFI",
    (CapabilityIntegrationPath.DJI_CLOUD, "CELLULAR"): "RC_CELLULAR",
    (CapabilityIntegrationPath.DJI_DOCK, "ETHERNET"): "DOCK_ETHERNET",
    (CapabilityIntegrationPath.DJI_DOCK, "CELLULAR"): "DOCK_CELLULAR",
}


class RuntimeCapabilityError(Exception):
    """Base error for CAP-5 validation, ordering, and integration failures."""


class RuntimeCapabilityValidationError(RuntimeCapabilityError):
    """A configuration or observation is not an exact contract value."""


class RuntimeObservationConflict(RuntimeCapabilityError):
    """An observation violates immutable ID or causal ordering semantics."""


class RuntimeObservationUnavailable(RuntimeCapabilityError):
    """The observation audit journal cannot safely accept more records."""


class RuntimeObservationRecoveryError(RuntimeCapabilityError):
    """Observation replay cannot establish one unambiguous current projection."""


class LegacyConnectivityAdaptationError(RuntimeCapabilityError):
    """A legacy snapshot cannot resolve to exactly one trusted runtime route."""


class RuntimeRouteAvailability(StrEnum):
    REPORTED_AVAILABLE = "REPORTED_AVAILABLE"
    REPORTED_UNAVAILABLE = "REPORTED_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class MissionPolicyDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class RuntimeProjectionReason(StrEnum):
    OPERATIONALLY_USABLE = "OPERATIONALLY_USABLE"
    DURABLE_AUTHORITY_MISSING = "DURABLE_AUTHORITY_MISSING"
    ACTIVATION_NOT_YET_EFFECTIVE = "ACTIVATION_NOT_YET_EFFECTIVE"
    ACTIVATION_SUPERSEDED = "ACTIVATION_SUPERSEDED"
    ACTIVATION_SUSPENDED = "ACTIVATION_SUSPENDED"
    ACTIVATION_REVOKED = "ACTIVATION_REVOKED"
    ACTIVATION_EXPIRED = "ACTIVATION_EXPIRED"
    DURABLE_PREREQUISITE_INVALID = "DURABLE_PREREQUISITE_INVALID"
    DURABLE_AUTHORITY_BLOCKED = "DURABLE_AUTHORITY_BLOCKED"
    UNMAPPED_NOT_ACTIVATABLE = "UNMAPPED_NOT_ACTIVATABLE"
    UNTRUSTED_LEGACY_ORGANIZATION = "UNTRUSTED_LEGACY_ORGANIZATION"
    TRUSTED_ORGANIZATION_MISMATCH = "TRUSTED_ORGANIZATION_MISMATCH"
    CONFIGURED_DEPLOYMENT_MISSING = "CONFIGURED_DEPLOYMENT_MISSING"
    CONFIGURED_DEPLOYMENT_SCOPE_INVALIDATED = (
        "CONFIGURED_DEPLOYMENT_SCOPE_INVALIDATED"
    )
    FEATURE_FLAG_OFF = "FEATURE_FLAG_OFF"
    PORT_CONFIGURATION_NOT_READY = "PORT_CONFIGURATION_NOT_READY"
    TRANSPORT_NOT_ALLOWED = "TRANSPORT_NOT_ALLOWED"
    OBSERVATION_MISSING = "OBSERVATION_MISSING"
    OBSERVATION_FUTURE_DATED = "OBSERVATION_FUTURE_DATED"
    OBSERVATION_STALE = "OBSERVATION_STALE"
    OBSERVATION_UNAVAILABLE = "OBSERVATION_UNAVAILABLE"
    OBSERVATION_UNKNOWN = "OBSERVATION_UNKNOWN"
    OBSERVATION_WRONG_ROUTE = "OBSERVATION_WRONG_ROUTE"
    OBSERVATION_WRONG_COMPONENT = "OBSERVATION_WRONG_COMPONENT"
    FRESHNESS_POLICY_MISMATCH = "FRESHNESS_POLICY_MISMATCH"
    FRESHNESS_POLICY_UNKNOWN = "FRESHNESS_POLICY_UNKNOWN"
    OBSERVATION_ORDERING_AMBIGUOUS = "OBSERVATION_ORDERING_AMBIGUOUS"
    MISSION_POLICY_DENIED = "MISSION_POLICY_DENIED"


class RuntimeEffectClassification(StrEnum):
    DURABLE_AUTHORITY_INEFFECTIVE = "DURABLE_AUTHORITY_INEFFECTIVE"
    TEMPORARY_RUNTIME_INEFFECTIVE = "TEMPORARY_RUNTIME_INEFFECTIVE"
    MISSION_POLICY_INEFFECTIVE = "MISSION_POLICY_INEFFECTIVE"
    OPERATIONALLY_USABLE = "OPERATIONALLY_USABLE"


class ExistingMissionContractEffect(StrEnum):
    UNCHANGED = "UNCHANGED"


class ObservationIngestDisposition(StrEnum):
    RECORDED = "RECORDED"
    EXACT_RETRY = "EXACT_RETRY"


def _sha256_prefixed(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _exact_utc(value: datetime, field: str) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError(f"{field} must be timezone-aware UTC")
    if offset.total_seconds() != 0:
        raise ValueError(f"{field} must use UTC offset +00:00")
    return value.astimezone(UTC)


def _subject_device_ids(
    subject_kind: RuntimeRouteSubjectKind,
    configured: ConfiguredDeploymentSnapshotV1,
) -> tuple[str, ...]:
    if subject_kind in {
        RuntimeRouteSubjectKind.GATEWAY_ROUTE_PORT,
        RuntimeRouteSubjectKind.DOCK_ROUTE_PORT,
    }:
        return (configured.gateway_device_id,)
    if subject_kind is RuntimeRouteSubjectKind.EDGE_ROUTE_PORT:
        return (configured.edge_device_id,)
    if subject_kind is RuntimeRouteSubjectKind.GATEWAY_EDGE_ROUTE_PORT:
        return (configured.gateway_device_id, configured.edge_device_id)
    raise RuntimeCapabilityValidationError(f"unsupported subject kind: {subject_kind}")


@dataclass(frozen=True, slots=True, order=True)
class RuntimeRouteLookupKey:
    """Exact subject identity; route and port are both authoritative key parts."""

    organization_id: str
    site_id: str
    configured_deployment_digest: str
    subject_kind: str
    subject_device_ids: tuple[str, ...]
    subject_port_id: str
    integration_path: str
    canonical_capability_id: str
    equipment_scope_digest: str
    runtime_build_digest: str


class RuntimeRouteFreshnessPolicyV1(CamelModel):
    """Core-owned exact validity window and operational refresh margin."""

    schema_version: Literal["1.0"] = "1.0"
    freshness_policy_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    observation_ttl_seconds: Annotated[int, Field(ge=1, le=300)]
    minimum_refresh_margin_seconds: Annotated[float, Field(gt=0)]
    freshness_policy_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "freshnessPolicyId": self.freshness_policy_id,
            "observationTtlSeconds": self.observation_ttl_seconds,
            "minimumRefreshMarginSeconds": self.minimum_refresh_margin_seconds,
        }

    @property
    def canonical_digest(self) -> str:
        return _sha256_prefixed(self.canonical_payload)

    @model_validator(mode="after")
    def _policy_is_exact(self) -> RuntimeRouteFreshnessPolicyV1:
        if self.minimum_refresh_margin_seconds >= self.observation_ttl_seconds:
            raise ValueError("minimumRefreshMarginSeconds must be shorter than the TTL")
        if self.freshness_policy_digest != self.canonical_digest:
            raise ValueError("freshnessPolicyDigest does not match canonical policy content")
        return self


class TrustedRuntimeRouteConfigurationV1(CamelModel):
    """Operator/Core-owned current deployment and exact selected route port."""

    configured_deployment: ConfiguredDeploymentSnapshotV1
    configured_deployment_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    subject_kind: RuntimeRouteSubjectKind
    subject_device_ids: Annotated[
        tuple[Annotated[str, Field(pattern=_PATH_ID_PATTERN)], ...],
        Field(min_length=1, max_length=2),
    ]
    subject_port_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    selected_transport: Annotated[str, Field(min_length=1, max_length=100)]
    allowed_transports: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...]
    feature_flag_enabled: bool = False
    port_configuration_ready: bool = False
    freshness_policy_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    freshness_policy_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    legacy_connectivity_adapter_enabled: bool = False

    @model_validator(mode="after")
    def _configuration_is_exact(self) -> TrustedRuntimeRouteConfigurationV1:
        configured = self.configured_deployment
        if configured.organization_id == "legacy":
            raise ValueError("legacy is not a trusted organization identity")
        if self.configured_deployment_digest != configured.canonical_digest:
            raise ValueError(
                "configuredDeploymentDigest does not match configuredDeployment"
            )
        try:
            requirement = RUNTIME_ROUTE_REGISTRY_V1.requirement_for(
                configured.canonical_capability_id, configured.integration_path
            )
        except CapabilityContractError as exc:
            raise ValueError(str(exc)) from exc
        if self.subject_kind is not requirement.subject_kind:
            raise ValueError("subjectKind does not match the exact runtime route registry")
        expected_devices = _subject_device_ids(self.subject_kind, configured)
        if self.subject_device_ids != expected_devices:
            raise ValueError("subjectDeviceIds do not match trusted configured deployment")
        if (
            not self.allowed_transports
            or len(self.allowed_transports) != len(set(self.allowed_transports))
            or tuple(sorted(self.allowed_transports)) != self.allowed_transports
        ):
            raise ValueError("allowedTransports must be non-empty, unique, and sorted")
        if self.selected_transport not in self.allowed_transports:
            raise ValueError("selectedTransport is not in allowedTransports")
        exact_allowed = _ALLOWED_RUNTIME_TRANSPORTS[configured.integration_path]
        if (
            self.selected_transport not in exact_allowed
            or not set(self.allowed_transports) <= exact_allowed
        ):
            raise ValueError("transport does not match the exact integrationPath registry")
        return self

    @property
    def key(self) -> RuntimeRouteLookupKey:
        configured = self.configured_deployment
        return RuntimeRouteLookupKey(
            organization_id=configured.organization_id,
            site_id=configured.site_id,
            configured_deployment_digest=self.configured_deployment_digest,
            subject_kind=self.subject_kind.value,
            subject_device_ids=self.subject_device_ids,
            subject_port_id=self.subject_port_id,
            integration_path=configured.integration_path.value,
            canonical_capability_id=configured.canonical_capability_id.value,
            equipment_scope_digest=configured.equipment_scope_digest,
            runtime_build_digest=configured.runtime_build_digest,
        )

    @property
    def route_slot(self) -> tuple[str, str, str, str]:
        configured = self.configured_deployment
        return (
            configured.organization_id,
            configured.site_id,
            configured.integration_path.value,
            configured.canonical_capability_id.value,
        )


class RuntimeRouteObservationV1(CamelModel):
    """Immutable report of current availability for one exact configured port."""

    observation_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    organization_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    site_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    configured_deployment_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    subject_kind: RuntimeRouteSubjectKind
    subject_device_ids: Annotated[
        tuple[Annotated[str, Field(pattern=_PATH_ID_PATTERN)], ...],
        Field(min_length=1, max_length=2),
    ]
    subject_port_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    integration_path: CapabilityIntegrationPath
    canonical_capability_id: CanonicalTransportCapability
    equipment_scope_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    runtime_build_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    availability: RuntimeRouteAvailability
    observed_at: datetime
    expires_at: datetime
    freshness_policy_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    freshness_policy_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    producer_principal_id: Annotated[str, Field(pattern=_PATH_ID_PATTERN)]
    producer_principal_kind: PrincipalKind
    source_observation_ref: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("observed_at", "expires_at")
    @classmethod
    def _times_are_exact_utc(cls, value: datetime, info: Any) -> datetime:
        return _exact_utc(value, info.field_name)

    @field_validator("source_observation_ref")
    @classmethod
    def _source_reference_is_nonblank(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("sourceObservationRef must be exact nonblank text")
        return value

    @model_validator(mode="after")
    def _observation_is_exact(self) -> RuntimeRouteObservationV1:
        if self.organization_id == "legacy":
            raise ValueError("legacy is not valid runtime organization evidence")
        if self.expires_at <= self.observed_at:
            raise ValueError("expiresAt must be later than observedAt")
        if not self.subject_device_ids or len(self.subject_device_ids) != len(
            set(self.subject_device_ids)
        ):
            raise ValueError("subjectDeviceIds must be non-empty and unique")
        expected_device_count = (
            2
            if self.subject_kind is RuntimeRouteSubjectKind.GATEWAY_EDGE_ROUTE_PORT
            else 1
        )
        if len(self.subject_device_ids) != expected_device_count:
            raise ValueError("subjectDeviceIds cardinality does not match subjectKind")
        try:
            requirement = RUNTIME_ROUTE_REGISTRY_V1.requirement_for(
                self.canonical_capability_id, self.integration_path
            )
        except CapabilityContractError as exc:
            raise ValueError(str(exc)) from exc
        if self.subject_kind is not requirement.subject_kind:
            raise ValueError("subjectKind does not match exact runtime route")
        return self

    @property
    def key(self) -> RuntimeRouteLookupKey:
        return RuntimeRouteLookupKey(
            organization_id=self.organization_id,
            site_id=self.site_id,
            configured_deployment_digest=self.configured_deployment_digest,
            subject_kind=self.subject_kind.value,
            subject_device_ids=self.subject_device_ids,
            subject_port_id=self.subject_port_id,
            integration_path=self.integration_path.value,
            canonical_capability_id=self.canonical_capability_id.value,
            equipment_scope_digest=self.equipment_scope_digest,
            runtime_build_digest=self.runtime_build_digest,
        )

    @property
    def canonical_digest(self) -> str:
        return _sha256_prefixed(self.model_dump(mode="json", by_alias=True))


class RuntimeRouteObservationEventV1(CamelModel):
    schema_version: str
    kind: str
    occurred_at: datetime
    payload: dict[str, Any]
    payload_sha256: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        return _exact_utc(value, "occurredAt")


@dataclass(frozen=True, slots=True)
class ObservationIngestResult:
    disposition: ObservationIngestDisposition
    observation: RuntimeRouteObservationV1


class RuntimeRouteObservationStore:
    """Separate append-only observation audit and deterministic current index."""

    _OBSERVED_KIND = "runtime-route-observed"
    _AMBIGUITY_KIND = "runtime-route-ordering-ambiguous"

    def __init__(self, journal: DurableJournal) -> None:
        self._journal = journal
        self._lock = threading.RLock()
        self._by_id: dict[str, RuntimeRouteObservationV1] = {}
        self._current: dict[RuntimeRouteLookupKey, RuntimeRouteObservationV1] = {}
        self._ambiguous_keys: set[RuntimeRouteLookupKey] = set()
        try:
            self._replay(journal.replay())
        except RuntimeObservationRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise RuntimeObservationRecoveryError(
                f"runtime observation replay failed: {exc}"
            ) from exc

    @property
    def record_count(self) -> int:
        with self._lock:
            return len(self._by_id)

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def close(self) -> None:
        self._journal.close()

    def observations(self) -> tuple[RuntimeRouteObservationV1, ...]:
        with self._lock:
            return tuple(
                item.model_copy(deep=True)
                for item in sorted(
                    self._by_id.values(), key=lambda value: value.observation_id
                )
            )

    def current_for(
        self, key: RuntimeRouteLookupKey
    ) -> RuntimeRouteObservationV1 | None:
        with self._lock:
            item = self._current.get(key)
            return item.model_copy(deep=True) if item is not None else None

    def is_ordering_ambiguous(self, key: RuntimeRouteLookupKey) -> bool:
        with self._lock:
            return key in self._ambiguous_keys

    def diagnose_missing(
        self, config: TrustedRuntimeRouteConfigurationV1
    ) -> RuntimeProjectionReason:
        """Explain a nearby self-report mismatch without accepting it as the key."""

        with self._lock:
            observations = tuple(self._current.values())
        configured = config.configured_deployment
        same_capability = tuple(
            item
            for item in observations
            if item.organization_id == configured.organization_id
            and item.site_id == configured.site_id
            and item.canonical_capability_id is configured.canonical_capability_id
        )
        if any(
            item.integration_path is not configured.integration_path
            or item.subject_port_id != config.subject_port_id
            for item in same_capability
        ):
            return RuntimeProjectionReason.OBSERVATION_WRONG_ROUTE
        if any(
            item.integration_path is configured.integration_path
            and (
                item.subject_kind is not config.subject_kind
                or item.subject_device_ids != config.subject_device_ids
                or item.configured_deployment_digest
                != config.configured_deployment_digest
                or item.equipment_scope_digest != configured.equipment_scope_digest
                or item.runtime_build_digest != configured.runtime_build_digest
            )
            for item in same_capability
        ):
            return RuntimeProjectionReason.OBSERVATION_WRONG_COMPONENT
        return RuntimeProjectionReason.OBSERVATION_MISSING

    def ingest(
        self, observation: RuntimeRouteObservationV1, *, received_at: datetime
    ) -> ObservationIngestResult:
        received_at = _exact_utc(received_at, "receivedAt")
        if observation.observed_at > received_at:
            raise RuntimeCapabilityValidationError(
                "future-dated observation cannot be ingested"
            )
        with self._lock:
            prior_id = self._by_id.get(observation.observation_id)
            if prior_id is not None:
                if prior_id.canonical_digest == observation.canonical_digest:
                    return ObservationIngestResult(
                        ObservationIngestDisposition.EXACT_RETRY,
                        prior_id.model_copy(deep=True),
                    )
                raise RuntimeObservationConflict(
                    "observationId was reused with different canonical content"
                )

            prior = self._current.get(observation.key)
            if prior is not None and observation.observed_at < prior.observed_at:
                raise RuntimeObservationConflict(
                    "out-of-order observation cannot overwrite newer route state"
                )
            if prior is not None and observation.observed_at == prior.observed_at:
                self._append_ambiguity(observation, prior=prior, occurred_at=received_at)
                self._ambiguous_keys.add(observation.key)
                raise RuntimeObservationConflict(
                    "different observation IDs at one observedAt are ordering-ambiguous"
                )

            raw = self._event_for_observation(observation, occurred_at=received_at)
            try:
                self._journal.append(raw)
            except JournalSealedError as exc:
                raise RuntimeObservationUnavailable(str(exc)) from exc
            self._project_observation(observation)
            return ObservationIngestResult(
                ObservationIngestDisposition.RECORDED,
                observation.model_copy(deep=True),
            )

    def _append_ambiguity(
        self,
        observation: RuntimeRouteObservationV1,
        *,
        prior: RuntimeRouteObservationV1,
        occurred_at: datetime,
    ) -> None:
        payload = {
            "routeKey": _key_payload(observation.key),
            "observedAt": iso_utc(observation.observed_at),
            "existingObservationId": prior.observation_id,
            "conflictingObservationId": observation.observation_id,
            "conflictingObservationDigest": observation.canonical_digest,
        }
        raw = self._event(
            kind=self._AMBIGUITY_KIND, occurred_at=occurred_at, payload=payload
        )
        try:
            self._journal.append(raw)
        except JournalSealedError as exc:
            raise RuntimeObservationUnavailable(str(exc)) from exc

    def _project_observation(self, observation: RuntimeRouteObservationV1) -> None:
        self._by_id[observation.observation_id] = observation
        self._current[observation.key] = observation
        # A strictly newer report provides deterministic causal order again.
        self._ambiguous_keys.discard(observation.key)

    def _replay(self, records: Iterable[dict[str, Any]]) -> None:
        for raw in records:
            try:
                event = RuntimeRouteObservationEventV1.model_validate(raw)
            except ValidationError as exc:
                raise RuntimeObservationRecoveryError(
                    f"invalid runtime observation event: {exc}"
                ) from exc
            expected_digest = _sha256_prefixed(
                {
                    "schemaVersion": event.schema_version,
                    "kind": event.kind,
                    "occurredAt": iso_utc(event.occurred_at),
                    "payload": event.payload,
                }
            )
            if event.schema_version != RUNTIME_ROUTE_OBSERVATION_SCHEMA_VERSION:
                raise RuntimeObservationRecoveryError(
                    f"unsupported observation schema: {event.schema_version}"
                )
            if event.payload_sha256 != expected_digest:
                raise RuntimeObservationRecoveryError(
                    "runtime observation event payload digest mismatch"
                )
            if event.kind == self._AMBIGUITY_KIND:
                try:
                    self._ambiguous_keys.add(_key_from_payload(event.payload["routeKey"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeObservationRecoveryError(
                        "invalid runtime ordering ambiguity event"
                    ) from exc
                continue
            if event.kind != self._OBSERVED_KIND:
                raise RuntimeObservationRecoveryError(
                    f"unsupported runtime observation event kind: {event.kind}"
                )
            try:
                observation = RuntimeRouteObservationV1.model_validate(
                    event.payload["observation"]
                )
            except (KeyError, ValidationError) as exc:
                raise RuntimeObservationRecoveryError(
                    f"invalid runtime observation payload: {exc}"
                ) from exc
            prior_id = self._by_id.get(observation.observation_id)
            if prior_id is not None:
                if prior_id.canonical_digest != observation.canonical_digest:
                    raise RuntimeObservationRecoveryError(
                        "duplicate observationId has conflicting replay content"
                    )
                continue
            prior = self._current.get(observation.key)
            if prior is not None and observation.observed_at <= prior.observed_at:
                raise RuntimeObservationRecoveryError(
                    "observation replay violates strictly increasing route ordering"
                )
            self._project_observation(observation)

    def _event_for_observation(
        self, observation: RuntimeRouteObservationV1, *, occurred_at: datetime
    ) -> dict[str, Any]:
        return self._event(
            kind=self._OBSERVED_KIND,
            occurred_at=occurred_at,
            payload={
                "observation": observation.model_dump(mode="json", by_alias=True)
            },
        )

    @staticmethod
    def _event(*, kind: str, occurred_at: datetime, payload: dict[str, Any]) -> dict[str, Any]:
        content = {
            "schemaVersion": RUNTIME_ROUTE_OBSERVATION_SCHEMA_VERSION,
            "kind": kind,
            "occurredAt": iso_utc(occurred_at),
            "payload": payload,
        }
        return content | {"payloadSha256": _sha256_prefixed(content)}


def _key_payload(key: RuntimeRouteLookupKey) -> dict[str, Any]:
    return {
        "organizationId": key.organization_id,
        "siteId": key.site_id,
        "configuredDeploymentDigest": key.configured_deployment_digest,
        "subjectKind": key.subject_kind,
        "subjectDeviceIds": list(key.subject_device_ids),
        "subjectPortId": key.subject_port_id,
        "integrationPath": key.integration_path,
        "canonicalCapabilityId": key.canonical_capability_id,
        "equipmentScopeDigest": key.equipment_scope_digest,
        "runtimeBuildDigest": key.runtime_build_digest,
    }


def _key_from_payload(raw: Mapping[str, Any]) -> RuntimeRouteLookupKey:
    devices = raw["subjectDeviceIds"]
    if not isinstance(devices, list) or not all(isinstance(item, str) for item in devices):
        raise ValueError("subjectDeviceIds must be a string array")
    return RuntimeRouteLookupKey(
        organization_id=str(raw["organizationId"]),
        site_id=str(raw["siteId"]),
        configured_deployment_digest=str(raw["configuredDeploymentDigest"]),
        subject_kind=str(raw["subjectKind"]),
        subject_device_ids=tuple(devices),
        subject_port_id=str(raw["subjectPortId"]),
        integration_path=str(raw["integrationPath"]),
        canonical_capability_id=str(raw["canonicalCapabilityId"]),
        equipment_scope_digest=str(raw["equipmentScopeDigest"]),
        runtime_build_digest=str(raw["runtimeBuildDigest"]),
    )


class TrustedRuntimeRouteConfigurationRegistry:
    """Current Core/operator configuration; device reports cannot mutate it."""

    def __init__(
        self, configurations: Iterable[TrustedRuntimeRouteConfigurationV1] = ()
    ) -> None:
        self._lock = threading.RLock()
        self._by_slot: dict[
            tuple[str, str, str, str], TrustedRuntimeRouteConfigurationV1
        ] = {}
        for configuration in configurations:
            self.register_initial(configuration)

    def register_initial(self, configuration: TrustedRuntimeRouteConfigurationV1) -> None:
        with self._lock:
            prior = self._by_slot.get(configuration.route_slot)
            if prior is not None and prior != configuration:
                raise RuntimeCapabilityValidationError(
                    "trusted route slot already has a different configuration"
                )
            self._by_slot[configuration.route_slot] = configuration.model_copy(deep=True)

    def get(
        self,
        *,
        organization_id: str,
        site_id: str,
        integration_path: CapabilityIntegrationPath,
        canonical_capability_id: CanonicalTransportCapability,
    ) -> TrustedRuntimeRouteConfigurationV1 | None:
        with self._lock:
            item = self._by_slot.get(
                (
                    organization_id,
                    site_id,
                    integration_path.value,
                    canonical_capability_id.value,
                )
            )
            return item.model_copy(deep=True) if item is not None else None

    def all(self) -> tuple[TrustedRuntimeRouteConfigurationV1, ...]:
        with self._lock:
            return tuple(
                item.model_copy(deep=True)
                for _, item in sorted(self._by_slot.items(), key=lambda pair: pair[0])
            )

    def replace_with_authority_fence(
        self,
        configuration: TrustedRuntimeRouteConfigurationV1,
        *,
        authority_store: CapabilityAuthorityStore,
        principal: Principal,
        operation_id: str,
        event_id: str,
        occurred_at: datetime,
        cause_record_id: str,
        cause_record_digest: str,
    ) -> None:
        """Replace a changed trusted scope only after CAP-4 durable suspension."""

        with self._lock:
            prior = self._by_slot.get(configuration.route_slot)
            if prior is None:
                self._by_slot[configuration.route_slot] = configuration.model_copy(deep=True)
                return
            if prior == configuration:
                return
            scope = prior.configured_deployment
            from ksi_core.capability.authority_store import ActivationApplicabilityScopeV1

            activation_scope = ActivationApplicabilityScopeV1(
                organization_id=scope.organization_id,
                site_id=scope.site_id,
                gateway_device_id=scope.gateway_device_id,
                edge_device_id=scope.edge_device_id,
                integration_path=scope.integration_path,
                canonical_capability_id=scope.canonical_capability_id,
                equipment_scope_digest=scope.equipment_scope_digest,
                runtime_build_digest=scope.runtime_build_digest,
                policy_scope_id=scope.policy_scope_id,
                mapping_version=scope.mapping_version,
                gate_version=scope.gate_version,
            )
            current = authority_store.current_durable_activations(
                activation_scope, now=occurred_at
            )
            for index, activation in enumerate(current):
                per_operation = operation_id if len(current) == 1 else f"{operation_id}.{index}"
                per_event = event_id if len(current) == 1 else f"{event_id}.{index}"
                suspension = CapabilityActivationSuspendedV1(
                    operation_id=per_operation,
                    target_activation_authorization_id=(
                        activation.record.activation_authorization_id
                    ),
                    target_activation_record_digest=(
                        operational_capability_activation_record_digest(activation.record)
                    ),
                    target_scope=activation.record.activation_scope,
                    target_scope_digest=activation.record.activation_scope_digest,
                    reason="trusted configured deployment scope changed",
                    cause=ActivationAuthorityCause.CONFIGURED_SCOPE_INVALIDATED,
                    cause_record_id=cause_record_id,
                    cause_record_digest=cause_record_digest,
                    suspending_principal_id=principal.principal_id,
                    suspended_at=occurred_at,
                )
                authority_store.suspend_operational_capability(
                    suspension,
                    principal=principal,
                    operation_id=per_operation,
                    event_id=per_event,
                    occurred_at=occurred_at,
                )
            self._by_slot[configuration.route_slot] = configuration.model_copy(deep=True)


class LegacyConnectivitySnapshotAdapter:
    """Read-only exact adapter from ConnectivitySnapshotV1 to CAP-5 observation.

    The legacy receipt supplies current status, never route authority.  Route,
    port, organization, deployment, and freshness policy are taken exclusively
    from one trusted Core configuration.  PSDK/Manifold/MSDK subjects require
    their own canonical producer and are intentionally excluded.
    """

    _ADAPTABLE_SUBJECTS = frozenset(
        {
            RuntimeRouteSubjectKind.GATEWAY_ROUTE_PORT,
            RuntimeRouteSubjectKind.DOCK_ROUTE_PORT,
        }
    )

    def __init__(
        self,
        *,
        connectivity_store: AcquisitionConnectivityStore,
        configuration_registry: TrustedRuntimeRouteConfigurationRegistry,
    ) -> None:
        self._connectivity_store = connectivity_store
        self._configurations = configuration_registry

    def adapt(
        self,
        *,
        organization_id: str,
        site_id: str,
        canonical_capability_id: CanonicalTransportCapability,
    ) -> RuntimeRouteObservationV1:
        if organization_id == "legacy":
            raise LegacyConnectivityAdaptationError(
                "legacy organization cannot authorize snapshot adaptation"
            )
        profile, snapshot, actor = self._connectivity_store.current_trusted_context(
            site_id, organization_id=organization_id
        )
        if profile is None or snapshot is None or actor is None:
            raise LegacyConnectivityAdaptationError(
                "current profile, snapshot, and producer provenance are required"
            )
        candidates = tuple(
            configuration
            for configuration in self._configurations.all()
            if configuration.configured_deployment.organization_id == organization_id
            and configuration.configured_deployment.site_id == site_id
            and configuration.configured_deployment.gateway_device_id
            == profile.gateway_device_id
            and configuration.configured_deployment.edge_device_id == profile.edge_device_id
            and configuration.configured_deployment.canonical_capability_id
            is canonical_capability_id
            and configuration.subject_kind in self._ADAPTABLE_SUBJECTS
            and configuration.legacy_connectivity_adapter_enabled
            and configuration.selected_transport
            == _LEGACY_GATEWAY_TRANSPORT.get(
                (
                    configuration.configured_deployment.integration_path,
                    snapshot.transport.value,
                )
            )
        )
        if len(candidates) != 1:
            raise LegacyConnectivityAdaptationError(
                "legacy capability receipt must resolve to exactly one trusted route"
            )
        configuration = candidates[0]
        configured = configuration.configured_deployment
        if (
            snapshot.site_id != site_id
            or snapshot.gateway_device_id != configured.gateway_device_id
            or snapshot.edge_device_id != configured.edge_device_id
        ):
            raise LegacyConnectivityAdaptationError(
                "legacy snapshot does not match trusted configured deployment"
            )
        receipts = tuple(
            receipt
            for receipt in snapshot.capabilities
            if receipt.capability.value == canonical_capability_id.value
        )
        if len(receipts) != 1:
            raise LegacyConnectivityAdaptationError(
                "legacy snapshot must contain one exact capability receipt"
            )
        receipt = receipts[0]
        availability = {
            CapabilityStatus.VERIFIED: RuntimeRouteAvailability.REPORTED_AVAILABLE,
            CapabilityStatus.BLOCKED: RuntimeRouteAvailability.REPORTED_UNAVAILABLE,
            CapabilityStatus.NOT_VERIFIED: RuntimeRouteAvailability.UNKNOWN,
        }[receipt.status]
        return RuntimeRouteObservationV1(
            observation_id=(
                f"legacy.{snapshot.snapshot_id}."
                f"{configured.integration_path.value.lower()}."
                f"{canonical_capability_id.value.lower()}"
            ),
            organization_id=organization_id,
            site_id=site_id,
            configured_deployment_digest=configuration.configured_deployment_digest,
            subject_kind=configuration.subject_kind,
            subject_device_ids=configuration.subject_device_ids,
            subject_port_id=configuration.subject_port_id,
            integration_path=configured.integration_path,
            canonical_capability_id=canonical_capability_id,
            equipment_scope_digest=configured.equipment_scope_digest,
            runtime_build_digest=configured.runtime_build_digest,
            availability=availability,
            observed_at=snapshot.observed_at.astimezone(UTC),
            expires_at=snapshot.expires_at.astimezone(UTC),
            freshness_policy_id=configuration.freshness_policy_id,
            freshness_policy_digest=configuration.freshness_policy_digest,
            producer_principal_id=actor,
            producer_principal_kind=PrincipalKind.GATEWAY_DEVICE,
            source_observation_ref=f"acquisition-connectivity:{snapshot.snapshot_id}",
        )

@dataclass(frozen=True, slots=True)
class RuntimeCapabilityProjection:
    activation_authorization_id: str
    durable_authority_valid: bool
    current_runtime_ready: bool
    current_mission_policy_allows: bool
    operationally_usable: bool
    reason: RuntimeProjectionReason
    classification: RuntimeEffectClassification
    activation_lifecycle_status: ActivationLifecycleStatus | None
    observation_id: str | None = None
    new_route_invocation_allowed: bool = False
    existing_signed_mission_contract_effect: ExistingMissionContractEffect = (
        ExistingMissionContractEffect.UNCHANGED
    )

    def __post_init__(self) -> None:
        expected = (
            self.durable_authority_valid
            and self.current_runtime_ready
            and self.current_mission_policy_allows
        )
        if self.operationally_usable is not expected:
            raise ValueError("operationallyUsable must equal the three-term conjunction")
        if self.new_route_invocation_allowed is not expected:
            raise ValueError("new route invocation must equal operational usability")


@dataclass(frozen=True, slots=True)
class RuntimeRouteInvocationRequest:
    """Exact trusted Gateway/device request for one *new* route invocation."""

    activation_authorization_id: str
    organization_id: str
    site_id: str
    gateway_device_id: str
    edge_device_id: str
    canonical_capability_id: CanonicalTransportCapability
    integration_path: CapabilityIntegrationPath
    subject_port_id: str
    selected_transport: str
    hardware_model: str
    firmware_version: str

    def __post_init__(self) -> None:
        values = (
            self.activation_authorization_id,
            self.organization_id,
            self.site_id,
            self.gateway_device_id,
            self.edge_device_id,
            self.subject_port_id,
            self.selected_transport,
            self.hardware_model,
            self.firmware_version,
        )
        if any(not is_path_safe_identifier(value) for value in values):
            raise ValueError("runtime invocation scope values must be path-safe identifiers")


class RuntimeCapabilityProjector:
    """Exact activation/runtime projection for new route invocation eligibility."""

    def __init__(
        self,
        *,
        authority_store: CapabilityAuthorityStore,
        configuration_registry: TrustedRuntimeRouteConfigurationRegistry,
        observation_store: RuntimeRouteObservationStore,
        supported_freshness_policies: Mapping[str, RuntimeRouteFreshnessPolicyV1],
        legacy_connectivity_adapter: LegacyConnectivitySnapshotAdapter | None = None,
    ) -> None:
        self._authority_store = authority_store
        self._configurations = configuration_registry
        self._observations = observation_store
        self._supported_freshness_policies = dict(supported_freshness_policies)
        for policy_id, policy in self._supported_freshness_policies.items():
            if policy_id != policy.freshness_policy_id:
                raise RuntimeCapabilityValidationError(
                    "freshness policy registry key does not match policy identity"
                )
        self._legacy_adapter = legacy_connectivity_adapter

    def activation_scope_for(self, activation_authorization_id: str) -> tuple[str, str] | None:
        """Return trusted CAP-4 organization/site scope for API ownership checks."""

        record = self._authority_store.get_activation_record(activation_authorization_id)
        if record is None:
            return None
        return record.activation_scope.organization_id, record.activation_scope.site_id

    def project_new_route_invocation(
        self,
        request: RuntimeRouteInvocationRequest,
        *,
        mission_policy: MissionPolicyDecision,
        now: datetime,
    ) -> RuntimeCapabilityProjection:
        """Validate the consumer-selected exact route before normal projection."""

        now = _exact_utc(now, "now")
        activation = self._authority_store.get_activation_projection(
            request.activation_authorization_id, now=now
        )
        mission_allows = mission_policy is MissionPolicyDecision.ALLOW
        if activation is None:
            return self._result(
                request.activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.DURABLE_AUTHORITY_MISSING,
                lifecycle=None,
            )
        durable = _durable_failure_reason(activation) is None and any(
            item.record.activation_authorization_id
            == request.activation_authorization_id
            for item in self._authority_store.current_durable_activations(
                activation.record.activation_scope, now=now
            )
        )
        scope = activation.record.activation_scope
        if request.organization_id == "legacy" or scope.organization_id == "legacy":
            return self._result(
                request.activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.UNTRUSTED_LEGACY_ORGANIZATION,
                lifecycle=activation.lifecycle_status,
            )
        if request.organization_id != scope.organization_id:
            return self._result(
                request.activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.TRUSTED_ORGANIZATION_MISMATCH,
                lifecycle=activation.lifecycle_status,
            )
        if (
            request.integration_path is not scope.integration_path
            or request.canonical_capability_id is not scope.canonical_capability_id
        ):
            return self._result(
                request.activation_authorization_id,
                durable=durable,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.OBSERVATION_WRONG_ROUTE,
                lifecycle=activation.lifecycle_status,
            )
        if (
            request.site_id != scope.site_id
            or request.gateway_device_id != scope.gateway_device_id
            or request.edge_device_id != scope.edge_device_id
        ):
            return self._result(
                request.activation_authorization_id,
                durable=durable,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.OBSERVATION_WRONG_COMPONENT,
                lifecycle=activation.lifecycle_status,
            )
        # Hardware/build applicability is pinned by CAP-4's exact configured
        # deployment. The Gateway may report which installed component it is,
        # but cannot introduce a model/version outside that trusted snapshot.
        if not any(
            component.hardware_model == request.hardware_model
            and component.firmware_or_image_version == request.firmware_version
            for component in activation.record.configured_deployment.equipment_scope.components
        ):
            return self._result(
                request.activation_authorization_id,
                durable=durable,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.OBSERVATION_WRONG_COMPONENT,
                lifecycle=activation.lifecycle_status,
            )
        config = self._configurations.get(
            organization_id=scope.organization_id,
            site_id=scope.site_id,
            integration_path=scope.integration_path,
            canonical_capability_id=scope.canonical_capability_id,
        )
        if config is None:
            return self._result(
                request.activation_authorization_id,
                durable=durable,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.CONFIGURED_DEPLOYMENT_MISSING,
                lifecycle=activation.lifecycle_status,
            )
        if request.subject_port_id != config.subject_port_id:
            return self._result(
                request.activation_authorization_id,
                durable=durable,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.OBSERVATION_WRONG_ROUTE,
                lifecycle=activation.lifecycle_status,
            )
        if request.selected_transport != config.selected_transport:
            return self._result(
                request.activation_authorization_id,
                durable=durable,
                runtime=False,
                mission=mission_allows,
                reason=RuntimeProjectionReason.TRANSPORT_NOT_ALLOWED,
                lifecycle=activation.lifecycle_status,
            )
        return self.project(
            request.activation_authorization_id,
            trusted_organization_id=request.organization_id,
            mission_policy=mission_policy,
            now=now,
        )

    def ingest_observation(
        self,
        observation: RuntimeRouteObservationV1,
        *,
        principal: Principal,
        received_at: datetime,
    ) -> ObservationIngestResult:
        """Authenticate provenance, then bind payload to trusted configuration."""

        if principal.organization_id == "legacy":
            raise RuntimeCapabilityValidationError(
                "legacy principal organization cannot authorize runtime observation"
            )
        if principal.organization_id != observation.organization_id:
            raise RuntimeCapabilityValidationError(
                "authenticated organization does not match observation"
            )
        if (
            principal.principal_id != observation.producer_principal_id
            or principal.kind is not observation.producer_principal_kind
        ):
            raise RuntimeCapabilityValidationError(
                "authenticated principal does not match observation producer"
            )
        if principal.kind not in {
            PrincipalKind.GATEWAY_DEVICE,
            PrincipalKind.EDGE_DEVICE,
        }:
            raise RuntimeCapabilityValidationError(
                "runtime observation producer must be an authenticated device"
            )
        if principal.device_id not in observation.subject_device_ids:
            raise RuntimeCapabilityValidationError(
                "producer device is not part of the exact observation subject"
            )
        allowed_producers = {
            RuntimeRouteSubjectKind.GATEWAY_ROUTE_PORT: frozenset(
                {PrincipalKind.GATEWAY_DEVICE}
            ),
            RuntimeRouteSubjectKind.DOCK_ROUTE_PORT: frozenset(
                {PrincipalKind.GATEWAY_DEVICE}
            ),
            RuntimeRouteSubjectKind.EDGE_ROUTE_PORT: frozenset(
                {PrincipalKind.EDGE_DEVICE}
            ),
            RuntimeRouteSubjectKind.GATEWAY_EDGE_ROUTE_PORT: frozenset(
                {PrincipalKind.GATEWAY_DEVICE, PrincipalKind.EDGE_DEVICE}
            ),
        }[observation.subject_kind]
        if principal.kind not in allowed_producers:
            raise RuntimeCapabilityValidationError(
                "producer kind cannot observe this exact route subject"
            )
        config = self._configurations.get(
            organization_id=observation.organization_id,
            site_id=observation.site_id,
            integration_path=observation.integration_path,
            canonical_capability_id=observation.canonical_capability_id,
        )
        if config is None or observation.key != config.key:
            raise RuntimeCapabilityValidationError(
                "observation does not match trusted configured deployment and route port"
            )
        if (
            observation.freshness_policy_id != config.freshness_policy_id
            or observation.freshness_policy_digest != config.freshness_policy_digest
        ):
            raise RuntimeCapabilityValidationError(
                "observation freshness policy does not match trusted configuration"
            )
        policy = self._supported_freshness_policies.get(
            observation.freshness_policy_id
        )
        if policy is None:
            raise RuntimeCapabilityValidationError(
                "observation freshness policy is not registered with an exact window"
            )
        if policy.freshness_policy_digest != observation.freshness_policy_digest:
            raise RuntimeCapabilityValidationError(
                "observation freshness policy digest does not match Core policy"
            )
        if observation.expires_at - observation.observed_at != timedelta(
            seconds=policy.observation_ttl_seconds
        ):
            raise RuntimeCapabilityValidationError(
                "observation validity interval does not match the exact freshness policy"
            )
        return self._observations.ingest(observation, received_at=received_at)

    def project(
        self,
        activation_authorization_id: str,
        *,
        trusted_organization_id: str,
        mission_policy: MissionPolicyDecision,
        now: datetime,
    ) -> RuntimeCapabilityProjection:
        now = _exact_utc(now, "now")
        activation = self._authority_store.get_activation_projection(
            activation_authorization_id, now=now
        )
        if activation is None:
            return self._result(
                activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.DURABLE_AUTHORITY_MISSING,
                lifecycle=None,
            )
        record = activation.record
        if (
            trusted_organization_id == "legacy"
            or record.activation_scope.organization_id == "legacy"
        ):
            return self._result(
                activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.UNTRUSTED_LEGACY_ORGANIZATION,
                lifecycle=activation.lifecycle_status,
            )
        if trusted_organization_id != record.activation_scope.organization_id:
            return self._result(
                activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.TRUSTED_ORGANIZATION_MISMATCH,
                lifecycle=activation.lifecycle_status,
            )
        durable_reason = _durable_failure_reason(activation)
        if durable_reason is not None:
            return self._result(
                activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=durable_reason,
                lifecycle=activation.lifecycle_status,
            )
        try:
            RUNTIME_ROUTE_REGISTRY_V1.requirement_for(
                record.activation_scope.canonical_capability_id,
                record.activation_scope.integration_path,
            )
        except CapabilityContractError:
            return self._result(
                activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.UNMAPPED_NOT_ACTIVATABLE,
                lifecycle=activation.lifecycle_status,
            )
        current = self._authority_store.current_durable_activations(
            record.activation_scope, now=now
        )
        if not any(
            item.record.activation_authorization_id == activation_authorization_id
            for item in current
        ):
            return self._result(
                activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.DURABLE_AUTHORITY_MISSING,
                lifecycle=activation.lifecycle_status,
            )
        config = self._configurations.get(
            organization_id=record.activation_scope.organization_id,
            site_id=record.activation_scope.site_id,
            integration_path=record.activation_scope.integration_path,
            canonical_capability_id=record.activation_scope.canonical_capability_id,
        )
        if config is None:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.CONFIGURED_DEPLOYMENT_MISSING,
                lifecycle=activation.lifecycle_status,
            )
        if (
            config.configured_deployment_digest != record.configured_deployment_digest
            or config.configured_deployment != record.configured_deployment
        ):
            return self._result(
                activation_authorization_id,
                durable=False,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.CONFIGURED_DEPLOYMENT_SCOPE_INVALIDATED,
                lifecycle=activation.lifecycle_status,
            )
        if not config.feature_flag_enabled:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.FEATURE_FLAG_OFF,
                lifecycle=activation.lifecycle_status,
            )
        if not config.port_configuration_ready:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.PORT_CONFIGURATION_NOT_READY,
                lifecycle=activation.lifecycle_status,
            )
        if config.selected_transport not in config.allowed_transports:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.TRANSPORT_NOT_ALLOWED,
                lifecycle=activation.lifecycle_status,
            )
        supported_policy = self._supported_freshness_policies.get(
            record.freshness_policy_id
        )
        if supported_policy is None:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.FRESHNESS_POLICY_UNKNOWN,
                lifecycle=activation.lifecycle_status,
            )
        if (
            supported_policy.freshness_policy_digest != record.freshness_policy_digest
            or config.freshness_policy_id != record.freshness_policy_id
            or config.freshness_policy_digest != record.freshness_policy_digest
        ):
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.FRESHNESS_POLICY_MISMATCH,
                lifecycle=activation.lifecycle_status,
            )
        if self._observations.is_ordering_ambiguous(config.key):
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.OBSERVATION_ORDERING_AMBIGUOUS,
                lifecycle=activation.lifecycle_status,
            )
        observation = self._observations.current_for(config.key)
        if observation is None and self._legacy_adapter is not None:
            try:
                adapted = self._legacy_adapter.adapt(
                    organization_id=record.activation_scope.organization_id,
                    site_id=record.activation_scope.site_id,
                    canonical_capability_id=(
                        record.activation_scope.canonical_capability_id
                    ),
                )
            except LegacyConnectivityAdaptationError:
                pass
            else:
                if adapted.key == config.key:
                    observation = adapted
        if observation is None:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=self._observations.diagnose_missing(config),
                lifecycle=activation.lifecycle_status,
            )
        if (
            observation.freshness_policy_id != record.freshness_policy_id
            or observation.freshness_policy_digest != record.freshness_policy_digest
            or observation.expires_at - observation.observed_at
            != timedelta(seconds=supported_policy.observation_ttl_seconds)
        ):
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.FRESHNESS_POLICY_MISMATCH,
                lifecycle=activation.lifecycle_status,
                observation=observation,
            )
        if now < observation.observed_at:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.OBSERVATION_FUTURE_DATED,
                lifecycle=activation.lifecycle_status,
                observation=observation,
            )
        if now >= observation.expires_at:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.OBSERVATION_STALE,
                lifecycle=activation.lifecycle_status,
                observation=observation,
            )
        if observation.availability is RuntimeRouteAvailability.REPORTED_UNAVAILABLE:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.OBSERVATION_UNAVAILABLE,
                lifecycle=activation.lifecycle_status,
                observation=observation,
            )
        if observation.availability is not RuntimeRouteAvailability.REPORTED_AVAILABLE:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=False,
                mission=mission_policy is MissionPolicyDecision.ALLOW,
                reason=RuntimeProjectionReason.OBSERVATION_UNKNOWN,
                lifecycle=activation.lifecycle_status,
                observation=observation,
            )
        if mission_policy is MissionPolicyDecision.DENY:
            return self._result(
                activation_authorization_id,
                durable=True,
                runtime=True,
                mission=False,
                reason=RuntimeProjectionReason.MISSION_POLICY_DENIED,
                lifecycle=activation.lifecycle_status,
                observation=observation,
            )
        return self._result(
            activation_authorization_id,
            durable=True,
            runtime=True,
            mission=True,
            reason=RuntimeProjectionReason.OPERATIONALLY_USABLE,
            lifecycle=activation.lifecycle_status,
            observation=observation,
        )

    @staticmethod
    def _result(
        activation_authorization_id: str,
        *,
        durable: bool,
        runtime: bool,
        mission: bool,
        reason: RuntimeProjectionReason,
        lifecycle: ActivationLifecycleStatus | None,
        observation: RuntimeRouteObservationV1 | None = None,
    ) -> RuntimeCapabilityProjection:
        operational = durable and runtime and mission
        if operational:
            classification = RuntimeEffectClassification.OPERATIONALLY_USABLE
        elif not durable:
            classification = RuntimeEffectClassification.DURABLE_AUTHORITY_INEFFECTIVE
        elif not runtime:
            classification = RuntimeEffectClassification.TEMPORARY_RUNTIME_INEFFECTIVE
        else:
            classification = RuntimeEffectClassification.MISSION_POLICY_INEFFECTIVE
        return RuntimeCapabilityProjection(
            activation_authorization_id=activation_authorization_id,
            durable_authority_valid=durable,
            current_runtime_ready=runtime,
            current_mission_policy_allows=mission,
            operationally_usable=operational,
            reason=reason,
            classification=classification,
            activation_lifecycle_status=lifecycle,
            observation_id=(observation.observation_id if observation is not None else None),
            new_route_invocation_allowed=operational,
        )


def _durable_failure_reason(
    activation: OperationalCapabilityActivationProjection,
) -> RuntimeProjectionReason | None:
    status = activation.lifecycle_status
    if status is ActivationLifecycleStatus.ACTIVE and activation.prerequisites_valid:
        return None
    return {
        ActivationLifecycleStatus.NOT_YET_EFFECTIVE: (
            RuntimeProjectionReason.ACTIVATION_NOT_YET_EFFECTIVE
        ),
        ActivationLifecycleStatus.SUPERSEDED: RuntimeProjectionReason.ACTIVATION_SUPERSEDED,
        ActivationLifecycleStatus.SUSPENDED: RuntimeProjectionReason.ACTIVATION_SUSPENDED,
        ActivationLifecycleStatus.REVOKED: RuntimeProjectionReason.ACTIVATION_REVOKED,
        ActivationLifecycleStatus.EXPIRED: RuntimeProjectionReason.ACTIVATION_EXPIRED,
        ActivationLifecycleStatus.PREREQUISITE_INVALID: (
            RuntimeProjectionReason.DURABLE_PREREQUISITE_INVALID
        ),
        ActivationLifecycleStatus.BLOCKED_CORRUPT: (
            RuntimeProjectionReason.DURABLE_AUTHORITY_BLOCKED
        ),
        ActivationLifecycleStatus.BLOCKED_UNSUPPORTED_VERSION: (
            RuntimeProjectionReason.DURABLE_AUTHORITY_BLOCKED
        ),
    }.get(status, RuntimeProjectionReason.DURABLE_AUTHORITY_MISSING)


__all__ = [
    "RUNTIME_ROUTE_OBSERVATION_JOURNAL_NAME",
    "ExistingMissionContractEffect",
    "LegacyConnectivityAdaptationError",
    "LegacyConnectivitySnapshotAdapter",
    "MissionPolicyDecision",
    "ObservationIngestDisposition",
    "ObservationIngestResult",
    "RuntimeCapabilityError",
    "RuntimeCapabilityProjection",
    "RuntimeCapabilityProjector",
    "RuntimeCapabilityValidationError",
    "RuntimeEffectClassification",
    "RuntimeObservationConflict",
    "RuntimeObservationRecoveryError",
    "RuntimeObservationUnavailable",
    "RuntimeProjectionReason",
    "RuntimeRouteAvailability",
    "RuntimeRouteLookupKey",
    "RuntimeRouteInvocationRequest",
    "RuntimeRouteFreshnessPolicyV1",
    "RuntimeRouteObservationStore",
    "RuntimeRouteObservationV1",
    "TrustedRuntimeRouteConfigurationRegistry",
    "TrustedRuntimeRouteConfigurationV1",
]
