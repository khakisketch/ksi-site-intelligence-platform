"""서명된 EdgeRuntimeProfile v1.0 배포 입력.

Mission Contract v1.2에는 모델/보정 *식별자*만 남긴다. 실제 TensorRT 입력,
카메라 보정, 등록 장비 형상은 이 별도 profile로만 전달하며, profile 자체의
digest는 Core가 서명하는 MissionDispatchEnvelope에 포함된다. 따라서 Edge가
경로·기본 크기·좌표계를 스스로 추정할 수 없다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ksi_mission_contracts.models import SiteFrame
from ksi_mission_contracts.risk_policy import EquipmentFootprint, PolicyValidity
from ksi_mission_contracts.signing import sha256_digest

_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_SHA256 = r"^sha256:[0-9a-f]{64}$"
_MAX_ONNX_BYTES = 1024 * 1024 * 1024
_MAX_ENGINE_BYTES = 2 * 1024 * 1024 * 1024
# The native adapter deliberately implements one preprocessing recipe only.
# A model export may not silently reuse the same tensor shape with a different
# image processor configuration: that would make a TensorRT engine appear
# registered while changing the pixels it actually sees.
TENSORRT_DFINE_PREPROCESSING_CONTRACT_V1 = "rtdetr-rgb-bilinear-1over255-v1"
TENSORRT_DFINE_DIFFERENTIAL_PROFILE_V1 = "ksi-dfine-tensorrt-onnx-semantic-v1"
_MAX_TENSORRT_DIFFERENTIAL_SAMPLES = 10_000
_MAX_TENSORRT_CONFIDENCE_ATOL = 1e-3
_MAX_TENSORRT_BBOX_ATOL_PX = 0.5


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


def _finite(value: float, *, label: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


class TensorRtTensorContractV1(_CamelModel):
    input_width: int = Field(ge=1, le=8192)
    input_height: int = Field(ge=1, le=8192)
    query_count: int = Field(ge=1, le=10_000)
    class_count: int = Field(ge=1, le=1_000)


class RegisteredEquipmentBindingV1(_CamelModel):
    """등록된 detector class → canonical equipment geometry binding.

    ``measuredDimensions``는 detector가 누락했을 때 쓰는 임의 기본값이 아니다.
    현장 보정 profile에 명시적으로 등록·서명된 물리 형상이며, mapping이 없으면
    native projector는 ``MISSING_DIMENSIONS``으로 drop한다.
    """

    source_class_id: int = Field(ge=0)
    source_class_name: str = Field(min_length=1)
    equipment_class: str = Field(min_length=1)
    measured_dimensions: EquipmentFootprint


class TensorRtDifferentialAttestationV1(_CamelModel):
    """Signed admission record for a TensorRT-vs-ONNX semantic comparison.

    ``evidenceDigest`` identifies the deterministic differential-evidence
    artifact produced by ``tools/edge/verify_tensorrt_differential.py``.  The
    profile binds it to the exact ONNX, preprocessing configuration and corpus
    used by the comparison.  The Edge does not manufacture this attestation;
    without one it remains capture-only even if TensorRT happens to be
    available on the device.
    """

    verification_profile_id: Literal["ksi-dfine-tensorrt-onnx-semantic-v1"]
    evidence_digest: str = Field(pattern=_SHA256)
    registered_onnx_digest: str = Field(pattern=_SHA256)
    preprocessing_contract_id: Literal["rtdetr-rgb-bilinear-1over255-v1"]
    preprocessing_config_digest: str = Field(pattern=_SHA256)
    corpus_id: str = Field(pattern=_SAFE_ID)
    corpus_digest: str = Field(pattern=_SHA256)
    sample_count: int = Field(ge=10, le=_MAX_TENSORRT_DIFFERENTIAL_SAMPLES)
    status: Literal["PASS"]
    confidence_atol: float = Field(gt=0, le=_MAX_TENSORRT_CONFIDENCE_ATOL)
    bbox_atol_px: float = Field(gt=0, le=_MAX_TENSORRT_BBOX_ATOL_PX)

    @model_validator(mode="after")
    def _finite_tolerances(self) -> TensorRtDifferentialAttestationV1:
        _finite(self.confidence_atol, label="tensorRtDifferential.confidenceAtol")
        _finite(self.bbox_atol_px, label="tensorRtDifferential.bboxAtolPx")
        return self


class DfineModelProfileV1(_CamelModel):
    model_pack_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    onnx_artifact_id: str = Field(pattern=_SAFE_ID)
    registered_onnx_digest: str = Field(pattern=_SHA256)
    engine_artifact_id: str = Field(pattern=_SAFE_ID)
    max_onnx_bytes: int = Field(ge=1, le=_MAX_ONNX_BYTES)
    max_engine_bytes: int = Field(ge=1, le=_MAX_ENGINE_BYTES)
    workspace_bytes: int = Field(ge=1, le=_MAX_ENGINE_BYTES)
    tensor_contract: TensorRtTensorContractV1
    class_bindings: list[RegisteredEquipmentBindingV1] = Field(min_length=1)
    score_threshold: float = Field(ge=0, le=1)
    top_k: int = Field(ge=1)
    ontology_version: str = Field(min_length=1)
    source_taxonomy: str = Field(min_length=1)
    tensor_rt_differential: TensorRtDifferentialAttestationV1

    @model_validator(mode="after")
    def _validate_closed_detector_mapping(self) -> DfineModelProfileV1:
        _finite(self.score_threshold, label="model.scoreThreshold")
        ids = [binding.source_class_id for binding in self.class_bindings]
        names = [binding.source_class_name for binding in self.class_bindings]
        if len(ids) != len(set(ids)) or len(names) != len(set(names)):
            raise ValueError("model.classBindings source class IDs and names must be unique")
        output_count = self.tensor_contract.query_count * self.tensor_contract.class_count
        if self.top_k > output_count:
            raise ValueError("model.topK cannot exceed the registered output element count")
        if (
            self.tensor_rt_differential.registered_onnx_digest
            != self.registered_onnx_digest
        ):
            raise ValueError(
                "model.tensorRtDifferential.registeredOnnxDigest must equal "
                "model.registeredOnnxDigest"
            )
        return self


class Vector3V1(_CamelModel):
    x: float
    y: float
    z: float

    @model_validator(mode="after")
    def _finite_values(self) -> Vector3V1:
        for name in ("x", "y", "z"):
            _finite(getattr(self, name), label=f"vector.{name}")
        return self


class UnitQuaternionV1(_CamelModel):
    w: float
    x: float
    y: float
    z: float

    @model_validator(mode="after")
    def _normalized(self) -> UnitQuaternionV1:
        for name in ("w", "x", "y", "z"):
            _finite(getattr(self, name), label=f"quaternion.{name}")
        norm = math.sqrt(self.w * self.w + self.x * self.x + self.y * self.y + self.z * self.z)
        if not math.isfinite(norm) or abs(norm - 1.0) > 1e-6:
            raise ValueError("cameraToGimbal must be a unit quaternion")
        return self


class Wgs84OriginV1(_CamelModel):
    latitude_rad: float = Field(ge=-math.pi / 2.0, le=math.pi / 2.0)
    longitude_rad: float = Field(ge=-math.pi, le=math.pi)
    altitude_m: float

    @model_validator(mode="after")
    def _finite_values(self) -> Wgs84OriginV1:
        _finite(self.latitude_rad, label="wgs84Origin.latitudeRad")
        _finite(self.longitude_rad, label="wgs84Origin.longitudeRad")
        _finite(self.altitude_m, label="wgs84Origin.altitudeM")
        return self


class EnuToSiteTransformV1(_CamelModel):
    """Explicit rigid ENU→Mission site-frame mapping in metres.

    Merely naming an EPSG CRS does not transform a WGS84 position.  The profile
    therefore carries an audited rigid local mapping and rejects reflections,
    scale, shear, and non-finite matrix entries before native code sees it.
    """

    rotation: list[list[float]] = Field(min_length=3, max_length=3)
    translation_m: Vector3V1

    @model_validator(mode="after")
    def _proper_rotation(self) -> EnuToSiteTransformV1:
        if any(len(row) != 3 for row in self.rotation):
            raise ValueError("enuToSite.rotation must be a 3x3 matrix")
        rows = [
            [_finite(value, label="enuToSite.rotation") for value in row]
            for row in self.rotation
        ]
        for row in rows:
            if abs(sum(value * value for value in row) - 1.0) > 1e-6:
                raise ValueError("enuToSite.rotation rows must be unit length")
        for left in range(3):
            for right in range(left + 1, 3):
                if abs(sum(rows[left][index] * rows[right][index] for index in range(3))) > 1e-6:
                    raise ValueError("enuToSite.rotation rows must be orthogonal")
        determinant = (
            rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
            - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
            + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0])
        )
        if abs(determinant - 1.0) > 1e-6:
            raise ValueError("enuToSite.rotation must be a proper rotation")
        return self


class CameraIntrinsicsV1(_CamelModel):
    reference_width: int = Field(ge=1, le=16_384)
    reference_height: int = Field(ge=1, le=16_384)
    focal_x_px: float = Field(gt=0)
    focal_y_px: float = Field(gt=0)
    principal_x_px: float = Field(ge=0)
    principal_y_px: float = Field(ge=0)

    @model_validator(mode="after")
    def _inside_reference_image(self) -> CameraIntrinsicsV1:
        for name in ("focal_x_px", "focal_y_px", "principal_x_px", "principal_y_px"):
            _finite(getattr(self, name), label=f"intrinsics.{name}")
        if (
            self.principal_x_px >= self.reference_width
            or self.principal_y_px >= self.reference_height
        ):
            raise ValueError("camera principal point must be inside the reference image")
        return self


class GroundPlaneCalibrationV1(_CamelModel):
    calibration_profile_id: str = Field(min_length=1)
    site_frame: SiteFrame
    wgs84_origin: Wgs84OriginV1
    enu_to_site: EnuToSiteTransformV1
    ground_plane_up_m: float
    intrinsics: CameraIntrinsicsV1
    # Rotates the conventional camera optical frame (x right, y down, z forward)
    # into the DJI gimbal frame. This convention is an explicit profile input;
    # an unknown mount never receives an identity replacement.
    camera_to_gimbal: UnitQuaternionV1
    camera_offset_in_gimbal_m: Vector3V1
    position_sigma_m: float = Field(ge=0)
    angular_sigma_rad: float = Field(ge=0)
    pixel_sigma_px: float = Field(gt=0)
    max_pose_age_ms: int = Field(ge=1, le=10_000)

    @model_validator(mode="after")
    def _finite_uncertainty(self) -> GroundPlaneCalibrationV1:
        for name in (
            "ground_plane_up_m",
            "position_sigma_m",
            "angular_sigma_rad",
            "pixel_sigma_px",
        ):
            _finite(getattr(self, name), label=f"calibration.{name}")
        return self


class SensorTimingRequirementV1(_CamelModel):
    # Receive-time correlation cannot be elevated to a world/risk observation.
    require_sensor_alignment: Literal[True] = True
    max_alignment_ms: int = Field(ge=1, le=1_000)


class EdgeRuntimeProfileV1(_CamelModel):
    """``contracts/schemas/edge-runtime-profile.v1.json`` 대응 모델."""

    schema_version: Literal["1.0"] = "1.0"
    edge_runtime_profile_id: str = Field(pattern=_SAFE_ID)
    validity: PolicyValidity
    site_id: str = Field(min_length=1)
    model: DfineModelProfileV1
    calibration: GroundPlaneCalibrationV1
    timing: SensorTimingRequirementV1


def edge_runtime_profile_wire_dict(profile: EdgeRuntimeProfileV1) -> dict[str, Any]:
    return profile.model_dump(by_alias=True, mode="json")


def edge_runtime_profile_digest(profile: EdgeRuntimeProfileV1 | Mapping[str, Any]) -> str:
    payload: Mapping[str, Any]
    if isinstance(profile, EdgeRuntimeProfileV1):
        payload = edge_runtime_profile_wire_dict(profile)
    else:
        payload = profile
    return sha256_digest(canonical_json_bytes(payload))


__all__ = [
    "CameraIntrinsicsV1",
    "DfineModelProfileV1",
    "EnuToSiteTransformV1",
    "EdgeRuntimeProfileV1",
    "GroundPlaneCalibrationV1",
    "RegisteredEquipmentBindingV1",
    "SensorTimingRequirementV1",
    "TensorRtDifferentialAttestationV1",
    "TENSORRT_DFINE_DIFFERENTIAL_PROFILE_V1",
    "TENSORRT_DFINE_PREPROCESSING_CONTRACT_V1",
    "TensorRtTensorContractV1",
    "UnitQuaternionV1",
    "Vector3V1",
    "Wgs84OriginV1",
    "edge_runtime_profile_digest",
    "edge_runtime_profile_wire_dict",
]
