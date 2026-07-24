"""센서 시간·클록 보정 모델 (P0-2).

PPS(Pulse-Per-Second) 하드웨어 동기가 이미 센서 간 클록을 정렬했다는 전제 위에서, 그래도
남는 두 종류의 잔차를 모델링한다.

- ``CalibrationOffset``: 센서 클록과 기준(로컬) 클록 사이의 **상수 오프셋**. 지상
  캘리브레이션 세션(예: 알려진 이벤트를 여러 센서로 동시 관측해 시간차 측정)에서 값을
  얻는다.
- ``SensorLatencyProfile``: ``capture_ts`` 를 못 주는 소스에서, ``receive_ts`` 로부터
  실제 캡처 시각을 역추정하기 위한 파이프라인 지연의 통계적 추정.

두 모델 모두 **값 자체는 담지 않는다** — 하드웨어 세션에서 실측한 값을 어떻게 적용할지
로직만 제공한다. 여기 하드코딩된 기본값은 없다(대표자 반영사항 7).

이 모듈은 항공기급 Clock Synchronizer(여러 독립 클록의 상대 드리프트를 실시간 추정·정렬하는
알고리즘)를 재구현하지 않는다 — DJI PPS 동기가 그 역할을 하드웨어에서 이미 수행했다고
전제한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationOffset:
    """센서 클록 → 기준(로컬) 클록으로 이동시키는 상수 오프셋 ± 불확실성.

    Attributes:
        sensor_id: 오프셋이 적용되는 센서/장비 식별자.
        time_offset_s: 기준 클록 = 센서 클록 + time_offset_s (초). 지상 캘리브레이션에서
            측정. 양수면 센서 클록이 기준보다 뒤처져 있다는 뜻.
        uncertainty_s: 위 오프셋 측정의 불확실성(초, >= 0). 측정 방법의 해상도·반복성에서
            나온다 — 추정치가 아니라 반드시 실측 근거가 있어야 한다.
        note: 측정 방법/세션에 대한 자유 서술(선택).
    """

    sensor_id: str
    time_offset_s: float
    uncertainty_s: float
    note: str = ""

    def __post_init__(self) -> None:
        if self.uncertainty_s < 0:
            raise ValueError(f"uncertainty_s must be >= 0, got {self.uncertainty_s}")

    def apply(self, ts: float) -> float:
        """적용 지점: 센서 클록 타임스탬프를 기준(로컬) 클록으로 이동."""
        return ts + self.time_offset_s

    @property
    def bounds(self) -> tuple[float, float]:
        """[time_offset_s - uncertainty_s, time_offset_s + uncertainty_s]."""
        return (self.time_offset_s - self.uncertainty_s, self.time_offset_s + self.uncertainty_s)


@dataclass(frozen=True)
class SensorLatencyProfile:
    """센서별 파이프라인 지연(capture → receive) 추정 ± 불확실성.

    ``capture_ts`` 를 제공하지 않는 소스(예: 캡처 시각을 찍지 않는 저사양 텔레메트리 링크)에서,
    ``receive_ts`` 로부터 실제 캡처 시각을 역추정하는 유일한 근거가 된다. 하드웨어 세션에서
    반복 측정한 평균/중앙값 지연과 그 산포를 담는다.

    Attributes:
        sensor_id: 지연 프로파일이 적용되는 센서/장비 식별자.
        latency_s: 캡처~수신 사이 고정 지연 추정치(초, >= 0).
        uncertainty_s: 위 추정의 불확실성(초, >= 0).
        sample_count: 추정에 쓰인 실측 샘플 수(0이면 미측정 — 호출자가 신뢰도 판단에 참고).
    """

    sensor_id: str
    latency_s: float
    uncertainty_s: float
    sample_count: int = 0

    def __post_init__(self) -> None:
        if self.latency_s < 0:
            raise ValueError(f"latency_s must be >= 0, got {self.latency_s}")
        if self.uncertainty_s < 0:
            raise ValueError(f"uncertainty_s must be >= 0, got {self.uncertainty_s}")

    def estimate_capture_ts(self, receive_ts: float) -> float:
        """적용 지점: 수신 시각에서 고정 지연만큼 거슬러 캡처 시각을 추정."""
        return receive_ts - self.latency_s

    @property
    def bounds(self) -> tuple[float, float]:
        """[latency_s - uncertainty_s, latency_s + uncertainty_s]."""
        return (self.latency_s - self.uncertainty_s, self.latency_s + self.uncertainty_s)
