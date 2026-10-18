import type { SpatialDataBounds } from "@/lib/core-api/spatial-data-types";

/** 검사가 관측한 래스터 격자 사실 — Core의 검사 영수증에서 온 값만 받는다. */
export interface InspectedRasterGrid {
  transform: readonly number[];
  width: number;
  height: number;
}

/**
 * 검사된 네이티브 격자의 정확한 사각형을 만든다 — 추측하거나 반올림하지 않는다.
 *
 * transform은 GDAL 6-튜플(px 폭, 회전, 원점 x, 회전, -px 높이, 원점 y)이다.
 * Core는 "정확한 네이티브 사각형"만 받으므로, 여기서 만든 값이 곧 그 사각형이다:
 * (minx, miny, maxx, maxy) — y는 위에서 아래로 내려가므로 miny가 남쪽이다.
 * 회전(rotated) 격자·비정상 값은 null을 돌려주고 요청 자체를 만들지 않는다.
 */
export function nativeBoundsFromInspection(raster: InspectedRasterGrid): SpatialDataBounds | null {
  const [a, b, c, d, e, f] = raster.transform;
  if (![a, b, c, d, e, f].every((value) => typeof value === "number" && Number.isFinite(value))) return null;
  if (!Number.isInteger(raster.width) || !Number.isInteger(raster.height) || raster.width <= 0 || raster.height <= 0) return null;
  if (b !== 0 || d !== 0) return null;
  if (a <= 0 || e >= 0) return null;
  const minx = c;
  const maxx = c + a * raster.width;
  const maxy = f;
  const miny = f + e * raster.height;
  if (!(minx < maxx) || !(miny < maxy)) return null;
  return [minx, miny, maxx, maxy];
}
