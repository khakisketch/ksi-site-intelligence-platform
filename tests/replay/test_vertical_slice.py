"""최소 Perception Vertical Slice 검증 (Track B).

green≠작동 초점: "슬라이스가 실행됨"이 아니라 **각 단계가 실제로 이어져 있고, 단계
실패가 조용히 삼켜지지 않으며, 같은 입력이 같은 산출물을 내는지** 확인한다.

이 슬라이스가 증명하지 않는 것(모델 정확도·실기 타이밍·연관 정확도)은
``vertical_slice`` 모듈 docstring에 명시돼 있고, 여기서 통과했다고 주장하지 않는다.
"""

from __future__ import annotations

import pytest
from ksi_domain.enums import EventStatus
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet
from vertical_slice import (
    MinimalTracker,
    ScriptedDetector,
    SliceFrame,
    SliceStage,
    person_detection,
    run_vertical_slice,
    synthetic_telemetry,
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

    슬라이스 전체가 같은 ``drone_position`` 을 쓰므로 모든 관측이 같은 viewpoint bin에
    들어간다 — 시차가 없으므로 다중 시점 증거가 아니다.
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
