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

from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from ksi_event_contracts.assembly import (
    AssemblyResult,
    AssemblyStatus,
    assemble_world_entity,
    world_entity_fingerprint,
)
from ksi_event_contracts.observation import (
    Observation,
    ViewpointEvidenceKind,
    viewpoint_bin_id,
)
from ksi_event_contracts.world_entity import WorldEntity
from ksi_geo_core.fusion import FusionStatus, covariance_trace
from pydantic import ValidationError

_FRAME = "EPSG:5186+KNGeoid2018@1.0.0"
_ISOTROPIC = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
_MODEL_VERSIONS = {"person-detector": "v3.1.0"}

# "인자를 안 넘김"과 "명시적으로 None(관측점 모름)"을 구분하는 sentinel.
_UNSET = object()
_BASE_TIME = datetime(2026, 7, 26, 4, 0, 0, tzinfo=UTC)


def _observation(
    observation_id: str,
    position: list[float],
    *,
    track_id: str | None = "trk-1",
    millis: int = 0,
    covariance: list[float] | None = None,
    site_frame: str = _FRAME,
    detection_confidence: float | None = 0.9,
    viewpoint_id: str | None | object = _UNSET,
    viewpoint_kind: ViewpointEvidenceKind | None = None,
    observed_class: str = "Person",
    ontology_version: str = "ksi-ontology-v1",
) -> Observation:
    # 미지정이면 관측 id에서 파생 — 별개 관측은 기본적으로 서로 다른 관측점으로 본다.
    # 같은 관측점이나 "모름(None)"을 표현하려면 호출자가 명시적으로 넘긴다.
    resolved_id = (
        f"vp-{observation_id}" if viewpoint_id is _UNSET else cast("str | None", viewpoint_id)
    )
    # 등급 기본값: ID가 있으면 보정 Pose 참조로 본다. 이 헬퍼를 쓰는 대부분의 테스트는
    # 공분산·융합·시간창 같은 **다른 축**을 검증하므로, 시점 증거를 매번 명시하게 하면
    # 그 축들의 의도가 흐려진다. 시점 증거 자체를 다루는 테스트는 명시적으로 넘긴다.
    resolved_kind = viewpoint_kind or (
        ViewpointEvidenceKind.UNKNOWN
        if resolved_id is None
        else ViewpointEvidenceKind.CALIBRATED_POSE
    )
    return Observation(
        observation_id=observation_id,
        observed_class=observed_class,
        ontology_version=ontology_version,
        track_id=track_id,
        observed_at=_BASE_TIME + timedelta(milliseconds=millis),
        site_frame=site_frame,
        position=position,
        position_covariance=covariance if covariance is not None else list(_ISOTROPIC),
        detection_confidence=detection_confidence,
        viewpoint_id=resolved_id,
        viewpoint_kind=resolved_kind,
    )


def _assemble(observations: list[Observation]) -> AssemblyResult:
    return assemble_world_entity(
        observations,
        entity_id="ent-001",
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
        _observation("obs-a", [10.0, 20.0, 1.7], millis=0),
        _observation("obs-b", [10.2, 19.9, 1.7], millis=100),
        _observation("obs-c", [9.9, 20.1, 1.8], millis=200),
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
            _observation("obs-a", [10.0, 20.0, 1.7], millis=0),
            _observation("obs-c", [10.0, 20.0, 1.7], millis=500),
            _observation("obs-b", [10.0, 20.0, 1.7], millis=200),
        ]
    )
    assert entity.timestamp == _BASE_TIME + timedelta(milliseconds=500)


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


def test_tight_multi_observation_from_distinct_viewpoints_is_confirmed() -> None:
    """공분산이 작고 **서로 다른 관측점** 2개면 CONFIRMED."""
    tight = [0.1, 0, 0, 0, 0.1, 0, 0, 0, 0.1]
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], covariance=tight, viewpoint_id="vp-1"),
            _observation("obs-b", [10.0, 20.0, 1.7], covariance=tight, viewpoint_id="vp-2"),
        ]
    )
    assert entity.uncertainty.localization_state == "CONFIRMED"


def test_same_viewpoint_multiple_frames_not_confirmed() -> None:
    """[2차 반증 P0] 같은 관측점의 여러 프레임은 시차가 없어 깊이를 독립 검증 못 한다.

    공분산이 아무리 작아도 CONFIRMED로 올리지 않고 LIKELY로 제한한다 — 관측 수만
    늘어난 것을 다중 시점 검증으로 오인하면 안 된다.
    """
    tight = [0.1, 0, 0, 0, 0.1, 0, 0, 0, 0.1]
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], covariance=tight, viewpoint_id="vp-same"),
            _observation("obs-b", [10.0, 20.0, 1.7], covariance=tight, viewpoint_id="vp-same"),
            _observation("obs-c", [10.0, 20.0, 1.7], covariance=tight, viewpoint_id="vp-same"),
        ]
    )
    assert entity.uncertainty.localization_state == "LIKELY"


