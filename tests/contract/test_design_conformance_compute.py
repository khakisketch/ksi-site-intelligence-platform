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
from ksi_geo_spatial.crs import reproject_point
from ksi_geo_spatial.vertical import GeoidGrid, GeoidUnavailableError
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
#: 격자를 갖고 있지 **않은** 모델로 선언된 정표고 — 계열이 맞아도 이을 수 없다.
_ORTHOMETRIC_VERTICAL = VerticalReference(
    datum=VerticalDatum.ORTHOMETRIC_KNGEOID2018,
    basis="설계사가 국가 수준점 기준 정표고로 작성했다고 표기",
    source=VerticalReferenceSource.USER_DECLARED,
)
#: 실무 도면의 정상 경로 — 우리가 격자를 가진 모델로 선언된 해발 높이.
_ORTHOMETRIC_2024_VERTICAL = VerticalReference(
    datum=VerticalDatum.ORTHOMETRIC_KNGEOID2024,
    basis="설계사 제공 도면 표제부에 인천 평균해면 기준 표고 명시",
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
    geoid_grid: GeoidGrid | None = None,
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
        geoid_grid=geoid_grid,
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


# ── 정표고 설계면: 지오이드 격자로 이어서 계산한다 ─────────────────────────
#
# 실무 설계도면은 거의 항상 해발(정표고)이고 우리 파이프라인은 타원체고를 낸다.
# 이 절의 테스트가 지키는 것은 셋이다: **변환량이 손계산과 같은가**, **변환해서
# 낸 숫자가 처음부터 같은 계열이었을 때와 같은가**, **격자가 없으면 숫자를 만들지
# 않는가**.
#
# 합성 격자는 **경도에 대해 기울어져 있다**(N = base + slope×(lon−ref)). 상수
# 격자를 쓰면 "구역 대표점 하나로 상수 보정"하는 구현도 통과해 버리는데, 실 격자의
# 기울기는 1km 현장에서 최대 4cm(집계 문턱 0.05m 와 같은 자릿수)라 그 구현은
# 틀린 것이다. 기울기가 있으면 셀별 보간만 통과한다.
#
# 1도 셀의 이중선형 보간은 **경도에 선형인 함수를 정확히 재현**하므로, 기대 N 을
# 해석식으로 손계산할 수 있다 — 격자 파일 없이도 골든이 성립한다.

_GEOID_BASE_M = 25.0
_GEOID_SLOPE_M_PER_DEG = 10.0
_GEOID_REF_LON = 126.5


def _expected_n_m(lon_deg: float) -> float:
    """합성 격자가 그 경도에서 내놓아야 하는 지오이드고(해석식)."""
    return _GEOID_BASE_M + _GEOID_SLOPE_M_PER_DEG * (lon_deg - _GEOID_REF_LON)


def _synthetic_geoid_grid(path: Path, *, far_away: bool = False) -> GeoidGrid:
    """경도로 기울어진 합성 지오이드 격자(EPSG:4326, 1도 셀).

    ``far_away`` 면 시험용 래스터가 격자 **밖**에 놓이도록 서쪽으로 옮긴다 —
    외삽 금지(INV-023)를 시험하는 배치다.
    """
    west = 120.0 if far_away else 126.0
    north = 39.0
    rows, cols = 5, 5
    lons = west + 0.5 + np.arange(cols, dtype=np.float64)
    values = np.tile(
        _GEOID_BASE_M + _GEOID_SLOPE_M_PER_DEG * (lons - _GEOID_REF_LON), (rows, 1)
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=from_origin(west, north, 1.0, 1.0),
    ) as dataset:
        dataset.write(values, 1)
    return GeoidGrid.from_path(path)


def _cell_lonlat(row: int, col: int) -> tuple[float, float]:
    """시험용 래스터 (row, col) 셀 **중심**의 경위도.

    구현이 쓰는 ``rasterio.warp.transform`` 이 아니라 ``reproject_point`` 로 따로
    계산한다 — 같은 함수로 기대값을 만들면 반 셀 밀림·행열 뒤바뀜을 못 잡는다.
    """
    return reproject_point(
        _ORIGIN_X + col + 0.5, _ORIGIN_Y - row - 0.5, from_crs=_CRS, to_crs="EPSG:4326"
    )


def _orthometric_of(ellipsoidal: np.ndarray) -> np.ndarray:
    """같은 지형을 **정표고로 적어 놓은** 설계면 — H = h − N (셀마다 다른 N)."""
    out = ellipsoidal.astype(np.float64).copy()
    for row in range(_SIZE):
        for col in range(_SIZE):
            lon, _lat = _cell_lonlat(row, col)
            out[row, col] -= _expected_n_m(lon)
    return out


def _orthometric_design(
    tmp_path: Path,
    values: np.ndarray,
    *,
    name: str = "design-ortho",
    current_values: np.ndarray | None = None,
) -> tuple[httpx.Client, CurrentDsmSource, DesignSource]:
    current_path = _write_raster(
        tmp_path / "current.tif", _ramp() if current_values is None else current_values
    )
    design_path = _write_raster(tmp_path / f"{name}.tif", values)
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
        vertical_reference=_ORTHOMETRIC_2024_VERTICAL,
    )
    return storage, current, design


