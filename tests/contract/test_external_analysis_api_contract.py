"""Public Analysis API wire contract stays selector-only and numeric-honest."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from ksi_event_contracts.external_analysis_api import (
    AnalysisBlockerV1,
    AnalysisEvidenceReferenceV1,
    AnalysisExecutionStateV1,
    AnalysisMetricsV1,
    AnalysisObservationSelectorV1,
    AnalysisResultV1,
    AnalysisSuitabilityStateV1,
    AnalysisViewV1,
    CreateAnalysisRequestV1,
)
from ksi_event_contracts.external_analysis_api_v2 import (
    AnalysisCheckpointEvidenceItemV2,
    AnalysisCoverageRangeV2,
    AnalysisCoverageSummaryV2,
    AnalysisEpochEvidenceItemV2,
    AnalysisEvaluationEvidenceItemV2,
    AnalysisEvidencePageV2,
    AnalysisLimitationEvidenceItemV2,
    AnalysisListItemV2,
    AnalysisListPageV2,
    AnalysisResultSummaryV2,
    AnalysisViewV2,
)
from ksi_event_contracts.external_relative_volume_calculation import RelativeVolumeCoverageWitnessV2
from pydantic import ValidationError


def _selector(work_order_id: str) -> AnalysisObservationSelectorV1:
    return AnalysisObservationSelectorV1(
        work_order_id=work_order_id,
        submission_ref="ers-v1-" + "a" * 64,
        revision=1,
    )


def test_create_request_is_limited_to_two_frozen_revision_selectors() -> None:
    """A caller cannot smuggle profile, runtime, artifact, or accuracy authority into create."""
    request = CreateAnalysisRequestV1(
        baseline=_selector("work-order-t0"),
        current=_selector("work-order-t1"),
    )

    assert request.model_dump(by_alias=True) == {
        "baseline": {
            "workOrderId": "work-order-t0",
            "submissionRef": "ers-v1-" + "a" * 64,
            "revision": 1,
        },
        "current": {
            "workOrderId": "work-order-t1",
            "submissionRef": "ers-v1-" + "a" * 64,
            "revision": 1,
        },
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CreateAnalysisRequestV1.model_validate(
            {
                **request.model_dump(by_alias=True),
                "profileDigest": "sha256:" + "0" * 64,
            }
        )


def test_blocked_view_carries_structured_blocker_without_numeric_result() -> None:
    """Missing vertical evidence is a durable typed block, never a fabricated zero volume."""
    view = AnalysisViewV1(
        analysis_id="analysis-1",
        site_id="site-1",
        work_area_id="area-1",
        baseline=_selector("work-order-t0"),
        current=_selector("work-order-t1"),
        execution_state=AnalysisExecutionStateV1.NOT_STARTED,
        suitability_state=AnalysisSuitabilityStateV1.BLOCKED,
        blockers=(
            AnalysisBlockerV1(
                code="MISSING_VERTICAL_REFERENCE",
                epoch="BASELINE",
                detail="The selected baseline DSM has no observed vertical reference.",
            ),
        ),
        evidence_refs=(),
        result=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert view.result is None
    assert view.blockers[0].code == "MISSING_VERTICAL_REFERENCE"


def test_completed_provisional_view_exposes_metrics_and_resolvable_evidence() -> None:
    """A completed local result links to evidence and remains explicitly provisional."""
    result = AnalysisResultV1(
        result_id="analysis-result-2",
        result_revision=1,
        report_digest="sha256:" + "a" * 64,
        numeric_result_identity_digest="sha256:" + "b" * 64,
        computed_at=datetime(2026, 9, 22, tzinfo=UTC),
        metrics=AnalysisMetricsV1(
            cut_m3=1.0,
            fill_m3=2.0,
            net_m3=1.0,
            threshold_m=0.0,
            uncertainty_m3=None,
        ),
        coverage=RelativeVolumeCoverageWitnessV2(
            rows=2,
            columns=2,
            row_offset=0,
            column_offset=0,
            selected_mask_b64="8A==",
            common_valid_mask_b64="8A==",
            unavailable_mask_b64="AA==",
            threshold_excluded_mask_b64="AA==",
            selected_cell_count=4,
            common_valid_cell_count=4,
            unavailable_cell_count=0,
            threshold_excluded_cell_count=0,
            cell_area_m2=1.0,
            selected_area_m2=4.0,
            common_valid_area_m2=4.0,
            bounds=(0.0, 0.0, 2.0, 2.0),
        ).sealed(),
    )
    view = AnalysisViewV1(
        analysis_id="analysis-2",
        site_id="site-1",
        work_area_id="area-1",
        baseline=_selector("work-order-t0"),
        current=_selector("work-order-t1"),
        execution_state=AnalysisExecutionStateV1.COMPLETED,
        suitability_state=AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
        blockers=(),
        evidence_refs=(
            AnalysisEvidenceReferenceV1(
                kind="INSPECTION_REPORT",
                record_id="inspection-1",
                href="/v1/sites/site-1/analyses/analysis-2/evidence",
            ),
        ),
        result=result,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert view.result is not None
    assert view.result.metrics.net_m3 == 1.0
    assert view.result.metrics.uncertainty_m3 is None
    assert view.evidence_refs[0].href.startswith("/v1/")


@pytest.mark.parametrize(
    "execution_state,suitability_state",
    [
        (AnalysisExecutionStateV1.NOT_STARTED, AnalysisSuitabilityStateV1.BLOCKED),
        (AnalysisExecutionStateV1.QUEUED, AnalysisSuitabilityStateV1.REMEDIATION_REQUIRED),
        (AnalysisExecutionStateV1.COMPLETED, AnalysisSuitabilityStateV1.REASSESSMENT_REQUIRED),
    ],
)
def test_withheld_states_reject_a_nonnull_numeric_result(
    execution_state: AnalysisExecutionStateV1,
    suitability_state: AnalysisSuitabilityStateV1,
) -> None:
    """A stale, blocked, or remediation projection cannot leak an historic result."""
    completed = AnalysisViewV1(
        analysis_id="analysis-2",
        site_id="site-1",
        work_area_id="area-1",
        baseline=_selector("work-order-t0"),
        current=_selector("work-order-t1"),
        execution_state=AnalysisExecutionStateV1.COMPLETED,
        suitability_state=AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
        blockers=(),
        evidence_refs=(),
        result=AnalysisResultV1(
            result_id="analysis-result-2",
            result_revision=1,
            report_digest="sha256:" + "a" * 64,
            numeric_result_identity_digest="sha256:" + "b" * 64,
            computed_at=datetime(2026, 9, 22, tzinfo=UTC),
            metrics=AnalysisMetricsV1(cut_m3=0.0, fill_m3=0.0, net_m3=0.0, threshold_m=0.0),
            coverage=RelativeVolumeCoverageWitnessV2(
                rows=1,
                columns=1,
                row_offset=0,
                column_offset=0,
                selected_mask_b64="gA==",
                common_valid_mask_b64="gA==",
                unavailable_mask_b64="AA==",
                threshold_excluded_mask_b64="AA==",
                selected_cell_count=1,
                common_valid_cell_count=1,
                unavailable_cell_count=0,
                threshold_excluded_cell_count=0,
                cell_area_m2=1.0,
                selected_area_m2=1.0,
                common_valid_area_m2=1.0,
                bounds=(0.0, 0.0, 1.0, 1.0),
            ).sealed(),
        ),
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    payload = completed.model_dump()
    payload["execution_state"] = execution_state
    payload["suitability_state"] = suitability_state
    if suitability_state is AnalysisSuitabilityStateV1.BLOCKED:
        payload["blockers"] = [{"code": "MISSING_VERTICAL_REFERENCE"}]

    with pytest.raises(ValidationError, match="numeric result"):
        AnalysisViewV1.model_validate(payload)


def test_published_json_schema_validates_the_same_closed_request_and_view() -> None:
    """The static integration contract must not drift from the shared public DTO."""
    schema_path = Path(__file__).resolve().parents[2] / "contracts/schemas/analysis-api.v1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    request = CreateAnalysisRequestV1(
        baseline=_selector("work-order-t0"), current=_selector("work-order-t1")
    )
    request_errors = list(
        validator.iter_errors({"createRequest": request.model_dump(by_alias=True)})
    )
    assert request_errors == []

    malformed = request.model_dump(by_alias=True)
    malformed["runtimeImageOciDigest"] = "sha256:" + "0" * 64
    assert list(validator.iter_errors({"createRequest": malformed}))


def test_static_schema_enforces_the_dto_state_invariants() -> None:
    """Portable JSON Schema rejects invalid state/result/blocker combinations."""
    schema_path = Path(__file__).resolve().parents[2] / "contracts/schemas/analysis-api.v1.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    valid_blocked = {
        "analysisId": "analysis-1",
        "siteId": "site-1",
        "workAreaId": "area-1",
        "baseline": _selector("work-order-t0").model_dump(by_alias=True),
        "current": _selector("work-order-t1").model_dump(by_alias=True),
        "executionState": "NOT_STARTED",
        "suitabilityState": "BLOCKED",
        "blockers": [{"code": "MISSING_VERTICAL_REFERENCE"}],
        "evidenceRefs": [],
        "authority": {},
        "result": None,
        "createdAt": "2026-09-22T00:00:00Z",
    }
    assert list(validator.iter_errors({"view": valid_blocked})) == []
    AnalysisViewV1.model_validate(valid_blocked)

    terminal_coverage_block = {
        **valid_blocked,
        "executionState": "FAILED",
        "blockers": [{"code": "INSUFFICIENT_COMMON_VALID_COVERAGE"}],
    }
    assert list(validator.iter_errors({"view": terminal_coverage_block})) == []
    AnalysisViewV1.model_validate(terminal_coverage_block)

    for invalid_execution_state in ("QUEUED", "RUNNING", "COMPLETED"):
        invalid_blocked_state = {
            **terminal_coverage_block,
            "executionState": invalid_execution_state,
        }
        assert list(validator.iter_errors({"view": invalid_blocked_state}))
        with pytest.raises(ValidationError):
            AnalysisViewV1.model_validate(invalid_blocked_state)

    wrong_terminal_failure = {
        **terminal_coverage_block,
        "blockers": [{"code": "ANALYSIS_EXECUTION_FAILED"}],
    }
    assert list(validator.iter_errors({"view": wrong_terminal_failure}))
    with pytest.raises(ValidationError):
        AnalysisViewV1.model_validate(wrong_terminal_failure)

    blocked_without_reason = {**valid_blocked, "blockers": []}
    assert list(validator.iter_errors({"view": blocked_without_reason}))
    with pytest.raises(ValidationError, match="blocked analysis requires"):
        AnalysisViewV1.model_validate(blocked_without_reason)

    completed_without_result = {
        **valid_blocked,
        "executionState": "COMPLETED",
        "suitabilityState": "PROVISIONAL_ACCURACY_UNVERIFIED",
        "blockers": [],
    }
    assert list(validator.iter_errors({"view": completed_without_result}))
    with pytest.raises(ValidationError, match="requires a numeric result"):
        AnalysisViewV1.model_validate(completed_without_result)


def test_static_contract_exposes_sealed_evidence_authority_fields() -> None:
    """Evidence GET exposes only the sealed AP/NX facts required to interpret a result."""
    schema_path = Path(__file__).resolve().parents[2] / "contracts/schemas/analysis-api.v1.json"
    definitions = json.loads(schema_path.read_text(encoding="utf-8"))["$defs"]

    assert definitions["EpochEvidence"]["properties"]["inspectionReportRef"] == {
        "$ref": "#/$defs/EvidenceReference"
    }
    assert definitions["AnalysisEvidenceViewV1"]["properties"]["calculation"] == {
        "anyOf": [
            {"$ref": "#/$defs/CalculationIdentityEvidence"},
            {"type": "null"},
        ]
    }
    assert definitions["AnalysisEvidenceViewV1"]["properties"]["evaluations"] == {
        "type": "array",
        "items": {"$ref": "#/$defs/EvaluationEvidence"},
        "maxItems": 2,
    }
    assert definitions["CalculationIdentityEvidence"]["properties"] == {
        "calculationId": {"type": "string", "minLength": 1, "maxLength": 255},
        "workAreaDefinitionDigest": {"$ref": "#/$defs/Digest"},
        "baselineInputDigest": {"$ref": "#/$defs/Digest"},
        "currentInputDigest": {"$ref": "#/$defs/Digest"},
        "policy": {"$ref": "#/$defs/PolicyEvidence"},
        "runtime": {"$ref": "#/$defs/RuntimeEvidence"},
    }


def test_static_openapi_declares_all_frozen_public_paths_and_required_idempotency_header() -> None:
    """The Dashboard contract is static, not merely a generated FastAPI side effect."""
    document = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "contracts/api/openapi-core.yaml").read_text(
            encoding="utf-8"
        )
    )
    paths = document["paths"]
    public = {
        "/v1/sites/{site_id}/analysis-observations": "get",
        "/v1/sites/{site_id}/work-areas/{work_area_id}/analyses": "post",
        "/v1/sites/{site_id}/analyses": "get",
        "/v1/sites/{site_id}/analyses/{analysis_id}": "get",
        "/v1/sites/{site_id}/analyses/{analysis_id}/result": "get",
        "/v1/sites/{site_id}/analyses/{analysis_id}/evidence": "get",
    }
    assert {path: next(iter(paths[path])) for path in public} == public
    create = paths["/v1/sites/{site_id}/work-areas/{work_area_id}/analyses"]["post"]
    header = next(item for item in create["parameters"] if item["name"] == "Idempotency-Key")
    assert header["in"] == "header"
    assert header["required"] is True
    assert create["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CreateAnalysisRequestV1"
    }
    schemas = document["components"]["schemas"]
    assert schemas["AnalysisEpochEvidenceV1"]["properties"]["inspectionReportRef"] == {
        "$ref": "#/components/schemas/AnalysisEvidenceReferenceV1"
    }
    assert schemas["AnalysisEvidenceViewV1"]["properties"]["calculation"] == {
        "anyOf": [
            {"$ref": "#/components/schemas/AnalysisCalculationIdentityEvidenceV1"},
            {"type": "null"},
        ]
    }
    assert schemas["AnalysisEvidenceViewV1"]["properties"]["evaluations"] == {
        "items": {"$ref": "#/components/schemas/AnalysisEvaluationEvidenceV1"},
        "type": "array",
        "maxItems": 2,
        "title": "Evaluations",
        "default": [],
    }


def test_static_openapi_declares_identity_bound_external_ai_acknowledgment() -> None:
    """All six routes document that identity and live consent govern external AI access."""
    document = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "contracts/api/openapi-core.yaml").read_text(
            encoding="utf-8"
        )
    )
    paths = document["paths"]
    public = {
        "/v1/sites/{site_id}/analysis-observations": ("get", "200"),
        "/v1/sites/{site_id}/work-areas/{work_area_id}/analyses": ("post", "202"),
        "/v1/sites/{site_id}/analyses": ("get", "200"),
        "/v1/sites/{site_id}/analyses/{analysis_id}": ("get", "200"),
        "/v1/sites/{site_id}/analyses/{analysis_id}/result": ("get", "200"),
        "/v1/sites/{site_id}/analyses/{analysis_id}/evidence": ("get", "200"),
    }
    for path, (method, success) in public.items():
        operation = paths[path][method]
        purpose = next(
            item for item in operation["parameters"] if item["name"] == "X-KSI-Access-Purpose"
        )
        assert purpose == {
            "name": "X-KSI-Access-Purpose",
            "in": "header",
            "required": False,
            "schema": {"type": "string", "enum": ["EXTERNAL_AI"]},
            "description": (
                "Compatibility hint only; it does not identify the caller or grant or skip "
                "consent. Core derives external AI access from the authenticated "
                "ANALYSIS_MCP_CLIENT identity and current Site consent."
            ),
        }
        assert operation["responses"][success]["headers"]["X-KSI-External-AI-Egress"] == {
            "required": False,
            "schema": {"type": "string", "const": "ALLOWED"},
            "description": (
                "Present only after Core authenticates ANALYSIS_MCP_CLIENT and confirms "
                "current consent for the scoped Site."
            ),
        }


def test_v2_detail_uses_compact_coverage_and_never_accepts_masks() -> None:
    summary = AnalysisResultSummaryV2(
        result_id="result-1",
        report_digest="sha256:" + "a" * 64,
        numeric_result_identity_digest="sha256:" + "b" * 64,
        computed_at=datetime(2026, 9, 22, tzinfo=UTC),
        metrics=AnalysisMetricsV1(cut_m3=2.0, fill_m3=5.0, net_m3=3.0, threshold_m=0.0),
        coverage=AnalysisCoverageSummaryV2.model_validate({
            "coverage_witness_digest": "sha256:" + "c" * 64,
            "rows": 100,
            "columns": 100,
            "selected_cell_count": 10000,
            "common_valid_cell_count": 9990,
            "unavailable_cell_count": 10,
            "threshold_excluded_cell_count": 0,
            "cell_area_m2": 1.0,
            "selected_area_m2": 10000.0,
            "common_valid_area_m2": 9990.0,
            "bounds": (0.0, 0.0, 100.0, 100.0),
        }),
        limitation_codes=("PROVISIONAL_ACCURACY_UNVERIFIED",),
    )
    view = AnalysisViewV2(
        analysis_id="analysis-1",
        site_id="site-1",
        work_area_id="area-1",
        baseline=_selector("work-order-t0"),
        current=_selector("work-order-t1"),
        execution_state=AnalysisExecutionStateV1.COMPLETED,
        suitability_state=AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
        blockers=(),
        result=summary,
        evidence_revision=1,
        evidence_digest="sha256:" + "d" * 64,
        evidence_href="/v2/sites/site-1/analyses/analysis-1/evidence",
        coverage_href="/v2/sites/site-1/analyses/analysis-1/coverage",
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    dumped = view.model_dump(by_alias=True)
    assert dumped["result"]["metrics"]["uncertaintyM3"] is None
    assert "coverageWitness" not in dumped["result"]
    assert "selectedMaskB64" not in view.model_dump_json(by_alias=True)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisViewV2.model_validate({**dumped, "selectedMaskB64": "AA=="})


def test_v2_pages_and_coverage_range_enforce_boundaries_without_truncation() -> None:
    item = AnalysisListItemV2(
        analysis_id="analysis-1",
        site_id="site-1",
        work_area_id="area-1",
        execution_state=AnalysisExecutionStateV1.QUEUED,
        suitability_state=AnalysisSuitabilityStateV1.BLOCKED,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
        result_id=None,
        metrics=None,
        limitation_count=1,
        analysis_href="/v2/sites/site-1/analyses/analysis-1",
    )
    assert item.limitation_count == 1
    assert "limitationCodes" not in item.model_dump(by_alias=True)
    page = AnalysisListPageV2(site_id="site-1", items=(item,) * 50, next_cursor="opaque-keyset")
    assert len(page.items) == 50
    with pytest.raises(ValidationError):
        AnalysisListPageV2(site_id="site-1", items=(item,) * 51)

    evidence = AnalysisLimitationEvidenceItemV2(
        kind="LIMITATION",
        record_id="inspection-1",
        digest="sha256:" + "e" * 64,
        source="RESULT",
        code="PROVISIONAL_ACCURACY_UNVERIFIED",
        detail="accuracy evidence is not available",
    )
    evidence_page = AnalysisEvidencePageV2(
        analysis_id="analysis-1",
        evidence_revision=1,
        evidence_digest="sha256:" + "d" * 64,
        items=(evidence,) * 32,
        next_cursor="digest-bound-cursor",
    )
    assert len(evidence_page.items) == 32
    with pytest.raises(ValidationError):
        AnalysisEvidencePageV2(
            analysis_id="analysis-1",
            evidence_revision=1,
            evidence_digest="sha256:" + "d" * 64,
            items=(evidence,) * 33,
        )

    assert AnalysisCoverageRangeV2(
        analysis_id="analysis-1",
        coverage_digest="sha256:" + "c" * 64,
        total_length_bytes=100_000,
        range_start=0,
        range_end=65_535,
        content_length_bytes=65_536,
    ).content_length_bytes == 65_536
    with pytest.raises(ValidationError):
        AnalysisCoverageRangeV2(
            analysis_id="analysis-1",
            coverage_digest="sha256:" + "c" * 64,
            total_length_bytes=100_000,
            range_start=0,
            range_end=65_536,
            content_length_bytes=65_537,
        )


def test_v2_maximum_valid_structured_fixtures_stay_under_512_kib() -> None:
    blockers = tuple(
        AnalysisBlockerV1(code=f"BLOCKER_{i:03d}", detail="x" * 512) for i in range(128)
    )
    view = AnalysisViewV2(
        analysis_id="分" * 255,
        site_id="場" * 255,
        work_area_id="域" * 255,
        baseline=_selector("b" * 255),
        current=_selector("c" * 255),
        execution_state=AnalysisExecutionStateV1.NOT_STARTED,
        suitability_state=AnalysisSuitabilityStateV1.BLOCKED,
        blockers=blockers,
        result=None,
        evidence_revision=1,
        evidence_digest="sha256:" + "d" * 64,
        evidence_href="/v2/" + "a" * 100,
        coverage_href="/v2/" + "b" * 100,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    list_item = AnalysisListItemV2(
        analysis_id="🛰" * 255,
        site_id="🛰" * 255,
        work_area_id="🛰" * 255,
        execution_state=AnalysisExecutionStateV1.COMPLETED,
        suitability_state=AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
        result_id="🛰" * 255,
        metrics=AnalysisMetricsV1(cut_m3=1.0, fill_m3=2.0, net_m3=1.0, threshold_m=0.0),
        limitation_count=128,
        analysis_href="/v2/" + "l" * 2043,
    )
    evidence_item = AnalysisLimitationEvidenceItemV2(
        kind="LIMITATION",
        record_id="🛰" * 255,
        digest="sha256:" + "e" * 64,
        limitation_codes=("L" + "X" * 127,) * 64,
        source="RESULT",
        code="LIMITATION_" + "X" * 116,
        detail="🛰" * 170,
    )
    fixtures = (
        view,
        AnalysisListPageV2(site_id="🛰" * 255, items=(list_item,) * 50, next_cursor="c" * 512),
        AnalysisEvidencePageV2(
            analysis_id="🛰" * 255,
            evidence_revision=2**31 - 1,
            evidence_digest="sha256:" + "d" * 64,
            items=(evidence_item,) * 32,
            next_cursor="c" * 512,
        ),
    )
    assert all(
        len(value.model_dump_json(by_alias=True).encode("utf-8")) <= 512 * 1024
        for value in fixtures
    )


def test_v2_detail_and_evidence_preserve_all_v1_reason_codes() -> None:
    reasons = tuple(f"EVALUATION_REASON_{index:03d}" for index in range(128))
    summary = AnalysisResultSummaryV2(
        result_id="result-1",
        report_digest="sha256:" + "a" * 64,
        numeric_result_identity_digest="sha256:" + "b" * 64,
        computed_at=datetime(2026, 9, 22, tzinfo=UTC),
        metrics=AnalysisMetricsV1(cut_m3=1.0, fill_m3=2.0, net_m3=1.0, threshold_m=0.0),
        coverage=AnalysisCoverageSummaryV2.model_validate({
            "coverage_witness_digest": "sha256:" + "c" * 64,
            "rows": 1,
            "columns": 1,
            "selected_cell_count": 1,
            "common_valid_cell_count": 1,
            "unavailable_cell_count": 0,
            "threshold_excluded_cell_count": 0,
            "cell_area_m2": 1.0,
            "selected_area_m2": 1.0,
            "common_valid_area_m2": 1.0,
            "bounds": (0.0, 0.0, 1.0, 1.0),
        }),
        limitation_codes=reasons,
    )
    assert summary.limitation_codes == reasons
    numeric_view = AnalysisViewV2(
        analysis_id="🛰" * 255,
        site_id="🛰" * 255,
        work_area_id="🛰" * 255,
        baseline=_selector("🛰" * 255),
        current=_selector("🛰" * 255),
        execution_state=AnalysisExecutionStateV1.COMPLETED,
        suitability_state=AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
        blockers=(),
        result=summary,
        evidence_revision=1,
        evidence_digest="sha256:" + "e" * 64,
        evidence_href="/v2/" + "a" * 2043,
        coverage_href="/v2/" + "c" * 2043,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    assert len(numeric_view.model_dump_json(by_alias=True).encode("utf-8")) <= 512 * 1024

    per_evaluation = tuple(f"EVALUATION_REASON_{index:03d}" for index in range(64))
    evidence_item = AnalysisEvaluationEvidenceItemV2(
        kind="EVALUATION",
        record_id="evaluation-1",
        digest="sha256:" + "d" * 64,
        evaluation_id="evaluation-1",
        epoch="BASELINE",
        revision=1,
        evaluation_digest="sha256:" + "1" * 64,
        outcome="UNASSESSED",
        reason_codes=per_evaluation,
        assessed_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    evidence_page = AnalysisEvidencePageV2(
        analysis_id="analysis-1",
        evidence_revision=1,
        evidence_digest="sha256:" + "e" * 64,
        items=(evidence_item, evidence_item),
    )
    assert isinstance(evidence_page.items[0], AnalysisEvaluationEvidenceItemV2)
    assert evidence_page.items[0].reason_codes == per_evaluation


def test_v2_evidence_pages_carry_typed_epoch_and_checkpoint_facts_without_fake_links() -> None:
    """Paged V2 facts are self-contained and omit item links without real resolvers."""
    epoch = {
        "kind": "EPOCH_IDENTITY",
        "recordId": "observation-epoch-t0",
        "digest": "sha256:" + "a" * 64,
        "epoch": "BASELINE",
        "selector": _selector("work-order-t0").model_dump(by_alias=True),
        "observationEpochId": "observation-epoch-t0",
        "artifactId": "dsm-t0",
        "observedSha256": "sha256:" + "b" * 64,
        "observedSizeBytes": 1024,
        "observedCrsIdentifier": "EPSG:5186",
        "observedCrsDigest": "sha256:" + "c" * 64,
        "verticalReferenceIdentifier": "TBM-01",
        "verticalReferenceBasis": "SITE_BENCHMARK",
        "verticalUnit": "metre",
        "transform": [1.0, 0.0, 0.0, 0.0, -1.0, 0.0],
        "transformDigest": "sha256:" + "d" * 64,
        "inspectionReportDigest": "sha256:" + "e" * 64,
        "inspectionReportRecordId": "sha256:" + "e" * 64,
        "inputDigest": "sha256:" + "f" * 64,
    }
    checkpoint = {
        "kind": "CHECKPOINT_FACT",
        "recordId": "checkpoint-record-1",
        "digest": "sha256:" + "1" * 64,
        "evaluationId": "evaluation-t0",
        "epoch": "BASELINE",
        "evaluationRevision": 1,
        "evidenceRef": "eev-v1-" + "2" * 64,
        "contextId": "context-1",
        "contextDigest": "sha256:" + "3" * 64,
        "evidenceManifestDigest": "sha256:" + "4" * 64,
        "evidenceRecordId": "checkpoint-record-1",
        "evidenceRecordDigest": "sha256:" + "1" * 64,
        "coreVerdict": "VALIDATED",
    }
    page = AnalysisEvidencePageV2.model_validate(
        {
            "analysisId": "analysis-1",
            "evidenceRevision": 1,
            "evidenceDigest": "sha256:" + "5" * 64,
            "items": [epoch, checkpoint],
        }
    )

    assert isinstance(page.items[0], AnalysisEpochEvidenceItemV2)
    assert isinstance(page.items[1], AnalysisCheckpointEvidenceItemV2)
    assert page.items[0].epoch == "BASELINE"
    assert page.items[0].observed_crs_identifier == "EPSG:5186"
    assert page.items[0].vertical_reference_identifier == "TBM-01"
    assert page.items[0].href is None
    assert page.items[1].evidence_record_digest == "sha256:" + "1" * 64
    assert page.items[1].href is None

    schema_path = Path(__file__).resolve().parents[2] / "contracts/schemas/analysis-api.v2.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(page.model_dump(by_alias=True, mode="json"))) == []
    malformed_epoch = {**epoch}
    malformed_epoch.pop("verticalReferenceIdentifier")
    assert list(
        validator.iter_errors(
            {
                "analysisId": "analysis-1",
                "evidenceRevision": 1,
                "evidenceDigest": "sha256:" + "5" * 64,
                "items": [malformed_epoch],
            }
        )
    )


def test_v2_maximum_multibyte_fixtures_fit_the_structured_response_limit() -> None:
    blockers = tuple(
        AnalysisBlockerV1(code=f"BLOCKER_{i:03d}", detail="🛰" * 512) for i in range(128)
    )
    view = AnalysisViewV2(
        analysis_id="🛰" * 255,
        site_id="🛰" * 255,
        work_area_id="🛰" * 255,
        baseline=_selector("🛰" * 255),
        current=_selector("🛰" * 255),
        execution_state=AnalysisExecutionStateV1.NOT_STARTED,
        suitability_state=AnalysisSuitabilityStateV1.BLOCKED,
        blockers=blockers,
        result=None,
        evidence_revision=1,
        evidence_digest="sha256:" + "d" * 64,
        evidence_href="/v2/" + "a" * 2043,
        coverage_href=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    evidence_item = AnalysisLimitationEvidenceItemV2(
        kind="LIMITATION",
        record_id="🛰" * 255,
        digest="sha256:" + "e" * 64,
        limitation_codes=("L" + "X" * 127,) * 64,
        source="RESULT",
        code="LIMITATION_" + "X" * 116,
        detail="🛰" * 170,
    )
    evidence_page = AnalysisEvidencePageV2(
        analysis_id="🛰" * 255,
        evidence_revision=2**31 - 1,
        evidence_digest="sha256:" + "d" * 64,
        items=(evidence_item,) * 32,
        next_cursor="c" * 512,
    )
    assert len(view.model_dump_json(by_alias=True).encode("utf-8")) <= 512 * 1024
    assert len(evidence_page.model_dump_json(by_alias=True).encode("utf-8")) <= 512 * 1024


def test_v2_json_schema_and_openapi_are_additive_and_bounded() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "contracts/schemas/analysis-api.v2.json").read_text(encoding="utf-8")
    )
    document = yaml.safe_load(
        (root / "contracts/api/openapi-core.yaml").read_text(encoding="utf-8")
    )
    assert Draft202012Validator.check_schema(schema) is None
    assert schema["$defs"]["AnalysisListPageV2"]["properties"]["items"]["maxItems"] == 50
    assert schema["$defs"]["AnalysisEvidencePageV2"]["properties"]["items"]["maxItems"] == 32
    assert (
        schema["$defs"]["AnalysisResultSummaryV2"]["properties"]["limitationCodes"]["maxItems"]
        == 128
    )
    evidence_union = schema["$defs"]["AnalysisEvidenceItemV2"]
    assert evidence_union["discriminator"]["propertyName"] == "kind"
    assert len(evidence_union["oneOf"]) == 8
    assert (
        schema["$defs"]["AnalysisEvaluationEvidenceItemV2"]["properties"]["reasonCodes"][
            "maxItems"
        ]
        == 64
    )
    list_item_schema = schema["$defs"]["AnalysisListItemV2"]
    assert "limitationCodes" not in list_item_schema["properties"]
    assert {"analysisHref", "limitationCount"} <= set(list_item_schema["properties"])
    coverage = schema["$defs"]["AnalysisCoverageRangeV2"]
    assert coverage["properties"]["contentLengthBytes"]["maximum"] == 65_536
    assert "selectedMaskB64" not in json.dumps(schema)
    v2_models = (
        "AnalysisCoverageSummaryV2",
        "AnalysisEvidenceItemV2",
        "AnalysisEvidencePageV2",
        "AnalysisListItemV2",
        "AnalysisListPageV2",
        "AnalysisResultSummaryV2",
        "AnalysisViewV2",
    )
    assert all(
        document["components"]["schemas"][name].get("x-status") != "planned"
        for name in v2_models
    )
    # Coverage range facts are response headers, not a JSON model emitted by Core.
    assert (
        document["components"]["schemas"]["AnalysisCoverageRangeV2"]["x-status"] == "planned"
    )
    contract_models = (
        AnalysisCoverageRangeV2,
        AnalysisEvidencePageV2,
        AnalysisListItemV2,
        AnalysisListPageV2,
        AnalysisCoverageSummaryV2,
        AnalysisResultSummaryV2,
        AnalysisViewV2,
    )
    for model in contract_models:
        name = model.__name__
        documented = document["components"]["schemas"][name]
        fields = {field.alias for field in model.model_fields.values()}
        assert set(documented["properties"]) == fields
        required = {field.alias for field in model.model_fields.values() if field.is_required()}
        assert set(documented.get("required", ())) == required
    assert len(document["components"]["schemas"]["AnalysisEvidenceItemV2"]["oneOf"]) == 8

    list_item = AnalysisListItemV2(
        analysis_id="analysis-1",
        site_id="site-1",
        work_area_id="area-1",
        execution_state=AnalysisExecutionStateV1.QUEUED,
        suitability_state=AnalysisSuitabilityStateV1.BLOCKED,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
        limitation_count=1,
        analysis_href="/v2/sites/site-1/analyses/analysis-1",
    )
    validator = Draft202012Validator(schema)
    list_page = AnalysisListPageV2(site_id="site-1", items=(list_item,))
    assert list(validator.iter_errors(json.loads(list_page.model_dump_json(by_alias=True)))) == []
    assert list(
        validator.iter_errors(
            json.loads(
                AnalysisListPageV2(site_id="site-1", items=(list_item,) * 50).model_dump_json(
                    by_alias=True
                )
            )
        )
    ) == []
    paths = document["paths"]
    assert "/v2/sites/{site_id}/work-areas/{work_area_id}/analyses" in paths
    assert "post" in paths["/v2/sites/{site_id}/work-areas/{work_area_id}/analyses"]
    v2_paths = [path for path in paths if path.startswith("/v2/sites/{site_id}/analyses")]
    assert set(v2_paths) == {
        "/v2/sites/{site_id}/analyses",
        "/v2/sites/{site_id}/analyses/{analysis_id}",
        "/v2/sites/{site_id}/analyses/{analysis_id}/evidence",
        "/v2/sites/{site_id}/analyses/{analysis_id}/coverage",
        "/v2/sites/{site_id}/analyses/{analysis_id}/review-target",
        "/v2/sites/{site_id}/analyses/{analysis_id}/reviews",
    }
    assert all(paths[path].get("x-status") != "planned" for path in v2_paths)
    assert next(
        parameter["schema"]["maximum"]
        for parameter in paths["/v2/sites/{site_id}/analyses"]["get"]["parameters"]
        if parameter.get("name") == "limit"
    ) == 50
    assert next(
        parameter["schema"]["maximum"]
        for parameter in paths[
            "/v2/sites/{site_id}/analyses/{analysis_id}/evidence"
        ]["get"]["parameters"]
        if parameter.get("name") == "limit"
    ) == 32
    assert "/v1/sites/{site_id}/analyses" in paths