def test_unknown_viewpoint_does_not_claim_diversity() -> None:
    """viewpoint_id 를 모르는 소스는 시점 다양성을 주장하지 않는다(모르면 확신 안 함)."""
    tight = [0.1, 0, 0, 0, 0.1, 0, 0, 0, 0.1]
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], covariance=tight, viewpoint_id=None),
            _observation("obs-b", [10.0, 20.0, 1.7], covariance=tight, viewpoint_id=None),
        ]
    )
    assert entity.uncertainty.localization_state == "LIKELY"


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
            _observation("obs-a", [10.0, 20.0, 1.7], millis=0),
            _observation("obs-b", [10.2, 19.9, 1.7], millis=100),
        ]

    first = _assemble_ok(build())
    second = _assemble_ok(build())

    assert world_entity_fingerprint(first) == world_entity_fingerprint(second)


def test_observation_order_does_not_change_fingerprint() -> None:
    """관측 도착 순서가 뒤섞여도 같은 WorldEntity — replay 재현의 핵심."""
    observations = [
        _observation("obs-a", [10.0, 20.0, 1.7], millis=0),
        _observation("obs-b", [10.2, 19.9, 1.7], millis=100),
        _observation("obs-c", [9.9, 20.1, 1.8], millis=200),
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
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
    )
    b = assemble_world_entity(
        observations,
        entity_id="ent-ZZZ",
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
        [_observation("obs-a", [10.6, 20.0, 1.7]), _observation("obs-b", [10.1, 20.0, 1.7])]
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
    assert result.fusion_status is FusionStatus.NON_POSITIVE_DEFINITE


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
    # 스키마 왕복 — 실제 JSON Schema SSOT 로 검증한다(주석만으로는 왕복 주장이
    # 공허하다). Blocker 5 의 lineage 확장 필드가 스키마와 정합함도 여기서 고정.
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    dumped = entity.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert dumped["class"] == "Person"
    assert dumped["lineage"]["classificationOntologyVersion"] == "ksi-ontology-v1"
    schema = json.loads(Path("contracts/schemas/world-entity.v1.json").read_text("utf-8"))
    Draft202012Validator(schema).validate(dumped)


# ── 2차 반증 리뷰 (2026-07-27) — 문턱 검증 + tz-aware 강제 ────────────────────


@pytest.mark.parametrize(
    ("confirmed", "likely"),
    [
        (float("nan"), 12.0),
        (float("inf"), 12.0),
        (-1.0, 12.0),
        (0.75, float("nan")),
        (0.75, float("inf")),
        (12.0, 0.75),  # 순서 역전 — 더 느슨한 기준이 먼저 적용되면 잘못된 CONFIRMED
    ],
)
def test_invalid_thresholds_rejected(confirmed: float, likely: float) -> None:
    """[2차 반증] 주입 가능하게 열어 둔 문턱은 검증도 필요하다."""
    result = assemble_world_entity(
        [_observation("obs-a", [0.0, 0.0, 0.0]), _observation("obs-b", [0.1, 0.0, 0.0])],
        entity_id="e",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
        confirmed_trace_max=confirmed,
        likely_trace_max=likely,
    )
    assert result.status is AssemblyStatus.INVALID_THRESHOLDS
    assert result.entity is None


def test_equal_thresholds_allowed() -> None:
    """confirmed == likely 는 유효하다(경계가 겹치는 것은 순서 역전이 아니다)."""
    result = assemble_world_entity(
        [_observation("obs-a", [0.0, 0.0, 0.0]), _observation("obs-b", [0.1, 0.0, 0.0])],
        entity_id="e",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
        confirmed_trace_max=1.0,
        likely_trace_max=1.0,
    )
    assert result.status is AssemblyStatus.OK


def test_naive_observed_at_rejected_by_contract() -> None:
    """[2차 반증] naive 시각이 섞이면 max() 비교가 런타임 예외가 된다 — 계약에서 차단."""
    with pytest.raises(ValidationError):
        Observation(
            observation_id="obs-a",
            observed_class="Person",
            ontology_version="ksi-ontology-v1",
            track_id="trk-1",
            observed_at=datetime(2026, 7, 26, 4, 0, 0),  # noqa: DTZ001 — 의도적 naive
            site_frame=_FRAME,
            position=[0.0, 0.0, 0.0],
            position_covariance=list(_ISOTROPIC),
        )


def test_non_utc_offset_observed_at_rejected() -> None:
    """tz-aware 이지만 UTC가 아닌 오프셋도 거부 — 시각 축을 UTC로 고정한다."""
    kst = timezone(timedelta(hours=9))
    with pytest.raises(ValidationError):
        Observation(
            observation_id="obs-a",
            observed_class="Person",
            ontology_version="ksi-ontology-v1",
            track_id="trk-1",
            observed_at=datetime(2026, 7, 26, 13, 0, 0, tzinfo=kst),
            site_frame=_FRAME,
            position=[0.0, 0.0, 0.0],
            position_covariance=list(_ISOTROPIC),
        )


def test_utc_observed_at_accepted() -> None:
    observation = Observation(
        observation_id="obs-a",
        observed_class="Person",
        ontology_version="ksi-ontology-v1",
        track_id="trk-1",
        observed_at=datetime(2026, 7, 26, 4, 0, 0, tzinfo=UTC),
        site_frame=_FRAME,
        position=[0.0, 0.0, 0.0],
        position_covariance=list(_ISOTROPIC),
    )
    assert observation.observed_at.utcoffset() == timedelta(0)


def test_duplicate_observation_id_blocked_at_assembly() -> None:
    """중복 관측이 조립 단계에서도 차단되는지 — 융합 실패가 전파돼야 한다."""
    result = _assemble(
        [
            _observation("obs-dup", [10.0, 20.0, 1.7]),
            _observation("obs-dup", [10.0, 20.0, 1.7]),
        ]
    )
    assert result.status is AssemblyStatus.FUSION_FAILED
    assert result.fusion_status is FusionStatus.DUPLICATE_OBSERVATION_ID
    assert result.entity is None


def test_contradictory_observations_never_reach_confirmed() -> None:
    """[2차 반증 P0] 모순 관측이 CONFIRMED로 승격되는 경로가 없어야 한다."""
    tight = [0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01]
    result = _assemble(
        [
            _observation("obs-a", [0.0, 0.0, 0.0], covariance=tight, viewpoint_id="vp-1"),
            _observation("obs-b", [100.0, 0.0, 0.0], covariance=tight, viewpoint_id="vp-2"),
        ]
    )
    assert result.status is AssemblyStatus.FUSION_FAILED
    assert result.fusion_status is FusionStatus.INCONSISTENT_OBSERVATIONS
    assert result.entity is None


def test_negative_covariance_never_reaches_confirmed() -> None:
    """[2차 반증 P0] 음수 공분산이 trace 음수 → CONFIRMED 되는 경로가 없어야 한다."""
    negative = [-1.0, 0, 0, 0, -1.0, 0, 0, 0, -1.0]
    result = _assemble(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], covariance=negative),
            _observation("obs-b", [10.0, 20.0, 1.7], covariance=negative),
        ]
    )
    assert result.status is AssemblyStatus.FUSION_FAILED
    assert result.fusion_status is FusionStatus.NON_POSITIVE_DEFINITE
    assert result.entity is None


