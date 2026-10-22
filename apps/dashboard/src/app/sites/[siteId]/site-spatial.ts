import type { AnalysisListItem } from "@/lib/core-api/analysis";
import type { ExternalRelativeVolumeHistoryItem } from "@/lib/core-api/external-result-workflow";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";
import type {
  SpatialAssetCatalogItem,
  SpatialAssetCatalogPage,
} from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";
import { assetBusinessTitle, assetLifecycleLabel, capturePeriodTitle } from "@/lib/operator-language";

/**
 * 현장 상세 기본 탭(읽기 전용 공간 확인)의 순수 선택·요약 규칙.
 *
 * 서버 컴포넌트(`page.tsx`, `SiteSpatialOverview.tsx`)와 vitest가 함께 쓴다.
 * 판정·재계산은 하지 않는다 — Core가 준 목록에서 "무엇을 보여줄지"만 고른다.
 * 모르는 값은 null/unknown으로 그대로 둔다(0이나 빈 목록으로 바꾸지 않는다).
 */

/** 쿼리 범위 id의 상한 — 식별자 자리에 비정상 입력을 그대로 믿지 않는다. */
export const MAX_SCOPE_ID_LENGTH = 200;

/** 단순 폴리곤 미리보기가 다룰 상한(`display-geometry.ts`와 같은 규율). */
export const MAX_PREVIEW_VERTICES = 512;

export function parseScopeId(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_SCOPE_ID_LENGTH) return null;
  return trimmed;
}

/**
 * 선택 구역 id — 정확히 아는 구역만 받는다.
 *
 * 모르는 값이면 아는 묶임 순서대로 고른다: 관측 작업 묶임이 먼저, 분석 묶임이
 * 다음, 그 다음이 최신 등록이다. 새로 만든 빈 구역이 실제 자료가 있는 구역을
 * 가리지 않게 한다. ACTIVE이 하나도 없으면 가장 최근 보관 구역, 없으면 null이다.
 * 오류를 내지 않는다 — 이 파라미터는 보기 상태이지 명령이 아니다.
 */
export function resolveSelectedWorkAreaId(
  areas: readonly WorkArea[],
  raw: unknown,
  bindings?: {
    workOrderAreaIds?: ReadonlyArray<string> | ReadonlySet<string>;
    analysisAreaIds?: ReadonlyArray<string> | ReadonlySet<string>;
  },
): string | null {
  const wanted = parseScopeId(raw);
  if (wanted && areas.some((area) => area.workAreaId === wanted)) return wanted;
  const orderBound = new Set(bindings?.workOrderAreaIds ?? []);
  const analysisBound = new Set(bindings?.analysisAreaIds ?? []);
  const byRecency = [...areas].sort((a, b) => {
    const time = (b.createdAt ?? "").localeCompare(a.createdAt ?? "");
    return time !== 0 ? time : a.workAreaId.localeCompare(b.workAreaId);
  });
  const active = byRecency.filter((area) => area.status === "ACTIVE");
  return active.find((area) => orderBound.has(area.workAreaId))?.workAreaId
    ?? active.find((area) => analysisBound.has(area.workAreaId))?.workAreaId
    ?? active[0]?.workAreaId
    ?? byRecency[0]?.workAreaId
    ?? null;
}

/** 선택 자산 참조 — 이번에 읽은 카탈로그 페이지 안에 있을 때만 받는다. */
export function resolveSelectedAssetRef(
  page: SpatialAssetCatalogPage | null,
  raw: unknown,
): string | null {
  const wanted = parseScopeId(raw);
  if (!wanted || !page) return null;
  return page.assets.some((item) => item.assetRef === wanted) ? wanted : null;
}

export function normalizeCrs(crs: string): string {
  return crs.trim().toUpperCase();
}

/** 평면 단위 판정 — 아는 좌표계만 단언한다. 모르는 CRS는 단위를 정하지 않는다. */
export type PlaneUnit = "meters" | "degrees" | "unknown";

/** `display-geometry.ts`의 알려진 집합과 같은 목록 — 바뀌면 함께 바꾼다. */
const KNOWN_PROJECTED_CRS = new Set([
  "EPSG:5185",
  "EPSG:5186",
  "EPSG:5187",
  "EPSG:5188",
  "EPSG:5179",
]);