def test_orthometric_design_converted_equals_the_same_surface_declared_ellipsoidal(
    golden: tuple[httpx.Client, CurrentDsmSource, DesignSource], tmp_path: Path
) -> None:
    """[핵심] 등가성 — 같은 설계면을 정표고로 넣고 변환한 결과 == 타원체고로 넣은 결과.

    설계면을 ``H = 110 − N`` 로 적어 두면 변환 후 정확히 110(평탄 설계면)이 되어야
    한다. 그러면 구역 수량이 이 파일의 골든(성토 1100 / 절토 900 / 순 +200)과
    **완전히** 같아야 한다. N 을 상수로 보정하거나 부호를 뒤집으면 여기서 깨진다.
    """
    grid = _synthetic_geoid_grid(tmp_path / "geoid.tif")
    storage, current, design = _orthometric_design(tmp_path, _orthometric_of(_flat()))

    converted, converted_path = _run(storage, current, design, geoid_grid=grid)
    ellipsoidal_storage, ellipsoidal_current, ellipsoidal_design = golden
    baseline, baseline_path = _run(
        ellipsoidal_storage, ellipsoidal_current, ellipsoidal_design
    )
    try:
        zone = converted.zones[0]
        assert zone.fill_m3 == pytest.approx(_EXPECTED_FILL_M3, abs=1e-6)
        assert zone.cut_m3 == pytest.approx(_EXPECTED_CUT_M3, abs=1e-6)
        assert zone.net_m3 == pytest.approx(_EXPECTED_FILL_M3 - _EXPECTED_CUT_M3, abs=1e-6)
        assert zone.fill_m3 == pytest.approx(baseline.zones[0].fill_m3, abs=1e-6)
        assert zone.cut_m3 == pytest.approx(baseline.zones[0].cut_m3, abs=1e-6)
    finally:
        shutil.rmtree(converted_path.parent, ignore_errors=True)
        shutil.rmtree(baseline_path.parent, ignore_errors=True)


def test_the_applied_geoid_separation_matches_hand_calculation_cell_by_cell(
    tmp_path: Path,
) -> None:
    """[핵심] 변환량 골든 — 차분 격자에서 되짚은 N 이 셀마다 손계산과 같다.

    현재 지형을 평탄 100m 로 두고 설계면을 정표고 85m 로 두면
    ``delta = (85 + N) − 100`` 이므로 **차분 격자에서 N 을 그대로 되짚을 수 있다.**
    기대값은 합성 격자의 해석식(경도의 1차식)이라 구현과 무관하게 계산된다.
    """
    grid = _synthetic_geoid_grid(tmp_path / "geoid.tif")
    storage, current, design = _orthometric_design(
        tmp_path, _flat(85.0), current_values=_flat(100.0)
    )

    report, raster_path = _run(storage, current, design, geoid_grid=grid)
    try:
        with rasterio.open(raster_path) as dataset:
            delta = dataset.read(1)
        for row, col in ((0, 0), (0, 19), (19, 0), (10, 7)):
            lon, _lat = _cell_lonlat(row, col)
            expected = (85.0 + _expected_n_m(lon)) - 100.0
            assert float(delta[row, col]) == pytest.approx(expected, abs=1e-6), (
                f"({row},{col}) 셀의 지오이드 보정이 손계산과 다르다"
            )
        # 격자가 기울어져 있으므로 셀마다 값이 달라야 한다 — 전부 같으면 구역
        # 대표점 하나로 상수 보정한 것이고, 그 구현은 실 격자에서 최대 4cm 틀린다.
        assert float(delta[0, 0]) != pytest.approx(float(delta[0, 19]), abs=1e-9)
        assert report.zones[0].fill_m3 > 0.0
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