# ── HIL 이전 보완 (독립 검토 2026-07-27 지정) ─────────────────────────────────


def test_observation_window_exceeded_rejected() -> None:
    """[보완 5] 넓은 시간창 관측은 정적 융합으로 합치지 않는다(이동거리가 편향이 된다)."""
    result = _assemble(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], millis=0),
            _observation("obs-b", [10.0, 20.0, 1.7], millis=1500),  # 1.5s > 기본 1.0s
        ]
    )
    assert result.status is AssemblyStatus.OBSERVATION_WINDOW_EXCEEDED
    assert result.entity is None
    assert result.detail is not None and "시간창" in result.detail


def test_observation_window_is_injectable() -> None:
    """창을 넓히면 통과 — 문턱이 실제로 쓰이는지 확인."""
    observations = [
        _observation("obs-a", [10.0, 20.0, 1.7], millis=0),
        _observation("obs-b", [10.0, 20.0, 1.7], millis=1500),
    ]
    result = assemble_world_entity(
        observations,
        entity_id="e",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
        max_observation_window_s=2.0,
    )
    assert result.status is AssemblyStatus.OK


@pytest.mark.parametrize("bad_window", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_observation_window_rejected(bad_window: float) -> None:
    result = assemble_world_entity(
        [_observation("obs-a", [0.0, 0.0, 0.0]), _observation("obs-b", [0.1, 0.0, 0.0])],
        entity_id="e",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
        max_observation_window_s=bad_window,
    )
    assert result.status is AssemblyStatus.INVALID_THRESHOLDS


def test_max_normalized_residual_is_threaded_to_fusion() -> None:
    """[보완 1] assemble 이 residual 문턱을 융합까지 전달하는지 — 좁히면 거부돼야 한다."""
    sigma_one = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
    observations = [
        _observation("obs-a", [0.0, 0.0, 0.0], covariance=sigma_one, viewpoint_id="vp-1"),
        _observation("obs-b", [5.0, 0.0, 0.0], covariance=sigma_one, viewpoint_id="vp-2"),
    ]

    lenient = assemble_world_entity(
        observations,
        entity_id="e",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
        max_normalized_residual=10.0,
    )
    strict = assemble_world_entity(
        observations,
        entity_id="e",
        model_versions=_MODEL_VERSIONS,
        calibration_profile_id="cal-1",
        max_normalized_residual=1.0,
    )

    assert lenient.status is AssemblyStatus.OK
    assert strict.status is AssemblyStatus.FUSION_FAILED
    assert strict.fusion_status is FusionStatus.INCONSISTENT_OBSERVATIONS


@pytest.mark.parametrize("field_name", ["observation_id", "track_id", "viewpoint_id", "sensor_id"])
def test_whitespace_only_identifier_rejected(field_name: str) -> None:
    """[보완 4] 공백만인 식별자는 min_length=1 을 통과하지만 식별자로 쓸 수 없다."""
    kwargs: dict[str, object] = {
        "observation_id": "obs-a",
        "track_id": "trk-1",
        "observed_at": datetime(2026, 7, 26, 4, 0, 0, tzinfo=UTC),
        "site_frame": _FRAME,
        "position": [0.0, 0.0, 0.0],
        "position_covariance": list(_ISOTROPIC),
        "viewpoint_id": "vp-1",
        "sensor_id": "cam-1",
    }
    kwargs[field_name] = "   "
    with pytest.raises(ValidationError):
        Observation(**kwargs)  # type: ignore[arg-type]


def test_empty_observation_id_rejected() -> None:
    with pytest.raises(ValidationError):
        Observation(
            observation_id="",
            observed_class="Person",
            ontology_version="ksi-ontology-v1",
            observed_at=datetime(2026, 7, 26, 4, 0, 0, tzinfo=UTC),
            site_frame=_FRAME,
            position=[0.0, 0.0, 0.0],
            position_covariance=list(_ISOTROPIC),
        )


# ── viewpoint bin (보완 2) ────────────────────────────────────────────────────


def test_nearby_viewpoints_share_bin() -> None:
    """[보완 2] 정지 호버링 중 미세하게 다른 위치는 같은 bin — 시차가 없으므로."""
    a = viewpoint_bin_id((10.0, 20.0, 30.0))
    b = viewpoint_bin_id((10.3, 20.2, 30.1))  # 0.3m 차이 < 기본 2m bin
    assert a == b


def test_distant_viewpoints_get_different_bins() -> None:
    """의미 있는 기선(baseline)만큼 떨어지면 서로 다른 bin."""
    a = viewpoint_bin_id((0.0, 0.0, 0.0))
    b = viewpoint_bin_id((5.0, 0.0, 0.0))
    assert a != b


def test_viewpoint_bin_is_deterministic() -> None:
    assert viewpoint_bin_id((1.5, 2.5, 3.5)) == viewpoint_bin_id((1.5, 2.5, 3.5))


def test_viewpoint_bin_size_affects_grouping() -> None:
    """bin 크기를 키우면 더 멀리 떨어진 관측점도 같은 bin으로 묶인다."""
    coarse_a = viewpoint_bin_id((0.0, 0.0, 0.0), bin_meters=100.0)
    coarse_b = viewpoint_bin_id((50.0, 0.0, 0.0), bin_meters=100.0)
    assert coarse_a == coarse_b


@pytest.mark.parametrize("bad_bin", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_bin_meters_rejected(bad_bin: float) -> None:
    with pytest.raises(ValueError, match="bin_meters"):
        viewpoint_bin_id((0.0, 0.0, 0.0), bin_meters=bad_bin)


def test_nonfinite_viewpoint_position_rejected() -> None:
    with pytest.raises(ValueError, match="position"):
        viewpoint_bin_id((float("nan"), 0.0, 0.0))


def test_hovering_frames_binned_to_same_viewpoint_not_confirmed() -> None:
    """[보완 2 통합] 호버링 프레임들이 bin으로 묶여 CONFIRMED 로 승격되지 않는다.

    이것이 viewpoint_id 를 임의 프레임 ID로 두면 안 되는 이유다 — bin을 쓰면 시차
    없는 관측이 다중 시점 증거로 오인되지 않는다.
    """
    tight = [0.1, 0, 0, 0, 0.1, 0, 0, 0, 0.1]
    # 같은 bin 내부에 확실히 들어가는 pose들(경계 미접촉) — 전형적 호버링 상황.
    hovering = [(10.0, 20.0, 30.0), (10.2, 20.1, 30.05), (10.4, 20.3, 30.2)]
    entity = _assemble_ok(
        [
            _observation(
                f"obs-{i}",
                [10.0, 20.0, 1.7],
                covariance=tight,
                millis=i * 100,
                viewpoint_id=viewpoint_bin_id(pose),
                viewpoint_kind=ViewpointEvidenceKind.SPATIAL_BIN,
            )
            for i, pose in enumerate(hovering)
        ]
    )
    assert entity.uncertainty.localization_state == "LIKELY", (
        "호버링 프레임이 CONFIRMED 로 승격되면 시점 다양성 게이트가 무력화된 것이다"
    )


def test_viewpoint_bin_boundary_sensitivity_is_known_limitation() -> None:
    """[보완 2 한계 기록] 격자 경계를 걸친 근접 pose는 다른 bin이 된다.

    이는 시점 다양성을 **과다 계상**하는 방향의 오차다(시차가 없는데 서로 다른 시점으로
    보임). 숨은 성질로 두면 위험하므로 여기 명시적으로 고정한다 — 권위 있는 형식은
    calibrated camera pose 참조이며, 이 폴백의 한계는 모듈 docstring에 기록돼 있다.
    """
    # bin 2m 에서 9.9 → floor(4.95)=4, 10.0 → floor(5.0)=5 : 0.1m 차이인데 다른 bin
    just_below = viewpoint_bin_id((9.9, 20.0, 30.0))
    just_above = viewpoint_bin_id((10.0, 20.0, 30.0))
    assert just_below != just_above, (
        "격자 경계 민감성이 사라졌다면 구현이 바뀐 것 — 문서와 한계 기록을 갱신하라"
    )


# ── 시점 증거 등급 게이트 (3차 반증 리뷰 2026-07-27) ──────────────────────────
#
# 위 경계 민감성은 "알려진 한계"로 기록만 돼 있었고, 조립 코드는 ID 문자열이 다른지만
# 셌다 — 즉 0.1m 떨어진 두 관측점이 CONFIRMED 를 만들 수 있었다. 아래 테스트들이
# 그 경로를 닫는다: bin 증거는 등급으로 차단되며, CONFIRMED 는 보정 Pose 전용이다.


def test_bin_boundary_pair_cannot_reach_confirmed() -> None:
    """[핵심 회귀] 격자 경계를 걸친 0.1m 차이 관측점 2개는 CONFIRMED 가 될 수 없다.

    ``viewpoint_bin_id`` 는 이 둘을 서로 다른 bin으로 계상하지만(위 한계 테스트),
    실제 기선은 0.1m 로 시차 검증이 불가능하다. 공분산이 아무리 작아도 이 조합이
    CONFIRMED 를 만들면 안 된다 — 이것이 시점 다양성 게이트의 우회 경로였다.
    """
    tight = [0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01]
    entity = _assemble_ok(
        [
            _observation(
                "obs-a",
                [10.0, 20.0, 1.7],
                covariance=tight,
                viewpoint_id=viewpoint_bin_id((9.9, 20.0, 30.0)),
                viewpoint_kind=ViewpointEvidenceKind.SPATIAL_BIN,
            ),
            _observation(
                "obs-b",
                [10.0, 20.0, 1.7],
                covariance=tight,
                millis=100,
                viewpoint_id=viewpoint_bin_id((10.0, 20.0, 30.0)),
                viewpoint_kind=ViewpointEvidenceKind.SPATIAL_BIN,
            ),
        ]
    )
    assert entity.uncertainty.localization_state == "LIKELY", (
        "0.1m 기선의 격자 경계 쌍이 CONFIRMED 로 승격됐다 — "
        "bin 증거의 과다 계상이 최고 확신 등급을 얻는 경로가 다시 열렸다"
    )


def test_spatial_bin_evidence_is_capped_at_likely() -> None:
    """멀리 떨어진 진짜 서로 다른 bin이어도 등급이 SPATIAL_BIN 이면 최대 LIKELY.

    bin 방식은 개별 사례가 아니라 **형식 자체**가 기선을 보장하지 못한다. 우연히
    충분히 떨어진 경우까지 일일이 구제하지 않는다 — 보장 없는 증거는 등급으로 막고,
    권한은 보정 Pose 경로에만 준다.
    """
    tight = [0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01]
    entity = _assemble_ok(
        [
            _observation(
                "obs-a",
                [10.0, 20.0, 1.7],
                covariance=tight,
                viewpoint_id=viewpoint_bin_id((0.0, 0.0, 30.0)),
                viewpoint_kind=ViewpointEvidenceKind.SPATIAL_BIN,
            ),
            _observation(
                "obs-b",
                [10.0, 20.0, 1.7],
                covariance=tight,
                millis=100,
                viewpoint_id=viewpoint_bin_id((40.0, 0.0, 30.0)),
                viewpoint_kind=ViewpointEvidenceKind.SPATIAL_BIN,
            ),
        ]
    )
    assert entity.uncertainty.localization_state == "LIKELY"


def test_unknown_kind_with_distinct_ids_is_capped_at_likely() -> None:
    """등급 미선언(UNKNOWN)은 ID가 서로 달라도 시점 다양성을 주장하지 못한다.

    기본값이 UNKNOWN 이므로, 새 소스가 필드를 채우지 않은 채 붙어도 **우연히**
    CONFIRMED 를 얻는 일이 없다(fail-safe).
    """
    tight = [0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01]
    entity = _assemble_ok(
        [
            _observation(
                "obs-a",
                [10.0, 20.0, 1.7],
                covariance=tight,
                viewpoint_id="pose-a",
                viewpoint_kind=ViewpointEvidenceKind.UNKNOWN,
            ),
            _observation(
                "obs-b",
                [10.0, 20.0, 1.7],
                covariance=tight,
                millis=100,
                viewpoint_id="pose-b",
                viewpoint_kind=ViewpointEvidenceKind.UNKNOWN,
            ),
        ]
    )
    assert entity.uncertainty.localization_state == "LIKELY"


def test_mixed_evidence_takes_weakest_grade() -> None:
    """보정 Pose 2곳이 있어도 약한 증거가 하나 섞이면 전체가 최대 LIKELY.

    낙관적 병합 금지 — 강한 증거만 골라 세면 출처 불명 관측이 섞인 융합 결과가
    CONFIRMED 를 얻는다. 등급은 가장 약한 관측을 따른다(분류 신뢰도 min 병합과 동형).
    """
    tight = [0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01]
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7], covariance=tight, viewpoint_id="pose-a"),
            _observation(
                "obs-b", [10.0, 20.0, 1.7], covariance=tight, millis=100, viewpoint_id="pose-b"
            ),
            _observation(
                "obs-c",
                [10.0, 20.0, 1.7],
                covariance=tight,
                millis=200,
                viewpoint_id=viewpoint_bin_id((0.0, 0.0, 30.0)),
                viewpoint_kind=ViewpointEvidenceKind.SPATIAL_BIN,
            ),
        ]
    )
    assert entity.uncertainty.localization_state == "LIKELY"


