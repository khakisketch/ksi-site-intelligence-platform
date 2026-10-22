/**
 * 현장 목록 대체 타일(합성 도식)의 순수 선택·조립·검증 규칙.
 *
 * 실제 픽셀이 없을 때 카드가 빈 칸이 되지 않게, 요청자가 이미 등록한 실제
 * 기록만으로 작은 도식을 꾸민다 — 등록된 작업구역 경계 1개(원본 좌표 평면
 * 그대로)와 그 구역의 등록 자료 사실(종류·촬영 구간·등록 상태) 최대 8건이다.
 * 합성·플레이스홀더·장식 지형·타 현장 기록은 절대 쓰지 않는다.
 *
 * - 읽지 않는다(fetch 없음, Core import 없음). 서버(현장 목록 페이지)가 같은
 *   세션 BFF 집계로 읽은 기술서를 prop·컨텍스트로 내려주면, 클라이언트는
 *   `sanitizeSiteVisualTileDescriptor` 로 다시 검증한 것만 그린다.
 * - 좌표 변환을 하지 않는다. 링은 원본 평면의 숫자 그대로 SVG viewBox에
 *   올린다(화면 맞춤은 표시용 view 맞춤뿐이다). 모르는 CRS의 단위는
 *   단정하지 않는다(`planeUnitForVisualCrs` 가 unknown을 돌린다).
 * - 바이트·원본 키·서명 URL·해시·파일명·GSD·revision은 기술서에 두지 않고
 *   타일에도 표시하지 않는다. `dataAccess` 는 카탈로그 상수일 뿐 읽을 값이
 *   아니라서 참조하지 않는다.
 * - `site-spatial.ts` 의 순수 규칙과 같은 규율이다. 알려진 좌표계 집합이
 *   바뀌면 양쪽을 함께 바꾼다.
 */

import {
  capturePeriodTitle,
  dataKindLabel,
} from "@/lib/operator-language";

/** 한 번의 목록 진입에서 훑는 작업구역 수 상한 — 미리보기 경로와 같은 bound. */
export const SITE_VISUAL_TILE_MAX_AREAS = 6;

/** 구역당 읽는 카탈로그 상한(메타데이터만, 바이트 없음) — 미리보기보다 넓지 않다. */
export const SITE_VISUAL_TILE_ITEMS_PER_AREA = 50;

/** 타일에 올리는 등록 자료 사실 상한 — 넘치면 "외 N건"으로만 말한다. */
export const SITE_VISUAL_TILE_MAX_FACTS = 8;

/** 그리는 링의 꼭짓점 상한 — 미리보기 단순 폴리곤과 같은 규율. */
export const SITE_VISUAL_TILE_MAX_VERTICES = 512;

/** 한 번의 목록 렌더에서 합성을 시도하는 현장 수 상한 — 폰 전체 목록의 N+1을 막는다. */
export const SITE_VISUAL_TILE_MAX_SITES_PER_RENDER = 48;

/** 경로 세그먼트에 들어갈 수 없는 문자 — Core 호출 전에 끊는 것과 같은 집합. */
const PATH_SEGMENT = /^[^/\\?#\s\x00-\x1f\x7f@]+$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * GeoJSON 단순 폴리곤의 바깥 링을 연 점열로 돌린다.
 *
 * 구멍·MultiPolygon·비정상 좌표는 null이다 — 구멍을 버리고 바깥 경계만
 * 그리면 실제 범위와 다른 그림이 된다. 닫힘점(마지막=첫 점)은 떼고 돌린다.
 * 한 점에 겹친 고리는 그릴 모양이 없으므로 null이다(발명하지 않는다).
 */
export function extractVisualRing(polygon: unknown): Array<[number, number]> | null {
  if (!isRecord(polygon)) return null;
  if (polygon.type !== "Polygon") return null;
  const coordinates: unknown = polygon.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length !== 1) return null;
  const ring: unknown = coordinates[0];
  if (!Array.isArray(ring)) return null;
  const points: Array<[number, number]> = [];
  for (const point of ring) {
    if (!Array.isArray(point) || point.length < 2) return null;
    const [x, y] = point as unknown[];
    if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) return null;
    points.push([x, y]);
  }
  const last = points.length - 1;
  const closed = points.length >= 2 && points[0][0] === points[last][0] && points[0][1] === points[last][1];
  const distinct = closed ? points.slice(0, -1) : points;
  if (distinct.length < 3 || distinct.length > SITE_VISUAL_TILE_MAX_VERTICES) return null;
  if (distinct.every(([x, y]) => x === distinct[0][0] && y === distinct[0][1])) return null;
  return distinct;
}

export function normalizeVisualCrs(crs: string): string {
  return crs.trim().toUpperCase();
}

