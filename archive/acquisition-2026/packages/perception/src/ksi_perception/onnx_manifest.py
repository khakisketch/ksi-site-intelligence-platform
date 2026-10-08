"""Versioned ONNX Export Manifest — typed 신뢰 경계 (재검토 P1, 2026-07-28).

이전 로더는 필드 **존재**만 확인하고 ``int(manifest["opset"])``·``i["name"]`` 를
예외 보호 밖에서 썼다 — 타입이 틀린 manifest 가 typed 결과 대신 raw traceback
으로 새는 경로다. 이 모듈이 그 경계를 pydantic 모델(extra="forbid")로 닫는다:
**생성(export)과 로드가 같은 모델을 공유**하므로 두 쪽의 계약이 어긋날 수 없다.

## dtype 은 canonical enum 이다 (substring 비교 금지)

"float" 부분 문자열 비교는 float64 주장과 float32 실물을 같게 본다 — canonical
값("float32" 등)과 torch/onnxruntime 표기의 **명시적 대응표**로만 변환·비교한다.

## 알려지지 않은 필드 정책

schema v1 은 ``extra="forbid"`` — 미지의 필드가 있는 manifest 는 v1 이 아니다.
필드 추가는 schema 버전 증가로만 한다(계보 문서의 의미가 조용히 확장되지 않게).
"""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MANIFEST_SCHEMA_V1 = "ksi-onnx-export-manifest/1"

_HEX64 = r"^[0-9a-f]{64}$"


class TensorDtype(StrEnum):
    """canonical dtype — torch/onnxruntime 표기와의 대응은 아래 표가 유일 경로다."""

    FLOAT32 = "float32"
    FLOAT16 = "float16"
    INT64 = "int64"


# torch 표기 → canonical (export 시 기록용)
TORCH_DTYPE_TO_CANONICAL: dict[str, TensorDtype] = {
    "torch.float32": TensorDtype.FLOAT32,
    "torch.float16": TensorDtype.FLOAT16,
    "torch.int64": TensorDtype.INT64,
}

# canonical → onnxruntime 표기 (세션 실계약 대조용)
CANONICAL_TO_ORT: dict[TensorDtype, str] = {
    TensorDtype.FLOAT32: "tensor(float)",
    TensorDtype.FLOAT16: "tensor(float16)",
    TensorDtype.INT64: "tensor(int64)",
}

# onnxruntime 표기 → canonical (export 시 실세션 값 기록용)
ORT_TO_CANONICAL: dict[str, TensorDtype] = {v: k for k, v in CANONICAL_TO_ORT.items()}


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("공백 문자열 불허")
    return value