def test_calibrated_pose_pair_still_reaches_confirmed() -> None:
    """게이트를 조인 뒤에도 정당한 경로는 살아 있다 — 보정 Pose 2곳 + 작은 공분산."""
    tight = [0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01]
    entity = _assemble_ok(
        [
            _observation(
                "obs-a",
                [10.0, 20.0, 1.7],
                covariance=tight,
                viewpoint_id="pose-a",
                viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
            ),
            _observation(
                "obs-b",
                [10.0, 20.0, 1.7],
                covariance=tight,
                millis=100,
                viewpoint_id="pose-b",
                viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
            ),
        ]
    )
    assert entity.uncertainty.localization_state == "CONFIRMED"


def test_bin_id_cannot_be_declared_as_calibrated_pose() -> None:
    """[계약 강제] bin ID를 CALIBRATED_POSE 로 위장 선언하면 계약 계층이 거부한다.

    등급이 자기신고이므로, 우리가 생성 형식을 아는 값(``vpbin:``)에 대해서는 위장을
    기계적으로 막는다 — 이 구멍을 열어두면 게이트가 이름만 남는다.
    """
    with pytest.raises(ValidationError, match="CALIBRATED_POSE"):
        Observation(
            observation_id="obs-a",
            observed_class="Person",
            ontology_version="ksi-ontology-v1",
            observed_at=_BASE_TIME,
            site_frame=_FRAME,
            position=[0.0, 0.0, 0.0],
            position_covariance=list(_ISOTROPIC),
            viewpoint_id=viewpoint_bin_id((0.0, 0.0, 0.0)),
            viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
        )


