# SINGLE_VOLUME SV-1 Implementation Plan — contracts, algorithm, Core authority/decision

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a `SINGLE_VOLUME` use decision resolvable and ELIGIBLE on the real Core graph (policy → sealed subject → inspection → attested evidence → WorkArea zone → admitted single mapping), with the new contract family, JSON schemas and the boundary-base volume algorithm ready for SV-2.

**Architecture:** A new sealed contract family (`external-single-volume-*.v1`) sits beside the relative-volume family and never extends it. Core gains a single-binding compatibility record admitted into the existing `ExternalQuantitativeAuthorityCatalog` (two new journal kinds), a third decision candidate in `ExternalUseDecisionStore`, and `ExternalUseEvaluator.request_single_volume`. The volume math lives in `ksi_change_detection.external_single_volume` and reuses `measure_external_volume_zone` on a `DiffResult(dsm − base)`.

**Tech Stack:** Python 3.12, pydantic v2 (`CamelModel`), numpy, rasterio, scipy (`LinearNDInterpolator`), FastAPI, jsonschema (tests), `uv run --locked` for every command.

**Spec:** `docs/superpowers/specs/2026-09-17-single-volume-design.md` (Sections 4, 5, 6 are SV-1; Sections 7–9 are SV-2..SV-4).

## Global Constraints

- Never edit `external_relative_volume.py` contract models, their schemas, or the relative journal kinds; sealed digests must not change (spec §2, §3).
- Use code: `SINGLE_VOLUME`. Product label: `단일 시점 체적`.
- Uncertainty method literal: `SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1`; base method literal: `BOUNDARY_LINEAR_INTERPOLATION_V1`.
- New journal kinds: `external-quantitative-single-mapping-activated`, `external-quantitative-single-mapping-revoked` (execution kinds are SV-2).
- New blocker reason `SINGLE_VOLUME_MAPPING_UNAVAILABLE` → remediation `AUTHORIZE_SINGLE_VOLUME_MAPPING`; the blocker catalog and the dashboard copy must stay byte-identical (`tests/contract/test_external_use_blockers.py`).
- Evidence rigor equals relative volume: one Core-validated evidence record whose sealed context has `independent_attestation` (spec §2).
- Every command runs from the repo root with `uv run --locked …`; commits use `git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit` and end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Gates before the final commit: `uv run --locked ruff check .`, `uv run --locked ruff format --check .`, `uv run --locked mypy`, `uv run --locked pytest tests/contract tests/replay packages/change-detection/tests -q`.
- New `ksi_core` modules get a legacy alias shim under `services/core/src/ksi_core/<name>.py` exactly like `services/core/src/ksi_core/external_relative_volumes.py`.

---

## File structure

| File | Responsibility |
|---|---|
| `packages/event-contracts/src/ksi_event_contracts/external_single_volume.py` (create) | Decision, execution policy, request, metrics, payload, report models + wire helpers |
| `contracts/schemas/external-single-volume-{decision,execution-policy,request,report}.v1.json` (create) | Draft 2020-12 schemas for the sealed wire forms |
| `packages/change-detection/src/ksi_change_detection/external_single_volume.py` (create) | Boundary base surface + single-volume zone measurement |
| `packages/change-detection/src/ksi_change_detection/external_volume.py` (modify) | Two new error reasons |
| `services/core/src/ksi_core/domains/external/ingress/external_validation_policy.py` (modify) | `SINGLE_VOLUME` in the closed use catalogue, single-subject arity |
| `services/core/src/ksi_core/domains/external/quantity/external_use_decisions.py` (modify) | Third candidate type, intent shape, single-volume joins |
| `services/core/src/ksi_core/domains/external/quantity/external_single_volume_authority.py` (create) | `SingleVolumeCompatibilityRuleDescriptorV1`, `ExternalSingleVolumeCompatibilityRecord` |
| `services/core/src/ksi_core/domains/external/quantity/external_single_volume_authorities.py` (create) | `ExternalSingleVolumeAuthority` value, port protocol, default-closed port |
| `services/core/src/ksi_core/domains/external/quantity/external_quantitative_authority.py` (modify) | Single mapping admission/revocation/resolution, participants single snapshot, replay kinds |
| `services/core/src/ksi_core/domains/external/quantity/external_use_evaluator.py` (modify) | `request_single_volume`, history verification, reason map, route |
| `services/core/src/ksi_core/domains/external/authority/provider_loading.py`, `external_authority_provider.py` (modify) | `ADMIT_SINGLE_MAPPING` / `REVOKE_SINGLE_MAPPING` |
| `services/core/src/ksi_core/composition/external_graph.py` (modify) | Pass the catalog as the single-volume authority |
| `contracts/catalogs/external-use-blockers.v1.json`, `apps/dashboard/src/lib/external-use-blockers.generated.json` (modify) | New reason/remediation copy |
| `contracts/api/openapi-core.yaml` (modify) | `…/use-decisions/single-volume` |
| `services/core/src/ksi_core/external_single_volume_authority.py`, `external_single_volume_authorities.py` (create) | Legacy alias shims |
| Tests | `tests/contract/test_external_single_volume_contracts.py`, `packages/change-detection/tests/test_external_single_volume.py`, additions to `test_external_validation_policy.py`, `test_external_use_decisions.py`, `test_external_quantitative_authority.py`, `tests/replay/test_external_quantitative_authority_replay.py`, `test_external_use_evaluator.py`, `test_external_authority_provider_contract.py`, `test_external_use_blockers.py` (unchanged, must pass) |

---

### Task 1: Contract family `external-single-volume-*.v1`

**Files:**
- Create: `packages/event-contracts/src/ksi_event_contracts/external_single_volume.py`
- Create: `contracts/schemas/external-single-volume-decision.v1.json`
- Create: `contracts/schemas/external-single-volume-execution-policy.v1.json`
- Create: `contracts/schemas/external-single-volume-request.v1.json`
- Create: `contracts/schemas/external-single-volume-report.v1.json`
- Test: `tests/contract/test_external_single_volume_contracts.py`

**Interfaces:**
- Consumes: `SealedExternalSubjectV1`, `SealedZoneReferenceV1`, `DecisionVerdict`, `FactClass` from `ksi_event_contracts.external_artifact_validation`; `ExternalVolumeZoneSnapshotV1`, `ExternalVolumeInputBindingV1`, `ExternalVolumeMetricsV1`, `_FrozenExternalRelativeVolumeModel`, `_digest`, `_require_utc_datetime_wire_value`, `_require_utc`, `_BoundedText`, `_MAX_FINITE_FLOAT`, `_FLOAT_REL_TOLERANCE`, `_FLOAT_ABS_TOLERANCE` from `ksi_event_contracts.external_relative_volume`.
- Produces: `ExternalSingleVolumeDecisionV1`, `ExternalSingleVolumeExecutionPolicyV1`, `ExternalSingleVolumeRequestV1`, `ExternalSingleVolumeMetricsV1`, `ExternalSingleVolumeMeasurementPayloadV1`, `ExternalSingleVolumeReportV1`, `external_single_volume_decision_wire_dict`, `external_single_volume_execution_policy_wire_dict`, `external_single_volume_request_wire_dict`, `external_single_volume_report_wire_dict`. Every model has `canonical_payload()`, `canonical_digest()`, `sealed()`.

- [ ] **Step 1: Write the failing contract test**

```python
# tests/contract/test_external_single_volume_contracts.py
"""Immutable external single-volume contracts stay closed and fail closed."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from ksi_event_contracts.external_artifact_validation import DecisionVerdict, SealedExternalSubjectV1
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeDecisionV1,
    ExternalSingleVolumeExecutionPolicyV1,
    ExternalSingleVolumeMeasurementPayloadV1,
    ExternalSingleVolumeMetricsV1,
    ExternalSingleVolumeReportV1,
    ExternalSingleVolumeRequestV1,
    external_single_volume_decision_wire_dict,
    external_single_volume_execution_policy_wire_dict,
    external_single_volume_report_wire_dict,
    external_single_volume_request_wire_dict,
)
from pydantic import ValidationError

_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "contracts/schemas"
_NOW = datetime(2026, 9, 17, 1, 2, 3, tzinfo=UTC)


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _subject() -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=1,
        submission_digest=_digest("a"),
        manifest_digest=_digest("b"),
    )


def _zone() -> ExternalVolumeZoneSnapshotV1:
    return ExternalVolumeZoneSnapshotV1(
        organization_id="organization-1",
        site_id="site-1",
        work_area_id="zone-1",
        polygon={
            "type": "Polygon",
            "coordinates": [[[0.0, 2.0], [2.0, 2.0], [2.0, 0.0], [0.0, 0.0], [0.0, 2.0]]],
        },
        crs="EPSG:5186",
        observed_crs_digest=_digest("c"),
        analysis_vertical_reference_digest=_digest("d"),
    ).sealed()


def _binding() -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=_subject(),
        inspection_report_digest=_digest("e"),
        dsm_artifact_id="dsm-1",
        observed_sha256=_digest("f"),
        observed_size_bytes=64,
        observed_crs_digest=_digest("c"),
        observed_vertical_reference_digest=_digest("d"),
        captured_from=_NOW - timedelta(hours=2),
        captured_to=_NOW - timedelta(hours=1),
    )


def _policy() -> ExternalSingleVolumeExecutionPolicyV1:
    return ExternalSingleVolumeExecutionPolicyV1(
        policy_id="single-policy-1",
        version=1,
        algorithm_build_digest=_digest("1"),
        config_digest=_digest("2"),
        threshold_m=0.05,
        minimum_common_valid_fraction=0.9,
        minimum_boundary_valid_fraction=0.8,
        uncertainty_method="SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1",
        base_surface_method="BOUNDARY_LINEAR_INTERPOLATION_V1",
        resource_envelope_digest=_digest("3"),
        authority_record_digest=_digest("4"),
        synthetic_test_only=False,
    ).sealed()


def _decision(*, verdict: DecisionVerdict = DecisionVerdict.ELIGIBLE) -> ExternalSingleVolumeDecisionV1:
    eligible = verdict is not DecisionVerdict.BLOCKED
    return ExternalSingleVolumeDecisionV1(
        decision_id="decision-1",
        subject=_subject(),
        subject_digest=_subject().canonical_digest(),
        policy_digest=_digest("5") if eligible else None,
        inspection_report_digest=_digest("e") if eligible else None,
        evidence_record_digests=(_digest("6"),) if eligible else (),
        zone=_zone().to_zone_reference() if eligible else None,
        compatibility_mapping_digest=_digest("7") if eligible else None,
        verdict=verdict,
        reasons=("USE_ELIGIBLE",) if eligible else ("POLICY_UNAVAILABLE",),
        remediations=("CURRENT_DEPENDENCIES_RETAINED",) if eligible else ("AUTHORIZE_POLICY",),
        decided_at=_NOW,
    ).sealed()


def _request() -> ExternalSingleVolumeRequestV1:
    policy = _policy()
    assert policy.policy_digest is not None
    return ExternalSingleVolumeRequestV1(
        request_id="external-single-volume-1",
        current_work_order_id="work-order-1",
        decision_id="decision-1",
        decision_digest=_digest("8"),
        target=_binding(),
        evidence_record_digests=(_digest("6"),),
        validation_policy_digest=_digest("5"),
        execution_policy_digest=policy.policy_digest,
        zone_snapshot=_zone(),
        issued_at=_NOW,
        idempotency_key="key-1",
    ).sealed()


def _metrics() -> ExternalSingleVolumeMetricsV1:
    return ExternalSingleVolumeMetricsV1(
        zone_cell_count=36,
        common_valid_cell_count=36,
        zone_area_m2=36.0,
        measured_area_m2=36.0,
        common_valid_fraction=1.0,
        cut_m3=0.0,
        fill_m3=12.0,
        net_m3=12.0,
        threshold_m=0.0,
        uncertainty_m3=1.8,
        uncertainty_note="single epoch: area x hypot(dsm rmse, base roughness)",
        base_roughness_m=0.0,
        boundary_cell_count=20,
        boundary_sample_count=20,
        boundary_valid_fraction=1.0,
    )


def _report() -> ExternalSingleVolumeReportV1:
    request = _request()
    assert request.request_digest is not None
    payload = ExternalSingleVolumeMeasurementPayloadV1(
        request_digest=request.request_digest,
        decision_digest=request.decision_digest,
        target_dsm_digest=request.target.observed_sha256,
        zone_snapshot_digest=request.zone_snapshot.canonical_digest(),
        execution_policy_digest=request.execution_policy_digest,
        algorithm_build_digest=_digest("1"),
        config_digest=_digest("2"),
        metrics=_metrics(),
    )
    return ExternalSingleVolumeReportV1(
        report_id="report-1",
        request_id=request.request_id,
        request_digest=request.request_digest,
        payload=payload,
        worker_instance_id="0f5a0c7e-1c33-4a0e-9f4c-7e3a7d9e2b11",
        lease_acquisition_id="8d1b7c4a-6f2e-4b7d-a1c9-3e5f7a9b1d22",
        lease_generation=1,
        computed_at=_NOW,
        reported_at=_NOW,
    ).sealed()


@pytest.mark.parametrize(
    ("schema_name", "wire"),
    [
        ("external-single-volume-decision.v1.json", lambda: external_single_volume_decision_wire_dict(_decision())),
        ("external-single-volume-decision.v1.json", lambda: external_single_volume_decision_wire_dict(_decision(verdict=DecisionVerdict.BLOCKED))),
        ("external-single-volume-execution-policy.v1.json", lambda: external_single_volume_execution_policy_wire_dict(_policy())),
        ("external-single-volume-request.v1.json", lambda: external_single_volume_request_wire_dict(_request())),
        ("external-single-volume-report.v1.json", lambda: external_single_volume_report_wire_dict(_report())),
    ],
)
def test_sealed_wire_round_trips_against_its_schema(schema_name: str, wire: Callable[[], dict[str, Any]]) -> None:
    schema = json.loads((_SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    raw = wire()
    validator.validate(raw)
    raw["unexpected"] = 1
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(raw)


def test_decision_digest_is_stable_and_binds_subject() -> None:
    first, second = _decision(), _decision()
    assert first.decision_digest == second.decision_digest
    assert first.decision_digest == first.canonical_digest()
    with pytest.raises(ValidationError, match="subjectDigest"):
        _decision().model_copy(update={"subject_digest": _digest("9"), "decision_digest": None}, deep=True).sealed()


def test_eligible_decision_requires_zone_mapping_and_exactly_one_evidence_record() -> None:
    base = _decision()
    for update, message in (
        ({"zone": None}, "zone"),
        ({"compatibility_mapping_digest": None}, "compatibilityMappingDigest"),
        ({"evidence_record_digests": ()}, "exactly one"),
        ({"evidence_record_digests": (_digest("6"), _digest("7"))}, "exactly one"),
    ):
        with pytest.raises(ValidationError, match=message):
            base.model_copy(update={**update, "decision_digest": None}, deep=True).sealed()


def test_blocked_decision_forbids_mapping_and_zone() -> None:
    blocked = _decision(verdict=DecisionVerdict.BLOCKED)
    with pytest.raises(ValidationError, match="BLOCKED"):
        blocked.model_copy(update={"compatibility_mapping_digest": _digest("7"), "decision_digest": None}, deep=True).sealed()


def test_request_requires_one_evidence_record_and_target_bound_to_work_order() -> None:
    request = _request()
    with pytest.raises(ValidationError, match="exactly one"):
        request.model_copy(update={"evidence_record_digests": (), "request_digest": None}, deep=True).sealed()
    with pytest.raises(ValidationError, match="currentWorkOrderId"):
        request.model_copy(update={"current_work_order_id": "other", "request_digest": None}, deep=True).sealed()
    with pytest.raises(ValidationError, match="vertical"):
        request.model_copy(
            update={"target": _binding().model_copy(update={"observed_vertical_reference_digest": _digest("9")}), "request_digest": None},
            deep=True,
        ).sealed()


def test_metrics_bind_boundary_fraction_to_counts() -> None:
    with pytest.raises(ValidationError, match="boundaryValidFraction"):
        _metrics().model_copy(update={"boundary_valid_fraction": 0.5})
    with pytest.raises(ValidationError, match="boundarySampleCount"):
        _metrics().model_copy(update={"boundary_sample_count": 21})


def test_report_seals_payload_and_binds_request_digest() -> None:
    report = _report()
    assert report.measurement_payload_digest == report.payload.canonical_digest()
    assert report.report_digest == report.canonical_digest()
    with pytest.raises(ValidationError, match="requestDigest"):
        report.model_copy(update={"request_digest": _digest("0"), "report_digest": None, "measurement_payload_digest": None}, deep=True).sealed()
```

