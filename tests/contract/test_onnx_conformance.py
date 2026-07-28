"""PyTorch↔ONNX conformance — corpus 전체 비교 (B2 선결, 대표자 지정 2026-07-28).

신뢰 사슬: PyTorch(원본) → ONNX(onnxruntime CPU) → [B2] TensorRT.
이 파일은 첫 화살표를 corpus 10종 × 기준 8종으로 고정한다. 전·후처리·adapter 는
두 경로가 **같은 코드를 공유**하므로(onnx_runtime 모듈 docstring), 여기서 차이가
나면 export 산출물의 문제임이 확정된다.

비교 기준(대표자 지정):
    detection 수 / canonical class·원시 id·이름 계보 정확 일치 /
    confidence 허용오차 명시 / bbox 허용오차 명시 / typed drop 사유 정확 일치 /
    Person fallback 부재 / 경로별 결정성 / (cross-경로 fingerprint 는 아래 참고)

## Cross-경로 fingerprint 에 대한 정직한 한계

fingerprint 는 융합 위치를 소수 9자리로 직렬화하므로 cross-경로 동일성은 사실상
bbox 의 bit-exact 를 요구한다. ONNX 와 PyTorch 는 연산 순서가 달라 bit-exact 가
보장되지 않는다 — 그래서 cross-경로는 **허용오차 기반 의미 비교**로 하고,
fingerprint 결정성은 **경로 내 2회 실행**으로 고정한다(비결정 요소의 정확한 기록,
대표자 지시 5항). 실측 결과는 manifest·Registry export 섹션에 남긴다.

모델 파일·corpus(models/ 아래)가 있을 때만 실행된다 — CI 는 skip.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from ksi_perception.dfine import DFineDetector, load_dfine_detector
from ksi_perception.onnx_runtime import (
    OnnxDFineDetector,
    OnnxLoadStatus,
    load_onnx_dfine_detector,
)
from ksi_perception.registry import load_model_entry

_MODEL_ID = "ksi-person-detector-dfine-s-coco"
_CORPUS = Path("models/test-assets/onnx-corpus")

# 허용오차 — 명시적 계약(대표자 지정). CPU 기준 실측 여유를 포함한 보수값이며,
# 이 값을 넘는 차이는 export 회귀로 취급한다.
CONFIDENCE_ATOL = 1e-3
BBOX_ATOL_PX = 0.5

_SCENES = [
    "single_person",
    "multiple_people",
    "no_detection",
    "small_person",
    "border_person",
    "overlap_people",
    "non_person_car",
    "unsupported_scene",
    "low_conf_noise",
    "clipping_scene",
]


def _model_dir() -> Path:
    check = load_model_entry(_MODEL_ID)
    if not check.ok or check.entry is None:
        return Path("models/__registry_unreadable__")
    return Path("models") / check.entry.weights_source.rsplit("/", 1)[-1] / check.entry.revision


_HAS_RUNTIME = (
    importlib.util.find_spec("torch") is not None
    and importlib.util.find_spec("onnxruntime") is not None
)

pytestmark = pytest.mark.skipif(
    not (_HAS_RUNTIME and _model_dir().is_dir() and _CORPUS.is_dir()),
    reason="[dfine] extra·모델·corpus 없음 — fetch_model + build_onnx_corpus 후 실행",
)


def _load_scene(name: str) -> np.ndarray:
    from PIL import Image

    with Image.open(_CORPUS / f"{name}.png") as img:
        return np.asarray(img.convert("RGB"))


@pytest.fixture(scope="module")
def detectors(tmp_path_factory: pytest.TempPathFactory) -> tuple[DFineDetector, OnnxDFineDetector]:
    """PyTorch detector + (export 1회 →) ONNX detector. 모듈 1회."""
    from ksi_perception.onnx_export import export_dfine_onnx

    torch_loaded = load_dfine_detector(local_dir=_model_dir())
    assert torch_loaded.ok, torch_loaded.detail
    assert torch_loaded.detector is not None

    onnx_path = tmp_path_factory.mktemp("onnx") / "dfine-s.onnx"
    export = export_dfine_onnx(
        torch_loaded.detector, _load_scene("multiple_people"), onnx_path, operator="ci-conformance"
    )
    assert export.manifest_path is not None and export.manifest_path.is_file()

    onnx_loaded = load_onnx_dfine_detector(onnx_path=onnx_path, model_dir=_model_dir())
    assert onnx_loaded.ok, onnx_loaded.detail
    assert onnx_loaded.detector is not None
    return torch_loaded.detector, onnx_loaded.detector


@pytest.mark.parametrize("scene", _SCENES)
def test_scene_conformance(
    scene: str, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[corpus × 8기준] 장면별 PyTorch↔ONNX 의미 동등성."""
    torch_det, onnx_det = detectors
    image = _load_scene(scene)
    a = torch_det.detect_image(image)
    b = onnx_det.detect_image(image)

    # 기준 1: detection 수
    assert len(a.detections) == len(b.detections), (
        f"{scene}: detection 수 불일치 torch={len(a.detections)} onnx={len(b.detections)}"
    )
    # 기준 2·3: canonical class + 원시 계보 정확 일치 / Person fallback 부재
    for da, db in zip(a.detections, b.detections, strict=True):
        assert da.detection_class == db.detection_class, scene
        assert da.source_class_id == db.source_class_id, scene
        assert da.source_class_name == db.source_class_name, scene
        assert da.ontology_version == db.ontology_version, scene
        if da.detection_class == "Person":
            assert da.source_class_name == "person", f"{scene}: Person fallback 의심"
        # 기준 4: confidence 허용오차
        assert abs(da.confidence - db.confidence) <= CONFIDENCE_ATOL, (
            f"{scene}: confidence 차이 {abs(da.confidence - db.confidence):.6f}"
        )
        # 기준 5: bbox 허용오차
        for va, vb in zip(
            (da.bbox.x_min, da.bbox.y_min, da.bbox.x_max, da.bbox.y_max),
            (db.bbox.x_min, db.bbox.y_min, db.bbox.x_max, db.bbox.y_max),
            strict=True,
        ):
            assert abs(va - vb) <= BBOX_ATOL_PX, f"{scene}: bbox 차이 {abs(va - vb):.3f}px"
    # 기준 6: typed drop 사유 — (사유, 라벨) 다중집합 정확 일치
    drops_a = sorted((d.reason.value, str(d.raw.label)) for d in a.dropped)
    drops_b = sorted((d.reason.value, str(d.raw.label)) for d in b.dropped)
    assert drops_a == drops_b, f"{scene}: drop 사유 불일치"


