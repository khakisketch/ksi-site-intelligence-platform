"""Prepare and validate a secret-free MVP Integration Milestone 1 evidence session.

``init`` creates metadata and directories only. ``preflight`` records local network
state and an ICMP reachability probe, but never opens a remote session or calls DJI
Cloud, aircraft, camera, storage, or object-storage APIs. Device and provider
operations remain explicit HIL steps in ``docs/hil/MVP_INTEGRATION_M1_ACCEPTANCE.md``.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

_SESSION_ID_RE = re.compile(r"^SESS-\d{8}T\d{6}Z-(?:PENDING-SN|[A-Za-z0-9-]+)$")
_AIRCRAFT_SN_RE = re.compile(r"^(?:PENDING-SN|[A-Za-z0-9-]+)$")
_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_BLOCKER_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_PRIVATE_HIL_NETWORKS = tuple(
    ipaddress.ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_SECRET_VALUE_RE = re.compile(
    r"(?:"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"Bearer\s+\S+|"
    r"AKIA[0-9A-Z]{16}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"(?:access[_-]?token|refresh[_-]?token|password|passwd|secret|app[_-]?key)"
    r"\s*[:=]\s*\S+"
    r")",
    re.IGNORECASE,
)
_FORBIDDEN_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "passwd",
    "privatekey",
    "refreshtoken",
    "secret",
    "sessiontoken",
    "token",
    "accesstoken",
    "apptoken",
    "appkey",
)
_TRACK_CHECKS: dict[str, tuple[str, ...]] = {
    "dji_cloud": (
        "workspace_opened_in_pilot2",
        "wayline_visible_without_file_operation",
        "operator_reviewed_execution_surface",
        "media_upload_started_without_file_operation",
        "work_order_mission_media_lineage_verified",
    ),
    "psdk_manifold": (
        "manifold_and_aircraft_link_verified",
        "camera_media_list_read",
        "one_original_jpeg_downloaded_and_hashed",
        "object_upload_and_lineage_verified",
        "downloader_rights_released",
    ),
}
_CHECK_EVIDENCE_STAGES: dict[str, dict[str, tuple[str, ...]]] = {
    "dji_cloud": {
        "workspace_opened_in_pilot2": ("10_cloud_pilot",),
        "wayline_visible_without_file_operation": ("10_cloud_pilot",),
        "operator_reviewed_execution_surface": ("10_cloud_pilot",),
        "media_upload_started_without_file_operation": ("10_cloud_pilot",),
        "work_order_mission_media_lineage_verified": ("12_gateway_lineage",),
    },
    "psdk_manifold": {
        "manifold_and_aircraft_link_verified": ("09_mvp_provider_preflight",),
        "camera_media_list_read": ("11_psdk_camera_media",),
        "one_original_jpeg_downloaded_and_hashed": ("11_psdk_camera_media",),
        "object_upload_and_lineage_verified": ("12_gateway_lineage",),
        "downloader_rights_released": ("11_psdk_camera_media",),
    },
}
_REQUIRED_PASS_ASSERTIONS: dict[str, dict[str, Mapping[str, Any]]] = {
    "dji_cloud": {
        "workspace_opened_in_pilot2": {
            "workspace_opened": True,
            "authenticated_session_present": True,
            "sensitive_value_recorded": False,
        },
        "wayline_visible_without_file_operation": {
            "wayline_visible": True,
            "file_operation_used": False,
            "provider_operation_recorded": True,
        },
        "operator_reviewed_execution_surface": {
            "operator_review_completed": True,
            "execution_started": False,
            "safety_state_visible": True,
        },
        "media_upload_started_without_file_operation": {
            "field_capture_was_separately_approved": True,
            "media_upload_started": True,
            "file_operation_used": False,
        },
        "work_order_mission_media_lineage_verified": {
            "object_upload_succeeded": True,
            "source_digest_matched": True,
            "work_order_mission_media_lineage_matched": True,
            "egress_policy_satisfied": True,
        },
    },
    "psdk_manifold": {
        "manifold_and_aircraft_link_verified": {
            "manifold_identity_verified": True,
            "app_framework_running": True,
            "aircraft_link_connected": True,
            "aircraft_sn_matched": True,
        },
        "camera_media_list_read": {
            "download_file_list_returned_success": True,
            "media_count_at_least_one": True,
            "delete_or_format_called": False,
        },
        "one_original_jpeg_downloaded_and_hashed": {
            "download_by_index_returned_success": True,
            "original_jpeg": True,
            "downloaded_bytes_positive": True,
            "sha256_verified": True,
            "delete_or_format_called": False,
        },
        "object_upload_and_lineage_verified": {
            "object_upload_succeeded": True,
            "source_digest_matched": True,
            "work_order_mission_media_lineage_matched": True,
            "egress_policy_satisfied": True,
        },
        "downloader_rights_released": {
            "downloader_rights_obtained": True,
            "downloader_rights_released": True,
            "pilot2_album_access_restored": True,
        },
    },
}
_SESSION_DIRS = (
    "09_mvp_provider_preflight",
    "10_cloud_pilot",
    "11_psdk_camera_media",
    "12_gateway_lineage",
    "13_provider_decision",
)
_ALLOWED_STATUSES = {"NOT_VERIFIED", "BLOCKED", "READY_FOR_DECISION", "VERIFIED"}
_TRACK_FIELDS = {"status", "checks", "blocker_code", "blocker_evidence_refs"}
_CHECK_FIELDS = {"passed", "evidence_refs"}
_MANIFEST_FIELDS_V11 = {
    "schema_version",
    "session_id",
    "operator",
    "aircraft_sn",
    "build_commit",
    "started_at_utc",
    "ended_at_utc",
    "purpose",
    "steps_completed",
    "tracks",
    "selected_path",
    "selection_reason",
}
_MANIFEST_FIELDS_V12 = _MANIFEST_FIELDS_V11 | {"selection_evidence_ref"}


class IntegrationManifestError(ValueError):
    """The structured HIL summary is unsafe or cannot support its verdict."""


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise IntegrationManifestError("started_at은 UTC tz-aware datetime이어야 한다")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _reject_secret_fields(value: Any, *, path: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise IntegrationManifestError(f"{path}의 key는 문자열이어야 한다")
            normalised = _normalise_key(key)
            if any(part in normalised for part in _FORBIDDEN_KEY_PARTS):
                raise IntegrationManifestError(
                    f"{path}.{key}는 secret-like 필드라 HIL summary에 기록할 수 없다"
                )
            _reject_secret_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, path=f"{path}[{index}]")
    elif isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise IntegrationManifestError(f"{path}에 secret-like 문자열을 기록할 수 없다")


def _parse_utc_timestamp(value: Any, *, field: str, allow_none: bool) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise IntegrationManifestError(f"{field}는 UTC ISO-8601 초 단위 문자열이어야 한다")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise IntegrationManifestError(f"{field}가 유효한 UTC 시각이 아니다") from exc


def _validate_evidence_ref(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrationManifestError(f"{field}는 비공백 상대 경로여야 한다")
    if "?" in value or "#" in value or "\\" in value:
        raise IntegrationManifestError(f"{field}에는 query, fragment, backslash를 넣을 수 없다")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise IntegrationManifestError(f"{field}는 세션 내부 상대 경로여야 한다")
    if not path.parts or path.parts[0] not in _SESSION_DIRS:
        raise IntegrationManifestError(
            f"{field}는 정의된 Milestone 1 증거 디렉터리를 가리켜야 한다"
        )
    return value


def _validate_evidence_exists(value: str, *, evidence_root: Path, field: str) -> None:
    root = evidence_root.resolve()
    candidate = evidence_root / value
    current = candidate
    while current != evidence_root:
        if current.is_symlink():
            raise IntegrationManifestError(f"{field}는 symlink를 가리킬 수 없다")
        current = current.parent
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise IntegrationManifestError(f"{field}가 evidence session 밖을 가리킨다") from exc
    if not candidate.exists():
        raise IntegrationManifestError(f"{field}가 실제 evidence를 가리키지 않는다")
    try:
        candidate_stat = candidate.stat()
    except OSError as exc:
        raise IntegrationManifestError(f"{field} evidence 속성을 확인할 수 없다: {exc}") from exc
    if not stat.S_ISREG(candidate_stat.st_mode):
        raise IntegrationManifestError(f"{field}는 일반 evidence 파일을 가리켜야 한다")
    if candidate_stat.st_uid != os.geteuid() or candidate_stat.st_mode & 0o077:
        raise IntegrationManifestError(
            f"{field} evidence는 현재 사용자 소유의 0600 이하 파일이어야 한다"
        )


def build_manifest(
    *,
    operator: str,
    aircraft_sn: str,
    build_commit: str,
    started_at: datetime,
) -> dict[str, Any]:
    if not operator.strip():
        raise IntegrationManifestError("operator는 비공백이어야 한다")
    if _AIRCRAFT_SN_RE.fullmatch(aircraft_sn) is None:
        raise IntegrationManifestError("aircraft_sn은 영숫자/하이픈 또는 PENDING-SN이어야 한다")
    if _COMMIT_RE.fullmatch(build_commit) is None:
        raise IntegrationManifestError("build_commit은 40자 lowercase git SHA여야 한다")
    started_at_text = _utc_text(started_at)
    compact = started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    session_id = f"SESS-{compact}-{aircraft_sn}"
    return {
        "schema_version": "1.2",
        "session_id": session_id,
        "operator": operator.strip(),
        "aircraft_sn": aircraft_sn,
        "build_commit": build_commit,
        "started_at_utc": started_at_text,
        "ended_at_utc": None,
        "purpose": "KSI MVP Integration Milestone 1 provider acceptance",
        "steps_completed": [],
        "tracks": {
            track: {
                "status": ("BLOCKED" if track == "dji_cloud" else "NOT_VERIFIED"),
                "checks": {check: {"passed": False, "evidence_refs": []} for check in checks},
                "blocker_code": (
                    "UNSUPPORTED_COMBINATION_IN_OFFICIAL_MATRIX" if track == "dji_cloud" else None
                ),
                "blocker_evidence_refs": (
                    ["10_cloud_pilot/provider_support_matrix.json"] if track == "dji_cloud" else []
                ),
            }
            for track, checks in _TRACK_CHECKS.items()
        },
        "selected_path": None,
        "selection_reason": None,
        "selection_evidence_ref": None,
    }


def validate_manifest(manifest: Mapping[str, Any], *, evidence_root: Path | None = None) -> None:
    _reject_secret_fields(manifest)
    schema_version = manifest.get("schema_version")
    expected_fields = _MANIFEST_FIELDS_V11 if schema_version == "1.1" else _MANIFEST_FIELDS_V12
    if schema_version not in {"1.1", "1.2"}:
        raise IntegrationManifestError("schema_version은 1.1 또는 1.2여야 한다")
    if set(manifest) != expected_fields:
        raise IntegrationManifestError("manifest 필드가 Milestone 1 schema와 다르다")
    started_at = _parse_utc_timestamp(
        manifest.get("started_at_utc"), field="started_at_utc", allow_none=False
    )
    ended_at = _parse_utc_timestamp(
        manifest.get("ended_at_utc"), field="ended_at_utc", allow_none=True
    )
    if ended_at is not None and started_at is not None and ended_at < started_at:
        raise IntegrationManifestError("ended_at_utc는 started_at_utc보다 이를 수 없다")
    session_id = manifest.get("session_id")
    if not isinstance(session_id, str) or _SESSION_ID_RE.fullmatch(session_id) is None:
        raise IntegrationManifestError("session_id 형식이 RAW_LOG_CONVENTIONS와 다르다")
    build_commit = manifest.get("build_commit")
    if not isinstance(build_commit, str) or _COMMIT_RE.fullmatch(build_commit) is None:
        raise IntegrationManifestError("build_commit이 유효한 40자 lowercase git SHA가 아니다")
    operator = manifest.get("operator")
    if not isinstance(operator, str) or not operator.strip():
        raise IntegrationManifestError("operator는 비공백 문자열이어야 한다")
    aircraft_sn = manifest.get("aircraft_sn")
    if not isinstance(aircraft_sn, str) or _AIRCRAFT_SN_RE.fullmatch(aircraft_sn) is None:
        raise IntegrationManifestError("aircraft_sn 형식이 유효하지 않다")
    if manifest.get("purpose") != "KSI MVP Integration Milestone 1 provider acceptance":
        raise IntegrationManifestError("purpose가 Milestone 1 acceptance와 다르다")
    steps = manifest.get("steps_completed")
    if not isinstance(steps, list) or any(not isinstance(step, str) for step in steps):
        raise IntegrationManifestError("steps_completed는 문자열 배열이어야 한다")
    tracks = manifest.get("tracks")
    if not isinstance(tracks, Mapping) or set(tracks) != set(_TRACK_CHECKS):
        raise IntegrationManifestError("tracks는 dji_cloud와 psdk_manifold만 가져야 한다")

    for track_name, required_checks in _TRACK_CHECKS.items():
        track = tracks[track_name]
        if not isinstance(track, Mapping):
            raise IntegrationManifestError(f"tracks.{track_name}는 object여야 한다")
        if set(track) != _TRACK_FIELDS:
            raise IntegrationManifestError(f"tracks.{track_name} 필드가 schema와 다르다")
        status = track.get("status")
        if status not in _ALLOWED_STATUSES:
            raise IntegrationManifestError(f"tracks.{track_name}.status가 유효하지 않다")
        checks = track.get("checks")
        if not isinstance(checks, Mapping) or set(checks) != set(required_checks):
            raise IntegrationManifestError(
                f"tracks.{track_name}.checks가 acceptance profile과 다르다"
            )
        passed_checks: list[bool] = []
        passed_ref_owners: dict[str, str] = {}
        for check_name, check in checks.items():
            field = f"tracks.{track_name}.checks.{check_name}"
            if not isinstance(check, Mapping) or set(check) != _CHECK_FIELDS:
                raise IntegrationManifestError(f"{field} 필드가 check evidence schema와 다르다")
            passed = check.get("passed")
            if not isinstance(passed, bool):
                raise IntegrationManifestError(f"{field}.passed는 boolean이어야 한다")
            refs = check.get("evidence_refs")
            if not isinstance(refs, list):
                raise IntegrationManifestError(f"{field}.evidence_refs는 배열이어야 한다")
            if passed and not refs:
                raise IntegrationManifestError(f"{field}는 evidence_ref 없이 passed일 수 없다")
            for index, ref in enumerate(refs):
                ref_field = f"{field}.evidence_refs[{index}]"
                validated_ref = _validate_evidence_ref(ref, field=ref_field)
                if (
                    PurePosixPath(validated_ref).parts[0]
                    not in _CHECK_EVIDENCE_STAGES[track_name][check_name]
                ):
                    allowed = ", ".join(_CHECK_EVIDENCE_STAGES[track_name][check_name])
                    raise IntegrationManifestError(
                        f"{ref_field}는 {check_name}의 evidence stage({allowed})에 있어야 한다"
                    )
                if evidence_root is not None:
                    _validate_evidence_exists(
                        validated_ref,
                        evidence_root=evidence_root,
                        field=ref_field,
                    )
                    if passed and schema_version == "1.2":
                        _validate_pass_evidence_payload(
                            manifest,
                            track_name=track_name,
                            check_name=check_name,
                            evidence_ref=validated_ref,
                            evidence_root=evidence_root,
                        )
                if passed:
                    previous_owner = passed_ref_owners.get(validated_ref)
                    if previous_owner is not None:
                        raise IntegrationManifestError(
                            f"tracks.{track_name}의 passed check {previous_owner}와 "
                            f"{check_name}가 같은 evidence를 재사용할 수 없다"
                        )
                    passed_ref_owners[validated_ref] = check_name
            passed_checks.append(passed)
        blocker_code = track.get("blocker_code")
        if blocker_code is not None and (
            not isinstance(blocker_code, str) or not blocker_code.strip()
        ):
            raise IntegrationManifestError(f"tracks.{track_name}.blocker_code가 유효하지 않다")
        blocker_refs = track.get("blocker_evidence_refs")
        if not isinstance(blocker_refs, list):
            raise IntegrationManifestError(
                f"tracks.{track_name}.blocker_evidence_refs는 배열이어야 한다"
            )
        for index, ref in enumerate(blocker_refs):
            ref_field = f"tracks.{track_name}.blocker_evidence_refs[{index}]"
            validated_ref = _validate_evidence_ref(ref, field=ref_field)
            if evidence_root is not None:
                _validate_evidence_exists(
                    validated_ref,
                    evidence_root=evidence_root,
                    field=ref_field,
                )
        if status == "VERIFIED" and not all(passed_checks):
            raise IntegrationManifestError(
                f"tracks.{track_name}는 모든 check의 개별 evidence 없이 VERIFIED일 수 없다"
            )
        if status == "VERIFIED" and (ended_at is None or aircraft_sn == "PENDING-SN"):
            raise IntegrationManifestError(
                f"tracks.{track_name}는 종료시각과 실제 aircraft_sn 없이 VERIFIED일 수 없다"
            )
        if status == "READY_FOR_DECISION" and not all(passed_checks):
            raise IntegrationManifestError(
                f"tracks.{track_name}는 모든 check가 passed여야 READY_FOR_DECISION일 수 있다"
            )
        if status == "READY_FOR_DECISION" and aircraft_sn == "PENDING-SN":
            raise IntegrationManifestError(
                f"tracks.{track_name}는 실제 aircraft_sn 없이 READY_FOR_DECISION일 수 없다"
            )
        if status == "BLOCKED" and (blocker_code is None or not blocker_refs):
            raise IntegrationManifestError(
                f"tracks.{track_name} BLOCKED에는 blocker_code와 blocker evidence가 필요하다"
            )
        if status == "BLOCKED" and all(passed_checks):
            raise IntegrationManifestError(
                f"tracks.{track_name}는 모든 check가 passed인데 BLOCKED일 수 없다"
            )
        if status != "BLOCKED" and (blocker_code is not None or blocker_refs):
            raise IntegrationManifestError(
                f"tracks.{track_name} blocker 정보는 BLOCKED 상태에서만 허용된다"
            )
        if status == "NOT_VERIFIED" and all(passed_checks):
            raise IntegrationManifestError(
                f"tracks.{track_name}는 모든 check가 passed이면 VERIFIED로 판정해야 한다"
            )

    selected = manifest.get("selected_path")
    reason = manifest.get("selection_reason")
    selection_evidence = manifest.get("selection_evidence_ref") if schema_version == "1.2" else None
    if selected is None:
        if reason is not None:
            raise IntegrationManifestError("selected_path 없이 selection_reason을 둘 수 없다")
        if selection_evidence is not None:
            raise IntegrationManifestError("selected_path 없이 selection_evidence_ref를 둘 수 없다")
        return
    if schema_version == "1.1":
        raise IntegrationManifestError(
            "selected legacy v1.1 manifest는 digest decision evidence가 없어 허용되지 않는다"
        )
    if selected not in _TRACK_CHECKS:
        raise IntegrationManifestError("selected_path는 dji_cloud 또는 psdk_manifold여야 한다")
    if tracks[selected]["status"] != "VERIFIED":
        raise IntegrationManifestError("VERIFIED가 아닌 provider를 selected_path로 채택할 수 없다")
    if selected == "psdk_manifold" and tracks["dji_cloud"]["status"] != "BLOCKED":
        raise IntegrationManifestError(
            "PSDK를 기본 provider로 채택하려면 Cloud track이 BLOCKED여야 한다"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise IntegrationManifestError("provider 채택에는 비공백 selection_reason이 필요하다")
    if schema_version == "1.2":
        validated_selection_ref = _validate_evidence_ref(
            selection_evidence,
            field="selection_evidence_ref",
        )
        if PurePosixPath(validated_selection_ref).parts[0] != "13_provider_decision":
            raise IntegrationManifestError(
                "selection_evidence_ref는 13_provider_decision을 가리켜야 한다"
            )
        if evidence_root is not None:
            _validate_evidence_exists(
                validated_selection_ref,
                evidence_root=evidence_root,
                field="selection_evidence_ref",
            )
            _validate_selection_decision(
                manifest,
                evidence_root=evidence_root,
                selection_evidence_ref=validated_selection_ref,
            )


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _replace_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.tmp.{os.getpid()}"
    _write_private_json(temporary, payload)
    try:
        os.replace(temporary, path)
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def _session_lock(manifest_path: Path) -> Iterator[None]:
    lock_path = manifest_path.parent / ".integration_manifest.lock"
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        lock_stat = os.fstat(descriptor)
        if lock_stat.st_uid != os.geteuid() or lock_stat.st_mode & 0o077:
            raise IntegrationManifestError(
                "integration manifest lock은 현재 사용자 소유의 0600 파일이어야 한다"
            )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _require_schema_v12(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != "1.2":
        raise IntegrationManifestError(
            "이 명령은 schema v1.2 session이 필요하다; 먼저 upgrade를 실행한다"
        )


def _session_summary_payload(manifest_path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    summary_path = manifest_path.parent / "session_manifest.json"
    if summary_path.is_symlink():
        raise IntegrationManifestError("session_manifest.json은 symlink일 수 없다")
    try:
        summary_stat = summary_path.stat()
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrationManifestError(f"session_manifest.json을 읽을 수 없다: {exc}") from exc
    if (
        not stat.S_ISREG(summary_stat.st_mode)
        or summary_stat.st_uid != os.geteuid()
        or summary_stat.st_mode & 0o077
    ):
        raise IntegrationManifestError(
            "session_manifest.json은 현재 사용자 소유의 0600 일반 파일이어야 한다"
        )
    if not isinstance(payload, dict) or set(payload) != {
        "session_id",
        "operator",
        "aircraft_sn",
        "build_commit",
        "started_at_utc",
        "ended_at_utc",
        "purpose",
        "steps_completed",
        "notes",
    }:
        raise IntegrationManifestError("session_manifest.json 필드가 raw-log 규약과 다르다")
    for key in (
        "session_id",
        "operator",
        "aircraft_sn",
        "build_commit",
        "started_at_utc",
        "ended_at_utc",
        "purpose",
        "steps_completed",
    ):
        payload[key] = manifest[key]
    _reject_secret_fields(payload, path="session_manifest")
    return payload


def _commit_manifest(manifest_path: Path, manifest: Mapping[str, Any]) -> None:
    validate_manifest(manifest, evidence_root=manifest_path.parent)
    summary = _session_summary_payload(manifest_path, manifest)
    _replace_private_json(manifest_path, manifest)
    _replace_private_json(manifest_path.parent / "session_manifest.json", summary)


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    file_stat = os.fstat(descriptor)
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.geteuid()
        or file_stat.st_mode & 0o077
    ):
        os.close(descriptor)
        raise IntegrationManifestError(
            "digest 대상 evidence는 현재 사용자 소유의 0600 일반 파일이어야 한다"
        )
    with os.fdopen(descriptor, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _read_private_json(path: Path, *, label: str, max_bytes: int = 1024 * 1024) -> Any:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_uid != os.geteuid()
            or file_stat.st_mode & 0o077
        ):
            raise IntegrationManifestError(
                f"{label}는 현재 사용자 소유의 0600 일반 파일이어야 한다"
            )
        if file_stat.st_size > max_bytes:
            raise IntegrationManifestError(f"{label}는 {max_bytes} bytes를 초과할 수 없다")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrationManifestError(f"{label}를 읽을 수 없다: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_pass_evidence_payload(
    manifest: Mapping[str, Any],
    *,
    track_name: str,
    check_name: str,
    evidence_ref: str,
    evidence_root: Path,
) -> None:
    if PurePosixPath(evidence_ref).suffix != ".json":
        raise IntegrationManifestError("passed check evidence envelope는 JSON이어야 한다")
    payload = _read_private_json(
        evidence_root / evidence_ref,
        label=f"{track_name}.{check_name} evidence envelope",
    )
    expected_fields = {
        "schema_version",
        "session_id",
        "aircraft_sn",
        "captured_at_utc",
        "track",
        "check",
        "verdict",
        "operator_attested",
        "assertions",
        "raw_evidence",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields:
        raise IntegrationManifestError(
            f"{track_name}.{check_name} evidence envelope schema가 다르다"
        )
    _reject_secret_fields(payload, path=f"evidence.{track_name}.{check_name}")
    expected_metadata = {
        "schema_version": "1.0",
        "session_id": manifest["session_id"],
        "aircraft_sn": manifest["aircraft_sn"],
        "track": track_name,
        "check": check_name,
        "verdict": "PASS",
        "operator_attested": True,
    }
    for key, expected in expected_metadata.items():
        if payload.get(key) != expected:
            raise IntegrationManifestError(
                f"{track_name}.{check_name} evidence envelope의 {key}가 기대값과 다르다"
            )
    captured_at = _parse_utc_timestamp(
        payload.get("captured_at_utc"),
        field=f"evidence.{track_name}.{check_name}.captured_at_utc",
        allow_none=False,
    )
    started_at = _parse_utc_timestamp(
        manifest.get("started_at_utc"),
        field="started_at_utc",
        allow_none=False,
    )
    if captured_at is None or started_at is None or captured_at < started_at:
        raise IntegrationManifestError(
            f"{track_name}.{check_name} evidence가 session 시작보다 이를 수 없다"
        )
    if captured_at > datetime.now(UTC) + timedelta(minutes=5):
        raise IntegrationManifestError(
            f"{track_name}.{check_name} evidence가 현재 시각보다 5분 넘게 미래다"
        )
    if payload.get("assertions") != _REQUIRED_PASS_ASSERTIONS[track_name][check_name]:
        raise IntegrationManifestError(
            f"{track_name}.{check_name} evidence envelope의 필수 assertion이 다르다"
        )
    raw_evidence = payload.get("raw_evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise IntegrationManifestError(
            f"{track_name}.{check_name} evidence envelope에는 raw_evidence가 필요하다"
        )
    seen_refs: set[str] = set()
    for index, item in enumerate(raw_evidence):
        field = f"evidence.{track_name}.{check_name}.raw_evidence[{index}]"
        if not isinstance(item, Mapping) or set(item) != {"ref", "sha256", "size_bytes"}:
            raise IntegrationManifestError(f"{field} schema가 다르다")
        raw_ref = _validate_evidence_ref(item.get("ref"), field=f"{field}.ref")
        if raw_ref == evidence_ref or raw_ref in seen_refs:
            raise IntegrationManifestError(f"{field}.ref는 self-reference/중복일 수 없다")
        seen_refs.add(raw_ref)
        if PurePosixPath(raw_ref).parts[0] not in _CHECK_EVIDENCE_STAGES[track_name][check_name]:
            raise IntegrationManifestError(f"{field}.ref가 선택 check의 stage와 다르다")
        _validate_evidence_exists(raw_ref, evidence_root=evidence_root, field=f"{field}.ref")
        digest, size = _sha256_file(evidence_root / raw_ref)
        if item.get("sha256") != digest or item.get("size_bytes") != size:
            raise IntegrationManifestError(f"{field} digest/size가 raw evidence와 다르다")


def _validate_selection_decision(
    manifest: Mapping[str, Any],
    *,
    evidence_root: Path,
    selection_evidence_ref: str,
) -> None:
    decision_path = evidence_root / selection_evidence_ref
    decision = _read_private_json(decision_path, label="provider decision evidence")
    expected_fields = {
        "schema_version",
        "session_id",
        "aircraft_sn",
        "build_commit",
        "selected_at_utc",
        "selected_provider",
        "selection_reason",
        "check_evidence",
    }
    if not isinstance(decision, Mapping) or set(decision) != expected_fields:
        raise IntegrationManifestError("provider decision evidence schema가 다르다")
    _reject_secret_fields(decision, path="provider_decision")
    expected_metadata = {
        "schema_version": "1.0",
        "session_id": manifest["session_id"],
        "aircraft_sn": manifest["aircraft_sn"],
        "build_commit": manifest["build_commit"],
        "selected_at_utc": manifest["ended_at_utc"],
        "selected_provider": manifest["selected_path"],
        "selection_reason": manifest["selection_reason"],
    }
    for key, expected in expected_metadata.items():
        if decision.get(key) != expected:
            raise IntegrationManifestError(
                f"provider decision evidence의 {key}가 manifest와 다르다"
            )
    selected_track = manifest["tracks"][manifest["selected_path"]]
    expected_evidence: list[dict[str, Any]] = []
    for check_name, check in selected_track["checks"].items():
        for evidence_ref in check["evidence_refs"]:
            digest, size = _sha256_file(evidence_root / evidence_ref)
            expected_evidence.append(
                {
                    "check": check_name,
                    "evidence_ref": evidence_ref,
                    "sha256": digest,
                    "size_bytes": size,
                }
            )
    if decision.get("check_evidence") != expected_evidence:
        raise IntegrationManifestError(
            "provider decision evidence의 check digest/size가 현재 evidence와 다르다"
        )


def upgrade_manifest(manifest_path: Path) -> dict[str, Any]:
    load_and_validate(manifest_path)
    with _session_lock(manifest_path):
        manifest = load_and_validate(manifest_path)
        if manifest["schema_version"] == "1.2":
            return manifest
        if manifest["selected_path"] is not None:
            raise IntegrationManifestError(
                "이미 채택된 legacy v1.1 session은 decision evidence 없이 자동 upgrade할 수 없다"
            )
        manifest["schema_version"] = "1.2"
        manifest["selection_evidence_ref"] = None
        _commit_manifest(manifest_path, manifest)
        return manifest


def record_check(
    manifest_path: Path,
    *,
    track_name: str,
    check_name: str,
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    if not evidence_refs:
        raise IntegrationManifestError("record-check에는 하나 이상의 --evidence가 필요하다")
    if len(set(evidence_refs)) != len(evidence_refs):
        raise IntegrationManifestError("record-check --evidence는 중복될 수 없다")
    load_and_validate(manifest_path)
    with _session_lock(manifest_path):
        manifest = load_and_validate(manifest_path)
        _require_schema_v12(manifest)
        if manifest["selected_path"] is not None:
            raise IntegrationManifestError("채택된 session의 check를 변경할 수 없다")
        if track_name not in _TRACK_CHECKS:
            raise IntegrationManifestError("--track이 acceptance profile에 없다")
        if check_name not in _TRACK_CHECKS[track_name]:
            raise IntegrationManifestError("--check가 선택 track의 acceptance profile에 없다")
        track = manifest["tracks"][track_name]
        if track["status"] in {"BLOCKED", "VERIFIED"}:
            raise IntegrationManifestError("BLOCKED/VERIFIED track에는 check PASS를 기록할 수 없다")
        validated_refs: list[str] = []
        for index, evidence_ref in enumerate(evidence_refs):
            validated = _validate_evidence_ref(
                evidence_ref,
                field=f"record-check.evidence[{index}]",
            )
            if (
                PurePosixPath(validated).parts[0]
                not in _CHECK_EVIDENCE_STAGES[track_name][check_name]
            ):
                raise IntegrationManifestError(
                    "record-check evidence가 선택 check의 stage와 다르다"
                )
            _validate_evidence_exists(
                validated,
                evidence_root=manifest_path.parent,
                field=f"record-check.evidence[{index}]",
            )
            _validate_pass_evidence_payload(
                manifest,
                track_name=track_name,
                check_name=check_name,
                evidence_ref=validated,
                evidence_root=manifest_path.parent,
            )
            validated_refs.append(validated)
        check = track["checks"][check_name]
        was_passed = check["passed"]
        check["passed"] = True
        check["evidence_refs"] = (
            list(dict.fromkeys([*check["evidence_refs"], *validated_refs]))
            if was_passed
            else validated_refs
        )
        all_passed = all(item["passed"] for item in track["checks"].values())
        if all_passed and manifest["aircraft_sn"] == "PENDING-SN":
            raise IntegrationManifestError(
                "마지막 check 전에 실제 aircraft_sn으로 새 acceptance session을 시작해야 한다"
            )
        track["status"] = "READY_FOR_DECISION" if all_passed else "NOT_VERIFIED"
        step = f"check:{track_name}:{check_name}"
        if step not in manifest["steps_completed"]:
            manifest["steps_completed"].append(step)
        _commit_manifest(manifest_path, manifest)
        return manifest


def attest_check(
    manifest_path: Path,
    *,
    track_name: str,
    check_name: str,
    raw_evidence_refs: Sequence[str],
    operator_attested: bool,
) -> Path:
    if not operator_attested:
        raise IntegrationManifestError("attest-check에는 --attest-required-assertions가 필요하다")
    if not raw_evidence_refs or len(set(raw_evidence_refs)) != len(raw_evidence_refs):
        raise IntegrationManifestError(
            "attest-check에는 하나 이상의 중복 없는 --raw-evidence가 필요하다"
        )
    manifest = load_and_validate(manifest_path)
    _require_schema_v12(manifest)
    if manifest["selected_path"] is not None:
        raise IntegrationManifestError("채택된 session에 check attestation을 추가할 수 없다")
    if track_name not in _TRACK_CHECKS or check_name not in _TRACK_CHECKS[track_name]:
        raise IntegrationManifestError("--track/--check가 acceptance profile에 없다")
    if manifest["tracks"][track_name]["status"] in {"BLOCKED", "VERIFIED"}:
        raise IntegrationManifestError("BLOCKED/VERIFIED track에는 attestation을 기록할 수 없다")
    raw_evidence: list[dict[str, Any]] = []
    for index, raw_ref_value in enumerate(raw_evidence_refs):
        field = f"attest-check.raw-evidence[{index}]"
        raw_ref = _validate_evidence_ref(raw_ref_value, field=field)
        if PurePosixPath(raw_ref).parts[0] not in _CHECK_EVIDENCE_STAGES[track_name][check_name]:
            raise IntegrationManifestError(f"{field}가 선택 check의 stage와 다르다")
        _validate_evidence_exists(raw_ref, evidence_root=manifest_path.parent, field=field)
        digest, size = _sha256_file(manifest_path.parent / raw_ref)
        raw_evidence.append({"ref": raw_ref, "sha256": digest, "size_bytes": size})
    captured_at = datetime.now(UTC).replace(microsecond=0)
    timestamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    stage = _CHECK_EVIDENCE_STAGES[track_name][check_name][0]
    relative_ref = f"{stage}/{timestamp}__{check_name}_evidence.json"
    evidence_path = manifest_path.parent / relative_ref
    payload = {
        "schema_version": "1.0",
        "session_id": manifest["session_id"],
        "aircraft_sn": manifest["aircraft_sn"],
        "captured_at_utc": _utc_text(captured_at),
        "track": track_name,
        "check": check_name,
        "verdict": "PASS",
        "operator_attested": True,
        "assertions": _REQUIRED_PASS_ASSERTIONS[track_name][check_name],
        "raw_evidence": raw_evidence,
    }
    _reject_secret_fields(payload, path="attest-check")
    _write_private_json(evidence_path, payload)
    record_check(
        manifest_path,
        track_name=track_name,
        check_name=check_name,
        evidence_refs=[relative_ref],
    )
    return evidence_path


def record_blocker(
    manifest_path: Path,
    *,
    track_name: str,
    check_name: str,
    blocker_code: str,
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    if _BLOCKER_CODE_RE.fullmatch(blocker_code) is None:
        raise IntegrationManifestError("--code는 uppercase snake-case blocker code여야 한다")
    if not evidence_refs:
        raise IntegrationManifestError("record-blocker에는 하나 이상의 --evidence가 필요하다")
    if len(set(evidence_refs)) != len(evidence_refs):
        raise IntegrationManifestError("record-blocker --evidence는 중복될 수 없다")
    load_and_validate(manifest_path)
    with _session_lock(manifest_path):
        manifest = load_and_validate(manifest_path)
        _require_schema_v12(manifest)
        if manifest["selected_path"] is not None:
            raise IntegrationManifestError("채택된 session에 blocker를 기록할 수 없다")
        if track_name not in _TRACK_CHECKS or check_name not in _TRACK_CHECKS[track_name]:
            raise IntegrationManifestError("--track/--check가 acceptance profile에 없다")
        track = manifest["tracks"][track_name]
        if track["status"] == "VERIFIED":
            raise IntegrationManifestError("VERIFIED track에 blocker를 기록할 수 없다")
        validated_refs: list[str] = []
        for index, evidence_ref in enumerate(evidence_refs):
            validated = _validate_evidence_ref(
                evidence_ref,
                field=f"record-blocker.evidence[{index}]",
            )
            if (
                PurePosixPath(validated).parts[0]
                not in _CHECK_EVIDENCE_STAGES[track_name][check_name]
            ):
                raise IntegrationManifestError(
                    "record-blocker evidence가 선택 check의 stage와 다르다"
                )
            _validate_evidence_exists(
                validated,
                evidence_root=manifest_path.parent,
                field=f"record-blocker.evidence[{index}]",
            )
            validated_refs.append(validated)
        check = track["checks"][check_name]
        check["passed"] = False
        check["evidence_refs"] = list(dict.fromkeys([*check["evidence_refs"], *validated_refs]))
        track["status"] = "BLOCKED"
        track["blocker_code"] = blocker_code
        track["blocker_evidence_refs"] = validated_refs
        step = f"blocker:{track_name}:{check_name}"
        if step not in manifest["steps_completed"]:
            manifest["steps_completed"].append(step)
        _commit_manifest(manifest_path, manifest)
        return manifest


def select_provider(
    manifest_path: Path,
    *,
    track_name: str,
    reason: str,
) -> Path:
    if not reason.strip():
        raise IntegrationManifestError("--reason은 비공백이어야 한다")
    _reject_secret_fields({"reason": reason}, path="provider_decision")
    load_and_validate(manifest_path)
    with _session_lock(manifest_path):
        manifest = load_and_validate(manifest_path)
        _require_schema_v12(manifest)
        if manifest["selected_path"] is not None:
            raise IntegrationManifestError("provider가 이미 채택된 session이다")
        if track_name not in _TRACK_CHECKS:
            raise IntegrationManifestError("--track이 acceptance profile에 없다")
        track = manifest["tracks"][track_name]
        if track["status"] != "READY_FOR_DECISION":
            raise IntegrationManifestError("provider 채택에는 READY_FOR_DECISION track이 필요하다")
        if track_name == "psdk_manifold" and manifest["tracks"]["dji_cloud"]["status"] != "BLOCKED":
            raise IntegrationManifestError("PSDK 채택에는 Cloud track BLOCKED evidence가 필요하다")

        selected_at = datetime.now(UTC).replace(microsecond=0)
        timestamp = selected_at.strftime("%Y%m%dT%H%M%SZ")
        relative_ref = f"13_provider_decision/{timestamp}__provider_decision.json"
        decision_path = manifest_path.parent / relative_ref
        check_evidence: list[dict[str, Any]] = []
        for check_name, check in track["checks"].items():
            for evidence_ref in check["evidence_refs"]:
                evidence_path = manifest_path.parent / evidence_ref
                digest, size = _sha256_file(evidence_path)
                check_evidence.append(
                    {
                        "check": check_name,
                        "evidence_ref": evidence_ref,
                        "sha256": digest,
                        "size_bytes": size,
                    }
                )
        _write_private_json(
            decision_path,
            {
                "schema_version": "1.0",
                "session_id": manifest["session_id"],
                "aircraft_sn": manifest["aircraft_sn"],
                "build_commit": manifest["build_commit"],
                "selected_at_utc": _utc_text(selected_at),
                "selected_provider": track_name,
                "selection_reason": reason.strip(),
                "check_evidence": check_evidence,
            },
        )
        track["status"] = "VERIFIED"
        manifest["ended_at_utc"] = _utc_text(selected_at)
        manifest["selected_path"] = track_name
        manifest["selection_reason"] = reason.strip()
        manifest["selection_evidence_ref"] = relative_ref
        if "provider_selected" not in manifest["steps_completed"]:
            manifest["steps_completed"].append("provider_selected")
        _commit_manifest(manifest_path, manifest)
        return decision_path


def _run_preflight_command(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "argv": command,
            "return_code": completed.returncode,
            "stdout": completed.stdout[-65536:],
            "stderr": completed.stderr[-65536:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "argv": command,
            "return_code": 124 if isinstance(exc, subprocess.TimeoutExpired) else 127,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }


def capture_host_preflight(manifest_path: Path, *, target: str, interface: str) -> Path:
    manifest = load_and_validate(manifest_path)
    initial_psdk = manifest["tracks"]["psdk_manifold"]
    if manifest["selected_path"] is not None or initial_psdk["status"] in {
        "READY_FOR_DECISION",
        "VERIFIED",
    }:
        raise IntegrationManifestError(
            "preflight는 READY/VERIFIED이거나 provider가 채택된 세션을 변경할 수 없다"
        )
    try:
        target_address = ipaddress.ip_address(target)
    except ValueError as exc:
        raise IntegrationManifestError("--target은 유효한 IP 주소여야 한다") from exc
    if not isinstance(target_address, ipaddress.IPv4Address) or not any(
        target_address in network for network in _PRIVATE_HIL_NETWORKS
    ):
        raise IntegrationManifestError("--target은 RFC1918 private HIL IPv4 주소여야 한다")
    if _INTERFACE_RE.fullmatch(interface) is None:
        raise IntegrationManifestError("--interface 형식이 유효하지 않다")

    commands = {
        "link": ["ip", "-br", "link", "show", "dev", interface],
        "address": ["ip", "-br", "addr", "show", "dev", interface],
        "route": ["ip", "route", "get", target],
        "neighbor": ["ip", "neigh", "show", target],
        "ping": ["ping", "-I", interface, "-c", "3", "-W", "1", target],
        "usb": ["lsusb"],
    }
    results = {name: _run_preflight_command(command) for name, command in commands.items()}
    reachable = results["ping"]["return_code"] == 0
    captured_at = datetime.now(UTC).replace(microsecond=0)
    timestamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    relative_ref = f"09_mvp_provider_preflight/{timestamp}__host_preflight.json"
    evidence_path = manifest_path.parent / relative_ref
    _write_private_json(
        evidence_path,
        {
            "schema_version": "1.0",
            "session_id": manifest["session_id"],
            "captured_at_utc": _utc_text(captured_at),
            "target": target,
            "interface": interface,
            "device_mutations": "none",
            "flight_or_gimbal_commands": "none",
            "manifold_reachable": reachable,
            "aircraft_link": "UNKNOWN",
            "host_usb_is_psdk_blocker": False,
            "verdict": "READY_FOR_REMOTE_PREFLIGHT" if reachable else "MANIFOLD_UNREACHABLE",
            "commands": results,
        },
    )

    with _session_lock(manifest_path):
        manifest = load_and_validate(manifest_path)
        psdk = manifest["tracks"]["psdk_manifold"]
        if manifest["selected_path"] is not None or psdk["status"] in {
            "READY_FOR_DECISION",
            "VERIFIED",
        }:
            raise IntegrationManifestError(
                "preflight evidence는 생성됐지만 READY/VERIFIED/채택 session을 변경하지 않았다"
            )
        link_check = psdk["checks"]["manifold_and_aircraft_link_verified"]
        if relative_ref not in link_check["evidence_refs"]:
            link_check["evidence_refs"].append(relative_ref)
        if not reachable:
            link_check["passed"] = False
        preflight_owns_blocker = (
            psdk["status"] != "BLOCKED" or psdk["blocker_code"] == "MANIFOLD_UNREACHABLE"
        )
        if preflight_owns_blocker:
            if reachable:
                psdk["status"] = "NOT_VERIFIED"
                psdk["blocker_code"] = None
                psdk["blocker_evidence_refs"] = []
            else:
                psdk["status"] = "BLOCKED"
                psdk["blocker_code"] = "MANIFOLD_UNREACHABLE"
                psdk["blocker_evidence_refs"] = [relative_ref]
        if "host_preflight" not in manifest["steps_completed"]:
            manifest["steps_completed"].append("host_preflight")
        _commit_manifest(manifest_path, manifest)
    return evidence_path


def initialise_session(root: Path, manifest: Mapping[str, Any]) -> Path:
    validate_manifest(manifest)
    if root.is_symlink():
        raise IntegrationManifestError("HIL raw root는 symlink일 수 없다")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir() or root.stat().st_uid != os.geteuid():
        raise IntegrationManifestError("HIL raw root는 현재 사용자가 소유한 디렉터리여야 한다")
    root.chmod(0o700)
    session_dir = root / str(manifest["session_id"])
    session_dir.mkdir(mode=0o700, exist_ok=False)
    for directory in _SESSION_DIRS:
        (session_dir / directory).mkdir(mode=0o700)
    _write_private_json(
        session_dir / "10_cloud_pilot" / "provider_support_matrix.json",
        {
            "schema_version": "1.0",
            "decision_recorded_at_utc": manifest["started_at_utc"],
            "source_reviewed_on": "2026-08-20",
            "revalidate_official_source_before_field_use": True,
            "product_combination": "Matrice 4D + DJI RC Plus 2 + DJI Pilot 2",
            "verdict": "BLOCKED",
            "blocker_code": "UNSUPPORTED_COMBINATION_IN_OFFICIAL_MATRIX",
            "observation": (
                "DJI Cloud API product support maps Matrice 4D/4TD to DJI Dock 3; "
                "the RC Plus 2 + Pilot 2 row lists Matrice 4E/4T, not Matrice 4D/4TD."
            ),
            "sources": [
                "https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html",
                "https://developer.dji.com/doc/cloud-api-tutorial/en/",
            ],
        },
    )
    session_manifest = {
        key: manifest[key]
        for key in (
            "session_id",
            "operator",
            "aircraft_sn",
            "build_commit",
            "started_at_utc",
            "ended_at_utc",
            "purpose",
            "steps_completed",
        )
    }
    session_manifest["notes"] = ""
    _write_private_json(session_dir / "session_manifest.json", session_manifest)
    _write_private_json(session_dir / "integration_manifest.json", manifest)
    return session_dir


def load_and_validate(path: Path) -> dict[str, Any]:
    if path.is_symlink() or path.parent.is_symlink():
        raise IntegrationManifestError("manifest와 evidence session root는 symlink일 수 없다")
    try:
        path_stat = path.stat()
        root_stat = path.parent.stat()
    except OSError as exc:
        raise IntegrationManifestError(f"manifest trust boundary를 확인할 수 없다: {exc}") from exc
    if not stat.S_ISREG(path_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise IntegrationManifestError("manifest는 private evidence session의 일반 파일이어야 한다")
    if path_stat.st_uid != os.geteuid() or root_stat.st_uid != os.geteuid():
        raise IntegrationManifestError("manifest와 evidence session은 현재 사용자가 소유해야 한다")
    if path_stat.st_mode & 0o077 or root_stat.st_mode & 0o077:
        raise IntegrationManifestError("manifest는 0600, evidence session은 0700 이하여야 한다")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrationManifestError(f"manifest를 읽을 수 없다: {exc}") from exc
    if not isinstance(payload, dict):
        raise IntegrationManifestError("manifest 최상위는 object여야 한다")
    if path.parent.name != payload.get("session_id"):
        raise IntegrationManifestError("evidence session 디렉터리 이름이 session_id와 다르다")
    validate_manifest(payload, evidence_root=path.parent)
    return payload


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _parse_started_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    if not value.endswith("Z"):
        raise IntegrationManifestError("--started-at은 Z로 끝나는 UTC ISO-8601이어야 한다")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.microsecond:
        raise IntegrationManifestError("--started-at은 초 단위여야 한다")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="secret-free evidence session skeleton 생성")
    init.add_argument("--root", type=Path, default=Path("hil_raw_logs"))
    init.add_argument("--operator", required=True)
    init.add_argument("--aircraft-sn", default="PENDING-SN")
    init.add_argument("--build-commit")
    init.add_argument("--started-at")
    verify = subparsers.add_parser("verify", help="integration_manifest.json fail-closed 검증")
    verify.add_argument("manifest", type=Path)
    preflight = subparsers.add_parser(
        "preflight", help="private session에 read-only host/Manifold 연결 evidence 수집"
    )
    preflight.add_argument("manifest", type=Path)
    preflight.add_argument("--target", required=True)
    preflight.add_argument("--interface", default="enP7s7")
    upgrade = subparsers.add_parser(
        "upgrade", help="미채택 schema v1.1 session을 v1.2로 안전하게 upgrade"
    )
    upgrade.add_argument("manifest", type=Path)
    record = subparsers.add_parser(
        "record-check", help="기존 private evidence를 acceptance check에 연결"
    )
    record.add_argument("manifest", type=Path)
    record.add_argument("--track", required=True, choices=sorted(_TRACK_CHECKS))
    record.add_argument("--check", required=True)
    record.add_argument("--evidence", required=True, action="append")
    attest = subparsers.add_parser(
        "attest-check", help="raw evidence digest와 필수 assertion으로 PASS envelope 생성·기록"
    )
    attest.add_argument("manifest", type=Path)
    attest.add_argument("--track", required=True, choices=sorted(_TRACK_CHECKS))
    attest.add_argument("--check", required=True)
    attest.add_argument("--raw-evidence", required=True, action="append")
    attest.add_argument("--attest-required-assertions", action="store_true")
    blocker = subparsers.add_parser(
        "record-blocker", help="실패 evidence와 blocker를 acceptance track에 기록"
    )
    blocker.add_argument("manifest", type=Path)
    blocker.add_argument("--track", required=True, choices=sorted(_TRACK_CHECKS))
    blocker.add_argument("--check", required=True)
    blocker.add_argument("--code", required=True)
    blocker.add_argument("--evidence", required=True, action="append")
    select = subparsers.add_parser(
        "select-provider", help="READY_FOR_DECISION provider를 digest decision record와 함께 채택"
    )
    select.add_argument("manifest", type=Path)
    select.add_argument("--track", required=True, choices=sorted(_TRACK_CHECKS))
    select.add_argument("--reason", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            manifest = build_manifest(
                operator=args.operator,
                aircraft_sn=args.aircraft_sn,
                build_commit=args.build_commit or _git_commit(),
                started_at=_parse_started_at(args.started_at),
            )
            session_dir = initialise_session(args.root, manifest)
            print(session_dir)
            return 0
        if args.command == "preflight":
            evidence_path = capture_host_preflight(
                args.manifest,
                target=args.target,
                interface=args.interface,
            )
            print(evidence_path)
            return 0
        if args.command == "upgrade":
            payload = upgrade_manifest(args.manifest)
            print(
                json.dumps(
                    {
                        "schema_version": payload["schema_version"],
                        "session_id": payload["session_id"],
                        "status": "VALID",
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "record-check":
            payload = record_check(
                args.manifest,
                track_name=args.track,
                check_name=args.check,
                evidence_refs=args.evidence,
            )
            print(
                json.dumps(
                    {
                        "check": args.check,
                        "session_id": payload["session_id"],
                        "track": args.track,
                        "track_status": payload["tracks"][args.track]["status"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "attest-check":
            evidence_path = attest_check(
                args.manifest,
                track_name=args.track,
                check_name=args.check,
                raw_evidence_refs=args.raw_evidence,
                operator_attested=args.attest_required_assertions,
            )
            payload = load_and_validate(args.manifest)
            print(
                json.dumps(
                    {
                        "check": args.check,
                        "evidence_ref": str(evidence_path.relative_to(args.manifest.parent)),
                        "session_id": payload["session_id"],
                        "track": args.track,
                        "track_status": payload["tracks"][args.track]["status"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "record-blocker":
            payload = record_blocker(
                args.manifest,
                track_name=args.track,
                check_name=args.check,
                blocker_code=args.code,
                evidence_refs=args.evidence,
            )
            print(
                json.dumps(
                    {
                        "blocker_code": args.code,
                        "session_id": payload["session_id"],
                        "track": args.track,
                        "track_status": "BLOCKED",
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "select-provider":
            decision_path = select_provider(
                args.manifest,
                track_name=args.track,
                reason=args.reason,
            )
            payload = load_and_validate(args.manifest)
            print(
                json.dumps(
                    {
                        "decision_evidence_ref": str(
                            decision_path.relative_to(args.manifest.parent)
                        ),
                        "selected_path": payload["selected_path"],
                        "session_id": payload["session_id"],
                        "status": "VERIFIED",
                    },
                    sort_keys=True,
                )
            )
            return 0
        payload = load_and_validate(args.manifest)
        print(
            json.dumps(
                {
                    "session_id": payload["session_id"],
                    "selected_path": payload["selected_path"],
                    "status": "VALID",
                },
                sort_keys=True,
            )
        )
        return 0
    except (IntegrationManifestError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