Note: pydantic's `model_copy` does not re-validate; the tests above that expect `ValidationError` from `model_copy(...)` on metrics must call `ExternalSingleVolumeMetricsV1.model_validate(_metrics().model_dump() | {...})` instead. Write them as:

```python
def test_metrics_bind_boundary_fraction_to_counts() -> None:
    body = _metrics().model_dump()
    with pytest.raises(ValidationError, match="boundaryValidFraction"):
        ExternalSingleVolumeMetricsV1.model_validate({**body, "boundary_valid_fraction": 0.5})
    with pytest.raises(ValidationError, match="boundarySampleCount"):
        ExternalSingleVolumeMetricsV1.model_validate({**body, "boundary_sample_count": 21})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --locked pytest tests/contract/test_external_single_volume_contracts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ksi_event_contracts.external_single_volume'`

- [ ] **Step 3: Write the contract module**

```python
# packages/event-contracts/src/ksi_event_contracts/external_single_volume.py
"""Sealed single-epoch (stockpile) volume contracts.

This family sits beside ``external_relative_volume`` and never extends it: a
single DSM epoch is measured against a base surface derived from the zone
boundary.  Models bind claims only; Core resolves eligibility and authority.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictFloat, StrictInt, field_validator, model_validator

from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    FactClass,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
)
from ksi_event_contracts.external_relative_volume import (
    _FLOAT_ABS_TOLERANCE,
    _FLOAT_REL_TOLERANCE,
    _MAX_FINITE_FLOAT,
    ExternalVolumeInputBindingV1,
    ExternalVolumeMetricsV1,
    ExternalVolumeZoneSnapshotV1,
    _BoundedText,
    _digest,
    _FrozenExternalRelativeVolumeModel,
    _require_utc,
    _require_utc_datetime_wire_value,
)

Digest = str  # sha256:<64 hex>; the schema pattern and Core validators enforce the form.
_Reason = str
_Remediation = str

SINGLE_VOLUME_USE = "SINGLE_VOLUME"
SINGLE_VOLUME_UNCERTAINTY_METHOD = "SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1"
SINGLE_VOLUME_BASE_SURFACE_METHOD = "BOUNDARY_LINEAR_INTERPOLATION_V1"


class ExternalSingleVolumeDecisionV1(_FrozenExternalRelativeVolumeModel):
    """Core's immutable single-subject SINGLE_VOLUME decision."""

    contract_version: Literal["external-single-volume-decision.v1"] = (
        "external-single-volume-decision.v1"
    )
    decision_id: _BoundedText
    subject: SealedExternalSubjectV1
    subject_digest: Digest
    use: Literal["SINGLE_VOLUME"] = "SINGLE_VOLUME"
    policy_digest: Digest | None = None
    inspection_report_digest: Digest | None = None
    evidence_record_digests: tuple[Digest, ...] = Field(max_length=64)
    zone: SealedZoneReferenceV1 | None = None
    compatibility_mapping_digest: Digest | None = None
    verdict: DecisionVerdict
    reasons: tuple[_Reason, ...] = Field(min_length=1, max_length=32)
    remediations: tuple[_Remediation, ...] = Field(min_length=1, max_length=32)
    decided_at: datetime
    decision_digest: Digest | None = None

    @field_validator("decided_at", mode="before")
    @classmethod
    def _decided_at_is_wire_value(cls, value: object) -> object:
        return _require_utc_datetime_wire_value(value, "decidedAt")

    @field_validator("decided_at")
    @classmethod
    def _decided_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "decidedAt")

    @model_validator(mode="after")
    def _binds_subject_and_use_specific_authority(self) -> ExternalSingleVolumeDecisionV1:
        if self.subject_digest != self.subject.canonical_digest():
            raise ValueError("subjectDigest must bind subject")
        if len(set(self.evidence_record_digests)) != len(self.evidence_record_digests):
            raise ValueError("evidenceRecordDigests must be unique")
        if self.verdict is DecisionVerdict.BLOCKED:
            if (
                self.compatibility_mapping_digest is not None
                or self.zone is not None
                or self.evidence_record_digests
            ):
                raise ValueError(
                    "BLOCKED SINGLE_VOLUME must not bind zone, mapping or evidence"
                )
        else:
            if self.policy_digest is None or self.inspection_report_digest is None:
                raise ValueError("non-BLOCKED decision requires policyDigest and inspectionReportDigest")
            if len(self.evidence_record_digests) != 1:
                raise ValueError("non-BLOCKED SINGLE_VOLUME requires exactly one evidence record")
            if self.zone is None:
                raise ValueError("non-BLOCKED SINGLE_VOLUME requires an exact zone")
            if self.compatibility_mapping_digest is None:
                raise ValueError("non-BLOCKED SINGLE_VOLUME requires compatibilityMappingDigest")
        if self.decision_digest is not None and (
            self.decision_digest != self._canonical_digest_unchecked()
        ):
            raise ValueError("decisionDigest does not match canonical single-volume decision")
        return self

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"decision_digest"})

    def canonical_payload(self) -> dict[str, Any]:
        return type(self).model_validate(self.__dict__)._canonical_payload_unchecked()

    def _canonical_digest_unchecked(self) -> str:
        return _digest(self._canonical_payload_unchecked())

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeDecisionV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"decision_digest": validated._canonical_digest_unchecked()}, deep=True
        )


class ExternalSingleVolumeExecutionPolicyV1(_FrozenExternalRelativeVolumeModel):
    """Versioned single-epoch execution limits; authority is always supplied."""

    contract_version: Literal["external-single-volume-execution-policy.v1"] = (
        "external-single-volume-execution-policy.v1"
    )
    policy_id: _BoundedText
    version: StrictInt = Field(ge=1)
    algorithm_build_digest: Digest
    config_digest: Digest
    threshold_m: StrictFloat = Field(ge=0.0, le=_MAX_FINITE_FLOAT)
    minimum_common_valid_fraction: StrictFloat = Field(gt=0.0, le=1.0)
    minimum_boundary_valid_fraction: StrictFloat = Field(gt=0.0, le=1.0)
    uncertainty_method: Literal["SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1"]
    base_surface_method: Literal["BOUNDARY_LINEAR_INTERPOLATION_V1"]
    resource_envelope_digest: Digest
    authority_record_digest: Digest
    synthetic_test_only: StrictBool
    policy_digest: Digest | None = None

    @model_validator(mode="after")
    def _finite_numbers_and_matching_digest(self) -> ExternalSingleVolumeExecutionPolicyV1:
        if not all(
            math.isfinite(value)
            for value in (
                self.threshold_m,
                self.minimum_common_valid_fraction,
                self.minimum_boundary_valid_fraction,
            )
        ):
            raise ValueError("execution policy numeric values must be finite")
        if self.policy_digest is not None and self.policy_digest != self._canonical_digest_unchecked():
            raise ValueError("policyDigest does not match canonical execution policy")
        return self

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"policy_digest"})

    def canonical_payload(self) -> dict[str, Any]:
        return type(self).model_validate(self.__dict__)._canonical_payload_unchecked()

    def _canonical_digest_unchecked(self) -> str:
        return _digest(self._canonical_payload_unchecked())

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeExecutionPolicyV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"policy_digest": validated._canonical_digest_unchecked()}, deep=True
        )


class ExternalSingleVolumeRequestV1(_FrozenExternalRelativeVolumeModel):
    """Core-issued single-epoch intent; binds claims, declares no eligibility."""

    contract_version: Literal["external-single-volume-request.v1"] = (
        "external-single-volume-request.v1"
    )
    request_id: _BoundedText
    current_work_order_id: _BoundedText
    decision_id: _BoundedText
    decision_digest: Digest
    target: ExternalVolumeInputBindingV1
    evidence_record_digests: tuple[Digest, ...] = Field(min_length=1, max_length=1)
    validation_policy_digest: Digest
    execution_policy_digest: Digest
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    issued_at: datetime
    idempotency_key: _BoundedText
    request_digest: Digest | None = None

    @field_validator("issued_at", mode="before")
    @classmethod
    def _issued_at_is_wire_value(cls, value: object) -> object:
        return _require_utc_datetime_wire_value(value, "issuedAt")

    @field_validator("issued_at")
    @classmethod
    def _issued_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "issuedAt")

    @model_validator(mode="after")
    def _binds_one_site_and_compatible_input(self) -> ExternalSingleVolumeRequestV1:
        subject, zone = self.target.subject, self.zone_snapshot
        if len(self.evidence_record_digests) != 1:
            raise ValueError("evidenceRecordDigests must carry exactly one record")
        if subject.work_order_id != self.current_work_order_id:
            raise ValueError("target.subject.workOrderId must equal currentWorkOrderId")
        if subject.organization_id != zone.organization_id or subject.site_id != zone.site_id:
            raise ValueError("target and zone must share organizationId and siteId")
        if self.target.observed_crs_digest != zone.observed_crs_digest:
            raise ValueError("target DSM observedCrsDigest must match zone observedCrsDigest")
        if self.target.observed_vertical_reference_digest != zone.analysis_vertical_reference_digest:
            raise ValueError("target DSM vertical reference must match zone analysis vertical reference")
        if zone.definition_digest != zone.sealed().definition_digest:
            raise ValueError("zoneSnapshot must carry its canonical definitionDigest")
        if self.request_digest is not None and self.request_digest != self._canonical_digest_unchecked():
            raise ValueError("requestDigest does not match canonical single-volume request")
        return self

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"request_digest"})

    def canonical_payload(self) -> dict[str, Any]:
        return type(self).model_validate(self.__dict__)._canonical_payload_unchecked()

    def _canonical_digest_unchecked(self) -> str:
        return _digest(self._canonical_payload_unchecked())

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeRequestV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"request_digest": validated._canonical_digest_unchecked()}, deep=True
        )


class ExternalSingleVolumeMetricsV1(ExternalVolumeMetricsV1):
    """Relative metrics plus the boundary-base facts that bound them."""

    base_roughness_m: StrictFloat = Field(ge=0.0, le=_MAX_FINITE_FLOAT)
    boundary_cell_count: StrictInt = Field(gt=0)
    boundary_sample_count: StrictInt = Field(ge=3)
    boundary_valid_fraction: StrictFloat = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _boundary_facts_are_consistent(self) -> ExternalSingleVolumeMetricsV1:
        if not math.isfinite(self.base_roughness_m):
            raise ValueError("baseRoughnessM must be finite")
        if self.boundary_sample_count > self.boundary_cell_count:
            raise ValueError("boundarySampleCount cannot exceed boundaryCellCount")
        expected = self.boundary_sample_count / self.boundary_cell_count
        if not math.isclose(
            self.boundary_valid_fraction, expected,
            rel_tol=_FLOAT_REL_TOLERANCE, abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError("boundaryValidFraction must match boundarySampleCount / boundaryCellCount")
        return self


class ExternalSingleVolumeMeasurementPayloadV1(_FrozenExternalRelativeVolumeModel):
    """Deterministic observed measurement content, excluding worker and fence facts."""

    fact_class: Literal[FactClass.OBSERVED] = FactClass.OBSERVED
    request_digest: Digest
    decision_digest: Digest
    target_dsm_digest: Digest
    zone_snapshot_digest: Digest
    execution_policy_digest: Digest
    algorithm_build_digest: Digest
    config_digest: Digest
    metrics: ExternalSingleVolumeMetricsV1

    def canonical_payload(self) -> dict[str, Any]:
        return type(self).model_validate(self.__dict__).model_dump(by_alias=True, mode="json")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())


class ExternalSingleVolumeReportV1(_FrozenExternalRelativeVolumeModel):
    """Fenced worker report whose payload is independently canonicalized."""

    contract_version: Literal["external-single-volume-report.v1"] = (
        "external-single-volume-report.v1"
    )
    report_id: _BoundedText
    request_id: _BoundedText
    request_digest: Digest
    payload: ExternalSingleVolumeMeasurementPayloadV1
    measurement_payload_digest: Digest | None = None
    worker_instance_id: _BoundedText
    lease_acquisition_id: _BoundedText
    lease_generation: StrictInt = Field(ge=1)
    computed_at: datetime
    reported_at: datetime
    report_digest: Digest | None = None

    @field_validator("computed_at", "reported_at", mode="before")
    @classmethod
    def _timestamps_are_wire_values(cls, value: object, info: Any) -> object:
        return _require_utc_datetime_wire_value(value, info.field_name)

    @field_validator("computed_at", "reported_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _require_utc(value, info.field_name)

    @field_validator("worker_instance_id", "lease_acquisition_id")
    @classmethod
    def _lease_identifiers_are_uuid4(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError("worker and lease identifiers must be canonical UUIDv4 strings") from exc
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("worker and lease identifiers must be canonical UUIDv4 strings")
        return value

    @model_validator(mode="after")
    def _binds_payload_request_and_fence_order(self) -> ExternalSingleVolumeReportV1:
        if self.computed_at > self.reported_at:
            raise ValueError("computedAt must be earlier than or equal to reportedAt")
        if self.payload.request_digest != self.request_digest:
            raise ValueError("payload.requestDigest must match requestDigest")
        if self.measurement_payload_digest is not None and (
            self.measurement_payload_digest != self.payload.canonical_digest()
        ):
            raise ValueError("measurementPayloadDigest does not match canonical payload")
        if self.report_digest is not None and self.report_digest != self._canonical_digest_unchecked():
            raise ValueError("reportDigest does not match canonical single-volume report")
        return self

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"report_digest"})

    def canonical_payload(self) -> dict[str, Any]:
        return type(self).model_validate(self.__dict__)._canonical_payload_unchecked()

    def _canonical_digest_unchecked(self) -> str:
        return _digest(self._canonical_payload_unchecked())

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeReportV1:
        validated = type(self).model_validate(self.__dict__)
        with_payload = validated.model_copy(
            update={"measurement_payload_digest": validated.payload.canonical_digest()}, deep=True
        )
        return with_payload.model_copy(
            update={"report_digest": with_payload._canonical_digest_unchecked()}, deep=True
        )


def _wire(model: _FrozenExternalRelativeVolumeModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def external_single_volume_decision_wire_dict(decision: ExternalSingleVolumeDecisionV1) -> dict[str, Any]:
    return _wire(decision.sealed())


def external_single_volume_execution_policy_wire_dict(policy: ExternalSingleVolumeExecutionPolicyV1) -> dict[str, Any]:
    return _wire(policy.sealed())


def external_single_volume_request_wire_dict(request: ExternalSingleVolumeRequestV1) -> dict[str, Any]:
    return _wire(request.sealed())


def external_single_volume_report_wire_dict(report: ExternalSingleVolumeReportV1) -> dict[str, Any]:
    return _wire(report.sealed())


__all__ = [
    "SINGLE_VOLUME_BASE_SURFACE_METHOD",
    "SINGLE_VOLUME_UNCERTAINTY_METHOD",
    "SINGLE_VOLUME_USE",
    "ExternalSingleVolumeDecisionV1",
    "ExternalSingleVolumeExecutionPolicyV1",
    "ExternalSingleVolumeMeasurementPayloadV1",
    "ExternalSingleVolumeMetricsV1",
    "ExternalSingleVolumeReportV1",
    "ExternalSingleVolumeRequestV1",
    "external_single_volume_decision_wire_dict",
    "external_single_volume_execution_policy_wire_dict",
    "external_single_volume_report_wire_dict",
    "external_single_volume_request_wire_dict",
]
```

If `Digest` in `external_relative_volume.py` is an `Annotated` alias (check `grep -n "^Digest\|Digest =" packages/event-contracts/src/ksi_event_contracts/external_relative_volume.py external_artifact_validation.py`), import that alias instead of the plain `str` above so the sha256 pattern is enforced by pydantic too.

- [ ] **Step 4: Write the four JSON schemas**

`contracts/schemas/external-single-volume-decision.v1.json` — copy `external-pair-use-decision.v1.json` and change: `$id`, `title: "ExternalSingleVolumeDecisionV1"`, `required` = `["contractVersion","decisionId","subject","subjectDigest","use","policyDigest","inspectionReportDigest","evidenceRecordDigests","zone","compatibilityMappingDigest","verdict","reasons","remediations","decidedAt","decisionDigest"]`, properties: `contractVersion const "external-single-volume-decision.v1"`, `subject`, `subjectDigest`, `use: {"const": "SINGLE_VOLUME"}`, `policyDigest`/`inspectionReportDigest`/`compatibilityMappingDigest` = `oneOf digest|null`, `evidenceRecordDigests: {"type":"array","maxItems":1,"items":{"$ref":"#/$defs/digest"}}`, `zone: oneOf zone|null`; `allOf` rule: when `verdict` ∈ `[ELIGIBLE, RESTRICTED]` then `compatibilityMappingDigest` is a digest and `zone` is `#/$defs/zone` and `evidenceRecordDigests.minItems = 1`, else all three null/empty (`maxItems: 0`). Keep the `$defs` (`text`, `digest`, `codes`, `utcDateTime`, `zone`, `subject`) verbatim from the pair schema.

