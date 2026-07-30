"""SiteStatus 상태전이 검증 테스트 (MASTER_PRD §6.3/§6.1, ADR-KSI-008 §4).

PATROL_READY 도달은 반드시 MODEL_VALIDATION -> PROVISIONAL_AUTONOMY 를 경유해야
한다(§6.1 품질 검증 생략 금지) — UNMAPPED 등에서 PATROL_READY 로 직행하는 간선은
존재하지 않는다. SUSPENDED 는 저장소가 기억한 진입 직전 상태로만 resume 된다.
"""

from __future__ import annotations

import pytest
from ksi_domain.enums import (
    _ALLOWED_SITE_TRANSITIONS,  # noqa: PLC2701 -- 전이표 전수 검사를 위한 의도적 내부 접근
    IllegalSiteTransitionError,
    SiteStatus,
    assert_site_transition,
    can_site_transition,
)


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        (SiteStatus.UNMAPPED, SiteStatus.BASELINE_MAPPING),
        (SiteStatus.UNMAPPED, SiteStatus.SUSPENDED),
        (SiteStatus.BASELINE_MAPPING, SiteStatus.MODEL_PROCESSING),
        (SiteStatus.BASELINE_MAPPING, SiteStatus.SUSPENDED),
        (SiteStatus.MODEL_PROCESSING, SiteStatus.MODEL_VALIDATION),
        (SiteStatus.MODEL_PROCESSING, SiteStatus.SUSPENDED),
        (SiteStatus.MODEL_VALIDATION, SiteStatus.PROVISIONAL_AUTONOMY),
        (SiteStatus.MODEL_VALIDATION, SiteStatus.REMAP_REQUIRED),
        (SiteStatus.MODEL_VALIDATION, SiteStatus.SUSPENDED),
        (SiteStatus.PROVISIONAL_AUTONOMY, SiteStatus.PATROL_READY),
        (SiteStatus.PROVISIONAL_AUTONOMY, SiteStatus.REMAP_REQUIRED),
        (SiteStatus.PROVISIONAL_AUTONOMY, SiteStatus.SUSPENDED),
        (SiteStatus.PATROL_READY, SiteStatus.PATROL_ACTIVE),
        (SiteStatus.PATROL_READY, SiteStatus.MODEL_STALE),
        (SiteStatus.PATROL_READY, SiteStatus.SUSPENDED),
        (SiteStatus.PATROL_ACTIVE, SiteStatus.PATROL_READY),
        (SiteStatus.PATROL_ACTIVE, SiteStatus.MODEL_STALE),
        (SiteStatus.PATROL_ACTIVE, SiteStatus.SUSPENDED),
        (SiteStatus.MODEL_STALE, SiteStatus.MODEL_PROCESSING),
        (SiteStatus.MODEL_STALE, SiteStatus.REMAP_REQUIRED),
        (SiteStatus.MODEL_STALE, SiteStatus.SUSPENDED),
        (SiteStatus.REMAP_REQUIRED, SiteStatus.BASELINE_MAPPING),
        (SiteStatus.REMAP_REQUIRED, SiteStatus.SUSPENDED),
    ],
)
def test_legal_transition_allowed(cur: SiteStatus, nxt: SiteStatus) -> None:
    assert_site_transition(cur, nxt)  # raise 없이 통과
    assert can_site_transition(cur, nxt) is True


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        # UNMAPPED -> PATROL_READY 직행 거부 (§6.1 품질 검증 생략 금지)
        (SiteStatus.UNMAPPED, SiteStatus.PATROL_READY),
        (SiteStatus.UNMAPPED, SiteStatus.MODEL_PROCESSING),
        # BASELINE_MAPPING 은 MODEL_PROCESSING 단계를 건너뛸 수 없다
        (SiteStatus.BASELINE_MAPPING, SiteStatus.MODEL_VALIDATION),
        (SiteStatus.BASELINE_MAPPING, SiteStatus.PATROL_READY),
        # MODEL_VALIDATION -> PATROL_READY 직행 거부 (PROVISIONAL_AUTONOMY 경유 필수)
        (SiteStatus.MODEL_VALIDATION, SiteStatus.PATROL_READY),
        # PROVISIONAL_AUTONOMY -> PATROL_ACTIVE 직행 거부 (PATROL_READY 경유 필수)
        (SiteStatus.PROVISIONAL_AUTONOMY, SiteStatus.PATROL_ACTIVE),
        # REMAP_REQUIRED 는 BASELINE_MAPPING 재매핑으로만 복귀 (재매핑 우회 금지)
        (SiteStatus.REMAP_REQUIRED, SiteStatus.PATROL_READY),
        (SiteStatus.REMAP_REQUIRED, SiteStatus.MODEL_VALIDATION),
        # MODEL_STALE 은 REMAP_REQUIRED 경유 없이 BASELINE_MAPPING 직행 불가
        (SiteStatus.MODEL_STALE, SiteStatus.BASELINE_MAPPING),
        # MODEL_STALE -> PATROL_READY 직행 거부(§6.1 품질검증 우회 금지) — 재검증은
        # 반드시 MODEL_PROCESSING -> MODEL_VALIDATION -> PROVISIONAL_AUTONOMY 경유
        (SiteStatus.MODEL_STALE, SiteStatus.PATROL_READY),
        # SUSPENDED (resume_target 없이) 는 정적 표에 간선이 없다 — 무조건 거부
        (SiteStatus.SUSPENDED, SiteStatus.PATROL_READY),
        (SiteStatus.SUSPENDED, SiteStatus.UNMAPPED),
    ],
)
def test_illegal_transition_rejected(cur: SiteStatus, nxt: SiteStatus) -> None:
    with pytest.raises(IllegalSiteTransitionError):
        assert_site_transition(cur, nxt)
    assert can_site_transition(cur, nxt) is False