def test_viewpoint_kind_requires_an_id() -> None:
    """관측점 ID 없이 증거 등급만 주장할 수 없다."""
    with pytest.raises(ValidationError, match="viewpoint_id"):
        Observation(
            observation_id="obs-a",
            observed_class="Person",
            ontology_version="ksi-ontology-v1",
            observed_at=_BASE_TIME,
            site_frame=_FRAME,
            position=[0.0, 0.0, 0.0],
            position_covariance=list(_ISOTROPIC),
            viewpoint_id=None,
            viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
        )


def test_viewpoint_kind_defaults_to_unknown() -> None:
    """필드를 채우지 않으면 UNKNOWN — 권한은 선언해야 얻는다."""
    observation = Observation(
        observation_id="obs-a",
        observed_class="Person",
        ontology_version="ksi-ontology-v1",
        observed_at=_BASE_TIME,
        site_frame=_FRAME,
        position=[0.0, 0.0, 0.0],
        position_covariance=list(_ISOTROPIC),
        viewpoint_id="pose-a",
    )
    assert observation.viewpoint_kind is ViewpointEvidenceKind.UNKNOWN


def test_construct_bypass_still_downgrades_bin_evidence() -> None:
    """[2차 방어선] pydantic 검증을 우회해 위장해도 조립이 등급을 되돌린다.

    ``model_construct`` 는 validator를 건너뛴다. 시점 다양성은 CONFIRMED 의 직접
    근거이므로 단일 검증 지점에 의존하지 않는다.
    """
    tight = [0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01]
    forged = [
        Observation.model_construct(
            observation_id=f"obs-{i}",
            observed_class="Person",
            ontology_version="ksi-ontology-v1",
            track_id="trk-1",
            observed_at=_BASE_TIME + timedelta(milliseconds=i * 100),
            site_frame=_FRAME,
            position=[10.0, 20.0, 1.7],
            position_covariance=tight,
            detection_confidence=0.9,
            geo_confidence=None,
            sensor_id=None,
            viewpoint_id=viewpoint_bin_id(pose),
            viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,  # 위장
            lineage={},
        )
        for i, pose in enumerate([(9.9, 20.0, 30.0), (10.0, 20.0, 30.0)])
    ]
    entity = _assemble_ok(forged)
    assert entity.uncertainty.localization_state == "LIKELY", (
        "검증 우회 객체가 CONFIRMED 를 얻었다 — 조립 단계 2차 방어선이 동작하지 않는다"
    )


