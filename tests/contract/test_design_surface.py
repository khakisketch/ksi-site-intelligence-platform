"""DesignSurface 계약 — 선언(주장)과 관측(사실)의 분리, 그리고 상태의 정직성.

이 파일이 지키는 세 문장:

1. **``SEALED`` 는 Core 가 증명한 사실이 아니라 클라이언트의 주장이다.** 그러니
   그 상태의 설계면으로는 비교를 시작할 수 없고, 관측·검증 시각도 붙을 수 없다.
2. **``VERIFIED`` 는 근거와 함께만 성립한다.** 관측이 없거나 관측 해시가 선언과
   다른 VERIFIED 레코드는 "검증됐다"의 뜻을 통째로 무너뜨린다.
3. **관측 모델은 판정하지 않는다.** 이상한 파일의 사실도 담을 수 있어야 워커가
   typed 거부를 보고할 수 있다 — 막는 것은 산술적으로 불가능한 조합뿐이다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest
from ksi_event_contracts.design_surface import (
    DESIGN_SURFACE_TRANSITIONS,
    DesignSurface,
    DesignSurfaceDeclared,
    DesignSurfaceObserved,
    DesignSurfaceStatus,
    can_transition,
    is_terminal,
)
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "design-surface.v1.json"

_REGISTERED_AT = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
_SEALED_AT = _REGISTERED_AT + timedelta(minutes=5)
_VERIFIED_AT = _SEALED_AT + timedelta(minutes=2)
_SHA = "a" * 64
_OTHER_SHA = "b" * 64


def _declared(**overrides: object) -> DesignSurfaceDeclared:
    payload: dict[str, object] = {
        "crs": "EPSG:5186",
        "sha256": _SHA,
        "vertical_reference": VerticalReference(
            datum=VerticalDatum.ELLIPSOIDAL,
            basis="설계사 제공 도면 표제부에 타원체고 명시",
            source=VerticalReferenceSource.USER_DECLARED,
        ),
    }
    payload.update(overrides)
    return DesignSurfaceDeclared(**payload)  # type: ignore[arg-type]


def _observed(**overrides: object) -> DesignSurfaceObserved:
    payload: dict[str, object] = {
        "sha256": _SHA,
        "crs": "EPSG:5186",
        "vertical_crs_epsg": None,
        "width": 400,
        "height": 300,
        "band_count": 1,
        "dtype": "float32",
        "nodata": -9999.0,
        "pixel_size_x_m": 0.5,
        "pixel_size_y_m": 0.5,
        "transform": (0.5, 0.0, 190000.0, 0.0, -0.5, 450000.0),
        "bounds_min_x": 190000.0,
        "bounds_min_y": 449850.0,
        "bounds_max_x": 190200.0,
        "bounds_max_y": 450000.0,
        "finite_cell_count": 118_000,
        "measured_at": _VERIFIED_AT,
        "measured_by": "worker-1",
    }
    payload.update(overrides)
    return DesignSurfaceObserved(**payload)  # type: ignore[arg-type]


def _surface(**overrides: object) -> DesignSurface:
    payload: dict[str, object] = {
        "design_surface_id": "ds-1",
        "site_id": "site-1",
        "name": "A공구 계획고",
        "revision": "Rev.C",
        "declared": _declared(),
        "observed": _observed(),
        "status": DesignSurfaceStatus.VERIFIED,
        "registered_at": _REGISTERED_AT,
        "registered_by": "operator-1",
        "sealed_at": _SEALED_AT,
        "verified_at": _VERIFIED_AT,
    }
    payload.update(overrides)
    return DesignSurface(**payload)  # type: ignore[arg-type]


def _registered(**overrides: object) -> DesignSurface:
    payload: dict[str, object] = {
        "status": DesignSurfaceStatus.REGISTERED,
        "observed": None,
        "sealed_at": None,
        "verified_at": None,
    }
    payload.update(overrides)
    return _surface(**payload)


def _sealed(**overrides: object) -> DesignSurface:
    payload: dict[str, object] = {
        "status": DesignSurfaceStatus.SEALED,
        "observed": None,
        "sealed_at": _SEALED_AT,
        "verified_at": None,
    }
    payload.update(overrides)
    return _surface(**payload)


def _rejected(**overrides: object) -> DesignSurface:
    payload: dict[str, object] = {
        "status": DesignSurfaceStatus.REJECTED,
        "observed": _observed(sha256=_OTHER_SHA),
        "rejection_reason": "DIGEST_MISMATCH — 올린 파일의 해시가 신고값과 다르다",
        "sealed_at": _SEALED_AT,
        "verified_at": None,
    }
    payload.update(overrides)
    return _surface(**payload)


# ── SEALED 는 주장이다 ──────────────────────────────────────────────────────


def test_sealed_surface_cannot_be_used_for_conformance() -> None:
    """[핵심] 클라이언트가 '업로드했다'고 말한 것만으로는 비교 입력이 되지 않는다."""
    assert _sealed().is_usable_for_conformance is False
    assert _registered().is_usable_for_conformance is False
    assert _rejected().is_usable_for_conformance is False
    assert _surface().is_usable_for_conformance is True


def test_sealed_surface_cannot_carry_an_observation_or_verification() -> None:
    """봉인은 원장 쪽 사실일 뿐 파일에 대해 아무것도 주장하지 않는다."""
    with pytest.raises(ValidationError, match="observed"):
        _sealed(observed=_observed())
    with pytest.raises(ValidationError, match="verifiedAt"):
        _sealed(verified_at=_VERIFIED_AT)


def test_the_module_docstring_keeps_the_sealed_warning() -> None:
    """[드리프트 가드] "SEALED = 주장" 경고가 지워지면 이 계약의 요점이 사라진다.

    이름만 남고 근거가 사라지는 것을 막는 유일한 자동 장치다 — 다음 사람이
    ``SEALED`` 를 "파일이 올라온 상태"로 읽는 순간 아무도 읽어보지 않은 파일로
    잔량 숫자가 나간다.
    """
    from ksi_event_contracts import design_surface

    doc = design_surface.__doc__ or ""
    assert "SEALED" in doc
    assert "주장" in doc
    assert "VERIFIED" in doc


# ── 상태 전이 표 ────────────────────────────────────────────────────────────


def test_transition_table_covers_every_status() -> None:
    assert set(DESIGN_SURFACE_TRANSITIONS) == set(DesignSurfaceStatus)


def test_only_verified_and_rejected_are_terminal() -> None:
    assert is_terminal(DesignSurfaceStatus.VERIFIED)
    assert is_terminal(DesignSurfaceStatus.REJECTED)
    assert not is_terminal(DesignSurfaceStatus.REGISTERED)
    assert not is_terminal(DesignSurfaceStatus.SEALED)


def test_registration_cannot_jump_straight_to_verified() -> None:
    """[음성] 봉인을 건너뛴 검증은 대조 대상 내용이 확정되기 전의 검증이다."""
    assert can_transition(DesignSurfaceStatus.REGISTERED, DesignSurfaceStatus.SEALED)
    assert not can_transition(DesignSurfaceStatus.REGISTERED, DesignSurfaceStatus.VERIFIED)
    assert can_transition(DesignSurfaceStatus.SEALED, DesignSurfaceStatus.VERIFIED)
    assert can_transition(DesignSurfaceStatus.SEALED, DesignSurfaceStatus.REJECTED)
    assert not can_transition(DesignSurfaceStatus.VERIFIED, DesignSurfaceStatus.REJECTED)


# ── VERIFIED 는 근거와 함께만 ───────────────────────────────────────────────


def test_verified_without_an_observation_is_refused() -> None:
    with pytest.raises(ValidationError, match="observed"):
        _surface(observed=None)


def test_verified_with_a_contradicting_observation_is_refused() -> None:
    """[핵심] 관측 해시가 선언과 다른데 VERIFIED — 대조를 통과하지 않은 검증이다."""
    with pytest.raises(ValidationError, match="sha256"):
        _surface(observed=_observed(sha256=_OTHER_SHA))


def test_verified_requires_both_sealed_and_verified_timestamps() -> None:
    with pytest.raises(ValidationError, match="sealedAt"):
        _surface(sealed_at=None)
    with pytest.raises(ValidationError, match="verifiedAt"):
        _surface(verified_at=None)


def test_timestamps_must_not_run_backwards() -> None:
    with pytest.raises(ValidationError, match="sealedAt"):
        _surface(sealed_at=_REGISTERED_AT - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="verifiedAt"):
        _surface(verified_at=_SEALED_AT - timedelta(seconds=1))


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(ValidationError, match="tz-aware"):
        _surface(verified_at=datetime(2026, 8, 12, 1, 10))


# ── REGISTERED / REJECTED ──────────────────────────────────────────────────


def test_registered_surface_carries_no_evidence_at_all() -> None:
    surface = _registered()
    assert surface.observed is None and surface.sealed_at is None
    with pytest.raises(ValidationError, match="sealedAt"):
        _registered(sealed_at=_SEALED_AT)
    with pytest.raises(ValidationError, match="observed"):
        _registered(observed=_observed())


def test_rejection_must_say_why() -> None:
    """[핵심] 사용자는 무엇을 고쳐 다시 올려야 하는지 알아야 한다."""
    with pytest.raises(ValidationError, match="rejectionReason"):
        _rejected(rejection_reason=None)
    with pytest.raises(ValidationError, match="rejectionReason"):
        _rejected(rejection_reason="   ")


def test_rejection_without_an_observation_is_allowed() -> None:
    """파일이 열리지 않으면(UNREADABLE_RASTER) 관측 자체가 없다 — 그래도 거부다."""
    surface = _rejected(observed=None, rejection_reason="UNREADABLE_RASTER — 열 수 없는 래스터")
    assert surface.observed is None
    assert surface.status is DesignSurfaceStatus.REJECTED


def test_a_passing_status_may_not_carry_a_rejection_reason() -> None:
    with pytest.raises(ValidationError, match="rejectionReason"):
        _surface(rejection_reason="사실은 거부됐다")


# ── declared 는 사용자 주장이다 ─────────────────────────────────────────────


def test_declared_vertical_reference_must_be_a_user_claim() -> None:
    """[음성] 업로드 폼의 값이 파이프라인 귀속으로 둔갑할 수 없다."""
    with pytest.raises(ValidationError, match="user_declared"):
        _declared(
            vertical_reference=VerticalReference(
                datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
                basis="워커가 그렇게 말했다",
                source=VerticalReferenceSource.PIPELINE_DECLARED,
            )
        )


def test_declared_length_unit_is_locked_to_meter() -> None:
    """피트 단위 도면이 미터로 취급되면 체적이 조용히 35배 틀린다."""
    with pytest.raises(ValidationError):
        _declared(length_unit="foot")


def test_declared_sha256_must_be_lowercase_hex() -> None:
    with pytest.raises(ValidationError):
        _declared(sha256=_SHA.upper())


# ── 관측은 판정하지 않는다 ─────────────────────────────────────────────────


def test_observation_may_record_an_unusable_file() -> None:
    """[핵심] 3밴드·0 유한셀 같은 '나쁜' 사실도 담긴다 — 거부는 Core 의 몫이다.

    담지 못하면 그 파일을 만난 워커가 typed 거부를 보고하는 대신 계약 예외로
    죽고, 사용자는 왜 실패했는지 받지 못한다.
    """
    observed = _observed(band_count=3, finite_cell_count=0, crs="EPSG:5187")
    assert observed.band_count == 3
    assert observed.finite_cell_count == 0


def test_observation_refuses_an_arithmetically_impossible_count() -> None:
    """[음성] 전체 셀 수보다 많은 유한셀 — 파일이 이상한 게 아니라 측정이 틀렸다."""
    with pytest.raises(ValidationError, match="finiteCellCount"):
        _observed(width=10, height=10, finite_cell_count=101)


def test_nan_nodata_is_carried_by_its_own_flag_not_by_a_nan_float() -> None:
    """JSON 에 NaN 이 없다 — 실으면 계약이 왕복하지 못한다."""
    assert _observed(nodata=None, nodata_is_nan=True).nodata_is_nan is True
    with pytest.raises(ValidationError, match="nodata"):
        _observed(nodata=float("nan"))
    with pytest.raises(ValidationError, match="nodata"):
        _observed(nodata=-9999.0, nodata_is_nan=True)


def test_observation_refuses_non_finite_geometry() -> None:
    with pytest.raises(ValidationError, match="transform"):
        _observed(transform=(0.5, 0.0, float("inf"), 0.0, -0.5, 450000.0))


def test_transform_must_have_exactly_six_entries() -> None:
    with pytest.raises(ValidationError):
        _observed(transform=(0.5, 0.0, 190000.0, 0.0, -0.5))


def test_unknown_field_is_refused() -> None:
    """계약 밖 필드를 조용히 삼키지 않는다(extra=forbid)."""
    with pytest.raises(ValidationError):
        _surface(uploadedAt=_SEALED_AT)


# ── 계약 모델 ↔ JSON 스키마 왕복 ────────────────────────────────────────────


def _schema() -> dict[str, object]:
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "factory",
    [_registered, _sealed, _rejected, _surface],
    ids=["REGISTERED", "SEALED", "REJECTED", "VERIFIED"],
)
def test_every_status_round_trips_through_the_json_schema(
    factory: Callable[[], DesignSurface],
) -> None:
    """네 상태 전부가 정본 스키마를 통과한다 — camelCase 왕복 포함."""
    surface = factory()
    payload = surface.model_dump(by_alias=True, mode="json")
    assert set(payload) >= {"designSurfaceId", "declared", "observed", "rejectionReason"}
    assert payload["declared"]["verticalReference"]["source"] == "user_declared"
    jsonschema.validate(payload, _schema())
    assert DesignSurface.model_validate(payload) == surface


def test_schema_refuses_unknown_fields() -> None:
    payload = _surface().model_dump(by_alias=True, mode="json")
    payload["uploadedAt"] = "2026-08-12T01:05:00Z"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_schema_requires_the_nullable_fields_to_be_present() -> None:
    """nullable 필수 — 생략과 명시적 null 을 구분한다(processing-artifact 관습)."""
    for field in ("observed", "rejectionReason", "sealedAt", "verifiedAt"):
        payload = _registered().model_dump(by_alias=True, mode="json")
        del payload[field]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(payload, _schema())


def test_schema_refuses_a_pipeline_declared_vertical_reference() -> None:
    """두 겹(모델·스키마)이 같은 규칙을 강제한다."""
    payload = _surface().model_dump(by_alias=True, mode="json")
    payload["declared"]["verticalReference"]["source"] = "pipeline_declared"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_schema_refuses_an_unknown_status() -> None:
    payload = _surface().model_dump(by_alias=True, mode="json")
    payload["status"] = "UPLOADED"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())
