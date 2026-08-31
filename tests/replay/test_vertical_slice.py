"""최소 Perception Vertical Slice 검증 (Track B).

green≠작동 초점: "슬라이스가 실행됨"이 아니라 **각 단계가 실제로 이어져 있고, 단계
실패가 조용히 삼켜지지 않으며, 같은 입력이 같은 산출물을 내는지** 확인한다.

이 슬라이스가 증명하지 않는 것(모델 정확도·실기 타이밍·연관 정확도)은
``vertical_slice`` 모듈 docstring에 명시돼 있고, 여기서 통과했다고 주장하지 않는다.
"""

from __future__ import annotations

import pytest
from ksi_domain.detection_adapter import FrameDetectionStatus
from ksi_domain.enums import EventStatus
from ksi_event_contracts.observation import ViewpointEvidenceKind
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet

# private 게이트(_event_bundle_from_entity)는 production 모듈에서 직접 — 픽스처와
# re-export 는 vertical_slice 경유(승격 후 동일 객체임은 identity 테스트가 고정).
from ksi_perception.pipeline import _event_bundle_from_entity
from vertical_slice import (
    EventBuildStatus,
    MinimalTracker,
    ScriptedDetector,
    SliceFrame,
    SliceStage,
    make_run_context,
    person_detection,
    run_vertical_slice,
    synthetic_telemetry,
    truck_detection,
)

_WIDTH, _HEIGHT = 1920, 1080
_DRONE_POSE = (100.0, 200.0, 60.0)


def _frames(timestamps: list[float]) -> list[SliceFrame]:
    return [
        SliceFrame(frame_id=i, capture_ts_utc=ts, width=_WIDTH, height=_HEIGHT)
        for i, ts in enumerate(timestamps)
    ]


def _walking_script(frame_count: int, *, step_px: float = 4.0) -> dict[int, list]:
    """한 사람이 프레임마다 조금씩 이동 — IoU 매칭이 이어지도록 작은 간격."""
    return {
        i: [
            person_detection(
                x_min=900.0 + i * step_px,
                y_min=500.0,
                x_max=980.0 + i * step_px,
                y_max=700.0,
            )
        ]
        for i in range(frame_count)
    }


# ── 전 구간 연결 ──────────────────────────────────────────────────────────────


def test_full_slice_produces_observations_entity_and_bundle() -> None:
    """Frame → … → Evidence Bundle 전 구간이 실제로 이어진다."""
    timestamps = [0.0, 0.2, 0.4]
    result = run_vertical_slice(
        frames=_frames(timestamps),
        detector=ScriptedDetector(_walking_script(3)),
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )

    assert result.dropped == [], f"탈락 없이 통과해야 한다: {result.dropped}"
    assert result.assembly_failures == [], result.assembly_failures
    assert len(result.observations) == 3, "프레임 3장 → 관측 3건"
    assert len(result.entities) == 1, "같은 track → WorldEntity 1개"
    assert len(result.bundles) == 1

    entity = result.entities[0]
    assert entity.lineage.track_id == "trk-001", "3프레임이 같은 track으로 이어져야 한다"
    assert len(entity.lineage.observation_ids or []) == 3
    assert entity.site_frame.startswith("EPSG:")

    bundle = result.bundles[0]
    assert bundle.status is EventStatus.CANDIDATE, "단일 실행이 사건을 확정하지 않는다(INV-022)"
    assert bundle.lineage.model_versions["detector"] == "scripted-stub-0"
    assert bundle.spatial_context["localizationState"] in {
        "CONFIRMED", "LIKELY", "BOUNDARY_UNCERTAIN", "INSUFFICIENT_OBSERVATION",
    }


def test_uncertainty_flows_through_to_bundle() -> None:
    """[INV-020/021] 공분산이 관측 → Entity → Bundle 까지 실제로 전달된다."""
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(_walking_script(2)),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )

    assert len(result.observations) == 2
    for observation in result.observations:
        assert len(observation.position_covariance) == 9
        assert observation.geo_confidence is not None

    covariance = result.bundles[0].spatial_context["positionCovariance"]
    assert len(covariance) == 9
    assert all(isinstance(v, float) for v in covariance)


def test_two_people_become_two_entities() -> None:
    """서로 다른 대상은 서로 다른 track → 서로 다른 WorldEntity."""
    script = {
        i: [
            person_detection(x_min=500.0 + i * 3, y_min=500.0, x_max=580.0 + i * 3, y_max=700.0),
            person_detection(x_min=1200.0 + i * 3, y_min=500.0, x_max=1280.0 + i * 3, y_max=700.0),
        ]
        for i in range(3)
    }
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=ScriptedDetector(script),
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )

    assert len(result.entities) == 2
    track_ids = {e.lineage.track_id for e in result.entities}
    assert len(track_ids) == 2
    # 두 사람의 세계좌표가 달라야 한다(투영이 bbox 차이를 반영하는지).
    positions = {tuple(e.pose.position[:2]) for e in result.entities}
    assert len(positions) == 2


# ── 단계 실패가 조용히 삼켜지지 않는다 ────────────────────────────────────────


def test_interpolation_gap_drops_detection_with_reason() -> None:
    """[INV-023] 텔레메트리 gap 프레임은 외삽 없이 탈락하고 **사유가 기록된다**."""
    result = run_vertical_slice(
        frames=_frames([0.0, 5.0, 10.0]),
        detector=ScriptedDetector(_walking_script(3)),
        telemetry=synthetic_telemetry([0.0, 10.0]),  # 5.0 지점은 gap
        drone_position=_DRONE_POSE,
        context=make_run_context(),
        max_gap_s=0.5,
    )

    dropped_frames = {d.frame_id for d in result.dropped}
    assert 1 in dropped_frames, "gap 프레임이 탈락해야 한다"
    dropped = next(d for d in result.dropped if d.frame_id == 1)
    assert dropped.stage is SliceStage.INTERPOLATION
    assert dropped.reason == "gap_exceeded"
    assert not any(o.observation_id.startswith("obs-0001") for o in result.observations)


