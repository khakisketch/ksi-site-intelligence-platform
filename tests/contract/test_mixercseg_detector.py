"""MixerCSeg 실모델 adapter 수용기준 (Phase 4, MODEL-P4-001).

[mixercseg] extra·모델 가중치가 있을 때만 실행된다 — CI(extra 미설치)에서는 전부
skip 되며, 이는 기능 미검증이 아니라 **분리된 게이트**다: 계약(round-trip)은 상시
테스트(test_defect_candidate.py)가 덮고, 실모델 정합은 모델을 가진 환경에서 이
파일이 덮는다(``ksi_perception`` 의 D-FINE 실모델 테스트와 동일 원칙,
``tests/contract/test_dfine_detector.py`` 참고).

수용기준 대조표:
- 런타임 자동 다운로드 금지              → test_missing_model_fails_closed_without_download
- 미고정 revision 사용 금지              → test_digest_gate_blocks_wrong_content
- 원장 외 파일 존재 시 로드 거부          → test_extra_file_in_model_dir_blocks_load
- 로드 전체가 네트워크 무접촉            → test_load_never_touches_network
- 구조 어긋난 입력 fail-closed          → test_invalid_image_shape_rejected
- 신호 없는 입력 → 빈 결과(예외 아님)    → test_noise_image_yields_no_candidates
- 실제 균열형 패턴 → 후보 검출           → test_synthetic_crack_pattern_is_detected
- 결정적 추론                          → test_deterministic_inference
- DefectCandidate 출력이 계약 스키마 만족 → test_candidate_output_satisfies_contract_schema
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from ksi_defect_detection.mixercseg_adapter import (
    MixerCSegDetector,
    MixerCSegLoadStatus,
    load_mixercseg_detector,
)
from ksi_defect_detection.postprocess import defect_candidates_from_probability_map
from ksi_defect_detection.registry import load_model_entry
from ksi_event_contracts.defect_candidate import defect_candidate_wire_dict

_MODEL_ID = "ksi-crack-segmenter-mixercseg-deepcrack"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "defect-candidate.v1.json"


def _registry_model_dir(model_id: str = _MODEL_ID) -> Path:
    """Registry 계보로부터 로컬 모델 디렉토리를 파생한다(원장이 SSOT) —
    tools/fetch_defect_model.py 와 동일 규칙(model_id 기준, google_drive 출처는
    사람이 읽을 이름이 없어 HF 계열과 다르게 파생한다)."""
    check = load_model_entry(model_id)
    if not check.ok or check.entry is None:
        return Path("models/__registry_unreadable__")
    return Path("models") / check.entry.model_id / check.entry.revision


_MODEL_DIR = _registry_model_dir()
_HAS_RUNTIME = all(
    importlib.util.find_spec(module) is not None
    for module in ("torch", "cv2", "mmcv", "mmseg", "mmengine", "timm")
)

pytestmark = pytest.mark.skipif(
    not (_HAS_RUNTIME and _MODEL_DIR.is_dir()),
    reason=(
        "[mixercseg] extra·모델 없음 — uv sync --extra mixercseg + "
        "tools/fetch_defect_model.py 후 실행"
    ),
)


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def detector() -> MixerCSegDetector:  # 모듈 스코프 캐시(모델 로드 1회 — 수 초 걸림)
    result = load_mixercseg_detector(local_dir=_MODEL_DIR, device="cpu")
    assert result.ok, result.detail
    assert result.detector is not None
    return result.detector


def _noise_image(height: int = 480, width: int = 640) -> np.ndarray:
    return np.random.default_rng(7).integers(0, 255, (height, width, 3), dtype=np.uint8)


def _synthetic_crack_image() -> np.ndarray:
    """회색 콘크리트 배경 + 어두운 얇은 대각선 2개(실제 데이터셋 없이 재현 가능한
    결정적 픽스처) — 실제 균열 사진은 아니지만 파이프라인이 '신호 있음'과
    '신호 없음'을 구분하는지는 이걸로 충분히 검증된다."""
    import cv2

    rng = np.random.default_rng(11)
    image = np.full((512, 512, 3), 180, dtype=np.uint8)
    noise = rng.integers(-15, 15, size=image.shape)
    image = (image.astype(np.int16) + noise).clip(0, 255).astype(np.uint8)
    cv2.line(image, (30, 480), (480, 30), color=(40, 40, 40), thickness=3)
    cv2.line(image, (100, 100), (400, 420), color=(35, 35, 35), thickness=2)
    return image


# ── 로드 게이트 ───────────────────────────────────────────────────────────────


def test_missing_model_fails_closed_without_download(tmp_path: Path) -> None:
    """모델 부재 = typed 실패 — 어떤 네트워크 접근도 다운로드도 없이."""
    result = load_mixercseg_detector(local_dir=tmp_path)
    assert result.status is MixerCSegLoadStatus.REGISTRY_REJECTED
    assert result.detail is not None and "file_missing" in result.detail
    assert not any(tmp_path.iterdir()), "실패 경로가 파일을 만들었다 — 자동 다운로드 의심"


def test_digest_gate_blocks_wrong_content(tmp_path: Path) -> None:
    """[미고정 revision 금지] 이름이 같아도 digest 가 다르면 로드 거부."""
    (tmp_path / "checkpoint_DeepCrack.pth").write_bytes(b"not-the-registered-checkpoint")
    result = load_mixercseg_detector(local_dir=tmp_path)
    assert result.status is MixerCSegLoadStatus.REGISTRY_REJECTED
    assert result.detail is not None and "digest_mismatch" in result.detail


def test_extra_file_in_model_dir_blocks_load(tmp_path: Path) -> None:
    """원장에 없는 파일이 디렉토리에 있으면 로드 거부(fail-closed)."""
    import shutil

    shutil.copy2(_MODEL_DIR / "checkpoint_DeepCrack.pth", tmp_path / "checkpoint_DeepCrack.pth")
    (tmp_path / "unexpected_extra.bin").write_bytes(b"x")
    result = load_mixercseg_detector(local_dir=tmp_path)
    assert result.status is MixerCSegLoadStatus.REGISTRY_REJECTED
    assert result.detail is not None and "unverified_extra_file" in result.detail


def test_vendor_import_does_not_pollute_sys_modules() -> None:
    """[risk defect-detection-vendor-syspath-pollution] 로드 후 'models'/'VMamba'
    라는 흔한 top-level 이름이 sys.modules 에 남지 않는다 — 남으면 프로세스의
    다른 곳에서 같은 이름을 import 할 때 벤더 코드를 잘못 받는다."""
    result = load_mixercseg_detector(local_dir=_MODEL_DIR, device="cpu")
    assert result.ok, result.detail
    assert "models" not in sys.modules
    assert "VMamba" not in sys.modules


def test_vendor_import_does_not_clobber_preexisting_bare_names() -> None:
    """[risk defect-detection-vendor-syspath-pollution] 로드 전에 이미
    'models'/'VMamba' 라는 이름으로 뭔가 다른 게 import 돼 있었다면(흔한 이름이라
    실제로 있을 수 있다), 로드가 끝난 뒤 그 값을 그대로 복구한다 — 우리가
    영구히 덮어쓰지 않는다."""
    fake_models = types.ModuleType("models")
    fake_vmamba = types.ModuleType("VMamba")
    original_models = sys.modules.get("models")
    original_vmamba = sys.modules.get("VMamba")
    sys.modules["models"] = fake_models
    sys.modules["VMamba"] = fake_vmamba
    try:
        result = load_mixercseg_detector(local_dir=_MODEL_DIR, device="cpu")
        assert result.ok, result.detail
        assert sys.modules["models"] is fake_models
        assert sys.modules["VMamba"] is fake_vmamba
    finally:
        if original_models is not None:
            sys.modules["models"] = original_models
        else:
            sys.modules.pop("models", None)
        if original_vmamba is not None:
            sys.modules["VMamba"] = original_vmamba
        else:
            sys.modules.pop("VMamba", None)


def test_load_never_touches_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """[다운로드 금지 실증] 정상 로드 전체가 네트워크 무접촉이다."""
    import socket

    def _no_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("모델 로드 중 네트워크 접근 발생 — 자동 다운로드 금지 위반")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    result = load_mixercseg_detector(local_dir=_MODEL_DIR, device="cpu")
    assert result.ok, result.detail


def test_invalid_image_shape_rejected(detector: MixerCSegDetector) -> None:
    """구조가 어긋난 입력(grayscale·RGBA·비 uint8)은 조용히 돌지 않고 거부된다."""
    for bad in (
        np.zeros((100, 100), dtype=np.uint8),  # 2D grayscale
        np.zeros((100, 100, 4), dtype=np.uint8),  # RGBA
        np.zeros((100, 100, 3), dtype=np.float32),  # 비 uint8
    ):
        with pytest.raises(ValueError, match="HWC uint8 RGB"):
            detector.segment_image(bad)


# ── 추론·후처리 계약 ───────────────────────────────────────────────────────────


def test_noise_image_yields_no_candidates(detector: MixerCSegDetector) -> None:
    """신호 없는 입력(랜덤 노이즈) → 빈 결과가 정상 동작(예외·None 금지)."""
    prob = detector.segment_image(_noise_image())
    assert prob.min() >= 0.0 and prob.max() <= 1.0
    candidates = defect_candidates_from_probability_map(
        prob,
        source_media_id="noise-1",
        model_id=detector.model_id,
        source_digests=detector.source_digests,
    )
    assert candidates == []


def test_synthetic_crack_pattern_is_detected(detector: MixerCSegDetector) -> None:
    """[핵심] 균열형 패턴이 있는 입력은 실제로 후보를 낸다 — noise 테스트가 '항상
    빈 결과'인 죽은 파이프라인을 가리지 않는다는 것의 대응 증거."""
    prob = detector.segment_image(_synthetic_crack_image())
    candidates = defect_candidates_from_probability_map(
        prob,
        source_media_id="synthetic-crack-1",
        model_id=detector.model_id,
        source_digests=detector.source_digests,
    )
    assert len(candidates) >= 1
    top = candidates[0]
    assert 0.0 <= top.confidence <= 1.0
    assert top.measurements is not None
    assert top.measurements.area_px2 is not None and top.measurements.area_px2 > 0