`contracts/schemas/external-single-volume-execution-policy.v1.json` — copy the relative execution policy schema; change `$id`, title `External Single Volume Execution Policy v1`, `contractVersion const "external-single-volume-execution-policy.v1"`, add required+properties `minimumBoundaryValidFraction: {"type":"number","exclusiveMinimum":0,"maximum":1}`, `uncertaintyMethod: {"const":"SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1"}`, `baseSurfaceMethod: {"const":"BOUNDARY_LINEAR_INTERPOLATION_V1"}`.

`contracts/schemas/external-single-volume-request.v1.json` — copy the relative request schema; change `$id`, title, `contractVersion const "external-single-volume-request.v1"`; replace `baseline`/`current` with `target: {"$ref":"#/$defs/inputBinding"}`; `evidenceRecordDigests: {"type":"array","minItems":1,"maxItems":1,"items":{"$ref":"#/$defs/digest"}}`; required = `["contractVersion","requestId","currentWorkOrderId","decisionId","decisionDigest","target","evidenceRecordDigests","validationPolicyDigest","executionPolicyDigest","zoneSnapshot","issuedAt","idempotencyKey","requestDigest"]`. Keep `$defs` verbatim.

`contracts/schemas/external-single-volume-report.v1.json` — copy the relative report schema; change `$id`, title, `contractVersion const "external-single-volume-report.v1"`; in `$defs.payload` replace `baselineDsmDigest`/`currentDsmDigest` with `targetDsmDigest` (required list updated); in `$defs.metrics` add to required+properties `baseRoughnessM: {"type":"number","minimum":0,"maximum":1e300}`, `boundaryCellCount: {"type":"integer","minimum":1}`, `boundarySampleCount: {"type":"integer","minimum":3}`, `boundaryValidFraction: {"type":"number","exclusiveMinimum":0,"maximum":1}`.

Validate each with `uv run --locked python -c "import json,sys; from jsonschema import Draft202012Validator as V; [V.check_schema(json.load(open(p))) for p in sys.argv[1:]]" contracts/schemas/external-single-volume-*.json`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --locked pytest tests/contract/test_external_single_volume_contracts.py -q`
Expected: PASS (11 tests). If the UUID validator rejects the fixture ids, replace them with `str(uuid.uuid4())` computed once at module import.

- [ ] **Step 6: Commit**

```bash
git add packages/event-contracts/src/ksi_event_contracts/external_single_volume.py contracts/schemas/external-single-volume-*.json tests/contract/test_external_single_volume_contracts.py
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "feat(contracts): external single-volume decision/request/report family (SV-1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Boundary base surface and single-volume measurement

**Files:**
- Create: `packages/change-detection/src/ksi_change_detection/external_single_volume.py`
- Modify: `packages/change-detection/src/ksi_change_detection/external_volume.py` (enum members)
- Test: `packages/change-detection/tests/test_external_single_volume.py`

**Interfaces:**
- Consumes: `measure_external_volume_zone`, `_full_window`, `_masked_full_zone`, `_validate_diff_grid`, `_error`, `ExternalVolumeMeasurementError`, `ExternalVolumeMeasurementErrorReason` from `external_volume`; `DiffResult`, `_same_frame` from `dsm_diff`; `ExternalSingleVolumeMetricsV1` from Task 1.
- Produces:
  - `BoundaryBaseSurface(base_m, valid, row_start, col_start, boundary_cell_count, boundary_sample_count, boundary_valid_fraction, base_roughness_m)`
  - `derive_boundary_base_surface(dsm_m, valid, *, transform, crs, polygon_geojson, from_crs, minimum_boundary_valid_fraction, maximum_zone_grid_cells) -> BoundaryBaseSurface | ExternalVolumeMeasurementError`
  - `ExternalSingleVolumeZoneMeasurement(zone_id, metrics: ExternalSingleVolumeMetricsV1)`
  - `measure_single_volume_zone(dsm_m, valid, *, transform, crs, cell_area_m2, polygon_geojson, zone_id, from_crs, threshold_m, minimum_common_valid_fraction, minimum_boundary_valid_fraction, maximum_zone_grid_cells, uncertainty_note, dsm_rmse_m) -> ExternalSingleVolumeZoneMeasurement | ExternalVolumeMeasurementError`
  - New enum members `INSUFFICIENT_BOUNDARY_COVERAGE`, `BOUNDARY_SAMPLES_INSUFFICIENT`.

- [ ] **Step 1: Write the failing algorithm tests**

```python
# packages/change-detection/tests/test_external_single_volume.py
"""Boundary-base single-epoch volume with hand-derived grids."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from ksi_change_detection.external_single_volume import (
    ExternalSingleVolumeZoneMeasurement,
    derive_boundary_base_surface,
    measure_single_volume_zone,
)
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    ExternalVolumeMeasurementErrorReason,
)
from rasterio.transform import from_origin

# 8x8 metre grid, origin top-left (0, 8); zone covers cells rows/cols 1..6 (x,y in 1..7).
_TRANSFORM = from_origin(0.0, 8.0, 1.0, 1.0)
_ZONE: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[1.0, 7.0], [7.0, 7.0], [7.0, 1.0], [1.0, 1.0], [1.0, 7.0]]],
}


def _ground(*, slope_x: float = 0.0) -> np.ndarray:
    cols = np.arange(8, dtype=np.float64) + 0.5
    return 10.0 + slope_x * np.broadcast_to(cols, (8, 8)).copy()


def _with_box(ground: np.ndarray, height: float) -> np.ndarray:
    dsm = ground.copy()
    dsm[3:5, 3:5] += height  # 2x2 cells, 1 m² each
    return dsm


def _measure(dsm: np.ndarray, valid: np.ndarray | None = None, **overrides: Any):
    arguments: dict[str, Any] = {
        "transform": _TRANSFORM,
        "crs": "EPSG:5186",
        "cell_area_m2": 1.0,
        "polygon_geojson": _ZONE,
        "zone_id": "zone-1",
        "from_crs": "EPSG:5186",
        "threshold_m": 0.0,
        "minimum_common_valid_fraction": 1.0,
        "minimum_boundary_valid_fraction": 0.5,
        "maximum_zone_grid_cells": 64,
        "uncertainty_note": "single epoch: area x hypot(dsm rmse, base roughness)",
        "dsm_rmse_m": 0.05,
    }
    arguments.update(overrides)
    return measure_single_volume_zone(
        dsm, np.ones(dsm.shape, dtype=np.bool_) if valid is None else valid, **arguments
    )


def test_box_on_flat_ground_reproduces_its_volume_with_zero_roughness() -> None:
    measured = _measure(_with_box(_ground(), 3.0))
    assert isinstance(measured, ExternalSingleVolumeZoneMeasurement)
    metrics = measured.metrics
    assert metrics.zone_cell_count == 36
    assert metrics.boundary_cell_count == 20
    assert metrics.boundary_sample_count == 20
    assert metrics.fill_m3 == pytest.approx(12.0)
    assert metrics.cut_m3 == pytest.approx(0.0)
    assert metrics.base_roughness_m == pytest.approx(0.0, abs=1e-9)
    assert metrics.uncertainty_m3 == pytest.approx(36.0 * 0.05)


def test_box_on_sloped_plane_is_measured_against_the_reproduced_plane() -> None:
    """Linear interpolation of a plane's boundary reproduces the plane exactly."""
    measured = _measure(_with_box(_ground(slope_x=0.5), 3.0))
    assert isinstance(measured, ExternalSingleVolumeZoneMeasurement)
    assert measured.metrics.fill_m3 == pytest.approx(12.0, abs=1e-9)
    assert measured.metrics.cut_m3 == pytest.approx(0.0, abs=1e-9)
    assert measured.metrics.base_roughness_m == pytest.approx(0.0, abs=1e-9)


def test_pit_below_ground_is_cut_not_fill() -> None:
    measured = _measure(_with_box(_ground(), -3.0))
    assert isinstance(measured, ExternalSingleVolumeZoneMeasurement)
    assert measured.metrics.cut_m3 == pytest.approx(12.0)
    assert measured.metrics.fill_m3 == pytest.approx(0.0)
    assert measured.metrics.net_m3 == pytest.approx(-12.0)


def test_rough_boundary_raises_uncertainty_through_base_roughness() -> None:
    dsm = _with_box(_ground(), 3.0)
    dsm[1, 1:7] += 0.2  # top boundary row bumped 20 cm
    measured = _measure(dsm)
    assert isinstance(measured, ExternalSingleVolumeZoneMeasurement)
    assert measured.metrics.base_roughness_m > 0.0
    assert measured.metrics.uncertainty_m3 == pytest.approx(
        36.0 * float(np.hypot(0.05, measured.metrics.base_roughness_m))
    )


def test_nodata_boundary_below_policy_fraction_fails_closed() -> None:
    dsm = _with_box(_ground(), 3.0)
    valid = np.ones(dsm.shape, dtype=np.bool_)
    valid[1, 1:7] = False  # 6 of 20 boundary cells
    valid[6, 1:7] = False  # 12 of 20 -> fraction 0.4 < 0.5
    measured = _measure(dsm, valid)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.INSUFFICIENT_BOUNDARY_COVERAGE


def test_interior_nodata_is_unknown_not_zero_and_fails_full_coverage() -> None:
    dsm = _with_box(_ground(), 3.0)
    valid = np.ones(dsm.shape, dtype=np.bool_)
    valid[3, 3] = False
    measured = _measure(dsm, valid)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE
    assert measured.common_valid_cell_count == 35


def test_zone_outside_raster_and_oversized_zone_reuse_typed_errors() -> None:
    outside = {"type": "Polygon", "coordinates": [[[20.0, 22.0], [22.0, 22.0], [22.0, 20.0], [20.0, 20.0], [20.0, 22.0]]]}
    measured = _measure(_ground(), polygon_geojson=outside)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.INSUFFICIENT_BOUNDARY_COVERAGE
    oversized = _measure(_ground(), maximum_zone_grid_cells=10)
    assert isinstance(oversized, ExternalVolumeMeasurementError)
    assert oversized.reason is ExternalVolumeMeasurementErrorReason.OVERSIZED_ZONE


def test_collinear_boundary_samples_are_insufficient() -> None:
    dsm = _ground()
    valid = np.zeros(dsm.shape, dtype=np.bool_)
    valid[1, 1:7] = True  # only the top row of the ring is valid: collinear
    surface = derive_boundary_base_surface(
        dsm, valid, transform=_TRANSFORM, crs="EPSG:5186", polygon_geojson=_ZONE,
        from_crs="EPSG:5186", minimum_boundary_valid_fraction=0.1, maximum_zone_grid_cells=64,
    )
    assert isinstance(surface, ExternalVolumeMeasurementError)
    assert surface.reason is ExternalVolumeMeasurementErrorReason.BOUNDARY_SAMPLES_INSUFFICIENT


def test_measurement_is_deterministic() -> None:
    dsm = _with_box(_ground(slope_x=0.25), 1.5)
    dsm[2, 4] += 0.3
    first, second = _measure(dsm), _measure(dsm)
    assert isinstance(first, ExternalSingleVolumeZoneMeasurement)
    assert isinstance(second, ExternalSingleVolumeZoneMeasurement)
    assert first.metrics.model_dump() == second.metrics.model_dump()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest packages/change-detection/tests/test_external_single_volume.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ksi_change_detection.external_single_volume'`

- [ ] **Step 3: Add the two error reasons**

In `packages/change-detection/src/ksi_change_detection/external_volume.py`, extend the enum:

```python
class ExternalVolumeMeasurementErrorReason(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_ZONE = "INVALID_ZONE"
    EMPTY_ZONE = "EMPTY_ZONE"
    OVERSIZED_ZONE = "OVERSIZED_ZONE"
    EMPTY_COMMON_VALID_COVERAGE = "EMPTY_COMMON_VALID_COVERAGE"
    INSUFFICIENT_COMMON_VALID_COVERAGE = "INSUFFICIENT_COMMON_VALID_COVERAGE"
    INSUFFICIENT_BOUNDARY_COVERAGE = "INSUFFICIENT_BOUNDARY_COVERAGE"
    BOUNDARY_SAMPLES_INSUFFICIENT = "BOUNDARY_SAMPLES_INSUFFICIENT"
```

- [ ] **Step 4: Write the algorithm module**

