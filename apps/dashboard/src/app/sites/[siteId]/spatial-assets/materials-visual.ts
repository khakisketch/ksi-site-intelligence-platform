import {
  capturePeriodTitle,
  dataKindLabel,
} from "@/lib/operator-language";
import { isSupportedDataKind } from "@/lib/operator-language";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";

/**
 * 자료 시각 탐색의 순수 선택·주소 규칙 (INV-020/051/053).
 *
 * - 판정·재계산을 하지 않는다. Core가 준 카탈로그 순서·사실에서만 고른다.
 * - 명시 참조(visualA/visualB/legacy assetRef)는 정확한 일치가 있을 때만
 *   쓴다. 모양이 어긋나거나 목록에 없으면 그쪽만 비우고 이유를 둔다 —
 *   조용히 다른 자료로 바꾸지 않는다.
 * - 기본 미리보기는 목록의 첫 자료(결정적 허용 카탈로그 첫 항목)다.
 *   두 번째(B)는 미리 고르지 않는다 — 사용자가 직접 고른다.
 * - 비교는 같은 화면에 나란히 두는 독립 보기다. 동기화·정합·수치 비교를
 *   주장하지 않으며, 새 비교 의미(공유 카메라·swipe)를 만들지 않는다.
 */

const EXACT_ASSET_REF_PATTERN = /^ksa-v1-[0-9a-f]{64}$/;

/** 미리보기 픽셀을 둘 수 있는 종류 — 정사영상·DSM만 실제 화면으로 둔다. */
export function isViewableRasterKind(kind: string): boolean {
  return kind === "ortho" || kind === "dsm";
}

/**
 * 레일 한 줄용 짧은 종류 이름 — 목록 첫 화면의 사람 말이다. 모르는 종류는
 * 중립 문구로 두고, 원문은 정보 펼침이 맡는다.
 */
export function shortKindLabel(kind: string): string {
  if (kind === "ortho") return "정사영상";
  if (kind === "dsm") return "DSM";
  if (kind === "dtm") return "DTM";
  if (kind === "point_cloud") return "포인트 클라우드";
  if (kind === "camera_poses") return "카메라 자세";
  if (kind === "mesh") return "Mesh";
  if (kind === "tiles_3d") return "3D 타일";
  if (kind === "report") return "보고서";
  return "자료 종류 확인 필요";
}

type RawRef = { kind: "absent" } | { kind: "invalid" } | { kind: "single"; value: string };

function parseVisualRef(raw: unknown): RawRef {
  if (raw === undefined) return { kind: "absent" };
  if (typeof raw !== "string" || !EXACT_ASSET_REF_PATTERN.test(raw)) return { kind: "invalid" };
  return { kind: "single", value: raw };
}

export interface VisualSelection {
  sideA: SpatialAssetCatalogItem | null;
  sideB: SpatialAssetCatalogItem | null;
  /** 양쪽이 모두 정해지고 서로 다를 때만 "compare" — 그 밖은 한 장 보기다. */
  mode: "single" | "compare";
  /** 기본값(목록 첫 자료)으로 A를 둔 경우 true — 최신 단언이 아니다. */
  defaultedA: boolean;
  /** 옛 assetRef를 A로 읽은 경우 true. */
  legacyMapped: boolean;
  notices: {
    invalidA: boolean;
    invalidB: boolean;
    foreignA: boolean;
    foreignB: boolean;
    samePair: boolean;
  };
}

/**
 * 시각 선택 해소 — 후보 풀은 이미 범위 확인된 목록 순서 그대로 둔다.
 * legacyRef는 호출자가 모양 검증까지 마친 단일 값(또는 undefined)이다.
 */
export function resolveVisualSelection(input: {
  pool: readonly SpatialAssetCatalogItem[];
  visualARaw: unknown;
  visualBRaw: unknown;
  legacyRef?: string | undefined;
}): VisualSelection {
  const pool = [...input.pool];
  const byRef = new Map(pool.map((item) => [item.assetRef, item]));
  const aParsed = parseVisualRef(input.visualARaw);
  const bParsed = parseVisualRef(input.visualBRaw);
  const notices = { invalidA: false, invalidB: false, foreignA: false, foreignB: false, samePair: false };

  let sideA: SpatialAssetCatalogItem | null = null;
  let legacyMapped = false;
  if (aParsed.kind === "invalid") {
    notices.invalidA = true;
  } else if (aParsed.kind === "single") {
    const found = byRef.get(aParsed.value) ?? null;
    if (found) sideA = found;
    else notices.foreignA = true;
  } else if (input.legacyRef) {
    const found = byRef.get(input.legacyRef) ?? null;
    if (found) {
      sideA = found;
      legacyMapped = true;
    } else {
      notices.foreignA = true;
    }
  }
  if (!sideA && aParsed.kind === "absent" && !input.legacyRef) {
    sideA = pool[0] ?? null;
  }

  let sideB: SpatialAssetCatalogItem | null = null;
  if (bParsed.kind === "invalid") {
    notices.invalidB = true;
  } else if (bParsed.kind === "single") {
    const found = byRef.get(bParsed.value) ?? null;
    if (found) sideB = found;
    else notices.foreignB = true;
  }

  if (sideA && sideB && sideA.assetRef === sideB.assetRef) {
    notices.samePair = true;
    sideB = null;
  }

  return {
    sideA,
    sideB,
    mode: sideA && sideB ? "compare" : "single",
    defaultedA: aParsed.kind === "absent" && !input.legacyRef && sideA !== null,
    legacyMapped,
    notices,
  };
}

