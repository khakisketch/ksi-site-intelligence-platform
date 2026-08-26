from __future__ import annotations

import importlib.util
import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from PIL import Image

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "hil" / "audit_phase3_readiness.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_phase3_readiness", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jpeg(path: Path, *, model: str = "M4D", with_xmp: bool = True) -> None:
    image = Image.new("RGB", (5280, 3956), color="white")
    exif = Image.Exif()
    exif[271] = "DJI"
    exif[272] = model
    exif[37386] = (12290, 1000)
    exif[41989] = 24
    image.save(path, format="JPEG", exif=exif)
    if not with_xmp:
        return
    xmp = (
        b"http://ns.adobe.com/xap/1.0/\x00"
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:drone-dji="http://www.dji.com/'
        b'drone-dji/1.0/" xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
        b'<rdf:Description drone-dji:ImageSource="WideCamera" '
        b'xmp:CreateDate="2026-08-20T03:34:56Z"/>'
        b"</x:xmpmeta>"
    )
    segment = b"\xff\xe1" + (len(xmp) + 2).to_bytes(2, "big") + xmp
    original = path.read_bytes()
    path.write_bytes(original[:2] + segment + original[2:])


def _repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True
    )
    (path / "seed").write_text("seed\n")
    subprocess.run(["git", "add", "seed"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=path, check=True)


def _report(tool: ModuleType, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    args: dict[str, Any] = {
        "repository_root": repo,
        "kit_dir": _ROOT / "docs" / "hil" / "field0a-kit",
        "pilot_import_evidence": [],
        "m4d_jpeg": None,
        "pilot_export_kmz": None,
        "generated_at": datetime(2026, 8, 26, 1, 2, 3, tzinfo=UTC),
    }
    args.update(overrides)
    return tool.build_report(**args)


def test_pinned_field0a_kit_has_expected_safe_structure() -> None:
    tool = _tool()
    result = tool.audit_kit(_ROOT / "docs" / "hil" / "field0a-kit")

    assert result["status"] == "PASS"
    assert [item["waypoint_count"] for item in result["files"]] == [80, 80, 80]
    assert [item["take_photo_action_count"] for item in result["files"]] == [80, 80, 80]
    assert [item["drone_enum_value"] for item in result["files"]] == ["100", "99", "100"]
    assert [item["payload_enum_value"] for item in result["files"]] == [
        "98",
        "65534",
        "98",
    ]


def test_kmz_with_extra_or_traversal_member_is_rejected(tmp_path: Path) -> None:
    tool = _tool()
    source = _ROOT / "docs" / "hil" / "field0a-kit" / tool.EXPECTED_KIT_FILES[0]
    target = tmp_path / "unsafe.kmz"
    target.write_bytes(source.read_bytes())
    with zipfile.ZipFile(target, "a") as archive:
        archive.writestr("../escape", "bad")

    with pytest.raises(tool.ReadinessAuditError, match="unexpected KMZ member"):
        tool.inspect_kmz(target)


def test_m4d_metadata_passes_without_emitting_gps_or_serial(tmp_path: Path) -> None:
    tool = _tool()
    jpeg = tmp_path / "m4d.jpg"
    _jpeg(jpeg)

    result = tool.inspect_m4d_jpeg(jpeg)
    encoded = json.dumps(result).lower()

    assert result["status"] == "PASS"
    assert result["focal_length_mm"] == 12.29
    assert result["capture_time_status"] == "VERIFIED"
    assert "gps" not in encoded
    assert "serial" not in encoded


def test_report_keeps_field0a_and_phase3_blocked_without_physical_evidence(
    tmp_path: Path,
) -> None:
    tool = _tool()
    screenshot = tmp_path / "pilot.png"
    Image.new("RGB", (32, 24), color="white").save(screenshot)
    jpeg = tmp_path / "m4d.jpg"
    _jpeg(jpeg)

    report = _report(
        tool,
        tmp_path,
        pilot_import_evidence=[screenshot],
        m4d_jpeg=jpeg,
    )

    assert report["field0a"]["status"] == "BLOCKED"
    assert report["field0a"]["blockers"] == ["PILOT_EXPORT_KMZ_REQUIRED"]
    assert report["phase3"]["status"] == "BLOCKED"
    assert set(report["phase3"]["capabilities"].values()) == {"NOT_VERIFIED"}
    assert report["safety_scope"] == {
        "device_contact": False,
        "device_write": False,
        "flight_or_motor_action": False,
        "customer_data_export": False,
    }


def test_unattested_export_bytes_do_not_close_field0a(tmp_path: Path) -> None:
    tool = _tool()
    export = _ROOT / "docs" / "hil" / "field0a-kit" / tool.EXPECTED_KIT_FILES[0]

    report = _report(tool, tmp_path, pilot_export_kmz=export)

    assert report["field0a"]["status"] == "BLOCKED"
    assert "PILOT_EXPORT_SOURCE_ATTESTATION_REQUIRED" in report["field0a"]["blockers"]


def test_private_output_is_exclusive_and_owner_only(tmp_path: Path) -> None:
    tool = _tool()
    output = tmp_path / "private" / "readiness.json"
    tool.write_private(output, {"schema_version": "test"})

    assert output.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        tool.write_private(output, {"schema_version": "test"})
