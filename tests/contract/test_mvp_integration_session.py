"""MVP Integration Milestone 1 evidence-session safety gates."""

from __future__ import annotations

import importlib.util
import json
import stat
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePath
from subprocess import CompletedProcess
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "hil" / "prepare_mvp_integration_session.py"
_COMMIT = "a" * 40
_EVIDENCE_STAGE_BY_CHECK = {
    "workspace_opened_in_pilot2": "10_cloud_pilot",
    "wayline_visible_without_file_operation": "10_cloud_pilot",
    "operator_reviewed_execution_surface": "10_cloud_pilot",
    "media_upload_started_without_file_operation": "10_cloud_pilot",
    "work_order_mission_media_lineage_verified": "12_gateway_lineage",
    "manifold_and_aircraft_link_verified": "09_mvp_provider_preflight",
    "camera_media_list_read": "11_psdk_camera_media",
    "one_original_jpeg_downloaded_and_hashed": "11_psdk_camera_media",
    "object_upload_and_lineage_verified": "12_gateway_lineage",
    "downloader_rights_released": "11_psdk_camera_media",
}


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_mvp_integration_session", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(tool: ModuleType) -> dict[str, Any]:
    return tool.build_manifest(
        operator="operator-a",
        aircraft_sn="PENDING-SN",
        build_commit=_COMMIT,
        started_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )


def _actual_manifest(tool: ModuleType) -> dict[str, Any]:
    return tool.build_manifest(
        operator="operator-a",
        aircraft_sn="M4D-ACCEPTANCE-1",
        build_commit=_COMMIT,
        started_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )


def _write_private_evidence(
    session_dir: Path, evidence_ref: str, data: bytes = b"evidence\n"
) -> Path:
    path = session_dir / evidence_ref
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def _write_pass_evidence(
    tool: ModuleType,
    session_dir: Path,
    manifest: dict[str, Any],
    *,
    track_name: str,
    check_name: str,
    evidence_ref: str,
) -> Path:
    envelope_path = PurePath(evidence_ref)
    raw_ref = str(envelope_path.with_name(f"{envelope_path.stem}__raw.log"))
    raw_path = _write_private_evidence(
        session_dir,
        raw_ref,
        f"raw-{track_name}-{check_name}\n".encode(),
    )
    payload = {
        "schema_version": "1.0",
        "session_id": manifest["session_id"],
        "aircraft_sn": manifest["aircraft_sn"],
        "captured_at_utc": "2026-08-20T12:10:00Z",
        "track": track_name,
        "check": check_name,
        "verdict": "PASS",
        "operator_attested": True,
        "assertions": tool._REQUIRED_PASS_ASSERTIONS[track_name][check_name],
        "raw_evidence": [
            {
                "ref": raw_ref,
                "sha256": sha256(raw_path.read_bytes()).hexdigest(),
                "size_bytes": raw_path.stat().st_size,
            }
        ],
    }
    return _write_private_evidence(
        session_dir,
        evidence_ref,
        (json.dumps(payload, sort_keys=True) + "\n").encode(),
    )


def _pass_all_checks(track: dict[str, Any], evidence_ref: str) -> list[str]:
    filename = PurePath(evidence_ref).name
    prefix, suffix = filename.rsplit(".", maxsplit=1)
    evidence_refs: list[str] = []
    for check_name, check in track["checks"].items():
        stage = _EVIDENCE_STAGE_BY_CHECK[check_name]
        check_evidence_ref = f"{stage}/{prefix}__{check_name}.{suffix}"
        check["passed"] = True
        check["evidence_refs"] = [check_evidence_ref]
        evidence_refs.append(check_evidence_ref)
    return evidence_refs


def _finish_manifest(manifest: dict[str, Any]) -> None:
    manifest["aircraft_sn"] = "M4D-ACCEPTANCE-1"
    manifest["session_id"] = "SESS-20260820T120000Z-M4D-ACCEPTANCE-1"
    manifest["ended_at_utc"] = "2026-08-20T12:30:00Z"


def _open_cloud_track(manifest: dict[str, Any]) -> dict[str, Any]:
    cloud = manifest["tracks"]["dji_cloud"]
    cloud["status"] = "NOT_VERIFIED"
    cloud["blocker_code"] = None
    cloud["blocker_evidence_refs"] = []
    return cloud


