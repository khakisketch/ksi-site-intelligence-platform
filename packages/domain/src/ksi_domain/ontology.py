"""Versioned Ontology — 모델 원시 Class → Canonical Entity Class (INV-031, F13).

## 왜 별도 계층인가

모델의 원시 라벨("person", COCO id 0)과 KSI 도메인 클래스("Person")를 같은
문자열로 취급하면 모델 교체(D-FINE-N·RT-DETRv2 fallback, 자체 fine-tune) 시
의미가 흔들린다 — 어떤 모델의 어떤 라벨이 어떤 도메인 의미로 번역됐는지는
**버전 있는 명시적 매핑**이어야 하고, 그 버전이 Observation·WorldEntity 계보에
남아야 한다(INV-042 모델 계보와 같은 원칙의 분류 축).

## SSOT 는 선언이 아니라 강제다 (독립 재검토 Blocker 1, 2026-07-28)

초판은 이 모듈을 "SSOT"라 부르면서 실제 배선은 자유 dict(class_map)를 받았다 —
``{"truck": "Person"}`` 을 주입하면 트럭이 Person Entity 가 되는 F13 경로가
설정 한 줄로 다시 열렸다. 지금은 :class:`OntologyMapping` 이 생성 시점에 자신을
이 모듈의 등록부와 대조 검증하며, adapter·loader 는 자유 dict 를 받지 않는다.

## Fail-closed

- 매핑에 없는 원시 클래스는 canonical class 를 얻지 못한다 — 어떤 경우에도
  Person 등 다른 의미로 fallback 하지 않는다(INV-031).
- 등록되지 않은 ontology 버전은 해석 불가로 거부된다(Blocker 4) — "모두가 같은
  미등록 버전"도 통과하지 못한다. 새 버전은 이 모듈에 등록해 확장한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

# Ontology 버전 — 매핑 내용이 바뀌면 반드시 올린다. Observation·산출물 계보에
# 이 값이 박혀 "그 시점의 번역 규칙"을 재현할 수 있어야 한다.
ONTOLOGY_VERSION = "ksi-ontology-v1"

# 해석 가능한 버전 등록부 — 여기 없는 버전의 분류 주장은 어떤 계층에서도 해석하지
# 않는다(Blocker 4). v2 가 생기면 여기 등록하고 버전별 매핑을 분기한다.
#
# ⚠ 두 번째 버전을 등록하는 변경은 **반드시 v1/v2 혼합 track 의
# ONTOLOGY_VERSION_MISMATCH 반증 테스트를 동반해야 한다**(대표자 조건 2026-07-28).
# 그 경로는 등록 버전이 1개인 동안 도달 불가능한 잠재 방어라 지금은 테스트가 없다 —
# test_world_entity_assembly 의 등록부 앵커 테스트가 이 조건을 깨지는 형태로 고정한다.
REGISTERED_ONTOLOGY_VERSIONS = frozenset({ONTOLOGY_VERSION})

# KSI Canonical Entity Class 집합 (ksi-ontology-v1).
# 중장비(굴착기·타워크레인 등)는 COCO 에 없어 자체 fine-tune 후 v2 에서 추가된다
# (MODEL-B1-001 production_gate — 권리 정리된 데이터 확보 이후).
CANONICAL_CLASSES = frozenset({"Person", "Vehicle_Car", "Vehicle_Truck"})

# v1 의 source taxonomy — 현재 유일 등록. 자체 fine-tune 라벨 체계가 생기면 확장.
COCO_TAXONOMY = "COCO-2017"

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

# v1 이 소비하는 COCO 클래스의 원시 index ↔ 이름 대응 (80-class 0-based 인덱싱,
# digest 고정 config 의 id2label 과 동일). 분류 계보(id·name)의 자기모순 대조표.
COCO_ID_TO_NAME: MappingProxyType[int, str] = MappingProxyType(
    {
        0: "person",
        2: "car",
        7: "truck",
    }
)


def resolve_coco_label(source_class_name: str) -> str | None:
    """COCO 라벨명 → Canonical Entity Class. 미지원이면 None (fallback 금지).

    반환 None 은 "모른다"가 아니라 "이 ontology 버전이 지원하지 않는다"다 —
    호출자는 이를 typed drop(UNKNOWN_LABEL 등)으로 기록해야 하며, 임의의
    canonical class 로 대체하면 INV-031 위반이다.
    """
    return COCO_TO_CANONICAL.get(source_class_name)


@dataclass(frozen=True)
class OntologyMapping:
    """검증된 번역 규칙 — adapter·loader 가 받는 **유일한** 매핑 형식.

    자유 dict 와 달리 생성 시점에 이 모듈의 등록부와 자신을 대조한다:
    등록된 버전·taxonomy 인지, canonical 값이 등록 집합에 속하는지, 각 pair 가
    taxonomy 의 권위 해석(:func:`resolve_coco_label`)과 일치하는지. 통과하지
    못하는 매핑(예: ``{"truck": "Person"}``)은 객체가 만들어지지 않는다.

    Attributes:
        version: 등록된 ontology 버전.
        source_taxonomy: 원시 라벨 체계 식별자(현재 ``COCO-2017`` 만 등록).
        mappings: 원시 라벨명 → canonical. **권위 매핑의 부분집합만 허용**된다 —
            소비 범위를 좁힐 수는 있어도 의미를 바꿀 수는 없다.
        id_to_name: 원시 index → 라벨명(계보 자기모순 대조용). 권위 대응의
            부분집합만 허용.
    """

    version: str
    source_taxonomy: str
    mappings: Mapping[str, str]
    id_to_name: Mapping[int, str]

    def __post_init__(self) -> None:
        # 검증 대상은 호출자 참조가 아니라 **스냅샷**이다(최종 재검토 P0, 2026-07-28) —
        # frozen 은 필드 재할당만 막고 내부 dict 변경은 막지 못하므로, 호출자가 원본
        # dict 를 쥐고 있으면 "검증 후 승인 범위 확장"(Person-only 로 검증받고 나중에
        # truck 추가)이 가능했다. 스냅샷을 검증하고 읽기 전용 뷰로 보관해 검증 시점과
        # 사용 시점의 내용이 항상 같게 만든다.
        mappings = dict(self.mappings)
        id_to_name = dict(self.id_to_name)

        if self.version not in REGISTERED_ONTOLOGY_VERSIONS:
            raise ValueError(
                f"미등록 ontology 버전 {self.version!r} — 등록부: "
                f"{sorted(REGISTERED_ONTOLOGY_VERSIONS)}"
            )
        if self.source_taxonomy != COCO_TAXONOMY:
            raise ValueError(
                f"미등록 taxonomy {self.source_taxonomy!r} — 현재 등록: {COCO_TAXONOMY!r}"
            )
        if not mappings:
            raise ValueError("mappings 가 비어 있다 — 소비할 클래스가 없으면 매핑이 무의미하다")
        for name, canonical in mappings.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"원시 라벨명은 공백 아닌 str 이어야 한다 ({name!r})")
            if canonical not in CANONICAL_CLASSES:
                raise ValueError(
                    f"{canonical!r} 는 등록된 Canonical Class 가 아니다 "
                    f"(등록: {sorted(CANONICAL_CLASSES)})"
                )
            authoritative = resolve_coco_label(name)
            if authoritative != canonical:
                raise ValueError(
                    f"매핑 {name!r} → {canonical!r} 가 권위 해석({name!r} → "
                    f"{authoritative!r})과 다르다 — 의미 변경은 새 버전 등록으로만 가능"
                )
        for source_id, name in id_to_name.items():
            # bool 은 int 의 subclass 라 False==0/True==1 로 권위 대응 조회를 조용히
            # 통과한다 — 키 타입을 순수 int 로 강제한다(최종 재검토 P0 동반 검사).
            if isinstance(source_id, bool) or not isinstance(source_id, int):
                raise ValueError(f"원시 id 키는 bool 아닌 int 여야 한다 ({source_id!r})")
            if COCO_ID_TO_NAME.get(source_id) != name:
                raise ValueError(
                    f"id 대응 {source_id} → {name!r} 가 권위 대응"
                    f"({source_id} → {COCO_ID_TO_NAME.get(source_id)!r})과 다르다"
                )

        # 소비하는 각 이름은 id 대응을 가져야 한다(반증 리뷰 F-L) — 실모델은 항상
        # source_class_id 를 채우므로, id_to_name 이 비면 승격 대상 전건이 계보
        # 자기모순(MALFORMED_CLASS_LINEAGE)으로 죽는 오도된 구성이 된다. 구성
        # 불완전은 생성 시점의 사유로 거부한다.
        name_to_id = {v: k for k, v in COCO_ID_TO_NAME.items()}
        for name in mappings:
            required_id = name_to_id.get(name)
            if required_id is not None and required_id not in id_to_name:
                raise ValueError(
                    f"매핑이 {name!r} 를 소비하는데 id_to_name 에 대응 id({required_id})가 "
                    "없다 — 실모델 경로에서 전건이 계보 모순으로 죽는 불완전 구성"
                )

        # 검증을 통과한 스냅샷만 읽기 전용으로 보관 — 직접 변경은 TypeError,
        # 호출자의 원본 dict 변경은 이 객체에 반영되지 않는다.
        object.__setattr__(self, "mappings", MappingProxyType(mappings))
        object.__setattr__(self, "id_to_name", MappingProxyType(id_to_name))


# 표준 인스턴스 — D-FINE COCO-only 경로의 기본 매핑(권위 전체 집합).
COCO_ONTOLOGY = OntologyMapping(
    version=ONTOLOGY_VERSION,
    source_taxonomy=COCO_TAXONOMY,
    mappings=COCO_TO_CANONICAL,
    id_to_name=COCO_ID_TO_NAME,
)


def classification_lineage_error(
    *,
    canonical: str,
    ontology_version: str,
    source_class_name: str | None,
    source_class_id: int | None,
) -> str | None:
    """분류 계보의 자기모순 사유를 반환한다(None = 정합).

    Detection·Observation 계약과 assembly 2차 방어가 공용하는 판정이다 —
    ``Detection(detection_class="Person", source_class_name="truck")`` 같은
    자기모순 레코드를 어느 계층에서든 같은 규칙으로 거부한다(Blocker 1·3).
    """
    if ontology_version not in REGISTERED_ONTOLOGY_VERSIONS:
        return (
            f"미등록 ontology 버전 {ontology_version!r} — 해석 불가"
            f"(등록: {sorted(REGISTERED_ONTOLOGY_VERSIONS)})"
        )
    if canonical not in CANONICAL_CLASSES:
        return f"{canonical!r} 는 등록된 Canonical Class 가 아니다"
    if source_class_name is not None:
        resolved = resolve_coco_label(source_class_name)
        if resolved != canonical:
            return (
                f"원시 라벨 {source_class_name!r} 의 권위 해석은 {resolved!r} 인데 "
                f"canonical 이 {canonical!r} 다 — 계보 자기모순"
            )
    if source_class_id is not None:
        id_name = COCO_ID_TO_NAME.get(source_class_id)
        if id_name is None:
            return f"원시 id {source_class_id} 는 v1 taxonomy 에 등록돼 있지 않다"
        if source_class_name is not None and id_name != source_class_name:
            return (
                f"원시 id {source_class_id} 의 이름은 {id_name!r} 인데 "
                f"source_class_name 이 {source_class_name!r} 다 — 계보 자기모순"
            )
        if resolve_coco_label(id_name) != canonical:
            return (
                f"원시 id {source_class_id}({id_name!r}) 의 권위 해석과 "
                f"canonical {canonical!r} 이 다르다 — 계보 자기모순"
            )
    return None
