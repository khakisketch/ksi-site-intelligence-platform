"""D-FINE 실모델 adapter 수용기준 (Track B-1-6, 대표자 지정 2026-07-27).

모델 파일·[dfine] extra 가 있을 때만 실행된다 — CI(extra 미설치)에서는 전부 skip
되며, 이는 기능 미검증이 아니라 **분리된 게이트**다: 계약·정규화는 상시 테스트
(test_detection_adapter/test_detector_conformance/test_model_registry)가 덮고,
실모델 정합은 모델을 가진 환경(개발기·HIL 준비 세션)에서 이 파일이 덮는다.

수용기준 대조표(대표자 지정 → 담당 테스트):
- 원본 이미지 크기로 bbox 복원          → test_bboxes_restored_to_original_size
- xyxy 좌표 순서 고정                   → (Detection/BoundingBox 생성이 강제 — 위 테스트가 실증)
- finite confidence [0,1]              → DetectionAdapter 상시 테스트 + 여기 실모델 실증
- 퇴화 bbox 제거·화면 밖 clip/reject    → DetectionAdapter 상시 테스트(동일 코드 경로)
- COCO person class 매핑 고정           → test_person_detected_and_mapped
- 빈 결과 정상 처리                     → test_empty_scene_returns_empty
- NaN/Inf fail-closed                  → DetectionAdapter 상시 테스트(동일 코드 경로)
- 결정적 후처리                         → test_deterministic_inference
- stub 과 동일 conformance suite 통과   → TestRecordedFrameDetectorConformance
- 런타임 자동 다운로드 금지              → test_missing_model_fails_closed_without_download
- 미고정 revision 사용 금지             → test_digest_gate_blocks_wrong_content
- PyTorch↔ONNX 허용오차 일치            → test_onnx_export_matches_pytorch
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ksi_perception.dfine import (
    DFineDetector,
    DFineLoadStatus,
    RecordedFrameDetector,
    load_dfine_detector,
)

_MODEL_ID = "ksi-person-detector-dfine-s-coco"


# 게이트 판정은 공유 헬퍼 한 곳이다(감사 #20·#57) — 파일별 복붙은 한 곳만
# 갱신될 때 그 파일만 조용히 전량 skip 되는 회귀를 만든다(반증 리뷰 F8 계열).
from _real_model_gate import real_model_runtime_available, registry_model_dir  # noqa: E402

_MODEL_DIR = registry_model_dir(_MODEL_ID)
_PERSON_IMAGE = Path("models/test-assets/person.jpg")

_HAS_RUNTIME = real_model_runtime_available()

pytestmark = pytest.mark.skipif(
    not (_HAS_RUNTIME and _MODEL_DIR.is_dir() and _PERSON_IMAGE.is_file()),
    reason=(
        "[dfine] extra·모델·평가 이미지 없음 — tools/fetch_model.py + "
        "tools/fetch_test_assets.py 후 실행"
    ),
)


@pytest.fixture(scope="module")
def detector() -> DFineDetector:  # 모듈 스코프 캐시(모델 로드 1회)
    result = load_dfine_detector(local_dir=_MODEL_DIR)
    assert result.ok, result.detail
    assert result.detector is not None
    return result.detector


def _noise_image(height: int = 480, width: int = 640) -> np.ndarray:
    return np.random.default_rng(7).integers(0, 255, (height, width, 3), dtype=np.uint8)


def _person_image() -> np.ndarray:
    from PIL import Image

    with Image.open(_PERSON_IMAGE) as img:
        return np.asarray(img.convert("RGB"))


# ── 로드 게이트 ───────────────────────────────────────────────────────────────


def test_missing_model_fails_closed_without_download(tmp_path: Path) -> None:
    """모델 부재 = typed 실패 — 어떤 네트워크 접근도 다운로드도 없이."""
    result = load_dfine_detector(local_dir=tmp_path)
    assert result.status is DFineLoadStatus.REGISTRY_REJECTED
    assert result.detail is not None and "file_missing" in result.detail
    assert not any(tmp_path.iterdir()), "실패 경로가 파일을 만들었다 — 자동 다운로드 의심"


def test_load_never_touches_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """[다운로드 금지 실증 — 반증 리뷰 F7] 정상 로드 전체가 네트워크 무접촉이다.

    이전 테스트는 tmp_path 만 봤는데 HF 다운로드는 ``~/.cache/huggingface`` 로 가므로
    아무것도 관찰하지 못했다(공허). 여기서는 socket 자체를 봉인하고 **성공 로드**를
    수행한다 — 로드 경로 어딘가가 hub 로 나가면 즉시 터진다.
    """
    import socket

    def _no_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("모델 로드 중 네트워크 접근 발생 — 자동 다운로드 금지 위반")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    result = load_dfine_detector(local_dir=_MODEL_DIR)
    assert result.ok, result.detail


def test_digest_gate_blocks_wrong_content(tmp_path: Path) -> None:
    """[미고정 revision 금지] 이름이 같아도 digest 가 다르면 로드 거부."""
    for name in ("model.safetensors", "config.json", "preprocessor_config.json"):
        (tmp_path / name).write_bytes(b"not-the-registered-model")
    result = load_dfine_detector(local_dir=tmp_path)
    assert result.status is DFineLoadStatus.REGISTRY_REJECTED
    assert result.detail is not None and "digest_mismatch" in result.detail


def test_extra_file_in_model_dir_blocks_load(tmp_path: Path) -> None:
    """[반증 리뷰 F3] 원장에 없는 파일이 디렉토리에 있으면 로드 거부.

    transformers 는 디렉토리에서 원장이 모르는 파일(예: PEFT ``adapter_config.json``)을
    집어 base 가중치 위에 얹을 수 있다 — 그 파일들은 digest 검증을 받지 않으므로
    존재 자체를 거부한다(fail-closed).
    """
    import shutil

    for name in ("model.safetensors", "config.json", "preprocessor_config.json"):
        shutil.copy2(_MODEL_DIR / name, tmp_path / name)
    (tmp_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    result = load_dfine_detector(local_dir=tmp_path)
    assert result.status is DFineLoadStatus.REGISTRY_REJECTED
    assert result.detail is not None and "unverified_extra_file" in result.detail


def test_invalid_image_shape_rejected() -> None:
    """[반증 리뷰 F12] grayscale·RGBA·비 uint8 입력은 조용히 돌지 않고 거부된다."""
    result = load_dfine_detector(local_dir=_MODEL_DIR)
    assert result.ok and result.detector is not None
    for bad in (
        np.zeros((100, 100), dtype=np.uint8),  # 2D grayscale
        np.zeros((100, 100, 4), dtype=np.uint8),  # RGBA
        np.zeros((100, 100, 3), dtype=np.float32),  # 비 uint8
    ):
        with pytest.raises(ValueError, match="HWC uint8 RGB"):
            result.detector.detect_image(bad)


# ── 추론 계약 ─────────────────────────────────────────────────────────────────


def test_empty_scene_returns_empty(detector: DFineDetector) -> None:
    """노이즈 이미지 + 높은 threshold → 빈 결과가 정상 동작(예외·None 금지)."""
    result = detector.detect_image(_noise_image())
    high_conf = [d for d in result.detections if d.confidence >= 0.5]
    assert high_conf == []
    for d in result.detections:  # score_floor 통과분도 전부 유효 계약을 지켜야 한다
        assert 0.0 <= d.confidence <= 1.0


def test_bboxes_restored_to_original_size(detector: DFineDetector) -> None:
    """모델 입력(640×640)이 아니라 **원본 이미지** 픽셀 좌표계로 복원된다."""
    image = _person_image()
    height, width = image.shape[0], image.shape[1]
    assert (width, height) != (640, 640), "원본이 모델 입력 크기와 같으면 이 테스트는 공허하다"
    result = detector.detect_image(image)
    assert result.detections, "person 이미지에서 탐지 0건 — 복원 검증이 공허해진다"
    for d in result.detections:
        assert 0.0 <= d.bbox.x_min < d.bbox.x_max <= width
        assert 0.0 <= d.bbox.y_min < d.bbox.y_max <= height


def test_person_detected_and_mapped(detector: DFineDetector) -> None:
    """[비공허성 앵커] 실제 사람 이미지에서 person → 'Person' 매핑이 실증된다."""
    result = detector.detect_image(_person_image())
    persons = [d for d in result.detections if d.detection_class == "Person"]
    assert persons, "사람 이미지에서 Person 0건 — 모델·매핑·전처리 어딘가가 죽어 있다"
    assert max(d.confidence for d in persons) >= 0.5, (
        "Person 최고 신뢰도가 0.5 미만 — 전처리(정규화·색순서) 오류 의심"
    )


def test_deterministic_inference(detector: DFineDetector) -> None:
    """같은 입력·같은 모델 artifact → 같은 출력(값 동일성, CPU 경로)."""
    image = _person_image()
    first = detector.detect_image(image)
    second = detector.detect_image(image)
    assert first.detections == second.detections
    assert first.dropped == second.dropped


# ── conformance suite (stub 과 동일 계약) ─────────────────────────────────────

# DetectorConformanceSuite 는 tests/contract 의 테스트 모듈에 있다 — 같은 디렉토리의
# 모듈로 직접 import 한다(rootdir 기반 수집이라 경로가 안정적).
from test_detector_conformance import DetectorConformanceSuite  # noqa: E402


class TestRecordedFrameDetectorConformance(DetectorConformanceSuite):
    """녹화 프레임 + 실모델 조합이 stub 과 **같은** Detector 계약을 통과한다."""

    # class scope: 상속된 conformance 테스트 7개가 모델을 매번 재로드하지 않게
    # (반증 리뷰 F17 — RecordedFrameDetector 는 테스트 간 공유해도 결정적이다).
    @pytest.fixture(scope="class")
    def detector(self) -> RecordedFrameDetector:
        result = load_dfine_detector(local_dir=_MODEL_DIR)
        assert result.ok, result.detail
        image = _person_image()
        # conformance suite 는 1920×1080 frame 1 에서 최소 1건을 요구한다 — 사람
        # 이미지를 1920×1080 캔버스에 앉힌다(리샘플링 왜곡 없이 원본 픽셀 유지).
        canvas = np.zeros((1080, 1920, 3), dtype=np.uint8)
        h = min(1080, image.shape[0])
        w = min(1920, image.shape[1])
        canvas[:h, :w] = image[:h, :w]
        assert result.detector is not None
        return RecordedFrameDetector(frames={1: canvas}, dfine=result.detector)


# ── ONNX export 계약 ─────────────────────────────────────────────────────────


def test_onnx_export_matches_pytorch(detector: DFineDetector, tmp_path: Path) -> None:
    """[B1 승인 범위] ONNX export 산출물이 PyTorch 경로와 허용오차 내 일치한다.

    export 는 제품 경로(:mod:`ksi_perception.onnx_export`)를 그대로 쓴다 — 이 유틸의
    float64→float32 정규화(position embedding 상수 경로) 이후에도 수치가 같은
    모델임을 여기서 고정한다. 성능 판정은 하지 않는다(TensorRT·처리율은 B2
    Manifold HIL 의 몫).
    """
    import onnxruntime as ort
    import torch
    from ksi_perception.onnx_export import export_dfine_onnx

    image = _person_image()
    export = export_dfine_onnx(detector, image, tmp_path / "dfine-s.onnx", operator="parity-test")

    # 정규화 증거(반증 리뷰 F9): 바뀐 지점이 위치 임베딩 상수 경로(Cast/Constant/
    # value_info)에 한정되는지 데이터로 확인 — 가중치 initializer 가 깎였다면
    # "상수 경로뿐" 전제가 깨진 것이다.
    assert export.double_fixes, "double 정규화 0건 — 모델이 바뀌었거나 전제가 무효"
    weight_fixes = [f for f in export.double_fixes if f.startswith("initializer:")]
    assert weight_fixes == [], f"가중치 initializer 가 double 이었다: {weight_fixes}"

    processor = detector._processor  # noqa: SLF001
    inputs = processor(images=image, return_tensors="pt")
    with torch.inference_mode():
        torch_out = detector._model(**inputs)  # noqa: SLF001

    session = ort.InferenceSession(str(export.path), providers=["CPUExecutionProvider"])
    onnx_logits, onnx_boxes = session.run(
        ["logits", "pred_boxes"], {"pixel_values": inputs["pixel_values"].numpy()}
    )

    np.testing.assert_allclose(
        torch_out.logits.numpy(), onnx_logits, rtol=1e-3, atol=1e-4
    )
    np.testing.assert_allclose(
        torch_out.pred_boxes.numpy(), onnx_boxes, rtol=1e-3, atol=1e-4
    )


# ── 분류 계보 (INV-031, F13) — 실모델 회귀 ────────────────────────────────────


def test_person_class_comes_only_from_person_label(detector: DFineDetector) -> None:
    """[F13 실모델 반증] 'Person' 은 원시 라벨 'person' 에서만 나온다.

    canonical class 와 원시 라벨의 계보가 실모델 경로에서 실제로 보존되며,
    비 person 라벨(차량 등)이 Person 으로 번역되는 경로가 없음을 실증한다.
    """
    result = detector.detect_image(_person_image())
    persons = [d for d in result.detections if d.detection_class == "Person"]
    assert persons, "person 이미지에서 Person 0건 — 반증이 공허해진다"
    for d in result.detections:
        assert d.ontology_version == "ksi-ontology-v1"
        if d.detection_class == "Person":
            assert d.source_class_name == "person", (
                f"Person 이 원시 라벨 {d.source_class_name!r} 에서 나왔다 — 계보 오염"
            )
        else:
            assert d.source_class_name != "person", (
                "person 라벨이 Person 아닌 class 로 번역됐다"
            )


def test_unsupported_labels_dropped_with_reason_not_person(detector: DFineDetector) -> None:
    """[F13] 미지원 COCO 라벨은 Person fallback 없이 typed drop 으로 남는다."""
    result = detector.detect_image(_person_image())
    from ksi_domain.detection_adapter import DropReason

    unknown_drops = [d for d in result.dropped if d.reason is DropReason.UNKNOWN_LABEL]
    for dropped in unknown_drops:
        assert dropped.raw.label not in ("person", "car", "truck"), (
            "지원 라벨이 UNKNOWN_LABEL 로 잘못 drop 됐다"
        )
    # 살아남은 Detection 중 미지원 라벨 유래는 0건이어야 한다(fallback 부재의 실증).
    supported = {"person", "car", "truck"}
    assert all(d.source_class_name in supported for d in result.detections)


def test_free_dict_ontology_rejected_by_loader() -> None:
    """[Blocker 1] 로더에 자유 dict 를 넘기면 typed 거부 — OntologyMapping 전용."""
    result = load_dfine_detector(
        local_dir=_MODEL_DIR,
        ontology={"truck": "Person"},  # type: ignore[arg-type]
    )
    assert result.status is DFineLoadStatus.LOAD_FAILED
    assert result.detail is not None and "OntologyMapping" in result.detail