def test_init_creates_private_secret_free_session_skeleton(tmp_path: Path) -> None:
    tool = _load_tool()
    root = tmp_path / "hil_raw_logs"
    session_dir = tool.initialise_session(root, _manifest(tool))

    assert session_dir.name == "SESS-20260820T120000Z-PENDING-SN"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(session_dir.stat().st_mode) == 0o700
    manifest_path = session_dir / "integration_manifest.json"
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    session_manifest_path = session_dir / "session_manifest.json"
    assert stat.S_IMODE(session_manifest_path.stat().st_mode) == 0o600
    assert json.loads(session_manifest_path.read_text())["session_id"] == session_dir.name
    loaded = tool.load_and_validate(manifest_path)
    assert loaded["schema_version"] == "1.2"
    assert loaded["selection_evidence_ref"] is None
    assert loaded["selected_path"] is None
    assert loaded["tracks"]["dji_cloud"]["status"] == "BLOCKED"
    assert (
        loaded["tracks"]["dji_cloud"]["blocker_code"]
        == "UNSUPPORTED_COMBINATION_IN_OFFICIAL_MATRIX"
    )
    blocker_evidence = session_dir / "10_cloud_pilot" / "provider_support_matrix.json"
    assert stat.S_IMODE(blocker_evidence.stat().st_mode) == 0o600
    blocker_payload = json.loads(blocker_evidence.read_text())
    assert blocker_payload["source_reviewed_on"] == "2026-08-20"
    assert blocker_payload["revalidate_official_source_before_field_use"] is True
    assert "checked_at_utc" not in blocker_payload
    assert loaded["tracks"]["dji_cloud"]["blocker_evidence_refs"] == [
        "10_cloud_pilot/provider_support_matrix.json"
    ]
    assert loaded["tracks"]["psdk_manifold"]["status"] == "NOT_VERIFIED"


def test_secret_like_fields_are_rejected_even_when_nested() -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    manifest["tracks"]["dji_cloud"]["access_token"] = "must-not-be-written"

    with pytest.raises(tool.IntegrationManifestError, match="secret-like"):
        tool.validate_manifest(manifest)


def test_secret_like_values_are_rejected() -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    manifest["selection_reason"] = "Bearer this-value-must-never-be-written"

    with pytest.raises(tool.IntegrationManifestError, match="secret-like 문자열"):
        tool.validate_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("started_at_utc", "not-a-timestamp"),
        ("started_at_utc", "2026-08-20T12:00:00+00:00"),
        ("started_at_utc", "2026-08-20T12:00:00.123Z"),
        ("ended_at_utc", {"unexpected": "object"}),
        ("ended_at_utc", "2026-08-20T11:59:59Z"),
    ],
)
def test_manifest_timestamps_are_strict_utc_seconds(field: str, value: Any) -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    manifest[field] = value

    with pytest.raises(tool.IntegrationManifestError):
        tool.validate_manifest(manifest)


def test_verified_track_requires_all_checks_and_evidence() -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    cloud = _open_cloud_track(manifest)
    cloud["status"] = "VERIFIED"

    with pytest.raises(tool.IntegrationManifestError, match="모든 check"):
        tool.validate_manifest(manifest)

    _pass_all_checks(cloud, "10_cloud_pilot/20260820T121000Z__cloud_acceptance.json")
    _finish_manifest(manifest)
    tool.validate_manifest(manifest)


def test_passed_checks_cannot_reuse_the_same_evidence() -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    psdk = manifest["tracks"]["psdk_manifold"]
    for check_name in ("camera_media_list_read", "one_original_jpeg_downloaded_and_hashed"):
        check = psdk["checks"][check_name]
        check["passed"] = True
        check["evidence_refs"] = ["11_psdk_camera_media/shared.json"]

    with pytest.raises(tool.IntegrationManifestError, match="재사용"):
        tool.validate_manifest(manifest)


