#!/usr/bin/env python3
"""Create and verify RC-first Connected Edge capability manifest v1.4.

The v1.4 writer binds a device-specific operation approval, adapter build identity and
private raw evidence to each capability verdict. v1.3 remains readable. A v1.2
provider-level manifest can only be migrated fail-closed: no semantic capability becomes
VERIFIED by inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "1.4"
LEGACY_SCHEMA_VERSION = "1.3"
CAPABILITIES = (
    "WAYLINE_DELIVERY",
    "EDGE_DOWNLINK",
    "EDGE_UPLINK",
    "MEDIA_PULL",
    "MEDIA_UPLOAD",
)
STATUSES = {"NOT_VERIFIED", "VERIFIED", "BLOCKED"}
PATHS = {"DJI_CLOUD", "PSDK_MANIFOLD", "MANIFOLD_DIRECT", "MSDK_FIELD", "DJI_DOCK"}
TRANSPORTS = {
    "RC_WIFI",
    "RC_CELLULAR",
    "MANIFOLD_CELLULAR",
    "DOCK_ETHERNET",
    "DOCK_CELLULAR",
    "MOP",
}
BUILD_STATUSES = {"NOT_BUILT", "CODE_READY", "SDK_BUILT", "BLOCKED"}
ALLOWED_OPERATIONS = {
    "DPK_INSTALL",
    "DPK_RESTART",
    "WAYLINE_UPLOAD_NO_START",
    "EDGE_CONTRACT_TRANSFER",
    "EDGE_BUNDLE_TRANSFER",
    "MEDIA_READ_ONE",
    "MEDIA_UPLOAD_SYNTHETIC",
}
CAPABILITY_OPERATIONS = {
    "WAYLINE_DELIVERY": "WAYLINE_UPLOAD_NO_START",
    "EDGE_DOWNLINK": "EDGE_CONTRACT_TRANSFER",
    "EDGE_UPLINK": "EDGE_BUNDLE_TRANSFER",
    "MEDIA_PULL": "MEDIA_READ_ONE",
    "MEDIA_UPLOAD": "MEDIA_UPLOAD_SYNTHETIC",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PENDING_DEVICE_IDENTITIES = {
    "PENDING-AIRCRAFT",
    "PENDING-EDGE-DEVICE",
    "PENDING-GATEWAY-DEVICE",
}
_V13_TOP_FIELDS = {
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
_V14_TOP_FIELDS = _V13_TOP_FIELDS | {
    "adapter_builds",
    "operation_approval",
    "finalization",
}
_PROFILE_FIELDS = {
    "operating_mode",
    "gateway_kind",
    "gateway_transport",
    "manifold_sim_present",
    "edge_device_id",
    "gateway_device_id",
}
_V13_RECEIPT_FIELDS = {
    "status",
    "path",
    "hardware_model",
    "firmware_version",
    "checked_at_utc",
    "evidence_refs",
    "blocker_code",
}
_V14_RECEIPT_FIELDS = _V13_RECEIPT_FIELDS | {
    "transport",
    "adapter_build_sha256",
    "provider_operation_id",
    "artifact_sha256",
    "request_sha256",
    "flight_action_started",
    "camera_write",
}
_BUILD_FIELDS = {"status", "sdk_version", "code_commit", "build_sha256", "evidence_refs"}
_APPROVAL_FIELDS = {
    "session_id",
    "aircraft_sn",
    "edge_device_id",
    "gateway_device_id",
    "dpk_sha256",
    "allowed_operations",
    "approved_by",
    "approved_at_utc",
    "expires_at_utc",
    "evidence_ref",
}
_FINALIZATION_FIELDS = {"finalized_at_utc", "manifest_sha256"}


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
                "transport": None,
                "hardware_model": "M4D+MANIFOLD3+RC_PLUS_2",
                "firmware_version": "PENDING-HIL",
                "checked_at_utc": None,
                "evidence_refs": [],
                "blocker_code": "HIL_REQUIRED",
                "adapter_build_sha256": None,
                "provider_operation_id": None,
                "artifact_sha256": None,
                "request_sha256": None,
                "flight_action_started": False,
                "camera_write": False,
            }
            for capability in CAPABILITIES
        },
        # Missing means OFF would be ambiguous in JSON review, so every capability is explicit.
        "feature_flags": {capability: False for capability in CAPABILITIES},
        "legacy_source_sha256": None,
        "adapter_builds": {
            path: {
                "status": "NOT_BUILT",
                "sdk_version": None,
                "code_commit": None,
                "build_sha256": None,
                "evidence_refs": [],
            }
            for path in sorted(PATHS)
        },
        "operation_approval": None,
        "finalization": None,
    }


def validate_manifest(
    manifest: Mapping[str, Any], *, evidence_root: Path | None = None
) -> None:
    version = manifest.get("schema_version")
    if version == LEGACY_SCHEMA_VERSION:
        top_fields = _V13_TOP_FIELDS
        receipt_fields = _V13_RECEIPT_FIELDS
    elif version == SCHEMA_VERSION:
        top_fields = _V14_TOP_FIELDS
        receipt_fields = _V14_RECEIPT_FIELDS
    else:
        raise ConnectedEdgeManifestError("manifest schema_version은 1.3 또는 1.4여야 한다")
    if set(manifest) != top_fields:
        raise ConnectedEdgeManifestError(f"manifest가 v{version} 필드 집합과 다르다")
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
        if not isinstance(receipt, Mapping) or set(receipt) != receipt_fields:
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
        if (
            version == SCHEMA_VERSION
            and checked is not None
            and started is not None
            and checked < started
        ):
            raise ConnectedEdgeManifestError(
                f"{capability} 결과시각이 session 시작보다 이를 수 없다"
            )
        if status_value == "VERIFIED":
            if path_value is None or checked is None or not evidence_refs:
                raise ConnectedEdgeManifestError(
                    f"VERIFIED {capability}에는 path, checked_at_utc, evidence가 필요하다"
                )
            if receipt.get("blocker_code") is not None:
                raise ConnectedEdgeManifestError(f"VERIFIED {capability}에 blocker가 남아 있다")
            if version == SCHEMA_VERSION:
                _validate_verified_v14(
                    manifest,
                    capability=capability,
                    receipt=receipt,
                    checked=checked,
                )
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
        if version == SCHEMA_VERSION:
            if receipt.get("transport") is not None and receipt["transport"] not in TRANSPORTS:
                raise ConnectedEdgeManifestError(f"{capability} transport가 유효하지 않다")
            for digest_field in (
                "adapter_build_sha256",
                "artifact_sha256",
                "request_sha256",
            ):
                digest = receipt.get(digest_field)
                if digest is not None and (
                    not isinstance(digest, str) or _SHA256.fullmatch(digest) is None
                ):
                    raise ConnectedEdgeManifestError(
                        f"{capability} {digest_field}가 유효하지 않다"
                    )
            provider_operation_id = receipt.get("provider_operation_id")
            if provider_operation_id is not None and (
                not isinstance(provider_operation_id, str) or not provider_operation_id.strip()
            ):
                raise ConnectedEdgeManifestError(
                    f"{capability} provider_operation_id가 유효하지 않다"
                )
            if receipt.get("flight_action_started") is not False:
                raise ConnectedEdgeManifestError(f"{capability} flight action은 금지된다")
            if receipt.get("camera_write") is not False:
                raise ConnectedEdgeManifestError(f"{capability} camera write는 금지된다")
        if evidence_root is not None:
            for ref in evidence_refs:
                _validate_evidence(evidence_root, ref)

    legacy_digest = manifest.get("legacy_source_sha256")
    if legacy_digest is not None and (
        not isinstance(legacy_digest, str) or _SHA256.fullmatch(legacy_digest) is None
    ):
        raise ConnectedEdgeManifestError("legacy_source_sha256이 유효하지 않다")

    if version == SCHEMA_VERSION:
        _validate_v14_control_fields(manifest, evidence_root=evidence_root)


def _validate_verified_v14(
    manifest: Mapping[str, Any],
    *,
    capability: str,
    receipt: Mapping[str, Any],
    checked: datetime,
) -> None:
    required = (
        "transport",
        "adapter_build_sha256",
        "provider_operation_id",
        "artifact_sha256",
        "request_sha256",
    )
    if any(receipt.get(field) is None for field in required):
        raise ConnectedEdgeManifestError(
            f"VERIFIED {capability}에는 transport, build, operation, "
            "artifact/request digest가 필요하다"
        )
    approval = manifest.get("operation_approval")
    if not isinstance(approval, Mapping):
        raise ConnectedEdgeManifestError(f"VERIFIED {capability}에는 operation approval이 필요하다")
    required_operation = CAPABILITY_OPERATIONS[capability]
    if required_operation not in approval.get("allowed_operations", []):
        raise ConnectedEdgeManifestError(
            f"VERIFIED {capability}에 필요한 승인 operation이 없다: {required_operation}"
        )
    expires = _parse_utc(approval.get("expires_at_utc"), nullable=False)
    approved = _parse_utc(approval.get("approved_at_utc"), nullable=False)
    if approved is not None and checked < approved:
        raise ConnectedEdgeManifestError(f"{capability} 결과가 operation approval보다 이르다")
    if expires is not None and checked > expires:
        raise ConnectedEdgeManifestError(f"{capability} 결과가 approval 만료 뒤에 기록됐다")
    path = str(receipt["path"])
    build = manifest.get("adapter_builds", {}).get(path)
    if not isinstance(build, Mapping) or build.get("status") != "SDK_BUILT":
        raise ConnectedEdgeManifestError(f"VERIFIED {capability} path는 SDK_BUILT여야 한다")
    if build.get("build_sha256") != receipt.get("adapter_build_sha256"):
        raise ConnectedEdgeManifestError(f"{capability} adapter build digest가 원장과 다르다")
    if path == "PSDK_MANIFOLD" and approval.get("dpk_sha256") != receipt.get(
        "adapter_build_sha256"
    ):
        raise ConnectedEdgeManifestError(
            f"{capability} PSDK build digest가 승인된 DPK digest와 다르다"
        )


def _validate_v14_control_fields(
    manifest: Mapping[str, Any], *, evidence_root: Path | None
) -> None:
    builds = manifest.get("adapter_builds")
    if not isinstance(builds, Mapping) or set(builds) != PATHS:
        raise ConnectedEdgeManifestError("adapter_builds는 다섯 integration path를 가져야 한다")
    for path, build in builds.items():
        if not isinstance(build, Mapping) or set(build) != _BUILD_FIELDS:
            raise ConnectedEdgeManifestError(f"{path} adapter build 필드가 다르다")
        status_value = build.get("status")
        if status_value not in BUILD_STATUSES:
            raise ConnectedEdgeManifestError(f"{path} adapter build status가 유효하지 않다")
        refs = build.get("evidence_refs")
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ConnectedEdgeManifestError(f"{path} adapter build evidence가 유효하지 않다")
        if len(refs) != len(set(refs)):
            raise ConnectedEdgeManifestError(f"{path} adapter build evidence가 중복됐다")
        digest = build.get("build_sha256")
        if digest is not None and (
            not isinstance(digest, str) or _SHA256.fullmatch(digest) is None
        ):
            raise ConnectedEdgeManifestError(f"{path} build_sha256이 유효하지 않다")
        code_commit = build.get("code_commit")
        if code_commit is not None and (
            not isinstance(code_commit, str) or not code_commit.strip()
        ):
            raise ConnectedEdgeManifestError(f"{path} code_commit이 유효하지 않다")
        sdk_version = build.get("sdk_version")
        if sdk_version is not None and (
            not isinstance(sdk_version, str) or not sdk_version.strip()
        ):
            raise ConnectedEdgeManifestError(f"{path} sdk_version이 유효하지 않다")
        if status_value == "CODE_READY" and code_commit is None:
            raise ConnectedEdgeManifestError(f"{path} CODE_READY에는 code_commit이 필요하다")
        if status_value == "SDK_BUILT" and (
            code_commit is None or sdk_version is None or digest is None or not refs
        ):
            raise ConnectedEdgeManifestError(
                f"{path} SDK_BUILT에는 code_commit, sdk_version, digest, evidence가 필요하다"
            )
        if status_value == "BLOCKED" and not refs:
            raise ConnectedEdgeManifestError(f"{path} BLOCKED에는 evidence가 필요하다")
        if evidence_root is not None:
            for ref in refs:
                _validate_evidence(evidence_root, ref)

    approval = manifest.get("operation_approval")
    if approval is not None:
        if not isinstance(approval, Mapping) or set(approval) != _APPROVAL_FIELDS:
            raise ConnectedEdgeManifestError("operation_approval 필드가 다르다")
        if approval.get("session_id") != manifest["session_id"]:
            raise ConnectedEdgeManifestError("approval session_id가 manifest와 다르다")
        profile = manifest["deployment_profile"]
        expected = {
            "aircraft_sn": manifest["aircraft_sn"],
            "edge_device_id": profile["edge_device_id"],
            "gateway_device_id": profile["gateway_device_id"],
        }
        if any(value in _PENDING_DEVICE_IDENTITIES for value in expected.values()):
            raise ConnectedEdgeManifestError(
                "operation approval에는 실제 aircraft/edge/gateway 장치 신원이 필요하다"
            )
        for field, value in expected.items():
            if approval.get(field) != value:
                raise ConnectedEdgeManifestError(f"approval {field}가 manifest와 다르다")
        if not isinstance(approval.get("dpk_sha256"), str) or _SHA256.fullmatch(
            approval["dpk_sha256"]
        ) is None:
            raise ConnectedEdgeManifestError("approval dpk_sha256이 유효하지 않다")
        operations = approval.get("allowed_operations")
        if (
            not isinstance(operations, list)
            or not operations
            or len(operations) != len(set(operations))
            or not set(operations) <= ALLOWED_OPERATIONS
        ):
            raise ConnectedEdgeManifestError("approval allowed_operations가 유효하지 않다")
        approved_by = approval.get("approved_by")
        if not isinstance(approved_by, str) or not approved_by.strip():
            raise ConnectedEdgeManifestError("approval approved_by가 필요하다")
        approved = _parse_utc(approval.get("approved_at_utc"), nullable=False)
        expires = _parse_utc(approval.get("expires_at_utc"), nullable=False)
        started = _parse_utc(manifest.get("started_at_utc"), nullable=False)
        if approved is not None and started is not None and approved < started:
            raise ConnectedEdgeManifestError("approval은 session 시작보다 이를 수 없다")
        if approved is not None and expires is not None and expires <= approved:
            raise ConnectedEdgeManifestError("approval 만료시각은 승인시각 뒤여야 한다")
        evidence_ref = approval.get("evidence_ref")
        if not isinstance(evidence_ref, str) or not evidence_ref:
            raise ConnectedEdgeManifestError("approval evidence_ref가 필요하다")
        if evidence_root is not None:
            _validate_evidence(evidence_root, evidence_ref)

    finalization = manifest.get("finalization")
    if finalization is not None:
        if not isinstance(finalization, Mapping) or set(finalization) != _FINALIZATION_FIELDS:
            raise ConnectedEdgeManifestError("finalization 필드가 다르다")
        ended = _parse_utc(manifest.get("ended_at_utc"), nullable=False)
        finalized = _parse_utc(finalization.get("finalized_at_utc"), nullable=False)
        if ended != finalized:
            raise ConnectedEdgeManifestError("ended_at_utc와 finalized_at_utc가 다르다")
        approval = manifest.get("operation_approval")
        if isinstance(approval, Mapping):
            approved = _parse_utc(approval.get("approved_at_utc"), nullable=False)
            if approved is not None and finalized is not None and finalized < approved:
                raise ConnectedEdgeManifestError(
                    "finalization이 operation approval보다 이를 수 없다"
                )
        for capability, receipt in manifest["capability_receipts"].items():
            checked = _parse_utc(receipt.get("checked_at_utc"), nullable=True)
            if checked is not None and finalized is not None and finalized < checked:
                raise ConnectedEdgeManifestError(
                    f"finalization이 {capability} verdict보다 이를 수 없다"
                )
        digest = finalization.get("manifest_sha256")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ConnectedEdgeManifestError("finalization digest가 유효하지 않다")
        if digest != _manifest_digest(manifest):
            raise ConnectedEdgeManifestError("finalized manifest digest가 일치하지 않는다")


def _validate_evidence(root: Path, ref: str) -> None:
    pure = PurePosixPath(ref)
    if pure.is_absolute() or ".." in pure.parts or "?" in ref or "#" in ref or "\\" in ref:
        raise ConnectedEdgeManifestError("evidence ref는 session 내부 상대 경로여야 한다")
    candidate = root / ref
    try:
        candidate.resolve().relative_to(root.resolve())
        relative = candidate.relative_to(root)
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ConnectedEdgeManifestError("evidence symlink는 허용하지 않는다")
        info = candidate.stat()
    except ConnectedEdgeManifestError:
        raise
    except (ValueError, OSError) as exc:
        raise ConnectedEdgeManifestError(f"evidence를 확인할 수 없다: {ref}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ConnectedEdgeManifestError(
            "evidence는 현재 사용자 소유의 private 일반 파일이어야 한다"
        )
    _reject_secret_material(candidate)


def _reject_secret_material(path: Path) -> None:
    data = path.read_bytes()
    if b"-----BEGIN PRIVATE KEY-----" in data or b"-----BEGIN OPENSSH PRIVATE KEY-----" in data:
        raise ConnectedEdgeManifestError("evidence에 private key material을 기록할 수 없다")
    if len(data) > 16 * 1024 * 1024:
        raise ConnectedEdgeManifestError("evidence 단일 파일은 16 MiB를 넘을 수 없다")
    text = data.decode("utf-8", errors="ignore")
    secret_value = re.compile(
        r'(?i)["\'](?:api[_-]?key|app[_-]?key|secret|password|access[_-]?token|refresh[_-]?token)["\']'
        r"\s*[:=]\s*[\"'](?!REDACTED|<redacted>|\*{3,})[^\"']{4,}[\"']"
    )
    if secret_value.search(text):
        raise ConnectedEdgeManifestError("evidence에 credential value를 기록할 수 없다")


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    payload = json.loads(json.dumps(manifest))
    payload["finalization"] = None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def acceptance_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    validate_manifest(manifest)
    receipts = manifest["capability_receipts"]
    missing = [
        capability
        for capability in CAPABILITIES
        if receipts[capability]["status"] != "VERIFIED"
    ]
    return {
        "schema_version": manifest["schema_version"],
        "rc_base_ready_for_feature_enable": not missing,
        "verified_capabilities": [
            capability
            for capability in CAPABILITIES
            if receipts[capability]["status"] == "VERIFIED"
        ],
        "missing_capabilities": missing,
        "feature_flags_enabled": [
            capability for capability in CAPABILITIES if manifest["feature_flags"][capability]
        ],
        "finalized": manifest.get("finalization") is not None,
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
    # Provider-level v1.2 success is not evidence for any independent semantic capability.
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


def _replace_private(path: Path, payload: Mapping[str, Any]) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ConnectedEdgeManifestError("manifest/session symlink는 허용하지 않는다")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def initialise(root: Path, manifest: Mapping[str, Any]) -> Path:
    validate_manifest(manifest)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    session = root / str(manifest["session_id"])
    session.mkdir(mode=0o700)
    (session / "14_connected_edge_capabilities").mkdir(mode=0o700)
    _write_private(
        session / f"integration_manifest.v{manifest['schema_version']}.json",
        manifest,
        exclusive=True,
    )
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


def _load_mutable_v14(path: Path) -> dict[str, Any]:
    manifest = load(path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ConnectedEdgeManifestError("변경 command는 v1.4 manifest만 지원한다")
    if manifest.get("finalization") is not None:
        raise ConnectedEdgeManifestError("finalized manifest는 변경할 수 없다")
    return manifest


def _persist_mutation(path: Path, manifest: dict[str, Any]) -> None:
    validate_manifest(manifest, evidence_root=path.parent)
    _replace_private(path, manifest)


def record_adapter_build(
    path: Path,
    *,
    integration_path: str,
    status_value: str,
    code_commit: str | None,
    sdk_version: str | None,
    build_sha256: str | None,
    evidence_refs: Sequence[str],
) -> None:
    manifest = _load_mutable_v14(path)
    if integration_path not in PATHS:
        raise ConnectedEdgeManifestError("integration path가 유효하지 않다")
    manifest["adapter_builds"][integration_path] = {
        "status": status_value,
        "sdk_version": sdk_version,
        "code_commit": code_commit,
        "build_sha256": build_sha256,
        "evidence_refs": list(evidence_refs),
    }
    _persist_mutation(path, manifest)


def record_approval(
    path: Path,
    *,
    approved_by: str,
    dpk_sha256: str,
    expires_at_utc: str,
    allowed_operations: Sequence[str],
    evidence_ref: str,
    approved_at: datetime | None = None,
) -> None:
    manifest = _load_mutable_v14(path)
    if manifest.get("operation_approval") is not None:
        raise ConnectedEdgeManifestError("operation approval은 교체할 수 없다")
    profile = manifest["deployment_profile"]
    manifest["operation_approval"] = {
        "session_id": manifest["session_id"],
        "aircraft_sn": manifest["aircraft_sn"],
        "edge_device_id": profile["edge_device_id"],
        "gateway_device_id": profile["gateway_device_id"],
        "dpk_sha256": dpk_sha256,
        "allowed_operations": list(allowed_operations),
        "approved_by": approved_by,
        "approved_at_utc": _utc(approved_at or datetime.now(UTC)),
        "expires_at_utc": expires_at_utc,
        "evidence_ref": evidence_ref,
    }
    _persist_mutation(path, manifest)


def record_result(
    path: Path,
    *,
    capability: str,
    integration_path: str,
    transport: str,
    hardware_model: str,
    firmware_version: str,
    adapter_build_sha256: str,
    provider_operation_id: str,
    artifact_sha256: str,
    request_sha256: str,
    evidence_refs: Sequence[str],
    checked_at: datetime | None = None,
) -> None:
    manifest = _load_mutable_v14(path)
    if capability not in CAPABILITIES:
        raise ConnectedEdgeManifestError("capability가 유효하지 않다")
    current = manifest["capability_receipts"][capability]
    if current["status"] != "NOT_VERIFIED":
        raise ConnectedEdgeManifestError(f"{capability} verdict는 교체할 수 없다")
    manifest["capability_receipts"][capability] = {
        "status": "VERIFIED",
        "path": integration_path,
        "transport": transport,
        "hardware_model": hardware_model,
        "firmware_version": firmware_version,
        "checked_at_utc": _utc(checked_at or datetime.now(UTC)),
        "evidence_refs": list(evidence_refs),
        "blocker_code": None,
        "adapter_build_sha256": adapter_build_sha256,
        "provider_operation_id": provider_operation_id,
        "artifact_sha256": artifact_sha256,
        "request_sha256": request_sha256,
        "flight_action_started": False,
        "camera_write": False,
    }
    _persist_mutation(path, manifest)


def record_blocker(
    path: Path,
    *,
    capability: str,
    integration_path: str | None,
    hardware_model: str,
    firmware_version: str,
    blocker_code: str,
    evidence_refs: Sequence[str],
    checked_at: datetime | None = None,
) -> None:
    manifest = _load_mutable_v14(path)
    if capability not in CAPABILITIES:
        raise ConnectedEdgeManifestError("capability가 유효하지 않다")
    current = manifest["capability_receipts"][capability]
    if current["status"] != "NOT_VERIFIED":
        raise ConnectedEdgeManifestError(f"{capability} verdict는 교체할 수 없다")
    manifest["capability_receipts"][capability] = {
        "status": "BLOCKED",
        "path": integration_path,
        "transport": None,
        "hardware_model": hardware_model,
        "firmware_version": firmware_version,
        "checked_at_utc": _utc(checked_at or datetime.now(UTC)),
        "evidence_refs": list(evidence_refs),
        "blocker_code": blocker_code,
        "adapter_build_sha256": None,
        "provider_operation_id": None,
        "artifact_sha256": None,
        "request_sha256": None,
        "flight_action_started": False,
        "camera_write": False,
    }
    _persist_mutation(path, manifest)


def finalize(path: Path, *, finalized_at: datetime | None = None) -> None:
    manifest = _load_mutable_v14(path)
    finalized = _utc(finalized_at or datetime.now(UTC))
    manifest["ended_at_utc"] = finalized
    manifest["finalization"] = {
        "finalized_at_utc": finalized,
        "manifest_sha256": _manifest_digest(manifest),
    }
    _persist_mutation(path, manifest)


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
    build = sub.add_parser("record-build")
    build.add_argument("manifest", type=Path)
    build.add_argument("--path", required=True, choices=sorted(PATHS))
    build.add_argument("--status", required=True, choices=sorted(BUILD_STATUSES - {"NOT_BUILT"}))
    build.add_argument("--code-commit")
    build.add_argument("--sdk-version")
    build.add_argument("--build-sha256")
    build.add_argument("--evidence-ref", action="append", default=[])
    approval = sub.add_parser("record-approval")
    approval.add_argument("manifest", type=Path)
    approval.add_argument("--approved-by", required=True)
    approval.add_argument("--dpk-sha256", required=True)
    approval.add_argument("--expires-at-utc", required=True)
    approval.add_argument(
        "--allow-operation",
        action="append",
        required=True,
        choices=sorted(ALLOWED_OPERATIONS),
    )
    approval.add_argument("--evidence-ref", required=True)
    result = sub.add_parser("record-result")
    result.add_argument("manifest", type=Path)
    result.add_argument("--capability", required=True, choices=CAPABILITIES)
    result.add_argument("--path", required=True, choices=sorted(PATHS))
    result.add_argument("--transport", required=True, choices=sorted(TRANSPORTS))
    result.add_argument("--hardware-model", required=True)
    result.add_argument("--firmware-version", required=True)
    result.add_argument("--adapter-build-sha256", required=True)
    result.add_argument("--provider-operation-id", required=True)
    result.add_argument("--artifact-sha256", required=True)
    result.add_argument("--request-sha256", required=True)
    result.add_argument("--evidence-ref", action="append", required=True)
    blocker = sub.add_parser("record-blocker")
    blocker.add_argument("manifest", type=Path)
    blocker.add_argument("--capability", required=True, choices=CAPABILITIES)
    blocker.add_argument("--path", choices=sorted(PATHS))
    blocker.add_argument("--hardware-model", required=True)
    blocker.add_argument("--firmware-version", required=True)
    blocker.add_argument("--blocker-code", required=True)
    blocker.add_argument("--evidence-ref", action="append", required=True)
    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("manifest", type=Path)
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
    if args.command == "record-build":
        record_adapter_build(
            args.manifest,
            integration_path=args.path,
            status_value=args.status,
            code_commit=args.code_commit,
            sdk_version=args.sdk_version,
            build_sha256=args.build_sha256,
            evidence_refs=args.evidence_ref,
        )
        return 0
    if args.command == "record-approval":
        record_approval(
            args.manifest,
            approved_by=args.approved_by,
            dpk_sha256=args.dpk_sha256,
            expires_at_utc=args.expires_at_utc,
            allowed_operations=args.allow_operation,
            evidence_ref=args.evidence_ref,
        )
        return 0
    if args.command == "record-result":
        record_result(
            args.manifest,
            capability=args.capability,
            integration_path=args.path,
            transport=args.transport,
            hardware_model=args.hardware_model,
            firmware_version=args.firmware_version,
            adapter_build_sha256=args.adapter_build_sha256,
            provider_operation_id=args.provider_operation_id,
            artifact_sha256=args.artifact_sha256,
            request_sha256=args.request_sha256,
            evidence_refs=args.evidence_ref,
        )
        return 0
    if args.command == "record-blocker":
        record_blocker(
            args.manifest,
            capability=args.capability,
            integration_path=args.path,
            hardware_model=args.hardware_model,
            firmware_version=args.firmware_version,
            blocker_code=args.blocker_code,
            evidence_refs=args.evidence_ref,
        )
        return 0
    if args.command == "finalize":
        finalize(args.manifest)
        return 0
    if args.command != "migrate-v12":
        raise AssertionError(f"처리하지 않은 command: {args.command}")
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
