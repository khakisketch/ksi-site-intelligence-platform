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
    """export 산출물 + 정규화 증거.

    ``double_fixes`` 는 DOUBLE→FLOAT 로 바뀐 지점의 서술("op/위치")이다 — "이 모델의
    double 사용은 위치 임베딩 상수 경로뿐"이라는 docstring 전제를 단언이 아니라
    데이터로 남긴다(반증 리뷰 F9). 예상 밖 지점이 여기 나타나면 전제가 깨진 것이다.
    """

    path: Path
    double_fixes: tuple[str, ...]

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
) -> OnnxExportResult:
    """detector 의 모델을 ONNX 로 export 하고 double 흔적을 정규화한다.

    legacy(TorchScript) exporter 를 쓴다 — dynamo exporter 는 transformers 의 내부
    검증 op(``aten._is_all_true``)를 아직 변환하지 못한다(torch 2.13 실측).
    출력은 ``logits``·``pred_boxes`` (post-process 이전의 모델 원 출력) — 후처리는
    배포 런타임 쪽 구현과 계약 테스트가 별도로 다룬다.

    실패 시 미완성/미정규화 산출물을 디스크에 남기지 않는다 — 정규화 전 파일이
    남으면 double 그래프가 최종 산출물로 오인된다(fail-closed).
    """
    import onnx
    import torch

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
        fixes = _double_to_float_graph(model.graph)
        if fixes:
            onnx.checker.check_model(model)
            # 파생 산출물에도 계보를 박는다 — B2 TensorRT 소비자가 원장과 대조할 앵커.
            entry = model.metadata_props.add()
            entry.key = "ksi.model_id"
            entry.value = detector.model_id
            onnx.save(model, str(output_path))
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return OnnxExportResult(path=output_path, double_fixes=tuple(fixes))
