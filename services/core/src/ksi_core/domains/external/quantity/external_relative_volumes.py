"""Durable, external-only relative-volume work ledger.

This module owns Core's immutable request, lease and observed-report journal for
the external DSM relative-volume path.  It deliberately does not create a
``ProcessingJob`` or ``ArtifactRef``: the two DSMs remain customer-owned
external reconstruction facts.  Eligibility, currentness and historical proof
are supplied only by the reviewed Core authority adapter at assembly time.

The adapter is a narrow port because this slice is intentionally independent of
the still-evolving external-use evaluator.  There is no permissive policy or
synthetic authority in production code.  Test fixtures must inject an explicit
authority port and the *same* currentness coordinator it owns.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Protocol, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ExternalValidationPolicyV1
from ksi_event_contracts.external_evidence import ExternalEvidenceRecordV1
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalRelativeVolumeMeasurementPayloadV1,
    ExternalRelativeVolumeReportV1,
    ExternalRelativeVolumeRequestV1,
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
    external_relative_volume_execution_policy_wire_dict,
    external_relative_volume_report_wire_dict,
    external_relative_volume_request_wire_dict,
    external_volume_zone_snapshot_wire_dict,
)
from ksi_event_contracts.processing_job import ProcessingJobStatus
from pydantic import Field, StrictInt, StringConstraints, field_validator

from ksi_core.domains.external.quantity.external_relative_volume_launch_material import (
    VolumeWorkerLaunchMaterialResolver,
)
from ksi_core.foundation.api_base import CamelModel, iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.leasing import (
    JobLease,
    LeaseDenialReason,
    LeaseFence,
    LeaseMode,
    check_lease,
    is_claimable,
    lease_raw_fields,
    next_lease,
)
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission

_LOGGER = logging.getLogger(__name__)
_VERSION = 1
_NOT_FOUND_DETAIL = "해당 외부 상대 물량 요청을 찾을 수 없다"
_FAILURE_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_AUTHORITY_SNAPSHOT_FIELDS = frozenset(
    {
        "organizationId",
        "siteId",
        "currentWorkOrderId",
        "decisionId",
        "decisionDigest",
        "compatibilityMappingDigest",
        "baseline",
        "current",
        "evidenceRecordDigests",
        "validationPolicyDigest",
        "zoneSnapshot",
        "executionPolicy",
        "authorizedActorIds",
        "validFrom",
        "validUntil",
        "historicalAuthorityDigest",
        "baselineRmseM",
        "currentRmseM",
        "maximumZoneCellCount",
        "maximumZoneAreaM2",
        "syntheticTestOnly",
    }
)
_INPUT_BINDING_SNAPSHOT_FIELDS = frozenset(
    {
        "subject",
        "inspectionReportDigest",
        "dsmArtifactId",
        "observedSha256",
        "observedSizeBytes",
        "observedCrsDigest",
        "observedVerticalReferenceDigest",
        "capturedFrom",
        "capturedTo",
    }
)
_SUBJECT_SNAPSHOT_FIELDS = frozenset(
    {
        "organizationId",
        "siteId",
        "workOrderId",
        "submissionId",
        "revision",
        "submissionDigest",
        "manifestDigest",
    }
)
_ZONE_SNAPSHOT_FIELDS = frozenset(
    {
        "contractVersion",
        "organizationId",
        "siteId",
        "workAreaId",
        "revision",
        "polygon",
        "crs",
        "observedCrsDigest",
        "analysisVerticalReferenceDigest",
        "definitionDigest",
    }
)
_EXECUTION_POLICY_SNAPSHOT_FIELDS = frozenset(
    {
        "contractVersion",
        "policyId",
        "version",
        "algorithmBuildDigest",
        "configDigest",
        "thresholdM",
        "minimumCommonValidFraction",
        "uncertaintyMethod",
        "resourceEnvelopeDigest",
        "authorityRecordDigest",
        "syntheticTestOnly",
        "policyDigest",
    }
)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: dict[str, Any]) -> str:
    return _digest({key: value for key, value in raw.items() if key != "eventDigest"})


def _require_utc(value: datetime, *, name: str) -> None:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{name} must be UTC")


def _raw_journal_string(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    if type(value) is not str:
        raise ExternalRelativeVolumeRecoveryError(
            f"external relative-volume journal {name} must be a string"
        )
    return value


def _raw_journal_int(raw: dict[str, Any], name: str) -> int:
    value = raw.get(name)
    if type(value) is not int:
        raise ExternalRelativeVolumeRecoveryError(
            f"external relative-volume journal {name} must be an integer"
        )
    return value


def _raw_journal_mapping(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if type(value) is not dict:
        raise ExternalRelativeVolumeRecoveryError(
            f"external relative-volume journal {name} must be an object"
        )
    return value


def _snapshot_object(raw: object, *, name: str, expected_fields: frozenset[str]) -> dict[str, Any]:
    if (
        type(raw) is not dict
        or any(type(field) is not str for field in raw)
        or set(raw) != expected_fields
    ):
        raise ValueError(f"authority snapshot {name} has an invalid object shape")
    return raw


def _snapshot_strings(raw: dict[str, Any], *, name: str, fields: tuple[str, ...]) -> None:
    if any(type(raw[field]) is not str for field in fields):
        raise ValueError(f"authority snapshot {name} has a non-string identifier or digest")


def _snapshot_ints(raw: dict[str, Any], *, name: str, fields: tuple[str, ...]) -> None:
    if any(type(raw[field]) is not int for field in fields):
        raise ValueError(f"authority snapshot {name} has a non-integer count")


def _snapshot_floats(raw: dict[str, Any], *, name: str, fields: tuple[str, ...]) -> None:
    if any(type(raw[field]) is not float for field in fields):
        raise ValueError(f"authority snapshot {name} has a non-canonical float")


def _snapshot_bools(raw: dict[str, Any], *, name: str, fields: tuple[str, ...]) -> None:
    if any(type(raw[field]) is not bool for field in fields):
        raise ValueError(f"authority snapshot {name} has a non-boolean flag")


def _snapshot_string_list(raw: object, *, name: str) -> list[str]:
    if type(raw) is not list or any(type(value) is not str for value in raw):
        raise ValueError(f"authority snapshot {name} must be a list of strings")
    return raw


def _validate_polygon_snapshot(raw: object) -> None:
    polygon = _snapshot_object(
        raw, name="zoneSnapshot.polygon", expected_fields=frozenset({"type", "coordinates"})
    )
    _snapshot_strings(polygon, name="zoneSnapshot.polygon", fields=("type",))
    rings = polygon["coordinates"]
    if type(rings) is not list:
        raise ValueError("authority snapshot zoneSnapshot.polygon coordinates must be a list")
    for ring in rings:
        if type(ring) is not list:
            raise ValueError("authority snapshot zoneSnapshot.polygon ring must be a list")
        for position in ring:
            if type(position) is not list or any(
                type(component) not in (int, float) for component in position
            ):
                raise ValueError(
                    "authority snapshot zoneSnapshot.polygon position must have JSON numbers"
                )


def _validate_input_binding_snapshot(raw: object, *, name: str) -> None:
    binding = _snapshot_object(raw, name=name, expected_fields=_INPUT_BINDING_SNAPSHOT_FIELDS)
    subject = _snapshot_object(
        binding["subject"], name=f"{name}.subject", expected_fields=_SUBJECT_SNAPSHOT_FIELDS
    )
    _snapshot_strings(
        subject,
        name=f"{name}.subject",
        fields=(
            "organizationId",
            "siteId",
            "workOrderId",
            "submissionId",
            "submissionDigest",
            "manifestDigest",
        ),
    )
    _snapshot_ints(subject, name=f"{name}.subject", fields=("revision",))
    _snapshot_strings(
        binding,
        name=name,
        fields=(
            "inspectionReportDigest",
            "dsmArtifactId",
            "observedSha256",
            "observedCrsDigest",
            "observedVerticalReferenceDigest",
            "capturedFrom",
            "capturedTo",
        ),
    )
    _snapshot_ints(binding, name=name, fields=("observedSizeBytes",))


def _validate_zone_snapshot(raw: object) -> None:
    zone = _snapshot_object(raw, name="zoneSnapshot", expected_fields=_ZONE_SNAPSHOT_FIELDS)
    _snapshot_strings(
        zone,
        name="zoneSnapshot",
        fields=(
            "contractVersion",
            "organizationId",
            "siteId",
            "workAreaId",
            "crs",
            "observedCrsDigest",
            "analysisVerticalReferenceDigest",
            "definitionDigest",
        ),
    )
    _snapshot_ints(zone, name="zoneSnapshot", fields=("revision",))
    _validate_polygon_snapshot(zone["polygon"])


def _validate_execution_policy_snapshot(raw: object) -> None:
    policy = _snapshot_object(
        raw, name="executionPolicy", expected_fields=_EXECUTION_POLICY_SNAPSHOT_FIELDS
    )
    _snapshot_strings(
        policy,
        name="executionPolicy",
        fields=(
            "contractVersion",
            "policyId",
            "algorithmBuildDigest",
            "configDigest",
            "uncertaintyMethod",
            "resourceEnvelopeDigest",
            "authorityRecordDigest",
            "policyDigest",
        ),
    )
    _snapshot_ints(policy, name="executionPolicy", fields=("version",))
    _snapshot_floats(
        policy, name="executionPolicy", fields=("thresholdM", "minimumCommonValidFraction")
    )
    _snapshot_bools(policy, name="executionPolicy", fields=("syntheticTestOnly",))


def _strict_snapshot_equal(raw: object, canonical: object) -> bool:
    """Compare serializer output without Python's ``True == 1`` or ``1 == 1.0`` coercion."""
    if type(raw) is not type(canonical):
        return False
    if isinstance(raw, dict) and isinstance(canonical, dict):
        return set(raw) == set(canonical) and all(
            _strict_snapshot_equal(raw[key], canonical[key]) for key in raw
        )
    if isinstance(raw, list) and isinstance(canonical, list):
        return len(raw) == len(canonical) and all(
            _strict_snapshot_equal(value, canonical[index]) for index, value in enumerate(raw)
        )
    return raw == canonical


def _validate_authority_snapshot_raw(raw: object) -> dict[str, Any]:
    authority = _snapshot_object(raw, name="authority", expected_fields=_AUTHORITY_SNAPSHOT_FIELDS)
    _snapshot_strings(
        authority,
        name="authority",
        fields=(
            "organizationId",
            "siteId",
            "currentWorkOrderId",
            "decisionId",
            "decisionDigest",
            "compatibilityMappingDigest",
            "validationPolicyDigest",
            "validFrom",
            "validUntil",
            "historicalAuthorityDigest",
        ),
    )
    if _SHA256_DIGEST.fullmatch(authority["historicalAuthorityDigest"]) is None:
        raise ValueError("historical authority identity must be a sha256 digest")
    _validate_input_binding_snapshot(authority["baseline"], name="baseline")
    _validate_input_binding_snapshot(authority["current"], name="current")
    _snapshot_string_list(authority["evidenceRecordDigests"], name="evidenceRecordDigests")
    _validate_zone_snapshot(authority["zoneSnapshot"])
    _validate_execution_policy_snapshot(authority["executionPolicy"])
    _snapshot_string_list(authority["authorizedActorIds"], name="authorizedActorIds")
    for field in ("baselineRmseM", "currentRmseM"):
        if authority[field] is not None and type(authority[field]) is not float:
            raise ValueError(f"authority snapshot {field} must be a canonical float or null")
    _snapshot_ints(authority, name="authority", fields=("maximumZoneCellCount",))
    _snapshot_floats(authority, name="authority", fields=("maximumZoneAreaM2",))
    _snapshot_bools(authority, name="authority", fields=("syntheticTestOnly",))
    return authority


def _valid_failure_reason(value: object) -> bool:
    return type(value) is str and _FAILURE_REASON.fullmatch(value) is not None


def _status_from_lease_denial(reason: LeaseDenialReason) -> ExternalRelativeVolumeVerdict:
    return {
        LeaseDenialReason.MISSING_OR_EXPIRED: ExternalRelativeVolumeVerdict.LEASE_REQUIRED,
        LeaseDenialReason.HELD_BY_ANOTHER: ExternalRelativeVolumeVerdict.LEASE_HELD_BY_ANOTHER,
        LeaseDenialReason.STALE_ACQUISITION: ExternalRelativeVolumeVerdict.STALE_LEASE_ACQUISITION,
        LeaseDenialReason.STALE_GENERATION: ExternalRelativeVolumeVerdict.STALE_LEASE_GENERATION,
        LeaseDenialReason.INVALID_FENCE: ExternalRelativeVolumeVerdict.INVALID_LEASE_FENCE,
    }[reason]


class ExternalRelativeVolumeRecoveryError(RuntimeError):
    """The append-only volume journal cannot safely be replayed."""


