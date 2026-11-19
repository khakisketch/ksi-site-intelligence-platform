"""Surface-profile job: the frozen input, lease/fence, receipt and views of one profile read.

This is a **separate, additive job kind**.  It does not touch the frozen native-window
(``ksi-native-window.v1``) job, receipt, runtime or reason vocabulary: a profile result is JSON,
not a prepared GeoTIFF, and must not be squeezed into a contract that says otherwise.  It reuses the
sealed pieces that are genuinely shared — source facts (``SpatialDataSourceV1``), the data grant
(``SpatialDataGrantV1``), the saved line revision and the numeric ``surface-profile.v1`` payload.

Nothing here grants authority.  A job is only evidence of what Core froze at admission; every
transition re-proves current scope, grant, source and the HEIGHT verdict.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import Field, StrictBool, StringConstraints, model_validator

from ksi_event_contracts._spatial_data import (
    MAX_COUNTER,
    Attribution,
    Bounds,
    Digest,
    Origin,
    PositiveInt,
    PositiveSeconds,
    SpatialDataDigestModel,
    SpatialDataModel,
    Text,
    UtcTimestamp,
    require_utc,
)
from ksi_event_contracts.external_artifact_validation import (
    ObservedVerticalReferenceV1,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.measurement_feature import (
    MeasurementFeatureRefV1,
    MeasurementFeatureRevisionV1,
)
from ksi_event_contracts.spatial_data import (
    PixelWindow,
    SpatialDataAvailabilityV1,
    SpatialDataExecutionStateV1,
    SpatialDataSourceV1,
)
from ksi_event_contracts.spatial_data_authority import SpatialDataGrantV1
from ksi_event_contracts.spatial_data_worker import SpatialDataSourceCapabilityV1
from ksi_event_contracts.surface_profile import (
    MAX_PROFILE_SAMPLES,
    CreateSurfaceProfileV1,
    PositiveMetres,
    SurfaceProfileResultV1,
)
from ksi_event_contracts.vertical_reference import VerticalDatum

SURFACE_PROFILE_PROFILE: Literal["ksi-surface-profile.v1"] = "ksi-surface-profile.v1"


class SurfaceProfileDeclaredVerticalV1(SpatialDataModel):
    """The user's vertical-reference claim a job was frozen on.  Never an observation.

    Frozen with its record digest so the job proves exactly which claim licensed the read; a
    corrected or withdrawn declaration is a different record and no longer licenses it.
    """

    declaration_id: Text
    declaration_digest: Digest
    datum: VerticalDatum
    unit: Literal["metre"] = "metre"
    basis: Text
    declared_by: Text
    declared_at: UtcTimestamp


class SurfaceProfileVerticalReferenceV1(SpatialDataModel):
    """Where the heights' vertical reference comes from: the file (observed) or a user (declared).

    Exactly one of the two facts is present.  A declared basis is carried here, next to the
    numbers, so no screen or export can present it as something the parser observed.
    """

    provenance: Literal["OBSERVED", "DECLARED"]
    observed: ObservedVerticalReferenceV1 | None = None
    declared: SurfaceProfileDeclaredVerticalV1 | None = None

    @model_validator(mode="after")
    def _exactly_the_stated_provenance(self) -> Self:
        if self.provenance == "OBSERVED" and (self.observed is None or self.declared is not None):
            raise ValueError("an observed vertical reference carries the observation only")
        if self.provenance == "DECLARED" and (self.declared is None or self.observed is not None):
            raise ValueError("a declared vertical reference carries the declaration only")
        return self


SurfaceProfileJobId = Annotated[
    str,
    StringConstraints(strict=True, min_length=36, max_length=36, pattern=r"^spj-[0-9a-f]{32}$"),
]

# Closed vocabulary.  Calculation refusals keep the names of ``SurfaceProfileRefusalReasonV1`` so
# one reason means one thing across the numeric payload, the job and the audit.
SurfaceProfileJobReasonV1 = Literal[
    # admission / authority
    "PERMISSION_DENIED",
    "NOT_FOUND",
    "IDEMPOTENCY_CONFLICT",
    "INVALID_REQUEST",
    "FEATURE_UNAVAILABLE",
    "HEIGHT_NOT_ELIGIBLE",
    "SOURCE_NOT_MEASURED",
    "SOURCE_MEASUREMENTS_MISMATCH",
    "ACCESS_REVOKED",
    "ACCESS_EXPIRED",
    "OUTPUT_OUTSIDE_GRANT",
    "PROCESSING_LOCATION_DENIED",
    "POLICY_UNAVAILABLE",
    "CURRENTNESS_UNAVAILABLE",
    "PROFILE_COMPARISON_NO_LONGER_ELIGIBLE",
    "RESOURCE_LIMIT_EXCEEDED",
    "LINE_OUTSIDE_SURFACE",
    "GRANT_REQUIRED",
    "AMBIGUOUS_GRANT",
    "SOURCE_UNAVAILABLE",
    # lifecycle
    "NOT_READY",
    "RETENTION_EXPIRED",
    "FENCE_CONFLICT",
    "LEASE_EXPIRED",
    "DEADLINE_EXCEEDED",
    "CANCELED_BY_REQUESTER",
    "REPORT_CONFLICT",
    "INTEGRITY_MISMATCH",
    "SOURCE_BYTES_MISMATCH",
    "STORAGE_UNAVAILABLE",
    "WORKER_FAILED",
    # calculation refusals (same names as surface-profile.v1)
    "INVALID_LINE",
    "INVALID_SAMPLING",
    "TOO_MANY_VERTICES",
    "TOO_MANY_SAMPLES",
    "LINE_TOO_LONG",
    "UNSUPPORTED_CRS",
    "REPROJECTION_FAILED",
    "CRS_MISMATCH",
    "UNREADABLE_RASTER",
    "UNSUPPORTED_RASTER",
    "SOURCE_BLOCK_TOO_LARGE",
    "WINDOW_TOO_LARGE",
    "PLAN_MISMATCH",
]

# Only transport/storage trouble may be retried; a calculation refusal is a property of the input.
TRANSIENT_JOB_REASONS = frozenset({"STORAGE_UNAVAILABLE"})


def _digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class SurfaceProfilePolicyV1(SpatialDataDigestModel):
    """Finite limits Core freezes into a job.  Never client input, never defaulted."""

    _digest_field = "policy_digest"
    profile: Literal["ksi-surface-profile.v1"] = SURFACE_PROFILE_PROFILE
    policy_id: Text
    revision: PositiveInt
    resource_envelope: ResourceEnvelopeV1
    maximum_vertices: Annotated[int, Field(strict=True, ge=2, le=256)]
    maximum_samples: Annotated[int, Field(strict=True, ge=2, le=MAX_PROFILE_SAMPLES)]
    maximum_line_length_m: PositiveMetres
    maximum_window_cells: PositiveInt
    maximum_source_block_cells: PositiveInt
    # The numeric result is JSON kept in the journal, so its size is bounded explicitly.
    max_result_bytes: PositiveInt
    max_active_jobs_per_organization: PositiveInt
    max_pending_records: PositiveInt
    max_list_records: PositiveInt
    max_idempotency_key_bytes: PositiveInt
    lease_seconds: PositiveSeconds
    deadline_seconds: PositiveSeconds
    max_attempts: PositiveInt
    min_retry_backoff_seconds: PositiveSeconds
    max_retry_backoff_seconds: PositiveSeconds
    retention_seconds: PositiveSeconds
    policy_digest: Digest | None = None

    @model_validator(mode="after")
    def _finite_cross_field_envelope(self) -> Self:
        env = self.resource_envelope
        if env.resource_envelope_digest != env.canonical_digest():
            raise ValueError("policy requires an explicitly sealed resource envelope")
        if self.maximum_window_cells > env.max_pixels:
            raise ValueError("read window exceeds the envelope pixel limit")
        if self.maximum_source_block_cells > env.max_pixels:
            raise ValueError("source block limit exceeds the envelope pixel limit")
        if self.maximum_vertices > env.max_geometry_vertices:
            raise ValueError("vertices exceed the envelope geometry limit")
        if self.max_result_bytes > env.max_output_bytes:
            raise ValueError("result exceeds the envelope output limit")
        if not 0 < self.lease_seconds <= self.deadline_seconds <= env.max_deadline_seconds:
            raise ValueError("lease/deadline must fit the envelope deadline")
        if self.max_attempts > env.max_retry_attempts:
            raise ValueError("attempts exceed envelope")
        if self.max_active_jobs_per_organization > env.max_tenant_concurrency:
            raise ValueError("job concurrency exceeds envelope")
        if self.max_pending_records > env.max_queue_depth:
            raise ValueError("pending records exceed envelope queue")
        if self.min_retry_backoff_seconds > self.max_retry_backoff_seconds:
            raise ValueError("retry backoff bounds reversed")
        return self


class SurfaceProfileRuntimeV1(SpatialDataDigestModel):
    """The exact build that is allowed to compute profiles."""

    _digest_field = "runtime_digest"
    profile: Literal["ksi-surface-profile.v1"] = SURFACE_PROFILE_PROFILE
    executable_digest: Digest
    build_digest: Digest
    runtime_image: Text
    runtime_image_version: Text
    runtime_image_digest: Digest
    dependency_lock_digest: Digest
    runtime_digest: Digest | None = None


class SurfaceProfileActivationV1(SpatialDataDigestModel):
    """Operator-provisioned authority for one worker instance to run profile jobs."""

    _digest_field = "activation_digest"
    activation_id: Text
    organization_id: Text
    worker_principal_id: Text
    worker_instance_id: Text
    profile: Literal["ksi-surface-profile.v1"] = SURFACE_PROFILE_PROFILE
    policy_digest: Digest
    runtime_digest: Digest
    trusted_endpoint_origins: Annotated[
        tuple[Origin, ...],
        Field(min_length=1, max_length=16, json_schema_extra={"uniqueItems": True}),
    ]
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp
    activation_digest: Digest | None = None

    @model_validator(mode="after")
    def _positive_unique_scope(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("activation validity must have positive duration")
        if len(set(self.trusted_endpoint_origins)) != len(self.trusted_endpoint_origins):
            raise ValueError("activation origins must be unique")
        return self

    def is_current_at(self, now: UtcTimestamp) -> bool:
        record = type(self).model_validate(self.__dict__)
        return record.valid_from <= require_utc(now) < record.valid_until

    def signing_bytes(self) -> bytes:
        """분리된 서명 대상. 도메인 문자열로 native 공간 자료 활성화 서명과 섞이지 않는다."""
        record = type(self).model_validate(self.__dict__)
        return canonical_json_bytes(
            {
                "domain": "ksi-surface-profile-activation.v1",
                "payload": record.model_dump(by_alias=True, mode="json"),
            }
        )


class SurfaceProfileReadWindowV1(SpatialDataModel):
    """The one native pixel window a worker may read: sample neighbours only, never the raster."""

    pixel_window: PixelWindow
    actual_bounds: Bounds

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        col0, col1, row0, row1 = self.pixel_window
        if col0 >= col1 or row0 >= row1:
            raise ValueError("pixel window must have positive extent")
        return self

    @property
    def cells(self) -> int:
        col0, col1, row0, row1 = self.pixel_window
        return (col1 - col0) * (row1 - row0)


class CreateSurfaceProfileJobV1(SpatialDataModel):
    """Public request: a saved line revision on one exact asset.  The line is *not* in the body —
    Core reads it from the saved revision, so a request cannot read a line nobody saved."""

    asset_ref: Annotated[str, StringConstraints(strict=True, pattern=r"^ksa-v1-[0-9a-f]{64}$")]
    feature: MeasurementFeatureRefV1
    height_decision_id: Text
    sample_spacing_m: PositiveMetres | None = None

    def canonical_digest(self) -> str:
        record = type(self).model_validate(self.__dict__)
        return _digest(record.model_dump(by_alias=True, mode="json"))


class SurfaceProfileFrozenJobV1(SpatialDataDigestModel):
    _digest_field = "job_digest"
    job_id: SurfaceProfileJobId
    organization_id: Text
    requester_principal_id: Text
    site_id: Text
    work_area_id: Text
    request: CreateSurfaceProfileJobV1
    feature: MeasurementFeatureRevisionV1
    profile_request: CreateSurfaceProfileV1
    source: SpatialDataSourceV1
    grant: SpatialDataGrantV1
    data_policy_digest: Digest
    height_decision_digest: Digest
    vertical_reference: SurfaceProfileVerticalReferenceV1
    policy: SurfaceProfilePolicyV1
    runtime: SurfaceProfileRuntimeV1
    # ``None`` = every sample is outside the surface, so nothing may be read at all.
    read_window: SurfaceProfileReadWindowV1 | None
    idempotency_key_hash: Digest
    request_fingerprint: Digest
    created_at: UtcTimestamp
    deadline: UtcTimestamp
    job_digest: Digest | None = None

    @model_validator(mode="after")
    def _bound_snapshots(self) -> Self:
        for snapshot in (self.feature, self.source, self.grant, self.policy, self.runtime):
            if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
                raise ValueError("frozen job requires fully sealed snapshots")
        feature, source, grant = self.feature, self.source, self.grant
        if (self.organization_id, self.site_id, self.work_area_id) != (
            source.sealed_subject.organization_id,
            source.site_id,
            source.work_area_id,
        ):
            raise ValueError("job scope must match exact source scope")
        if (feature.site_id, feature.work_area_id) != (self.site_id, self.work_area_id):
            raise ValueError("the saved line must belong to the job's work area")
        if (self.organization_id, self.requester_principal_id, self.site_id, self.work_area_id) != (
            grant.organization_id,
            grant.beneficiary_principal_id,
            grant.site_id,
            grant.work_area_id,
        ):
            raise ValueError("job beneficiary/scope must match grant")
        if not (
            self.request.asset_ref
            == self.profile_request.asset_ref
            == source.asset_ref
            == grant.asset_ref
        ):
            raise ValueError("request, source and grant must bind the same exact asset")
        if self.request.feature != feature.ref() or self.profile_request.feature != feature.ref():
            raise ValueError("request must bind the exact saved line revision")
        if self.profile_request.line != feature.line:
            raise ValueError("the line read must be the saved revision's line")
        if self.profile_request.sample_spacing_m != self.request.sample_spacing_m:
            raise ValueError("sampling spacing must be the requested spacing")
        if self.request_fingerprint != self.request.canonical_digest():
            raise ValueError("request fingerprint does not bind the normalized body")
        if grant.policy_digest != self.data_policy_digest:
            raise ValueError("grant must bind the frozen data policy")
        if source.artifact_kind != "dsm":
            raise ValueError("a surface profile reads a DSM")
        measured = source.inspection.measurements
        if measured is None or measured.observed_crs_digest != grant.observed_crs_digest:
            raise ValueError("source CRS must match the grant")
        vertical = self.vertical_reference
        if vertical.provenance == "OBSERVED":
            if vertical.observed != measured.observed_vertical_reference:
                raise ValueError("an observed vertical reference must be the source's own")
        elif measured.observed_vertical_reference is not None:
            raise ValueError("a file that carries its own vertical reference takes no declaration")
        if not {"PREPARE", "READ"} <= set(grant.operations) or (
            "GENERAL_DATA_USE" not in grant.purposes
        ):
            raise ValueError("the grant must allow preparing and reading for general data use")
        if not grant.is_current_at(self.created_at):
            raise ValueError("grant must be current at admission")
        if self.read_window is not None:
            left, bottom, right, top = grant.allowed_bounds
            xmin, ymin, xmax, ymax = self.read_window.actual_bounds
            if xmin < left or ymin < bottom or xmax > right or ymax > top:
                raise ValueError("the read window must lie inside the grant")
            if self.read_window.cells > self.policy.maximum_window_cells:
                raise ValueError("the read window exceeds the policy limit")
        elapsed = (self.deadline - self.created_at).total_seconds()
        if not 0 < elapsed <= self.policy.deadline_seconds:
            raise ValueError("job deadline exceeds the policy")
        return self


class SurfaceProfileAttemptV1(SpatialDataDigestModel):
    _digest_field = "attempt_digest"
    job_id: SurfaceProfileJobId
    frozen_job_digest: Digest
    attempt_number: PositiveInt
    fence: PositiveInt
    worker_principal_id: Text
    worker_instance_id: Text
    acquisition_key_hash: Digest
    acquired_at: UtcTimestamp
    lease_until: UtcTimestamp
    attempt_digest: Digest | None = None

    @model_validator(mode="after")
    def _positive_lease(self) -> Self:
        if self.lease_until <= self.acquired_at:
            raise ValueError("lease interval must have positive duration")
        return self

    def fence_digest(self) -> str:
        """Stable acquisition identity: a renewal changes ``lease_until`` but never the fence."""
        record = type(self).model_validate(self.__dict__)
        return _digest(
            record.model_dump(by_alias=True, mode="json", exclude={"attempt_digest", "lease_until"})
        )


class SurfaceProfileReceiptV1(SpatialDataDigestModel):
    """What the worker attests it did.  Core verifies it against the frozen job; it never replaces
    that check, and it asserts no accuracy."""

    _digest_field = "receipt_digest"
    job_id: SurfaceProfileJobId
    job_digest: Digest
    source_digest: Digest
    request_digest: Digest
    grant_digest: Digest
    data_policy_digest: Digest
    policy_digest: Digest
    runtime_digest: Digest
    preparation_profile: Literal["ksi-surface-profile.v1"] = SURFACE_PROFILE_PROFILE
    artifact_id: Text
    source_sha256: Digest
    source_size_bytes: PositiveInt
    observed_crs_identifier: Text
    observed_crs_digest: Digest
    vertical_reference: SurfaceProfileVerticalReferenceV1
    result_digest: Digest
    read_window: SurfaceProfileReadWindowV1 | None
    window_cells_read: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNTER)]
    accuracy_assessed: Annotated[StrictBool, Field(json_schema_extra={"const": False})]
    prepared_at: UtcTimestamp
    attribution: Attribution
    limitations: tuple[Text, ...] = Field(max_length=16)
    receipt_digest: Digest | None = None


class SurfaceProfileLeaseRequestV1(SpatialDataModel):
    worker_instance_id: Text
    acquisition_id: Text


class SurfaceProfileLeaseViewV1(SpatialDataModel):
    job_id: SurfaceProfileJobId
    attempt: SurfaceProfileAttemptV1


class SurfaceProfileRenewRequestV1(SpatialDataModel):
    attempt: SurfaceProfileAttemptV1


class SurfaceProfileCompleteRequestV1(SpatialDataModel):
    attempt: SurfaceProfileAttemptV1
    result: SurfaceProfileResultV1
    receipt: SurfaceProfileReceiptV1

    @model_validator(mode="after")
    def _result_is_the_one_the_receipt_attests(self) -> Self:
        result = self.result
        if result.result_digest is None or result.result_digest != result.canonical_digest():
            raise ValueError("the result must be sealed")
        if self.receipt.receipt_digest is None or (
            self.receipt.receipt_digest != self.receipt.canonical_digest()
        ):
            raise ValueError("the receipt must be sealed")
        if (
            self.receipt.result_digest != result.result_digest
            or self.receipt.job_id != self.attempt.job_id
            or self.receipt.job_digest != self.attempt.frozen_job_digest
            or self.receipt.window_cells_read != result.window_cells_read
        ):
            raise ValueError("the receipt must attest this result for this attempt")
        return self


class SurfaceProfileFailureRequestV1(SpatialDataModel):
    attempt: SurfaceProfileAttemptV1
    reason: SurfaceProfileJobReasonV1
    retryable: StrictBool

    @model_validator(mode="after")
    def _transport_only_retry(self) -> Self:
        if self.retryable != (self.reason in TRANSIENT_JOB_REASONS):
            raise ValueError("only storage/transport failures are retryable")
        return self


class SurfaceProfileJobViewV1(SpatialDataModel):
    """Requester-visible state.  Carries the receipt, never the numeric samples — those need a
    fresh READ proof through the result route."""

    job_id: SurfaceProfileJobId
    asset_ref: Annotated[str, StringConstraints(strict=True, pattern=r"^ksa-v1-[0-9a-f]{64}$")]
    site_id: Text
    work_area_id: Text
    feature: MeasurementFeatureRefV1
    created_at: UtcTimestamp
    execution_state: SpatialDataExecutionStateV1
    availability: SpatialDataAvailabilityV1
    reason: SurfaceProfileJobReasonV1 | None = None
    receipt: SurfaceProfileReceiptV1 | None = None

    @model_validator(mode="after")
    def _receipt_only_when_completed(self) -> Self:
        completed = self.execution_state is SpatialDataExecutionStateV1.COMPLETED
        if (self.receipt is not None) != completed:
            raise ValueError("only a COMPLETED job has a receipt")
        return self


class SurfaceProfileResultViewV1(SpatialDataModel):
    """The numbers, released only after current READ authority was proven again."""

    job: SurfaceProfileJobViewV1
    result: SurfaceProfileResultV1


class CreateSurfaceProfileComparisonV1(SpatialDataModel):
    """Explicitly request the same saved-line profile from two ordered epochs."""

    baseline_job_id: SurfaceProfileJobId
    current_job_id: SurfaceProfileJobId

    @model_validator(mode="after")
    def _distinct_jobs(self) -> Self:
        if self.baseline_job_id == self.current_job_id:
            raise ValueError("baseline and current profile jobs must differ")
        return self


class SurfaceProfileComparisonSampleV1(SpatialDataModel):
    distance_m: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    baseline_m: Annotated[float, Field(strict=True, allow_inf_nan=False)] | None
    current_m: Annotated[float, Field(strict=True, allow_inf_nan=False)] | None
    difference_m: Annotated[float, Field(strict=True, allow_inf_nan=False)] | None
    invalid_reason: (
        Literal["BASELINE_UNAVAILABLE", "CURRENT_UNAVAILABLE", "BOTH_UNAVAILABLE"] | None
    )

    @model_validator(mode="after")
    def _difference_requires_both_values(self) -> Self:
        expected_reason = (
            "BOTH_UNAVAILABLE"
            if self.baseline_m is None and self.current_m is None
            else "BASELINE_UNAVAILABLE"
            if self.baseline_m is None
            else "CURRENT_UNAVAILABLE"
            if self.current_m is None
            else None
        )
        expected_difference = (
            None
            if self.baseline_m is None or self.current_m is None
            else self.current_m - self.baseline_m
        )
        if self.invalid_reason != expected_reason or self.difference_m != expected_difference:
            raise ValueError("comparison values and unknown reason must agree")
        return self


class SurfaceProfileComparisonResultV1(SpatialDataDigestModel):
    """Numeric output bound to both exact immutable single-surface results."""

    _digest_field = "comparison_digest"
    baseline_result_digest: Digest
    current_result_digest: Digest
    samples: Annotated[
        tuple[SurfaceProfileComparisonSampleV1, ...],
        Field(min_length=2, max_length=MAX_PROFILE_SAMPLES),
    ]
    valid_count: Annotated[int, Field(strict=True, ge=0)]
    largest_rise_m: Annotated[float, Field(strict=True, allow_inf_nan=False)] | None
    largest_drop_m: Annotated[float, Field(strict=True, allow_inf_nan=False)] | None
    comparison_digest: Digest | None = None

    @model_validator(mode="after")
    def _consistent_samples(self) -> Self:
        distances = [sample.distance_m for sample in self.samples]
        if distances[0] != 0 or any(b <= a for a, b in zip(distances, distances[1:], strict=False)):
            raise ValueError("comparison distances must start at zero and strictly increase")
        differences = [
            sample.difference_m for sample in self.samples if sample.difference_m is not None
        ]
        if (
            self.valid_count != len(differences)
            or self.largest_rise_m != max((d for d in differences if d > 0), default=None)
            or self.largest_drop_m != min((d for d in differences if d < 0), default=None)
        ):
            raise ValueError("comparison summary must match known samples")
        return self


class SurfaceProfileComparisonV1(SpatialDataModel):
    contract_version: Literal["surface-profile-comparison.v1"] = "surface-profile-comparison.v1"
    baseline_job_id: SurfaceProfileJobId
    current_job_id: SurfaceProfileJobId
    decision_id: Text
    decision_digest: Digest
    verdict: Literal["BLOCKED", "ELIGIBLE"]
    reasons: tuple[Text, ...] = Field(min_length=1, max_length=32)
    remediations: tuple[Text, ...] = Field(min_length=1, max_length=32)
    result: SurfaceProfileComparisonResultV1 | None = None

    @model_validator(mode="after")
    def _numbers_only_after_eligible_decision(self) -> Self:
        if (self.verdict == "ELIGIBLE") != (self.result is not None):
            raise ValueError("numeric comparison requires an eligible decision")
        return self


SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER = "X-Surface-Profile-Worker-Instance-Id"
SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER = "X-Surface-Profile-Attempt-Digest"


class SurfaceProfileErrorV1(SpatialDataModel):
    reason: SurfaceProfileJobReasonV1
    message: Text
    retryable: StrictBool
    remediation: tuple[
        Literal["CONTACT_OPERATOR", "RECHECK_CURRENT_PAIR", "CREATE_NEW_COMPARISON"], ...
    ]


class SurfaceProfileJobPageV1(SpatialDataModel):
    items: tuple[SurfaceProfileJobViewV1, ...] = Field(max_length=MAX_COUNTER)


class SurfaceProfileWorkerPendingItemV1(SpatialDataModel):
    job_id: SurfaceProfileJobId


class SurfaceProfileWorkerPendingPageV1(SpatialDataModel):
    items: tuple[SurfaceProfileWorkerPendingItemV1, ...] = Field(max_length=MAX_COUNTER)


class SurfaceProfileWorkerInputV1(SpatialDataModel):
    """일꾼이 받는 입력: 봉인된 작업, 현재 attempt, 활성화와 짧은 수명의 원본 읽기 capability."""

    job: SurfaceProfileFrozenJobV1
    attempt: SurfaceProfileAttemptV1
    activation: SurfaceProfileActivationV1
    source_capability: SpatialDataSourceCapabilityV1

    @model_validator(mode="after")
    def _exact_attempt_activation_and_capability(self) -> Self:
        job, attempt, activation, cap = (
            self.job,
            self.attempt,
            self.activation,
            self.source_capability,
        )
        for snapshot in (job, attempt, activation):
            if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
                raise ValueError("worker input requires sealed snapshots")
        if attempt.job_id != job.job_id or attempt.frozen_job_digest != job.job_digest:
            raise ValueError("worker input must bind exact frozen job and attempt")
        if (
            activation.organization_id != job.organization_id
            or activation.worker_principal_id != attempt.worker_principal_id
            or activation.worker_instance_id != attempt.worker_instance_id
            or activation.runtime_digest != job.runtime.runtime_digest
            or activation.policy_digest != job.policy.policy_digest
        ):
            raise ValueError("activation must bind organization, worker, runtime and policy")
        if not activation.is_current_at(attempt.acquired_at):
            raise ValueError("activation is not current at lease acquisition")
        if (
            cap.expires_at
            > min(attempt.lease_until, job.deadline, job.grant.valid_until, activation.valid_until)
            or cap.expires_at <= attempt.acquired_at
        ):
            raise ValueError("source capability must be current and no longer than every gate")
        source = job.source
        if (cap.artifact_id, cap.source_digest, cap.observed_sha256, cap.observed_size_bytes) != (
            source.artifact_id,
            source.source_digest,
            source.observed_sha256,
            source.observed_size_bytes,
        ):
            raise ValueError("source capability must bind exact sealed bytes")
        parsed = urlsplit(cap.download_url)
        if f"{parsed.scheme}://{parsed.netloc}" not in activation.trusted_endpoint_origins:
            raise ValueError("source capability origin is not activated")
        return self


class SurfaceProfileWorkerInputResponseV1(SpatialDataModel):
    input: SurfaceProfileWorkerInputV1


__all__ = [
    "SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER",
    "SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER",
    "SurfaceProfileErrorV1",
    "SurfaceProfileJobPageV1",
    "SurfaceProfileWorkerPendingItemV1",
    "SurfaceProfileWorkerPendingPageV1",
    "SurfaceProfileWorkerInputResponseV1",
    "SurfaceProfileWorkerInputV1",
    "SURFACE_PROFILE_PROFILE",
    "TRANSIENT_JOB_REASONS",
    "CreateSurfaceProfileJobV1",
    "CreateSurfaceProfileComparisonV1",
    "SurfaceProfileActivationV1",
    "SurfaceProfileAttemptV1",
    "SurfaceProfileCompleteRequestV1",
    "SurfaceProfileFailureRequestV1",
    "SurfaceProfileFrozenJobV1",
    "SurfaceProfileJobId",
    "SurfaceProfileJobReasonV1",
    "SurfaceProfileJobViewV1",
    "SurfaceProfileLeaseRequestV1",
    "SurfaceProfileLeaseViewV1",
    "SurfaceProfilePolicyV1",
    "SurfaceProfileReadWindowV1",
    "SurfaceProfileReceiptV1",
    "SurfaceProfileRenewRequestV1",
    "SurfaceProfileResultViewV1",
    "SurfaceProfileComparisonSampleV1",
    "SurfaceProfileComparisonResultV1",
    "SurfaceProfileComparisonV1",
    "SurfaceProfileRuntimeV1",
]