def test_construct_bypass_without_class_rejected_typed() -> None:
    """[2차 방어 — 재검토 #11] 검증 우회 객체에 observed_class 가 없어도 예외가 아니라
    typed 거부(MISSING_CLASSIFICATION)다 — "예외를 던지지 않는다" 계약 유지."""
    forged = Observation.model_construct(
        observation_id="obs-forged",
        # observed_class·ontology_version 의도적 누락(model_construct 는 검증 생략)
        track_id="trk-1",
        observed_at=_BASE_TIME,
        site_frame=_FRAME,
        position=[10.0, 20.0, 1.7],
        position_covariance=list(_ISOTROPIC),
        detection_confidence=0.9,
        geo_confidence=None,
        sensor_id=None,
        viewpoint_id="vp-1",
        viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
        lineage={},
    )
    normal = _observation("obs-b", [10.0, 20.0, 1.7], millis=100)
    result = _assemble([forged, normal])
    assert result.status is AssemblyStatus.MISSING_CLASSIFICATION
    assert result.entity is None


def test_unregistered_ontology_version_rejected_even_if_uniform() -> None:
    """[Blocker 4] 미등록 버전은 **전원이 동일해도** 거부 — 혼합 검사만으로는
    "모두가 같은 attacker-v99" 를 통과시킨다. 등록부 검사가 혼합 검사보다 먼저다.

    계약 계층(Observation validator)도 미등록 버전을 거부하므로 여기서는 검증 우회
    객체(model_construct)로 2차 방어(assembly)를 직접 겨눈다.
    """
    forged = [
        Observation.model_construct(
            observation_id=f"obs-{i}",
            observed_class="Person",
            ontology_version="attacker-v99",  # 전원 동일한 미등록 버전
            source_class_id=None,
            source_class_name=None,
            track_id="trk-1",
            observed_at=_BASE_TIME + timedelta(milliseconds=i * 100),
            site_frame=_FRAME,
            position=[10.0, 20.0, 1.7],
            position_covariance=list(_ISOTROPIC),
            detection_confidence=0.9,
            geo_confidence=None,
            sensor_id=None,
            viewpoint_id=f"vp-{i}",
            viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
            lineage={},
        )
        for i in range(2)
    ]
    result = _assemble(forged)
    assert result.status is AssemblyStatus.UNSUPPORTED_ONTOLOGY_VERSION
    assert result.entity is None


