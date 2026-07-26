"""EventCandidateBuilder 계약 검증 (반증 리뷰 2026-07-26 P0, P0-6).

이전 구현은 ``confirm_after_observations=4``를 생성자에서 허용했지만, 한 관측당 한
단계만 전이하는 elif 체인의 실제 동작상 4와 5가 똑같이 "5번째 관측에서 확정"으로
귀결돼 파라미터가 계약과 달랐다. 최소값을 5로 고정한 뒤 그 경계를 직접 확인한다.
"""

from __future__ import annotations

import pytest
from harness import EventCandidateBuilder, Observation
from ksi_domain.enums import EventStatus, Severity


def _obs(frame_id: int, ts: float, lat: float = 37.5, lon: float = 127.0) -> Observation:
    return Observation(frame_id=frame_id, timestamp=ts, lat=lat, lon=lon, confidence=0.8)


def test_confirm_after_observations_below_five_rejected() -> None:
    with pytest.raises(ValueError, match="confirm_after_observations"):
        EventCandidateBuilder("TEST_EVENT", Severity.HIGH, confirm_after_observations=4)
    with pytest.raises(ValueError, match="confirm_after_observations"):
        EventCandidateBuilder("TEST_EVENT", Severity.HIGH, confirm_after_observations=1)


def test_confirmed_exactly_at_fifth_observation_not_before() -> None:
    """임계값 5에서 정확히 다섯 번째 관측에 확인 + 네 번째까지는 Confirmed 금지."""
    builder = EventCandidateBuilder("TEST_EVENT", Severity.HIGH, confirm_after_observations=5)

    for i in range(4):
        builder.ingest(_obs(i, float(i)))
        assert builder.status is not EventStatus.CONFIRMED_EVENT, (
            f"관측 {i + 1}건째에 이미 CONFIRMED_EVENT — INV-022 위반"
        )

    builder.ingest(_obs(4, 4.0))
    assert builder.status is EventStatus.CONFIRMED_EVENT


def test_confirm_after_six_requires_sixth_observation() -> None:
    """confirm_after_observations를 6으로 올리면 5번째까지는 FINDING에 머문다."""
    builder = EventCandidateBuilder("TEST_EVENT", Severity.HIGH, confirm_after_observations=6)

    for i in range(5):
        builder.ingest(_obs(i, float(i)))
    assert builder.status is EventStatus.FINDING

    builder.ingest(_obs(5, 5.0))
    assert builder.status is EventStatus.CONFIRMED_EVENT


def test_negative_position_tolerance_rejected() -> None:
    with pytest.raises(ValueError, match="position_tolerance_m"):
        EventCandidateBuilder("TEST_EVENT", Severity.HIGH, position_tolerance_m=-1.0)


def test_zero_position_tolerance_allowed() -> None:
    """0은 '완전 일치만 허용'이라는 유효한 정책값이라 거부 대상이 아니다."""
    builder = EventCandidateBuilder("TEST_EVENT", Severity.HIGH, position_tolerance_m=0.0)
    builder.ingest(_obs(0, 0.0))
    assert builder.status is EventStatus.OBSERVATION
