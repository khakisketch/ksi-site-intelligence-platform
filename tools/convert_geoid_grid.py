#!/usr/bin/env python3
"""KNGeoid 텍스트 격자 → GeoTIFF 변환 (risk `geoid-grid-provenance-unverified`).

국토지리정보원(NGII)이 배포하는 KNGeoid 모델은 rasterio 가 직접 열 수 없는 텍스트
포맷으로 온다. 이번에 확보한 KNGeoid24 패키지는 실제로 **두 가지 텍스트 포맷**을
함께 담고 있었다(둘 다 이 스크립트가 지원한다):

- ``gri`` — GRAVSOFT 계열 격자 포맷. 첫 줄이 ``lat_min lat_max lon_min lon_max dlat
  dlon`` 6개 숫자 헤더, 그 뒤로 위도 내림차순(북→​남) × 경도 오름차순(서→동) 순서의
  격자값이 공백/개행 구분으로 이어진다. 결측은 관례값 9999.000.
- ``dat`` — ``lat lon N`` 3열 텍스트. 각 행이 이미 격자 한 칸의 **중심점**이고,
  전체가 완전한 직사각형 격자를 이룬다(결측 없음).

**실측 확인(2026-08-12): 두 포맷은 겹치는 좌표에서 동일한 N 값을 준다** — 이번에
받은 파일에서 무작위 15개 좌표를 대조해 전부 오차 0.0 이었다. 즉 ``gri`` 는 같은
지오이드고 값을 더 넓은(위경도 정수 경계) 사각형에 담고 남는 자리를 9999 로 채운
것이고, ``dat`` 는 그 유효 범위만 뽑아 나열한 것이다 — 둘 중 하나가 보정 전
원시값이고 다른 하나가 보정 후 최종값인 관계가 아니다(참고 저장소
``references/repos/ksi-terra/docs/GEOID_ACQUISITION.md`` 가 KNGeoid18 에서는 이런
넓은 포맷 파일을 "보정 전 원시 격자로 추정"이라 적어 두었는데, 이번 KNGeoid24 실측
대조로 그 추정이 이번 파일에는 적용되지 않음을 직접 확인했다 — 값이 정확히
같으므로 자매 파일이지 다른 보정 단계가 아니다).

이 스크립트는 두 포맷 모두 변환 가능하지만, 기본 산출물은 ``dat``(3열) 쪽을 쓴다
— nodata 패딩이 없어 변환기 자체의 실수 여지가 적고(9999 를 실수로 유효값처럼
보간하는 사고를 원천적으로 배제), 국내 유효 범위만 정확히 담는다. ``gri`` 변환은
교차검증용으로 남겨 둔다(``--format gri``).

격자 정의·픽셀 중심 규약(중요 — ``ksi_geo_spatial.vertical.GeoidGrid.height_at`` 과
반드시 일치해야 함): 입력의 각 (lat, lon) 은 이미 셀 **중심점**이다. rasterio/GDAL
의 affine transform 은 픽셀 **좌상단 모서리** 기준이므로, GeoTIFF 원점(west, north)
은 입력의 최소경도·최대위도보다 반 셀씩 바깥으로 밀려나야 한다:

    west  = lon_min - dlon / 2
    north = lat_max + dlat / 2

이러면 픽셀(0,0)의 중심이 정확히 (lon_min, lat_max) 와 일치하고, ``GeoidGrid``가
조회 시 되짚는 -0.5 오프셋과 대칭이 맞는다.

nodata(9999.000 관례값) 칸은 GeoTIFF 밴드에 **NaN**으로 쓴다(리터럴 9999.0 을 그대로
쓰면 ``GeoidGrid.height_at`` 의 finite 검사를 우연히 통과해 경계 부근에서 9999 를
섞은 보간값을 조용히 돌려줄 위험이 있다 — vertical.py 모듈독스트링의 "N=0 대치
금지"와 같은 종류의 사고를 nodata 경계에서 일으킬 수 있다).

사용법::

    uv run python tools/convert_geoid_grid.py \\
        --input data/geoid/raw/KNGeoid24.dat --format dat \\
        --output data/geoid/KNGeoid24.tif --verify-samples 20
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

_NODATA_CONVENTION = 9999.0
_SPACING_TOLERANCE_FRACTION = 0.05  # 격자 간격 균일성 검사 허용오차(간격 대비 5%)


class GeoidGridFormatError(ValueError):
    """입력 텍스트가 기대한 격자 포맷 불변식을 만족하지 않는다."""


def _detect_format(path: Path) -> str:
    with path.open("r", encoding="ascii", errors="strict") as f:
        first_line = f.readline().split()
    if len(first_line) == 6:
        return "gri"
    if len(first_line) == 3:
        return "dat"
    raise GeoidGridFormatError(
        f"{path} 의 첫 줄 토큰 수({len(first_line)})가 gri(6)·dat(3) 어느 쪽과도 "
        "맞지 않는다 — 포맷을 --format 으로 명시하라"
    )


def parse_gri(path: Path, *, nodata: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """GRAVSOFT ``.gri`` 헤더+격자값 텍스트를 파싱한다.

    반환: (lat_axis 내림차순, lon_axis 오름차순, values[row, col]) — nodata 는 NaN.
    """
    tokens = path.read_text(encoding="ascii", errors="strict").split()
    if len(tokens) < 6:
        raise GeoidGridFormatError(f"{path}: 헤더 6개 숫자조차 없다")
    lat_min, lat_max, lon_min, lon_max, dlat, dlon = (float(x) for x in tokens[:6])

    rows = round((lat_max - lat_min) / dlat) + 1
    cols = round((lon_max - lon_min) / dlon) + 1
    body = tokens[6:]
    if len(body) != rows * cols:
        raise GeoidGridFormatError(
            f"{path}: 격자값 개수 {len(body)} 개가 rows({rows})×cols({cols})="
            f"{rows * cols} 와 맞지 않는다 — 헤더 오독이거나 파일이 잘렸다"
        )

    values = np.array([float(v) for v in body], dtype=np.float64).reshape(rows, cols)
    values[values == nodata] = np.nan

    lat_axis = lat_max - np.arange(rows) * dlat  # 내림차순(북→남), GRAVSOFT 관례
    lon_axis = lon_min + np.arange(cols) * dlon  # 오름차순(서→동)
    return lat_axis, lon_axis, values


def parse_dat_columns(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``lat lon N`` 3열 텍스트를 파싱해 완전 직사각형 격자로 재구성한다.

    입력 파일의 실제 정렬 순서에 의존하지 않는다 — 모든 점을 읽어 고유
    위도(내림차순)·경도(오름차순) 축을 직접 구성한 뒤 인덱스에 채운다.
    """
    lats: list[float] = []
    lons: list[float] = []
    vals: list[float] = []
    with path.open("r", encoding="ascii", errors="strict") as f:
        for lineno, line in enumerate(f, start=1):
            parts = line.split()
            if not parts:
                continue
            if len(parts) != 3:
                raise GeoidGridFormatError(f"{path}:{lineno}: 3열이 아니다 — {line!r}")
            lat, lon, n = (float(x) for x in parts)
            lats.append(lat)
            lons.append(lon)
            vals.append(n)

    lat_arr = np.array(lats)
    lon_arr = np.array(lons)
    val_arr = np.array(vals)

    lat_axis = np.unique(lat_arr)[::-1]  # 내림차순
    lon_axis = np.unique(lon_arr)  # 오름차순
    rows, cols = len(lat_axis), len(lon_axis)

    if rows * cols != len(val_arr):
        raise GeoidGridFormatError(
            f"{path}: 점 {len(val_arr)}개가 완전 직사각형이 아니다 "
            f"(고유 위도{rows} x 고유 경도{cols}={rows * cols}) — 결측/중복 좌표 의심"
        )

    _assert_uniform_spacing(lat_axis, path, "위도")
    _assert_uniform_spacing(lon_axis, path, "경도")

    values = np.full((rows, cols), np.nan, dtype=np.float64)
    # 위도 내림차순 인덱스, 경도 오름차순 인덱스로 역매핑.
    row_idx = (rows - 1) - np.searchsorted(lat_axis[::-1], lat_arr)
    col_idx = np.searchsorted(lon_axis, lon_arr)
    values[row_idx, col_idx] = val_arr

    if np.isnan(values).any():
        raise GeoidGridFormatError(
            f"{path}: 축 재구성 후에도 빈 칸이 남았다 — 좌표 중복/충돌 의심"
        )

    return lat_axis, lon_axis, values


