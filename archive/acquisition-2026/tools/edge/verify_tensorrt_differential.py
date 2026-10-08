"""Create or audit the D-FINE TensorRT-versus-ONNX semantic evidence artifact.

The normal path is intentionally two-process and reproducible:

1. this host tool validates a signed-profile-shaped candidate, an ONNX digest,
   a pinned RTDetr preprocessor config, and a raw-RGB corpus;
2. it invokes ``tensorrt_differential_runner`` (C++/TensorRT) with exactly
   those profile values; and
3. it independently runs ONNX Runtime with the native RGB bilinear+1/255
   recipe, compares class/confidence/bbox/typed drops, and writes canonical
   evidence whose digest is placed in the profile before Core signs it.

It is an offline replay/oracle tool only.  It never runs in the PSDK callback,
never sends a flight command, and cannot make a hardware or production claim.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_mission_contracts.runtime_profile import (
    TENSORRT_DFINE_DIFFERENTIAL_PROFILE_V1,
    TENSORRT_DFINE_PREPROCESSING_CONTRACT_V1,
    EdgeRuntimeProfileV1,
)
from ksi_mission_contracts.signing import sha256_digest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_SHA256 = r"^sha256:[0-9a-f]{64}$"
_RUNNER_VERSION = "ksi-tensorrt-dfine-runner-v1"
_DROP_REASONS = (
    "SCORE_BELOW_THRESHOLD",
    "UNKNOWN_CLASS",
    "NON_FINITE_TENSOR",
    "MALFORMED_TENSOR",
)


class DifferentialFailure(ValueError):
    """A typed offline-gate rejection; no partial PASS artifact is emitted."""


class _StrictCamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", strict=True
    )


def _finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


class RawRgbCorpusSampleV1(_StrictCamelModel):
    sample_id: str = Field(pattern=_SAFE_ID)
    width: int = Field(ge=1, le=16_384)
    height: int = Field(ge=1, le=16_384)
    rgb_file: str = Field(min_length=1)
    rgb_digest: str = Field(pattern=_SHA256)

    @field_validator("rgb_file")
    @classmethod
    def _relative_rgb_file(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("rgbFile must use a safe POSIX-relative path")
        path = Path(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("rgbFile must be a safe relative path")
        return value


class RawRgbCorpusV1(_StrictCamelModel):
    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(pattern=_SAFE_ID)
    samples: list[RawRgbCorpusSampleV1] = Field(min_length=10, max_length=10_000)

    @model_validator(mode="after")
    def _unique_sample_ids(self) -> RawRgbCorpusV1:
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("raw RGB corpus sampleId values must be unique")
        return self


class TensorContractReportV1(_StrictCamelModel):
    input_width: int = Field(ge=1, le=8192)
    input_height: int = Field(ge=1, le=8192)
    query_count: int = Field(ge=1, le=10_000)
    class_count: int = Field(ge=1, le=1_000)


class TensorRtDetectionReportV1(_StrictCamelModel):
    query_index: int = Field(ge=0)
    class_id: int = Field(ge=0)
    class_name: str = Field(min_length=1)
    confidence: float
    box: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def _finite_detection(self) -> TensorRtDetectionReportV1:
        _finite(self.confidence, "detection.confidence")
        for value in self.box:
            _finite(value, "detection.box")
        return self


class TensorRtSampleReportV1(_StrictCamelModel):
    sample_id: str = Field(pattern=_SAFE_ID)
    width: int = Field(ge=1, le=16_384)
    height: int = Field(ge=1, le=16_384)
    rgb_digest: str = Field(pattern=_SHA256)
    preprocessed_input_digest: str = Field(pattern=_SHA256)
    detections: list[TensorRtDetectionReportV1]
    drops: dict[str, int]

    @model_validator(mode="after")
    def _exact_typed_drops(self) -> TensorRtSampleReportV1:
        if set(self.drops) != set(_DROP_REASONS) or any(
            isinstance(value, bool) or value < 0 for value in self.drops.values()
        ):
            raise ValueError("drops must contain every typed D-FINE drop reason exactly once")
        return self


class TensorRtRunnerReportV1(_StrictCamelModel):
    schema_version: Literal["1.0"] = "1.0"
    runner_version: Literal["ksi-tensorrt-dfine-runner-v1"]
    registered_onnx_digest: str = Field(pattern=_SHA256)
    preprocessing_contract_id: Literal["rtdetr-rgb-bilinear-1over255-v1"]
    tensor_contract: TensorContractReportV1
    score_threshold: float
    top_k: int = Field(ge=1)
    samples: list[TensorRtSampleReportV1] = Field(min_length=10, max_length=10_000)

    @model_validator(mode="after")
    def _finite_and_unique(self) -> TensorRtRunnerReportV1:
        _finite(self.score_threshold, "runner.scoreThreshold")
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("runner sampleId values must be unique")
        return self


@dataclass(frozen=True, slots=True)
class OracleDetection:
    query_index: int
    class_id: int
    class_name: str
    confidence: float
    box: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class OracleSample:
    sample_id: str
    width: int
    height: int
    rgb_digest: str
    preprocessed_input_digest: str
    detections: tuple[OracleDetection, ...]
    drops: dict[str, int]


def _reject_json_constant(value: str) -> NoReturn:
    raise DifferentialFailure(f"non-standard JSON constant rejected: {value!r}")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DifferentialFailure) as exc:
        raise DifferentialFailure(f"cannot read JSON artifact {path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DifferentialFailure(f"JSON artifact {path.name} must be an object")
    return raw


def load_raw_rgb_corpus(path: Path) -> RawRgbCorpusV1:
    try:
        return RawRgbCorpusV1.model_validate(_load_json_object(path))
    except ValueError as exc:
        raise DifferentialFailure(f"raw RGB corpus rejected: {exc}") from exc


def corpus_digest(corpus: RawRgbCorpusV1) -> str:
    return sha256_digest(canonical_json_bytes(corpus.model_dump(by_alias=True, mode="json")))


def _resolve_corpus_sample(corpus_path: Path, sample: RawRgbCorpusSampleV1) -> tuple[Path, bytes]:
    corpus_root = corpus_path.parent.resolve()
    candidate = corpus_root / sample.rgb_file
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DifferentialFailure(f"RGB sample {sample.sample_id} is unreadable") from exc
    if not resolved.is_relative_to(corpus_root) or candidate.is_symlink() or not resolved.is_file():
        raise DifferentialFailure(f"RGB sample {sample.sample_id} escapes the corpus directory")
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise DifferentialFailure(f"RGB sample {sample.sample_id} cannot be read") from exc
    expected_size = sample.width * sample.height * 3
    if len(data) != expected_size:
        raise DifferentialFailure(
            f"RGB sample {sample.sample_id} byte size {len(data)} != {expected_size}"
        )
    actual_digest = sha256_digest(data)
    if actual_digest != sample.rgb_digest:
        raise DifferentialFailure(f"RGB sample {sample.sample_id} digest mismatch")
    return resolved, data


def _b64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).rstrip(b"=").decode("ascii")


def _write_private_sample_list(
    path: Path, corpus_path: Path, corpus: RawRgbCorpusV1
) -> dict[str, bytes]:
    lines = ["KSI_TENSORRT_RAW_RGB_SAMPLES_V1"]
    rgb_bytes: dict[str, bytes] = {}
    for sample in corpus.samples:
        resolved, data = _resolve_corpus_sample(corpus_path, sample)
        rgb_bytes[sample.sample_id] = data
        lines.append(
            "\t".join(
                (
                    _b64url(sample.sample_id),
                    str(sample.width),
                    str(sample.height),
                    _b64url(str(resolved)),
                    sample.rgb_digest,
                )
            )
        )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return rgb_bytes


def _load_profile(path: Path) -> EdgeRuntimeProfileV1:
    try:
        return EdgeRuntimeProfileV1.model_validate(_load_json_object(path))
    except ValueError as exc:
        raise DifferentialFailure(f"runtime profile rejected: {exc}") from exc


def _file_sha256(path: Path, label: str) -> str:
    try:
        return sha256_digest(path.read_bytes())
    except OSError as exc:
        raise DifferentialFailure(f"{label} cannot be read") from exc


def _validate_inputs(
    profile: EdgeRuntimeProfileV1,
    corpus: RawRgbCorpusV1,
    onnx_path: Path,
    preprocessing_config: Path,
) -> None:
    model = profile.model
    attestation = model.tensor_rt_differential
    if attestation.verification_profile_id != TENSORRT_DFINE_DIFFERENTIAL_PROFILE_V1:
        raise DifferentialFailure("unsupported TensorRT differential verification profile")
    if attestation.preprocessing_contract_id != TENSORRT_DFINE_PREPROCESSING_CONTRACT_V1:
        raise DifferentialFailure("unsupported native preprocessing contract")
    if attestation.corpus_id != corpus.corpus_id:
        raise DifferentialFailure("profile TensorRT corpusId does not match supplied corpus")
    if attestation.corpus_digest != corpus_digest(corpus):
        raise DifferentialFailure("profile TensorRT corpusDigest does not match supplied corpus")
    if attestation.sample_count != len(corpus.samples):
        raise DifferentialFailure("profile TensorRT sampleCount does not match supplied corpus")
    if _file_sha256(onnx_path, "ONNX") != model.registered_onnx_digest:
        raise DifferentialFailure("ONNX bytes do not match profile registeredOnnxDigest")
    if (
        _file_sha256(preprocessing_config, "preprocessing config")
        != attestation.preprocessing_config_digest
    ):
        raise DifferentialFailure("preprocessing config bytes do not match signed profile")


def _runner_command(
    runner: Path,
    profile: EdgeRuntimeProfileV1,
    onnx_path: Path,
    engine_vault_directory: Path,
    sample_list: Path,
) -> list[str]:
    model = profile.model
    command = [
        str(runner),
        "--onnx",
        str(onnx_path),
        "--registered-onnx-digest",
        model.registered_onnx_digest,
        "--engine-artifact-id",
        model.engine_artifact_id,
        "--engine-vault-dir",
        str(engine_vault_directory),
        "--max-onnx-bytes",
        str(model.max_onnx_bytes),
        "--max-engine-bytes",
        str(model.max_engine_bytes),
        "--workspace-bytes",
        str(model.workspace_bytes),
        "--input-width",
        str(model.tensor_contract.input_width),
        "--input-height",
        str(model.tensor_contract.input_height),
        "--query-count",
        str(model.tensor_contract.query_count),
        "--class-count",
        str(model.tensor_contract.class_count),
        "--score-threshold",
        repr(model.score_threshold),
        "--top-k",
        str(model.top_k),
    ]
    for binding in sorted(model.class_bindings, key=lambda item: item.source_class_id):
        command.extend(
            ("--class-binding", f"{binding.source_class_id}:{_b64url(binding.source_class_name)}")
        )
    command.extend(("--samples", str(sample_list)))
    return command


def _run_runner(command: Sequence[str], timeout_seconds: int) -> TensorRtRunnerReportV1:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DifferentialFailure(f"TensorRT runner did not complete: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "no typed runner verdict"
        raise DifferentialFailure(f"TensorRT runner rejected execution: {detail}")
    try:
        raw = json.loads(completed.stdout, parse_constant=_reject_json_constant)
        return TensorRtRunnerReportV1.model_validate(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise DifferentialFailure(f"TensorRT runner report rejected: {exc}") from exc


def _validate_runner_metadata(
    profile: EdgeRuntimeProfileV1, report: TensorRtRunnerReportV1
) -> None:
    model = profile.model
    contract = report.tensor_contract
    expected = model.tensor_contract
    if report.registered_onnx_digest != model.registered_onnx_digest:
        raise DifferentialFailure("runner report ONNX digest is not the signed model digest")
    if report.preprocessing_contract_id != TENSORRT_DFINE_PREPROCESSING_CONTRACT_V1:
        raise DifferentialFailure("runner report preprocessing contract mismatch")
    if (
        contract.input_width != expected.input_width
        or contract.input_height != expected.input_height
        or contract.query_count != expected.query_count
        or contract.class_count != expected.class_count
        or report.top_k != model.top_k
        or not math.isclose(report.score_threshold, model.score_threshold, abs_tol=1e-7)
    ):
        raise DifferentialFailure("runner report tensor/postprocess contract differs from profile")


def _preprocess_rgb_bilinear_1over255(
    rgb_bytes: bytes, width: int, height: int, target_width: int, target_height: int
) -> Any:
    """Exact native algorithm expressed with float64 interpolation then f32 NCHW.

    ``tensorrt.cpp`` samples pixel centers, clamps source indices, interpolates
    in C++ double and only then casts to float.  This function follows that
    sequence—not Pillow/transformers resize defaults—so the input digest makes
    preprocessing drift observable before model-output comparison.
    """
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - workspace requires numpy
        raise DifferentialFailure("numpy is required for the ONNX oracle") from exc
    image = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(height, width, 3)
    source_x = (np.arange(target_width, dtype=np.float64) + 0.5) * width / target_width - 0.5
    source_y = (np.arange(target_height, dtype=np.float64) + 0.5) * height / target_height - 0.5
    x_floor = np.floor(source_x).astype(np.int64)
    y_floor = np.floor(source_y).astype(np.int64)
    x0 = np.clip(x_floor, 0, width - 1)
    x1 = np.clip(x_floor + 1, 0, width - 1)
    y0 = np.clip(y_floor, 0, height - 1)
    y1 = np.clip(y_floor + 1, 0, height - 1)
    wx = source_x - x_floor
    wy = source_y - y_floor
    output = np.empty((1, 3, target_height, target_width), dtype="<f4")
    for channel in range(3):
        upper = (
            image[y0[:, None], x0[None, :], channel] * (1.0 - wx)[None, :]
            + image[y0[:, None], x1[None, :], channel] * wx[None, :]
        )
        lower = (
            image[y1[:, None], x0[None, :], channel] * (1.0 - wx)[None, :]
            + image[y1[:, None], x1[None, :], channel] * wx[None, :]
        )
        output[0, channel] = ((upper * (1.0 - wy)[:, None] + lower * wy[:, None]) / 255.0).astype(
            "<f4"
        )
    return output


def _sigmoid_float32(value: Any) -> float:
    import numpy as np

    with np.errstate(over="ignore", under="ignore"):
        if value >= np.float32(0.0):
            exp_value = np.exp(np.float32(-value))
            return float(np.float32(1.0) / (np.float32(1.0) + exp_value))
        exp_value = np.exp(value)
        return float(exp_value / (np.float32(1.0) + exp_value))


def _onnx_postprocess(
    logits: Any,
    boxes: Any,
    *,
    sample: RawRgbCorpusSampleV1,
    profile: EdgeRuntimeProfileV1,
    input_digest: str,
) -> OracleSample:
    import numpy as np

    contract = profile.model.tensor_contract
    if (
        logits.dtype != np.dtype("float32")
        or boxes.dtype != np.dtype("float32")
        or logits.shape != (1, contract.query_count, contract.class_count)
        or boxes.shape != (1, contract.query_count, 4)
    ):
        raise DifferentialFailure(f"ONNX output tensor contract mismatch for {sample.sample_id}")
    drops = {reason: 0 for reason in _DROP_REASONS}
    candidates: list[tuple[float, int]] = []
    flattened = logits.reshape(-1)
    for index, logit in enumerate(flattened):
        if not np.isfinite(logit):
            drops["NON_FINITE_TENSOR"] += 1
            continue
        candidates.append((_sigmoid_float32(logit), index))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    taxonomy = {
        binding.source_class_id: binding.source_class_name
        for binding in profile.model.class_bindings
    }
    detections: list[OracleDetection] = []
    for score, flat_index in candidates[: profile.model.top_k]:
        if score <= profile.model.score_threshold:
            drops["SCORE_BELOW_THRESHOLD"] += 1
            continue
        query_index, class_id = divmod(flat_index, contract.class_count)
        class_name = taxonomy.get(class_id)
        if class_name is None:
            drops["UNKNOWN_CLASS"] += 1
            continue
        box = boxes[0, query_index]
        if not np.isfinite(box).all():
            drops["NON_FINITE_TENSOR"] += 1
            continue
        x_center = np.float32(box[0] * np.float32(sample.width))
        y_center = np.float32(box[1] * np.float32(sample.height))
        box_width = np.float32(box[2] * np.float32(sample.width))
        box_height = np.float32(box[3] * np.float32(sample.height))
        detections.append(
            OracleDetection(
                query_index=query_index,
                class_id=class_id,
                class_name=class_name,
                confidence=score,
                box=(
                    float(np.float32(x_center - box_width / np.float32(2.0))),
                    float(np.float32(y_center - box_height / np.float32(2.0))),
                    float(np.float32(x_center + box_width / np.float32(2.0))),
                    float(np.float32(y_center + box_height / np.float32(2.0))),
                ),
            )
        )
    return OracleSample(
        sample_id=sample.sample_id,
        width=sample.width,
        height=sample.height,
        rgb_digest=sample.rgb_digest,
        preprocessed_input_digest=input_digest,
        detections=tuple(detections),
        drops=drops,
    )


def _run_onnx_oracle(
    profile: EdgeRuntimeProfileV1,
    onnx_path: Path,
    corpus: RawRgbCorpusV1,
    rgb_bytes: Mapping[str, bytes],
) -> tuple[dict[str, OracleSample], dict[str, Any]]:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise DifferentialFailure(
            "onnxruntime is required for the TensorRT differential oracle"
        ) from exc
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_names = [item.name for item in session.get_inputs()]
    if input_names != ["pixel_values"]:
        raise DifferentialFailure(f"ONNX input contract mismatch: {input_names}")
    output_names = [item.name for item in session.get_outputs()]
    if set(output_names) != {"logits", "pred_boxes"}:
        raise DifferentialFailure(f"ONNX output contract mismatch: {output_names}")
    outputs: dict[str, OracleSample] = {}
    serialized_samples: list[dict[str, Any]] = []
    for sample in corpus.samples:
        pixel_values = _preprocess_rgb_bilinear_1over255(
            rgb_bytes[sample.sample_id],
            sample.width,
            sample.height,
            profile.model.tensor_contract.input_width,
            profile.model.tensor_contract.input_height,
        )
        input_digest = sha256_digest(pixel_values.tobytes(order="C"))
        logits, boxes = session.run(["logits", "pred_boxes"], {"pixel_values": pixel_values})
        result = _onnx_postprocess(
            logits,
            boxes,
            sample=sample,
            profile=profile,
            input_digest=input_digest,
        )
        outputs[sample.sample_id] = result
        serialized_samples.append(_oracle_sample_wire(result))
    return outputs, {
        "schemaVersion": "1.0",
        "oracle": "ksi-onnxruntime-native-preprocess-v1",
        "registeredOnnxDigest": profile.model.registered_onnx_digest,
        "preprocessingContractId": TENSORRT_DFINE_PREPROCESSING_CONTRACT_V1,
        "samples": serialized_samples,
    }


def _oracle_sample_wire(sample: OracleSample) -> dict[str, Any]:
    return {
        "sampleId": sample.sample_id,
        "width": sample.width,
        "height": sample.height,
        "rgbDigest": sample.rgb_digest,
        "preprocessedInputDigest": sample.preprocessed_input_digest,
        "detections": [
            {
                "queryIndex": item.query_index,
                "classId": item.class_id,
                "className": item.class_name,
                "confidence": item.confidence,
                "box": list(item.box),
            }
            for item in sample.detections
        ],
        "drops": dict(sample.drops),
    }


def compare_semantic_reports(
    profile: EdgeRuntimeProfileV1,
    corpus: RawRgbCorpusV1,
    report: TensorRtRunnerReportV1,
    oracle: Mapping[str, OracleSample],
) -> None:
    """Raise :class:`DifferentialFailure` for any semantic or lineage drift."""
    _validate_runner_metadata(profile, report)
    report_by_id = {sample.sample_id: sample for sample in report.samples}
    corpus_by_id = {sample.sample_id: sample for sample in corpus.samples}
    if set(report_by_id) != set(corpus_by_id) or set(oracle) != set(corpus_by_id):
        raise DifferentialFailure(
            "TensorRT report, ONNX oracle and corpus sample IDs must match exactly"
        )
    tolerance = profile.model.tensor_rt_differential
    for sample_id, corpus_sample in corpus_by_id.items():
        native = report_by_id[sample_id]
        expected = oracle[sample_id]
        if (
            native.width != corpus_sample.width
            or native.height != corpus_sample.height
            or native.rgb_digest != corpus_sample.rgb_digest
            or native.preprocessed_input_digest != expected.preprocessed_input_digest
        ):
            raise DifferentialFailure(f"{sample_id}: RGB/preprocessing lineage mismatch")
        if native.drops != expected.drops:
            raise DifferentialFailure(f"{sample_id}: typed D-FINE drops differ")
        if len(native.detections) != len(expected.detections):
            raise DifferentialFailure(f"{sample_id}: detection count differs")
        for index, (native_detection, expected_detection) in enumerate(
            zip(native.detections, expected.detections, strict=True)
        ):
            if (
                native_detection.query_index != expected_detection.query_index
                or native_detection.class_id != expected_detection.class_id
                or native_detection.class_name != expected_detection.class_name
            ):
                raise DifferentialFailure(f"{sample_id}: detection {index} class/query differs")
            if (
                abs(native_detection.confidence - expected_detection.confidence)
                > tolerance.confidence_atol
            ):
                raise DifferentialFailure(
                    f"{sample_id}: detection {index} confidence exceeds tolerance"
                )
            for native_value, expected_value in zip(
                native_detection.box, expected_detection.box, strict=True
            ):
                if abs(native_value - expected_value) > tolerance.bbox_atol_px:
                    raise DifferentialFailure(
                        f"{sample_id}: detection {index} bbox exceeds tolerance"
                    )


def build_differential_evidence(
    profile: EdgeRuntimeProfileV1,
    corpus: RawRgbCorpusV1,
    report: TensorRtRunnerReportV1,
    oracle_report: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Build deterministic evidence after :func:`compare_semantic_reports` succeeds."""
    attestation = profile.model.tensor_rt_differential
    report_wire = report.model_dump(by_alias=True, mode="json")
    samples = [
        {
            "sampleId": sample.sample_id,
            "rgbDigest": sample.rgb_digest,
            "preprocessedInputDigest": sample.preprocessed_input_digest,
            "detectionCount": len(sample.detections),
            "typedDrops": dict(sample.drops),
        }
        for sample in report.samples
    ]
    evidence = {
        "schemaVersion": "1.0",
        "verificationProfileId": attestation.verification_profile_id,
        "status": "PASS",
        "registeredOnnxDigest": profile.model.registered_onnx_digest,
        "preprocessingContractId": attestation.preprocessing_contract_id,
        "preprocessingConfigDigest": attestation.preprocessing_config_digest,
        "corpusId": corpus.corpus_id,
        "corpusDigest": corpus_digest(corpus),
        "sampleCount": len(samples),
        "confidenceAtol": attestation.confidence_atol,
        "bboxAtolPx": attestation.bbox_atol_px,
        "tensorRtReportDigest": sha256_digest(canonical_json_bytes(report_wire)),
        "onnxOracleReportDigest": sha256_digest(canonical_json_bytes(dict(oracle_report))),
        "samples": samples,
    }
    return evidence, sha256_digest(canonical_json_bytes(evidence))


