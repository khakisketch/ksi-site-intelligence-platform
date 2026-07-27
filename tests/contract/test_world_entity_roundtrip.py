"""WorldEntity/Observation 계약 검증 (Stage C-1).

WorldEntity는 ``contracts/schemas/world-entity.v1.json``이 SSOT이므로 P0-1과 동일하게
모델 dump → jsonschema 왕복을 검증한다. Observation은 대응 JSON Schema가 없어
(``ksi_event_contracts.observation`` 모듈 docstring 참고) 필드 불변식만 검증한다.

INV-020 초점: 세계좌표를 주장하는 계약은 CRS(site_frame)·timestamp·covariance를
반드시 동반해야 한다 — 셋 중 무엇이든 빠지면 거부되는지를 네거티브로 확인한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ksi_event_contracts.observation import Observation
from ksi_event_contracts.world_entity import WorldEntity
from pydantic import ValidationError

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "schemas"
_IDENTITY_COVARIANCE = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _valid_world_entity() -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "entityId": "ent-001",
        "class": "Person",
        "timestamp": "2026-07-26T04:00:00Z",
        "siteFrame": "EPSG:5186+KNGeoid2018@1.0.0",
        "pose": {"position": [10.0, 20.0, 1.7]},
        "uncertainty": {
            "positionCovariance": _IDENTITY_COVARIANCE,
            "classificationConfidence": 0.92,
            "localizationState": "CONFIRMED",
        },
        "lineage": {
            "trackId": "trk-77",
            "modelVersions": {"person-detector": "v3.1.0"},
            "calibrationProfileId": "cal-1",
        },
    }


def test_world_entity_roundtrip_matches_schema() -> None:
    schema = _load_schema("world-entity.v1.json")
    model = WorldEntity.model_validate(_valid_world_entity())
    dumped = model.model_dump(by_alias=True, mode="json", exclude_none=True)

    Draft202012Validator(schema).validate(dumped)
    assert dumped["class"] == "Person"  # 예약어 필드가 alias로 정확히 직렬화됐는지


def test_world_entity_schema_file_is_valid_draft202012() -> None:
    Draft202012Validator.check_schema(_load_schema("world-entity.v1.json"))


def test_world_entity_extra_field_rejected() -> None:
    data = _valid_world_entity()
    data["unexpectedField"] = "reject me"
    with pytest.raises(ValidationError):
        WorldEntity.model_validate(data)


@pytest.mark.parametrize("missing", ["timestamp", "siteFrame", "uncertainty", "lineage", "pose"])
def test_world_entity_missing_required_invariant_field_rejected(missing: str) -> None:
    """[INV-020/042] CRS·시각·불확실성·계보는 선택 항목이 아니다."""
    data = _valid_world_entity()
    del data[missing]
    with pytest.raises(ValidationError):
        WorldEntity.model_validate(data)


def test_world_entity_requires_position_covariance() -> None:
    """[INV-021] 위치를 단일 점으로만 주장할 수 없다 — 공분산이 필수."""
    data = _valid_world_entity()
    del data["uncertainty"]["positionCovariance"]
    with pytest.raises(ValidationError):
        WorldEntity.model_validate(data)


@pytest.mark.parametrize("bad_covariance", [[1.0] * 8, [1.0] * 10, []])
def test_world_entity_covariance_must_be_nine_elements(bad_covariance: list[float]) -> None:
    data = _valid_world_entity()
    data["uncertainty"]["positionCovariance"] = bad_covariance
    with pytest.raises(ValidationError):
        WorldEntity.model_validate(data)


@pytest.mark.parametrize("bad_position", [[1.0, 2.0], [1.0, 2.0, 3.0, 4.0]])
def test_world_entity_position_must_be_three_elements(bad_position: list[float]) -> None:
    data = _valid_world_entity()
    data["pose"]["position"] = bad_position
    with pytest.raises(ValidationError):
        WorldEntity.model_validate(data)


def test_world_entity_invalid_localization_state_rejected() -> None:
    data = _valid_world_entity()
    data["uncertainty"]["localizationState"] = "PROBABLY_FINE"
    with pytest.raises(ValidationError):
        WorldEntity.model_validate(data)


def test_world_entity_lineage_requires_model_and_calibration_versions() -> None:
    """[INV-042] track/model/calibration 계보 없이는 Entity를 만들 수 없다."""
    for field in ("trackId", "modelVersions", "calibrationProfileId"):
        data = _valid_world_entity()
        del data["lineage"][field]
        with pytest.raises(ValidationError):
            WorldEntity.model_validate(data)


# ── Observation (Python-first — JSON Schema SSOT 없음) ────────────────────────


def _valid_observation() -> dict[str, Any]:
    return {
        "observationId": "obs-001",
        "observedClass": "Person",
        "sourceClassId": 0,
        "sourceClassName": "person",
        "ontologyVersion": "ksi-ontology-v1",
        "trackId": "trk-77",
        "observedAt": "2026-07-26T04:00:00Z",
        "siteFrame": "EPSG:5186+KNGeoid2018@1.0.0",
        "position": [10.0, 20.0, 1.7],
        "positionCovariance": _IDENTITY_COVARIANCE,
        "detectionConfidence": 0.88,
        "geoConfidence": 0.79,
        "sensorId": "cam-wide",
        "lineage": {"detector": "v3.1.0"},
    }


def test_observation_accepts_valid_payload() -> None:
    obs = Observation.model_validate(_valid_observation())
    assert obs.track_id == "trk-77"
    assert obs.site_frame.startswith("EPSG:")


@pytest.mark.parametrize("missing", ["observedAt", "siteFrame", "positionCovariance", "position"])
def test_observation_missing_invariant_field_rejected(missing: str) -> None:
    """[INV-020] 좌표계·시각·불확실성 없는 관측은 세계좌표를 주장할 수 없다."""
    data = _valid_observation()
    del data[missing]
    with pytest.raises(ValidationError):
        Observation.model_validate(data)


def test_observation_extra_field_rejected() -> None:
    data = _valid_observation()
    data["unexpectedField"] = "reject me"
    with pytest.raises(ValidationError):
        Observation.model_validate(data)


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_observation_confidence_out_of_range_rejected(confidence: float) -> None:
    for field in ("detectionConfidence", "geoConfidence"):
        data = _valid_observation()
        data[field] = confidence
        with pytest.raises(ValidationError):
            Observation.model_validate(data)


def test_observation_roundtrips_through_camel_aliases() -> None:
    obs = Observation.model_validate(_valid_observation())
    dumped = obs.model_dump(by_alias=True, mode="json")
    assert set(dumped) >= {"observationId", "observedAt", "siteFrame", "positionCovariance"}
    assert Observation.model_validate(dumped) == obs