def _assert_uniform_spacing(axis: np.ndarray, path: Path, label: str) -> float:
    diffs = np.abs(np.diff(axis))
    spacing = float(np.median(diffs))
    tol = spacing * _SPACING_TOLERANCE_FRACTION
    bad = np.where(np.abs(diffs - spacing) > tol)[0]
    if len(bad):
        raise GeoidGridFormatError(
            f"{path}: {label} 축 간격이 불균일하다(중앙값 {spacing:.6f}, "
            f"이상 지점 {len(bad)}개, 예: idx={bad[0]} diff={diffs[bad[0]]:.6f})"
        )
    return spacing


def write_geotiff(
    lat_axis: np.ndarray, lon_axis: np.ndarray, values: np.ndarray, output_path: Path
) -> None:
    """픽셀 중심 = (lat_axis[row], lon_axis[col]) 이 되도록 GeoTIFF 를 쓴다."""
    rows, cols = values.shape
    dlat = float(abs(lat_axis[0] - lat_axis[1])) if rows > 1 else 0.0
    dlon = float(abs(lon_axis[1] - lon_axis[0])) if cols > 1 else 0.0

    lat_max = float(lat_axis[0])
    lon_min = float(lon_axis[0])
    west = lon_min - dlon / 2.0
    north = lat_max + dlat / 2.0
    transform = from_origin(west, north, dlon, dlat)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=transform,
        nodata=float("nan"),
    ) as dataset:
        dataset.write(values, 1)


