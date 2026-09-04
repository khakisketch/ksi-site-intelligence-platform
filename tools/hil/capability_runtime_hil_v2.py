# ruff: noqa: E501, E701, E702
"""Offline Route-1 HIL raw-capture and deterministic evidence verifier.

The executable only reads JSON and local raw files.  It intentionally has no
Core client, network, DJI SDK, device, CAP-2, approval, or activation path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "capability-runtime-hil-evidence-v2"
_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _ROOT / "contracts/hil/capability-runtime-hil-evidence-v2.schema.json"
_SCENARIOS = (
    "A_ABSENT_UNAVAILABLE_NOT_READY",
    "B_REAL_CONNECT_CORE_ACCEPTS",
    "C_FLAG_OFF_DENY_NO_INVOKE",
    "D_MISSION_DENY_NO_INVOKE",
    "E_SAFE_ON_ALLOW_INVOKE",
    "F_SYNTHETIC_SEND_INDEPENDENT_PEER_RECEIPT",
    "G_DISCONNECT_UNAVAILABLE_PROVIDER_DENIED",
    "H_EXPIRY_STALE_DENY",
    "I_RECONNECT_NEW_OBSERVATION_RUNTIME_RECOVERY_NO_CAP4",
    "J_COMPANION_RESTART_NEW_SIGNAL_OBSERVATION_RECOVERY",
)
_AUTHORITY = {
    "routeEvidenceQualification": "NOT_QUALIFIED",
    "qualificationScope": "ROUTE_1_HIL_RAW_EVIDENCE_ONLY",
    "authorityDecisionCreatedByTool": False,
    "productCapabilityApproval": "NOT_APPROVED",
    "operationalCapabilityActivation": "NOT_ACTIVATED",
    "productApprovalEvidence": None,
    "activationEvidence": None,
}
_ROLES = {"PSDK_RAW_LOG", "GATEWAY_RAW_LOG", "CORE_RAW_LOG", "PEER_RAW_LOG", "OPERATOR_ATTESTATION", "TIMING_LOG", "OBSERVATION_JOURNAL_SNAPSHOT", "AUTHORITY_JOURNAL_SNAPSHOT", "MISSION_REFERENCE"}
_COMPONENTS = {"AIRCRAFT", "RC", "MANIFOLD", "PEER_ENDPOINT"}
_EVENTS: dict[str, tuple[str, ...]] = {
    _SCENARIOS[0]: ("ROUTE_NOT_READY",),
    _SCENARIOS[1]: ("MOP_CONNECTED", "CORE_INGRESS_ACCEPTED"),
    _SCENARIOS[2]: ("PRELIGHT_DENIED",),
    _SCENARIOS[3]: ("PRELIGHT_DENIED",),
    _SCENARIOS[4]: ("PROVIDER_INVOKED",),
    _SCENARIOS[5]: ("TRANSMISSION_HANDOFF", "PEER_RECEIPT"),
    _SCENARIOS[6]: ("MOP_DISCONNECTED", "PROVIDER_DENIED"),
    _SCENARIOS[7]: ("OBSERVATION_EXPIRED", "PRELIGHT_DENIED"),
    _SCENARIOS[8]: ("MOP_RECONNECTED", "RUNTIME_RECOVERED"),
    _SCENARIOS[9]: ("COMPANION_RESTART", "RUNTIME_RECOVERED"),
}
_PREFLIGHTS: dict[str, tuple[str, bool, str]] = {
    _SCENARIOS[0]: ("ROUTE_NOT_READY", False, "ON"), _SCENARIOS[2]: ("FEATURE_FLAG_OFF", False, "OFF"),
    _SCENARIOS[3]: ("MISSION_DENY", False, "ON"), _SCENARIOS[4]: ("ROUTE_ALLOWED", True, "ON"),
    _SCENARIOS[6]: ("PROVIDER_UNAVAILABLE", False, "ON"), _SCENARIOS[7]: ("EXPIRED_ROUTE_STATE", False, "ON"),
}


class CapabilityRuntimeHilV2Error(ValueError):
    """Unsafe, incomplete, inconsistent, or tampered evidence."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityRuntimeHilV2Error(f"JSON을 읽을 수 없다: {path}") from exc


def _mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CapabilityRuntimeHilV2Error(f"{name}의 필드가 정확하지 않다")
    return value


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CapabilityRuntimeHilV2Error(f"{name}는 배열이어야 한다")
    return list(value)


