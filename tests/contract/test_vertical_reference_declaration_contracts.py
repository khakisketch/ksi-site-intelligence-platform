"""수직 기준 선언 계약 — 선언은 주장이며 관측과 섞이지 않는다.

합성 값만 쓴다. 이 시험은 계약 모양의 증거이지 측량 정확도·고객 수락의 증거가 아니다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ksi_event_contracts import vertical_reference_declaration as module
from ksi_event_contracts.vertical_reference import VerticalDatum
from ksi_event_contracts.vertical_reference_declaration import (
    MAX_DECLARATIONS_PER_ASSET,
    DeclareVerticalReferenceV1,
    VerticalReferenceDeclarationStateViewV1,
    VerticalReferenceDeclarationV1,
    VerticalReferenceDeclarationWriteViewV1,
    WithdrawVerticalReferenceV1,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
ASSET_REF = "ksa-v1-" + "a" * 64
NOW = datetime(2026, 11, 17, 3, 0, tzinfo=UTC)


def _active(**overrides: Any) -> VerticalReferenceDeclarationV1:
    values: dict[str, Any] = {
        "declaration_id": "vrd-" + "1" * 32,
        "site_id": "site-1",
        "work_area_id": "area-1",
        "asset_ref": ASSET_REF,
        "sequence": 1,
        "status": "ACTIVE",
        "datum": VerticalDatum.ORTHOMETRIC_KNGEOID2018,
        "basis": "Terra에서 정표고(KNGeoid18)로 내보냄",
        "declared_by": "operator-1",
        "declared_at": NOW,
    }
    values.update(overrides)
    return VerticalReferenceDeclarationV1(**values).sealed()


def test_active_declaration_is_sealed_and_metre_only() -> None:
    record = _active()
    assert record.declaration_digest == record.canonical_digest()
    assert record.unit == "metre"
    wire = record.model_dump(by_alias=True, mode="json")
    assert wire["datum"] == "orthometric_kngeoid2018"
    assert wire["unit"] == "metre"


def test_unit_cannot_be_anything_but_metre() -> None:
    with pytest.raises(ValidationError):
        DeclareVerticalReferenceV1.model_validate(
            {"datum": "ellipsoidal", "unit": "foot", "basis": "x", "expectedSequence": 0}
        )
    with pytest.raises(ValidationError):
        _active(unit="foot")


def test_an_active_record_names_datum_and_basis() -> None:
    with pytest.raises(ValidationError):
        _active(datum=None)
    with pytest.raises(ValidationError):
        _active(basis=None)


def test_a_withdrawal_carries_no_claim() -> None:
    record = _active(sequence=2, status="WITHDRAWN", datum=None, basis=None)
    assert record.datum is None and record.basis is None
    with pytest.raises(ValidationError):
        _active(sequence=2, status="WITHDRAWN")
    with pytest.raises(ValidationError):
        _active(sequence=2, status="WITHDRAWN", datum=None)


def test_digest_binds_every_field() -> None:
    record = _active()
    for field, value in (
        ("basis", "다른 근거"),
        ("datum", VerticalDatum.ELLIPSOIDAL),
        ("sequence", 2),
        ("declared_by", "someone-else"),
        ("asset_ref", "ksa-v1-" + "b" * 64),
        ("work_area_id", "area-2"),
    ):
        tampered = {**record.__dict__, field: value}
        with pytest.raises(ValidationError):
            VerticalReferenceDeclarationV1(**tampered)


def test_datum_is_the_closed_platform_vocabulary_not_free_text() -> None:
    with pytest.raises(ValidationError):
        DeclareVerticalReferenceV1.model_validate(
            {"datum": "EGM96", "basis": "x", "expectedSequence": 0}
        )
    for datum in VerticalDatum:
        DeclareVerticalReferenceV1(datum=datum, basis="x", expected_sequence=0)


def test_ids_and_sequences_are_bounded() -> None:
    assert MAX_DECLARATIONS_PER_ASSET == 64  # 표현 상한이다. 운영 예산이 아니다.
    for bad_id in ("", "vrd-xyz", "vrd-" + "A" * 32, "x" * 36):
        with pytest.raises(ValidationError):
            _active(declaration_id=bad_id)
    with pytest.raises(ValidationError):
        _active(sequence=0)
    with pytest.raises(ValidationError):
        _active(sequence=MAX_DECLARATIONS_PER_ASSET + 1)
    with pytest.raises(ValidationError):
        WithdrawVerticalReferenceV1(expected_sequence=0)
    DeclareVerticalReferenceV1(datum=VerticalDatum.ELLIPSOIDAL, basis="x", expected_sequence=0)


def test_requests_reject_unknown_fields_and_wrong_types() -> None:
    with pytest.raises(ValidationError):
        DeclareVerticalReferenceV1.model_validate(
            {"datum": "ellipsoidal", "basis": "x", "expectedSequence": 0, "siteId": "other"}
        )
    with pytest.raises(ValidationError):
        DeclareVerticalReferenceV1.model_validate(
            {"datum": "ellipsoidal", "basis": "x", "expectedSequence": "0"}
        )


def test_timestamp_must_be_utc() -> None:
    with pytest.raises(ValidationError):
        _active(declared_at=datetime(2026, 11, 17, 3, 0))
    with pytest.raises(ValidationError):
        _active(declared_at=datetime(2026, 11, 17, 3, 0, tzinfo=timezone(timedelta(hours=9))))


def test_state_view_keeps_observed_separate_from_the_declaration() -> None:
    record = _active()
    view = VerticalReferenceDeclarationStateViewV1(
        asset_ref=ASSET_REF, observed=False, current=record, history=(record,)
    )
    wire = view.model_dump(by_alias=True, mode="json")
    assert wire["observed"] is False
    assert wire["current"]["status"] == "ACTIVE"
    assert VerticalReferenceDeclarationWriteViewV1(verdict="DECLARED", declaration=record)


def test_checked_in_schema_matches_the_models_and_validates_a_record() -> None:
    path = ROOT / "contracts/schemas/vertical-reference-declaration.v1.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    names = {name for name in vars(module) if name.endswith("V1") and not name.startswith("_")}
    assert names - {"VerticalReferenceDeclarationVerdictV1"} <= set(schema["$defs"])
    record = _active().model_dump(by_alias=True, mode="json")
    validator = Draft202012Validator({**schema, "$ref": "#/$defs/VerticalReferenceDeclarationV1"})
    assert list(validator.iter_errors(record)) == []
    assert list(validator.iter_errors({**record, "unit": "foot"}))
