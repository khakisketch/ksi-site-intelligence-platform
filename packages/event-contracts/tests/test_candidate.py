"""EventCandidate — lastSeenAt/firstSeenAt 순서 회귀 테스트.

reviewer 지적: 이 패키지의 다른 timestamp-ordered 모델(ComparisonRequest,
DesignSurface, ChangeDetectionResult)은 전부 "나중 시각이 앞선 시각보다 이르면
거부"하는 검증을 갖는데 EventCandidate 만 빠져 있었다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ksi_domain.enums import EventStatus, Severity
from ksi_event_contracts.candidate import EventCandidate
from pydantic import ValidationError


def _kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "eventType": "SLOPE_INSTABILITY",
        "severity": Severity.HIGH,
        "firstSeenAt": datetime(2026, 1, 1, tzinfo=UTC),
        "lastSeenAt": datetime(2026, 1, 2, tzinfo=UTC),
        "status": EventStatus.OBSERVATION,
    }
    base.update(overrides)
    return base


def test_last_seen_at_after_first_seen_at_is_accepted() -> None:
    candidate = EventCandidate.model_validate(_kwargs())
    assert candidate.last_seen_at > candidate.first_seen_at


def test_last_seen_at_equal_to_first_seen_at_is_accepted() -> None:
    same = datetime(2026, 1, 1, tzinfo=UTC)
    candidate = EventCandidate.model_validate(
        _kwargs(firstSeenAt=same, lastSeenAt=same)
    )
    assert candidate.last_seen_at == candidate.first_seen_at


def test_last_seen_at_before_first_seen_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EventCandidate.model_validate(
            _kwargs(
                firstSeenAt=datetime(2026, 1, 2, tzinfo=UTC),
                lastSeenAt=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
