"""EventBundle v1.2 standalone classification lineage 계약 (INV-031).

EventBundle 이 WorldEntity 와 분리되어 Core 에 단독 전송돼도 분류 계보가 검증
가능해야 한다 — 여기서는 **bundle 단독** round-trip 과 변조 반증만 다룬다
(파이프라인이 계보를 채우는 정상 경로는 tests/replay 가 고정한다).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from ksi_domain.enums import EventStatus
from ksi_event_contracts.event_bundle import (
    ClassificationLineage,
    EventBundle,
    Evidence,
    Lineage,
)
from ksi_event_contracts.world_entity import ClassificationSource
from pydantic import ValidationError

_FPR = "a" * 64


def _classification(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entityClass": "Person",
        "ontologyVersion": "ksi-ontology-v1",
        "source": {
            "taxonomy": "COCO-2017",
            "sourceClassIds": [0],
            "sourceClassNames": ["person"],
        },
        "entityFingerprint": _FPR,
    }
    payload.update(overrides)
    return payload


def _bundle_payload() -> dict[str, Any]:
    return {
        "schemaVersion": "1.2",
        "eventId": "evt-ent-trk-001",
        "missionId": "mission-1",
        "siteId": "site-1",
        "eventType": "PERSON_PRESENT",
        "occurredAt": "2026-07-27T06:00:00Z",
        "status": "CANDIDATE",
        "entities": ["ent-trk-001"],
        "spatialContext": {},
        "reasoning": {},
        "evidence": {},
        "lineage": {
            "edgeVersion": "slice-0.0.1",
            "modelVersions": {"detector": "stub"},
            "policyVersion": "slice-policy-0",
            "calibrationProfileId": "slice-cal-0",
            "classification": {"ent-trk-001": _classification()},
        },
    }


def _build() -> EventBundle:
    return EventBundle.model_validate(_bundle_payload())


# ── 단독 round-trip: 계보 유지 ───────────────────────────────────────────────


def test_standalone_roundtrip_preserves_classification_lineage() -> None:
    """serialize → deserialize 후에도 bundle 단독으로 계보가 온전하다."""
    bundle = _build()
    revived = EventBundle.model_validate_json(bundle.model_dump_json(by_alias=True))
    lineage = revived.lineage.classification["ent-trk-001"]
    assert lineage.entity_class == "Person"
    assert lineage.ontology_version == "ksi-ontology-v1"
    assert lineage.source.source_class_names == ["person"]
    assert lineage.entity_fingerprint == _FPR
    assert revived == bundle


def test_python_construction_equals_json_construction() -> None:
    """snake_case 생성과 camelCase JSON 로드가 같은 계약이다(populate_by_name)."""
    built = EventBundle(
        event_id="evt-ent-trk-001",
        mission_id="mission-1",
        site_id="site-1",
        event_type="PERSON_PRESENT",
        occurred_at=datetime(2026, 7, 27, 6, 0, 0, tzinfo=UTC),
        status=EventStatus.CANDIDATE,
        entities=["ent-trk-001"],
        spatial_context={},
        reasoning={},
        evidence=Evidence(),
        lineage=Lineage(
            edge_version="slice-0.0.1",
            model_versions={"detector": "stub"},
            policy_version="slice-policy-0",
            calibration_profile_id="slice-cal-0",
            classification={
                "ent-trk-001": ClassificationLineage(
                    entity_class="Person",
                    ontology_version="ksi-ontology-v1",
                    source=ClassificationSource(
                        taxonomy="COCO-2017", source_class_ids=[0], source_class_names=["person"]
                    ),
                    entity_fingerprint=_FPR,
                )
            },
        ),
    )
    assert built == _build()


# ── 변조·누락은 typed 거부다 ────────────────────────────────────────────────


def test_missing_classification_field_rejected() -> None:
    """v1.2 에서 classification 자체가 없는 lineage 는 검증 실패다(v1.1 결함 재발 방지)."""
    payload = _bundle_payload()
    del payload["lineage"]["classification"]
    with pytest.raises(ValidationError):
        EventBundle.model_validate(payload)


def test_entity_without_lineage_entry_rejected() -> None:
    """entities 에 있는 entity 의 계보 누락 — 계보 없는 이벤트 대상 금지."""
    payload = _bundle_payload()
    payload["lineage"]["classification"] = {}
    with pytest.raises(ValidationError, match="누락"):
        EventBundle.model_validate(payload)


def test_surplus_lineage_entry_rejected() -> None:
    """entities 에 없는 entity 의 계보 편승 — 검증 불가 데이터의 무단 진입 금지."""
    payload = _bundle_payload()
    payload["lineage"]["classification"]["ent-ghost"] = _classification()
    with pytest.raises(ValidationError, match="잉여"):
        EventBundle.model_validate(payload)


def test_unregistered_ontology_version_rejected() -> None:
    payload = _bundle_payload()
    payload["lineage"]["classification"]["ent-trk-001"] = _classification(
        ontologyVersion="attacker-v99"
    )
    with pytest.raises(ValidationError, match="미등록 ontology"):
        EventBundle.model_validate(payload)


def test_blank_entity_class_rejected() -> None:
    payload = _bundle_payload()
    payload["lineage"]["classification"]["ent-trk-001"] = _classification(
        entityClass="   "
    )
    with pytest.raises(ValidationError, match="공백"):
        EventBundle.model_validate(payload)


def test_empty_source_ids_or_names_rejected() -> None:
    for source in (
        {"taxonomy": "COCO-2017", "sourceClassIds": [], "sourceClassNames": ["person"]},
        {"taxonomy": "COCO-2017", "sourceClassIds": [0], "sourceClassNames": []},
    ):
        payload = _bundle_payload()
        payload["lineage"]["classification"]["ent-trk-001"] = _classification(
            source=source
        )
        with pytest.raises(ValidationError, match="비어 있다"):
            EventBundle.model_validate(payload)


def test_malformed_fingerprint_rejected() -> None:
    """fingerprint 는 world_entity_fingerprint 산출 형식(hex64)만 — 자유 문자열 금지."""
    for bad in ("", "not-a-hash", "A" * 64, "a" * 63):
        payload = _bundle_payload()
        payload["lineage"]["classification"]["ent-trk-001"] = _classification(
            entityFingerprint=bad
        )
        with pytest.raises(ValidationError, match="hex64"):
            EventBundle.model_validate(payload)


def test_v11_schema_version_rejected() -> None:
    """v1.1 표기 bundle 은 이 모델의 계약이 아니다 — 버전 위장 금지."""
    payload = _bundle_payload()
    payload["schemaVersion"] = "1.1"
    with pytest.raises(ValidationError):
        EventBundle.model_validate(payload)
