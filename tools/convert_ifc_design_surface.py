#!/usr/bin/env python3
"""IFC 설계모델 → 설계 기준면 GeoTIFF 변환 (M4-A 설계면 등록 경로 접속).

## 왜 변환 도구인가 — 계약 확장이 아니라

설계면 계약(``contracts/schemas/design-surface.v1.json``)은 ``format: geotiff``
하나다. 검증(``design_surface_verifier``)·잔량 계산(``run_design_conformance``)·
차분(``diff_raster``)이 전부 래스터 전제라, IFC 를 네이티브로 받으려면 그 전부를
이원화해야 한다(M4-B — 실데이터가 GeoTIFF 로 충분하면 우선순위가 내려간다,
``docs/goals/REMAINING_WORK_PLAN.md`` §4). 대신 이 도구가 IFC 를 설계면 GeoTIFF
로 변환해 **기존 등록 경로(업로드 → 선언 vs 관측 대조 → 잔량)에 그대로 태운다**
— digest 대조·Core 재해싱·CRS 검증을 공짜로 상속한다. 전례:
``tools/convert_geoid_grid.py`` (외부 포맷 → 파이프라인이 읽는 GeoTIFF).

## 상단 표면(top surface) 의미론 — 셀값 = 그 셀에 떨어진 표면 표본의 최대 z

설계 지형면은 위에서 본 표면이다 — 재구성 파이프라인의 DSM(digital *surface*
model)과 같은 의미론이어야 잔량 차분(설계 − 현재)이 같은 것을 빼는 것이 된다.
그래서 셀마다 그 셀에 떨어지는 표면 표본(삼각형 위 보간점·정점)의 **최대 z** 를
계획고로 쓴다. 한계: 교량 하부·터널처럼 한 (x,y)에 면이 위아래로 겹치는 설계는
위쪽 면만 남는다 — 그런 구조물은 지형면 잔량 계산의 대상이 아니므로 의도된
동작이지만, 파일에 섞여 있으면 하부 형상이 계획고에서 사라진다는 것은 알고
써야 한다.

## 면 래스터화를 기본으로 한다 — 실측 근거

IFC 의 큰 평면은 정점 몇 개로만 표현된다(``ksi_bim_integration.ifc_reference_model``
모듈 docstring "알려진 한계"). 정점만 찍으면: 10m×10m 평면(정점 4개·삼각형 2개)을
0.5m 셀로 래스터화할 때 400셀 중 **4셀(1%)** 만 값이 생기고 나머지는 전부
구멍이다(2026-08-12 실측, ``test_convert_ifc_design_surface.py`` 가 이 수치를
회귀로 고정). ``ifcopenshell.geom`` 이 triangulation face 인덱스를 실제로 준다는
것을 확인했으므로(같은 날 실측: 정점 4개 평면에서 ``faces=[2,0,1,2,3,0]``),
삼각형 면을 셀 중심에 무게중심(barycentric) 보간으로 직접 구워 **같은 평면이
400/400셀(100%)** 이 되는 면 래스터화를 쓴다. 정점도 함께 찍는다 — XY 투영에서
퇴화한 삼각형(수직 벽)이나 셀 중심을 하나도 덮지 않는 가는 조각의 표본을
버리지 않기 위해서다(둘 다 "그 셀의 표면 표본"이므로 max 의미론과 일관된다).

## 점이 없는 셀은 NaN — 보간으로 메우지 않는다

값이 없는 자리는 "모른다"지 "0"도 "이웃과 비슷하다"도 아니다(``diff_raster``
의 "무효 셀은 NaN" 규율과 동일). 설계면의 구멍을 보간으로 메우면 설계에 없는
계획고를 도구가 지어내는 것이고, 잔량 숫자에 그대로 들어간다. 면 래스터화
덕분에 실제 설계 표면이 덮는 셀은 채워지므로, 남는 NaN 은 "설계 범위 밖"이라는
정직한 사실이다. 잔량 계산은 NaN 셀을 "모름"으로 집계에서 제외한다.

## 결정성 — 같은 입력은 같은 바이트

산출물 digest 가 재현 가능한 사실이어야 등록 경로의 해시 대조가 의미를 갖는다.
프로파일을 고정하고(``diff_raster.DIFF_RASTER_PROFILE`` 전례 — 이 환경의 GTiff
드라이버는 시각·버전 태그를 쓰지 않음을 그쪽 실측이 확인), 격자 원점을 셀 크기의
배수로 스냅해 입력에서만 유도되게 한다. max 축적은 순서 무관 연산이라 요소 순회
순서가 결과를 바꾸지 않는다. 같은 입력 2회 → 같은 sha256 을 계약 테스트가
강제한다.

## 수직기준은 이 도구가 알 수 없다

IFC 도 GeoTIFF 도 높이가 타원체고인지 해발(정표고)인지 신뢰성 있게 담지 않는다
(이 저장소의 확립된 사실 — design-surface.v1 의 verticalReference 가 declared
에만 있는 이유). 이 도구는 높이값을 **그대로 옮길 뿐**이고, 등록 화면에서
사용자가 기준을 선언한다 — 해발이면 잔량 계산이 지오이드 격자(KNGeoid24)로
자동 정합한다. 변환이 끝나면 이 안내를 출력한다.

사용법::

    uv run python tools/convert_ifc_design_surface.py \\
        --input design.ifc --output design_surface.tif --cell-size 0.5

CRS 는 IFC 의 georeferencing(IfcProjectedCRS 의 ``EPSG:xxxx`` 이름)에서 읽고,
못 읽으면 ``--crs EPSG:xxxx`` 를 요구한다. georeferencing 자체가 없거나 IFC2X3
면 거부한다 — 조용히 로컬 좌표로 진행하지 않는다.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import ifcopenshell
import numpy as np
import rasterio
from ksi_bim_integration.ifc_reference_model import (
    IfcReferenceModelError,
    IfcSurfaceMesh,
    has_georeferencing,
    read_georeference,
    sample_mesh_from_ifc,
)
from ksi_geo_spatial.tin_surface import (
    DEFAULT_CELL_SIZE_M,
    TinSurface,
    TinSurfaceError,
)
from ksi_geo_spatial.tin_surface import (
    DESIGN_SURFACE_RASTER_PROFILE as DESIGN_SURFACE_PROFILE,
)
from ksi_geo_spatial.tin_surface import (
    _bake_faces as _shared_bake_faces,
)
from ksi_geo_spatial.tin_surface import (
    _grid_definition as _shared_grid_definition,
)
from ksi_geo_spatial.tin_surface import (
    _splat_vertices as _shared_splat_vertices,
)
from ksi_geo_spatial.tin_surface import (
    rasterize_top_surface as _rasterize_tin_surface,
)
from numpy.typing import NDArray

#: 기본 셀 크기(m). 근거: 잔량 계산(``run_design_conformance``)은 설계면을 현재
#: DSM 격자로 bilinear 재표본하므로(``align_and_diff`` 는 baseline=현재 DSM 격자를
#: 기준으로 삼는다) 설계면이 드론 DSM 의 cm 급 해상도를 가질 필요가 없다 — 계획면은
#: 구간별 평면이라 재표본 오차는 경사 변화선 부근에만 생기고, 0.5m 는 토공 관리
#: 단위보다 충분히 촘촘하다. 파일 크기로도 1km² 현장이 4×10⁶ 셀(float32 deflate)로
#: 부담이 없다. 경사 변화가 조밀한 설계는 ``--cell-size`` 로 줄인다.
# ``DEFAULT_CELL_SIZE_M`` 와 GeoTIFF profile 은 LandXML 경로와 반드시 같아야
# 한다. 정본은 ``ksi_geo_spatial.tin_surface`` 이며 여기서는 CLI 호환 이름만
# 재수출한다.

_EPSG_PATTERN: Final = re.compile(r"EPSG:(\d{1,6})", flags=re.IGNORECASE)


class IfcDesignSurfaceConversionError(ValueError):
    """입력 IFC 가 설계면 변환의 전제(georeferencing·CRS·격자 한도)를 만족하지 않는다."""


@dataclass(frozen=True, slots=True)
class ConversionSummary:
    """변환 1회의 실측 요약 — main() 이 출력하는 값 전부가 여기서 나온다."""

    crs: str
    rows: int
    cols: int
    cell_size_m: float
    finite_cells: int
    vertex_count: int
    triangle_count: int
    z_min_m: float
    z_max_m: float


def resolve_epsg_crs(
    ifc_file: ifcopenshell.file, ifc_path: Path, crs_override: str | None
) -> str:
    """산출 GeoTIFF 에 태깅할 CRS 를 정한다 — 지어내지 않는다.

    georeferencing 이 없으면 여기서 거부한다(로컬 좌표를 조용히 세계좌표처럼
    쓰지 않는다 — ``ifc_reference_model`` 모듈 docstring 의 규율). IFC2X3 는
    :func:`has_georeferencing` 이 typed 로 거부한다.

    파일의 EPSG(IfcProjectedCRS 이름)와 ``--crs`` 가 둘 다 있고 서로 다르면
    거부한다 — 한쪽을 조용히 이기게 하면 사용자가 어느 좌표계가 실렸는지 모른다.
    """
    if not has_georeferencing(ifc_file):
        raise IfcDesignSurfaceConversionError(
            f"{ifc_path}: georeferencing(IfcCoordinateOperation)이 없다 — 로컬 좌표를 "
            "세계좌표처럼 실을 수 없다. 설계 소프트웨어에서 좌표 기준(georeferencing)을 "
            "넣어 다시 내보내라"
        )
    file_epsg: str | None = None
    try:
        georef = read_georeference(ifc_file)
    except IfcReferenceModelError:
        # IfcRigidOperation 계열 — 좌표 변환 자체는 정확하지만(auto_local2global 이
        # 처리) CRS 파라미터를 "읽는" 것은 지원되지 않는다. --crs 로 받는다.
        georef = None
    if georef is not None:
        matched = _EPSG_PATTERN.fullmatch(georef.projected_crs_name.strip())
        if matched:
            file_epsg = f"EPSG:{int(matched.group(1))}"
    override: str | None = None
    if crs_override is not None:
        matched = _EPSG_PATTERN.fullmatch(crs_override.strip())
        if matched is None:
            raise IfcDesignSurfaceConversionError(
                f"--crs 는 'EPSG:숫자' 형태여야 한다 (got {crs_override!r})"
            )
        override = f"EPSG:{int(matched.group(1))}"
    if file_epsg is not None and override is not None and file_epsg != override:
        raise IfcDesignSurfaceConversionError(
            f"{ifc_path}: 파일의 CRS({file_epsg})와 --crs({override})가 다르다 — "
            "어느 쪽이 맞는지 이 도구가 판정하지 않는다. 파일을 고치거나 --crs 를 빼라"
        )
    crs = file_epsg or override
    if crs is None:
        raise IfcDesignSurfaceConversionError(
            f"{ifc_path}: IFC 에서 EPSG 코드를 읽을 수 없다"
            f"(IfcProjectedCRS 이름: {georef.projected_crs_name!r} — 'EPSG:숫자' 형태가"
            " 아니다) — --crs EPSG:xxxx 로 명시하라"
            if georef is not None
            else f"{ifc_path}: 이 georeferencing 종류에서는 CRS 파라미터를 읽을 수 없다 "
            "— --crs EPSG:xxxx 로 명시하라"
        )
    return crs


# Backward-compatible test seams.  The implementation is owned by the shared
# normaliser; keeping these thin aliases lets the established IFC evidence
# continue to prove the same sampling semantics after the extraction.
def _grid_definition(
    vertices: NDArray[np.float64], cell_size: float
) -> tuple[float, float, int, int]:
    return _shared_grid_definition(vertices, cell_size)


def _splat_vertices(
    acc: NDArray[np.float64],
    vertices: NDArray[np.float64],
    west: float,
    north: float,
    cell_size: float,
) -> None:
    _shared_splat_vertices(acc, vertices, west, north, cell_size)


def _bake_faces(
    acc: NDArray[np.float64],
    mesh: IfcSurfaceMesh,
    west: float,
    north: float,
    cell_size: float,
) -> None:
    _shared_bake_faces(
        acc,
        TinSurface(vertices=mesh.vertices, faces=mesh.faces),
        west,
        north,
        cell_size,
    )


def rasterize_top_surface(
    mesh: IfcSurfaceMesh, cell_size: float
) -> tuple[NDArray[np.float32], Any]:
    """IFC 메쉬를 공용 deterministic TIN 규칙으로 정규화한다."""
    try:
        return _rasterize_tin_surface(
            TinSurface(vertices=mesh.vertices, faces=mesh.faces), cell_size_m=cell_size
        )
    except TinSurfaceError as exc:
        raise IfcDesignSurfaceConversionError(str(exc)) from exc


def convert(
    input_path: Path,
    output_path: Path,
    *,
    cell_size: float = DEFAULT_CELL_SIZE_M,
    crs_override: str | None = None,
) -> ConversionSummary:
    """IFC 1건 → 설계면 GeoTIFF 1건. 거부는 전부 typed 예외다."""
    if not (math.isfinite(cell_size) and cell_size > 0):
        raise IfcDesignSurfaceConversionError(f"--cell-size 는 양수여야 한다 (got {cell_size!r})")
    try:
        ifc_file = ifcopenshell.open(str(input_path))
    except Exception as exc:  # noqa: BLE001 — ifcopenshell 이 다양한 파서 예외를 던진다
        raise IfcReferenceModelError(f"IFC 파일을 열 수 없다: {input_path} ({exc})") from exc
    crs = resolve_epsg_crs(ifc_file, input_path, crs_override)

    mesh = sample_mesh_from_ifc(input_path)
    values, transform = rasterize_top_surface(mesh, cell_size)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    height, width = values.shape
    with rasterio.open(
        output_path,
        "w",
        height=height,
        width=width,
        crs=crs,
        transform=transform,
        **DESIGN_SURFACE_PROFILE,
    ) as dataset:
        dataset.write(values, 1)

    finite = values[np.isfinite(values)]
    return ConversionSummary(
        crs=crs,
        rows=height,
        cols=width,
        cell_size_m=cell_size,
        finite_cells=int(finite.size),
        vertex_count=int(mesh.vertices.shape[0]),
        triangle_count=int(mesh.faces.shape[0]),
        z_min_m=float(finite.min()),
        z_max_m=float(finite.max()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, required=True, help="입력 IFC 경로(IFC4 이상)")
    parser.add_argument("--output", type=Path, required=True, help="산출 GeoTIFF 경로")
    parser.add_argument(
        "--cell-size",
        type=float,
        default=DEFAULT_CELL_SIZE_M,
        help=f"셀 크기(m, 기본 {DEFAULT_CELL_SIZE_M} — 모듈 docstring 의 근거 참조)",
    )
    parser.add_argument(
        "--crs",
        default=None,
        help="EPSG:xxxx — IFC 에서 EPSG 를 읽을 수 없을 때만 필요(파일 값과 다르면 거부)",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"✗ 입력 파일이 없다: {args.input}", file=sys.stderr)
        return 1
    try:
        summary = convert(
            args.input, args.output, cell_size=args.cell_size, crs_override=args.crs
        )
    except (IfcDesignSurfaceConversionError, IfcReferenceModelError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    total = summary.rows * summary.cols
    print(
        f"[1/2] 변환 완료: {args.output}\n"
        f"      CRS={summary.crs}, 격자 {summary.rows}x{summary.cols}"
        f"(셀 {summary.cell_size_m}m), 값 있는 셀 {summary.finite_cells}/{total}"
        f"({summary.finite_cells / total:.1%})\n"
        f"      입력 메쉬: 정점 {summary.vertex_count}개, 삼각형 {summary.triangle_count}개, "
        f"계획고 범위 {summary.z_min_m:.3f}~{summary.z_max_m:.3f}m"
    )
    print(
        "[2/2] 높이 기준(수직기준) 안내 — 이 파일로는 알 수 없어 값을 그대로 옮겼다.\n"
        "      등록 화면에서 이 도면의 높이가 타원체 기준인지 해발(표고)인지 근거와 함께\n"
        "      선언하라 — 해발이면 잔량 계산이 지오이드 격자(KNGeoid24)로 자동 정합한다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
