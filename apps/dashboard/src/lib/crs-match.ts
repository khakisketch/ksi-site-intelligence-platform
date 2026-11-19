import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import { isAnalysisCrs } from "@/lib/geo/known-crs";
import { koreanCalendarDate } from "@/lib/observation-default-name";

/**
 * 같은 구역에 이미 올린 DSM이 어떤 좌표계인지 모으고, 새로 올릴 파일과 대조한다.
 *
 * 표시 전용이다. 비교·체적을 허용할지는 Core가 같은 좌표계인지 다시 확인해 판정한다(INV-020).
 * 여기서는 자동 변환도, 좌표계가 같다는 보증도 하지 않는다.
 */

export type CrsGroup = {
  crs: string;
  count: number;
  /** 촬영일(`YYYY-MM-DD`, 한국 달력 기준). 모르면 null. */
  firstDate: string | null;
  lastDate: string | null;
};

export type AreaDsmCrs = {
  /** 건수가 많은 좌표계부터, 같으면 코드 순. */
  groups: readonly CrsGroup[];
  /** 좌표계를 읽은 DSM 수(groups의 count 합). */
  total: number;
  /** 한 페이지(최근 50건)만 보았다. 더 오래된 자료가 있을 수 있다. */
  truncated: boolean;
};

export type CrsMatchVerdict = "first" | "same" | "different" | "mixed" | "not-analysis";

export type CrsMatch = {
  fileCrs: string;
  verdict: CrsMatchVerdict;
  groups: ReadonlyArray<CrsGroup & { same: boolean }>;
  total: number;
  sameCount: number;
  truncated: boolean;
};

export function normalizeCrs(value: string | null | undefined): string | null {
  const code = value?.trim().toUpperCase();
  return code ? code : null;
}

function captureDateOf(item: SpatialAssetCatalogItem): string | null {
  const { captureDate, captureStartedAt } = item.declared;
  if (captureDate) return captureDate;
  if (!captureStartedAt) return null;
  const moment = new Date(captureStartedAt);
  return Number.isNaN(moment.getTime()) ? null : koreanCalendarDate(moment);
}

/** 대체된 버전과 검사가 끝나지 않은 자료는 좌표계 근거로 쓰지 않는다. */
export function summarizeAreaDsmCrs(assets: readonly SpatialAssetCatalogItem[], hasMore: boolean): AreaDsmCrs {
  const byCrs = new Map<string, { count: number; dates: string[] }>();
  for (const item of assets) {
    if (item.kind !== "dsm" || item.lifecycleState === "SUPERSEDED") continue;
    if (item.inspection.outcome !== "MEASURED") continue;
    const crs = normalizeCrs(item.inspection.raster?.observedCrsIdentifier);
    if (!crs) continue;
    const entry = byCrs.get(crs) ?? { count: 0, dates: [] };
    entry.count += 1;
    const date = captureDateOf(item);
    if (date) entry.dates.push(date);
    byCrs.set(crs, entry);
  }
  const groups = [...byCrs.entries()]
    .map(([crs, { count, dates }]): CrsGroup => {
      const sorted = [...dates].sort();
      return { crs, count, firstDate: sorted[0] ?? null, lastDate: sorted[sorted.length - 1] ?? null };
    })
    .sort((a, b) => b.count - a.count || a.crs.localeCompare(b.crs));
  return { groups, total: groups.reduce((sum, group) => sum + group.count, 0), truncated: hasMore };
}

/** 파일의 좌표계를 모르거나 구역 자료를 읽지 못했으면 null(화면은 아무것도 보태지 않는다). */
export function matchFileToArea(fileCrs: string | null | undefined, area: AreaDsmCrs | null | undefined): CrsMatch | null {
  const crs = normalizeCrs(fileCrs);
  if (!crs || !area) return null;
  const groups = area.groups.map((group) => ({ ...group, same: group.crs === crs }));
  const sameCount = groups.filter((group) => group.same).reduce((sum, group) => sum + group.count, 0);
  const verdict: CrsMatchVerdict = !isAnalysisCrs(crs)
    ? "not-analysis"
    : area.total === 0
      ? "first"
      : sameCount === area.total
        ? "same"
        : sameCount === 0
          ? "different"
          : "mixed";
  return { fileCrs: crs, verdict, groups, total: area.total, sameCount, truncated: area.truncated };
}

/** 한 화면 안에서 좌표계마다 같은 색 번호(1~5)를 준다. 같은 색끼리만 비교된다는 뜻으로 읽힌다. */
export const CRS_SWATCH_COUNT = 5;

export function assignCrsSwatches(codes: readonly string[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const code of codes) {
    if (!out.has(code)) out.set(code, (out.size % CRS_SWATCH_COUNT) + 1);
  }
  return out;
}
