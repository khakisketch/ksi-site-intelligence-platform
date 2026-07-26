"""재생 결정성 (P0-6 수용기준, 대표자 반영사항 10).

Event ID가 아니라 event_fingerprint·observation_hash·final_position·transitions로
동일성을 검증한다. 각 테스트는 같은 fixture를 서로 다른 실행/입력순서로 재생해 네
값이 전부 동일함을 확인한다.
"""

from __future__ import annotations

from dataclasses import replace

from fixtures import confirmed_intrusion_fixture
from harness import run_replay


def test_two_fresh_runs_produce_identical_results() -> None:
    """가장 기본적인 재현성 — 같은 fixture를 두 번 독립 실행."""
    result_a = run_replay(confirmed_intrusion_fixture())
    result_b = run_replay(confirmed_intrusion_fixture())

    assert result_a.event_fingerprint == result_b.event_fingerprint
    assert result_a.observation_hash == result_b.observation_hash
    assert result_a.final_position == result_b.final_position
    assert result_a.transitions == result_b.transitions
    assert result_a.status == result_b.status


def test_shuffled_input_order_produces_identical_results() -> None:
    """텔레메트리·검출 프레임 도착 순서가 뒤섞여도 결과는 동일해야 한다.

    TelemetryInterpolator는 bisect 삽입으로 이미 순서 무관하고, run_replay도
    검출 프레임을 query_ts로 재정렬한다 — 이 테스트는 그 조합이 실제로 순서
    독립적임을 실행으로 확인한다(정적 추론이 아니라).
    """
    baseline = confirmed_intrusion_fixture()
    shuffled = replace(
        baseline,
        telemetry_samples=tuple(reversed(baseline.telemetry_samples)),
        detections=tuple(reversed(baseline.detections)),
    )

    result_baseline = run_replay(baseline)
    result_shuffled = run_replay(shuffled)

    assert result_baseline.event_fingerprint == result_shuffled.event_fingerprint
    assert result_baseline.observation_hash == result_shuffled.observation_hash
    assert result_baseline.final_position == result_shuffled.final_position
    assert result_baseline.transitions == result_shuffled.transitions


def test_final_position_bit_identical_across_runs() -> None:
    """final_position은 부동소수 비트까지 동일해야 한다(순수 함수 합성이므로)."""
    result_a = run_replay(confirmed_intrusion_fixture())
    result_b = run_replay(confirmed_intrusion_fixture())

    assert result_a.final_position is not None
    assert result_a.final_position == result_b.final_position
    lat_a, lon_a = result_a.final_position
    lat_b, lon_b = result_b.final_position
    assert lat_a == lat_b  # noqa: PLR0124 — 의도적으로 float == float(비트 동일성 확인)
    assert lon_a == lon_b  # noqa: PLR0124