def verify(
    *,
    runner: Path,
    runtime_profile: Path,
    onnx_path: Path,
    preprocessing_config: Path,
    corpus_path: Path,
    engine_vault_directory: Path,
    evidence_out: Path,
    timeout_seconds: int,
    require_profile_evidence_digest: bool,
) -> str:
    if timeout_seconds < 1:
        raise DifferentialFailure("timeout must be positive")
    if not runner.is_file() or not os.access(runner, os.X_OK):
        raise DifferentialFailure("TensorRT runner is not an executable file")
    profile = _load_profile(runtime_profile)
    corpus = load_raw_rgb_corpus(corpus_path)
    _validate_inputs(profile, corpus, onnx_path, preprocessing_config)
    engine_vault_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ksi-tensorrt-differential-") as temporary:
        sample_list = Path(temporary) / "samples.native.v1"
        rgb_bytes = _write_private_sample_list(sample_list, corpus_path, corpus)
        report = _run_runner(
            _runner_command(runner, profile, onnx_path, engine_vault_directory, sample_list),
            timeout_seconds,
        )
        oracle, oracle_report = _run_onnx_oracle(profile, onnx_path, corpus, rgb_bytes)
    compare_semantic_reports(profile, corpus, report, oracle)
    evidence, evidence_digest = build_differential_evidence(profile, corpus, report, oracle_report)
    if (
        require_profile_evidence_digest
        and profile.model.tensor_rt_differential.evidence_digest != evidence_digest
    ):
        raise DifferentialFailure(
            "signed profile evidenceDigest does not match regenerated evidence"
        )
    evidence_out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        evidence_out.write_bytes(canonical_json_bytes(evidence) + b"\n")
    except OSError as exc:
        raise DifferentialFailure("could not write differential evidence") from exc
    return evidence_digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    digest_parser = subcommands.add_parser(
        "corpus-digest", help="print canonical raw-RGB corpus digest"
    )
    digest_parser.add_argument("--corpus", type=Path, required=True)
    verify_parser = subcommands.add_parser(
        "verify", help="run TensorRT and ONNX semantic comparison"
    )
    verify_parser.add_argument("--runner", type=Path, required=True)
    verify_parser.add_argument("--runtime-profile", type=Path, required=True)
    verify_parser.add_argument("--onnx", type=Path, required=True)
    verify_parser.add_argument("--preprocessing-config", type=Path, required=True)
    verify_parser.add_argument("--corpus", type=Path, required=True)
    verify_parser.add_argument("--engine-vault-dir", type=Path, required=True)
    verify_parser.add_argument("--evidence-out", type=Path, required=True)
    verify_parser.add_argument("--timeout-seconds", type=int, default=600)
    verify_parser.add_argument("--require-profile-evidence-digest", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "corpus-digest":
            print(corpus_digest(load_raw_rgb_corpus(args.corpus)))
            return 0
        evidence_digest = verify(
            runner=args.runner,
            runtime_profile=args.runtime_profile,
            onnx_path=args.onnx,
            preprocessing_config=args.preprocessing_config,
            corpus_path=args.corpus,
            engine_vault_directory=args.engine_vault_dir,
            evidence_out=args.evidence_out,
            timeout_seconds=args.timeout_seconds,
            require_profile_evidence_digest=args.require_profile_evidence_digest,
        )
    except DifferentialFailure as exc:
        print(f"✗ TensorRT differential verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"✓ TensorRT/ONNX semantic differential PASS: {evidence_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
