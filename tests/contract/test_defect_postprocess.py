"""확률맵 → DefectCandidate 후처리 계약 — 모델 없이 상시 실행(reviewer 지적
F2: postprocess.py 는 순수 numpy/cv2 코드인데 [mixercseg] 실모델 게이트 뒤에만
테스트가 있어 CI 에서 한 줄도 실행되지 않았다. opencv-python-headless 가 이제
ksi-defect-detection base 의존이라(pyproject.toml, torch/mmcv 대비 훨씬 가벼움)
모델 가중치 없이도 합성 확률맵으로 검증 가능하다).
"""

from __future__ import annotations

import numpy as np
from ksi_defect_detection.postprocess import (
    DEFAULT_THRESHOLD,
    MIN_CONTOUR_AREA_PX2,
    defect_candidates_from_probability_map,
)


def test_all_zero_probability_yields_no_candidates() -> None:
    prob = np.zeros((256, 256), dtype=np.float32)
    candidates = defect_candidates_from_probability_map(
        prob, source_media_id="m", model_id="model-x", source_digests={}
    )
    assert candidates == []


def test_thin_one_pixel_line_is_not_dropped() -> None:
    """[핵심 회귀 — reviewer 지적 P2] cv2.contourArea(폴리곤 면적)는 폭 1px
    형상에서 좌우 윤곽이 거의 겹쳐 0에 가깝게 퇴화한다 — 그 경로로 필터링하면
    가장 가는(=가장 실사용 가치가 큰 초기) 균열이 노이즈로 오인돼 통째로
    사라진다. area_px2 는 폴리곤 면적이 아니라 실제 foreground 픽셀 카운트
    (cv2.countNonZero)여야 한다."""
    prob = np.zeros((256, 256), dtype=np.float32)
    for i in range(100):
        prob[i, i] = 1.0
    candidates = defect_candidates_from_probability_map(
        prob, source_media_id="m", model_id="model-x", source_digests={}
    )
    assert len(candidates) == 1
    assert candidates[0].measurements is not None
    assert candidates[0].measurements.area_px2 == 100.0


def test_small_speck_below_min_area_is_dropped() -> None:
    """MIN_CONTOUR_AREA_PX2 미만인 조각(단일 픽셀 요동)은 노이즈로 버린다."""
    prob = np.zeros((256, 256), dtype=np.float32)
    prob[10, 10] = 1.0  # 1px — MIN_CONTOUR_AREA_PX2(9) 미만
    candidates = defect_candidates_from_probability_map(
        prob, source_media_id="m", model_id="model-x", source_digests={}
    )
    assert candidates == []


