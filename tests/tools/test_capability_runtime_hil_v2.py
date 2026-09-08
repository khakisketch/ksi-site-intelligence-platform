# ruff: noqa: E501, E701, E702
"""Focused hostile-input tests for Route-1 HIL evidence v2."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = _ROOT / "tools/hil/capability_runtime_hil_v2.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capability_runtime_hil_v2", _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _manifest(root: Path, tool: ModuleType, *, status: str = "OBSERVED") -> dict[str, Any]:
    raw_files = {
        "psdk.log": ("PSDK_RAW_LOG", "physical psdk log"),
        "gateway.log": ("GATEWAY_RAW_LOG", "gateway log"),
        "core.log": ("CORE_RAW_LOG", "core ingress log"),
        "peer.log": ("PEER_RAW_LOG", "independent peer receipt"),
        "operator.txt": ("OPERATOR_ATTESTATION", "operator attestation"),
        "timing.log": ("TIMING_LOG", "monotonic timestamps"),
        "observation-journal.json": ("OBSERVATION_JOURNAL_SNAPSHOT", "observation journal snapshot"),
        "authority-journal.json": ("AUTHORITY_JOURNAL_SNAPSHOT", "authority journal snapshot"),
        "mission-reference.json": ("MISSION_REFERENCE", "mission contract reference"),
    }
    for path, (_, content) in raw_files.items(): (root / path).write_text(content, encoding="utf-8")
    def ref(path: str) -> dict[str, str]: return {"rawArtifactRef": path}
    payload = _digest("synthetic-bundle")
    metadata = {"objectRef": "synthetic/edge-bundle.json", "contentType": "application/json", "sha256": payload, "sizeBytes": 42}
    utc = "2026-09-03T01:02:03Z"
    event_data = [
        ("a", tool._SCENARIOS[0], "ROUTE_NOT_READY", 90, "core.log"), ("b1", tool._SCENARIOS[1], "MOP_CONNECTED", 150, "psdk.log"),
        ("b2", tool._SCENARIOS[1], "CORE_INGRESS_ACCEPTED", 180, "core.log"), ("c", tool._SCENARIOS[2], "PRELIGHT_DENIED", 290, "core.log"),
        ("d", tool._SCENARIOS[3], "PRELIGHT_DENIED", 390, "core.log"), ("e", tool._SCENARIOS[4], "PROVIDER_INVOKED", 490, "psdk.log"),
        ("f1", tool._SCENARIOS[5], "TRANSMISSION_HANDOFF", 590, "psdk.log"), ("f2", tool._SCENARIOS[5], "PEER_RECEIPT", 600, "peer.log"),
        ("g1", tool._SCENARIOS[6], "MOP_DISCONNECTED", 650, "psdk.log"), ("g2", tool._SCENARIOS[6], "PROVIDER_DENIED", 660, "gateway.log"),
        ("h1", tool._SCENARIOS[7], "OBSERVATION_EXPIRED", 790, "core.log"), ("h2", tool._SCENARIOS[7], "PRELIGHT_DENIED", 795, "core.log"),
        ("i1", tool._SCENARIOS[8], "MOP_RECONNECTED", 850, "psdk.log"), ("i2", tool._SCENARIOS[8], "RUNTIME_RECOVERED", 860, "gateway.log"),
        ("j1", tool._SCENARIOS[9], "COMPANION_RESTART", 950, "psdk.log"), ("j2", tool._SCENARIOS[9], "RUNTIME_RECOVERED", 960, "gateway.log"),
    ]
    return {
        "authority": {**tool._AUTHORITY, "productCapabilityApproval": "APPROVED", "operationalCapabilityActivation": "ACTIVATED", "productApprovalEvidence": {"id": "approval-1", "digest": "sha256:" + "5" * 64}, "activationEvidence": {"id": "activation-1", "digest": "sha256:" + "6" * 64}, "authorityJournalSnapshot": ref("authority-journal.json")},
        "session": {"evidenceArtifactId": "hil1r-artifact-001", "testRunId": "hil1r-run-001", "startedAtUtc": "2026-09-03T01:00:00Z", "endedAtUtc": "2026-09-03T01:10:00Z", "testEnvironment": "isolated-propeller-off"},
        "route": {"routeId": "HIL_ROUTE_1", "capabilityId": "EDGE_UPLINK", "subjectPortId": "psdk.edge_uplink", "integrationPath": "PSDK_MANIFOLD", "configuredDeploymentDigest": "sha256:" + "a" * 64, "freshnessPolicy": {"id": "route-fast-v1", "digest": "sha256:" + "b" * 64}, "physicalComponentIdentities": [{"componentKind": kind, "identity": f"private-{kind.lower()}", "manufacturer": "KSI", "model": kind, "hardwareRevision": "rev-1"} for kind in ("AIRCRAFT", "RC", "MANIFOLD", "PEER_ENDPOINT")], "firmwareBuildVersions": [{"name": name, "version": "1.0.0", "sha256": "sha256:" + char * 64} for name, char in (("aircraft", "c"), ("rc", "d"), ("manifold", "e"))]},
        "software": {"buildDigest": "sha256:" + "f" * 64, "gitRevision": "0123456789abcdef", "operatorId": "operator-private", "exactPsdkVersion": "3.16.0", "dpkPackageDigest": "sha256:" + "1" * 64, "packageInventory": [{"name": "ksi_psdk_app", "version": "1.0.0", "sha256": "sha256:" + "2" * 64}]},
        "featureFlag": {"id": "edge-uplink", "digest": "sha256:" + "3" * 64, "state": "ON"},
        "mission": {"missionId": "mission-001", "missionContractDigest": "sha256:" + "4" * 64, "missionReference": ref("mission-reference.json"), "policyResult": "ALLOW"},
        "rawArtifacts": [{"ref": path, "role": role, "localPath": path} for path, (role, _) in raw_files.items()],
        "observationJournalSnapshot": ref("observation-journal.json"),
        "observations": [
            {"scenarioId": tool._SCENARIOS[0], "observationId": "obs-a", "signalId": "signal-a", "availability": "UNAVAILABLE", "observedAtMonotonicNs": 80, "observedAtUtc": utc, "expiresAtUtc": "2026-09-03T01:02:04Z", "subjectPortId": "psdk.edge_uplink", "integrationPath": "PSDK_MANIFOLD", "producer": "psdk", "coreIngressResult": "ACCEPTED"},
            {"scenarioId": tool._SCENARIOS[1], "observationId": "obs-b", "signalId": "signal-b", "availability": "AVAILABLE", "observedAtMonotonicNs": 170, "observedAtUtc": utc, "expiresAtUtc": "2026-09-03T01:02:05Z", "subjectPortId": "psdk.edge_uplink", "integrationPath": "PSDK_MANIFOLD", "producer": "psdk", "coreIngressResult": "ACCEPTED"},
            {"scenarioId": tool._SCENARIOS[6], "observationId": "obs-g", "signalId": "signal-g", "availability": "UNAVAILABLE", "observedAtMonotonicNs": 680, "observedAtUtc": utc, "expiresAtUtc": "2026-09-03T01:02:06Z", "subjectPortId": "psdk.edge_uplink", "integrationPath": "PSDK_MANIFOLD", "producer": "psdk", "coreIngressResult": "ACCEPTED"},
            {"scenarioId": tool._SCENARIOS[8], "observationId": "obs-i", "signalId": "signal-i", "availability": "AVAILABLE", "observedAtMonotonicNs": 880, "observedAtUtc": utc, "expiresAtUtc": "2026-09-03T01:02:07Z", "subjectPortId": "psdk.edge_uplink", "integrationPath": "PSDK_MANIFOLD", "producer": "psdk", "coreIngressResult": "ACCEPTED"},
            {"scenarioId": tool._SCENARIOS[9], "observationId": "obs-j", "signalId": "signal-j", "availability": "AVAILABLE", "observedAtMonotonicNs": 980, "observedAtUtc": utc, "expiresAtUtc": "2026-09-03T01:02:08Z", "subjectPortId": "psdk.edge_uplink", "integrationPath": "PSDK_MANIFOLD", "producer": "psdk", "coreIngressResult": "ACCEPTED"},
        ],
        "preflightDecisions": [
            {"scenarioId": tool._SCENARIOS[0], "atMonotonicNs": 85, "requestScope": "A", "decision": "DENY", "reasonCode": "ROUTE_NOT_READY", "timestampUtc": utc, "featureFlagState": "ON", "providerInvoked": False}, {"scenarioId": tool._SCENARIOS[2], "atMonotonicNs": 280, "requestScope": "C", "decision": "DENY", "reasonCode": "FEATURE_FLAG_OFF", "timestampUtc": utc, "featureFlagState": "OFF", "providerInvoked": False}, {"scenarioId": tool._SCENARIOS[3], "atMonotonicNs": 380, "requestScope": "D", "decision": "DENY", "reasonCode": "MISSION_DENY", "timestampUtc": utc, "featureFlagState": "ON", "providerInvoked": False}, {"scenarioId": tool._SCENARIOS[4], "atMonotonicNs": 480, "requestScope": "E", "decision": "ALLOW", "reasonCode": "ROUTE_ALLOWED", "timestampUtc": utc, "featureFlagState": "ON", "providerInvoked": True}, {"scenarioId": tool._SCENARIOS[6], "atMonotonicNs": 685, "requestScope": "G", "decision": "DENY", "reasonCode": "PROVIDER_UNAVAILABLE", "timestampUtc": utc, "featureFlagState": "ON", "providerInvoked": False}, {"scenarioId": tool._SCENARIOS[7], "atMonotonicNs": 780, "requestScope": "H", "decision": "DENY", "reasonCode": "EXPIRED_ROUTE_STATE", "timestampUtc": utc, "featureFlagState": "ON", "providerInvoked": False},
        ],
        "physicalEvents": [{"eventId": event_id, "scenarioId": scenario_id, "eventType": event_type, "atMonotonicNs": at, "timestampUtc": utc, **({"operationId": "DjiMopChannel_SendData-op-1", "payloadSha256": payload} if event_type in {"TRANSMISSION_HANDOFF", "PEER_RECEIPT"} else {}), **ref(log)} for event_id, scenario_id, event_type, at, log in event_data],
        "bundleTransfer": {"providerOperationId": "DjiMopChannel_SendData-op-1", "payloadKind": "EDGE_BUNDLE_METADATA_ONLY", "acceptedFramesBefore": 7, "acceptedFramesAfter": 8, "objectMetadata": metadata, "claimedSha256": payload, "peerValidatedMetadata": dict(metadata), "providerRawLog": ref("psdk.log"), "independentPeerLog": ref("peer.log"), "peerReceiptTimestampUtc": utc},
        "scenarioCaptures": [{"id": scenario, "observedAtMonotonicNs": (index + 1) * 100, "status": status, "evidenceRefs": [ref("timing.log")]} for index, scenario in enumerate(tool._SCENARIOS)],
    }


def test_complete_capture_finalize_is_deterministic_and_non_authoritative(tmp_path: Path) -> None:
    tool = _tool(); capture = tool.capture(_manifest(tmp_path, tool), tmp_path)
    artifact = tool.finalize(capture, tmp_path, verified_at_utc="2026-09-03T02:03:04Z")
    assert "verifierDecision" not in capture
    assert artifact["verifierDecision"]["result"] == "PASS"
    assert artifact["authority"]["routeEvidenceQualification"] == "NOT_QUALIFIED"
    assert artifact["rawCapture"]["bundleTransfer"]["providerRawLog"]["rawArtifactRef"] != artifact["rawCapture"]["bundleTransfer"]["independentPeerLog"]["rawArtifactRef"]
    tool.validate_artifact(artifact, tmp_path)


@pytest.mark.parametrize(("mutate", "match"), [
    (lambda data: data["route"]["physicalComponentIdentities"][0].pop("hardwareRevision"), "physical"),
    (lambda data: data["scenarioCaptures"][0].__setitem__("status", "PASS"), "사용자가 입력한 PASS"),
    (lambda data: data["scenarioCaptures"].__setitem__(0, data["scenarioCaptures"][1]), "scenario A-J"),
    (lambda data: data["preflightDecisions"][1].__setitem__("providerInvoked", True), "preflight/provider"),
    (lambda data: data["bundleTransfer"]["peerValidatedMetadata"].__setitem__("sha256", "sha256:" + "0" * 64), "metadata/digest"),
    (lambda data: data["physicalEvents"][6].__setitem__("operationId", "wrong-operation"), "operationId"),
    (lambda data: data["bundleTransfer"].__setitem__("acceptedFramesAfter", 9), "acceptedFrames"),
    (lambda data: data["observations"][1].__setitem__("coreIngressResult", "REJECTED"), "B_REAL_CONNECT"),
    (lambda data: data["authority"].pop("authorityJournalSnapshot"), "authority"),
    (lambda data: data["mission"].pop("missionReference"), "mission"),
    (lambda data: data.__setitem__("overallPassed", True), "capture manifest"),
])
def test_rejects_missing_fields_fabricated_pass_scenario_and_provider_inconsistency(tmp_path: Path, mutate: object, match: str) -> None:
    tool = _tool(); manifest = _manifest(tmp_path, tool); mutate(manifest)  # type: ignore[operator]
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match=match): tool.capture(manifest, tmp_path)


def test_rejects_raw_and_output_artifact_tampering(tmp_path: Path) -> None:
    tool = _tool(); capture = tool.capture(_manifest(tmp_path, tool), tmp_path)
    (tmp_path / "peer.log").write_text("changed", encoding="utf-8")
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="digest 또는 size"): tool.finalize(capture, tmp_path, verified_at_utc="2026-09-03T02:03:04Z")
    capture = tool.capture(_manifest(tmp_path, tool), tmp_path)
    artifact = tool.finalize(capture, tmp_path, verified_at_utc="2026-09-03T02:03:04Z")
    artifact["authority"]["routeEvidenceQualification"] = "QUALIFIED"
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="schema validation|qualification"): tool.validate_artifact(artifact, tmp_path)


def test_rejects_path_traversal_and_symlink_escape(tmp_path: Path) -> None:
    tool = _tool(); outside = tmp_path.parent / "outside-hil.log"; outside.write_text("outside", encoding="utf-8")
    manifest = _manifest(tmp_path, tool); manifest["rawArtifacts"][0]["localPath"] = "../outside-hil.log"
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="path traversal"): tool.capture(manifest, tmp_path)
    manifest = _manifest(tmp_path, tool); link = tmp_path / "escape.log"; link.symlink_to(outside); manifest["rawArtifacts"][0]["localPath"] = "escape.log"
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="path traversal|symlink"): tool.capture(manifest, tmp_path)


def test_rejects_schema_missing_field_fabricated_verdict_and_inconsistent_events(tmp_path: Path) -> None:
    tool = _tool(); capture = tool.capture(_manifest(tmp_path, tool, status="INCONCLUSIVE"), tmp_path)
    artifact = tool.finalize(capture, tmp_path, verified_at_utc="2026-09-03T02:03:04Z")
    artifact["verifierDecision"]["result"] = "PASS"
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="결정적으로"): tool.validate_artifact(artifact, tmp_path)
    capture = tool.capture(_manifest(tmp_path, tool), tmp_path); capture["session"].pop("testRunId")
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="schema validation"): tool.validate_raw_capture(capture, tmp_path)
    manifest = _manifest(tmp_path, tool); manifest["physicalEvents"] = [event for event in manifest["physicalEvents"] if event["eventType"] != "PEER_RECEIPT"]
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="F_SYNTHETIC_SEND"): tool.capture(manifest, tmp_path)


def test_enforces_fail_enum_scenario_windows_and_no_cap4_event(tmp_path: Path) -> None:
    tool = _tool(); artifact = tool.finalize(tool.capture(_manifest(tmp_path, tool, status="FAIL"), tmp_path), tmp_path, verified_at_utc="2026-09-03T02:03:04Z")
    assert artifact["verifierDecision"]["result"] == "FAIL"
    manifest = _manifest(tmp_path, tool); manifest["physicalEvents"][1]["atMonotonicNs"] = 250
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="scenario window"): tool.capture(manifest, tmp_path)
    manifest = _manifest(tmp_path, tool); manifest["physicalEvents"].append({"eventId": "cap4", "scenarioId": tool._SCENARIOS[8], "eventType": "CAP4_ACTIVATED", "atMonotonicNs": 899, "timestampUtc": "2026-09-03T01:02:03Z", "rawArtifactRef": "gateway.log"})
    with pytest.raises(tool.CapabilityRuntimeHilV2Error, match="schema validation"): tool.capture(manifest, tmp_path)


def test_failed_or_inconclusive_scenario_does_not_require_fabricated_success(tmp_path: Path) -> None:
    tool = _tool(); manifest = _manifest(tmp_path, tool)
    manifest["scenarioCaptures"][5]["status"] = "FAIL"
    manifest["physicalEvents"] = [event for event in manifest["physicalEvents"] if event["scenarioId"] != tool._SCENARIOS[5]]
    manifest["bundleTransfer"] = None
    artifact = tool.finalize(tool.capture(manifest, tmp_path), tmp_path, verified_at_utc="2026-09-03T02:03:04Z")
    assert artifact["verifierDecision"]["result"] == "FAIL"
    assert artifact["verifierDecision"]["reasonCodes"] == [f"{tool._SCENARIOS[5]}_FAIL"]


def test_preserves_optional_authority_references_without_promoting_them(tmp_path: Path) -> None:
    tool = _tool(); manifest = _manifest(tmp_path, tool)
    artifact = tool.finalize(tool.capture(manifest, tmp_path), tmp_path, verified_at_utc="2026-09-03T02:03:04Z")
    assert artifact["authority"]["productCapabilityApproval"] == "APPROVED"
    assert artifact["authority"]["operationalCapabilityActivation"] == "ACTIVATED"
    assert artifact["authority"]["authorityDecisionCreatedByTool"] is False
    assert artifact["authority"]["routeEvidenceQualification"] == "NOT_QUALIFIED"


def test_cli_only_reads_local_files(tmp_path: Path) -> None:
    tool = _tool(); manifest_path, capture_path, artifact_path = tmp_path / "manifest.json", tmp_path / "capture.json", tmp_path / "artifact.json"
    manifest_path.write_text(json.dumps(_manifest(tmp_path, tool)), encoding="utf-8")
    assert tool.main(["capture", "--manifest", str(manifest_path), "--raw-root", str(tmp_path), "--output", str(capture_path)]) == 0
    assert tool.main(["validate-capture", "--input", str(capture_path), "--raw-root", str(tmp_path)]) == 0
    assert tool.main(["finalize", "--capture", str(capture_path), "--raw-root", str(tmp_path), "--verified-at-utc", "2026-09-03T02:03:04Z", "--output", str(artifact_path)]) == 0
    assert tool.main(["validate-artifact", "--input", str(artifact_path), "--raw-root", str(tmp_path)]) == 0