class ExternalRelativeVolumeVerdict(StrEnum):
    ISSUED = "ISSUED"
    ALREADY_ISSUED = "ALREADY_ISSUED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    QUEUE_FULL = "QUEUE_FULL"
    AUTHORITY_UNAVAILABLE = "AUTHORITY_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    REQUEST_NOT_ACTIVE = "REQUEST_NOT_ACTIVE"
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    LEASED = "LEASED"
    LEASE_RENEWED = "LEASE_RENEWED"
    LEASE_REQUIRED = "LEASE_REQUIRED"
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    STALE_LEASE_ACQUISITION = "STALE_LEASE_ACQUISITION"
    STALE_LEASE_GENERATION = "STALE_LEASE_GENERATION"
    INVALID_LEASE_FENCE = "INVALID_LEASE_FENCE"
    INPUT_READY = "INPUT_READY"
    REPORTED = "REPORTED"
    REPORT_CONFLICT = "REPORT_CONFLICT"
    INVALID_REPORT = "INVALID_REPORT"
    FAILED = "FAILED"


_HTTP_STATUS: dict[ExternalRelativeVolumeVerdict, int] = {
    ExternalRelativeVolumeVerdict.ISSUED: 201,
    ExternalRelativeVolumeVerdict.ALREADY_ISSUED: 200,
    ExternalRelativeVolumeVerdict.IDEMPOTENCY_CONFLICT: 409,
    ExternalRelativeVolumeVerdict.QUEUE_FULL: 429,
    ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE: 422,
    ExternalRelativeVolumeVerdict.NOT_FOUND: 404,
    ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE: 503,
    ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE: 409,
    ExternalRelativeVolumeVerdict.DEADLINE_EXPIRED: 409,
    ExternalRelativeVolumeVerdict.RETRY_EXHAUSTED: 409,
    ExternalRelativeVolumeVerdict.LEASED: 201,
    ExternalRelativeVolumeVerdict.LEASE_RENEWED: 200,
    ExternalRelativeVolumeVerdict.LEASE_REQUIRED: 409,
    ExternalRelativeVolumeVerdict.LEASE_HELD_BY_ANOTHER: 409,
    ExternalRelativeVolumeVerdict.STALE_LEASE_ACQUISITION: 409,
    ExternalRelativeVolumeVerdict.STALE_LEASE_GENERATION: 409,
    ExternalRelativeVolumeVerdict.INVALID_LEASE_FENCE: 422,
    ExternalRelativeVolumeVerdict.INPUT_READY: 200,
    ExternalRelativeVolumeVerdict.REPORTED: 201,
    ExternalRelativeVolumeVerdict.REPORT_CONFLICT: 409,
    ExternalRelativeVolumeVerdict.INVALID_REPORT: 422,
    ExternalRelativeVolumeVerdict.FAILED: 200,
}


@dataclass(frozen=True, slots=True)
class ExternalRelativeVolumeQueuePolicy:
    """Explicit Core-owned queue bounds, never worker or client input."""

    lease_ttl: timedelta
    deadline_after_issue: timedelta
    max_attempts: int
    max_active_requests_per_organization: int

    def __post_init__(self) -> None:
        if self.lease_ttl <= timedelta() or self.deadline_after_issue <= timedelta():
            raise ValueError("queue lease and deadline durations must be positive")
        if self.lease_ttl > self.deadline_after_issue:
            raise ValueError("queue lease duration cannot exceed request deadline")
        if self.max_attempts < 1 or self.max_attempts > 64:
            raise ValueError("queue max_attempts must be between 1 and 64")
        if not 1 <= self.max_active_requests_per_organization <= 100_000:
            raise ValueError(
                "queue max_active_requests_per_organization must be between 1 and 100000"
            )


@dataclass(frozen=True, slots=True)
class ExternalRelativeVolumeExecutionAuthority:
    """Full, independently resolved eligibility and execution binding.

    This is intentionally richer than a digest.  Its fields bind the decision,
    ordered DSM inputs, evidence, immutable zone, active policies and numeric
    limits before Core mints a request.  A real adapter derives it from Core's
    external-use/evidence stores; no caller is allowed to supply it.
    """

    organization_id: str
    site_id: str
    current_work_order_id: str
    decision_id: str
    decision_digest: str
    compatibility_mapping_digest: str
    baseline: ExternalVolumeInputBindingV1
    current: ExternalVolumeInputBindingV1
    evidence_record_digests: tuple[str, ...]
    validation_policy_digest: str
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    execution_policy: ExternalRelativeVolumeExecutionPolicyV1
    authorized_actor_ids: frozenset[str]
    valid_from: datetime
    valid_until: datetime
    historical_authority_digest: str
    baseline_rmse_m: float | None
    current_rmse_m: float | None
    maximum_zone_cell_count: int
    maximum_zone_area_m2: float
    synthetic_test_only: bool = False

    def __post_init__(self) -> None:
        _require_utc(self.valid_from, name="valid_from")
        _require_utc(self.valid_until, name="valid_until")
        if self.valid_from >= self.valid_until:
            raise ValueError("authority validity interval must be ordered")
        if not self.authorized_actor_ids:
            raise ValueError("authority requires at least one authorized actor")
        if not self.evidence_record_digests or len(set(self.evidence_record_digests)) != len(
            self.evidence_record_digests
        ):
            raise ValueError("authority evidence records must be non-empty and unique")
        if self.current.subject.work_order_id != self.current_work_order_id:
            raise ValueError("authority current input must bind current_work_order_id")
        if _SHA256_DIGEST.fullmatch(self.compatibility_mapping_digest) is None:
            raise ValueError("authority compatibility mapping must be a sha256 digest")
        if _SHA256_DIGEST.fullmatch(self.historical_authority_digest) is None:
            raise ValueError("historical authority identity must be a sha256 digest")
        if (
            self.baseline.subject.organization_id != self.organization_id
            or self.current.subject.organization_id != self.organization_id
        ):
            raise ValueError("authority inputs must have the authority organization")
        if (
            self.baseline.subject.site_id != self.site_id
            or self.current.subject.site_id != self.site_id
        ):
            raise ValueError("authority inputs must have the authority site")
        if (
            self.zone_snapshot.organization_id != self.organization_id
            or self.zone_snapshot.site_id != self.site_id
        ):
            raise ValueError("authority zone must have the authority scope")
        if (
            self.execution_policy.policy_digest is None
            or self.zone_snapshot.definition_digest is None
        ):
            raise ValueError("authority requires sealed policy and zone snapshots")
        if (
            type(self.maximum_zone_cell_count) is not int
            or type(self.maximum_zone_area_m2) is not float
            or type(self.synthetic_test_only) is not bool
        ):
            raise ValueError(
                "authority resource limits and test flag must use canonical JSON types"
            )
        if (
            self.maximum_zone_cell_count < 1
            or not math.isfinite(self.maximum_zone_area_m2)
            or self.maximum_zone_area_m2 <= 0
        ):
            raise ValueError("authority numeric resource limits must be finite and positive")
        for value in (self.baseline_rmse_m, self.current_rmse_m):
            if value is not None and type(value) is not float:
                raise ValueError("authority RMSE values must use canonical float or null")
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("authority RMSE values must be finite non-negative numbers")
        _validate_authority_snapshot_raw(self.snapshot_payload())

    def is_current_at(self, now: datetime) -> bool:
        _require_utc(now, name="now")
        return self.valid_from <= now < self.valid_until

    def snapshot_payload(self) -> dict[str, Any]:
        return {
            "organizationId": self.organization_id,
            "siteId": self.site_id,
            "currentWorkOrderId": self.current_work_order_id,
            "decisionId": self.decision_id,
            "decisionDigest": self.decision_digest,
            "compatibilityMappingDigest": self.compatibility_mapping_digest,
            "baseline": self.baseline.model_dump(by_alias=True, mode="json"),
            "current": self.current.model_dump(by_alias=True, mode="json"),
            "evidenceRecordDigests": list(self.evidence_record_digests),
            "validationPolicyDigest": self.validation_policy_digest,
            "zoneSnapshot": external_volume_zone_snapshot_wire_dict(self.zone_snapshot),
            "executionPolicy": external_relative_volume_execution_policy_wire_dict(
                self.execution_policy
            ),
            "authorizedActorIds": sorted(self.authorized_actor_ids),
            "validFrom": iso_utc(self.valid_from),
            "validUntil": iso_utc(self.valid_until),
            "historicalAuthorityDigest": self.historical_authority_digest,
            "baselineRmseM": self.baseline_rmse_m,
            "currentRmseM": self.current_rmse_m,
            "maximumZoneCellCount": self.maximum_zone_cell_count,
            "maximumZoneAreaM2": self.maximum_zone_area_m2,
            "syntheticTestOnly": self.synthetic_test_only,
        }

    @classmethod
    def from_snapshot(cls, raw: dict[str, Any]) -> ExternalRelativeVolumeExecutionAuthority:
        snapshot = _validate_authority_snapshot_raw(raw)
        authority = cls(
            organization_id=snapshot["organizationId"],
            site_id=snapshot["siteId"],
            current_work_order_id=snapshot["currentWorkOrderId"],
            decision_id=snapshot["decisionId"],
            decision_digest=snapshot["decisionDigest"],
            compatibility_mapping_digest=snapshot["compatibilityMappingDigest"],
            baseline=ExternalVolumeInputBindingV1.model_validate(snapshot["baseline"]),
            current=ExternalVolumeInputBindingV1.model_validate(snapshot["current"]),
            evidence_record_digests=tuple(snapshot["evidenceRecordDigests"]),
            validation_policy_digest=snapshot["validationPolicyDigest"],
            zone_snapshot=ExternalVolumeZoneSnapshotV1.model_validate(snapshot["zoneSnapshot"]),
            execution_policy=ExternalRelativeVolumeExecutionPolicyV1.model_validate(
                snapshot["executionPolicy"]
            ),
            authorized_actor_ids=frozenset(snapshot["authorizedActorIds"]),
            valid_from=datetime.fromisoformat(snapshot["validFrom"]),
            valid_until=datetime.fromisoformat(snapshot["validUntil"]),
            historical_authority_digest=snapshot["historicalAuthorityDigest"],
            baseline_rmse_m=snapshot["baselineRmseM"],
            current_rmse_m=snapshot["currentRmseM"],
            maximum_zone_cell_count=snapshot["maximumZoneCellCount"],
            maximum_zone_area_m2=snapshot["maximumZoneAreaM2"],
            synthetic_test_only=snapshot["syntheticTestOnly"],
        )
        if not _strict_snapshot_equal(snapshot, authority.snapshot_payload()):
            raise ValueError("authority snapshot does not match canonical serializer output")
        return authority


def _canonical_authority_snapshot(
    authority: ExternalRelativeVolumeExecutionAuthority,
) -> tuple[ExternalRelativeVolumeExecutionAuthority, dict[str, Any]]:
    """Return a complete strict snapshot and its reconstruction for live publication.

    Authority ports are trusted Core seams, but an unsafe in-memory mutation must
    still not append a journal record that strict recovery will reject.
    """

    snapshot = authority.snapshot_payload()
    return ExternalRelativeVolumeExecutionAuthority.from_snapshot(snapshot), snapshot