def test_cli_validation_requires_referenced_evidence_to_exist(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    cloud = _open_cloud_track(manifest)
    cloud["status"] = "VERIFIED"
    _pass_all_checks(cloud, "10_cloud_pilot/missing.json")
    _finish_manifest(manifest)
    session_dir = tmp_path / manifest["session_id"]
    session_dir.mkdir(mode=0o700)
    manifest_path = session_dir / "integration_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)

    with pytest.raises(tool.IntegrationManifestError, match="실제 evidence"):
        tool.load_and_validate(manifest_path)


def test_cli_validation_rejects_manifest_or_session_symlink(tmp_path: Path) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"

    manifest_alias = session_dir / "manifest-alias.json"
    manifest_alias.symlink_to(manifest_path)
    with pytest.raises(tool.IntegrationManifestError, match="symlink"):
        tool.load_and_validate(manifest_alias)

    session_alias = tmp_path / "session-alias"
    session_alias.symlink_to(session_dir, target_is_directory=True)
    with pytest.raises(tool.IntegrationManifestError, match="symlink"):
        tool.load_and_validate(session_alias / "integration_manifest.json")


def test_provider_selection_requires_verified_track_and_reason() -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    manifest["selected_path"] = "psdk_manifold"
    manifest["selection_reason"] = "PSDK media path passed"

    with pytest.raises(tool.IntegrationManifestError, match="VERIFIED가 아닌"):
        tool.validate_manifest(manifest)


def test_blocked_track_requires_blocker_evidence() -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    cloud = manifest["tracks"]["dji_cloud"]
    cloud["blocker_evidence_refs"] = []

    with pytest.raises(tool.IntegrationManifestError, match="blocker evidence"):
        tool.validate_manifest(manifest)


def test_verified_track_requires_real_aircraft_and_end_time() -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    cloud = _open_cloud_track(manifest)
    cloud["status"] = "VERIFIED"
    _pass_all_checks(cloud, "10_cloud_pilot/cloud.json")

    with pytest.raises(tool.IntegrationManifestError, match="종료시각과 실제 aircraft_sn"):
        tool.validate_manifest(manifest)


def test_psdk_selection_requires_cloud_to_be_blocked() -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    _finish_manifest(manifest)
    psdk = manifest["tracks"]["psdk_manifold"]
    psdk["status"] = "VERIFIED"
    _pass_all_checks(psdk, "11_psdk_camera_media/psdk.json")
    manifest["selected_path"] = "psdk_manifold"
    manifest["selection_reason"] = "PSDK acceptance passed"
    manifest["selection_evidence_ref"] = "13_provider_decision/provider_decision.json"

    manifest["tracks"]["dji_cloud"]["status"] = "NOT_VERIFIED"
    manifest["tracks"]["dji_cloud"]["blocker_code"] = None
    manifest["tracks"]["dji_cloud"]["blocker_evidence_refs"] = []
    with pytest.raises(tool.IntegrationManifestError, match="Cloud track이 BLOCKED"):
        tool.validate_manifest(manifest)

    manifest["tracks"]["dji_cloud"]["status"] = "BLOCKED"
    manifest["tracks"]["dji_cloud"]["blocker_code"] = "UNSUPPORTED_PRODUCT_COMBINATION"
    manifest["tracks"]["dji_cloud"]["blocker_evidence_refs"] = [
        "10_cloud_pilot/provider_support_matrix.json"
    ]
    tool.validate_manifest(manifest)


@pytest.mark.parametrize(
    "evidence_ref",
    [
        "../outside.log",
        "/tmp/evidence.log",
        "11_psdk_camera_media/file.json?token=value",
        "unknown_stage/file.log",
    ],
)
def test_evidence_refs_cannot_escape_or_embed_credentials(evidence_ref: str) -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    psdk = manifest["tracks"]["psdk_manifold"]
    first_check = next(iter(psdk["checks"].values()))
    first_check["evidence_refs"] = [evidence_ref]

    with pytest.raises(tool.IntegrationManifestError):
        tool.validate_manifest(manifest)


def test_cli_verify_reports_only_non_sensitive_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _manifest(tool))

    assert tool.main(["verify", str(session_dir / "integration_manifest.json")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "selected_path": None,
        "session_id": "SESS-20260820T120000Z-PENDING-SN",
        "status": "VALID",
    }


def test_cli_rejects_evidence_directory_and_non_private_file(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", manifest)
    check = manifest["tracks"]["dji_cloud"]["checks"]["workspace_opened_in_pilot2"]

    check["evidence_refs"] = ["10_cloud_pilot"]
    with pytest.raises(tool.IntegrationManifestError, match="일반 evidence 파일"):
        tool.validate_manifest(manifest, evidence_root=session_dir)

    evidence = session_dir / "10_cloud_pilot" / "workspace.json"
    evidence.write_text("{}\n", encoding="utf-8")
    evidence.chmod(0o644)
    check["evidence_refs"] = ["10_cloud_pilot/workspace.json"]
    with pytest.raises(tool.IntegrationManifestError, match="0600 이하"):
        tool.validate_manifest(manifest, evidence_root=session_dir)


def test_cli_rejects_session_directory_name_mismatch(tmp_path: Path) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _manifest(tool))
    wrong_dir = tmp_path / "wrong-session"
    session_dir.rename(wrong_dir)

    with pytest.raises(tool.IntegrationManifestError, match="디렉터리 이름"):
        tool.load_and_validate(wrong_dir / "integration_manifest.json")


def test_preflight_records_unreachable_manifold_without_passing_aircraft_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        return CompletedProcess(
            command,
            1 if command[0] == "ping" else 0,
            stdout="3 packets transmitted, 0 received\n" if command[0] == "ping" else "ok\n",
            stderr="",
        )

    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    evidence_path = tool.capture_host_preflight(
        manifest_path,
        target="172.30.1.33",
        interface="enP7s7",
    )

    assert evidence_path.parent.name == "09_mvp_provider_preflight"
    assert stat.S_IMODE(evidence_path.stat().st_mode) == 0o600
    evidence = json.loads(evidence_path.read_text())
    assert evidence["verdict"] == "MANIFOLD_UNREACHABLE"
    assert evidence["aircraft_link"] == "UNKNOWN"
    assert evidence["host_usb_is_psdk_blocker"] is False
    loaded = tool.load_and_validate(manifest_path)
    psdk = loaded["tracks"]["psdk_manifold"]
    assert psdk["status"] == "BLOCKED"
    assert psdk["blocker_code"] == "MANIFOLD_UNREACHABLE"
    assert psdk["checks"]["manifold_and_aircraft_link_verified"]["passed"] is False
    assert psdk["blocker_evidence_refs"] == [
        psdk["checks"]["manifold_and_aircraft_link_verified"]["evidence_refs"][0]
    ]


def test_preflight_rejects_public_target_and_unsafe_interface(tmp_path: Path) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"

    with pytest.raises(tool.IntegrationManifestError, match="private HIL"):
        tool.capture_host_preflight(
            manifest_path,
            target="8.8.8.8",
            interface="enP7s7",
        )
    with pytest.raises(tool.IntegrationManifestError, match="RFC1918"):
        tool.capture_host_preflight(
            manifest_path,
            target="192.0.2.1",
            interface="enP7s7",
        )
    with pytest.raises(tool.IntegrationManifestError, match="interface"):
        tool.capture_host_preflight(
            manifest_path,
            target="172.30.1.33",
            interface="enP7s7;touch-pwned",
        )


def test_preflight_cannot_mutate_verified_or_selected_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _actual_manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"
    manifest = tool.load_and_validate(manifest_path)
    for check_name in tool._TRACK_CHECKS["psdk_manifold"]:
        stage = _EVIDENCE_STAGE_BY_CHECK[check_name]
        evidence_ref = f"{stage}/{check_name}.json"
        _write_pass_evidence(
            tool,
            session_dir,
            manifest,
            track_name="psdk_manifold",
            check_name=check_name,
            evidence_ref=evidence_ref,
        )
        tool.record_check(
            manifest_path,
            track_name="psdk_manifold",
            check_name=check_name,
            evidence_refs=[evidence_ref],
        )
    tool.select_provider(
        manifest_path,
        track_name="psdk_manifold",
        reason="PSDK real-device acceptance passed",
    )

    def must_not_run(*_: Any, **__: Any) -> CompletedProcess[str]:
        raise AssertionError("preflight commands must not run")

    monkeypatch.setattr(tool.subprocess, "run", must_not_run)
    with pytest.raises(tool.IntegrationManifestError, match="VERIFIED"):
        tool.capture_host_preflight(
            manifest_path,
            target="172.30.1.33",
            interface="enP7s7",
        )
    assert list((session_dir / "09_mvp_provider_preflight").glob("*host_preflight*")) == []


def test_upgrade_legacy_unselected_v11_session_and_sync_summary(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest = _manifest(tool)
    manifest["schema_version"] = "1.1"
    manifest.pop("selection_evidence_ref")
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", manifest)
    manifest_path = session_dir / "integration_manifest.json"
    manifest["steps_completed"] = ["host_preflight"]
    tool._replace_private_json(manifest_path, manifest)

    upgraded = tool.upgrade_manifest(manifest_path)

    assert upgraded["schema_version"] == "1.2"
    assert upgraded["selection_evidence_ref"] is None
    assert tool.load_and_validate(manifest_path)["schema_version"] == "1.2"
    summary = json.loads((session_dir / "session_manifest.json").read_text())
    assert summary["steps_completed"] == ["host_preflight"]
    lock_path = session_dir / ".integration_manifest.lock"
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_upgrade_refuses_selected_legacy_session(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest = _actual_manifest(tool)
    manifest["schema_version"] = "1.1"
    manifest.pop("selection_evidence_ref")
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", manifest)
    psdk = manifest["tracks"]["psdk_manifold"]
    psdk["status"] = "VERIFIED"
    evidence_refs = _pass_all_checks(psdk, "11_psdk_camera_media/psdk.json")
    manifest["ended_at_utc"] = "2026-08-20T12:30:00Z"
    manifest["selected_path"] = "psdk_manifold"
    manifest["selection_reason"] = "legacy selection"
    for ref in evidence_refs:
        _write_private_evidence(session_dir, ref)
    tool._replace_private_json(session_dir / "integration_manifest.json", manifest)

    with pytest.raises(tool.IntegrationManifestError, match="legacy v1.1"):
        tool.upgrade_manifest(session_dir / "integration_manifest.json")


def test_all_check_envelope_profiles_are_recordable(tmp_path: Path) -> None:
    tool = _load_tool()
    for track_name, check_names in tool._TRACK_CHECKS.items():
        for check_name in check_names:
            manifest = _actual_manifest(tool)
            if track_name == "dji_cloud":
                _open_cloud_track(manifest)
            root = tmp_path / track_name / check_name / "hil_raw_logs"
            session_dir = tool.initialise_session(root, manifest)
            manifest_path = session_dir / "integration_manifest.json"
            stage = _EVIDENCE_STAGE_BY_CHECK[check_name]
            evidence_ref = f"{stage}/{check_name}.json"
            _write_pass_evidence(
                tool,
                session_dir,
                manifest,
                track_name=track_name,
                check_name=check_name,
                evidence_ref=evidence_ref,
            )

            recorded = tool.record_check(
                manifest_path,
                track_name=track_name,
                check_name=check_name,
                evidence_refs=[evidence_ref],
            )

            assert recorded["tracks"][track_name]["checks"][check_name]["passed"] is True


def test_record_checks_reaches_ready_and_select_writes_digest_decision(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _actual_manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"
    manifest = tool.load_and_validate(manifest_path)
    evidence_by_check = {
        "manifold_and_aircraft_link_verified": "09_mvp_provider_preflight/link.json",
        "camera_media_list_read": "11_psdk_camera_media/list.json",
        "one_original_jpeg_downloaded_and_hashed": "11_psdk_camera_media/jpeg.json",
        "object_upload_and_lineage_verified": "12_gateway_lineage/lineage.json",
        "downloader_rights_released": "11_psdk_camera_media/rights.json",
    }
    for index, (check_name, evidence_ref) in enumerate(evidence_by_check.items()):
        _write_pass_evidence(
            tool,
            session_dir,
            manifest,
            track_name="psdk_manifold",
            check_name=check_name,
            evidence_ref=evidence_ref,
        )
        payload = tool.record_check(
            manifest_path,
            track_name="psdk_manifold",
            check_name=check_name,
            evidence_refs=[evidence_ref],
        )
        expected = "READY_FOR_DECISION" if index == 4 else "NOT_VERIFIED"
        assert payload["tracks"]["psdk_manifold"]["status"] == expected

    decision_path = tool.select_provider(
        manifest_path,
        track_name="psdk_manifold",
        reason="PSDK M1 acceptance checks passed",
    )

    decision = json.loads(decision_path.read_text())
    assert stat.S_IMODE(decision_path.stat().st_mode) == 0o600
    assert decision["selected_provider"] == "psdk_manifold"
    assert len(decision["check_evidence"]) == 5
    first = decision["check_evidence"][0]
    assert first["sha256"] == sha256((session_dir / first["evidence_ref"]).read_bytes()).hexdigest()
    loaded = tool.load_and_validate(manifest_path)
    assert loaded["selected_path"] == "psdk_manifold"
    assert loaded["tracks"]["psdk_manifold"]["status"] == "VERIFIED"
    assert loaded["selection_evidence_ref"] == str(decision_path.relative_to(session_dir))
    assert loaded["ended_at_utc"] is not None
    summary = json.loads((session_dir / "session_manifest.json").read_text())
    assert summary["ended_at_utc"] == loaded["ended_at_utc"]
    assert "provider_selected" in summary["steps_completed"]

    first_envelope = json.loads((session_dir / first["evidence_ref"]).read_text())
    first_path = session_dir / first_envelope["raw_evidence"][0]["ref"]
    original = first_path.read_bytes()
    first_path.write_bytes(b"tampered\n")
    with pytest.raises(tool.IntegrationManifestError, match="digest/size"):
        tool.load_and_validate(manifest_path)
    first_path.write_bytes(original)

    decision_path.unlink()
    with pytest.raises(tool.IntegrationManifestError, match="실제 evidence"):
        tool.load_and_validate(manifest_path)


def test_record_check_pending_aircraft_cannot_reach_ready(tmp_path: Path) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"
    manifest = tool.load_and_validate(manifest_path)
    check_names = list(tool._TRACK_CHECKS["psdk_manifold"])
    for index, check_name in enumerate(check_names):
        stage = _EVIDENCE_STAGE_BY_CHECK[check_name]
        evidence_ref = f"{stage}/check_{index}.json"
        _write_pass_evidence(
            tool,
            session_dir,
            manifest,
            track_name="psdk_manifold",
            check_name=check_name,
            evidence_ref=evidence_ref,
        )
        if index == len(check_names) - 1:
            with pytest.raises(tool.IntegrationManifestError, match="실제 aircraft_sn"):
                tool.record_check(
                    manifest_path,
                    track_name="psdk_manifold",
                    check_name=check_name,
                    evidence_refs=[evidence_ref],
                )
        else:
            tool.record_check(
                manifest_path,
                track_name="psdk_manifold",
                check_name=check_name,
                evidence_refs=[evidence_ref],
            )
    loaded = tool.load_and_validate(manifest_path)
    assert loaded["tracks"]["psdk_manifold"]["status"] == "NOT_VERIFIED"
    assert loaded["tracks"]["psdk_manifold"]["checks"][check_names[-1]]["passed"] is False


def test_record_blocker_marks_failed_check_and_preserves_private_evidence(tmp_path: Path) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _actual_manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"
    evidence_ref = "11_psdk_camera_media/camera_list_failure.json"
    _write_private_evidence(session_dir, evidence_ref)

    payload = tool.record_blocker(
        manifest_path,
        track_name="psdk_manifold",
        check_name="camera_media_list_read",
        blocker_code="CAMERA_MEDIA_LIST_FAILED",
        evidence_refs=[evidence_ref],
    )

    psdk = payload["tracks"]["psdk_manifold"]
    assert psdk["status"] == "BLOCKED"
    assert psdk["blocker_code"] == "CAMERA_MEDIA_LIST_FAILED"
    assert psdk["blocker_evidence_refs"] == [evidence_ref]
    assert psdk["checks"]["camera_media_list_read"] == {
        "passed": False,
        "evidence_refs": [evidence_ref],
    }


def test_preflight_does_not_clear_a_more_specific_psdk_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _actual_manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"
    blocker_ref = "11_psdk_camera_media/camera_list_failure.json"
    _write_private_evidence(session_dir, blocker_ref)
    tool.record_blocker(
        manifest_path,
        track_name="psdk_manifold",
        check_name="camera_media_list_read",
        blocker_code="CAMERA_MEDIA_LIST_FAILED",
        evidence_refs=[blocker_ref],
    )

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        return CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    preflight_path = tool.capture_host_preflight(
        manifest_path,
        target="172.30.1.33",
        interface="enP7s7",
    )

    loaded = tool.load_and_validate(manifest_path)
    psdk = loaded["tracks"]["psdk_manifold"]
    assert psdk["status"] == "BLOCKED"
    assert psdk["blocker_code"] == "CAMERA_MEDIA_LIST_FAILED"
    assert psdk["blocker_evidence_refs"] == [blocker_ref]
    assert (
        str(preflight_path.relative_to(session_dir))
        in psdk["checks"]["manifold_and_aircraft_link_verified"]["evidence_refs"]
    )


def test_attest_check_requires_explicit_attestation_and_hashes_raw_evidence(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _actual_manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"
    raw_ref = "11_psdk_camera_media/media_list_raw.log"
    raw_path = _write_private_evidence(session_dir, raw_ref, b"camera-media-list\n")

    with pytest.raises(tool.IntegrationManifestError, match="attest-required-assertions"):
        tool.attest_check(
            manifest_path,
            track_name="psdk_manifold",
            check_name="camera_media_list_read",
            raw_evidence_refs=[raw_ref],
            operator_attested=False,
        )

    evidence_path = tool.attest_check(
        manifest_path,
        track_name="psdk_manifold",
        check_name="camera_media_list_read",
        raw_evidence_refs=[raw_ref],
        operator_attested=True,
    )

    envelope = json.loads(evidence_path.read_text())
    assert envelope["operator_attested"] is True
    assert envelope["raw_evidence"] == [
        {
            "ref": raw_ref,
            "sha256": sha256(raw_path.read_bytes()).hexdigest(),
            "size_bytes": raw_path.stat().st_size,
        }
    ]
    loaded = tool.load_and_validate(manifest_path)
    assert loaded["tracks"]["psdk_manifold"]["checks"]["camera_media_list_read"]["passed"]

    raw_path.write_bytes(b"changed\n")
    with pytest.raises(tool.IntegrationManifestError, match="digest/size"):
        tool.load_and_validate(manifest_path)


def test_pass_transition_replaces_prior_failure_evidence(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest = _actual_manifest(tool)
    prior_ref = "09_mvp_provider_preflight/prior_unreachable.json"
    link_check = manifest["tracks"]["psdk_manifold"]["checks"][
        "manifold_and_aircraft_link_verified"
    ]
    link_check["evidence_refs"] = [prior_ref]
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", manifest)
    manifest_path = session_dir / "integration_manifest.json"
    _write_private_evidence(session_dir, prior_ref)
    raw_ref = "09_mvp_provider_preflight/current_link_raw.log"
    _write_private_evidence(session_dir, raw_ref)

    envelope_path = tool.attest_check(
        manifest_path,
        track_name="psdk_manifold",
        check_name="manifold_and_aircraft_link_verified",
        raw_evidence_refs=[raw_ref],
        operator_attested=True,
    )

    loaded = tool.load_and_validate(manifest_path)
    assert loaded["tracks"]["psdk_manifold"]["checks"]["manifold_and_aircraft_link_verified"][
        "evidence_refs"
    ] == [str(envelope_path.relative_to(session_dir))]
    assert (session_dir / prior_ref).exists()


def test_record_check_rejects_wrong_stage_and_unsafe_lock(tmp_path: Path) -> None:
    tool = _load_tool()
    session_dir = tool.initialise_session(tmp_path / "hil_raw_logs", _actual_manifest(tool))
    manifest_path = session_dir / "integration_manifest.json"
    wrong_stage_ref = "11_psdk_camera_media/link.json"
    _write_private_evidence(session_dir, wrong_stage_ref)

    with pytest.raises(tool.IntegrationManifestError, match="stage"):
        tool.record_check(
            manifest_path,
            track_name="psdk_manifold",
            check_name="manifold_and_aircraft_link_verified",
            evidence_refs=[wrong_stage_ref],
        )

    right_stage_ref = "09_mvp_provider_preflight/link.json"
    _write_private_evidence(session_dir, right_stage_ref)
    lock_path = session_dir / ".integration_manifest.lock"
    lock_path.write_text("", encoding="utf-8")
    lock_path.chmod(0o644)
    with pytest.raises(tool.IntegrationManifestError, match="lock"):
        tool.record_check(
            manifest_path,
            track_name="psdk_manifold",
            check_name="manifold_and_aircraft_link_verified",
            evidence_refs=[right_stage_ref],
        )
