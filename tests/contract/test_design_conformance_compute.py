"""설계 대비 잔량 계산 — **부호**와 **결정성**이 이 파일의 전부다 (M4-A 5단계).

계산 엔진(``align_and_diff``·``volume_delta_in_polygon``)은 M1 에서 이미 검증됐다.
여기서 새로 지는 위험은 둘뿐이라, 그 둘을 손계산과 바이트 비교로 못박는다:

1. **부호** — ``align_and_diff(baseline, current)`` 는 ``current - baseline`` 을
   내는데, 설계 대비 잔량은 ``설계 − 현재`` 를 원한다. 그래서 호출부가 인자를
   뒤집어 넣는다. 뒤집기를 빠뜨리거나 두 번 하면 "1100m³ 쌓아야 함"이 "1100m³
   깎아야 함"으로 바뀌면서도 화면에서는 여전히 그럴듯하다. 그래서 골든 케이스를
   **cut ≠ fill 인 비대칭 지형**으로 만든다 — 모든 셀이 같은 부호면 뒤집혀도
   테스트가 통과한다.
2. **결정성** — 같은 입력이 같은 바이트를 내야 ``DiffRasterRef.digest`` 가
   재현 가능한 사실이 되고, Core 의 재해싱 확인이 의미를 갖는다.

가짜인 것은 스토리지 트랜스포트와 "Core 가 확인했다"는 시각뿐이다. GeoTIFF 는
rasterio 로 진짜로 쓰고, 차분·마스킹·재투영·해시는 전부 실제 코드가 한다.

## 골든 지형 (손계산)

20×20 셀, 1m 격자, EPSG:5186.

.. code-block:: text

    현재 DSM  z = 100 + col       (col 0..19 → 100..119)
    설계면    z = 110  (평탄)
    delta = 설계 − 현재 = 10 − col

    col 0..9  : delta = +10..+1  → 쌓아야 함(fill)
    col 10    : delta = 0        → 집계 제외
    col 11..19: delta = −1..−9   → 깎아야 함(cut)

    fill = (10+9+…+1) × 20행 × 1m² = 1100 m³
    cut  = (1+2+…+9)  × 20행 × 1m² =  900 m³
    net  = fill − cut = +200 m³ (순 성토 필요)

부호가 뒤집히면 1100 과 900 이 자리를 바꾸고 net 은 −200 이 된다 — 세 값 모두
어긋나므로 반드시 실패한다.
"""

from __future__ import annotations

import math
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import rasterio
from ksi_change_detection.diff_raster import (
    NON_DETERMINISTIC_TIFF_TAGS,
    sha256_of_file,
    write_diff_geotiff,
)
from ksi_change_detection.dsm_diff import align_and_diff
from ksi_change_detection.run_design_conformance import (
    CurrentDsmSource,
    DesignConformanceRunError,
    DesignSource,
    compute_design_conformance,
)
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy, current_comparison_policy
from ksi_event_contracts.design_conformance_report import DesignConformanceReport
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalDatumIncompatibleError,
    VerticalReference,
    VerticalReferenceSource,
)
from rasterio.transform import from_origin

_ORIGIN_X = 200_000.0
_ORIGIN_Y = 550_000.0
_SIZE = 20
_CRS = "EPSG:5186"
_NODATA = -9999.0

_COMPUTED_AT = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
_VERIFIED_AT = datetime(2026, 8, 12, 3, 0, 30, tzinfo=UTC)

_EXPECTED_FILL_M3 = 1100.0
_EXPECTED_CUT_M3 = 900.0

_CURRENT_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis="ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)
_DESIGN_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL,
    basis="설계사 제공 도면 표제부에 타원체고 명시",
    source=VerticalReferenceSource.USER_DECLARED,
)
_ORTHOMETRIC_VERTICAL = VerticalReference(
    datum=VerticalDatum.ORTHOMETRIC_KNGEOID2018,
    basis="설계사가 국가 수준점 기준 정표고로 작성했다고 표기",
    source=VerticalReferenceSource.USER_DECLARED,
)