class ExternalRelativeVolumeExecutionActivator(Protocol):
    def __call__(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None: ...


class _VolumeExecutionPolicy(Protocol):
    @property
    def synthetic_test_only(self) -> bool: ...

    def canonical_digest(self) -> str: ...


class _VolumeAuthority(Protocol):
    @property
    def organization_id(self) -> str: ...
    @property
    def site_id(self) -> str: ...
    @property
    def current_work_order_id(self) -> str: ...
    @property
    def decision_id(self) -> str: ...
    @property
    def decision_digest(self) -> str: ...
    @property
    def historical_authority_digest(self) -> str: ...
    @property
    def authorized_actor_ids(self) -> frozenset[str]: ...
    @property
    def valid_until(self) -> datetime: ...
    @property
    def synthetic_test_only(self) -> bool: ...
    @property
    def validation_policy_digest(self) -> str: ...
    @property
    def execution_policy(self) -> _VolumeExecutionPolicy: ...
    @property
    def zone_snapshot(self) -> ExternalVolumeZoneSnapshotV1: ...

    def is_current_at(self, now: datetime) -> bool: ...

    def snapshot_payload(self) -> dict[str, Any]: ...


class _VolumeRequest(Protocol):
    @property
    def request_id(self) -> str: ...
    @property
    def request_digest(self) -> str | None: ...
    @property
    def current_work_order_id(self) -> str: ...
    @property
    def decision_id(self) -> str: ...
    @property
    def decision_digest(self) -> str: ...
    @property
    def idempotency_key(self) -> str: ...
    @property
    def issued_at(self) -> datetime: ...
    @property
    def validation_policy_digest(self) -> str: ...
    @property
    def execution_policy_digest(self) -> str: ...
    @property
    def zone_snapshot(self) -> ExternalVolumeZoneSnapshotV1: ...

    def model_copy(self, *, deep: bool = ...) -> Any: ...


class _VolumeReport(Protocol):
    @property
    def report_id(self) -> str: ...
    @property
    def report_digest(self) -> str | None: ...
    @property
    def request_id(self) -> str: ...
    @property
    def request_digest(self) -> str: ...
    @property
    def measurement_payload_digest(self) -> str | None: ...
    @property
    def worker_instance_id(self) -> str: ...
    @property
    def lease_acquisition_id(self) -> str: ...
    @property
    def lease_generation(self) -> int: ...
    @property
    def reported_at(self) -> datetime: ...
    @property
    def payload(self) -> Any: ...

    def model_copy(self, *, deep: bool = ...) -> Any: ...


class _VolumePayload(Protocol):
    def canonical_digest(self) -> str: ...


class ExternalVolumeExecutionAuthorityPort[AuthorityT: _VolumeAuthority](Protocol):
    """Trusted Core seam.  Implementations must have no caller-derived truth."""

    currentness_coordinator: ExternalAuthorityCurrentnessCoordinator

    def resolve_for_issue(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        now: datetime,
    ) -> AuthorityT | None: ...

    def guard_current(
        self,
        *,
        authority: AuthorityT,
        principal: Principal,
        now: datetime,
    ) -> AbstractContextManager[AuthorityT | None]: ...

    def resolve_historical(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        issued_at: datetime,
        now: datetime,
    ) -> AuthorityT | None: ...


class VolumeLaunchMaterialResolverPort[RequestT: _VolumeRequest, AuthorityT: _VolumeAuthority](
    Protocol
):
    @property
    def currentness_coordinator(self) -> ExternalAuthorityCurrentnessCoordinator: ...

    def preflight(self, request: RequestT, authority: AuthorityT, *, now: datetime) -> Any: ...

    def material_remains_current(
        self, request: RequestT, authority: AuthorityT, material: Any, *, now: datetime
    ) -> bool: ...


class ExternalRelativeVolumeExecutionAuthorityPort(
    ExternalVolumeExecutionAuthorityPort[ExternalRelativeVolumeExecutionAuthority], Protocol
):
    """Relative-volume parametrization of the execution authority seam."""


class ExternalRelativeVolumeStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ExternalVolumeRecord[
    RequestT: _VolumeRequest,
    AuthorityT: _VolumeAuthority,
    ReportT: _VolumeReport,
]:
    request: RequestT
    authority: AuthorityT
    status: ExternalRelativeVolumeStatus
    issued_by: str
    issued_at: datetime
    deadline_at: datetime
    attempts: int = 0
    lease: JobLease | None = None
    report: ReportT | None = None
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedVolumeReport[
    RequestT: _VolumeRequest,
    AuthorityT: _VolumeAuthority,
    ReportT: _VolumeReport,
]:
    """Immutable report source proof for a downstream Core-only consumer."""

    request: RequestT
    report: ReportT
    execution_authority: AuthorityT


@dataclass(frozen=True, slots=True)
class ExternalVolumeResult[
    RequestT: _VolumeRequest,
    AuthorityT: _VolumeAuthority,
    ReportT: _VolumeReport,
]:
    verdict: ExternalRelativeVolumeVerdict
    record: ExternalVolumeRecord[RequestT, AuthorityT, ReportT] | None = None
    created: bool = False
    detail: str | None = None

    @property
    def fence(self) -> LeaseFence | None:
        return self.record.lease.fence if self.record is not None and self.record.lease else None

    @property
    def lease_expires_at(self) -> datetime | None:
        if self.record is None or self.record.lease is None:
            return None
        return self.record.lease.expires_at


@dataclass(frozen=True, slots=True)
class ExternalVolumeObservedReportInput[PayloadT: _VolumePayload]:
    """Worker observation.  Core supplies id, fence and report sealing fields."""

    payload: PayloadT
    computed_at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.computed_at, name="computed_at")


ExternalRelativeVolumeRecord = ExternalVolumeRecord[
    ExternalRelativeVolumeRequestV1,
    ExternalRelativeVolumeExecutionAuthority,
    ExternalRelativeVolumeReportV1,
]
ExternalRelativeVolumeResult = ExternalVolumeResult[
    ExternalRelativeVolumeRequestV1,
    ExternalRelativeVolumeExecutionAuthority,
    ExternalRelativeVolumeReportV1,
]
ResolvedRelativeVolumeReport = ResolvedVolumeReport[
    ExternalRelativeVolumeRequestV1,
    ExternalRelativeVolumeExecutionAuthority,
    ExternalRelativeVolumeReportV1,
]
ExternalRelativeVolumeObservedReportInput = ExternalVolumeObservedReportInput[
    ExternalRelativeVolumeMeasurementPayloadV1
]


class ExternalRelativeVolumeIssueInput(CamelModel):
    decision_ref: _BoundedText


class ExternalRelativeVolumeLeaseInput(CamelModel):
    worker_instance_id: _BoundedText
    lease_acquisition_id: _BoundedText
    # Zero is a CLAIM-only acquisition sentinel.  Core persists and returns
    # the positive journal generation; all later worker mutations require it.
    lease_generation: StrictInt = Field(ge=0)
    mode: LeaseMode = LeaseMode.CLAIM


class ExternalRelativeVolumeHeartbeatInput(CamelModel):
    worker_instance_id: _BoundedText
    lease_acquisition_id: _BoundedText
    lease_generation: StrictInt = Field(ge=1)


class ExternalRelativeVolumeWorkerReportInput(CamelModel):
    payload: ExternalRelativeVolumeMeasurementPayloadV1
    computed_at: datetime

    @field_validator("computed_at")
    @classmethod
    def _computed_at_is_utc(cls, value: datetime) -> datetime:
        _require_utc(value, name="computedAt")
        return value


class ExternalRelativeVolumeWorkerFailureInput(CamelModel):
    reason: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{0,127}$"
        ),
    ]


class ExternalRelativeVolumeRequestView(CamelModel):
    request_ref: str
    status: ExternalRelativeVolumeStatus
    current_work_order_id: str
    decision_digest: str
    issued_at: datetime
    deadline_at: datetime
    report_ref: str | None
    report_digest: str | None


class ExternalRelativeVolumeListResponse(CamelModel):
    items: list[ExternalRelativeVolumeRequestView]


class ExternalRelativeVolumeMutationResponse(CamelModel):
    verdict: ExternalRelativeVolumeVerdict
    request: ExternalRelativeVolumeRequestView | None = None
    fence: ExternalRelativeVolumeLeaseFenceView | None = None
    lease_expires_at: datetime | None = None
    detail: str | None = None


class ExternalRelativeVolumeLeaseFenceView(CamelModel):
    worker_instance_id: str
    lease_acquisition_id: str
    lease_generation: StrictInt = Field(ge=1)


class ExternalRelativeVolumePendingView(CamelModel):
    request_ref: str
    issued_at: datetime


class ExternalRelativeVolumePendingResponse(CamelModel):
    items: list[ExternalRelativeVolumePendingView]


class ExternalRelativeVolumeInputCapability(CamelModel):
    role: str
    download_url: str
    required_headers: dict[str, str]
    expires_at: datetime


class ExternalRelativeVolumeWorkerInputView(CamelModel):
    request: dict[str, Any]
    execution_policy: dict[str, Any]
    validation_policy: ExternalValidationPolicyV1
    volume_evidence_records: tuple[ExternalEvidenceRecordV1, ExternalEvidenceRecordV1]
    inputs: tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability]


class ExternalRelativeVolumeWorkerInputResponse(CamelModel):
    verdict: ExternalRelativeVolumeVerdict
    input: ExternalRelativeVolumeWorkerInputView | None = None
    detail: str | None = None


class ExternalRelativeVolumeInputCapabilityIssuer(Protocol):
    def __call__(
        self,
        record: ExternalRelativeVolumeRecord,
        *,
        fence: LeaseFence,
        principal: Principal,
        now: datetime,
    ) -> (
        tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability] | None
    ): ...


