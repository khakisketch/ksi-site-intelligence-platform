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
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from ksi_domain.detection import BoundingBox
from ksi_perception.dfine import DFineDetector, load_dfine_detector
from ksi_perception.onnx_export import OnnxExportResult
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
    "partial_person",
]

# 장면별 의도 현상 기대 — 2026-07-28 실모델 실측으로 확정(추정 아님). 이 앵커가
# 없으면 "양 경로 모두 빈 결과"로도 conformance 가 공허하게 통과한다(재검토 P1).
# person@0.5 = confidence>=0.5 인 Person 수(저신뢰 floor 통과 노이즈 제외 기준).
_SCENE_EXPECTATIONS: dict[str, dict[str, float]] = {
    "single_person": {"person_at_05_min": 1},  # 크롭에도 어머니+아기 — 실측 2
    "multiple_people": {"person_at_05_min": 2},  # 실측 4
    "no_detection": {"detections_max": 0},  # 단색 — 실측 0(floor 미달 전멸)
    "small_person": {"person_at_05_min": 1},  # 실측 3
    "border_person": {"person_at_05_min": 1, "clipped_min": 1},  # 경계 클리핑 실증(실측 1)
    "overlap_people": {"person_at_05_min": 2, "overlap_iou_min": 0.3},  # 겹침 실증
    "non_person_car": {"vehicle_min": 1, "person_at_05_max": 0},  # 실측 차량 16
    "unsupported_scene": {"unknown_label_drop_min": 1},  # 미지원 drop 경로(실측 142)
    "low_conf_noise": {"unknown_label_drop_min": 1, "person_at_05_max": 0},  # 실측 300
    "partial_person": {"person_at_05_min": 1},  # 부분 가시 강건성(실측 2)
}


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
    # 기준 6b(재검토 P1): clipped 채널도 (class, area_kept, 원시 계보) 로 비교 —
    # 접지점 편향 기록이 경로 간 다르면 하류 위치 의미가 달라진다.
    clipped_a = sorted(
        (c.detection.detection_class, round(c.area_kept, 4), c.detection.source_class_name or "")
        for c in a.clipped
    )
    clipped_b = sorted(
        (c.detection.detection_class, round(c.area_kept, 4), c.detection.source_class_name or "")
        for c in b.clipped
    )
    assert clipped_a == clipped_b, f"{scene}: clipped 채널 불일치"


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    ox = max(0.0, min(a.x_max, b.x_max) - max(a.x_min, b.x_min))
    oy = max(0.0, min(a.y_max, b.y_max) - max(a.y_min, b.y_min))
    inter = ox * oy
    if inter <= 0:
        return 0.0
    union = (
        (a.x_max - a.x_min) * (a.y_max - a.y_min)
        + (b.x_max - b.x_min) * (b.y_max - b.y_min)
        - inter
    )
    return inter / union