def _write_raster(path: Path, values: np.ndarray) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=_SIZE,
        width=_SIZE,
        count=1,
        dtype="float64",
        crs=_CRS,
        nodata=_NODATA,
        transform=from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(values.astype(np.float64), 1)
    return path


def _ramp(*, nodata_cols: tuple[int, ...] = ()) -> np.ndarray:
    """서→동으로 1m/셀 오르는 현재 지형. ``nodata_cols`` 는 측정 불가 열."""
    cols = np.arange(_SIZE, dtype=np.float64)
    values = np.tile(100.0 + cols, (_SIZE, 1))
    for col in nodata_cols:
        values[:, col] = _NODATA
    return values


def _flat(level: float = 110.0) -> np.ndarray:
    return np.full((_SIZE, _SIZE), level, dtype=np.float64)


def _full_extent_zone() -> dict[str, Any]:
    """래스터 전체를 덮는 구역(설계면과 같은 좌표계) — 손계산이 성립하는 배치."""
    ring = [
        [_ORIGIN_X, _ORIGIN_Y],
        [_ORIGIN_X + _SIZE, _ORIGIN_Y],
        [_ORIGIN_X + _SIZE, _ORIGIN_Y - _SIZE],
        [_ORIGIN_X, _ORIGIN_Y - _SIZE],
        [_ORIGIN_X, _ORIGIN_Y],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _storage(files: dict[str, Path]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = files.get(request.url.path.rsplit("/", 1)[-1])
        if path is None:
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    return httpx.Client(transport=httpx.MockTransport(handler))


class _Publisher:
    """래스터를 올리고 'Core 가 재해싱해 확인한 시각'을 돌려주는 쪽의 대역.

    가짜인 것은 **업로드와 확인 시각**뿐이다 — 넘겨받은 digest·크기는 실제
    파일에서 계산된 값이고, 이 대역은 그것을 그대로 기록해 테스트가 대조한다.
    """

    def __init__(self, verified_at: datetime = _VERIFIED_AT) -> None:
        self._verified_at = verified_at
        self.calls: list[tuple[Path, str, int]] = []

    def publish_diff_raster(self, path: Path, *, digest: str, size_bytes: int) -> datetime:
        self.calls.append((path, digest, size_bytes))
        return self._verified_at


@pytest.fixture
def golden(tmp_path: Path) -> tuple[httpx.Client, CurrentDsmSource, DesignSource]:
    """경사 현재 지형 + 평탄 설계면 — 모듈 docstring 의 손계산 배치."""
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    storage = _storage({"current-dsm": current_path, "design": design_path})
    current = CurrentDsmSource(
        ref=ArtifactRef(job_id="job-1", artifact_id="dsm-current"),
        download_url="https://storage.invalid/current-dsm",
        vertical_reference=_CURRENT_VERTICAL,
    )
    design = DesignSource(
        design_surface_id="ds-1",
        sha256=sha256_of_file(design_path).removeprefix("sha256:"),
        download_url="https://storage.invalid/design",
        vertical_reference=_DESIGN_VERTICAL,
    )
    return storage, current, design


def _run(
    storage: httpx.Client,
    current: CurrentDsmSource,
    design: DesignSource,
    *,
    publisher: _Publisher | None = None,
    policy: ComparisonPolicy | None = None,
    zones: dict[str, dict[str, Any]] | None = None,
    work_dir: Path | None = None,
) -> tuple[DesignConformanceReport, Path]:
    return compute_design_conformance(
        design_conformance_id="dc-1",
        diff_raster_id="dr-1",
        current_dsm=current,
        design=design,
        zones=zones if zones is not None else {"zone-all": _full_extent_zone()},
        zone_crs=_CRS,
        policy=policy or current_comparison_policy(),
        computed_at=_COMPUTED_AT,
        http_client=storage,
        publish_diff_raster=publisher or _Publisher(),
        work_dir=work_dir,
    )


# ── 부호 골든 ──────────────────────────────────────────────────────────────


def test_sign_golden_fill_is_what_must_be_added_cut_is_what_must_be_removed(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[핵심] 설계가 현재보다 높은 곳은 성토, 낮은 곳은 절토 — 손계산과 정확히 일치.

    부호가 뒤집히면 1100 과 900 이 자리를 바꾸므로 세 단언이 모두 깨진다.
    """
    storage, current, design = golden
    report, raster_path = _run(storage, current, design)
    try:
        zone = report.zones[0]
        assert zone.fill_m3 == pytest.approx(_EXPECTED_FILL_M3)
        assert zone.cut_m3 == pytest.approx(_EXPECTED_CUT_M3)
        assert zone.net_m3 == pytest.approx(_EXPECTED_FILL_M3 - _EXPECTED_CUT_M3)
        # 비대칭이 아니면 이 테스트는 부호를 못 잡는다 — 그 전제를 명시한다.
        assert zone.fill_m3 != pytest.approx(zone.cut_m3)
        assert zone.area_m2 == pytest.approx(float(_SIZE * _SIZE))
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


def test_diff_raster_values_have_the_same_sign_as_the_numbers(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[핵심] 지도와 표가 같은 말을 한다 — 서쪽(설계가 높음)은 양수, 동쪽은 음수."""
    storage, current, design = golden
    report, raster_path = _run(storage, current, design)
    try:
        with rasterio.open(raster_path) as dataset:
            values = dataset.read(1)
        # col 0 은 설계 110 − 현재 100 = +10(쌓아야 함), col 19 는 −9(깎아야 함).
        assert values[0, 0] == pytest.approx(10.0)
        assert values[0, 19] == pytest.approx(-9.0)
        assert values[0, 10] == pytest.approx(0.0)
        assert report.zones[0].net_m3 > 0.0  # 순 성토 필요
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


def test_report_numbers_can_be_recomputed_from_the_stored_raster(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[핵심] 숫자와 지도가 **같은 배열**에서 나온다 — 래스터를 같은 문턱으로 다시
    집계하면 리포트의 구역 값이 그대로 나온다. 여기가 갈리면 화면의 히트맵이
    표와 다른 진실을 말하게 되고, 그 불일치는 어느 화면에서도 보이지 않는다."""
    storage, current, design = golden
    report, raster_path = _run(storage, current, design)
    try:
        with rasterio.open(raster_path) as dataset:
            values = dataset.read(1)
            cell_area = abs(dataset.transform.a * dataset.transform.e)
        zone = report.zones[0]
        finite = values[np.isfinite(values)]
        counted = finite[np.abs(finite) >= zone.threshold_m]
        fill = float(counted[counted > 0].sum() * cell_area)
        cut = float(-counted[counted < 0].sum() * cell_area)
        assert fill == pytest.approx(zone.fill_m3, rel=1e-6)
        assert cut == pytest.approx(zone.cut_m3, rel=1e-6)
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


# ── 래스터 결정성 ──────────────────────────────────────────────────────────


def _diff_of(tmp_path: Path) -> Any:
    current_path = _write_raster(tmp_path / "c.tif", _ramp())
    design_path = _write_raster(tmp_path / "d.tif", _flat())
    return align_and_diff(current_path, design_path)


def test_writing_the_same_diff_twice_produces_identical_bytes(tmp_path: Path) -> None:
    """[핵심] 같은 입력 2회 → 같은 sha256.

    1초를 넘겨 기다린 뒤 두 번째를 쓴다 — TIFF 의 시각 태그는 초 단위라, 기다리지
    않으면 비결정 태그가 있어도 우연히 같은 바이트가 나올 수 있다.
    """
    diff = _diff_of(tmp_path)
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"
    write_diff_geotiff(diff, first)
    time.sleep(1.1)
    write_diff_geotiff(diff, second)

    assert sha256_of_file(first) == sha256_of_file(second)
    assert first.read_bytes() == second.read_bytes()


def test_no_timestamp_or_version_tags_are_written(tmp_path: Path) -> None:
    """[회귀] 비결정 태그가 들어오면 바이트 비교보다 **먼저** 이유와 함께 깨진다."""
    diff = _diff_of(tmp_path)
    path = tmp_path / "tagged.tif"
    write_diff_geotiff(diff, path)

    with rasterio.open(path) as dataset:
        tags = dataset.tags()
    present = [tag for tag in NON_DETERMINISTIC_TIFF_TAGS if tag in tags]
    assert not present, f"비결정 태그가 실렸다: {present} — 프로파일에서 명시적으로 제거해야 한다"


def test_the_fixed_profile_is_actually_on_the_file(tmp_path: Path) -> None:
    """프로파일이 '고정'이라고 말만 하지 않는다 — 파일에서 되읽어 확인한다."""
    diff = _diff_of(tmp_path)
    path = tmp_path / "profile.tif"
    write_diff_geotiff(diff, path)

    with rasterio.open(path) as dataset:
        profile = dataset.profile
        assert dataset.block_shapes == [(256, 256)]
    assert profile["driver"] == "GTiff"
    assert profile["dtype"] == "float32"
    assert profile["count"] == 1
    assert profile["compress"] == "deflate"
    assert profile["tiled"] is True
    assert math.isnan(profile["nodata"])


def test_invalid_cells_are_nan_not_zero(tmp_path: Path) -> None:
    """[핵심] '모름'을 0 으로 쓰면 지도가 '설계대로 됐다'고 거짓말한다."""
    current_path = _write_raster(tmp_path / "c.tif", _ramp(nodata_cols=(3, 4)))
    design_path = _write_raster(tmp_path / "d.tif", _flat())
    diff = align_and_diff(current_path, design_path)
    path = tmp_path / "nan.tif"
    write_diff_geotiff(diff, path)

    with rasterio.open(path) as dataset:
        values = dataset.read(1)
    assert np.isnan(values[:, 3]).all()
    assert np.isnan(values[:, 4]).all()
    assert np.isfinite(values[:, 0]).all()


def test_identical_inputs_produce_an_identical_report_and_raster(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """종단 결정성 — 리포트도 래스터 digest 도 두 번 다 같다."""
    storage, current, design = golden
    first, first_path = _run(storage, current, design)
    second, second_path = _run(storage, current, design)
    try:
        assert first == second
        assert first.diff_raster.digest == second.diff_raster.digest
        assert sha256_of_file(first_path) == sha256_of_file(second_path)
    finally:
        shutil.rmtree(first_path.parent, ignore_errors=True)
        shutil.rmtree(second_path.parent, ignore_errors=True)


# ── 리포트가 사실만 싣는가 ────────────────────────────────────────────────


def test_digest_and_size_in_the_report_are_the_real_file(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[핵심] 리포트의 digest·크기는 실제로 올라간 그 파일에서 잰 값이다."""
    storage, current, design = golden
    publisher = _Publisher()
    report, raster_path = _run(storage, current, design, publisher=publisher)
    try:
        (published_path, digest, size_bytes) = publisher.calls[0]
        assert published_path == raster_path
        assert digest == sha256_of_file(raster_path)
        assert size_bytes == raster_path.stat().st_size
        assert report.diff_raster.digest == digest
        assert report.diff_raster.size_bytes == size_bytes
        assert report.diff_raster.core_verified_digest_at == _VERIFIED_AT
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


def test_raster_geometry_in_the_report_matches_the_file(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """참조가 말하는 격자와 파일의 격자가 같다 — 지도가 엉뚱한 자리에 그려지지 않게."""
    storage, current, design = golden
    report, raster_path = _run(storage, current, design)
    try:
        with rasterio.open(raster_path) as dataset:
            assert report.diff_raster.width == dataset.width
            assert report.diff_raster.height == dataset.height
            assert report.diff_raster.transform == pytest.approx(
                tuple(dataset.transform)[:6]
            )
        assert report.diff_raster.pixel_size_x_m == pytest.approx(1.0)
        assert report.diff_raster.pixel_size_y_m == pytest.approx(1.0)
        assert report.crs == _CRS
        assert report.diff_raster.crs == _CRS
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


def test_uncertainty_is_null_and_says_why(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[핵심 정직성] 설계면에는 RMSE 가 없다 → 오차한계 없음 + 사유 (INV-024)."""
    storage, current, design = golden
    report, raster_path = _run(storage, current, design)
    try:
        zone = report.zones[0]
        assert zone.uncertainty_m3 is None
        assert "설계면" in zone.uncertainty_note
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


def test_threshold_comes_from_the_policy_snapshot_only(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """문턱값은 정책 스냅샷 한 곳에서만 온다 — 구역·래스터 참조가 같은 값을 싣는다."""
    storage, current, design = golden
    policy = current_comparison_policy().model_copy(update={"volume_threshold_m": 2.0})
    report, raster_path = _run(storage, current, design, policy=policy)
    try:
        assert report.diff_raster.threshold_m == pytest.approx(2.0)
        assert report.zones[0].threshold_m == pytest.approx(2.0)
        # |delta| < 2 인 col 9(+1)·10(0)·11(−1) 이 빠진다: fill 1100−1=1099,
        # cut 900−1=899. 문턱이 실제로 집계에 걸렸다는 증거다.
        assert report.zones[0].fill_m3 == pytest.approx(_EXPECTED_FILL_M3 - 20.0)
        assert report.zones[0].cut_m3 == pytest.approx(_EXPECTED_CUT_M3 - 20.0)
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


def test_diff_raster_vertical_reference_is_pipeline_declared_and_inherits_the_dsm_datum(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """차분 격자의 수직기준은 우리 파이프라인의 귀속이고, 실측된 쪽 datum 을 승계한다.

    현재 DSM 이 ``ellipsoidal_native``(변환하지 못해 남은 상태)면 그것을 빼서 만든
    격자도 같은 상태다 — 설계면 쪽 ``ellipsoidal`` 을 물려받으면 "의도적으로 고른
    기준"이라는 뜻이 붙어 재처리 대상 표시가 사라진다.
    """
    storage, current, design = golden
    report, raster_path = _run(storage, current, design)
    try:
        reference = report.diff_raster.vertical_reference
        assert reference.source is VerticalReferenceSource.PIPELINE_DECLARED
        assert reference.datum is VerticalDatum.ELLIPSOIDAL_NATIVE
        assert report.vertical_reference.datum is reference.datum
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


# ── fail-closed ────────────────────────────────────────────────────────────


def test_incompatible_vertical_datums_are_refused_before_any_download(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[핵심][음성] 타원체고와 정표고를 그냥 빼지 않는다 — 다운로드조차 하지 않는다."""
    _storage_client, current, design = golden
    orthometric_design = DesignSource(
        design_surface_id=design.design_surface_id,
        sha256=design.sha256,
        download_url=design.download_url,
        vertical_reference=_ORTHOMETRIC_VERTICAL,
    )

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("수직기준이 맞지 않는데 바이트를 받으러 갔다")

    with pytest.raises(VerticalDatumIncompatibleError):
        _run(
            httpx.Client(transport=httpx.MockTransport(explode)),
            current,
            orthometric_design,
        )


def test_a_design_file_that_changed_since_verification_is_refused(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[핵심][음성] 검증 때 잰 그 파일이 아니면 숫자를 내지 않는다."""
    storage, current, design = golden
    tampered = DesignSource(
        design_surface_id=design.design_surface_id,
        sha256="0" * 64,
        download_url=design.download_url,
        vertical_reference=design.vertical_reference,
    )
    with pytest.raises(DesignConformanceRunError) as excinfo:
        _run(storage, current, tampered)
    assert "검증 시점과 다르다" in str(excinfo.value)


def test_no_zones_is_a_refusal_not_an_empty_report(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[음성] 잴 구역이 없으면 빈 리포트가 아니라 거부다."""
    storage, current, design = golden
    with pytest.raises(DesignConformanceRunError):
        _run(storage, current, design, zones={})


def test_download_failure_does_not_leak_the_presigned_signature(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[회귀] 실패 사유는 FAILED detail 로 원장·화면에 남는다 — 서명이 새면 그 URL 로
    누구나 원본을 받을 수 있다(비교 워커 쪽에서 실제로 발생했던 결함과 같은 자리)."""
    storage, current, design = golden
    missing = DesignSource(
        design_surface_id=design.design_surface_id,
        sha256=design.sha256,
        download_url="https://storage.invalid/nope?X-Amz-Signature=deadbeef1234",
        vertical_reference=design.vertical_reference,
    )
    with pytest.raises(DesignConformanceRunError) as excinfo:
        _run(storage, current, missing)
    assert "deadbeef1234" not in str(excinfo.value)
    assert "X-Amz-Signature" not in str(excinfo.value)


def test_a_failed_run_leaves_no_raster_behind(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource], tmp_path: Path
) -> None:
    """[음성] 실패하면 호출자는 경로를 못 받는다 — 그 파일을 남기면 아무도 안 지운다."""
    storage, current, design = golden
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    tampered = DesignSource(
        design_surface_id=design.design_surface_id,
        sha256="1" * 64,
        download_url=design.download_url,
        vertical_reference=design.vertical_reference,
    )
    with pytest.raises(DesignConformanceRunError):
        _run(storage, current, tampered, work_dir=work_dir)
    assert list(work_dir.iterdir()) == []


def test_a_publisher_that_refuses_prevents_the_report(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource], tmp_path: Path
) -> None:
    """[핵심][음성] Core 가 digest 를 확인해주지 않으면 리포트 자체가 만들어지지 않는다.

    ``coreVerifiedDigestAt`` 은 "Core 가 바이트를 다시 해싱해 확인한 시각"이라
    지어낼 수 없는 값이다. 확인이 없었는데 리포트가 나오면 그 필드는 거짓이 된다.
    """
    storage, current, design = golden
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    class _Refusing:
        def publish_diff_raster(self, path: Path, *, digest: str, size_bytes: int) -> datetime:
            raise RuntimeError("digest 확인 실패")

    with pytest.raises(RuntimeError, match="digest 확인 실패"):
        compute_design_conformance(
            design_conformance_id="dc-x",
            diff_raster_id="dr-x",
            current_dsm=current,
            design=design,
            zones={"zone-all": _full_extent_zone()},
            zone_crs=_CRS,
            policy=current_comparison_policy(),
            computed_at=_COMPUTED_AT,
            http_client=storage,
            publish_diff_raster=_Refusing(),
            work_dir=work_dir,
        )
    assert list(work_dir.iterdir()) == []


def test_a_zone_outside_the_raster_fails_as_a_typed_run_error(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource],
) -> None:
    """[음성] 잴 수 없는 구역은 '변화 0' 이 아니다 — 워커가 FAILED 로 보고할 수 있게
    ``DsmDiffError`` 를 이 모듈의 타입으로 감싼다(비교 경로와 대칭)."""
    storage, current, design = golden
    far = _ORIGIN_X + 10_000.0
    ring = [
        [far, _ORIGIN_Y],
        [far + 10.0, _ORIGIN_Y],
        [far + 10.0, _ORIGIN_Y - 10.0],
        [far, _ORIGIN_Y - 10.0],
        [far, _ORIGIN_Y],
    ]
    with pytest.raises(DesignConformanceRunError):
        _run(
            storage,
            current,
            design,
            zones={"zone-far": {"type": "Polygon", "coordinates": [ring]}},
        )
