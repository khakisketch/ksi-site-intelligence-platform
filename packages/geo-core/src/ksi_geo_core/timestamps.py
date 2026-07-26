"""센서 타임스탬프 모델 (P0-2).

영상 프레임과 텔레메트리는 서로 다른 채널로 도착하고, 각 채널 안에도 "언제 실제로
일어났나"에 대한 서로 다른 시각 정보가 존재한다. 이를 단일 float 하나로 뭉개면 그
차이(센서 캡처 지연, 전송·파싱 지연, 로컬 클록 재조정)가 사라져 시간동기 오차의 원인을
추적할 수 없다. ``TimestampSet`` 은 이 시각들을 구분해 보존한다.

DJI PPS(Pulse-Per-Second) 하드웨어 동기가 이미 센서 간 클록을 정렬했다는 것이 이 모델의
전제다 — 여러 독립 클록의 상대 드리프트를 추정·정렬하는 항공기급 Clock Synchronizer를
여기서 재구현하지 않는다. 이 모델이 다루는 건 그 위에 남는 잔차(``calibration``
모듈)와, 어느 시각을 "정렬·보간의 기준"으로 쓸지 결정하는 좁은 로직뿐이다.

## 시간축 두 종류를 섞지 않는다 (반증 리뷰 2026-07-26 P0)

- **UTC epoch 도메인** (``*_ts_utc`` 접미사): ``source_ts_utc``·``receive_ts_utc``·
  ``capture_ts_utc``. 서로 다른 프로세스·기기 간에 비교 가능하고, ``CalibrationOffset``·
  ``SensorLatencyProfile``이 다루는 시각축이다. :meth:`TimestampSet.sync_ts_utc` 는
  **오직 이 세 필드만** 읽는다.
- **process-local monotonic 도메인** (``receive_monotonic_s``): ``time.monotonic()``류
  값 — 같은 프로세스 안에서만 의미가 있고(재시작마다 기준점이 바뀐다), UTC 필드와 절대
  같은 값일 수 없고 산술적으로 비교해서도 안 된다. 같은 프로세스 내 상대 지연 측정
  용도로만 optional하게 들고 다니며, 동기화·보간 계산에는 절대 관여하지 않는다.

이전 구현은 이름이 이 구분을 드러내지 않아(``monotonic_ts``가 UTC로 오해되기 쉬웠다)
보간 결과에 두 도메인을 뒤섞어 대입하는 결함(:class:`DerivedTimestamp` 참고)이 있었다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ksi_geo_core.calibration import CalibrationOffset, SensorLatencyProfile


def _require_finite(name: str, value: float | None) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{name}는 finite해야 한다 (got {value!r})")


@dataclass(frozen=True)
class TimestampSet:
    """실제로 수신된 한 텔레메트리/프레임 샘플에 결부된 시각들(모든 ``*_ts_utc``는 UTC epoch 초).

    Attributes:
        source_ts_utc: 장비가 스스로 보고하는 UTC 타임스탬프(예: DJI OSD 페이로드에
            실린 값). 장비 내부 클록 기준이라 로컬 기준 클록과 상수 오프셋이 있을 수
            있다(``CalibrationOffset``이 이 오프셋을 보정하는 대상).
        receive_ts_utc: 우리 프로세스가 그 메시지를 실제로 수신한 UTC 시각. 네트워크·
            파싱 지연을 포함하므로 항상 capture_ts_utc/source_ts_utc 이후다.
        receive_monotonic_s: 수신 시점의 로컬 단조시계(``time.monotonic()``) 값(선택).
            같은 프로세스 안에서의 **순서** 보장이나 지연 측정에만 쓴다 — UTC 필드와
            비교하거나 동기화 계산에 사용하지 않는다(위 모듈 docstring 참고).
        capture_ts_utc: 센서가 실제로 값을 취득한 순간의 UTC 시각(예: GPS/IMU 칩이
            샘플링한 시각). 소스가 이를 제공하지 못하면 ``None`` — 이 경우
            ``SensorLatencyProfile``로 ``receive_ts_utc``에서 역추정하거나, 그것도
            없으면 ``source_ts_utc``로 폴백한다(PPS 하드웨어 동기 전제이므로 폴백
            오차는 상수 오프셋 범위 안이라고 본다).
    """

    source_ts_utc: float
    receive_ts_utc: float
    receive_monotonic_s: float | None = None
    capture_ts_utc: float | None = None

    def __post_init__(self) -> None:
        _require_finite("source_ts_utc", self.source_ts_utc)
        _require_finite("receive_ts_utc", self.receive_ts_utc)
        _require_finite("receive_monotonic_s", self.receive_monotonic_s)
        _require_finite("capture_ts_utc", self.capture_ts_utc)

    def resolved_capture_ts_utc(
        self, latency_profile: SensorLatencyProfile | None = None
    ) -> float:
        """캡처 시각(UTC)을 최선으로 복원한다.

        우선순위: ``capture_ts_utc`` 실측값 → ``latency_profile``로 ``receive_ts_utc``
        에서 역추정 → ``source_ts_utc`` 폴백(PPS 하드웨어 동기 전제). ``receive_monotonic_s``
        는 이 계산에 절대 관여하지 않는다(도메인이 다르다).
        """
        if self.capture_ts_utc is not None:
            return self.capture_ts_utc
        if latency_profile is not None:
            return latency_profile.estimate_capture_ts(self.receive_ts_utc)
        return self.source_ts_utc

    def sync_ts_utc(
        self,
        *,
        latency_profile: SensorLatencyProfile | None = None,
        calibration: CalibrationOffset | None = None,
    ) -> float:
        """정렬·보간의 기준으로 쓸 단일 UTC 시각.

        ``CalibrationOffset`` 적용 지점: :meth:`resolved_capture_ts_utc`로 얻은 시각에
        상수 오프셋을 더해 기준(로컬) 클록으로 이동시킨다. ``TelemetryInterpolator``는
        ``add()``/``at()`` 양쪽에서 항상 이 메서드가 반환하는 값을 정렬·보간 키로 쓴다.
        """
        base = self.resolved_capture_ts_utc(latency_profile)
        if calibration is not None:
            return calibration.apply(base)
        return base


@dataclass(frozen=True, slots=True)
class DerivedTimestamp:
    """보간 등으로 파생된 샘플의 시각 — 실제 수신 이벤트가 없어 provenance가 없다.

    이전 구현은 보간 결과를 만들 때 ``query_ts`` 하나를 ``TimestampSet``의 네 필드
    (source/receive/monotonic/capture)에 그대로 복제했다 — 이는 존재하지 않는
    "수신 시각"·"단조시계 판독값"을 지어내는 것이었고, UTC 값이 monotonic 필드에
    들어가는 도메인 혼합이기도 했다(반증 리뷰 2026-07-26 P0). ``DerivedTimestamp``는
    파생 샘플임을 타입으로 명시해 이 fabrication을 구조적으로 막는다 — 이 클래스에는
    ``source_ts_utc``/``receive_ts_utc``/``receive_monotonic_s`` 필드 자체가 없다.
    """

    synchronized_ts_utc: float

    def __post_init__(self) -> None:
        _require_finite("synchronized_ts_utc", self.synchronized_ts_utc)

    def resolved_capture_ts_utc(
        self, latency_profile: SensorLatencyProfile | None = None
    ) -> float:
        del latency_profile  # 파생 시각은 이미 확정된 단일 순간 — latency 재추정 대상이 아니다
        return self.synchronized_ts_utc

    def sync_ts_utc(
        self,
        *,
        latency_profile: SensorLatencyProfile | None = None,
        calibration: CalibrationOffset | None = None,
    ) -> float:
        # 이미 동기화된 시각이다 — calibration/latency는 원본 수신 샘플에만 적용하는
        # 보정이라, 파생 샘플에 재적용하면 이중 보정이 된다.
        del latency_profile, calibration
        return self.synchronized_ts_utc


SyncedTimestamp = TimestampSet | DerivedTimestamp
"""동기화 키를 제공하는 두 시각 표현의 합 — 실제 수신 샘플(``TimestampSet``) 또는
파생 샘플(``DerivedTimestamp``)."""