def _utc(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CapabilityRuntimeHilV2Error(f"{field}는 Z UTC ISO-8601 문자열이어야 한다")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CapabilityRuntimeHilV2Error(f"{field}를 파싱할 수 없다") from exc
    if parsed.utcoffset() != UTC.utcoffset(parsed) or parsed.microsecond:
        raise CapabilityRuntimeHilV2Error(f"{field}는 초 단위 UTC여야 한다")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _before(left: str, right: str, label: str) -> None:
    if _utc(left, label) > _utc(right, label):
        raise CapabilityRuntimeHilV2Error(f"{label} timestamp 순서가 역전됐다")


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:") or any(c not in "0123456789abcdef" for c in value[7:]):
        raise CapabilityRuntimeHilV2Error(f"{field}는 sha256:<64hex>여야 한다")
    return value


def _string(value: object, field: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise CapabilityRuntimeHilV2Error(f"{field}가 필요하다")
    return value


def _reject_pass(value: object) -> None:
    if isinstance(value, Mapping):
        for child in value.values(): _reject_pass(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value: _reject_pass(child)
    elif value == "PASS":
        raise CapabilityRuntimeHilV2Error("raw capture에 사용자가 입력한 PASS는 허용되지 않는다")


def _hash(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk); size += len(chunk)
    except OSError as exc:
        raise CapabilityRuntimeHilV2Error(f"raw artifact를 읽을 수 없다: {path}") from exc
    if not size: raise CapabilityRuntimeHilV2Error("빈 raw artifact는 증거가 될 수 없다")
    return f"sha256:{digest.hexdigest()}", size


def _raw_path(root: Path, ref: object) -> Path:
    if not isinstance(ref, str) or not ref or Path(ref).is_absolute():
        raise CapabilityRuntimeHilV2Error("raw path는 root 아래 상대 경로여야 한다")
    resolved, safe_root = (root / ref).resolve(), root.resolve()
    if safe_root not in resolved.parents or not resolved.is_file():
        raise CapabilityRuntimeHilV2Error("raw path traversal 또는 symlink escape를 거부한다")
    return resolved


def _authority(value: object, artifacts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    authority = _mapping(value, set(_AUTHORITY) | {"authorityJournalSnapshot"}, "authority")
    if authority["routeEvidenceQualification"] != "NOT_QUALIFIED" or authority["qualificationScope"] != "ROUTE_1_HIL_RAW_EVIDENCE_ONLY" or authority["authorityDecisionCreatedByTool"] is not False:
        raise CapabilityRuntimeHilV2Error("CAP-2 qualification 또는 scope 승격은 허용되지 않는다")
    approval = authority["productCapabilityApproval"]
    activation = authority["operationalCapabilityActivation"]
    if approval not in {"APPROVED", "NOT_APPROVED"} or activation not in {"ACTIVATED", "NOT_ACTIVATED"}:
        raise CapabilityRuntimeHilV2Error("기존 approval/activation 상태가 유효하지 않다")
    result: dict[str, Any] = {"routeEvidenceQualification": "NOT_QUALIFIED", "qualificationScope": "ROUTE_1_HIL_RAW_EVIDENCE_ONLY", "authorityDecisionCreatedByTool": False, "productCapabilityApproval": approval, "operationalCapabilityActivation": activation}
    result["authorityJournalSnapshot"] = _hydrate_ref(authority["authorityJournalSnapshot"], artifacts, "authority journal snapshot")
    if artifacts[result["authorityJournalSnapshot"]["rawArtifactRef"]]["role"] != "AUTHORITY_JOURNAL_SNAPSHOT":
        raise CapabilityRuntimeHilV2Error("authority journal snapshot raw evidence가 필요하다")
    for key in ("productApprovalEvidence", "activationEvidence"):
        item = authority[key]
        if item is None: result[key] = None; continue
        evidence = _mapping(item, {"id", "digest"}, key)
        result[key] = {"id": _string(evidence["id"], f"{key}.id"), "digest": _digest(evidence["digest"], f"{key}.digest")}
    if (approval == "APPROVED") != (result["productApprovalEvidence"] is not None):
        raise CapabilityRuntimeHilV2Error("approval 상태와 기존 approval evidence가 일치하지 않는다")
    if (activation == "ACTIVATED") != (result["activationEvidence"] is not None):
        raise CapabilityRuntimeHilV2Error("activation 상태와 기존 activation evidence가 일치하지 않는다")
    if activation == "ACTIVATED" and approval != "APPROVED":
        raise CapabilityRuntimeHilV2Error("activation은 기존 product approval 없이 존재할 수 없다")
    return result


def _packages(value: object, name: str, minimum: int) -> list[dict[str, str]]:
    result, names = [], set()
    for item in _array(value, name):
        package = _mapping(item, {"name", "version", "sha256"}, name)
        package_name = _string(package["name"], f"{name}.name")
        if package_name in names: raise CapabilityRuntimeHilV2Error(f"{name} package가 중복됐다")
        names.add(package_name)
        result.append({"name": package_name, "version": _string(package["version"], f"{name}.version"), "sha256": _digest(package["sha256"], f"{name}.sha256")})
    if len(result) < minimum: raise CapabilityRuntimeHilV2Error(f"{name}가 부족하다")
    return result


def _session(value: object) -> dict[str, str]:
    session = _mapping(value, {"evidenceArtifactId", "testRunId", "startedAtUtc", "endedAtUtc", "testEnvironment"}, "session")
    result = {key: _string(session[key], f"session.{key}") for key in ("evidenceArtifactId", "testRunId", "testEnvironment")}
    result["startedAtUtc"], result["endedAtUtc"] = _utc(session["startedAtUtc"], "session.startedAtUtc"), _utc(session["endedAtUtc"], "session.endedAtUtc")
    _before(result["startedAtUtc"], result["endedAtUtc"], "session")
    return result


def _route(value: object) -> dict[str, Any]:
    route = _mapping(value, {"routeId", "capabilityId", "subjectPortId", "integrationPath", "configuredDeploymentDigest", "freshnessPolicy", "physicalComponentIdentities", "firmwareBuildVersions"}, "route")
    if route["routeId"] != "HIL_ROUTE_1" or route["capabilityId"] != "EDGE_UPLINK" or route["integrationPath"] != "PSDK_MANIFOLD": raise CapabilityRuntimeHilV2Error("Route-1 capability identity가 정확하지 않다")
    policy = _mapping(route["freshnessPolicy"], {"id", "digest"}, "freshnessPolicy")
    identities, kinds = [], set()
    for item in _array(route["physicalComponentIdentities"], "physicalComponentIdentities"):
        identity = _mapping(item, {"componentKind", "identity", "manufacturer", "model", "hardwareRevision"}, "physical identity")
        kind = identity["componentKind"]
        if kind not in _COMPONENTS or kind in kinds: raise CapabilityRuntimeHilV2Error("physical aircraft/RC/Manifold/peer identity가 완전하지 않다")
        kinds.add(kind); identities.append({key: _string(identity[key], f"physical.{key}") for key in identity})
    if kinds != _COMPONENTS: raise CapabilityRuntimeHilV2Error("physical aircraft/RC/Manifold/peer ID와 hardware revision이 모두 필요하다")
    return {"routeId": "HIL_ROUTE_1", "capabilityId": "EDGE_UPLINK", "subjectPortId": _string(route["subjectPortId"], "route.subjectPortId"), "integrationPath": "PSDK_MANIFOLD", "configuredDeploymentDigest": _digest(route["configuredDeploymentDigest"], "configuredDeploymentDigest"), "freshnessPolicy": {"id": _string(policy["id"], "freshnessPolicy.id"), "digest": _digest(policy["digest"], "freshnessPolicy.digest")}, "physicalComponentIdentities": identities, "firmwareBuildVersions": _packages(route["firmwareBuildVersions"], "firmwareBuildVersions", 3)}


def _software(value: object) -> dict[str, Any]:
    software = _mapping(value, {"buildDigest", "gitRevision", "operatorId", "exactPsdkVersion", "dpkPackageDigest", "packageInventory"}, "software")
    return {"buildDigest": _digest(software["buildDigest"], "software.buildDigest"), "gitRevision": _string(software["gitRevision"], "software.gitRevision", 7), "operatorId": _string(software["operatorId"], "software.operatorId"), "exactPsdkVersion": _string(software["exactPsdkVersion"], "software.exactPsdkVersion"), "dpkPackageDigest": _digest(software["dpkPackageDigest"], "software.dpkPackageDigest"), "packageInventory": _packages(software["packageInventory"], "packageInventory", 1)}


def _manifest_raw(value: object, root: Path) -> list[dict[str, Any]]:
    result, refs, roles = [], set(), set()
    for item in _array(value, "rawArtifacts"):
        raw = _mapping(item, {"ref", "role", "localPath"}, "raw artifact manifest")
        ref, role = _string(raw["ref"], "rawArtifact.ref"), raw["role"]
        if ref in refs or role not in _ROLES or role in roles: raise CapabilityRuntimeHilV2Error("raw artifact ref/role이 유효하지 않다")
        digest, size = _hash(_raw_path(root, raw["localPath"]))
        result.append({"ref": ref, "role": role, "sha256": digest, "sizeBytes": size}); refs.add(ref); roles.add(role)
    if roles != _ROLES: raise CapabilityRuntimeHilV2Error("PSDK/Gateway/Core/peer/operator/timing raw evidence가 모두 필요하다")
    return result


def _raw_artifacts(value: object, root: Path | None) -> dict[str, dict[str, Any]]:
    result, roles = {}, set()
    for item in _array(value, "rawArtifacts"):
        raw = _mapping(item, {"ref", "role", "sha256", "sizeBytes"}, "raw artifact")
        ref, role = _string(raw["ref"], "rawArtifact.ref"), raw["role"]
        if ref in result or role not in _ROLES or role in roles or not isinstance(raw["sizeBytes"], int) or raw["sizeBytes"] < 1: raise CapabilityRuntimeHilV2Error("raw artifact ref/role/size가 유효하지 않다")
        result[ref] = {"ref": ref, "role": role, "sha256": _digest(raw["sha256"], "rawArtifact.sha256"), "sizeBytes": raw["sizeBytes"]}; roles.add(role)
    if roles != _ROLES: raise CapabilityRuntimeHilV2Error("PSDK/Gateway/Core/peer/operator/timing raw evidence가 모두 필요하다")
    if root:
        for item in result.values():
            digest, size = _hash(_raw_path(root, item["ref"]))
            if digest != item["sha256"] or size != item["sizeBytes"]: raise CapabilityRuntimeHilV2Error("raw artifact digest 또는 size가 재계산 결과와 다르다")
    return result


def _hydrate_ref(value: object, artifacts: Mapping[str, Mapping[str, Any]], name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) not in ({"rawArtifactRef"}, {"rawArtifactRef", "rawArtifactSha256"}): raise CapabilityRuntimeHilV2Error(f"{name}의 필드가 정확하지 않다")
    ref = value["rawArtifactRef"]
    if not isinstance(ref, str) or ref not in artifacts: raise CapabilityRuntimeHilV2Error(f"{name} raw artifact ref가 없다")
    digest = artifacts[ref]["sha256"]
    if "rawArtifactSha256" in value and _digest(value["rawArtifactSha256"], name) != digest: raise CapabilityRuntimeHilV2Error(f"{name} raw digest가 일치하지 않는다")
    return {"rawArtifactRef": ref, "rawArtifactSha256": digest}


def _capture_body(value: object, root: Path | None) -> dict[str, Any]:
    raw = _mapping(value, {"artifactType", "schemaVersion", "nonActuating", "authority", "session", "route", "software", "featureFlag", "mission", "rawArtifacts", "observationJournalSnapshot", "observations", "preflightDecisions", "physicalEvents", "bundleTransfer", "scenarioCaptures"}, "raw capture")
    if raw["artifactType"] != "HIL_1R_ROUTE_1_RAW_CAPTURE" or raw["schemaVersion"] != SCHEMA_VERSION or raw["nonActuating"] is not True: raise CapabilityRuntimeHilV2Error("HIL-1R raw capture type/version/nonActuating이 유효하지 않다")
    artifacts = _raw_artifacts(raw["rawArtifacts"], root)
    authority, session, route, software = _authority(raw["authority"], artifacts), _session(raw["session"]), _route(raw["route"]), _software(raw["software"])
    observation_journal = _hydrate_ref(raw["observationJournalSnapshot"], artifacts, "observation journal snapshot")
    if artifacts[observation_journal["rawArtifactRef"]]["role"] != "OBSERVATION_JOURNAL_SNAPSHOT":
        raise CapabilityRuntimeHilV2Error("observation journal snapshot raw evidence가 필요하다")
    flag = _mapping(raw["featureFlag"], {"id", "digest", "state"}, "featureFlag")
    if flag["state"] not in {"ON", "OFF"}: raise CapabilityRuntimeHilV2Error("feature flag state가 유효하지 않다")
    feature = {"id": _string(flag["id"], "featureFlag.id"), "digest": _digest(flag["digest"], "featureFlag.digest"), "state": flag["state"]}
    mission = _mapping(raw["mission"], {"missionId", "missionContractDigest", "missionReference", "policyResult"}, "mission")
    if mission["policyResult"] not in {"ALLOW", "DENY"}: raise CapabilityRuntimeHilV2Error("mission policy result가 유효하지 않다")
    mission_reference = _hydrate_ref(mission["missionReference"], artifacts, "mission reference")
    if artifacts[mission_reference["rawArtifactRef"]]["role"] != "MISSION_REFERENCE":
        raise CapabilityRuntimeHilV2Error("mission reference raw evidence가 필요하다")
    mission_value = {"missionId": _string(mission["missionId"], "missionId"), "missionContractDigest": _digest(mission["missionContractDigest"], "missionContractDigest"), "missionReference": mission_reference, "policyResult": mission["policyResult"]}

    scenarios, times, previous = [], {}, -1
    for expected, item in zip(_SCENARIOS, _array(raw["scenarioCaptures"], "scenarioCaptures"), strict=True):
        scenario = _mapping(item, {"id", "observedAtMonotonicNs", "status", "evidenceRefs"}, "scenario")
        if scenario["id"] != expected or not isinstance(scenario["observedAtMonotonicNs"], int) or scenario["observedAtMonotonicNs"] <= previous or scenario["status"] not in {"OBSERVED", "FAIL", "INCONCLUSIVE", "NOT_CAPTURED"}: raise CapabilityRuntimeHilV2Error("scenario A-J order/status/monotonic timestamp가 유효하지 않다")
        refs = [_hydrate_ref(ref, artifacts, "scenario evidence") for ref in _array(scenario["evidenceRefs"], "scenario evidenceRefs")]
        if not refs: raise CapabilityRuntimeHilV2Error("각 scenario에는 raw evidence가 필요하다")
        previous, times[expected] = scenario["observedAtMonotonicNs"], scenario["observedAtMonotonicNs"]
        scenarios.append({"id": expected, "observedAtMonotonicNs": previous, "status": scenario["status"], "evidenceRefs": refs})
    if len(scenarios) != 10: raise CapabilityRuntimeHilV2Error("scenario A-J가 모두 필요하다")

    observations, observation_ids, signals = [], set(), set()
    for item in _array(raw["observations"], "observations"):
        obs = _mapping(item, {"scenarioId", "observationId", "signalId", "availability", "observedAtMonotonicNs", "observedAtUtc", "expiresAtUtc", "subjectPortId", "integrationPath", "producer", "coreIngressResult"}, "observation")
        oid, signal = _string(obs["observationId"], "observationId"), _string(obs["signalId"], "signalId")
        if oid in observation_ids or signal in signals or obs["scenarioId"] not in {_SCENARIOS[0], _SCENARIOS[1], _SCENARIOS[6], _SCENARIOS[8], _SCENARIOS[9]} or obs["availability"] not in {"AVAILABLE", "UNAVAILABLE"} or obs["coreIngressResult"] not in {"ACCEPTED", "REJECTED"} or not isinstance(obs["observedAtMonotonicNs"], int) or obs["subjectPortId"] != route["subjectPortId"] or obs["integrationPath"] != "PSDK_MANIFOLD": raise CapabilityRuntimeHilV2Error("observation identity/route/availability/core ingress가 일관되지 않다")
        observed, expires = _utc(obs["observedAtUtc"], "observation.observedAtUtc"), _utc(obs["expiresAtUtc"], "observation.expiresAtUtc"); _before(observed, expires, "observation")
        if not (0 if obs["scenarioId"] == _SCENARIOS[0] else times[_SCENARIOS[_SCENARIOS.index(obs["scenarioId"]) - 1]]) < obs["observedAtMonotonicNs"] <= times[obs["scenarioId"]]: raise CapabilityRuntimeHilV2Error("observation이 scenario window 밖에 있다")
        observations.append({"scenarioId": obs["scenarioId"], "observationId": oid, "signalId": signal, "availability": obs["availability"], "observedAtMonotonicNs": obs["observedAtMonotonicNs"], "observedAtUtc": observed, "expiresAtUtc": expires, "subjectPortId": route["subjectPortId"], "integrationPath": "PSDK_MANIFOLD", "producer": _string(obs["producer"], "producer"), "coreIngressResult": obs["coreIngressResult"]}); observation_ids.add(oid); signals.add(signal)
    expected_observations = {_SCENARIOS[0]: "UNAVAILABLE", _SCENARIOS[1]: "AVAILABLE", _SCENARIOS[6]: "UNAVAILABLE", _SCENARIOS[8]: "AVAILABLE", _SCENARIOS[9]: "AVAILABLE"}
    observed_scenarios = {item["id"] for item in scenarios if item["status"] == "OBSERVED"}
    if {_SCENARIOS[3], _SCENARIOS[4]} & observed_scenarios and (
        authority["productCapabilityApproval"] != "APPROVED"
        or authority["operationalCapabilityActivation"] != "ACTIVATED"
    ):
        raise CapabilityRuntimeHilV2Error("D/E observed scenario에는 기존 approval/activation authority evidence가 필요하다")
    for scenario_id, availability in expected_observations.items():
        if scenario_id in observed_scenarios and not any(item["scenarioId"] == scenario_id and item["availability"] == availability and item["coreIngressResult"] == "ACCEPTED" for item in observations): raise CapabilityRuntimeHilV2Error(f"{scenario_id} exact observation/Core ingress evidence가 없다")

    preflights = []
    for item in _array(raw["preflightDecisions"], "preflightDecisions"):
        decision = _mapping(item, {"scenarioId", "atMonotonicNs", "requestScope", "decision", "reasonCode", "timestampUtc", "featureFlagState", "providerInvoked"}, "preflight")
        if decision["scenarioId"] not in _PREFLIGHTS or not isinstance(decision["atMonotonicNs"], int) or decision["decision"] not in {"ALLOW", "DENY"} or decision["featureFlagState"] not in {"ON", "OFF"} or not isinstance(decision["providerInvoked"], bool): raise CapabilityRuntimeHilV2Error("preflight scenario/decision/feature flag/providerInvoked가 유효하지 않다")
        if not (0 if decision["scenarioId"] == _SCENARIOS[0] else times[_SCENARIOS[_SCENARIOS.index(decision["scenarioId"]) - 1]]) < decision["atMonotonicNs"] <= times[decision["scenarioId"]]: raise CapabilityRuntimeHilV2Error("preflight가 scenario window 밖에 있다")
        preflights.append({"scenarioId": decision["scenarioId"], "atMonotonicNs": decision["atMonotonicNs"], "requestScope": _string(decision["requestScope"], "preflight.requestScope"), "decision": decision["decision"], "reasonCode": _string(decision["reasonCode"], "preflight.reasonCode"), "timestampUtc": _utc(decision["timestampUtc"], "preflight.timestampUtc"), "featureFlagState": decision["featureFlagState"], "providerInvoked": decision["providerInvoked"]})
    for required_scenario, (reason, invoked, flag_state) in _PREFLIGHTS.items():
        required_decision = "ALLOW" if required_scenario == _SCENARIOS[4] else "DENY"
        if required_scenario in observed_scenarios and not any(item["scenarioId"] == required_scenario and item["decision"] == required_decision and item["reasonCode"] == reason and item["providerInvoked"] is invoked and item["featureFlagState"] == flag_state for item in preflights): raise CapabilityRuntimeHilV2Error(f"{required_scenario} preflight/provider invocation evidence가 없다")

    events, ids = [], set()
    for item in _array(raw["physicalEvents"], "physicalEvents"):
        event_fields = {"scenarioId", "eventId", "eventType", "atMonotonicNs", "timestampUtc", "rawArtifactRef", "rawArtifactSha256"}
        event_fields |= {"operationId"} if "operationId" in item else set()
        event_fields |= {"payloadSha256"} if "payloadSha256" in item else set()
        event = _mapping(item, event_fields, "physical event")
        event_id = _string(event["eventId"], "eventId")
        if event_id in ids or event["scenarioId"] not in _SCENARIOS or event["eventType"] not in {event_type for values in _EVENTS.values() for event_type in values} | {"PROVIDER_DENIED"} or not isinstance(event["atMonotonicNs"], int): raise CapabilityRuntimeHilV2Error("physical event scenario/identity/type/timestamp가 유효하지 않다")
        if not (0 if event["scenarioId"] == _SCENARIOS[0] else times[_SCENARIOS[_SCENARIOS.index(event["scenarioId"]) - 1]]) < event["atMonotonicNs"] <= times[event["scenarioId"]]: raise CapabilityRuntimeHilV2Error("physical event가 scenario window 밖에 있다")
        reference = _hydrate_ref({"rawArtifactRef": event["rawArtifactRef"], "rawArtifactSha256": event["rawArtifactSha256"]}, artifacts, "physical event")
        checked_event = {"scenarioId": event["scenarioId"], "eventId": event_id, "eventType": event["eventType"], "atMonotonicNs": event["atMonotonicNs"], "timestampUtc": _utc(event["timestampUtc"], "physicalEvent.timestampUtc"), **reference}
        if "operationId" in event: checked_event["operationId"] = _string(event["operationId"], "physicalEvent.operationId")
        if "payloadSha256" in event: checked_event["payloadSha256"] = _digest(event["payloadSha256"], "physicalEvent.payloadSha256")
        events.append(checked_event); ids.add(event_id)
    for required_scenario, required in _EVENTS.items():
        if required_scenario in observed_scenarios and any(not any(event["scenarioId"] == required_scenario and event["eventType"] == event_type for event in events) for event_type in required): raise CapabilityRuntimeHilV2Error(f"{required_scenario} exact physical event evidence가 없다")
    def event_at(scenario_id: str, event_type: str) -> int:
        return next(event["atMonotonicNs"] for event in events if event["scenarioId"] == scenario_id and event["eventType"] == event_type)
    def observation_at(scenario_id: str) -> int:
        return next(item["observedAtMonotonicNs"] for item in observations if item["scenarioId"] == scenario_id)
    if _SCENARIOS[1] in observed_scenarios and not event_at(_SCENARIOS[1], "MOP_CONNECTED") < observation_at(_SCENARIOS[1]) <= event_at(_SCENARIOS[1], "CORE_INGRESS_ACCEPTED"):
        raise CapabilityRuntimeHilV2Error("B real connect/AVAILABLE/Core acceptance temporal correlation이 유효하지 않다")
    if _SCENARIOS[6] in observed_scenarios and observation_at(_SCENARIOS[6]) <= event_at(_SCENARIOS[6], "MOP_DISCONNECTED"):
        raise CapabilityRuntimeHilV2Error("G disconnect 뒤 UNAVAILABLE observation이 필요하다")
    if _SCENARIOS[8] in observed_scenarios and observation_at(_SCENARIOS[8]) <= max(event_at(_SCENARIOS[8], "MOP_RECONNECTED"), event_at(_SCENARIOS[8], "RUNTIME_RECOVERED")):
        raise CapabilityRuntimeHilV2Error("I reconnect/runtime recovery 뒤 new observation이 필요하다")
    if _SCENARIOS[9] in observed_scenarios and observation_at(_SCENARIOS[9]) <= max(event_at(_SCENARIOS[9], "COMPANION_RESTART"), event_at(_SCENARIOS[9], "RUNTIME_RECOVERED")):
        raise CapabilityRuntimeHilV2Error("J companion restart 뒤 new signal/observation recovery가 필요하다")

    if raw["bundleTransfer"] is None:
        if _SCENARIOS[5] in observed_scenarios:
            raise CapabilityRuntimeHilV2Error("F_SYNTHETIC_SEND에는 independent peer receipt bundle evidence가 필요하다")
        bundle_value = None
        return {"schemaVersion": SCHEMA_VERSION, "artifactType": "HIL_1R_ROUTE_1_RAW_CAPTURE", "nonActuating": True, "authority": authority, "session": session, "route": route, "software": software, "featureFlag": feature, "mission": mission_value, "rawArtifacts": list(artifacts.values()), "observationJournalSnapshot": observation_journal, "observations": observations, "preflightDecisions": preflights, "physicalEvents": events, "bundleTransfer": bundle_value, "scenarioCaptures": scenarios}
    bundle = _mapping(raw["bundleTransfer"], {"providerOperationId", "payloadKind", "acceptedFramesBefore", "acceptedFramesAfter", "objectMetadata", "claimedSha256", "peerValidatedMetadata", "providerRawLog", "independentPeerLog", "peerReceiptTimestampUtc"}, "bundleTransfer")
    before, after = bundle["acceptedFramesBefore"], bundle["acceptedFramesAfter"]
    if bundle["payloadKind"] != "EDGE_BUNDLE_METADATA_ONLY" or not isinstance(before, int) or not isinstance(after, int) or before < 0 or after != before + 1:
        raise CapabilityRuntimeHilV2Error("EDGE_UPLINK은 metadata-only payload와 exact acceptedFrames increment만 허용한다")
    provider_ref, peer_ref = _hydrate_ref(bundle["providerRawLog"], artifacts, "provider raw log"), _hydrate_ref(bundle["independentPeerLog"], artifacts, "independent peer log")
    if artifacts[provider_ref["rawArtifactRef"]]["role"] not in {"PSDK_RAW_LOG", "GATEWAY_RAW_LOG"} or artifacts[peer_ref["rawArtifactRef"]]["role"] != "PEER_RAW_LOG" or provider_ref["rawArtifactRef"] == peer_ref["rawArtifactRef"]: raise CapabilityRuntimeHilV2Error("provider handoff와 peer receipt raw evidence는 독립돼야 한다")
    def metadata(item: object, name: str) -> dict[str, Any]:
        data = _mapping(item, {"objectRef", "contentType", "sha256", "sizeBytes"}, name)
        if not isinstance(data["sizeBytes"], int) or data["sizeBytes"] < 1: raise CapabilityRuntimeHilV2Error(f"{name}.sizeBytes가 유효하지 않다")
        object_ref, content_type = _string(data["objectRef"], f"{name}.objectRef"), _string(data["contentType"], f"{name}.contentType")
        if not object_ref.startswith("synthetic/") or content_type != "application/json": raise CapabilityRuntimeHilV2Error("EDGE_UPLINK object metadata는 synthetic JSON이며 live video/source media bytes가 아니어야 한다")
        return {"objectRef": object_ref, "contentType": content_type, "sha256": _digest(data["sha256"], f"{name}.sha256"), "sizeBytes": data["sizeBytes"]}
    object_metadata, peer_metadata = metadata(bundle["objectMetadata"], "objectMetadata"), metadata(bundle["peerValidatedMetadata"], "peerValidatedMetadata")
    claimed = _digest(bundle["claimedSha256"], "bundleTransfer.claimedSha256")
    if object_metadata != peer_metadata or object_metadata["sha256"] != claimed: raise CapabilityRuntimeHilV2Error("provider claimed bundle metadata/digest와 peer validated metadata가 일치하지 않는다")
    handoff = next(event for event in events if event["eventType"] == "TRANSMISSION_HANDOFF")
    receipt = next(event for event in events if event["eventType"] == "PEER_RECEIPT")
    if handoff["atMonotonicNs"] > receipt["atMonotonicNs"] or _utc(bundle["peerReceiptTimestampUtc"], "peerReceiptTimestampUtc") < receipt["timestampUtc"]: raise CapabilityRuntimeHilV2Error("SendData handoff timestamp는 independent peer receipt보다 늦을 수 없다")
    if handoff.get("operationId") != bundle["providerOperationId"] or receipt.get("operationId") != bundle["providerOperationId"] or handoff.get("payloadSha256") != claimed or receipt.get("payloadSha256") != claimed: raise CapabilityRuntimeHilV2Error("provider operation/peer receipt operationId 또는 payload digest가 일치하지 않는다")
    bundle_value = {"providerOperationId": _string(bundle["providerOperationId"], "providerOperationId"), "payloadKind": "EDGE_BUNDLE_METADATA_ONLY", "acceptedFramesBefore": before, "acceptedFramesAfter": after, "objectMetadata": object_metadata, "claimedSha256": claimed, "peerValidatedMetadata": peer_metadata, "providerRawLog": provider_ref, "independentPeerLog": peer_ref, "peerReceiptTimestampUtc": _utc(bundle["peerReceiptTimestampUtc"], "peerReceiptTimestampUtc")}
    return {"schemaVersion": SCHEMA_VERSION, "artifactType": "HIL_1R_ROUTE_1_RAW_CAPTURE", "nonActuating": True, "authority": authority, "session": session, "route": route, "software": software, "featureFlag": feature, "mission": mission_value, "rawArtifacts": list(artifacts.values()), "observationJournalSnapshot": observation_journal, "observations": observations, "preflightDecisions": preflights, "physicalEvents": events, "bundleTransfer": bundle_value, "scenarioCaptures": scenarios}


def _validator() -> Draft202012Validator:
    schema = _load_json(_SCHEMA_PATH)
    if not isinstance(schema, Mapping): raise CapabilityRuntimeHilV2Error("schema가 object가 아니다")
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _schema(value: object) -> None:
    errors = sorted(_validator().iter_errors(value), key=lambda item: list(item.path))
    if errors:
        location = "/".join(str(part) for part in errors[0].path) or "<root>"
        raise CapabilityRuntimeHilV2Error(f"schema validation 실패 at {location}: {errors[0].message}")


def capture(manifest: object, raw_root: Path) -> dict[str, Any]:
    _reject_pass(manifest)
    source = _mapping(manifest, {"authority", "session", "route", "software", "featureFlag", "mission", "rawArtifacts", "observationJournalSnapshot", "observations", "preflightDecisions", "physicalEvents", "bundleTransfer", "scenarioCaptures"}, "capture manifest")
    artifacts = _manifest_raw(source["rawArtifacts"], raw_root)
    lookup = {item["ref"]: item for item in artifacts}
    def hydrate(value: object, name: str) -> dict[str, str]: return _hydrate_ref(value, lookup, name)
    authority = dict(_mapping(source["authority"], set(_AUTHORITY) | {"authorityJournalSnapshot"}, "authority"))
    authority["authorityJournalSnapshot"] = hydrate(authority["authorityJournalSnapshot"], "authority journal snapshot")
    mission = dict(_mapping(source["mission"], {"missionId", "missionContractDigest", "missionReference", "policyResult"}, "mission"))
    mission["missionReference"] = hydrate(mission["missionReference"], "mission reference")
    events = []
    for item in _array(source["physicalEvents"], "physicalEvents"):
        event = dict(item); event.update(hydrate({key: event[key] for key in ("rawArtifactRef", "rawArtifactSha256") if key in event}, "physical event")); events.append(event)
    scenarios = []
    for item in _array(source["scenarioCaptures"], "scenarioCaptures"):
        scenario = dict(item); scenario["evidenceRefs"] = [hydrate(ref, "scenario evidence") for ref in _array(scenario["evidenceRefs"], "scenario evidenceRefs")]; scenarios.append(scenario)
    if source["bundleTransfer"] is None:
        bundle = None
    else:
        bundle = dict(_mapping(source["bundleTransfer"], {"providerOperationId", "payloadKind", "acceptedFramesBefore", "acceptedFramesAfter", "objectMetadata", "claimedSha256", "peerValidatedMetadata", "providerRawLog", "independentPeerLog", "peerReceiptTimestampUtc"}, "bundleTransfer")); bundle["providerRawLog"], bundle["independentPeerLog"] = hydrate(bundle["providerRawLog"], "provider raw log"), hydrate(bundle["independentPeerLog"], "independent peer log")
    result = {"schemaVersion": SCHEMA_VERSION, "artifactType": "HIL_1R_ROUTE_1_RAW_CAPTURE", "nonActuating": True, "authority": authority, "session": source["session"], "route": source["route"], "software": source["software"], "featureFlag": source["featureFlag"], "mission": mission, "rawArtifacts": artifacts, "observationJournalSnapshot": hydrate(source["observationJournalSnapshot"], "observation journal snapshot"), "observations": source["observations"], "preflightDecisions": source["preflightDecisions"], "physicalEvents": events, "bundleTransfer": bundle, "scenarioCaptures": scenarios}
    _schema(result); return _capture_body(result, raw_root)


def validate_raw_capture(value: object, raw_root: Path | None = None) -> None:
    _reject_pass(value); _schema(value); _capture_body(value, raw_root)


def _decision(raw: Mapping[str, Any]) -> tuple[str, list[str]]:
    scenarios = raw["scenarioCaptures"]
    if all(item["status"] == "OBSERVED" for item in scenarios): return "PASS", ["ALL_MANDATORY_ROUTE_1_RAW_EVIDENCE_REHASHED"]
    if any(item["status"] == "FAIL" for item in scenarios): return "FAIL", [f"{item['id']}_FAIL" for item in scenarios if item["status"] == "FAIL"]
    return "INCONCLUSIVE", [f"{item['id']}_{item['status']}" for item in scenarios if item["status"] != "OBSERVED"]


def finalize(raw_capture: object, raw_root: Path, *, verified_at_utc: str) -> dict[str, Any]:
    validate_raw_capture(raw_capture, raw_root)
    if not isinstance(raw_capture, Mapping): raise CapabilityRuntimeHilV2Error("raw capture가 object가 아니다")
    result, reasons = _decision(raw_capture)
    artifact = {"schemaVersion": SCHEMA_VERSION, "artifactType": "HIL_1R_ROUTE_1_EVIDENCE", "authority": raw_capture["authority"], "rawCapture": raw_capture, "verifierDecision": {"result": result, "reasonCodes": reasons, "verifiedAtUtc": _utc(verified_at_utc, "verifiedAtUtc")}}
    validate_artifact(artifact, raw_root); return artifact


def validate_artifact(value: object, raw_root: Path | None = None) -> None:
    _schema(value)
    artifact = _mapping(value, {"schemaVersion", "artifactType", "authority", "rawCapture", "verifierDecision"}, "evidence artifact")
    if artifact["schemaVersion"] != SCHEMA_VERSION or artifact["artifactType"] != "HIL_1R_ROUTE_1_EVIDENCE": raise CapabilityRuntimeHilV2Error("evidence type/version이 유효하지 않다")
    validate_raw_capture(artifact["rawCapture"], raw_root)
    if not isinstance(artifact["rawCapture"], Mapping) or artifact["authority"] != artifact["rawCapture"]["authority"]: raise CapabilityRuntimeHilV2Error("evidence/raw authority가 일치하지 않는다")
    decision = _mapping(artifact["verifierDecision"], {"result", "reasonCodes", "verifiedAtUtc"}, "verifierDecision")
    _utc(decision["verifiedAtUtc"], "verifiedAtUtc")
    expected_result, expected_reasons = _decision(artifact["rawCapture"])
    if decision["result"] != expected_result or decision["reasonCodes"] != expected_reasons: raise CapabilityRuntimeHilV2Error("verifier decision은 raw capture에서 결정적으로 재현되어야 한다")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture"); capture_parser.add_argument("--manifest", required=True, type=Path); capture_parser.add_argument("--raw-root", required=True, type=Path); capture_parser.add_argument("--output", required=True, type=Path)
    check_capture = commands.add_parser("validate-capture"); check_capture.add_argument("--input", required=True, type=Path); check_capture.add_argument("--raw-root", required=True, type=Path)
    final_parser = commands.add_parser("finalize"); final_parser.add_argument("--capture", required=True, type=Path); final_parser.add_argument("--raw-root", required=True, type=Path); final_parser.add_argument("--verified-at-utc", required=True); final_parser.add_argument("--output", required=True, type=Path)
    check_artifact = commands.add_parser("validate-artifact"); check_artifact.add_argument("--input", required=True, type=Path); check_artifact.add_argument("--raw-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            args.output.write_text(_canonical_json(capture(_load_json(args.manifest), args.raw_root)), encoding="utf-8")
        elif args.command == "validate-capture": validate_raw_capture(_load_json(args.input), args.raw_root)
        elif args.command == "finalize": args.output.write_text(_canonical_json(finalize(_load_json(args.capture), args.raw_root, verified_at_utc=args.verified_at_utc)), encoding="utf-8")
        else: validate_artifact(_load_json(args.input), args.raw_root)
    except CapabilityRuntimeHilV2Error as exc:
        print(f"capability-runtime-hil-v2: {exc}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__": raise SystemExit(main())
