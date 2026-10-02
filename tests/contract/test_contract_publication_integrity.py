"""Published bundles must work independently, not only inside FastAPI's OpenAPI tree."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from ksi_event_contracts.external_analysis_worker import (
    AnalysisWorkerPendingItemV1,
    AnalysisWorkerPendingListV1,
)
from yaml.nodes import MappingNode, Node, SequenceNode

ROOT = Path(__file__).resolve().parents[2]


def test_worker_schema_validates_nonempty_model_valid_pending_response() -> None:
    schema = json.loads((ROOT / "contracts/schemas/external-analysis-worker.v1.json").read_text())
    payload = AnalysisWorkerPendingListV1(items=(AnalysisWorkerPendingItemV1(
        analysis_id="analysis-local", calculation_request_id="calculation-local",
        issued_at=datetime(2026, 10, 2, tzinfo=UTC),
    ),)).model_dump(by_alias=True, mode="json")
    validator = Draft202012Validator({
        "$schema": schema["$schema"], "$defs": schema["$defs"],
        "$ref": "#/$defs/AnalysisWorkerPendingListV1",
    })
    validator.validate(payload)
    assert list(validator.iter_errors({"items": [{**payload["items"][0], "objectKey": "caller"}]}))


def test_all_published_worker_local_references_resolve() -> None:
    schema = json.loads((ROOT / "contracts/schemas/external-analysis-worker.v1.json").read_text())

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                ref = value["$ref"]
                assert ref.startswith("#/$defs/"), ref
                target = schema
                for key in ref[2:].split("/"):
                    target = target[key.replace("~1", "/").replace("~0", "~")]
                assert isinstance(target, dict)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    Draft202012Validator.check_schema(schema)
    visit(schema)


def _require_unique_yaml_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen = set()
        for key, value in node.value:
            assert key.value not in seen, (
                f"duplicate YAML key {key.value} at line {key.start_mark.line + 1}"
            )
            seen.add(key.value)
            _require_unique_yaml_keys(value)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            _require_unique_yaml_keys(item)


def test_openapi_has_no_duplicate_mapping_keys() -> None:
    node = yaml.compose((ROOT / "contracts/api/openapi-core.yaml").read_text())
    assert node is not None
    _require_unique_yaml_keys(node)


def test_uniqueness_gate_rejects_even_equal_duplicate_values() -> None:
    node = yaml.compose("component: {a: 1, a: 1}\n")
    assert node is not None
    with pytest.raises(AssertionError, match="duplicate YAML key a"):
        _require_unique_yaml_keys(node)
