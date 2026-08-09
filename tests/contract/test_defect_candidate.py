"""DefectCandidate 계약 왕복 (Phase 4 "표면 점검·결함 후보", MODEL-P4-001,
contracts/schemas/defect-candidate.v1.json)."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from ksi_event_contracts.defect_candidate import (
    DefectCandidate,
    DefectGeometry,
    DefectMeasurements,
    DefectModelRef,
    ImageSize,
    defect_candidate_from_wire,
    defect_candidate_wire_dict,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "defect-candidate.v1.json"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))


def _candidate(**overrides: object) -> DefectCandidate:
    defaults: dict[str, object] = dict(
        defect_candidate_id="defect-1",
        defect_type="CRACK",
        source_media_id="img-001.jpg",
        image_size=ImageSize(width_px=4000, height_px=3000),
        geometry=DefectGeometry(
            format="IMAGE_POLYGON_2D",
            payload=[(100, 200), (140, 205), (138, 260), (98, 255)],
        ),
        model=DefectModelRef(
            model_id="ksi-crack-segmenter-mixercseg-deepcrack",
            source_digests={"checkpoint.pth": "a" * 64},
        ),
        confidence=0.87,
    )
    defaults.update(overrides)
    return DefectCandidate(**defaults)  # type: ignore[arg-type]


def test_model_output_satisfies_contract_schema() -> None:
    """Python 모델의 wire 산출이 계약 스키마를 만족한다 — 두 정본이 갈라지지 않게."""
    _validator().validate(defect_candidate_wire_dict(_candidate()))


def test_wire_round_trips_back_to_equivalent_model() -> None:
    """wire → model 역방향도 검증한다 — RiskField 가 남긴 단방향 잔여 리스크
    (risk-field-round-trip-one-direction-only)를 이 계약에서는 처음부터 만들지 않는다."""
    original = _candidate()
    wire = defect_candidate_wire_dict(original)
    restored = defect_candidate_from_wire(wire)
    assert restored == original


def test_geometry_payload_none_still_satisfies_schema_required() -> None:
    """geometry.payload=None이어도 wire에 payload 키는 남아야 한다(스키마
    geometry.required=["format","payload"]) — RiskField 의 동일 함정(F2)을 여기서도
    피한다."""
    candidate = _candidate(geometry=DefectGeometry(format="IMAGE_POLYGON_2D", payload=None))
    wire = defect_candidate_wire_dict(candidate)
    assert "payload" in wire["geometry"]
    assert wire["geometry"]["payload"] is None
    _validator().validate(wire)


def test_measurements_omitted_when_not_given() -> None:
    candidate = _candidate()
    assert candidate.measurements is None
    wire = defect_candidate_wire_dict(candidate)
    assert "measurements" not in wire
    _validator().validate(wire)


def test_measurements_partial_fields_drop_nulls() -> None:
    candidate = _candidate(
        measurements=DefectMeasurements(area_px2=1234.5, length_px=None, mean_width_px=None)
    )
    wire = defect_candidate_wire_dict(candidate)
    assert wire["measurements"] == {"areaPx2": 1234.5}
    _validator().validate(wire)


def test_confidence_out_of_range_rejected() -> None:
    try:
        _candidate(confidence=1.5)
    except ValueError:
        return
    raise AssertionError("confidence>1.0 은 pydantic 검증에서 거부돼야 한다")


def test_geometry_payload_fewer_than_three_points_rejected() -> None:
    """[reviewer 재검토 잔여 지적] 스키마는 처음부터 payload minItems=3 을 요구했는데
    pydantic 쪽엔 길이 제약이 없어서 2점짜리도 통과했다 — 두 정본이 갈라져 있었다."""
    try:
        _candidate(geometry=DefectGeometry(format="IMAGE_POLYGON_2D", payload=[(0, 0), (1, 1)]))
    except ValueError:
        return
    raise AssertionError("3점 미만 payload 는 pydantic 검증에서 거부돼야 한다")
