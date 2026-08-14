"""C++ Edge WorldEntity/RiskField 산출물을 Python 계약 모델로 재검증한다.

Usage:
    uv run python tools/edge/verify_native_artifact_oracle.py /path/to/edge_runtime_tests

The native test executable emits exactly one deterministic fixture through
``--emit-native-artifacts``.  This tool is deliberately a host/replay oracle:
it does not pretend that a host fixture proves Manifold camera or TensorRT HIL.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ksi_equipment_intelligence.risk_field import RiskField, risk_field_wire_dict
from ksi_event_contracts.assembly import world_entity_fingerprint
from ksi_event_contracts.event_bundle import EventBundle
from ksi_event_contracts.offline_sync import payload_digest
from ksi_event_contracts.world_entity import WorldEntity


def verify_payload(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Validate one native oracle payload and return its stable fingerprints.

    The check intentionally commits to cross-artifact lineage as well as each
    individual schema: a RiskField for another entity or calibration must not
    be attached to this WorldEntity simply because both JSON values validate.
    """
    if set(payload) != {"worldEntity", "riskField"}:
        raise ValueError("oracle payload must contain exactly worldEntity and riskField")
    raw_entity = payload["worldEntity"]
    raw_risk = payload["riskField"]
    if not isinstance(raw_entity, Mapping) or not isinstance(raw_risk, Mapping):
        raise ValueError("worldEntity and riskField must both be JSON objects")

    entity = WorldEntity.model_validate(raw_entity)
    risk = RiskField.model_validate(raw_risk)
    if risk.schema_version != "1.1":
        raise ValueError("native Edge must emit only RiskField v1.1")
    if entity.entity_id not in risk.source_entity_ids:
        raise ValueError("RiskField sourceEntityIds does not bind the emitted WorldEntity")
    assert risk.lineage is not None  # RiskField v1.1 validator enforces this.
    if risk.lineage.calibration_profile_id != entity.lineage.calibration_profile_id:
        raise ValueError("RiskField and WorldEntity calibrationProfileId differ")
    if risk.lineage.source_timestamp != entity.timestamp:
        raise ValueError("RiskField sourceTimestamp does not match WorldEntity timestamp")

    # Re-dump only to catch accidentally omitted aliases/required payload keys.
    risk_field_wire_dict(risk)
    return world_entity_fingerprint(entity), risk.risk_field_id


def verify_native_event_payload(payload: Mapping[str, Any]) -> str:
    """Validate one native EventBundle candidate before Core sync.

    This is deliberately separate from the WorldEntity/RiskField artifact
    oracle because the EventBundle can travel first in the durable journal.
    The linkage it carries must nevertheless already name the exact RiskField
    artifact that Core will later validate for a CRITICAL transition.
    """
    bundle = EventBundle.model_validate(payload)
    if bundle.status.value not in {"OBSERVATION", "CANDIDATE", "EVIDENCE_COLLECTION"}:
        raise ValueError("native Edge emitted a non-assertable terminal event status")
    risk_artifact = bundle.evidence.risk_field_artifact
    reasoning_risk_id = bundle.reasoning.get("riskFieldId")
    spatial_risk_id = bundle.spatial_context.get("riskFieldId")
    if not isinstance(risk_artifact, str) or not risk_artifact:
        raise ValueError("native EventBundle has no riskFieldArtifact")
    if risk_artifact != reasoning_risk_id or risk_artifact != spatial_risk_id:
        raise ValueError("RiskField artifact reference does not match EventBundle lineage")
    return payload_digest(dict(payload))


def verify_native_vertical_slice(
    artifacts_payload: Mapping[str, Any], event_payload: Mapping[str, Any]
) -> tuple[str, str, str]:
    """Cross-check the two native fixtures as the Core will relate them.

    The EventBundle is uploaded before direct evidence PUT, so each fixture can
    validate alone while still being mutually incompatible.  This cross-check
    catches that exact failure class before an Edge implementation can claim a
    candidate whose later CRITICAL evidence gate is impossible to satisfy.
    """
    entity_fingerprint, risk_field_id = verify_payload(artifacts_payload)
    event_digest = verify_native_event_payload(event_payload)
    event = EventBundle.model_validate(event_payload)
    if event.evidence.risk_field_artifact != risk_field_id:
        raise ValueError("EventBundle riskFieldArtifact does not name native RiskField.riskFieldId")
    return entity_fingerprint, risk_field_id, event_digest


def _run_native_fixture(binary: Path, argument: str) -> Mapping[str, Any]:
    result = subprocess.run(
        [str(binary), argument], capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.rstrip() or "native artifact oracle failed")
    raw = json.loads(result.stdout)
    if not isinstance(raw, Mapping):
        raise ValueError("native artifact oracle did not emit an object")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edge_runtime_tests", type=Path)
    parser.add_argument(
        "--kind",
        choices=("artifacts", "event", "vertical-slice"),
        default="artifacts",
        help="native fixture emitted by the test binary (default: artifacts)",
    )
    args = parser.parse_args(argv)
    binary = args.edge_runtime_tests
    if not binary.is_file() or not binary.stat().st_mode & 0o111:
        print(f"✗ executable not found: {binary}", file=sys.stderr)
        return 2
    try:
        if args.kind == "artifacts":
            entity_fingerprint, risk_field_id = verify_payload(
                _run_native_fixture(binary, "--emit-native-artifacts")
            )
        elif args.kind == "event":
            event_digest = verify_native_event_payload(
                _run_native_fixture(binary, "--emit-native-event")
            )
        else:
            entity_fingerprint, risk_field_id, event_digest = verify_native_vertical_slice(
                _run_native_fixture(binary, "--emit-native-artifacts"),
                _run_native_fixture(binary, "--emit-native-event"),
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"✗ native artifact oracle contract failure: {exc}", file=sys.stderr)
        return 1
    if args.kind == "artifacts":
        print(
            f"✓ native artifacts validated: entityFingerprint={entity_fingerprint} "
            f"riskFieldId={risk_field_id}"
        )
    elif args.kind == "event":
        print(f"✓ native EventBundle validated: payloadDigest={event_digest}")
    else:
        print(
            f"✓ native vertical slice validated: entityFingerprint={entity_fingerprint} "
            f"riskFieldId={risk_field_id} payloadDigest={event_digest}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