def test_projection_failure_drops_detection_with_reason() -> None:
    """투영 실패(지평선 위 광선)도 사유와 함께 탈락한다."""
    horizon_telemetry = [
        TelemetrySample(
            ts=TimestampSet(source_ts_utc=ts, receive_ts_utc=ts, capture_ts_utc=ts),
            drone_lat=37.5,
            drone_lon=127.0,
            altitude_rel_m=60.0,
            heading_deg=0.0,
            # 수직 FOV 반각이 약 27°(FOV 84°, 1920x1080)이므로 +5° 로는 이미지 하단
            # 픽셀이 여전히 지면을 향한다 — 전체 화면이 지평선 위가 되려면 그보다
            # 크게 위를 봐야 한다.
            gimbal_pitch_deg=45.0,
            camera_fov_deg=84.0,
            zoom_factor=1.0,
            rtk_fixed=True,
            source_quality=SourceQuality.FULL,
        )
        for ts in (0.0, 0.2)
    ]
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(_walking_script(2)),
        telemetry=horizon_telemetry,
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )

    assert result.observations == [], "지평선 위 광선에서 좌표를 만들면 안 된다"
    assert len(result.dropped) == 2
    assert all(d.stage is SliceStage.PROJECTION for d in result.dropped)
    assert all(d.reason == "horizon" for d in result.dropped)


def test_no_detections_yields_empty_result_without_error() -> None:
    """탐지가 없으면 조용히 빈 결과 — 예외를 던지지 않는다."""
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector({}),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert result.observations == []
    assert result.entities == []
    assert result.bundles == []
    assert result.dropped == []


