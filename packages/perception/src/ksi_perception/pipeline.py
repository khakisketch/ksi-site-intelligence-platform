"""Perception offline replay 파이프라인 — Detection→Tracking→Geo→Observation→Entity→Event.

## 경계 결정 (2026-08-31)

이 orchestration 은 ``tests/replay/vertical_slice.py`` 에서 검증된 뒤 여기로
이관됐다. 제품 package 안에 있는 이유는 replay와 모델 평가가 테스트 트리의 복사본이
아니라 같은 계약 코드를 재사용하게 하기 위해서다. 이것은 **온보드 production Edge
Runtime 승격이 아니다**. 실제 Manifold runtime은 ``edge/psdk-app``의 native
``ksi_psdk_app``이며 이 모듈은 Core/worker/DPK production entrypoint에 포함되지 않는다.
``tests/replay``는 이 모듈을 import하되 별도 orchestration 복사본을 두지 않는다.

파이프라인 전 구간::

    Recorded/Live Frame
      → Detection            (ksi_domain.detection — Detector 구현 교체 지점)
      → Tracking             (이 모듈, IoU+class 기반 최소 구현)
      → Telemetry Interpolation  (ksi_geo_core.sync)
      → Geo Projection       (ksi_geo_core.projection)
      → Observation          (ksi_event_contracts.observation)
      → WorldEntity Fusion   (ksi_event_contracts.assembly)
      → Event Candidate      (ksi_domain.enums 상태전이)
      → Evidence Bundle      (ksi_event_contracts.event_bundle)

## 이 파이프라인이 증명하는 것 / 아닌 것

**증명한다:** 배선이 실제로 이어져 있고, 각 단계의 실패가 조용히 삼켜지지 않으며,
같은 입력이 같은 산출물을 낸다.

**증명하지 않는다:** production event evidence, 실기 타이밍(합성/녹화
텔레메트리다), 연관 정확도(IoU 최소 구현이다), Manifold 성능(B2). 생성 bundle은
``productionEvidence=false``와 ``vertical-slice-demo``를 담으며 Core production
edge-sync가 원장 반영 전에 거부한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from ksi_domain.detection import BoundingBox, Detection, Detector
from ksi_domain.detection_adapter import FrameDetectionStatus
from ksi_domain.enums import EventStatus, Severity, assert_event_transition
from ksi_event_contracts.assembly import (
    AssemblyStatus,
    assemble_world_entity,
    world_entity_fingerprint,
)
from ksi_event_contracts.event_bundle import (
    EVIDENCE_CLIP_SECONDS as _EVENT_BUNDLE_EVIDENCE_CLIP_SECONDS,
)
from ksi_event_contracts.event_bundle import (
    ClassificationLineage,
    ClipPolicy,
    EventBundle,
    Evidence,
    Lineage,
)
from ksi_event_contracts.observation import (
    Observation,
    ViewpointEvidenceKind,
    viewpoint_bin_id,
)
from ksi_event_contracts.world_entity import WorldEntity
from ksi_geo_core.projection import project_foot_point
from ksi_geo_core.sync import TelemetryInterpolator, TelemetrySample
from pydantic import ValidationError


@dataclass(frozen=True, slots=True)
class RunContext:
    """실행 1회의 계보 신원 — 기본값이 없다(INV-040/042, 감사 #23 폐쇄).

    초판 파이프라인은 mission/site/policy/calibration/epoch 를 모듈 상수와 기본
    인자("mission-slice-1" 등)로 채웠다 — 필드가 채워져 있다는 이유로 계보
    게이트를 전부 통과하는 placeholder 였고, 그 산출물이 Core durable 원장에
    영구 기록되면 "어느 임무·어느 현장의 사건인가"를 복원할 수 없다. 이제 모든
    계보 값은 호출자가 명시해야 하며, 공백은 생성 시점 typed 거부다(fail-closed).

    ``epoch_utc`` 는 :class:`SliceFrame.capture_ts_utc` (상대 초)를 절대 시각으로
    만드는 기준이다 — 허구의 하드코딩 epoch 가 Evidence 의 occurred_at 이 되는
    것을 막는다(recorded 재생은 텔레메트리 시간축, 합성 테스트는 픽스처가 명시).
    """

    mission_id: str
    site_id: str
    site_frame: str
    epoch_utc: datetime
    model_version: str
    policy_version: str
    calibration_profile_id: str
    edge_version: str
    sensor_id: str

    def __post_init__(self) -> None:
        for name in (
            "mission_id",
            "site_id",
            "site_frame",
            "model_version",
            "policy_version",
            "calibration_profile_id",
            "edge_version",
            "sensor_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"RunContext.{name} 는 공백일 수 없다 — 계보 없는 실행 금지")
        if self.epoch_utc.tzinfo is None or self.epoch_utc.utcoffset() != timedelta(0):
            raise ValueError(f"epoch_utc 는 UTC aware 여야 한다 ({self.epoch_utc!r})")


@dataclass(frozen=True, slots=True)
class SliceFrame:
    """파이프라인 입력 프레임 1장 — 실제 이미지 대신 메타데이터만 담는다.

    이미지 실물은 Detector 구현(RecordedFrameDetector 의 frame_id→배열 매핑,
    이후 PSDK Live View 콜백)이 소유한다 — 파이프라인의 나머지는 bbox·시각·
    크기만 쓰므로 프레임 소스 교체에 영향받지 않는다.
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
    최종본이 아니다(가림·밀집·미검출 구간에 약하다). 목적은 "track_id 가
    파이프라인을 타고 흐르는지" 확인이며, 확률적 다특징 연관은 이후 단계다.

    **class-aware (INV-031 1차 방어, F13):** IoU 가 충분해도 canonical class 가
    다르면 연관하지 않는다 — 같은 자리에서 person 이 truck 으로 바뀌면 그것은 같은
    대상이 아니라 다른 대상(또는 오분류)이며, 한 track 으로 묶으면 class 충돌이
    hidden 연관 오류로 세계 모델에 들어간다. tracker 를 우회한 혼합은 assembly 의
    CLASSIFICATION_CONFLICT(2차 방어)가 잡는다.

    결정적이다 — 같은 입력 순서에 같은 track_id 를 배정한다(재현성).

    **Eviction (staleness, efficiency 반증 대응):** ``_active`` 는 매칭 안 된 detection
    마다 새 항목을 쌓기만 하고 한 번도 비우지 않으면 실행 시간에 비례해 무한정
    자란다 — 장시간 임무에서 메모리와 매 프레임 매칭 비용(O(len(detections)*
    len(active)))이 계속 늘어난다. 각 항목에 "마지막으로 매칭된 프레임 번호"를
    같이 들고, ``max_missed_frames`` 프레임 연속으로 매칭되지 않은 track 은
    다음 호출 시작 시 제거한다. ``assign()`` 호출 1회 = 프레임 1장(호출자가
    시각순으로 부른다는 기존 계약, ``run_vertical_slice`` 참고)이므로 별도
    타임스탬프 인자 없이 내부 카운터로 충분하다. 기본값 30 은 도메인에서
    유도된 상수가 아니라 "짧은 가림·미검출 구간은 흡수하되 무한 성장은 막는다"는
    보수적 정책값이다(재검토 필요 시 조정 지점).
    """

    def __init__(self, *, iou_threshold: float = 0.3, max_missed_frames: int = 30) -> None:
        if not (0.0 < iou_threshold <= 1.0):
            raise ValueError(f"iou_threshold 는 (0,1] 범위여야 한다 ({iou_threshold!r})")
        if max_missed_frames < 1:
            raise ValueError(f"max_missed_frames 는 1 이상이어야 한다 ({max_missed_frames!r})")
        self._iou_threshold = iou_threshold
        self._max_missed_frames = max_missed_frames
        self._next_id = 1
        self._frame_counter = 0
        # track → (bbox, class, 마지막으로 매칭된 frame_counter)
        self._active: dict[str, tuple[BoundingBox, str, int]] = {}

    def assign(self, detections: list[Detection]) -> list[tuple[str, Detection]]:
        """탐지 목록에 track_id 를 배정한다. 입력 순서대로 그리디 매칭."""
        self._frame_counter += 1
        current_frame = self._frame_counter
        # 오래 매칭되지 않은 track 을 이번 프레임의 매칭보다 먼저 비운다 — 새
        # detection 이 방금 죽은 track_id 를 우연히 재사용하지 않게 매칭 전에 정리.
        stale = [
            track_id
            for track_id, (_, _, last_seen) in self._active.items()
            if current_frame - last_seen > self._max_missed_frames
        ]
        for track_id in stale:
            del self._active[track_id]

        assigned: list[tuple[str, Detection]] = []
        claimed: set[str] = set()
        for detection in detections:
            best_id: str | None = None
            best_iou = 0.0
            for track_id, (previous_bbox, previous_class, _) in self._active.items():
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
            self._active[best_id] = (detection.bbox, detection.detection_class, current_frame)
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


@dataclass(frozen=True, slots=True)
class FrameFailure:
    """프레임 1장 전체의 typed 실패 기록 — detection 단위 탈락과 구분한다.

    frame_id·capture 시각·모델 계보를 실패에도 보존한다 — "언제의 어떤 프레임이
    어떤 모델 아래에서 왜 실패했는가"를 실패 기록만으로 역추적할 수 있어야
    Evidence 로 쓸 수 있다.
    """

    frame_id: int
    capture_ts_utc: float
    status: FrameDetectionStatus
    detail: str | None
    model_version: str


@dataclass
class SliceResult:
    """파이프라인 실행 결과 — 각 단계 산출물과 탈락 이유를 모두 보존한다."""

    observations: list[Observation] = field(default_factory=list)
    dropped: list[DroppedDetection] = field(default_factory=list)
    # 프레임 단위 typed 실패(FRAME_NOT_FOUND/INVALID_FRAME/INFERENCE_FAILED) —
    # 한 프레임의 실패가 배치 전체를 죽이지 않고 여기 기록된 채 다음 프레임이
    # 계속 처리된다(slice-inference-exception-channel 폐쇄).
    frame_failures: list[FrameFailure] = field(default_factory=list)
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
    context: RunContext,
) -> Observation:
    """투영 결과 → Observation 계약.

    공분산은 오차반경을 등방 표준편차로 해석해 구성한다 — 실제 covariance 전파는
    Phase 2+ 대상이며, 여기서는 "불확실성이 계약을 타고 흐른다"만 보인다(그 사실을
    숨기지 않기 위해 이 주석을 남긴다).

    관측점은 아직 보정된 카메라 Pose가 아니라 이산 bin 폴백이므로 증거 등급을
    ``SPATIAL_BIN`` 으로 **명시 선언**한다. 그 결과 이 파이프라인이 만드는 Entity는
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
        observed_at=context.epoch_utc + timedelta(seconds=frame.capture_ts_utc),
        site_frame=context.site_frame,
        position=[lat, lon, altitude_m],
        position_covariance=[variance, 0.0, 0.0, 0.0, variance, 0.0, 0.0, 0.0, variance],
        detection_confidence=detection.confidence,
        geo_confidence=geo_confidence,
        sensor_id=context.sensor_id,
        viewpoint_id=viewpoint_bin_id(drone_position),
        viewpoint_kind=ViewpointEvidenceKind.SPATIAL_BIN,
        lineage={"detector": context.model_version},
    )


