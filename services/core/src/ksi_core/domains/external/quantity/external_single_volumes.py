"""Durable, external-only single-epoch (stockpile) volume work ledger.

One sealed DSM epoch is measured against a base surface derived from the zone
boundary.  The queue, lease, fence, idempotency and replay machinery is the
shared :class:`ExternalVolumeLedger`; this module supplies the single-volume
family: its execution authority snapshot, request/report contracts, payload
checks, worker launch material and routes.

Worker launches carry two sealed inputs — the target DSM (mounted) and the
exact checkpoint CSV of the one bound evidence record (spooled and hash
checked) — so the hardened measurement sandbox transport stays unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
)
from ksi_event_contracts.external_evidence import ExternalEvidenceRecordV1
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
    external_volume_zone_snapshot_wire_dict,
)
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeExecutionPolicyV1,
    ExternalSingleVolumeMeasurementPayloadV1,
    ExternalSingleVolumeReportV1,
    ExternalSingleVolumeRequestV1,
    external_single_volume_execution_policy_wire_dict,
    external_single_volume_report_wire_dict,
    external_single_volume_request_wire_dict,
)
from pydantic import field_validator

from ksi_core.domains.external.ingress.external_evidence_validations import (
    ExternalEvidenceValidationStore,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicySelectionStatus,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    _HTTP_STATUS,
    _SHA256_DIGEST,
    ExternalRelativeVolumeHeartbeatInput,
    ExternalRelativeVolumeInputCapability,
    ExternalRelativeVolumeIssueInput,
    ExternalRelativeVolumeLeaseFenceView,
    ExternalRelativeVolumeLeaseInput,
    ExternalRelativeVolumeListResponse,
    ExternalRelativeVolumeMutationResponse,
    ExternalRelativeVolumePendingResponse,
    ExternalRelativeVolumePendingView,
    ExternalRelativeVolumeRequestView,
    ExternalRelativeVolumeVerdict,
    ExternalRelativeVolumeWorkerFailureInput,
    ExternalVolumeExecutionAuthorityPort,
    ExternalVolumeLedger,
    ExternalVolumeObservedReportInput,
    ExternalVolumeRecord,
    ExternalVolumeResult,
    ResolvedVolumeReport,
    _digest,
    _fence_from_input,
    _require_utc,
    _snapshot_bools,
    _snapshot_floats,
    _snapshot_ints,
    _snapshot_object,
    _snapshot_string_list,
    _snapshot_strings,
    _strict_snapshot_equal,
    _to_view,
    _validate_input_binding_snapshot,
    _validate_zone_snapshot,
)
from ksi_core.foundation.api_base import CamelModel, iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.leasing import LeaseFence
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission

_NOT_FOUND_DETAIL = "해당 외부 단일 시점 체적 요청을 찾을 수 없다"


def _require_scoped_work_order(
    work_orders: Any | None, principal: Principal, work_order_id: str
) -> None:
    """F-01(2026-10-12): mapped/scoped operators read only granted WorkOrders.

    Legacy (unscoped) identities keep the previous organization-filtered
    behavior. Mapped identities additionally need the exact WorkOrder
    site/area grants, and any mismatch is the same 404 as a missing request.
    """
    if principal.allowed_site_ids is None and principal.allowed_work_area_ids is None:
        return
    order = (
        work_orders.get(work_order_id, organization_id=principal.organization_id)
        if work_orders is not None
        else None
    )
    if order is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
    if principal.allowed_site_ids is not None and order.site_id not in principal.allowed_site_ids:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
    if (
        principal.allowed_work_area_ids is not None
        and not set(order.work_area_ids).issubset(principal.allowed_work_area_ids)
    ):
        raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
_ISSUE_DOMAIN = "external-single-volume-issue.v1"
_AUTHORITY_SNAPSHOT_FIELDS = frozenset(
    {
        "organizationId",
        "siteId",
        "currentWorkOrderId",
        "decisionId",
        "decisionDigest",
        "compatibilityMappingDigest",
        "target",
        "evidenceRecordDigests",
        "validationPolicyDigest",
        "zoneSnapshot",
        "executionPolicy",
        "authorizedActorIds",
        "validFrom",
        "validUntil",
        "historicalAuthorityDigest",
        "targetRmseM",
        "maximumZoneCellCount",
        "maximumZoneAreaM2",
        "syntheticTestOnly",
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
        "minimumBoundaryValidFraction",
        "uncertaintyMethod",
        "baseSurfaceMethod",
        "resourceEnvelopeDigest",
        "authorityRecordDigest",
        "syntheticTestOnly",
        "policyDigest",
    }
)


class ExternalSingleVolumeRecoveryError(RuntimeError):
    """The append-only single-volume journal cannot safely be replayed."""


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
            "baseSurfaceMethod",
            "resourceEnvelopeDigest",
            "authorityRecordDigest",
            "policyDigest",
        ),
    )
    _snapshot_ints(policy, name="executionPolicy", fields=("version",))
    _snapshot_floats(
        policy,
        name="executionPolicy",
        fields=("thresholdM", "minimumCommonValidFraction", "minimumBoundaryValidFraction"),
    )
    _snapshot_bools(policy, name="executionPolicy", fields=("syntheticTestOnly",))


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
    _validate_input_binding_snapshot(authority["target"], name="target")
    _snapshot_string_list(authority["evidenceRecordDigests"], name="evidenceRecordDigests")
    _validate_zone_snapshot(authority["zoneSnapshot"])
    _validate_execution_policy_snapshot(authority["executionPolicy"])
    _snapshot_string_list(authority["authorizedActorIds"], name="authorizedActorIds")
    if authority["targetRmseM"] is not None and type(authority["targetRmseM"]) is not float:
        raise ValueError("authority snapshot targetRmseM must be a canonical float or null")
    _snapshot_ints(authority, name="authority", fields=("maximumZoneCellCount",))
    _snapshot_floats(authority, name="authority", fields=("maximumZoneAreaM2",))
    _snapshot_bools(authority, name="authority", fields=("syntheticTestOnly",))
    return authority


@dataclass(frozen=True, slots=True)
class ExternalSingleVolumeExecutionAuthority:
    """Full, independently resolved single-epoch eligibility and execution binding."""

    organization_id: str
    site_id: str
    current_work_order_id: str
    decision_id: str
    decision_digest: str
    compatibility_mapping_digest: str
    target: ExternalVolumeInputBindingV1
    evidence_record_digests: tuple[str, ...]
    validation_policy_digest: str
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    execution_policy: ExternalSingleVolumeExecutionPolicyV1
    authorized_actor_ids: frozenset[str]
    valid_from: datetime
    valid_until: datetime
    historical_authority_digest: str
    target_rmse_m: float | None
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
        if len(self.evidence_record_digests) != 1:
            raise ValueError("single-volume authority requires exactly one evidence record")
        if self.target.subject.work_order_id != self.current_work_order_id:
            raise ValueError("authority target input must bind current_work_order_id")
        if _SHA256_DIGEST.fullmatch(self.compatibility_mapping_digest) is None:
            raise ValueError("authority compatibility mapping must be a sha256 digest")
        if _SHA256_DIGEST.fullmatch(self.historical_authority_digest) is None:
            raise ValueError("historical authority identity must be a sha256 digest")
        if (
            self.target.subject.organization_id != self.organization_id
            or self.target.subject.site_id != self.site_id
        ):
            raise ValueError("authority target must have the authority scope")
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
        rmse = self.target_rmse_m
        if rmse is not None and (type(rmse) is not float or not math.isfinite(rmse) or rmse < 0):
            raise ValueError("authority target RMSE must be a finite non-negative float or null")
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
            "target": self.target.model_dump(by_alias=True, mode="json"),
            "evidenceRecordDigests": list(self.evidence_record_digests),
            "validationPolicyDigest": self.validation_policy_digest,
            "zoneSnapshot": external_volume_zone_snapshot_wire_dict(self.zone_snapshot),
            "executionPolicy": external_single_volume_execution_policy_wire_dict(
                self.execution_policy
            ),
            "authorizedActorIds": sorted(self.authorized_actor_ids),
            "validFrom": iso_utc(self.valid_from),
            "validUntil": iso_utc(self.valid_until),
            "historicalAuthorityDigest": self.historical_authority_digest,
            "targetRmseM": self.target_rmse_m,
            "maximumZoneCellCount": self.maximum_zone_cell_count,
            "maximumZoneAreaM2": self.maximum_zone_area_m2,
            "syntheticTestOnly": self.synthetic_test_only,
        }

    @classmethod
    def from_snapshot(cls, raw: dict[str, Any]) -> ExternalSingleVolumeExecutionAuthority:
        snapshot = _validate_authority_snapshot_raw(raw)
        authority = cls(
            organization_id=snapshot["organizationId"],
            site_id=snapshot["siteId"],
            current_work_order_id=snapshot["currentWorkOrderId"],
            decision_id=snapshot["decisionId"],
            decision_digest=snapshot["decisionDigest"],
            compatibility_mapping_digest=snapshot["compatibilityMappingDigest"],
            target=ExternalVolumeInputBindingV1.model_validate(snapshot["target"]),
            evidence_record_digests=tuple(snapshot["evidenceRecordDigests"]),
            validation_policy_digest=snapshot["validationPolicyDigest"],
            zone_snapshot=ExternalVolumeZoneSnapshotV1.model_validate(snapshot["zoneSnapshot"]),
            execution_policy=ExternalSingleVolumeExecutionPolicyV1.model_validate(
                snapshot["executionPolicy"]
            ),
            authorized_actor_ids=frozenset(snapshot["authorizedActorIds"]),
            valid_from=datetime.fromisoformat(snapshot["validFrom"]),
            valid_until=datetime.fromisoformat(snapshot["validUntil"]),
            historical_authority_digest=snapshot["historicalAuthorityDigest"],
            target_rmse_m=snapshot["targetRmseM"],
            maximum_zone_cell_count=snapshot["maximumZoneCellCount"],
            maximum_zone_area_m2=snapshot["maximumZoneAreaM2"],
            synthetic_test_only=snapshot["syntheticTestOnly"],
        )
        if not _strict_snapshot_equal(snapshot, authority.snapshot_payload()):
            raise ValueError("authority snapshot does not match canonical serializer output")
        return authority


ExternalSingleVolumeExecutionAuthorityPort = ExternalVolumeExecutionAuthorityPort[
    ExternalSingleVolumeExecutionAuthority
]
ExternalSingleVolumeRecord = ExternalVolumeRecord[
    ExternalSingleVolumeRequestV1,
    ExternalSingleVolumeExecutionAuthority,
    ExternalSingleVolumeReportV1,
]
ExternalSingleVolumeResult = ExternalVolumeResult[
    ExternalSingleVolumeRequestV1,
    ExternalSingleVolumeExecutionAuthority,
    ExternalSingleVolumeReportV1,
]
ResolvedSingleVolumeReport = ResolvedVolumeReport[
    ExternalSingleVolumeRequestV1,
    ExternalSingleVolumeExecutionAuthority,
    ExternalSingleVolumeReportV1,
]
ExternalSingleVolumeObservedReportInput = ExternalVolumeObservedReportInput[
    ExternalSingleVolumeMeasurementPayloadV1
]


class DefaultClosedExternalSingleVolumeExecutionPort:
    """Production-safe execution seam when no single-volume catalog is configured."""

    def __init__(self, *, currentness_coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self.currentness_coordinator = currentness_coordinator

    def resolve_for_issue(
        self, *, principal: Principal, current_work_order_id: str, decision_ref: str, now: datetime
    ) -> ExternalSingleVolumeExecutionAuthority | None:
        del principal, current_work_order_id, decision_ref, now
        return None

    @contextmanager
    def guard_current(
        self,
        *,
        authority: ExternalSingleVolumeExecutionAuthority,
        principal: Principal,
        now: datetime,
    ) -> Iterator[ExternalSingleVolumeExecutionAuthority | None]:
        del authority, principal, now
        yield None

    def resolve_historical(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        issued_at: datetime,
        now: datetime,
    ) -> ExternalSingleVolumeExecutionAuthority | None:
        del historical_authority_digest, decision_id, decision_digest, issued_at, now
        return None


class ExternalSingleVolumeExecutionActivator(Protocol):
    def __call__(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        now: datetime,
    ) -> ExternalSingleVolumeExecutionAuthority | None: ...


# --------------------------------------------------------------------------------------
# Worker launch material
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SingleVolumeWorkerLaunchMaterial:
    """Sealed policy plus the one attested evidence record and its exact context."""

    validation_policy: ExternalValidationPolicyV1
    evidence_record: ExternalEvidenceRecordV1
    evidence_context: ExternalEvidenceMeasurementContextV1


class SingleVolumeWorkerLaunchMaterialResolver:
    """Resolve and locally recheck exact single-volume launch material."""

    def __init__(
        self,
        *,
        policy_registry: ExternalValidationPolicyRegistry,
        evidence_validations: ExternalEvidenceValidationStore,
        currentness_coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if policy_registry.coordinator is not currentness_coordinator:
            raise ValueError("policy registry must share currentness coordinator")
        if evidence_validations.coordinator is not currentness_coordinator:
            raise ValueError("evidence validations must share currentness coordinator")
        self._policy_registry = policy_registry
        self._evidence_validations = evidence_validations
        self._coordinator = currentness_coordinator

    @property
    def currentness_coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def preflight(
        self,
        request: ExternalSingleVolumeRequestV1,
        authority: ExternalSingleVolumeExecutionAuthority,
        *,
        now: datetime,
    ) -> SingleVolumeWorkerLaunchMaterial | None:
        """Resolve live policy/evidence before capability issuance and final guard."""
        del now
        if not _request_matches_authority(request, authority):
            return None
        selection = self._policy_registry.select_for_use("SINGLE_VOLUME", (request.target.subject,))
        policy = selection.policy
        if policy is None or not _policy_matches(request, authority, selection.status, policy):
            return None
        resolved = self._evidence_validations.record_for_current_use(
            request.evidence_record_digests[0],
            subject=request.target.subject,
            policy_digest=request.validation_policy_digest,
        )
        if resolved is None:
            return None
        record, context = resolved
        if not _record_matches_target(record, context, request, policy):
            return None
        return SingleVolumeWorkerLaunchMaterial(
            validation_policy=policy.model_copy(deep=True),
            evidence_record=record.model_copy(deep=True),
            evidence_context=context.model_copy(deep=True),
        )

    def material_remains_current(
        self,
        request: ExternalSingleVolumeRequestV1,
        authority: ExternalSingleVolumeExecutionAuthority,
        material: SingleVolumeWorkerLaunchMaterial,
        *,
        now: datetime,
    ) -> bool:
        """Final local-only recheck while the shared coordinator is held."""
        if not isinstance(material, SingleVolumeWorkerLaunchMaterial):
            return False
        if not _request_matches_authority(request, authority):
            return False
        if not self._policy_registry.locally_current_use_permitted(
            request.validation_policy_digest,
            use="SINGLE_VOLUME",
            subjects=(request.target.subject,),
            at=now,
        ):
            return False
        policy_result = self._policy_registry.resolve(request.validation_policy_digest)
        policy = policy_result.policy
        if (
            policy is None
            or policy != material.validation_policy
            or not _policy_matches(request, authority, policy_result.status, policy)
        ):
            return False
        resolved = self._evidence_validations.record_for_locally_current_use(
            request.evidence_record_digests[0],
            subject=request.target.subject,
            policy_digest=request.validation_policy_digest,
        )
        if resolved is None:
            return False
        record, context = resolved
        return (
            record == material.evidence_record
            and context == material.evidence_context
            and _record_matches_target(record, context, request, policy)
        )


def _request_matches_authority(
    request: ExternalSingleVolumeRequestV1,
    authority: ExternalSingleVolumeExecutionAuthority,
) -> bool:
    return (
        request.request_digest is not None
        and request.target == authority.target
        and request.evidence_record_digests == authority.evidence_record_digests
        and request.validation_policy_digest == authority.validation_policy_digest
        and request.execution_policy_digest == authority.execution_policy.canonical_digest()
    )


def _policy_matches(
    request: ExternalSingleVolumeRequestV1,
    authority: ExternalSingleVolumeExecutionAuthority,
    status: PolicySelectionStatus,
    policy: ExternalValidationPolicyV1,
) -> bool:
    return (
        status is PolicySelectionStatus.ACTIVE
        and policy.status is PolicyStatus.ACTIVE
        and policy.policy_digest == request.validation_policy_digest
        and policy.policy_digest == authority.validation_policy_digest
        and policy.resource_envelope is not None
        and policy.resource_envelope_digest is not None
        and policy.resource_envelope_digest == authority.execution_policy.resource_envelope_digest
    )


def _record_matches_target(
    record: ExternalEvidenceRecordV1,
    context: ExternalEvidenceMeasurementContextV1,
    request: ExternalSingleVolumeRequestV1,
    policy: ExternalValidationPolicyV1,
) -> bool:
    binding = request.target
    context_digest = context.context_digest
    return (
        record.evidence_record_digest == request.evidence_record_digests[0]
        and record.evidence_record_digest == record.canonical_digest()
        and record.subject_digest == binding.subject.canonical_digest()
        and record.target_dsm_observed_sha256 == binding.observed_sha256
        and record.policy_digest == policy.policy_digest
        and record.evidence_manifest_digest == context.evidence_manifest_digest
        and context_digest is not None
        and context_digest == context.canonical_digest()
        and context.subject == binding.subject
        and context.policy_digest == policy.policy_digest
        and context.target_dsm_artifact_id == binding.dsm_artifact_id
        and context.target_dsm_observed_sha256 == binding.observed_sha256
        and context.independent_attestation is not None
    )


# --------------------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------------------


class ExternalSingleVolumeStore(
    ExternalVolumeLedger[
        ExternalSingleVolumeRequestV1,
        ExternalSingleVolumeExecutionAuthority,
        ExternalSingleVolumeReportV1,
        ExternalSingleVolumeMeasurementPayloadV1,
    ]
):
    """The external single-epoch volume family."""

    _LABEL = "single-volume"
    _KIND_PREFIX = "external-single-volume"
    _recovery_error = ExternalSingleVolumeRecoveryError

    @property
    def launch_material_resolver(self) -> SingleVolumeWorkerLaunchMaterialResolver | None:
        resolver = self._launch_material_resolver
        return resolver if isinstance(resolver, SingleVolumeWorkerLaunchMaterialResolver) else None

    def _authority_from_snapshot(
        self, raw: dict[str, Any]
    ) -> ExternalSingleVolumeExecutionAuthority:
        return ExternalSingleVolumeExecutionAuthority.from_snapshot(raw)

    def _request_from_wire(self, raw: object) -> ExternalSingleVolumeRequestV1:
        return ExternalSingleVolumeRequestV1.model_validate(raw)

    def _request_wire(self, request: ExternalSingleVolumeRequestV1) -> dict[str, Any]:
        return external_single_volume_request_wire_dict(request)

    def _report_from_wire(self, raw: object) -> ExternalSingleVolumeReportV1:
        return ExternalSingleVolumeReportV1.model_validate(raw)

    def _report_wire(self, report: ExternalSingleVolumeReportV1) -> dict[str, Any]:
        return external_single_volume_report_wire_dict(report)

    def _build_report(self, **fields: Any) -> ExternalSingleVolumeReportV1:
        return ExternalSingleVolumeReportV1(**fields).sealed()

    def _build_request(
        self,
        authority: ExternalSingleVolumeExecutionAuthority,
        *,
        request_id: str,
        current_work_order_id: str,
        issued_at: datetime,
        idempotency_key: str,
    ) -> ExternalSingleVolumeRequestV1:
        return ExternalSingleVolumeRequestV1(
            request_id=request_id,
            current_work_order_id=current_work_order_id,
            decision_id=authority.decision_id,
            decision_digest=authority.decision_digest,
            target=authority.target,
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
                "domain": _ISSUE_DOMAIN,
                "organizationId": organization_id,
                "currentWorkOrderId": current_work_order_id,
                "decisionId": authority.decision_id,
                "decisionDigest": authority.decision_digest,
                "compatibilityMapping": authority.compatibility_mapping_digest,
                "target": authority.target.observed_sha256,
                "evidence": list(authority.evidence_record_digests),
                "validationPolicy": authority.validation_policy_digest,
                "executionPolicy": authority.execution_policy.canonical_digest(),
                "zone": authority.zone_snapshot.canonical_digest(),
            }
        )

    def _inputs_binding_error(
        self,
        request: ExternalSingleVolumeRequestV1,
        authority: ExternalSingleVolumeExecutionAuthority,
    ) -> str | None:
        if request.target != authority.target:
            return "issued DSM input differs from authority"
        if request.evidence_record_digests != authority.evidence_record_digests:
            return "issued evidence differs from authority"
        return None

    def _primary_site_id(self, authority: ExternalSingleVolumeExecutionAuthority) -> str:
        return authority.target.subject.site_id

    def _report_sort_time(self, record: ExternalSingleVolumeRecord) -> datetime:
        return record.request.target.captured_to

    def _measurement_payload_error(
        self,
        record: ExternalSingleVolumeRecord,
        payload: ExternalSingleVolumeMeasurementPayloadV1,
    ) -> str | None:
        request, authority = record.request, record.authority
        policy = authority.execution_policy
        if (
            request.request_digest is None
            or payload.request_digest != request.request_digest
            or payload.decision_digest != authority.decision_digest
            or payload.target_dsm_digest != authority.target.observed_sha256
            or payload.zone_snapshot_digest != authority.zone_snapshot.canonical_digest()
            or payload.execution_policy_digest != policy.canonical_digest()
            or payload.algorithm_build_digest != policy.algorithm_build_digest
            or payload.config_digest != policy.config_digest
        ):
            return "worker payload does not match sealed request authority"
        metrics = payload.metrics
        if metrics.threshold_m != policy.threshold_m:
            return "worker threshold differs from selected execution policy"
        if metrics.common_valid_fraction < policy.minimum_common_valid_fraction:
            return "coverage is below the selected execution policy minimum"
        if metrics.boundary_valid_fraction < policy.minimum_boundary_valid_fraction:
            return "boundary coverage is below the selected execution policy minimum"
        if (
            metrics.zone_cell_count > authority.maximum_zone_cell_count
            or metrics.zone_area_m2 > authority.maximum_zone_area_m2
        ):
            return "worker metrics exceed the selected resource envelope"
        if authority.target_rmse_m is None:
            if metrics.uncertainty_m3 is not None:
                return "uncertainty must be unknown without a trusted target RMSE"
            return None
        expected = metrics.measured_area_m2 * math.hypot(
            metrics.base_roughness_m, authority.target_rmse_m
        )
        if metrics.uncertainty_m3 is None or not math.isclose(
            metrics.uncertainty_m3, expected, rel_tol=1e-12, abs_tol=1e-12
        ):
            return "uncertainty does not match the single-epoch boundary-base bound"
        return None


# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------


class ExternalSingleVolumeWorkerReportInput(CamelModel):
    payload: ExternalSingleVolumeMeasurementPayloadV1
    computed_at: datetime

    @field_validator("computed_at")
    @classmethod
    def _computed_at_is_utc(cls, value: datetime) -> datetime:
        _require_utc(value, name="computedAt")
        return value


class ExternalSingleVolumeWorkerInputView(CamelModel):
    request: dict[str, Any]
    execution_policy: dict[str, Any]
    validation_policy: ExternalValidationPolicyV1
    evidence_record: ExternalEvidenceRecordV1
    inputs: tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability]


class ExternalSingleVolumeWorkerInputResponse(CamelModel):
    verdict: ExternalRelativeVolumeVerdict
    input: ExternalSingleVolumeWorkerInputView | None = None
    detail: str | None = None


class ExternalSingleVolumeInputCapabilityIssuer(Protocol):
    def __call__(
        self,
        record: ExternalSingleVolumeRecord,
        material: SingleVolumeWorkerLaunchMaterial,
        *,
        fence: LeaseFence,
        principal: Principal,
        now: datetime,
    ) -> (
        tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability] | None
    ): ...


_PUBLIC_BASE = "/v1/observation-work-orders/{work_order_id}/single-volume-requests"
_INTERNAL_BASE = "/v1/internal/external-validation/single-volumes"


def build_external_single_volume_router(
    store: ExternalSingleVolumeStore,
    *,
    input_capability_issuer: ExternalSingleVolumeInputCapabilityIssuer,
    execution_activator: ExternalSingleVolumeExecutionActivator | None = None,
    work_orders: Any | None = None,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-single-volumes"])

    def mutation_response(
        result: ExternalSingleVolumeResult, response: Response
    ) -> ExternalRelativeVolumeMutationResponse:
        fence = (
            result.fence
            if result.verdict
            in {ExternalRelativeVolumeVerdict.LEASED, ExternalRelativeVolumeVerdict.LEASE_RENEWED}
            else None
        )
        if fence is not None and result.lease_expires_at is not None:
            response.headers["X-KSI-Worker-Instance-Id"] = fence.worker_instance_id
            response.headers["X-KSI-Lease-Acquisition-Id"] = fence.lease_acquisition_id
            response.headers["X-KSI-Lease-Generation"] = str(fence.lease_generation)
            response.headers["X-KSI-Lease-Expires-At"] = iso_utc(result.lease_expires_at)
        response.status_code = _HTTP_STATUS[result.verdict]
        if result.verdict is ExternalRelativeVolumeVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
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
        _PUBLIC_BASE, response_model=ExternalRelativeVolumeMutationResponse, status_code=201
    )
    def issue_single_volume(
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
                prior_result: ExternalSingleVolumeResult | None = None
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
                            verdict=ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
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
            raise HTTPException(
                status_code=404, detail="single-volume request was not found"
            ) from exc
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        return mutation_response(result, response)

    @router.get(_PUBLIC_BASE, response_model=ExternalRelativeVolumeListResponse)
    def list_single_volumes(
        work_order_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ExternalRelativeVolumeListResponse:
        _require_scoped_work_order(work_orders, principal, work_order_id)
        return ExternalRelativeVolumeListResponse(
            items=[
                _to_view(record)
                for record in store.list_for_work_order(
                    work_order_id, organization_id=principal.organization_id
                )
            ]
        )

    @router.get(_PUBLIC_BASE + "/{request_ref}", response_model=ExternalRelativeVolumeRequestView)
    def get_single_volume(
        work_order_id: str,
        request_ref: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ExternalRelativeVolumeRequestView:
        _require_scoped_work_order(work_orders, principal, work_order_id)
        record = store.get(request_ref, organization_id=principal.organization_id)
        if record is None or record.request.current_work_order_id != work_order_id:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return _to_view(record)

    @router.get(_INTERNAL_BASE, response_model=ExternalRelativeVolumePendingResponse)
    def list_pending_single_volumes(
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
        _INTERNAL_BASE + "/{request_ref}/lease",
        response_model=ExternalRelativeVolumeMutationResponse,
        status_code=201,
    )
    def lease_single_volume(
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
        return mutation_response(result, response)

    @router.post(
        _INTERNAL_BASE + "/{request_ref}/heartbeat",
        response_model=ExternalRelativeVolumeMutationResponse,
    )
    def heartbeat_single_volume(
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
        return mutation_response(result, response)

    @router.get(
        _INTERNAL_BASE + "/{request_ref}/input",
        response_model=ExternalSingleVolumeWorkerInputResponse,
    )
    def get_single_volume_input(
        request_ref: str,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: int | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> ExternalSingleVolumeWorkerInputResponse:
        unavailable = ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
        fence = _fence_from_input(
            worker_instance_id or "", lease_acquisition_id or "", lease_generation or 0
        )
        first = store.worker_input(request_ref, principal=principal, fence=fence, now=now())
        if first.record is None or first.verdict is not ExternalRelativeVolumeVerdict.INPUT_READY:
            response.status_code = _HTTP_STATUS[first.verdict]
            return ExternalSingleVolumeWorkerInputResponse(
                verdict=first.verdict, detail=first.detail
            )
        resolver = store.launch_material_resolver
        material = (
            resolver.preflight(first.record.request, first.record.authority, now=now())
            if resolver is not None
            else None
        )
        if material is None:
            response.status_code = _HTTP_STATUS[unavailable]
            return ExternalSingleVolumeWorkerInputResponse(verdict=unavailable)
        # Preflight and presigning occur outside Core locks; the local-only
        # confirmation below prevents a revoked request from receiving capabilities.
        capabilities = input_capability_issuer(
            first.record, material, fence=fence, principal=principal, now=now()
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
            verdict = second.verdict if capabilities is not None else unavailable
            response.status_code = _HTTP_STATUS[verdict]
            return ExternalSingleVolumeWorkerInputResponse(verdict=verdict, detail=second.detail)
        return ExternalSingleVolumeWorkerInputResponse(
            verdict=ExternalRelativeVolumeVerdict.INPUT_READY,
            input=ExternalSingleVolumeWorkerInputView(
                request=external_single_volume_request_wire_dict(second.record.request),
                execution_policy=external_single_volume_execution_policy_wire_dict(
                    second.record.authority.execution_policy
                ),
                validation_policy=material.validation_policy,
                evidence_record=material.evidence_record,
                inputs=capabilities,
            ),
        )

    @router.post(
        _INTERNAL_BASE + "/{request_ref}/report",
        response_model=ExternalRelativeVolumeMutationResponse,
        status_code=201,
    )
    def report_single_volume(
        request_ref: str,
        request: ExternalSingleVolumeWorkerReportInput,
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
            observed=ExternalSingleVolumeObservedReportInput(
                payload=request.payload, computed_at=request.computed_at
            ),
            now=now(),
        )
        return mutation_response(result, response)

    @router.post(
        _INTERNAL_BASE + "/{request_ref}/incomplete-failure",
        response_model=ExternalRelativeVolumeMutationResponse,
    )
    def fail_single_volume(
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
        return mutation_response(result, response)

    return router


__all__ = [
    "DefaultClosedExternalSingleVolumeExecutionPort",
    "ExternalSingleVolumeExecutionActivator",
    "ExternalSingleVolumeExecutionAuthority",
    "ExternalSingleVolumeExecutionAuthorityPort",
    "ExternalSingleVolumeInputCapabilityIssuer",
    "ExternalSingleVolumeObservedReportInput",
    "ExternalSingleVolumeRecord",
    "ExternalSingleVolumeRecoveryError",
    "ExternalSingleVolumeResult",
    "ExternalSingleVolumeStore",
    "ExternalSingleVolumeWorkerInputResponse",
    "ExternalSingleVolumeWorkerInputView",
    "ResolvedSingleVolumeReport",
    "SingleVolumeWorkerLaunchMaterial",
    "SingleVolumeWorkerLaunchMaterialResolver",
    "build_external_single_volume_router",
]
