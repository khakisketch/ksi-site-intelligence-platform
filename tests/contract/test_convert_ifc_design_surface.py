"""IFC → 설계면 GeoTIFF 변환 도구 계약 (tools/convert_ifc_design_surface.py).

고정하는 계약: (1) georeferencing 있는 IFC 가 손계산 골든값 그대로의 GeoTIFF 가
된다, (2) georeferencing 없음·IFC2X3 는 typed 거부다(조용한 로컬 좌표 진행 없음),
(3) 같은 입력 2회는 같은 바이트다(결정성 — 등록 경로의 digest 대조 전제),
(4) 산출물이 설계면 검증 워커의 실측(``measure_design_surface``)을 통과한다 —
즉 기존 설계면 등록 경로에 태울 수 있는 형태다, (5) 면 래스터화 결정의 실측
근거(정점만: 400셀 중 4셀 vs 면: 400셀)를 회귀로 남긴다.

픽스처는 ``test_ifc_reference_model.py`` 와 같은 방식(ifcopenshell 로 실물 IFC
조립)이다 — mock 이 아니라 도구가 실제로 읽을 파일이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.georeference
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import numpy as np
import pytest
import rasterio
from ksi_bim_integration.ifc_reference_model import (
    IfcReferenceModelError,
    sample_mesh_from_ifc,
)
from ksi_processing_controller.design_surface_verifier import measure_design_surface

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from convert_ifc_design_surface import (  # noqa: E402 -- 위 sys.path 조작 뒤에만 해석 가능
    IfcDesignSurfaceConversionError,
    _bake_faces,
    _grid_definition,
    _splat_vertices,
    convert,
)


def _build_ifc(
    tmp_path: Path,
    *,
    name: str,
    georeference: dict[str, float] | None,
    crs_name: str = "EPSG:5186",
    length_prefix: str | None = None,
    vertices: list[list[float]] | None = None,
    faces: list[list[list[int]]] | None = None,
) -> Path:
    """georeference 붙은 최소 IFC4 — 기본 지오메트리는 10m×10m 수평 평면(z=5).

    정점 4개·삼각형 2개짜리 큰 평면이 기본인 이유: "큰 평면이 메쉬 정점 몇 개로만
    표현된다"는 IFC 특성(ifc_reference_model 모듈 docstring 의 알려진 한계)을
    그대로 재현해, 정점 래스터화로는 구멍투성이가 되는 실무 조건을 픽스처로 쓴다.
    """
    f = ifcopenshell.api.project.create_file(version="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Test Project")
    length_unit = ifcopenshell.api.unit.add_si_unit(
        f, unit_type="LENGTHUNIT", prefix=length_prefix
    )
    ifcopenshell.api.unit.assign_unit(f, units=[length_unit])
    model_context = ifcopenshell.api.context.add_context(f, context_type="Model")
    body_context = ifcopenshell.api.context.add_context(
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_context,
    )
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")

    if georeference is not None:
        ifcopenshell.api.georeference.add_georeferencing(f)
        # EPSG:5186은 m 단위다. mm 프로젝트의 Scale=0.001이 project→map 단위
        # 변환이라는 계약을 픽스처 자체에도 명시한다.
        map_unit = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT")
        ifcopenshell.api.georeference.edit_georeferencing(
            f,
            projected_crs={"Name": crs_name, "MapUnit": map_unit},
            coordinate_operation={
                "Eastings": georeference["eastings"],
                "Northings": georeference["northings"],
                "OrthogonalHeight": georeference["orthogonal_height"],
                "XAxisAbscissa": 1.0,
                "XAxisOrdinate": 0.0,
                "Scale": 0.001 if length_prefix == "MILLI" else 1.0,
            },
        )

    element = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuildingElementProxy", name="Pad"
    )
    verts = vertices or [
        [0.0, 0.0, 5.0],
        [10.0, 0.0, 5.0],
        [10.0, 10.0, 5.0],
        [0.0, 10.0, 5.0],
    ]
    tri = faces or [[[0, 1, 2], [0, 2, 3]]]
    rep = ifcopenshell.api.geometry.add_mesh_representation(
        f, body_context, vertices=[verts], faces=tri
    )
    ifcopenshell.api.geometry.assign_representation(f, element, rep)

    path = tmp_path / f"{name}.ifc"
    f.write(str(path))
    return path


# ── 골든값 (손계산) ───────────────────────────────────────────────────────────


def test_converts_plane_to_hand_computed_geotiff(tmp_path: Path) -> None:
    """[핵심] Eastings=1000·Northings=2000·OrthogonalHeight=30, 로컬 z=5 평면
    → 세계좌표 [1000,1010]×[2000,2010], 계획고 35.0m. 셀 1.0m 면 원점 스냅으로
    west=1000·north=2010, 10×10 격자 전 셀이 정확히 35.0 이어야 한다."""
    ifc = _build_ifc(
        tmp_path,
        name="plane",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 30.0},
    )
    out = tmp_path / "plane.tif"
    summary = convert(ifc, out, cell_size=1.0)

    assert summary.crs == "EPSG:5186"
    assert (summary.rows, summary.cols) == (10, 10)
    assert summary.finite_cells == 100
    assert summary.z_min_m == pytest.approx(35.0)
    assert summary.z_max_m == pytest.approx(35.0)

    with rasterio.open(out) as ds:
        assert str(ds.crs) == "EPSG:5186"
        assert ds.transform.c == pytest.approx(1000.0)  # west
        assert ds.transform.f == pytest.approx(2010.0)  # north
        assert ds.transform.a == pytest.approx(1.0)
        assert ds.transform.e == pytest.approx(-1.0)
        band = ds.read(1)
    assert band.shape == (10, 10)
    assert np.isfinite(band).all()
    np.testing.assert_allclose(band, 35.0)


def test_millimetre_georeference_converts_to_same_design_surface(tmp_path: Path) -> None:
    """IFC→GeoTIFF 실제 소비자 회귀 — mm 파일도 같은 10m 평면·35m 계획고다.

    점 추출 함수 단독 테스트만 있으면 그 값이 래스터화 과정에서 다시 축소돼도 놓친다.
    bounds, 격자 크기, 높이를 함께 고정해 1000배 수평/수직 오류를 모두 잡는다.
    """
    ifc = _build_ifc(
        tmp_path,
        name="plane_mm",
        length_prefix="MILLI",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 30.0},
    )
    out = tmp_path / "plane_mm.tif"
    summary = convert(ifc, out, cell_size=1.0)

    assert (summary.rows, summary.cols) == (10, 10)
    assert summary.finite_cells == 100
    assert summary.z_min_m == pytest.approx(35.0)
    assert summary.z_max_m == pytest.approx(35.0)
    with rasterio.open(out) as ds:
        assert ds.bounds.left == pytest.approx(1000.0)
        assert ds.bounds.right == pytest.approx(1010.0)
        assert ds.bounds.bottom == pytest.approx(2000.0)
        assert ds.bounds.top == pytest.approx(2010.0)
        np.testing.assert_allclose(ds.read(1), 35.0)


def test_uncovered_cells_stay_nan_not_interpolated(tmp_path: Path) -> None:
    """[핵심] 설계 표면이 덮지 않는 셀은 NaN 으로 남는다 — 보간으로 메우지 않는다.

    반쪽 평면(삼각형 1개, 빗변 x+y=10)이면 10×10 격자에서 중심이 삼각형 안(경계
    포함)인 셀은 손계산으로 정확히 55개다: 셀 (i,j) 중심의 로컬합 = (j+0.5) +
    (9.5-i) 이 10 이하 ⇔ j ≤ i, 개수 = 1+2+…+10 = 55."""
    ifc = _build_ifc(
        tmp_path,
        name="half",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 30.0},
        vertices=[[0.0, 0.0, 5.0], [10.0, 0.0, 5.0], [0.0, 10.0, 5.0]],
        faces=[[[0, 1, 2]]],
    )
    out = tmp_path / "half.tif"
    summary = convert(ifc, out, cell_size=1.0)
    assert summary.finite_cells == 55

    with rasterio.open(out) as ds:
        band = ds.read(1)
    finite = np.isfinite(band)
    assert int(finite.sum()) == 55
    assert int((~finite).sum()) == 45
    np.testing.assert_allclose(band[finite], 35.0)
    # 하삼각(j<=i)만 채워졌다 — 보간이 있었다면 상삼각에도 값이 생겼을 것이다.
    rows_idx, cols_idx = np.where(finite)
    assert (cols_idx <= rows_idx).all()


# ── typed 거부 ────────────────────────────────────────────────────────────────


def test_rejects_ifc_without_georeferencing(tmp_path: Path) -> None:
    """georeferencing 없는 IFC 는 거부다 — 로컬 좌표를 조용히 세계좌표처럼 싣지
    않는다(ifc_reference_model 모듈 docstring 의 규율)."""
    ifc = _build_ifc(tmp_path, name="no_georef", georeference=None)
    with pytest.raises(IfcDesignSurfaceConversionError, match="georeferencing"):
        convert(ifc, tmp_path / "no_georef.tif")


def test_rejects_ifc2x3(tmp_path: Path) -> None:
    """IFC2X3 는 typed 거부다(별도 pset 메커니즘 — has_georeferencing 이 거부)."""
    f = ifcopenshell.api.project.create_file(version="IFC2X3")
    path = tmp_path / "legacy.ifc"
    f.write(str(path))
    with pytest.raises(IfcReferenceModelError, match="IFC2X3"):
        convert(path, tmp_path / "legacy.tif")


def test_requires_crs_flag_when_epsg_unreadable(tmp_path: Path) -> None:
    """IfcProjectedCRS 이름이 'EPSG:숫자' 가 아니면 --crs 없이는 거부하고,
    --crs 를 주면 그 값이 태깅된다 — CRS 를 지어내지 않는다."""
    ifc = _build_ifc(
        tmp_path,
        name="freetext_crs",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 0.0},
        crs_name="Korea2000-CentralBelt",
    )
    with pytest.raises(IfcDesignSurfaceConversionError, match="--crs"):
        convert(ifc, tmp_path / "freetext.tif")

    summary = convert(ifc, tmp_path / "freetext.tif", crs_override="EPSG:5186")
    assert summary.crs == "EPSG:5186"


def test_rejects_conflicting_crs_override(tmp_path: Path) -> None:
    """파일의 EPSG 와 --crs 가 다르면 거부 — 어느 쪽이 맞는지 도구가 판정하지 않는다."""
    ifc = _build_ifc(
        tmp_path,
        name="conflict",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 0.0},
    )
    with pytest.raises(IfcDesignSurfaceConversionError, match="다르다"):
        convert(ifc, tmp_path / "conflict.tif", crs_override="EPSG:32652")


# ── 결정성 ────────────────────────────────────────────────────────────────────


def test_same_input_twice_yields_identical_bytes(tmp_path: Path) -> None:
    """[핵심] 같은 입력 2회 → 같은 바이트. 등록 경로의 digest 대조(선언 sha256 vs
    Core 재해싱)가 재현 가능한 사실이 되는 전제다(diff_raster 의 결정성 규율)."""
    ifc = _build_ifc(
        tmp_path,
        name="det",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 30.0},
    )
    out1 = tmp_path / "det1.tif"
    out2 = tmp_path / "det2.tif"
    convert(ifc, out1, cell_size=1.0)
    convert(ifc, out2, cell_size=1.0)
    assert out1.read_bytes() == out2.read_bytes()


# ── 설계면 등록 경로 접속 가능성 ──────────────────────────────────────────────


def test_output_passes_design_surface_measurement(tmp_path: Path) -> None:
    """[통합] 산출물이 설계면 검증 워커의 실측을 실제로 통과한다 — CRS 가 읽히고,
    1밴드·NaN nodata·유한셀 수가 기대와 일치한다. 이 측정치가 Core 대조를 통과하는
    형태(수평 EPSG 관측, nodataIsNan=true, finiteCellCount>0)임을 고정한다."""
    ifc = _build_ifc(
        tmp_path,
        name="measurable",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 30.0},
    )
    out = tmp_path / "measurable.tif"
    convert(ifc, out, cell_size=1.0)

    measurement = measure_design_surface(out)
    assert measurement.crs == "EPSG:5186"
    assert measurement.band_count == 1
    assert measurement.dtype == "float32"
    assert measurement.nodata is None
    assert measurement.nodata_is_nan is True
    assert measurement.finite_cell_count == 100
    assert measurement.pixel_size_x_m == pytest.approx(1.0)
    assert measurement.pixel_size_y_m == pytest.approx(1.0)
    assert measurement.bounds_min_x == pytest.approx(1000.0)
    assert measurement.bounds_max_y == pytest.approx(2010.0)


# ── 정점 vs 면 래스터화 — 결정 근거를 회귀로 고정 ─────────────────────────────


def test_face_rasterization_decision_evidence(tmp_path: Path) -> None:
    """[결정 근거, 2026-08-12 실측] 10m×10m 평면(정점 4개·삼각형 2개)을 0.5m 셀로:

    - 정점만 찍기: 400셀 중 **4셀(1%)** — 큰 평면이 정점 몇 개로만 표현되는 IFC
      특성 때문에 실무 IFC 에서는 구멍이 지배한다.
    - 삼각형 면 굽기: **400셀(100%)** — ifcopenshell.geom 이 face 인덱스를 실제로
      제공하므로 가능하다.

    이 수치가 면 래스터화를 기본으로 택한 근거다(도구 모듈 docstring)."""
    ifc = _build_ifc(
        tmp_path,
        name="evidence",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 0.0},
    )
    mesh = sample_mesh_from_ifc(ifc)
    assert mesh.vertices.shape == (4, 3)
    assert mesh.faces.shape == (2, 3)

    cell = 0.5
    west, north, rows, cols = _grid_definition(mesh.vertices, cell)
    assert (rows, cols) == (20, 20)

    vertex_only = np.full((rows, cols), -np.inf)
    _splat_vertices(vertex_only, mesh.vertices, west, north, cell)
    faces_baked = np.full((rows, cols), -np.inf)
    _bake_faces(faces_baked, mesh, west, north, cell)

    assert int(np.isfinite(vertex_only).sum()) == 4  # 400셀 중 4셀 — 구멍 99%
    assert int(np.isfinite(faces_baked).sum()) == 400  # 전 셀