/** 평면 단위 판정 — 아는 좌표계만 단언한다. 모르는 CRS는 단위를 정하지 않는다. */
export type VisualPlaneUnit = "meters" | "degrees" | "unknown";

/** `site-spatial.ts` 의 알려진 집합과 같은 목록 — 바뀌면 함께 바꾼다. */
const KNOWN_PROJECTED_CRS = new Set([
  "EPSG:5185",
  "EPSG:5186",
  "EPSG:5187",
  "EPSG:5188",
  "EPSG:5179",
]);

export function planeUnitForVisualCrs(crs: string): VisualPlaneUnit {
  const code = normalizeVisualCrs(crs);
  if (code === "EPSG:4326") return "degrees";
  if (KNOWN_PROJECTED_CRS.has(code)) return "meters";
  return "unknown";
}

export interface VisualTileAreaInput {
  workAreaId: unknown;
  name: unknown;
  polygon: unknown;
  crs: unknown;
  status: unknown;
}

export interface PickedVisualTileArea {
  workAreaId: string;
  workAreaName: string;
  crs: string;
  ring: Array<[number, number]>;
}

/**
 * 합성에 쓸 구역 1개 — Core 반환 순서 안에서 첫 ACTIVE 그리기 가능 구역이다.
 * 보관 구역은 고르지 않고, 시간으로 재정렬하지 않으며, 그릴 수 없으면
 * null이다(없음이지, 다른 구역의 모양을 빌려오지 않는다).
 */
export function pickVisualTileArea(
  areas: readonly VisualTileAreaInput[],
): PickedVisualTileArea | null {
  for (const area of areas) {
    if (!isRecord(area)) continue;
    if (area.status !== "ACTIVE") continue;
    if (typeof area.workAreaId !== "string" || !PATH_SEGMENT.test(area.workAreaId)) continue;
    if (typeof area.name !== "string" || area.name.trim().length === 0) continue;
    if (typeof area.crs !== "string" || area.crs.trim().length === 0) continue;
    const ring = extractVisualRing(area.polygon);
    if (!ring) continue;
    return { workAreaId: area.workAreaId, workAreaName: area.name, crs: area.crs, ring };
  }
  return null;
}

export interface SiteVisualTileAssetFact {
  kind: string;
  captureStartedAt: string | null;
  captureEndedAt: string | null;
  captureDate: string | null;
  lifecycleState: string;
  /**
   * The registered file's OBSERVED spatial extent, in the same plane as the
   * work area. It is a rectangle the inspected raster actually covers, so
   * drawing it beside the work-area boundary shows what the data really
   * reaches. Null when the file has not been inspected, or when its extent
   * is in a different plane — then nothing is drawn, never a guess.
   */
  extentRing: Array<[number, number]> | null;
}

export interface VisualTileCatalogInput {
  siteId: unknown;
  workAreaId: unknown;
  kind: unknown;
  lifecycleState: unknown;
  declared: unknown;
  inspection?: unknown;
}

/**
 * The inspected raster's observed extent, as a rectangle in the raster's own
 * plane. Only a full-object inspection that actually measured a raster
 * carries one; anything else draws nothing.
 */
function toVisualTileExtentRing(
  inspection: unknown,
): Array<[number, number]> | null {
  if (!isRecord(inspection)) return null;
  const raster = inspection.raster;
  if (!isRecord(raster)) return null;
  const width = raster.width;
  const height = raster.height;
  const transform = raster.transform;
  if (
    typeof width !== "number" ||
    typeof height !== "number" ||
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0 ||
    !Array.isArray(transform) ||
    transform.length !== 6 ||
    !transform.every((value) => typeof value === "number" && Number.isFinite(value))
  ) {
    return null;
  }
  // The affine transform maps raster pixel corners to the observed plane.
  const [a, b, c, d, e, f] = transform as number[];
  const corners: Array<[number, number]> = [
    [0, 0],
    [width, 0],
    [width, height],
    [0, height],
  ];
  return corners.map(([px, py]) => [a * px + c * py + e, b * px + d * py + f]);
}

function toVisualTileFact(item: unknown): SiteVisualTileAssetFact | null {
  if (!isRecord(item)) return null;
  if (typeof item.kind !== "string" || item.kind.trim().length === 0 || item.kind.length > 64) return null;
  if (typeof item.lifecycleState !== "string" || item.lifecycleState.length > 32) return null;
  if (!isRecord(item.declared)) return null;
  const { captureStartedAt, captureEndedAt, captureDate } = item.declared;
  for (const moment of [captureStartedAt, captureEndedAt, captureDate]) {
    if (moment !== null && moment !== undefined && typeof moment !== "string") return null;
  }
  return {
    kind: item.kind,
    captureStartedAt: (captureStartedAt as string | null) ?? null,
    captureEndedAt: (captureEndedAt as string | null) ?? null,
    captureDate: (captureDate as string | null) ?? null,
    lifecycleState: item.lifecycleState,
    extentRing: toVisualTileExtentRing(item.inspection),
  };
}