# Event Type 별 호환 Entity Class (INV-031 — Event 는 Entity class 와 호환될 때만).
# 파이프라인 수준의 최소 정책이다 — 실제 Solution Pack 정책은 Core 소유(Phase 2+).
EVENT_TYPE_COMPATIBLE_CLASSES: dict[str, frozenset[str]] = {
    "PERSON_PRESENT": frozenset({"Person"}),
}

# Entity Class → 발행할 Event Type. 여기 없는 class 는 Entity 는 유지하되 Event 를
# 발행하지 않는다(unpublished_events 에 typed 사유 기록 — 조용한 소멸 금지).
DEFAULT_EVENT_POLICY: dict[str, str] = {"Person": "PERSON_PRESENT"}

# 두 정책표의 상호 일관성 — 기본 정책이 가리키는 event_type 은 반드시 호환표에
# 있어야 한다(감사 #41: 한쪽만 갱신하면 그 class 의 이벤트가 전부 조용히
# UNKNOWN_EVENT_TYPE 으로 미발행되는 회귀가 리뷰에서 안 보인다).
assert set(DEFAULT_EVENT_POLICY.values()) <= set(EVENT_TYPE_COMPATIBLE_CLASSES), (
    "DEFAULT_EVENT_POLICY 가 호환표에 없는 event_type 을 가리킨다: "
    f"{set(DEFAULT_EVENT_POLICY.values()) - set(EVENT_TYPE_COMPATIBLE_CLASSES)}"
)


