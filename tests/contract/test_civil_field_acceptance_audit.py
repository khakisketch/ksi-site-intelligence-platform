"""Civil field acceptance auditor: private evidence only, fail closed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ksi_core.processing_profiles import ksi_odm_civil_v1
from PIL import Image

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "audit_civil_field_acceptance.py"
_SCHEMA = _ROOT / "contracts" / "schemas" / "civil-field-acceptance-manifest.v1.json"


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("audit_civil_field_acceptance", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_schema_is_a_valid_draft_2020_12_contract() -> None:
    Draft202012Validator.check_schema(json.loads(_SCHEMA.read_text(encoding="utf-8")))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _landxml() -> bytes:
    return b"""<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2">
  <Units><Metric linearUnit="meter"/></Units>
  <Surfaces><Surface name="Plan"><Definition surfType="TIN"><Pnts>
    <P id="a">0 0 10</P><P id="b">0 2 12</P><P id="c">2 0 14</P>
  </Pnts><Faces><F>a b c</F></Faces></Definition></Surface></Surfaces>
</LandXML>"""


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o600)


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    evidence_root = tmp_path / "evidence"
    evidence_root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    evidence_root.mkdir(mode=0o700)
    session = evidence_root / "civil-20260828-01"
    session.mkdir(mode=0o700)

    def evidence(relative: str, payload: bytes) -> dict[str, str]:
        target = session / relative
        _write(target, payload)
        return {"path": relative, "sha256": _sha256(target)}

    def jpeg(relative: str, index: int) -> dict[str, str]:
        target = session / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        Image.new("RGB", (16, 16), color=(index, index, index)).save(target, format="JPEG")
        target.chmod(0o600)
        return {"path": relative, "sha256": _sha256(target)}

    baseline = [
        {
            **jpeg(f"baseline/image-{index}.jpg", index),
            "originalCameraFileAttested": True,
        }
        for index in range(5)
    ]
    current = [
        {
            **jpeg(f"current/image-{index}.jpg", index + 10),
            "originalCameraFileAttested": True,
        }
        for index in range(5)
    ]
    design = evidence("design/plan.landxml", _landxml())
    reference = evidence("reference/checkpoints.csv", b"independent checkpoints")
    commercial_rights = evidence("rights/commercial.txt", b"commercial processing permission")
    derivative_rights = evidence("rights/derivatives.txt", b"derivative outputs permission")
    baseline_gcp = evidence("gcp/baseline.csv", b"baseline georeferencing evidence")
    current_gcp = evidence("gcp/current.csv", b"current georeferencing evidence")
    vertical = {"datum": "orthometric_kngeoid2024", "basis": "survey brief"}
    manifest: dict[str, Any] = {
        "schemaVersion": "1.0",
        "sessionId": session.name,
        "operatorAttested": True,
        "site": {"anonymized": True, "sameSiteAttested": True},
        "rights": {
            "commercialProcessing": {
                "attested": True,
                "basis": "owner authorization",
                "evidence": commercial_rights,
            },
            "derivativeOutputs": {
                "attested": True,
                "basis": "owner authorization",
                "evidence": derivative_rights,
            },
        },
        "processingProfileId": "ksi-odm-civil-v1",
        "processingProfileDigest": ksi_odm_civil_v1().profile_digest,
        "crs": "EPSG:5186",
        "verticalReference": dict(vertical),
        "epochs": [
            {
                "epochId": "baseline",
                "captureStartedAtUtc": "2026-08-01T01:00:00Z",
                "captureEndedAtUtc": "2026-08-01T01:05:00Z",
                "images": baseline,
                "georeferencing": {
                    "method": "RTK GCP",
                    "crs": "EPSG:5186",
                    "verticalReference": dict(vertical),
                    "evidence": baseline_gcp,
                },
            },
            {
                "epochId": "current",
                "captureStartedAtUtc": "2026-08-15T01:00:00Z",
                "captureEndedAtUtc": "2026-08-15T01:05:00Z",
                "images": current,
                "georeferencing": {
                    "method": "RTK GCP",
                    "crs": "EPSG:5186",
                    "verticalReference": dict(vertical),
                    "evidence": current_gcp,
                },
            },
        ],
        "designSurface": {
            **design,
            "format": "landxml",
            "surfaceSelector": "Plan",
            "revision": "R1",
            "crs": "EPSG:5186",
            "verticalReference": dict(vertical),
        },
        "groundControlFiles": [
            {"epochId": "baseline", **baseline_gcp},
            {"epochId": "current", **current_gcp},
        ],
        "independentReference": {
            **reference,
            "kind": "independent_checkpoint",
            "method": "independent total-station check",
            "crs": "EPSG:5186",
            "verticalReference": dict(vertical),
            "checkpointCount": 5,
            "accuracy": {"horizontalM": 0.02, "verticalM": 0.03, "basis": "survey report"},
        },
    }
    manifest_path = session / "civil-field-acceptance.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    return evidence_root, manifest_path, manifest


def _audit(tool: Any, root: Path, manifest_path: Path) -> dict[str, Any]:
    original = tool._canonical_evidence_root
    tool._canonical_evidence_root = lambda: root
    try:
        return tool.audit_manifest(manifest_path=manifest_path)
    finally:
        tool._canonical_evidence_root = original


def _rewrite(manifest_path: Path, manifest: dict[str, Any]) -> None:
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)


def test_owner_only_valid_field_acceptance_manifest_passes(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, _manifest = _fixture(tmp_path)

    result = _audit(tool, root, manifest_path)

    assert result["status"] == "INPUT_READY"
    assert result["fieldAcceptance"] == "NOT_EVALUATED"
    assert result["blockers"] == []
    assert result["sessionId"] == "civil-20260828-01"
    assert "safeRelativePaths" not in result
    encoded = json.dumps(result)
    assert str(root) not in encoded
    assert "0 0 10" not in encoded
    assert "image-0.jpg" not in encoded


def test_missing_manifest_is_blocked_without_path_disclosure(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, _manifest = _fixture(tmp_path)
    manifest_path.unlink()

    result = _audit(tool, root, manifest_path)

    assert result == {
        "schemaVersion": "1.0",
        "status": "BLOCKED",
        "fieldAcceptance": "NOT_EVALUATED",
        "blockers": ["MANIFEST_UNSAFE"],
    }


def test_unsafe_permissions_and_symlink_are_blocked(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    unsafe = root / manifest["sessionId"] / manifest["epochs"][0]["images"][0]["path"]
    unsafe.chmod(0o644)
    assert "EVIDENCE_FILE_UNSAFE" in _audit(tool, root, manifest_path)["blockers"]

    unsafe.chmod(0o600)
    unsafe.unlink()
    unsafe.symlink_to(root / manifest["sessionId"] / manifest["epochs"][0]["images"][1]["path"])
    assert "EVIDENCE_FILE_UNSAFE" in _audit(tool, root, manifest_path)["blockers"]


def test_digest_mismatch_and_path_traversal_are_typed_blockers(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    manifest["epochs"][0]["images"][0]["sha256"] = "0" * 64
    _rewrite(manifest_path, manifest)
    assert "EVIDENCE_DIGEST_MISMATCH" in _audit(tool, root, manifest_path)["blockers"]

    root, manifest_path, manifest = _fixture(tmp_path / "traversal")
    manifest["epochs"][0]["images"][0]["path"] = "../outside.jpg"
    _rewrite(manifest_path, manifest)
    assert "EVIDENCE_PATH_UNSAFE" in _audit(tool, root, manifest_path)["blockers"]


def test_unsupported_crs_and_invalid_landxml_are_blocked(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    manifest["crs"] = "EPSG:32610"
    _rewrite(manifest_path, manifest)
    assert "UNSUPPORTED_KOREAN_CRS" in _audit(tool, root, manifest_path)["blockers"]

    root, manifest_path, manifest = _fixture(tmp_path / "invalid-landxml")
    design_path = root / manifest["sessionId"] / manifest["designSurface"]["path"]
    _write(design_path, b"<LandXML/>")
    manifest["designSurface"]["sha256"] = _sha256(design_path)
    _rewrite(manifest_path, manifest)
    assert "LANDXML_INVALID" in _audit(tool, root, manifest_path)["blockers"]


def test_landxml_size_limit_is_checked_before_parsing(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, _manifest = _fixture(tmp_path)
    tool.MAX_LANDXML_BYTES = 1

    assert "LANDXML_INVALID" in _audit(tool, root, manifest_path)["blockers"]


def test_canonical_root_profile_digest_and_rights_evidence_are_fail_closed(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)

    noncanonical = tool.audit_manifest(manifest_path=manifest_path, evidence_root=root)
    assert "CANONICAL_ROOT_REQUIRED" in noncanonical["blockers"]

    manifest["processingProfileDigest"] = "sha256:" + "0" * 64
    commercial_rights = manifest["rights"]["commercialProcessing"]
    manifest["rights"]["derivativeOutputs"]["evidence"] = commercial_rights["evidence"]
    _rewrite(manifest_path, manifest)
    blockers = _audit(tool, root, manifest_path)["blockers"]
    assert "PROCESSING_PROFILE_DIGEST_MISMATCH" in blockers
    assert "RIGHTS_EVIDENCE_NOT_SEPARATE" not in blockers


def test_epoch_georeferencing_must_bind_gcp_and_images_must_verify(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    session = root / manifest["sessionId"]
    image = session / manifest["epochs"][0]["images"][0]["path"]
    _write(image, b"\xff\xd8\xffnot-an-image\xff\xd9")
    manifest["epochs"][0]["images"][0]["sha256"] = _sha256(image)
    manifest["epochs"][1]["georeferencing"]["evidence"] = {
        "path": manifest["designSurface"]["path"],
        "sha256": manifest["designSurface"]["sha256"],
    }
    _rewrite(manifest_path, manifest)

    blockers = _audit(tool, root, manifest_path)["blockers"]
    assert "ORIGINAL_JPEG_REQUIRED" in blockers
    assert "GEOREFERENCING_EVIDENCE_NOT_BOUND" in blockers


def test_duplicate_epochs_images_and_rights_are_blocked(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    manifest["epochs"][1]["epochId"] = "baseline"
    manifest["epochs"][1]["images"][0] = manifest["epochs"][0]["images"][0]
    manifest["rights"]["commercialProcessing"]["attested"] = False
    manifest["rights"]["derivativeOutputs"]["attested"] = False
    _rewrite(manifest_path, manifest)

    blockers = _audit(tool, root, manifest_path)["blockers"]
    assert "EPOCH_SET_INVALID" in blockers
    assert "EPOCH_IMAGES_NOT_UNIQUE" in blockers
    assert "COMMERCIAL_PROCESSING_RIGHTS_NOT_ATTESTED" in blockers
    assert "DERIVATIVE_OUTPUT_RIGHTS_NOT_ATTESTED" in blockers


def test_reference_must_be_independent_of_inputs_and_gcp(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    image = manifest["epochs"][0]["images"][0]
    manifest["independentReference"]["path"] = image["path"]
    manifest["independentReference"]["sha256"] = image["sha256"]
    _rewrite(manifest_path, manifest)

    assert "REFERENCE_NOT_INDEPENDENT" in _audit(tool, root, manifest_path)["blockers"]


def test_each_epoch_requires_its_own_distinct_bound_ground_control_file(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    manifest["groundControlFiles"][1]["epochId"] = "baseline"
    _rewrite(manifest_path, manifest)

    blockers = _audit(tool, root, manifest_path)["blockers"]
    assert "GROUND_CONTROL_EPOCH_BINDING_INVALID" in blockers
    assert "GEOREFERENCING_EVIDENCE_NOT_BOUND" in blockers

    root, manifest_path, manifest = _fixture(tmp_path / "duplicate-control")
    manifest["groundControlFiles"][1]["path"] = manifest["groundControlFiles"][0]["path"]
    manifest["groundControlFiles"][1]["sha256"] = manifest["groundControlFiles"][0]["sha256"]
    manifest["epochs"][1]["georeferencing"]["evidence"] = {
        "path": manifest["groundControlFiles"][0]["path"],
        "sha256": manifest["groundControlFiles"][0]["sha256"],
    }
    _rewrite(manifest_path, manifest)

    assert "GROUND_CONTROL_IDENTITY_NOT_DISTINCT" in _audit(tool, root, manifest_path)["blockers"]


def test_overlapping_epochs_and_design_reference_mismatches_are_blocked(tmp_path: Path) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    manifest["epochs"][1]["captureStartedAtUtc"] = "2026-08-01T01:05:00Z"
    manifest["designSurface"]["crs"] = "EPSG:5187"
    manifest["designSurface"]["verticalReference"]["basis"] = "different vertical source"
    _rewrite(manifest_path, manifest)

    blockers = _audit(tool, root, manifest_path)["blockers"]
    assert "EPOCHS_NOT_DISTINCT" in blockers
    assert "CRS_MISMATCH" in blockers
    assert "VERTICAL_REFERENCE_MISMATCH" in blockers


def test_operator_attestation_and_cli_output_are_deterministic_and_non_mutating(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    manifest["operatorAttested"] = False
    _rewrite(manifest_path, manifest)
    before = manifest_path.stat().st_mtime_ns

    original = tool._canonical_evidence_root
    tool._canonical_evidence_root = lambda: root
    first_exit = tool.main(["--manifest", str(manifest_path)])
    first = capsys.readouterr().out
    second_exit = tool.main(["--manifest", str(manifest_path)])
    second = capsys.readouterr().out
    tool._canonical_evidence_root = original

    assert first_exit == second_exit == 2
    assert first == second
    assert "OPERATOR_ATTESTATION_REQUIRED" in first
    assert str(root) not in first
    assert manifest_path.stat().st_mtime_ns == before


@pytest.mark.parametrize("value", [None, "", "not-utc", "2026-08-01T01:00:00+09:00"])
def test_capture_interval_requires_explicit_utc(tmp_path: Path, value: object) -> None:
    tool = _tool()
    root, manifest_path, manifest = _fixture(tmp_path)
    manifest["epochs"][0]["captureStartedAtUtc"] = value
    _rewrite(manifest_path, manifest)

    blockers = _audit(tool, root, manifest_path)["blockers"]
    assert {"MANIFEST_SCHEMA_INVALID", "EPOCH_CAPTURE_INTERVAL_INVALID"} & set(blockers)
