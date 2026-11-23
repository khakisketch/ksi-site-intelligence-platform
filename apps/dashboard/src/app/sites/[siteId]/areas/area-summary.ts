import type { Tone } from "@/lib/core-api/labels";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";
import {
  CRS_SWATCH_COUNT,
  captureDateOf,
  summarizeAreaDsmCrs,
  type AreaDsmCrs,
} from "@/lib/crs-match";
import { isAnalysisCrs } from "@/lib/geo/known-crs";

import {
  extractSimpleRing,
  nativeScaleBarLength,
  planeUnitForCrs,
  sameDisplayPlane,
  selectableGeometry,
} from "../site-spatial";

/**
 * 공간 화면 "영역" 탭의 순수 모델 — 렌더링과 Core 호출을 모른다.
 *
 * 여기서 만드는 모든 값은 **화면 표시용**이다. 면적·지도 모양은 근삿값이고, 영역 경계가
 * 분석에 맞다는 뜻이 아니다. 비교·체적을 열지는 Core가 같은 좌표계인지 다시 확인해 정한다
 * (INV-020). 모르는 값은 0이나 빈 값으로 바꾸지 않고 null로 둔다.
 */

/** 지구 평균 반지름(m). 경위도 영역의 표시용 면적·지도 근사에만 쓴다. */
const EARTH_RADIUS_M = 6_371_008.8;
const METERS_PER_DEGREE = (EARTH_RADIUS_M * Math.PI) / 180;

type Ring = ReadonlyArray<readonly [number, number]>;

function validGeographicRing(ring: Ring): boolean {
  return ring.every(([lon, lat]) => Math.abs(lon) <= 180 && Math.abs(lat) <= 90);
}

/** 평면 위 좌표(미터 단위로 맞춘 값)로 옮긴다. 경위도는 `centerLat`의 등장방형 근사를 쓴다. */
function toLocalMeters(ring: Ring, unit: "meters" | "degrees", centerLat: number): Array<[number, number]> {
  if (unit === "meters") return ring.map(([x, y]) => [x, y]);
  const lonScale = METERS_PER_DEGREE * Math.cos((centerLat * Math.PI) / 180);
  return ring.map(([lon, lat]) => [lon * lonScale, lat * METERS_PER_DEGREE]);
}

function shoelace(points: ReadonlyArray<readonly [number, number]>): number {
  let sum = 0;
  for (let i = 0; i < points.length; i += 1) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * y2 - x2 * y1;
  }
  return sum / 2;
}

function latitudeCenter(ring: Ring): number {
  const lats = ring.map(([, lat]) => lat);
  return (Math.min(...lats) + Math.max(...lats)) / 2;
}

/**
 * 영역 넓이(㎡)의 **표시용 근삿값**.
 *
 * - 미터 단위 투영 좌표계: 바깥 링의 신발끈(shoelace) 넓이 그대로.
 * - 경위도(EPSG:4326): 링의 중심 위도에서 등장방형으로 펴서 같은 계산.
 * - 구멍·MultiPolygon·읽을 수 없는 모양·모르는 좌표계 단위·넓이 0은 null이다 — 0이나 추측값을 내지 않는다.
 *
 * 면적 계산이 아니라 목록에 "약 N ㎡"로 보이기 위한 값이다. 정산·수량 근거로 쓰지 않는다.
 */
export function approxAreaSquareMeters(polygon: Record<string, unknown> | null | undefined, crs: string | null | undefined): number | null {
  if (!polygon || typeof crs !== "string" || crs.trim().length === 0) return null;
  const ring = extractSimpleRing(polygon);
  if (!ring) return null;
  const unit = planeUnitForCrs(crs);
  if (unit === "unknown") return null;
  if (unit === "degrees" && !validGeographicRing(ring)) return null;
  const local = toLocalMeters(ring, unit, unit === "degrees" ? latitudeCenter(ring) : 0);
  const area = Math.abs(shoelace(local));
  return Number.isFinite(area) && area > 0 ? area : null;
}

/** "약 12,480 ㎡". 1,000㎡ 이상은 10㎡ 단위로 반올림해 근삿값임을 드러낸다. 모르면 null. */
export function formatApproxArea(squareMeters: number | null): string | null {
  if (squareMeters === null || !Number.isFinite(squareMeters)) return null;
  if (squareMeters < 1) return "1 ㎡ 미만";
  const rounded = squareMeters >= 1000 ? Math.round(squareMeters / 10) * 10 : Math.round(squareMeters);
  return `약 ${rounded.toLocaleString("en-US")} ㎡`;
}