@pytest.mark.parametrize("scene", _SCENES)
def test_scene_intended_phenomenon_is_real(
    scene: str, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[재검토 P1] 장면별 의도 현상이 실제로 유발된다 — "양 경로 모두 빈 결과"류
    공허 통과 차단. 기대값은 실측(2026-07-28)으로 확정된 하한/상한이다."""
    torch_det, _ = detectors
    expect = _SCENE_EXPECTATIONS[scene]
    result = torch_det.detect_image(_load_scene(scene))
    persons_05 = [
        d for d in result.detections if d.detection_class == "Person" and d.confidence >= 0.5
    ]
    if "person_at_05_min" in expect:
        assert len(persons_05) >= expect["person_at_05_min"], (
            f"{scene}: person@0.5 {len(persons_05)} < 기대 하한 — 장면 전제 붕괴"
        )
    if "person_at_05_max" in expect:
        assert len(persons_05) <= expect["person_at_05_max"]
    if "detections_max" in expect:
        assert len(result.detections) <= expect["detections_max"]
    if "vehicle_min" in expect:
        vehicles = [
            d
            for d in result.detections
            if d.detection_class in ("Vehicle_Car", "Vehicle_Truck")
        ]
        assert len(vehicles) >= expect["vehicle_min"]
    if "clipped_min" in expect:
        assert len(result.clipped) >= expect["clipped_min"], (
            f"{scene}: 경계 클리핑 미발생 — 장면 이름·주장 수정 필요"
        )
    if "unknown_label_drop_min" in expect:
        unknown = [d for d in result.dropped if d.reason.value == "unknown_label"]
        assert len(unknown) >= expect["unknown_label_drop_min"]
    if "overlap_iou_min" in expect:
        pairs = [
            _iou(a.bbox, b.bbox)
            for i, a in enumerate(persons_05)
            for b in persons_05[i + 1 :]
        ]
        assert pairs and max(pairs) >= expect["overlap_iou_min"], (
            f"{scene}: 인물 겹침(IoU) 미실증"
        )


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
    export_dfine_onnx(torch_det, _load_scene("no_detection"), onnx_path, operator="tamper-test")
    # 변조
    data = bytearray(onnx_path.read_bytes())
    data[-1] ^= 0xFF
    onnx_path.write_bytes(bytes(data))
    result = load_onnx_dfine_detector(onnx_path=onnx_path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH

    # manifest 삭제
    onnx_path2 = tmp_path / "m2.onnx"
    export2 = export_dfine_onnx(
        torch_det, _load_scene("no_detection"), onnx_path2, operator="tamper-test"
    )
    assert export2.manifest_path is not None
    export2.manifest_path.unlink()
    result2 = load_onnx_dfine_detector(onnx_path=onnx_path2, model_dir=_model_dir())
    assert result2.status is OnnxLoadStatus.MANIFEST_MISSING


# ── 신뢰 사슬 반증 (재검토 P0, 2026-07-28) ───────────────────────────────────
#
# manifest 는 산출물 옆의 자기 서술 — ONNX+manifest 를 함께 교체하면 자체 일관성
# 검사(digest 상호 대조)를 통과한다. Registry(코드리뷰 원장) export 레코드가 외부
# 권위 앵커로 대조돼야 사슬이 닫힌다. 아래가 지정 반증 전건이다.


def _export_valid(
    detectors: tuple[DFineDetector, OnnxDFineDetector],
    path: Path,
    *,
    opset_version: int = 17,
    operator: str = "refutation-test",
) -> OnnxExportResult:
    from ksi_perception.onnx_export import export_dfine_onnx

    torch_det, _ = detectors
    return export_dfine_onnx(
        torch_det,
        _load_scene("no_detection"),
        path,
        opset_version=opset_version,
        operator=operator,
    )


def _rewrite_manifest(manifest_path: Path, mutate: Callable[[dict], None]) -> None:
    import json

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(data)
    manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_self_consistent_swap_rejected_by_registry_anchor(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[반증 1 — 핵심] 다른 유효 ONNX + 그에 맞춘 자체 일관 manifest → Registry
    앵커 불일치로 거부. opset 18 export 는 실제 유효 그래프지만 등록된 산출물이
    아니다."""
    export = _export_valid(detectors, tmp_path / "swapped.onnx", opset_version=18)
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH
    assert result.detail is not None and "Registry" in result.detail


def test_source_digest_tamper_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[반증 2] source_artifact_digests 변조 → 거부 (다른 원본 주장 차단)."""
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)

    def mutate(d: dict) -> None:
        d["source_artifact_digests"]["model.safetensors"] = "0" * 64

    assert export.manifest_path is not None
    _rewrite_manifest(export.manifest_path, mutate)
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH
    assert result.detail is not None and "source_artifact_digests" in result.detail


def test_opset_tamper_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[반증 3] manifest opset 변조 → Registry opset 과 불일치 거부.

    onnx_sha256 필드는 그대로 두므로(실물과 일치) opset 대조가 없으면 통과했을
    입력이다 — 단 순수 opset 축 검증을 위해 digest 대조를 통과하는 등록 산출물이
    필요해, 여기서는 opset 만 바꾼 manifest 가 digest 검사보다 먼저 죽지 않도록
    Registry 앵커 digest 와 일치하는 export 가 전제다. 전제가 성립하지 않으면
    (toolchain 변경으로 digest 상이) skip 이 아니라 명시 실패로 드러난다.
    """
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)

    def mutate(d: dict) -> None:
        d["opset"] = 19

    assert export.manifest_path is not None
    _rewrite_manifest(export.manifest_path, mutate)
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH


@pytest.mark.parametrize(
    "missing_field",
    ["preprocessing", "postprocessing", "graph_transforms", "source_artifact_digests"],
)
def test_missing_manifest_field_rejected(
    missing_field: str, tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[반증 4] 필수 필드 누락 manifest 는 계보가 아니다 — 거부."""
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)

    def mutate(d: dict) -> None:
        del d[missing_field]

    assert export.manifest_path is not None
    _rewrite_manifest(export.manifest_path, mutate)
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.MANIFEST_MISSING
    assert result.detail is not None and missing_field in result.detail


def test_registry_manifest_digest_mismatch_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[반증 5] manifest.onnx_sha256 을 실물과 함께 위조해도 Registry 앵커와 다르면
    거부 — 자체 일관성으로는 통과할 수 없다."""
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)
    # 실물 1바이트 변조 + manifest 의 digest 를 변조 실물에 맞춰 재계산(자체 일관)
    data = bytearray(export.path.read_bytes())
    data[-1] ^= 0xFF
    export.path.write_bytes(bytes(data))
    import hashlib

    new_digest = hashlib.sha256(export.path.read_bytes()).hexdigest()

    def mutate(d: dict) -> None:
        d["onnx_sha256"] = new_digest

    assert export.manifest_path is not None
    _rewrite_manifest(export.manifest_path, mutate)
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH
    assert result.detail is not None and "Registry" in result.detail


def test_operator_unspecified_rejected_at_export(
    detectors: tuple[DFineDetector, OnnxDFineDetector], tmp_path: Path
) -> None:
    """[반증 7] operator 공백/'unspecified' 는 export 생성 자체가 거부된다."""
    from ksi_perception.onnx_export import export_dfine_onnx

    torch_det, _ = detectors
    for bad in ("", "  ", "unspecified"):
        with pytest.raises(ValueError, match="operator"):
            export_dfine_onnx(
                torch_det, _load_scene("no_detection"), tmp_path / "x.onnx", operator=bad
            )


def test_non_utc_exported_at_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[반증 8] exported_at_utc 가 UTC 가 아니거나 파싱 불가 → 거부."""
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)
    assert export.manifest_path is not None
    for bad in ("2026-07-28T12:00:00+09:00", "not-a-date"):

        def _set_bad(d: dict, value: str = bad) -> None:
            d["exported_at_utc"] = value

        _rewrite_manifest(export.manifest_path, _set_bad)
        result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
        assert result.status is OnnxLoadStatus.MANIFEST_MISSING, bad


# ── typed 신뢰 경계 반증 A1~A13 (재검토 P1, 2026-07-28) ──────────────────────
#
# malformed manifest 는 어떤 형태든 raw traceback 이 아니라 typed 결과여야 한다.
# (A14 정상 로드 = detectors fixture 자체 / A15 자체일관 교체 거부 = 기존
#  test_self_consistent_swap_rejected_by_registry_anchor 가 담당)

_MALFORMED_MUTATIONS: dict[str, object] = {
    "A1_opset_str": ("opset", "bad"),
    "A2_opset_bool": ("opset", True),
    "A3a_inputs_dict": ("inputs", {}),
    "A3b_inputs_empty_obj": ("inputs", [{}]),
    "A3c_inputs_null": ("inputs", None),
    "A4_dup_output_name": (
        "outputs",
        [
            {"name": "logits", "shape": [1, 300, 80], "dtype": "float32", "meaning": "x"},
            {"name": "logits", "shape": [1, 300, 4], "dtype": "float32", "meaning": "y"},
        ],
    ),
    "A5a_sha_short": ("onnx_sha256", "abc123"),
    "A5b_sha_nonhex": ("onnx_sha256", "z" * 64),
    "A6_source_digest_nonhex": ("source_artifact_digests", {"model.safetensors": "nothex"}),
    "A7a_operator_int": ("operator", 7),
    "A7b_operator_list": ("operator", ["a"]),
    "A7c_operator_dict": ("operator", {"x": 1}),
    "A8a_exported_at_list": ("exported_at_utc", ["2026"]),
    "A8b_exported_at_dict": ("exported_at_utc", {}),
    "extra_unknown_field": ("__unknown_field__", "schema v1 은 extra forbid"),
    "shape_bool_dim": (
        "inputs",
        [{"name": "pixel_values", "shape": [True, 3, 640, 640], "dtype": "float32",
          "axes": "static"}],
    ),
    "dtype_unknown": (
        "inputs",
        [{"name": "pixel_values", "shape": [1, 3, 640, 640], "dtype": "float64",
          "axes": "static"}],
    ),
}


@pytest.mark.parametrize("case", sorted(_MALFORMED_MUTATIONS))
def test_malformed_manifest_typed_rejection_no_traceback(
    case: str, tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[A1~A8 + fuzz] 필드 타입·구조·형식 오류 전건이 typed 거부, 예외 전파 0."""
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)
    mutation = _MALFORMED_MUTATIONS[case]
    assert isinstance(mutation, tuple)
    field_name, new_value = str(mutation[0]), mutation[1]

    def mutate(d: dict) -> None:
        if field_name == "__unknown_field__":
            d["totally_unknown"] = new_value
        else:
            d[field_name] = new_value

    assert export.manifest_path is not None
    _rewrite_manifest(export.manifest_path, mutate)
    # 예외가 새면 이 호출 자체가 테스트 실패(전파 0 검증)다.
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.MANIFEST_MISSING, case
    assert result.detector is None


