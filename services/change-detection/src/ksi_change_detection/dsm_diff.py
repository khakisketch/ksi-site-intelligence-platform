"""DSM 차분 기반 구역 체적 — 두 시점의 표면이 얼마나 움직였나 (ADR-KSI-016 D3).

## 왜 point cloud 가 아니라 DSM 인가

ADR-KSI-003 은 Point Cloud 를 원본 SSOT 로 두고 DSM 을 파생으로 둔다. 그런데
**체적은 2.5D 문제**다 — "이 구역의 지표면이 얼마나 올라갔나"는 표면 함수
z=f(x,y) 의 적분이고, 점군에서 그걸 구하려면 어차피 격자로 만들어야 한다.
파생물에서 원본 수준의 측정을 하지 않는다는 INV-051 의 금지선은 "정밀 측정을
파생물로 대체하지 마라"는 뜻이지, 2.5D 문제에 2.5D 표현을 쓰지 말라는 뜻이
아니다. 수직면·구조물처럼 표면 함수로 표현되지 않는 대상은 원본 계열에서
다뤄야 하며, 이 모듈은 그 경우를 다루지 않는다.

## 정직성 규칙 (INV-024)

여기서 나오는 값은 **상대 비교**다. 두 epoch 가 같은 파이프라인·같은 좌표계에서
나왔다는 전제 위에서 "얼마나 변했나"를 말하고, "실제로 몇 m³ 인가"의 절대
정확도는 주장하지 않는다. 오차한계(``uncertainty_m3``)는 **양쪽 epoch 모두**
독립 검사점으로 검증된 RMSE 를 가질 때만 계산하며, 하나라도 없으면 ``None``
이다 — ODM 경로에는 그 리포트가 없으므로(ADR-KSI-012 D3) 지금은 항상 None 이다.

## 부호 규약

``cut`` = 깎인 양(현재가 기준보다 낮음), ``fill`` = 쌓인 양. **둘 다 양수**이고
방향은 ``net = fill - cut`` 하나로만 말한다. 부호가 두 곳에 있으면 한쪽만
뒤집혀도 화면에서는 그럴듯하다. 같은 구역에서 깎고 쌓았으면 net 이 0 이어도
cut·fill 은 각각 남는다 — 토공 진척은 흙이 움직인 양이지 순증감이 아니다.

## fail-closed 지점

- 두 래스터의 CRS 가 다르면 거부한다(:class:`~ksi_geo_spatial.crs.CrsMismatchError`,
  INV-020) — 빼면 셀이 엉뚱하게 대응되고 결과는 여전히 숫자다.
- 겹치는 영역이 없으면 거부한다 — "변화 0" 이 아니다.
- 구역 폴리곤이 래스터 밖이면 거부한다 — 잴 수 없는 것과 변화가 없는 것은 다르다.
- nodata 셀은 집계에서 뺀다 — 0 으로 읽으면 그 셀에서 거대한 절토가 생긴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from ksi_geo_spatial.crs import assert_same_crs, reproject_geometry
from numpy.typing import NDArray
from rasterio import features
from rasterio.warp import Resampling, reproject


class DsmDiffError(ValueError):
    """DSM 차분·체적 계산이 성립하지 않는다 — 숫자를 지어내지 않는다."""


@dataclass(frozen=True, slots=True)
class DiffResult:
    """두 DSM 의 표고차 격자 — ``current - baseline`` (m).

    ``valid`` 가 False 인 셀은 **모름**이지 0 이 아니다. 두 시점 중 한쪽이라도
    nodata 면 그 셀의 변화량은 알 수 없다.
    """

    diff_m: NDArray[np.float64]
    valid: NDArray[np.bool_]
    transform: Any
    crs: str
    cell_area_m2: float


def align_and_diff(baseline_path: Path, current_path: Path) -> DiffResult:
    """두 DSM 을 공통 격자에 맞추고 뺀다.

    기준 격자는 **baseline** 이다 — 시계열 비교에서 "무엇 대비"의 그 무엇이
    격자도 정한다. current 를 baseline 격자로 재투영(bilinear)한다.
    """
    with rasterio.open(baseline_path) as base_ds, rasterio.open(current_path) as curr_ds:
        base_crs = base_ds.crs
        curr_crs = curr_ds.crs
        if base_crs is None or curr_crs is None:
            raise DsmDiffError(
                "DSM 에 좌표계가 없다 — CRS 없는 래스터는 다른 시점과 비교할 수 없다"
            )
        # INV-020 강제 지점. 다르면 여기서 멈춘다.
        crs = assert_same_crs(str(base_crs), str(curr_crs))

        base = base_ds.read(1).astype(np.float64)
        base_valid = _valid_mask(base, base_ds.nodata)

        curr_on_base = np.empty_like(base)
        curr_valid_float = np.zeros_like(base)
        reproject(
            source=curr_ds.read(1).astype(np.float64),
            destination=curr_on_base,
            src_transform=curr_ds.transform,
            src_crs=curr_ds.crs,
            dst_transform=base_ds.transform,
            dst_crs=base_ds.crs,
            src_nodata=curr_ds.nodata,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        # 유효성 마스크도 같은 변환으로 옮긴다 — 재투영이 nodata 를 채운 자리를
        # 유효한 값으로 오인하지 않기 위해서다.
        reproject(
            source=_valid_mask(curr_ds.read(1).astype(np.float64), curr_ds.nodata).astype(
                np.float64
            ),
            destination=curr_valid_float,
            src_transform=curr_ds.transform,
            src_crs=curr_ds.crs,
            dst_transform=base_ds.transform,
            dst_crs=base_ds.crs,
            src_nodata=None,
            dst_nodata=0.0,
            resampling=Resampling.nearest,
        )
        transform = base_ds.transform
        cell_area = abs(transform.a * transform.e)

    valid = base_valid & (curr_valid_float > 0.5) & np.isfinite(curr_on_base)
    if not valid.any():
        raise DsmDiffError(
            "두 DSM 이 겹치는 유효 영역이 없다 — 비교 대상이 아니다(변화 0 이 아니라 "
            "잴 수 없는 것이다)"
        )

    diff = np.zeros_like(base)
    diff[valid] = curr_on_base[valid] - base[valid]
    return DiffResult(
        diff_m=diff, valid=valid, transform=transform, crs=crs, cell_area_m2=cell_area
    )


def _valid_mask(values: NDArray[np.float64], nodata: float | None) -> NDArray[np.bool_]:
    mask = np.isfinite(values)
    if nodata is not None:
        mask &= values != nodata
    return mask


def volume_delta_in_polygon(
    diff: DiffResult,
    polygon_geojson: dict[str, Any],
    *,
    zone_id: str,
    from_crs: str,
    threshold_m: float,
    uncertainty_note: str,
    baseline_rmse_m: float | None = None,
    current_rmse_m: float | None = None,
) -> ZoneVolumeDelta:
    """구역 하나의 절토·성토.

    ``from_crs`` 는 폴리곤의 좌표계다 — AOI 는 보통 WGS84 로 들어오고 래스터는
    투영좌표계라, 여기서 맞춰준다(수평축만; 수직은 이 함수의 관심사가 아니다).

    ``threshold_m`` 미만의 표고차는 세지 않는다. 재구성 노이즈를 변화로 읽으면
    아무것도 안 한 날에도 체적이 나온다.
    """
    if threshold_m < 0.0 or not math.isfinite(threshold_m):
        raise DsmDiffError(f"threshold_m 은 0 이상의 finite 여야 한다: {threshold_m!r}")

    geometry = (
        polygon_geojson
        if _same_frame(from_crs, diff.crs)
        else reproject_geometry(polygon_geojson, from_crs=from_crs, to_crs=diff.crs)
    )

    try:
        zone_mask = features.geometry_mask(
            [geometry],
            out_shape=diff.diff_m.shape,
            transform=diff.transform,
            invert=True,  # 폴리곤 **안**이 True
            all_touched=False,
        )
    except ValueError as exc:
        raise DsmDiffError(f"구역 폴리곤을 래스터 격자에 올릴 수 없다: {exc}") from exc

    selected = zone_mask & diff.valid
    cell_count = int(selected.sum())
    if cell_count == 0:
        raise DsmDiffError(
            "구역 안에 유효한 DSM 셀이 하나도 없다 — 래스터 밖이거나 전부 nodata 다. "
            "'변화 0' 과 '잴 수 없음' 은 다른 사실이다"
        )

    delta = diff.diff_m[selected]
    counted = np.abs(delta) >= threshold_m
    cell_area = diff.cell_area_m2

    fill_m3 = float(delta[counted & (delta > 0)].sum() * cell_area)
    cut_m3 = float(-delta[counted & (delta < 0)].sum() * cell_area)
    area_m2 = float(cell_count * cell_area)

    return ZoneVolumeDelta(
        zone_id=zone_id,
        cut_m3=cut_m3,
        fill_m3=fill_m3,
        net_m3=fill_m3 - cut_m3,
        area_m2=area_m2,
        threshold_m=threshold_m,
        uncertainty_m3=_uncertainty_m3(
            area_m2=area_m2,
            baseline_rmse_m=baseline_rmse_m,
            current_rmse_m=current_rmse_m,
        ),
        uncertainty_note=uncertainty_note,
    )


def _uncertainty_m3(
    *, area_m2: float, baseline_rmse_m: float | None, current_rmse_m: float | None
) -> float | None:
    """체적 오차한계 — **양쪽이 검증됐을 때만** 값이다 (INV-024).

    한쪽만 알면 차분의 오차를 말할 수 없다. 모르는 쪽을 0 으로 두면 "검증된
    한쪽만큼만 틀릴 수 있다"는 거짓 주장이 된다.

    두 시점의 수직 오차가 독립이라 보고 제곱합근으로 합성한 뒤 면적을 곱한다.
    이는 **오차가 구역 전체에서 완전히 상관돼 있다고 본 보수적 상한**이다 —
    셀별로 독립이라면 상쇄되어 훨씬 작아진다. 어느 쪽인지는 실측 없이 알 수
    없으므로 큰 쪽을 택한다.
    """
    if baseline_rmse_m is None or current_rmse_m is None:
        return None
    if baseline_rmse_m < 0 or current_rmse_m < 0:
        raise DsmDiffError("RMSE 는 음수일 수 없다")
    combined = math.hypot(baseline_rmse_m, current_rmse_m)
    return combined * area_m2


def _same_frame(a: str, b: str) -> bool:
    try:
        assert_same_crs(a, b)
    except Exception:
        return False
    return True


__all__ = [
    "DiffResult",
    "DsmDiffError",
    "align_and_diff",
    "volume_delta_in_polygon",
]