class _TensorContractBase(BaseModel):
    """입력·출력 텐서 계약의 공통부 — name/shape/dtype 셋과 그 검증 규칙.

    입력(``axes``)·출력(``meaning``) 전용 필드만 하위 클래스가 각자 더한다.
    pydantic 의 ``field_validator`` 는 필드별로 그 필드를 선언한 클래스에 달아야
    하므로, 그 마지막 한 필드의 "공백 거부" 검증만은 하위 클래스에 남는다 —
    본문은 :func:`_require_nonblank` 하나로 공유한다.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    shape: list[int] = Field(min_length=1)
    # dtype 만 값 기반 수용(strict=False) — JSON 의 "float32" 문자열을 Enum 값으로
    # 받되, 미지원 값("float64" 등)은 여전히 거부된다.
    dtype: TensorDtype = Field(strict=False)

    @field_validator("name")
    @classmethod
    def _nonblank_name(cls, value: str) -> str:
        return _require_nonblank(value)

    @field_validator("shape")
    @classmethod
    def _positive_int_dims(cls, value: list[int]) -> list[int]:
        for dim in value:
            # bool 은 int subclass — 차원으로 위장 금지.
            if isinstance(dim, bool) or not isinstance(dim, int) or dim <= 0:
                raise ValueError(f"차원은 bool 아닌 양의 int 여야 한다 ({dim!r})")
        return value


class OnnxTensorContract(_TensorContractBase):
    """입력 텐서 계약 — 이름·shape·dtype·축 정책."""

    axes: str = Field(min_length=1)

    @field_validator("axes")
    @classmethod
    def _nonblank_axes(cls, value: str) -> str:
        return _require_nonblank(value)


class OnnxOutputContract(_TensorContractBase):
    """출력 텐서 계약 — shape·dtype 은 추정이 아니라 **실제 세션에서 읽은 값**이다."""

    meaning: str = Field(min_length=1)

    @field_validator("meaning")
    @classmethod
    def _nonblank_meaning(cls, value: str) -> str:
        return _require_nonblank(value)


class OnnxExportManifestV1(BaseModel):
    """schema v1 manifest — 생성·로드 공용 typed 계약.

    검증 실패는 pydantic ValidationError 로 모이며, 로더가 이를 typed
    OnnxDetectorLoadResult 로 변환한다(예외 전파 금지).
    """

    # strict: lax coercion(bool→int, int→str …) 차단 — A2/shape-bool 실측 반증.
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_: str = Field(alias="schema")
    model_id: str = Field(min_length=1)
    source_artifact_digests: dict[str, str] = Field(min_length=1)
    versions: dict[str, str] = Field(min_length=1)
    exporter: str = Field(min_length=1)
    opset: int
    inputs: list[OnnxTensorContract] = Field(min_length=1)
    outputs: list[OnnxOutputContract] = Field(min_length=1)
    preprocessing: str = Field(min_length=1)
    postprocessing: str = Field(min_length=1)
    graph_transforms: list[str] = Field(min_length=1)
    graph_transform_fix_count: int
    export_command: str = Field(min_length=1)
    onnx_sha256: str = Field(pattern=_HEX64)
    operator: str = Field(min_length=1)
    exported_at_utc: str = Field(min_length=1)

    @field_validator("schema_")
    @classmethod
    def _schema_exact(cls, value: str) -> str:
        if value != MANIFEST_SCHEMA_V1:
            raise ValueError(f"미지원 schema {value!r} (지원: {MANIFEST_SCHEMA_V1!r})")
        return value

    @field_validator("source_artifact_digests")
    @classmethod
    def _digests_hex64(cls, value: dict[str, str]) -> dict[str, str]:
        import re

        for name, digest in value.items():
            if not name.strip():
                raise ValueError("digest 파일명이 공백이다")
            if not isinstance(digest, str) or not re.fullmatch(_HEX64, digest):
                raise ValueError(f"{name} 의 digest 가 hex64 가 아니다 ({digest!r})")
        return value

    @field_validator("versions")
    @classmethod
    def _versions_nonblank(cls, value: dict[str, str]) -> dict[str, str]:
        required = {"python", "torch", "transformers", "onnx", "onnxruntime"}
        missing = required - set(value)
        if missing:
            raise ValueError(f"필수 도구 버전 누락: {sorted(missing)}")
        for tool, version in value.items():
            if not isinstance(version, str) or not version.strip():
                raise ValueError(f"{tool} 버전이 공백/비문자열이다 ({version!r})")
        return value

    @field_validator("opset")
    @classmethod
    def _opset_positive_int(cls, value: int) -> int:
        if isinstance(value, bool) or value <= 0:
            raise ValueError(f"opset 은 bool 아닌 양의 int 여야 한다 ({value!r})")
        return value

    @field_validator("graph_transform_fix_count")
    @classmethod
    def _fix_count_nonnegative(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError(f"fix_count 는 bool 아닌 0 이상 int 여야 한다 ({value!r})")
        return value

    @field_validator("graph_transforms")
    @classmethod
    def _transforms_nonblank(cls, value: list[str]) -> list[str]:
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"graph_transform 항목이 공백/비문자열이다 ({item!r})")
        return value

    @field_validator("operator")
    @classmethod
    def _operator_meaningful(cls, value: str) -> str:
        if not value.strip() or value.strip() == "unspecified":
            raise ValueError("operator 는 공백/'unspecified' 일 수 없다")
        return value

    @field_validator("exported_at_utc")
    @classmethod
    def _utc_parseable(cls, value: str) -> str:
        from datetime import datetime, timedelta

        parsed = datetime.fromisoformat(value)  # 실패 시 ValueError → ValidationError
        if parsed.utcoffset() != timedelta(0):
            raise ValueError(f"UTC 가 아니다 (offset={parsed.utcoffset()})")
        return value

    @model_validator(mode="after")
    def _tensor_names_unique(self) -> OnnxExportManifestV1:
        input_names = [t.name for t in self.inputs]
        output_names = [t.name for t in self.outputs]
        if len(set(input_names)) != len(input_names):
            raise ValueError(f"입력 이름 중복: {input_names}")
        if len(set(output_names)) != len(output_names):
            raise ValueError(f"출력 이름 중복: {output_names}")
        return self


def reject_nonstandard_json_constant(value: str) -> None:
    """json.loads(parse_constant=...) 훅 — NaN/Infinity 는 표준 JSON 이 아니다."""
    raise ValueError(f"비표준 JSON 상수 {value!r} 불허 (NaN/Infinity)")


def is_finite_number(value: object) -> bool:
    """bool 을 숫자로 위장시키지 않는 finite 검사."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
