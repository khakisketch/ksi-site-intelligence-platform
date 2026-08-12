"""탐지 결과 → 동적 객체 영역 배열 (PRD §15.2 ④, phase2-dynamic-object-masking).

## 이 모듈이 아는 것과 모르는 것

여기서 만드는 것은 ``bool (height, width)`` 배열 하나뿐이다 — True 인 픽셀이
동적 객체(사람·차량) 탐지 bbox 안에 있다는 사실만 담는다. **재구성 엔진이
"제외" 를 흰색으로 표현하는지 검정으로 표현하는지, 마스크 파일명이 어떤
규약을 따라야 하는지는 이 모듈이 모른다** — 그건 소비하는 엔진(NodeODM/ODM)
고유의 REST·파일명 사실이라, 실기동으로 확인된 그 사실은
``ksi_processing_controller.odm_masking`` 이 갖는다(경계는 "탐지 도메인
지식" vs "엔진 wire 사실"). 이 분리 덕분에 이 모듈은 엔진이 Pix4D 등으로
바뀌어도 그대로 재사용된다.

## D-FINE-S 는 bbox 만 낸다 — 세그멘테이션이 아니다

:mod:`ksi_perception.dfine` 의 파이프라인(모듈 docstring)은
``RTDetrImageProcessor.post_process_object_detection`` 출력을 그대로 쓰고,
그 출력은 xyxy bbox 다(픽셀 단위 사각형). 사람의 실제 윤곽(가지·다리 사이
배경 등)까지 정밀 마스킹하려면 세그멘테이션 모델이 필요한데, 재사용 후보로
지정된 D-FINE-S 는 그 모델이 아니다(model-lineage-coco-residual 리스크가
받아들인 것은 D-FINE-S 탐지기 자체이지 별도 세그멘테이션 모델이 아니다 —
새 모델을 들이지 않는다는 이번 세션 지침과도 맞다). 그래서 마스크는 bbox
사각형이다 — 사람 실루엣보다 넓게 가려지는 과다마스킹(주변 배경까지 제외)이
있을 수 있지만, 사람을 놓치는 과소마스킹보다는 안전한 방향이다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from ksi_domain.detection import Detection

# PRD §15.2 ④가 말하는 "동적 객체(사람/차량 등)". ksi-ontology-v1 이 인식하는
# canonical class 전부가 우연히 이미 동적 개체다(ontology.py 의
# CANONICAL_CLASSES) — 그렇다고 여기서 ``CANONICAL_CLASSES`` 를 그대로 재사용
# 하지 않는다. ontology v2 가 중장비(굴착기·타워크레인 등 **정적** 설비)를
# 추가하면 그 즉시 "정적 설비까지 마스킹"으로 조용히 새는 경로가 생기기
# 때문이다(ontology.py 모듈 docstring 참고) — 이 목록은 그 확장과 독립으로
# 유지해야 하는 명시적 선택이다.
DYNAMIC_OBJECT_CLASSES: frozenset[str] = frozenset(
    {"Person", "Vehicle_Car", "Vehicle_Truck"}
)


def dynamic_object_regions(
    detections: Sequence[Detection],
    *,
    width: int,
    height: int,
    classes: frozenset[str] = DYNAMIC_OBJECT_CLASSES,
) -> np.ndarray:
    """탐지 목록 → ``bool (height, width)`` 배열(True = 동적 객체 bbox 내부).

    ``classes`` 에 없는 ``detection_class`` 는 조용히 건너뛴다 — 이미 걸러진
    입력(예: person 만 필터링된 목록)을 넘겨도 안전하다는 뜻이지, 필터링을
    생략해도 된다는 뜻은 아니다(호출자가 이미 정규화된 :class:`Detection`
    전체를 그대로 넘기는 것이 기본 사용법이다).

    ``Detection.bbox`` 는 이미 :class:`~ksi_domain.detection_adapter.
    DetectionAdapter` 가 프레임 경계로 클리핑한 값이다(fail-closed 정규화가
    이미 끝난 입력을 전제) — 그래도 이 함수는 자신의 ``width``/``height`` 로
    다시 한번 clip 한다. 호출자가 다른 이미지의 탐지를 실수로 섞어 넣는
    호출자 버그를 조용히 통과시키지 않기 위해서다(clip 후 면적 0 이면 그냥
    무시한다 — 개별 탐지 하나가 배치를 죽이면 안 된다는 이 저장소의
    fail-closed 관용구와 동형이되, 여기는 실패 기록이 필요 없는 순수 기하
    연산이라 그 처리 자체를 조용히 생략하는 것으로 충분하다).
    """
    if not (isinstance(width, int) and isinstance(height, int)) or width <= 0 or height <= 0:
        raise ValueError(f"이미지 크기는 양의 int 여야 한다 ({width!r}x{height!r})")

    regions = np.zeros((height, width), dtype=bool)
    for det in detections:
        if det.detection_class not in classes:
            continue
        x0 = max(0, math.floor(det.bbox.x_min))
        y0 = max(0, math.floor(det.bbox.y_min))
        x1 = min(width, math.ceil(det.bbox.x_max))
        y1 = min(height, math.ceil(det.bbox.y_max))
        if x1 > x0 and y1 > y0:
            regions[y0:y1, x0:x1] = True
    return regions


__all__ = ["DYNAMIC_OBJECT_CLASSES", "dynamic_object_regions"]
