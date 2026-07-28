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
from typing import TYPE_CHECKING

from ksi_domain.ontology import ONTOLOGY_VERSION, classification_lineage_error

if TYPE_CHECKING:
    # FrameDetectionResult 는 탈락·클리핑 타입과 함께 detection_adapter 소유다 —
    # 런타임 순환 import 없이 타입 계약만 참조한다.
    from ksi_domain.detection_adapter import FrameDetectionResult


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
    """단일 프레임의 탐지 후보 1건 — 아직 세계좌표도 이벤트도 아니다.

    ``detection_class`` 는 **Canonical Entity Class** 다(:mod:`ksi_domain.ontology`).
    모델 원시 라벨은 별도 계보 필드에 보존한다 — 원시 라벨과 도메인 클래스를 같은
    문자열로 취급하면 모델 교체 시 의미가 흔들린다(INV-031 분류 계보).

    Attributes:
        detection_class: Canonical Entity Class ("Person" 등).
        confidence: 분류 신뢰도 [0,1].
        bbox: 픽셀 bbox.
        source_class_id: 모델 원시 클래스 index (모를 수 있음).
        source_class_name: 모델 원시 클래스명 ("person" 등, 모를 수 있음).
        ontology_version: 원시→canonical 번역에 쓰인 ontology 버전. 결정적 stub
            등 모델을 거치지 않은 생성자는 기본값(현행 버전)을 쓴다.
    """

    detection_class: str
    confidence: float
    bbox: BoundingBox
    source_class_id: int | None = None
    source_class_name: str | None = None
    ontology_version: str = ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        if not self.detection_class.strip():
            raise ValueError("detection_class 는 공백일 수 없다")
        if not (math.isfinite(self.confidence) and 0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence 는 [0,1] 범위의 finite 값이어야 한다 ({self.confidence!r})"
            )
        if not self.ontology_version.strip():
            raise ValueError("ontology_version 은 공백일 수 없다")
        # 계보 정합(독립 재검토 Blocker 1·3·4) — 미등록 버전·미등록 canonical·
        # 원시 라벨과 canonical 의 자기모순(Person 인데 source 가 truck)을 생성
        # 시점에 거부한다. 판정 규칙은 ontology 모듈과 공용(계층 간 동일 규칙).
        lineage_error = classification_lineage_error(
            canonical=self.detection_class,
            ontology_version=self.ontology_version,
            source_class_name=self.source_class_name,
            source_class_id=self.source_class_id,
        )
        if lineage_error is not None:
            raise ValueError(f"분류 계보 위반: {lineage_error}")


class Detector(ABC):
    """프레임 → typed 프레임 결과. 구현 교체 지점(모델 license 게이트는 구현체의 책임).

    계약은 :class:`~ksi_domain.detection_adapter.FrameDetectionResult` 하나다 —
    탐지 목록만 반환하고 탈락·클리핑을 mutable 속성으로 흘리던 이전 계약
    (``detect() -> list[Detection]`` + ``last_dropped``/``last_clipped``)은
    stale/교차 오염 경로라 제거됐다(slice-inference-exception-channel 폐쇄).

    상태 구분 의무:

    - 없는 frame_id 는 빈 탐지가 아니라 ``FRAME_NOT_FOUND`` 다.
    - 프레임 1장의 예상 가능한 추론 실패는 ``INFERENCE_FAILED`` 로 반환하고
      예외를 던지지 않는다(호출자는 다음 프레임을 계속 처리한다).
    - 호출 인자 계약 위반(비양수 크기)·프로그래머 오류는 typed 로 삼키지 않고
      예외로 남긴다.
    """

    @abstractmethod
    def detect_frame(self, frame_id: int, width: int, height: int) -> FrameDetectionResult:
        """프레임 1장을 처리해 per-call immutable typed 결과를 반환한다.

        Args:
            frame_id: 프레임 식별자(재현성을 위해 결정적 구현은 이 값을 시드로 쓴다).
            width: 프레임 너비(px, 양수).
            height: 프레임 높이(px, 양수).
        """
