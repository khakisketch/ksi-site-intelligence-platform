/**
 * 뷰포트 → 네이티브 창 집합 해석(순수 함수).
 *
 * 표시/LOD 계약 §3(어드레싱·경계 정확성)과 §4(줌·팬 시 요청 동작)의
 * Console 측 해석 규칙이다. Core의 격자·권리·영수증 판정을 대신하지
 * 않는다 — 무엇을 요청할지만 고른다.
 *
 * - 모든 창은 관측의 네이티브 격자에서 정수 픽셀 사각형
 *   (c0, c1, r0, r1)(half-open 열·행)으로 주소한다.
 * - 타일 경계는 소스 격자 원점(0) 기준 maxDim 배수이며, 뷰포트에 맞춰
 *   움직이지 않는다 — 같은 영역은 같은 창 집합으로 해석된다(결정적).
 * - 인접 창은 정수 경계를 정확히 공유한다(틈·겹침 없음).
 * - 한 창은 출력 픽셀 상한(기본 512×512)을 넘지 않는다.
 * - 시점이 여러 개면 각 시점의 격자에서 따로 해석한다 — 한 시점의
 *   픽셀 창을 다른 시점에 재해석하지 않는다(계약 §7).
 *
 * transform 튜플은 (xScale, rot, xOrigin, rot, yScale, yOrigin)이며
 * yScale은 t[4], yOrigin은 t[5]이다.
 *
 * Invariants: INV-020(면적 어림 없음 — 범위 판정 없음)/INV-024(원본 식별
 * 보존)/INV-053(네이티브 격자 — 좌표 재해석 없음)/INV-060·061(권한·이그레스).
 */

import { MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM } from "./spatial-data-request";

/** 네이티브 격자 사실 — Core 검사 영수증에서 온 값만 받는다. */
export interface DisplaySourceGrid {
  transform: readonly number[];
  width: number;
  height: number;
}

/** 네이티브 평면의 뷰포트 범위 [minx, miny, maxx, maxy]. */
export type DisplayViewportBounds = [number, number, number, number];

/** 해석된 한 창 — Core pixelWindow와 같은 half-open 순서다. */
export interface DisplayWindowPlan {
  /** [c0, c1, r0, r1] — 열 half-open, 행 half-open. */
  pixelWindow: [number, number, number, number];
  /** 창에서 유도된 정확한 네이티브 사각형 — 반올림하지 않는다. */
  actualBounds: DisplayViewportBounds;
  width: number;
  height: number;
}

export type ViewportResolveReason =
  | "NO_INSPECTION"
  | "INVALID_GRID"
  | "ROTATED_GRID"
  | "INVALID_VIEWPORT"
  | "NO_COVERAGE"
  | "OVER_PIXEL_CAP";

export type ViewportResolveResult =
  | { ok: true; windows: DisplayWindowPlan[] }
  | { ok: false; reason: ViewportResolveReason };

/** 화면에 그대로 두는 해석 차단 사유 — 판정을 새로 만들지 않는다. */
export const VIEWPORT_RESOLVE_COPY: Record<ViewportResolveReason, string> = {
  NO_INSPECTION: "검사된 격자 정보를 확인하지 못해 창 집합을 만들 수 없습니다. 파일 검사 상태를 확인하세요.",
  INVALID_GRID: "검사 격자의 수치 형식이 올바르지 않아 창 집합을 만들 수 없습니다. 화면을 새로 고쳐 다시 확인하세요.",
  ROTATED_GRID: "회전되거나 비표준 격자라 창 집합을 만들 수 없습니다. 지원되는 격자인지 관리자에게 확인하세요.",
  INVALID_VIEWPORT: "보기 범위의 수치 형식이 올바르지 않아 창 집합을 만들 수 없습니다. 범위를 다시 확인하세요.",
  NO_COVERAGE: "이 보기 범위에는 이 시점의 관측이 없습니다. 범위를 옮기거나 다른 시점을 확인하세요.",
  OVER_PIXEL_CAP: "한 창의 출력 한계를 넘어 창 집합을 만들 수 없습니다. 보기 범위를 좁히세요.",
};

export interface ViewportResolveOptions {
  /** 한 창의 한 변 상한 — 기본 512(Core 출력 한도와 같은 자리수). */
  maxDim?: number;
  /** 한 창의 출력 픽셀 상한 — 기본 512×512(Core per-output cap과 같은 값). */
  maxPixels?: number;
}

export const DISPLAY_WINDOW_MAX_PIXELS = 512 * 512;