class ExternalVolumeLedger[
    RequestT: _VolumeRequest,
    AuthorityT: _VolumeAuthority,
    ReportT: _VolumeReport,
    PayloadT: _VolumePayload,
]:
    """One append-only journal, one lock, and rechecked authoritative permission.

    Family-neutral: a concrete volume family supplies its contract types, journal
    kind prefix and the hooks below.  Everything about queueing, leasing,
    fencing, idempotency and replay is shared.
    """

    _LABEL: ClassVar[str]
    _KIND_PREFIX: ClassVar[str]
    _recovery_error: ClassVar[type[RuntimeError]]

    # -- family hooks ---------------------------------------------------------------------
    def _authority_from_snapshot(self, raw: dict[str, Any]) -> AuthorityT:
        raise NotImplementedError

    def _request_from_wire(self, raw: object) -> RequestT:
        raise NotImplementedError

    def _request_wire(self, request: RequestT) -> dict[str, Any]:
        raise NotImplementedError

    def _report_from_wire(self, raw: object) -> ReportT:
        raise NotImplementedError

    def _report_wire(self, report: ReportT) -> dict[str, Any]:
        raise NotImplementedError

    def _build_report(self, **fields: Any) -> ReportT:
        raise NotImplementedError

    def _build_request(
        self,
        authority: AuthorityT,
        *,
        request_id: str,
        current_work_order_id: str,
        issued_at: datetime,
        idempotency_key: str,
    ) -> RequestT:
        raise NotImplementedError

    @staticmethod
    def _natural_fingerprint(
        *, organization_id: str, current_work_order_id: str, authority: Any
    ) -> str:
        raise NotImplementedError

    def _inputs_binding_error(self, request: RequestT, authority: AuthorityT) -> str | None:
        raise NotImplementedError

    def _primary_site_id(self, authority: AuthorityT) -> str:
        raise NotImplementedError

    def _report_sort_time(
        self, record: ExternalVolumeRecord[RequestT, AuthorityT, ReportT]
    ) -> datetime:
        raise NotImplementedError

    def _measurement_payload_error(
        self, record: ExternalVolumeRecord[RequestT, AuthorityT, ReportT], payload: PayloadT
    ) -> str | None:
        raise NotImplementedError

    # -- shared helpers -------------------------------------------------------------------
    def _kind(self, suffix: str) -> str:
        return f"{self._KIND_PREFIX}-{suffix}"

    def _raw_string(self, raw: dict[str, Any], name: str) -> str:
        value = raw.get(name)
        if type(value) is not str:
            raise self._recovery_error(f"external {self._LABEL} journal {name} must be a string")
        return value

    def _raw_int(self, raw: dict[str, Any], name: str) -> int:
        value = raw.get(name)
        if type(value) is not int:
            raise self._recovery_error(f"external {self._LABEL} journal {name} must be an integer")
        return value

    def _raw_mapping(self, raw: dict[str, Any], name: str) -> dict[str, Any]:
        value = raw.get(name)
        if type(value) is not dict:
            raise self._recovery_error(f"external {self._LABEL} journal {name} must be an object")
        return value

    def _canonical_authority_snapshot(
        self, authority: AuthorityT
    ) -> tuple[AuthorityT, dict[str, Any]]:
        """Return a complete strict snapshot and its reconstruction for live publication.

        Authority ports are trusted Core seams, but an unsafe in-memory mutation must
        still not append a journal record that strict recovery will reject.
        """
        snapshot = authority.snapshot_payload()
        return self._authority_from_snapshot(snapshot), snapshot

    def __init__(
        self,
        journal: DurableJournal,
        *,
        authority_port: ExternalVolumeExecutionAuthorityPort[AuthorityT],
        currentness_coordinator: ExternalAuthorityCurrentnessCoordinator,
        queue_policy: ExternalRelativeVolumeQueuePolicy,
        launch_material_resolver: VolumeLaunchMaterialResolverPort[RequestT, AuthorityT]
        | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if authority_port.currentness_coordinator is not currentness_coordinator:
            raise ValueError("authority port and store must share one currentness coordinator")
        self._journal = journal
        self._authority_port = authority_port
        self._coordinator = currentness_coordinator
        if (
            launch_material_resolver is not None
            and launch_material_resolver.currentness_coordinator is not currentness_coordinator
        ):
            raise ValueError(
                "launch material resolver and store must share one currentness coordinator"
            )
        self._launch_material_resolver = launch_material_resolver
        self._queue_policy = queue_policy
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._records: dict[str, ExternalVolumeRecord[RequestT, AuthorityT, ReportT]] = {}
        self._idempotency: dict[tuple[str, str, str], tuple[str, str]] = {}
        self._natural: dict[str, str] = {}
        self._report_refs: dict[tuple[str, str], str] = {}
        self._lease_generation: dict[str, int] = {}
        self._lease_acquisition_ids: dict[str, set[str]] = {}
        self._report_listeners: list[
            Callable[[ExternalVolumeRecord[RequestT, AuthorityT, ReportT]], None]
        ] = []
        self._replay()

    @property
    def launch_material_resolver(
        self,
    ) -> VolumeLaunchMaterialResolverPort[RequestT, AuthorityT] | None:
        return self._launch_material_resolver

    def bind_report_listener(
        self, listener: Callable[[ExternalVolumeRecord[RequestT, AuthorityT, ReportT]], None]
    ) -> None:
        """Bind a post-commit projection; the report verdict never depends on it."""
        with self._lock:
            if listener not in self._report_listeners:
                self._report_listeners.append(listener)

    def _notify_report_listeners(
        self, record: ExternalVolumeRecord[RequestT, AuthorityT, ReportT]
    ) -> None:
        """Run outside store locks and coordinator guards; failures are logged only."""
        for listener in tuple(self._report_listeners):
            try:
                listener(record)
            except Exception:
                _LOGGER.exception(
                    self._LABEL.replace("-", " ") + " report listener failed",
                    extra={"request_ref": record.request.request_id},
                )

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        """Readonly assembly identity for shared Core-currentness validation."""
        return self._coordinator

    def journal_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._journal.replay())

    @staticmethod
    def _idempotency_hash(key: str) -> str:
        normalized = key.strip()
        if not normalized or len(normalized) > 255:
            raise ValueError("Idempotency-Key required")
        return hashlib.sha256(normalized.encode()).hexdigest()

    @classmethod
    def _request_id(cls, natural: str) -> str:
        return cls._KIND_PREFIX + "-" + hashlib.sha256((natural + "\0id").encode()).hexdigest()[:32]

    def _now(self, supplied: datetime | None) -> datetime:
        value = supplied if supplied is not None else self._clock()
        _require_utc(value, name="now")
        return value

    def _append_locked(
        self,
        raw: dict[str, Any],
        *,
        issued_authority: AuthorityT | None = None,
    ) -> None:
        raw["eventDigest"] = _event_digest(raw)
        self._journal.append(raw)
        self._apply(raw, issued_authority=issued_authority)

    def _replay(self) -> None:
        for raw in self._journal.replay():
            issued_authority: AuthorityT | None = None
            kind = self._raw_string(raw, "kind")
            if self._raw_int(raw, "version") != _VERSION:
                raise self._recovery_error(f"external {self._LABEL} event version is invalid")
            if kind == self._kind("issued"):
                try:
                    request = self._request_from_wire(raw["request"])
                    if request.request_digest is None:
                        raise ValueError("issued request must be sealed")
                    issued_at = datetime.fromisoformat(self._raw_string(raw, "issuedAt"))
                    _require_utc(issued_at, name="issuedAt")
                    snapshot_authority = self._authority_from_snapshot(raw["authority"])
                    issued_authority = self._authority_port.resolve_historical(
                        historical_authority_digest=snapshot_authority.historical_authority_digest,
                        decision_id=request.decision_id,
                        decision_digest=request.decision_digest,
                        issued_at=issued_at,
                        now=issued_at,
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise self._recovery_error(
                        f"malformed historical {self._LABEL} issue authority"
                    ) from exc
                if issued_authority is None:
                    raise self._recovery_error(f"historical {self._LABEL} authority is unavailable")
            self._apply(raw, recovery=True, issued_authority=issued_authority)

    def _issued_request_authority_error(
        self,
        request: RequestT,
        authority: AuthorityT,
        *,
        organization_id: str,
        key_hash: str,
        natural: str,
        issued_at: datetime,
        issued_by: str,
    ) -> str | None:
        """Return a deterministic error for a sealed issue/authority mismatch."""

        if request.request_digest is None:
            return "issued request is not sealed"
        if organization_id != authority.organization_id:
            return "issued organization differs from authority"
        if request.current_work_order_id != authority.current_work_order_id:
            return "issued work order differs from authority"
        if (
            request.decision_id != authority.decision_id
            or request.decision_digest != authority.decision_digest
        ):
            return "issued decision differs from authority"
        inputs_error = self._inputs_binding_error(request, authority)
        if inputs_error is not None:
            return inputs_error
        if request.validation_policy_digest != authority.validation_policy_digest:
            return "issued validation policy differs from authority"
        if request.execution_policy_digest != authority.execution_policy.canonical_digest():
            return "issued execution policy differs from authority"
        if request.zone_snapshot != authority.zone_snapshot:
            return "issued zone differs from authority"
        if request.issued_at != issued_at or not authority.is_current_at(issued_at):
            return "issued authority time binding is invalid"
        if issued_by not in authority.authorized_actor_ids:
            return "issued principal differs from authority"
        if self._idempotency_hash(request.idempotency_key) != key_hash:
            return "issued idempotency key binding is invalid"
        expected_natural = self._natural_fingerprint(
            organization_id=organization_id,
            current_work_order_id=request.current_work_order_id,
            authority=authority,
        )
        if natural != expected_natural or request.request_id != self._request_id(expected_natural):
            return "issued natural request binding is invalid"
        return None

    def _apply(
        self,
        raw: dict[str, Any],
        *,
        recovery: bool = False,
        issued_authority: AuthorityT | None = None,
    ) -> None:
        try:
            if self._raw_int(raw, "version") != _VERSION or raw.get("eventDigest") != _event_digest(
                raw
            ):
                raise self._recovery_error(f"external {self._LABEL} event digest/version mismatch")
            kind = self._raw_string(raw, "kind")
            if kind == self._kind("issued"):
                request = self._request_from_wire(raw["request"])
                if request.request_digest is None:
                    raise self._recovery_error("issued request must be sealed")
                snapshot_authority = self._authority_from_snapshot(raw["authority"])
                if issued_authority is None or issued_authority != snapshot_authority:
                    raise self._recovery_error(
                        f"historical {self._LABEL} authority differs from issued snapshot"
                    )
                authority = issued_authority
                request_ref = self._raw_string(raw, "requestRef")
                if request.request_id in self._records or request.request_id != request_ref:
                    raise self._recovery_error(f"duplicate or substituted {self._LABEL} request")
                natural = self._raw_string(raw, "natural")
                binding = self._raw_mapping(raw, "idempotency")
                organization_id = self._raw_string(binding, "organizationId")
                key_hash = self._raw_string(binding, "keyHash")
                fingerprint = self._raw_string(binding, "fingerprint")
                if fingerprint != natural or natural in self._natural:
                    raise self._recovery_error(f"forged {self._LABEL} idempotency binding")
                issued_at = datetime.fromisoformat(self._raw_string(raw, "issuedAt"))
                deadline_at = datetime.fromisoformat(self._raw_string(raw, "deadlineAt"))
                _require_utc(issued_at, name="issuedAt")
                _require_utc(deadline_at, name="deadlineAt")
                if deadline_at <= issued_at:
                    raise self._recovery_error("issued deadline is not ordered")
                binding_error = self._issued_request_authority_error(
                    request,
                    authority,
                    organization_id=organization_id,
                    key_hash=key_hash,
                    natural=natural,
                    issued_at=issued_at,
                    issued_by=self._raw_string(raw, "issuedBy"),
                )
                if binding_error is not None:
                    raise self._recovery_error(
                        f"historical {self._LABEL} issue binding is invalid: {binding_error}"
                    )
                record: ExternalVolumeRecord[RequestT, AuthorityT, ReportT] = ExternalVolumeRecord(
                    request=request,
                    authority=authority,
                    status=ExternalRelativeVolumeStatus.QUEUED,
                    issued_by=self._raw_string(raw, "issuedBy"),
                    issued_at=issued_at,
                    deadline_at=deadline_at,
                )
                self._records[request.request_id] = record
                self._natural[natural] = request.request_id
                self._idempotency[(organization_id, request.current_work_order_id, key_hash)] = (
                    natural,
                    request.request_id,
                )
            elif kind == self._kind("idempotency-bound"):
                binding = self._raw_mapping(raw, "idempotency")
                target = self._raw_string(raw, "requestRef")
                target_record = self._records.get(target)
                if target_record is None:
                    raise self._recovery_error("idempotency binding refers to absent request")
                organization_id = self._raw_string(binding, "organizationId")
                natural = self._natural_fingerprint(
                    organization_id=organization_id,
                    current_work_order_id=target_record.request.current_work_order_id,
                    authority=target_record.authority,
                )
                key = (
                    organization_id,
                    target_record.request.current_work_order_id,
                    self._raw_string(binding, "keyHash"),
                )
                expected = (self._raw_string(binding, "fingerprint"), target)
                if (
                    organization_id != target_record.authority.organization_id
                    or expected != (natural, target)
                    or self._natural.get(natural) != target
                    or self._idempotency.get(key, expected) != expected
                ):
                    raise self._recovery_error("conflicting idempotency binding")
                self._idempotency[key] = expected
            elif kind == self._kind("leased"):
                self._apply_lease(raw)
            elif kind == self._kind("reported"):
                self._apply_report(raw)
            elif kind == self._kind("failed"):
                self._apply_failure(raw)
            else:
                raise self._recovery_error(f"unknown external {self._LABEL} event")
        except (KeyError, TypeError, ValueError) as exc:
            if recovery:
                raise self._recovery_error(f"malformed external {self._LABEL} journal") from exc
            raise

    def _apply_lease(self, raw: dict[str, Any]) -> None:
        request_id = self._raw_string(raw, "requestRef")
        record = self._records.get(request_id)
        if record is None or record.status not in {
            ExternalRelativeVolumeStatus.QUEUED,
            ExternalRelativeVolumeStatus.RUNNING,
        }:
            raise self._recovery_error(f"lease targets inactive {self._LABEL} request")
        lease = JobLease(
            worker_id=self._raw_string(raw, "workerInstanceId"),
            granted_at=datetime.fromisoformat(self._raw_string(raw, "grantedAt")),
            expires_at=datetime.fromisoformat(self._raw_string(raw, "expiresAt")),
            lease_acquisition_id=self._raw_string(raw, "leaseAcquisitionId"),
            lease_generation=self._raw_int(raw, "leaseGeneration"),
            authenticated_actor_id=self._raw_string(raw, "authenticatedActorId"),
        )
        if (
            lease.fence is None
            or not lease.fence.is_well_formed()
            or lease.expires_at <= lease.granted_at
        ):
            raise self._recovery_error(f"malformed {self._LABEL} lease")
        high_water = self._lease_generation.get(request_id, 0)
        lease_mode = self._raw_string(raw, "leaseMode")
        if lease_mode not in {LeaseMode.CLAIM.value, LeaseMode.RENEW.value}:
            raise self._recovery_error(f"{self._LABEL} lease mode is invalid")
        if lease.lease_generation != high_water + 1 and not (
            lease_mode == LeaseMode.RENEW.value
            and record.lease is not None
            and lease.lease_generation == high_water
            and record.lease.fence == lease.fence
        ):
            raise self._recovery_error(f"{self._LABEL} lease generation is not monotonic")
        used_acquisitions = self._lease_acquisition_ids.setdefault(request_id, set())
        acquisition_id = lease.lease_acquisition_id
        if acquisition_id is None:
            raise self._recovery_error(f"{self._LABEL} lease acquisition is absent")
        if lease_mode == LeaseMode.CLAIM.value and acquisition_id in used_acquisitions:
            raise self._recovery_error(f"{self._LABEL} lease acquisition is reused")
        self._lease_generation[request_id] = max(high_water, lease.lease_generation)
        if lease_mode == LeaseMode.CLAIM.value:
            used_acquisitions.add(acquisition_id)
        attempts = record.attempts + (1 if lease_mode == LeaseMode.CLAIM.value else 0)
        self._records[request_id] = replace(
            record, status=ExternalRelativeVolumeStatus.RUNNING, attempts=attempts, lease=lease
        )

    def _apply_report(self, raw: dict[str, Any]) -> None:
        request_id = self._raw_string(raw, "requestRef")
        record = self._records.get(request_id)
        if (
            record is None
            or record.report is not None
            or record.status is not ExternalRelativeVolumeStatus.RUNNING
            or record.lease is None
        ):
            raise self._recovery_error(f"duplicate or inactive {self._LABEL} report")
        report = self._report_from_wire(raw["report"])
        if (
            report.report_digest is None
            or report.request_id != request_id
            or report.request_digest != record.request.request_digest
        ):
            raise self._recovery_error(f"{self._LABEL} report request binding mismatch")
        if (
            report.worker_instance_id != record.lease.worker_instance_id
            or report.lease_acquisition_id != record.lease.lease_acquisition_id
            or report.lease_generation != record.lease.lease_generation
            or report.reported_at >= record.lease.expires_at
            or report.reported_at >= record.deadline_at
        ):
            raise self._recovery_error(f"{self._LABEL} report lease lineage mismatch")
        error = self._measurement_payload_error(record, report.payload)
        if error is not None:
            raise self._recovery_error(f"{self._LABEL} report violates sealed authority: {error}")
        report_key = (record.authority.organization_id, report.report_id)
        existing_request_ref = self._report_refs.get(report_key)
        if existing_request_ref is not None and existing_request_ref != request_id:
            raise self._recovery_error(
                f"{self._LABEL} report identity conflicts with another request"
            )
        self._report_refs[report_key] = request_id
        self._records[request_id] = replace(
            record, status=ExternalRelativeVolumeStatus.SUCCEEDED, report=report
        )

    def _apply_failure(self, raw: dict[str, Any]) -> None:
        request_id = self._raw_string(raw, "requestRef")
        record = self._records.get(request_id)
        if (
            record is None
            or record.status is not ExternalRelativeVolumeStatus.RUNNING
            or record.lease is None
        ):
            raise self._recovery_error(f"{self._LABEL} failure transition is invalid")
        reason = self._raw_string(raw, "reason")
        if not _valid_failure_reason(reason):
            raise self._recovery_error(f"{self._LABEL} failure reason is invalid")
        failure_at = datetime.fromisoformat(self._raw_string(raw, "failedAt"))
        _require_utc(failure_at, name="failedAt")
        fence = LeaseFence(
            self._raw_string(raw, "workerInstanceId"),
            self._raw_string(raw, "leaseAcquisitionId"),
            self._raw_int(raw, "leaseGeneration"),
        )
        authenticated_actor_id = self._raw_string(raw, "authenticatedActorId")
        if (
            not fence.is_well_formed()
            or record.lease.fence != fence
            or record.lease.authenticated_actor_id != authenticated_actor_id
            or failure_at < record.lease.granted_at
            or failure_at >= record.lease.expires_at
            or failure_at >= record.deadline_at
        ):
            raise self._recovery_error(f"{self._LABEL} failure lease lineage mismatch")
        self._records[request_id] = replace(
            record, status=ExternalRelativeVolumeStatus.FAILED, failure_reason=reason
        )

    def _prior_idempotency_result_locked(
        self,
        *,
        organization_id: str,
        current_work_order_id: str,
        key_hash: str,
        decision_ref: str,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT] | None:
        prior = self._idempotency.get((organization_id, current_work_order_id, key_hash))
        if prior is None:
            return None
        _, request_ref = prior
        record = self._records.get(request_ref)
        if record is None:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE)
        if decision_ref != record.authority.decision_id:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.IDEMPOTENCY_CONFLICT, record)
        # This is a read of an already immutable issue.  It grants no new
        # numerical execution, so it remains available after live authority
        # withdrawal or expiry.
        return ExternalVolumeResult(ExternalRelativeVolumeVerdict.ALREADY_ISSUED, record)

    def _active_request_count_locked(self, *, organization_id: str, now: datetime) -> int:
        return sum(
            record.authority.organization_id == organization_id
            and record.status
            in {ExternalRelativeVolumeStatus.QUEUED, ExternalRelativeVolumeStatus.RUNNING}
            and now < record.deadline_at
            for record in self._records.values()
        )

    def is_issue_retry(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        idempotency_key: str,
    ) -> bool:
        """Only an exact retained issue retry survives administrative closure."""

        key_hash = self._idempotency_hash(idempotency_key)
        with self._lock:
            prior = self._prior_idempotency_result_locked(
                organization_id=principal.organization_id,
                current_work_order_id=current_work_order_id,
                key_hash=key_hash,
                decision_ref=decision_ref,
            )
        return prior is not None and prior.verdict is ExternalRelativeVolumeVerdict.ALREADY_ISSUED

    def classify_issue_activation(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        idempotency_key: str,
        now: datetime,
    ) -> tuple[ExternalVolumeResult[RequestT, AuthorityT, ReportT] | None, bool]:
        """Read-only classification under the caller's authenticated WorkOrder guard.

        Existing idempotency results, including conflicts, must precede activation.
        A live execution authority needs no activation even for a new key; issue()
        still computes the exact natural fingerprint, checks currentness and writes
        any durable alias. Never hold the projection lock across authority lookup.
        This result is not commit authority and does not replace issue()'s checks.
        """
        issued_at = self._now(now)
        key_hash = self._idempotency_hash(idempotency_key)
        with self._lock:
            prior = self._prior_idempotency_result_locked(
                organization_id=principal.organization_id,
                current_work_order_id=current_work_order_id,
                key_hash=key_hash,
                decision_ref=decision_ref,
            )
            if prior is not None:
                return prior, False
        authority = self._authority_port.resolve_for_issue(
            principal=principal,
            current_work_order_id=current_work_order_id,
            decision_ref=decision_ref,
            now=issued_at,
        )
        with self._lock:
            prior = self._prior_idempotency_result_locked(
                organization_id=principal.organization_id,
                current_work_order_id=current_work_order_id,
                key_hash=key_hash,
                decision_ref=decision_ref,
            )
            if prior is not None:
                return prior, False
            if self._journal.sealed_reason is not None:
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE), False
        return None, authority is None

    def issue(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT]:
        issued_at = self._now(now)
        key_hash = self._idempotency_hash(idempotency_key)
        # An exact retry is a historical read, not a fresh execution request.
        # Check the scoped slot before resolving live authority so a revoked
        # decision cannot erase the caller's immutable response.
        with self._lock:
            prior = self._prior_idempotency_result_locked(
                organization_id=principal.organization_id,
                current_work_order_id=current_work_order_id,
                key_hash=key_hash,
                decision_ref=decision_ref,
            )
            if prior is not None:
                return prior
        # Resolution may entail durable Core lookups; it is intentionally outside
        # both the volume lock and the currentness critical section.
        authority = self._authority_port.resolve_for_issue(
            principal=principal,
            current_work_order_id=current_work_order_id,
            decision_ref=decision_ref,
            now=issued_at,
        )
        if authority is None:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
        try:
            canonical_authority, authority_snapshot = self._canonical_authority_snapshot(authority)
        except (AttributeError, TypeError, ValueError):
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
        if (
            canonical_authority.organization_id != principal.organization_id
            or canonical_authority.site_id != self._primary_site_id(canonical_authority)
        ):
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
        natural = self._natural_fingerprint(
            organization_id=principal.organization_id,
            current_work_order_id=current_work_order_id,
            authority=canonical_authority,
        )
        request = self._build_request(
            canonical_authority,
            request_id=self._request_id(natural),
            current_work_order_id=current_work_order_id,
            issued_at=issued_at,
            idempotency_key=idempotency_key.strip(),
        )
        binding_error = self._issued_request_authority_error(
            request,
            canonical_authority,
            organization_id=principal.organization_id,
            key_hash=key_hash,
            natural=natural,
            issued_at=issued_at,
            issued_by=principal.principal_id,
        )
        if binding_error is not None:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
        # A reviewed adapter's guard is local/coordinator-backed.  It may not
        # perform remote I/O and it is opened before this store's lock.
        with (
            self._coordinator.mutation(),
            self._authority_port.guard_current(
                authority=authority, principal=principal, now=issued_at
            ) as current_authority,
        ):
            if current_authority is None:
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
            if current_authority != authority:
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
            try:
                current_canonical_authority, current_authority_snapshot = (
                    self._canonical_authority_snapshot(current_authority)
                )
            except (AttributeError, TypeError, ValueError):
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
            if not _strict_snapshot_equal(authority_snapshot, current_authority_snapshot):
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
            with self._lock:
                prior = self._prior_idempotency_result_locked(
                    organization_id=principal.organization_id,
                    current_work_order_id=current_work_order_id,
                    key_hash=key_hash,
                    decision_ref=decision_ref,
                )
                if prior is not None:
                    return prior
                if self._journal.sealed_reason is not None:
                    return ExternalVolumeResult(ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE)
                existing_ref = self._natural.get(natural)
                if existing_ref is not None:
                    record = self._records[existing_ref]
                    raw = {
                        "kind": self._kind("idempotency-bound"),
                        "version": _VERSION,
                        "requestRef": existing_ref,
                        "idempotency": {
                            "organizationId": principal.organization_id,
                            "keyHash": key_hash,
                            "fingerprint": natural,
                        },
                    }
                    try:
                        self._append_locked(raw)
                    except JournalSealedError:
                        return ExternalVolumeResult(ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE)
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.ALREADY_ISSUED, record
                    )
                if (
                    self._active_request_count_locked(
                        organization_id=principal.organization_id, now=issued_at
                    )
                    >= self._queue_policy.max_active_requests_per_organization
                ):
                    return ExternalVolumeResult(ExternalRelativeVolumeVerdict.QUEUE_FULL)
                raw = {
                    "kind": self._kind("issued"),
                    "version": _VERSION,
                    "requestRef": request.request_id,
                    "request": self._request_wire(request),
                    "authority": current_authority_snapshot,
                    "natural": natural,
                    "idempotency": {
                        "organizationId": principal.organization_id,
                        "keyHash": key_hash,
                        "fingerprint": natural,
                    },
                    "issuedBy": principal.principal_id,
                    "issuedAt": iso_utc(issued_at),
                    "deadlineAt": iso_utc(issued_at + self._queue_policy.deadline_after_issue),
                }
                try:
                    self._append_locked(raw, issued_authority=current_canonical_authority)
                except JournalSealedError:
                    return ExternalVolumeResult(ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE)
                return ExternalVolumeResult(
                    ExternalRelativeVolumeVerdict.ISSUED,
                    self._records[request.request_id],
                    created=True,
                )

    def get(
        self, request_ref: str, *, organization_id: str
    ) -> ExternalVolumeRecord[RequestT, AuthorityT, ReportT] | None:
        with self._lock:
            record = self._records.get(request_ref)
            return (
                record
                if record is not None and record.authority.organization_id == organization_id
                else None
            )

    def list_for_work_order(
        self, current_work_order_id: str, *, organization_id: str
    ) -> tuple[ExternalVolumeRecord[RequestT, AuthorityT, ReportT], ...]:
        with self._lock:
            return tuple(
                record
                for record in self._records.values()
                if record.request.current_work_order_id == current_work_order_id
                and record.authority.organization_id == organization_id
            )

    def report_refs_for_site(self, site_id: str, *, organization_id: str) -> tuple[str, ...]:
        """Return retained report references in deterministic newest-first order.

        This deliberately exposes no request ledger. Callers must still resolve
        every reference through the independent historical authority before they
        display any report content.
        """

        with self._lock:
            records = [
                record
                for record in self._records.values()
                if record.authority.organization_id == organization_id
                and record.authority.site_id == site_id
                and record.report is not None
            ]
        return tuple(
            record.report.report_id
            for record in sorted(
                records,
                key=lambda record: (
                    self._report_sort_time(record),
                    record.report.reported_at if record.report is not None else record.issued_at,
                    record.report.report_id if record.report is not None else "",
                ),
                reverse=True,
            )
            if record.report is not None
        )

    def list_pending(
        self,
        *,
        organization_id: str,
        now: datetime | None = None,
        limit: int = 50,
    ) -> tuple[ExternalVolumeRecord[RequestT, AuthorityT, ReportT], ...]:
        when = self._now(now)
        if limit < 1 or limit > 200:
            raise ValueError("pending limit must be between 1 and 200")
        with self._lock:
            return tuple(
                sorted(
                    (
                        record
                        for record in self._records.values()
                        if record.authority.organization_id == organization_id
                        and record.attempts < self._queue_policy.max_attempts
                        and when < record.deadline_at
                        and is_claimable(
                            ProcessingJobStatus(record.status.value), record.lease, when
                        )
                    ),
                    key=lambda record: (record.issued_at, record.request.request_id),
                )[:limit]
            )

    def _lease_denial_locked(
        self,
        record: ExternalVolumeRecord[RequestT, AuthorityT, ReportT],
        *,
        fence: LeaseFence,
        principal_id: str,
        now: datetime,
    ) -> ExternalRelativeVolumeVerdict | None:
        denial = check_lease(
            record.lease, fence=fence, authenticated_actor_id=principal_id, now=now
        )
        return _status_from_lease_denial(denial) if denial is not None else None

    def claim(
        self,
        request_ref: str,
        *,
        organization_id: str,
        principal_id: str,
        fence: LeaseFence,
        now: datetime | None = None,
        mode: LeaseMode = LeaseMode.CLAIM,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT]:
        when = self._now(now)
        if type(fence.lease_generation) is not int:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.INVALID_LEASE_FENCE)
        is_initial_claim = (
            mode is LeaseMode.CLAIM and fence.lease_generation == 0 and fence.has_valid_ids()
        )
        if not fence.is_well_formed() and not is_initial_claim:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.INVALID_LEASE_FENCE)
        record = self.get(request_ref, organization_id=organization_id)
        if record is None:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
        worker = Principal(
            principal_id=principal_id,
            kind=PrincipalKind.PROCESSING_WORKER,
            role=None,
            device_id=None,
            organization_id=organization_id,
        )
        # Claim and renew are mutations too: accepting a new worker lease after
        # evidence/policy revocation would create an avoidable execution window.
        # The authority port is entered before the store lock and must be the
        # same coordinator participant configured at assembly.
        with (
            self._coordinator.mutation(),
            self._authority_port.guard_current(
                authority=record.authority, principal=worker, now=when
            ) as authority,
        ):
            if authority is None or authority != record.authority:
                return ExternalVolumeResult(
                    ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE, record
                )
            with self._lock:
                if self._journal.sealed_reason is not None:
                    return ExternalVolumeResult(ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE)
                record = self.get(request_ref, organization_id=organization_id)
                if record is None:
                    return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
                if record.status not in {
                    ExternalRelativeVolumeStatus.QUEUED,
                    ExternalRelativeVolumeStatus.RUNNING,
                }:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE, record
                    )
                if when >= record.deadline_at:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.DEADLINE_EXPIRED, record
                    )
                if mode is LeaseMode.RENEW:
                    denied = self._lease_denial_locked(
                        record, fence=fence, principal_id=principal_id, now=when
                    )
                    if denied is not None:
                        return ExternalVolumeResult(denied, record)
                    generation = fence.lease_generation
                    verdict = ExternalRelativeVolumeVerdict.LEASE_RENEWED
                else:
                    if record.lease is not None and record.lease.is_active(when):
                        if record.lease.authenticated_actor_id == principal_id and (
                            record.lease.fence == fence
                            or (
                                is_initial_claim
                                and record.lease.worker_instance_id == fence.worker_instance_id
                                and record.lease.lease_acquisition_id == fence.lease_acquisition_id
                            )
                        ):
                            return ExternalVolumeResult(
                                ExternalRelativeVolumeVerdict.LEASED, record
                            )
                        return ExternalVolumeResult(
                            ExternalRelativeVolumeVerdict.LEASE_HELD_BY_ANOTHER, record
                        )
                    if record.attempts >= self._queue_policy.max_attempts:
                        return ExternalVolumeResult(
                            ExternalRelativeVolumeVerdict.RETRY_EXHAUSTED, record
                        )
                    if fence.lease_acquisition_id in self._lease_acquisition_ids.get(
                        request_ref, set()
                    ):
                        return ExternalVolumeResult(
                            ExternalRelativeVolumeVerdict.STALE_LEASE_ACQUISITION, record
                        )
                    generation = self._lease_generation.get(request_ref, 0) + 1
                    if not is_initial_claim and fence.lease_generation != generation:
                        return ExternalVolumeResult(
                            ExternalRelativeVolumeVerdict.STALE_LEASE_GENERATION, record
                        )
                    verdict = ExternalRelativeVolumeVerdict.LEASED
                lease = next_lease(
                    now=when,
                    ttl=min(self._queue_policy.lease_ttl, record.deadline_at - when),
                    worker_instance_id=fence.worker_instance_id,
                    lease_acquisition_id=fence.lease_acquisition_id,
                    lease_generation=generation,
                    authenticated_actor_id=principal_id,
                )
                raw = {
                    "kind": self._kind("leased"),
                    "version": _VERSION,
                    "requestRef": request_ref,
                    "grantedAt": iso_utc(lease.granted_at),
                    "expiresAt": iso_utc(lease.expires_at),
                    **lease_raw_fields(lease=lease, mode=mode),
                }
                try:
                    self._append_locked(raw)
                except JournalSealedError:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE, record
                    )
                return ExternalVolumeResult(verdict, self._records[request_ref])

    def heartbeat(
        self,
        request_ref: str,
        *,
        organization_id: str,
        principal_id: str,
        fence: LeaseFence,
        now: datetime | None = None,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT]:
        return self.claim(
            request_ref,
            organization_id=organization_id,
            principal_id=principal_id,
            fence=fence,
            now=now,
            mode=LeaseMode.RENEW,
        )

    def worker_input(
        self,
        request_ref: str,
        *,
        principal: Principal,
        fence: LeaseFence,
        now: datetime | None = None,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT]:
        when = self._now(now)
        record = self.get(request_ref, organization_id=principal.organization_id)
        if record is None:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
        if record.status is not ExternalRelativeVolumeStatus.RUNNING:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE, record)
        with (
            self._coordinator.guarded_read(),
            self._authority_port.guard_current(
                authority=record.authority, principal=principal, now=when
            ) as authority,
        ):
            if authority is None or authority != record.authority:
                return ExternalVolumeResult(
                    ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE, record
                )
            with self._lock:
                fresh = self.get(request_ref, organization_id=principal.organization_id)
                if fresh is None:
                    return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
                if fresh.status is not ExternalRelativeVolumeStatus.RUNNING:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE, fresh
                    )
                if when >= fresh.deadline_at:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.DEADLINE_EXPIRED, fresh
                    )
                denied = self._lease_denial_locked(
                    fresh, fence=fence, principal_id=principal.principal_id, now=when
                )
                if denied is not None:
                    return ExternalVolumeResult(denied, fresh)
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.INPUT_READY, fresh)

    def confirm_worker_launch_material(
        self,
        request_ref: str,
        *,
        principal: Principal,
        fence: LeaseFence,
        expected_record: ExternalVolumeRecord[RequestT, AuthorityT, ReportT],
        material: Any,
        now: datetime | None = None,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT]:
        """Final local-only material/lease recheck after capability issuance.

        ``preflight`` may call policy/evidence authority ports and is therefore
        deliberately completed by the router before this method acquires the
        shared coordinator.  This final method touches retained projections,
        local currentness, and the volume journal only.
        """
        resolver = self._launch_material_resolver
        if resolver is None:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE)
        when = self._now(now)
        with (
            self._coordinator.guarded_read(),
            self._authority_port.guard_current(
                authority=expected_record.authority, principal=principal, now=when
            ) as authority,
        ):
            if authority is None or authority != expected_record.authority:
                return ExternalVolumeResult(
                    ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE, expected_record
                )
            with self._lock:
                fresh = self.get(request_ref, organization_id=principal.organization_id)
                if fresh is None:
                    return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
                if fresh.status is not ExternalRelativeVolumeStatus.RUNNING:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE, fresh
                    )
                if when >= fresh.deadline_at:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.DEADLINE_EXPIRED, fresh
                    )
                if fresh != expected_record:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE, fresh
                    )
                denied = self._lease_denial_locked(
                    fresh, fence=fence, principal_id=principal.principal_id, now=when
                )
                if denied is not None:
                    return ExternalVolumeResult(denied, fresh)
                if not resolver.material_remains_current(
                    fresh.request, fresh.authority, material, now=when
                ):
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE, fresh
                    )
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.INPUT_READY, fresh)

    def _validate_report(
        self,
        record: ExternalVolumeRecord[RequestT, AuthorityT, ReportT],
        observed: ExternalVolumeObservedReportInput[PayloadT],
        *,
        fence: LeaseFence,
        now: datetime,
    ) -> str | None:
        error = self._measurement_payload_error(record, observed.payload)
        if error is not None:
            return error
        if observed.computed_at > now or now >= record.deadline_at:
            return "report time is outside the active request deadline"
        if not fence.is_well_formed():
            return "report requires a well-formed worker lease fence"
        return None

    def _completed_report_retry(
        self,
        request_ref: str,
        *,
        organization_id: str,
        principal_id: str,
        fence: LeaseFence,
        observed: ExternalVolumeObservedReportInput[PayloadT],
        now: datetime,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT] | None:
        """Return an immutable report retry without reopening execution authority.

        Historical authority resolution deliberately happens before the shared
        coordinator/store critical section.  The result is then re-read under
        the normal coordinator -> store order so a stale snapshot cannot grant
        a retry response for a different terminal record.
        """

        record = self.get(request_ref, organization_id=organization_id)
        if record is None or record.report is None:
            return None
        historical_report = self.resolve_historical_report(
            request_ref, organization_id=organization_id, now=now
        )
        with self._coordinator.mutation(), self._lock:
            fresh = self.get(request_ref, organization_id=organization_id)
            if fresh is None:
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
            if fresh.report is None:
                return None
            if historical_report is None or fresh.report != historical_report:
                return ExternalVolumeResult(
                    ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE, fresh
                )
            same = (
                fresh.report.measurement_payload_digest == observed.payload.canonical_digest()
                and fresh.report.worker_instance_id == fence.worker_instance_id
                and fresh.report.lease_acquisition_id == fence.lease_acquisition_id
                and fresh.report.lease_generation == fence.lease_generation
                and fresh.lease is not None
                and fresh.lease.authenticated_actor_id == principal_id
            )
            return ExternalVolumeResult(
                ExternalRelativeVolumeVerdict.REPORTED
                if same
                else ExternalRelativeVolumeVerdict.REPORT_CONFLICT,
                fresh,
            )

    def record_observed_report(
        self,
        request_ref: str,
        *,
        organization_id: str,
        principal_id: str,
        fence: LeaseFence,
        observed: ExternalVolumeObservedReportInput[PayloadT],
        now: datetime | None = None,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT]:
        when = self._now(now)
        completed_retry = self._completed_report_retry(
            request_ref,
            organization_id=organization_id,
            principal_id=principal_id,
            fence=fence,
            observed=observed,
            now=when,
        )
        if completed_retry is not None:
            return completed_retry
        record = self.get(request_ref, organization_id=organization_id)
        if record is None:
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
        reported: ExternalVolumeRecord[RequestT, AuthorityT, ReportT] | None = None
        # Result authority is rechecked under the shared coordinator before the
        # journal lock.  The port is never called while the store lock is held.
        worker = Principal(
            principal_id=principal_id,
            kind=PrincipalKind.PROCESSING_WORKER,
            role=None,
            device_id=None,
            organization_id=organization_id,
        )
        with (
            self._coordinator.mutation(),
            self._authority_port.guard_current(
                authority=record.authority, principal=worker, now=when
            ) as authority,
        ):
            if authority is None or authority != record.authority:
                return ExternalVolumeResult(
                    ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE, record
                )
            with self._lock:
                fresh = self.get(request_ref, organization_id=organization_id)
                if fresh is None:
                    return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
                if self._journal.sealed_reason is not None:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE, fresh
                    )
                if fresh.report is not None:
                    same = (
                        fresh.report.measurement_payload_digest
                        == observed.payload.canonical_digest()
                        and fresh.report.worker_instance_id == fence.worker_instance_id
                        and fresh.report.lease_acquisition_id == fence.lease_acquisition_id
                        and fresh.report.lease_generation == fence.lease_generation
                    )
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.REPORTED
                        if same
                        else ExternalRelativeVolumeVerdict.REPORT_CONFLICT,
                        fresh,
                    )
                if fresh.status is not ExternalRelativeVolumeStatus.RUNNING:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE, fresh
                    )
                denied = self._lease_denial_locked(
                    fresh, fence=fence, principal_id=principal_id, now=when
                )
                if denied is not None:
                    return ExternalVolumeResult(denied, fresh)
                failure = self._validate_report(fresh, observed, fence=fence, now=when)
                if failure is not None:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.INVALID_REPORT, fresh, detail=failure
                    )
                report = self._build_report(
                    report_id=self._KIND_PREFIX
                    + "-report-"
                    + hashlib.sha256((fresh.request.request_id + "\0report").encode()).hexdigest()[
                        :32
                    ],
                    request_id=fresh.request.request_id,
                    request_digest=fresh.request.request_digest or "",
                    payload=observed.payload,
                    worker_instance_id=fence.worker_instance_id,
                    lease_acquisition_id=fence.lease_acquisition_id,
                    lease_generation=fence.lease_generation,
                    computed_at=observed.computed_at,
                    reported_at=when,
                )
                indexed_request_ref = self._report_refs.get((organization_id, report.report_id))
                if (
                    indexed_request_ref is not None
                    and indexed_request_ref != fresh.request.request_id
                ):
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.REPORT_CONFLICT, fresh
                    )
                raw = {
                    "kind": self._kind("reported"),
                    "version": _VERSION,
                    "requestRef": fresh.request.request_id,
                    "report": self._report_wire(report),
                }
                try:
                    self._append_locked(raw)
                except JournalSealedError:
                    return ExternalVolumeResult(
                        ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE, fresh
                    )
                reported = self._records[request_ref]
        assert reported is not None
        self._notify_report_listeners(reported)
        return ExternalVolumeResult(ExternalRelativeVolumeVerdict.REPORTED, reported)

    def record_incomplete_failure(
        self,
        request_ref: str,
        *,
        organization_id: str,
        principal_id: str,
        fence: LeaseFence,
        reason: str,
        now: datetime | None = None,
    ) -> ExternalVolumeResult[RequestT, AuthorityT, ReportT]:
        when = self._now(now)
        if not _valid_failure_reason(reason):
            return ExternalVolumeResult(ExternalRelativeVolumeVerdict.INVALID_REPORT)
        # Failure closes an already leased attempt and grants no new numerical
        # capability.  It intentionally remains available after withdrawal,
        # while participating in the shared mutation -> store -> journal order.
        with self._coordinator.mutation(), self._lock:
            record = self.get(request_ref, organization_id=organization_id)
            if record is None:
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.NOT_FOUND)
            if record.status is not ExternalRelativeVolumeStatus.RUNNING:
                return ExternalVolumeResult(
                    ExternalRelativeVolumeVerdict.REQUEST_NOT_ACTIVE, record
                )
            denied = self._lease_denial_locked(
                record, fence=fence, principal_id=principal_id, now=when
            )
            if denied is not None:
                return ExternalVolumeResult(denied, record)
            raw = {
                "kind": self._kind("failed"),
                "version": _VERSION,
                "requestRef": request_ref,
                "reason": reason,
                "workerInstanceId": fence.worker_instance_id,
                "leaseAcquisitionId": fence.lease_acquisition_id,
                "leaseGeneration": fence.lease_generation,
                "authenticatedActorId": principal_id,
                "failedAt": iso_utc(when),
            }
            try:
                self._append_locked(raw)
            except JournalSealedError:
                return ExternalVolumeResult(ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE, record)
            return ExternalVolumeResult(
                ExternalRelativeVolumeVerdict.FAILED, self._records[request_ref]
            )

    def resolve_historical_report(
        self, request_ref: str, *, organization_id: str, now: datetime | None = None
    ) -> ReportT | None:
        record = self.get(request_ref, organization_id=organization_id)
        if record is None or record.report is None or record.request.request_digest is None:
            return None
        # Historical proof is a separate authority lookup; it does not reuse the
        # live guard, and stale/revoked current state cannot rewrite old reports.
        authority = self._authority_port.resolve_historical(
            historical_authority_digest=record.authority.historical_authority_digest,
            decision_id=record.request.decision_id,
            decision_digest=record.request.decision_digest,
            issued_at=record.issued_at,
            now=self._now(now),
        )
        if authority is None or authority != record.authority:
            return None
        try:
            key_hash = self._idempotency_hash(record.request.idempotency_key)
        except ValueError:
            return None
        natural = self._natural_fingerprint(
            organization_id=organization_id,
            current_work_order_id=record.request.current_work_order_id,
            authority=authority,
        )
        binding_error = self._issued_request_authority_error(
            record.request,
            authority,
            organization_id=organization_id,
            key_hash=key_hash,
            natural=natural,
            issued_at=record.issued_at,
            issued_by=record.issued_by,
        )
        if binding_error is not None or self._measurement_payload_error(
            record, record.report.payload
        ):
            return None
        with self._lock:
            if self._records.get(request_ref) != record:
                return None
            if self._natural.get(natural) != request_ref:
                return None
            if self._idempotency.get(
                (organization_id, record.request.current_work_order_id, key_hash)
            ) != (natural, request_ref):
                return None
        return record.report

    def resolve_historical_report_ref(
        self, report_ref: str, *, organization_id: str, now: datetime | None = None
    ) -> ResolvedVolumeReport[RequestT, AuthorityT, ReportT] | None:
        """Resolve one organization-scoped immutable report without live authority.

        The index is persisted only through the report event and rebuilt under
        replay.  Historical authority resolution stays outside every Core
        coordinator/store lock, then the exact index and retained record are
        checked again before a deep immutable snapshot is returned.
        """
        with self._lock:
            request_ref = self._report_refs.get((organization_id, report_ref))
            record = self._records.get(request_ref) if request_ref is not None else None
        if request_ref is None:
            return None
        if (
            record is None
            or record.report is None
            or record.report.report_id != report_ref
            or record.authority.organization_id != organization_id
        ):
            return None
        report = self.resolve_historical_report(
            request_ref, organization_id=organization_id, now=now
        )
        if report is None or report.report_id != report_ref:
            return None
        authority = self._authority_port.resolve_historical(
            historical_authority_digest=record.authority.historical_authority_digest,
            decision_id=record.request.decision_id,
            decision_digest=record.request.decision_digest,
            issued_at=record.issued_at,
            now=self._now(now),
        )
        if authority is None or authority != record.authority:
            return None
        with self._lock:
            fresh = self._records.get(request_ref)
            if (
                fresh != record
                or self._report_refs.get((organization_id, report_ref)) != request_ref
                or fresh is None
                or fresh.report != report
            ):
                return None
        return ResolvedVolumeReport(
            request=record.request.model_copy(deep=True),
            report=report.model_copy(deep=True),
            execution_authority=self._authority_from_snapshot(authority.snapshot_payload()),
        )

    def preflight_current_report_ref(
        self,
        report_ref: str,
        *,
        organization_id: str,
        principal: Principal,
        now: datetime | None = None,
    ) -> ResolvedVolumeReport[RequestT, AuthorityT, ReportT] | None:
        """Resolve a current-use witness before the final local guard.

        The only potentially independent current authority resolution happens
        here, before the shared coordinator is acquired.  The caller must pass
        this witness to :meth:`guard_current_report_ref` while appending its
        own downstream journal transition.
        """
        when = self._now(now)
        if principal.organization_id != organization_id:
            return None
        resolved = self.resolve_historical_report_ref(
            report_ref, organization_id=organization_id, now=when
        )
        if resolved is None:
            return None
        current = self._authority_port.resolve_for_issue(
            principal=principal,
            current_work_order_id=resolved.request.current_work_order_id,
            decision_ref=resolved.request.decision_id,
            now=when,
        )
        if current is None or current != resolved.execution_authority:
            return None
        return resolved

    @contextmanager
    def guard_current_report_ref(
        self,
        report_ref: str,
        *,
        organization_id: str,
        principal: Principal,
        witness: ResolvedVolumeReport[RequestT, AuthorityT, ReportT],
        now: datetime | None = None,
    ) -> Iterator[ResolvedVolumeReport[RequestT, AuthorityT, ReportT] | None]:
        """Locally recheck an already-preflighted report witness under Core lock."""
        when = self._now(now)
        if principal.organization_id != organization_id:
            yield None
            return
        with (
            self._coordinator.guarded_read(),
            self._authority_port.guard_current(
                authority=witness.execution_authority, principal=principal, now=when
            ) as authority,
        ):
            if authority is None or authority != witness.execution_authority:
                yield None
                return
            with self._lock:
                request_ref = self._report_refs.get((organization_id, report_ref))
                record = self._records.get(request_ref) if request_ref is not None else None
                if (
                    record is None
                    or record.report is None
                    or record.report.report_id != report_ref
                    or record.request != witness.request
                    or record.report != witness.report
                    or record.authority != witness.execution_authority
                ):
                    yield None
                    return
                yield ResolvedVolumeReport(
                    request=record.request.model_copy(deep=True),
                    report=record.report.model_copy(deep=True),
                    execution_authority=self._authority_from_snapshot(
                        record.authority.snapshot_payload()
                    ),
                )