```python
# packages/change-detection/src/ksi_change_detection/external_single_volume.py
"""Single-epoch (stockpile) volume against a boundary-derived base surface.

Import-only, no durable authority.  The base surface is the linear
interpolation of the DSM elevation sampled on the zone boundary ring; cells
the interpolation cannot reach are unknown, never zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeMetricsV1
from ksi_event_contracts.work_area import assert_polygon_is_usable
from ksi_geo_spatial.crs import assert_supported_project_crs, normalise_crs, reproject_geometry
from rasterio.transform import Affine
from scipy.interpolate import LinearNDInterpolator

from ksi_change_detection.dsm_diff import DiffResult, _same_frame
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    ExternalVolumeMeasurementErrorReason,
    _error,
    _full_window,
    _masked_full_zone,
    measure_external_volume_zone,
)


@dataclass(frozen=True, slots=True)
class BoundaryBaseSurface:
    """Base elevations on the zone window grid plus the boundary facts behind them."""

    base_m: np.ndarray
    valid: np.ndarray
    row_start: int
    col_start: int
    boundary_cell_count: int
    boundary_sample_count: int
    boundary_valid_fraction: float
    base_roughness_m: float


@dataclass(frozen=True, slots=True)
class ExternalSingleVolumeZoneMeasurement:
    zone_id: str
    metrics: ExternalSingleVolumeMetricsV1


def _grid_geometry(
    polygon_geojson: dict[str, Any], *, from_crs: str, grid_crs: str
) -> dict[str, Any] | ExternalVolumeMeasurementError:
    try:
        source = normalise_crs(from_crs)
        target = assert_supported_project_crs(grid_crs)
        assert_polygon_is_usable(polygon_geojson, crs=source)
        geometry = (
            polygon_geojson
            if _same_frame(source, target)
            else reproject_geometry(polygon_geojson, from_crs=source, to_crs=target)
        )
        assert_polygon_is_usable(geometry, crs=target)
        return geometry
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_ZONE,
            f"zone geometry is invalid or cannot be projected: {exc}",
        )


def _boundary_ring(zone: np.ndarray) -> np.ndarray:
    """Zone cells with at least one 4-neighbour outside the zone."""
    padded = np.pad(zone, 1, constant_values=False)
    interior = (
        zone
        & padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
    )
    return zone & ~interior


def derive_boundary_base_surface(
    dsm_m: np.ndarray,
    valid: np.ndarray,
    *,
    transform: Affine,
    crs: str,
    polygon_geojson: dict[str, Any],
    from_crs: str,
    minimum_boundary_valid_fraction: float,
    maximum_zone_grid_cells: int,
) -> BoundaryBaseSurface | ExternalVolumeMeasurementError:
    if (
        not isinstance(dsm_m, np.ndarray)
        or not isinstance(valid, np.ndarray)
        or dsm_m.ndim != 2
        or valid.shape != dsm_m.shape
        or valid.dtype != np.dtype(np.bool_)
    ):
        return _error(ExternalVolumeMeasurementErrorReason.INVALID_INPUT, "dsm and valid must be equal-shape 2D arrays")
    if not (0.0 < float(minimum_boundary_valid_fraction) <= 1.0):
        return _error(ExternalVolumeMeasurementErrorReason.INVALID_INPUT, "minimum_boundary_valid_fraction must be in (0, 1]")
    geometry = _grid_geometry(polygon_geojson, from_crs=from_crs, grid_crs=crs)
    if isinstance(geometry, ExternalVolumeMeasurementError):
        return geometry
    window = _full_window(geometry, transform, maximum_zone_grid_cells)
    if isinstance(window, ExternalVolumeMeasurementError):
        return window
    row_start, row_stop, col_start, col_stop = window
    zone = _masked_full_zone(
        geometry, transform=transform, row_start=row_start, row_stop=row_stop,
        col_start=col_start, col_stop=col_stop,
    )
    if isinstance(zone, ExternalVolumeMeasurementError):
        return zone
    if not zone.any():
        return _error(ExternalVolumeMeasurementErrorReason.EMPTY_ZONE, "zone selects no grid cell centers")

    # DSM validity on the window grid; cells outside the raster stay invalid.
    window_valid = np.zeros(zone.shape, dtype=np.bool_)
    window_dsm = np.zeros(zone.shape, dtype=np.float64)
    r0, r1 = max(0, row_start), min(dsm_m.shape[0], row_stop)
    c0, c1 = max(0, col_start), min(dsm_m.shape[1], col_stop)
    if r0 < r1 and c0 < c1:
        window_valid[r0 - row_start : r1 - row_start, c0 - col_start : c1 - col_start] = valid[r0:r1, c0:c1]
        window_dsm[r0 - row_start : r1 - row_start, c0 - col_start : c1 - col_start] = dsm_m[r0:r1, c0:c1]

    ring = _boundary_ring(zone)
    boundary_cell_count = int(ring.sum())
    samples = ring & window_valid
    boundary_sample_count = int(samples.sum())
    boundary_valid_fraction = boundary_sample_count / boundary_cell_count
    if boundary_valid_fraction < minimum_boundary_valid_fraction:
        return _error(
            ExternalVolumeMeasurementErrorReason.INSUFFICIENT_BOUNDARY_COVERAGE,
            "valid boundary elevation coverage is below the supplied policy minimum",
            zone_cell_count=int(zone.sum()),
        )
    rows, cols = np.nonzero(samples)  # row-major order: deterministic
    xs, ys = transform * (cols + col_start + 0.5, rows + row_start + 0.5)
    points = np.column_stack((np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)))
    z = window_dsm[rows, cols]
    centered = points - points.mean(axis=0)
    if boundary_sample_count < 3 or np.linalg.matrix_rank(centered, tol=1e-9) < 2:
        return _error(
            ExternalVolumeMeasurementErrorReason.BOUNDARY_SAMPLES_INSUFFICIENT,
            "boundary samples must span a plane (at least three non-collinear cells)",
        )
    design = np.column_stack((points, np.ones(boundary_sample_count)))
    coefficients, *_ = np.linalg.lstsq(design, z, rcond=None)
    residual = z - design @ coefficients
    base_roughness_m = float(math.sqrt(float(np.mean(residual * residual))))

    zone_rows, zone_cols = np.nonzero(zone)
    zx, zy = transform * (zone_cols + col_start + 0.5, zone_rows + row_start + 0.5)
    interpolated = LinearNDInterpolator(points, z)(
        np.column_stack((np.asarray(zx, dtype=np.float64), np.asarray(zy, dtype=np.float64)))
    )
    base = np.zeros(zone.shape, dtype=np.float64)
    base_valid = np.zeros(zone.shape, dtype=np.bool_)
    reachable = np.isfinite(interpolated)
    base[zone_rows[reachable], zone_cols[reachable]] = interpolated[reachable]
    base_valid[zone_rows[reachable], zone_cols[reachable]] = True
    return BoundaryBaseSurface(
        base_m=base,
        valid=base_valid,
        row_start=row_start,
        col_start=col_start,
        boundary_cell_count=boundary_cell_count,
        boundary_sample_count=boundary_sample_count,
        boundary_valid_fraction=boundary_valid_fraction,
        base_roughness_m=base_roughness_m,
    )


def measure_single_volume_zone(
    dsm_m: np.ndarray,
    valid: np.ndarray,
    *,
    transform: Affine,
    crs: str,
    cell_area_m2: float,
    polygon_geojson: dict[str, Any],
    zone_id: str,
    from_crs: str,
    threshold_m: float,
    minimum_common_valid_fraction: float,
    minimum_boundary_valid_fraction: float,
    maximum_zone_grid_cells: int,
    uncertainty_note: str,
    dsm_rmse_m: float | None,
) -> ExternalSingleVolumeZoneMeasurement | ExternalVolumeMeasurementError:
    surface = derive_boundary_base_surface(
        dsm_m, valid, transform=transform, crs=crs, polygon_geojson=polygon_geojson,
        from_crs=from_crs, minimum_boundary_valid_fraction=minimum_boundary_valid_fraction,
        maximum_zone_grid_cells=maximum_zone_grid_cells,
    )
    if isinstance(surface, ExternalVolumeMeasurementError):
        return surface
    diff = np.zeros(dsm_m.shape, dtype=np.float64)
    diff_valid = np.zeros(dsm_m.shape, dtype=np.bool_)
    height, width = surface.base_m.shape
    r0, r1 = max(0, surface.row_start), min(dsm_m.shape[0], surface.row_start + height)
    c0, c1 = max(0, surface.col_start), min(dsm_m.shape[1], surface.col_start + width)
    if r0 < r1 and c0 < c1:
        local = (slice(r0 - surface.row_start, r1 - surface.row_start), slice(c0 - surface.col_start, c1 - surface.col_start))
        target = (slice(r0, r1), slice(c0, c1))
        both = surface.valid[local] & valid[target]
        diff_valid[target] = both
        diff[target] = np.where(both, dsm_m[target] - surface.base_m[local], 0.0)
    measured = measure_external_volume_zone(
        DiffResult(diff_m=diff, valid=diff_valid, transform=transform, crs=crs, cell_area_m2=cell_area_m2),
        polygon_geojson,
        zone_id=zone_id,
        from_crs=from_crs,
        threshold_m=threshold_m,
        minimum_common_valid_fraction=minimum_common_valid_fraction,
        maximum_zone_grid_cells=maximum_zone_grid_cells,
        uncertainty_note=uncertainty_note,
        baseline_rmse_m=surface.base_roughness_m,
        current_rmse_m=dsm_rmse_m,
    )
    if isinstance(measured, ExternalVolumeMeasurementError):
        return measured
    try:
        metrics = ExternalSingleVolumeMetricsV1(
            **measured.metrics.model_dump(),
            base_roughness_m=surface.base_roughness_m,
            boundary_cell_count=surface.boundary_cell_count,
            boundary_sample_count=surface.boundary_sample_count,
            boundary_valid_fraction=surface.boundary_valid_fraction,
        )
    except ValueError as exc:
        return _error(ExternalVolumeMeasurementErrorReason.INVALID_INPUT, str(exc))
    return ExternalSingleVolumeZoneMeasurement(zone_id=zone_id, metrics=metrics)


__all__ = [
    "BoundaryBaseSurface",
    "ExternalSingleVolumeZoneMeasurement",
    "derive_boundary_base_surface",
    "measure_single_volume_zone",
]
```

Two facts the implementer must verify while writing: (a) `transform * (cols, rows)` with numpy arrays — if `Affine.__mul__` rejects arrays, use `rasterio.transform.xy(transform, rows, cols, offset="center")` which accepts sequences; (b) `measure_external_volume_zone` requires `uncertainty_m3` only when both RMSEs are non-None; with `dsm_rmse_m=None` the metric stays `None`, which the contract allows.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --locked pytest packages/change-detection/tests/test_external_single_volume.py packages/change-detection/tests/test_external_volume.py -q`
Expected: PASS. If `test_zone_outside_raster…` returns `EMPTY_ZONE`/`INVALID_ZONE` instead of `INSUFFICIENT_BOUNDARY_COVERAGE` because the window is fully outside, accept whichever typed error the shared helper raises first by asserting `measured.reason in {INSUFFICIENT_BOUNDARY_COVERAGE, EMPTY_ZONE}` — the point is fail-closed, not the exact code.

- [ ] **Step 6: Commit**

```bash
git add packages/change-detection/src/ksi_change_detection/external_single_volume.py packages/change-detection/src/ksi_change_detection/external_volume.py packages/change-detection/tests/test_external_single_volume.py
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "feat(change-detection): boundary-base single-epoch volume measurement (SV-1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `SINGLE_VOLUME` in the closed policy use catalogue

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/ingress/external_validation_policy.py:39-41` (`_PERMITTED_USES`), `:196` (`permits_selection` single set), `:933-936` (`_selection_arity_reason` single set)
- Test: `tests/contract/test_external_validation_policy.py`

**Interfaces:**
- Produces: `select_for_use("SINGLE_VOLUME", (subject,))`, `locally_current_use_permitted(..., use="SINGLE_VOLUME", subjects=(subject,))`, `historical_use_permitted(...)` all treat SINGLE_VOLUME as a single-subject use; `PolicyAuthorityRecord(permitted_uses=("SINGLE_VOLUME",))` is accepted.

- [ ] **Step 1: Write the failing test**

Append to `tests/contract/test_external_validation_policy.py` (reuse its `_subject`, `_bound_policy`, `FakePolicyAuthorityPort`, `_registry`, `NOW`, `PolicyReceiptStatus`, `PolicySelectionStatus`):

```python
def test_single_volume_is_a_single_subject_use(tmp_path: Path) -> None:
    subject = _subject(marker="a")
    policy, authority = _bound_policy(subjects=(subject,), uses=("SINGLE_VOLUME",))
    registry = _registry(tmp_path, FakePolicyAuthorityPort(authority))
    assert registry.admit(policy, actor="authority", now=NOW).status is PolicyReceiptStatus.ADMITTED

    selected = registry.select_for_use("SINGLE_VOLUME", (subject,))
    assert selected.status is PolicySelectionStatus.ACTIVE
    assert registry.locally_current_use_permitted(
        policy.policy_digest or "", use="SINGLE_VOLUME", subjects=(subject,), at=NOW
    )
    paired = registry.select_for_use("SINGLE_VOLUME", (subject, _subject(marker="d")))
    assert paired.status is PolicySelectionStatus.POLICY_UNAVAILABLE
    assert paired.reason == "SUBJECT_ARITY_INVALID"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --locked pytest tests/contract/test_external_validation_policy.py -k single_volume -q`
Expected: FAIL with `ValueError: policy use must be an allowed closed-catalogue value`

- [ ] **Step 3: Extend the catalogue and arity sets**

```python
_PERMITTED_USES = frozenset(
    {
        "INSPECTION",
        "EVIDENCE",
        "DISPLAY",
        "HEIGHT",
        "VISUAL_COMPARISON",
        "RELATIVE_VOLUME",
        "SINGLE_VOLUME",
    }
)
_SINGLE_SUBJECT_USES = frozenset({"INSPECTION", "EVIDENCE", "DISPLAY", "HEIGHT", "SINGLE_VOLUME"})
```

Replace the two literal sets `{"INSPECTION", "EVIDENCE", "DISPLAY", "HEIGHT"}` in `permits_selection` and `_selection_arity_reason` with `_SINGLE_SUBJECT_USES`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/contract/test_external_validation_policy.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/core/src/ksi_core/domains/external/ingress/external_validation_policy.py tests/contract/test_external_validation_policy.py
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "feat(core): SINGLE_VOLUME joins the closed policy use catalogue (SV-1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Third decision candidate in `ExternalUseDecisionStore`

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_use_decisions.py` (`DecisionCandidate`, `ExternalDecisionIntent`, `_intent_from_payload`, `_candidate_from_wire`, `_scope_and_operation`, `_scope_and_operation_for_intent`, `_validate_intent`, new joins after `resolve_historical_pair`)
- Test: `tests/contract/test_external_use_decisions.py`

**Interfaces:**
- Consumes: `ExternalSingleVolumeDecisionV1` (Task 1).
- Produces: `DecisionCandidate = ExternalUseDecisionV1 | ExternalPairUseDecisionV1 | ExternalSingleVolumeDecisionV1`; `ExternalDecisionIntent(requested_use="SINGLE_VOLUME", subject=..., requested_zone_id=..., zone=...)`; operation string `"SINGLE_VOLUME"`; `resolve_current_single_volume_for_issue(decision_id, *, principal, current_work_order_id) -> ExternalSingleVolumeDecisionV1 | None`; `resolve_historical_single_volume(*, organization_id, site_id, decision_id, decision_digest) -> ExternalSingleVolumeDecisionV1 | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/contract/test_external_use_decisions.py`:

```python
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeDecisionV1


def _single_volume(*, decision_id: str = "decision-single-volume") -> ExternalSingleVolumeDecisionV1:
    subject = _subject(marker="a")
    return ExternalSingleVolumeDecisionV1(
        decision_id=decision_id,
        subject=subject,
        subject_digest=subject.canonical_digest(),
        evidence_record_digests=(),
        verdict=DecisionVerdict.BLOCKED,
        reasons=("SINGLE_VOLUME_MAPPING_UNAVAILABLE",),
        remediations=("AUTHORIZE_SINGLE_VOLUME_MAPPING",),
        decided_at=NOW,
    ).sealed()


def test_single_volume_candidate_is_staged_with_its_zone_intent_and_resolved_for_issue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    candidate = _single_volume()
    intent = ExternalDecisionIntent(
        requested_use="SINGLE_VOLUME", subject=candidate.subject, requested_zone_id="zone-1"
    )
    store.stage_evaluated(candidate, intent=intent, principal=_principal(), idempotency_key="sv-1")
    store.reconcile_pending()

    assert store.existing_for_intent(intent=intent, principal=_principal(), idempotency_key="sv-1") == candidate
    other_zone = ExternalDecisionIntent(
        requested_use="SINGLE_VOLUME", subject=candidate.subject, requested_zone_id="zone-2"
    )
    with pytest.raises(ExternalUseDecisionConflictError):
        store.stage_evaluated(candidate, intent=other_zone, principal=_principal(), idempotency_key="sv-1")
    assert (
        store.resolve_current_single_volume_for_issue(
            "decision-single-volume", principal=_principal(), current_work_order_id="work-order-a"
        )
        == candidate
    )
    assert store.resolve_current_pair_for_issue(
        "decision-single-volume", principal=_principal(), current_work_order_id="work-order-a"
    ) is None
    assert store.resolve_current_single_volume_for_issue(
        "decision-single-volume", principal=_principal(organization_id="org-b"), current_work_order_id="work-order-a"
    ) is None
    assert candidate.decision_digest is not None
    assert (
        store.resolve_historical_single_volume(
            organization_id="org-a", site_id="site-a",
            decision_id="decision-single-volume", decision_digest=candidate.decision_digest,
        )
        == candidate
    )


def test_single_volume_candidate_survives_journal_replay(tmp_path: Path) -> None:
    candidate = _single_volume()
    intent = ExternalDecisionIntent(requested_use="SINGLE_VOLUME", subject=candidate.subject, requested_zone_id="zone-1")
    store = _store(tmp_path)
    store.stage_evaluated(candidate, intent=intent, principal=_principal(), idempotency_key="sv-replay")
    store.reconcile_pending()
    store._journal.close()  # noqa: SLF001
    reopened = _store(tmp_path)
    assert reopened.get_scoped("decision-single-volume", principal=_principal(), site_id="site-a") == candidate
```

Check the exact names `ExternalUseDecisionConflictError` and `get_scoped` signature at the top of the test file / store; adjust imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/contract/test_external_use_decisions.py -k single_volume -q`
Expected: FAIL with `ValueError: single decision intent is invalid` (or `decision candidate contract version is unknown`)

- [ ] **Step 3: Implement the third candidate**

In `external_use_decisions.py`:

```python
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeDecisionV1