# ── 독립 재검토 Blocker 반증 (2026-07-28) ────────────────────────────────────


def test_lineage_conflict_person_from_truck_rejected_at_contract() -> None:
    """[Blocker 1] observed_class="Person" + source="truck" 자기모순은 계약에서 거부."""
    with pytest.raises(ValidationError, match="계보"):
        Observation(
            observation_id="obs-a",
            observed_class="Person",
            source_class_name="truck",
            ontology_version="ksi-ontology-v1",
            observed_at=_BASE_TIME,
            site_frame=_FRAME,
            position=[0.0, 0.0, 0.0],
            position_covariance=list(_ISOTROPIC),
        )


def test_lineage_conflict_bypassed_object_rejected_at_assembly() -> None:
    """[Blocker 1 — 2차 방어] 계약을 우회한 자기모순 객체도 assembly 가 typed 거부."""
    forged = Observation.model_construct(
        observation_id="obs-forged",
        observed_class="Person",
        source_class_name="truck",  # 자기모순 — 검증 우회로 주입
        source_class_id=None,
        ontology_version="ksi-ontology-v1",
        track_id="trk-1",
        observed_at=_BASE_TIME,
        site_frame=_FRAME,
        position=[10.0, 20.0, 1.7],
        position_covariance=list(_ISOTROPIC),
        detection_confidence=0.9,
        geo_confidence=None,
        sensor_id=None,
        viewpoint_id="vp-1",
        viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
        lineage={},
    )
    normal = _observation("obs-b", [10.0, 20.0, 1.7], millis=100)
    result = _assemble([forged, normal])
    assert result.status is AssemblyStatus.CLASSIFICATION_LINEAGE_CONFLICT
    assert result.entity is None


def test_unregistered_version_rejected_at_contract() -> None:
    """[Blocker 4] 미등록 ontology 버전은 계약 시점에 거부된다."""
    with pytest.raises(ValidationError, match="미등록"):
        _observation("obs-a", [0.0, 0.0, 0.0], ontology_version="attacker-v99")


def test_invalid_canonical_bypassed_object_rejected_at_assembly() -> None:
    """[Blocker 2] 등록 Canonical 밖 class 의 우회 객체 → INVALID_CANONICAL_CLASS."""
    forged = Observation.model_construct(
        observation_id="obs-forged",
        observed_class="Worker",  # 등록 집합 밖
        source_class_name=None,
        source_class_id=None,
        ontology_version="ksi-ontology-v1",
        track_id="trk-1",
        observed_at=_BASE_TIME,
        site_frame=_FRAME,
        position=[10.0, 20.0, 1.7],
        position_covariance=list(_ISOTROPIC),
        detection_confidence=0.9,
        geo_confidence=None,
        sensor_id=None,
        viewpoint_id="vp-1",
        viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
        lineage={},
    )
    result = _assemble([forged])
    assert result.status is AssemblyStatus.INVALID_CANONICAL_CLASS