def test_the_report_says_which_grid_converted_which_direction(tmp_path: Path) -> None:
    """[핵심] 변환 사실이 결과에 남는다 — 화면이 그대로 읽어 준다.

    datum 은 실측된 현재 DSM 의 것을 승계하므로(``ellipsoidal_native``) 그 값만으로는
    "설계면이 정표고였다"를 알 수 없다. 그래서 근거(basis)에 격자·방향·적용량이
    실려야 하고, 대시보드는 이 문장을 숫자 바로 옆에 띄운다.
    """
    grid = _synthetic_geoid_grid(tmp_path / "geoid.tif")
    storage, current, design = _orthometric_design(
        tmp_path, _flat(85.0), current_values=_flat(100.0)
    )

    report, raster_path = _run(storage, current, design, geoid_grid=grid)
    try:
        basis = report.vertical_reference.basis
        assert "geoid.tif" in basis  # 어느 격자로
        assert grid.source_sha256 is not None and grid.source_sha256[:12] in basis
        assert "정표고 → 타원체고" in basis  # 어느 방향으로
        assert "h = H + N" in basis
        assert "20~30m" not in basis  # 거부 문구가 성공 리포트에 새어 나오지 않는다
        # 얼마나 — 합성 격자의 이 창에서 N 은 30m 대다(해석식과 대조).
        lon_west, _ = _cell_lonlat(0, 0)
        assert f"{_expected_n_m(lon_west):.3f}" in basis
        assert report.vertical_reference.datum is VerticalDatum.ELLIPSOIDAL_NATIVE
        assert report.diff_raster.vertical_reference.basis == basis
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


def test_a_design_outside_the_geoid_grid_is_refused_not_extrapolated(
    tmp_path: Path,
) -> None:
    """[음성] 격자 범위 밖은 외삽하지 않는다(INV-023) — 숫자를 만들지 않는다."""
    grid = _synthetic_geoid_grid(tmp_path / "geoid-far.tif", far_away=True)
    storage, current, design = _orthometric_design(tmp_path, _flat(85.0))

    with pytest.raises(GeoidUnavailableError):
        _run(storage, current, design, geoid_grid=grid)


def test_without_a_grid_an_orthometric_design_is_refused_before_any_download(
    tmp_path: Path,
) -> None:
    """[핵심][음성] 격자가 없으면 거부한다 — N=0 으로 대치하지 않고, 받으러 가지도 않는다.

    사유 타입이 ``GeoidUnavailableError`` 인 것이 요점이다:
    ``VerticalDatumIncompatibleError``("이 도면은 이을 수 없다")와 달리 이것은
    "격자를 붙이면 그대로 계산된다"는 뜻이라, 사람이 고칠 자리가 다르다.
    """
    _storage_client, current, design = _orthometric_design(tmp_path, _flat(85.0))

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("격자도 없는데 바이트를 받으러 갔다")

    with pytest.raises(GeoidUnavailableError) as excinfo:
        _run(httpx.Client(transport=httpx.MockTransport(explode)), current, design)
    message = str(excinfo.value)
    assert "KSI_GEOID_GRID" in message
    assert VerticalDatum.ORTHOMETRIC_KNGEOID2024.value in message


