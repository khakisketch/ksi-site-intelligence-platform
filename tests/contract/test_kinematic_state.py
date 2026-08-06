"""KinematicState 계약 검증 (Phase 3, PRD RISK-002) — Observation 과 동일한
fail-closed 규약(UTC 강제·공분산 필수·비유한 값 거부)을 속도 차원까지 지키는지."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from ksi_equipment_intelligence.kinematic_state import KinematicState
from pydantic import ValidationError

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "entity_id": "entity-1",
        "observed_at": _NOW,
        "site_frame": "site-001",
        "position": [10.0, 20.0, 0.0],
        "position_covariance": [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0],
        "velocity": [1.0, 0.0, 0.0],
        "velocity_covariance": [0.1, 0, 0, 0, 0.1, 0, 0, 0, 0.1],
        "source_class": "Excavator",
    }
    kwargs.update(overrides)
    return kwargs


def test_valid_state_round_trips() -> None:
    state = KinematicState.model_validate(_base_kwargs())
    assert state.entity_id == "entity-1"
    assert state.velocity == [1.0, 0.0, 0.0]
    assert state.heading_deg is None


def test_wire_uses_camel_case() -> None:
    state = KinematicState.model_validate(_base_kwargs())
    wire = state.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert "entityId" in wire
    assert "positionCovariance" in wire
    assert "velocityCovariance" in wire
    assert "sourceClass" in wire


@pytest.mark.parametrize("field", ["entity_id", "site_frame", "source_class"])
def test_blank_identifier_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="공백"):
        KinematicState.model_validate(_base_kwargs(**{field: "   "}))


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        KinematicState.model_validate(_base_kwargs(observed_at=datetime(2026, 8, 6, 12, 0, 0)))


def test_non_utc_offset_rejected() -> None:
    kst = _NOW.astimezone(timezone(timedelta(hours=9)))
    with pytest.raises(ValidationError, match="UTC"):
        KinematicState.model_validate(_base_kwargs(observed_at=kst))


@pytest.mark.parametrize("field", ["position", "velocity"])
def test_wrong_length_vector_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        KinematicState.model_validate(_base_kwargs(**{field: [1.0, 2.0]}))


@pytest.mark.parametrize("field", ["position_covariance", "velocity_covariance"])
def test_wrong_length_covariance_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        KinematicState.model_validate(_base_kwargs(**{field: [1.0] * 8}))


@pytest.mark.parametrize(
    "field", ["position", "velocity", "position_covariance", "velocity_covariance"]
)
def test_non_finite_values_rejected(field: str) -> None:
    length = 3 if field in ("position", "velocity") else 9
    bad = [float("nan")] + [0.0] * (length - 1)
    with pytest.raises(ValidationError, match="비유한"):
        KinematicState.model_validate(_base_kwargs(**{field: bad}))


def test_infinite_heading_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        KinematicState.model_validate(_base_kwargs(heading_deg=float("inf")))


def test_heading_optional_and_finite_when_present() -> None:
    state = KinematicState.model_validate(_base_kwargs(heading_deg=45.0))
    assert state.heading_deg == 45.0


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        KinematicState.model_validate(_base_kwargs(unexpectedField="x"))


def test_state_is_frozen() -> None:
    state = KinematicState.model_validate(_base_kwargs())
    with pytest.raises(ValidationError):
        state.entity_id = "other"