DecisionCandidate = ExternalUseDecisionV1 | ExternalPairUseDecisionV1 | ExternalSingleVolumeDecisionV1
```

`ExternalDecisionIntent.from_candidate`:

```python
        if isinstance(candidate, ExternalUseDecisionV1):
            return cls(requested_use=candidate.use, subject=candidate.subject)
        if isinstance(candidate, ExternalSingleVolumeDecisionV1):
            return cls(
                requested_use="SINGLE_VOLUME",
                subject=candidate.subject,
                zone=candidate.zone,
                requested_zone_id=candidate.zone.zone_id if candidate.zone is not None else None,
            )
        return cls(  # pair, unchanged
```

`ExternalDecisionIntent.payload` — insert before the existing single branch:

```python
        if self.subject is not None and self.requested_use == "SINGLE_VOLUME":
            if (
                self.baseline_subject is not None
                or self.current_subject is not None
                or self.requested_zone_id is None
                or not self.requested_zone_id.strip()
                or len(self.requested_zone_id) > 255
            ):
                raise ValueError("single-volume intent requires a zone selection")
            if self.zone is not None and self.requested_zone_id != self.zone.zone_id:
                raise ValueError("sealed volume zone does not match selected zone")
            return {
                "requestedUse": "SINGLE_VOLUME",
                "subject": self.subject.canonical_payload(),
                "zone": self.zone.model_dump(by_alias=True, mode="json") if self.zone else None,
                "requestedZoneId": self.requested_zone_id,
            }
```

`_intent_from_payload` — add a branch for `set(raw) == {"requestedUse", "subject", "zone", "requestedZoneId"}` that builds the intent with `subject`, `zone` (validated `SealedZoneReferenceV1` or None) and the text-checked `requested_zone_id`.

`_candidate_from_wire` — add `elif contract_version == "external-single-volume-decision.v1": candidate = ExternalSingleVolumeDecisionV1.model_validate(raw)`.

`_scope_and_operation`:

```python
    if isinstance(candidate, ExternalSingleVolumeDecisionV1):
        subject = candidate.subject
        return _Scope(subject.organization_id, subject.site_id), "SINGLE_VOLUME"
```

`_scope_and_operation_for_intent`: when `intent.subject is not None`, return operation `"SINGLE_VOLUME"` if `intent.requested_use == "SINGLE_VOLUME"` else `"SINGLE"`.

`_validate_intent` — add before the pair branch:

```python
    if isinstance(candidate, ExternalSingleVolumeDecisionV1):
        if (
            intent.requested_use != "SINGLE_VOLUME"
            or intent.subject != candidate.subject
            or intent.requested_zone_id is None
            or (candidate.zone is not None and intent.requested_zone_id != candidate.zone.zone_id)
        ):
            raise ValueError("decision intent does not match evaluator candidate")
        return
```

New joins after `resolve_historical_pair`, mirroring the pair versions exactly with `ExternalSingleVolumeDecisionV1` and `candidate.subject.work_order_id`:

```python
    def resolve_current_single_volume_for_issue(
        self, decision_id: str, *, principal: Principal, current_work_order_id: str
    ) -> ExternalSingleVolumeDecisionV1 | None:
        with self._lock:
            candidate = self._recorded.get(decision_id)
            scope = self._scopes.get(decision_id)
            if (
                not isinstance(candidate, ExternalSingleVolumeDecisionV1)
                or scope is None
                or scope.organization_id != principal.organization_id
                or candidate.decision_id != decision_id
                or candidate.subject.work_order_id != current_work_order_id
                or candidate.decision_digest is None
                or candidate.canonical_digest() != candidate.decision_digest
            ):
                return None
            return candidate.model_copy(deep=True)

    def resolve_historical_single_volume(
        self, *, organization_id: str, site_id: str, decision_id: str, decision_digest: str
    ) -> ExternalSingleVolumeDecisionV1 | None:
        with self._lock:
            candidate = self._recorded.get(decision_id)
            scope = self._scopes.get(decision_id)
            if (
                not isinstance(candidate, ExternalSingleVolumeDecisionV1)
                or scope != _Scope(organization_id, site_id)
                or candidate.decision_id != decision_id
                or candidate.decision_digest != decision_digest
                or candidate.canonical_digest() != decision_digest
            ):
                return None
            return candidate.model_copy(deep=True)
```

Also check `_apply_requested` / `_apply_recorded` for any `isinstance(..., ExternalUseDecisionV1)`-else-pair assumptions and route the new type through `_scope_and_operation` (grep `ExternalPairUseDecisionV1` in the file; every `else` that assumes pair must become an explicit `isinstance` chain).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/contract/test_external_use_decisions.py tests/replay/test_external_use_decisions_replay.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/core/src/ksi_core/domains/external/quantity/external_use_decisions.py tests/contract/test_external_use_decisions.py
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "feat(core): single-volume decision candidate, intent and issue joins (SV-1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Single-volume compatibility record and authority value types

**Files:**
- Create: `services/core/src/ksi_core/domains/external/quantity/external_single_volume_authority.py`
- Create: `services/core/src/ksi_core/domains/external/quantity/external_single_volume_authorities.py`
- Create: `services/core/src/ksi_core/external_single_volume_authority.py`, `services/core/src/ksi_core/external_single_volume_authorities.py` (alias shims)
- Test: `tests/contract/test_external_single_volume_authority.py`

**Interfaces:**
- Consumes: `_digest`, `_utc`, `_wire_time`, `_parse_time`, `_required_digest`, `_strict_mapping`, `_PROFILE` from `external_quantitative_authority`; `ExternalVolumeInputBindingV1`, `ExternalVolumeZoneSnapshotV1`; `SealedZoneReferenceV1`, `SealedExternalSubjectV1`, `ExternalValidationPolicyV1`.
- Produces:
  - `SingleVolumeCompatibilityRuleDescriptorV1` (frozen dataclass; `canonical_payload()`, `canonical_digest()` with domain `ksi.external-single-volume-compatibility-rule.v1`).
  - `ExternalSingleVolumeCompatibilityRecord(organization_id, site_id, target, zone_snapshot, validation_policy_digest, external_profile, grammar_digest, inspector_build_digest, evidence_record_digests: tuple[str] (len 1), execution_policy_ref, valid_from, valid_until, compatibility_rule_descriptor, compatibility_rule_digest, mapping_record_digest)` with `mapping_digest` property, `canonical_payload()`, `canonical_digest()` (domain `ksi.external-single-volume-compatibility.v1`), `sealed()`, `is_active_at(now)`, `from_event_payload(raw)`.
  - `ExternalSingleVolumeAuthority(zone: SealedZoneReferenceV1, compatibility_mapping_digest, historical_authority_digest, synthetic_test_only)`.
  - `ExternalSingleVolumeAuthorityPort` Protocol: `currentness_coordinator`; `resolve_for_use(*, subject, zone_id, policy, now) -> ExternalSingleVolumeAuthority | None`; `is_current_for_use(authority, *, now) -> bool`; `resolve_historical_for_decision(decision: ExternalSingleVolumeDecisionV1) -> ExternalSingleVolumeAuthority | None`.
  - `DefaultClosedExternalSingleVolumeAuthorityPort(currentness_coordinator=...)` returning None/False.

- [ ] **Step 1: Write the failing test**

```python
# tests/contract/test_external_single_volume_authority.py
"""Single-volume compatibility record: sealed, bound to one epoch and one zone."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from ksi_core.external_single_volume_authority import (
    ExternalSingleVolumeCompatibilityRecord,
    SingleVolumeCompatibilityRuleDescriptorV1,
)
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)

_NOW = datetime(2026, 9, 17, tzinfo=UTC)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _subject() -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a", site_id="site-a", work_order_id="work-a",
        submission_id="submission-a", revision=1,
        submission_digest=_digest("submission-a"), manifest_digest=_digest("manifest-a"),
    )


def _binding() -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=_subject(), inspection_report_digest=_digest("inspection-a"),
        dsm_artifact_id="dsm-a", observed_sha256=_digest("dsm-bytes-a"), observed_size_bytes=16,
        observed_crs_digest=_digest("crs"), observed_vertical_reference_digest=_digest("vertical"),
        captured_from=_NOW, captured_to=_NOW + timedelta(hours=1),
    )


def _zone() -> ExternalVolumeZoneSnapshotV1:
    return ExternalVolumeZoneSnapshotV1(
        organization_id="org-a", site_id="site-a", work_area_id="work-area-a",
        polygon={"type": "Polygon", "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]},
        crs="EPSG:5186", observed_crs_digest=_digest("crs"),
        analysis_vertical_reference_digest=_digest("vertical"),
    ).sealed()


def single_mapping() -> ExternalSingleVolumeCompatibilityRecord:
    return ExternalSingleVolumeCompatibilityRecord(
        organization_id="org-a", site_id="site-a", target=_binding(), zone_snapshot=_zone(),
        validation_policy_digest=_digest("validation-policy"),
        external_profile="external-geotiff-profile.v1",
        grammar_digest=_digest("grammar"), inspector_build_digest=_digest("inspector-build"),
        evidence_record_digests=(_digest("evidence-a"),),
        execution_policy_ref=_digest("execution-policy-authority"),
        valid_from=_NOW - timedelta(minutes=1), valid_until=_NOW + timedelta(minutes=10),
    ).sealed()


def test_sealed_record_round_trips_through_its_event_payload() -> None:
    record = single_mapping()
    assert record.mapping_digest == record.canonical_digest()
    payload = {"mappingRecordDigest": record.mapping_digest, **record.canonical_payload()}
    assert ExternalSingleVolumeCompatibilityRecord.from_event_payload(payload) == record
    assert record.compatibility_rule_digest == SingleVolumeCompatibilityRuleDescriptorV1().canonical_digest()


def test_record_requires_exactly_one_evidence_record_and_matching_references() -> None:
    from dataclasses import replace

    base = single_mapping()
    with pytest.raises(ValueError, match="exactly one evidence"):
        replace(base, evidence_record_digests=(_digest("x"), _digest("y")), mapping_record_digest=None)
    with pytest.raises(ValueError, match="references must match"):
        replace(
            base,
            target=_binding().model_copy(update={"observed_vertical_reference_digest": _digest("other")}),
            mapping_record_digest=None,
        )
    with pytest.raises(ValueError, match="share organization and site"):
        replace(base, site_id="site-b", mapping_record_digest=None)


def test_rule_digest_differs_from_the_pair_rule() -> None:
    from ksi_core.external_quantitative_authority import CompatibilityRuleDescriptorV1

    assert SingleVolumeCompatibilityRuleDescriptorV1().canonical_digest() != CompatibilityRuleDescriptorV1().canonical_digest()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --locked pytest tests/contract/test_external_single_volume_authority.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the record module**

```python
# services/core/src/ksi_core/domains/external/quantity/external_single_volume_authority.py
"""Pre-decision compatibility authorization for one DSM epoch and one zone."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
    external_volume_zone_snapshot_wire_dict,
)

from ksi_core.domains.external.quantity.external_quantitative_authority import (
    _PROFILE,
    _digest,
    _parse_time,
    _required_digest,
    _strict_mapping,
    _utc,
    _wire_time,
)


@dataclass(frozen=True, slots=True)
class SingleVolumeCompatibilityRuleDescriptorV1:
    """Stable predicates a policy may pre-approve for single-epoch volume."""

    external_profile: str = _PROFILE
    requires_same_grammar_digest: bool = True
    requires_same_inspector_build_digest: bool = True
    requires_independent_measured_checkpoint: bool = True
    requires_exact_work_area_match: bool = True
    base_surface_method: str = "BOUNDARY_LINEAR_INTERPOLATION_V1"

    def __post_init__(self) -> None:
        if self.external_profile != _PROFILE:
            raise ValueError("single-volume descriptor accepts only external-geotiff-profile.v1")
        if not all(
            type(value) is bool and value
            for value in (
                self.requires_same_grammar_digest,
                self.requires_same_inspector_build_digest,
                self.requires_independent_measured_checkpoint,
                self.requires_exact_work_area_match,
            )
        ):
            raise ValueError("single-volume compatibility predicates must remain required")
        if self.base_surface_method != "BOUNDARY_LINEAR_INTERPOLATION_V1":
            raise ValueError("single-volume base surface method is fixed in V1")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "externalProfile": self.external_profile,
            "requiresSameGrammarDigest": self.requires_same_grammar_digest,
            "requiresSameInspectorBuildDigest": self.requires_same_inspector_build_digest,
            "requiresIndependentMeasuredCheckpoint": self.requires_independent_measured_checkpoint,
            "requiresExactWorkAreaMatch": self.requires_exact_work_area_match,
            "baseSurfaceMethod": self.base_surface_method,
        }

    def canonical_digest(self) -> str:
        return _digest(
            {"domain": "ksi.external-single-volume-compatibility-rule.v1", "rule": self.canonical_payload()}
        )


@dataclass(frozen=True, slots=True)
class ExternalSingleVolumeCompatibilityRecord:
    """Immutable single-epoch compatibility authorization; its digest is the mapping ID."""

    organization_id: str
    site_id: str
    target: ExternalVolumeInputBindingV1
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    validation_policy_digest: str
    external_profile: str
    grammar_digest: str
    inspector_build_digest: str
    evidence_record_digests: tuple[str, ...]
    execution_policy_ref: str
    valid_from: datetime
    valid_until: datetime
    compatibility_rule_descriptor: SingleVolumeCompatibilityRuleDescriptorV1 = field(
        default_factory=SingleVolumeCompatibilityRuleDescriptorV1
    )
    compatibility_rule_digest: str | None = None
    mapping_record_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.organization_id or not self.site_id:
            raise ValueError("single-volume record requires organization and site")
        if self.external_profile != _PROFILE:
            raise ValueError("single-volume authority accepts only external-geotiff-profile.v1")
        for name, value in (
            ("validation policy", self.validation_policy_digest),
            ("grammar", self.grammar_digest),
            ("inspector build", self.inspector_build_digest),
            ("execution policy reference", self.execution_policy_ref),
        ):
            _required_digest(value, name=name)
        if len(self.evidence_record_digests) != 1:
            raise ValueError("single-volume record requires exactly one evidence record")
        _required_digest(self.evidence_record_digests[0], name="evidence record")
        _utc(self.valid_from, name="single-volume valid_from")
        _utc(self.valid_until, name="single-volume valid_until")
        if self.valid_from >= self.valid_until:
            raise ValueError("single-volume validity interval must be ordered")
        if (
            self.target.subject.organization_id != self.organization_id
            or self.zone_snapshot.organization_id != self.organization_id
            or self.target.subject.site_id != self.site_id
            or self.zone_snapshot.site_id != self.site_id
        ):
            raise ValueError("single-volume participants must share organization and site")
        if (
            self.target.observed_crs_digest != self.zone_snapshot.observed_crs_digest
            or self.target.observed_vertical_reference_digest
            != self.zone_snapshot.analysis_vertical_reference_digest
        ):
            raise ValueError("single-volume DSM and WorkArea references must match")
        if (
            self.compatibility_rule_digest is not None
            and self.compatibility_rule_digest != self.compatibility_rule_descriptor.canonical_digest()
        ):
            raise ValueError("single-volume rule digest does not match rule facts")
        if self.mapping_record_digest is not None and self.mapping_record_digest != self.canonical_digest():
            raise ValueError("single-volume mapping record digest does not match canonical record")

    @property
    def mapping_digest(self) -> str | None:
        return self.mapping_record_digest

    def compatibility_rule_canonical_digest(self) -> str:
        return self.compatibility_rule_descriptor.canonical_digest()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "organizationId": self.organization_id,
            "siteId": self.site_id,
            "target": self.target.model_dump(by_alias=True, mode="json"),
            "zoneSnapshot": external_volume_zone_snapshot_wire_dict(self.zone_snapshot),
            "validationPolicyDigest": self.validation_policy_digest,
            "externalProfile": self.external_profile,
            "grammarDigest": self.grammar_digest,
            "inspectorBuildDigest": self.inspector_build_digest,
            "evidenceRecordDigests": list(self.evidence_record_digests),
            "compatibilityRuleDigest": self.compatibility_rule_digest
            or self.compatibility_rule_canonical_digest(),
            "executionPolicyRef": self.execution_policy_ref,
            "validFrom": _wire_time(self.valid_from),
            "validUntil": _wire_time(self.valid_until),
        }

    def canonical_digest(self) -> str:
        return _digest({"domain": "ksi.external-single-volume-compatibility.v1", "record": self.canonical_payload()})

    def sealed(self) -> ExternalSingleVolumeCompatibilityRecord:
        with_rule = replace(
            self, compatibility_rule_digest=self.compatibility_rule_canonical_digest(), mapping_record_digest=None
        )
        return replace(with_rule, mapping_record_digest=with_rule.canonical_digest())

    def is_active_at(self, now: datetime) -> bool:
        _utc(now, name="single-volume lookup time")
        return self.valid_from <= now < self.valid_until

    @classmethod
    def from_event_payload(cls, raw: object) -> ExternalSingleVolumeCompatibilityRecord:
        payload = _strict_mapping(
            raw,
            frozenset({
                "mappingRecordDigest", "organizationId", "siteId", "target", "zoneSnapshot",
                "validationPolicyDigest", "externalProfile", "grammarDigest", "inspectorBuildDigest",
                "evidenceRecordDigests", "compatibilityRuleDigest", "executionPolicyRef",
                "validFrom", "validUntil",
            }),
            name="single-volume compatibility record",
        )
        evidence = payload["evidenceRecordDigests"]
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise ValueError("single-volume evidence records must be a string list")
        return cls(
            organization_id=str(payload["organizationId"]),
            site_id=str(payload["siteId"]),
            target=ExternalVolumeInputBindingV1.model_validate(payload["target"]),
            zone_snapshot=ExternalVolumeZoneSnapshotV1.model_validate(payload["zoneSnapshot"]),
            validation_policy_digest=str(payload["validationPolicyDigest"]),
            external_profile=str(payload["externalProfile"]),
            grammar_digest=str(payload["grammarDigest"]),
            inspector_build_digest=str(payload["inspectorBuildDigest"]),
            evidence_record_digests=tuple(evidence),
            compatibility_rule_digest=str(payload["compatibilityRuleDigest"]),
            execution_policy_ref=str(payload["executionPolicyRef"]),
            valid_from=_parse_time(payload["validFrom"], name="single-volume validFrom"),
            valid_until=_parse_time(payload["validUntil"], name="single-volume validUntil"),
            mapping_record_digest=str(payload["mappingRecordDigest"]),
        )


