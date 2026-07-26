"""MissionContract 계약 round-trip 테스트 (P0-1).

유효 v1.1/v1.2 인스턴스가 model_dump(by_alias=True, mode="json") 후 해당 JSON Schema
(Draft 2020-12)를 통과하는지, 스키마 밖 필드를 모델이 거부(extra=forbid)하는지,
스키마 파일 자체가 유효한 Draft 2020-12 메타스키마인지를 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ksi_mission_contracts.models import MissionContractV1_1, MissionContractV1_2
from pydantic import BaseModel, ValidationError

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _valid_contract_dict(schema_version: str) -> dict[str, Any]:
    """유효한 MissionContract 인스턴스(camelCase) — signature만 버전별로 다르다."""
    base: dict[str, Any] = {
        "schemaVersion": schema_version,
        "missionId": "mission-001",
        "siteId": "site-001",
        "missionType": "UNIFIED_SITE_SURVEY",
        "validity": {
            "notBefore": "2026-07-25T00:00:00Z",
            "notAfter": "2026-07-26T00:00:00Z",
        },
        "siteFrame": {
            "crs": "EPSG:5186",
            "verticalDatum": "KNGeoid2018",
            "unit": "meter",
            "transformVersion": "1.0.0",
        },
        "flightEnvelope": {
            "allowedVolumes": ["vol-1"],
            "excludedVolumes": [],
            "minAltitudeM": 5.0,
            "maxAltitudeM": 120.0,
            "minimumStructureStandoffM": 3.0,
            "minimumPersonStandoffM": 5.0,
        },
        "objectives": ["현장 외곽 전체 커버리지 확보"],
        "policies": {
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
            "coveragePolicy": {
                "mandatoryHazardCoverage": 1.0,
                "mandatoryAssetCoverage": 1.0,
                "accessibleGeneralCoverage": 0.97,
            },
            "communicationLossPolicy": {
                "serverLink": "CONTINUE_WHILE_CONTRACT_AND_SAFETY_VALID",
                "rcCommandLink": "DELEGATE_TO_DJI_FLIGHT_CONTROLLER",
            },
            "batteryPolicy": {
                "mode": "RETURN_ENERGY_PLUS_RESERVE",
                "defaultReservePercent": 30,
                "siteOverrideAllowed": True,
            },
            "unknownObstaclePolicy": {
                "initialAction": "SLOW",
                "unresolvedAction": "RETREAT",
            },
            "evidencePolicy": {
                "candidatePrePostSeconds": 3,
                "highPrePostSeconds": 5,
                "criticalPrePostSeconds": 10,
            },
        },
        "artifacts": {
            "worldModelManifestId": "wm-1",
            "modelPackId": "mp-1",
            "calibrationProfileId": "cal-1",
        },
    }
    if schema_version == "1.1":
        base["signature"] = {"algorithm": "SHA256withECDSA", "digest": "sha256:" + "ab" * 32}
    else:
        base["signature"] = {
            "algorithm": "Ed25519",
            "keyId": "key-001",
            "digest": "sha256:" + "cd" * 32,
            "signature": "c2lnbmF0dXJlLWJ5dGVzLXBsYWNlaG9sZGVy",
        }
    return base


@pytest.mark.parametrize(
    ("schema_version", "schema_file", "model_cls"),
    [
        ("1.1", "mission-contract.v1.1.json", MissionContractV1_1),
        ("1.2", "mission-contract.v1.2.json", MissionContractV1_2),
    ],
)
def test_valid_instance_matches_schema(
    schema_version: str, schema_file: str, model_cls: type[BaseModel]
) -> None:
    schema = _load_schema(schema_file)
    data = _valid_contract_dict(schema_version)

    model = model_cls.model_validate(data)
    dumped = model.model_dump(by_alias=True, mode="json")

    Draft202012Validator(schema).validate(dumped)


@pytest.mark.parametrize(
    ("schema_version", "model_cls"),
    [
        ("1.1", MissionContractV1_1),
        ("1.2", MissionContractV1_2),
    ],
)
def test_extra_field_rejected(schema_version: str, model_cls: type[BaseModel]) -> None:
    data = _valid_contract_dict(schema_version)
    data["unexpectedField"] = "should be rejected"

    with pytest.raises(ValidationError):
        model_cls.model_validate(data)


@pytest.mark.parametrize(
    "schema_file",
    ["mission-contract.v1.1.json", "mission-contract.v1.2.json", "event-bundle.v1.1.json"],
)
def test_schema_file_is_valid_draft202012(schema_file: str) -> None:
    schema = _load_schema(schema_file)
    Draft202012Validator.check_schema(schema)


def test_v1_1_signature_missing_key_id_field() -> None:
    """v1.1 signature는 {algorithm, digest}만 필요 — keyId/signature 없어도 유효."""
    data = _valid_contract_dict("1.1")
    model = MissionContractV1_1.model_validate(data)
    assert model.signature.algorithm == "SHA256withECDSA"


def test_v1_2_signature_requires_all_four_fields() -> None:
    data = _valid_contract_dict("1.2")
    del data["signature"]["keyId"]

    with pytest.raises(ValidationError):
        MissionContractV1_2.model_validate(data)
