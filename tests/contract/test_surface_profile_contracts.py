"""측정 대상·표면 단면 계약 — 모르는 값은 null+사유, 결과는 읽은 선 revision에 결속된다.

합성 값만 쓴다. 이 시험은 계약 모양의 증거이지 측량 정확도·고객 수락의 증거가 아니다.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from jsonschema import Draft202012Validator
from ksi_event_contracts import measurement_feature, surface_profile
from ksi_event_contracts.measurement_feature import (
    CreateMeasurementFeatureV1,
    MeasurementFeatureRevisionV1,
    MeasurementLineV1,
)
from ksi_event_contracts.surface_profile import (
    CreateSurfaceProfileV1,
    SurfaceProfileRefusalV1,
    SurfaceProfileResultV1,
    SurfaceProfileSampleV1,
)
from ksi_geo_spatial.surface_profile import SampleInvalidReason, SurfaceProfileErrorReason
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
ASSET = "ksa-v1-" + "a" * 64
FEATURE_ID = "mf-" + "1" * 32
NOW = datetime(2026, 11, 17, tzinfo=UTC)
LINE = MeasurementLineV1(crs="EPSG:5186", vertices=((0.0, 0.0), (30.0, 0.0), (30.0, 40.0)))


def _revision(**overrides: Any) -> MeasurementFeatureRevisionV1:
    values: dict[str, Any] = dict(
        feature_id=FEATURE_ID,
        site_id="site-local",
        work_area_id="area-local",
        revision=1,
        name="북쪽 경사면",
        line=LINE,
        line_digest=LINE.digest(),
        created_at=NOW,
    )
    values.update(overrides)
    return MeasurementFeatureRevisionV1(**values)


def _samples(*elevations: float | None) -> list[dict[str, Any]]:
    return [
        dict(
            index=i,
            distance_m=float(i * 10),
            x=float(i * 10),
            y=0.0,
            elevation_m=value,
            invalid_reason=None if value is not None else "NODATA",
        )
        for i, value in enumerate(elevations)
    ]


def _result(samples: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    rows = samples if samples is not None else _samples(1.0, None, 3.0)
    known = [row["elevation_m"] for row in rows if row["elevation_m"] is not None]
    payload: dict[str, Any] = dict(
        asset_ref=ASSET,
        line_digest=LINE.digest(),
        horizontal_crs="EPSG:5186",
        line_length_m=float(10 * (len(rows) - 1)),
        sample_spacing_m=10.0,
        window_cells_read=64,
        samples=rows,
        valid_count=len(known),
        unknown_count=len(rows) - len(known),
        minimum_m=min(known) if known else None,
        maximum_m=max(known) if known else None,
    )
    payload.update(overrides)
    return payload


def test_schemas_match_models_and_are_valid_json_schema() -> None:
    spec = importlib.util.spec_from_file_location(
        "generate_surface_profile_schemas", ROOT / "tools/generate_surface_profile_schemas.py"
    )
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    for module, stem in generator.MODULES.items():
        actual = json.loads((ROOT / f"contracts/schemas/{stem}.v1.json").read_text())
        assert actual == generator.schema_for(module)
        Draft202012Validator.check_schema(actual)


def test_line_digest_binds_geometry_and_crs() -> None:
    same = MeasurementLineV1(crs="EPSG:5186", vertices=LINE.vertices)
    moved = MeasurementLineV1(crs="EPSG:5186", vertices=((0.0, 0.0), (30.0, 0.0), (30.0, 41.0)))
    other_crs = MeasurementLineV1(crs="EPSG:5185", vertices=LINE.vertices)
    assert same.digest() == LINE.digest()
    assert len({LINE.digest(), moved.digest(), other_crs.digest()}) == 3


@pytest.mark.parametrize(
    "vertices",
    [
        ((0.0, 0.0),),
        ((1.0, 1.0), (1.0, 1.0)),
        ((0.0, float("nan")), (1.0, 1.0)),
        ((0.0, float("inf")), (1.0, 1.0)),
        tuple((float(i), 0.0) for i in range(measurement_feature.MAX_LINE_VERTICES + 1)),
    ],
)
def test_line_rejects_degenerate_or_non_finite_geometry(vertices: tuple) -> None:
    with pytest.raises(ValidationError):
        MeasurementLineV1(crs="EPSG:5186", vertices=vertices)


@pytest.mark.parametrize("crs", ["", "epsg:5186", "EPSG:0", "EPSG:5186 ", "WKT", "EPSG:1234567"])
def test_line_requires_a_registered_epsg_identifier(crs: str) -> None:
    with pytest.raises(ValidationError):
        MeasurementLineV1(crs=crs, vertices=LINE.vertices)


def test_revision_digest_seals_every_field_and_line_digest_must_match() -> None:
    sealed = _revision().sealed()
    assert sealed.revision_digest == sealed.canonical_digest()
    assert _revision(name="다른 이름").sealed().revision_digest != sealed.revision_digest
    assert _revision(revision=2).sealed().revision_digest != sealed.revision_digest
    with pytest.raises(ValidationError):
        _revision(line_digest="sha256:" + "0" * 64)
    with pytest.raises(ValidationError):
        MeasurementFeatureRevisionV1(**{**sealed.__dict__, "name": "바뀜"})


def test_revision_ref_names_exact_revision_and_geometry() -> None:
    ref = _revision(revision=3).ref()
    assert (ref.feature_id, ref.revision, ref.line_digest) == (FEATURE_ID, 3, LINE.digest())


def test_feature_creation_carries_no_scope_beyond_its_work_area() -> None:
    assert set(CreateMeasurementFeatureV1.model_fields) == {"work_area_id", "name", "line"}
    with pytest.raises(ValidationError):
        CreateMeasurementFeatureV1(
            work_area_id="a",
            name="n",
            line=LINE,
            site_id="x",  # type: ignore[call-arg]
        )


def test_request_binds_feature_to_the_requested_line() -> None:
    ref = _revision().ref()
    ok = CreateSurfaceProfileV1(asset_ref=ASSET, line=LINE, feature=ref)
    assert ok.sample_spacing_m is None
    moved = MeasurementLineV1(crs="EPSG:5186", vertices=((0.0, 0.0), (9.0, 9.0)))
    with pytest.raises(ValidationError, match="lineDigest"):
        CreateSurfaceProfileV1(asset_ref=ASSET, line=moved, feature=ref)


@pytest.mark.parametrize("spacing", [0.0, -1.0, float("nan"), float("inf")])
def test_request_rejects_unusable_spacing(spacing: float) -> None:
    with pytest.raises(ValidationError):
        CreateSurfaceProfileV1(asset_ref=ASSET, line=LINE, sample_spacing_m=spacing)


def test_request_takes_an_asset_reference_never_a_path_or_url() -> None:
    for bad in ("/data/dsm.tif", "https://x/dsm.tif", "s3://b/k.tif", "ksa-v1-short"):
        with pytest.raises(ValidationError):
            CreateSurfaceProfileV1(asset_ref=bad, line=LINE)
    assert not {"path", "url", "file_path"} & set(CreateSurfaceProfileV1.model_fields)


def test_sample_has_an_elevation_or_a_reason_never_both_or_neither() -> None:
    row: dict[str, Any] = dict(index=0, distance_m=0.0, x=0.0, y=0.0)
    SurfaceProfileSampleV1(**row, elevation_m=0.0, invalid_reason=None)  # a real zero is valid
    SurfaceProfileSampleV1(**row, elevation_m=None, invalid_reason="OUTSIDE_SURFACE")
    bad: tuple[tuple[float | None, Any], ...] = ((None, None), (1.0, "NODATA"))
    for elevation, reason in bad:
        with pytest.raises(ValidationError):
            SurfaceProfileSampleV1(**row, elevation_m=elevation, invalid_reason=reason)


def test_result_keeps_unknown_unknown_and_real_zero_zero() -> None:
    result = SurfaceProfileResultV1(**_result(_samples(0.0, None, -2.0)))
    assert [row.elevation_m for row in result.samples] == [0.0, None, -2.0]
    assert (result.minimum_m, result.maximum_m) == (-2.0, 0.0)
    assert (result.valid_count, result.unknown_count) == (2, 1)
    assert result.volume_computed is False and result.accuracy_assessed is False


def test_result_without_any_known_elevation_has_no_extremes() -> None:
    result = SurfaceProfileResultV1(**_result(_samples(None, None)))
    assert (result.minimum_m, result.maximum_m, result.valid_count) == (None, None, 0)
    with pytest.raises(ValidationError):
        SurfaceProfileResultV1(**_result(_samples(None, None), minimum_m=0.0, maximum_m=0.0))


@pytest.mark.parametrize(
    "change",
    [
        dict(valid_count=3),
        dict(unknown_count=0),
        dict(minimum_m=0.0),  # a zero that is not in the known samples
        dict(maximum_m=99.0),
        dict(line_length_m=25.0),
        dict(volume_computed=True),
        dict(accuracy_assessed=True),
        dict(window_cells_read=-1),
        dict(line_digest="sha256:short"),
    ],
)
def test_result_rejects_inconsistent_or_overclaiming_values(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SurfaceProfileResultV1(**_result(**change))


def test_result_rejects_bad_sample_order() -> None:
    rows = _samples(1.0, 2.0, 3.0)
    rows[1]["index"] = 5
    with pytest.raises(ValidationError):
        SurfaceProfileResultV1(**_result(rows))
    rows = _samples(1.0, 2.0, 3.0)
    rows[1]["distance_m"] = 0.0  # not strictly increasing
    with pytest.raises(ValidationError):
        SurfaceProfileResultV1(**_result(rows))
    rows = _samples(1.0, 2.0, 3.0)
    rows[0]["distance_m"] = 1.0  # must start at the line start
    with pytest.raises(ValidationError):
        SurfaceProfileResultV1(**_result(rows))


def test_result_feature_must_be_the_read_line() -> None:
    ref = _revision().ref()
    SurfaceProfileResultV1(**_result(feature=ref))
    other = MeasurementLineV1(crs="EPSG:5186", vertices=((0.0, 0.0), (9.0, 9.0)))
    with pytest.raises(ValidationError):
        SurfaceProfileResultV1(
            **_result(feature=_revision(line=other, line_digest=other.digest()).ref())
        )


def test_result_digest_seals_samples_and_detects_tampering() -> None:
    sealed = SurfaceProfileResultV1(**_result()).sealed()
    assert sealed.result_digest == sealed.canonical_digest()
    changed = _samples(1.0, 2.0, 3.0)
    assert SurfaceProfileResultV1(**_result(changed)).sealed().result_digest != sealed.result_digest
    with pytest.raises(ValidationError):
        SurfaceProfileResultV1(**{**sealed.__dict__, "window_cells_read": 65})


def test_result_sample_count_is_bounded() -> None:
    too_many = _samples(*([1.0] * (surface_profile.MAX_PROFILE_SAMPLES + 1)))
    with pytest.raises(ValidationError):
        SurfaceProfileResultV1(**_result(too_many))


def test_wire_schema_refuses_a_sample_with_both_or_neither() -> None:
    schema = json.loads((ROOT / "contracts/schemas/surface-profile.v1.json").read_text())
    assert "SurfaceProfileResultV1" in schema["$defs"]
    wire = SurfaceProfileResultV1(**_result()).model_dump(by_alias=True, mode="json")
    validator = Draft202012Validator(
        {"$ref": "#/$defs/SurfaceProfileResultV1", "$defs": schema["$defs"]}
    )
    assert not list(validator.iter_errors(wire))
    wire["volumeComputed"] = True
    assert list(validator.iter_errors(wire))
    wire["volumeComputed"] = False
    wire["unexpected"] = 1
    assert list(validator.iter_errors(wire))


def test_reason_vocabulary_matches_the_calculation_primitive() -> None:
    assert set(get_args(surface_profile.SurfaceProfileRefusalReasonV1)) == {
        reason.value for reason in SurfaceProfileErrorReason
    }
    assert set(get_args(surface_profile.SampleInvalidReasonV1)) == {
        reason.value for reason in SampleInvalidReason
    }


def test_refusal_is_typed_and_never_retryable() -> None:
    refusal = SurfaceProfileRefusalV1(reason="WINDOW_TOO_LARGE")
    assert refusal.retryable is False
    assert set(SurfaceProfileRefusalV1.model_fields) == {"reason", "retryable"}
    with pytest.raises(ValidationError):
        SurfaceProfileRefusalV1(reason="/data/secret.tif")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("elevation", "reason"),
    [(None, None), (1.0, "NODATA"), (None, "NOT_A_REASON")],
)
def test_wire_schema_refuses_a_malformed_sample(
    elevation: float | None, reason: str | None
) -> None:
    schema = json.loads((ROOT / "contracts/schemas/surface-profile.v1.json").read_text())
    validator = Draft202012Validator(
        {"$ref": "#/$defs/SurfaceProfileSampleV1", "$defs": schema["$defs"]}
    )
    wire = dict(index=0, distanceM=0.0, x=0.0, y=0.0, elevationM=elevation, invalidReason=reason)
    assert list(validator.iter_errors(wire))
    with pytest.raises(ValidationError):
        SurfaceProfileSampleV1.model_validate(wire)


@pytest.mark.parametrize(
    ("elevation", "reason"),
    [(0.0, None), (-3.5, None), (None, "NODATA"), (None, "OUTSIDE_SURFACE")],
)
def test_wire_schema_accepts_a_well_formed_sample(
    elevation: float | None, reason: str | None
) -> None:
    schema = json.loads((ROOT / "contracts/schemas/surface-profile.v1.json").read_text())
    validator = Draft202012Validator(
        {"$ref": "#/$defs/SurfaceProfileSampleV1", "$defs": schema["$defs"]}
    )
    wire = dict(index=0, distanceM=0.0, x=0.0, y=0.0, elevationM=elevation, invalidReason=reason)
    assert not list(validator.iter_errors(wire))
    SurfaceProfileSampleV1.model_validate(wire)
