"""Detection 계약 + Detector 인터페이스 (Track B).

## Detector는 인터페이스로만 둔다 — 모델은 아직 도입하지 않는다

Scout 감사가 Ultralytics YOLO를 ``BLOCKED_LICENSE`` 로 판정했다(비공개 상용·Embedded
Edge 사용은 Enterprise 계약 또는 AGPL 공개전략 확정 전 Production 금지). 그래서 이
단계에서는 **모델을 도입하지 않고** 인터페이스와 결정적 stub만 만든다.

이 선택의 실익: vertical slice가 검증하는 것은 **파이프라인 배선**이지 모델 정확도가
아니다. 모델을 먼저 넣으면 "탐지가 안 되는 것"과 "배선이 잘못된 것"을 동시에 디버깅해야
한다. stub으로 배선을 확정한 뒤 Detector 구현만 교체하는 것이 순서다.

허용 모델 후보는 Scout 정책대로 permissive license(RF-DETR 계열)이며, 실제 채택 시
Model Registry에 license·dataset lineage·benchmark를 기록해야 한다(INV-043).

## Detection은 Event가 아니다 (INV-031)

Detector 출력은 화면 좌표 후보일 뿐이다. 세계좌표·불확실성을 얻어 Observation이 되고,
그 다음에야 이벤트 상태머신에 진입한다. 이 모듈의 타입에는 event 관련 필드가 없다 —
그 경계를 타입으로 표현한다.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """이미지 픽셀 좌표 bbox. 좌상단 원점, x 우측·y 하측 증가(OpenCV 관습)."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        values = (self.x_min, self.y_min, self.x_max, self.y_max)
        if not all(math.isfinite(v) for v in values):
            raise ValueError(f"bbox 좌표는 finite해야 한다 (got {values!r})")
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError(
                f"bbox 는 양의 면적을 가져야 한다 (got {values!r}) — "
                "퇴화 bbox는 foot point가 정의되지 않는다"
            )

    @property
    def foot_point(self) -> tuple[float, float]:
        """접지점(하단 중앙) — 지면 투영의 기준점.

        사람·차량의 세계좌표는 bbox 중심이 아니라 **지면에 닿는 점**으로 구한다.
        중심을 쓰면 대상 높이의 절반만큼 체계적으로 멀어진다.
        """
        return ((self.x_min + self.x_max) / 2.0, self.y_max)


@dataclass(frozen=True, slots=True)
class Detection:
    """단일 프레임의 탐지 후보 1건 — 아직 세계좌표도 이벤트도 아니다."""

    detection_class: str
    confidence: float
    bbox: BoundingBox

    def __post_init__(self) -> None:
        if not self.detection_class.strip():
            raise ValueError("detection_class 는 공백일 수 없다")
        if not (math.isfinite(self.confidence) and 0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence 는 [0,1] 범위의 finite 값이어야 한다 ({self.confidence!r})"
            )


class Detector(ABC):
    """프레임 → 탐지 후보 목록. 구현 교체 지점(모델 license 게이트는 구현체의 책임)."""

    @abstractmethod
    def detect(self, frame_id: int, width: int, height: int) -> list[Detection]:
        """프레임 1장에서 탐지 후보를 만든다.

        Args:
            frame_id: 프레임 식별자(재현성을 위해 결정적 구현은 이 값을 시드로 쓴다).
            width: 프레임 너비(px, 양수).
            height: 프레임 높이(px, 양수).
        """
