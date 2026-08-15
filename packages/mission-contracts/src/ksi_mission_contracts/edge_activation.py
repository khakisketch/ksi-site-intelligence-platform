"""Verified MissionDispatchEnvelope → local Edge activation bridge.

The upstream :mod:`ksi_mission_contracts.consumer` remains the single owner of
Mission Contract parsing, key loading, signature/TTL checking, and atomic
``active-contract.json`` replacement.  This module adds the distinct outer
dispatch boundary: it verifies the Core-signed device binding and RiskPolicyPack
digest before delegating the inner contract activation to that consumer.

It runs only at activation/recovery time.  No frame callback or safety-loop
operation imports this module; native C++ consumes only a locally durable
activation snapshot after this verifier has succeeded.
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import math
import os
import stat
import struct
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ksi_mission_contracts.consumer import (
    ContractInputError,
    MissionContractConsumer,
    VerificationKeyError,
    _parse_json_object,
    _read_bounded,
    load_verification_keys,
)
from ksi_mission_contracts.dispatch import (
    ActivationReceiptV1,
    DispatchValidity,
    DispatchVerdict,
    MissionDispatchEnvelopeV1,
    mission_contract_digest,
    verify_mission_dispatch_envelope,
)
from ksi_mission_contracts.risk_policy import RiskPolicyPackV1, risk_policy_pack_digest
from ksi_mission_contracts.runtime_profile import (
    EdgeRuntimeProfileV1,
    edge_runtime_profile_digest,
)
from ksi_mission_contracts.signing import KeyRegistry

_ACTIVE_DISPATCH_FILENAME = "active-dispatch.json"
_NATIVE_ACTIVE_DISPATCH_FILENAME = "active-dispatch.native.v1"
_NATIVE_RUNTIME_PROFILE_FILENAME = "active-edge-runtime-profile.native.v1"
_MAX_DISPATCH_BYTES = 1024 * 1024


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ActiveDispatchSnapshotV1(_CamelModel):
    """Native-runtime input written only after both activation checks succeed."""

    schema_version: Literal["1.0"] = "1.0"
    dispatch_id: str = Field(min_length=1)
    edge_device_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    mission_contract_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    risk_policy_pack: dict[str, Any]
    risk_policy_pack_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    edge_runtime_profile: dict[str, Any]
    edge_runtime_profile_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    validity: DispatchValidity
    activated_at: datetime
    runtime_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_policy_and_activation_time(self) -> ActiveDispatchSnapshotV1:
        pack = RiskPolicyPackV1.model_validate(self.risk_policy_pack)
        profile = EdgeRuntimeProfileV1.model_validate(self.edge_runtime_profile)
        if risk_policy_pack_digest(self.risk_policy_pack) != self.risk_policy_pack_digest:
            raise ValueError("active dispatch RiskPolicyPack digest mismatch")
        if (
            edge_runtime_profile_digest(self.edge_runtime_profile)
            != self.edge_runtime_profile_digest
        ):
            raise ValueError("active dispatch EdgeRuntimeProfile digest mismatch")
        if self.activated_at.tzinfo is None:
            raise ValueError("active dispatch activatedAt must be tz-aware")
        if not (self.validity.not_before <= self.activated_at <= self.validity.not_after):
            raise ValueError("active dispatch activatedAt is outside dispatch validity")
        # Force the typed validation result to be used; the local snapshot does
        # not carry a separate unconstrained policy identifier.
        if not pack.risk_policy_pack_id:
            raise ValueError("active dispatch RiskPolicyPack has no ID")
        if not (profile.validity.not_before <= self.activated_at <= profile.validity.not_after):
            raise ValueError("active dispatch EdgeRuntimeProfile is not valid at activation")
        return self


@dataclass(frozen=True, slots=True)
class DispatchActivationResult:
    """One activation attempt, including an idempotent receipt on replay."""

    dispatch_verdict: DispatchVerdict
    activated: bool
    reused_activation: bool = False
    activation_receipt: ActivationReceiptV1 | None = None
    active_snapshot_path: Path | None = None
    detail: str | None = None


def _effective_now(now: datetime | None) -> datetime:
    effective = now if now is not None else datetime.now(UTC)
    if effective.tzinfo is None:
        raise ValueError("now must be tz-aware")
    return effective


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    """Reuse the upstream consumer's bounded duplicate-key-safe file reader."""
    return _parse_json_object(
        _read_bounded(path, limit=_MAX_DISPATCH_BYTES, label=label), label=label
    )


