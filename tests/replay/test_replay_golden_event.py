"""재생 동작 검증 (P0-6) — green≠작동: "재생이 끝남"이 아니라 기대 상태·기대 drop을 확인.

각 fixture가 실제로 의도한 시나리오(정상 확정/단일프레임 미확정/gap drop/오탐 dismissal)를
만들어내는지 검증한다 — 미리 finalize된 픽스처를 읽는 게 아니라 매번 파이프라인을 처음부터
통과시킨다.
"""

from __future__ import annotations

from fixtures import (
    confirmed_intrusion_fixture,
    gap_exceeded_fixture,
    inconsistent_position_fixture,
    single_frame_fixture,
)
from harness import run_replay
from ksi_domain.enums import EventStatus


def test_confirmed_intrusion_reaches_confirmed_event_via_full_lifecycle() -> None:
    result = run_replay(confirmed_intrusion_fixture())

    assert result.status is EventStatus.CONFIRMED_EVENT
    assert len(result.observations) == 6
    assert result.dropped == ()
    # 6개 관측이 남긴 전이는 정확히 이 5단계 — 6번째(종단 상태에서 추가 관측)는
    # 재전이를 시도하지 않으므로 여기 나타나지 않는다.
    assert result.transitions == (
        ("DETECTION", "OBSERVATION"),
        ("OBSERVATION", "CANDIDATE"),
        ("CANDIDATE", "EVIDENCE_COLLECTION"),
        ("EVIDENCE_COLLECTION", "FINDING"),
        ("FINDING", "CONFIRMED_EVENT"),
    )
    assert result.event_fingerprint is not None
    assert result.observation_hash is not None


def test_single_frame_never_reaches_confirmed_event() -> None:
    """INV-022 — 단일 프레임으로 사건을 확정하지 않는다."""
    result = run_replay(single_frame_fixture())

    assert result.status is EventStatus.OBSERVATION
    assert result.status is not EventStatus.CONFIRMED_EVENT
    assert result.status is not EventStatus.FINDING
    assert len(result.observations) == 1
    assert result.transitions == (("DETECTION", "OBSERVATION"),)


def test_gap_exceeded_frame_is_dropped_not_fabricated() -> None:
    """INV-023 — 보간 gap 초과 시 외삽하지 않고 typed 실패로 drop한다(값을 지어내지 않음)."""
    result = run_replay(gap_exceeded_fixture())

    dropped_ids = {d.frame_id for d in result.dropped}
    assert 1 in dropped_ids  # query_ts=5.0 프레임이 drop
    dropped_reason = next(d.reason for d in result.dropped if d.frame_id == 1)
    assert dropped_reason == "interpolation:gap_exceeded"
    # drop된 프레임은 관측으로 승격되지 않았어야 한다.
    assert 1 not in {o.frame_id for o in result.observations}
    # 나머지 2개(양끝, gap 없음)는 정상 관측됐어야 한다.
    assert len(result.observations) == 2


def test_inconsistent_position_dismisses_the_candidate() -> None:
    """두 번째 관측이 anchor에서 멀면 OBSERVATION→DISMISSED로 귀결(오탐 패턴)."""
    result = run_replay(inconsistent_position_fixture())

    assert result.status is EventStatus.DISMISSED
    assert result.transitions == (
        ("DETECTION", "OBSERVATION"),
        ("OBSERVATION", "DISMISSED"),
    )