def test_missing_ontology_version_distinct_from_missing_class() -> None:
    """[Blocker 2] 사유 세분화 — class 는 있는데 버전이 없으면 MISSING_ONTOLOGY_VERSION."""
    forged = Observation.model_construct(
        observation_id="obs-forged",
        observed_class="Person",
        # ontology_version 의도적 누락
        source_class_name=None,
        source_class_id=None,
        track_id="trk-1",
        observed_at=_BASE_TIME,
        site_frame=_FRAME,
        position=[10.0, 20.0, 1.7],
        position_covariance=list(_ISOTROPIC),
        detection_confidence=0.9,
        geo_confidence=None,
        sensor_id=None,
        viewpoint_id="vp-1",
        viewpoint_kind=ViewpointEvidenceKind.CALIBRATED_POSE,
        lineage={},
    )
    result = _assemble([forged])
    assert result.status is AssemblyStatus.MISSING_ONTOLOGY_VERSION


def test_entity_lineage_carries_classification_ontology(  # [Blocker 5]
) -> None:
    """Entity 자체에서 "이 Person 은 어느 번역 규칙의 의미인가"를 알 수 있다."""
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7]),
            _observation("obs-b", [10.0, 20.0, 1.7], millis=100),
        ]
    )
    assert entity.lineage.classification_ontology_version == "ksi-ontology-v1"
    assert entity.lineage.classification_source is not None
    assert entity.lineage.classification_source.taxonomy == "COCO-2017"


def test_fingerprint_sensitive_to_ontology_version() -> None:
    """[Blocker 5] fingerprint 는 ontology 버전에 민감하다 — 같은 class 문자열이라도
    번역 규칙이 다르면 다른 Entity 로 판별돼야 한다."""
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7]),
            _observation("obs-b", [10.0, 20.0, 1.7], millis=100),
        ]
    )
    original = world_entity_fingerprint(entity)
    mutated = entity.model_copy(deep=True)
    mutated.lineage.classification_ontology_version = "ksi-ontology-v2-hypothetical"
    assert world_entity_fingerprint(mutated) != original


def test_classification_source_aggregates_observation_lineage() -> None:
    """[Blocker 5 권장] 원시 id·이름이 Entity 계보로 집계된다."""
    obs = [
        Observation(
            observation_id=f"obs-{i}",
            observed_class="Person",
            source_class_id=0,
            source_class_name="person",
            ontology_version="ksi-ontology-v1",
            track_id="trk-1",
            observed_at=_BASE_TIME + timedelta(milliseconds=i * 100),
            site_frame=_FRAME,
            position=[10.0, 20.0, 1.7],
            position_covariance=list(_ISOTROPIC),
            detection_confidence=0.9,
            viewpoint_id=f"vp-{i}",
        )
        for i in range(2)
    ]
    entity = _assemble_ok(obs)
    source = entity.lineage.classification_source
    assert source is not None
    assert source.source_class_ids == [0]
    assert source.source_class_names == ["person"]


def test_ontology_registry_expansion_requires_mismatch_refutation() -> None:
    """[대표자 조건 2026-07-28] 등록부 확장 시 혼합 반증 테스트 동반을 깨지는 형태로 고정.

    ONTOLOGY_VERSION_MISMATCH 경로는 등록 버전이 1개인 동안 도달 불가능한 잠재
    방어다. 두 번째 버전이 등록되는 순간 이 테스트가 실패하며, 그때 해야 할 일:
    ① v1/v2 혼합 track 이 ONTOLOGY_VERSION_MISMATCH 로 거부되는 반증 테스트 추가
    ② 이 테스트의 기대 집합 갱신.
    """
    from ksi_domain.ontology import REGISTERED_ONTOLOGY_VERSIONS

    assert {"ksi-ontology-v1"} == REGISTERED_ONTOLOGY_VERSIONS, (
        "등록부가 확장됐다 — v1/v2 혼합 track 의 ONTOLOGY_VERSION_MISMATCH 반증 "
        "테스트를 추가한 뒤 이 기대 집합을 갱신하라(대표자 조건 2026-07-28)"
    )


def test_fingerprint_sensitive_to_classification_source() -> None:
    """[재검토 확인항목 #2] fingerprint 는 버전뿐 아니라 classificationSource 의
    taxonomy·원시 id·이름 변경에도 민감하다."""
    entity = _assemble_ok(
        [
            _observation("obs-a", [10.0, 20.0, 1.7]),
            _observation("obs-b", [10.0, 20.0, 1.7], millis=100),
        ]
    )
    original = world_entity_fingerprint(entity)
    assert entity.lineage.classification_source is not None

    taxonomy_mutated = entity.model_copy(deep=True)
    assert taxonomy_mutated.lineage.classification_source is not None
    taxonomy_mutated.lineage.classification_source.taxonomy = "OTHER-TAXONOMY"
    assert world_entity_fingerprint(taxonomy_mutated) != original

    ids_mutated = entity.model_copy(deep=True)
    assert ids_mutated.lineage.classification_source is not None
    ids_mutated.lineage.classification_source.source_class_ids = [7]
    assert world_entity_fingerprint(ids_mutated) != original

    names_mutated = entity.model_copy(deep=True)
    assert names_mutated.lineage.classification_source is not None
    names_mutated.lineage.classification_source.source_class_names = ["truck"]
    assert world_entity_fingerprint(names_mutated) != original