/** JS의 Number용 ulp — Python math.ulp와 같은 정의다. */
function jsUlp(value: number): number {
  if (!Number.isFinite(value)) return Number.NaN;
  if (value === 0) return Number.MIN_VALUE;
  const magnitude = Math.abs(value);
  const exponent = Math.floor(Math.log2(magnitude));
  const unit = Math.pow(2, exponent - 52);
  return unit < Number.MIN_VALUE ? Number.MIN_VALUE : unit;
}

/**
 * Core `_stable_pixel_index`와 같은 이진 탐색 — 표현 가능한 어파인
 * 경계에서 floor/ceil을 고정한다. 같은 격자·같은 범위에는 같은
 * 인덱스를 돌려준다.
 */
function stablePixelIndex(
  coordinate: number,
  origin: number,
  step: number,
  dimension: number,
  rounding: "floor" | "ceil",
): number {
  if (dimension <= 0 || step === 0) throw new Error("INVALID_SOURCE_GEOMETRY");
  const finalEdge = origin + step * dimension;
  const extent = step * dimension;
  const precisionFloor = Math.max(jsUlp(origin), jsUlp(finalEdge), jsUlp(extent));
  if (!Number.isFinite(finalEdge) || Math.abs(step) < precisionFloor) {
    throw new Error("UNREPRESENTABLE_GRID");
  }
  const direction = step > 0 ? 1 : -1;
  const target = coordinate * direction;
  let low = 0;
  let high = dimension;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    const edge = origin + step * middle;
    if (!Number.isFinite(edge)) throw new Error("INVALID_SOURCE_GEOMETRY");
    if (edge * direction < target) low = middle + 1;
    else high = middle;
  }
  const edge = origin + step * low;
  if (edge === coordinate) return low;
  return rounding === "floor" ? low - 1 : low;
}

function readGrid(grid: DisplaySourceGrid): {
  ok: true;
  a: number;
  e: number;
  c: number;
  f: number;
} | { ok: false; reason: ViewportResolveReason } {
  const [a, b, c, d, e, f] = grid.transform;
  if (
    ![a, b, c, d, e, f].every((value) => typeof value === "number" && Number.isFinite(value))
  ) {
    return { ok: false, reason: "INVALID_GRID" };
  }
  if (
    !Number.isInteger(grid.width) ||
    !Number.isInteger(grid.height) ||
    grid.width <= 0 ||
    grid.height <= 0
  ) {
    return { ok: false, reason: "INVALID_GRID" };
  }
  if (b !== 0 || d !== 0) return { ok: false, reason: "ROTATED_GRID" };
  if (a <= 0 || e >= 0) return { ok: false, reason: "INVALID_GRID" };
  return { ok: true, a: a as number, e: e as number, c: c as number, f: f as number };
}

/**
 * 뷰포트 범위를 최소 창 집합으로 해석한다.
 *
 * - 뷰포트를 소스 발자국과 교차시킨 뒤, 그 교차 범위를 셀 경계로
 *   넓혀 픽셀 범위로 바꾼다.
 * - 픽셀 범위를 소스 원점 기준 maxDim 배수 경계로 나눈다 — 같은
 *   격자의 같은 영역은 호출 시점과 무관하게 같은 창 집합이다.
 * - 각 창의 actualBounds는 정수 창에서 정확히 유도한다.
 */