def test_probability_map_restored_to_original_image_size(detector: MixerCSegDetector) -> None:
    """[핵심 회귀 — reviewer 지적 F3] 모델 입력(512x512)이 아니라 **원본** 이미지
    픽셀 좌표계로 확률맵이 복원된다 — 그렇지 않으면 postprocess 가 만드는
    polygon·면적·길이가 전부 모델 좌표계 값이 돼 호출자가 원본으로 되돌릴
    방법이 없다(비등방 리사이즈는 단일 배율로도 복원 불가)."""
    height, width = 300, 700  # 512x512 와도, 서로와도 다른 비정사각 크기
    image = np.random.default_rng(3).integers(0, 255, (height, width, 3), dtype=np.uint8)
    prob = detector.segment_image(image)
    assert prob.shape == (height, width), "확률맵이 원본 크기가 아니라 모델 입력 크기다"
    assert prob.min() >= 0.0 and prob.max() <= 1.0


def test_deterministic_inference(detector: MixerCSegDetector) -> None:
    """같은 입력 2회 → bit-exact 동일 출력(2026-08-07 이 워크스페이스 CPU 실측
    기반 — VMamba/models/csm_triton.py 로컬 patch 이후 확정)."""
    image = _synthetic_crack_image()
    prob1 = detector.segment_image(image)
    prob2 = detector.segment_image(image)
    assert np.array_equal(prob1, prob2)


def test_candidate_output_satisfies_contract_schema(detector: MixerCSegDetector) -> None:
    """DefectCandidate wire 산출이 계약 스키마를 만족한다 — 두 정본이 갈라지지 않게."""
    prob = detector.segment_image(_synthetic_crack_image())
    candidates = defect_candidates_from_probability_map(
        prob,
        source_media_id="synthetic-crack-1",
        model_id=detector.model_id,
        source_digests=detector.source_digests,
    )
    assert candidates
    validator = _validator()
    for candidate in candidates:
        validator.validate(defect_candidate_wire_dict(candidate))