def test_scene_expectations_are_not_vacuous(
    detectors: tuple[DFineDetector, OnnxDFineDetector],
) -> None:
    """corpus 가 의도한 현상을 실제로 유발하는지 — 비교가 공허하지 않음을 앵커."""
    torch_det, _ = detectors
    assert any(
        d.detection_class == "Person"
        for d in torch_det.detect_image(_load_scene("multiple_people")).detections
    ), "multiple_people 에서 Person 0건 — corpus 전제 붕괴"
    assert any(
        d.detection_class in ("Vehicle_Car", "Vehicle_Truck")
        for d in torch_det.detect_image(_load_scene("non_person_car")).detections
    ), "non_person_car 에서 차량 0건 — corpus 전제 붕괴"
    high_conf_on_blank = [
        d
        for d in torch_det.detect_image(_load_scene("no_detection")).detections
        if d.confidence >= 0.5
    ]
    assert high_conf_on_blank == [], "단색 배경에서 고신뢰 탐지 — corpus 전제 붕괴"


def test_per_path_determinism(
    detectors: tuple[DFineDetector, OnnxDFineDetector],
) -> None:
    """기준 7: 경로별 2회 실행 결정성(값 동일성)."""
    torch_det, onnx_det = detectors
    image = _load_scene("multiple_people")
    assert torch_det.detect_image(image).detections == torch_det.detect_image(image).detections
    assert onnx_det.detect_image(image).detections == onnx_det.detect_image(image).detections


def test_manifest_digest_gate_blocks_tampered_onnx(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """manifest 없는/변조된 ONNX 는 로드 거부 — 계보 없는 산출물 차단."""
    torch_det, _ = detectors
    from ksi_perception.onnx_export import export_dfine_onnx

    onnx_path = tmp_path / "m.onnx"
    export_dfine_onnx(torch_det, _load_scene("no_detection"), onnx_path)
    # 변조
    data = bytearray(onnx_path.read_bytes())
    data[-1] ^= 0xFF
    onnx_path.write_bytes(bytes(data))
    result = load_onnx_dfine_detector(onnx_path=onnx_path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH

    # manifest 삭제
    onnx_path2 = tmp_path / "m2.onnx"
    export2 = export_dfine_onnx(torch_det, _load_scene("no_detection"), onnx_path2)
    assert export2.manifest_path is not None
    export2.manifest_path.unlink()
    result2 = load_onnx_dfine_detector(onnx_path=onnx_path2, model_dir=_model_dir())
    assert result2.status is OnnxLoadStatus.MANIFEST_MISSING
