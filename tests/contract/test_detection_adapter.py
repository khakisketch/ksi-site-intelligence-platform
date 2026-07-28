"""DetectionAdapter 정규화 규칙 검증 (Track B-1).

모델 raw output → Detection 계약 경계의 전 규칙을 고정한다: 포맷 변환 산술,
fail-closed typed drop, 클리핑 정합(geo projection 픽셀 검증과 상한 포함 일치),
순서 보존·결정성. conformance suite(:mod:`test_detector_conformance`)가 "Detector
로서의 계약"을 본다면, 여기는 "정규화 그 자체"를 본다.
"""

from __future__ import annotations

import pytest
from ksi_domain.detection_adapter import (
    MIN_AREA_KEPT_AFTER_CLIP,
    AdapterBackedDetector,
    BoxFormat,
    DetectionAdapter,
    DropReason,
    RawDetection,
)
from ksi_domain.ontology import COCO_ONTOLOGY, OntologyMapping
from ksi_geo_core.projection import project_foot_point
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet

_W, _H = 1920, 1080


def _adapter(**overrides: object) -> DetectionAdapter:
    kwargs: dict = {
        "box_format": BoxFormat.XYXY,
        "normalized": False,
        # 자유 dict 가 아니라 검증된 OntologyMapping — 독립 재검토 Blocker 1 이후
        # adapter 는 이것만 받는다(의미 변조 매핑은 생성 시점에 거부).
        "ontology": COCO_ONTOLOGY,
    }
    kwargs.update(overrides)
    return DetectionAdapter(**kwargs)


# ── 포맷 변환 산술 ────────────────────────────────────────────────────────────


def test_xyxy_passthrough() -> None:
    result = _adapter().convert(
        [RawDetection(label="person", score=0.9, box=(10.0, 20.0, 110.0, 220.0))],
        width=_W,
        height=_H,
    )
    [d] = result.detections
    assert (d.bbox.x_min, d.bbox.y_min, d.bbox.x_max, d.bbox.y_max) == (10.0, 20.0, 110.0, 220.0)


def test_xywh_converts_to_corners() -> None:
    result = _adapter(box_format=BoxFormat.XYWH).convert(
        [RawDetection(label="person", score=0.9, box=(10.0, 20.0, 100.0, 200.0))],
        width=_W,
        height=_H,
    )
    [d] = result.detections
    assert (d.bbox.x_min, d.bbox.y_min, d.bbox.x_max, d.bbox.y_max) == (10.0, 20.0, 110.0, 220.0)


def test_cxcywh_converts_to_corners() -> None:
    result = _adapter(box_format=BoxFormat.CXCYWH).convert(
        [RawDetection(label="person", score=0.9, box=(60.0, 120.0, 100.0, 200.0))],
        width=_W,
        height=_H,
    )
    [d] = result.detections
    assert (d.bbox.x_min, d.bbox.y_min, d.bbox.x_max, d.bbox.y_max) == (10.0, 20.0, 110.0, 220.0)


def test_normalized_coordinates_scaled_by_frame() -> None:
    """normalized [0,1] 좌표는 프레임 크기로 환산된다 (DETR 계열 출력 형태)."""
    result = _adapter(box_format=BoxFormat.CXCYWH, normalized=True).convert(
        [RawDetection(label="person", score=0.9, box=(0.5, 0.5, 0.25, 0.5))],
        width=_W,
        height=_H,
    )
    [d] = result.detections
    assert (d.bbox.x_min, d.bbox.y_min, d.bbox.x_max, d.bbox.y_max) == (
        _W * 0.375,
        _H * 0.25,
        _W * 0.625,
        _H * 0.75,
    )


# ── fail-closed typed drop ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        RawDetection(label="person", score=float("nan"), box=(10.0, 20.0, 110.0, 220.0)),
        RawDetection(label="person", score=0.9, box=(float("inf"), 20.0, 110.0, 220.0)),
        RawDetection(label="person", score=0.9, box=(10.0, float("nan"), 110.0, 220.0)),
    ],
)
def test_non_finite_values_dropped(raw: RawDetection) -> None:
    result = _adapter().convert([raw], width=_W, height=_H)
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.NON_FINITE


