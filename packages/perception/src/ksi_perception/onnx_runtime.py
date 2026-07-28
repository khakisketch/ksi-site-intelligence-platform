"""ONNX Runtime 경로의 D-FINE detector — PyTorch 경로와의 conformance 비교용.

B2 TensorRT 로 가기 전의 중간 신뢰 사슬이다::

    PyTorch(원본)  ──conformance──▶  ONNX(onnxruntime CPU)  ──B2──▶  TensorRT

전처리(RTDetrImageProcessor)·후처리(post_process_object_detection)·정규화
(DetectionAdapter + OntologyMapping)를 PyTorch 경로와 **같은 코드로 공유**하고,
모델 forward 만 onnxruntime 세션으로 바꾼다 — 그래야 비교에서 차이가 나면 그것이
export 산출물의 문제임이 확정된다(전·후처리 재구현 차이가 섞이면 원인 분리 불가).

로드 게이트는 PyTorch 경로와 동일하다: Registry digest 검증 통과 디렉토리에서만
processor 를 읽고(local_files_only), ONNX 파일은 manifest 의 sha256 과 대조한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ksi_domain.detection_adapter import (
    AdapterResult,
    BoxFormat,
    DetectionAdapter,
    RawDetection,
)
from ksi_domain.ontology import COCO_ONTOLOGY, OntologyMapping
from pydantic import ValidationError

from ksi_perception.dfine import DEFAULT_SCORE_FLOOR
from ksi_perception.onnx_manifest import (
    CANONICAL_TO_ORT,
    OnnxExportManifestV1,
    reject_nonstandard_json_constant,
)
from ksi_perception.registry import DEFAULT_REGISTRY_PATH, verify_local_model

if TYPE_CHECKING:
    import numpy as np


class OnnxLoadStatus(StrEnum):
    OK = "ok"
    REGISTRY_REJECTED = "registry_rejected"
    MANIFEST_MISSING = "manifest_missing"  # manifest 없는 ONNX 는 계보 없는 산출물
    DIGEST_MISMATCH = "digest_mismatch"  # ONNX 실물과 manifest sha256 불일치
    RUNTIME_MISSING = "runtime_missing"
    LOAD_FAILED = "load_failed"


@dataclass(frozen=True, slots=True)
class OnnxDetectorLoadResult:
    status: OnnxLoadStatus
    detector: OnnxDFineDetector | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is OnnxLoadStatus.OK


class OnnxDFineDetector:
    """ONNX 세션 + 공유 전·후처리. :func:`load_onnx_dfine_detector` 로만 만든다."""

    def __init__(
        self,
        *,
        session: Any,
        processor: Any,
        id2label: dict[int, str],
        adapter: DetectionAdapter,
        score_floor: float,
    ) -> None:
        self._session = session
        self._processor = processor
        self._id2label = id2label
        self._adapter = adapter
        self._score_floor = score_floor

    def detect_image(self, image: np.ndarray) -> AdapterResult:
        """PyTorch 경로(:meth:`DFineDetector.detect_image`)와 동일 계약."""
        import torch

        if image.ndim != 3 or image.shape[2] != 3 or image.dtype.name != "uint8":
            raise ValueError(
                f"이미지는 HWC uint8 RGB 여야 한다 (shape={image.shape}, dtype={image.dtype})"
            )
        height, width = int(image.shape[0]), int(image.shape[1])
        inputs = self._processor(images=image, return_tensors="pt")
        logits, pred_boxes = self._session.run(
            ["logits", "pred_boxes"], {"pixel_values": inputs["pixel_values"].numpy()}
        )

        # 후처리는 PyTorch 경로와 같은 함수를 태운다 — ONNX 출력만 텐서로 감싼다.
        class _Out:
            pass

        outputs = _Out()
        outputs.logits = torch.from_numpy(logits)  # type: ignore[attr-defined]
        outputs.pred_boxes = torch.from_numpy(pred_boxes)  # type: ignore[attr-defined]
        processed = self._processor.post_process_object_detection(
            outputs, target_sizes=[(height, width)], threshold=self._score_floor
        )[0]
        raws = [
            RawDetection(
                label=self._id2label.get(int(label), int(label)),
                score=float(score),
                box=(float(b[0]), float(b[1]), float(b[2]), float(b[3])),
                source_class_id=int(label),
            )
            for score, label, b in zip(
                processed["scores"].tolist(),
                processed["labels"].tolist(),
                processed["boxes"].tolist(),
                strict=True,
            )
        ]
        return self._adapter.convert(raws, width=width, height=height)


def load_onnx_dfine_detector(
    *,
    onnx_path: Path,
    model_dir: Path,
    model_id: str = "ksi-person-detector-dfine-s-coco",
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    ontology: OntologyMapping = COCO_ONTOLOGY,
    min_confidence: float = 0.0,
    score_floor: float = DEFAULT_SCORE_FLOOR,
) -> OnnxDetectorLoadResult:
    """manifest digest 검증 → Registry 검증 디렉토리의 processor → ONNX 세션 구성.

    예외를 던지지 않는다 — 실패는 typed 로 반환된다.
    """
    if not isinstance(ontology, OntologyMapping):
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.LOAD_FAILED,
            detail=f"ontology 는 OntologyMapping 이어야 한다 ({type(ontology).__name__})",
        )

    manifest_path = onnx_path.with_suffix(onnx_path.suffix + ".manifest.json")
    if not manifest_path.is_file():
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.MANIFEST_MISSING,
            detail=f"{manifest_path} 없음 — manifest 없는 ONNX 는 계보 없는 산출물이라 거부",
        )
    if not onnx_path.is_file():
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.LOAD_FAILED, detail=f"{onnx_path} 없음"
        )
    # typed 신뢰 경계(재검토 P1) — 어떤 malformed manifest 도 raw traceback 이 아니라
    # typed 결과다. 파싱(비표준 JSON 상수 거부)과 구조·타입·형식 검증 전부를
    # OnnxExportManifestV1(extra="forbid")이 담당하고, 실패는 여기서 흡수된다.
    try:
        raw_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            parse_constant=reject_nonstandard_json_constant,
        )
        if not isinstance(raw_manifest, dict):
            return OnnxDetectorLoadResult(
                status=OnnxLoadStatus.MANIFEST_MISSING,
                detail=f"manifest 최상위가 JSON object 가 아니다 ({type(raw_manifest).__name__})",
            )
        manifest = OnnxExportManifestV1.model_validate(raw_manifest)
    # ValidationError 는 ValueError 의 서브클래스 — 먼저 잡아야 상세 사유가 남는다.
    except ValidationError as exc:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.MANIFEST_MISSING,
            detail=f"manifest 검증 실패: {exc.errors()[:3]}",
        )
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as exc:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.MANIFEST_MISSING,
            detail=f"manifest 손상: {exc!r}",
        )
    if manifest.model_id != model_id:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.DIGEST_MISMATCH,
            detail=f"manifest model_id {manifest.model_id!r} ≠ 요청 {model_id!r}",
        )
    expected = manifest.onnx_sha256
    actual = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    if actual != expected:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.DIGEST_MISMATCH,
            detail=(
                f"ONNX digest 불일치 — manifest {expected[:12]}… vs 실물 {actual[:12]}…"
            ),
        )

    import math

    if not (
        isinstance(score_floor, float)
        and math.isfinite(score_floor)
        and 0.0 <= score_floor <= 1.0
    ):
        # score_floor 는 post_process threshold 로 직행해 adapter 기록 없이 후보를
        # 소멸시킨다(반증 리뷰 F-D) — 검증 없이는 NaN/0.9 오설정이 무경고로 필터를
        # 무력화하거나 대부분을 죽인다. min_confidence 와 동일 규약으로 강제한다.
        _detail = f"score_floor 는 [0,1] 범위의 finite float 이어야 한다 ({score_floor!r})"
        return OnnxDetectorLoadResult(status=OnnxLoadStatus.LOAD_FAILED, detail=_detail)

    check = verify_local_model(model_id, model_dir, registry_path=registry_path)
    if not check.ok:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.REGISTRY_REJECTED,
            detail=f"{check.status}: {check.detail}",
        )
    assert check.entry is not None

    # ── 외부 권위 앵커 대조 (재검토 P0) ──────────────────────────────────────
    # manifest 는 산출물 옆의 자기 서술이라 ONNX+manifest 동시 교체(자체 일관)를
    # 막지 못한다 — Registry(코드리뷰 원장) export 레코드와 대조해야 사슬이 닫힌다.
    export = check.entry.export
    if export is None:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.REGISTRY_REJECTED,
            detail=f"{model_id} 의 Registry 에 export 섹션이 없다 — 권위 앵커 없는 ONNX 거부",
        )
    if manifest.source_artifact_digests != check.entry.file_digests:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.DIGEST_MISMATCH,
            detail=(
                "manifest.source_artifact_digests 가 Registry 검증 가중치 digest 와 다르다 "
                "— 다른 원본에서 export 된 산출물"
            ),
        )
    if expected != export.onnx_sha256:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.DIGEST_MISMATCH,
            detail=(
                f"manifest onnx_sha256 {expected[:12]}… ≠ Registry export 앵커 "
                f"{export.onnx_sha256[:12]}… — 등록되지 않은 export 산출물"
            ),
        )
    if manifest.opset != export.opset:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.DIGEST_MISMATCH,
            detail=f"manifest opset {manifest.opset} ≠ Registry opset {export.opset}",
        )
    manifest_inputs = tuple(t.name for t in manifest.inputs)
    manifest_outputs = tuple(t.name for t in manifest.outputs)
    if manifest_inputs != export.input_names or manifest_outputs != export.output_names:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.DIGEST_MISMATCH,
            detail=(
                f"manifest 입출력 계약 ({manifest_inputs}→{manifest_outputs}) ≠ Registry "
                f"({export.input_names}→{export.output_names})"
            ),
        )

    try:
        import onnxruntime as ort
        from transformers import AutoConfig, AutoImageProcessor
    except ImportError as exc:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.RUNTIME_MISSING,
            detail=f"[dfine] extra 미설치({exc})",
        )

    try:
        processor = AutoImageProcessor.from_pretrained(model_dir, local_files_only=True)
        config = AutoConfig.from_pretrained(model_dir, local_files_only=True)
        id2label = {int(k): str(v) for k, v in config.id2label.items()}
        session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        adapter = DetectionAdapter(
            box_format=BoxFormat.XYXY,
            normalized=False,
            ontology=ontology,
            min_confidence=min_confidence,
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.LOAD_FAILED,
            detail=f"{type(exc).__name__}: {exc}",
        )

    # ── 실제 세션 계약 대조 (재검토 P0 #8 + P1 완전화) — manifest 가 주장하는
    # 입출력이 로드된 그래프의 실제 계약과 **이름·순서·shape·dtype exact** 로
    # 일치하는가. dtype 은 substring 이 아니라 canonical 대응표로만 비교한다
    # (substring 은 float64 주장과 float32 실물을 같게 본다 — 재검토 지적).
    session_inputs = {i.name: i for i in session.get_inputs()}
    session_outputs = {o.name: o for o in session.get_outputs()}
    if tuple(session_inputs) != manifest_inputs or tuple(session_outputs) != manifest_outputs:
        return OnnxDetectorLoadResult(
            status=OnnxLoadStatus.DIGEST_MISMATCH,
            detail=(
                f"세션 실계약 ({tuple(session_inputs)}→{tuple(session_outputs)}) ≠ manifest "
                f"({manifest_inputs}→{manifest_outputs})"
            ),
        )
    for declared_tensor in list(manifest.inputs) + list(manifest.outputs):
        actual_tensor = (
            session_inputs.get(declared_tensor.name)
            or session_outputs[declared_tensor.name]
        )
        if [int(d) for d in actual_tensor.shape] != declared_tensor.shape:
            return OnnxDetectorLoadResult(
                status=OnnxLoadStatus.DIGEST_MISMATCH,
                detail=(
                    f"텐서 {declared_tensor.name!r} shape {actual_tensor.shape} ≠ manifest "
                    f"{declared_tensor.shape}"
                ),
            )
        expected_ort_dtype = CANONICAL_TO_ORT[declared_tensor.dtype]
        if str(actual_tensor.type) != expected_ort_dtype:
            return OnnxDetectorLoadResult(
                status=OnnxLoadStatus.DIGEST_MISMATCH,
                detail=(
                    f"텐서 {declared_tensor.name!r} dtype {actual_tensor.type} ≠ manifest "
                    f"{declared_tensor.dtype}({expected_ort_dtype})"
                ),
            )
    return OnnxDetectorLoadResult(
        status=OnnxLoadStatus.OK,
        detector=OnnxDFineDetector(
            session=session,
            processor=processor,
            id2label=id2label,
            adapter=adapter,
            score_floor=score_floor,
        ),
    )