def _snapshot_path(consumer: MissionContractConsumer) -> Path:
    return consumer.active_path.parent / _ACTIVE_DISPATCH_FILENAME


def _native_snapshot_path(consumer: MissionContractConsumer) -> Path:
    """Fixed-format startup handoff consumed by the dependency-free C++ runtime.

    This is intentionally a private local implementation format, not an
    additional wire contract.  The JSON snapshot remains the operator-readable
    activation record; this companion contains only the fields C++ needs to
    construct ``ActivationContext`` without pulling a JSON parser or Python
    into the PSDK process.
    """
    return consumer.active_path.parent / _NATIVE_ACTIVE_DISPATCH_FILENAME


def _native_runtime_profile_path(consumer: MissionContractConsumer) -> Path:
    """Native C++ perception handoff, published before its activation marker."""
    return consumer.active_path.parent / _NATIVE_RUNTIME_PROFILE_FILENAME


def _load_snapshot(path: Path) -> ActiveDispatchSnapshotV1 | None:
    if path.is_symlink():
        raise ContractInputError("active dispatch snapshot path is a symlink")
    if not path.exists():
        return None
    try:
        return ActiveDispatchSnapshotV1.model_validate(
            _read_json_object(path, label="active dispatch snapshot")
        )
    except (ContractInputError, ValueError) as exc:
        raise ContractInputError(f"active dispatch snapshot is invalid: {exc}") from exc


