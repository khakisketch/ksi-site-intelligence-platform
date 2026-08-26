from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools" / "edge"))

from check_psdk_waypoint_archive import (  # noqa: E402
    audit_archive,
    parse_nm_locations,
)


def _fixture(tmp_path: Path, nm_output: str) -> tuple[Path, Path, Path]:
    psdk_root = tmp_path / "psdk"
    archive = psdk_root / "psdk_lib/lib/aarch64-linux-gnu-gcc/libpayloadsdk.a"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"pinned archive fixture")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    lock = tmp_path / "PSDK_LOCK.yaml"
    lock.write_text(
        "\n".join(
            (
                '  observed_version: "3.16.0"',
                "  library_path: psdk_lib/lib/aarch64-linux-gnu-gcc/libpayloadsdk.a",
                f"  library_sha256_on_device: {digest}",
            )
        ),
        encoding="utf-8",
    )
    output_file = tmp_path / "nm.txt"
    output_file.write_text(nm_output, encoding="utf-8")
    nm_tool = tmp_path / "nm"
    nm_tool.write_text(
        '#!/usr/bin/env bash\ncat "${KSI_TEST_NM_OUTPUT}"\n',
        encoding="utf-8",
    )
    nm_tool.chmod(nm_tool.stat().st_mode | stat.S_IEXEC)
    return lock, psdk_root, nm_tool


def _line(symbol: str, *, member: str = "dji_waypoint_v3.c.o", binding: str = "T") -> str:
    return f"fixture/libpayloadsdk.a:{member}:00000000 {binding} {symbol}\n"


def test_nm_parser_preserves_archive_member_and_binding() -> None:
    parsed = parse_nm_locations(
        _line("DjiWaypointV3_Init")
        + _line("DjiWaypointV3_StartAction", binding="t")
    )
    assert parsed["DjiWaypointV3_Init"][0].member == "dji_waypoint_v3.c.o"
    assert parsed["DjiWaypointV3_StartAction"][0].binding == "t"


def test_exact_upload_only_members_are_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = "".join(
        _line(symbol, member=f"{symbol}.o")
        for symbol in (
            "DjiWaypointV3_Init",
            "DjiWaypointV3_UploadKmzFile",
            "DjiWaypointV3_DeInit",
        )
    )
    lock, psdk_root, nm_tool = _fixture(tmp_path, output)
    monkeypatch.setenv("KSI_TEST_NM_OUTPUT", str(tmp_path / "nm.txt"))
    audit = audit_archive(lock_path=lock, psdk_root=psdk_root, nm_tool=str(nm_tool))
    assert audit.status == "READY"
    assert audit.unexpected_symbols == ()
    assert audit.flight_action_started is False
    assert audit.camera_write is False


def test_action_in_upload_member_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = "".join(
        _line(symbol)
        for symbol in (
            "DjiWaypointV3_Init",
            "DjiWaypointV3_UploadKmzFile",
            "DjiWaypointV3_DeInit",
            "DjiWaypointV3_Action",
            "DjiWaypointV3_StartAction",
        )
    )
    lock, psdk_root, nm_tool = _fixture(tmp_path, output)
    monkeypatch.setenv("KSI_TEST_NM_OUTPUT", str(tmp_path / "nm.txt"))
    audit = audit_archive(lock_path=lock, psdk_root=psdk_root, nm_tool=str(nm_tool))
    assert audit.status == "BLOCKED"
    assert "ACTION_COLOCATED_WITH_UPLOAD" in audit.reason_codes
    assert audit.unexpected_symbols == (
        "DjiWaypointV3_Action",
        "DjiWaypointV3_StartAction",
    )


def test_action_in_unselected_member_does_not_create_false_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = "".join(
        (
            _line("DjiWaypointV3_Init", member="init.o"),
            _line("DjiWaypointV3_UploadKmzFile", member="upload.o"),
            _line("DjiWaypointV3_DeInit", member="deinit.o"),
            _line("DjiWaypointV3_Action", member="action.o"),
        )
    )
    lock, psdk_root, nm_tool = _fixture(tmp_path, output)
    monkeypatch.setenv("KSI_TEST_NM_OUTPUT", str(tmp_path / "nm.txt"))
    audit = audit_archive(lock_path=lock, psdk_root=psdk_root, nm_tool=str(nm_tool))
    assert audit.status == "READY"
    assert "DjiWaypointV3_Action" not in audit.retained_waypoint_symbols


def test_hash_mismatch_is_unavailable_without_running_nm(tmp_path: Path) -> None:
    lock, psdk_root, nm_tool = _fixture(tmp_path, "")
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(
            hashlib.sha256(b"pinned archive fixture").hexdigest(), "0" * 64
        ),
        encoding="utf-8",
    )
    audit = audit_archive(lock_path=lock, psdk_root=psdk_root, nm_tool=str(nm_tool))
    assert audit.status == "UNAVAILABLE"
    assert audit.reason_codes == ("PINNED_ARCHIVE_SHA256_MISMATCH",)


def test_current_pinned_archive_emits_reproducible_action_blocker() -> None:
    archive = (
        _ROOT
        / "edge/third_party/psdk/psdk_lib/lib/aarch64-linux-gnu-gcc/libpayloadsdk.a"
    )
    if not archive.is_file():
        pytest.skip("pinned PSDK tree is an explicit local build input")
    completed = subprocess.run(
        [
            sys.executable,
            str(_ROOT / "tools/edge/check_psdk_waypoint_archive.py"),
            "--format",
            "json",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "BLOCKED"
    assert "ACTION_COLOCATED_WITH_UPLOAD" in payload["reason_codes"]
    assert "DjiWaypointV3_Action" in payload["unexpected_symbols"]


def test_psdk_app_configure_runs_archive_gate_before_adding_candidate_source() -> None:
    cmake = (_ROOT / "edge/psdk-app/CMakeLists.txt").read_text(encoding="utf-8")
    gate = cmake.index("check_psdk_waypoint_archive.py")
    source = cmake.index("src/flight_execution/waypoint_v3_upload_only.cpp")
    assert gate < source
    assert "Waypoint upload-only archive preflight failed closed" in cmake