class ExternalRelativeVolumeStore(
    ExternalVolumeLedger[
        ExternalRelativeVolumeRequestV1,
        ExternalRelativeVolumeExecutionAuthority,
        ExternalRelativeVolumeReportV1,
        ExternalRelativeVolumeMeasurementPayloadV1,
    ]
):
    """The external relative-volume family: an ordered baseline/current DSM pair."""

    _LABEL = "relative-volume"
    _KIND_PREFIX = "external-relative-volume"
    _recovery_error = ExternalRelativeVolumeRecoveryError

    @property
    def launch_material_resolver(self) -> VolumeWorkerLaunchMaterialResolver | None:
        # Assembly binds the concrete relative-volume resolver; keep its type visible.
        return cast(VolumeWorkerLaunchMaterialResolver | None, self._launch_material_resolver)

    def _authority_from_snapshot(
        self, raw: dict[str, Any]
    ) -> ExternalRelativeVolumeExecutionAuthority:
        return ExternalRelativeVolumeExecutionAuthority.from_snapshot(raw)

    def _request_from_wire(self, raw: object) -> ExternalRelativeVolumeRequestV1:
        return ExternalRelativeVolumeRequestV1.model_validate(raw)

    def _request_wire(self, request: ExternalRelativeVolumeRequestV1) -> dict[str, Any]:
        return external_relative_volume_request_wire_dict(request)

    def _report_from_wire(self, raw: object) -> ExternalRelativeVolumeReportV1:
        return ExternalRelativeVolumeReportV1.model_validate(raw)

    def _report_wire(self, report: ExternalRelativeVolumeReportV1) -> dict[str, Any]:
        return external_relative_volume_report_wire_dict(report)

    def _build_report(self, **fields: Any) -> ExternalRelativeVolumeReportV1:
        return ExternalRelativeVolumeReportV1(**fields).sealed()

    def _build_request(
        self,
        authority: ExternalRelativeVolumeExecutionAuthority,
        *,
        request_id: str,
        current_work_order_id: str,
        issued_at: datetime,
        idempotency_key: str,
    ) -> ExternalRelativeVolumeRequestV1:
        return ExternalRelativeVolumeRequestV1(
            request_id=request_id,
            current_work_order_id=current_work_order_id,
            decision_id=authority.decision_id,
            decision_digest=authority.decision_digest,
            baseline=authority.baseline,
            current=authority.current,
            evidence_record_digests=authority.evidence_record_digests,
            validation_policy_digest=authority.validation_policy_digest,
            execution_policy_digest=authority.execution_policy.canonical_digest(),
            zone_snapshot=authority.zone_snapshot,
            issued_at=issued_at,
            idempotency_key=idempotency_key,
        ).sealed()

    @staticmethod
    def _natural_fingerprint(
        *,
        organization_id: str,
        current_work_order_id: str,
        authority: Any,
    ) -> str:
        return _digest(
            {
                "domain": "external-relative-volume-issue.v1",
                "organizationId": organization_id,
                "currentWorkOrderId": current_work_order_id,
                "decisionId": authority.decision_id,
                "decisionDigest": authority.decision_digest,
                "compatibilityMapping": authority.compatibility_mapping_digest,
                "baseline": authority.baseline.observed_sha256,
                "current": authority.current.observed_sha256,
                "evidence": list(authority.evidence_record_digests),
                "validationPolicy": authority.validation_policy_digest,
                "executionPolicy": authority.execution_policy.canonical_digest(),
                "zone": authority.zone_snapshot.canonical_digest(),
            }
        )

    def _inputs_binding_error(
        self,
        request: ExternalRelativeVolumeRequestV1,
        authority: ExternalRelativeVolumeExecutionAuthority,
    ) -> str | None:
        if request.baseline != authority.baseline or request.current != authority.current:
            return "issued DSM inputs differ from authority"
        if request.evidence_record_digests != authority.evidence_record_digests:
            return "issued evidence differs from authority"
        return None

    def _primary_site_id(self, authority: ExternalRelativeVolumeExecutionAuthority) -> str:
        return authority.current.subject.site_id

    def _report_sort_time(self, record: ExternalRelativeVolumeRecord) -> datetime:
        return record.request.current.captured_to

    def _measurement_payload_error(
        self,
        record: ExternalRelativeVolumeRecord,
        payload: ExternalRelativeVolumeMeasurementPayloadV1,
    ) -> str | None:
        request, authority = record.request, record.authority
        if (
            request.request_digest is None
            or payload.request_digest != request.request_digest
            or payload.decision_digest != authority.decision_digest
            or payload.baseline_dsm_digest != authority.baseline.observed_sha256
            or payload.current_dsm_digest != authority.current.observed_sha256
            or payload.zone_snapshot_digest != authority.zone_snapshot.canonical_digest()
            or payload.execution_policy_digest != authority.execution_policy.canonical_digest()
            or payload.algorithm_build_digest != authority.execution_policy.algorithm_build_digest
            or payload.config_digest != authority.execution_policy.config_digest
        ):
            return "worker payload does not match sealed request authority"
        metrics = payload.metrics
        if metrics.threshold_m != authority.execution_policy.threshold_m:
            return "worker threshold differs from selected execution policy"
        if metrics.common_valid_fraction < authority.execution_policy.minimum_common_valid_fraction:
            return "coverage is below the selected execution policy minimum"
        if (
            metrics.zone_cell_count > authority.maximum_zone_cell_count
            or metrics.zone_area_m2 > authority.maximum_zone_area_m2
        ):
            return "worker metrics exceed the selected resource envelope"
        expected_uncertainty: float | None
        if authority.baseline_rmse_m is None or authority.current_rmse_m is None:
            expected_uncertainty = None
        else:
            expected_uncertainty = metrics.measured_area_m2 * math.hypot(
                authority.baseline_rmse_m, authority.current_rmse_m
            )
        if expected_uncertainty is None:
            if metrics.uncertainty_m3 is not None:
                return "uncertainty must be unknown without two trusted RMSE values"
        elif metrics.uncertainty_m3 is None or not math.isclose(
            metrics.uncertainty_m3, expected_uncertainty, rel_tol=1e-12, abs_tol=1e-12
        ):
            return "uncertainty does not match the independent epoch RMSE bound"
        return None


