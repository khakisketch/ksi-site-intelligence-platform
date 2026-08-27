from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import zipfile
from collections.abc import Callable
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _field0a_evidence(tool: ModuleType, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    raw = tmp_path / "raw-evidence"
    raw.mkdir(mode=0o700)
    screenshot = raw / "pilot-import-a.png"
    Image.new("RGB", (32, 24), color="white").save(screenshot)
    export = raw / "pilot-export.kmz"
    export.write_bytes(
        (_ROOT / "docs" / "hil" / "field0a-kit" / tool.EXPECTED_KIT_FILES[0]).read_bytes()
    )
    m4d = raw / "m4d-original.jpg"
    _jpeg(m4d)
    return raw, screenshot, export, m4d


def _attestation_payload(
    *,
    commit: str,
    raw: Path,
    screenshot: Path,
    export: Path,
    m4d: Path,
) -> dict[str, Any]:
    def artifact(path: Path) -> dict[str, str]:
        return {
            "session_id": "field0a-20260827-01",
            "operator_id": "operator-001",
            "observed_at_utc": "2026-08-27T01:30:00Z",
            "raw_evidence_path": path.relative_to(raw).as_posix(),
            "sha256": _sha256(path),
        }

    pilot_import = artifact(screenshot)
    pilot_import.update({"variant": "A", "result": "IMPORTED_AND_MAPPED"})
    return {
        "schema_version": "1.0",
        "session_id": "field0a-20260827-01",
        "operator_id": "operator-001",
        "operator_attested": True,
        "build_commit": commit,
        "started_at_utc": "2026-08-27T01:00:00Z",
        "ended_at_utc": "2026-08-27T02:00:00Z",
        "safety_scope": {
            "device_contact": True,
            "device_write": True,
            "propellers_removed": True,
            "flight_or_motor_action": False,
        },
        "raw_evidence_root": str(raw),
        "pilot_imports": [pilot_import],
        "pilot_export": artifact(export),
        "m4d_original": artifact(m4d),
    }


def _write_attestation(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def _mock_durable_share(tool: ModuleType, monkeypatch: pytest.MonkeyPatch, raw: Path) -> None:
    monkeypatch.setattr(tool, "_canonical_field0a_evidence_root", lambda: raw.parent)
    monkeypatch.setattr(tool, "_mount_filesystem_type", lambda _path: "nfs4")


def _attested_report(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    commit, _dirty = tool._commit(repo)
    raw, screenshot, export, m4d = _field0a_evidence(tool, tmp_path)
    _mock_durable_share(tool, monkeypatch, raw)
    attestation = tmp_path / "field0a-session-attestation.json"
    payload = _attestation_payload(
        commit=commit, raw=raw, screenshot=screenshot, export=export, m4d=m4d
    )
    if mutate is not None:
        mutate(payload)
    _write_attestation(attestation, payload)
    return tool.build_report(
        repository_root=repo,
        kit_dir=_ROOT / "docs" / "hil" / "field0a-kit",
        pilot_import_evidence=[screenshot],
        m4d_jpeg=m4d,
        pilot_export_kmz=export,
        field0a_session_attestation=attestation,
        generated_at=datetime(2026, 8, 27, 2, 3, 4, tzinfo=UTC),
    )


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
    assert report["field0a"]["blockers"] == [
        "PILOT_EXPORT_KMZ_REQUIRED",
        "FIELD0A_ATTESTATION_REQUIRED",
    ]
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
    assert "FIELD0A_ATTESTATION_REQUIRED" in report["field0a"]["blockers"]


def test_safe_pilot_export_extension_uses_core_candidate_validator(tmp_path: Path) -> None:
    tool = _tool()
    source = _ROOT / "docs" / "hil" / "field0a-kit" / tool.EXPECTED_KIT_FILES[0]
    export = tmp_path / "pilot-export.kmz"
    export.write_bytes(source.read_bytes())
    with zipfile.ZipFile(export, "a") as archive:
        archive.writestr("wpmz/res/pilot-export-metadata.json", "{}")

    report = _report(tool, tmp_path, pilot_export_kmz=export)

    assert report["field0a"]["status"] == "BLOCKED"
    assert report["field0a"]["pilot_export"]["status"] == "STRUCTURALLY_VALIDATED_UNATTESTED"
    assert report["field0a"]["pilot_export"]["placemark_count"] == 80
    assert "PILOT_EXPORT_SOURCE_ATTESTATION_REQUIRED" in report["field0a"]["blockers"]


def test_missing_attestation_preserves_no_device_contact_scope(tmp_path: Path) -> None:
    tool = _tool()
    raw, screenshot, export, m4d = _field0a_evidence(tool, tmp_path)
    assert raw.is_dir()

    report = _report(
        tool,
        tmp_path,
        pilot_import_evidence=[screenshot],
        m4d_jpeg=m4d,
        pilot_export_kmz=export,
    )

    assert (
        report["field0a"]["session_attestation"]["blocker_code"]
        == "FIELD0A_ATTESTATION_REQUIRED"
    )
    assert report["safety_scope"]["device_contact"] is False
    assert report["safety_scope"]["device_write"] is False
    assert report["safety_scope"]["flight_or_motor_action"] is False


def test_valid_private_attestation_closes_field0a_but_not_phase3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()

    report = _attested_report(tool, tmp_path, monkeypatch)

    assert report["field0a"]["status"] == "PASS"
    assert report["field0a"]["blockers"] == []
    assert report["field0a"]["pilot_import"]["status"] == "PASS"
    assert report["field0a"]["session_attestation"]["status"] == "PASS"
    assert report["safety_scope"] == {
        "device_contact": True,
        "device_write": True,
        "flight_or_motor_action": False,
        "customer_data_export": False,
    }
    assert report["phase3"]["status"] == "BLOCKED"
    assert set(report["phase3"]["capabilities"].values()) == {"NOT_VERIFIED"}


def test_attestation_rejects_a_local_or_wrong_durable_share_root(tmp_path: Path) -> None:
    tool = _tool()
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    commit, _dirty = tool._commit(repo)
    raw, screenshot, export, m4d = _field0a_evidence(tool, tmp_path)
    attestation = tmp_path / "attestation.json"
    _write_attestation(
        attestation,
        _attestation_payload(
            commit=commit, raw=raw, screenshot=screenshot, export=export, m4d=m4d
        ),
    )

    report = tool.build_report(
        repository_root=repo,
        kit_dir=_ROOT / "docs" / "hil" / "field0a-kit",
        pilot_import_evidence=[screenshot],
        m4d_jpeg=m4d,
        pilot_export_kmz=export,
        field0a_session_attestation=attestation,
        generated_at=datetime(2026, 8, 27, 2, 3, 4, tzinfo=UTC),
    )

    assert (
        report["field0a"]["session_attestation"]["blocker_code"]
        == "FIELD0A_ATTESTATION_DURABLE_SHARE_REQUIRED"
    )


@pytest.mark.parametrize("filesystem", [None, "ext4"])
def test_attestation_requires_a_network_filesystem_at_the_canonical_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filesystem: str | None
) -> None:
    tool = _tool()
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    commit, _dirty = tool._commit(repo)
    raw, screenshot, export, m4d = _field0a_evidence(tool, tmp_path)
    monkeypatch.setattr(tool, "_canonical_field0a_evidence_root", lambda: raw.parent)
    monkeypatch.setattr(tool, "_mount_filesystem_type", lambda _path: filesystem)
    attestation = tmp_path / "attestation.json"
    _write_attestation(
        attestation,
        _attestation_payload(
            commit=commit, raw=raw, screenshot=screenshot, export=export, m4d=m4d
        ),
    )

    report = tool.build_report(
        repository_root=repo,
        kit_dir=_ROOT / "docs" / "hil" / "field0a-kit",
        pilot_import_evidence=[screenshot],
        m4d_jpeg=m4d,
        pilot_export_kmz=export,
        field0a_session_attestation=attestation,
        generated_at=datetime(2026, 8, 27, 2, 3, 4, tzinfo=UTC),
    )

    assert (
        report["field0a"]["session_attestation"]["blocker_code"]
        == "FIELD0A_ATTESTATION_DURABLE_SHARE_REQUIRED"
    )


def test_attestation_requires_explicit_operator_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()

    report = _attested_report(
        tool,
        tmp_path,
        monkeypatch,
        mutate=lambda payload: payload.update({"operator_attested": False}),
    )

    assert (
        report["field0a"]["session_attestation"]["blocker_code"]
        == "FIELD0A_ATTESTATION_OPERATOR_NOT_ATTESTED"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", "other-session"),
        ("operator_id", "other-operator"),
        ("observed_at_utc", "2026-08-27T03:00:00Z"),
    ],
)
def test_attestation_binds_each_artifact_to_the_session_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    tool = _tool()

    def mutate(payload: dict[str, Any]) -> None:
        payload["pilot_imports"][0][field] = value

    report = _attested_report(tool, tmp_path, monkeypatch, mutate=mutate)

    assert (
        report["field0a"]["session_attestation"]["blocker_code"]
        == "FIELD0A_ATTESTATION_SESSION_MISMATCH"
    )


def test_invalid_attestation_is_reported_as_typed_blocker(tmp_path: Path) -> None:
    tool = _tool()
    raw, screenshot, export, m4d = _field0a_evidence(tool, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    attestation = tmp_path / "attestation.json"
    attestation.write_text("not-json", encoding="utf-8")
    attestation.chmod(0o600)

    report = tool.build_report(
        repository_root=repo,
        kit_dir=_ROOT / "docs" / "hil" / "field0a-kit",
        pilot_import_evidence=[screenshot],
        m4d_jpeg=m4d,
        pilot_export_kmz=export,
        field0a_session_attestation=attestation,
        generated_at=datetime(2026, 8, 27, 2, 3, 4, tzinfo=UTC),
    )

    assert report["field0a"]["status"] == "BLOCKED"
    assert report["field0a"]["session_attestation"] == {
        "status": "BLOCKED",
        "blocker_code": "FIELD0A_ATTESTATION_INVALID",
    }


def test_attestation_digest_mismatch_is_a_typed_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    commit, _dirty = tool._commit(repo)
    raw, screenshot, export, m4d = _field0a_evidence(tool, tmp_path)
    _mock_durable_share(tool, monkeypatch, raw)
    payload = _attestation_payload(
        commit=commit, raw=raw, screenshot=screenshot, export=export, m4d=m4d
    )
    payload["pilot_export"]["sha256"] = "0" * 64
    attestation = tmp_path / "attestation.json"
    _write_attestation(attestation, payload)

    report = tool.build_report(
        repository_root=repo,
        kit_dir=_ROOT / "docs" / "hil" / "field0a-kit",
        pilot_import_evidence=[screenshot],
        m4d_jpeg=m4d,
        pilot_export_kmz=export,
        field0a_session_attestation=attestation,
        generated_at=datetime(2026, 8, 27, 2, 3, 4, tzinfo=UTC),
    )

    assert (
        report["field0a"]["session_attestation"]["blocker_code"]
        == "FIELD0A_ATTESTATION_DIGEST_MISMATCH"
    )


def test_attestation_symlink_is_rejected_as_a_typed_blocker(tmp_path: Path) -> None:
    tool = _tool()
    raw, screenshot, export, m4d = _field0a_evidence(tool, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    target = tmp_path / "attestation-target.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    attestation = tmp_path / "attestation.json"
    attestation.symlink_to(target)

    report = tool.build_report(
        repository_root=repo,
        kit_dir=_ROOT / "docs" / "hil" / "field0a-kit",
        pilot_import_evidence=[screenshot],
        m4d_jpeg=m4d,
        pilot_export_kmz=export,
        field0a_session_attestation=attestation,
        generated_at=datetime(2026, 8, 27, 2, 3, 4, tzinfo=UTC),
    )

    assert (
        report["field0a"]["session_attestation"]["blocker_code"]
        == "FIELD0A_ATTESTATION_SYMLINK_REJECTED"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("flight_or_motor_action", True), ("propellers_removed", False)],
)
def test_unsafe_field0a_session_is_a_typed_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: bool
) -> None:
    tool = _tool()
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    commit, _dirty = tool._commit(repo)
    raw, screenshot, export, m4d = _field0a_evidence(tool, tmp_path)
    _mock_durable_share(tool, monkeypatch, raw)
    payload = _attestation_payload(
        commit=commit, raw=raw, screenshot=screenshot, export=export, m4d=m4d
    )
    payload["safety_scope"][field] = value
    attestation = tmp_path / "attestation.json"
    _write_attestation(attestation, payload)

    report = tool.build_report(
        repository_root=repo,
        kit_dir=_ROOT / "docs" / "hil" / "field0a-kit",
        pilot_import_evidence=[screenshot],
        m4d_jpeg=m4d,
        pilot_export_kmz=export,
        field0a_session_attestation=attestation,
        generated_at=datetime(2026, 8, 27, 2, 3, 4, tzinfo=UTC),
    )

    expected = (
        "FIELD0A_ATTESTATION_FLIGHT_OR_MOTOR_ACTION_REPORTED"
        if field == "flight_or_motor_action"
        else "FIELD0A_ATTESTATION_UNSAFE_SESSION"
    )
    assert report["field0a"]["session_attestation"]["blocker_code"] == expected


def test_private_output_is_exclusive_and_owner_only(tmp_path: Path) -> None:
    tool = _tool()
    output = tmp_path / "private" / "readiness.json"
    tool.write_private(output, {"schema_version": "test"})

    assert output.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        tool.write_private(output, {"schema_version": "test"})
