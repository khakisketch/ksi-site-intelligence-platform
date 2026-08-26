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
from typing import Any
from xml.etree import ElementTree as ET

from ksi_processing_controller.capture_time import (
    CaptureTimeStatus,
    extract_capture_time,
)
from PIL import ExifTags, Image

SCHEMA_VERSION = "1.0"
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


def build_report(
    *,
    repository_root: Path,
    kit_dir: Path,
    pilot_import_evidence: Sequence[Path],
    m4d_jpeg: Path | None,
    pilot_export_kmz: Path | None,
    generated_at: datetime,
) -> dict[str, Any]:
    commit, dirty = _commit(repository_root)
    kit = audit_kit(kit_dir)
    import_evidence = [inspect_image(path) for path in pilot_import_evidence]
    m4d = inspect_m4d_jpeg(m4d_jpeg) if m4d_jpeg is not None else None
    exported = inspect_kmz(pilot_export_kmz) if pilot_export_kmz is not None else None

    blockers: list[str] = []
    if not import_evidence:
        blockers.append("PILOT_IMPORT_EVIDENCE_REQUIRED")
    if m4d is None or m4d["status"] != "PASS":
        blockers.append("M4D_ORIGINAL_METADATA_REQUIRED")
    if exported is None:
        blockers.append("PILOT_EXPORT_KMZ_REQUIRED")
    else:
        # Bytes alone do not prove that Pilot 2 exported the file.
        blockers.append("PILOT_EXPORT_SOURCE_ATTESTATION_REQUIRED")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "repository": {"commit": commit, "worktree_dirty": dirty},
        "safety_scope": {
            "device_contact": False,
            "device_write": False,
            "flight_or_motor_action": False,
            "customer_data_export": False,
        },
        "field0a": {
            "status": "PASS" if not blockers else "BLOCKED",
            "blockers": blockers,
            "kit": kit,
            "pilot_import": {
                "status": "OBSERVED_REQUIRES_HUMAN_ATTESTATION"
                if import_evidence
                else "NOT_VERIFIED",
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