def test_a_grid_does_not_unlock_a_datum_we_have_no_grid_for(tmp_path: Path) -> None:
    """[음성] 격자를 쥐고 있어도 KNGeoid18 로 선언된 설계면은 거부한다.

    "정표고니까 아무 격자로나 되돌리면 된다"가 이 저장소의 규칙이 아니다 —
    되돌릴 격자는 **그 선언이 말하는 모델의 격자**여야 한다.
    """
    grid = _synthetic_geoid_grid(tmp_path / "geoid.tif")
    _storage_client, current, design = _orthometric_design(tmp_path, _flat(85.0))
    stale_model = DesignSource(
        design_surface_id=design.design_surface_id,
        sha256=design.sha256,
        download_url=design.download_url,
        vertical_reference=_ORTHOMETRIC_VERTICAL,
    )

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("이을 수 없는 수직기준인데 바이트를 받으러 갔다")

    with pytest.raises(VerticalDatumIncompatibleError):
        _run(
            httpx.Client(transport=httpx.MockTransport(explode)),
            current,
            stale_model,
            geoid_grid=grid,
        )


def test_conversion_keeps_nodata_cells_unmeasured(tmp_path: Path) -> None:
    """[음성] 변환이 '모름'을 숫자로 바꾸지 않는다 — nodata 는 nodata 로 남는다."""
    grid = _synthetic_geoid_grid(tmp_path / "geoid.tif")
    design_values = _orthometric_of(_flat())
    design_values[:, 5] = _NODATA
    storage, current, design = _orthometric_design(tmp_path, design_values)

    report, raster_path = _run(storage, current, design, geoid_grid=grid)
    try:
        with rasterio.open(raster_path) as dataset:
            delta = dataset.read(1)
        assert np.isnan(delta[:, 5]).all()
        assert np.isfinite(delta[:, 0]).all()
        # 그 열이 빠졌으므로 골든에서 그 열 몫(설계 110 − 현재 105 = +5, 20행)만
        # 줄어든다: 1100 − 100 = 1000.
        assert report.zones[0].fill_m3 == pytest.approx(_EXPECTED_FILL_M3 - 100.0, abs=1e-6)
    finally:
        shutil.rmtree(raster_path.parent, ignore_errors=True)


# ── 실 KNGeoid24 격자 대조 (격자 없는 환경에서는 skip) ─────────────────────
#
# 위 합성 격자 테스트가 변환 수학·배선을 상시 검증하므로 이 skip 은 "기능 미검증"이
# 아니다(test_geo_spatial_vertical.py 와 같은 관례). 여기서만 확인되는 것은 **실제
# 국가 격자를 물렸을 때 나오는 값**이다.

_REAL_KNGEOID24_PATH = Path("data/geoid/KNGeoid24.tif")

_real_grid_only = pytest.mark.skipif(
    not _REAL_KNGEOID24_PATH.is_file(),
    reason="실 KNGeoid24 격자 없음 — docs/geo/GEOID_ACQUISITION.md 취득·변환 절차 참조",
)


@_real_grid_only
def test_real_kngeoid24_grid_applies_the_expected_separation(tmp_path: Path) -> None:
    """[핵심] 실 격자 골든 — 시험 좌표(중부원점 200km/550km)에서 N=23.3809m 를 더한다.

    ``h = H + N`` 손계산: 설계면 정표고 85m, 현재 지형 평탄 100m →
    차분 = 85 + 23.3809 − 100 = 8.3809m. 격자 재변환·좌표 규약 변경 등으로 값이
    달라지면 이 골든이 깨진다(``test_geo_spatial_vertical`` 의 서울시청 23.325m
    고정과 같은 역할).
    """
    grid = GeoidGrid.from_path(_REAL_KNGEOID24_PATH)
    storage, current, design = _orthometric_design(tmp_path, _flat(85.0))

    report, raster_path = _run(storage, current, design, geoid_grid=grid)
    try:
        lon, lat = _cell_lonlat(0, 0)
        n_here = grid.height_at(lat_deg=lat, lon_deg=lon)
        assert n_here == pytest.approx(23.3809, abs=0.001)

        with rasterio.open(raster_path) as dataset:
            delta = dataset.read(1)
        assert float(delta[0, 0]) == pytest.approx(85.0 + n_here - 100.0, abs=1e-5)
        assert float(delta[0, 0]) == pytest.approx(8.3809, abs=0.001)
        assert "KNGeoid24.tif" in report.vertical_reference.basis
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
