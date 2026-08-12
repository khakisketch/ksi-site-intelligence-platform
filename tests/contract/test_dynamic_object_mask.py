"""탐지 결과 → 동적 객체 영역 배열 계약 (PRD §15.2 ④, phase2-dynamic-object-masking).

이 파일은 :mod:`ksi_perception.dynamic_object_mask` 만 본다 — 순수 numpy
함수라 모델 파일도 [dfine] extra 도 필요 없다(항상 실행). ODM/NodeODM 파일명·
폴라리티 규약은 여기 없다 — 그건 실물로 검증된 별도 사실이고
``tests/contract/test_odm_masking.py`` 가 담당한다.
"""

from __future__ import annotations

import numpy as np
import pytest
from ksi_domain.detection import BoundingBox, Detection
from ksi_domain.ontology import COCO_ID_TO_NAME, COCO_TO_CANONICAL
from ksi_perception.dynamic_object_mask import (
    DYNAMIC_OBJECT_CLASSES,
    dynamic_object_regions,
)

_W, _H = 100, 80

# canonical → (원시 라벨명, 원시 id) — 계보 자기모순 검증을 통과하는 실제 값.
_CANONICAL_TO_SOURCE = {
    canonical: (name, source_id)
    for source_id, name in COCO_ID_TO_NAME.items()
    for canonical in [COCO_TO_CANONICAL[name]]
}


def _detection(
    detection_class: str = "Person",
    *,
    x_min: float = 10.0,
    y_min: float = 20.0,
    x_max: float = 30.0,
    y_max: float = 60.0,
) -> Detection:
    source_name, source_id = _CANONICAL_TO_SOURCE[detection_class]
    return Detection(
        detection_class=detection_class,
        confidence=0.9,
        bbox=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
        source_class_id=source_id,
        source_class_name=source_name,
    )


def test_empty_detections_yield_an_all_clear_region() -> None:
    """[핵심 대조] 사람이 없으면 마스킹 영역도 없다."""
    regions = dynamic_object_regions([], width=_W, height=_H)
    assert regions.shape == (_H, _W)
    assert regions.dtype == np.bool_
    assert not regions.any()


def test_a_person_detection_marks_its_bbox_region() -> None:
    """[핵심 대조] 사람이 있으면 그 bbox 영역만 True 다 — 나머지는 그대로 False."""
    det = _detection(x_min=10, y_min=20, x_max=30, y_max=60)
    regions = dynamic_object_regions([det], width=_W, height=_H)

    assert regions.any()
    assert regions[20:60, 10:30].all(), "bbox 내부가 전부 마스킹돼야 한다"
    assert not regions[0:20, :].any(), "bbox 밖(위쪽)은 마스킹되면 안 된다"
    assert not regions[:, 0:10].any(), "bbox 밖(왼쪽)은 마스킹되면 안 된다"


@pytest.mark.parametrize("cls", sorted(DYNAMIC_OBJECT_CLASSES))
def test_every_dynamic_class_is_masked(cls: str) -> None:
    """[비공허] 사람뿐 아니라 차량류(Vehicle_Car·Vehicle_Truck)도 마스킹된다."""
    regions = dynamic_object_regions([_detection(cls)], width=_W, height=_H)
    assert regions.any()


def test_classes_outside_the_allowlist_are_ignored() -> None:
    """[fail-closed] 호출자가 넘긴 목록에 없는 클래스는 조용히 건너뛴다.

    실제 ontology(v1)는 Person/Vehicle_Car/Vehicle_Truck 만 내므로 이 경로는
    호출자가 직접 좁힌 ``classes`` 인자를 쓸 때만 실제로 도달한다 — 그 좁힌
    사용법이 사고로 전체를 마스킹하지 않는지 확인한다.
    """
    det = _detection("Person")
    regions = dynamic_object_regions(
        [det], width=_W, height=_H, classes=frozenset({"Vehicle_Car"})
    )
    assert not regions.any()


def test_multiple_detections_union_their_regions() -> None:
    """여러 탐지가 있으면 영역이 합집합으로 쌓인다(겹쳐도 OR)."""
    a = _detection(x_min=0, y_min=0, x_max=10, y_max=10)
    b = _detection(x_min=50, y_min=50, x_max=60, y_max=60)
    regions = dynamic_object_regions([a, b], width=_W, height=_H)

    assert regions[0:10, 0:10].all()
    assert regions[50:60, 50:60].all()
    assert not regions[20:40, 20:40].any()


def test_bbox_extending_past_the_declared_frame_is_clipped_not_dropped() -> None:
    """호출자가 다른 프레임 크기의 탐지를 실수로 섞어 넣어도 죽지 않는다 —
    자기 크기로 다시 clip 하고, clip 후 남는 영역만 마스킹한다."""
    det = _detection(x_min=90.0, y_min=70.0, x_max=150.0, y_max=200.0)  # 프레임 밖으로 넘침
    regions = dynamic_object_regions([det], width=_W, height=_H)

    assert regions[70:80, 90:100].all(), "프레임 안에 남는 부분은 마스킹된다"
    assert regions.shape == (_H, _W)


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, 0), (-1, 10)])
def test_non_positive_frame_size_is_a_caller_contract_violation(
    width: int, height: int
) -> None:
    """비양수 크기는 개별 탐지의 문제가 아니라 호출자 버그다 — 예외로 남긴다."""
    with pytest.raises(ValueError):
        dynamic_object_regions([], width=width, height=height)
