"""``ksi_core.leasing`` 순수 함수 3개의 단위 테스트 (P1-2).

``ProcessingJobStore``·``ComparisonRequestStore`` 양쪽이 이 함수들을 호출해서
lease 판정을 하므로, 여기서 만료 경계(직전/직후)를 정확히 고정해두면 두 store
쪽 테스트는 "이 함수를 올바르게 호출하는가"만 보면 된다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ksi_core.leasing import JobLease, LeaseDenialReason, check_lease, is_claimable, next_lease
from ksi_event_contracts.processing_job import ProcessingJobStatus

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_TTL = timedelta(minutes=15)


def _lease(*, worker_id: str = "w-1", expires_at: datetime) -> JobLease:
    return JobLease(worker_id=worker_id, granted_at=_NOW, expires_at=expires_at)


# ── check_lease ──────────────────────────────────────────────────────────


def test_check_lease_missing_is_denied() -> None:
    assert check_lease(None, worker_id="w-1", now=_NOW) is LeaseDenialReason.MISSING_OR_EXPIRED


def test_check_lease_held_by_same_worker_passes() -> None:
    lease = _lease(expires_at=_NOW + _TTL)
    assert check_lease(lease, worker_id="w-1", now=_NOW) is None


def test_check_lease_held_by_another_worker_is_denied() -> None:
    lease = _lease(worker_id="w-1", expires_at=_NOW + _TTL)
    assert check_lease(lease, worker_id="w-2", now=_NOW) is LeaseDenialReason.HELD_BY_ANOTHER


def test_check_lease_expiry_boundary_is_exclusive() -> None:
    """``is_active`` 는 ``now < expires_at`` — 만료 시각 그 순간부터 만료다."""
    lease = _lease(expires_at=_NOW + _TTL)
    # 만료 1초 전: 여전히 이 워커의 것.
    just_before = _NOW + _TTL - timedelta(seconds=1)
    assert check_lease(lease, worker_id="w-1", now=just_before) is None
    # 만료 시각 그 자체: 이미 만료(다른 워커도 새로 잡을 수 있다는 뜻).
    assert (
        check_lease(lease, worker_id="w-1", now=lease.expires_at)
        is LeaseDenialReason.MISSING_OR_EXPIRED
    )
    # 만료 1초 후: 당연히 만료.
    just_after = _NOW + _TTL + timedelta(seconds=1)
    assert (
        check_lease(lease, worker_id="w-1", now=just_after) is LeaseDenialReason.MISSING_OR_EXPIRED
    )


# ── is_claimable ─────────────────────────────────────────────────────────


def test_is_claimable_queued_always_claimable() -> None:
    assert is_claimable(ProcessingJobStatus.QUEUED, None, _NOW) is True
    lease = _lease(expires_at=_NOW + _TTL)
    assert is_claimable(ProcessingJobStatus.QUEUED, lease, _NOW) is True


def test_is_claimable_running_with_active_lease_is_not_claimable() -> None:
    lease = _lease(expires_at=_NOW + _TTL)
    assert is_claimable(ProcessingJobStatus.RUNNING, lease, _NOW) is False


def test_is_claimable_running_with_expired_lease_is_claimable() -> None:
    lease = _lease(expires_at=_NOW + _TTL)
    assert is_claimable(ProcessingJobStatus.RUNNING, lease, lease.expires_at) is True


def test_is_claimable_running_without_any_lease_is_claimable() -> None:
    assert is_claimable(ProcessingJobStatus.RUNNING, None, _NOW) is True


def test_is_claimable_terminal_statuses_are_never_claimable() -> None:
    for status in (
        ProcessingJobStatus.SUCCEEDED,
        ProcessingJobStatus.FAILED,
        ProcessingJobStatus.CANCELLED,
    ):
        assert is_claimable(status, None, _NOW) is False


# ── next_lease ───────────────────────────────────────────────────────────


def test_next_lease_defaults_granted_at_to_now() -> None:
    lease = next_lease(worker_id="w-1", now=_NOW, ttl=_TTL)
    assert lease.worker_id == "w-1"
    assert lease.granted_at == _NOW
    assert lease.expires_at == _NOW + _TTL


def test_next_lease_preserves_explicit_granted_at_for_renewal() -> None:
    original_grant = _NOW - timedelta(minutes=5)
    renewal_time = _NOW
    lease = next_lease(worker_id="w-1", now=renewal_time, ttl=_TTL, granted_at=original_grant)
    assert lease.granted_at == original_grant
    assert lease.expires_at == renewal_time + _TTL
