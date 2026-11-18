/**
 * 측정 선 단면의 순수 계산. 화면 상태나 Core 호출을 모른다.
 *
 * 원칙: 모르는 지점(elevationM = null)은 0이나 이웃 값, 직선 보간으로 채우지 않는다.
 * 선은 모르는 지점에서 끊고, 구간 읽기는 구간 안의 유효 값만 쓴다.
 */
import type { ProfileSample, SampleInvalidReason } from "@/lib/core-api/measurement-types";

const UNKNOWN_LABEL: Record<SampleInvalidReason, string> = {
  OUTSIDE_SURFACE: "범위 밖",
  INSUFFICIENT_NEIGHBORS: "가장자리",
  NODATA: "자료 없음",
};

export function unknownLabel(reason: SampleInvalidReason): string {
  return UNKNOWN_LABEL[reason];
}

export interface UnknownCounts {
  outside: number;
  edge: number;
  nodata: number;
  total: number;
}

export function countUnknown(samples: readonly ProfileSample[]): UnknownCounts {
  const counts: UnknownCounts = { outside: 0, edge: 0, nodata: 0, total: 0 };
  for (const row of samples) {
    if (row.invalidReason === null) continue;
    counts.total += 1;
    if (row.invalidReason === "OUTSIDE_SURFACE") counts.outside += 1;
    else if (row.invalidReason === "INSUFFICIENT_NEIGHBORS") counts.edge += 1;
    else counts.nodata += 1;
  }
  return counts;
}

/** 값이 있는 지점이 이어진 묶음. 모르는 지점이 끼면 묶음이 갈라진다. */
export function knownRuns(samples: readonly ProfileSample[]): ProfileSample[][] {
  const runs: ProfileSample[][] = [];
  let current: ProfileSample[] = [];
  for (const row of samples) {
    if (row.elevationM === null) {
      if (current.length > 0) runs.push(current);
      current = [];
    } else {
      current.push(row);
    }
  }
  if (current.length > 0) runs.push(current);
  return runs;
}

/** 거리에 가장 가까운 지점. 거리가 오름차순인 계약(0에서 시작해 엄격히 증가)에 기댄 이분 탐색이다. */
export function nearestSample(samples: readonly ProfileSample[], distanceM: number): ProfileSample | null {
  if (samples.length === 0) return null;
  let low = 0;
  let high = samples.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (samples[mid]!.distanceM < distanceM) low = mid + 1;
    else high = mid;
  }
  const after = samples[low]!;
  const before = low > 0 ? samples[low - 1]! : null;
  if (before && distanceM - before.distanceM <= after.distanceM - distanceM) return before;
  return after;
}

export interface RangeReading {
  fromM: number;
  toM: number;
  /** 선택한 구간의 길이(m). */
  lengthM: number;
  /** 구간 안 처음 유효 값에서 마지막 유효 값까지의 높이 변화(m). */
  heightChangeM: number;
  /** 같은 두 유효 지점 사이의 기울기(%). 오르막이 양수다. */
  gradePercent: number;
}

/** 구간 [fromM, toM]의 높이 차와 기울기. 유효 지점이 둘보다 적으면 값을 만들지 않고 null이다. */
export function readRange(samples: readonly ProfileSample[], a: number, b: number): RangeReading | null {
  const fromM = Math.min(a, b);
  const toM = Math.max(a, b);
  let first: ProfileSample | null = null;
  let last: ProfileSample | null = null;
  for (const row of samples) {
    if (row.distanceM < fromM || row.distanceM > toM || row.elevationM === null) continue;
    if (first === null) first = row;
    last = row;
  }
  if (first === null || last === null || last.distanceM <= first.distanceM) return null;
  const heightChangeM = last.elevationM! - first.elevationM!;
  return {
    fromM,
    toM,
    lengthM: toM - fromM,
    heightChangeM,
    gradePercent: (heightChangeM / (last.distanceM - first.distanceM)) * 100,
  };
}

export interface VerticalScale {
  lo: number;
  hi: number;
  ticks: number[];
}