export function planeUnitForCrs(crs: string): PlaneUnit {
  const code = normalizeCrs(crs);
  if (code === "EPSG:4326") return "degrees";
  if (KNOWN_PROJECTED_CRS.has(code)) return "meters";
  return "unknown";
}

/** 좌표계 표기가 같은 평면(같은 단위계)인지 — 다르면 겹쳐 그리지 않는다. */
export function sameDisplayPlane(a: string, b: string): boolean {
  return normalizeCrs(a) === normalizeCrs(b);
}

/**
 * 화면에 올릴 수 있는 기하 원본 — polygon·crs가 실제로 있을 때만 돌린다.
 * 없으면 null이다(빈 지도나 가짜 좌표를 그리지 않는다).
 */
export function selectableGeometry(
  area: WorkArea,
): { polygon: Record<string, unknown>; crs: string } | null {
  const polygon = area.polygon as unknown;
  const crs = area.crs as unknown;
  if (typeof polygon !== "object" || polygon === null) return null;
  if (typeof crs !== "string" || crs.trim().length === 0) return null;
  return { polygon: polygon as Record<string, unknown>, crs };
}

/**
 * GeoJSON 단순 폴리곤의 바깥 링을 연 점열로 돌린다.
 *
 * 구멍·MultiPolygon·비정상 좌표는 null이다 — "지원되는 만큼만" 보여주지 않고
 * 막는다(구멍을 버리고 바깥 경계만 그리면 실제 범위와 다른 그림이 된다).
 */
export function extractSimpleRing(polygon: Record<string, unknown>): Array<[number, number]> | null {
  if (typeof polygon !== "object" || polygon === null) return null;
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
  if (distinct.length < 3 || distinct.length > MAX_PREVIEW_VERTICES) return null;
  return distinct;
}

/**
 * 검사된 래스터 footprint WKT를 점열로 돌린다.
 *
 * `POLYGON ((x y, ...))` 단일 링만 받는다. 다른 기하·비정상은 null이다 —
 * footprint를 어림해서 그리지 않는다.
 */
