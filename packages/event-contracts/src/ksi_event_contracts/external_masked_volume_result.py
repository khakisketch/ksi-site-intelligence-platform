"""Sealed V3 masked-volume numeric result and lossless coverage witness.

Additive only. Reuses the fixed V2 arithmetic leaf
(:class:`RelativeVolumeMetricsV2`) without extending it. The V3 result key
references :class:`MaskedCalculationIdentityV3` plus the sealed profile and
mask-binding digests; it never reuses a V2 numeric result identity.

Coverage semantics (row-major, big-endian packed bits, zero padding):

- ``originalSelected``: hole-selected WorkArea cells (polygon holes first).
- ``maskExcluded``: subset of ``originalSelected`` removed by the mask.
- ``effectiveSelected``: exactly ``originalSelected`` minus ``maskExcluded``.
- ``commonValid``: subset of ``effectiveSelected`` with finite values.
- ``unavailable``: exactly ``effectiveSelected`` minus ``commonValid``.

Success requires nonzero effective cells and 100% common-valid coverage.
``impact`` records the unmasked-vs-masked consequence: when the original
zone has missing source values the full unmasked numeric impact is UNKNOWN
(``None``, never an invented excluded volume of zero); otherwise the
unmasked and excluded cut/fill/net are recorded with consistent finite
arithmetic.
"""

from __future__ import annotations

import base64
import hashlib
import math
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest
from ksi_event_contracts.external_relative_volume_calculation import RelativeVolumeMetricsV2

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


class _FrozenMaskedResultModel(_CamelModel):
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