/**
 * 고른 구역의 카탈로그 페이지에서 타일에 올릴 사실만 추린다.
 *
 * Core 반환 순서를 유지하고 시간으로 다시 정렬하지 않는다. 앞의 최대 8건만
 * 올리고 나머지는 건수로만 말한다(조용히 합치거나 버리지 않는다).
 * 묶임이 어긋난 항목은 세지 않는다. 올릴 게 하나도 없으면 null이다.
 */
export function toVisualTileFacts(
  siteId: string,
  workAreaId: string,
  assets: readonly VisualTileCatalogInput[],
): { surfaced: SiteVisualTileAssetFact[]; scanned: number } | null {
  if (!Array.isArray(assets)) return null;
  const bound: SiteVisualTileAssetFact[] = [];
  for (const item of assets) {
    if (!isRecord(item)) continue;
    if (item.siteId !== siteId || item.workAreaId !== workAreaId) continue;
    const fact = toVisualTileFact(item);
    if (fact) bound.push(fact);
  }
  if (bound.length === 0) return null;
  return { surfaced: bound.slice(0, SITE_VISUAL_TILE_MAX_FACTS), scanned: bound.length };
}

export interface SiteVisualTileDescriptor {
  available: true;
  siteId: string;
  workAreaId: string;
  workAreaName: string;
  /** 등록된 원본 좌표계 표기 — 변환하지 않고 이 평면 그대로 그린다. */
  crs: string;
  /** 등록된 경계 링(원본 숫자 그대로, 닫힘점 제외). */
  ring: Array<[number, number]>;
  vertexCount: number;
  /** 올린 등록 자료 사실 — 최대 8건, Core 반환 순서. */
  facts: SiteVisualTileAssetFact[];
  /** 고른 구역에서 읽은 카탈로그 건수(≤50). */
  scannedAssetCount: number;
  /** 카탈로그에 더 있으면 true — 전체 건수를 단정하지 않는다. */
  hasMoreAssets: boolean;
  /** 타일이 여는 정확한 현장 주소(구역 고정, 바이트·서명 없음). */
  siteHref: string;
}

export type SiteVisualTileLookup =
  | SiteVisualTileDescriptor
  | { available: false; reason: "no-geometry" | "no-records" | "unknown" };

/**
 * BFF 집계(서버)가 읽은 구역·카탈로그 사실을 표시 기술서로 접는다.
 * 파일명·revision·해시·바이트 자격은 담지 않는다 — 타일은 모양+사실만 말한다.
 */
export function buildSiteVisualTileDescriptor(input: {
  siteId: string;
  area: PickedVisualTileArea;
  facts: SiteVisualTileAssetFact[];
  scannedAssetCount: number;
  hasMoreAssets: boolean;
}): SiteVisualTileDescriptor {
  const { siteId, area, facts, scannedAssetCount, hasMoreAssets } = input;
  const siteHref =
    `/sites/${encodeURIComponent(siteId)}` +
    `?workAreaId=${encodeURIComponent(area.workAreaId)}`;
  return {
    available: true,
    siteId,
    workAreaId: area.workAreaId,
    workAreaName: area.workAreaName,
    crs: area.crs,
    ring: area.ring,
    vertexCount: area.ring.length,
    facts,
    scannedAssetCount,
    hasMoreAssets,
    siteHref,
  };
}

/**
 * 합성 기술서의 런타임 바인딩 검증 — 받은 URL을 믿지 않고, 검증된 식별자로
 * 기대 경로를 로컬에서 다시 조립해 받은 값과 비교한다. 바이트 경로·서명
 * URL·원본 키·외부 리다이렉트는 구조상 들어올 수 없다. 실패하면 null이다.
 */