def test_single_observation_track_does_not_reach_confirmed() -> None:
    """[PRD §10.9] 관측 1건뿐인 track은 INSUFFICIENT_OBSERVATION 이다."""
    result = run_vertical_slice(
        frames=_frames([0.0]),
        detector=ScriptedDetector(_walking_script(1)),
        telemetry=synthetic_telemetry([0.0]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert len(result.entities) == 1
    assert result.entities[0].uncertainty.localization_state == "INSUFFICIENT_OBSERVATION"


def test_same_viewpoint_frames_do_not_reach_confirmed() -> None:
    """같은 관측점(고정 드론)의 여러 프레임은 CONFIRMED 로 승격되지 않는다.

    이유가 **두 겹**이며, 둘 다 성립해야 한다:

    1. 슬라이스 전체가 같은 ``drone_position`` 을 쓰므로 모든 관측이 같은 viewpoint
       bin에 들어간다 — 시차가 없으므로 다중 시점 증거가 아니다.
    2. 그보다 강하게, 이 슬라이스의 관측점 증거는 ``SPATIAL_BIN`` 이므로 드론이
       움직였더라도 CONFIRMED 에 도달할 수 없다(3차 반증 리뷰 2026-07-27). 격자 경계
       과다계상이 최고 확신 등급을 얻는 경로를 구조적으로 막은 결과다.

    2번을 함께 단정하는 이유: 1번만 확인하면 등급 게이트가 제거돼도 이 테스트는 계속
    통과한다(같은 bin이라 어차피 distinct=1). 게이트가 살아 있음을 직접 고정한다.
    """
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=ScriptedDetector(_walking_script(3)),
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert len(result.entities) == 1
    assert result.entities[0].uncertainty.localization_state != "CONFIRMED", (
        "고정 관측점의 프레임 누적이 CONFIRMED 를 만들면 시점 다양성 게이트가 무력화된 것이다"
    )
    assert result.observations, "관측이 없으면 아래 등급 단정이 공허해진다"
    assert all(
        o.viewpoint_kind is ViewpointEvidenceKind.SPATIAL_BIN for o in result.observations
    ), (
        "슬라이스가 합성 bin 관측점을 CALIBRATED_POSE 로 승격했다 — "
        "실기 pose 경로 없이 최고 확신 등급을 얻는 문이 열린 것이다"
    )


# ── 재현성 ────────────────────────────────────────────────────────────────────


def test_slice_is_deterministic_across_runs() -> None:
    """같은 입력 2회 실행 → 동일 fingerprint(P0-6 규약)."""
    def build_args() -> dict:
        return {
            "frames": _frames([0.0, 0.2, 0.4]),
            "detector": ScriptedDetector(_walking_script(3)),
            "telemetry": synthetic_telemetry([0.0, 0.2, 0.4]),
            "drone_position": _DRONE_POSE,
            "context": make_run_context(),
        }

    first = run_vertical_slice(**build_args())
    second = run_vertical_slice(**build_args())

    assert first.entity_fingerprints() == second.entity_fingerprints()
    assert [o.position for o in first.observations] == [o.position for o in second.observations]


def test_frame_arrival_order_does_not_change_result() -> None:
    """프레임 도착 순서가 뒤섞여도 같은 결과 — capture_ts 로 재정렬하므로."""
    forward = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=ScriptedDetector(_walking_script(3)),
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    shuffled_frames = list(reversed(_frames([0.0, 0.2, 0.4])))
    shuffled = run_vertical_slice(
        frames=shuffled_frames,
        detector=ScriptedDetector(_walking_script(3)),
        telemetry=synthetic_telemetry([0.4, 0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )

    assert forward.entity_fingerprints() == shuffled.entity_fingerprints()


# ── 구성요소 단위 ─────────────────────────────────────────────────────────────


def test_tracker_reuses_id_for_overlapping_boxes() -> None:
    tracker = MinimalTracker()
    first = tracker.assign([person_detection(x_min=100, y_min=100, x_max=200, y_max=300)])
    second = tracker.assign([person_detection(x_min=105, y_min=100, x_max=205, y_max=300)])
    assert first[0][0] == second[0][0]


def test_tracker_assigns_new_id_for_disjoint_boxes() -> None:
    tracker = MinimalTracker()
    first = tracker.assign([person_detection(x_min=100, y_min=100, x_max=200, y_max=300)])
    second = tracker.assign([person_detection(x_min=900, y_min=100, x_max=1000, y_max=300)])
    assert first[0][0] != second[0][0]


def test_tracker_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="iou_threshold"):
        MinimalTracker(iou_threshold=0.0)
    with pytest.raises(ValueError, match="iou_threshold"):
        MinimalTracker(iou_threshold=1.5)


def test_tracker_rejects_invalid_max_missed_frames() -> None:
    with pytest.raises(ValueError, match="max_missed_frames"):
        MinimalTracker(max_missed_frames=0)


def test_tracker_evicts_stale_track_after_missed_frame_budget() -> None:
    """[Eviction] max_missed_frames 를 넘겨 매칭 안 된 track 은 제거되고, 재등장한
    detection 은 옛 track_id 를 재사용하지 않고 새 id 를 받는다(무한 성장 방지 반증
    대응 — _active 가 매칭 안 된 track 을 영원히 들고 있지 않는지 공개 API 로 확인).
    """
    tracker = MinimalTracker(max_missed_frames=1)
    box = {"x_min": 100.0, "y_min": 100.0, "x_max": 200.0, "y_max": 300.0}
    first = tracker.assign([person_detection(**box)])
    tracker.assign([])  # 1회 미매칭 — 아직 유예 범위 내
    tracker.assign([])  # 2회 연속 미매칭 — 유예를 넘겨 제거된다
    reappeared = tracker.assign([person_detection(**box)])
    assert reappeared[0][0] != first[0][0], (
        "제거됐어야 할 track_id 가 재등장한 detection 에 재사용됐다 — 미제거 회귀"
    )


def test_tracker_retains_track_within_missed_frame_budget() -> None:
    """[Eviction 경계] 유예 프레임 수 이내의 짧은 미검출 구간은 track_id 를 유지한다
    — eviction 이 가림·일시 미검출까지 과도하게 끊지 않는지 확인."""
    tracker = MinimalTracker(max_missed_frames=5)
    box = {"x_min": 100.0, "y_min": 100.0, "x_max": 200.0, "y_max": 300.0}
    first = tracker.assign([person_detection(**box)])
    tracker.assign([])
    tracker.assign([])
    reappeared = tracker.assign([person_detection(**box)])
    assert reappeared[0][0] == first[0][0], "유예 범위 내 재등장은 같은 track_id 를 유지해야 한다"


def test_foot_point_is_bottom_center_not_centroid() -> None:
    """접지점은 하단 중앙 — 중심을 쓰면 대상 높이 절반만큼 체계적 오차가 생긴다."""
    detection = person_detection(x_min=100.0, y_min=200.0, x_max=200.0, y_max=600.0)
    assert detection.bbox.foot_point == (150.0, 600.0)


def test_degenerate_bbox_rejected() -> None:
    with pytest.raises(ValueError, match="양의 면적"):
        person_detection(x_min=100.0, y_min=100.0, x_max=100.0, y_max=200.0)


def test_out_of_range_confidence_rejected() -> None:
    with pytest.raises(ValueError, match="confidence"):
        person_detection(x_min=0.0, y_min=0.0, x_max=10.0, y_max=10.0, confidence=1.5)


def test_scripted_detector_rejects_invalid_frame_size() -> None:
    detector = ScriptedDetector({})
    with pytest.raises(ValueError, match="프레임 크기"):
        detector.detect_frame(0, 0, 1080)


# ── 분류 계보 (INV-031, F13 — 3차 반증 리뷰 P0) ──────────────────────────────
#
# 초판 슬라이스는 entity_class="Person" 상수와 event_type="PERSON_PRESENT" 기본
# 인자로 조립·발행했다 — Detector 가 트럭을 탐지해도 Person Entity + PERSON_PRESENT
# Event 가 됐다. 아래가 그 경로들을 전부 닫았음을 고정한다(대표자 수용기준 전건).


def _truck_script(frame_count: int, *, step_px: float = 4.0) -> dict[int, list]:
    return {
        i: [
            truck_detection(
                x_min=900.0 + i * step_px,
                y_min=500.0,
                x_max=1100.0 + i * step_px,
                y_max=700.0,
            )
        ]
        for i in range(frame_count)
    }


def test_truck_never_becomes_person_entity_or_person_event() -> None:
    """[핵심 반증] 트럭 탐지는 Person Entity 도 PERSON_PRESENT Event 도 되지 않는다."""
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=ScriptedDetector(_truck_script(3)),
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert len(result.entities) == 1, "트럭도 WorldEntity 로는 편입된다(세계 모델 유지)"
    assert result.entities[0].entity_class == "Vehicle_Truck", (
        "트럭이 Person Entity 가 됐다 — F13 회귀"
    )
    assert result.bundles == [], "PERSON_PRESENT 등 어떤 Event 도 발행되면 안 된다"
    [(entity_id, entity_class, reason)] = result.unpublished_events
    assert entity_class == "Vehicle_Truck"
    assert "unsupported_event_policy" in reason, "미발행 사유가 typed 로 남아야 한다"


def test_observed_class_flows_from_detection_to_entity() -> None:
    """[정상 경로] person Detection 의 분류 계보가 Observation→Entity 까지 흐른다."""
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=ScriptedDetector(_walking_script(3)),
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert all(o.observed_class == "Person" for o in result.observations)
    assert all(o.source_class_name == "person" for o in result.observations)
    assert all(o.ontology_version == "ksi-ontology-v1" for o in result.observations)
    assert result.entities[0].entity_class == "Person"
    assert len(result.bundles) == 1
    assert result.bundles[0].event_type == "PERSON_PRESENT"
    assert result.unpublished_events == []


def test_class_change_at_same_location_splits_track() -> None:
    """[Tracker 1차 방어] 같은 자리에서 class 가 바뀌면 IoU 와 무관하게 다른 track."""
    tracker = MinimalTracker()
    first = tracker.assign(
        [person_detection(x_min=900.0, y_min=500.0, x_max=980.0, y_max=700.0)]
    )
    second = tracker.assign(
        [truck_detection(x_min=900.0, y_min=500.0, x_max=980.0, y_max=700.0)]
    )
    assert first[0][0] != second[0][0], (
        "동일 위치의 person→truck 이 같은 track 으로 이어졌다 — class 게이트 무력화"
    )


def test_mixed_class_track_rejected_at_assembly() -> None:
    """[Assembly 2차 방어] tracker 를 우회한 class 혼합은 CLASSIFICATION_CONFLICT."""
    from datetime import UTC, datetime, timedelta

    from ksi_event_contracts.assembly import AssemblyStatus, assemble_world_entity
    from ksi_event_contracts.observation import Observation

    def _obs(oid: str, observed_class: str, millis: int) -> Observation:
        return Observation(
            observation_id=oid,
            observed_class=observed_class,
            ontology_version="ksi-ontology-v1",
            track_id="trk-forced",
            observed_at=datetime(2026, 7, 27, 6, 0, 0, tzinfo=UTC) + timedelta(milliseconds=millis),
            site_frame="EPSG:4326+WGS84@slice-1.0.0",
            position=[37.5, 127.0, 0.0],
            position_covariance=[1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0],
            detection_confidence=0.9,
        )

    result = assemble_world_entity(
        [_obs("obs-a", "Person", 0), _obs("obs-b", "Vehicle_Truck", 100)],
        entity_id="ent-forced",
        model_versions={"detector": "stub"},
        calibration_profile_id="cal-1",
    )
    assert result.status is AssemblyStatus.CLASSIFICATION_CONFLICT
    assert result.entity is None, "class 충돌 track 이 Entity 로 확정됐다 — fail-closed 위반"


def test_truck_entity_with_person_event_type_rejected() -> None:
    """[Event/Class compatibility] Truck Entity + PERSON_PRESENT → EVENT_CLASS_MISMATCH."""
    from ksi_domain.enums import Severity

    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(_truck_script(2)),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    [truck_entity] = result.entities
    built = _event_bundle_from_entity(
        truck_entity,
        severity=Severity.CANDIDATE,
        event_type="PERSON_PRESENT",
        context=make_run_context(),
    )
    assert built.status is EventBuildStatus.EVENT_CLASS_MISMATCH
    assert built.bundle is None


def test_misconfigured_policy_blocked_by_compatibility_gate() -> None:
    """정책이 불호환 event type 을 가리켜도 발행 직전 gate 가 끊는다(2중 방어)."""
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(_truck_script(2)),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
        event_policy={"Vehicle_Truck": "PERSON_PRESENT"},  # 잘못된 정책 주입
    )
    assert result.bundles == [], "불호환 정책이 Event 를 발행시켰다 — gate 무력화"
    [(_, _, reason)] = result.unpublished_events
    assert "event_class_mismatch" in reason


def test_unknown_event_type_rejected() -> None:
    """호환표에 없는 event type 은 정책 없는 발행으로 거부된다."""
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(_walking_script(2)),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
        event_policy={"Person": "UNREGISTERED_EVENT"},
    )
    assert result.bundles == []
    [(_, _, reason)] = result.unpublished_events
    assert "unknown_event_type" in reason


def test_two_class_scene_is_deterministic_under_shuffle() -> None:
    """[재현성] person+truck 혼합 장면 — 입력 순서 shuffle 에도 동일 결과."""

    def build(reverse: bool) -> dict:
        script = {
            i: sorted(
                [
                    person_detection(
                        x_min=300.0 + i * 4.0, y_min=500.0, x_max=380.0 + i * 4.0, y_max=700.0
                    ),
                    truck_detection(
                        x_min=1200.0 + i * 4.0, y_min=450.0, x_max=1500.0 + i * 4.0, y_max=700.0
                    ),
                ],
                key=lambda d: d.bbox.x_min,
                reverse=reverse,
            )
            for i in range(3)
        }
        result = run_vertical_slice(
            frames=_frames([0.0, 0.2, 0.4]),
            detector=ScriptedDetector(script),
            telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
            drone_position=_DRONE_POSE,
        context=make_run_context(),
        )
        return {
            "fingerprints": result.entity_fingerprints(),
            "classes": sorted(e.entity_class for e in result.entities),
            "event_types": sorted(b.event_type for b in result.bundles),
            "unpublished": sorted(c for _, c, _ in result.unpublished_events),
        }

    forward, backward = build(False), build(True)
    assert forward == backward
    assert forward["classes"] == ["Person", "Vehicle_Truck"]
    assert forward["event_types"] == ["PERSON_PRESENT"]
    assert forward["unpublished"] == ["Vehicle_Truck"]


def test_partial_key_collision_deterministic_under_reverse() -> None:
    """[Blocker 6] x_min/y_min/x_max/class 가 같고 y_max 만 다른 두 detection —
    입력 순서를 뒤집어도 같은 Track/Entity fingerprint.

    초판 정렬 키는 y_max·confidence 를 빼먹어 이 쌍이 같은 키가 됐고, stable 정렬이
    입력 순서를 보존해 track 라벨이 순서 종속이었다.
    """

    def build(reverse: bool) -> list[str]:
        pair = [
            person_detection(x_min=900.0, y_min=500.0, x_max=980.0, y_max=700.0),
            person_detection(x_min=900.0, y_min=500.0, x_max=980.0, y_max=690.0),
        ]
        script = {0: list(reversed(pair)) if reverse else list(pair)}
        result = run_vertical_slice(
            frames=_frames([0.0]),
            detector=ScriptedDetector(script),
            telemetry=synthetic_telemetry([0.0]),
            drone_position=_DRONE_POSE,
        context=make_run_context(),
        )
        return result.entity_fingerprints()

    assert build(False) == build(True)


def test_detection_contract_rejects_person_from_truck_source() -> None:
    """[Blocker 1] Detection(Person, source=truck) 자기모순은 생성 자체가 거부된다."""
    from ksi_domain.detection import BoundingBox, Detection

    with pytest.raises(ValueError, match="계보"):
        Detection(
            detection_class="Person",
            confidence=0.9,
            bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=10.0, y_max=10.0),
            source_class_name="truck",
        )


