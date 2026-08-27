#!/usr/bin/env python3
"""Audit FIELD-0a inputs without contacting or mutating DJI equipment.

The output is deliberately a readiness record, not a capability receipt.  It can
prove that the deterministic handoff kit and local evidence files are intact, but
it cannot infer Pilot 2 export provenance or promote any Connected Edge
capability.  GPS coordinates and device serial numbers are never emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import zipfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from xml.etree import ElementTree as ET

from ksi_core.flight_artifacts import inspect_pilot_export_kmz as inspect_pilot_export_candidate
from ksi_processing_controller.capture_time import (
    CaptureTimeStatus,
    extract_capture_time,
)
from PIL import ExifTags, Image

SCHEMA_VERSION = "1.0"
FIELD0A_SESSION_ATTESTATION_SCHEMA_VERSION = "1.0"
CANONICAL_FIELD0A_EVIDENCE_ROOT = Path("/mnt/ksi-field-evidence")
_DURABLE_SHARE_FILESYSTEMS = frozenset({"nfs", "nfs4", "cifs", "smb3"})
EXPECTED_KIT_FILES = (
    "KSI-FIELD0A-A-droneEnum-100-payload-98.kmz",
    "KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz",
    "KSI-FIELD0A-C-droneEnum-100-wpml-1.0.3.kmz",
)
EXPECTED_KMZ_MEMBERS = {
    "wpmz/template.kml",
    "wpmz/waylines.wpml",
    "wpmz/res/",
}
CAPABILITIES = (
    "WAYLINE_DELIVERY",
    "EDGE_DOWNLINK",
    "EDGE_UPLINK",
    "MEDIA_PULL",
    "MEDIA_UPLOAD",
)
KML_NS = "http://www.opengis.net/kml/2.2"
_GIT_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ReadinessAuditError(ValueError):
    pass


class Field0aAttestationError(ReadinessAuditError):
    """A private FIELD-0a attestation failed a fail-closed validation rule."""

    def __init__(self, blocker_code: str, message: str) -> None:
        super().__init__(message)
        self.blocker_code = blocker_code


def _attestation_error(blocker_code: str, message: str) -> NoReturn:
    raise Field0aAttestationError(blocker_code, message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_source(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ReadinessAuditError(f"symlink evidence is not allowed: {path.name}")
    try:
        info = path.stat()
    except OSError as exc:
        raise ReadinessAuditError(f"evidence is unavailable: {path.name}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise ReadinessAuditError(f"evidence must be an owner-held regular file: {path.name}")
    return {"source_name": path.name, "size_bytes": info.st_size, "sha256": _sha256(path)}


def _manifest_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        if match is None:
            raise ReadinessAuditError("SHA256SUMS contains a malformed or unsafe line")
        digest, name = match.groups()
        if name in checksums:
            raise ReadinessAuditError(f"duplicate checksum entry: {name}")
        checksums[name] = digest
    if tuple(checksums) != EXPECTED_KIT_FILES:
        raise ReadinessAuditError("FIELD-0a checksum manifest file set/order changed")
    return checksums


def _namespace_for_local_name(root: ET.Element, local_name: str) -> str:
    for node in root.iter():
        match = re.match(rf"^\{{([^}}]+)\}}{re.escape(local_name)}$", node.tag)
        if match is not None:
            namespace = match.group(1)
            if not namespace.startswith("http://www.dji.com/wpmz/"):
                raise ReadinessAuditError("WPML element uses an unexpected namespace")
            return namespace
    raise ReadinessAuditError(f"WPML element is missing: {local_name}")


def _one_text(root: ET.Element, namespace: str, local_name: str) -> str | None:
    node = root.find(f".//{{{namespace}}}{local_name}")
    if node is None or node.text is None:
        return None
    return node.text


def inspect_kmz(path: Path) -> dict[str, Any]:
    source = _safe_source(path)
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = {item.filename for item in members}
            if names != EXPECTED_KMZ_MEMBERS:
                raise ReadinessAuditError(f"unexpected KMZ member set: {path.name}")
            for item in members:
                pure = PurePosixPath(item.filename)
                if pure.is_absolute() or ".." in pure.parts or item.flag_bits & 0x1:
                    raise ReadinessAuditError(f"unsafe KMZ member: {item.filename}")
                file_type = (item.external_attr >> 16) & 0o170000
                if file_type == stat.S_IFLNK:
                    raise ReadinessAuditError(f"KMZ symlink member is not allowed: {item.filename}")
            waylines = ET.fromstring(archive.read("wpmz/waylines.wpml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ReadinessAuditError(f"invalid KMZ: {path.name}") from exc

    wpml_namespace = _namespace_for_local_name(waylines, "actionActuatorFunc")
    placemarks = waylines.findall(f".//{{{KML_NS}}}Placemark")
    actions = [
        node.text
        for node in waylines.findall(f".//{{{wpml_namespace}}}actionActuatorFunc")
        if node.text
    ]
    heights = {
        node.text
        for node in waylines.findall(f".//{{{wpml_namespace}}}executeHeight")
        if node.text
    }
    lens_values = sorted(
        {
            node.text
            for node in waylines.findall(f".//{{{wpml_namespace}}}payloadLensIndex")
            if node.text
        }
    )
    source.update(
        {
            "wpml_namespace": wpml_namespace,
            "waypoint_count": len(placemarks),
            "take_photo_action_count": actions.count("takePhoto"),
            "execute_heights_m": sorted(heights),
            "drone_enum_value": _one_text(waylines, wpml_namespace, "droneEnumValue"),
            "drone_sub_enum_value": _one_text(
                waylines, wpml_namespace, "droneSubEnumValue"
            ),
            "payload_enum_value": _one_text(
                waylines, wpml_namespace, "payloadEnumValue"
            ),
            "payload_sub_enum_value": _one_text(
                waylines, wpml_namespace, "payloadSubEnumValue"
            ),
            "waypoint_heading_path_mode": _one_text(
                waylines, wpml_namespace, "waypointHeadingPathMode"
            ),
            "payload_lens_indices": lens_values,
        }
    )
    return source


def inspect_pilot_export_kmz(path: Path) -> dict[str, Any]:
    """Inspect a supplied Pilot-export candidate without treating it as FIELD proof.

    The pinned FIELD-0a kit deliberately has an exact member set and continues
    to be checked by :func:`inspect_kmz`.  A real Pilot export, however, can
    legitimately carry additional safe resources.  Reuse the Core ingress
    validator so the HIL preparation report and the candidate ingest boundary
    do not drift, while retaining the explicit provenance-attestation blocker.
    """

    source = _safe_source(path)
    try:
        inspection = inspect_pilot_export_candidate(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReadinessAuditError(f"invalid Pilot export KMZ: {path.name}") from exc
    source.update(
        {
            "status": "STRUCTURALLY_VALIDATED_UNATTESTED",
            "validation_scope": "WPML_STRUCTURE_ONLY",
            "placemark_count": inspection.placemark_count,
            "min_execute_height_m": min(inspection.execute_heights_m),
            "max_execute_height_m": max(inspection.execute_heights_m),
            "execute_height_mode": inspection.execute_height_mode,
        }
    )
    return source


def audit_kit(kit_dir: Path) -> dict[str, Any]:
    if kit_dir.is_symlink() or not kit_dir.is_dir():
        raise ReadinessAuditError("FIELD-0a kit must be a real directory")
    checksums = _manifest_checksums(kit_dir / "SHA256SUMS")
    files: list[dict[str, Any]] = []
    for name in EXPECTED_KIT_FILES:
        inspected = inspect_kmz(kit_dir / name)
        if inspected["sha256"] != checksums[name]:
            raise ReadinessAuditError(f"FIELD-0a checksum mismatch: {name}")
        if inspected["waypoint_count"] != 80:
            raise ReadinessAuditError(f"FIELD-0a waypoint count changed: {name}")
        if inspected["take_photo_action_count"] != 80:
            raise ReadinessAuditError(f"FIELD-0a photo action count changed: {name}")
        if inspected["execute_heights_m"] != ["40"]:
            raise ReadinessAuditError(f"FIELD-0a execute height changed: {name}")
        files.append(inspected)
    return {"status": "PASS", "files": files}


def inspect_image(path: Path) -> dict[str, Any]:
    source = _safe_source(path)
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format
    except Exception as exc:  # noqa: BLE001 -- corrupt evidence must fail closed
        raise ReadinessAuditError(f"invalid image evidence: {path.name}") from exc
    source.update({"format": image_format, "width": width, "height": height})
    return source


def _text(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00 ")
    if isinstance(value, str):
        return value.strip("\x00 ")
    return None


def _number(value: Any) -> float | None:
    try:
        if isinstance(value, tuple) and len(value) == 2:
            return round(float(value[0]) / float(value[1]), 6)
        return round(float(value), 6)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def inspect_m4d_jpeg(path: Path) -> dict[str, Any]:
    source = inspect_image(path)
    # M4D may store its .jpg as a two-frame Multi-Picture Object. Pillow reports
    # that intact camera original as MPO; flattening it to JPEG would discard
    # provenance-bearing bytes, so both original container reports are valid.
    if source["format"] not in {"JPEG", "MPO"}:
        raise ReadinessAuditError("M4D evidence must be an original JPEG/MPO")
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            values: dict[Any, Any] = dict(exif)
            with suppress(AttributeError, KeyError, TypeError):
                values.update(exif.get_ifd(ExifTags.IFD.Exif))
            packets = [
                payload
                for _marker, payload in getattr(image, "applist", ())
                if isinstance(payload, bytes) and b"drone-dji" in payload.lower()
            ]
    except Exception as exc:  # noqa: BLE001
        raise ReadinessAuditError("M4D EXIF/XMP metadata is unreadable") from exc

    model = _text(values.get(272))
    make = _text(values.get(271))
    focal_length_mm = _number(values.get(37386))
    focal_length_35mm = _number(values.get(41989))
    wide_camera = any(b'ImageSource="WideCamera"' in packet for packet in packets)
    capture_time = extract_capture_time(path)
    metadata_pass = (
        make == "DJI"
        and model == "M4D"
        and source["width"] == 5280
        and source["height"] == 3956
        and focal_length_mm is not None
        and focal_length_35mm is not None
        and wide_camera
        and capture_time.status is CaptureTimeStatus.VERIFIED
        and capture_time.captured_at is not None
    )
    source.update(
        {
            "status": "PASS" if metadata_pass else "BLOCKED",
            "camera_make": make,
            "camera_model": model,
            "image_source": "WideCamera" if wide_camera else "UNKNOWN",
            "focal_length_mm": focal_length_mm,
            "focal_length_35mm": focal_length_35mm,
            "capture_time_status": capture_time.status.value,
            "capture_time_source": capture_time.source.value,
            "captured_at_utc": (
                capture_time.captured_at.isoformat().replace("+00:00", "Z")
                if capture_time.captured_at is not None
                else None
            ),
        }
    )
    return source


def _commit(root: Path) -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReadinessAuditError("repository identity is unavailable") from exc
    if _GIT_OID.fullmatch(commit) is None:
        raise ReadinessAuditError("repository commit is not a valid Git object id")
    return commit, dirty


def _parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        _attestation_error("FIELD0A_ATTESTATION_INVALID", f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _attestation_error("FIELD0A_ATTESTATION_INVALID", f"{field} is not a timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        _attestation_error("FIELD0A_ATTESTATION_INVALID", f"{field} must use UTC")
    return parsed.astimezone(UTC).replace(microsecond=0)


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        _attestation_error("FIELD0A_ATTESTATION_INVALID", f"{field} is required")
    return value.strip()


def _relative_evidence_path(value: Any) -> str:
    if not isinstance(value, str):
        _attestation_error("FIELD0A_ATTESTATION_INVALID", "raw_evidence_path is required")
    relative = PurePosixPath(value)
    if (
        not value
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        _attestation_error(
            "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
            "raw_evidence_path must be a safe relative path",
        )
    return relative.as_posix()


def _owner_private_json(path: Path) -> Mapping[str, Any]:
    if path.is_symlink():
        _attestation_error(
            "FIELD0A_ATTESTATION_SYMLINK_REJECTED",
            "FIELD-0a attestation symlink is not allowed",
        )
    try:
        info = path.stat()
    except OSError as exc:
        raise Field0aAttestationError(
            "FIELD0A_ATTESTATION_INVALID", "FIELD-0a attestation is unavailable"
        ) from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        _attestation_error(
            "FIELD0A_ATTESTATION_PERMISSION_DENIED",
            "FIELD-0a attestation must be an owner-held regular file",
        )
    if info.st_mode & 0o077:
        _attestation_error(
            "FIELD0A_ATTESTATION_PERMISSION_DENIED",
            "FIELD-0a attestation must be owner-only",
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Field0aAttestationError(
            "FIELD0A_ATTESTATION_INVALID", "FIELD-0a attestation is not valid JSON"
        ) from exc
    if not isinstance(value, Mapping):
        _attestation_error("FIELD0A_ATTESTATION_INVALID", "FIELD-0a attestation must be an object")
    return value


def _canonical_field0a_evidence_root() -> Path:
    """Return the operator-provisioned network-share mount for FIELD-0a raw evidence."""

    return CANONICAL_FIELD0A_EVIDENCE_ROOT


def _mount_filesystem_type(path: Path) -> str | None:
    """Return the filesystem type of the longest Linux mount containing ``path``."""

    try:
        target = path.resolve(strict=True)
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    matches: list[tuple[int, str]] = []
    for line in lines:
        fields = line.split()
        with suppress(ValueError):
            separator = fields.index("-")
            mount_point = Path(fields[4].replace(r"\040", " ").replace(r"\011", "\t"))
            try:
                target.relative_to(mount_point)
            except ValueError:
                continue
            matches.append((len(mount_point.parts), fields[separator + 1]))
    return max(matches, default=(0, None))[1]


def _validate_durable_evidence_root(raw_evidence_root: Path) -> Path:
    """Fail closed unless evidence lives in a private session directory on the share."""

    try:
        resolved_root = raw_evidence_root.resolve(strict=True)
        canonical_root = _canonical_field0a_evidence_root().resolve(strict=True)
        relative = resolved_root.relative_to(canonical_root)
    except (OSError, ValueError) as exc:
        raise Field0aAttestationError(
            "FIELD0A_ATTESTATION_DURABLE_SHARE_REQUIRED",
            "raw_evidence_root must be beneath the canonical FIELD-0a durable share",
        ) from exc
    if len(relative.parts) != 1:
        _attestation_error(
            "FIELD0A_ATTESTATION_DURABLE_SHARE_REQUIRED",
            "raw_evidence_root must be a durable-share session directory",
        )
    if _mount_filesystem_type(resolved_root) not in _DURABLE_SHARE_FILESYSTEMS:
        _attestation_error(
            "FIELD0A_ATTESTATION_DURABLE_SHARE_REQUIRED",
            "raw_evidence_root must be mounted from an approved network share",
        )
    return resolved_root


def _attested_artifact(
    *,
    record: Mapping[str, Any],
    field: str,
    session_id: str,
    operator_id: str,
    starts_at: datetime,
    ends_at: datetime,
    raw_evidence_root: Path,
    supplied_path: Path,
) -> dict[str, str]:
    if _required_text(record, "session_id") != session_id:
        _attestation_error("FIELD0A_ATTESTATION_SESSION_MISMATCH", f"{field} session_id differs")
    if _required_text(record, "operator_id") != operator_id:
        _attestation_error("FIELD0A_ATTESTATION_SESSION_MISMATCH", f"{field} operator_id differs")
    observed_at = _parse_utc(record.get("observed_at_utc"), field=f"{field}.observed_at_utc")
    if not starts_at <= observed_at <= ends_at:
        _attestation_error(
            "FIELD0A_ATTESTATION_SESSION_MISMATCH",
            f"{field} observed_at_utc is outside the session interval",
        )
    relative_path = _relative_evidence_path(record.get("raw_evidence_path"))
    relative_parts = PurePosixPath(relative_path).parts
    expected_path = raw_evidence_root.joinpath(*relative_parts)
    candidate = raw_evidence_root
    has_symlink = False
    for part in relative_parts:
        candidate = candidate / part
        if candidate.is_symlink():
            has_symlink = True
            break
    if has_symlink or supplied_path.is_symlink():
        _attestation_error(
            "FIELD0A_ATTESTATION_SYMLINK_REJECTED",
            f"{field} evidence symlink is not allowed",
        )
    try:
        expected_info = expected_path.stat()
        supplied_info = supplied_path.stat()
    except OSError as exc:
        raise Field0aAttestationError(
            "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
            f"{field} raw evidence path is unavailable",
        ) from exc
    if (
        not stat.S_ISREG(expected_info.st_mode)
        or expected_info.st_uid != os.geteuid()
        or not stat.S_ISREG(supplied_info.st_mode)
        or supplied_info.st_uid != os.geteuid()
    ):
        _attestation_error(
            "FIELD0A_ATTESTATION_PERMISSION_DENIED",
            f"{field} evidence must be an owner-held regular file",
        )
    try:
        same_file = os.path.samefile(expected_path, supplied_path)
    except OSError as exc:
        raise Field0aAttestationError(
            "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
            f"{field} evidence relation cannot be verified",
        ) from exc
    if not same_file:
        _attestation_error(
            "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
            f"{field} raw evidence path does not identify the supplied file",
        )
    digest = _required_text(record, "sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != _sha256(supplied_path):
        _attestation_error(
            "FIELD0A_ATTESTATION_DIGEST_MISMATCH", f"{field} SHA-256 does not match"
        )
    return {
        "raw_evidence_path": relative_path,
        "sha256": digest,
        "observed_at_utc": observed_at.isoformat().replace("+00:00", "Z"),
    }


def validate_field0a_session_attestation(
    path: Path,
    *,
    commit: str,
    pilot_import_evidence: Sequence[Path],
    m4d_jpeg: Path | None,
    pilot_export_kmz: Path | None,
) -> dict[str, Any]:
    """Validate a private human attestation and bind every supplied FIELD artifact.

    This is intentionally a local evidence gate.  It never changes a Mission
    Contract, dispatch state, or Phase 3 capability state.
    """

    payload = _owner_private_json(path)
    if payload.get("schema_version") != FIELD0A_SESSION_ATTESTATION_SCHEMA_VERSION:
        _attestation_error("FIELD0A_ATTESTATION_INVALID", "unsupported attestation schema")
    session_id = _required_text(payload, "session_id")
    operator_id = _required_text(payload, "operator_id")
    if payload.get("operator_attested") is not True:
        _attestation_error(
            "FIELD0A_ATTESTATION_OPERATOR_NOT_ATTESTED",
            "operator_attested must be true",
        )
    if _required_text(payload, "build_commit") != commit:
        _attestation_error(
            "FIELD0A_ATTESTATION_BUILD_COMMIT_MISMATCH",
            "attestation build_commit does not match the audited repository",
        )
    starts_at = _parse_utc(payload.get("started_at_utc"), field="started_at_utc")
    ends_at = _parse_utc(payload.get("ended_at_utc"), field="ended_at_utc")
    if starts_at >= ends_at:
        _attestation_error(
            "FIELD0A_ATTESTATION_SESSION_MISMATCH",
            "session UTC interval must be increasing",
        )
    safety_scope = payload.get("safety_scope")
    if not isinstance(safety_scope, Mapping):
        _attestation_error("FIELD0A_ATTESTATION_INVALID", "safety_scope must be an object")
    if (
        safety_scope.get("device_contact") is not True
        or safety_scope.get("device_write") is not True
        or safety_scope.get("propellers_removed") is not True
    ):
        _attestation_error(
            "FIELD0A_ATTESTATION_UNSAFE_SESSION",
            "device contact/write and propeller removal must be explicitly attested",
        )
    if safety_scope.get("flight_or_motor_action") is not False:
        _attestation_error(
            "FIELD0A_ATTESTATION_FLIGHT_OR_MOTOR_ACTION_REPORTED",
            "FIELD-0a must not include flight or motor action",
        )
    root_value = _required_text(payload, "raw_evidence_root")
    raw_evidence_root = Path(root_value)
    if not raw_evidence_root.is_absolute() or raw_evidence_root.is_symlink():
        _attestation_error(
            "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
            "raw_evidence_root must be a real absolute directory",
        )
    try:
        root_info = raw_evidence_root.stat()
    except OSError as exc:
        raise Field0aAttestationError(
            "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
            "raw_evidence_root is unavailable",
        ) from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or root_info.st_uid != os.geteuid()
        or root_info.st_mode & 0o077
    ):
        _attestation_error(
            "FIELD0A_ATTESTATION_PERMISSION_DENIED",
            "raw_evidence_root must be an owner-only directory",
        )
    raw_evidence_root = _validate_durable_evidence_root(raw_evidence_root)

    imports = payload.get("pilot_imports")
    if not isinstance(imports, list) or len(imports) != len(pilot_import_evidence):
        _attestation_error(
            "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
            "pilot_imports must bind every supplied screenshot exactly once",
        )
    bound_imports: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for supplied, item in zip(pilot_import_evidence, imports, strict=True):
        if not isinstance(item, Mapping):
            _attestation_error(
                "FIELD0A_ATTESTATION_INVALID", "pilot_imports entries must be objects"
            )
        variant = _required_text(item, "variant")
        result = _required_text(item, "result")
        if variant not in {"A", "B", "C"} or result not in {"IMPORTED_AND_MAPPED", "REJECTED"}:
            _attestation_error("FIELD0A_ATTESTATION_INVALID", "invalid Pilot import result")
        bound = _attested_artifact(
            record=item,
            field="pilot_import",
            session_id=session_id,
            operator_id=operator_id,
            starts_at=starts_at,
            ends_at=ends_at,
            raw_evidence_root=raw_evidence_root,
            supplied_path=supplied,
        )
        if bound["raw_evidence_path"] in seen_paths:
            _attestation_error(
                "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
                "a raw screenshot may only be attested once",
            )
        seen_paths.add(bound["raw_evidence_path"])
        bound_imports.append({"variant": variant, "result": result, **bound})

    if m4d_jpeg is None or pilot_export_kmz is None:
        _attestation_error(
            "FIELD0A_ATTESTATION_EVIDENCE_PATH_MISMATCH",
            "M4D original and Pilot export must be supplied with the attestation",
        )
    pilot_export = payload.get("pilot_export")
    m4d_original = payload.get("m4d_original")
    if not isinstance(pilot_export, Mapping) or not isinstance(m4d_original, Mapping):
        _attestation_error(
            "FIELD0A_ATTESTATION_INVALID",
            "pilot_export and m4d_original must be objects",
        )
    bound_export = _attested_artifact(
        record=pilot_export,
        field="pilot_export",
        session_id=session_id,
        operator_id=operator_id,
        starts_at=starts_at,
        ends_at=ends_at,
        raw_evidence_root=raw_evidence_root,
        supplied_path=pilot_export_kmz,
    )
    bound_m4d = _attested_artifact(
        record=m4d_original,
        field="m4d_original",
        session_id=session_id,
        operator_id=operator_id,
        starts_at=starts_at,
        ends_at=ends_at,
        raw_evidence_root=raw_evidence_root,
        supplied_path=m4d_jpeg,
    )
    return {
        "status": "PASS",
        "session_id": session_id,
        "operator_id": operator_id,
        "build_commit": commit,
        "started_at_utc": starts_at.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ends_at.isoformat().replace("+00:00", "Z"),
        "safety_scope": {
            "device_contact": True,
            "device_write": True,
            "propellers_removed": True,
            "flight_or_motor_action": False,
        },
        "pilot_imports": bound_imports,
        "pilot_export": bound_export,
        "m4d_original": bound_m4d,
    }


def build_report(
    *,
    repository_root: Path,
    kit_dir: Path,
    pilot_import_evidence: Sequence[Path],
    m4d_jpeg: Path | None,
    pilot_export_kmz: Path | None,
    generated_at: datetime,
    field0a_session_attestation: Path | None = None,
) -> dict[str, Any]:
    commit, dirty = _commit(repository_root)
    kit = audit_kit(kit_dir)
    import_evidence = [inspect_image(path) for path in pilot_import_evidence]
    m4d = inspect_m4d_jpeg(m4d_jpeg) if m4d_jpeg is not None else None
    exported = (
        inspect_pilot_export_kmz(pilot_export_kmz) if pilot_export_kmz is not None else None
    )

    blockers: list[str] = []
    if not import_evidence:
        blockers.append("PILOT_IMPORT_EVIDENCE_REQUIRED")
    if m4d is None or m4d["status"] != "PASS":
        blockers.append("M4D_ORIGINAL_METADATA_REQUIRED")
    if exported is None:
        blockers.append("PILOT_EXPORT_KMZ_REQUIRED")
    attestation: dict[str, Any]
    if field0a_session_attestation is None:
        attestation = {
            "status": "NOT_VERIFIED",
            "blocker_code": "FIELD0A_ATTESTATION_REQUIRED",
        }
        blockers.append("FIELD0A_ATTESTATION_REQUIRED")
    else:
        try:
            attestation = validate_field0a_session_attestation(
                field0a_session_attestation,
                commit=commit,
                pilot_import_evidence=pilot_import_evidence,
                m4d_jpeg=m4d_jpeg,
                pilot_export_kmz=pilot_export_kmz,
            )
        except Field0aAttestationError as exc:
            attestation = {"status": "BLOCKED", "blocker_code": exc.blocker_code}
            blockers.append(exc.blocker_code)

    import_status = (
        "PASS"
        if attestation.get("status") == "PASS"
        and any(
            item["result"] == "IMPORTED_AND_MAPPED"
            for item in attestation["pilot_imports"]
        )
        else (
            "OBSERVED_REQUIRES_HUMAN_ATTESTATION" if import_evidence else "NOT_VERIFIED"
        )
    )
    if attestation.get("status") == "PASS" and import_status != "PASS":
        blockers.append("PILOT_IMPORT_SUCCESS_REQUIRED")

    if exported is not None and attestation.get("status") != "PASS":
        # Structurally valid bytes alone do not prove a Pilot 2 export.
        blockers.append("PILOT_EXPORT_SOURCE_ATTESTATION_REQUIRED")
    safety_scope = (
        {
            "device_contact": True,
            "device_write": True,
            "flight_or_motor_action": False,
            "customer_data_export": False,
        }
        if attestation.get("status") == "PASS"
        else {
            "device_contact": False,
            "device_write": False,
            "flight_or_motor_action": False,
            "customer_data_export": False,
        }
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "repository": {"commit": commit, "worktree_dirty": dirty},
        "safety_scope": safety_scope,
        "field0a": {
            "status": "PASS" if not blockers else "BLOCKED",
            "blockers": blockers,
            "kit": kit,
            "pilot_import": {
                "status": import_status,
                "evidence": import_evidence,
            },
            "m4d_original": m4d
            if m4d is not None
            else {"status": "NOT_VERIFIED"},
            "pilot_export": exported
            if exported is not None
            else {
                "status": "BLOCKED",
                "blocker_code": "PILOT_EXPORT_KMZ_REQUIRED",
            },
            "session_attestation": attestation,
        },
        "phase3": {
            "status": "BLOCKED",
            "blocker_code": "PHYSICAL_READ_ONLY_SESSION_APPROVAL_REQUIRED",
            "capabilities": {capability: "NOT_VERIFIED" for capability in CAPABILITIES},
        },
    }


def write_private(path: Path, report: Mapping[str, Any]) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ReadinessAuditError("output symlink is not allowed")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=root)
    parser.add_argument(
        "--kit-dir", type=Path, default=root / "docs" / "hil" / "field0a-kit"
    )
    parser.add_argument("--pilot-import-evidence", type=Path, action="append", default=[])
    parser.add_argument("--m4d-jpeg", type=Path)
    parser.add_argument("--pilot-export-kmz", type=Path)
    parser.add_argument("--field0a-session-attestation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(
        repository_root=args.repository_root,
        kit_dir=args.kit_dir,
        pilot_import_evidence=args.pilot_import_evidence,
        m4d_jpeg=args.m4d_jpeg,
        pilot_export_kmz=args.pilot_export_kmz,
        field0a_session_attestation=args.field0a_session_attestation,
        generated_at=datetime.now(UTC),
    )
    write_private(args.output, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "field0a_status": report["field0a"]["status"],
                "field0a_blockers": report["field0a"]["blockers"],
                "phase3_status": report["phase3"]["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