export function parseFootprintWkt(wkt: string): Array<[number, number]> | null {
  const match = /^POLYGON\s*\(\(\s*(.+?)\s*\)\)$/.exec(wkt.trim());
  if (!match) return null;
  const pairs = match[1].split(",");
  if (pairs.length < 4 || pairs.length > MAX_PREVIEW_VERTICES + 1) return null;
  const points: Array<[number, number]> = [];
  for (const pair of pairs) {
    const parts = pair.trim().split(/\s+/);
    if (parts.length < 2) return null;
    const x = Number(parts[0]);
    const y = Number(parts[1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    points.push([x, y]);
  }
  const last = points.length - 1;
  const closed = points[0][0] === points[last][0] && points[0][1] === points[last][1];
  const distinct = closed ? points.slice(0, -1) : points;
  if (distinct.length < 3) return null;
  return distinct;
}

export interface PlaneBounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * 두 링이 같은 범위인지 — 점 순서·시작점·방향이 달라도 같은 점 집합의
 * 순환이면 겹친 것으로 본다. 다르면 겹치지 않았다고만 말한다.
 */
export function ringsCoincident(
  a: ReadonlyArray<readonly [number, number]>,
  b: ReadonlyArray<readonly [number, number]>,
): boolean {
  if (a.length !== b.length || a.length === 0) return false;
  const key = (p: readonly [number, number]) => `${p[0]},${p[1]}`;
  const candidate = b.map(key);
  const reversed = [...b].reverse().map(key);
  const source = a.map(key);
  const rotations = (seq: string[]) => seq.map((_, i) => [...seq.slice(i), ...seq.slice(0, i)].join("|"));
  const targets = new Set(rotations(source));
  return rotations(candidate).some((r) => targets.has(r))
    || rotations(reversed).some((r) => targets.has(r));
}

/** 원본 좌표 평면의 실제 범위 — 숫자 꾸밈 없이 그대로 잰다. */
export function computePlaneBounds(
  boundary: ReadonlyArray<readonly [number, number]>,
  extra?: ReadonlyArray<readonly [number, number]> | null,
): PlaneBounds | null {
  const all = extra ? [...boundary, ...extra] : [...boundary];
  if (all.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of all) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(maxX) || !Number.isFinite(maxY)) return null;
  // 한 점·한 선에 가까운 범위도 0으로 나누지 않고 그린다.
  const padX = maxX === minX ? 1 : 0;
  const padY = maxY === minY ? 1 : 0;
  return { minX: minX - padX, minY: minY - padY, maxX: maxX + padX, maxY: maxY + padY };
}

/** 평면 축 수치 표기 — 미터면 소수 둘째, 도(°)면 여섯째, 모르면 원문 그대로. */
export function formatPlaneValue(value: number, unit: PlaneUnit): string {
  if (!Number.isFinite(value)) return "표시 불가";
  if (unit === "meters") {
    const rounded = Math.round(value * 100) / 100;
    return Number.isInteger(rounded) ? String(rounded) : String(rounded);
  }
  if (unit === "degrees") return String(Math.round(value * 1_000_000) / 1_000_000);
  return String(value);
}

/**
 * 좁은 자리(선택 상자 등)용 이름 — 잘라도 전체 이름은 title·aria로 함께 둔다.
 * 자른 표시에 "…"를 붙이고, 자르지 않았으면 원문을 그대로 돌린다.
 */
/**
 * 충돌하는 구역 이름에만 전체 workAreaId를 덧붙인다 — 번호를 지어내지 않는다.
 * 겹치지 않는 이름은 그대로 둔다.
 */
export function disambiguatedAreaNames(
  areas: readonly WorkArea[],
): Map<string, { label: string; disambiguated: boolean }> {
  const base = new Map<string, string>();
  const counts = new Map<string, number>();
  for (const area of areas) {
    const raw = (area as { name?: unknown }).name;
    const name = typeof raw === "string" && raw.trim().length > 0 ? raw : "이름을 확인할 수 없는 구역";
    base.set(area.workAreaId, name);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const out = new Map<string, { label: string; disambiguated: boolean }>();
  for (const area of areas) {
    const name = base.get(area.workAreaId) ?? area.workAreaId;
    const collided = (counts.get(name) ?? 0) > 1;
    out.set(area.workAreaId, { label: collided ? `${name} · ${area.workAreaId}` : name, disambiguated: collided });
  }
  return out;
}

/**
 * 파일명·revision·촬영 구간이 겹치는 자산에만 전체 assetRef를 덧붙인다.
 * 기술 식별 정보는 기존 메타데이터 상세 링크에 항상 있다.
 */
export function disambiguatedAssetHeadlines(
  assets: readonly SpatialAssetCatalogItem[],
): Map<string, { label: string; disambiguated: boolean }> {
  const keyOf = (item: SpatialAssetCatalogItem) =>
    [item.declared.fileName, item.revision, item.declared.captureStartedAt, item.declared.captureEndedAt].join("|");
  const counts = new Map<string, number>();
  for (const item of assets) counts.set(keyOf(item), (counts.get(keyOf(item)) ?? 0) + 1);
  const out = new Map<string, { label: string; disambiguated: boolean }>();
  for (const item of assets) {
    const base = `${item.declared.fileName} · revision ${item.revision}`;
    const collided = (counts.get(keyOf(item)) ?? 0) > 1;
    out.set(item.assetRef, { label: collided ? `${base} · ${item.assetRef}` : base, disambiguated: collided });
  }
  return out;
}

export function displayName(name: string, maxLength = 40): string {
  const trimmed = name.trim();
  if (trimmed.length === 0) return "이름을 확인할 수 없는 구역";
  if (trimmed.length <= maxLength || maxLength < 2) return trimmed;
  return `${trimmed.slice(0, maxLength - 1)}…`;
}

export function ordersForArea(
  orders: readonly ObservationWorkOrderView[] | null,
  workAreaId: string,
): ObservationWorkOrderView[] | null {
  if (!orders) return null;
  return orders.filter((order) => Array.isArray(order.workAreaIds) && order.workAreaIds.includes(workAreaId));
}

export function analysesForArea(
  items: readonly AnalysisListItem[] | null,
  workAreaId: string,
): AnalysisListItem[] | null {
  if (!items) return null;
  return items.filter((item) => item.workAreaId === workAreaId);
}

/** 외부 비교 이력(legacy) 중 이 구역의 행 — V2 분석 기록과 합치지 않는다. */
export function legacyRowsForArea(
  items: readonly ExternalRelativeVolumeHistoryItem[] | null,
  workAreaId: string,
): ExternalRelativeVolumeHistoryItem[] | null {
  if (!items) return null;
  return items.filter((item) => item.result?.workAreaId === workAreaId);
}

/**
 * 겹침 표시용 검사 footprint — 선택 자산 우선, 없으면 첫 측정 자산.
 *
 * 그리는 것은 `footprintWkt` 단일 링뿐이며, 구역과 같은 좌표계 표기일 때만
 * 같은 평면에 올린다(판단은 호출자가 `sameDisplayPlane`으로 한다).
 */
export function pickFootprintAsset(
  assets: readonly SpatialAssetCatalogItem[],
  selectedAssetRef: string | null,
): SpatialAssetCatalogItem | null {
  const selected = selectedAssetRef
    ? assets.find((item) => item.assetRef === selectedAssetRef) ?? null
    : null;
  if (selected?.inspection?.raster) return selected;
  return assets.find((item) => item.inspection?.raster) ?? null;
}

export interface AreaCaptureEntry {
  key: string;
  source: "asset" | "legacy";
  /** 자산 행만 값 — 선택 쿼리(`?workAreaId&assetRef`)를 만들 때 쓴다. */
  assetRef: string | null;
  reportRef?: string;
  headline: string;
  detail: string;
  capturedFrom: string | null;
  capturedTo: string | null;
  reportedAt: string | null;
}

/**
 * 선택 구역의 실제 관측 시점·출처 목록 — 새로 계산하지 않고 신고·관측 값만 옮긴다.
 * 자산 신고와 legacy 행을 한 줄에 합치지 않고 출처별로 그대로 둔다.
 * 어느 한쪽 조회가 실패해도 아는 쪽은 그대로 둔다(unknown은 별도 공지로만 둔다).
 */
export function buildAreaCaptureEntries({
  assets,
  legacyRows,
  limit = 10,
}: {
  assets: readonly SpatialAssetCatalogItem[] | null;
  legacyRows: readonly ExternalRelativeVolumeHistoryItem[] | null;
  limit?: number;
}): AreaCaptureEntry[] {
  const entries: AreaCaptureEntry[] = [];
  for (const item of assets ?? []) {
    entries.push({
      key: `asset:${item.assetRef}`,
      source: "asset",
      assetRef: item.assetRef,
      headline: assetBusinessTitle(item),
      detail: assetLifecycleLabel(item.lifecycleState),
      capturedFrom: item.declared.captureStartedAt,
      capturedTo: item.declared.captureEndedAt,
      reportedAt: item.declared.submittedAt,
    });
  }
  for (const row of legacyRows ?? []) {
    const result = row.result;
    if (!result) {
      entries.push({
        key: `legacy:${row.reportRef}`,
        source: "legacy",
        assetRef: null,
        reportRef: row.reportRef,
        headline: "외부 비교 기록",
        detail: "보관된 결과를 확인할 수 없습니다.",
        capturedFrom: null,
        capturedTo: null,
        reportedAt: null,
      });
      continue;
    }
    entries.push({
      key: `legacy:${row.reportRef}`,
      source: "legacy",
      assetRef: null,
      reportRef: row.reportRef,
      headline: `외부 비교 결과 · ${capturePeriodTitle(result.currentCapturedFrom, result.currentCapturedTo)}`,
      detail: result.baselineCapturedFrom && result.baselineCapturedTo
        ? `비교 기준 · ${capturePeriodTitle(result.baselineCapturedFrom, result.baselineCapturedTo)}`
        : "비교 기준의 관측 시점 미기재",
      capturedFrom: result.currentCapturedFrom,
      capturedTo: result.currentCapturedTo,
      reportedAt: result.reportedAt,
    });
  }
  const timeOf = (entry: AreaCaptureEntry) =>
    entry.capturedTo ?? entry.capturedFrom ?? entry.reportedAt ?? "";
  return entries
    .sort((a, b) => timeOf(b).localeCompare(timeOf(a)))
    .slice(0, Math.max(0, limit));
}