def test_detection_contract_rejects_unregistered_ontology_version() -> None:
    """[Blocker 4] 미등록 버전의 Detection 은 생성 자체가 거부된다."""
    from ksi_domain.detection import BoundingBox, Detection

    with pytest.raises(ValueError, match="미등록"):
        Detection(
            detection_class="Person",
            confidence=0.9,
            bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=10.0, y_max=10.0),
            ontology_version="attacker-v99",
        )


# ── B1-7 배선 상시 검증 (반증 리뷰 F-B — CI 에서도 도는 stub 경로) ───────────


def test_detection_stage_drops_absorbed_into_slice() -> None:
    """[F-B 폐쇄] detector 의 typed drop 이 SliceStage.DETECTION 으로 흡수된다.

    실모델 E2E 는 CI 에서 skip 이라, 이 배선(vertical_slice 의 last_dropped 소비)을
    지우면 전 테스트가 green 인 채로 회귀했다(F-B 실험으로 확인). stub 경로에서
    비공허하게 고정한다: 미지원 라벨을 내는 AdapterBackedDetector 를 물리면
    DETECTION 단계 탈락이 프레임별로 정확히 기록돼야 한다.
    """
    from ksi_domain.detection_adapter import (
        AdapterBackedDetector,
        BoxFormat,
        DetectionAdapter,
        RawDetection,
    )
    from ksi_domain.ontology import COCO_ONTOLOGY

    def raw_source(frame_id: int, width: int, height: int) -> list[RawDetection]:
        return [
            # 지원 person 1건(승격) + 미지원 라벨 1건(UNKNOWN_LABEL drop)
            RawDetection(
                label="person",
                score=0.9,
                box=(900.0 + frame_id * 4.0, 500.0, 980.0 + frame_id * 4.0, 700.0),
                source_class_id=0,
            ),
            RawDetection(label="giraffe", score=0.9, box=(100.0, 100.0, 200.0, 200.0)),
        ]

    detector = AdapterBackedDetector(
        raw_source=raw_source,
        adapter=DetectionAdapter(
            box_format=BoxFormat.XYXY, normalized=False, ontology=COCO_ONTOLOGY
        ),
    )
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=detector,
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    detection_drops = [d for d in result.dropped if d.stage is SliceStage.DETECTION]
    assert len(detection_drops) == 2, (
        f"프레임 2장 × 미지원 1건 = DETECTION 탈락 2건이어야 한다 (실제 {len(detection_drops)}) "
        "— 배선이 제거되면 여기가 깨진다"
    )
    assert {d.frame_id for d in detection_drops} == {0, 1}, "프레임별 기록이 아니다"
    assert all("unknown_label" in d.reason for d in detection_drops)
    assert all(d.track_id == "(pre-track)" for d in detection_drops)
    # 승격된 person 은 정상 흐름 유지
    assert len(result.entities) == 1
    assert result.entities[0].entity_class == "Person"


