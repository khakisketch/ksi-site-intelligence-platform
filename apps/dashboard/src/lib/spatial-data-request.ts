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

/**
 * Console이 요청할 수 있는 네이티브 픽셀 창의 한 변 상한.
 * 출력 예산을 묶기 위해 512를 넘지 않는다 — 1024 변형 게이트를 넓히지 않는다.
 * 하한은 두지 않는다: 1px 이상의 실제 검사 격자는 그대로 요청할 수 있다.
 */
export const MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM = 512;

/** 픽셀 창을 만들 수 없는 typed 사유 — 화면은 이 값으로만 다음 행동을 고른다. */
export type PixelWindowBlockerReason =
  | "NO_INSPECTION"
  | "INVALID_GRID"
  | "ROTATED_GRID"
  | "INVALID_WINDOW"
  | "OUT_OF_BOUNDS";

export interface BoundedPixelWindow {
  /** 파일 좌표 순서 [원점 열, 원점 행, 너비, 높이] — Core pixelWindow와 같은 순서다. */
  window: [number, number, number, number];
  /** 창에서 유도된 정확한 네이티브 사각형 — 반올림하지 않는다. */
  requestedBounds: SpatialDataBounds;
  width: number;
  height: number;
}

export type BoundedPixelWindowResult =
  | { ok: true; value: BoundedPixelWindow }
  | { ok: false; reason: PixelWindowBlockerReason };

/** 화면에 그대로 두는 차단 사유 문구 — 판정을 새로 만들지 않는다. */
export const PIXEL_WINDOW_BLOCKER_COPY: Record<PixelWindowBlockerReason, string> = {
  NO_INSPECTION: "검사된 격자 정보를 확인하지 못해 요청 범위를 만들 수 없습니다. 파일 검사 상태를 확인하세요.",
  INVALID_GRID: "검사 격자의 수치 형식이 올바르지 않아 요청 범위를 만들 수 없습니다. 화면을 새로 고쳐 다시 확인하세요.",
  ROTATED_GRID: "회전되거나 비표준 격자라 요청 범위를 만들 수 없습니다. 지원되는 격자인지 관리자에게 확인하세요.",
  INVALID_WINDOW: "픽셀 창의 수치 형식이 올바르지 않습니다. 너비·높이는 1 이상 512 이하의 정수, 원점은 0 이상의 정수를 입력하세요.",
  OUT_OF_BOUNDS: "픽셀 창이 검사 격자를 벗어납니다. 원점과 크기를 격자 안에 맞게 조정하세요.",
};

/** 요청자가 고른 창 — 너비·높이는 독립적이다(정사각형 강제 없음). */
export interface PixelWindowSelection {
  width: number;
  height: number;
  col: number;
  row: number;
}

/**
 * 격자에 들어가는 초기 창 — 작은 격자는 전체 격자 그대로, 큰 격자는
 * 가운데 512 이하 창. 유효한 격자에는 항상 창을 돌려준다(최소 크기 fiction 없음).
 * 유효하지 않은 격자에는 null이다.
 */
export function initialPixelWindowDims(
  width: number,
  height: number,
): PixelWindowSelection | null {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) return null;
  const windowWidth = Math.min(width, MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM);
  const windowHeight = Math.min(height, MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM);
  return {
    width: windowWidth,
    height: windowHeight,
    col: Math.floor((width - windowWidth) / 2),
    row: Math.floor((height - windowHeight) / 2),
  };
}

/** 전체 격자를 그대로 요청할 수 있을 때만 true — 어느 한 변도 512를 넘지 않는다. */
export function canUseWholeGrid(width: number, height: number): boolean {
  return Number.isInteger(width) && Number.isInteger(height)
    && width >= 1 && height >= 1
    && width <= MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM
    && height <= MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM;
}

/**
 * 실제 검사 격자에서만 유도된 유한 픽셀 창과 그 네이티브 사각형을 만든다.
 * 리샘플링·반올림·추측을 하지 않으며, 막히면 사유만 돌려준다.
 */
export function resolveBoundedPixelWindow(
  raster: InspectedRasterGrid | null,
  selection: PixelWindowSelection,
): BoundedPixelWindowResult {
  if (raster === null) return { ok: false, reason: "NO_INSPECTION" };
  const [a, b, c, d, e, f] = raster.transform;
  if (![a, b, c, d, e, f].every((value) => typeof value === "number" && Number.isFinite(value))) {
    return { ok: false, reason: "INVALID_GRID" };
  }
  if (!Number.isInteger(raster.width) || !Number.isInteger(raster.height) || raster.width <= 0 || raster.height <= 0) {
    return { ok: false, reason: "INVALID_GRID" };
  }
  if (b !== 0 || d !== 0) return { ok: false, reason: "ROTATED_GRID" };
  if (a <= 0 || e >= 0) return { ok: false, reason: "INVALID_GRID" };
  const { width, height, col, row } = selection;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0
    || width > MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM || height > MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM) {
    return { ok: false, reason: "INVALID_WINDOW" };
  }
  if (!Number.isInteger(col) || !Number.isInteger(row) || col < 0 || row < 0) {
    return { ok: false, reason: "INVALID_WINDOW" };
  }
  if (col + width > raster.width || row + height > raster.height) {
    return { ok: false, reason: "OUT_OF_BOUNDS" };
  }
  const minx = c + a * col;
  const maxx = c + a * (col + width);
  const maxy = f + e * row;
  const miny = f + e * (row + height);
  if (!(minx < maxx) || !(miny < maxy)) return { ok: false, reason: "INVALID_GRID" };
  return {
    ok: true,
    value: {
      window: [col, row, width, height],
      requestedBounds: [minx, miny, maxx, maxy],
      width,
      height,
    },
  };
}
