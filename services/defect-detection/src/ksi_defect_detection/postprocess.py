"""확률맵 → :class:`~ksi_event_contracts.defect_candidate.DefectCandidate` 목록.

``mixercseg_adapter.MixerCSegDetector.segment_image`` 가 낸 확률맵(H,W float32
0~1)을 임계값으로 이진화하고, 연결된 성분별로 윤곽을 뽑아 계약 객체로 만든다.

## 계측치는 근사값이다 — 정밀 균열 계측이 아니다

``lengthPx``/``meanWidthPx`` 는 스켈레톤 기반 정밀 계측이 아니라 윤곽 둘레·면적에서
유도한 근사치다(모듈 상수 주석 참고). "초기 리서치 MVP" 단계에서 결함 후보의
대략적 규모를 알려주는 신호로 충분하다는 판단이고, 실측 정밀도가 필요해지면
이 함수만 교체하면 된다 — 계약(DefectCandidate)과 분리돼 있어 하류 소비자는
영향받지 않는다.

## ``areaPx2`` 는 폴리곤 면적이 아니라 픽셀 카운트다

``cv2.contourArea``(신발끈 공식)는 가늘고 긴 형상에서 좌·우 윤곽 경로가 거의
겹쳐 실제 픽셀 수와 무관하게 0에 가깝게 퇴화한다 — 폭 1px 균열은 픽셀이
실재해도 면적이 거의 0으로 계산돼 노이즈 필터에 걸려 사라진다(reviewer 지적
P2, 2026-08-07 실측: 1px 대각선 100px 길이가 면적 0으로 드롭됨). 그래서
``area_px2`` 는 윤곽을 채운 마스크의 ``cv2.countNonZero``(실제 foreground
픽셀 수)로 계산한다 — 이미 confidence 계산에 쓰던 마스크를 재사용한다.

## ``min_area_px2`` 는 512x512 기준값이고, 입력 해상도에 맞춰 자동으로 스케일된다

``mixercseg_adapter.MixerCSegDetector.segment_image`` 가 확률맵을 **원본 이미지
해상도**로 복원해서 내놓는다(모델 좌표계가 아니라 — 이유는 그쪽 모듈 docstring
"reviewer 지적 F3"). 그런데 이 함수는 512x512 모델 좌표계를 기준으로 캘리브레이션한
``MIN_CONTOUR_AREA_PX2``를 쓴다 — 4000x3000 원본이면 모델 좌표 1px 가 원본에서
약 46px² 가 되므로, 절대 픽셀수로 문턱을 고정하면 큰 이미지에서는 노이즈 필터가
사실상 무력화되고 작은 이미지에서는 과공격적이 된다(reviewer 지적, 2026-08-07
실측: 4000x3000에서 7x7=49px² 파편이 9px² 문턱을 그냥 통과 — 모델 좌표론
1.07px² 짜리 잡음인데도). 그래서 ``min_area_px2`` 는 항상 "512x512 환산" 값으로
받고, 실제 필터링은 입력 해상도 비율로 스케일한 값을 쓴다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ksi_event_contracts.defect_candidate import (
    DefectCandidate,
    DefectGeometry,
    DefectMeasurements,
    DefectModelRef,
    ImageSize,
)

if TYPE_CHECKING:
    import numpy as np

# 이진화 임계값 — sigmoid 확률맵을 crack/not-crack 으로 나누는 문턱.
# BCEWithLogitsLoss+Dice 로 학습된 모델의 표준 관례(0.5)를 따른다.
DEFAULT_THRESHOLD = 0.5

# 이 픽셀 면적(512x512 환산) 미만인 연결 성분은 노이즈로 버린다 — 3x3px 미만
# 파편은 실제 균열이 아니라 이진화 임계값 근처의 단일 픽셀 요동일 가능성이 높다.
# MixerCSeg 의 registry 등재 입력 해상도(512x512, MODEL_REGISTRY.yaml)와 같은 값 —
# 이 함수가 실제로 받는 해상도(원본 이미지)와는 다를 수 있어 아래에서 스케일한다.
MIN_CONTOUR_AREA_PX2 = 9.0
_REFERENCE_RESOLUTION_PX2 = 512 * 512


def defect_candidates_from_probability_map(
    probability: np.ndarray,
    *,
    source_media_id: str,
    model_id: str,
    source_digests: dict[str, str],
    threshold: float = DEFAULT_THRESHOLD,
    min_area_px2: float = MIN_CONTOUR_AREA_PX2,
    id_prefix: str = "defect",
) -> list[DefectCandidate]:
    """확률맵 1장 → :class:`DefectCandidate` 목록(연결 성분별 1건).

    빈 목록은 정상 반환값이다(균열 후보 없음) — 예외가 아니다.
    """
    import cv2
    import numpy as np

    if probability.ndim != 2 or probability.dtype.kind != "f":
        raise ValueError(
            f"probability 는 2D float 배열이어야 한다 (shape={probability.shape}, "
            f"dtype={probability.dtype})"
        )
    height_px, width_px = probability.shape
    # 위 모듈 docstring "min_area_px2 는 512x512 기준값" 절 — 실제 필터링은 이
    # 함수가 받은 해상도로 환산한 값을 쓴다. 512x512 로 들어오면(예: 테스트
    # 픽스처, 또는 원본이 마침 512x512) scale=1 이라 이전 동작과 동일하다.
    scale = (height_px * width_px) / _REFERENCE_RESOLUTION_PX2
    effective_min_area_px2 = min_area_px2 * scale

    binary = (probability >= threshold).astype(np.uint8)
    # 기본은 CHAIN_APPROX_SIMPLE(압축) — payload 를 원본 마스크 래스터 크기로
    # 부풀리지 않는다(defect_candidate.py 가 polygon 을 택한 이유 자체가
    # "래스터 전체를 안 싣는다"). 다만 완전한 직선 형상(가는 균열)은 SIMPLE 이
    # 정점 2개로 압축해 아래 "다각형 최소 3점" 요건에 걸려 통째로 드롭된다
    # (reviewer 지적 P2) — 그 경우에만 그 성분을 NONE(비압축)으로 다시 뽑는다.
    # RETR_EXTERNAL 은 같은 입력에서 압축 모드와 무관하게 같은 순서로 성분을
    # 순회하므로(트레이싱 시작점 스캔 순서는 압축과 무관) 인덱스로 대응시킬 수
    # 있다 — 매 성분마다 NONE 을 돌리는 비용을 피하려고 지연 계산한다.
    contours, _hierarchy = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours_uncompressed = None

    candidates: list[DefectCandidate] = []
    for i, contour in enumerate(contours):
        if len(contour) < 3:
            if contours_uncompressed is None:
                uncompressed, _ = cv2.findContours(
                    binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
                )
                contours_uncompressed = list(uncompressed)
            if i >= len(contours_uncompressed) or len(contours_uncompressed[i]) < 3:
                continue
            contour = contours_uncompressed[i]
        mask = np.zeros_like(binary)
        cv2.drawContours(mask, [contour], contourIdx=-1, color=1, thickness=cv2.FILLED)
        # RETR_EXTERNAL 은 외곽 윤곽만 보므로 내부 구멍(임계값 미만 영역)을 모른다
        # — FILLED 로 채우면 그 구멍까지 area/confidence 계산에 섞여 들어간다
        # (실제보다 낮은 confidence·부풀려진 area). 실제 foreground(binary)와
        # 교집합해 구멍을 제외한다.
        mask &= binary
        area_px2 = float(cv2.countNonZero(mask))
        if area_px2 < effective_min_area_px2:
            continue
        perimeter_px = float(cv2.arcLength(contour, closed=True))
        # 가늘고 긴 형상(균열) 근사: 둘레 ≈ 2*(길이+폭), 폭 << 길이일 때
        # 둘레/2 는 길이의 합리적 근사, 폭은 면적/길이로 역산한 **평균**값이다
        # (최댓값이 아니다 — DefectMeasurements.mean_width_px 문서 참고).
        length_px = perimeter_px / 2.0
        mean_width_px = area_px2 / length_px if length_px > 0 else 0.0

        region_probs = probability[mask.astype(bool)]
        confidence = float(region_probs.mean()) if region_probs.size > 0 else 0.0

        polygon = [(float(pt[0][0]), float(pt[0][1])) for pt in contour]

        candidates.append(
            DefectCandidate(
                defect_candidate_id=f"{id_prefix}-{source_media_id}-{i}",
                defect_type="CRACK",
                source_media_id=source_media_id,
                image_size=ImageSize(width_px=int(width_px), height_px=int(height_px)),
                geometry=DefectGeometry(format="IMAGE_POLYGON_2D", payload=polygon),
                model=DefectModelRef(model_id=model_id, source_digests=source_digests),
                confidence=max(0.0, min(1.0, confidence)),
                measurements=DefectMeasurements(
                    area_px2=area_px2,
                    length_px=length_px,
                    mean_width_px=mean_width_px,
                ),
            )
        )
    return candidates


__all__ = [
    "DEFAULT_THRESHOLD",
    "MIN_CONTOUR_AREA_PX2",
    "defect_candidates_from_probability_map",
]
