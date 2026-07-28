"""B1-7 — Recorded 입력 + 실 D-FINE 으로 Vertical Slice 전 구간 재현.

승인 순서(독립 재검토 PASS 2026-07-28)의 실행물::

    Recorded single image → Recorded frame sequence
      → D-FINE Detection → Tracking → Projection
      → Observation → WorldEntity → Event policy → Evidence Bundle

모델 파일·[dfine] extra 가 있을 때만 실행된다(CI 는 skip — 분리된 게이트,
test_dfine_detector 와 동일 규약). stub 슬라이스 테스트(test_vertical_slice)가
배선 계약을 상시 고정하고, 이 파일은 **실모델이 그 배선을 실제로 태우는지**를
모델 보유 환경에서 고정한다.

여기서 증명하는 것: 실모델 분류가 계보 그대로 Entity·Event 까지 흐른다 / 2회
실행이 동일 fingerprint 다 / detector 단계 탈락이 typed 로 기록된다.
증명하지 않는 것: 모델 정확도 일반화(단일 PD 이미지다) · 실기 타이밍 · Manifold
성능(B2). 실제 드론 녹화 영상 corpus 는 확보 시 이 파일의 시퀀스 소스만 바꿔
확장한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from ksi_domain.enums import EventStatus
from ksi_perception.dfine import RecordedFrameDetector, load_dfine_detector
from ksi_perception.recorded import load_frame_sequence, sequence_dimensions
from ksi_perception.registry import load_model_entry
from vertical_slice import (
    SliceFrame,
    SliceResult,
    SliceStage,
    run_vertical_slice,
    synthetic_telemetry,
)

_MODEL_ID = "ksi-person-detector-dfine-s-coco"
_PERSON_IMAGE = Path("models/test-assets/person.jpg")


def _model_dir() -> Path:
    check = load_model_entry(_MODEL_ID)
    if not check.ok or check.entry is None:
        return Path("models/__registry_unreadable__")
    return Path("models") / check.entry.weights_source.rsplit("/", 1)[-1] / check.entry.revision


_HAS_RUNTIME = (
    importlib.util.find_spec("torch") is not None
    and importlib.util.find_spec("transformers") is not None
)

pytestmark = pytest.mark.skipif(
    not (_HAS_RUNTIME and _model_dir().is_dir() and _PERSON_IMAGE.is_file()),
    reason="[dfine] extra·모델·녹화 이미지 없음 — tools/fetch_model.py 후 실행",
)


def _run_recorded_slice() -> SliceResult:
    """녹화 시퀀스(단일 이미지 3프레임 재생) + 실 D-FINE 으로 슬라이스 실행.

    같은 이미지의 반복은 '정지 장면 녹화'와 등가다 — 프레임 소스 교체(B3 Live
    View) 전까지의 recorded 경로 검증으로 충분하며, 시간축 변화는 실 영상 corpus
    확보 시 확장한다.
    """
    # min_confidence 는 명시적 선택이다(adapter 철학) — 기본 0.0 으로 두면 300
    # query 의 저신뢰 노이즈가 수백 개의 독립 track/Entity/Event 로 폭주한다
    # (실측: threshold 없이 Person Entity 158개). 0.5 는 이 PD 이미지의 실제 인물
    # 1명을 남기는 실운용급 문턱이며, 실기 배포값은 HIL 측정으로 확정한다.
    loaded = load_dfine_detector(local_dir=_model_dir(), min_confidence=0.5)
    assert loaded.ok, loaded.detail
    assert loaded.detector is not None

    frames = load_frame_sequence([_PERSON_IMAGE, _PERSON_IMAGE, _PERSON_IMAGE])
    width, height = sequence_dimensions(frames)
    detector = RecordedFrameDetector(frames=frames, dfine=loaded.detector)
    timestamps = [0.0, 0.2, 0.4]
    return run_vertical_slice(
        frames=[
            SliceFrame(frame_id=i, capture_ts_utc=ts, width=width, height=height)
            for i, ts in enumerate(timestamps)
        ],
        detector=detector,
        telemetry=synthetic_telemetry(timestamps),
        drone_position=(100.0, 200.0, 60.0),
        model_version="dfine-s-coco@f79e65b5",
    )


@pytest.fixture(scope="module")
def slice_result() -> SliceResult:  # 모듈 스코프 — 실추론 3프레임을 1회만
    return _run_recorded_slice()


def test_recorded_person_flows_to_person_event(slice_result: SliceResult) -> None:
    """[B1-7 핵심] 녹화 이미지의 실모델 person 분류가 Entity·Event 까지 흐른다."""
    result = slice_result
    assert result.observations, "실모델이 관측을 만들지 못했다 — 전 구간이 공허하다"
    person_obs = [o for o in result.observations if o.observed_class == "Person"]
    assert person_obs, "Person 관측 0건"
    # 분류 계보가 실모델 원시 출력에서 유래했는지(상수 주입이 아니라).
    assert all(o.source_class_name == "person" for o in person_obs)
    assert all(o.source_class_id == 0 for o in person_obs)
    assert all(o.ontology_version == "ksi-ontology-v1" for o in person_obs)

    person_entities = [e for e in result.entities if e.entity_class == "Person"]
    # 이 사진(Migrant Mother)에는 어머니+아이들 복수 인물이 있다 — threshold 0.5
    # 실측은 4건(명확한 인물 2 + 아이/중복 박스 2, conf 0.88/0.83/0.57/0.52).
    # 정확 개수는 모델 스냅샷 고정이라 의미 단정이 아니므로, 여기서는 "탐지가
    # 실재하고 노이즈 폭주(threshold 0.0 실측 158개)가 아니다"만 고정한다.
    # DETR 류의 중복 박스 억제는 threshold 로 불완전하며 그 개선은 B2 이후의 몫.
    assert 1 <= len(person_entities) <= 8, (
        f"Person Entity {len(person_entities)}개 — 0이면 배선 죽음, 수십 개면 "
        "threshold 무력화(노이즈 폭주 회귀)"
    )
    entity = person_entities[0]
    assert entity.lineage.classification_ontology_version == "ksi-ontology-v1"
    assert entity.lineage.classification_source is not None
    assert "person" in entity.lineage.classification_source.source_class_names

    assert result.bundles, "Event Bundle 0건"
    assert all(b.event_type == "PERSON_PRESENT" for b in result.bundles)
    assert all(b.status is EventStatus.CANDIDATE for b in result.bundles), (
        "단일 슬라이스 실행이 사건을 확정했다(INV-022 위반)"
    )


def test_recorded_slice_never_promotes_confirmed(slice_result: SliceResult) -> None:
    """[INV-025] 녹화 슬라이스의 viewpoint 는 SPATIAL_BIN — CONFIRMED 도달 불가."""
    result = slice_result
    for entity in result.entities:
        assert entity.uncertainty.localization_state != "CONFIRMED"


def test_recorded_slice_is_deterministic() -> None:
    """[P0-6] 같은 녹화 입력 2회 실행 → 동일 entity fingerprint·이벤트·탈락 기록."""
    first = _run_recorded_slice()
    second = _run_recorded_slice()
    assert first.entity_fingerprints() == second.entity_fingerprints()
    assert [b.event_type for b in first.bundles] == [b.event_type for b in second.bundles]
    assert [(d.frame_id, d.stage, d.reason) for d in first.dropped] == [
        (d.frame_id, d.stage, d.reason) for d in second.dropped
    ]


def test_detector_stage_drops_are_recorded(slice_result: SliceResult) -> None:
    """[B1-7 배선] detector 단계의 typed drop 이 SliceResult 에 흡수된다.

    실이미지에는 ontology 미지원 COCO 클래스(의자·책 등)가 흔히 함께 탐지된다 —
    그 탈락이 조용히 사라지지 않고 DETECTION 단계 기록으로 남는지 확인한다.
    기록이 0건이면 이 장면에 미지원 탐지가 없었던 것이므로 기록 형식만 검증한다.
    """
    result = slice_result
    detection_drops = [d for d in result.dropped if d.stage is SliceStage.DETECTION]
    for drop in detection_drops:
        assert drop.track_id == "(pre-track)"
        assert drop.reason, "탈락 사유가 비어 있다"
    # 비공허성 확인은 unknown_label 존재 시에만 — 장면 의존이라 강제하지 않는다.
    # (미지원 클래스 탈락의 기계적 검증은 stub 경로의 상시 테스트가 담당.)