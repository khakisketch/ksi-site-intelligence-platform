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
_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64


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


def _private_file(root: Path, ref: str, payload: str = "{}\n") -> Path:
    path = root / ref
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)
    return path


def _session(tool: ModuleType, tmp_path: Path) -> tuple[Path, Path]:
    session = tool.initialise(tmp_path / "hil", _manifest(tool))
    return session, session / "integration_manifest.v1.4.json"


def _prepare_approved_build(tool: ModuleType, session: Path, manifest_path: Path) -> None:
    _private_file(session, "14_connected_edge_capabilities/psdk-build.json")
    tool.record_adapter_build(
        manifest_path,
        integration_path="PSDK_MANIFOLD",
        status_value="SDK_BUILT",
        code_commit="commit-1",
        sdk_version="PSDK-3.16.0",
        build_sha256=_SHA_A,
        evidence_refs=["14_connected_edge_capabilities/psdk-build.json"],
    )
    _private_file(session, "14_connected_edge_capabilities/approval.json")
    tool.record_approval(
        manifest_path,
        approved_by="owner-1",
        dpk_sha256=_SHA_B,
        expires_at_utc="2026-08-21T10:00:00Z",
        allowed_operations=["DPK_INSTALL", "WAYLINE_UPLOAD_NO_START"],
        evidence_ref="14_connected_edge_capabilities/approval.json",
        approved_at=datetime(2026, 8, 21, 9, 1, tzinfo=UTC),
    )


def test_v14_defaults_all_capabilities_paths_and_flags_fail_closed() -> None:
    tool = _tool()
    manifest = _manifest(tool)
    tool.validate_manifest(manifest)
    summary = tool.acceptance_summary(manifest)
    assert manifest["schema_version"] == "1.4"
    assert set(manifest["adapter_builds"]) == tool.PATHS
    assert set(summary["missing_capabilities"]) == set(tool.CAPABILITIES)
    assert summary["verified_capabilities"] == []
    assert summary["feature_flags_enabled"] == []
    assert summary["rc_base_ready_for_feature_enable"] is False
    assert summary["finalized"] is False


def test_v13_reader_remains_fail_closed() -> None:
    tool = _tool()
    manifest = _manifest(tool)
    manifest["schema_version"] = "1.3"
    for field in ("adapter_builds", "operation_approval", "finalization"):
        manifest.pop(field)
    added_receipt_fields = tool._V14_RECEIPT_FIELDS - tool._V13_RECEIPT_FIELDS
    for receipt in manifest["capability_receipts"].values():
        for field in added_receipt_fields:
            receipt.pop(field)
    tool.validate_manifest(manifest)
    assert tool.acceptance_summary(manifest)["schema_version"] == "1.3"


def test_feature_flag_cannot_enable_unverified_capability() -> None:
    tool = _tool()
    manifest = _manifest(tool)
    manifest["feature_flags"]["MEDIA_PULL"] = True
    with pytest.raises(tool.ConnectedEdgeManifestError, match="VERIFIED 전"):
        tool.validate_manifest(manifest)


def test_sdk_build_requires_digest_version_commit_and_private_evidence(tmp_path: Path) -> None:
    tool = _tool()
    session, manifest_path = _session(tool, tmp_path)
    _private_file(session, "14_connected_edge_capabilities/build.json")
    with pytest.raises(tool.ConnectedEdgeManifestError, match="SDK_BUILT"):
        tool.record_adapter_build(
            manifest_path,
            integration_path="PSDK_MANIFOLD",
            status_value="SDK_BUILT",
            code_commit="commit-1",
            sdk_version=None,
            build_sha256=_SHA_A,
            evidence_refs=["14_connected_edge_capabilities/build.json"],
        )
    assert tool.load(manifest_path)["adapter_builds"]["PSDK_MANIFOLD"]["status"] == "NOT_BUILT"


def test_approval_is_bound_to_session_devices_digest_operations_and_expiry(tmp_path: Path) -> None:
    tool = _tool()
    session, manifest_path = _session(tool, tmp_path)
    _private_file(session, "14_connected_edge_capabilities/approval.json")
    tool.record_approval(
        manifest_path,
        approved_by="owner-1",
        dpk_sha256=_SHA_B,
        expires_at_utc="2026-08-21T10:00:00Z",
        allowed_operations=["DPK_INSTALL", "WAYLINE_UPLOAD_NO_START"],
        evidence_ref="14_connected_edge_capabilities/approval.json",
        approved_at=datetime(2026, 8, 21, 9, 1, tzinfo=UTC),
    )
    approval = tool.load(manifest_path)["operation_approval"]
    assert approval["session_id"].startswith("CONNECTED-")
    assert approval["aircraft_sn"] == "M4D-1"
    assert approval["edge_device_id"] == "manifold-1"
    assert approval["gateway_device_id"] == "rc-plus-2-1"
    assert approval["dpk_sha256"] == _SHA_B
    assert set(approval["allowed_operations"]) == {"DPK_INSTALL", "WAYLINE_UPLOAD_NO_START"}

    tampered = tool.load(manifest_path)
    tampered["operation_approval"]["aircraft_sn"] = "OTHER"
    with pytest.raises(tool.ConnectedEdgeManifestError, match="aircraft_sn"):
        tool.validate_manifest(tampered, evidence_root=session)


