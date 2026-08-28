#!/usr/bin/env python3
"""Fail-closed, non-mutating auditor for civil field acceptance evidence.

The manifest and evidence stay in a private owner-only session directory.  This
tool deliberately returns only typed blockers and a session identifier: it must
never turn a local acceptance audit into an accidental source-media, coordinate,
or filename disclosure channel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from ksi_core.processing_profiles import KSI_ODM_CIVIL_V1_ID, ksi_odm_civil_v1
from ksi_geo_spatial.crs import UnsupportedCrsError, assert_supported_project_crs
from ksi_processing_controller.landxml import (
    MAX_LANDXML_BYTES,
    LandXmlError,
    parse_landxml_tin,
)
from PIL import Image, UnidentifiedImageError

SCHEMA_VERSION = "1.0"
_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = _ROOT / "contracts" / "schemas" / "civil-field-acceptance-manifest.v1.json"
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_EVIDENCE_ROOT = Path.home() / ".local" / "share" / "ksi-civil-acceptance"


def _canonical_evidence_root() -> Path:
    """Private owner-only root; tests may monkeypatch this boundary."""
    return CANONICAL_EVIDENCE_ROOT


def _expected_processing_profile_digest() -> str:
    digest = ksi_odm_civil_v1().profile_digest
    if digest is None:  # pragma: no cover - sealed registry contract protects this.
        raise RuntimeError("issued civil processing profile has no digest")
    return digest


def _schema_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _owner_only_directory(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        not path.is_symlink()
        and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )


def _owner_only_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        not path.is_symlink()
        and stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
    )


def _safe_relative(value: object) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return candidate


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


class _Audit:
    def __init__(self, *, evidence_root: Path, manifest_path: Path) -> None:
        self.evidence_root = evidence_root
        self.manifest_path = manifest_path
        self.blockers: set[str] = set()
        self.session: Path | None = None
        self.session_id: str | None = None

    def block(self, code: str) -> None:
        self.blockers.add(code)

    def validate_location(self) -> bool:
        canonical_root = _canonical_evidence_root()
        if self.evidence_root != canonical_root:
            self.block("CANONICAL_ROOT_REQUIRED")
            return False
        if not self.evidence_root.is_absolute() or self.evidence_root != self.evidence_root.resolve(
            strict=False
        ):
            self.block("CANONICAL_ROOT_REQUIRED")
            return False
        if not _owner_only_directory(self.evidence_root):
            self.block("CANONICAL_ROOT_UNSAFE")
            return False
        if not self.manifest_path.is_absolute():
            self.block("MANIFEST_UNSAFE")
            return False
        try:
            relative = self.manifest_path.relative_to(self.evidence_root)
        except ValueError:
            self.block("MANIFEST_OUTSIDE_CANONICAL_ROOT")
            return False
        if len(relative.parts) != 2 or any(part in {"", ".", ".."} for part in relative.parts):
            self.block("MANIFEST_UNSAFE")
            return False
        session = self.evidence_root / relative.parts[0]
        if not _owner_only_directory(session):
            self.block("SESSION_UNSAFE")
            return False
        if self.manifest_path != session / relative.parts[1] or not _owner_only_file(
            self.manifest_path
        ):
            self.block("MANIFEST_UNSAFE")
            return False
        self.session = session
        return True

    def evidence_file(self, value: object) -> Path | None:
        if self.session is None or self.session_id is None:
            self.block("MANIFEST_SCHEMA_INVALID")
            return None
        relative = _safe_relative(value)
        if relative is None:
            self.block("EVIDENCE_PATH_UNSAFE")
            return None
        path = self.session.joinpath(*relative.parts)
        parent = self.session
        for part in relative.parts[:-1]:
            parent = parent / part
            if not _owner_only_directory(parent):
                self.block("EVIDENCE_PATH_UNSAFE")
                return None
        if not _owner_only_file(path):
            self.block("EVIDENCE_FILE_UNSAFE")
            return None
        return path

    def exact_file(self, item: object) -> tuple[Path | None, str | None]:
        if not isinstance(item, Mapping):
            self.block("MANIFEST_SCHEMA_INVALID")
            return (None, None)
        expected = item.get("sha256")
        path_value = item.get("path")
        if not isinstance(expected, str) or _SHA256.fullmatch(expected) is None:
            self.block("MANIFEST_SCHEMA_INVALID")
            return (None, None)
        path = self.evidence_file(path_value)
        if path is None:
            return (None, None)
        try:
            actual = _sha256(path)
        except OSError:
            self.block("EVIDENCE_FILE_UNSAFE")
            return (None, None)
        if actual != expected:
            self.block("EVIDENCE_DIGEST_MISMATCH")
            return (None, None)
        return (path, expected)

    def report(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "INPUT_READY" if not self.blockers else "BLOCKED",
            "fieldAcceptance": "NOT_EVALUATED",
            "blockers": sorted(self.blockers),
        }
        if self.session_id is not None:
            result["sessionId"] = self.session_id
        return result


def _validate_schema(manifest: object, audit: _Audit) -> Mapping[str, Any] | None:
    if not isinstance(manifest, Mapping):
        audit.block("MANIFEST_SCHEMA_INVALID")
        return None
    if any(_schema_validator().iter_errors(manifest)):
        audit.block("MANIFEST_SCHEMA_INVALID")
        return None
    return manifest


def _validate_attestations(manifest: Mapping[str, Any], audit: _Audit) -> None:
    if manifest.get("operatorAttested") is not True:
        audit.block("OPERATOR_ATTESTATION_REQUIRED")
    site = manifest.get("site")
    if not isinstance(site, Mapping) or site.get("anonymized") is not True:
        audit.block("SITE_ANONYMIZATION_NOT_ATTESTED")
    if not isinstance(site, Mapping) or site.get("sameSiteAttested") is not True:
        audit.block("SAME_SITE_NOT_ATTESTED")
    rights = manifest.get("rights")
    for key, code in (
        ("commercialProcessing", "COMMERCIAL_PROCESSING_RIGHTS_NOT_ATTESTED"),
        ("derivativeOutputs", "DERIVATIVE_OUTPUT_RIGHTS_NOT_ATTESTED"),
    ):
        attestation = rights.get(key) if isinstance(rights, Mapping) else None
        if not isinstance(attestation, Mapping) or attestation.get("attested") is not True:
            audit.block(code)
            continue
        basis = attestation.get("basis")
        if not isinstance(basis, str) or not basis.strip():
            audit.block("RIGHTS_BASIS_REQUIRED")
        audit.exact_file(attestation.get("evidence"))
    if manifest.get("processingProfileId") != KSI_ODM_CIVIL_V1_ID:
        audit.block("PROCESSING_PROFILE_MISMATCH")
    if manifest.get("processingProfileDigest") != _expected_processing_profile_digest():
        audit.block("PROCESSING_PROFILE_DIGEST_MISMATCH")


def _validate_crs_and_vertical(manifest: Mapping[str, Any], audit: _Audit) -> None:
    crs = manifest.get("crs")
    try:
        assert_supported_project_crs(crs if isinstance(crs, str) else "")
    except UnsupportedCrsError:
        audit.block("UNSUPPORTED_KOREAN_CRS")
    vertical = manifest.get("verticalReference")
    if (
        not isinstance(vertical, Mapping)
        or not isinstance(vertical.get("datum"), str)
        or not vertical["datum"].strip()
        or not isinstance(vertical.get("basis"), str)
        or not vertical["basis"].strip()
    ):
        audit.block("VERTICAL_REFERENCE_MISSING")


def _same_vertical_reference(left: object, right: object) -> bool:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    return left.get("datum") == right.get("datum") and left.get("basis") == right.get("basis")


def _is_jpeg(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            if image.format != "JPEG":
                return False
            image.verify()
    except (OSError, UnidentifiedImageError, ValueError, SyntaxError):
        return False
    return True


def _validate_ground_control_files(
    manifest: Mapping[str, Any], audit: _Audit
) -> dict[str, tuple[str, str]]:
    controls = manifest.get("groundControlFiles")
    if (
        not isinstance(controls, Sequence)
        or isinstance(controls, (str, bytes))
        or len(controls) != 2
    ):
        audit.block("GROUND_CONTROL_EVIDENCE_REQUIRED")
        return {}
    identities: dict[str, tuple[str, str]] = {}
    for control in controls:
        _path, digest = audit.exact_file(control)
        if (
            not isinstance(control, Mapping)
            or not isinstance(control.get("epochId"), str)
            or not isinstance(control.get("path"), str)
            or digest is None
        ):
            continue
        epoch_id = control["epochId"]
        if epoch_id in identities or epoch_id not in {"baseline", "current"}:
            audit.block("GROUND_CONTROL_EPOCH_BINDING_INVALID")
            continue
        identities[epoch_id] = (control["path"], digest)
    if set(identities) != {"baseline", "current"}:
        audit.block("GROUND_CONTROL_EPOCH_BINDING_INVALID")
    elif len(set(identities.values())) != 2:
        audit.block("GROUND_CONTROL_IDENTITY_NOT_DISTINCT")
    if not identities:
        audit.block("GROUND_CONTROL_EVIDENCE_REQUIRED")
    return identities


def _validate_georeferencing(
    epoch: Mapping[str, Any],
    *,
    control_identities: Mapping[str, tuple[str, str]],
    manifest_crs: object,
    manifest_vertical: object,
    audit: _Audit,
) -> None:
    georeferencing = epoch.get("georeferencing")
    if not isinstance(georeferencing, Mapping):
        audit.block("GEOREFERENCING_EVIDENCE_REQUIRED")
        return
    evidence = georeferencing.get("evidence")
    _path, digest = audit.exact_file(evidence)
    if (
        not isinstance(evidence, Mapping)
        or not isinstance(evidence.get("path"), str)
        or digest is None
    ):
        audit.block("GEOREFERENCING_EVIDENCE_REQUIRED")
    else:
        epoch_id = epoch.get("epochId")
        bound_control = control_identities.get(epoch_id) if isinstance(epoch_id, str) else None
        if bound_control != (evidence["path"], digest):
            audit.block("GEOREFERENCING_EVIDENCE_NOT_BOUND")
    declared_crs = georeferencing.get("crs")
    try:
        if assert_supported_project_crs(
            declared_crs if isinstance(declared_crs, str) else ""
        ) != assert_supported_project_crs(manifest_crs if isinstance(manifest_crs, str) else ""):
            audit.block("CRS_MISMATCH")
    except UnsupportedCrsError:
        audit.block("UNSUPPORTED_KOREAN_CRS")
    if not _same_vertical_reference(georeferencing.get("verticalReference"), manifest_vertical):
        audit.block("VERTICAL_REFERENCE_MISMATCH")


def _validate_epochs(
    manifest: Mapping[str, Any], audit: _Audit, control_identities: Mapping[str, tuple[str, str]]
) -> set[str]:
    epochs = manifest.get("epochs")
    if not isinstance(epochs, Sequence) or isinstance(epochs, (str, bytes)) or len(epochs) != 2:
        audit.block("EPOCH_SET_INVALID")
        return set()

    epoch_ids: set[str] = set()
    intervals: dict[str, tuple[datetime, datetime]] = {}
    all_paths: set[str] = set()
    all_digests: set[str] = set()
    for epoch in epochs:
        if not isinstance(epoch, Mapping):
            audit.block("EPOCH_SET_INVALID")
            continue
        epoch_id = epoch.get("epochId")
        if (
            not isinstance(epoch_id, str)
            or epoch_id in epoch_ids
            or epoch_id not in {"baseline", "current"}
        ):
            audit.block("EPOCH_SET_INVALID")
        else:
            epoch_ids.add(epoch_id)

        started = _parse_utc(epoch.get("captureStartedAtUtc"))
        ended = _parse_utc(epoch.get("captureEndedAtUtc"))
        if started is None or ended is None or ended < started:
            audit.block("EPOCH_CAPTURE_INTERVAL_INVALID")
        elif isinstance(epoch_id, str):
            intervals[epoch_id] = (started, ended)

        _validate_georeferencing(
            epoch,
            control_identities=control_identities,
            manifest_crs=manifest.get("crs"),
            manifest_vertical=manifest.get("verticalReference"),
            audit=audit,
        )

        images = epoch.get("images")
        if not isinstance(images, Sequence) or isinstance(images, (str, bytes)) or len(images) < 5:
            audit.block("EPOCH_IMAGE_COUNT_INSUFFICIENT")
            continue
        epoch_paths: set[str] = set()
        epoch_digests: set[str] = set()
        for image in images:
            if not isinstance(image, Mapping):
                audit.block("EPOCH_IMAGES_NOT_UNIQUE")
                continue
            path_value = image.get("path")
            path_key = path_value if isinstance(path_value, str) else ""
            path, digest = audit.exact_file(image)
            if path_key in epoch_paths or path_key in all_paths:
                audit.block("EPOCH_IMAGES_NOT_UNIQUE")
            epoch_paths.add(path_key)
            all_paths.add(path_key)
            if digest is not None:
                if digest in epoch_digests or digest in all_digests:
                    audit.block("EPOCH_IMAGES_NOT_UNIQUE")
                epoch_digests.add(digest)
                all_digests.add(digest)
            if (
                path is None
                or path.suffix.lower() not in {".jpg", ".jpeg"}
                or not _is_jpeg(path)
                or image.get("originalCameraFileAttested") is not True
            ):
                audit.block("ORIGINAL_JPEG_REQUIRED")

    if epoch_ids != {"baseline", "current"}:
        audit.block("EPOCH_SET_INVALID")
    elif set(intervals) == {"baseline", "current"} and (
        intervals["baseline"][1] >= intervals["current"][0]
    ):
        audit.block("EPOCHS_NOT_DISTINCT")
    return all_digests


def _validate_design_surface(manifest: Mapping[str, Any], audit: _Audit) -> str | None:
    design = manifest.get("designSurface")
    if not isinstance(design, Mapping):
        audit.block("LANDXML_REQUIRED")
        return None
    path, digest = audit.exact_file(design)
    if path is None:
        return digest
    if path.suffix.lower() not in {".xml", ".landxml"}:
        audit.block("LANDXML_REQUIRED")
        return digest
    selector = design.get("surfaceSelector")
    try:
        if path.stat().st_size > MAX_LANDXML_BYTES:
            raise LandXmlError("LANDXML_TOO_LARGE", "LandXML exceeds the parser byte limit")
        parse_landxml_tin(
            path.read_bytes(), surface_selector=selector if isinstance(selector, str) else None
        )
    except (LandXmlError, OSError):
        audit.block("LANDXML_INVALID")
    design_crs = design.get("crs")
    manifest_crs_value = manifest.get("crs")
    try:
        normalised_design_crs = assert_supported_project_crs(
            design_crs if isinstance(design_crs, str) else ""
        )
        manifest_crs = assert_supported_project_crs(
            manifest_crs_value if isinstance(manifest_crs_value, str) else ""
        )
        if normalised_design_crs != manifest_crs:
            audit.block("CRS_MISMATCH")
    except UnsupportedCrsError:
        audit.block("UNSUPPORTED_KOREAN_CRS")
    vertical = design.get("verticalReference")
    if not isinstance(vertical, Mapping) or not vertical.get("datum") or not vertical.get("basis"):
        audit.block("VERTICAL_REFERENCE_MISSING")
    else:
        manifest_vertical = manifest.get("verticalReference")
        if not _same_vertical_reference(vertical, manifest_vertical):
            audit.block("VERTICAL_REFERENCE_MISMATCH")
    return digest


def _validate_independent_reference(
    manifest: Mapping[str, Any], audit: _Audit, input_digests: set[str], design_digest: str | None
) -> None:
    reference = manifest.get("independentReference")
    if not isinstance(reference, Mapping):
        audit.block("INDEPENDENT_REFERENCE_REQUIRED")
        return
    _path, digest = audit.exact_file(reference)
    if digest is None:
        return
    if digest in input_digests or digest == design_digest:
        audit.block("REFERENCE_NOT_INDEPENDENT")
    reference_crs = reference.get("crs")
    manifest_crs_value = manifest.get("crs")
    try:
        if assert_supported_project_crs(
            reference_crs if isinstance(reference_crs, str) else ""
        ) != assert_supported_project_crs(
            manifest_crs_value if isinstance(manifest_crs_value, str) else ""
        ):
            audit.block("CRS_MISMATCH")
    except UnsupportedCrsError:
        audit.block("UNSUPPORTED_KOREAN_CRS")
    if not _same_vertical_reference(
        reference.get("verticalReference"), manifest.get("verticalReference")
    ):
        audit.block("VERTICAL_REFERENCE_MISMATCH")
    control_files = manifest.get("groundControlFiles")
    if not isinstance(control_files, Sequence) or isinstance(control_files, (str, bytes)):
        audit.block("GROUND_CONTROL_EVIDENCE_REQUIRED")
        return
    reference_path = reference.get("path")
    for control in control_files:
        _control_path, control_digest = audit.exact_file(control)
        if isinstance(control, Mapping) and control.get("path") == reference_path:
            audit.block("REFERENCE_NOT_INDEPENDENT")
        if control_digest is not None and control_digest == digest:
            audit.block("REFERENCE_NOT_INDEPENDENT")


def audit_manifest(*, manifest_path: Path, evidence_root: Path | None = None) -> dict[str, Any]:
    """Return deterministic INPUT_READY/BLOCKED evidence readiness, without mutation."""
    audit = _Audit(
        evidence_root=_canonical_evidence_root() if evidence_root is None else evidence_root,
        manifest_path=manifest_path,
    )
    if not audit.validate_location():
        return audit.report()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        audit.block("MANIFEST_INVALID")
        return audit.report()
    validated = _validate_schema(manifest, audit)
    if validated is None:
        return audit.report()

    session_id = validated.get("sessionId")
    if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
        audit.block("SESSION_ID_INVALID")
        return audit.report()
    audit.session_id = session_id
    if audit.session is None or audit.session.name != session_id:
        audit.block("SESSION_ID_MISMATCH")
        return audit.report()

    _validate_attestations(validated, audit)
    _validate_crs_and_vertical(validated, audit)
    control_identities = _validate_ground_control_files(validated, audit)
    image_digests = _validate_epochs(validated, audit, control_identities)
    design_digest = _validate_design_surface(validated, audit)
    _validate_independent_reference(validated, audit, image_digests, design_digest)
    return audit.report()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    result = audit_manifest(manifest_path=args.manifest)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "INPUT_READY" else 2


if __name__ == "__main__":
    sys.exit(main())