def test_clipped_detections_absorbed_into_slice() -> None:
    """[F-E 폐쇄] 살아남은 경계 클리핑 기록도 슬라이스에 보존된다(접지점 편향 가시성)."""
    from ksi_domain.detection_adapter import (
        AdapterBackedDetector,
        BoxFormat,
        DetectionAdapter,
        RawDetection,
    )
    from ksi_domain.ontology import COCO_ONTOLOGY

    def raw_source(frame_id: int, width: int, height: int) -> list[RawDetection]:
        # 왼쪽 경계를 살짝 벗어나 클리핑되지만 잔존 면적비 > 0.5 로 살아남는 person
        return [
            RawDetection(
                label="person", score=0.9, box=(-20.0, 500.0, 60.0, 700.0), source_class_id=0
            )
        ]

    detector = AdapterBackedDetector(
        raw_source=raw_source,
        adapter=DetectionAdapter(
            box_format=BoxFormat.XYXY, normalized=False, ontology=COCO_ONTOLOGY
        ),
    )
    result = run_vertical_slice(
        frames=_frames([0.0]),
        detector=detector,
        telemetry=synthetic_telemetry([0.0]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert len(result.clipped_detections) == 1, "클리핑 기록이 슬라이스에서 소실됐다"
    frame_id, area_kept, detail = result.clipped_detections[0]
    assert frame_id == 0
    assert 0.5 <= area_kept < 1.0
    assert "Person" in detail


# ── Frame typed outcome 경계 (slice-inference-exception-channel 폐쇄) ────────


def test_mid_frame_inference_failure_does_not_kill_batch() -> None:
    """[핵심] 프레임 1장의 추론 실패가 배치 전체를 죽이지 않는다.

    frame 0 성공 → frame 1 INFERENCE_FAILED(typed 기록) → frame 2 성공. 실패
    기록에는 frame_id·capture 시각·모델 계보가 보존된다.
    """
    detector = ScriptedDetector(
        _walking_script(3), fail_frames={1: "synthetic: CUDA error (주입 실패)"}
    )
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=detector,
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert len(result.observations) == 2, "frame 0·2 는 계속 처리돼야 한다"
    [failure] = result.frame_failures
    assert failure.frame_id == 1
    assert failure.capture_ts_utc == 0.2
    assert failure.status is FrameDetectionStatus.INFERENCE_FAILED
    assert failure.detail is not None and "주입 실패" in failure.detail
    assert failure.model_version == "scripted-stub-0", "실패 기록에도 모델 계보가 남아야 한다"
    # 살아남은 두 프레임은 같은 track 으로 이어지고 이벤트도 발행된다.
    assert len(result.entities) == 1
    assert len(result.entities[0].lineage.observation_ids or []) == 2
    assert len(result.bundles) == 1


def test_missing_frame_is_frame_not_found_not_empty_scene() -> None:
    """[핵심] 없는 frame_id 는 빈 장면이 아니다 — 소스 결손의 무사고 위장 금지."""
    detector = ScriptedDetector(_walking_script(1), known_frames={0, 2})
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=detector,
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    [failure] = result.frame_failures
    assert failure.frame_id == 1
    assert failure.status is FrameDetectionStatus.FRAME_NOT_FOUND

    # 대조군: 소스에 있는 프레임의 탐지 0건은 실패가 아니라 정상 빈 장면이다.
    clean = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=ScriptedDetector(_walking_script(1), known_frames={0, 1, 2}),
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert clean.frame_failures == [], "빈 장면이 FRAME_NOT_FOUND 로 위장 실패했다"


def test_first_frame_drops_do_not_bleed_into_later_frames() -> None:
    """[진단 격리] frame 0 에서만 나온 탈락이 뒤 프레임 기록으로 새지 않는다."""
    from ksi_domain.detection_adapter import (
        AdapterBackedDetector,
        BoxFormat,
        DetectionAdapter,
        RawDetection,
    )
    from ksi_domain.ontology import COCO_ONTOLOGY

    def raw_source(frame_id: int, width: int, height: int) -> list[RawDetection]:
        if frame_id == 0:
            return [
                RawDetection(label="giraffe", score=0.9, box=(100.0, 100.0, 200.0, 200.0)),
                # 살아남는 클리핑 1건 — clipped 채널의 격리도 함께 본다.
                RawDetection(
                    label="person", score=0.9, box=(-20.0, 500.0, 60.0, 700.0), source_class_id=0
                ),
            ]
        return [
            RawDetection(
                label="person",
                score=0.9,
                box=(900.0 + frame_id * 4.0, 500.0, 980.0 + frame_id * 4.0, 700.0),
                source_class_id=0,
            )
        ]

    detector = AdapterBackedDetector(
        raw_source=raw_source,
        adapter=DetectionAdapter(
            box_format=BoxFormat.XYXY, normalized=False, ontology=COCO_ONTOLOGY
        ),
    )
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2, 0.4]),
        detector=detector,
        telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    detection_drops = [d for d in result.dropped if d.stage is SliceStage.DETECTION]
    assert [d.frame_id for d in detection_drops] == [0], (
        f"frame 0 의 탈락이 다른 프레임 기록으로 샜다: {detection_drops}"
    )
    assert [f for f, _, _ in result.clipped_detections] == [0], "clipped 채널 격리 실패"