def test_filled_square_measurements_are_plausible() -> None:
    """10x10 채움 사각형 — area=100, confidence=1.0(threshold 이상 전 영역이
    1.0)이 되는 결정적 골든벡터."""
    prob = np.zeros((256, 256), dtype=np.float32)
    prob[50:60, 50:60] = 1.0
    candidates = defect_candidates_from_probability_map(
        prob, source_media_id="square-1", model_id="model-x", source_digests={}
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.confidence == 1.0
    assert candidate.measurements is not None
    assert candidate.measurements.area_px2 == 100.0
    assert candidate.image_size.width_px == 256
    assert candidate.image_size.height_px == 256
    assert candidate.defect_candidate_id == "defect-square-1-0"


def test_min_area_scales_with_resolution() -> None:
    """[핵심 회귀 — reviewer 재검토 지적] MIN_CONTOUR_AREA_PX2(9)는 512x512 기준
    캘리브레이션이다. mixercseg_adapter.segment_image 가 이제 원본 해상도로
    확률맵을 복원해서 내놓으므로(F3), 절대 픽셀수로 문턱을 고정하면 큰 이미지
    에서 필터가 사실상 무력화된다(4000x3000에서 실측: 7x7=49px² 파편이 9px²
    문턱을 그냥 통과 — 모델좌표론 1.07px² 짜리 잡음인데도). 같은 해상도에서
    진짜 큰 결함(200x200)은 여전히 통과해야 한다."""
    small_fragment = np.zeros((3000, 4000), dtype=np.float32)
    small_fragment[1000:1007, 1000:1007] = 1.0  # 49px² — 모델좌표 환산 ~1.07px²
    assert (
        defect_candidates_from_probability_map(
            small_fragment, source_media_id="m", model_id="x", source_digests={}
        )
        == []
    )

    real_defect = np.zeros((3000, 4000), dtype=np.float32)
    real_defect[1000:1200, 1000:1200] = 1.0  # 200x200=40000px²
    candidates = defect_candidates_from_probability_map(
        real_defect, source_media_id="m", model_id="x", source_digests={}
    )
    assert len(candidates) == 1
    assert candidates[0].measurements is not None
    assert candidates[0].measurements.area_px2 == 40000.0


def test_threshold_excludes_low_confidence_region() -> None:
    """threshold 미만인 영역은 이진화 단계에서 통째로 제외된다."""
    prob = np.full((256, 256), DEFAULT_THRESHOLD - 0.01, dtype=np.float32)
    candidates = defect_candidates_from_probability_map(
        prob, source_media_id="m", model_id="model-x", source_digests={}
    )
    assert candidates == []


def test_custom_min_area_threshold_is_respected() -> None:
    # 512x512(기준 해상도, scale=1) 에서 돈다 — 다른 해상도면 min_area_px2 가
    # 내부적으로 스케일돼(test_min_area_scales_with_resolution 참고) 여기서
    # 쓰는 리터럴 픽셀수 비교(9 vs +1)가 그대로 성립하지 않는다.
    prob = np.zeros((512, 512), dtype=np.float32)
    prob[10:13, 10:13] = 1.0  # 9px — 기본 MIN_CONTOUR_AREA_PX2(9) 통과, 더 큰 값엔 걸림
    assert (
        defect_candidates_from_probability_map(
            prob, source_media_id="m", model_id="x", source_digests={}
        )
        != []
    )
    assert (
        defect_candidates_from_probability_map(
            prob,
            source_media_id="m",
            model_id="x",
            source_digests={},
            min_area_px2=MIN_CONTOUR_AREA_PX2 + 1,
        )
        == []
    )


def test_geometry_polygon_matches_source_location() -> None:
    """[defect-detection-postprocess-no-spatial-check] 기존 테스트는 개수·면적·
    confidence 만 확인하고 검출된 polygon 이 실제 결함이 있던 자리를 가리키는지는
    보지 않는다 — polygon 이 통째로 이동하거나 x/y 가 뒤바뀌어도(transpose 버그)
    area 는 그대로라 못 잡는다. 가로≠세로인 비대칭 사각형을 알려진 오프셋에
    둬서 bbox 로 위치 대응을 직접 검증한다."""
    prob = np.zeros((256, 256), dtype=np.float32)
    prob[30:50, 100:108] = 1.0  # 세로(y) 30..49, 가로(x) 100..107 — 비대칭 20x8
    candidates = defect_candidates_from_probability_map(
        prob, source_media_id="m", model_id="model-x", source_digests={}
    )
    assert len(candidates) == 1
    polygon = candidates[0].geometry.payload
    assert polygon is not None
    xs = [pt[0] for pt in polygon]
    ys = [pt[1] for pt in polygon]
    assert min(xs) == 100.0 and max(xs) == 107.0
    assert min(ys) == 30.0 and max(ys) == 49.0


def test_confidence_and_area_exclude_interior_holes() -> None:
    """[defect-detection-confidence-includes-holes] cv2.findContours 는
    RETR_EXTERNAL(외곽 윤곽만) 이라 내부 구멍을 모른다 — drawContours(FILLED)로
    만든 mask 는 임계값 미만인 내부 구멍 픽셀까지 area/confidence 계산에
    포함시켜, 실제보다 낮은 confidence·부풀려진 area 를 낸다. 20x20 채움
    사각형 안에 6x6 구멍(threshold 미만)을 뚫어 mask 가 실제 foreground
    (cv2.countNonZero 의 이진 마스크)와 교집합돼야 함을 확인한다."""
    prob = np.zeros((256, 256), dtype=np.float32)
    prob[40:60, 40:60] = 1.0  # 20x20=400
    prob[47:53, 47:53] = 0.0  # 내부 6x6=36 구멍 — threshold 미만
    candidates = defect_candidates_from_probability_map(
        prob, source_media_id="ring", model_id="model-x", source_digests={}
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.measurements is not None
    assert candidate.measurements.area_px2 == 400.0 - 36.0
    assert candidate.confidence == 1.0


def test_invalid_probability_shape_rejected() -> None:
    for bad in (
        np.zeros((256, 256, 1), dtype=np.float32),  # 3D
        np.zeros((256, 256), dtype=np.uint8),  # 비 float
    ):
        try:
            defect_candidates_from_probability_map(
                bad, source_media_id="m", model_id="x", source_digests={}
            )
        except ValueError:
            continue
        raise AssertionError("2D float 가 아닌 입력은 ValueError 여야 한다")