const STEPS = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100];

function niceStep(span: number, target: number): number {
  const raw = span / target;
  for (const step of STEPS) if (step >= raw) return step;
  return STEPS[STEPS.length - 1]!;
}

function ticksFor(lo: number, hi: number, step: number): number[] {
  const ticks: number[] = [];
  const first = Math.ceil(lo / step - 1e-9) * step;
  for (let value = first; value <= hi + 1e-9; value += step) {
    ticks.push(Math.round(value / step) * step);
  }
  return ticks;
}

/**
 * 세로 범위. "fit"은 유효 값을 여유와 함께 덮고, "true"는 가로 1 m와 세로 1 m가 같은 화면 길이가
 * 되도록 잡는다(실제 기울기가 얼마나 완만한지 그대로 보인다).
 */
export function verticalScale(
  runs: readonly (readonly ProfileSample[])[],
  mode: "fit" | "true",
  plotWidthPx: number,
  plotHeightPx: number,
  lengthM: number,
): VerticalScale | null {
  let min = Infinity;
  let max = -Infinity;
  for (const run of runs) {
    for (const row of run) {
      if (row.elevationM === null) continue;
      if (row.elevationM < min) min = row.elevationM;
      if (row.elevationM > max) max = row.elevationM;
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  let lo: number;
  let hi: number;
  if (mode === "true") {
    const spanM = plotHeightPx / (plotWidthPx / lengthM);
    const mid = (min + max) / 2;
    lo = mid - spanM / 2;
    hi = mid + spanM / 2;
  } else {
    const pad = Math.max((max - min) * 0.12, 0.25);
    lo = min - pad;
    hi = max + pad;
  }
  return { lo, hi, ticks: ticksFor(lo, hi, niceStep(hi - lo, 4)) };
}

const FORMULA_START = /^[=+\-@\t\r]/;

function csvText(value: string): string {
  // 스프레드시트가 수식으로 읽지 않도록 앞에 작은따옴표를 붙인다.
  const safe = FORMULA_START.test(value) ? `'${value}` : value;
  return `"${safe.replaceAll('"', '""')}"`;
}

export interface CsvSeries {
  label: string;
  samples: readonly ProfileSample[];
  /** 높이가 읽힌 수직 기준 코드(`observed:EPSG:n` 또는 `declared:<기준>`). 모르면 비운다. */
  vertical?: string;
}

/** 길게 늘어선 CSV. 모르는 지점은 높이를 비우고 이유 코드를 적는다. 0으로 채우지 않는다. */
export function profileCsv(series: readonly CsvSeries[]): string {
  const lines = ["series,distance_m,x,y,elevation_m,unknown_reason,vertical_reference"];
  for (const item of series) {
    for (const row of item.samples) {
      lines.push(
        [
          csvText(item.label),
          String(row.distanceM),
          String(row.x),
          String(row.y),
          row.elevationM === null ? "" : String(row.elevationM),
          row.invalidReason ?? "",
          // 선언한 기준은 파일에서 확인한 값이 아니다. 내보낸 뒤에도 표에서 갈라 읽을 수 있게 한 열을 둔다.
          csvText(item.vertical ?? ""),
        ].join(","),
      );
    }
  }
  return `﻿${lines.join("\r\n")}\r\n`;
}

const CRS_NAME: Record<string, string> = {
  "EPSG:5179": "한국 통합 TM",
  "EPSG:5185": "한국 서부원점 TM",
  "EPSG:5186": "한국 중부원점 TM",
  "EPSG:5187": "한국 동부원점 TM",
  "EPSG:5188": "한국 동해원점 TM",
};

export function crsLabel(crs: string): string {
  const name = CRS_NAME[crs];
  return name ? `${name} · ${crs}` : crs;
}

/** 부호를 항상 붙인다. 음수는 하이픈이 아니라 빼기 기호를 쓴다. */
export function formatSigned(value: number, digits: number): string {
  const text = Math.abs(value).toFixed(digits);
  return value < 0 && Number(text) !== 0 ? `−${text}` : `+${text}`;
}