class EventBuildStatus(StrEnum):
    OK = "ok"
    EVENT_CLASS_MISMATCH = "event_class_mismatch"  # event_type 이 entity class 와 불호환
    UNKNOWN_EVENT_TYPE = "unknown_event_type"  # 호환표에 없는 event_type
    # entity 에 분류 계보(ontology version·원시 출처)가 없다 — 계보 없는 이벤트
    # 발행 금지(INV-031, EventBundle v1.2 standalone lineage 의 assembly gate).
    MISSING_CLASSIFICATION_LINEAGE = "missing_classification_lineage"
    # 클립 정책표에 없는 severity — 임의 기본 길이를 지어내지 않는다(INV-030,
    # 감사 #26: MEDIUM 은 §17.2 상 재검증 경로라 클립 정책이 정의돼 있지 않다).
    UNSUPPORTED_SEVERITY_POLICY = "unsupported_severity_policy"


# INV-030 — Evidence Clip 전후 길이(초). mission-contract evidencePolicy 의
# candidate/high/critical 3단계와 정합해야 한다(감사 #26·#37: 초판은 2단계라
# CRITICAL 이 5초 클립을 받았다). 여기 없는 severity 는 typed 거부.
#
# SSOT 는 ksi_event_contracts.event_bundle 이다(EventBundle 자신도 이 표로
# clip_policy·severity 정합을 교차검증한다) — 여기서 재선언하면 두 표가
# 갈라질 때 감사 #26·#37 급 드리프트가 재발한다. 이름은 하위 호환 re-export
# 로 유지한다(tests/replay/vertical_slice.py 가 이 이름으로 가져간다).
EVIDENCE_CLIP_SECONDS = _EVENT_BUNDLE_EVIDENCE_CLIP_SECONDS


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
    context: RunContext,
) -> EventBuildResult:
    """WorldEntity → EventBundle. 상태전이는 반드시 전이표를 경유한다(INV-031).

    **Event/Class compatibility gate (F13):** event_type 이 entity 의 class 와
    호환되지 않으면 EventBundle 을 만들지 않고 typed 로 거부한다 — Truck Entity 에
    PERSON_PRESENT 를 요청하는 호출은 코드 어디서 오든 여기서 끊긴다.

    Detection 에서 곧바로 CONFIRMED 로 가지 않고 OBSERVATION → CANDIDATE 를 밟는다 —
    단일 실행이 사건을 확정하지 않는다(INV-022).
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

    # Standalone classification lineage (EventBundle v1.2, INV-031) — bundle 이
    # WorldEntity 와 분리 전송돼도 분류 계보가 검증 가능해야 한다. entity 의
    # 계보가 비어 있으면 이벤트를 만들지 않는다(계보 없는 발행 금지).
    ontology_version = entity.lineage.classification_ontology_version
    classification_source = entity.lineage.classification_source
    if ontology_version is None or classification_source is None:
        return EventBuildResult(
            status=EventBuildStatus.MISSING_CLASSIFICATION_LINEAGE,
            detail=(
                f"entity {entity.entity_id}: classification_ontology_version/"
                "classification_source 부재 — 계보 없는 이벤트 발행 금지(INV-031)"
            ),
        )

    # '계보 없음'은 키 부재만이 아니다 — 상류 WorldEntity(ClassificationSource)는
    # 빈 원시 id/이름·공백 class 를 구조적으로 합법 취급하는데, v1.2
    # ClassificationLineage 는 그걸 model_validator 로 거부한다(스키마 검증은
    # 완화하지 않는다). 여기서 typed 로 거르지 않으면 그 ValidationError 가 이 함수
    # 밖으로 새어나가 run_vertical_slice 의 배치 루프를 통째로 죽인다("예외를 던지지
    # 않는다" 계약 위반, P1 — 실질 공허 계보의 게이트 우회).
    try:
        classification_lineage = ClassificationLineage(
            entity_class=entity.entity_class,
            ontology_version=ontology_version,
            source=classification_source,
            entity_fingerprint=world_entity_fingerprint(entity),
        )
    except ValidationError as exc:
        return EventBuildResult(
            status=EventBuildStatus.MISSING_CLASSIFICATION_LINEAGE,
            detail=(
                f"entity {entity.entity_id}: 분류 계보가 형식상 존재하나 실질적으로 "
                f"공허하다(빈 원시 id/이름·공백 class 등) — {exc} — 계보 없는 이벤트 "
                "발행 금지(INV-031)"
            ),
        )

    clip_seconds = EVIDENCE_CLIP_SECONDS.get(severity)
    if clip_seconds is None:
        return EventBuildResult(
            status=EventBuildStatus.UNSUPPORTED_SEVERITY_POLICY,
            detail=(
                f"severity {severity.value} 의 Evidence Clip 정책이 정의돼 있지 않다 — "
                "임의 길이를 지어내지 않는다(INV-030, 정책표: "
                f"{sorted(s.value for s in EVIDENCE_CLIP_SECONDS)})"
            ),
        )

    # 상태는 전이표를 실제로 통과한 변수다 — 리터럴 상수 인자는 입력과 무관하게
    # 항상 통과하는 장식 게이트였다(감사 #77). 이 체인이 전이표에 없는 경로로
    # 바뀌면 여기서 IllegalEventTransitionError 로 즉시 터진다.
    status: EventStatus | None = None
    for next_status in (EventStatus.OBSERVATION, EventStatus.CANDIDATE):
        assert_event_transition(status, next_status)
        status = next_status
    assert status is EventStatus.CANDIDATE

    bundle = EventBundle(
        event_id=f"evt-{entity.entity_id}",
        mission_id=context.mission_id,
        site_id=context.site_id,
        event_type=event_type,
        severity=severity,
        occurred_at=entity.timestamp,
        status=status,
        entities=[entity.entity_id],
        spatial_context={
            "siteFrame": entity.site_frame,
            "position": entity.pose.position,
            "positionCovariance": entity.uncertainty.position_covariance,
            "localizationState": entity.uncertainty.localization_state,
        },
        reasoning={
            "rule": "vertical-slice-demo",
            "executionClass": "OFFLINE_REPLAY_EVALUATION",
            "productionEvidence": False,
            "observationCount": len(entity.lineage.observation_ids or []),
            "note": "배선 검증용 — 실제 위험 판정 규칙이 아니다",
        },
        evidence=Evidence(
            # ClipPolicy 를 직접 생성 — dict + type: ignore 는 INV-030 강제 지점의
            # 유일한 정적 안전망을 끄는 것이었다(감사 #68).
            clip_policy=ClipPolicy(pre_seconds=clip_seconds, post_seconds=clip_seconds),
        ),
        lineage=Lineage(
            edge_version=context.edge_version,
            model_versions={"detector": context.model_version},
            policy_version=context.policy_version,
            calibration_profile_id=context.calibration_profile_id,
            # 생성 규칙(entity_fingerprint): world_entity_fingerprint(entity) 뿐 —
            # 수신자는 WorldEntity 확보 시 같은 함수로 재계산해 대조한다. 객체는
            # 위에서 이미 typed 게이트를 통과해 구성된 것을 그대로 쓴다(재구성 시
            # 여기서 또 ValidationError 가 날 경로를 만들지 않는다).
            classification={entity.entity_id: classification_lineage},
        ),
    )
    return EventBuildResult(status=EventBuildStatus.OK, bundle=bundle)


def run_vertical_slice(
    *,
    frames: list[SliceFrame],
    detector: Detector,
    telemetry: list[TelemetrySample],
    drone_position: tuple[float, float, float],
    context: RunContext,
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
        outcome = detector.detect_frame(frame.frame_id, frame.width, frame.height)
        if not outcome.ok:
            # 프레임 단위 typed 실패 — 이 프레임만 기록하고 다음 프레임을 계속
            # 처리한다(한 장의 실패가 배치 전체를 죽이지 않는다). FRAME_NOT_FOUND
            # 는 빈 장면과 구분되는 실패다(소스 결손의 무사고 위장 금지).
            result.frame_failures.append(
                FrameFailure(
                    frame_id=frame.frame_id,
                    capture_ts_utc=frame.capture_ts_utc,
                    status=outcome.status,
                    detail=outcome.detail,
                    model_version=context.model_version,
                )
            )
            continue
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
            outcome.detections,
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
        # EXCESSIVE_CLIP 등)도 탈락 기록으로 흡수한다 — 진단이 "기록 후 폐기"로
        # 남지 않게(B1-7 배선, 반증 리뷰 F3 완결). per-call 반환값 소비라 이전
        # 프레임 진단이 섞일 경로가 없다. track 배정 전 탈락이라 track_id 는
        # 자리표시자다.
        for detector_drop in outcome.dropped:
            result.dropped.append(
                DroppedDetection(
                    frame.frame_id,
                    "(pre-track)",
                    SliceStage.DETECTION,
                    f"{detector_drop.reason}: {detector_drop.detail}",
                )
            )
        for clipped in outcome.clipped:
            result.clipped_detections.append(
                (
                    frame.frame_id,
                    clipped.area_kept,
                    f"{clipped.detection.detection_class} bbox 경계 클리핑 — 접지점 편향 가능",
                )
            )
        # 보간은 프레임당 1회다 — detection 마다 같은 capture_ts 로 같은 결과를
        # 반복 계산할 이유가 없다(감사 #42). 실패 시 그 프레임의 전 detection 이
        # 같은 사유로 탈락한다(조용한 소멸 금지 유지).
        interpolated = interpolator.at(frame.capture_ts_utc)
        for track_id, detection in tracker.assign(detections):
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
                context=context,
            )
            result.observations.append(observation)
            per_track.setdefault(track_id, []).append(observation)

    for track_id, observations in sorted(per_track.items()):
        # entity class 는 인자로 주지 않는다 — 관측들의 observed_class 에서 유도되며
        # 충돌은 CLASSIFICATION_CONFLICT 로 거부된다(INV-031, F13).
        assembly = assemble_world_entity(
            observations,
            entity_id=f"ent-{track_id}",
            model_versions={"detector": context.model_version},
            calibration_profile_id=context.calibration_profile_id,
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
            context=context,
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