def _to_view(record: ExternalVolumeRecord[Any, Any, Any]) -> ExternalRelativeVolumeRequestView:
    return ExternalRelativeVolumeRequestView(
        request_ref=record.request.request_id,
        status=record.status,
        current_work_order_id=record.request.current_work_order_id,
        decision_digest=record.request.decision_digest,
        issued_at=record.issued_at,
        deadline_at=record.deadline_at,
        report_ref=record.report.report_id if record.report is not None else None,
        report_digest=record.report.report_digest if record.report is not None else None,
    )


def _fence_from_input(
    worker_instance_id: str, lease_acquisition_id: str, lease_generation: int
) -> LeaseFence:
    return LeaseFence(worker_instance_id, lease_acquisition_id, lease_generation)


def build_external_relative_volume_router(
    store: ExternalRelativeVolumeStore,
    *,
    input_capability_issuer: ExternalRelativeVolumeInputCapabilityIssuer,
    execution_activator: ExternalRelativeVolumeExecutionActivator | None = None,
    work_orders: Any | None = None,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Return only this feature's router; app/assembly/OpenAPI ownership stays with Lead."""

    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-relative-volumes"])

    def mutation_response(
        result: ExternalRelativeVolumeResult, response: Response
    ) -> ExternalRelativeVolumeMutationResponse:
        fence = (
            result.fence
            if result.verdict
            in {
                ExternalRelativeVolumeVerdict.LEASED,
                ExternalRelativeVolumeVerdict.LEASE_RENEWED,
            }
            else None
        )
        if fence is not None and result.lease_expires_at is not None:
            response.headers["X-KSI-Worker-Instance-Id"] = fence.worker_instance_id
            response.headers["X-KSI-Lease-Acquisition-Id"] = fence.lease_acquisition_id
            response.headers["X-KSI-Lease-Generation"] = str(fence.lease_generation)
            response.headers["X-KSI-Lease-Expires-At"] = iso_utc(result.lease_expires_at)
        return ExternalRelativeVolumeMutationResponse(
            verdict=result.verdict,
            request=_to_view(result.record) if result.record else None,
            fence=(
                ExternalRelativeVolumeLeaseFenceView(
                    worker_instance_id=fence.worker_instance_id,
                    lease_acquisition_id=fence.lease_acquisition_id,
                    lease_generation=fence.lease_generation,
                )
                if fence is not None
                else None
            ),
            lease_expires_at=result.lease_expires_at if fence is not None else None,
            detail=result.detail,
        )

    @router.post(
        "/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
        response_model=ExternalRelativeVolumeMutationResponse,
        status_code=201,
    )
    def issue_relative_volume(
        work_order_id: str,
        request: ExternalRelativeVolumeIssueInput,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> ExternalRelativeVolumeMutationResponse:
        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(status_code=403, detail="권한이 부족하다")
        if work_orders is None:
            raise HTTPException(status_code=503, detail="EXTERNAL_WORKFLOW_GUARD_UNAVAILABLE")
        try:
            with work_orders.guard_new_external_intent(
                work_order_id,
                organization_id=principal.organization_id,
                is_durable_retry=lambda: store.is_issue_retry(
                    principal=principal,
                    current_work_order_id=work_order_id,
                    decision_ref=request.decision_ref,
                    idempotency_key=idempotency_key or "",
                ),
            ):
                issued_at = now()
                prior_result = None
                needs_activation = False
                if execution_activator is not None:
                    prior_result, needs_activation = store.classify_issue_activation(
                        principal=principal,
                        current_work_order_id=work_order_id,
                        decision_ref=request.decision_ref,
                        idempotency_key=idempotency_key or "",
                        now=issued_at,
                    )
                if execution_activator is not None and needs_activation:
                    activated = execution_activator(
                        principal=principal,
                        current_work_order_id=work_order_id,
                        decision_ref=request.decision_ref,
                        now=issued_at,
                    )
                    if activated is None:
                        response.status_code = _HTTP_STATUS[
                            ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
                        ]
                        return ExternalRelativeVolumeMutationResponse(
                            verdict=ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE,
                            request=None,
                        )
                result = (
                    prior_result
                    if prior_result is not None
                    else store.issue(
                        principal=principal,
                        current_work_order_id=work_order_id,
                        decision_ref=request.decision_ref,
                        idempotency_key=idempotency_key or "",
                        now=issued_at,
                    )
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LookupError as exc:
            # The closure guard scopes the WorkOrder before attempting issue.
            # Keep absent and foreign identifiers indistinguishable from the
            # other scoped external-workflow reads.
            raise HTTPException(
                status_code=404, detail="relative-volume request was not found"
            ) from exc
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        response.status_code = _HTTP_STATUS[result.verdict]
        if result.verdict is ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ExternalRelativeVolumeMutationResponse(
            verdict=result.verdict,
            request=_to_view(result.record) if result.record else None,
            detail=result.detail,
        )

    @router.get(
        "/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
        response_model=ExternalRelativeVolumeListResponse,
    )
    def list_relative_volumes(
        work_order_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ExternalRelativeVolumeListResponse:
        return ExternalRelativeVolumeListResponse(
            items=[
                _to_view(record)
                for record in store.list_for_work_order(
                    work_order_id, organization_id=principal.organization_id
                )
            ]
        )

    @router.get(
        "/v1/observation-work-orders/{work_order_id}/relative-volume-requests/{request_ref}",
        response_model=ExternalRelativeVolumeRequestView,
    )
    def get_relative_volume(
        work_order_id: str,
        request_ref: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ExternalRelativeVolumeRequestView:
        record = store.get(request_ref, organization_id=principal.organization_id)
        if record is None or record.request.current_work_order_id != work_order_id:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return _to_view(record)

    @router.get(
        "/v1/internal/external-validation/relative-volumes",
        response_model=ExternalRelativeVolumePendingResponse,
    )
    def list_pending_relative_volumes(
        limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ExternalRelativeVolumePendingResponse:
        return ExternalRelativeVolumePendingResponse(
            items=[
                ExternalRelativeVolumePendingView(
                    request_ref=record.request.request_id, issued_at=record.issued_at
                )
                for record in store.list_pending(
                    organization_id=principal.organization_id, now=now(), limit=limit
                )
            ]
        )

    @router.post(
        "/v1/internal/external-validation/relative-volumes/{request_ref}/lease",
        response_model=ExternalRelativeVolumeMutationResponse,
        status_code=201,
    )
    def lease_relative_volume(
        request_ref: str,
        request: ExternalRelativeVolumeLeaseInput,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ExternalRelativeVolumeMutationResponse:
        result = store.claim(
            request_ref,
            organization_id=principal.organization_id,
            principal_id=principal.principal_id,
            fence=_fence_from_input(
                request.worker_instance_id, request.lease_acquisition_id, request.lease_generation
            ),
            mode=request.mode,
            now=now(),
        )
        response.status_code = _HTTP_STATUS[result.verdict]
        return mutation_response(result, response)

    @router.post(
        "/v1/internal/external-validation/relative-volumes/{request_ref}/heartbeat",
        response_model=ExternalRelativeVolumeMutationResponse,
    )
    def heartbeat_relative_volume(
        request_ref: str,
        request: ExternalRelativeVolumeHeartbeatInput,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ExternalRelativeVolumeMutationResponse:
        result = store.heartbeat(
            request_ref,
            organization_id=principal.organization_id,
            principal_id=principal.principal_id,
            fence=_fence_from_input(
                request.worker_instance_id, request.lease_acquisition_id, request.lease_generation
            ),
            now=now(),
        )
        response.status_code = _HTTP_STATUS[result.verdict]
        return mutation_response(result, response)

    @router.get(
        "/v1/internal/external-validation/relative-volumes/{request_ref}/input",
        response_model=ExternalRelativeVolumeWorkerInputResponse,
    )
    def get_relative_volume_input(
        request_ref: str,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: int | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ExternalRelativeVolumeWorkerInputResponse:
        try:
            fence = _fence_from_input(
                worker_instance_id or "", lease_acquisition_id or "", lease_generation or 0
            )
        except ValueError:
            fence = LeaseFence("", "", 0)
        first = store.worker_input(request_ref, principal=principal, fence=fence, now=now())
        if first.record is None:
            response.status_code = _HTTP_STATUS[first.verdict]
            return ExternalRelativeVolumeWorkerInputResponse(
                verdict=first.verdict, detail=first.detail
            )
        if first.verdict is not ExternalRelativeVolumeVerdict.INPUT_READY:
            response.status_code = _HTTP_STATUS[first.verdict]
            return ExternalRelativeVolumeWorkerInputResponse(
                verdict=first.verdict, detail=first.detail
            )
        resolver = store.launch_material_resolver
        if resolver is None:
            response.status_code = _HTTP_STATUS[ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE]
            return ExternalRelativeVolumeWorkerInputResponse(
                verdict=ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
            )
        material = resolver.preflight(first.record.request, first.record.authority, now=now())
        if material is None:
            response.status_code = _HTTP_STATUS[ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE]
            return ExternalRelativeVolumeWorkerInputResponse(
                verdict=ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
            )
        # Policy/evidence preflight and presigning occur outside Core locks. A
        # second local-only check prevents a revoked or changed request from
        # receiving a capability response.
        capabilities = input_capability_issuer(
            first.record, fence=fence, principal=principal, now=now()
        )
        second = store.confirm_worker_launch_material(
            request_ref,
            principal=principal,
            fence=fence,
            expected_record=first.record,
            material=material,
            now=now(),
        )
        if (
            capabilities is None
            or second.verdict is not ExternalRelativeVolumeVerdict.INPUT_READY
            or second.record is None
        ):
            response.status_code = _HTTP_STATUS[
                second.verdict
                if capabilities is not None
                else ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
            ]
            return ExternalRelativeVolumeWorkerInputResponse(
                verdict=second.verdict
                if capabilities is not None
                else ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE,
                detail=second.detail,
            )
        return ExternalRelativeVolumeWorkerInputResponse(
            verdict=ExternalRelativeVolumeVerdict.INPUT_READY,
            input=ExternalRelativeVolumeWorkerInputView(
                request=external_relative_volume_request_wire_dict(second.record.request),
                execution_policy=external_relative_volume_execution_policy_wire_dict(
                    second.record.authority.execution_policy
                ),
                validation_policy=material.validation_policy,
                volume_evidence_records=material.evidence_records,
                inputs=capabilities,
            ),
        )

    @router.post(
        "/v1/internal/external-validation/relative-volumes/{request_ref}/report",
        response_model=ExternalRelativeVolumeMutationResponse,
        status_code=201,
    )
    def report_relative_volume(
        request_ref: str,
        request: ExternalRelativeVolumeWorkerReportInput,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: int | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ExternalRelativeVolumeMutationResponse:
        result = store.record_observed_report(
            request_ref,
            organization_id=principal.organization_id,
            principal_id=principal.principal_id,
            fence=_fence_from_input(
                worker_instance_id or "", lease_acquisition_id or "", lease_generation or 0
            ),
            observed=ExternalRelativeVolumeObservedReportInput(
                payload=request.payload, computed_at=request.computed_at
            ),
            now=now(),
        )
        response.status_code = _HTTP_STATUS[result.verdict]
        return ExternalRelativeVolumeMutationResponse(
            verdict=result.verdict,
            request=_to_view(result.record) if result.record else None,
            detail=result.detail,
        )

    @router.post(
        "/v1/internal/external-validation/relative-volumes/{request_ref}/incomplete-failure",
        response_model=ExternalRelativeVolumeMutationResponse,
    )
    def fail_relative_volume(
        request_ref: str,
        request: ExternalRelativeVolumeWorkerFailureInput,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: int | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ExternalRelativeVolumeMutationResponse:
        result = store.record_incomplete_failure(
            request_ref,
            organization_id=principal.organization_id,
            principal_id=principal.principal_id,
            fence=_fence_from_input(
                worker_instance_id or "", lease_acquisition_id or "", lease_generation or 0
            ),
            reason=request.reason,
            now=now(),
        )
        response.status_code = _HTTP_STATUS[result.verdict]
        return ExternalRelativeVolumeMutationResponse(
            verdict=result.verdict,
            request=_to_view(result.record) if result.record else None,
            detail=result.detail,
        )

    return router


__all__ = [
    "ExternalVolumeExecutionAuthorityPort",
    "ExternalVolumeLedger",
    "ExternalVolumeObservedReportInput",
    "ExternalVolumeRecord",
    "ExternalVolumeResult",
    "ResolvedVolumeReport",
    "VolumeLaunchMaterialResolverPort",
    "ExternalRelativeVolumeExecutionAuthority",
    "ExternalRelativeVolumeExecutionAuthorityPort",
    "ExternalRelativeVolumeInputCapability",
    "ExternalRelativeVolumeObservedReportInput",
    "ExternalRelativeVolumeQueuePolicy",
    "ExternalRelativeVolumeRecord",
    "ExternalRelativeVolumeRecoveryError",
    "ExternalRelativeVolumeResult",
    "ExternalRelativeVolumeStatus",
    "ExternalRelativeVolumeStore",
    "ExternalRelativeVolumeVerdict",
    "ResolvedRelativeVolumeReport",
    "build_external_relative_volume_router",
]
