"""Fail-closed HIL-0 capability-runtime evidence emitter.

The tool is intentionally offline. It accepts only explicit `NOT_CAPTURED`
inputs, emits canonical JSON, and never creates a successful HIL result,
qualification, approval, activation, deployment action, or device contact.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "capability-runtime-hil-evidence-v1"
_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _ROOT / "contracts" / "hil" / "capability-runtime-hil-evidence-v1.schema.json"

_ROUTE_FAMILIES: tuple[tuple[int, str, str], ...] = (
    (1, "PSDK_MOP_EDGE_UPLINK", "BLOCKED_EXTERNAL"),
    (2, "MANIFOLD_DIRECT", "NOT_EXECUTED"),
    (3, "DJI_CLOUD", "NOT_EXECUTED"),
    (4, "DJI_DOCK", "NOT_EXECUTED"),
    (5, "MSDK_FIELD", "NOT_EXECUTED"),
)
_SCENARIO_EFFECTS: tuple[tuple[str, str], ...] = (
    ("AVAILABILITY", "REQUIRE_EXACT_TYPED_ROUTE_STATE_SIGNAL"),
    ("UNAVAILABILITY", "REJECT_NEW_ROUTE_SELECTION"),
    ("RECONNECT", "REQUIRE_FRESH_EXACT_ROUTE_STATE_SIGNAL"),
    ("EXPIRY", "REJECT_EXPIRED_ROUTE_STATE_SIGNAL"),
    ("WRONG_ROUTE", "REJECT_MISMATCHED_ROUTE_BINDING"),
    ("MISSION_DENY", "PRESERVE_MISSION_DENIAL"),
    ("FLAG_OFF", "KEEP_ROUTE_FEATURE_DISABLED"),
    ("CORE_UNAVAILABLE", "NO_NEW_CORE_MEDIATED_ROUTE_SELECTION"),
    ("EDGE_BUNDLE_UPLOAD", "SYNTHETIC_EDGE_BUNDLE_ONLY_NO_ACTUATION"),
)
_SCENARIOS = tuple(item[0] for item in _SCENARIO_EFFECTS)


class CapabilityRuntimeHilError(ValueError):
    """Raised when a caller tries to create an unsafe or ambiguous artifact."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityRuntimeHilError(f"JSON을 읽을 수 없다: {path}") from exc


