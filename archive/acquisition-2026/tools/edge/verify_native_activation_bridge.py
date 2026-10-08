"""Replay the real Python activation handoff through the native C++ parser.

The Python verifier owns Mission Dispatch signature validation and writes a
private ``active-dispatch.native.v1`` handoff.  The PSDK process must consume
the exact bytes it writes, rather than a separately hand-maintained C++ test
fixture.  This host/target bridge oracle creates a typed snapshot with the
production serializer and asks the C++ test executable to inspect it.

It verifies the format boundary only; it is not a replacement for DPK or
Manifold HIL evidence.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ksi_mission_contracts.dispatch import DispatchValidity
from ksi_mission_contracts.edge_activation import (
    ActiveDispatchSnapshotV1,
    _write_native_runtime_profile_atomically,
    _write_native_snapshot_atomically,
)
from ksi_mission_contracts.risk_policy import RiskPolicyPackV1, risk_policy_pack_digest
from ksi_mission_contracts.runtime_profile import EdgeRuntimeProfileV1, edge_runtime_profile_digest


def _snapshot() -> tuple[ActiveDispatchSnapshotV1, int]:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    policy = RiskPolicyPackV1.model_validate(
        {
            "schemaVersion": "1.0",
            "riskPolicyPackId": "risk-pack-bridge-v1",
            "validity": {
                "notBefore": (now - timedelta(minutes=1)).isoformat(),
                "notAfter": (now + timedelta(minutes=5)).isoformat(),
            },
            "calibrationProfileId": "calibration-bridge-v1",
            "equipmentPolicies": [
                {
                    "equipmentClass": "Vehicle_Truck",
                    "riskFieldPolicyId": "risk-truck-bridge-v1",
                    "footprint": {"lengthM": 4.0, "widthM": 2.0, "heightM": 2.0},
                    "prediction": {"horizonSeconds": 2.0, "samplePeriodSeconds": 0.2},
                    "covarianceSigmaMultiplier": 2.0,
                    "occlusionExpansionM": 1.0,
                    "severity": 0.7,
                }
            ],
        }
    )
    raw_policy = policy.model_dump(by_alias=True, mode="json")
    profile = EdgeRuntimeProfileV1.model_validate(
        {
            "schemaVersion": "1.0",
            "edgeRuntimeProfileId": "runtime-profile-bridge-v1",
            "validity": {
                "notBefore": (now - timedelta(minutes=1)).isoformat(),
                "notAfter": (now + timedelta(minutes=5)).isoformat(),
            },
            "siteId": "site-bridge-001",
            "model": {
                "modelPackId": "model-pack-bridge-v1",
                "modelId": "dfine-bridge-v1",
                "onnxArtifactId": "dfine-bridge.onnx",
                "registeredOnnxDigest": "sha256:" + "b" * 64,
                "engineArtifactId": "dfine-bridge.engine",
                "maxOnnxBytes": 104857600,
                "maxEngineBytes": 209715200,
                "workspaceBytes": 104857600,
                "tensorContract": {
                    "inputWidth": 640,
                    "inputHeight": 640,
                    "queryCount": 300,
                    "classCount": 80,
                },
                "classBindings": [
                    {
                        "sourceClassId": 0,
                        "sourceClassName": "truck",
                        "equipmentClass": "Vehicle_Truck",
                        "measuredDimensions": {"lengthM": 4.0, "widthM": 2.0, "heightM": 2.0},
                    }
                ],
                "scoreThreshold": 0.5,
                "topK": 10,
                "ontologyVersion": "ksi-ontology-v1",
                "sourceTaxonomy": "COCO-2017",
                "tensorRtDifferential": {
                    "verificationProfileId": "ksi-dfine-tensorrt-onnx-semantic-v1",
                    "evidenceDigest": "sha256:" + "c" * 64,
                    "registeredOnnxDigest": "sha256:" + "b" * 64,
                    "preprocessingContractId": "rtdetr-rgb-bilinear-1over255-v1",
                    "preprocessingConfigDigest": "sha256:" + "d" * 64,
                    "corpusId": "dfine-onnx-corpus-v1",
                    "corpusDigest": "sha256:" + "e" * 64,
                    "sampleCount": 10,
                    "status": "PASS",
                    "confidenceAtol": 0.001,
                    "bboxAtolPx": 0.5,
                },
            },
            "calibration": {
                "calibrationProfileId": "calibration-bridge-v1",
                "siteFrame": {
                    "crs": "EPSG:5186",
                    "verticalDatum": "KNGeoid2018",
                    "unit": "meter",
                    "transformVersion": "1.0.0",
                },
                "wgs84Origin": {"latitudeRad": 0.5, "longitudeRad": 1.0, "altitudeM": 20.0},
                "enuToSite": {
                    "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    "translationM": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                "groundPlaneUpM": 0.0,
                "intrinsics": {
                    "referenceWidth": 1920,
                    "referenceHeight": 1080,
                    "focalXPx": 1000.0,
                    "focalYPx": 1000.0,
                    "principalXPx": 960.0,
                    "principalYPx": 540.0,
                },
                "cameraToGimbal": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
                "cameraOffsetInGimbalM": {"x": 0.0, "y": 0.0, "z": 0.0},
                "positionSigmaM": 1.0,
                "angularSigmaRad": 0.01,
                "pixelSigmaPx": 1.0,
                "maxPoseAgeMs": 500,
            },
            "timing": {"requireSensorAlignment": True, "maxAlignmentMs": 50},
        }
    )
    raw_profile = profile.model_dump(by_alias=True, mode="json")
    snapshot = ActiveDispatchSnapshotV1(
        dispatch_id="dispatch-bridge-001",
        edge_device_id="edge-bridge-001",
        mission_id="mission-bridge-001",
        mission_contract_digest="sha256:" + "a" * 64,
        risk_policy_pack=raw_policy,
        risk_policy_pack_digest=risk_policy_pack_digest(raw_policy),
        edge_runtime_profile=raw_profile,
        edge_runtime_profile_digest=edge_runtime_profile_digest(raw_profile),
        validity=DispatchValidity(
            not_before=now - timedelta(minutes=1), not_after=now + timedelta(minutes=5)
        ),
        activated_at=now,
        runtime_version="manifold3-edge-shadow-0.2.0",
    )
    return snapshot, int(now.timestamp() * 1000)


def verify(binary: Path) -> None:
    if not binary.is_file() or not binary.stat().st_mode & 0o111:
        raise ValueError(f"executable not found: {binary}")
    snapshot, now_utc_ms = _snapshot()
    with tempfile.TemporaryDirectory(prefix="ksi-native-activation-bridge-") as temporary:
        state_dir = Path(temporary)
        state_dir.chmod(0o700)
        _write_native_runtime_profile_atomically(
            state_dir / "active-edge-runtime-profile.native.v1", snapshot
        )
        _write_native_snapshot_atomically(state_dir / "active-dispatch.native.v1", snapshot)
        result = subprocess.run(
            [
                str(binary),
                "--inspect-native-activation",
                str(state_dir),
                snapshot.edge_device_id,
                snapshot.runtime_version,
                str(now_utc_ms),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            raise ValueError(result.stderr.rstrip() or "native activation inspector failed")
        if result.stdout.strip() != "LOADED":
            raise ValueError(f"native parser rejected Python handoff: {result.stdout.strip()!r}")
        profile_result = subprocess.run(
            [
                str(binary),
                "--inspect-native-runtime-profile",
                str(state_dir),
                snapshot.edge_device_id,
                snapshot.dispatch_id,
                snapshot.mission_id,
                snapshot.mission_contract_digest,
                snapshot.risk_policy_pack_digest,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if profile_result.returncode != 0:
            raise ValueError(
                profile_result.stderr.rstrip() or "native runtime profile inspector failed"
            )
        if profile_result.stdout.strip() != "LOADED":
            raise ValueError(
                "native runtime profile parser rejected Python handoff: "
                f"{profile_result.stdout.strip()!r}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edge_runtime_tests", type=Path)
    args = parser.parse_args(argv)
    try:
        verify(args.edge_runtime_tests)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"✗ native activation bridge failure: {exc}", file=sys.stderr)
        return 1
    print("✓ Python native activation/runtime-profile handoffs accepted by C++ parsers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