def test_verified_result_requires_approval_exact_build_and_keeps_flag_off(tmp_path: Path) -> None:
    tool = _tool()
    session, manifest_path = _session(tool, tmp_path)
    _prepare_approved_build(tool, session, manifest_path)
    _private_file(session, "14_connected_edge_capabilities/wayline-result.json")
    tool.record_result(
        manifest_path,
        capability="WAYLINE_DELIVERY",
        integration_path="PSDK_MANIFOLD",
        transport="MOP",
        hardware_model="M4D+MANIFOLD3+RC_PLUS_2",
        firmware_version="M4D-17.00.00.01+PSDK-3.16.0",
        adapter_build_sha256=_SHA_A,
        provider_operation_id="wayline-upload-1",
        artifact_sha256=_SHA_C,
        request_sha256=_SHA_D,
        evidence_refs=["14_connected_edge_capabilities/wayline-result.json"],
        checked_at=datetime(2026, 8, 21, 9, 10, tzinfo=UTC),
    )
    manifest = tool.load(manifest_path)
    receipt = manifest["capability_receipts"]["WAYLINE_DELIVERY"]
    assert receipt["status"] == "VERIFIED"
    assert receipt["flight_action_started"] is False
    assert receipt["camera_write"] is False
    assert manifest["feature_flags"]["WAYLINE_DELIVERY"] is False


def test_result_rejects_missing_operation_or_expired_approval(tmp_path: Path) -> None:
    tool = _tool()
    session, manifest_path = _session(tool, tmp_path)
    _private_file(session, "14_connected_edge_capabilities/build.json")
    tool.record_adapter_build(
        manifest_path,
        integration_path="PSDK_MANIFOLD",
        status_value="SDK_BUILT",
        code_commit="commit-1",
        sdk_version="PSDK-3.16.0",
        build_sha256=_SHA_A,
        evidence_refs=["14_connected_edge_capabilities/build.json"],
    )
    _private_file(session, "14_connected_edge_capabilities/approval.json")
    tool.record_approval(
        manifest_path,
        approved_by="owner-1",
        dpk_sha256=_SHA_B,
        expires_at_utc="2026-08-21T09:05:00Z",
        allowed_operations=["DPK_INSTALL"],
        evidence_ref="14_connected_edge_capabilities/approval.json",
        approved_at=datetime(2026, 8, 21, 9, 1, tzinfo=UTC),
    )
    _private_file(session, "14_connected_edge_capabilities/result.json")
    with pytest.raises(tool.ConnectedEdgeManifestError, match="승인 operation"):
        tool.record_result(
            manifest_path,
            capability="WAYLINE_DELIVERY",
            integration_path="PSDK_MANIFOLD",
            transport="MOP",
            hardware_model="M4D+MANIFOLD3+RC_PLUS_2",
            firmware_version="firmware-1",
            adapter_build_sha256=_SHA_A,
            provider_operation_id="op-1",
            artifact_sha256=_SHA_C,
            request_sha256=_SHA_D,
            evidence_refs=["14_connected_edge_capabilities/result.json"],
            checked_at=datetime(2026, 8, 21, 9, 10, tzinfo=UTC),
        )


def test_capability_evidence_cannot_be_reused_and_verdict_cannot_be_replaced(
    tmp_path: Path,
) -> None:
    tool = _tool()
    session, manifest_path = _session(tool, tmp_path)
    shared = "14_connected_edge_capabilities/shared.json"
    _private_file(session, shared)
    tool.record_blocker(
        manifest_path,
        capability="EDGE_DOWNLINK",
        integration_path="DJI_CLOUD",
        hardware_model="M4D+MANIFOLD3+RC_PLUS_2",
        firmware_version="firmware-1",
        blocker_code="NO_RECEIVE_API",
        evidence_refs=[shared],
        checked_at=datetime(2026, 8, 21, 9, 10, tzinfo=UTC),
    )
    with pytest.raises(tool.ConnectedEdgeManifestError, match="재사용"):
        tool.record_blocker(
            manifest_path,
            capability="EDGE_UPLINK",
            integration_path="DJI_CLOUD",
            hardware_model="M4D+MANIFOLD3+RC_PLUS_2",
            firmware_version="firmware-1",
            blocker_code="NO_SESSION",
            evidence_refs=[shared],
            checked_at=datetime(2026, 8, 21, 9, 11, tzinfo=UTC),
        )
    with pytest.raises(tool.ConnectedEdgeManifestError, match="교체"):
        tool.record_blocker(
            manifest_path,
            capability="EDGE_DOWNLINK",
            integration_path="DJI_CLOUD",
            hardware_model="M4D+MANIFOLD3+RC_PLUS_2",
            firmware_version="firmware-1",
            blocker_code="SECOND_VERDICT",
            evidence_refs=[shared],
        )


