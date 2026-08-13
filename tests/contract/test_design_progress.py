"""계획 대비 진척 — 뺄셈의 뜻과 그 뜻이 깨지는 조건 (M4-C).

이 파일이 지키는 세 문장:

1. **완료 = 계획 − 잔여**이고 그 값이 손계산과 일치한다.
2. **다른 자로 잰 두 값은 빼지 않는다.** 설계면 판·집계 문턱·수직기준·좌표계 중
   하나라도 다르면 표를 만들지 않는다 — 그 결과는 어느 화면에서도 이상해 보이지
   않기 때문에 계약이 막아야 한다.
3. **낼 수 없는 칸은 0이 아니라 '해당 없음'이다.** 계획이 없는데 0% 로 적으면
   "할 일이 있는데 하나도 안 했다"는 정반대 뜻이 된다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ksi_core.design_progress import derive_progress
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy
from ksi_event_contracts.design_conformance_report import (
    DesignConformanceReport,
    DesignSurfaceRef,
    DiffRasterRef,
)
from ksi_event_contracts.design_progress import ZoneProgress
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from pydantic import ValidationError

_SHA = "a" * 64
_UNCERTAINTY_NOTE = "설계면은 측정물이 아니라 검증된 RMSE 가 없다(INV-024)"


def _vertical(datum: VerticalDatum = VerticalDatum.ELLIPSOIDAL_NATIVE) -> VerticalReference:
    return VerticalReference(
        datum=datum,
        basis="테스트 픽스처",
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )


def _zone(zone_id: str, *, cut: float, fill: float) -> ZoneVolumeDelta:
    return ZoneVolumeDelta(
        zone_id=zone_id,
        cut_m3=cut,
        fill_m3=fill,
        net_m3=fill - cut,
        area_m2=1000.0,
        threshold_m=0.05,
        uncertainty_m3=None,
        uncertainty_note=_UNCERTAINTY_NOTE,
    )


def _report(
    design_conformance_id: str,
    zones: list[ZoneVolumeDelta],
    *,
    sha256: str = _SHA,
    threshold_m: float = 0.05,
    datum: VerticalDatum = VerticalDatum.ELLIPSOIDAL_NATIVE,
    crs: str = "EPSG:5186",
    computed_at: datetime | None = None,
) -> DesignConformanceReport:
    # 계약이 zones[*].thresholdM == policy.volumeThresholdM 를 강제한다(범례가 말하는
    # 기준과 집계에 쓴 기준이 갈라지지 않게) — 픽스처도 그 규율을 따른다.
    return DesignConformanceReport(
        design_conformance_id=design_conformance_id,
        design_surface_ref=DesignSurfaceRef(design_surface_id="ds-1", sha256=sha256),
        current=ArtifactRef(job_id="job-1", artifact_id="dsm-1"),
        crs=crs,
        vertical_reference=_vertical(datum),
        zones=[zone.model_copy(update={"threshold_m": threshold_m}) for zone in zones],
        policy=ComparisonPolicy(
            policy_version="test-1",
            distance_threshold_m=0.1,
            volume_threshold_m=threshold_m,
            revisit_ratio_threshold=0.2,
        ),
        diff_raster=DiffRasterRef(
            diff_raster_id="dr-1",
            digest=f"sha256:{'b' * 64}",
            format="geotiff",
            crs=crs,
            vertical_reference=_vertical(datum),
            width=10,
            height=10,
            pixel_size_x_m=1.0,
            pixel_size_y_m=1.0,
            transform=(1.0, 0.0, 0.0, 0.0, -1.0, 0.0),
            nodata_encoding="nan",
            threshold_m=threshold_m,
            size_bytes=1234,
            core_verified_digest_at=datetime(2026, 8, 13, 4, 0, tzinfo=UTC),
        ),
        computed_at=computed_at or datetime(2026, 8, 13, 4, 0, tzinfo=UTC),
    )


# ── 골든: 손계산과 일치 ─────────────────────────────────────────────────
def test_progress_golden_matches_hand_calculation() -> None:
    """계획 5000 절토 / 잔여 1240 → 완료 3760 · 진척률 75.2%.

    이 수치는 M4-C 계획 문서의 예시 그대로다 — 화면에 뜰 숫자가 손계산과 같은지를
    고정한다.
    """
    baseline = _report("dc-baseline", [_zone("wa-1", cut=5000.0, fill=0.0)])
    latest = _report("dc-latest", [_zone("wa-1", cut=1240.0, fill=0.0)])

    derived = derive_progress(baseline, latest, site_id="site-1")

    assert derived.detail is None
    assert derived.progress is not None
    zone = derived.progress.zones[0]
    assert zone.planned_cut_m3 == pytest.approx(5000.0)
    assert zone.remaining_cut_m3 == pytest.approx(1240.0)
    assert zone.done_cut_m3 == pytest.approx(3760.0)
    assert zone.cut_progress_ratio == pytest.approx(0.752)
    # 성토는 계획이 없다 — 0% 가 아니라 '해당 없음'이다.
    assert zone.fill_progress_ratio is None
    assert "해당 없음" in zone.basis


def test_zone_names_are_attached_when_work_areas_are_known() -> None:
    baseline = _report("dc-b", [_zone("wa-site-1-0001", cut=100.0, fill=0.0)])
    latest = _report("dc-l", [_zone("wa-site-1-0001", cut=40.0, fill=0.0)])
    derived = derive_progress(
        baseline, latest, site_id="site-1", zone_names={"wa-site-1-0001": "A공구 절토부"}
    )
    assert derived.progress is not None
    assert derived.progress.zones[0].zone_name == "A공구 절토부"


# ── 이어붙이기 거부 ─────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"sha256": "c" * 64}, "설계면 판"),
        ({"threshold_m": 0.10}, "집계 문턱"),
        ({"datum": VerticalDatum.ORTHOMETRIC_KNGEOID2024}, "수직기준"),
        ({"crs": "EPSG:5187"}, "좌표계"),
    ],
)
def test_refuses_to_join_reports_measured_with_a_different_ruler(
    kwargs: dict[str, object], expected: str
) -> None:
    """다른 자로 잰 두 값의 차이는 진척이 아니다 — 그런데 화면에서는 그냥 숫자로 보인다."""
    baseline = _report("dc-b", [_zone("wa-1", cut=100.0, fill=0.0)])
    latest = _report("dc-l", [_zone("wa-1", cut=40.0, fill=0.0)], **kwargs)  # type: ignore[arg-type]

    derived = derive_progress(baseline, latest, site_id="site-1")

    assert derived.progress is None
    assert derived.detail is not None
    assert expected in derived.detail


def test_refuses_when_baseline_and_latest_are_the_same_report() -> None:
    report = _report("dc-same", [_zone("wa-1", cut=100.0, fill=0.0)])
    derived = derive_progress(report, report, site_id="site-1")
    assert derived.progress is None
    assert derived.detail is not None
    assert "같은 리포트" in derived.detail


def test_zones_that_exist_on_only_one_side_are_reported_not_dropped_silently() -> None:
    """조용히 빠지면 총합이 달라진 이유를 아무도 모른다."""
    baseline = _report(
        "dc-b", [_zone("wa-1", cut=100.0, fill=0.0), _zone("wa-2", cut=50.0, fill=0.0)]
    )
    latest = _report("dc-l", [_zone("wa-1", cut=40.0, fill=0.0)])

    derived = derive_progress(baseline, latest, site_id="site-1")

    assert derived.progress is not None
    assert [z.zone_id for z in derived.progress.zones] == ["wa-1"]
    assert derived.unmatched_zone_ids == ("wa-2",)


def test_no_common_zone_means_no_table_and_a_reason() -> None:
    """즉석으로 그린 폴리곤은 매번 다른 구역이 된다 — 그 사실을 화면이 말해야 한다."""
    baseline = _report("dc-b", [_zone("zone-old", cut=100.0, fill=0.0)])
    latest = _report("dc-l", [_zone("zone-new", cut=40.0, fill=0.0)])

    derived = derive_progress(baseline, latest, site_id="site-1")

    assert derived.progress is None
    assert derived.detail is not None
    assert "같은 작업구역" in derived.detail


# ── 현장에서 실제로 일어나는 상태 ────────────────────────────────────────
def test_backfill_makes_done_negative_and_says_so() -> None:
    """되메우기·재시공·붕괴 — 계산 오류가 아니라 현장 상태다. 막지 않고 이름을 준다."""
    baseline = _report("dc-b", [_zone("wa-1", cut=100.0, fill=0.0)])
    latest = _report("dc-l", [_zone("wa-1", cut=150.0, fill=0.0)])

    derived = derive_progress(baseline, latest, site_id="site-1")

    assert derived.progress is not None
    zone = derived.progress.zones[0]
    assert zone.done_cut_m3 == pytest.approx(-50.0)
    assert zone.cut_progress_ratio == pytest.approx(-0.5)
    assert "되메우기" in zone.basis


def test_overshoot_is_allowed_and_named() -> None:
    """설계보다 더 깎았다(과굴착) — 진척률이 1.0 을 넘는 것이 정상 표현이다."""
    baseline = _report("dc-b", [_zone("wa-1", cut=100.0, fill=0.0)])
    latest = _report("dc-l", [_zone("wa-1", cut=0.0, fill=20.0)])

    derived = derive_progress(baseline, latest, site_id="site-1")

    assert derived.progress is not None
    zone = derived.progress.zones[0]
    assert zone.cut_progress_ratio == pytest.approx(1.0)
    assert zone.done_fill_m3 == pytest.approx(-20.0)
    assert "되메우기" in zone.basis or "과굴착" in zone.basis


# ── 계약 자체가 보는 모순 ───────────────────────────────────────────────
def test_contract_refuses_done_that_does_not_match_planned_minus_remaining() -> None:
    """파생값이라 계산이 한 곳뿐이지만, 그 한 곳이 틀렸을 때 그럴듯한 표를 막는다."""
    with pytest.raises(ValidationError, match="계획−잔여"):
        ZoneProgress(
            zone_id="wa-1",
            planned_cut_m3=100.0,
            planned_fill_m3=0.0,
            remaining_cut_m3=40.0,
            remaining_fill_m3=0.0,
            done_cut_m3=999.0,  # 60.0 이어야 한다
            done_fill_m3=0.0,
            cut_progress_ratio=9.99,
            fill_progress_ratio=None,
            basis="테스트",
        )


def test_contract_refuses_a_ratio_when_there_is_no_plan() -> None:
    with pytest.raises(ValidationError, match="0으로 나눌 수 없고"):
        ZoneProgress(
            zone_id="wa-1",
            planned_cut_m3=0.0,
            planned_fill_m3=0.0,
            remaining_cut_m3=0.0,
            remaining_fill_m3=0.0,
            done_cut_m3=0.0,
            done_fill_m3=0.0,
            cut_progress_ratio=0.0,  # 계획이 없는데 0% 라고 적으면 반대 뜻이 된다
            fill_progress_ratio=None,
            basis="테스트",
        )


def test_contract_refuses_a_missing_ratio_when_a_plan_exists() -> None:
    with pytest.raises(ValidationError, match="비워두면"):
        ZoneProgress(
            zone_id="wa-1",
            planned_cut_m3=100.0,
            planned_fill_m3=0.0,
            remaining_cut_m3=40.0,
            remaining_fill_m3=0.0,
            done_cut_m3=60.0,
            done_fill_m3=0.0,
            cut_progress_ratio=None,
            fill_progress_ratio=None,
            basis="테스트",
        )