class MaskedCoverageWitnessV3(_FrozenMaskedResultModel):
    """Lossless bounded masks: original, mask-excluded, effective, common, unavailable."""

    contract_version: Literal["external-masked-volume-coverage-witness.v3"] = (
        "external-masked-volume-coverage-witness.v3"
    )
    rows: StrictInt = Field(gt=0)
    columns: StrictInt = Field(gt=0)
    row_offset: StrictInt
    column_offset: StrictInt
    original_selected_mask_b64: _MASK_TEXT
    mask_excluded_mask_b64: _MASK_TEXT
    effective_selected_mask_b64: _MASK_TEXT
    common_valid_mask_b64: _MASK_TEXT
    unavailable_mask_b64: _MASK_TEXT
    original_selected_cell_count: StrictInt = Field(ge=0)
    mask_excluded_cell_count: StrictInt = Field(ge=0)
    effective_selected_cell_count: StrictInt = Field(ge=0)
    common_valid_cell_count: StrictInt = Field(ge=0)
    unavailable_cell_count: StrictInt = Field(ge=0)
    cell_area_m2: StrictFloat = Field(gt=0.0)
    original_selected_area_m2: StrictFloat = Field(ge=0.0)
    effective_selected_area_m2: StrictFloat = Field(ge=0.0)
    common_valid_area_m2: StrictFloat = Field(ge=0.0)
    bounds: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    coverage_witness_digest: Digest | None = None

    @model_validator(mode="after")
    def _has_exact_lossless_masked_coverage(self) -> Self:
        cell_count = self.rows * self.columns
        expected_bytes = (cell_count + 7) // 8
        masks = {
            "originalSelectedMaskB64": _mask_bytes(
                self.original_selected_mask_b64,
                expected_bytes=expected_bytes,
                name="originalSelectedMaskB64",
            ),
            "maskExcludedMaskB64": _mask_bytes(
                self.mask_excluded_mask_b64,
                expected_bytes=expected_bytes,
                name="maskExcludedMaskB64",
            ),
            "effectiveSelectedMaskB64": _mask_bytes(
                self.effective_selected_mask_b64,
                expected_bytes=expected_bytes,
                name="effectiveSelectedMaskB64",
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
        }
        padding_bits = (-cell_count) % 8
        if padding_bits and any(mask[-1] & ((1 << padding_bits) - 1) for mask in masks.values()):
            raise ValueError("mask padding bits must be zero")
        original = masks["originalSelectedMaskB64"]
        excluded = masks["maskExcludedMaskB64"]
        effective = masks["effectiveSelectedMaskB64"]
        common = masks["commonValidMaskB64"]
        unavailable = masks["unavailableMaskB64"]
        if any(ex & ~sel for ex, sel in zip(excluded, original, strict=True)):
            raise ValueError("mask-excluded cells must be a subset of original-selected")
        if any(
            eff != (sel & ~ex) for eff, sel, ex in zip(effective, original, excluded, strict=True)
        ):
            raise ValueError("effective cells must equal original-selected minus mask-excluded")
        if any(cm & ~eff for cm, eff in zip(common, effective, strict=True)):
            raise ValueError("common-valid cells must be a subset of effective-selected")
        if any(
            un != (eff & ~cm) for un, eff, cm in zip(unavailable, effective, common, strict=True)
        ):
            raise ValueError("unavailable cells must be exactly effective minus common-valid")
        actual_counts = (
            _count_bits(original),
            _count_bits(excluded),
            _count_bits(effective),
            _count_bits(common),
            _count_bits(unavailable),
        )
        declared_counts = (
            self.original_selected_cell_count,
            self.mask_excluded_cell_count,
            self.effective_selected_cell_count,
            self.common_valid_cell_count,
            self.unavailable_cell_count,
        )
        if actual_counts != declared_counts:
            raise ValueError("coverage mask counts do not match their decoded bits")
        if self.effective_selected_cell_count == 0:
            raise ValueError("masked profile requires a nonzero effective zone")
        if (
            self.unavailable_cell_count != 0
            or self.common_valid_cell_count != self.effective_selected_cell_count
        ):
            raise ValueError("masked profile requires 100% common-valid effective coverage")
        expected_areas = (
            self.original_selected_cell_count * self.cell_area_m2,
            self.effective_selected_cell_count * self.cell_area_m2,
            self.common_valid_cell_count * self.cell_area_m2,
        )
        actual_areas = (
            self.original_selected_area_m2,
            self.effective_selected_area_m2,
            self.common_valid_area_m2,
        )
        if not all(
            math.isclose(
                actual, expected, rel_tol=_FLOAT_REL_TOLERANCE, abs_tol=_FLOAT_ABS_TOLERANCE
            )
            for actual, expected in zip(actual_areas, expected_areas, strict=True)
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


class MaskedVolumeImpactV3(_FrozenMaskedResultModel):
    """Unmasked-vs-masked consequence; unknown stays null, never zero-invented."""

    unmasked_impact_known: StrictBool
    excluded_cell_count: StrictInt = Field(ge=0)
    unmasked_cut_m3: StrictFloat | None = Field(default=None, ge=0.0)
    unmasked_fill_m3: StrictFloat | None = Field(default=None, ge=0.0)
    unmasked_net_m3: StrictFloat | None = None
    excluded_cut_m3: StrictFloat | None = Field(default=None, ge=0.0)
    excluded_fill_m3: StrictFloat | None = Field(default=None, ge=0.0)
    excluded_net_m3: StrictFloat | None = None

    @model_validator(mode="after")
    def _has_consistent_impact_shape(self) -> Self:
        volumes = (
            self.unmasked_cut_m3,
            self.unmasked_fill_m3,
            self.unmasked_net_m3,
            self.excluded_cut_m3,
            self.excluded_fill_m3,
            self.excluded_net_m3,
        )
        if not self.unmasked_impact_known:
            if any(value is not None for value in volumes):
                raise ValueError("unknown unmasked impact must carry null volumes")
            return self
        if any(value is None for value in volumes):
            raise ValueError("known unmasked impact must carry all volumes")
        assert (
            self.unmasked_cut_m3 is not None
            and self.unmasked_fill_m3 is not None
            and self.unmasked_net_m3 is not None
            and self.excluded_cut_m3 is not None
            and self.excluded_fill_m3 is not None
            and self.excluded_net_m3 is not None
        )
        finite_values = (
            self.unmasked_cut_m3,
            self.unmasked_fill_m3,
            self.unmasked_net_m3,
            self.excluded_cut_m3,
            self.excluded_fill_m3,
            self.excluded_net_m3,
        )
        if not all(math.isfinite(value) for value in finite_values):
            raise ValueError("masked impact volumes must be finite")
        if not math.isclose(
            self.unmasked_net_m3,
            self.unmasked_fill_m3 - self.unmasked_cut_m3,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ) or not math.isclose(
            self.excluded_net_m3,
            self.excluded_fill_m3 - self.excluded_cut_m3,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError("impact net volumes must equal fill minus cut")
        return self


class MaskedVolumeNumericResultV3(_FrozenMaskedResultModel):
    """Identity-bound masked numeric content; the V2 leaf is reused, never extended."""

    contract_version: Literal["external-masked-volume-numeric-result.v3"] = (
        "external-masked-volume-numeric-result.v3"
    )
    masked_calculation_identity_digest: Digest
    masked_profile_digest: Digest
    mask_binding_digest: Digest
    metrics: RelativeVolumeMetricsV2
    coverage: MaskedCoverageWitnessV3
    impact: MaskedVolumeImpactV3
    numeric_result_identity_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_full_coverage_masked_result(self) -> Self:
        if self.coverage.coverage_witness_digest is None or (
            self.coverage.coverage_witness_digest != self.coverage.canonical_digest()
        ):
            raise ValueError("coverage witness must be sealed")
        if self.contract_version == "external-relative-volume-numeric-result.v2":
            raise ValueError("masked result must not reuse a V2 result identity")
        if self.impact.excluded_cell_count != self.coverage.mask_excluded_cell_count:
            raise ValueError("impact excluded count must match the coverage witness")
        if self.impact.unmasked_impact_known:
            assert (
                self.impact.unmasked_cut_m3 is not None
                and self.impact.unmasked_fill_m3 is not None
                and self.impact.unmasked_net_m3 is not None
                and self.impact.excluded_cut_m3 is not None
                and self.impact.excluded_fill_m3 is not None
                and self.impact.excluded_net_m3 is not None
            )
            if not (
                math.isclose(
                    self.impact.excluded_cut_m3,
                    self.impact.unmasked_cut_m3 - self.metrics.cut_m3,
                    rel_tol=_FLOAT_REL_TOLERANCE,
                    abs_tol=_FLOAT_ABS_TOLERANCE,
                )
                and math.isclose(
                    self.impact.excluded_fill_m3,
                    self.impact.unmasked_fill_m3 - self.metrics.fill_m3,
                    rel_tol=_FLOAT_REL_TOLERANCE,
                    abs_tol=_FLOAT_ABS_TOLERANCE,
                )
                and math.isclose(
                    self.impact.excluded_net_m3,
                    self.impact.unmasked_net_m3 - self.metrics.net_m3,
                    rel_tol=_FLOAT_REL_TOLERANCE,
                    abs_tol=_FLOAT_ABS_TOLERANCE,
                )
            ):
                raise ValueError("excluded volumes must equal unmasked minus masked")
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


class MaskedVolumeCalculationReportV3(_FrozenMaskedResultModel):
    """Fenced worker report that wraps, but cannot alter, masked numeric content."""

    contract_version: Literal["external-masked-volume-calculation-report.v3"] = (
        "external-masked-volume-calculation-report.v3"
    )
    report_id: Text
    masked_calculation_identity_digest: Digest
    numeric_result: MaskedVolumeNumericResultV3
    numeric_result_identity_digest: Digest
    computed_at: datetime
    reported_at: datetime
    report_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_numeric_content_and_time(self) -> Self:
        self._require_utc(self.computed_at, "computedAt")
        self._require_utc(self.reported_at, "reportedAt")
        if self.computed_at > self.reported_at:
            raise ValueError("computedAt must be earlier than or equal to reportedAt")
        numeric = self.numeric_result
        if numeric.numeric_result_identity_digest is None or (
            numeric.numeric_result_identity_digest != numeric.canonical_digest()
        ):
            raise ValueError("numeric result must be sealed")
        if self.numeric_result_identity_digest != numeric.numeric_result_identity_digest:
            raise ValueError("numeric result identity does not bind numeric result")
        if numeric.masked_calculation_identity_digest != self.masked_calculation_identity_digest:
            raise ValueError("numeric result identity does not bind the masked calculation")
        if self.report_digest is not None and self.report_digest != self.canonical_digest():
            raise ValueError("report digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("report_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("report_digest")


class MaskedVolumeCalculationFailureV3(_FrozenMaskedResultModel):
    """A typed immutable attempt outcome that contains no partial numeric result."""

    contract_version: Literal["external-masked-volume-calculation-failure.v3"] = (
        "external-masked-volume-calculation-failure.v3"
    )
    failure_id: Text
    masked_calculation_identity_digest: Digest
    reason_code: Reason
    failed_at: datetime
    failure_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_exact_identity_and_timestamp(self) -> Self:
        self._require_utc(self.failed_at, "failedAt")
        if self.failure_digest is not None and self.failure_digest != self.canonical_digest():
            raise ValueError("failure digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("failure_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("failure_digest")


def _wire(model: _FrozenMaskedResultModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def masked_coverage_witness_wire_dict(witness: MaskedCoverageWitnessV3) -> dict[str, Any]:
    return _wire(witness.sealed())


def masked_volume_numeric_result_wire_dict(result: MaskedVolumeNumericResultV3) -> dict[str, Any]:
    return _wire(result.sealed())


def masked_volume_calculation_report_wire_dict(
    report: MaskedVolumeCalculationReportV3,
) -> dict[str, Any]:
    return _wire(report.sealed())


def masked_volume_calculation_failure_wire_dict(
    failure: MaskedVolumeCalculationFailureV3,
) -> dict[str, Any]:
    return _wire(failure.sealed())


__all__ = [
    "MaskedCoverageWitnessV3",
    "MaskedVolumeCalculationFailureV3",
    "MaskedVolumeCalculationReportV3",
    "MaskedVolumeImpactV3",
    "MaskedVolumeNumericResultV3",
    "masked_coverage_witness_wire_dict",
    "masked_volume_calculation_failure_wire_dict",
    "masked_volume_calculation_report_wire_dict",
    "masked_volume_numeric_result_wire_dict",
]