/** 바깥 링의 꼭짓점 수(닫는 점 제외). 읽을 수 없는 모양은 null. */
export function areaVertexCount(area: WorkArea): number | null {
  const geometry = selectableGeometry(area);
  const ring = geometry ? extractSimpleRing(geometry.polygon) : null;
  return ring ? ring.length : null;
}

/** 목록·지도가 함께 쓰는 번호와 범주색 번호(1~5). 같은 영역은 두 곳에서 같은 번호·색이다. */
export type AreaMark = { ordinal: number; swatch: number };

export function assignAreaMarks(activeAreasInOrder: readonly WorkArea[]): Map<string, AreaMark> {
  const marks = new Map<string, AreaMark>();
  activeAreasInOrder.forEach((area, index) => {
    marks.set(area.workAreaId, { ordinal: index + 1, swatch: (index % CRS_SWATCH_COUNT) + 1 });
  });
  return marks;
}

export type AreaMapShape = {
  workAreaId: string;
  /** SVG path `d`. */
  d: string;
  labelX: number;
  labelY: number;
  mark: AreaMark | null;
  archived: boolean;
  selected: boolean;
};

export type AreaMapOmitReason = "unreadable" | "unknown-unit" | "other-plane";

export type AreaMapModel = {
  width: number;
  height: number;
  shapes: AreaMapShape[];
  omitted: Array<{ workAreaId: string; reason: AreaMapOmitReason }>;
  /** 지도에 올린 영역들의 좌표계(같은 평면). 올린 것이 없으면 null. */
  planeCrs: string | null;
  scaleBar: { x1: number; x2: number; y: number; label: string } | null;
};

export const AREA_MAP_WIDTH = 600;
export const AREA_MAP_HEIGHT = 440;
const MAP_PAD = 40;

type Candidate = { area: WorkArea; ring: Array<[number, number]>; crs: string; unit: "meters" | "degrees" };

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/**
 * 영역들을 한 SVG 좌표계에 맞춘다.
 *
 * **같은 좌표계 평면의 영역끼리만** 한 지도에 올린다. 기준 평면은 고른 영역의 것이고, 고른 영역을
 * 못 그리면 가장 많은 영역이 쓰는 평면이다. 다른 평면이거나 모양을 읽을 수 없는 영역은 지도에서만
 * 빼고(`omitted`) 호출부가 개수를 알린다 — 좌표를 변환해 겹쳐 그리지 않는다.
 * 사용 중 영역은 모두 올리고, 고른 영역이 보관됨이면 그것만 점선으로 함께 올린다.
 */