def _parse_utc(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CapabilityRuntimeHilError(f"{field}는 Z UTC ISO-8601 문자열이어야 한다")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CapabilityRuntimeHilError(f"{field}를 파싱할 수 없다") from exc
    if parsed.utcoffset() != UTC.utcoffset(parsed) or parsed.microsecond:
        raise CapabilityRuntimeHilError(f"{field}는 초 단위 UTC여야 한다")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_exact_mapping(value: object, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CapabilityRuntimeHilError(f"{name}의 필드가 정확하지 않다")
    return value


def validate_captured_input(value: object) -> dict[str, Any]:
    """Validate the only input shape HIL-0 may turn into an artifact.

    Captures are deliberately all `NOT_CAPTURED`: allowing a local JSON edit to
    claim route availability would manufacture a HIL result without a device.
    A later field-evidence contract must carry independently verified raw proof.
    """

    payload = _require_exact_mapping(
        value,
        fields={
            "captureId",
            "capturedAtUtc",
            "configuredDeploymentDigest",
            "firmwareBuildVersions",
            "freshnessPolicy",
            "physicalComponentIdentities",
            "softwareBuildDigest",
            "missionLatency",
            "routeStateSignal",
            "scenarioCaptures",
        },
        name="입력",
    )
    capture_id = payload["captureId"]
    if not isinstance(capture_id, str) or not capture_id.strip():
        raise CapabilityRuntimeHilError("captureId가 필요하다")
    captured_at = _parse_utc(payload["capturedAtUtc"], field="capturedAtUtc")
    for field in ("configuredDeploymentDigest", "softwareBuildDigest"):
        value = payload[field]
        if (
            not isinstance(value, str)
            or len(value) != 71
            or not value.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in value[7:])
        ):
            raise CapabilityRuntimeHilError(f"{field}는 sha256:<64hex>여야 한다")
    policy = _require_exact_mapping(
        payload["freshnessPolicy"], fields={"id", "digest"}, name="freshnessPolicy"
    )
    if not isinstance(policy["id"], str) or not policy["id"].strip():
        raise CapabilityRuntimeHilError("freshnessPolicy.id가 필요하다")
    if (
        not isinstance(policy["digest"], str)
        or len(policy["digest"]) != 71
        or not policy["digest"].startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in policy["digest"][7:])
    ):
        raise CapabilityRuntimeHilError("freshnessPolicy.digest가 필요하다")
    if payload["physicalComponentIdentities"] != [] or payload["firmwareBuildVersions"] != []:
        raise CapabilityRuntimeHilError(
            "blocked HIL-0은 확인하지 못한 physical/firmware identity를 채울 수 없다"
        )
    if payload["routeStateSignal"] != "ABSENT":
        raise CapabilityRuntimeHilError("HIL-0은 genuine route-state signal 부재만 기록한다")

    latency = _require_exact_mapping(
        payload["missionLatency"], fields={"captureStatus", "samples"}, name="missionLatency"
    )
    if latency["captureStatus"] != "NOT_CAPTURED" or latency["samples"] != []:
        raise CapabilityRuntimeHilError(
            "Mission latency는 FIELD_REQUIRED이며 HIL-0에서 측정할 수 없다"
        )

    captures = payload["scenarioCaptures"]
    if not isinstance(captures, Sequence) or isinstance(captures, (str, bytes)):
        raise CapabilityRuntimeHilError("scenarioCaptures는 배열이어야 한다")
    by_scenario: dict[str, dict[str, Any]] = {}
    for item in captures:
        capture = _require_exact_mapping(
            item, fields={"evidenceRefs", "scenario", "status"}, name="scenarioCapture"
        )
        scenario = capture["scenario"]
        if scenario not in _SCENARIOS or scenario in by_scenario:
            raise CapabilityRuntimeHilError(
                "scenarioCaptures는 각 HIL-0 시나리오를 정확히 한 번 포함해야 한다"
            )
        if capture["status"] != "NOT_CAPTURED" or capture["evidenceRefs"] != []:
            raise CapabilityRuntimeHilError(
                "HIL-0은 성공 또는 raw evidence를 합성하거나 기록하지 않는다"
            )
        by_scenario[scenario] = {
            "scenario": scenario,
            "status": "NOT_CAPTURED",
            "evidenceRefs": [],
        }
    if set(by_scenario) != set(_SCENARIOS):
        raise CapabilityRuntimeHilError("scenarioCaptures에 필수 HIL-0 시나리오가 누락됐다")

    return {
        "captureId": capture_id,
        "capturedAtUtc": captured_at,
        "configuredDeploymentDigest": payload["configuredDeploymentDigest"],
        "softwareBuildDigest": payload["softwareBuildDigest"],
        "freshnessPolicy": dict(policy),
        "physicalComponentIdentities": [],
        "firmwareBuildVersions": [],
        "routeStateSignal": "ABSENT",
        "scenarioCaptures": [by_scenario[scenario] for scenario in _SCENARIOS],
        "missionLatency": {"captureStatus": "NOT_CAPTURED", "samples": []},
    }


def _schema_validator() -> Draft202012Validator:
    schema = _load_json(_SCHEMA_PATH)
    if not isinstance(schema, Mapping):
        raise CapabilityRuntimeHilError("HIL schema가 object가 아니다")
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_artifact(value: object) -> None:
    errors = sorted(_schema_validator().iter_errors(value), key=lambda error: list(error.path))
    if errors:
        location = "/".join(str(part) for part in errors[0].path) or "<root>"
        raise CapabilityRuntimeHilError(
            f"schema validation 실패 at {location}: {errors[0].message}"
        )

    if not isinstance(value, Mapping):  # covered above; narrows type for deterministic checks.
        raise CapabilityRuntimeHilError("artifact가 object가 아니다")
    routes = value["routeFamilyPlan"]
    expected_routes = [
        {"rank": rank, "family": family, "status": status}
        for rank, family, status in _ROUTE_FAMILIES
    ]
    if routes != expected_routes:
        raise CapabilityRuntimeHilError("routeFamilyPlan은 HIL-0 고정 우선순위와 일치해야 한다")
    expected_plan = [
        {"scenario": scenario, "fieldRequirement": "FIELD_REQUIRED", "safeEffect": effect}
        for scenario, effect in _SCENARIO_EFFECTS
    ]
    if value["scenarioPlan"] != expected_plan:
        raise CapabilityRuntimeHilError("scenarioPlan은 HIL-0 fail-closed plan과 일치해야 한다")
    expected_captures = [
        {"scenario": scenario, "status": "NOT_CAPTURED", "evidenceRefs": []}
        for scenario in _SCENARIOS
    ]
    if value["scenarioCaptures"] != expected_captures:
        raise CapabilityRuntimeHilError("scenarioCaptures는 성공을 주장하거나 순서를 바꿀 수 없다")