def test_private_evidence_rejects_permissions_symlink_and_secret_material(tmp_path: Path) -> None:
    tool = _tool()
    manifest = _manifest(tool)
    receipt = manifest["capability_receipts"]["MEDIA_PULL"]
    receipt.update(
        {
            "status": "BLOCKED",
            "path": "PSDK_MANIFOLD",
            "checked_at_utc": "2026-08-21T09:10:00Z",
            "evidence_refs": ["14_connected_edge_capabilities/evidence.json"],
            "blocker_code": "NO_MEDIA",
        }
    )
    evidence = _private_file(tmp_path, receipt["evidence_refs"][0])
    evidence.chmod(0o644)
    with pytest.raises(tool.ConnectedEdgeManifestError, match="private"):
        tool.validate_manifest(manifest, evidence_root=tmp_path)

    evidence.chmod(0o600)
    target = _private_file(tmp_path, "14_connected_edge_capabilities/target.json")
    evidence.unlink()
    evidence.symlink_to(target.name)
    with pytest.raises(tool.ConnectedEdgeManifestError, match="symlink"):
        tool.validate_manifest(manifest, evidence_root=tmp_path)

    evidence.unlink()
    _private_file(
        tmp_path,
        receipt["evidence_refs"][0],
        '{"access_token":"plain-secret-value"}\n',
    )
    with pytest.raises(tool.ConnectedEdgeManifestError, match="credential"):
        tool.validate_manifest(manifest, evidence_root=tmp_path)


def test_finalize_seals_digest_and_rejects_later_mutation_or_tamper(tmp_path: Path) -> None:
    tool = _tool()
    session, manifest_path = _session(tool, tmp_path)
    _private_file(session, "14_connected_edge_capabilities/blocker.json")
    tool.record_blocker(
        manifest_path,
        capability="MEDIA_UPLOAD",
        integration_path="MANIFOLD_DIRECT",
        hardware_model="M4D+MANIFOLD3+RC_PLUS_2",
        firmware_version="firmware-1",
        blocker_code="NO_NETWORK",
        evidence_refs=["14_connected_edge_capabilities/blocker.json"],
        checked_at=datetime(2026, 8, 21, 9, 10, tzinfo=UTC),
    )
    tool.finalize(manifest_path, finalized_at=datetime(2026, 8, 21, 9, 20, tzinfo=UTC))
    sealed = tool.load(manifest_path)
    assert sealed["finalization"]["manifest_sha256"]
    assert tool.acceptance_summary(sealed)["finalized"] is True
    with pytest.raises(tool.ConnectedEdgeManifestError, match="finalized"):
        tool.record_blocker(
            manifest_path,
            capability="EDGE_UPLINK",
            integration_path="DJI_CLOUD",
            hardware_model="M4D+MANIFOLD3+RC_PLUS_2",
            firmware_version="firmware-1",
            blocker_code="NO_SESSION",
            evidence_refs=["14_connected_edge_capabilities/blocker.json"],
        )

    sealed["operator"] = "tampered"
    manifest_path.write_text(json.dumps(sealed), encoding="utf-8")
    manifest_path.chmod(0o600)
    with pytest.raises(tool.ConnectedEdgeManifestError, match="digest"):
        tool.load(manifest_path)


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
    assert migrated["schema_version"] == "1.4"
    assert migrated["legacy_source_sha256"]
    assert all(
        receipt["status"] == "NOT_VERIFIED"
        for receipt in migrated["capability_receipts"].values()
    )
    assert all(flag is False for flag in migrated["feature_flags"].values())


def test_init_writes_private_v14_manifest(tmp_path: Path) -> None:
    tool = _tool()
    session = tool.initialise(tmp_path / "hil", _manifest(tool))
    path = session / "integration_manifest.v1.4.json"
    assert path.stat().st_mode & 0o077 == 0
    assert json.loads(path.read_text())["schema_version"] == "1.4"
