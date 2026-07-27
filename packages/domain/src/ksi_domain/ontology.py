"""Versioned Ontology — 모델 원시 Class → Canonical Entity Class (INV-031, F13).

## 왜 별도 계층인가

모델의 원시 라벨("person", COCO id 0)과 KSI 도메인 클래스("Person")를 같은
문자열로 취급하면 모델 교체(D-FINE-N·RT-DETRv2 fallback, 자체 fine-tune) 시
의미가 흔들린다 — 어떤 모델의 어떤 라벨이 어떤 도메인 의미로 번역됐는지는
**버전 있는 명시적 매핑**이어야 하고, 그 버전이 Observation·WorldEntity 계보에
남아야 한다(INV-042 모델 계보와 같은 원칙의 분류 축).

## Fail-closed

매핑에 없는 원시 클래스는 canonical class 를 얻지 못한다 — 어떤 경우에도
Person 등 더 강한 의미로 fallback 하지 않는다(INV-031). 미지원 클래스의 탈락
기록은 DetectionAdapter 의 UNKNOWN_LABEL drop 이 담당한다(조용한 소멸 금지).
"""

from __future__ import annotations

from types import MappingProxyType

# Ontology 버전 — 매핑 내용이 바뀌면 반드시 올린다. Observation·산출물 계보에
# 이 값이 박혀 "그 시점의 번역 규칙"을 재현할 수 있어야 한다.
ONTOLOGY_VERSION = "ksi-ontology-v1"

# KSI Canonical Entity Class 집합 (ksi-ontology-v1).
# 중장비(굴착기·타워크레인 등)는 COCO 에 없어 자체 fine-tune 후 v2 에서 추가된다
# (MODEL-B1-001 production_gate — 권리 정리된 데이터 확보 이후).
CANONICAL_CLASSES = frozenset({"Person", "Vehicle_Car", "Vehicle_Truck"})

# COCO 라벨명 → Canonical. D-FINE COCO-only 체크포인트의 id2label 라벨명 기준
# (config.json 이 digest 로 고정돼 라벨명도 고정된 사실이다 — Registry 참조).
# 여기 없는 COCO 클래스(자전거·개·신호등 …)는 의도적 미지원이다.
COCO_TO_CANONICAL: MappingProxyType[str, str] = MappingProxyType(
    {
        "person": "Person",
        "car": "Vehicle_Car",
        "truck": "Vehicle_Truck",
    }
)


def resolve_coco_label(source_class_name: str) -> str | None:
    """COCO 라벨명 → Canonical Entity Class. 미지원이면 None (fallback 금지).

    반환 None 은 "모른다"가 아니라 "이 ontology 버전이 지원하지 않는다"다 —
    호출자는 이를 typed drop(UNKNOWN_LABEL 등)으로 기록해야 하며, 임의의
    canonical class 로 대체하면 INV-031 위반이다.
    """
    return COCO_TO_CANONICAL.get(source_class_name)