def build_artifact(captured_input: object) -> dict[str, Any]:
    """Build a deterministic, non-approving artifact from explicit input only."""

    captured = validate_captured_input(captured_input)
    artifact: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "HIL_0_CAPABILITY_RUNTIME_EVIDENCE",
        "evidenceId": captured["captureId"],
        "nonActuating": True,
        "capture": {
            "capturedAtUtc": captured["capturedAtUtc"],
            "routeStateSignal": captured["routeStateSignal"],
        },
        "routeRun": {
            "integrationPath": "PSDK_MANIFOLD",
            "canonicalCapabilityId": "EDGE_UPLINK",
            "subjectPortId": "UNCONFIRMED_EXTERNAL_SIGNAL_PORT",
            "physicalComponentIdentities": captured["physicalComponentIdentities"],
            "softwareBuildDigest": captured["softwareBuildDigest"],
            "firmwareBuildVersions": captured["firmwareBuildVersions"],
            "configuredDeploymentDigest": captured["configuredDeploymentDigest"],
            "freshnessPolicy": captured["freshnessPolicy"],
        },
        "capabilityAuthority": {
            "routeEvidenceQualification": "NOT_QUALIFIED",
            "productCapabilityApproval": "NOT_APPROVED",
            "operationalCapabilityActivation": "NOT_ACTIVATED",
        },
        "routeFamilyPlan": [
            {"rank": rank, "family": family, "status": status}
            for rank, family, status in _ROUTE_FAMILIES
        ],
        "routeState": {
            "routeId": "HIL_ROUTE_1",
            "status": "BLOCKED_EXTERNAL",
            "blockerCode": "NO_GENUINE_ROUTE_STATE_SIGNAL",
            "effect": "NO_NEW_ROUTE_SELECTION",
        },
        "scenarioPlan": [
            {"scenario": scenario, "fieldRequirement": "FIELD_REQUIRED", "safeEffect": effect}
            for scenario, effect in _SCENARIO_EFFECTS
        ],
        "scenarioCaptures": captured["scenarioCaptures"],
        "observationSequence": [],
        "preflightDecisions": [],
        "missionPolicyResult": "NOT_CAPTURED",
        "providerInvocationResult": "NOT_CAPTURED",
        "disconnectAt": None,
        "reconnectAt": None,
        "errors": ["NO_GENUINE_ROUTE_STATE_SIGNAL"],
        "artifactLogDigests": [],
        "overallResult": "INCONCLUSIVE",
        "missionLatencyMeasurement": {
            "requirement": "FIELD_REQUIRED",
            "captureStatus": captured["missionLatency"]["captureStatus"],
        },
    }
    validate_artifact(artifact)
    return artifact


def emit(input_path: Path, output_path: Path) -> None:
    artifact = build_artifact(_load_json(input_path))
    output_path.write_text(_canonical_json(artifact), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    emit_parser = subparsers.add_parser("emit", help="emit deterministic non-approving HIL-0 JSON")
    emit_parser.add_argument("--input", required=True, type=Path)
    emit_parser.add_argument("--output", required=True, type=Path)
    validate_parser = subparsers.add_parser("validate", help="validate an emitted HIL-0 artifact")
    validate_parser.add_argument("--input", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "emit":
            emit(args.input, args.output)
        else:
            validate_artifact(_load_json(args.input))
    except CapabilityRuntimeHilError as exc:
        print(f"capability-runtime-hil: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
