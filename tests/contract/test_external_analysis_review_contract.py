"""Additive V2 human review wire documentation matches the runtime models."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from ksi_event_contracts.external_analysis_review import (
    AnalysisReviewEvaluationV2,
    AnalysisReviewListV2,
    AnalysisReviewReceiptV2,
    AnalysisReviewTargetV2,
    CreateAnalysisReviewV2,
)
from pydantic.json_schema import models_json_schema

ROOT = Path(__file__).resolve().parents[2]
MODELS = (
    AnalysisReviewEvaluationV2,
    AnalysisReviewTargetV2,
    CreateAnalysisReviewV2,
    AnalysisReviewReceiptV2,
    AnalysisReviewListV2,
)


def test_review_wire_schema_is_generated_and_has_exact_bounded_limitations() -> None:
    _, expected = models_json_schema([(model, "validation") for model in MODELS], by_alias=True)
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    actual = json.loads((ROOT / "contracts/schemas/external-analysis-review.v2.json").read_text())
    assert actual == expected
    Draft202012Validator.check_schema(actual)
    defs = actual["$defs"]
    assert defs["AnalysisReviewListV2"]["properties"]["items"]["maxItems"] == 50
    limitations = defs["AnalysisReviewReceiptV2"]["properties"]["factualLimitations"]
    assert limitations["minItems"] == limitations["maxItems"] == 3
    assert [item["const"] for item in limitations["prefixItems"]] == [
        "HUMAN_REVIEW_IS_NOT_ACCURACY_VALIDATION",
        "HUMAN_REVIEW_IS_NOT_FIELD_OR_FLIGHT_AUTHORIZATION",
        "RELATIVE_VOLUME_IS_NOT_SETTLEMENT_OR_COMPLETION_PROOF",
    ]


def test_review_openapi_paths_and_models_match_runtime_contract() -> None:
    document = yaml.safe_load((ROOT / "contracts/api/openapi-core.yaml").read_text())
    base = "/v2/sites/{site_id}/analyses/{analysis_id}"
    for suffix, method, code, response in (
        ("/review-target", "get", "200", "AnalysisReviewTargetV2"),
        ("/reviews", "get", "200", "AnalysisReviewListV2"),
        ("/reviews", "post", "201", "AnalysisReviewReceiptV2"),
    ):
        operation = document["paths"][base + suffix][method]
        assert operation["security"] == [{"bearerAuth": []}]
        assert operation["responses"][code]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{response}"
        }
        assert {"401", "403", "404", "409"} <= operation["responses"].keys()
    post = document["paths"][base + "/reviews"]["post"]
    assert post["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/CreateAnalysisReviewV2"
    )
    assert any(
        item["name"] == "Idempotency-Key" and item["required"] for item in post["parameters"]
    )
    for model in MODELS:
        documented = document["components"]["schemas"][model.__name__]
        assert set(documented["properties"]) == {item.alias for item in model.model_fields.values()}
        assert set(documented.get("required", [])) == {
            item.alias for item in model.model_fields.values() if item.is_required()
        }