def verify_against_source(
    output_path: Path, lat_arr: np.ndarray, lon_arr: np.ndarray, val_arr: np.ndarray, n: int
) -> float:
    """변환된 GeoTIFF 를 실제 ``GeoidGrid`` 로 열어 원본 표본과 대조, 최대오차(m) 반환."""
    # 지연 import — 이 스크립트가 패키지 미설치 환경에서도 파싱/변환 단계까지는
    # 동작해야 한다(검증만 선택적으로 건너뛸 수 있게).
    _pkg_src = Path(__file__).resolve().parents[1] / "packages" / "geo-spatial" / "src"
    sys.path.insert(0, str(_pkg_src))
    from ksi_geo_spatial.vertical import GeoidGrid  # noqa: PLC0415

    grid = GeoidGrid.from_path(output_path)
    rng = random.Random(42)
    idxs = rng.sample(range(len(val_arr)), k=min(n, len(val_arr)))

    max_err = 0.0
    for i in idxs:
        lat, lon, expected = float(lat_arr[i]), float(lon_arr[i]), float(val_arr[i])
        got = grid.height_at(lat_deg=lat, lon_deg=lon)
        err = abs(got - expected)
        max_err = max(max_err, err)
        print(
            f"    검증: lat={lat:.5f} lon={lon:.5f} 원본={expected:.4f} "
            f"변환후보간={got:.4f} 오차={err:.2e}"
        )
    return max_err


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, required=True, help="원본 텍스트 격자 경로")
    parser.add_argument(
        "--format",
        choices=["auto", "gri", "dat"],
        default="auto",
        help="입력 포맷(기본 auto — 첫 줄 토큰 수로 판별)",
    )
    parser.add_argument("--output", type=Path, required=True, help="산출 GeoTIFF 경로")
    parser.add_argument(
        "--nodata", type=float, default=_NODATA_CONVENTION, help="gri 포맷의 결측 관례값"
    )
    parser.add_argument(
        "--verify-samples", type=int, default=0, help="변환 후 무작위 대조 표본 수(0=건너뜀)"
    )
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"✗ 입력 파일이 없다: {args.input}", file=sys.stderr)
        return 1

    fmt = args.format if args.format != "auto" else _detect_format(args.input)
    print(f"[1/3] 포맷={fmt} 로 파싱: {args.input}")

    if fmt == "gri":
        lat_axis, lon_axis, values = parse_gri(args.input, nodata=args.nodata)
        rows, cols = values.shape
        valid = np.isfinite(values)
        print(f"      격자 {rows}x{cols}={rows * cols}개, 유효값 {int(valid.sum())}개 "
              f"({int(valid.sum()) / values.size:.1%}), nodata {int((~valid).sum())}개")
        lat_grid, lon_grid = np.meshgrid(lat_axis, lon_axis, indexing="ij")
        lat_arr = lat_grid[valid]
        lon_arr = lon_grid[valid]
        val_arr = values[valid]
    else:
        lat_axis, lon_axis, values = parse_dat_columns(args.input)
        rows, cols = values.shape
        print(f"      격자 {rows}x{cols}={rows * cols}개(완전 직사각형, 결측 없음)")
        lat_grid, lon_grid = np.meshgrid(lat_axis, lon_axis, indexing="ij")
        lat_arr = lat_grid.ravel()
        lon_arr = lon_grid.ravel()
        val_arr = values.ravel()

    print(f"      위도범위(유효) {lat_axis[-1] if fmt == 'dat' else lat_arr.min():.5f}~"
          f"{lat_axis[0] if fmt == 'dat' else lat_arr.max():.5f}, "
          f"경도범위 {lon_arr.min():.5f}~{lon_arr.max():.5f}, "
          f"N범위 {np.nanmin(val_arr):.3f}~{np.nanmax(val_arr):.3f}")

    print(f"[2/3] GeoTIFF 기록: {args.output} (EPSG:4326, 단일밴드 float64, nodata=NaN)")
    write_geotiff(lat_axis, lon_axis, values, args.output)

    if args.verify_samples > 0:
        print(
            f"[3/3] 원본 대조 검증 ({args.verify_samples}개 무작위 표본, 격자 노드 위치이므로 "
            "이중선형 보간이 정확히 수렴해야 함)"
        )
        max_err = verify_against_source(
            args.output, lat_arr, lon_arr, val_arr, args.verify_samples
        )
        print(f"      최대오차: {max_err:.2e} m")
        if max_err > 1e-6:
            print(
                "✗ 최대오차가 1e-6m 를 넘는다 — 변환 규약(픽셀 중심 오프셋 등) 재확인 필요",
                file=sys.stderr,
            )
            return 1
    else:
        print("[3/3] 검증 건너뜀(--verify-samples 미지정)")

    print("✓ 변환 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