def test_out_of_order_frames_keep_per_frame_diagnostics() -> None:
    """[진단 격리] 입력 순서를 뒤섞어도 frame별 진단·실패 귀속이 교차하지 않는다."""
    def build(frames_order: list[float]) -> object:
        return run_vertical_slice(
            frames=[
                SliceFrame(
                    frame_id=int(ts / 0.2), capture_ts_utc=ts, width=_WIDTH, height=_HEIGHT
                )
                for ts in frames_order
            ],
            detector=ScriptedDetector(
                _walking_script(3), fail_frames={2: "동일 주입 실패"}
            ),
            telemetry=synthetic_telemetry([0.0, 0.2, 0.4]),
            drone_position=_DRONE_POSE,
        context=make_run_context(),
        )

    forward = build([0.0, 0.2, 0.4])
    shuffled = build([0.4, 0.0, 0.2])
    assert [f.frame_id for f in forward.frame_failures] == [2]  # type: ignore[attr-defined]
    assert [
        (f.frame_id, f.status, f.capture_ts_utc) for f in forward.frame_failures  # type: ignore[attr-defined]
    ] == [
        (f.frame_id, f.status, f.capture_ts_utc) for f in shuffled.frame_failures  # type: ignore[attr-defined]
    ]
    assert forward.entity_fingerprints() == shuffled.entity_fingerprints()  # type: ignore[attr-defined]


