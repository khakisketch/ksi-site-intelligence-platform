"""Replay Harness 골격 (P0-6, PRD §27.1 Replay-first).

기록된(합성) 텔레메트리+검출 프레임을 재생해 P0-2(시간동기) → P0-4(투영) →
이벤트 상태전이(P0-1 ``ksi_domain.enums``)를 실제로 통과시킨다. 관측·재생 전용이며
비행제어 코드는 없다(00_READ_FIRST 구현 금지 항목).

## 결정성 계약 (대표자 반영사항 10)

재현 동일성은 **Event ID가 아니라** 다음 네 가지로 검증한다 — Event ID는 흔히 UUID나
단조증가 카운터로 실행마다 달라지는 게 정상이라, 그것이 같아야 한다고 요구하면 시험
자체가 구현을 왜곡시킨다:

1. ``event_fingerprint``: (event_type, anchor 위치, 최초 관측 시각)의 결정적 해시.
2. ``observation_hash``: 관측 시퀀스(시각순 정렬) 전체의 결정적 해시.
3. ``anchor_position``: 최초 관측 위경도 좌표(``EventCandidateBuilder.anchor`` —
   부동소수 정확히 동일, 순수 함수 합성이라 재실행해도 같은 비트 패턴이 나와야
   한다). "최종"이 아니라 **최초** 관측 위치다 — 재현성이 목적이라 평균 대신
   고정점을 쓴다(``anchor`` 프로퍼티 docstring). 이전 이름 ``final_position``
   은 뜻을 반대로 암시해 stale 모듈 재감사(#78, 2026-08-06)에서 정정됐다.
4. ``transitions``: 밟은 상태전이 순서(튜플) — INV-022(단일 프레임 즉시확정 금지)가
   실제로 지켜졌는지도 이 시퀀스 길이로 드러난다.

## EventCandidateBuilder의 성격

Scout ``events/engine.py`` (``EventEngine``, ``confirm_after_frames``)의 **구조만
참고**했다 — REFERENCE_ONLY: Scout의 실제 구현은 track dedup·구역별 키·후보 evict 등
site-safety 세부가 Phase 0 관측 하네스 범위를 크게 넘어서 코드를 그대로 옮기지
않았다. 여기 구현은 "여러 관측이 쌓여야 확정된다"는 최소 골격만 재현한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ksi_domain.enums import EventStatus, Severity, assert_event_transition
from ksi_geo_core.frames import great_circle_distance_m
from ksi_geo_core.projection import project_foot_point
from ksi_geo_core.sync import TelemetryInterpolator, TelemetrySample


@dataclass(frozen=True, slots=True)
class DetectionFrame:
    """재생용 합성 검출 프레임 — 실제 비디오 프레임 대신 픽셀 좌표만 담는다."""

    frame_id: int
    query_ts: float
    u_px: float
    v_px: float
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Observation:
    """투영에 성공한 검출 1건 — 이벤트 상태머신의 입력 단위."""

    frame_id: int
    timestamp: float
    lat: float
    lon: float
    confidence: float


@dataclass(frozen=True, slots=True)
class DroppedFrame:
    """관측으로 승격되지 못한 프레임 + 사유(조용히 버리지 않고 항상 기록, "no silent caps")."""

    frame_id: int
    reason: str


class EventCandidateBuilder:
    """관측이 쌓일수록 :class:`~ksi_domain.enums.EventStatus` 를 전진시킨다.

    모든 전이는 :func:`ksi_domain.enums.assert_event_transition` 을 통과해야만
    기록된다 — 전이표 밖의 상태 변화는 이 클래스가 아니라 그 함수가 막는다.
    """

    def __init__(
        self,
        event_type: str,
        severity: Severity,
        *,
        confirm_after_observations: int = 5,
        position_tolerance_m: float = 5.0,
    ) -> None:
        if confirm_after_observations < 5:
            raise ValueError(
                "confirm_after_observations는 5 이상이어야 한다 "
                "(반증 리뷰 2026-07-26: 한 관측당 한 단계만 전이하는 elif 체인이라 "
                "OBSERVATION→CANDIDATE→EVIDENCE_COLLECTION→FINDING 4단계를 거친 뒤 "
                "5번째 관측에서만 CONFIRMED_EVENT에 도달한다 — 4를 허용하면 값이 "
                "실제 동작과 달리 4/5 모두 5번째 관측에서 확정되는 계약 불일치가 있었다)"
            )
        if position_tolerance_m < 0:
            raise ValueError(
                f"position_tolerance_m은 0 이상이어야 한다 (got {position_tolerance_m!r})"
            )
        self.event_type = event_type
        self.severity = severity
        self._confirm_after = confirm_after_observations
        self._tolerance_m = position_tolerance_m
        self._observations: list[Observation] = []
        self._status: EventStatus | None = None
        self._transitions: list[tuple[str, str]] = []
        self._anchor: tuple[float, float] | None = None

    @property
    def status(self) -> EventStatus | None:
        return self._status

    @property
    def transitions(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._transitions)

    @property
    def anchor(self) -> tuple[float, float] | None:
        """첫 관측 위치 — 이 이벤트의 기준 위치로 쓴다(재현성이 목적이라 평균 대신 고정점)."""
        return self._anchor

    @property
    def observations(self) -> tuple[Observation, ...]:
        return tuple(self._observations)

    def _transition(self, nxt: EventStatus) -> None:
        assert_event_transition(self._status, nxt)
        cur_repr = self._status.value if self._status is not None else "DETECTION"
        self._transitions.append((cur_repr, nxt.value))
        self._status = nxt

    def ingest(self, obs: Observation) -> None:
        """관측 1건을 순서대로 반영한다. 호출자가 시각순으로 넣어야 한다(재현성 전제)."""
        self._observations.append(obs)
        if self._anchor is None:
            self._anchor = (obs.lat, obs.lon)
            self._transition(EventStatus.OBSERVATION)
            return

        distance_m = great_circle_distance_m(*self._anchor, obs.lat, obs.lon)
        consistent = distance_m <= self._tolerance_m
        count = len(self._observations)

        if not consistent:
            if self._status is EventStatus.OBSERVATION:
                self._transition(EventStatus.DISMISSED)
            elif self._status not in (EventStatus.DISMISSED, EventStatus.CONFIRMED_EVENT):
                self._transition(EventStatus.UNRESOLVED)
            return

        if self._status is EventStatus.OBSERVATION and count >= 2:
            self._transition(EventStatus.CANDIDATE)
        elif self._status is EventStatus.CANDIDATE and count >= 3:
            self._transition(EventStatus.EVIDENCE_COLLECTION)
        elif self._status is EventStatus.EVIDENCE_COLLECTION and count >= 4:
            self._transition(EventStatus.FINDING)
        elif self._status is EventStatus.FINDING and count >= self._confirm_after:
            self._transition(EventStatus.CONFIRMED_EVENT)
        # 그 외(예: 이미 CONFIRMED_EVENT/종단 상태)는 재전이 시도 없음 — 종단 상태 유지.


def event_fingerprint(
    event_type: str, anchor: tuple[float, float], first_observed_ts: float
) -> str:
    """(event_type, anchor 위치, 최초 관측 시각)의 결정적 해시 — Event ID가 아니다."""
    canonical = (
        f"{event_type}|{round(anchor[0], 7)}|{round(anchor[1], 7)}|{first_observed_ts:.3f}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def observation_hash(observations: tuple[Observation, ...]) -> str:
    """관측 시퀀스 전체(시각순 정렬)의 결정적 해시 — 입력 도착 순서 무관."""
    ordered = sorted(observations, key=lambda o: (o.timestamp, o.frame_id))
    canonical = "|".join(
        f"{o.frame_id}:{o.timestamp:.3f}:{round(o.lat, 7)}:{round(o.lon, 7)}" for o in ordered
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: EventStatus | None
    transitions: tuple[tuple[str, str], ...]
    observations: tuple[Observation, ...]
    dropped: tuple[DroppedFrame, ...]
    event_fingerprint: str | None
    observation_hash: str | None
    anchor_position: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class ReplayFixture:
    """합성 재생 입력 — 실제 영상 없이 텔레메트리 샘플+검출 프레임 좌표만 담는다."""

    telemetry_samples: tuple[TelemetrySample, ...]
    detections: tuple[DetectionFrame, ...]
    event_type: str
    severity: Severity
    confirm_after_observations: int = 5
    position_tolerance_m: float = 5.0
    max_gap_s: float = field(default=0.5)


def run_replay(fixture: ReplayFixture) -> ReplayResult:
    """fixture를 재생해 ``ReplayResult`` 를 만든다. 매 호출이 새 상태에서 시작한다.

    입력 리스트의 순서에 의존하지 않는다 — 텔레메트리는 ``TelemetryInterpolator`` 가
    내부적으로 시각순 정렬하고, 검출 프레임도 이 함수가 ``query_ts`` 기준으로
    재정렬한다(도착 순서 뒤섞여도 동일 결과 — 결정성 테스트가 이를 확인한다).
    """
    interpolator = TelemetryInterpolator(max_gap_s=fixture.max_gap_s)
    for sample in fixture.telemetry_samples:
        interpolator.add(sample)

    ordered_detections = sorted(fixture.detections, key=lambda d: (d.query_ts, d.frame_id))
    observations: list[Observation] = []
    dropped: list[DroppedFrame] = []

    for det in ordered_detections:
        interp = interpolator.at(det.query_ts)
        if not interp.ok or interp.sample is None:
            dropped.append(DroppedFrame(det.frame_id, f"interpolation:{interp.status.value}"))
            continue

        proj = project_foot_point(det.u_px, det.v_px, det.width, det.height, interp.sample)
        if not proj.ok or proj.lat is None or proj.lon is None:
            dropped.append(DroppedFrame(det.frame_id, f"projection:{proj.status.value}"))
            continue

        observations.append(
            Observation(det.frame_id, det.query_ts, proj.lat, proj.lon, proj.confidence)
        )

    builder = EventCandidateBuilder(
        fixture.event_type,
        fixture.severity,
        confirm_after_observations=fixture.confirm_after_observations,
        position_tolerance_m=fixture.position_tolerance_m,
    )
    for obs in observations:
        builder.ingest(obs)

    observations_tuple = tuple(observations)
    fingerprint: str | None = None
    obs_hash: str | None = None
    if builder.anchor is not None and observations_tuple:
        fingerprint = event_fingerprint(
            fixture.event_type, builder.anchor, observations_tuple[0].timestamp
        )
        obs_hash = observation_hash(observations_tuple)

    return ReplayResult(
        status=builder.status,
        transitions=builder.transitions,
        observations=observations_tuple,
        dropped=tuple(dropped),
        event_fingerprint=fingerprint,
        observation_hash=obs_hash,
        anchor_position=builder.anchor,
    )
