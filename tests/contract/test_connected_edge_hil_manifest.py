from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "hil" / "prepare_connected_edge_session.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_connected_edge_session", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(tool: ModuleType) -> dict[str, Any]:
    return tool.build_manifest(
        operator="operator-1",
        aircraft_sn="M4D-1",
        edge_device_id="manifold-1",
        gateway_device_id="rc-plus-2-1",
        started_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
    )


def test_v13_defaults_all_capabilities_and_flags_fail_closed() -> None:
    tool = _tool()
    manifest = _manifest(tool)
    tool.validate_manifest(manifest)
    summary = tool.acceptance_summary(manifest)
    assert set(summary["missing_capabilities"]) == set(tool.CAPABILITIES)
    assert summary["feature_flags_enabled"] == []
    assert summary["rc_base_ready_for_feature_enable"] is False


def test_verified_capability_requires_exact_path_time_and_private_evidence(tmp_path: Path) -> None:
    tool = _tool()
    manifest = _manifest(tool)
    receipt = manifest["capability_receipts"]["EDGE_DOWNLINK"]
    receipt.update(
        {
            "status": "VERIFIED",
            "path": "DJI_CLOUD",
            "checked_at_utc": "2026-08-21T09:10:00Z",
            "evidence_refs": ["14_connected_edge_capabilities/edge-downlink.json"],
            "blocker_code": None,
        }
    )
    with pytest.raises(tool.ConnectedEdgeManifestError, match="evidence"):
        tool.validate_manifest(manifest, evidence_root=tmp_path)
    evidence = tmp_path / "14_connected_edge_capabilities" / "edge-downlink.json"
    evidence.parent.mkdir(mode=0o700)
    evidence.write_text("{}\n")
    evidence.chmod(0o600)
    tool.validate_manifest(manifest, evidence_root=tmp_path)


def test_feature_flag_cannot_enable_unverified_capability() -> None:
    tool = _tool()
    manifest = _manifest(tool)
    manifest["feature_flags"]["MEDIA_PULL"] = True
    with pytest.raises(tool.ConnectedEdgeManifestError, match="VERIFIED 전"):
        tool.validate_manifest(manifest)


def test_capability_evidence_cannot_be_reused_or_blocked_without_evidence() -> None:
    tool = _tool()
    manifest = _manifest(tool)
    for capability in ("EDGE_UPLINK", "MEDIA_UPLOAD"):
        manifest["capability_receipts"][capability].update(
            {
                "status": "VERIFIED",
                "path": "DJI_CLOUD",
                "checked_at_utc": "2026-08-21T09:10:00Z",
                "evidence_refs": ["14_connected_edge_capabilities/shared.json"],
                "blocker_code": None,
            }
        )
    with pytest.raises(tool.ConnectedEdgeManifestError, match="재사용"):
        tool.validate_manifest(manifest)

    manifest = _manifest(tool)
    manifest["capability_receipts"]["MEDIA_PULL"].update(
        {"status": "BLOCKED", "blocker_code": "MEDIA_PULL_FAILED"}
    )
    with pytest.raises(tool.ConnectedEdgeManifestError, match="blocker_code와 evidence"):
        tool.validate_manifest(manifest)


def test_v12_migration_never_infers_capability_verification() -> None:
    tool = _tool()
    legacy = {
        "schema_version": "1.2",
        "session_id": "SESS-20260821T090000Z-M4D-1",
        "operator": "operator-1",
        "aircraft_sn": "M4D-1",
        "started_at_utc": "2026-08-21T09:00:00Z",
        "selected_path": "psdk_manifold",
        "tracks": {"psdk_manifold": {"status": "VERIFIED"}},
    }
    migrated = tool.migrate_v12(legacy)
    assert migrated["legacy_source_sha256"]
    assert all(
        receipt["status"] == "NOT_VERIFIED"
        for receipt in migrated["capability_receipts"].values()
    )
    assert all(flag is False for flag in migrated["feature_flags"].values())


def test_init_writes_private_manifest(tmp_path: Path) -> None:
    tool = _tool()
    session = tool.initialise(tmp_path / "hil", _manifest(tool))
    path = session / "integration_manifest.v1.3.json"
    assert path.stat().st_mode & 0o077 == 0
    assert json.loads(path.read_text())["schema_version"] == "1.3"