# ── EventBundle standalone classification lineage (v1.2, INV-031) ────────────


def test_bundle_carries_standalone_classification_lineage() -> None:
    """정상 경로: bundle 이 entity 없이도 검증 가능한 분류 계보를 들고 다닌다."""
    from ksi_event_contracts.assembly import world_entity_fingerprint

    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(_walking_script(2)),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    [bundle] = result.bundles
    [entity] = result.entities
    lineage = bundle.lineage.classification[entity.entity_id]
    assert lineage.entity_class == "Person"
    assert lineage.ontology_version == "ksi-ontology-v1"
    assert "person" in lineage.source.source_class_names
    assert lineage.entity_fingerprint == world_entity_fingerprint(entity), (
        "fingerprint 는 world_entity_fingerprint 재계산과 일치해야 한다(검증 규칙)"
    )


def test_entity_without_classification_lineage_cannot_publish_event() -> None:
    """[assembly gate] 분류 계보가 빈 entity 는 이벤트가 되지 못한다(typed 거부)."""
    from datetime import UTC, datetime

    from ksi_domain.enums import Severity
    from ksi_event_contracts.world_entity import (
        EntityLineage,
        Pose,
        Uncertainty,
        WorldEntity,
    )
    from ksi_perception.pipeline import _event_bundle_from_entity

    bare = WorldEntity(
        entity_id="ent-bare",
        entity_class="Person",  # type: ignore[call-arg]
        timestamp=datetime(2026, 7, 27, 6, 0, 0, tzinfo=UTC),
        site_frame="EPSG:4326+WGS84@slice-1.0.0",
        pose=Pose(position=[37.5, 127.0, 0.0]),
        uncertainty=Uncertainty(position_covariance=[1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]),
        lineage=EntityLineage(
            track_id="trk-001",
            model_versions={"detector": "stub"},
            calibration_profile_id="cal-0",
            # classification_ontology_version / classification_source 부재 —
            # v1.1 산출물(후방 호환 Optional)이 이벤트로 흐르려는 상황.
        ),
    )
    built = _event_bundle_from_entity(
        bare, severity=Severity.CANDIDATE, event_type="PERSON_PRESENT",
        context=make_run_context(model_version="stub"),
    )
    assert not built.ok and built.bundle is None
    assert built.status is EventBuildStatus.MISSING_CLASSIFICATION_LINEAGE


def test_entity_with_empty_raw_classification_lineage_rejected_typed_not_raised() -> None:
    """[W4 Part A, P1] '계보 없음'은 키 부재만이 아니다 — 원시 id/이름이 형식상

    존재하되 실질적으로 빈 경우도 같은 typed MISSING_CLASSIFICATION_LINEAGE 로
    거부돼야 한다. 이전에는 ontology_version/classification_source 가 채워져
    있으면(키 존재) 이 사전 게이트를 통과해버려, v1.2 ``ClassificationLineage`` 의
    ``_source_nonempty`` model_validator 가 던지는 ``ValidationError`` 가 함수 밖으로
    그대로 새어나갔다("예외를 던지지 않는다" 계약 위반).
    """
    from datetime import UTC, datetime

    from ksi_domain.enums import Severity
    from ksi_event_contracts.world_entity import (
        ClassificationSource,
        EntityLineage,
        Pose,
        Uncertainty,
        WorldEntity,
    )
    from ksi_perception.pipeline import _event_bundle_from_entity

    empty_source_entity = WorldEntity(
        entity_id="ent-empty-source",
        entity_class="Person",  # type: ignore[call-arg]
        timestamp=datetime(2026, 7, 27, 6, 0, 0, tzinfo=UTC),
        site_frame="EPSG:4326+WGS84@slice-1.0.0",
        pose=Pose(position=[37.5, 127.0, 0.0]),
        uncertainty=Uncertainty(position_covariance=[1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]),
        lineage=EntityLineage(
            track_id="trk-002",
            model_versions={"detector": "stub"},
            calibration_profile_id="cal-0",
            classification_ontology_version="ksi-ontology-v1",
            # 키는 존재(None 아님)하지만 원시 id/이름이 비어 있다 — WorldEntity
            # 계층(ClassificationSource)은 이를 구조적으로 합법 취급한다(P1 구멍).
            classification_source=ClassificationSource(
                taxonomy="COCO-2017", source_class_ids=[], source_class_names=[]
            ),
        ),
    )
    built = _event_bundle_from_entity(
        empty_source_entity,
        severity=Severity.CANDIDATE,
        event_type="PERSON_PRESENT",
        context=make_run_context(model_version="stub"),
    )
    assert not built.ok and built.bundle is None
    assert built.status is EventBuildStatus.MISSING_CLASSIFICATION_LINEAGE


