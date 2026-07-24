"""센서 타임스탬프 모델 (P0-2).

영상 프레임과 텔레메트리는 서로 다른 채널로 도착하고, 각 채널 안에도 "언제 실제로
일어났나"에 대한 서로 다른 시각 정보가 존재한다. 이를 단일 float 하나로 뭉개면 그
차이(센서 캡처 지연, 전송·파싱 지연, 로컬 클록 재조정)가 사라져 시간동기 오차의 원인을
추적할 수 없다. ``TimestampSet`` 은 이 네 시각을 구분해 보존한다.

DJI PPS(Pulse-Per-Second) 하드웨어 동기가 이미 센서 간 클록을 정렬했다는 것이 이 모델의
전제다 — 여러 독립 클록의 상대 드리프트를 추정·정렬하는 항공기급 Clock Synchronizer를
여기서 재구현하지 않는다. 이 모델이 다루는 건 그 위에 남는 잔차(``calibration``
모듈)와, 어느 시각을 "정렬·보간의 기준"으로 쓸지 결정하는 좁은 로직뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ksi_geo_core.calibration import CalibrationOffset, SensorLatencyProfile


@dataclass(frozen=True)
class TimestampSet:
    """한 텔레메트리/프레임 샘플에 결부된 네 가지 시각(모두 UTC epoch 초).

    Attributes:
        source_ts: 장비가 스스로 보고하는 타임스탬프(예: DJI OSD 페이로드에 실린 값).
            장비 내부 클록 기준이라 로컬 기준 클록과 상수 오프셋이 있을 수 있다
            (``CalibrationOffset`` 이 이 오프셋을 보정하는 대상).
        receive_ts: 우리 프로세스가 그 메시지를 실제로 수신한 시각. 네트워크·파싱
            지연을 포함하므로 항상 capture_ts/source_ts 이후다.
        monotonic_ts: 로컬 단조시계(예: ``time.monotonic()``) 값. 시스템 시각의
            역행·NTP 재조정 영향을 받지 않아, 같은 프로세스 안에서의 **순서** 보장이나
            지연 측정(receive_ts - monotonic_ts 기준 상대 델타)에 쓴다. 클록 동기의
            절대 기준으로는 쓰지 않는다(프로세스 재시작마다 기준점이 바뀜).
        capture_ts: 센서가 실제로 값을 취득한 순간(예: GPS/IMU 칩이 샘플링한 시각).
            소스가 이를 제공하지 못하면 ``None`` — 이 경우 ``SensorLatencyProfile`` 로
            ``receive_ts`` 에서 역추정하거나, 그것도 없으면 ``source_ts`` 로 폴백한다
            (PPS 하드웨어 동기 전제이므로 폴백 오차는 상수 오프셋 범위 안이라고 본다).
    """

    source_ts: float
    receive_ts: float
    monotonic_ts: float
    capture_ts: float | None = None

    def resolved_capture_ts(self, latency_profile: SensorLatencyProfile | None = None) -> float:
        """캡처 시각을 최선으로 복원한다.

        우선순위: ``capture_ts`` 실측값 → ``latency_profile`` 로 ``receive_ts`` 에서
        역추정 → ``source_ts`` 폴백(PPS 하드웨어 동기 전제).
        """
        if self.capture_ts is not None:
            return self.capture_ts
        if latency_profile is not None:
            return latency_profile.estimate_capture_ts(self.receive_ts)
        return self.source_ts

    def sync_ts(
        self,
        *,
        latency_profile: SensorLatencyProfile | None = None,
        calibration: CalibrationOffset | None = None,
    ) -> float:
        """정렬·보간의 기준으로 쓸 단일 시각.

        ``CalibrationOffset`` 적용 지점: :meth:`resolved_capture_ts` 로 얻은 시각에
        상수 오프셋을 더해 기준(로컬) 클록으로 이동시킨다. ``TelemetryInterpolator`` 는
        ``add()``/``at()`` 양쪽에서 항상 이 메서드가 반환하는 값을 정렬·보간 키로 쓴다.
        """
        base = self.resolved_capture_ts(latency_profile)
        if calibration is not None:
            return calibration.apply(base)
        return base