/**
 * 관측 묶음 grouping — Core가 준 관측 기록 ID 순서 그대로 둔다.
 * 시간으로 재정열하지 않고, 묶음 식별자가 없는 항목은 따로 모은다.
 */
export function groupAssetsByObservation(
  items: readonly SpatialAssetCatalogItem[],
): Array<{ epochId: string; items: SpatialAssetCatalogItem[] }> {
  const groups: Array<{ epochId: string; items: SpatialAssetCatalogItem[] }> = [];
  const index = new Map<string, SpatialAssetCatalogItem[]>();
  for (const item of items) {
    const key = typeof item.observationEpochId === "string" && item.observationEpochId.length > 0
      ? item.observationEpochId
      : "";
    let list = index.get(key);
    if (!list) {
      list = [];
      index.set(key, list);
      groups.push({ epochId: key, items: list });
    }
    list.push(item);
  }
  return groups;
}

/** 묶음 안의 촬영 구간이 모두 같을 때만 한 줄로 말한다. 다르면 항목별로만 둔다. */
export function observationGroupDateLine(items: readonly SpatialAssetCatalogItem[]): string | null {
  const lines = items.map((item) =>
    capturePeriodTitle(item.declared.captureStartedAt, item.declared.captureEndedAt, {
      captureDate: item.declared.captureDate ?? null,
    }));
  const first = lines[0];
  if (first === undefined) return null;
  return lines.every((line) => line === first) ? first : null;
}

export interface MaterialsScope {
  visualA?: string | null;
  visualB?: string | null;
  /** 옛 assetRef 진입의 왕복용 — 새 선택에는 싣지 않는다. */
  assetRef?: string | null;
  cursor?: string | null;
  q?: string;
  kind?: string;
  state?: string;
  /** 정보 펼침 열림 — "1"일 때만 싣는다. */
  info?: string | null;
}

/**
 * 자료 탐색 주소 — 같은 일관 키(workAreaId·visualA/B·assetRef·필터·cursor·info만)
 * 쓴다. 새 비교 의미·개방 리다이렉트를 만들지 않는다.
 */
export function materialsHref(
  siteId: string,
  workAreaId: string,
  scope: MaterialsScope = {},
): string {
  const query = new URLSearchParams({ workAreaId });
  if (scope.visualA) query.set("visualAAssetRef", scope.visualA);
  if (scope.visualB) query.set("visualBAssetRef", scope.visualB);
  if (scope.assetRef) query.set("assetRef", scope.assetRef);
  if (scope.q) query.set("q", scope.q);
  if (scope.kind) query.set("kind", scope.kind);
  if (scope.state) query.set("state", scope.state);
  if (scope.cursor) query.set("cursor", scope.cursor);
  if (scope.info) query.set("info", scope.info);
  return `/sites/${encodeURIComponent(siteId)}/spatial-assets?${query.toString()}`;
}

/** 목록 필터 — Core 카탈로그는 정렬·검색 계약을 따로 받지 않으므로, 불러온
 *  페이지 안에서만 적용한다. */
export interface CatalogFilters {
  q: string;
  kind: string;
  state: "" | "inspected" | "attention";
}

/** 검사 실패와 검사 전을 한 칸에 둔다 — 둘 다 아직 쓸 수 있다고 말할 수 없다. */
export function needsCatalogAttention(item: SpatialAssetCatalogItem): boolean {
  return item.inspection.state === "FAILED"
    || item.inspection.outcome === "REJECTED"
    || item.inspection.outcome === null;
}

/**
 * 불러온 페이지 안 필터 — 대상은 호출자가 이미 범위 확인한 목록이다.
 * 필터가 빗나가도 선택 미리보기를 바꾸지 않는다(호출자가 분리한다).
 */
export function applyCatalogFilters(
  items: readonly SpatialAssetCatalogItem[],
  filters: CatalogFilters,
): SpatialAssetCatalogItem[] {
  return items.filter((item) => {
    if (filters.kind && item.kind !== filters.kind) return false;
    if (filters.state === "inspected" && item.inspection.outcome !== "MEASURED") return false;
    if (filters.state === "attention" && !needsCatalogAttention(item)) return false;
    if (filters.q) {
      const haystack = `${item.declared.fileName} · ${dataKindLabel(item.kind)} · ${shortKindLabel(item.kind)}`.toLowerCase();
      if (!haystack.includes(filters.q.toLowerCase())) return false;
    }
    return true;
  });
}

export function catalogCounts(items: readonly SpatialAssetCatalogItem[]): {
  total: number;
  inspected: number;
  attention: number;
} {
  return {
    total: items.length,
    inspected: items.filter((item) => item.inspection.outcome === "MEASURED").length,
    attention: items.filter(needsCatalogAttention).length,
  };
}

/** 목록 필터 값 정리 — 지원하지 않는 종류·상태는 빈 값으로 둔다. */
export function normalizeCatalogFilters(input: { q?: string; kind?: string; state?: string }): CatalogFilters {
  return {
    q: (input.q ?? "").slice(0, 80),
    kind: input.kind && isSupportedDataKind(input.kind) ? input.kind : "",
    state: input.state === "inspected" || input.state === "attention" ? input.state : "",
  };
}