export function sanitizeSiteVisualTileDescriptor(
  raw: unknown,
  siteId: string,
): SiteVisualTileDescriptor | null {
  if (!isRecord(raw) || raw.available !== true) return null;
  const workAreaId = raw.workAreaId;
  if (typeof siteId !== "string" || !PATH_SEGMENT.test(siteId)) return null;
  if (typeof workAreaId !== "string" || !PATH_SEGMENT.test(workAreaId)) return null;
  if (raw.siteId !== siteId || raw.workAreaId !== workAreaId) return null;
  if (typeof raw.workAreaName !== "string" || raw.workAreaName.trim().length === 0) return null;
  if (typeof raw.crs !== "string" || raw.crs.trim().length === 0 || raw.crs.length > 64) return null;
  const ring: unknown = raw.ring;
  if (!Array.isArray(ring) || ring.length < 3 || ring.length > SITE_VISUAL_TILE_MAX_VERTICES) return null;
  const points: Array<[number, number]> = [];
  for (const point of ring) {
    if (!Array.isArray(point) || point.length < 2) return null;
    const [x, y] = point as unknown[];
    if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) return null;
    points.push([x, y]);
  }
  if (points.every(([x, y]) => x === points[0][0] && y === points[0][1])) return null;
  if (raw.vertexCount !== points.length) return null;
  const facts: unknown = raw.facts;
  if (!Array.isArray(facts) || facts.length === 0 || facts.length > SITE_VISUAL_TILE_MAX_FACTS) return null;
  const checkedFacts: SiteVisualTileAssetFact[] = [];
  for (const item of facts) {
    // 기술서의 사실은 납작하다(촬영 구간이 최상위) — 카탈로그의 declared
    // 둥지와 헷갈리지 않게 여기서 직접 확인한다.
    if (!isRecord(item)) return null;
    const { kind, captureStartedAt, captureEndedAt, captureDate, lifecycleState } = item;
    if (typeof kind !== "string" || kind.trim().length === 0 || kind.length > 64) return null;
    if (typeof lifecycleState !== "string" || lifecycleState.length > 32) return null;
    for (const moment of [captureStartedAt, captureEndedAt, captureDate]) {
      if (moment !== null && typeof moment !== "string") return null;
    }
    let extentRing: Array<[number, number]> | null = null;
    const rawExtent = item.extentRing;
    if (rawExtent !== null && rawExtent !== undefined) {
      if (!Array.isArray(rawExtent) || rawExtent.length < 3 || rawExtent.length > 8) return null;
      const ring: Array<[number, number]> = [];
      for (const point of rawExtent) {
        if (!Array.isArray(point) || point.length < 2) return null;
        const [x, y] = point as unknown[];
        if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) {
          return null;
        }
        ring.push([x, y]);
      }
      extentRing = ring;
    }
    checkedFacts.push({
      kind,
      captureStartedAt: captureStartedAt as string | null,
      captureEndedAt: captureEndedAt as string | null,
      captureDate: captureDate as string | null,
      lifecycleState,
      extentRing,
    });
  }
  if (!Number.isSafeInteger(raw.scannedAssetCount) || (raw.scannedAssetCount as number) < checkedFacts.length) return null;
  if (typeof raw.hasMoreAssets !== "boolean") return null;
  const expectedSiteHref =
    `/sites/${encodeURIComponent(siteId)}` +
    `?workAreaId=${encodeURIComponent(workAreaId)}`;
  if (raw.siteHref !== expectedSiteHref) return null;
  return {
    available: true,
    siteId,
    workAreaId,
    workAreaName: raw.workAreaName,
    crs: raw.crs,
    ring: points,
    vertexCount: points.length,
    facts: checkedFacts,
    scannedAssetCount: raw.scannedAssetCount as number,
    hasMoreAssets: raw.hasMoreAssets,
    siteHref: expectedSiteHref,
  };
}

/** 타일 한 줄 요약 — 첫 사실의 종류·촬영 구간 + 나머지는 건수로만 말한다. */
export function visualTileFactLine(tile: SiteVisualTileDescriptor): string {
  const [first] = tile.facts;
  const head = `${dataKindLabel(first.kind)} · ${capturePeriodTitle(
    first.captureStartedAt,
    first.captureEndedAt,
    { captureDate: first.captureDate },
  )}`;
  if (tile.hasMoreAssets) return `${head} 외 더 있음`;
  const remaining = tile.scannedAssetCount - 1;
  if (remaining > 0) return `${head} 외 ${remaining}건`;
  return head;
}

/** 타일 출처 줄 — 어느 구역의 등록 범위와 몇 건의 등록 자료인지 말한다. */
export function visualTileCountLine(tile: SiteVisualTileDescriptor): string {
  const total = tile.hasMoreAssets
    ? `${tile.scannedAssetCount}건 이상`
    : `${tile.scannedAssetCount}건`;
  return `${tile.workAreaName} · 등록 자료 ${total}`;
}

/** 타일의 접근성 이름 — 사진이 아님을 먼저 밝히고 실제 기록을 이름 붙인다. */
export function visualTileAccessibleName(tile: SiteVisualTileDescriptor): string {
  return `범위 도식 열기 (사진 아님). ${visualTileCountLine(tile)}. ${visualTileFactLine(tile)}`;
}