def test_manifest_nan_constant_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[A8·비표준 JSON] NaN/Infinity 상수는 파싱 단계에서 거부된다."""
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)
    assert export.manifest_path is not None
    text = export.manifest_path.read_text(encoding="utf-8")
    text = text.replace('"opset": 17', '"opset": NaN')
    export.manifest_path.write_text(text, encoding="utf-8")
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.MANIFEST_MISSING


def test_manifest_toplevel_not_object_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)
    assert export.manifest_path is not None
    export.manifest_path.write_text('["not", "an", "object"]', encoding="utf-8")
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.MANIFEST_MISSING


def test_input_dtype_claim_vs_session_mismatch_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[A9] manifest 가 float16 을 주장하는데 실제 세션이 float32 → 거부.

    substring 비교였다면 "float" 공통으로 통과했을 조합 — canonical 대응표 비교의
    실증이다.
    """
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)

    def mutate(d: dict) -> None:
        d["inputs"][0]["dtype"] = "float16"

    assert export.manifest_path is not None
    _rewrite_manifest(export.manifest_path, mutate)
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH
    assert result.detail is not None and "dtype" in result.detail


def test_output_dtype_mismatch_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[A10] 출력 dtype 불일치 거부."""
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)

    def mutate(d: dict) -> None:
        d["outputs"][0]["dtype"] = "int64"

    assert export.manifest_path is not None
    _rewrite_manifest(export.manifest_path, mutate)
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH
    assert result.detail is not None and "dtype" in result.detail


def test_output_shape_mismatch_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[A11] 출력 shape 불일치 거부 — 세션 실계약이 출력까지 검증됨의 실증."""
    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)

    def mutate(d: dict) -> None:
        d["outputs"][0]["shape"] = [1, 300, 91]

    assert export.manifest_path is not None
    _rewrite_manifest(export.manifest_path, mutate)
    result = load_onnx_dfine_detector(onnx_path=export.path, model_dir=_model_dir())
    assert result.status is OnnxLoadStatus.DIGEST_MISMATCH
    assert result.detail is not None and "shape" in result.detail


def test_malformed_registry_export_rejected(
    tmp_path: Path, detectors: tuple[DFineDetector, OnnxDFineDetector]
) -> None:
    """[A12] Registry export 섹션 구조 오류 → MALFORMED_REGISTRY (typed)."""
    import shutil

    import yaml

    export = _export_valid(detectors, tmp_path / "m.onnx", opset_version=17)
    # 실제 Registry 를 복사해 export.opset 만 오염
    registry = yaml.safe_load(
        Path("docs/models/MODEL_REGISTRY.yaml").read_text(encoding="utf-8")
    )
    registry["models"][0]["export"]["opset"] = "seventeen"
    bad_registry = tmp_path / "registry.yaml"
    bad_registry.write_text(yaml.safe_dump(registry, allow_unicode=True), encoding="utf-8")
    # 모델 파일은 실제 검증 디렉토리를 그대로 참조
    model_dir = tmp_path / "model"
    shutil.copytree(_model_dir(), model_dir)
    result = load_onnx_dfine_detector(
        onnx_path=export.path, model_dir=model_dir, registry_path=bad_registry
    )
    assert result.status is OnnxLoadStatus.REGISTRY_REJECTED
    assert result.detail is not None and "malformed_registry" in result.detail
