#!/usr/bin/env python3
"""Create and verify RC-first Connected Edge capability manifest v1.3.

Unlike integration_manifest v1.2, this manifest never selects one provider for every
operation. WAYLINE_DELIVERY, EDGE_DOWNLINK, EDGE_UPLINK, MEDIA_PULL, and MEDIA_UPLOAD
are accepted independently for an exact hardware/firmware/path tuple. Reading a v1.2
manifest is supported only through a fail-closed migration: provider-level evidence is
preserved by digest, but no v1.3 capability becomes VERIFIED by inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "1.3"
CAPABILITIES = (
    "WAYLINE_DELIVERY",
    "EDGE_DOWNLINK",
    "EDGE_UPLINK",
    "MEDIA_PULL",
    "MEDIA_UPLOAD",
)
STATUSES = {"NOT_VERIFIED", "VERIFIED", "BLOCKED"}
PATHS = {"DJI_CLOUD", "PSDK_MANIFOLD", "MANIFOLD_DIRECT", "MSDK_FIELD", "DJI_DOCK"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOP_FIELDS = {
    "schema_version",
    "session_id",
    "operator",
    "aircraft_sn",
    "started_at_utc",
    "ended_at_utc",
    "deployment_profile",
    "capability_receipts",
    "feature_flags",
    "legacy_source_sha256",
}
_PROFILE_FIELDS = {
    "operating_mode",
    "gateway_kind",
    "gateway_transport",
    "manifold_sim_present",
    "edge_device_id",
    "gateway_device_id",
}
_RECEIPT_FIELDS = {
    "status",
    "path",
    "hardware_model",
    "firmware_version",
    "checked_at_utc",
    "evidence_refs",
    "blocker_code",
}


class ConnectedEdgeManifestError(ValueError):
    pass


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ConnectedEdgeManifestError("started_at은 tz-aware여야 한다")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any, *, nullable: bool) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ConnectedEdgeManifestError("시각은 Z로 끝나는 UTC ISO-8601이어야 한다")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ConnectedEdgeManifestError("UTC 시각을 파싱할 수 없다") from exc
    if parsed.microsecond:
        raise ConnectedEdgeManifestError("시각은 초 단위여야 한다")
    return parsed


def build_manifest(
    *,
    operator: str,
    aircraft_sn: str,
    edge_device_id: str,
    gateway_device_id: str,
    started_at: datetime,
) -> dict[str, Any]:
    started = _utc(started_at)
    compact = started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": f"CONNECTED-{compact}-{aircraft_sn}",
        "operator": operator,
        "aircraft_sn": aircraft_sn,
        "started_at_utc": started,
        "ended_at_utc": None,
        "deployment_profile": {
            "operating_mode": "RC_ATTENDED",
            "gateway_kind": "RC_PLUS_2",
            "gateway_transport": "WIFI",
            "manifold_sim_present": False,
            "edge_device_id": edge_device_id,
            "gateway_device_id": gateway_device_id,
        },
        "capability_receipts": {
            capability: {
                "status": "NOT_VERIFIED",
                "path": None,
                "hardware_model": "M4D+MANIFOLD3+RC_PLUS_2",
                "firmware_version": "PENDING-HIL",
                "checked_at_utc": None,
                "evidence_refs": [],
                "blocker_code": "HIL_REQUIRED",
            }
            for capability in CAPABILITIES
        },
        # Missing means OFF would be ambiguous in JSON review, so every capability is explicit.
        "feature_flags": {capability: False for capability in CAPABILITIES},
        "legacy_source_sha256": None,
    }


def validate_manifest(
    manifest: Mapping[str, Any], *, evidence_root: Path | None = None
) -> None:
    if set(manifest) != _TOP_FIELDS or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ConnectedEdgeManifestError("manifest가 v1.3 필드 집합과 다르다")
    for field in ("session_id", "aircraft_sn"):
        value = manifest.get(field)
        if not isinstance(value, str) or _ID.fullmatch(value) is None:
            raise ConnectedEdgeManifestError(f"{field}는 경로-안전 식별자여야 한다")
    operator = manifest.get("operator")
    if not isinstance(operator, str) or not operator.strip():
        raise ConnectedEdgeManifestError("operator는 비공백이어야 한다")
    started = _parse_utc(manifest.get("started_at_utc"), nullable=False)
    ended = _parse_utc(manifest.get("ended_at_utc"), nullable=True)
    if ended is not None and started is not None and ended < started:
        raise ConnectedEdgeManifestError("ended_at_utc가 started_at_utc보다 이를 수 없다")

    profile = manifest.get("deployment_profile")
    if not isinstance(profile, Mapping) or set(profile) != _PROFILE_FIELDS:
        raise ConnectedEdgeManifestError("deployment_profile 필드가 다르다")
    if profile.get("operating_mode") != "RC_ATTENDED" or profile.get("gateway_kind") != "RC_PLUS_2":
        raise ConnectedEdgeManifestError("v1.3 첫 acceptance는 RC_ATTENDED/RC_PLUS_2만 허용한다")
    if profile.get("gateway_transport") not in {"WIFI", "CELLULAR"}:
        raise ConnectedEdgeManifestError("RC transport는 WIFI 또는 CELLULAR여야 한다")
    if profile.get("manifold_sim_present") is not False:
        raise ConnectedEdgeManifestError("첫 RC 기본형 acceptance는 Manifold SIM 없음이 필수다")
    for field in ("edge_device_id", "gateway_device_id"):
        value = profile.get(field)
        if not isinstance(value, str) or _ID.fullmatch(value) is None:
            raise ConnectedEdgeManifestError(f"{field}가 유효하지 않다")
    if profile["edge_device_id"] == profile["gateway_device_id"]:
        raise ConnectedEdgeManifestError("Gateway와 Edge 장치 신원은 달라야 한다")

    receipts = manifest.get("capability_receipts")
    flags = manifest.get("feature_flags")
    if not isinstance(receipts, Mapping) or set(receipts) != set(CAPABILITIES):
        raise ConnectedEdgeManifestError("capability_receipts는 v1.3 기능 전수를 가져야 한다")
    if not isinstance(flags, Mapping) or set(flags) != set(CAPABILITIES):
        raise ConnectedEdgeManifestError("feature_flags는 v1.3 기능 전수를 가져야 한다")
    all_evidence_refs: set[str] = set()
    for capability in CAPABILITIES:
        receipt = receipts[capability]
        if not isinstance(receipt, Mapping) or set(receipt) != _RECEIPT_FIELDS:
            raise ConnectedEdgeManifestError(f"{capability} receipt 필드가 다르다")
        status_value = receipt.get("status")
        if status_value not in STATUSES:
            raise ConnectedEdgeManifestError(f"{capability} status가 유효하지 않다")
        path_value = receipt.get("path")
        if path_value is not None and path_value not in PATHS:
            raise ConnectedEdgeManifestError(f"{capability} path가 유효하지 않다")
        if not isinstance(receipt.get("hardware_model"), str) or not receipt["hardware_model"]:
            raise ConnectedEdgeManifestError(f"{capability} hardware_model이 필요하다")
        if not isinstance(receipt.get("firmware_version"), str) or not receipt["firmware_version"]:
            raise ConnectedEdgeManifestError(f"{capability} firmware_version이 필요하다")
        evidence_refs = receipt.get("evidence_refs")
        if not isinstance(evidence_refs, list) or any(
            not isinstance(ref, str) for ref in evidence_refs
        ):
            raise ConnectedEdgeManifestError(f"{capability} evidence_refs가 유효하지 않다")
        if len(evidence_refs) != len(set(evidence_refs)):
            raise ConnectedEdgeManifestError(f"{capability} evidence_ref가 중복됐다")
        reused = all_evidence_refs.intersection(evidence_refs)
        if reused:
            raise ConnectedEdgeManifestError(
                f"{capability} evidence_ref가 다른 capability와 재사용됐다: {sorted(reused)}"
            )
        all_evidence_refs.update(evidence_refs)
        checked = _parse_utc(receipt.get("checked_at_utc"), nullable=True)
        if status_value == "VERIFIED":
            if path_value is None or checked is None or not evidence_refs:
                raise ConnectedEdgeManifestError(
                    f"VERIFIED {capability}에는 path, checked_at_utc, evidence가 필요하다"
                )
            if receipt.get("blocker_code") is not None:
                raise ConnectedEdgeManifestError(f"VERIFIED {capability}에 blocker가 남아 있다")
        elif status_value == "BLOCKED" and (
            not receipt.get("blocker_code") or not evidence_refs
        ):
            raise ConnectedEdgeManifestError(
                f"BLOCKED {capability}에는 blocker_code와 evidence가 필요하다"
            )
        elif flags[capability] is True:
            raise ConnectedEdgeManifestError(
                f"{capability}는 VERIFIED 전 feature flag를 켤 수 없다"
            )
        if not isinstance(flags[capability], bool):
            raise ConnectedEdgeManifestError(f"{capability} feature flag는 boolean이어야 한다")
        if evidence_root is not None:
            for ref in evidence_refs:
                _validate_evidence(evidence_root, ref)

    legacy_digest = manifest.get("legacy_source_sha256")
    if legacy_digest is not None and (
        not isinstance(legacy_digest, str) or _SHA256.fullmatch(legacy_digest) is None
    ):
        raise ConnectedEdgeManifestError("legacy_source_sha256이 유효하지 않다")


def _validate_evidence(root: Path, ref: str) -> None:
    pure = PurePosixPath(ref)
    if pure.is_absolute() or ".." in pure.parts or "?" in ref or "#" in ref or "\\" in ref:
        raise ConnectedEdgeManifestError("evidence ref는 session 내부 상대 경로여야 한다")
    candidate = root / ref
    try:
        candidate.resolve().relative_to(root.resolve())
        info = candidate.stat()
    except (ValueError, OSError) as exc:
        raise ConnectedEdgeManifestError(f"evidence를 확인할 수 없다: {ref}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ConnectedEdgeManifestError(
            "evidence는 현재 사용자 소유의 private 일반 파일이어야 한다"
        )


def acceptance_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    validate_manifest(manifest)
    receipts = manifest["capability_receipts"]
    missing = [
        capability
        for capability in CAPABILITIES
        if receipts[capability]["status"] != "VERIFIED"
    ]
    return {
        "rc_base_ready_for_feature_enable": not missing,
        "missing_capabilities": missing,
        "feature_flags_enabled": [
            capability for capability in CAPABILITIES if manifest["feature_flags"][capability]
        ],
    }


def migrate_v12(legacy: Mapping[str, Any]) -> dict[str, Any]:
    if legacy.get("schema_version") != "1.2":
        raise ConnectedEdgeManifestError("legacy manifest는 schema_version 1.2여야 한다")
    required = {"session_id", "operator", "aircraft_sn", "started_at_utc"}
    if not required <= set(legacy):
        raise ConnectedEdgeManifestError("legacy manifest 필수 식별 필드가 없다")
    canonical = json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
    migrated = build_manifest(
        operator=str(legacy["operator"]),
        aircraft_sn=str(legacy["aircraft_sn"]),
        edge_device_id="PENDING-EDGE-DEVICE",
        gateway_device_id="PENDING-GATEWAY-DEVICE",
        started_at=_parse_utc(legacy["started_at_utc"], nullable=False) or datetime.now(UTC),
    )
    migrated["session_id"] = str(legacy["session_id"]).replace("SESS-", "CONNECTED-", 1)
    migrated["legacy_source_sha256"] = hashlib.sha256(canonical).hexdigest()
    # Provider-level v1.2 success is not evidence for any independent v1.3 capability.
    for receipt in migrated["capability_receipts"].values():
        receipt["blocker_code"] = "V12_PROVIDER_EVIDENCE_REQUIRES_CAPABILITY_RETEST"
    validate_manifest(migrated)
    return migrated


def _write_private(path: Path, payload: Mapping[str, Any], *, exclusive: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if exclusive:
            path.unlink(missing_ok=True)
        raise


def initialise(root: Path, manifest: Mapping[str, Any]) -> Path:
    validate_manifest(manifest)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    session = root / str(manifest["session_id"])
    session.mkdir(mode=0o700)
    (session / "14_connected_edge_capabilities").mkdir(mode=0o700)
    _write_private(session / "integration_manifest.v1.3.json", manifest, exclusive=True)
    return session


def load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or path.parent.is_symlink():
        raise ConnectedEdgeManifestError("manifest/session symlink는 허용하지 않는다")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ConnectedEdgeManifestError("manifest는 현재 사용자 소유의 0600 일반 파일이어야 한다")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConnectedEdgeManifestError("manifest 최상위는 object여야 한다")
    validate_manifest(payload, evidence_root=path.parent)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--root", type=Path, default=Path("hil_raw_logs"))
    init.add_argument("--operator", required=True)
    init.add_argument("--aircraft-sn", default="PENDING-AIRCRAFT")
    init.add_argument("--edge-device-id", default="PENDING-EDGE-DEVICE")
    init.add_argument("--gateway-device-id", default="PENDING-GATEWAY-DEVICE")
    verify = sub.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    migrate = sub.add_parser("migrate-v12")
    migrate.add_argument("legacy_manifest", type=Path)
    migrate.add_argument("output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        manifest = build_manifest(
            operator=args.operator,
            aircraft_sn=args.aircraft_sn,
            edge_device_id=args.edge_device_id,
            gateway_device_id=args.gateway_device_id,
            started_at=datetime.now(UTC),
        )
        print(initialise(args.root, manifest))
        return 0
    if args.command == "verify":
        print(json.dumps(acceptance_summary(load(args.manifest)), sort_keys=True))
        return 0
    if args.legacy_manifest.is_symlink() or args.legacy_manifest.parent.is_symlink():
        raise ConnectedEdgeManifestError("legacy manifest symlink는 허용하지 않는다")
    legacy_info = args.legacy_manifest.stat()
    if (
        not stat.S_ISREG(legacy_info.st_mode)
        or legacy_info.st_uid != os.geteuid()
        or legacy_info.st_mode & 0o077
    ):
        raise ConnectedEdgeManifestError(
            "legacy manifest는 현재 사용자 소유의 0600 일반 파일이어야 한다"
        )
    legacy = json.loads(args.legacy_manifest.read_text(encoding="utf-8"))
    migrated = migrate_v12(legacy)
    _write_private(args.output, migrated, exclusive=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
