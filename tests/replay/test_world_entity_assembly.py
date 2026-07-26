"""Track→WorldEntity 조립 + replay 재현 (P1-2, Phase 1 수용기준).

Phase 1의 핵심 주장을 검증한다: **여러 프레임에서 관찰된 동일 대상이 하나의 공간
객체로 합쳐지고, 같은 관측 집합은 항상 같은 결과를 낸다.**

    Frame A의 사람 ┐
    Frame B의 사람 ├→ WorldEntity 1개 (위치 + Covariance + Observation History)
    Frame C의 사람 ┘

결정성은 P0-6 규약대로 entity_id가 아니라 fingerprint(관측 계보·좌표계·융합 위치·
불확실성 상태)로 검증한다 — id는 실행마다 달라도 무방한 값이다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ksi_event_contracts.assembly import (
    AssemblyResult,
    AssemblyStatus,
    assemble_world_entity,
    world_entity_fingerprint,
)
from ksi_event_contracts.observation import Observation
from ksi_event_contracts.world_entity import WorldEntity
from ksi_geo_core.fusion import FusionStatus, covariance_trace

_FRAME = "EPSG:5186+KNGeoid2018@1.0.0"
_ISOTROPIC = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
_MODEL_VERSIONS = {"person-detector": "v3.1.0"}


def _observation(
    observation_id: str,
    position: list[float],
    *,
    track_id: str | None = "trk-1",
    seconds: int = 0,
    covariance: list[float] | None = None,
    site_frame: str = _FRAME,
    detection_confidence: float | None = 0.9,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        track_id=track_id,
        observed_at=datetime(2026, 7, 26, 4, 0, seconds, tzinfo=UTC),
        site_frame=site_frame,
        position=position,
        position_covariance=covariance if covariance is not None else list(_ISOTROPIC),
        detection_confidence=detection_confidence,
    )


def _assemble(observations: list[Observation]) -> AssemblyResult:
    return assemble_world_entity(
        observations,
        entity_id="ent-001",
        entity_class="Person",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
    )


def _assemble_ok(observations: list[Observation]) -> WorldEntity:
    """조립이 성공했음을 단정하고 non-optional entity를 돌려준다.

    Optional 해제를 테스트마다 반복하지 않기 위한 헬퍼 — 동시에 "성공했어야
    한다"는 기대를 명시적으로 만든다.
    """
    result = _assemble(observations)
    assert result.status is AssemblyStatus.OK, result.detail
    assert result.entity is not None
    return result.entity


# ── 다중 프레임 → 단일 WorldEntity ────────────────────────────────────────────


def test_three_frames_become_one_world_entity() -> None:
    """세 프레임의 같은 사람이 WorldEntity 1개로 합쳐진다 — Phase 1 핵심 주장."""
    observations = [
        _observation("obs-a", [10.0, 20.0, 1.7], seconds=0),
        _observation("obs-b", [10.2, 19.9, 1.7], seconds=1),
        _observation("obs-c", [9.9, 20.1, 1.8], seconds=2),
    ]

    entity = _assemble_ok(observations)
    assert entity.entity_class == "Person"
    assert entity.site_frame == _FRAME
    assert entity.lineage.track_id == "trk-1"
    # Observation History 가 보존된다(정렬된 형태로).
    assert entity.lineage.observation_ids == ["obs-a", "obs-b", "obs-c"]
    # 융합 위치는 세 관측 사이에 있다.
    assert 9.9 <= entity.pose.position[0] <= 10.2
    assert 19.9 <= entity.pose.position[1] <= 20.1


def test_fusion_reduces_uncertainty_below_single_observation() -> None:
    """[INV-021] 3관측 융합 공분산은 단일 관측보다 작아야 한다."""
    single = _assemble_ok([_observation("obs-a", [10.0, 20.0, 1.7])])
    triple = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7]),
            _observation("obs-b", [10.1, 20.0, 1.7]),
            _observation("obs-c", [9.9, 20.0, 1.7]),
        ]
    )

    single_trace = covariance_trace(tuple(single.uncertainty.position_covariance))
    triple_trace = covariance_trace(tuple(triple.uncertainty.position_covariance))
    assert triple_trace < single_trace


def test_timestamp_is_latest_observation() -> None:
    """Entity 시각은 가장 늦은 관측 시각 — 가장 최근 정보가 반영된 시점."""
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], seconds=0),
            _observation("obs-c", [10.0, 20.0, 1.7], seconds=5),
            _observation("obs-b", [10.0, 20.0, 1.7], seconds=2),
        ]
    )
    assert entity.timestamp.second == 5


def test_classification_confidence_uses_minimum_not_optimistic() -> None:
    """낙관적 병합 금지(P0-2 품질 병합과 같은 원칙) — 최솟값을 취한다."""
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], detection_confidence=0.95),
            _observation("obs-b", [10.0, 20.0, 1.7], detection_confidence=0.62),
        ]
    )
    assert entity.uncertainty.classification_confidence == pytest.approx(0.62)


def test_missing_any_confidence_yields_none() -> None:
    """하나라도 신뢰도가 없으면 결과도 없음 — 없는 값을 채워 넣지 않는다."""
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], detection_confidence=0.9),
            _observation("obs-b", [10.0, 20.0, 1.7], detection_confidence=None),
        ]
    )
    assert entity.uncertainty.classification_confidence is None


# ── localization_state 판정 ───────────────────────────────────────────────────


def test_single_observation_is_insufficient_regardless_of_covariance() -> None:
    """[PRD §10.9] 관측 1건은 공분산이 아무리 작아도 INSUFFICIENT_OBSERVATION.

    작은 공분산이 곧 다중 시점 검증을 뜻하지는 않는다 — 단일 시점 깊이 추정을
    신뢰하지 않는다는 원칙을 상태로 표현한다.
    """
    tiny = [0.001, 0, 0, 0, 0.001, 0, 0, 0, 0.001]
    entity = _assemble_ok([_observation("obs-a", [10.0, 20.0, 1.7], covariance=tiny)])
    assert entity.uncertainty.localization_state == "INSUFFICIENT_OBSERVATION"


def test_tight_multi_observation_is_confirmed() -> None:
    tight = [0.1, 0, 0, 0, 0.1, 0, 0, 0, 0.1]
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], covariance=tight),
            _observation("obs-b", [10.0, 20.0, 1.7], covariance=tight),
        ]
    )
    assert entity.uncertainty.localization_state == "CONFIRMED"


def test_loose_multi_observation_is_boundary_uncertain() -> None:
    """공분산이 크면 CONFIRMED로 올리지 않는다 — 불확실성을 숨기지 않는다."""
    loose = [50.0, 0, 0, 0, 50.0, 0, 0, 0, 50.0]
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], covariance=loose),
            _observation("obs-b", [10.0, 20.0, 1.7], covariance=loose),
        ]
    )
    assert entity.uncertainty.localization_state == "BOUNDARY_UNCERTAIN"


def test_state_thresholds_are_injectable_not_hardcoded_truth() -> None:
    """문턱값은 실측 미검증 임시값이라 호출자가 주입할 수 있어야 한다."""
    covariance = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
    observations = [
        _observation("obs-a", [0.0, 0.0, 0.0], covariance=covariance),
        _observation("obs-b", [0.0, 0.0, 0.0], covariance=covariance),
    ]
    strict = assemble_world_entity(
        observations,
        entity_id="e",
        entity_class="Person",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
        confirmed_trace_max=0.01,  # 매우 엄격 → CONFIRMED 불가
        likely_trace_max=100.0,
    )
    assert strict.entity is not None
    assert strict.entity.uncertainty.localization_state == "LIKELY"


# ── replay 재현 (결정성) ──────────────────────────────────────────────────────


def test_same_observations_produce_identical_fingerprint() -> None:
    """동일 관측 집합 → 동일 fingerprint (2회 독립 조립)."""
    def build() -> list[Observation]:
        return [
            _observation("obs-a", [10.0, 20.0, 1.7], seconds=0),
            _observation("obs-b", [10.2, 19.9, 1.7], seconds=1),
        ]

    first = _assemble_ok(build())
    second = _assemble_ok(build())

    assert world_entity_fingerprint(first) == world_entity_fingerprint(second)


def test_observation_order_does_not_change_fingerprint() -> None:
    """관측 도착 순서가 뒤섞여도 같은 WorldEntity — replay 재현의 핵심."""
    observations = [
        _observation("obs-a", [10.0, 20.0, 1.7], seconds=0),
        _observation("obs-b", [10.2, 19.9, 1.7], seconds=1),
        _observation("obs-c", [9.9, 20.1, 1.8], seconds=2),
    ]

    forward = _assemble_ok(list(observations))
    reversed_order = _assemble_ok(list(reversed(observations)))
    shuffled = _assemble_ok([observations[1], observations[2], observations[0]])

    fp_forward = world_entity_fingerprint(forward)
    fp_reversed = world_entity_fingerprint(reversed_order)
    fp_shuffled = world_entity_fingerprint(shuffled)
    assert fp_forward == fp_reversed == fp_shuffled

    # 위치도 비트 동일해야 한다(부동소수 누산 순서 정규화).
    assert forward.pose.position == reversed_order.pose.position


def test_entity_id_does_not_affect_fingerprint() -> None:
    """entity_id는 실행마다 달라도 무방한 값 — fingerprint에 포함되지 않는다."""
    observations = [
        _observation("obs-a", [10.0, 20.0, 1.7]),
        _observation("obs-b", [10.1, 20.0, 1.7]),
    ]
    a = assemble_world_entity(
        observations,
        entity_id="ent-AAA",
        entity_class="Person",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
    )
    b = assemble_world_entity(
        observations,
        entity_id="ent-ZZZ",
        entity_class="Person",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
    )
    assert a.entity is not None and b.entity is not None
    assert world_entity_fingerprint(a.entity) == world_entity_fingerprint(b.entity)


def test_different_observations_produce_different_fingerprint() -> None:
    """fingerprint가 실제로 내용에 민감한지 — 무조건 같은 값을 내는 게 아님을 확인."""
    base = _assemble_ok(
        [_observation("obs-a", [10.0, 20.0, 1.7]), _observation("obs-b", [10.1, 20.0, 1.7])]
    )
    moved = _assemble_ok(
        [_observation("obs-a", [99.0, 20.0, 1.7]), _observation("obs-b", [10.1, 20.0, 1.7])]
    )
    assert world_entity_fingerprint(base) != world_entity_fingerprint(moved)


# ── 네거티브 (fail-closed) ────────────────────────────────────────────────────


def test_empty_observations_rejected() -> None:
    result = _assemble([])
    assert result.status is AssemblyStatus.NO_OBSERVATIONS
    assert result.entity is None


def test_observation_without_track_id_rejected() -> None:
    """연관이 확정되지 않은 관측은 Entity로 승격할 수 없다."""
    result = _assemble(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], track_id="trk-1"),
            _observation("obs-b", [10.1, 20.0, 1.7], track_id=None),
        ]
    )
    assert result.status is AssemblyStatus.MISSING_TRACK_ID
    assert result.entity is None


def test_mixed_track_ids_rejected() -> None:
    """서로 다른 track을 한 Entity로 합치면 서로 다른 대상을 뭉개는 것이다."""
    result = _assemble(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], track_id="trk-1"),
            _observation("obs-b", [10.1, 20.0, 1.7], track_id="trk-2"),
        ]
    )
    assert result.status is AssemblyStatus.TRACK_ID_MISMATCH
    assert result.entity is None


def test_crs_mismatch_propagates_as_fusion_failure() -> None:
    """[INV-020] 좌표계가 다르면 융합 단계에서 거부되고 그 사유가 보존된다."""
    result = _assemble(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], site_frame="EPSG:5186+KNGeoid2018@1.0.0"),
            _observation("obs-b", [10.1, 20.0, 1.7], site_frame="EPSG:4326+WGS84@1.0.0"),
        ]
    )
    assert result.status is AssemblyStatus.FUSION_FAILED
    assert result.fusion_status is FusionStatus.CRS_MISMATCH
    assert result.entity is None


def test_singular_covariance_propagates_as_fusion_failure() -> None:
    result = _assemble(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], covariance=[0.0] * 9),
            _observation("obs-b", [10.1, 20.0, 1.7]),
        ]
    )
    assert result.status is AssemblyStatus.FUSION_FAILED
    assert result.fusion_status is FusionStatus.SINGULAR_COVARIANCE


def test_assembled_entity_satisfies_world_entity_schema_invariants() -> None:
    """조립 결과가 WorldEntity 계약(INV-020/042)을 실제로 만족하는지."""
    entity = _assemble_ok(
        [_observation("obs-a", [10.0, 20.0, 1.7]), _observation("obs-b", [10.1, 20.0, 1.7])]
    )
    # INV-020: CRS·시각·공분산
    assert entity.site_frame
    assert entity.timestamp.tzinfo is not None
    assert len(entity.uncertainty.position_covariance) == 9
    # INV-042: 계보
    assert entity.lineage.track_id
    assert entity.lineage.model_versions == _MODEL_VERSIONS
    assert entity.lineage.calibration_profile_id == "cal-1"
    assert entity.lineage.observation_ids == ["obs-a", "obs-b"]
    # 스키마 왕복도 통과해야 한다.
    dumped = entity.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert dumped["class"] == "Person"