def test_illegal_transition_error_is_value_error() -> None:
    """assert_site_transition 의 불법 전이 예외는 ValueError 서브클래스여야 한다."""
    with pytest.raises(ValueError):
        assert_site_transition(SiteStatus.UNMAPPED, SiteStatus.PATROL_READY)


def test_patrol_ready_incoming_edges_are_exactly_two_plus_suspended_resume() -> None:
    """PATROL_READY 로 들어오는 정적 간선은 PROVISIONAL_AUTONOMY·PATROL_ACTIVE
    둘뿐임을 전이표 전수 검사로 증명한다(§6.1 품질검증 우회 경로 부재).

    MODEL_STALE 은 더 이상 PATROL_READY 로 직행하지 않는다 — 재검토 지적 반영,
    MODEL_STALE -> MODEL_PROCESSING 재처리를 거쳐야만 PROVISIONAL_AUTONOMY 재검증
    경유로 PATROL_READY 에 복귀한다. SUSPENDED 로부터의 resume 은 정적 표에 없고
    (동적 규칙) 별도 테스트에서 검증한다.
    """
    incoming = {
        cur
        for cur, targets in _ALLOWED_SITE_TRANSITIONS.items()
        if SiteStatus.PATROL_READY in targets
    }
    assert incoming == {
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_ACTIVE,
    }


def test_model_stale_recovers_to_patrol_ready_only_via_full_revalidation() -> None:
    """MODEL_STALE 은 REMAP_REQUIRED 경유 없이도 MODEL_PROCESSING 재처리로
    이탈할 수 있지만, PATROL_READY 복귀는 MODEL_VALIDATION -> PROVISIONAL_AUTONOMY
    품질검증 재수행을 다시 거쳐야 한다(§6.1 우회 금지, 재검토 지적 반영)."""
    assert can_site_transition(SiteStatus.MODEL_STALE, SiteStatus.MODEL_PROCESSING) is True
    assert can_site_transition(SiteStatus.MODEL_STALE, SiteStatus.PATROL_READY) is False
    assert_site_transition(SiteStatus.MODEL_STALE, SiteStatus.MODEL_PROCESSING)
    assert_site_transition(SiteStatus.MODEL_PROCESSING, SiteStatus.MODEL_VALIDATION)
    assert_site_transition(SiteStatus.MODEL_VALIDATION, SiteStatus.PROVISIONAL_AUTONOMY)
    assert_site_transition(SiteStatus.PROVISIONAL_AUTONOMY, SiteStatus.PATROL_READY)