def _write_private_atomically(path: Path, payload: bytes, *, label: str) -> None:
    """Write one private state record with file+directory durability.

    Callers deliberately choose the record ordering.  In particular the native
    handoff is written only after MissionContractConsumer has atomically
    activated the inner signed contract, so a failed write stays capture-only.
    """
    state_dir = path.parent
    try:
        directory_stat = state_dir.lstat()
    except OSError as exc:
        raise ContractInputError(
            f"cannot inspect dispatch state directory: {type(exc).__name__}"
        ) from exc
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise ContractInputError("dispatch state directory is not a real directory")
    if directory_stat.st_uid != os.geteuid() or stat.S_IMODE(directory_stat.st_mode) & 0o077:
        raise ContractInputError("dispatch state directory is not private to the current user")
    if path.is_symlink():
        raise ContractInputError(f"{label} path is a symlink")
    temporary: Path | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            dir=state_dir, prefix=".active-dispatch-", suffix=".tmp"
        )
        temporary = Path(raw_temporary)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ContractInputError(
            f"cannot atomically store {label}: {type(exc).__name__}"
        ) from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _write_snapshot_atomically(path: Path, snapshot: ActiveDispatchSnapshotV1) -> None:
    """Persist the operator-readable activation record after inner activation."""
    _write_private_atomically(
        path,
        json.dumps(
            snapshot.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        label="active dispatch snapshot",
    )


def _utc_millis(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("activation timestamp must be tz-aware")
    normalized = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = normalized - epoch
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


def _native_b64(value: str) -> str:
    # No padding, control characters, or delimiter escaping is needed in the
    # compact line format.  C++ rejects non-canonical residual bits on input.
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _native_float64_bits(value: float) -> str:
    """Locale-independent finite IEEE-754 transport for native policy values."""
    if not math.isfinite(value):
        raise ContractInputError("RiskPolicyPack contains a non-finite native policy value")
    return struct.pack(">d", value).hex()


def _native_snapshot_bytes(snapshot: ActiveDispatchSnapshotV1) -> bytes:
    """Serialize the C++ activation handoff in a strict fixed field set.

    Do not add a field here without changing the native format version and its
    C++ parser.  A parser that silently ignores new safety fields is a version
    downgrade path, so both sides require the exact field set.
    """
    policy_pack = RiskPolicyPackV1.model_validate(snapshot.risk_policy_pack)
    lines = [
        "KSI_EDGE_NATIVE_ACTIVATION_V1",
        f"activated_at_utc_ms={_utc_millis(snapshot.activated_at)}",
        f"dispatch_id_b64={_native_b64(snapshot.dispatch_id)}",
        f"edge_device_id_b64={_native_b64(snapshot.edge_device_id)}",
        f"mission_contract_digest={snapshot.mission_contract_digest}",
        f"mission_id_b64={_native_b64(snapshot.mission_id)}",
        f"risk_policy_pack_digest={snapshot.risk_policy_pack_digest}",
        f"risk_policy_pack_id_b64={_native_b64(policy_pack.risk_policy_pack_id)}",
        f"risk_policy_calibration_profile_id_b64={_native_b64(policy_pack.calibration_profile_id)}",
        f"risk_policy_count={len(policy_pack.equipment_policies)}",
        f"runtime_version_b64={_native_b64(snapshot.runtime_version)}",
        f"valid_from_utc_ms={_utc_millis(snapshot.validity.not_before)}",
        f"valid_until_utc_ms={_utc_millis(snapshot.validity.not_after)}",
    ]
    # Sort to ensure a signed policy whose JSON producer happened to use a
    # different array order produces the same local C++ record.  Class
    # uniqueness was already validated by RiskPolicyPackV1.
    for index, policy in enumerate(
        sorted(policy_pack.equipment_policies, key=lambda item: item.equipment_class)
    ):
        prefix = f"risk_policy_{index}_"
        lines.extend(
            (
                f"{prefix}equipment_class_b64={_native_b64(policy.equipment_class)}",
                f"{prefix}risk_field_policy_id_b64={_native_b64(policy.risk_field_policy_id)}",
                f"{prefix}footprint_length_bits={_native_float64_bits(policy.footprint.length_m)}",
                f"{prefix}footprint_width_bits={_native_float64_bits(policy.footprint.width_m)}",
                f"{prefix}footprint_height_bits={_native_float64_bits(policy.footprint.height_m)}",
                f"{prefix}prediction_horizon_bits={_native_float64_bits(policy.prediction.horizon_seconds)}",
                f"{prefix}sample_period_bits={_native_float64_bits(policy.prediction.sample_period_seconds)}",
                f"{prefix}covariance_sigma_multiplier_bits="
                f"{_native_float64_bits(policy.covariance_sigma_multiplier)}",
                f"{prefix}occlusion_expansion_bits={_native_float64_bits(policy.occlusion_expansion_m)}",
                f"{prefix}severity_bits={_native_float64_bits(policy.severity)}",
            )
        )
    lines.append("")
    return "\n".join(lines).encode("ascii")


def _write_native_snapshot_atomically(path: Path, snapshot: ActiveDispatchSnapshotV1) -> None:
    _write_private_atomically(
        path,
        _native_snapshot_bytes(snapshot),
        label="native active dispatch handoff",
    )


def _native_runtime_profile_bytes(snapshot: ActiveDispatchSnapshotV1) -> bytes:
    """Serialize the dependency-free native perception profile handoff.

    The local record is deliberately line-oriented and exact-field-set parsed
    by C++17.  It is *not* an alternate transport contract: profile integrity
    was already established by the signed outer dispatch and the JSON snapshot
    retains an operator-readable source of truth.  Publish this record before
    the active-dispatch marker so a crash produces capture-only behavior.
    """
    profile = EdgeRuntimeProfileV1.model_validate(snapshot.edge_runtime_profile)
    model = profile.model
    calibration = profile.calibration
    lines = [
        "KSI_EDGE_NATIVE_RUNTIME_PROFILE_V1",
        f"dispatch_id_b64={_native_b64(snapshot.dispatch_id)}",
        f"edge_device_id_b64={_native_b64(snapshot.edge_device_id)}",
        f"mission_id_b64={_native_b64(snapshot.mission_id)}",
        f"mission_contract_digest={snapshot.mission_contract_digest}",
        f"risk_policy_pack_digest={snapshot.risk_policy_pack_digest}",
        f"edge_runtime_profile_digest={snapshot.edge_runtime_profile_digest}",
        f"edge_runtime_profile_id_b64={_native_b64(profile.edge_runtime_profile_id)}",
        f"site_id_b64={_native_b64(profile.site_id)}",
        f"model_pack_id_b64={_native_b64(model.model_pack_id)}",
        f"model_id_b64={_native_b64(model.model_id)}",
        f"model_onnx_artifact_id_b64={_native_b64(model.onnx_artifact_id)}",
        f"model_registered_onnx_digest={model.registered_onnx_digest}",
        f"model_tensorrt_differential_verification_profile_id_b64={_native_b64(model.tensor_rt_differential.verification_profile_id)}",
        f"model_tensorrt_differential_evidence_digest={model.tensor_rt_differential.evidence_digest}",
        f"model_tensorrt_differential_registered_onnx_digest={model.tensor_rt_differential.registered_onnx_digest}",
        f"model_tensorrt_differential_preprocessing_contract_id_b64={_native_b64(model.tensor_rt_differential.preprocessing_contract_id)}",
        f"model_tensorrt_differential_preprocessing_config_digest={model.tensor_rt_differential.preprocessing_config_digest}",
        f"model_tensorrt_differential_corpus_id_b64={_native_b64(model.tensor_rt_differential.corpus_id)}",
        f"model_tensorrt_differential_corpus_digest={model.tensor_rt_differential.corpus_digest}",
        f"model_tensorrt_differential_sample_count={model.tensor_rt_differential.sample_count}",
        f"model_tensorrt_differential_status={model.tensor_rt_differential.status}",
        f"model_tensorrt_differential_confidence_atol_bits={_native_float64_bits(model.tensor_rt_differential.confidence_atol)}",
        f"model_tensorrt_differential_bbox_atol_px_bits={_native_float64_bits(model.tensor_rt_differential.bbox_atol_px)}",
        f"model_engine_artifact_id_b64={_native_b64(model.engine_artifact_id)}",
        f"model_max_onnx_bytes={model.max_onnx_bytes}",
        f"model_max_engine_bytes={model.max_engine_bytes}",
        f"model_workspace_bytes={model.workspace_bytes}",
        f"model_input_width={model.tensor_contract.input_width}",
        f"model_input_height={model.tensor_contract.input_height}",
        f"model_query_count={model.tensor_contract.query_count}",
        f"model_class_count={model.tensor_contract.class_count}",
        f"model_score_threshold_bits={_native_float64_bits(model.score_threshold)}",
        f"model_top_k={model.top_k}",
        f"model_ontology_version_b64={_native_b64(model.ontology_version)}",
        f"model_source_taxonomy_b64={_native_b64(model.source_taxonomy)}",
        f"model_class_binding_count={len(model.class_bindings)}",
        f"calibration_profile_id_b64={_native_b64(calibration.calibration_profile_id)}",
        f"calibration_site_frame_crs_b64={_native_b64(calibration.site_frame.crs)}",
        f"calibration_site_frame_vertical_datum_b64={_native_b64(calibration.site_frame.vertical_datum)}",
        f"calibration_site_frame_transform_version_b64={_native_b64(calibration.site_frame.transform_version)}",
        f"calibration_wgs84_latitude_rad_bits={_native_float64_bits(calibration.wgs84_origin.latitude_rad)}",
        f"calibration_wgs84_longitude_rad_bits={_native_float64_bits(calibration.wgs84_origin.longitude_rad)}",
        f"calibration_wgs84_altitude_m_bits={_native_float64_bits(calibration.wgs84_origin.altitude_m)}",
        f"calibration_enu_to_site_r00_bits={_native_float64_bits(calibration.enu_to_site.rotation[0][0])}",
        f"calibration_enu_to_site_r01_bits={_native_float64_bits(calibration.enu_to_site.rotation[0][1])}",
        f"calibration_enu_to_site_r02_bits={_native_float64_bits(calibration.enu_to_site.rotation[0][2])}",
        f"calibration_enu_to_site_r10_bits={_native_float64_bits(calibration.enu_to_site.rotation[1][0])}",
        f"calibration_enu_to_site_r11_bits={_native_float64_bits(calibration.enu_to_site.rotation[1][1])}",
        f"calibration_enu_to_site_r12_bits={_native_float64_bits(calibration.enu_to_site.rotation[1][2])}",
        f"calibration_enu_to_site_r20_bits={_native_float64_bits(calibration.enu_to_site.rotation[2][0])}",
        f"calibration_enu_to_site_r21_bits={_native_float64_bits(calibration.enu_to_site.rotation[2][1])}",
        f"calibration_enu_to_site_r22_bits={_native_float64_bits(calibration.enu_to_site.rotation[2][2])}",
        f"calibration_enu_to_site_translation_x_m_bits={_native_float64_bits(calibration.enu_to_site.translation_m.x)}",
        f"calibration_enu_to_site_translation_y_m_bits={_native_float64_bits(calibration.enu_to_site.translation_m.y)}",
        f"calibration_enu_to_site_translation_z_m_bits={_native_float64_bits(calibration.enu_to_site.translation_m.z)}",
        f"calibration_ground_plane_up_m_bits={_native_float64_bits(calibration.ground_plane_up_m)}",
        f"calibration_reference_width={calibration.intrinsics.reference_width}",
        f"calibration_reference_height={calibration.intrinsics.reference_height}",
        f"calibration_focal_x_px_bits={_native_float64_bits(calibration.intrinsics.focal_x_px)}",
        f"calibration_focal_y_px_bits={_native_float64_bits(calibration.intrinsics.focal_y_px)}",
        f"calibration_principal_x_px_bits={_native_float64_bits(calibration.intrinsics.principal_x_px)}",
        f"calibration_principal_y_px_bits={_native_float64_bits(calibration.intrinsics.principal_y_px)}",
        f"calibration_camera_to_gimbal_w_bits={_native_float64_bits(calibration.camera_to_gimbal.w)}",
        f"calibration_camera_to_gimbal_x_bits={_native_float64_bits(calibration.camera_to_gimbal.x)}",
        f"calibration_camera_to_gimbal_y_bits={_native_float64_bits(calibration.camera_to_gimbal.y)}",
        f"calibration_camera_to_gimbal_z_bits={_native_float64_bits(calibration.camera_to_gimbal.z)}",
        f"calibration_camera_offset_x_m_bits={_native_float64_bits(calibration.camera_offset_in_gimbal_m.x)}",
        f"calibration_camera_offset_y_m_bits={_native_float64_bits(calibration.camera_offset_in_gimbal_m.y)}",
        f"calibration_camera_offset_z_m_bits={_native_float64_bits(calibration.camera_offset_in_gimbal_m.z)}",
        f"calibration_position_sigma_m_bits={_native_float64_bits(calibration.position_sigma_m)}",
        f"calibration_angular_sigma_rad_bits={_native_float64_bits(calibration.angular_sigma_rad)}",
        f"calibration_pixel_sigma_px_bits={_native_float64_bits(calibration.pixel_sigma_px)}",
        f"calibration_max_pose_age_ms={calibration.max_pose_age_ms}",
        f"timing_max_alignment_ms={profile.timing.max_alignment_ms}",
    ]
    for index, binding in enumerate(
        sorted(model.class_bindings, key=lambda item: item.source_class_id)
    ):
        prefix = f"model_class_binding_{index}_"
        lines.extend(
            (
                f"{prefix}source_class_id={binding.source_class_id}",
                f"{prefix}source_class_name_b64={_native_b64(binding.source_class_name)}",
                f"{prefix}equipment_class_b64={_native_b64(binding.equipment_class)}",
                f"{prefix}measured_length_bits={_native_float64_bits(binding.measured_dimensions.length_m)}",
                f"{prefix}measured_width_bits={_native_float64_bits(binding.measured_dimensions.width_m)}",
                f"{prefix}measured_height_bits={_native_float64_bits(binding.measured_dimensions.height_m)}",
            )
        )
    lines.append("")
    return "\n".join(lines).encode("ascii")


def _write_native_runtime_profile_atomically(
    path: Path, snapshot: ActiveDispatchSnapshotV1
) -> None:
    _write_private_atomically(
        path,
        _native_runtime_profile_bytes(snapshot),
        label="native Edge runtime profile handoff",
    )


def _invalidate_native_snapshot(
    path: Path, *, label: str = "native active dispatch handoff"
) -> None:
    """Remove a prior C++ handoff before replacing the inner active contract.

    Without this step a crash after the upstream consumer updates
    ``active-contract.json`` but before the new sidecar is written could make
    C++ continue under a *previous* dispatch.  Absence is intentionally a
    capture-only state; an unsafe existing path is never overwritten.
    """
    state_dir = path.parent
    try:
        directory_stat = state_dir.lstat()
    except FileNotFoundError:
        # First activation has no pre-existing native handoff to invalidate.
        # MissionContractConsumer creates and validates the directory before it
        # writes the inner active contract below.
        return
    except OSError as exc:
        raise ContractInputError(
            f"cannot inspect dispatch state directory: {type(exc).__name__}"
        ) from exc
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise ContractInputError("dispatch state directory is not a real directory")
    if directory_stat.st_uid != os.geteuid() or stat.S_IMODE(directory_stat.st_mode) & 0o077:
        raise ContractInputError("dispatch state directory is not private to the current user")
    if path.is_symlink():
        raise ContractInputError(f"{label} path is a symlink")
    try:
        existing = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ContractInputError(
            f"cannot inspect {label}: {type(exc).__name__}"
        ) from exc
    if (
        not stat.S_ISREG(existing.st_mode)
        or existing.st_uid != os.geteuid()
        or stat.S_IMODE(existing.st_mode) & 0o077
    ):
        raise ContractInputError(f"{label} is not a private regular file")
    try:
        path.unlink()
        directory_fd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ContractInputError(
            f"cannot invalidate {label}: {type(exc).__name__}"
        ) from exc


def _activate_inner_contract(
    consumer: MissionContractConsumer, contract: Mapping[str, Any], *, now: datetime
) -> bool:
    """Delegate inner contract activation to the upstream consumer unchanged."""
    descriptor, raw_candidate = tempfile.mkstemp(prefix="ksi-dispatch-inner-", suffix=".json")
    candidate = Path(raw_candidate)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(
                json.dumps(
                    dict(contract), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        return consumer.activate_file(candidate, now=now).activated
    finally:
        with suppress(FileNotFoundError):
            candidate.unlink()


def _snapshot_matches_active_contract(
    snapshot: ActiveDispatchSnapshotV1,
    envelope: MissionDispatchEnvelopeV1,
    consumer: MissionContractConsumer,
    *,
    runtime_version: str,
    now: datetime,
) -> bool:
    if (
        snapshot.dispatch_id != envelope.dispatch_id
        or snapshot.edge_device_id != envelope.edge_device_id
        or snapshot.mission_id != envelope.mission_id
        or snapshot.mission_contract_digest != envelope.mission_contract_digest
        or snapshot.risk_policy_pack_digest != envelope.risk_policy_pack_digest
        or snapshot.risk_policy_pack != envelope.risk_policy_pack
        or snapshot.edge_runtime_profile_digest != envelope.edge_runtime_profile_digest
        or snapshot.edge_runtime_profile != envelope.edge_runtime_profile
        or snapshot.validity != envelope.validity
        or snapshot.runtime_version != runtime_version
    ):
        return False
    loaded = consumer.load_active(now=now)
    if (
        not loaded.is_valid
        or loaded.model is None
        or loaded.model.mission_id != envelope.mission_id
    ):
        return False
    active = _read_json_object(consumer.active_path, label="active Mission Contract")
    return mission_contract_digest(active) == envelope.mission_contract_digest


def _policy_rollback_detail(
    existing: ActiveDispatchSnapshotV1, envelope: MissionDispatchEnvelopeV1
) -> tuple[DispatchVerdict, str] | None:
    """Same threat as ``MissionContractConsumer._superseded_detail``, on the
    two axes that check cannot see.

    The inner Mission Contract can stay unchanged (or be a normal, later
    reissue) while the outer envelope swaps in an *older* RiskPolicyPack or
    EdgeRuntimeProfile for the same mission — e.g. a reserve-margin or
    altitude-ceiling relaxation replayed from an earlier, still-validly-signed
    envelope. Neither field has an issuance-order field in its schema (same
    limitation as Mission Contract v1.2 —
    ``mission-contract-no-issuance-ordering-field``), so this uses the same
    ``validity.notBefore`` monotonicity heuristic, scoped to the same mission
    and only when the candidate's digest actually differs from what is active
    (an unchanged pack/profile is a reactivation, not a rollback).

    Returns ``None`` when there is nothing to compare (different mission) or
    the candidate is not older on either axis.
    """
    if existing.mission_id != envelope.mission_id:
        return None
    if envelope.risk_policy_pack_digest != existing.risk_policy_pack_digest:
        existing_pack = RiskPolicyPackV1.model_validate(existing.risk_policy_pack)
        new_pack = RiskPolicyPackV1.model_validate(envelope.risk_policy_pack)
        if new_pack.validity.not_before < existing_pack.validity.not_before:
            return (
                DispatchVerdict.SUPERSEDED_RISK_POLICY_PACK,
                "이미 활성인 RiskPolicyPack보다 이른 validity.notBefore를 가진 후보다 — "
                "이전 정책으로 되돌리는 활성화를 거부한다",
            )
    if envelope.edge_runtime_profile_digest != existing.edge_runtime_profile_digest:
        existing_profile = EdgeRuntimeProfileV1.model_validate(existing.edge_runtime_profile)
        new_profile = EdgeRuntimeProfileV1.model_validate(envelope.edge_runtime_profile)
        if new_profile.validity.not_before < existing_profile.validity.not_before:
            return (
                DispatchVerdict.SUPERSEDED_EDGE_RUNTIME_PROFILE,
                "이미 활성인 EdgeRuntimeProfile보다 이른 validity.notBefore를 가진 후보다 — "
                "이전 설정으로 되돌리는 활성화를 거부한다",
            )
    return None


def activate_mission_dispatch_file(
    dispatch_path: Path,
    *,
    consumer: MissionContractConsumer,
    registry: KeyRegistry,
    expected_edge_device_id: str,
    runtime_version: str,
    now: datetime | None = None,
) -> DispatchActivationResult:
    """Verify and activate one downloaded dispatch, or return its exact retry receipt.

    The outer envelope is verified before any local active state can change.
    Then, and only then, the unchanged upstream MissionContractConsumer verifies
    and atomically replaces the inner contract.  The native handoff is written
    last; a crash in between is fail-closed because C++ sees no new handoff.
    """
    effective_now = _effective_now(now)
    if not runtime_version:
        raise ValueError("runtime_version must not be empty")
    raw = _read_json_object(dispatch_path, label="MissionDispatchEnvelope candidate")
    verification = verify_mission_dispatch_envelope(
        raw,
        registry,
        expected_edge_device_id=expected_edge_device_id,
        now=effective_now,
    )
    if not verification.is_valid or verification.envelope is None:
        return DispatchActivationResult(
            dispatch_verdict=verification.verdict,
            activated=False,
            detail=verification.detail,
        )
    envelope = verification.envelope
    snapshot_path = _snapshot_path(consumer)
    native_snapshot_path = _native_snapshot_path(consumer)
    native_runtime_profile_path = _native_runtime_profile_path(consumer)
    # ``Path.exists`` is false for a broken symlink, so reject this separately
    # before changing the upstream active contract as well.
    if snapshot_path.is_symlink():
        raise ContractInputError("active dispatch snapshot path is a symlink")
    existing = _load_snapshot(snapshot_path)
    if existing is not None and _snapshot_matches_active_contract(
        existing,
        envelope,
        consumer,
        runtime_version=runtime_version,
        now=effective_now,
    ):
        # A previous activation may have crashed after the JSON record but
        # before its native companions. Recreate the profile first and publish
        # its activation marker last on an idempotent retry; no contract
        # verification is duplicated here.
        _write_native_runtime_profile_atomically(native_runtime_profile_path, existing)
        _write_native_snapshot_atomically(native_snapshot_path, existing)
        return DispatchActivationResult(
            dispatch_verdict=DispatchVerdict.VALID,
            activated=True,
            reused_activation=True,
            activation_receipt=ActivationReceiptV1(
                dispatch_id=existing.dispatch_id,
                edge_device_id=existing.edge_device_id,
                mission_id=existing.mission_id,
                mission_contract_digest=existing.mission_contract_digest,
                risk_policy_pack_digest=existing.risk_policy_pack_digest,
                activated_at=existing.activated_at,
                runtime_version=existing.runtime_version,
            ),
            active_snapshot_path=snapshot_path,
        )

    if existing is not None:
        rollback = _policy_rollback_detail(existing, envelope)
        if rollback is not None:
            verdict, detail = rollback
            return DispatchActivationResult(
                dispatch_verdict=verdict,
                activated=False,
                detail=detail,
            )

    raw_contract = raw.get("missionContract")
    raw_policy = raw.get("riskPolicyPack")
    raw_profile = raw.get("edgeRuntimeProfile")
    if (
        not isinstance(raw_contract, Mapping)
        or not isinstance(raw_policy, Mapping)
        or not isinstance(raw_profile, Mapping)
    ):
        # This should be unreachable after the typed verifier, but execution
        # state always chooses a typed refusal over an assert/no-op.
        return DispatchActivationResult(
            dispatch_verdict=DispatchVerdict.MALFORMED_DISPATCH,
            activated=False,
            detail="validated dispatch lost contract, policy, or runtime profile object",
        )
    # Do this *before* the upstream consumer atomically replaces the inner
    # contract.  If this attempt crashes or a later write fails, an absent
    # native record forces PSDK into capture-only rather than leaving the prior
    # dispatch usable beside a newer active Mission Contract.
    _invalidate_native_snapshot(native_snapshot_path)
    _invalidate_native_snapshot(
        native_runtime_profile_path,
        label="native Edge runtime profile handoff",
    )
    if not _activate_inner_contract(consumer, raw_contract, now=effective_now):
        return DispatchActivationResult(
            dispatch_verdict=DispatchVerdict.MISSION_CONTRACT_INVALID,
            activated=False,
            detail="upstream MissionContractConsumer rejected the inner contract",
        )
    snapshot = ActiveDispatchSnapshotV1(
        dispatch_id=envelope.dispatch_id,
        edge_device_id=envelope.edge_device_id,
        mission_id=envelope.mission_id,
        mission_contract_digest=envelope.mission_contract_digest,
        risk_policy_pack=copy.deepcopy(dict(raw_policy)),
        risk_policy_pack_digest=envelope.risk_policy_pack_digest,
        edge_runtime_profile=copy.deepcopy(dict(raw_profile)),
        edge_runtime_profile_digest=envelope.edge_runtime_profile_digest,
        validity=envelope.validity,
        activated_at=effective_now,
        runtime_version=runtime_version,
    )
    _write_snapshot_atomically(snapshot_path, snapshot)
    _write_native_runtime_profile_atomically(native_runtime_profile_path, snapshot)
    _write_native_snapshot_atomically(native_snapshot_path, snapshot)
    return DispatchActivationResult(
        dispatch_verdict=DispatchVerdict.VALID,
        activated=True,
        activation_receipt=ActivationReceiptV1(
            dispatch_id=envelope.dispatch_id,
            edge_device_id=envelope.edge_device_id,
            mission_id=envelope.mission_id,
            mission_contract_digest=envelope.mission_contract_digest,
            risk_policy_pack_digest=envelope.risk_policy_pack_digest,
            activated_at=effective_now,
            runtime_version=runtime_version,
        ),
        active_snapshot_path=snapshot_path,
    )


def _parse_now(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must be tz-aware RFC3339")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """Offline activation CLI; upload the returned receipt through Edge sync separately."""
    parser = argparse.ArgumentParser(
        description="Verify and activate an Edge MissionDispatchEnvelope"
    )
    parser.add_argument("--keys-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--edge-device-id", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--now", help="RFC3339 verification time for replay/HIL")
    parser.add_argument("dispatch", type=Path)
    args = parser.parse_args(argv)
    try:
        registry = load_verification_keys(args.keys_dir)
        result = activate_mission_dispatch_file(
            args.dispatch,
            consumer=MissionContractConsumer(registry=registry, state_dir=args.state_dir),
            registry=registry,
            expected_edge_device_id=args.edge_device_id,
            runtime_version=args.runtime_version,
            now=_parse_now(args.now),
        )
    except (ContractInputError, VerificationKeyError, ValueError) as exc:
        print(json.dumps({"verdict": "ACTIVATION_ERROR", "detail": str(exc)}, sort_keys=True))
        return 3
    body = {
        "dispatchVerdict": result.dispatch_verdict.value,
        "activated": result.activated,
        "reusedActivation": result.reused_activation,
        "activationReceipt": (
            result.activation_receipt.model_dump(by_alias=True, mode="json")
            if result.activation_receipt is not None
            else None
        ),
        "activeSnapshotPath": str(result.active_snapshot_path)
        if result.active_snapshot_path is not None
        else None,
        "detail": result.detail,
    }
    print(json.dumps(body, ensure_ascii=False, sort_keys=True))
    return 0 if result.activated else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ActiveDispatchSnapshotV1",
    "DispatchActivationResult",
    "activate_mission_dispatch_file",
    "main",
]
