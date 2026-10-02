"""Sealed V2 numeric relative-volume records, separate from eligibility history.

The AP V2 analysis records establish *whether* a calculation may run.  This
module records only immutable numeric output and its exact coverage witness;
execution authorization and durable lifecycle records are added in later
sections of the same V2 contract family without changing AP journal events.
"""

from __future__ import annotations

import base64
import hashlib
import math
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import ConfigDict, Field, StrictFloat, StrictInt, StringConstraints, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest, ResourceEnvelopeV1

_FLOAT_REL_TOLERANCE = 1e-12
_FLOAT_ABS_TOLERANCE = 1e-12
_MAX_MASK_BASE64_CHARS = 2_000_000
_MASK_TEXT = Annotated[
    str,
    StringConstraints(
        strip_whitespace=False,
        min_length=4,
        max_length=_MAX_MASK_BASE64_CHARS,
        pattern=r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
    ),
]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Reason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{0,127}$"
    ),
]


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _mask_bytes(value: str, *, expected_bytes: int, name: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be canonical base64") from exc
    if len(decoded) != expected_bytes:
        raise ValueError(f"{name} byte length does not match rows and columns")
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{name} must be canonical base64")
    return decoded


def _count_bits(value: bytes) -> int:
    return sum(byte.bit_count() for byte in value)


class _FrozenCalculationModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    def _payload(self, digest_field: str) -> dict[str, Any]:
        raw = self.model_dump(by_alias=True, mode="json")
        alias = self.__class__.model_fields[digest_field].alias or digest_field
        raw.pop(alias, None)
        return raw

    def _seal(self, digest_field: str) -> Self:
        return self.model_copy(update={digest_field: _digest(self._payload(digest_field))})

    @staticmethod
    def _require_utc(value: datetime, name: str) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError(f"{name} must be UTC")
        return value


class RelativeVolumeCoverageWitnessV2(_FrozenCalculationModel):
    """Lossless bounded full-zone masks for a baseline-grid calculation.

    Bits are row-major and big-endian within each byte.  ``selected`` is the
    complete cell-centre WorkArea mask; ``commonValid`` is the exact cells that
    had finite values in both epochs; ``unavailable`` is the selected-minus-
    common mask.  The first fixed profile has a zero threshold, so its
    threshold-excluded mask must always be empty.
    """

    contract_version: Literal["external-relative-volume-coverage-witness.v2"] = (
        "external-relative-volume-coverage-witness.v2"
    )
    rows: StrictInt = Field(gt=0)
    columns: StrictInt = Field(gt=0)
    row_offset: StrictInt
    column_offset: StrictInt
    selected_mask_b64: _MASK_TEXT
    common_valid_mask_b64: _MASK_TEXT
    unavailable_mask_b64: _MASK_TEXT
    threshold_excluded_mask_b64: _MASK_TEXT
    selected_cell_count: StrictInt = Field(ge=0)
    common_valid_cell_count: StrictInt = Field(ge=0)
    unavailable_cell_count: StrictInt = Field(ge=0)
    threshold_excluded_cell_count: StrictInt = Field(ge=0)
    cell_area_m2: StrictFloat = Field(gt=0.0)
    selected_area_m2: StrictFloat = Field(ge=0.0)
    common_valid_area_m2: StrictFloat = Field(ge=0.0)
    bounds: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    coverage_witness_digest: Digest | None = None

    @model_validator(mode="after")
    def _has_exact_lossless_masks_and_areas(self) -> Self:
        cell_count = self.rows * self.columns
        expected_bytes = (cell_count + 7) // 8
        masks = {
            "selectedMaskB64": _mask_bytes(
                self.selected_mask_b64, expected_bytes=expected_bytes, name="selectedMaskB64"
            ),
            "commonValidMaskB64": _mask_bytes(
                self.common_valid_mask_b64,
                expected_bytes=expected_bytes,
                name="commonValidMaskB64",
            ),
            "unavailableMaskB64": _mask_bytes(
                self.unavailable_mask_b64,
                expected_bytes=expected_bytes,
                name="unavailableMaskB64",
            ),
            "thresholdExcludedMaskB64": _mask_bytes(
                self.threshold_excluded_mask_b64,
                expected_bytes=expected_bytes,
                name="thresholdExcludedMaskB64",
            ),
        }
        padding_bits = (-cell_count) % 8
        if padding_bits and any(mask[-1] & ((1 << padding_bits) - 1) for mask in masks.values()):
            raise ValueError("mask padding bits must be zero")
        selected = masks["selectedMaskB64"]
        common = masks["commonValidMaskB64"]
        unavailable = masks["unavailableMaskB64"]
        excluded = masks["thresholdExcludedMaskB64"]
        if any(
            common_bit & ~selected_bit
            for common_bit, selected_bit in zip(common, selected, strict=True)
        ):
            raise ValueError("common-valid cells must be selected")
        if any(
            unavailable_bit != (selected_bit & ~common_bit)
            for unavailable_bit, selected_bit, common_bit in zip(
                unavailable, selected, common, strict=True
            )
        ):
            raise ValueError("unavailable cells must be exactly selected minus common-valid")
        if any(excluded):
            raise ValueError("threshold-excluded cells must be empty for the fixed zero threshold")
        actual_counts = (
            _count_bits(selected),
            _count_bits(common),
            _count_bits(unavailable),
            _count_bits(excluded),
        )
        declared_counts = (
            self.selected_cell_count,
            self.common_valid_cell_count,
            self.unavailable_cell_count,
            self.threshold_excluded_cell_count,
        )
        if actual_counts != declared_counts:
            raise ValueError("coverage mask counts do not match their decoded bits")
        expected_selected_area = self.selected_cell_count * self.cell_area_m2
        expected_common_area = self.common_valid_cell_count * self.cell_area_m2
        if not math.isclose(
            self.selected_area_m2,
            expected_selected_area,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ) or not math.isclose(
            self.common_valid_area_m2,
            expected_common_area,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError("coverage areas must equal their cell counts times cell area")
        left, bottom, right, top = self.bounds
        if not all(math.isfinite(value) for value in self.bounds) or left >= right or bottom >= top:
            raise ValueError("coverage bounds must be finite and ordered")
        if self.coverage_witness_digest is not None and (
            self.coverage_witness_digest != self.canonical_digest()
        ):
            raise ValueError("coverage witness digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("coverage_witness_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("coverage_witness_digest")


class RelativeVolumeMetricsV2(_FrozenCalculationModel):
    """Finite cut/fill arithmetic for the one fixed profile."""

    cut_m3: StrictFloat = Field(ge=0.0)
    fill_m3: StrictFloat = Field(ge=0.0)
    net_m3: StrictFloat
    threshold_m: StrictFloat
    uncertainty_m3: None = None

    @model_validator(mode="after")
    def _is_fixed_profile_arithmetic(self) -> Self:
        if self.threshold_m != 0.0:
            raise ValueError("first profile requires a zero threshold")
        if not all(math.isfinite(value) for value in (self.cut_m3, self.fill_m3, self.net_m3)):
            raise ValueError("relative-volume metrics must be finite")
        if not math.isclose(
            self.net_m3,
            self.fill_m3 - self.cut_m3,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError("netM3 must equal fillM3 minus cutM3")
        return self


class RelativeVolumeNumericResultV2(_FrozenCalculationModel):
    """Calculation content only: it deliberately excludes attempt/admission state."""

    contract_version: Literal["external-relative-volume-numeric-result.v2"] = (
        "external-relative-volume-numeric-result.v2"
    )
    calculation_identity_digest: Digest
    profile_digest: Digest
    metrics: RelativeVolumeMetricsV2
    coverage: RelativeVolumeCoverageWitnessV2
    numeric_result_identity_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_the_fixed_full_coverage_profile(self) -> Self:
        if self.coverage.coverage_witness_digest is None or (
            self.coverage.coverage_witness_digest != self.coverage.canonical_digest()
        ):
            raise ValueError("coverage witness must be sealed")
        if (
            self.coverage.selected_cell_count == 0
            or self.coverage.unavailable_cell_count != 0
            or self.coverage.common_valid_cell_count != self.coverage.selected_cell_count
            or self.coverage.common_valid_area_m2 != self.coverage.selected_area_m2
        ):
            raise ValueError("fixed profile requires complete selected-zone common coverage")
        if self.numeric_result_identity_digest is not None and (
            self.numeric_result_identity_digest != self.canonical_digest()
        ):
            raise ValueError("numeric result identity differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("numeric_result_identity_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("numeric_result_identity_digest")


class AnalysisExecutionAuthorizationV2(_FrozenCalculationModel):
    """Core-selected resource and authority snapshot, separate from numeric identity."""

    contract_version: Literal["external-relative-volume-execution-authorization.v2"] = (
        "external-relative-volume-execution-authorization.v2"
    )
    authorization_id: Text
    organization_id: Text
    calculation_identity_digest: Digest
    admission_digest: Digest
    resource_envelope: ResourceEnvelopeV1
    resource_envelope_digest: Digest
    authorized_at: datetime
    execution_authorization_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_sealed_core_execution_limits(self) -> Self:
        self._require_utc(self.authorized_at, "authorizedAt")
        envelope = self.resource_envelope
        if envelope.resource_envelope_digest is None or (
            envelope.resource_envelope_digest != envelope.canonical_digest()
        ):
            raise ValueError("resource envelope must be sealed")
        if self.resource_envelope_digest != envelope.resource_envelope_digest:
            raise ValueError("resource envelope digest does not bind the supplied envelope")
        if self.execution_authorization_digest is not None and (
            self.execution_authorization_digest != self.canonical_digest()
        ):
            raise ValueError("execution authorization digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("execution_authorization_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("execution_authorization_digest")


class AnalysisExecutionAttemptV2(_FrozenCalculationModel):
    """A fenced worker ownership interval for exactly one authorization."""

    contract_version: Literal["external-relative-volume-execution-attempt.v2"] = (
        "external-relative-volume-execution-attempt.v2"
    )
    attempt_id: Text
    authorization: AnalysisExecutionAuthorizationV2
    authorization_digest: Digest
    worker_instance_id: Text
    lease_acquisition_id: Text
    lease_generation: StrictInt = Field(ge=1)
    issued_at: datetime
    lease_expires_at: datetime
    execution_attempt_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_exact_authorization_and_fence_interval(self) -> Self:
        self._require_utc(self.issued_at, "issuedAt")
        self._require_utc(self.lease_expires_at, "leaseExpiresAt")
        if self.lease_expires_at <= self.issued_at:
            raise ValueError("leaseExpiresAt must be after issuedAt")
        authorization = self.authorization
        if authorization.execution_authorization_digest is None or (
            authorization.execution_authorization_digest != authorization.canonical_digest()
        ):
            raise ValueError("execution authorization must be sealed")
        if self.authorization_digest != authorization.execution_authorization_digest:
            raise ValueError("authorization digest does not bind the supplied authorization")
        if self.execution_attempt_digest is not None and (
            self.execution_attempt_digest != self.canonical_digest()
        ):
            raise ValueError("execution attempt digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("execution_attempt_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("execution_attempt_digest")


class RelativeVolumeCalculationReportV2(_FrozenCalculationModel):
    """Fenced worker report that wraps, but cannot alter, numeric calculation content."""

    contract_version: Literal["external-relative-volume-calculation-report.v2"] = (
        "external-relative-volume-calculation-report.v2"
    )
    report_id: Text
    attempt: AnalysisExecutionAttemptV2
    attempt_digest: Digest
    numeric_result: RelativeVolumeNumericResultV2
    numeric_result_identity_digest: Digest
    computed_at: datetime
    reported_at: datetime
    report_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_fence_numeric_content_and_time(self) -> Self:
        self._require_utc(self.computed_at, "computedAt")
        self._require_utc(self.reported_at, "reportedAt")
        if self.computed_at > self.reported_at:
            raise ValueError("computedAt must be earlier than or equal to reportedAt")
        attempt = self.attempt
        if attempt.execution_attempt_digest is None or (
            attempt.execution_attempt_digest != attempt.canonical_digest()
        ):
            raise ValueError("execution attempt must be sealed")
        if self.attempt_digest != attempt.execution_attempt_digest:
            raise ValueError("attempt digest does not bind the supplied attempt")
        numeric = self.numeric_result
        if numeric.numeric_result_identity_digest is None or (
            numeric.numeric_result_identity_digest != numeric.canonical_digest()
        ):
            raise ValueError("numeric result must be sealed")
        if self.numeric_result_identity_digest != numeric.numeric_result_identity_digest:
            raise ValueError("numeric result identity does not bind numeric result")
        if (
            numeric.calculation_identity_digest
            != attempt.authorization.calculation_identity_digest
        ):
            raise ValueError("numeric result calculation identity does not bind authorization")
        if self.report_digest is not None and self.report_digest != self.canonical_digest():
            raise ValueError("report digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("report_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("report_digest")


class RelativeVolumeCalculationFailureV2(_FrozenCalculationModel):
    """A typed immutable attempt outcome that contains no partial numeric result."""

    contract_version: Literal["external-relative-volume-calculation-failure.v2"] = (
        "external-relative-volume-calculation-failure.v2"
    )
    failure_id: Text
    attempt: AnalysisExecutionAttemptV2
    attempt_digest: Digest
    reason_code: Reason
    failed_at: datetime
    failure_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_exact_attempt_and_timestamp(self) -> Self:
        self._require_utc(self.failed_at, "failedAt")
        attempt = self.attempt
        if attempt.execution_attempt_digest is None or (
            attempt.execution_attempt_digest != attempt.canonical_digest()
        ):
            raise ValueError("execution attempt must be sealed")
        if self.attempt_digest != attempt.execution_attempt_digest:
            raise ValueError("attempt digest does not bind the supplied attempt")
        if self.failure_digest is not None and self.failure_digest != self.canonical_digest():
            raise ValueError("failure digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("failure_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("failure_digest")


__all__ = [
    "AnalysisExecutionAttemptV2",
    "AnalysisExecutionAuthorizationV2",
    "RelativeVolumeCalculationFailureV2",
    "RelativeVolumeCalculationReportV2",
    "RelativeVolumeCoverageWitnessV2",
    "RelativeVolumeMetricsV2",
    "RelativeVolumeNumericResultV2",
]