def test_unmapped_to_patrol_ready_direct_rejected() -> None:
    """UNMAPPED -> PATROL_READY 직행은 어떤 경로 표현으로도 거부된다."""
    assert can_site_transition(SiteStatus.UNMAPPED, SiteStatus.PATROL_READY) is False
    with pytest.raises(IllegalSiteTransitionError):
        assert_site_transition(SiteStatus.UNMAPPED, SiteStatus.PATROL_READY)


class TestSuspendedResume:
    """SUSPENDED resume 의 4분기: 정상 resume · resume_target 불일치 · None · 재진입 거부."""

    def test_normal_resume_allowed(self) -> None:
        assert_site_transition(
            SiteStatus.SUSPENDED,
            SiteStatus.PATROL_READY,
            resume_target=SiteStatus.PATROL_READY,
        )
        assert (
            can_site_transition(
                SiteStatus.SUSPENDED,
                SiteStatus.PATROL_READY,
                resume_target=SiteStatus.PATROL_READY,
            )
            is True
        )

    def test_resume_target_mismatch_rejected(self) -> None:
        """저장소가 기억한 직전 상태와 다른 상태로의 resume 은 거부된다."""
        with pytest.raises(IllegalSiteTransitionError):
            assert_site_transition(
                SiteStatus.SUSPENDED,
                SiteStatus.PATROL_READY,
                resume_target=SiteStatus.BASELINE_MAPPING,
            )
        assert (
            can_site_transition(
                SiteStatus.SUSPENDED,
                SiteStatus.PATROL_READY,
                resume_target=SiteStatus.BASELINE_MAPPING,
            )
            is False
        )

    def test_resume_target_none_rejected(self) -> None:
        """resume_target 이 없으면(직전 상태를 저장소가 기억 못함) 어떤 nxt 도 거부된다."""
        with pytest.raises(IllegalSiteTransitionError):
            assert_site_transition(SiteStatus.SUSPENDED, SiteStatus.PATROL_READY)
        assert can_site_transition(SiteStatus.SUSPENDED, SiteStatus.PATROL_READY) is False

    def test_suspended_reentry_rejected(self) -> None:
        """SUSPENDED -> SUSPENDED 재진입은 resume_target 일치 여부와 무관하게 거부된다."""
        with pytest.raises(IllegalSiteTransitionError):
            assert_site_transition(
                SiteStatus.SUSPENDED,
                SiteStatus.SUSPENDED,
                resume_target=SiteStatus.SUSPENDED,
            )
        assert (
            can_site_transition(
                SiteStatus.SUSPENDED,
                SiteStatus.SUSPENDED,
                resume_target=SiteStatus.SUSPENDED,
            )
            is False
        )


def test_terminal_state_invariant_suspended_only_via_static_table_or_resume() -> None:
    """SUSPENDED 자체는 정적 표에서 아무 상태로도 전이하지 못한다(빈 set) —
    모든 SUSPENDED 이탈은 resume_target 경유의 동적 검증만 통과한다."""
    assert _ALLOWED_SITE_TRANSITIONS[SiteStatus.SUSPENDED] == set()


def test_transition_table_keys_cover_every_status() -> None:
    """전이표 키 전수 == SiteStatus 전수(누락 상태 없음)."""
    assert set(_ALLOWED_SITE_TRANSITIONS.keys()) == set(SiteStatus)
