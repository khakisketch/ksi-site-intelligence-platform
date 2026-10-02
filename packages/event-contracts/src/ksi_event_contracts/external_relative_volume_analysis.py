"""Frozen V2 suitability records for future external relative-volume calculation.

The contracts bind a *possible* calculation to its exact inputs and the
checkpoint evidence consulted by Core.  They deliberately contain no computed
volume: a measurement worker owns that later, separate record.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    Digest,
    ObservedVerticalReferenceV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import EvidenceCoreVerdict, ExternalEvidenceRecordV1
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.work_area import assert_polygon_is_usable

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class _FrozenAnalysisModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    def _payload(self, digest_field: str) -> dict[str, Any]:
        raw = self.model_dump(by_alias=True, mode="json")
        alias = self.__class__.model_fields[digest_field].alias or digest_field
        raw.pop(alias, None)
        return raw

    def _seal(self, digest_field: str) -> Self:
        return self.model_copy(update={digest_field: _digest(self._payload(digest_field))})

    @field_validator(
        "assessed_at",
        "baseline_capture_started_at",
        "baseline_capture_ended_at",
        "current_capture_started_at",
        "current_capture_ended_at",
        check_fields=False,
    )
    @classmethod
    def _requires_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("analysis timestamps must be UTC")
        return value


class AdmissionDispositionV2(StrEnum):
    ADMIT_PROVISIONAL = "ADMIT_PROVISIONAL"
    ADMIT_EVALUATED = "ADMIT_EVALUATED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    BLOCKED = "BLOCKED"


class EvaluationOutcomeV1(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNASSESSED = "UNASSESSED"
    UNAVAILABLE = "UNAVAILABLE"


class AnalysisPolicyV2(_FrozenAnalysisModel):
    """The first V2 profile's mathematical identity, without an execution result."""

    contract_version: Literal["external-relative-volume-analysis-policy.v2"] = (
        "external-relative-volume-analysis-policy.v2"
    )
    policy_id: Text
    version: StrictInt = Field(ge=1)
    profile_id: Literal["KSI-GIS-RELATIVE-VOLUME-V2"]
    profile_digest: Digest
    algorithm_digest: Digest
    config_digest: Digest
    baseline_grid_rule: Literal["BASELINE_NATIVE_NORTH_UP_AFFINE_V1"]
    current_elevation_resampling: Literal["BILINEAR"]
    current_mask_resampling: Literal["NEAREST"]
    work_area_rasterization: Literal["CELL_CENTER"]
    minimum_common_valid_fraction: StrictFloat
    threshold_m: StrictFloat
    cell_area_rule: Literal["ABSOLUTE_AFFINE_DETERMINANT"]
    delta_rule: Literal["CURRENT_MINUS_BASELINE"]
    uncertainty_method: Literal["NONE_UNCERTAINTY_M3_NULL_V1"]
    policy_digest: Digest | None = None

    @model_validator(mode="after")
    def _has_matching_digest(self) -> Self:
        if self.minimum_common_valid_fraction != 1.0:
            raise ValueError("first profile requires 100% common valid coverage")
        if self.threshold_m != 0.0:
            raise ValueError("first profile requires a zero threshold")
        if self.policy_digest is not None and self.policy_digest != self.canonical_digest():
            raise ValueError("policy digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("policy_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("policy_digest")


class CalculationIdentityV2(_FrozenAnalysisModel):
    """The immutable, non-numeric identity of one future worker calculation."""

    contract_version: Literal["external-relative-volume-calculation-identity.v2"] = (
        "external-relative-volume-calculation-identity.v2"
    )
    calculation_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    work_area_polygon: dict[str, Any]
    work_area_crs: Text
    work_area_definition_digest: Digest
    baseline_subject: SealedExternalSubjectV1
    current_subject: SealedExternalSubjectV1
    baseline_capture_started_at: datetime
    baseline_capture_ended_at: datetime
    current_capture_started_at: datetime
    current_capture_ended_at: datetime
    baseline_dsm_artifact_id: Text
    current_dsm_artifact_id: Text
    baseline_input_digest: Digest
    current_input_digest: Digest
    baseline_dsm_observed_sha256: Digest
    current_dsm_observed_sha256: Digest
    baseline_dsm_observed_size_bytes: StrictInt = Field(gt=0)
    current_dsm_observed_size_bytes: StrictInt = Field(gt=0)
    baseline_observed_crs_identifier: Text
    current_observed_crs_identifier: Text
    baseline_observed_crs_digest: Digest
    current_observed_crs_digest: Digest
    baseline_projected_unit: Literal["metre"]
    current_projected_unit: Literal["metre"]
    baseline_vertical_reference: ObservedVerticalReferenceV1
    current_vertical_reference: ObservedVerticalReferenceV1
    baseline_vertical_reference_digest: Digest
    current_vertical_reference_digest: Digest
    baseline_vertical_unit: Literal["metre"]
    current_vertical_unit: Literal["metre"]
    baseline_vertical_unit_provenance: Literal["OBSERVED_VERTICAL_CRS_AXIS"]
    current_vertical_unit_provenance: Literal["OBSERVED_VERTICAL_CRS_AXIS"]
    baseline_inspection_report_digest: Digest
    current_inspection_report_digest: Digest
    baseline_inspection_policy_digest: Digest
    current_inspection_policy_digest: Digest
    baseline_inspector_build_digest: Digest
    current_inspector_build_digest: Digest
    baseline_transform_digest: Digest
    current_transform_digest: Digest
    baseline_transform: tuple[
        StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat
    ]
    current_transform: tuple[
        StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat
    ]
    horizontal_crs_digest: Digest
    vertical_reference_digest: Digest
    policy: AnalysisPolicyV2
    worker_executable_digest: Digest
    worker_build_digest: Digest
    runtime_image_version: Text
    runtime_image_oci_digest: Digest
    dependency_lock_digest: Digest
    calculation_identity_digest: Digest | None = None

    @model_validator(mode="after")
    def _has_matching_identity(self) -> Self:
        assert_polygon_is_usable(self.work_area_polygon, crs=self.work_area_crs)
        if self.work_area_definition_digest != _digest(
            {
                "workAreaId": self.work_area_id,
                "crs": self.work_area_crs,
                "polygon": self.work_area_polygon,
            }
        ):
            raise ValueError("work area definition digest differs from its exact snapshot")
        if (
            self.policy.policy_digest is None
            or self.policy.policy_digest != self.policy.canonical_digest()
        ):
            raise ValueError("analysis policy must be sealed")
        if self.baseline_subject == self.current_subject:
            raise ValueError("analysis epochs require distinct sealed subjects")
        if self.baseline_capture_ended_at > self.current_capture_started_at:
            raise ValueError("baseline capture must end before current capture begins")
        if (
            self.baseline_transform_digest != _digest({"transform": list(self.baseline_transform)})
            or self.current_transform_digest != _digest({"transform": list(self.current_transform)})
        ):
            raise ValueError("transform digest differs from its exact affine")
        if (
            self.baseline_vertical_reference_digest
            != self.baseline_vertical_reference.canonical_digest()
            or self.current_vertical_reference_digest
            != self.current_vertical_reference.canonical_digest()
        ):
            raise ValueError("vertical reference digest differs from its exact observed reference")
        if (
            self.horizontal_crs_digest != self.baseline_observed_crs_digest
            or self.horizontal_crs_digest != self.current_observed_crs_digest
            or self.vertical_reference_digest != self.baseline_vertical_reference_digest
            or self.vertical_reference_digest != self.current_vertical_reference_digest
        ):
            raise ValueError("shared coordinate references differ from epoch provenance")
        if (
            self.calculation_identity_digest is not None
            and self.calculation_identity_digest != self.canonical_digest()
        ):
            raise ValueError("identity digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("calculation_identity_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("calculation_identity_digest")


class EvaluationEvidenceFactV1(_FrozenAnalysisModel):
    """One immutable terminal record bound to the exact criterion context used."""

    evidence_ref: Text
    context: ExternalEvidenceMeasurementContextV1
    terminal_record: ExternalEvidenceRecordV1

    @model_validator(mode="after")
    def _has_exact_context_binding(self) -> Self:
        record = self.terminal_record
        context = self.context
        if (
            context.context_digest is None
            or record.evidence_record_digest is None
            or record.evidence_manifest_digest != context.evidence_manifest_digest
            or record.target_dsm_observed_sha256 != context.target_dsm_observed_sha256
            or record.policy_digest != context.policy_digest
        ):
            raise ValueError("terminal record does not bind its exact criterion context")
        return self


class EvaluationV1(_FrozenAnalysisModel):
    """One immutable per-epoch evidence snapshot, separate from calculation output."""

    contract_version: Literal["external-relative-volume-evaluation.v1"] = (
        "external-relative-volume-evaluation.v1"
    )
    evaluation_id: Text
    calculation_identity_digest: Digest
    epoch: Literal["BASELINE", "CURRENT"]
    revision: StrictInt = Field(ge=1)
    subject: SealedExternalSubjectV1
    evidence_facts: tuple[EvaluationEvidenceFactV1, ...] = Field(max_length=64)
    outcome: EvaluationOutcomeV1
    reason_codes: tuple[Reason, ...] = Field(min_length=1, max_length=64)
    assessed_at: datetime
    evaluation_digest: Digest | None = None

    @model_validator(mode="after")
    def _has_exact_evidence_shape(self) -> Self:
        record_digests = tuple(
            item.terminal_record.evidence_record_digest for item in self.evidence_facts
        )
        if any(digest is None for digest in record_digests) or len(set(record_digests)) != len(
            record_digests
        ):
            raise ValueError("terminal record digests must be unique")
        if any(item.context.subject != self.subject for item in self.evidence_facts):
            raise ValueError("evaluation context does not bind its subject")
        if (
            self.outcome in {EvaluationOutcomeV1.PASS, EvaluationOutcomeV1.FAIL}
            and not self.evidence_facts
        ):
            raise ValueError("terminal evidence is required for a pass or failure")
        verdicts = {item.terminal_record.core_verdict for item in self.evidence_facts}
        if self.outcome is EvaluationOutcomeV1.PASS and (
            verdicts != {EvidenceCoreVerdict.VALIDATED}
            or any(item.context.independent_attestation is None for item in self.evidence_facts)
        ):
            raise ValueError("a passing evaluation requires independent validated terminal facts")
        if (
            self.outcome is EvaluationOutcomeV1.FAIL
            and EvidenceCoreVerdict.REJECTED not in verdicts
        ):
            raise ValueError("a failing evaluation requires a rejected terminal fact")
        if (
            self.outcome is EvaluationOutcomeV1.UNASSESSED
            and EvidenceCoreVerdict.REJECTED in verdicts
        ):
            raise ValueError("rejected terminal evidence cannot be classified as unassessed")
        if self.evaluation_digest is not None and self.evaluation_digest != self.canonical_digest():
            raise ValueError("evaluation digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("evaluation_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        return self._seal("evaluation_digest")


class AdmissionV2(_FrozenAnalysisModel):
    """A numeric-free suitability decision for a separately executed calculation."""

    contract_version: Literal["external-relative-volume-admission.v2"] = (
        "external-relative-volume-admission.v2"
    )
    admission_id: Text
    calculation_identity: CalculationIdentityV2 | None
    calculation_identity_digest: Digest | None = None
    evaluation_revisions: tuple[EvaluationV1, ...] = Field(max_length=2)
    disposition: AdmissionDispositionV2
    reason_codes: tuple[Reason, ...] = Field(min_length=1, max_length=64)
    assessed_at: datetime
    admission_digest: Digest | None = None

    @model_validator(mode="after")
    def _has_matching_bindings(self) -> Self:
        identity = self.calculation_identity
        if identity is None:
            if self.disposition is not AdmissionDispositionV2.BLOCKED:
                raise ValueError("only a blocked admission may lack a calculation identity")
            if self.calculation_identity_digest is not None or self.evaluation_revisions:
                raise ValueError("an unresolved blocked admission cannot bind evaluations")
            if (
                self.admission_digest is not None
                and self.admission_digest != self.canonical_digest()
            ):
                raise ValueError("admission digest differs from its exact content")
            return self
        if (
            identity.calculation_identity_digest is None
            or identity.calculation_identity_digest != identity.canonical_digest()
        ):
            raise ValueError("admission calculation identity must be sealed")
        if (
            self.calculation_identity_digest is not None
            and self.calculation_identity_digest != identity.calculation_identity_digest
        ):
            raise ValueError("admission calculation identity digest differs")
        evaluations = self.evaluation_revisions
        if len({(item.epoch, item.revision) for item in evaluations}) != len(evaluations):
            raise ValueError("evaluation epoch revisions must be unique")
        if any(
            item.calculation_identity_digest != identity.calculation_identity_digest
            or item.evaluation_digest is None
            or item.evaluation_digest != item.canonical_digest()
            for item in evaluations
        ):
            raise ValueError("admission evaluation does not bind the calculation identity")
        if evaluations:
            expected_subject = {
                "BASELINE": identity.baseline_subject,
                "CURRENT": identity.current_subject,
            }
            if {item.epoch for item in evaluations} != {"BASELINE", "CURRENT"} or any(
                item.subject != expected_subject[item.epoch] for item in evaluations
            ):
                raise ValueError("admission evaluation epoch or subject linkage is invalid")
            outcomes = {item.outcome for item in evaluations}
            expected_disposition = (
                AdmissionDispositionV2.REMEDIATION_REQUIRED
                if EvaluationOutcomeV1.FAIL in outcomes
                else AdmissionDispositionV2.BLOCKED
                if EvaluationOutcomeV1.UNAVAILABLE in outcomes
                else AdmissionDispositionV2.ADMIT_PROVISIONAL
                if EvaluationOutcomeV1.UNASSESSED in outcomes
                else AdmissionDispositionV2.ADMIT_EVALUATED
            )
            if self.disposition is not expected_disposition:
                raise ValueError("admission disposition does not match evaluation outcomes")
        elif self.disposition is AdmissionDispositionV2.ADMIT_EVALUATED:
            raise ValueError("evaluated admission requires both epoch evaluations")
        if self.admission_digest is not None and self.admission_digest != self.canonical_digest():
            raise ValueError("admission digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("admission_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        identity_digest = (
            self.calculation_identity.calculation_identity_digest
            if self.calculation_identity is not None
            else None
        )
        normalized = self.model_copy(
            update={"calculation_identity_digest": identity_digest, "admission_digest": None}
        )
        return normalized._seal("admission_digest")
