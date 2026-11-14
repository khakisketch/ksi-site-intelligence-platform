import {
  capturePeriodTitle,
  dataKindLabel,
  isSupportedDataKind,
} from "@/lib/operator-language";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";

const EXACT_ASSET_REF_PATTERN = /^ksa-v1-[0-9a-f]{64}$/;

type SearchValue = string | string[] | undefined;
export type MaterialsSearchParams = Partial<Record<
  "workAreaId" | "cursor" | "assetRef" | "visualAAssetRef" | "visualBAssetRef" | "q" | "kind" | "state" | "info",
  SearchValue
>>;

export function exactMaterialsAssetRef(raw: unknown): string | null {
  return typeof raw === "string" && EXACT_ASSET_REF_PATTERN.test(raw) ? raw : null;
}


export function isMetadataOnly(item: SpatialAssetCatalogItem): boolean {
  return item.dataAccess === "NOT_AVAILABLE_FROM_CATALOG"
    && item.analysisStatus === "NOT_EVALUATED"
    && item.supportedActions.length === 1
    && item.supportedActions[0] === "VIEW_METADATA";
}

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
  baseline?: string | null;
  current?: string | null;
  compare?: boolean;
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
  workAreaId: string | null,
  scope: MaterialsScope = {},
): string {
  const query = new URLSearchParams({ panel: "materials" });
  if (workAreaId) query.set("workAreaId", workAreaId);
  if (scope.visualA) query.set("visualAAssetRef", scope.visualA);
  if (scope.visualB) query.set("visualBAssetRef", scope.visualB);
  if (scope.baseline) query.set("baselineAssetRef", scope.baseline);
  if (scope.current) query.set("currentAssetRef", scope.current);
  if (scope.compare || (scope.visualA && scope.visualB)) query.set("mode", "compare");
  if (scope.assetRef) query.set("assetRef", scope.assetRef);
  if (scope.q) query.set("q", scope.q);
  if (scope.kind) query.set("kind", scope.kind);
  if (scope.state) query.set("state", scope.state);
  if (scope.cursor) query.set("cursor", scope.cursor);
  if (scope.info) query.set("info", scope.info);
  return `/sites/${encodeURIComponent(siteId)}?${query.toString()}`;
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

/** 목록 필터 값 정리 — 지원하지 않는 종류·상태는 빈 값으로 둔다. */
export function normalizeCatalogFilters(input: { q?: string; kind?: string; state?: string }): CatalogFilters {
  return {
    q: (input.q ?? "").slice(0, 80),
    kind: input.kind && isSupportedDataKind(input.kind) ? input.kind : "",
    state: input.state === "inspected" || input.state === "attention" ? input.state : "",
  };
}