@pytest.mark.parametrize("score", [-0.1, 1.1, 100.0])
def test_out_of_range_score_dropped_not_clamped(score: float) -> None:
    """score 범위 밖은 drop — 조용한 clamp 는 P0 검토에서 blocker 였던 패턴이다."""
    result = _adapter().convert(
        [RawDetection(label="person", score=score, box=(10.0, 20.0, 110.0, 220.0))],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.SCORE_OUT_OF_RANGE


def test_unknown_label_dropped_with_record() -> None:
    """미등록 라벨은 조용히 통과하지도, 조용히 사라지지도 않는다."""
    result = _adapter().convert(
        [RawDetection(label="giraffe", score=0.9, box=(10.0, 20.0, 110.0, 220.0))],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.UNKNOWN_LABEL
    assert "giraffe" in dropped.detail


def test_below_threshold_dropped_when_threshold_set() -> None:
    result = _adapter(min_confidence=0.5).convert(
        [
            RawDetection(label="person", score=0.49, box=(10.0, 20.0, 110.0, 220.0)),
            RawDetection(label="person", score=0.5, box=(10.0, 20.0, 110.0, 220.0)),
        ],
        width=_W,
        height=_H,
    )
    assert len(result.detections) == 1  # 경계값 0.5 는 통과(미달만 drop)
    [dropped] = result.dropped
    assert dropped.reason is DropReason.BELOW_CONFIDENCE


def test_default_threshold_passes_low_confidence() -> None:
    """기본 threshold 0.0 — 거르는 결정은 호출자의 명시적 선택이다(미탐 방향 방지)."""
    result = _adapter().convert(
        [RawDetection(label="person", score=0.01, box=(10.0, 20.0, 110.0, 220.0))],
        width=_W,
        height=_H,
    )
    assert len(result.detections) == 1


# ── 클리핑·퇴화 ───────────────────────────────────────────────────────────────


def test_slightly_out_of_frame_clipped_inclusive_bounds() -> None:
    """경계 살짝 밖은 클리핑 — 상한은 width/height **포함**(projection 계약 정합)."""
    result = _adapter().convert(
        [RawDetection(label="person", score=0.9, box=(-5.0, -3.0, _W + 10.0, _H + 7.0))],
        width=_W,
        height=_H,
    )
    [d] = result.detections
    assert (d.bbox.x_min, d.bbox.y_min, d.bbox.x_max, d.bbox.y_max) == (
        0.0,
        0.0,
        float(_W),
        float(_H),
    )


def test_fully_outside_frame_dropped_as_degenerate() -> None:
    result = _adapter().convert(
        [RawDetection(label="person", score=0.9, box=(-200.0, -200.0, -10.0, -10.0))],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.DEGENERATE_BOX


def test_zero_area_box_dropped() -> None:
    result = _adapter().convert(
        [RawDetection(label="person", score=0.9, box=(10.0, 20.0, 10.0, 220.0))],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.DEGENERATE_BOX


# ── 배치 동작·구성 검증 ───────────────────────────────────────────────────────


def test_batch_preserves_order_and_isolates_failures() -> None:
    """한 건의 문제는 그 건만 죽인다 — 배치의 나머지는 순서대로 살아남는다."""
    raws = [
        RawDetection(label="person", score=0.9, box=(10.0, 20.0, 110.0, 220.0)),
        RawDetection(label="giraffe", score=0.9, box=(10.0, 20.0, 110.0, 220.0)),  # drop
        RawDetection(label="truck", score=0.8, box=(300.0, 40.0, 340.0, 80.0)),
        RawDetection(label="person", score=float("nan"), box=(1.0, 1.0, 2.0, 2.0)),  # drop
    ]
    result = _adapter().convert(raws, width=_W, height=_H)
    assert [d.detection_class for d in result.detections] == ["Person", "Vehicle_Truck"]
    assert [d.reason for d in result.dropped] == [
        DropReason.UNKNOWN_LABEL,
        DropReason.NON_FINITE,
    ]


def test_conversion_is_deterministic() -> None:
    raws = [RawDetection(label=0, score=0.7, box=(10.0, 20.0, 110.0, 220.0))]
    a = _adapter().convert(raws, width=_W, height=_H)
    b = _adapter().convert(raws, width=_W, height=_H)
    assert a.detections == b.detections
    assert a.dropped == b.dropped


@pytest.mark.parametrize(("width", "height"), [(0, 100), (100, 0), (-1, 100)])
def test_invalid_frame_size_is_caller_error(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="프레임 크기"):
        _adapter().convert([], width=width, height=height)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_min_confidence_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="min_confidence"):
        _adapter(min_confidence=bad)


def test_free_dict_rejected_by_adapter() -> None:
    """[Blocker 1] adapter 는 자유 dict 를 받지 않는다 — 검증된 OntologyMapping 전용."""
    with pytest.raises(ValueError, match="OntologyMapping"):
        _adapter(ontology={"truck": "Person"})


def test_meaning_altering_mapping_cannot_be_constructed() -> None:
    """[Blocker 1 핵심 반증] {"truck": "Person"} 의미 변조 매핑은 생성 자체가 거부된다."""
    with pytest.raises(ValueError, match="권위 해석"):
        OntologyMapping(
            version="ksi-ontology-v1",
            source_taxonomy="COCO-2017",
            mappings={"truck": "Person"},
            id_to_name={},
        )


def test_unregistered_canonical_rejected_in_mapping() -> None:
    """등록 Canonical 집합 밖의 값("Worker" 등)은 매핑에 넣을 수 없다."""
    with pytest.raises(ValueError, match="Canonical"):
        OntologyMapping(
            version="ksi-ontology-v1",
            source_taxonomy="COCO-2017",
            mappings={"person": "Worker"},
            id_to_name={},
        )


def test_unregistered_ontology_version_rejected_in_mapping() -> None:
    """[Blocker 4] 미등록 버전으로는 매핑을 만들 수 없다."""
    with pytest.raises(ValueError, match="미등록 ontology"):
        OntologyMapping(
            version="attacker-v99",
            source_taxonomy="COCO-2017",
            mappings={"person": "Person"},
            id_to_name={},
        )


def test_subset_mapping_allowed() -> None:
    """권위 매핑의 부분집합(person 만 소비)은 허용 — 범위 축소는 의미 변조가 아니다."""
    subset = OntologyMapping(
        version="ksi-ontology-v1",
        source_taxonomy="COCO-2017",
        mappings={"person": "Person"},
        id_to_name={0: "person"},
    )
    result = _adapter(ontology=subset).convert(
        [
            RawDetection(label="person", score=0.9, box=(10.0, 20.0, 110.0, 220.0)),
            RawDetection(label="truck", score=0.9, box=(10.0, 20.0, 110.0, 220.0)),
        ],
        width=_W,
        height=_H,
    )
    assert [d.detection_class for d in result.detections] == ["Person"]
    [dropped] = result.dropped
    assert dropped.reason is DropReason.UNKNOWN_LABEL  # truck 은 이 부분집합 밖


# ── AdapterBackedDetector 조립 ────────────────────────────────────────────────


def test_adapter_backed_detector_exposes_last_dropped() -> None:
    """탈락 기록이 조용히 사라지지 않고 last_dropped 로 노출된다."""

    def raw_source(frame_id: int, width: int, height: int) -> list[RawDetection]:
        return [RawDetection(label="giraffe", score=0.9, box=(10.0, 20.0, 110.0, 220.0))]

    detector = AdapterBackedDetector(raw_source=raw_source, adapter=_adapter())
    assert detector.detect(1, _W, _H) == []
    [dropped] = detector.last_dropped
    assert dropped.reason is DropReason.UNKNOWN_LABEL


def test_adapter_backed_detector_resets_dropped_per_frame() -> None:
    """last_dropped 는 마지막 호출분만 — 프레임 간 누적되지 않는다."""

    def raw_source(frame_id: int, width: int, height: int) -> list[RawDetection]:
        if frame_id == 1:
            return [RawDetection(label="giraffe", score=0.9, box=(10.0, 20.0, 110.0, 220.0))]
        return [RawDetection(label="person", score=0.9, box=(10.0, 20.0, 110.0, 220.0))]

    detector = AdapterBackedDetector(raw_source=raw_source, adapter=_adapter())
    detector.detect(1, _W, _H)
    assert len(detector.last_dropped) == 1
    assert len(detector.detect(2, _W, _H)) == 1
    assert detector.last_dropped == []


# ── 반증 리뷰 회귀 (2026-07-27) ───────────────────────────────────────────────
#
# 초판 adapter 에 대한 adversarial 반증이 확인한 실결함 4건(F1 산술 NaN escape /
# F2 무제한 클리핑 / F3 stale 기록 / F4 bool 라벨 매칭)과, 정합 주장을 우연에
# 맡기지 않기 위한 커플링 앵커를 고정한다.


def test_conversion_arithmetic_overflow_dropped_not_raised() -> None:
    """[F1] 원본은 finite 지만 변환 산술이 inf/NaN 을 만드는 입력 — 예외가 아니라 drop.

    1e308×1920=inf, inf-inf=nan 이 클리핑(min/max 는 NaN 통과)과 퇴화 검사(NaN 비교는
    False)를 뚫고 BoundingBox 생성자에서 ValueError 로 터지던 경로. 한 건이 배치
    전체를 죽이는, "예외를 던지지 않는다" 계약의 위반이었다.
    """
    adapter = DetectionAdapter(
        box_format=BoxFormat.CXCYWH, normalized=True, ontology=COCO_ONTOLOGY
    )
    good = RawDetection(label=0, score=0.9, box=(0.5, 0.5, 0.25, 0.5))
    overflowing = RawDetection(label=0, score=0.9, box=(1e308, 0.5, 1e308, 0.5))
    result = adapter.convert([good, overflowing], width=_W, height=_H)
    assert len(result.detections) == 1  # 배치의 정상 건은 살아남는다
    [dropped] = result.dropped
    assert dropped.reason is DropReason.NON_FINITE
    assert "변환 산술" in dropped.detail


def test_mostly_outside_frame_dropped_as_excessive_clip() -> None:
    """[F2] 대부분 프레임 밖인 bbox 는 경계 bbox 로 둔갑하지 않는다.

    (-1e6,-1e6,1e6,1e6) 이 전 프레임 bbox(0,0,W,H)로 클리핑돼 고신뢰 Detection 으로
    통과하던 경로 — 접지점이 원래 대상과 무관한 편향 위치가 된다.
    """
    result = _adapter().convert(
        [RawDetection(label="person", score=0.99, box=(-1e6, -1e6, 1e6, 1e6))],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.EXCESSIVE_CLIP


def test_clip_survival_boundary_matches_threshold() -> None:
    """[F2] 잔존 면적비가 문턱 이상이면 통과 + clipped 기록, 미만이면 drop."""
    # 절반만 프레임 안: x 가 [-100, 100] → 잔존 0.5 (경계값, 통과)
    at_threshold = RawDetection(label="person", score=0.9, box=(-100.0, 10.0, 100.0, 110.0))
    # 1/4 만 프레임 안: 잔존 0.25 < 0.5 (drop)
    below = RawDetection(label="person", score=0.9, box=(-300.0, 10.0, 100.0, 110.0))
    result = _adapter().convert([at_threshold, below], width=_W, height=_H)
    assert len(result.detections) == 1
    [clipped] = result.clipped
    assert clipped.area_kept == pytest.approx(MIN_AREA_KEPT_AFTER_CLIP)
    [dropped] = result.dropped
    assert dropped.reason is DropReason.EXCESSIVE_CLIP


def test_clipped_records_expose_partial_clip() -> None:
    """[F2] 살아남았지만 잘린 bbox 는 clipped 에 기록된다 — 편향 사실을 지우지 않는다."""
    result = _adapter().convert(
        [
            RawDetection(label="person", score=0.9, box=(10.0, 20.0, 110.0, 220.0)),  # 온전
            RawDetection(label="person", score=0.9, box=(-5.0, 20.0, 95.0, 220.0)),  # 잘림
        ],
        width=_W,
        height=_H,
    )
    assert len(result.detections) == 2
    [clipped] = result.clipped
    assert clipped.detection.bbox.x_min == 0.0
    assert 0.0 < clipped.area_kept < 1.0


def test_unclipped_batch_has_empty_clipped_records() -> None:
    result = _adapter().convert(
        [RawDetection(label="person", score=0.9, box=(10.0, 20.0, 110.0, 220.0))],
        width=_W,
        height=_H,
    )
    assert result.clipped == []


def test_stale_dropped_cleared_on_failed_call() -> None:
    """[F3] 실패한 호출 뒤 last_dropped 는 이전 프레임 기록을 유지하지 않는다."""

    def raw_source(frame_id: int, width: int, height: int) -> list[RawDetection]:
        return [RawDetection(label="giraffe", score=0.9, box=(10.0, 20.0, 110.0, 220.0))]

    detector = AdapterBackedDetector(raw_source=raw_source, adapter=_adapter())
    detector.detect(1, _W, _H)
    assert len(detector.last_dropped) == 1
    with pytest.raises(ValueError):
        detector.detect(2, 0, _H)
    assert detector.last_dropped == [], "실패한 호출의 stale 기록이 남았다 — 오독 경로"


def test_bool_label_does_not_match_int_class_key() -> None:
    """[F4] label=False 가 class_map 의 0 키에 매칭되면 fail-closed 우회다."""
    result = _adapter().convert(
        [
            RawDetection(label=False, score=0.9, box=(10.0, 20.0, 110.0, 220.0)),
            RawDetection(label=True, score=0.9, box=(10.0, 20.0, 110.0, 220.0)),
        ],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    assert [d.reason for d in result.dropped] == [DropReason.UNKNOWN_LABEL] * 2


def test_non_str_mapping_key_rejected() -> None:
    """[F4 계승] OntologyMapping 키는 공백 아닌 str 만 — bool/int 키는 생성 거부."""
    with pytest.raises(ValueError, match="라벨명"):
        OntologyMapping(
            version="ksi-ontology-v1",
            source_taxonomy="COCO-2017",
            mappings={True: "Person"},  # type: ignore[dict-item]
            id_to_name={},
        )


@pytest.mark.parametrize(
    "raw",
    [
        RawDetection(label="person", score=0.9, box=(10.0, 20.0, 110.0)),  # type: ignore[arg-type]
        RawDetection(label="person", score=0.9, box=(10.0, "20", 110.0, 220.0)),  # type: ignore[arg-type]
        RawDetection(label="person", score="0.9", box=(10.0, 20.0, 110.0, 220.0)),  # type: ignore[arg-type]
        # score=True 는 mypy 를 통과한다(bool 은 float 로 승인) — 런타임 거부가 유일한 방어.
        RawDetection(label="person", score=True, box=(10.0, 20.0, 110.0, 220.0)),
    ],
)
def test_structurally_malformed_raw_dropped(raw: RawDetection) -> None:
    """[F8] 구조 위반 입력은 unpack/TypeError 로 새지 않고 MALFORMED drop 된다."""
    result = _adapter().convert([raw], width=_W, height=_H)
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.MALFORMED


def test_nan_frame_size_rejected_not_nan_blind() -> None:
    """[F8] float NaN 프레임 크기는 `<= 0` 비교가 False 라 가드를 뚫었다 — int 강제."""
    with pytest.raises(ValueError, match="프레임 크기"):
        _adapter().convert([], width=float("nan"), height=_H)  # type: ignore[arg-type]
    detector = AdapterBackedDetector(raw_source=lambda *_: [], adapter=_adapter())
    with pytest.raises(ValueError, match="프레임 크기"):
        detector.detect(1, float("nan"), _H)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("box_format", "box"),
    [
        (BoxFormat.XYXY, (110.0, 20.0, 10.0, 220.0)),  # 반전 x
        (BoxFormat.XYWH, (10.0, 20.0, -100.0, 200.0)),  # 음수 폭
        (BoxFormat.CXCYWH, (60.0, 120.0, -100.0, 200.0)),  # 음수 폭(중심 기준)
    ],
)
def test_negative_or_inverted_extent_dropped(box_format: BoxFormat, box: tuple) -> None:
    """[리뷰 확인 고정] 음수 폭·반전 좌표는 어떤 포맷에서도 유효 Detection 이 안 된다."""
    adapter = _adapter(box_format=box_format)
    result = adapter.convert(
        [RawDetection(label="person", score=0.9, box=box)], width=_W, height=_H
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.DEGENERATE_BOX


def test_raw_source_not_called_on_invalid_frame_size() -> None:
    """[F9] 크기 가드는 raw_source 호출 **전에** 서야 한다 — 실모델이면 GPU 호출이다."""
    calls: list[int] = []

    def raw_source(frame_id: int, width: int, height: int) -> list[RawDetection]:
        calls.append(frame_id)
        return []

    detector = AdapterBackedDetector(raw_source=raw_source, adapter=_adapter())
    with pytest.raises(ValueError):
        detector.detect(1, 0, _H)
    assert calls == [], "invalid 크기에서 raw_source 가 호출됐다"


# ── adapter ↔ projection 커플링 앵커 ─────────────────────────────────────────


def _telemetry_sample() -> TelemetrySample:
    """projection 골든 테스트와 같은 정상 텔레메트리(직하방 짐벌·RTK)."""
    return TelemetrySample(
        ts=TimestampSet(source_ts_utc=0.0, receive_ts_utc=0.0),
        drone_lat=37.5,
        drone_lon=127.0,
        altitude_rel_m=100.0,
        heading_deg=0.0,
        gimbal_pitch_deg=-90.0,
        camera_fov_deg=84.0,
        zoom_factor=1.0,
        rtk_fixed=True,
        source_quality=SourceQuality.FULL,
    )


def test_clipped_boundary_foot_point_accepted_by_projection() -> None:
    """[커플링] 경계로 클리핑된 bbox 의 foot point 는 projection 에서 거부되지 않는다.

    adapter 의 "상한 포함 클리핑"과 projection 의 "상한 포함 픽셀 검증"은 독립 상수다
    — 이 테스트가 없으면 두 값의 정합은 우연이다. projection 이 배타 상한으로 바뀌면
    여기가 깨져서, 경계 클리핑 bbox 전부가 INVALID_PIXEL 로 조용히 증발하는 회귀를
    앞당겨 잡는다.
    """
    # 우하단 모서리 걸침 → x_max==W, y_max==H 로 클리핑 → foot point (u, H)
    result = _adapter().convert(
        [RawDetection(label="person", score=0.9, box=(_W - 60.0, _H - 100.0, _W + 40.0, _H + 5.0))],
        width=_W,
        height=_H,
    )
    [detection] = result.detections
    u_px, v_px = detection.bbox.foot_point
    assert v_px == float(_H)  # 실제로 경계에 닿았다(전제 확인 — 공허성 방지)
    projection = project_foot_point(u_px, v_px, _W, _H, _telemetry_sample())
    assert projection.ok, (
        f"경계 클리핑 foot point ({u_px}, {v_px}) 가 projection 에서 거부됐다 "
        f"({projection.status}) — adapter 클리핑 상한과 projection 픽셀 검증의 정합이 깨졌다"
    )


# ── 분류 계보 (INV-031, F13 후속 — 재검토 #2) ────────────────────────────────


def test_source_id_and_name_both_preserved_for_named_label() -> None:
    """라벨명 소스가 원시 index 도 알면 둘 다 Detection 계보로 흐른다."""
    result = _adapter().convert(
        [
            RawDetection(
                label="person", score=0.9, box=(10.0, 20.0, 110.0, 220.0), source_class_id=0
            )
        ],
        width=_W,
        height=_H,
    )
    [d] = result.detections
    assert (d.source_class_name, d.source_class_id) == ("person", 0)
    assert d.ontology_version == "ksi-ontology-v1"


def test_conflicting_int_label_and_source_id_dropped() -> None:
    """[재검토 #2] label(int)≠source_class_id 자기모순 레코드는 MALFORMED drop."""
    result = _adapter().convert(
        [RawDetection(label=0, score=0.9, box=(10.0, 20.0, 110.0, 220.0), source_class_id=7)],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.MALFORMED_CLASS_LINEAGE
    assert "서로 다른 원시 클래스" in dropped.detail


def test_matching_int_label_and_source_id_accepted() -> None:
    """일치하는 중복 선언은 정상 — 모순만 죽인다."""
    result = _adapter().convert(
        [RawDetection(label=0, score=0.9, box=(10.0, 20.0, 110.0, 220.0), source_class_id=0)],
        width=_W,
        height=_H,
    )
    [d] = result.detections
    assert d.source_class_id == 0


# ── 최종 재검토 P0 반증 (2026-07-28): 검증 후 mutation 차단 ──────────────────


def test_mapping_snapshot_isolated_from_caller_dict() -> None:
    """[반증 1·4] 생성 후 원본 dict 를 바꿔도 OntologyMapping 은 변하지 않는다."""
    mappings = {"person": "Person"}
    ids = {0: "person"}
    ontology = OntologyMapping(
        version="ksi-ontology-v1",
        source_taxonomy="COCO-2017",
        mappings=mappings,
        id_to_name=ids,
    )
    mappings["truck"] = "Vehicle_Truck"  # 검증 후 승인 범위 확장 시도
    ids[7] = "truck"
    assert "truck" not in ontology.mappings
    assert 7 not in ontology.id_to_name


def test_mapping_direct_mutation_is_typeerror() -> None:
    """[반증 2] ontology.mappings 직접 변경은 TypeError (읽기 전용 뷰)."""
    with pytest.raises(TypeError):
        COCO_ONTOLOGY.mappings["truck"] = "Person"  # type: ignore[index]
    with pytest.raises(TypeError):
        COCO_ONTOLOGY.id_to_name[7] = "truck"  # type: ignore[index]


def test_adapter_unaffected_by_post_validation_dict_expansion() -> None:
    """[반증 3] Person-only 로 검증받은 뒤 원본에 truck 을 추가해도 adapter 는
    UNKNOWN_LABEL — "검증 시점 내용 = 사용 시점 내용" 이 성립한다."""
    mappings = {"person": "Person"}
    ontology = OntologyMapping(
        version="ksi-ontology-v1",
        source_taxonomy="COCO-2017",
        mappings=mappings,
        id_to_name={0: "person"},
    )
    adapter = _adapter(ontology=ontology)
    mappings["truck"] = "Vehicle_Truck"  # 사후 확장 시도
    result = adapter.convert(
        [RawDetection(label="truck", score=0.9, box=(10.0, 20.0, 110.0, 220.0))],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.UNKNOWN_LABEL


def test_bool_id_key_rejected_in_mapping() -> None:
    """[반증 5] bool id 키(False==0)는 OntologyMapping 생성에서 거부된다."""
    with pytest.raises(ValueError, match="bool"):
        OntologyMapping(
            version="ksi-ontology-v1",
            source_taxonomy="COCO-2017",
            mappings={"person": "Person"},
            # bool 은 int 서브클래스라 mypy 를 통과한다 — 런타임 거부가 유일한 방어.
            id_to_name={False: "person"},
        )


def test_unsupported_label_with_unregistered_id_is_unknown_not_malformed() -> None:
    """[B1-7 실측 회귀] 미지원 라벨 + 미등록 id(예: "cell phone"/67)는 자기모순이
    아니라 미지원(UNKNOWN_LABEL)이다 — 모순 판정은 승격 대상에만 의미가 있다."""
    result = _adapter().convert(
        [
            RawDetection(
                label="cell phone", score=0.9, box=(10.0, 20.0, 110.0, 220.0),
                source_class_id=67,
            )
        ],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.UNKNOWN_LABEL


def test_supported_label_with_wrong_id_still_malformed() -> None:
    """승격 대상(person)이 다른 원시 클래스 id 를 달고 있으면 여전히 자기모순 drop."""
    result = _adapter().convert(
        [
            RawDetection(
                label="person", score=0.9, box=(10.0, 20.0, 110.0, 220.0),
                source_class_id=999,
            )
        ],
        width=_W,
        height=_H,
    )
    assert result.detections == []
    [dropped] = result.dropped
    assert dropped.reason is DropReason.MALFORMED_CLASS_LINEAGE
