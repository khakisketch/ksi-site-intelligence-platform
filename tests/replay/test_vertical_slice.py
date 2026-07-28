"""최소 Perception Vertical Slice 검증 (Track B).

green≠작동 초점: "슬라이스가 실행됨"이 아니라 **각 단계가 실제로 이어져 있고, 단계
실패가 조용히 삼켜지지 않으며, 같은 입력이 같은 산출물을 내는지** 확인한다.

이 슬라이스가 증명하지 않는 것(모델 정확도·실기 타이밍·연관 정확도)은
``vertical_slice`` 모듈 docstring에 명시돼 있고, 여기서 통과했다고 주장하지 않는다.
"""

from __future__ import annotations

import pytest
from ksi_domain.enums import EventStatus
from ksi_event_contracts.observation import ViewpointEvidenceKind
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet
from vertical_slice import (
    EventBuildStatus,
    MinimalTracker,
    ScriptedDetector,
    SliceFrame,
    SliceStage,
    _event_bundle_from_entity,
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
    )
    shuffled_frames = list(reversed(_frames([0.0, 0.2, 0.4])))
    shuffled = run_vertical_slice(
        frames=shuffled_frames,
        detector=ScriptedDetector(_walking_script(3)),
        telemetry=synthetic_telemetry([0.4, 0.0, 0.2]),
        drone_position=_DRONE_POSE,
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
        detector.detect(0, 0, 1080)


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
    )
    [truck_entity] = result.entities
    built = _event_bundle_from_entity(
        truck_entity,
        severity=Severity.CANDIDATE,
        event_type="PERSON_PRESENT",
        model_version="stub",
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
