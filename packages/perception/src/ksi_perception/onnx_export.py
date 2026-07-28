"""D-FINE ONNX export + float64 정규화 (B1 승인 범위 — MODEL-B1-001).

## 왜 후처리가 필요한가

transformers 의 D-FINE position embedding(``build_2d_sincos`` 계열)은 주파수 산술을
**의도적으로 float64** 로 한다(모델 코드 주석 명시). 고정 입력 크기에서 이 경로는
입력과 무관한 상수 서브그래프인데, ONNX Runtime CPU EP 는 double ``Cos``/``Sin``
커널이 없어 fold 도 실행도 못 하고 세션 초기화가 죽는다. TensorRT(B2 타깃)도
double 을 지원하지 않으므로 이 변환은 테스트 편의가 아니라 **배포 경로의 일부**다.

변환은 그래프 전역 DOUBLE→FLOAT 이다 — 이 모델의 double 사용은 위 상수 경로뿐이라
안전하며(가중치 전체는 float32), 변환 후 수치 동일성은 계약 테스트가
PyTorch 출력과의 허용오차 비교로 고정한다(`test_onnx_export_matches_pytorch`).

## 성능은 여기서 판정하지 않는다

이 모듈은 "export 산출물이 같은 모델인가"까지만 담당한다. TensorRT 변환·처리율·
발열은 B2 Manifold HIL 의 몫이다(MODEL-B1-001 hil_selection_order).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

    from ksi_perception.dfine import DFineDetector


@dataclass(frozen=True, slots=True)
class OnnxExportResult:
    """export 산출물 + 정규화 증거 + manifest.

    ``double_fixes`` 는 DOUBLE→FLOAT 로 바뀐 지점의 서술("op/위치")이다 — "이 모델의
    double 사용은 위치 임베딩 상수 경로뿐"이라는 docstring 전제를 단언이 아니라
    데이터로 남긴다(반증 리뷰 F9). 예상 밖 지점이 여기 나타나면 전제가 깨진 것이다.
    """

    path: Path
    double_fixes: tuple[str, ...]
    manifest_path: Path | None = None

# ONNX TensorProto.DataType 값 (onnx.TensorProto.DOUBLE/FLOAT 과 동일 — 상수로 두어
# 모듈 import 시점에 onnx 의존을 만들지 않는다).
_ONNX_DOUBLE = 11
_ONNX_FLOAT = 1


def _double_to_float_graph(graph: Any) -> list[str]:
    """그래프의 DOUBLE 흔적을 FLOAT 로 바꾼다. 바꾼 지점의 서술 목록을 반환한다."""
    import onnx
    from onnx import numpy_helper

    fixes: list[str] = []

    for initializer in graph.initializer:
        if initializer.data_type == _ONNX_DOUBLE:
            array = numpy_helper.to_array(initializer).astype("float32")
            initializer.CopyFrom(
                numpy_helper.from_array(array, name=initializer.name)
            )
            fixes.append(f"initializer:{initializer.name}")

    for value in list(graph.input) + list(graph.output) + list(graph.value_info):
        t = value.type.tensor_type
        if t.elem_type == _ONNX_DOUBLE:
            t.elem_type = _ONNX_FLOAT
            fixes.append(f"value_info:{value.name}")

    for node in graph.node:
        for attr in node.attribute:
            is_cast_to_double = (
                attr.type == onnx.AttributeProto.INT
                and attr.name == "to"
                and attr.i == _ONNX_DOUBLE
            )
            if is_cast_to_double:
                attr.i = _ONNX_FLOAT  # Cast(to=DOUBLE) → Cast(to=FLOAT)
                fixes.append(f"{node.op_type}:{node.name}")
            elif attr.type == onnx.AttributeProto.TENSOR and attr.t.data_type == _ONNX_DOUBLE:
                array = numpy_helper.to_array(attr.t).astype("float32")
                attr.t.CopyFrom(numpy_helper.from_array(array))
                fixes.append(f"{node.op_type}:{node.name}")
            elif attr.type == onnx.AttributeProto.GRAPH:
                fixes.extend(_double_to_float_graph(attr.g))  # If/Loop 서브그래프
    return fixes


def export_dfine_onnx(
    detector: DFineDetector,
    sample_image: np.ndarray,
    output_path: Path,
    *,
    opset_version: int = 17,
    operator: str,
) -> OnnxExportResult:
    """detector 의 모델을 ONNX 로 export 하고 double 흔적을 정규화한다.

    legacy(TorchScript) exporter 를 쓴다 — dynamo exporter 는 transformers 의 내부
    검증 op(``aten._is_all_true``)를 아직 변환하지 못한다(torch 2.13 실측).
    출력은 ``logits``·``pred_boxes`` (post-process 이전의 모델 원 출력) — 후처리는
    배포 런타임 쪽 구현과 계약 테스트가 별도로 다룬다.

    산출물 옆에 **Versioned Export Manifest**(``<output>.manifest.json``)를 기록한다
    (onnx-export-recipe risk 폐쇄, 대표자 지정 2026-07-28) — B2 TensorRT 소비자가
    "이 ONNX 가 어느 가중치·어느 도구 버전·어느 변환으로 만들어졌는가"를 원장 없이
    재현·대조할 수 있어야 한다. 모델 파일과 manifest 는 git 에 넣지 않는다(계보
    요약만 MODEL_REGISTRY 의 export 섹션에 기록).

    실패 시 미완성/미정규화 산출물을 디스크에 남기지 않는다 — 정규화 전 파일이
    남으면 double 그래프가 최종 산출물로 오인된다(fail-closed).
    """
    import hashlib
    import json
    import platform
    from datetime import UTC, datetime

    # 책임자 없는 export 는 증거가 아니다(재검토 P0 반증 7) — 로더도 같은 규칙으로
    # 거부하지만, 생성 시점에 끊는 것이 1차다.
    if not operator.strip() or operator.strip() == "unspecified":
        raise ValueError("operator 는 공백/'unspecified' 일 수 없다 — 실행 책임자를 기록하라")

    import onnx
    import onnxruntime
    import torch
    import transformers

    inputs = detector._processor(images=sample_image, return_tensors="pt")  # noqa: SLF001
    try:
        torch.onnx.export(
            detector._model,  # noqa: SLF001
            (inputs["pixel_values"],),
            str(output_path),
            input_names=["pixel_values"],
            output_names=["logits", "pred_boxes"],
            dynamo=False,
            opset_version=opset_version,
        )

        model = onnx.load(str(output_path))
        # legacy exporter 는 트레이스 부수 텐서를 그래프 출력에 남긴다(실측: logits·
        # pred_boxes 외 내부 노드 다수) — 선언 계약과 실제 그래프가 달라지면 세션
        # 실계약 대조(재검토 P0 #8)가 성립하지 않으므로, 명명된 출력 2개만 남긴다.
        declared_outputs = {"logits", "pred_boxes"}
        surplus = [o for o in model.graph.output if o.name not in declared_outputs]
        for o in surplus:
            model.graph.output.remove(o)
        fixes = _double_to_float_graph(model.graph)
        if fixes or surplus:
            onnx.checker.check_model(model)
            # 파생 산출물에도 계보를 박는다 — B2 TensorRT 소비자가 원장과 대조할 앵커.
            entry = model.metadata_props.add()
            entry.key = "ksi.model_id"
            entry.value = detector.model_id
            onnx.save(model, str(output_path))
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    pixel = inputs["pixel_values"]
    manifest = {
        "schema": "ksi-onnx-export-manifest/1",
        "model_id": detector.model_id,
        "source_artifact_digests": dict(detector.source_digests),
        "versions": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "onnx": onnx.__version__,
            "onnxruntime": onnxruntime.__version__,
        },
        "exporter": "torch.onnx.export(dynamo=False)  # legacy TorchScript exporter",
        "opset": opset_version,
        "inputs": [
            {
                "name": "pixel_values",
                "shape": list(pixel.shape),
                "dtype": str(pixel.dtype),
                # legacy exporter + dynamic_axes 미지정 = 전 축 static. 배포 입력은
                # 전처리가 640×640 으로 고정하므로 batch=1 static 이 의도된 계약이다.
                "axes": "static (batch=1, 640x640 — 전처리가 고정)",
            }
        ],
        "outputs": [
            {"name": "logits", "meaning": "per-query class logits (post-process 이전)"},
            {"name": "pred_boxes", "meaning": "per-query cxcywh normalized boxes"},
        ],
        "preprocessing": (
            "RTDetrImageProcessor(digest 고정 preprocessor_config.json): resize 640x640, "
            "rescale 1/255, normalize 없음, RGB(HWC uint8) 입력 계약"
        ),
        "postprocessing": (
            "post_process_object_detection(threshold=score_floor, target_sizes=원본 HW) "
            "→ RawDetection → DetectionAdapter(OntologyMapping)"
        ),
        "graph_transforms": [
            "position embedding constants float64 → float32 (전체 지점은 double_fixes)",
            "surplus trace outputs 제거 — 그래프 출력을 선언 계약(logits·pred_boxes)으로 고정",
        ],
        "graph_transform_fix_count": len(fixes),
        "export_command": (
            f"ksi_perception.onnx_export.export_dfine_onnx(opset_version={opset_version})"
        ),
        "onnx_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "operator": operator,
        "exported_at_utc": datetime.now(UTC).isoformat(),
    }
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return OnnxExportResult(
        path=output_path, double_fixes=tuple(fixes), manifest_path=manifest_path
    )