def test_empty_raw_classification_lineage_does_not_kill_batch() -> None:
    """[W4 Part A, P1] 원시 계보가 빈 entity 가 배치에 섞여도 run_vertical_slice 는

    예외 없이 완주하고, 그 track 만 typed 사유로 미발행되며, 나머지 유효 track 은
    계속 처리돼 Event 를 발행한다(수정 전에는 ValidationError 전파로 이 호출
    자체가 배치 전체를 죽였다).
    """
    from ksi_domain.detection import BoundingBox, Detection

    def _bare_person(
        *, x_min: float, y_min: float, x_max: float, y_max: float
    ) -> Detection:
        # source_class_id/source_class_name 을 주지 않는다 — Detection/Observation/
        # assembly 모두 이 조합을 합법으로 허용한다(원시 계보 부재는 canonical
        # 분류 부재와 다르다).
        return Detection(
            detection_class="Person",
            confidence=0.9,
            bbox=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
        )

    script = {
        i: [
            _bare_person(
                x_min=100.0 + i * 4.0, y_min=100.0, x_max=180.0 + i * 4.0, y_max=300.0
            ),
            person_detection(
                x_min=900.0 + i * 4.0, y_min=500.0, x_max=980.0 + i * 4.0, y_max=700.0
            ),
        ]
        for i in range(2)
    }
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(script),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
    )
    assert len(result.entities) == 2, (
        "두 track 모두 Entity 로 조립돼야 한다 — assembly 는 canonical class/ontology"
        " 만 요구하고 원시 id/이름 부재는 거부하지 않는다"
    )
    assert len(result.bundles) == 1, "원시 계보가 있는 track 만 Event 를 발행해야 한다"
    reasons = [reason for (_, _, reason) in result.unpublished_events]
    assert any("missing_classification_lineage" in r for r in reasons), reasons


# ── OFFLINE REPLAY MODULE — 복사본 부재 앵커 ────────────────────────────────


def test_orchestration_is_shared_offline_module_not_a_copy() -> None:
    """Replay 하네스는 package의 offline pipeline **동일 객체**를 쓴다.

    tests/replay에 orchestration 복사본이 다시 생기면 CLI와 test가 서로 다른 배선을
    검증하므로 identity 비교가 즉시 깨진다. 이는 production 승격 주장이 아니다.
    """
    import vertical_slice
    from ksi_perception import pipeline

    assert vertical_slice.run_vertical_slice is pipeline.run_vertical_slice
    assert vertical_slice.MinimalTracker is pipeline.MinimalTracker
    assert vertical_slice.SliceFrame is pipeline.SliceFrame
    assert vertical_slice.SliceResult is pipeline.SliceResult
    assert vertical_slice.SliceStage is pipeline.SliceStage
    assert vertical_slice.DroppedDetection is pipeline.DroppedDetection
    assert vertical_slice.EventBuildStatus is pipeline.EventBuildStatus


# ── RunContext·Evidence Clip 정책 (감사 #23·#26·#37 폐쇄) ────────────────────


def test_run_context_rejects_blank_lineage() -> None:
    """계보 필드 공백은 생성 시점 typed 거부 — placeholder 실행 자체가 불가하다."""
    from datetime import UTC, datetime
    from typing import Any

    from vertical_slice import RunContext

    good: dict[str, Any] = dict(
        mission_id="m", site_id="s", site_frame="EPSG:4326+WGS84@t",
        epoch_utc=datetime(2026, 1, 1, tzinfo=UTC), model_version="v",
        policy_version="p", calibration_profile_id="c", edge_version="e",
        sensor_id="cam",
    )
    RunContext(**good)  # 정상 경로
    for field_name in good:
        if field_name == "epoch_utc":
            continue
        broken = dict(good)
        broken[field_name] = "   "
        with pytest.raises(ValueError, match=field_name):
            RunContext(**broken)
    naive = dict(good)
    naive["epoch_utc"] = datetime(2026, 1, 1)  # tz 없음
    with pytest.raises(ValueError, match="UTC"):
        RunContext(**naive)


def test_evidence_clip_policy_is_three_tier() -> None:
    """[INV-030] CANDIDATE/HIGH/CRITICAL = 3/5/10초 — 초판은 2단계라 CRITICAL 이
    절반(5초) 클립을 받았다(감사 #26·#37)."""
    from ksi_domain.enums import Severity

    expectations = {Severity.CANDIDATE: 3.0, Severity.HIGH: 5.0, Severity.CRITICAL: 10.0}
    for severity, seconds in expectations.items():
        result = run_vertical_slice(
            frames=_frames([0.0, 0.2]),
            detector=ScriptedDetector(_walking_script(2)),
            telemetry=synthetic_telemetry([0.0, 0.2]),
            drone_position=_DRONE_POSE,
            context=make_run_context(),
            severity=severity,
        )
        [bundle] = result.bundles
        assert bundle.evidence.clip_policy is not None
        assert bundle.evidence.clip_policy.pre_seconds == seconds, severity
        assert bundle.evidence.clip_policy.post_seconds == seconds, severity


def test_medium_severity_has_no_clip_policy_and_is_rejected() -> None:
    """MEDIUM 은 클립 정책 미정의 — 임의 길이를 지어내지 않고 typed 거부한다."""
    from ksi_domain.enums import Severity

    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(_walking_script(2)),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=make_run_context(),
        severity=Severity.MEDIUM,
    )
    assert result.bundles == [], "정책 없는 severity 로 Evidence 가 발행됐다"
    [(entity_id, _cls, reason)] = result.unpublished_events
    assert "unsupported_severity_policy" in reason


def test_bundle_lineage_carries_run_context_not_placeholders() -> None:
    """산출물 계보가 호출자의 RunContext 값이다 — 하드코딩 placeholder 아님."""
    context = make_run_context()
    result = run_vertical_slice(
        frames=_frames([0.0, 0.2]),
        detector=ScriptedDetector(_walking_script(2)),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=_DRONE_POSE,
        context=context,
    )
    [bundle] = result.bundles
    assert bundle.mission_id == context.mission_id
    assert bundle.site_id == context.site_id
    assert bundle.lineage.policy_version == context.policy_version
    assert bundle.lineage.calibration_profile_id == context.calibration_profile_id
    assert bundle.lineage.edge_version == context.edge_version
    [observation] = [o for o in result.observations if o.observation_id.endswith("trk-001")][:1]
    assert observation.site_frame == context.site_frame
    assert observation.sensor_id == context.sensor_id
