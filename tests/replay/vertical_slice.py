"""최소 Perception Vertical Slice (Track B).

독립 검토(2026-07-27)가 승인한 첫 vertical slice 전 구간을 하나로 연결한다:

    Recorded/Synthetic Frame
      → Detection            (ksi_domain.detection — 인터페이스 + 결정적 stub)
      → Tracking             (이 모듈, IoU 기반 최소 구현)
      → Telemetry Interpolation  (ksi_geo_core.sync — P0-2)
      → Geo Projection       (ksi_geo_core.projection — P0-4)
      → Observation          (ksi_event_contracts.observation — Stage C-1)
      → WorldEntity Fusion   (ksi_event_contracts.assembly — P1-1/P1-2)
      → Event Candidate      (ksi_domain.enums 상태전이 — P0-1)
      → Evidence Bundle      (ksi_event_contracts.event_bundle — P0-1)

## 왜 실제 비행 없이 먼저 완성하는가

Frame source만 나중에 PSDK Live View로 교체하면 되는 구조로 만든다. 그러면 모델 문제·
Geo 문제·PSDK 문제를 한꺼번에 디버깅하지 않아도 된다 — 실기에서 결과가 틀렸을 때
"어느 계층인가"를 이미 아는 상태로 들어갈 수 있다.

## 이 슬라이스가 증명하는 것 / 아닌 것

**증명한다:** 배선이 실제로 이어져 있고, 각 단계의 실패가 조용히 삼켜지지 않으며,
같은 입력이 같은 산출물을 낸다.

**증명하지 않는다:** 모델 정확도(stub이다), 실기 타이밍(합성 텔레메트리다), 연관
정확도(IoU 최소 구현이다). 각각은 별개 검증 대상이며 여기서 통과했다고 주장하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ksi_domain.detection import BoundingBox, Detection, Detector
from ksi_domain.enums import EventStatus, Severity, assert_event_transition
from ksi_event_contracts.assembly import (
    AssemblyStatus,
    assemble_world_entity,
    world_entity_fingerprint,
)
from ksi_event_contracts.event_bundle import EventBundle, Evidence, Lineage
from ksi_event_contracts.observation import (
    Observation,
    ViewpointEvidenceKind,
    viewpoint_bin_id,
)
from ksi_event_contracts.world_entity import WorldEntity
from ksi_geo_core.projection import project_foot_point
from ksi_geo_core.sync import SourceQuality, TelemetryInterpolator, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet

_EPOCH = datetime(2026, 7, 27, 6, 0, 0, tzinfo=UTC)


class ScriptedDetector(Detector):
    """결정적 stub Detector — 프레임별 bbox를 스크립트로 지정한다.

    모델을 도입하지 않는 이유는 ``ksi_domain.detection`` 모듈 docstring 참고
    (Ultralytics BLOCKED_LICENSE, 배선과 모델 정확도를 분리해 디버깅).

    실제 Detector로 교체할 때 이 클래스만 바뀌고 파이프라인은 그대로다.
    """

    def __init__(self, script: dict[int, list[Detection]]) -> None:
        self._script = script

    def detect(self, frame_id: int, width: int, height: int) -> list[Detection]:
        if width <= 0 or height <= 0:
            raise ValueError(f"프레임 크기는 양수여야 한다 ({width}x{height})")
        return list(self._script.get(frame_id, []))


@dataclass(frozen=True, slots=True)
class SliceFrame:
    """재생 프레임 1장 — 실제 이미지 대신 메타데이터만 담는다.

    PSDK Live View로 교체할 때 이 구조에 실제 프레임 버퍼 참조가 추가되며, 파이프라인의
    나머지는 bbox·시각·크기만 쓰므로 변경되지 않는다.
    """

    frame_id: int
    capture_ts_utc: float
    width: int
    height: int


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    """두 bbox의 IoU. 겹치지 않으면 0."""
    overlap_x = max(0.0, min(a.x_max, b.x_max) - max(a.x_min, b.x_min))
    overlap_y = max(0.0, min(a.y_max, b.y_max) - max(a.y_min, b.y_min))
    intersection = overlap_x * overlap_y
    if intersection <= 0.0:
        return 0.0
    area_a = (a.x_max - a.x_min) * (a.y_max - a.y_min)
    area_b = (b.x_max - b.x_min) * (b.y_max - b.y_min)
    return intersection / (area_a + area_b - intersection)


class MinimalTracker:
    """IoU + class 기반 최소 tracker — 프레임 간 같은 대상에 같은 track_id 를 준다.

    **범위 명시:** Scout 감사가 중심점 greedy 연관을 REPLACE로 판정했듯, 이 구현도
    최종본이 아니다(가림·밀집·미검출 구간에 약하다). vertical slice의 목적은 "track_id
    가 파이프라인을 타고 흐르는지" 확인이며, 확률적 다특징 연관은 이후 단계다.

    **class-aware (INV-031 1차 방어, F13):** IoU 가 충분해도 canonical class 가
    다르면 연관하지 않는다 — 같은 자리에서 person 이 truck 으로 바뀌면 그것은 같은
    대상이 아니라 다른 대상(또는 오분류)이며, 한 track 으로 묶으면 class 충돌이
    hidden 연관 오류로 세계 모델에 들어간다. tracker 를 우회한 혼합은 assembly 의
    CLASSIFICATION_CONFLICT(2차 방어)가 잡는다.

    결정적이다 — 같은 입력 순서에 같은 track_id 를 배정한다(재현성).
    """

    def __init__(self, *, iou_threshold: float = 0.3) -> None:
        if not (0.0 < iou_threshold <= 1.0):
            raise ValueError(f"iou_threshold 는 (0,1] 범위여야 한다 ({iou_threshold!r})")
        self._iou_threshold = iou_threshold
        self._next_id = 1
        self._active: dict[str, tuple[BoundingBox, str]] = {}  # track → (bbox, class)

    def assign(self, detections: list[Detection]) -> list[tuple[str, Detection]]:
        """탐지 목록에 track_id 를 배정한다. 입력 순서대로 그리디 매칭."""
        assigned: list[tuple[str, Detection]] = []
        claimed: set[str] = set()
        for detection in detections:
            best_id: str | None = None
            best_iou = 0.0
            for track_id, (previous_bbox, previous_class) in self._active.items():
                if track_id in claimed:
                    continue
                if previous_class != detection.detection_class:
                    continue  # class 불일치 — IoU 와 무관하게 다른 track
                score = _iou(previous_bbox, detection.bbox)
                if score >= self._iou_threshold and score > best_iou:
                    best_id, best_iou = track_id, score
            if best_id is None:
                best_id = f"trk-{self._next_id:03d}"
                self._next_id += 1
            claimed.add(best_id)
            self._active[best_id] = (detection.bbox, detection.detection_class)
            assigned.append((best_id, detection))
        return assigned


class SliceStage(StrEnum):
    """어느 단계에서 프레임이 탈락했는지 — 조용히 사라지지 않게 기록한다."""

    DETECTION = "detection"  # adapter 의 typed drop(라벨·계보·클리핑·score)
    INTERPOLATION = "interpolation"
    PROJECTION = "projection"


@dataclass(frozen=True, slots=True)
class DroppedDetection:
    frame_id: int
    track_id: str
    stage: SliceStage
    reason: str


@dataclass
class SliceResult:
    """슬라이스 실행 결과 — 각 단계 산출물과 탈락 이유를 모두 보존한다."""

    observations: list[Observation] = field(default_factory=list)
    dropped: list[DroppedDetection] = field(default_factory=list)
    entities: list[WorldEntity] = field(default_factory=list)
    bundles: list[EventBundle] = field(default_factory=list)
    assembly_failures: list[tuple[str, AssemblyStatus, str | None]] = field(default_factory=list)
    # Entity 는 생성됐지만 Event 가 발행되지 않은 건 — (entity_id, entity_class, 사유).
    # Solution Pack 이 지원하지 않는 class 는 Event 미발행이 정상 경로다(조용한 소멸 금지).
    unpublished_events: list[tuple[str, str, str]] = field(default_factory=list)
    # 살아남았지만 경계 클리핑된 detection — (frame_id, 잔존 면적비, 상세).
    # 클리핑은 접지점을 잘린 방향으로 이동시키므로(위치 편향) 사실을 산출물에
    # 보존한다(반증 리뷰 F-E — drop 채널만 절반 배선하지 않는다).
    clipped_detections: list[tuple[int, float, str]] = field(default_factory=list)

    def entity_fingerprints(self) -> list[str]:
        """재현성 비교용 — entity_id 를 제외한 내용 기반 지문(P0-6 규약)."""
        return sorted(world_entity_fingerprint(e) for e in self.entities)


def _observation_from_projection(
    *,
    frame: SliceFrame,
    track_id: str,
    detection: Detection,
    lat: float,
    lon: float,
    altitude_m: float,
    geo_confidence: float,
    error_radius_m: float,
    drone_position: tuple[float, float, float],
    model_version: str,
) -> Observation:
    """투영 결과 → Observation 계약.

    공분산은 오차반경을 등방 표준편차로 해석해 구성한다 — 실제 covariance 전파는
    Phase 2+ 대상이며, 여기서는 "불확실성이 계약을 타고 흐른다"만 보인다(그 사실을
    숨기지 않기 위해 이 주석을 남긴다).

    관측점은 아직 보정된 카메라 Pose가 아니라 이산 bin 폴백이므로 증거 등급을
    ``SPATIAL_BIN`` 으로 **명시 선언**한다. 그 결과 이 슬라이스가 만드는 Entity는
    구조적으로 ``CONFIRMED`` 에 도달할 수 없다 — 실기 Pose 경로가 붙기 전까지
    합성 입력이 최고 확신 등급을 만들어내면 안 된다.
    """
    variance = error_radius_m**2
    return Observation(
        observation_id=f"obs-{frame.frame_id:04d}-{track_id}",
        # 분류 계보(INV-031, F13) — Detection 의 canonical class 와 원시 라벨·ontology
        # 버전이 Observation 을 타고 흐른다. 상수로 덮어쓰지 않는다.
        observed_class=detection.detection_class,
        source_class_id=detection.source_class_id,
        source_class_name=detection.source_class_name,
        ontology_version=detection.ontology_version,
        track_id=track_id,
        observed_at=_EPOCH + timedelta(seconds=frame.capture_ts_utc),
        site_frame="EPSG:4326+WGS84@slice-1.0.0",
        position=[lat, lon, altitude_m],
        position_covariance=[variance, 0.0, 0.0, 0.0, variance, 0.0, 0.0, 0.0, variance],
        detection_confidence=detection.confidence,
        geo_confidence=geo_confidence,
        sensor_id="slice-wide-camera",
        viewpoint_id=viewpoint_bin_id(drone_position),
        viewpoint_kind=ViewpointEvidenceKind.SPATIAL_BIN,
        lineage={"detector": model_version},
    )


# Event Type 별 호환 Entity Class (INV-031 — Event 는 Entity class 와 호환될 때만).
# 슬라이스 수준의 최소 정책이다 — 실제 Solution Pack 정책은 Core 소유(Phase 2+).
EVENT_TYPE_COMPATIBLE_CLASSES: dict[str, frozenset[str]] = {
    "PERSON_PRESENT": frozenset({"Person"}),
}

# Entity Class → 발행할 Event Type. 여기 없는 class 는 Entity 는 유지하되 Event 를
# 발행하지 않는다(unpublished_events 에 typed 사유 기록 — 조용한 소멸 금지).
DEFAULT_EVENT_POLICY: dict[str, str] = {"Person": "PERSON_PRESENT"}


class EventBuildStatus(StrEnum):
    OK = "ok"
    EVENT_CLASS_MISMATCH = "event_class_mismatch"  # event_type 이 entity class 와 불호환
    UNKNOWN_EVENT_TYPE = "unknown_event_type"  # 호환표에 없는 event_type


@dataclass(frozen=True, slots=True)
class EventBuildResult:
    status: EventBuildStatus
    bundle: EventBundle | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is EventBuildStatus.OK


def _event_bundle_from_entity(
    entity: WorldEntity,
    *,
    severity: Severity,
    event_type: str,
    model_version: str,
) -> EventBuildResult:
    """WorldEntity → EventBundle. 상태전이는 반드시 전이표를 경유한다(INV-031).

    **Event/Class compatibility gate (F13):** event_type 이 entity 의 class 와
    호환되지 않으면 EventBundle 을 만들지 않고 typed 로 거부한다 — Truck Entity 에
    PERSON_PRESENT 를 요청하는 호출은 코드 어디서 오든 여기서 끊긴다.

    Detection 에서 곧바로 CONFIRMED 로 가지 않고 OBSERVATION → CANDIDATE 를 밟는다 —
    단일 슬라이스 실행이 사건을 확정하지 않는다(INV-022).
    """
    compatible = EVENT_TYPE_COMPATIBLE_CLASSES.get(event_type)
    if compatible is None:
        return EventBuildResult(
            status=EventBuildStatus.UNKNOWN_EVENT_TYPE,
            detail=f"event_type {event_type!r} 는 호환표에 없다 — 정책 없는 이벤트 발행 금지",
        )
    if entity.entity_class not in compatible:
        return EventBuildResult(
            status=EventBuildStatus.EVENT_CLASS_MISMATCH,
            detail=(
                f"event_type {event_type!r} 는 entity class {entity.entity_class!r} 와 "
                f"불호환(허용: {sorted(compatible)}) — Event 를 생성하지 않는다(INV-031)"
            ),
        )

    assert_event_transition(None, EventStatus.OBSERVATION)
    assert_event_transition(EventStatus.OBSERVATION, EventStatus.CANDIDATE)

    clip_seconds = 3.0 if severity is Severity.CANDIDATE else 5.0
    bundle = EventBundle(
        event_id=f"evt-{entity.entity_id}",
        mission_id="mission-slice-1",
        site_id="site-slice-1",
        event_type=event_type,
        severity=severity,
        occurred_at=entity.timestamp,
        status=EventStatus.CANDIDATE,
        entities=[entity.entity_id],
        spatial_context={
            "siteFrame": entity.site_frame,
            "position": entity.pose.position,
            "positionCovariance": entity.uncertainty.position_covariance,
            "localizationState": entity.uncertainty.localization_state,
        },
        reasoning={
            "rule": "vertical-slice-demo",
            "observationCount": len(entity.lineage.observation_ids or []),
            "note": "배선 검증용 — 실제 위험 판정 규칙이 아니다",
        },
        evidence=Evidence(
            clip_policy={"preSeconds": clip_seconds, "postSeconds": clip_seconds},  # type: ignore[arg-type]
        ),
        lineage=Lineage(
            edge_version="slice-0.0.1",
            model_versions={"detector": model_version},
            policy_version="slice-policy-0",
            calibration_profile_id="slice-cal-0",
        ),
    )
    return EventBuildResult(status=EventBuildStatus.OK, bundle=bundle)


def run_vertical_slice(
    *,
    frames: list[SliceFrame],
    detector: Detector,
    telemetry: list[TelemetrySample],
    drone_position: tuple[float, float, float],
    model_version: str = "scripted-stub-0",
    severity: Severity = Severity.CANDIDATE,
    max_gap_s: float = 0.5,
    event_policy: dict[str, str] | None = None,
) -> SliceResult:
    """전 구간을 실행한다. 예외를 던지지 않고 단계별 탈락을 결과에 기록한다.

    Event Type 은 호출자가 상수로 넘기지 않는다(F13 — ``event_type="PERSON_PRESENT"``
    기본 인자는 트럭 Entity 도 Person 이벤트로 만들었다). Entity 의 class 와
    ``event_policy`` (class → event type) 의 조합으로 결정되며, 정책에 없는 class 는
    Entity 를 유지한 채 Event 만 발행하지 않고 사유를 ``unpublished_events`` 에
    남긴다. 발행 직전 :func:`_event_bundle_from_entity` 의 compatibility gate 가
    한 번 더 검증한다(정책 오기입 방어).

    프레임은 ``capture_ts_utc`` 기준으로 정렬해 실행하므로 입력 순서에 의존하지 않는다
    (P0-6 재현성 규약).
    """
    policy = event_policy if event_policy is not None else dict(DEFAULT_EVENT_POLICY)
    interpolator = TelemetryInterpolator(max_gap_s=max_gap_s)
    for sample in telemetry:
        interpolator.add(sample)

    tracker = MinimalTracker()
    result = SliceResult()
    per_track: dict[str, list[Observation]] = {}

    for frame in sorted(frames, key=lambda f: (f.capture_ts_utc, f.frame_id)):
        # 프레임 내 detection 도 결정적 순서로 정규화한다 — tracker 의 그리디 배정이
        # 입력 순서 종속이라, 정렬 없이는 같은 장면의 detection 순서 차이가 track
        # 라벨을 뒤바꿔 재현성(P0-6)이 깨진다(프레임 정렬과 같은 정신).
        #
        # 키는 Detection 의 **전체 관측 필드**를 덮는 완전 순서다(독립 재검토
        # Blocker 6 — y_max·confidence 가 빠지면 그 축만 다른 두 detection 이 같은
        # 키가 되어 입력 순서가 다시 결과를 좌우한다). 모든 필드가 완전히 동일한
        # 중복 detection 은 어느 순서로 처리해도 산출물이 같으므로 stable 정렬로
        # 충분하다 — 그 중복을 합칠지는 tracker 가 아니라 상류(NMS)의 몫이다.
        detections = sorted(
            detector.detect(frame.frame_id, frame.width, frame.height),
            key=lambda d: (
                d.detection_class,
                d.bbox.x_min,
                d.bbox.y_min,
                d.bbox.x_max,
                d.bbox.y_max,
                d.confidence,
                # None 은 sentinel 값이 아니라 튜플 태그로 구분한다 — -1 같은
                # 마법값은 이론상 실제 id 와 충돌할 수 있다(재검토 확인항목 #3).
                (1, d.source_class_id) if d.source_class_id is not None else (0, 0),
                d.source_class_name or "",
                d.ontology_version,
            ),
        )
        # Detector 단계의 typed drop(adapter 의 UNKNOWN_LABEL·MALFORMED_CLASS_LINEAGE·
        # EXCESSIVE_CLIP 등)도 슬라이스 탈락 기록으로 흡수한다 — 진단 채널
        # (last_dropped)이 "기록 후 폐기"로 남지 않게(B1-7 배선, 반증 리뷰 F3 완결).
        # track 배정 전 탈락이라 track_id 는 자리표시자다.
        for detector_drop in getattr(detector, "last_dropped", []):
            result.dropped.append(
                DroppedDetection(
                    frame.frame_id,
                    "(pre-track)",
                    SliceStage.DETECTION,
                    f"{detector_drop.reason}: {detector_drop.detail}",
                )
            )
        for clipped in getattr(detector, "last_clipped", []):
            result.clipped_detections.append(
                (
                    frame.frame_id,
                    clipped.area_kept,
                    f"{clipped.detection.detection_class} bbox 경계 클리핑 — 접지점 편향 가능",
                )
            )
        for track_id, detection in tracker.assign(detections):
            interpolated = interpolator.at(frame.capture_ts_utc)
            if not interpolated.ok or interpolated.sample is None:
                result.dropped.append(
                    DroppedDetection(
                        frame.frame_id, track_id, SliceStage.INTERPOLATION,
                        interpolated.status.value,
                    )
                )
                continue

            u_px, v_px = detection.bbox.foot_point
            projected = project_foot_point(
                u_px, v_px, frame.width, frame.height, interpolated.sample
            )
            if not projected.ok or projected.lat is None or projected.lon is None:
                result.dropped.append(
                    DroppedDetection(
                        frame.frame_id, track_id, SliceStage.PROJECTION, projected.status.value
                    )
                )
                continue

            observation = _observation_from_projection(
                frame=frame,
                track_id=track_id,
                detection=detection,
                lat=projected.lat,
                lon=projected.lon,
                altitude_m=0.0,  # 접지점이므로 지면 높이 기준 0
                geo_confidence=projected.confidence,
                error_radius_m=projected.error_radius_m or 1.0,
                drone_position=drone_position,
                model_version=model_version,
            )
            result.observations.append(observation)
            per_track.setdefault(track_id, []).append(observation)

    for track_id, observations in sorted(per_track.items()):
        # entity class 는 인자로 주지 않는다 — 관측들의 observed_class 에서 유도되며
        # 충돌은 CLASSIFICATION_CONFLICT 로 거부된다(INV-031, F13).
        assembly = assemble_world_entity(
            observations,
            entity_id=f"ent-{track_id}",
            model_versions={"detector": model_version},
            calibration_profile_id="slice-cal-0",
        )
        if not assembly.ok or assembly.entity is None:
            result.assembly_failures.append((track_id, assembly.status, assembly.detail))
            continue
        result.entities.append(assembly.entity)

        entity_class = assembly.entity.entity_class
        event_type = policy.get(entity_class)
        if event_type is None:
            # Solution Pack 미지원 class — Entity 는 세계 모델에 남기고 Event 만
            # 발행하지 않는다(typed 사유, 조용한 소멸 금지).
            result.unpublished_events.append(
                (
                    assembly.entity.entity_id,
                    entity_class,
                    f"unsupported_event_policy: {entity_class!r} 에 대한 이벤트 정책 없음",
                )
            )
            continue
        built = _event_bundle_from_entity(
            assembly.entity,
            severity=severity,
            event_type=event_type,
            model_version=model_version,
        )
        if not built.ok or built.bundle is None:
            # 정책이 불호환 event type 을 가리키는 구성 오류 — compatibility gate 가
            # 발행을 끊고 사유를 남긴다.
            result.unpublished_events.append(
                (assembly.entity.entity_id, entity_class, f"{built.status}: {built.detail}")
            )
            continue
        result.bundles.append(built.bundle)

    return result


def synthetic_telemetry(
    timestamps: list[float],
    *,
    lat: float = 37.5,
    lon: float = 127.0,
    altitude_rel_m: float = 60.0,
    heading_deg: float = 0.0,
    gimbal_pitch_deg: float = -60.0,
) -> list[TelemetrySample]:
    """합성 텔레메트리 — PSDK 실입력으로 교체될 자리.

    ``gimbal_pitch_deg`` 기본값을 -60°로 둔 이유: 정수직(-90°)이면 모든 픽셀이 거의
    같은 지점으로 투영되어 bbox 차이가 좌표에 드러나지 않아 배선 검증이 약해진다.
    """
    samples: list[TelemetrySample] = []
    for ts in timestamps:
        samples.append(
            TelemetrySample(
                ts=TimestampSet(source_ts_utc=ts, receive_ts_utc=ts, capture_ts_utc=ts),
                drone_lat=lat,
                drone_lon=lon,
                altitude_rel_m=altitude_rel_m,
                heading_deg=heading_deg,
                gimbal_pitch_deg=gimbal_pitch_deg,
                camera_fov_deg=84.0,
                zoom_factor=1.0,
                rtk_fixed=True,
                source_quality=SourceQuality.FULL,
            )
        )
    return samples


def person_detection(
    *, x_min: float, y_min: float, x_max: float, y_max: float, confidence: float = 0.9
) -> Detection:
    """테스트 편의 — 사람 탐지 1건 (canonical class + 분류 계보 포함).

    초판은 ``detection_class="person"`` (원시 라벨)이었다 — canonical("Person")과
    원시 라벨을 같은 문자열로 취급하던 F13 의 실례라 수정됐다.
    """
    return Detection(
        detection_class="Person",
        confidence=confidence,
        bbox=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
        source_class_id=0,
        source_class_name="person",
    )


def truck_detection(
    *, x_min: float, y_min: float, x_max: float, y_max: float, confidence: float = 0.9
) -> Detection:
    """테스트 편의 — 트럭 탐지 1건. F13 반증(비Person 이 Person 이 되지 않는다)용."""
    return Detection(
        detection_class="Vehicle_Truck",
        confidence=confidence,
        bbox=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
        source_class_id=7,
        source_class_name="truck",
    )