__all__ = ["ExternalSingleVolumeCompatibilityRecord", "SingleVolumeCompatibilityRuleDescriptorV1"]
```

If importing `_PROFILE`/helpers from `external_quantitative_authority` creates an import cycle in Task 6 (the catalog imports this module), move the shared helpers (`_digest`, `_utc`, `_wire_time`, `_parse_time`, `_required_digest`, `_strict_mapping`, `_PROFILE`) into a new `external_quantitative_common.py` and import them from both files.

- [ ] **Step 4: Write the authority value module**

```python
# services/core/src/ksi_core/domains/external/quantity/external_single_volume_authorities.py
"""Single-volume mapping authority value and default-closed port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
)
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeDecisionV1

from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator


@dataclass(frozen=True, slots=True)
class ExternalSingleVolumeAuthority:
    zone: SealedZoneReferenceV1
    compatibility_mapping_digest: str
    historical_authority_digest: str
    synthetic_test_only: bool


class ExternalSingleVolumeAuthorityPort(Protocol):
    currentness_coordinator: ExternalAuthorityCurrentnessCoordinator

    def resolve_for_use(
        self, *, subject: SealedExternalSubjectV1, zone_id: str,
        policy: ExternalValidationPolicyV1, now: datetime,
    ) -> ExternalSingleVolumeAuthority | None: ...

    def is_current_for_use(self, authority: ExternalSingleVolumeAuthority, *, now: datetime) -> bool: ...

    def resolve_historical_for_decision(
        self, decision: ExternalSingleVolumeDecisionV1
    ) -> ExternalSingleVolumeAuthority | None: ...


class DefaultClosedExternalSingleVolumeAuthorityPort:
    def __init__(self, *, currentness_coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self.currentness_coordinator = currentness_coordinator

    def resolve_for_use(self, *, subject: SealedExternalSubjectV1, zone_id: str, policy: ExternalValidationPolicyV1, now: datetime) -> ExternalSingleVolumeAuthority | None:
        del subject, zone_id, policy, now
        return None

    def is_current_for_use(self, authority: ExternalSingleVolumeAuthority, *, now: datetime) -> bool:
        del authority, now
        return False

    def resolve_historical_for_decision(self, decision: ExternalSingleVolumeDecisionV1) -> ExternalSingleVolumeAuthority | None:
        del decision
        return None


__all__ = [
    "DefaultClosedExternalSingleVolumeAuthorityPort",
    "ExternalSingleVolumeAuthority",
    "ExternalSingleVolumeAuthorityPort",
]
```

Alias shims (`services/core/src/ksi_core/external_single_volume_authority.py`, `…/external_single_volume_authorities.py`):

```python
"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.quantity import external_single_volume_authority as _canonical
from ksi_core.domains.external.quantity.external_single_volume_authority import *  # noqa: F403

_sys.modules[__name__] = _canonical
```

(second shim identical with `external_single_volume_authorities`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/contract/test_external_single_volume_authority.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/core/src/ksi_core/domains/external/quantity/external_single_volume_authority.py services/core/src/ksi_core/domains/external/quantity/external_single_volume_authorities.py services/core/src/ksi_core/external_single_volume_authority.py services/core/src/ksi_core/external_single_volume_authorities.py tests/contract/test_external_single_volume_authority.py
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "feat(core): single-volume compatibility record and authority port (SV-1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Catalog admits, revokes and resolves single-volume mappings

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_quantitative_authority.py` (constants, `ExternalQuantitativeCatalogAuthorityBinding` type widening, `ExternalQuantitativeAuthorityParticipants`, `ExternalQuantitativeAuthorityCatalog`)
- Test: `tests/contract/test_external_quantitative_authority.py`, `tests/replay/test_external_quantitative_authority_replay.py`

**Interfaces:**
- Consumes: Task 5 types.
- Produces on `ExternalQuantitativeAuthorityCatalog`: `admit_single_mapping(record, *, actor, now) -> ExternalSingleVolumeCompatibilityRecord | None`; `revoke_single_mapping(mapping_digest, *, actor, now) -> bool`; `resolve_single_for_use(*, subject, zone_id, policy, now) -> ExternalSingleVolumeAuthority | None`; `is_current_for_single_use(authority, *, now) -> bool`; `resolve_historical_for_single_decision(decision) -> ExternalSingleVolumeAuthority | None`; `single_mapping_port` property returning an adapter object with `currentness_coordinator`, `resolve_for_use`, `is_current_for_use`, `resolve_historical_for_decision` (so the evaluator can consume the catalog through `ExternalSingleVolumeAuthorityPort`).
- Produces on `ExternalQuantitativeAuthorityParticipants`: `single_current_snapshot(record, now) -> _SingleParticipantSnapshot | None`, `single_locally_current(record, snapshot, now) -> bool`, `validates_single(record, now) -> bool`.
- Journal kinds `_SINGLE_MAPPING_ACTIVATED = "external-quantitative-single-mapping-activated"`, `_SINGLE_MAPPING_REVOKED = "external-quantitative-single-mapping-revoked"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/contract/test_external_quantitative_authority.py`:

```python
from test_external_single_volume_authority import single_mapping as _single_mapping  # noqa: E402  (sys.path already includes tests/contract via conftest; otherwise import via `from tests.contract...`)


def test_single_mapping_is_durable_and_resolves_for_its_subject_and_zone(tmp_path: Path) -> None:
    mapping = _single_mapping()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=coordinator,
        mapping_admission_validator=lambda _record, _now: True,
        execution_template_resolver=lambda _record, _now: _template(),
    )
    assert catalog.admit_single_mapping(mapping, actor="authority-a", now=_NOW) == mapping
    policy = cast(ExternalValidationPolicyV1, SimpleNamespace(policy_digest=mapping.validation_policy_digest))

    resolved = catalog.resolve_single_for_use(
        subject=mapping.target.subject, zone_id="work-area-a", policy=policy, now=_NOW
    )
    assert resolved is not None
    assert resolved.compatibility_mapping_digest == mapping.mapping_digest
    assert resolved.zone == mapping.zone_snapshot.to_zone_reference()
    assert catalog.is_current_for_single_use(resolved, now=_NOW)
    assert catalog.resolve_single_for_use(
        subject=mapping.target.subject, zone_id="work-area-other", policy=policy, now=_NOW
    ) is None
    # The pair index does not see single mappings.
    assert catalog.resolve_for_use(
        baseline=mapping.target.subject, current=mapping.target.subject, zone_id="work-area-a", policy=policy, now=_NOW
    ) is None

    assert mapping.mapping_digest is not None
    assert catalog.revoke_single_mapping(mapping.mapping_digest, actor="authority-a", now=_NOW + timedelta(seconds=1))
    assert not catalog.is_current_for_single_use(resolved, now=_NOW + timedelta(seconds=2))
    catalog._journal.close()  # noqa: SLF001

    reopened = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
    )
    assert [e["kind"] for e in reopened._journal.replay()] == [  # noqa: SLF001
        "external-quantitative-single-mapping-activated",
        "external-quantitative-single-mapping-revoked",
    ]
    assert reopened.resolve_single_for_use(
        subject=mapping.target.subject, zone_id="work-area-a", policy=policy, now=_NOW + timedelta(seconds=2)
    ) is None


def test_single_mapping_admission_fails_closed_without_validator_approval(tmp_path: Path) -> None:
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(tmp_path / "quantitative-authority.jsonl"),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: False,
    )
    assert catalog.admit_single_mapping(_single_mapping(), actor="authority-a", now=_NOW) is None
    assert list(catalog._journal.replay()) == []  # noqa: SLF001
```

Append to `tests/replay/test_external_quantitative_authority_replay.py`:

```python
def test_restart_rejects_mutated_single_mapping_activation(tmp_path: Path) -> None:
    from test_external_single_volume_authority import single_mapping

    path = tmp_path / "quantitative-authority.jsonl"
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path), currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
    )
    catalog.admit_single_mapping(single_mapping(), actor="authority-a", now=_NOW)
    catalog._journal.close()  # noqa: SLF001
    lines = path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["mapping"]["siteId"] = "site-forged"
    event["eventDigest"] = _event_digest(event)
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(ExternalQuantitativeAuthorityRecoveryError):
        ExternalQuantitativeAuthorityCatalog(
            DurableJournal(path), currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
            mapping_admission_validator=lambda _record, _now: True,
        )
```

(`_event_digest` already exists in that replay test file; reuse it.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/contract/test_external_quantitative_authority.py tests/replay/test_external_quantitative_authority_replay.py -k single -q`
Expected: FAIL with `AttributeError: 'ExternalQuantitativeAuthorityCatalog' object has no attribute 'admit_single_mapping'`

- [ ] **Step 3: Implement the catalog changes**

1. Constants next to the existing ones:

```python
_SINGLE_MAPPING_ACTIVATED = "external-quantitative-single-mapping-activated"
_SINGLE_MAPPING_REVOKED = "external-quantitative-single-mapping-revoked"
```

2. Import `ExternalSingleVolumeCompatibilityRecord` (Task 5) and `ExternalSingleVolumeAuthority` (Task 5), `ExternalSingleVolumeDecisionV1` (Task 1). Define `AnyCompatibilityRecord = ExternalQuantitativeCompatibilityRecord | ExternalSingleVolumeCompatibilityRecord` and widen the `record` parameter annotations of `ExternalQuantitativeCatalogAuthorityBinding.resolve_current / locally_permits / permits` to `AnyCompatibilityRecord` (they only read `execution_policy_ref` and `organization_id`).

3. `ExternalQuantitativeAuthorityParticipants`: split `_record_facts_match` into

```python
    def _zone_facts_match(self, zone: ExternalVolumeZoneSnapshotV1, *, site_id: str) -> bool:
        area = self.work_areas.get(zone.work_area_id)
        return not (
            area is None
            or area.status is not WorkAreaStatus.ACTIVE
            or area.site_id != site_id
            or area.polygon != zone.polygon
            or area.crs != zone.crs
            or zone.definition_digest != zone.definition_canonical_digest()
        )

    def _binding_facts_match(
        self, binding: ExternalVolumeInputBindingV1, *, validation_policy_digest: str, inspector_build_digest: str
    ) -> bool:
        # body = the per-binding loop body of the current _record_facts_match, unchanged
```

and rewrite `_record_facts_match` as `self._zone_facts_match(record.zone_snapshot, site_id=record.site_id) and len(record.evidence_record_digests) == 2 and all(self._binding_facts_match(b, ...) for b in (record.baseline, record.current))`. Existing tests must stay green after this refactor before adding the single methods.

Add:

```python
@dataclass(frozen=True, slots=True)
class _SingleParticipantSnapshot:
    catalog_authority: ExternalQuantitativeCatalogAuthorityRecord
    policy: ExternalValidationPolicyV1
    evidence_record: tuple[object, object]
```

```python
    def single_current_snapshot(
        self, record: ExternalSingleVolumeCompatibilityRecord, now: datetime
    ) -> _SingleParticipantSnapshot | None:
        catalog_authority = self.catalog_authority.resolve_current(record, now)
        if catalog_authority is None:
            return None
        selected = self.policy_registry.select_for_use("SINGLE_VOLUME", (record.target.subject,))
        policy = selected.policy
        if (
            selected.status is not PolicySelectionStatus.ACTIVE
            or policy is None
            or policy.policy_digest != record.validation_policy_digest
            or policy.synthetic_test_only
            or policy.grammar_digest != record.grammar_digest
            or policy.parser_build_digest != record.inspector_build_digest
            or policy.resource_envelope is None
            or policy.resource_envelope_digest is None
            or record.compatibility_rule_digest not in policy.compatibility_mapping_digests
        ):
            return None
        if not self._single_record_facts_match(record):
            return None
        evidence = self.evidence_validations.record_for_current_use(
            record.evidence_record_digests[0], subject=record.target.subject,
            policy_digest=record.validation_policy_digest,
        )
        if evidence is None or not self._evidence_matches_binding(record.target, evidence):
            return None
        return _SingleParticipantSnapshot(catalog_authority=catalog_authority, policy=policy, evidence_record=evidence)

    def single_locally_current(
        self, record: ExternalSingleVolumeCompatibilityRecord, snapshot: _SingleParticipantSnapshot, now: datetime
    ) -> bool:
        if not self.catalog_authority.locally_permits(record, snapshot.catalog_authority, now):
            return False
        if not self.policy_registry.locally_current_use_permitted(
            record.validation_policy_digest, use="SINGLE_VOLUME", subjects=(record.target.subject,), at=now
        ):
            return False
        selected = self.policy_registry.resolve(record.validation_policy_digest)
        policy = selected.policy
        if (
            selected.status is not PolicySelectionStatus.ACTIVE
            or policy is None
            or policy != snapshot.policy
            or not self._single_record_facts_match(record)
        ):
            return False
        evidence = self.evidence_validations.record_for_locally_current_use(
            record.evidence_record_digests[0], subject=record.target.subject,
            policy_digest=record.validation_policy_digest,
        )
        return evidence == snapshot.evidence_record and self._evidence_matches_binding(record.target, evidence)

    def validates_single(self, record: ExternalSingleVolumeCompatibilityRecord, now: datetime) -> bool:
        snapshot = self.single_current_snapshot(record, now)
        return snapshot is not None and self.single_locally_current(record, snapshot, now)

    def _single_record_facts_match(self, record: ExternalSingleVolumeCompatibilityRecord) -> bool:
        return self._zone_facts_match(record.zone_snapshot, site_id=record.site_id) and self._binding_facts_match(
            record.target,
            validation_policy_digest=record.validation_policy_digest,
            inspector_build_digest=record.inspector_build_digest,
        )
```

4. Catalog state and constructor: add `self._single_mappings: dict[str, _SingleMappingState] = {}` and `self._current_single_snapshots: dict[str, _SingleParticipantSnapshot] = {}` before `_replay()`; define

```python
@dataclass(frozen=True, slots=True)
class _SingleMappingState:
    record: ExternalSingleVolumeCompatibilityRecord
    activated_at: datetime
    revoked_at: datetime | None = None

    def active_at(self, at: datetime) -> bool:
        return self.activated_at <= at and self.record.is_active_at(at) and (self.revoked_at is None or at < self.revoked_at)
```

Widen `mapping_admission_validator`'s annotation to `Callable[[AnyCompatibilityRecord, datetime], bool]`. Add `_current_single_participants(record, now)` / `_single_participants_remain_current(record, snapshot, now)` mirroring the pair helpers but calling `participants.single_current_snapshot` / `single_locally_current` (validator fallback identical).

5. Methods `admit_single_mapping` and `revoke_single_mapping`: copy `admit_mapping`/`revoke_mapping` bodies with `_single_mappings`, `_SINGLE_MAPPING_ACTIVATED`/`_REVOKED`, `_SingleMappingState`, the single participant helpers, and event payload `"mapping": {"mappingRecordDigest": sealed.mapping_digest, **sealed.canonical_payload()}`.

6. `resolve_single_for_use(*, subject, zone_id, policy, now)`: copy `resolve_for_use` with match predicate `state.record.target.subject == subject and state.record.zone_snapshot.work_area_id == zone_id and state.record.validation_policy_digest == policy_digest`, storing the snapshot in `_current_single_snapshots`, returning `ExternalSingleVolumeAuthority(zone=record.zone_snapshot.to_zone_reference(), compatibility_mapping_digest=record.mapping_digest, historical_authority_digest=record.mapping_digest, synthetic_test_only=False)`.

7. `is_current_for_single_use(authority, *, now)`: copy `is_current_for_use` against `_single_mappings` / `_current_single_snapshots` / `single_locally_current`.

8. `resolve_historical_for_single_decision(decision: ExternalSingleVolumeDecisionV1)`: copy `resolve_historical_for_decision`; predicates `decision.use == "SINGLE_VOLUME"`, `record.target.subject == decision.subject`, `record.validation_policy_digest == decision.policy_digest`, `record.zone_snapshot.to_zone_reference() == decision.zone`.

9. Port adapter for the evaluator:

```python
    @property
    def single_mapping_port(self) -> _SingleMappingPortAdapter:
        return _SingleMappingPortAdapter(self)


class _SingleMappingPortAdapter:
    def __init__(self, catalog: ExternalQuantitativeAuthorityCatalog) -> None:
        self._catalog = catalog
        self.currentness_coordinator = catalog.currentness_coordinator

    def resolve_for_use(self, *, subject, zone_id, policy, now):
        return self._catalog.resolve_single_for_use(subject=subject, zone_id=zone_id, policy=policy, now=now)

    def is_current_for_use(self, authority, *, now):
        return self._catalog.is_current_for_single_use(authority, now=now)

    def resolve_historical_for_decision(self, decision):
        return self._catalog.resolve_historical_for_single_decision(decision)
```

(add full type annotations; mypy runs strict).

10. `_apply`: add two `elif` branches before `else` mirroring the pair mapping branches with `ExternalSingleVolumeCompatibilityRecord.from_event_payload`, `_single_mappings`, `_SingleMappingState`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/contract/test_external_quantitative_authority.py tests/replay/test_external_quantitative_authority_replay.py tests/contract/test_external_quantitative_production_flow.py -q`
Expected: PASS (the production-flow test guards the refactor of `_record_facts_match`).

- [ ] **Step 5: Commit**

```bash
git add services/core/src/ksi_core/domains/external/quantity/external_quantitative_authority.py tests/contract/test_external_quantitative_authority.py tests/replay/test_external_quantitative_authority_replay.py
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "feat(core): catalog admits and resolves single-volume mappings (SV-1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Evaluator `request_single_volume`, history verification, blocker copy and route

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_use_evaluator.py`
- Modify: `contracts/catalogs/external-use-blockers.v1.json`, `apps/dashboard/src/lib/external-use-blockers.generated.json`
- Modify: `contracts/api/openapi-core.yaml` (after the `…/use-decisions/pair` path)
- Test: `tests/contract/test_external_use_evaluator.py`, `tests/contract/test_external_use_blockers.py` (existing, must pass)

**Interfaces:**
- Consumes: Task 1 decision model, Task 4 store joins, Task 5 port/value types.
- Produces: `ExternalUseEvaluator(..., single_volume_authority: ExternalSingleVolumeAuthorityPort | None = None)`; `request_single_volume(subject, *, zone_id, idempotency_key, principal, now) -> ExternalSingleVolumeDecisionV1`; `existing_single_volume_retry(subject, *, zone_id, principal, idempotency_key) -> ExternalSingleVolumeDecisionV1 | None`; `CoreExternalUseDecisionHistoryVerifier(..., single_volume_authority=...)` verifying the new candidate; `ExternalSingleVolumeDecisionRequest(zone_id: str)`; route `POST {base}/single-volume` (201, same 404/409/422 mapping as pair); `PAIR_REASON_REMEDIATIONS["SINGLE_VOLUME_MAPPING_UNAVAILABLE"] = "AUTHORIZE_SINGLE_VOLUME_MAPPING"`.

- [ ] **Step 1: Write the failing evaluator tests**

Append to `tests/contract/test_external_use_evaluator.py` (reusing `_report_with_measured_dsm`, `_report_for_subject`, `_receipt`, `_PolicyAuthority`, `_Reconstruction`, `_Inspections`, `_EvidenceProjection`, `_SyntheticHistoryVerifier`, `subject`, `policy_template`, `digest`, `NOW`, `_principal`):

```python
from ksi_core.external_single_volume_authorities import ExternalSingleVolumeAuthority
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeDecisionV1


class _SingleVolumeAuthority:
    def __init__(self, coordinator: ExternalAuthorityCurrentnessCoordinator, authority: ExternalSingleVolumeAuthority | None) -> None:
        self.currentness_coordinator = coordinator
        self.authority = authority

    def resolve_for_use(self, **kwargs: object) -> ExternalSingleVolumeAuthority | None:
        del kwargs
        return self.authority

    def is_current_for_use(self, authority: ExternalSingleVolumeAuthority, *, now: datetime) -> bool:
        del now
        return authority == self.authority

    def resolve_historical_for_decision(self, decision: ExternalSingleVolumeDecisionV1) -> ExternalSingleVolumeAuthority | None:
        del decision
        return self.authority


def _single_volume_evaluator(
    tmp_path: Path, *, attested: bool | None, mapping: bool = True
) -> tuple[ExternalUseEvaluator, SealedExternalSubjectV1, _SingleVolumeAuthority]:
    sealed_subject = subject()
    template = policy_template()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id, policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(sealed_subject,), permitted_uses=("SINGLE_VOLUME",),
        authorized_actor_ids=("authority",), active_from=NOW - timedelta(minutes=1),
        active_until=datetime.now(UTC) + timedelta(days=14), synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True).sealed()
    assert policy.policy_digest is not None
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    policy_authority = _PolicyAuthority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"), authority_port=policy_authority,
        authority_currentness_port=policy_authority.bind(coordinator), clock=lambda: NOW, coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)
    report = _report_with_measured_dsm(_report_for_subject(sealed_subject, policy, request_id="single-volume"))
    records: dict[tuple[SealedExternalSubjectV1, str], tuple[tuple[str, object, object], ...]] = {}
    if attested is not None:
        records[(sealed_subject, policy.policy_digest)] = (
            (
                digest("e"),
                SimpleNamespace(evidence_record_digest=digest("e")),
                SimpleNamespace(
                    independent_attestation=object() if attested else None,
                    target_dsm_artifact_id="dsm", target_dsm_observed_sha256=digest("d"),
                ),
            ),
        )
    volume = _SingleVolumeAuthority(
        coordinator,
        ExternalSingleVolumeAuthority(
            zone=SealedZoneReferenceV1(zone_id="zone-1", revision=1, definition_digest=digest("1"), observed_crs_digest=digest("2"), observed_vertical_reference_digest=digest("3")),
            compatibility_mapping_digest=digest("4"), historical_authority_digest=digest("4"), synthetic_test_only=False,
        ) if mapping else None,
    )
    evaluator = ExternalUseEvaluator(
        decisions=ExternalUseDecisionStore(DurableJournal(tmp_path / "decisions.jsonl"), coordinator=coordinator, history_verifier=_SyntheticHistoryVerifier()),
        reconstruction=_Reconstruction(sealed_subject, coordinator),  # type: ignore[arg-type]
        inspections=_Inspections(sealed_subject, report, _receipt(report, policy), coordinator),
        policy_registry=registry,
        evidence_validations=cast(ExternalEvidenceValidationStore, _EvidenceProjection(coordinator, records)),
        coordinator=coordinator,
        single_volume_authority=volume,
    )
    return evaluator, sealed_subject, volume


def test_single_volume_is_eligible_with_attested_evidence_and_mapping(tmp_path: Path) -> None:
    evaluator, sealed_subject, volume = _single_volume_evaluator(tmp_path, attested=True)
    decision = evaluator.request_single_volume(
        sealed_subject, zone_id="zone-1", idempotency_key="sv-eligible", principal=_principal(), now=NOW
    )
    assert isinstance(decision, ExternalSingleVolumeDecisionV1)
    assert decision.verdict is DecisionVerdict.ELIGIBLE
    assert decision.reasons == ("USE_ELIGIBLE",)
    assert decision.evidence_record_digests == (digest("e"),)
    assert volume.authority is not None and decision.zone == volume.authority.zone
    assert decision.compatibility_mapping_digest == digest("4")
    assert evaluator.existing_single_volume_retry(
        sealed_subject, zone_id="zone-1", principal=_principal(), idempotency_key="sv-eligible"
    ) == decision


def test_single_volume_names_unattested_evidence_before_the_mapping(tmp_path: Path) -> None:
    evaluator, sealed_subject, _ = _single_volume_evaluator(tmp_path, attested=False, mapping=False)
    decision = evaluator.request_single_volume(
        sealed_subject, zone_id="zone-1", idempotency_key="sv-unattested", principal=_principal(), now=NOW
    )
    assert decision.verdict is DecisionVerdict.BLOCKED
    assert decision.reasons == ("EVIDENCE_INDEPENDENCE_UNATTESTED",)
    assert decision.remediations == ("ATTEST_INDEPENDENT_EVIDENCE",)


def test_single_volume_without_mapping_is_blocked_with_its_own_reason(tmp_path: Path) -> None:
    evaluator, sealed_subject, _ = _single_volume_evaluator(tmp_path, attested=True, mapping=False)
    decision = evaluator.request_single_volume(
        sealed_subject, zone_id="zone-1", idempotency_key="sv-no-mapping", principal=_principal(), now=NOW
    )
    assert decision.verdict is DecisionVerdict.BLOCKED
    assert decision.reasons == ("SINGLE_VOLUME_MAPPING_UNAVAILABLE",)
    assert decision.remediations == ("AUTHORIZE_SINGLE_VOLUME_MAPPING",)
    assert decision.zone is None and decision.compatibility_mapping_digest is None


def test_single_volume_requires_a_zone_selection(tmp_path: Path) -> None:
    evaluator, sealed_subject, _ = _single_volume_evaluator(tmp_path, attested=True)
    with pytest.raises(ValueError, match="zone"):
        evaluator.request_single_volume(sealed_subject, zone_id="", idempotency_key="sv-zone", principal=_principal(), now=NOW)
```

Check `_Inspections.__init__` positional/keyword signature at `tests/contract/test_external_use_evaluator.py:92` and match it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/contract/test_external_use_evaluator.py -k single_volume -q`
Expected: FAIL with `TypeError: ExternalUseEvaluator.__init__() got an unexpected keyword argument 'single_volume_authority'`

- [ ] **Step 3: Implement the evaluator**

1. Imports: `ExternalSingleVolumeDecisionV1`, `ExternalSingleVolumeAuthority`, `ExternalSingleVolumeAuthorityPort`, `DefaultClosedExternalSingleVolumeAuthorityPort`.

2. Reason map:

```python
PAIR_REASON_REMEDIATIONS: dict[str, str] = {
    ...existing entries...,
    "SINGLE_VOLUME_MAPPING_UNAVAILABLE": "AUTHORIZE_SINGLE_VOLUME_MAPPING",
}
```

3. Request model + response unchanged:

```python
class ExternalSingleVolumeDecisionRequest(CamelModel):
    zone_id: str = Field(min_length=1, max_length=255)
```

4. `CoreExternalUseDecisionHistoryVerifier.__init__` gains `single_volume_authority: ExternalSingleVolumeAuthorityPort | None = None` (stored); `verify` dispatches `isinstance(candidate, ExternalSingleVolumeDecisionV1)` → `_verify_single_volume`:

```python
    def _verify_single_volume(self, candidate: ExternalSingleVolumeDecisionV1) -> bool:
        policy_digest, report_digest = candidate.policy_digest, candidate.inspection_report_digest
        if policy_digest is None or report_digest is None or self._single_volume_authority is None:
            return False
        if not self._policy_registry.historical_use_permitted(
            policy_digest, use="SINGLE_VOLUME", subjects=(candidate.subject,), at=candidate.decided_at
        ):
            return False
        policy = self._policy_registry.resolve(policy_digest).policy
        report = self._inspections.historical_report(candidate.subject, report_digest=report_digest, policy_digest=policy_digest)
        if (
            policy is None
            or self._reconstruction.resolve_sealed_subject(candidate.subject) is None
            or not ExternalUseEvaluator._report_binds(candidate.subject, report, policy)
        ):
            return False
        assert report is not None
        authority = self._single_volume_authority.resolve_historical_for_decision(candidate)
        if (
            authority is None
            or candidate.compatibility_mapping_digest != authority.compatibility_mapping_digest
            or candidate.zone != authority.zone
            or len(candidate.evidence_record_digests) != 1
        ):
            return False
        evidence = self._evidence_validations.record_for_use(
            candidate.evidence_record_digests[0], subject=candidate.subject, policy_digest=policy_digest
        )
        if evidence is None:
            return False
        _record, context = evidence
        return context.independent_attestation is not None and ExternalUseEvaluator._report_measures_dsm(
            report, context.target_dsm_artifact_id, context.target_dsm_observed_sha256
        )
```

5. `ExternalUseEvaluator.__init__` gains `single_volume_authority: ExternalSingleVolumeAuthorityPort | None = None` with the same coordinator check as the relative port; default `DefaultClosedExternalSingleVolumeAuthorityPort(currentness_coordinator=coordinator)`.

6. Methods (place after `existing_pair_retry`):

```python
    def request_single_volume(
        self, subject: SealedExternalSubjectV1, *, zone_id: str, idempotency_key: str,
        principal: Principal, now: datetime,
    ) -> ExternalSingleVolumeDecisionV1:
        self._require_scope(principal, subject)
        if not zone_id or not zone_id.strip():
            raise ValueError("single volume requires a zone selection")
        intent = ExternalDecisionIntent(requested_use="SINGLE_VOLUME", subject=subject, requested_zone_id=zone_id)
        existing = self._decisions.existing_for_intent(intent=intent, principal=principal, idempotency_key=idempotency_key)
        if existing is not None:
            if not isinstance(existing, ExternalSingleVolumeDecisionV1):
                raise ValueError("idempotency decision operation conflicts")
            self._decisions.reconcile_pending()
            return existing
        evaluation_identity = self._decisions.evaluation_identity(intent=intent, principal=principal, idempotency_key=idempotency_key)
        snapshot = self._single_snapshot(subject, "SINGLE_VOLUME")
        volume = (
            self._single_volume_authority.resolve_for_use(subject=subject, zone_id=zone_id, policy=snapshot.policy, now=now)
            if snapshot.policy is not None else None
        )
        evidence_reason = self._single_volume_evidence_block_reason(subject, snapshot) if snapshot.policy is not None else None
        with self._coordinator.guarded_read():
            current = self._single_still_current(subject, "SINGLE_VOLUME", snapshot, now=now)
            if volume is not None and not self._single_volume_authority.is_current_for_use(volume, now=now):
                volume = None
            candidate = self._single_volume_candidate(
                subject, zone_id, current, volume, evaluation_identity, now, evidence_reason=evidence_reason
            )
            return cast(ExternalSingleVolumeDecisionV1, self._record(candidate, intent, principal, idempotency_key))

    def existing_single_volume_retry(
        self, subject: SealedExternalSubjectV1, *, zone_id: str, principal: Principal, idempotency_key: str
    ) -> ExternalSingleVolumeDecisionV1 | None:
        intent = ExternalDecisionIntent(requested_use="SINGLE_VOLUME", subject=subject, requested_zone_id=zone_id)
        existing = self._decisions.existing_for_intent(intent=intent, principal=principal, idempotency_key=idempotency_key)
        return existing if isinstance(existing, ExternalSingleVolumeDecisionV1) else None
```

Check `_single_snapshot(subject, use)` signature (it selects a policy via `select_for_use(use, (subject,))`); if it also loads display state that is fine — single-volume ignores it.

```python
    def _single_volume_evidence_block_reason(self, subject: SealedExternalSubjectV1, snapshot: _SingleSnapshot) -> str | None:
        policy, report = snapshot.policy, snapshot.inspection.report
        if policy is None:
            return "POLICY_UNAVAILABLE"
        if report is None:
            return "INSPECTION_REPORT_BINDING_INVALID"
        matching, blocker = self._evidence_binding(subject, policy, report, locally_current=False)
        return None if matching is not None else blocker

    def _single_volume_reason(
        self, subject: SealedExternalSubjectV1, snapshot: _SingleSnapshot,
        volume: ExternalSingleVolumeAuthority | None, *, evidence_reason: str | None,
    ) -> tuple[str | None, tuple[str, ...]]:
        if snapshot.revision is None:
            return "SUBJECT_NOT_SEALED", ()
        if snapshot.policy is None:
            return "POLICY_UNAVAILABLE", ()
        report = snapshot.inspection.report
        if not self._report_binds(subject, report, snapshot.policy):
            return "INSPECTION_REPORT_BINDING_INVALID", ()
        if evidence_reason is not None:
            return evidence_reason, ()
        if volume is None:
            return "SINGLE_VOLUME_MAPPING_UNAVAILABLE", ()
        if volume.zone.zone_id == "" or volume.zone.revision != 1:
            return "VOLUME_ZONE_BINDING_INVALID", ()
        assert report is not None
        matching, blocker = self._evidence_binding(subject, snapshot.policy, report)
        if matching is None:
            return blocker, ()
        return None, (matching,)

    def _single_volume_candidate(
        self, subject: SealedExternalSubjectV1, requested_zone_id: str, snapshot: _SingleSnapshot,
        volume: ExternalSingleVolumeAuthority | None, evaluation_identity: str, now: datetime,
        *, evidence_reason: str | None,
    ) -> ExternalSingleVolumeDecisionV1:
        reason, evidence = self._single_volume_reason(subject, snapshot, volume, evidence_reason=evidence_reason)
        eligible = reason is None
        policy, report = snapshot.policy, snapshot.inspection.report
        decision_id = self._decision_id({
            "intent": ExternalDecisionIntent(requested_use="SINGLE_VOLUME", subject=subject, requested_zone_id=requested_zone_id).payload(),
            "policy": policy.policy_digest if policy else None,
            "zone": volume.zone.model_dump(by_alias=True, mode="json") if volume else None,
            "compatibilityMapping": volume.compatibility_mapping_digest if volume else None,
            "evaluationIdentity": evaluation_identity,
        })
        return ExternalSingleVolumeDecisionV1(
            decision_id=decision_id,
            subject=subject,
            subject_digest=subject.canonical_digest(),
            policy_digest=policy.policy_digest if eligible and policy else None,
            inspection_report_digest=report.report_digest if eligible and report else None,
            evidence_record_digests=evidence if eligible else (),
            zone=volume.zone if eligible and volume else None,
            compatibility_mapping_digest=volume.compatibility_mapping_digest if eligible and volume else None,
            verdict=DecisionVerdict.ELIGIBLE if eligible else DecisionVerdict.BLOCKED,
            reasons=("USE_ELIGIBLE",) if eligible else (reason or "POLICY_UNAVAILABLE",),
            remediations=("CURRENT_DEPENDENCIES_RETAINED",) if eligible else (self._remediation(reason),),
            decided_at=now,
        ).sealed()
```

7. Route, placed after `request_pair` in the router builder:

```python
    @router.post(base + "/single-volume", response_model=ExternalUseDecisionResponse, status_code=201)
    def request_single_volume(
        work_order_id: str, submission_ref: str, revision: int,
        request: ExternalSingleVolumeDecisionRequest,
        idempotency_key: str = Depends(idempotency_header),  # noqa: B008
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalUseDecisionResponse:
        human(principal)
        subject = subject_for(work_order_id, submission_ref, revision, principal)
        try:
            with work_orders.guard_new_external_intent(
                work_order_id, organization_id=principal.organization_id,
                is_durable_retry=lambda: evaluator.existing_single_volume_retry(
                    subject, zone_id=request.zone_id, principal=principal, idempotency_key=idempotency_key
                ) is not None,
            ):
                return write_result(evaluator.request_single_volume(
                    subject, zone_id=request.zone_id, idempotency_key=idempotency_key,
                    principal=principal, now=datetime.now(UTC),
                ))
        except ExternalUseDecisionConflictError as exc:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT") from exc
        except ValueError as exc:
            raise HTTPException(422, "EXTERNAL_USE_SELECTION_INVALID") from exc
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(409, str(exc)) from exc
            raise
```

Check `write_result` handles any `DecisionCandidate` (it wraps `candidate.model_dump`) and `get_decision` / `get_scoped` do not `isinstance`-filter to two types.

8. Blocker catalog — add to `contracts/catalogs/external-use-blockers.v1.json` `reasons`:

```json
"SINGLE_VOLUME_MAPPING_UNAVAILABLE": {"title": "단일 시점 체적 매핑이 없습니다", "explanation": "이 산출물과 구역을 단일 시점 체적으로 측정해도 된다는 호환성 매핑이 등록되어 있지 않거나 만료되었습니다.", "owner": "ADMIN", "target": "MAPPING"}
```

and to `remediations`:

```json
"AUTHORIZE_SINGLE_VOLUME_MAPPING": {"step": "관리자에게 이 산출물과 구역에 대한 단일 시점 체적 매핑 등록을 요청하세요.", "owner": "ADMIN", "target": "MAPPING"}
```

then `cp contracts/catalogs/external-use-blockers.v1.json apps/dashboard/src/lib/external-use-blockers.generated.json`.

9. OpenAPI — add after the `pair` path, copying the `single` entry with path suffix `/use-decisions/single-volume`, summary `Resolve and persist a scoped SINGLE_VOLUME external use decision`, description noting one sealed DSM epoch, one attested checkpoint evidence record, an ACTIVE WorkArea and an admitted single mapping; request body `properties: { zoneId: { type: string, minLength: 1, maxLength: 255 } }, required: [zoneId]`; same responses.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/contract/test_external_use_evaluator.py tests/contract/test_external_use_blockers.py tests/contract/test_openapi_core_contract.py -q` (use the actual openapi test file name from `ls tests/contract | grep -i openapi`; skip if none).
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/core/src/ksi_core/domains/external/quantity/external_use_evaluator.py contracts/catalogs/external-use-blockers.v1.json apps/dashboard/src/lib/external-use-blockers.generated.json contracts/api/openapi-core.yaml tests/contract/test_external_use_evaluator.py
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "feat(core): SINGLE_VOLUME use decision with its own blocker and route (SV-1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Provider actions `ADMIT_SINGLE_MAPPING` / `REVOKE_SINGLE_MAPPING` and composition wiring

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/authority/provider_loading.py:425-500`
- Modify: `services/core/src/ksi_core/domains/external/authority/external_authority_provider.py:428-460`
- Modify: `services/core/src/ksi_core/composition/external_graph.py:227-255`
- Test: `tests/contract/test_external_authority_provider_contract.py`

**Interfaces:**
- Consumes: Task 5 record, Task 6 catalog methods, Task 7 evaluator/verifier keyword.
- Produces: signed administration actions `ADMIT_SINGLE_MAPPING` (payload key `mapping`, validated via `ExternalSingleVolumeCompatibilityRecord.from_event_payload`) and `REVOKE_SINGLE_MAPPING` (payload key `mappingDigest`), rank 1; the evaluator and verifier receive `single_volume_authority=external_volume_mapping.single_mapping_port` when the mapping catalog exists.

- [ ] **Step 1: Write the failing provider test**

In `tests/contract/test_external_authority_provider_contract.py`, next to the existing `ADMIT_MAPPING` case (around line 1749), add a test that builds a single mapping through the production-flow helpers. The relative case constructs `mapping = production_flow._mapping(...)`; add a sibling helper in `tests/contract/test_external_quantitative_production_flow.py`:

```python
def _single_mapping(*, subject: Any, revision: Any, report: Any, evidence_record: Any, policy: Any, area: Any, now: datetime, catalog_digest: str) -> Any:
    from ksi_core.external_single_volume_authority import ExternalSingleVolumeCompatibilityRecord

    dsm = next(entry for entry in revision.manifest.entries if entry.kind is ProcessingArtifactKind.DSM)
    binding = ExternalVolumeInputBindingV1(
        subject=subject, inspection_report_digest=report.report_digest, dsm_artifact_id=dsm.artifact_id,
        observed_sha256="sha256:" + dsm.observed_sha256, observed_size_bytes=dsm.observed_size_bytes,
        observed_crs_digest=_digest("observed-crs-5186"),
        observed_vertical_reference_digest=_observed_vertical_reference().canonical_digest(),
        captured_from=revision.submission.input_declaration.capture_started_at,
        captured_to=revision.submission.input_declaration.capture_ended_at,
    )
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id="org-a", site_id="site-a", work_area_id=area.work_area_id, polygon=area.polygon, crs=area.crs,
        observed_crs_digest=_digest("observed-crs-5186"),
        analysis_vertical_reference_digest=_observed_vertical_reference().canonical_digest(),
    ).sealed()
    return ExternalSingleVolumeCompatibilityRecord(
        organization_id="org-a", site_id="site-a", target=binding, zone_snapshot=zone,
        validation_policy_digest=policy.policy_digest, external_profile="external-geotiff-profile.v1",
        grammar_digest=policy.grammar_digest, inspector_build_digest=policy.parser_build_digest,
        evidence_record_digests=(evidence_record.evidence_record_digest,), execution_policy_ref=catalog_digest,
        valid_from=now - timedelta(hours=1), valid_until=now + timedelta(hours=1),
    ).sealed()
```

Then in the provider contract test, duplicate the block that admits `mapping_action` (lines ~1749–1790) as `test_signed_provider_admits_and_revokes_single_mapping`, using the same seeded policy/revision/report/evidence for the *baseline* epoch only (the relative test seeds two epochs; take index 0), with actions:

```python
        single = production_flow._single_mapping(subject=subjects[0], revision=revisions[0], report=reports[0], evidence_record=evidence_records[0], policy=policy, area=area, now=now, catalog_digest=catalog_digest)
        admit = {"actionId": "provider-admit-single", "kind": "ADMIT_SINGLE_MAPPING", "effectiveAt": iso(now), "actorId": administrator,
                 "mapping": {"mappingRecordDigest": single.mapping_digest, **single.canonical_payload()}}
        revoke = {"actionId": "provider-revoke-single", "kind": "REVOKE_SINGLE_MAPPING", "effectiveAt": iso(now + timedelta(seconds=1)), "actorId": administrator,
                 "mappingDigest": single.mapping_digest}
```

and assert the catalog journal kinds are `["external-quantitative-single-mapping-activated", "external-quantitative-single-mapping-revoked"]`. The policy admitted in that test must include `"SINGLE_VOLUME"` in its permitted uses and `SingleVolumeCompatibilityRuleDescriptorV1().canonical_digest()` in `compatibility_mapping_digests` — extend the helper `_admit_policy`/`_signed_policy_admission` with keyword parameters `extra_uses: tuple[str, ...] = ()` and `extra_mapping_digests: tuple[str, ...] = ()` that default to the current behaviour.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --locked pytest tests/contract/test_external_authority_provider_contract.py -k single_mapping -q`
Expected: FAIL with `ValueError: quantitative administration action is unsupported`

- [ ] **Step 3: Implement the provider actions and wiring**

`provider_loading.py` — in `ranks` add `"ADMIT_SINGLE_MAPPING": 1, "REVOKE_SINGLE_MAPPING": 1`; in the required-key chain add `elif kind == "ADMIT_SINGLE_MAPPING": required.add("mapping")` and treat `REVOKE_SINGLE_MAPPING` like `REVOKE_MAPPING` (`required.add("mappingDigest")`, digest regex check); validation branch `elif kind == "ADMIT_SINGLE_MAPPING": ExternalSingleVolumeCompatibilityRecord.from_event_payload(action["mapping"])`.

`external_authority_provider.py::_apply_mapping_actions` — add:

```python
            elif action.kind == "ADMIT_SINGLE_MAPPING":
                if action.actor_id != self._config.catalog_administration_actor_id:
                    raise ValueError("mapping action actor is not the configured catalog administrator")
                single = ExternalSingleVolumeCompatibilityRecord.from_event_payload(action.payload["mapping"])
                if single.organization_id != self.organization_id or catalog.admit_single_mapping(single, actor=action.actor_id, now=action.effective_at) is None:
                    raise ExternalAuthorityProviderError("signed single mapping admission was not applied")
            elif action.kind == "REVOKE_SINGLE_MAPPING":
                if action.actor_id != self._config.catalog_administration_actor_id or not catalog.revoke_single_mapping(
                    cast(str, action.payload["mappingDigest"]), actor=action.actor_id, now=action.effective_at
                ):
                    raise ExternalAuthorityProviderError("signed single mapping revocation was not applied")
```

`external_graph.py` — compute once:

```python
    external_single_volume_mapping = (
        external_volume_mapping.single_mapping_port
        if external_volume_mapping is not None and hasattr(external_volume_mapping, "single_mapping_port")
        else None
    )
```

and pass `single_volume_authority=external_single_volume_mapping` to both `CoreExternalUseDecisionHistoryVerifier(...)` and `ExternalUseEvaluator(...)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/contract/test_external_authority_provider_contract.py tests/contract/test_external_quantitative_production_flow.py tests/replay/test_external_authority_provider_replay.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/core/src/ksi_core/domains/external/authority/provider_loading.py services/core/src/ksi_core/domains/external/authority/external_authority_provider.py services/core/src/ksi_core/composition/external_graph.py tests/contract/test_external_authority_provider_contract.py tests/contract/test_external_quantitative_production_flow.py
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "feat(core): signed single-mapping admission and evaluator wiring (SV-1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: SINGLE_VOLUME decision on the real durable graph, gates, ledger

**Files:**
- Test: `tests/contract/test_external_quantitative_production_flow.py` (new test function)
- Modify: `docs/superpowers/plans/2026-09-17-single-volume-sv1.md` (this file: tick boxes), `.opencode/working-state.md`

**Interfaces:**
- Consumes everything above through the assembled app (`_assemble`, `_register_signed_provider_site_and_area`, `_submission`, `_sealed_revision`, `_admit_policy`, `_inspect`, `_seal_evidence`, `_validate_evidence`, `_signed_provider_config`).

- [ ] **Step 1: Write the integrated test**

Add `test_single_volume_decision_is_eligible_on_the_real_graph` to `tests/contract/test_external_quantitative_production_flow.py`, modelled on the first ~120 lines of `test_signed_provider_drives_complete_external_relative_volume_lifecycle` (line 1733): seed the site and area, one submission/sealed revision with a DSM, admit a policy whose permitted uses include `"SINGLE_VOLUME"` and whose `compatibility_mapping_digests` include `SingleVolumeCompatibilityRuleDescriptorV1().canonical_digest()`, inspect, seal + validate attested evidence, write a signed provider snapshot with one `ADMIT_SINGLE_MAPPING` action built by `_single_mapping(...)`, then:

```python
    response = client.post(
        f"/v1/observation-work-orders/{order.work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/1/use-decisions/single-volume",
        json={"zoneId": area.work_area_id},
        headers={**operator_headers, "Idempotency-Key": "sv-real-graph"},
    )
    assert response.status_code == 201, response.text
    decision = response.json()["decision"]
    assert decision["contractVersion"] == "external-single-volume-decision.v1"
    assert decision["verdict"] == "ELIGIBLE"
    assert decision["zone"]["zoneId"] == area.work_area_id
    assert decision["compatibilityMappingDigest"] == single.mapping_digest
    assert len(decision["evidenceRecordDigests"]) == 1
```

Reuse the exact client/header helpers the neighbouring test uses (read them; do not invent names).

- [ ] **Step 2: Run the test to verify it passes (or fix what it exposes)**

Run: `uv run --locked pytest tests/contract/test_external_quantitative_production_flow.py -k single_volume -q`
Expected: PASS. Any failure here is a real integration gap in Tasks 3–8; fix the owning task's code, not the test.

- [ ] **Step 3: Run the full gates**

```bash
uv run --locked ruff check . && uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest tests/contract tests/replay packages/change-detection/tests -q
```

Expected: all green. Fix lint/type findings in place.

- [ ] **Step 4: Update checkpoint and commit**

Rewrite `.opencode/working-state.md` (≤80 lines): HEAD, "SV-1 done: contracts/algorithm/policy use/decision/catalog/evaluator/provider/wiring; next SV-2 (store + routes + worker)". Tick every box in this plan.

```bash
git add tests/contract/test_external_quantitative_production_flow.py docs/superpowers/plans/2026-09-17-single-volume-sv1.md .opencode/working-state.md
git -c user.name=khakiskech -c user.email=khakiskech@gmail.com commit -m "test(core): SINGLE_VOLUME decision eligible on the real graph; SV-1 closed

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage (SV-1 = §4, §5, §6):** §4 algorithm → Task 2; §5 five models + schemas → Task 1 (payload schema embedded in the report schema, as the relative family does); §6.1 record/catalog/participants → Tasks 5–6; §6.2 execution template → deferred to SV-2 by design (spec §10 says execution activation belongs with the store); §6.3 provider actions → Task 8; §6.4 decisions → Task 4; §6.5 evaluator/route/blocker → Task 7; policy use catalogue (implied by §6.1 "active validation policy permitting SINGLE_VOLUME") → Task 3; integrated proof → Task 9.
- **Placeholders:** none; every step carries code or an exact edit instruction with the target lines.
- **Type consistency:** `ExternalSingleVolumeAuthority` (Task 5) is what Task 6 returns and Task 7 consumes; `single_mapping_port` (Task 6) is what Task 8 wires; `resolve_current_single_volume_for_issue` / `resolve_historical_single_volume` (Task 4) are the joins SV-2's store will bind; reason/remediation strings match between Task 7 code, the catalog JSON and the Task 4/7 tests.
