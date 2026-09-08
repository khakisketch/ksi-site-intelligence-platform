"""Focused fail-closed tests for the HIL-0 capability-runtime artifact."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = _ROOT / "tools" / "hil" / "capability_runtime_hil.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capability_runtime_hil", _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _input(tool: ModuleType) -> dict[str, object]:
    return {
        "captureId": "HIL0-CAP-RUNTIME-20260903T010203Z",
        "capturedAtUtc": "2026-09-03T01:02:03Z",
        "configuredDeploymentDigest": "sha256:" + "a" * 64,
        "softwareBuildDigest": "sha256:" + "b" * 64,
        "freshnessPolicy": {"id": "psdk-fast-v1", "digest": "sha256:" + "c" * 64},
        "physicalComponentIdentities": [],
        "firmwareBuildVersions": [],
        "routeStateSignal": "ABSENT",
        "scenarioCaptures": [
            {"scenario": scenario, "status": "NOT_CAPTURED", "evidenceRefs": []}
            for scenario in reversed(tool._SCENARIOS)
        ],
        "missionLatency": {"captureStatus": "NOT_CAPTURED", "samples": []},
    }


def test_emitted_artifact_is_deterministic_schema_valid_and_non_approving() -> None:
    tool = _tool()
    first = tool.build_artifact(_input(tool))
    second = tool.build_artifact(_input(tool))

    assert tool._canonical_json(first) == tool._canonical_json(second)
    assert [route["family"] for route in first["routeFamilyPlan"]] == [
        "PSDK_MOP_EDGE_UPLINK",
        "MANIFOLD_DIRECT",
        "DJI_CLOUD",
        "DJI_DOCK",
        "MSDK_FIELD",
    ]
    assert first["routeState"] == {
        "routeId": "HIL_ROUTE_1",
        "status": "BLOCKED_EXTERNAL",
        "blockerCode": "NO_GENUINE_ROUTE_STATE_SIGNAL",
        "effect": "NO_NEW_ROUTE_SELECTION",
    }
    assert first["capabilityAuthority"] == {
        "routeEvidenceQualification": "NOT_QUALIFIED",
        "productCapabilityApproval": "NOT_APPROVED",
        "operationalCapabilityActivation": "NOT_ACTIVATED",
    }
    assert first["missionLatencyMeasurement"] == {
        "requirement": "FIELD_REQUIRED",
        "captureStatus": "NOT_CAPTURED",
    }
    assert first["routeRun"]["integrationPath"] == "PSDK_MANIFOLD"
    assert first["observationSequence"] == []
    assert first["preflightDecisions"] == []
    assert first["overallResult"] == "INCONCLUSIVE"
    assert all(item["fieldRequirement"] == "FIELD_REQUIRED" for item in first["scenarioPlan"])
    tool.validate_artifact(first)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda value: value.__setitem__("routeStateSignal", "PRESENT"), "route-state signal"),
        (
            lambda value: value["scenarioCaptures"][0].__setitem__("status", "AVAILABLE"),
            "성공 또는 raw evidence",
        ),
        (
            lambda value: value["scenarioCaptures"][0].__setitem__(
                "evidenceRefs", ["invented.json"]
            ),
            "성공 또는 raw evidence",
        ),
        (
            lambda value: value["missionLatency"].__setitem__("captureStatus", "CAPTURED"),
            "Mission latency",
        ),
    ],
)
def test_input_rejects_claimed_or_synthetic_hil_evidence(mutate: object, match: str) -> None:
    tool = _tool()
    value = _input(tool)
    mutate(value)  # type: ignore[operator]
    with pytest.raises(tool.CapabilityRuntimeHilError, match=match):
        tool.build_artifact(value)


def test_schema_rejects_tampered_route_order_and_approval() -> None:
    tool = _tool()
    artifact = tool.build_artifact(_input(tool))
    artifact["routeFamilyPlan"][0]["rank"] = 2
    with pytest.raises(tool.CapabilityRuntimeHilError, match="routeFamilyPlan"):
        tool.validate_artifact(artifact)

    artifact = tool.build_artifact(_input(tool))
    artifact["capabilityAuthority"]["productCapabilityApproval"] = "APPROVED"
    with pytest.raises(tool.CapabilityRuntimeHilError, match="schema validation"):
        tool.validate_artifact(artifact)


def test_cli_emits_canonical_json_and_validate_reads_only_local_files(tmp_path: Path) -> None:
    tool = _tool()
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "artifact.json"
    input_path.write_text(json.dumps(_input(tool)), encoding="utf-8")

    assert tool.main(["emit", "--input", str(input_path), "--output", str(output_path)]) == 0
    expected = tool._canonical_json(tool.build_artifact(_input(tool)))
    assert output_path.read_text(encoding="utf-8") == expected
    assert tool.main(["validate", "--input", str(output_path)]) == 0
