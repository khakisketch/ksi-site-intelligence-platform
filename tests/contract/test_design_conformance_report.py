"""DesignConformanceReport 계약 — 숫자와 지도가 같은 것을 말하는가.

초점 셋:

1. **지도의 출처가 리포트 안에 있다** — 체적 집계에 실제로 쓴 그 격자를
   :class:`DiffRasterRef` 로 들고 다닌다. 브라우저가 원본을 다시 차분하는 두 번째
   진실이 생기지 않게, 그리고 그 참조가 **Core 가 직접 재해싱해 확인한 사실**
   (``coreVerifiedDigestAt``)이 되게 한다.
2. **문턱값이 한 값이다** — policy · 구역 · 래스터 셋이 갈라지면 범례가 말하는
   기준과 집계에 쓴 기준이 달라지고, 그 거짓말은 어느 화면에서도 보이지 않는다.
3. **재사용이 실제로 재사용이다** — ``ZoneVolumeDelta`` 를 그대로 쓰므로
   cut/fill/net 자기정합 검증이 여기서도 그대로 발화한다(복제였다면 조용히
   빠졌을 검사다).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import current_comparison_policy
from ksi_event_contracts.design_conformance_report import (
    DesignConformanceReport,
    DesignSurfaceRef,
    DiffRasterRef,
)
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "design-conformance-report.v1.json"

_NOW = datetime(2026, 8, 12, 4, 0, tzinfo=UTC)
_POLICY = current_comparison_policy()
_THRESHOLD_M = _POLICY.volume_threshold_m
_SHA = "c" * 64
_DIGEST = "sha256:" + "d" * 64

_PIPELINE_REF = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL,
    basis="설계면(타원체고 선언)과 DSM(ODM 타원체고)이 같은 계열이라 그대로 뺐다",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)


def _zone(**overrides: object) -> ZoneVolumeDelta:
    payload: dict[str, object] = {
        "zone_id": "zone-0",
        "cut_m3": 120.0,
        "fill_m3": 45.0,
        "net_m3": -75.0,
        "area_m2": 2500.0,
        "threshold_m": _THRESHOLD_M,
        "uncertainty_m3": None,
        "uncertainty_note": "설계면은 측정물이 아니라 검증된 RMSE 가 없다 — 상대 잔량만 유효",
    }
    payload.update(overrides)
    return ZoneVolumeDelta(**payload)  # type: ignore[arg-type]


def _diff_raster(**overrides: object) -> DiffRasterRef:
    payload: dict[str, object] = {
        "diff_raster_id": "dcr-1-diff",
        "digest": _DIGEST,
        "crs": "EPSG:5186",
        "vertical_reference": _PIPELINE_REF,
        "width": 400,
        "height": 300,
        "pixel_size_x_m": 0.5,
        "pixel_size_y_m": 0.5,
        "transform": (0.5, 0.0, 190000.0, 0.0, -0.5, 450000.0),
        "threshold_m": _THRESHOLD_M,
        "size_bytes": 480_128,
        "core_verified_digest_at": _NOW,
    }
    payload.update(overrides)
    return DiffRasterRef(**payload)  # type: ignore[arg-type]


def _report(**overrides: object) -> DesignConformanceReport:
    payload: dict[str, object] = {
        "design_conformance_id": "dc-1",
        "design_surface_ref": DesignSurfaceRef(design_surface_id="ds-1", sha256=_SHA),
        "current": ArtifactRef(job_id="job-9", artifact_id="dsm"),
        "crs": "EPSG:5186",
        "vertical_reference": _PIPELINE_REF,
        "zones": [_zone()],
        "policy": _POLICY,
        "diff_raster": _diff_raster(),
        "computed_at": _NOW,
    }
    payload.update(overrides)
    return DesignConformanceReport(**payload)  # type: ignore[arg-type]


def test_a_consistent_report_round_trips() -> None:
    report = _report()
    assert report.total_net_m3 == pytest.approx(-75.0)
    payload = report.model_dump(by_alias=True, mode="json")
    assert payload["diffRaster"]["nodataEncoding"] == "nan"
    assert payload["designSurfaceRef"]["sha256"] == _SHA
    assert DesignConformanceReport.model_validate(payload) == report


# ── 숫자와 지도가 갈라지지 않는다 ───────────────────────────────────────────


def test_thresholds_must_agree_across_policy_zones_and_raster() -> None:
    """[핵심] 범례의 문턱과 집계의 문턱이 다르면 지도와 표가 조용히 갈린다."""
    with pytest.raises(ValidationError, match="문턱값"):
        _report(diff_raster=_diff_raster(threshold_m=_THRESHOLD_M + 0.01))
    with pytest.raises(ValidationError, match="문턱값"):
        _report(zones=[_zone(threshold_m=0.0)])


def test_raster_crs_must_match_the_report_crs() -> None:
    with pytest.raises(ValidationError, match="crs"):
        _report(diff_raster=_diff_raster(crs="EPSG:5187"))


def test_raster_vertical_datum_must_match_the_report() -> None:
    """[음성] 지도와 표가 다른 높이 기준을 말할 수 없다."""
    other = VerticalReference(
        datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
        basis="ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )
    with pytest.raises(ValidationError, match="수직기준"):
        _report(diff_raster=_diff_raster(vertical_reference=other))


def test_duplicate_zone_ids_are_refused() -> None:
    with pytest.raises(ValidationError, match="중복"):
        _report(zones=[_zone(), _zone()])


def test_empty_zones_is_refused() -> None:
    with pytest.raises(ValidationError):
        _report(zones=[])


def test_naive_timestamp_is_refused() -> None:
    with pytest.raises(ValidationError, match="tz-aware"):
        _report(computed_at=datetime(2026, 8, 12, 4, 0))


# ── diff raster 참조는 사실이어야 한다 ──────────────────────────────────────


def test_diff_raster_vertical_reference_must_be_pipeline_declared() -> None:
    """[음성] 우리 계산이 만든 격자의 수직기준을 사용자가 주장할 수 없다."""
    user_claim = VerticalReference(
        datum=VerticalDatum.ELLIPSOIDAL,
        basis="업로더가 그렇게 적었다",
        source=VerticalReferenceSource.USER_DECLARED,
    )
    with pytest.raises(ValidationError, match="pipeline_declared"):
        _diff_raster(vertical_reference=user_claim)


def test_diff_raster_requires_the_core_verification_timestamp() -> None:
    """[핵심] 확인 없이 만들어진 리포트는 지도의 출처를 주장만으로 세운다."""
    payload = _report().model_dump(by_alias=True, mode="json")
    del payload["diffRaster"]["coreVerifiedDigestAt"]
    with pytest.raises(ValidationError):
        DesignConformanceReport.model_validate(payload)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_diff_raster_digest_uses_the_prefixed_form() -> None:
    """산출물 참조 digest 는 ``sha256:`` 접두사를 붙인다(설계면 파일 해시와 구분)."""
    with pytest.raises(ValidationError):
        _diff_raster(digest="d" * 64)


def test_design_surface_ref_uses_the_bare_file_hash() -> None:
    """설계면 참조는 접두사 없는 원문 해시 — 대조가 문자열 비교로 끝나야 한다."""
    with pytest.raises(ValidationError):
        DesignSurfaceRef(design_surface_id="ds-1", sha256=_DIGEST)


def test_nodata_encoding_is_locked_to_nan() -> None:
    """0 으로 칠하면 지도가 '설계대로 됐다'고 거짓말한다."""
    with pytest.raises(ValidationError):
        _diff_raster(nodata_encoding="zero")


def test_diff_raster_refuses_non_finite_geometry() -> None:
    with pytest.raises(ValidationError, match="transform"):
        _diff_raster(transform=(0.5, 0.0, float("nan"), 0.0, -0.5, 450000.0))


# ── ZoneVolumeDelta 재사용이 실제 재사용이다 ────────────────────────────────


def test_zone_self_consistency_is_inherited_not_reimplemented() -> None:
    """[핵심] cut/fill/net 모순이 여기서도 그대로 걸린다 — 복제였다면 빠졌을 검사다."""
    with pytest.raises(ValidationError, match="netM3"):
        _zone(cut_m3=120.0, fill_m3=45.0, net_m3=75.0)


def test_uncertainty_is_null_with_a_reason() -> None:
    """설계면은 측정물이 아니라 RMSE 가 없다 — null 이 정직한 상태다(INV-024)."""
    assert _report().zones[0].uncertainty_m3 is None
    with pytest.raises(ValidationError):
        _zone(uncertainty_note="")


def test_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        _report(progressPercent=42.0)


# ── 계약 모델 ↔ JSON 스키마 왕복 ────────────────────────────────────────────


def _schema() -> dict[str, object]:
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


def test_wire_payload_validates_against_the_json_schema() -> None:
    payload = _report().model_dump(by_alias=True, mode="json")
    jsonschema.validate(payload, _schema())


def test_schema_refuses_unknown_fields() -> None:
    payload = _report().model_dump(by_alias=True, mode="json")
    payload["progressPercent"] = 42.0
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_schema_refuses_a_user_declared_diff_raster() -> None:
    """두 겹(모델·스키마)이 같은 규칙을 강제한다."""
    payload = _report().model_dump(by_alias=True, mode="json")
    payload["diffRaster"]["verticalReference"]["source"] = "user_declared"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_schema_refuses_a_zone_without_the_uncertainty_reason() -> None:
    payload = _report().model_dump(by_alias=True, mode="json")
    del payload["zones"][0]["uncertaintyNote"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())