export function resolveViewportWindows(
  grid: DisplaySourceGrid | null,
  viewport: DisplayViewportBounds,
  options: ViewportResolveOptions = {},
): ViewportResolveResult {
  if (grid === null) return { ok: false, reason: "NO_INSPECTION" };
  const parsed = readGrid(grid);
  if (!parsed.ok) return { ok: false, reason: parsed.reason };
  const maxDim = options.maxDim ?? MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM;
  const maxPixels = options.maxPixels ?? DISPLAY_WINDOW_MAX_PIXELS;
  if (
    !Array.isArray(viewport) ||
    viewport.length !== 4 ||
    !viewport.every((value) => typeof value === "number" && Number.isFinite(value))
  ) {
    return { ok: false, reason: "INVALID_VIEWPORT" };
  }
  const [vx0, vy0, vx1, vy1] = viewport;
  if (!(vx0 < vx1) || !(vy0 < vy1)) return { ok: false, reason: "INVALID_VIEWPORT" };

  const { a, e, c, f } = parsed;
  const left = c;
  const right = c + a * grid.width;
  const top = f;
  const bottom = f + e * grid.height;
  if (!(left < right) || !(bottom < top)) return { ok: false, reason: "INVALID_GRID" };

  const ix0 = Math.max(vx0, left);
  const iy0 = Math.max(vy0, bottom);
  const ix1 = Math.min(vx1, right);
  const iy1 = Math.min(vy1, top);
  if (!(ix0 < ix1) || !(iy0 < iy1)) return { ok: false, reason: "NO_COVERAGE" };

  let c0: number;
  let c1: number;
  let r0: number;
  let r1: number;
  try {
    c0 = stablePixelIndex(ix0, c, a, grid.width, "floor");
    c1 = stablePixelIndex(ix1, c, a, grid.width, "ceil");
    // 행: 위쪽(ymax)이 작은 인덱스다 — yScale(t[4])이 음수이므로
    // 원점 y(t[5])에서 내려간다.
    r0 = stablePixelIndex(iy1, f, e, grid.height, "floor");
    r1 = stablePixelIndex(iy0, f, e, grid.height, "ceil");
  } catch {
    return { ok: false, reason: "INVALID_GRID" };
  }
  c0 = Math.max(0, c0);
  r0 = Math.max(0, r0);
  c1 = Math.min(grid.width, c1);
  r1 = Math.min(grid.height, r1);
  if (!(c0 < c1) || !(r0 < r1)) return { ok: false, reason: "NO_COVERAGE" };

  // 소스 원점 기준 타일 경계 — 뷰포트에 맞춘 원점이 아니다.
  const colEdges: number[] = [c0];
  const firstColLine = Math.floor(c0 / maxDim) * maxDim + maxDim;
  for (let edge = firstColLine; edge > c0 && edge < c1; edge += maxDim) colEdges.push(edge);
  colEdges.push(c1);
  const rowEdges: number[] = [r0];
  const firstRowLine = Math.floor(r0 / maxDim) * maxDim + maxDim;
  for (let edge = firstRowLine; edge > r0 && edge < r1; edge += maxDim) rowEdges.push(edge);
  rowEdges.push(r1);

  const windows: DisplayWindowPlan[] = [];
  for (let ri = 0; ri + 1 < rowEdges.length; ri += 1) {
    for (let ci = 0; ci + 1 < colEdges.length; ci += 1) {
      const wc0 = colEdges[ci] as number;
      const wc1 = colEdges[ci + 1] as number;
      const wr0 = rowEdges[ri] as number;
      const wr1 = rowEdges[ri + 1] as number;
      const width = wc1 - wc0;
      const height = wr1 - wr0;
      if (width <= 0 || height <= 0) continue;
      if (width * height > maxPixels) return { ok: false, reason: "OVER_PIXEL_CAP" };
      const minx = c + a * wc0;
      const maxx = c + a * wc1;
      const maxy = f + e * wr0;
      const miny = f + e * wr1;
      if (!(minx < maxx) || !(miny < maxy)) return { ok: false, reason: "INVALID_GRID" };
      windows.push({
        pixelWindow: [wc0, wc1, wr0, wr1],
        actualBounds: [minx, miny, maxx, maxy],
        width,
        height,
      });
    }
  }
  if (windows.length === 0) return { ok: false, reason: "NO_COVERAGE" };
  return { ok: true, windows };
}

/** 전체 격자를 가리는 창 집합 — 부분 뷰포트와 같은 규칙이다. */
export function resolveFullCoverWindows(
  grid: DisplaySourceGrid | null,
  options: ViewportResolveOptions = {},
): ViewportResolveResult {
  if (grid === null) return { ok: false, reason: "NO_INSPECTION" };
  const parsed = readGrid(grid);
  if (!parsed.ok) return { ok: false, reason: parsed.reason };
  const { a, e, c, f } = parsed;
  return resolveViewportWindows(
    grid,
    [c, f + e * grid.height, c + a * grid.width, f],
    options,
  );
}

/**
 * 시점별 창 집합 — 각 시점은 자신의 격자에서 따로 해석한다.
 *
 * 같은 숫자의 뷰포트라도 격자가 다르면 결과가 다르며, 한 시점의
 * 픽셀 창을 다른 시점에 그대로 쓰지 않는다. 시점 전환은 이 함수를
 * 새 시점 격자로 다시 호출하는 것이다(계약 §7).
 */
export function resolvePerEpochWindows(
  grids: Record<string, DisplaySourceGrid | null>,
  viewports: Record<string, DisplayViewportBounds>,
  options: ViewportResolveOptions = {},
): Record<string, ViewportResolveResult> {
  const result: Record<string, ViewportResolveResult> = {};
  for (const epochId of Object.keys(grids)) {
    const viewport = viewports[epochId];
    if (viewport === undefined) {
      result[epochId] = { ok: false, reason: "INVALID_VIEWPORT" };
      continue;
    }
    result[epochId] = resolveViewportWindows(grids[epochId] ?? null, viewport, options);
  }
  return result;
}
