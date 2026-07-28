"""Replay 테스트 픽스처 — 제품 orchestration 은 :mod:`ksi_perception.pipeline` 소유.

## 승격 이후의 역할 (PRODUCTION EDGE RUNTIME PROMOTION, 2026-07-28)

독립 검토로 다듬어진 vertical slice orchestration(run_vertical_slice·
MinimalTracker·SliceFrame/Result/Stage·event 정책 게이트)은
``packages/perception/src/ksi_perception/pipeline.py`` 로 **승격**됐다 — 검증된
배선이 테스트 하네스에만 있으면 PSDK Live View 를 붙일 자리가 테스트 모듈이
되기 때문이다.

이 파일에는 두 가지만 남는다:

1. **하위 호환 re-export** — 기존 replay 테스트의 ``from vertical_slice import
   run_vertical_slice`` 가 production 모듈의 **같은 객체**를 받는다. 별도
   orchestration 복사본은 두지 않는다(복사본 존재 = 실패 —
   test_vertical_slice 의 identity 테스트가 고정).
2. **테스트 전용 픽스처** — 결정적 stub Detector·합성 텔레메트리·탐지 생성기.
   합성 입력 생성은 제품 코드가 아니다(production 은 실 텔레메트리·실 프레임을
   받는다).
"""

from __future__ import annotations

from ksi_domain.detection import BoundingBox, Detection, Detector
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet

# 제품 orchestration re-export — 복사본이 아니라 동일 객체다.
from ksi_perception.pipeline import (  # noqa: F401
    DEFAULT_EVENT_POLICY,
    EVENT_TYPE_COMPATIBLE_CLASSES,
    DroppedDetection,
    EventBuildResult,
    EventBuildStatus,
    MinimalTracker,
    SliceFrame,
    SliceResult,
    SliceStage,
    run_vertical_slice,
)


class ScriptedDetector(Detector):
    """결정적 stub Detector — 프레임별 bbox를 스크립트로 지정한다.

    모델을 도입하지 않는 이유는 ``ksi_domain.detection`` 모듈 docstring 참고
    (배선과 모델 정확도를 분리해 디버깅). 실제 Detector로 교체할 때 이 클래스만
    바뀌고 파이프라인은 그대로다.
    """

    def __init__(self, script: dict[int, list[Detection]]) -> None:
        self._script = script

    def detect(self, frame_id: int, width: int, height: int) -> list[Detection]:
        if width <= 0 or height <= 0:
            raise ValueError(f"프레임 크기는 양수여야 한다 ({width}x{height})")
        return list(self._script.get(frame_id, []))


def synthetic_telemetry(
    timestamps: list[float],
    *,
    lat: float = 37.5,
    lon: float = 127.0,
    altitude_rel_m: float = 60.0,
    heading_deg: float = 0.0,
    gimbal_pitch_deg: float = -60.0,
) -> list[TelemetrySample]:
    """합성 텔레메트리 — PSDK 실입력으로 교체될 자리.

    ``gimbal_pitch_deg`` 기본값을 -60°로 둔 이유: 정수직(-90°)이면 모든 픽셀이 거의
    같은 지점으로 투영되어 bbox 차이가 좌표에 드러나지 않아 배선 검증이 약해진다.
    """
    samples: list[TelemetrySample] = []
    for ts in timestamps:
        samples.append(
            TelemetrySample(
                ts=TimestampSet(source_ts_utc=ts, receive_ts_utc=ts, capture_ts_utc=ts),
                drone_lat=lat,
                drone_lon=lon,
                altitude_rel_m=altitude_rel_m,
                heading_deg=heading_deg,
                gimbal_pitch_deg=gimbal_pitch_deg,
                camera_fov_deg=84.0,
                zoom_factor=1.0,
                rtk_fixed=True,
                source_quality=SourceQuality.FULL,
            )
        )
    return samples


def person_detection(
    *, x_min: float, y_min: float, x_max: float, y_max: float, confidence: float = 0.9
) -> Detection:
    """테스트 편의 — 사람 탐지 1건 (canonical class + 분류 계보 포함).

    초판은 ``detection_class="person"`` (원시 라벨)이었다 — canonical("Person")과
    원시 라벨을 같은 문자열로 취급하던 F13 의 실례라 수정됐다.
    """
    return Detection(
        detection_class="Person",
        confidence=confidence,
        bbox=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
        source_class_id=0,
        source_class_name="person",
    )


def truck_detection(
    *, x_min: float, y_min: float, x_max: float, y_max: float, confidence: float = 0.9
) -> Detection:
    """테스트 편의 — 트럭 탐지 1건. F13 반증(비Person 이 Person 이 되지 않는다)용."""
    return Detection(
        detection_class="Vehicle_Truck",
        confidence=confidence,
        bbox=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
        source_class_id=7,
        source_class_name="truck",
    )