export function buildAreaMap(
  areas: readonly WorkArea[],
  selectedWorkAreaId: string | null,
  marks: ReadonlyMap<string, AreaMark>,
): AreaMapModel {
  const width = AREA_MAP_WIDTH;
  const height = AREA_MAP_HEIGHT;
  const empty: AreaMapModel = { width, height, shapes: [], omitted: [], planeCrs: null, scaleBar: null };
  const included = areas.filter((area) => area.status === "ACTIVE" || area.workAreaId === selectedWorkAreaId);

  const omitted: AreaMapModel["omitted"] = [];
  const candidates: Candidate[] = [];
  for (const area of included) {
    const geometry = selectableGeometry(area);
    const ring = geometry ? extractSimpleRing(geometry.polygon) : null;
    if (!geometry || !ring) {
      omitted.push({ workAreaId: area.workAreaId, reason: "unreadable" });
      continue;
    }
    const unit = planeUnitForCrs(geometry.crs);
    if (unit === "unknown") {
      omitted.push({ workAreaId: area.workAreaId, reason: "unknown-unit" });
      continue;
    }
    if (unit === "degrees" && !validGeographicRing(ring)) {
      omitted.push({ workAreaId: area.workAreaId, reason: "unreadable" });
      continue;
    }
    candidates.push({ area, ring, crs: geometry.crs, unit });
  }
  if (candidates.length === 0) return { ...empty, omitted };

  let reference = candidates.find((candidate) => candidate.area.workAreaId === selectedWorkAreaId)?.crs;
  if (reference === undefined) {
    const counts: Array<{ crs: string; count: number }> = [];
    for (const candidate of candidates) {
      const entry = counts.find((item) => sameDisplayPlane(item.crs, candidate.crs));
      if (entry) entry.count += 1;
      else counts.push({ crs: candidate.crs, count: 1 });
    }
    reference = counts.reduce((best, item) => (item.count > best.count ? item : best)).crs;
  }
  const plotted = candidates.filter((candidate) => {
    const same = sameDisplayPlane(candidate.crs, reference);
    if (!same) omitted.push({ workAreaId: candidate.area.workAreaId, reason: "other-plane" });
    return same;
  });

  // 같은 평면이면 단위도 같다. 경위도는 올린 영역 전체에 하나의 위도 보정을 쓴다.
  const unit = plotted[0].unit;
  const allPoints = plotted.flatMap((candidate) => candidate.ring);
  const centerLat = unit === "degrees" ? latitudeCenter(allPoints) : 0;
  const local = plotted.map((candidate) => toLocalMeters(candidate.ring, unit, centerLat));
  const flat = local.flat();
  const minX = Math.min(...flat.map(([x]) => x));
  const maxX = Math.max(...flat.map(([x]) => x));
  const minY = Math.min(...flat.map(([, y]) => y));
  const maxY = Math.max(...flat.map(([, y]) => y));
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const scale = Math.min((width - 2 * MAP_PAD) / spanX, (height - 2 * MAP_PAD) / spanY);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (height - spanY * scale) / 2;
  const project = ([x, y]: readonly [number, number]): [number, number] => [
    round1(offsetX + (x - minX) * scale),
    round1(height - (offsetY + (y - minY) * scale)),
  ];

  const shapes: AreaMapShape[] = plotted.map((candidate, index) => {
    const points = local[index].map(project);
    const signed = shoelace(points);
    let cx = points.reduce((sum, [x]) => sum + x, 0) / points.length;
    let cy = points.reduce((sum, [, y]) => sum + y, 0) / points.length;
    if (Math.abs(signed) > 1e-6) {
      // 오목한 모양에서 꼭짓점 평균이 밖으로 나가지 않게 넓이 무게중심을 쓴다.
      let gx = 0;
      let gy = 0;
      for (let i = 0; i < points.length; i += 1) {
        const [x1, y1] = points[i];
        const [x2, y2] = points[(i + 1) % points.length];
        const cross = x1 * y2 - x2 * y1;
        gx += (x1 + x2) * cross;
        gy += (y1 + y2) * cross;
      }
      cx = gx / (6 * signed);
      cy = gy / (6 * signed);
    }
    return {
      workAreaId: candidate.area.workAreaId,
      d: `${points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x} ${y}`).join(" ")} Z`,
      labelX: round1(cx),
      labelY: round1(cy),
      mark: marks.get(candidate.area.workAreaId) ?? null,
      archived: candidate.area.status === "ARCHIVED",
      selected: candidate.area.workAreaId === selectedWorkAreaId,
    };
  });

  // 막대 길이는 지도 폭의 1/4 안팎을 1·2·5 계열로 고른다(표시용 어림).
  const innerMeters = (width - 2 * MAP_PAD) / scale;
  const barMeters = nativeScaleBarLength(innerMeters);
  const scaleBar = barMeters > 0
    ? {
      x1: MAP_PAD,
      x2: round1(MAP_PAD + barMeters * scale),
      y: height - 24,
      label: barMeters >= 1000 ? `${barMeters / 1000} km` : `${barMeters} m`,
    }
    : null;

  return { width, height, shapes, omitted, planeCrs: reference, scaleBar };
}

/** 고른 영역의 자료 요약 입력 — 읽지 못한 것을 0건으로 단정하지 않는다. */
export type AreaAssetsInput =
  | { status: "ready"; assets: readonly SpatialAssetCatalogItem[]; hasMore: boolean }
  | { status: "denied" | "unavailable" | "not-requested" };

export type AreaCrsVerdict = {
  kind: "none" | "single" | "mixed";
  /** 의미색. mixed는 amber(caution)이고 빨강(warning)은 쓰지 않는다 — 빨강은 실패 전용이다. */
  tone: Extract<Tone, "neutral" | "positive" | "caution">;
  label: string;
  /** 좌표계 코드들(건수가 많은 순). */
  codes: string[];
};

/**
 * DSM 좌표계 판정 — `summarizeAreaDsmCrs`의 groups만 읽는다.
 * none: DSM이 없거나 검사 전(좌표계를 읽은 DSM이 0) · single · mixed.
 * 표시 전용이다. 비교 허용은 Core가 같은 좌표계인지 다시 확인한다.
 */
export function areaCrsVerdict(dsm: AreaDsmCrs, partial = false): AreaCrsVerdict {
  const codes = dsm.groups.map((group) => group.crs);
  if (dsm.groups.length === 0) return { kind: "none", tone: "neutral", label: "좌표계 확인 전", codes };
  // 섞였다는 사실만 알린다. 같은 좌표계 자료끼리의 비교 가능 여부는 Core가 판정한다(INV-020).
  if (dsm.groups.length > 1) return { kind: "mixed", tone: "caution", label: "좌표계 섞임", codes };
  const [code] = codes;
  if (!isAnalysisCrs(code)) return { kind: "single", tone: "neutral", label: `분석 밖 좌표계 · ${code}`, codes };
  // 검사가 끝난 DSM만 좌표계를 읽는다. 일부만 읽었으면 "같은 좌표계"라고 단정하지 않는다.
  if (partial) return { kind: "single", tone: "neutral", label: `검사된 DSM은 ${code} · 일부만 확인`, codes };
  return { kind: "single", tone: "positive", label: `같은 좌표계 · ${code}`, codes };
}

export type AreaAssetSummary = {
  /** 대체된 버전(SUPERSEDED)을 뺀 등록 자료 건수(종류 무관). 읽은 페이지 안의 값이다. */
  count: number;
  /** 촬영일이 있는 날짜(YYYY-MM-DD, 오름차순, 중복 없음). */
  captureDates: string[];
  latestDate: string | null;
  /** 한 페이지(최근 50건)만 읽었다 — 더 오래된 자료가 있을 수 있다. */
  truncated: boolean;
  crs: AreaCrsVerdict;
  /** 좌표계 판정의 근거 — 대체되지 않은 DSM 중 검사가 끝나 좌표계를 읽은 수. */
  crsBasis: { dsm: number; measured: number };
};

export function summarizeAreaAssets(assets: readonly SpatialAssetCatalogItem[], hasMore: boolean): AreaAssetSummary {
  const live = assets.filter((item) => item.lifecycleState !== "SUPERSEDED");
  const dates = new Set<string>();
  for (const item of live) {
    const date = captureDateOf(item);
    if (date) dates.add(date);
  }
  const captureDates = [...dates].sort();
  const dsmCrs = summarizeAreaDsmCrs(assets, hasMore);
  const dsm = live.filter((item) => item.kind === "dsm").length;
  return {
    count: live.length,
    captureDates,
    latestDate: captureDates[captureDates.length - 1] ?? null,
    truncated: hasMore,
    crs: areaCrsVerdict(dsmCrs, dsmCrs.total < dsm),
    crsBasis: { dsm, measured: dsmCrs.total },
  };
}

/** `YYYY-MM-DD` → `MM-DD`. 형식이 다르면 원문. */
export function shortDate(date: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date.slice(5) : date;
}

/** `YYYY-MM-DD` → `9월 14일`(연도가 여러 개면 `2026년 9월 14일`). */
export function spokenDate(date: string, withYear: boolean): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return date;
  const md = `${Number(match[2])}월 ${Number(match[3])}일`;
  return withYear ? `${match[1]}년 ${md}` : md;
}

export const CAPTURE_STRIP_MAX = 8;
export const CAPTURE_STRIP_WIDTH = 300;
const STRIP_PAD = 22;
const STRIP_MIN_GAP = 34;

export type CaptureStrip = {
  /** 날짜 전체 개수(띠에는 최근 `CAPTURE_STRIP_MAX`개까지만 올린다). */
  total: number;
  points: Array<{ date: string; x: number; latest: boolean }>;
  spoken: string;
};

/**
 * 촬영 날짜 점 띠 배치. 간격은 날짜 차이에 비례하되 라벨이 겹치지 않게 최소 간격을 지킨다.
 * 오래된 날짜가 8개를 넘으면 최근 8개만 올린다(`total`로 전체 수를 따로 알린다).
 */
export function layoutCaptureStrip(dates: readonly string[]): CaptureStrip | null {
  const sorted = [...new Set(dates)].sort();
  if (sorted.length === 0) return null;
  const shown = sorted.slice(-CAPTURE_STRIP_MAX);
  const days = shown.map((date) => Date.parse(`${date}T00:00:00Z`) / 86_400_000);
  const left = STRIP_PAD;
  const right = CAPTURE_STRIP_WIDTH - STRIP_PAD;
  let xs: number[];
  if (shown.length === 1) {
    xs = [CAPTURE_STRIP_WIDTH / 2];
  } else {
    const first = days[0];
    const span = days[days.length - 1] - first;
    xs = days.map((day) => (Number.isFinite(span) && span > 0 ? left + ((day - first) / span) * (right - left) : left));
    for (let i = 1; i < xs.length; i += 1) xs[i] = Math.max(xs[i], xs[i - 1] + STRIP_MIN_GAP);
    if (xs[xs.length - 1] > right) {
      xs = shown.map((_, i) => left + (i / (shown.length - 1)) * (right - left));
    }
  }
  const years = new Set(shown.map((date) => date.slice(0, 4)));
  return {
    total: sorted.length,
    points: shown.map((date, i) => ({ date, x: round1(xs[i]), latest: i === shown.length - 1 })),
    spoken: shown.map((date) => spokenDate(date, years.size > 1)).join(", "),
  };
}
