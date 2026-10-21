import Link from "next/link";

import type { AnalysisListItem, AnalysisView } from "@/lib/core-api/analysis";
import type { ExternalRelativeVolumeHistoryItem } from "@/lib/core-api/external-result-workflow";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";
import type { WorkArea } from "@/lib/core-api/types";
import type {
  ExplicitComparisonResolution,
  ExplicitResultResolution,
  WorkspaceMode,
  WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";
import { SiteSpatialOverview, type SiteSpatialAssetsState } from "./SiteSpatialOverview";
import { SiteWorkspaceCompare } from "./SiteWorkspaceCompare";
import { SiteWorkspaceResults } from "./SiteWorkspaceResults";
import { analysesForArea, disambiguatedAreaNames } from "./site-spatial";

const WORKSPACE_MODES: ReadonlyArray<{ key: WorkspaceMode; label: string }> = [
  { key: "explore", label: "탐색" },
  { key: "compare", label: "비교" },
  { key: "results", label: "결과" },
];

function modeHref(
  sitePath: string,
  mode: WorkspaceMode,
  scope: { workAreaId: string | null; assetRef: string | null },
): string {
  const query = new URLSearchParams();
  if (mode !== "explore") query.set("mode", mode);
  if (scope.workAreaId) query.set("workAreaId", scope.workAreaId);
  if (mode === "explore" && scope.assetRef) query.set("assetRef", scope.assetRef);
  const search = query.toString();
  return search ? `${sitePath}?${search}` : sitePath;
}

/**
 * 현장 공간 작업공간 겉틀 (SWX-2 구조) — 탐색·비교·결과의 작업 방식만 나눈다.
 *
 * - 다섯 영역(현황·자료·분석·검토·작업·관리)과 Console 정체·머리는 그대로 둔다.
 *   이 겉틀은 현장명을 다시 쓰지 않는다(중복 제목 금지).
 * - 탐색은 기존 읽기 전용 공간 확인을 그대로 싣는다(첫 뷰포트: 실제 관측 범위).
 * - 비교는 두 개의 동등한 지도 자리 + 미지원 고지다. 동기화·정합을 지어내지 않는다.
 * - 결과는 기존 기록·근거와 한계를 새 요청보다 먼저 둔다.
 */
export function SiteWorkspaceShell({
  sitePath,
  mode,
  areas,
  areasKnown,
  orders,
  analyses,
  analysesKnown,
  analysesHasMore,
  legacy,
  legacyHasMore,
  assetsState,
  selectedWorkAreaId,
  selectedAssetRef,
  canCreateWorkOrder,
  canCreateAnalysis,
  scopeNotice,
  facts,
  baselineRequestedRef,
  currentRequestedRef,
  comparison,
  explicitResult,
  explicitDetail,
  scopedCompareHref,
}: {
  sitePath: string;
  mode: WorkspaceMode;
  areas: WorkArea[];
  areasKnown: boolean;
  orders: ObservationWorkOrderView[] | null;
  analyses: AnalysisListItem[] | null;
  analysesKnown: boolean;
  analysesHasMore: boolean;
  legacy: ExternalRelativeVolumeHistoryItem[] | null;
  legacyHasMore: boolean;
  assetsState: SiteSpatialAssetsState;
  selectedWorkAreaId: string | null;
  selectedAssetRef: string | null;
  canCreateWorkOrder: boolean;
  canCreateAnalysis: boolean;
  scopeNotice: boolean;
  facts: WorkspaceServerFacts;
  baselineRequestedRef: string | null;
  currentRequestedRef: string | null;
  comparison: ExplicitComparisonResolution | { status: "prompt" };
  explicitResult: ExplicitResultResolution | null;
  explicitDetail: AnalysisView | null;
  scopedCompareHref: string;
}) {
  const scope = { workAreaId: selectedWorkAreaId, assetRef: selectedAssetRef };
  const selected = areas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null;
  const areaLabel = selected
    ? (disambiguatedAreaNames(areas).get(selected.workAreaId)?.label ?? selected.workAreaId)
    : null;
  const areaAnalyses = selected ? analysesForArea(analyses, selected.workAreaId) : null;
  return <div className="flex flex-col gap-3">
    <nav aria-label="공간 작업 방식" className="flex flex-wrap gap-1">
      {WORKSPACE_MODES.map((option) => {
        const active = option.key === mode;
        return (
          <Link
            key={option.key}
            href={modeHref(sitePath, option.key, scope)}
            aria-current={active ? "page" : undefined}
            className={`tap-target inline-flex items-center rounded-md px-3 py-1.5 text-[13px] break-keep ${
              active ? "bg-sunk font-bold" : "text-ink-2"
            }`}
          >
            {option.label}
          </Link>
        );
      })}
    </nav>

    {mode === "explore" && (
      <SiteSpatialOverview
        sitePath={sitePath}
        areas={areas}
        areasKnown={areasKnown}
        orders={orders}
        analyses={analyses}
        analysesKnown={analysesKnown}
        analysesHasMore={analysesHasMore}
        legacy={legacy}
        legacyHasMore={legacyHasMore}
        assetsState={assetsState}
        selectedWorkAreaId={selectedWorkAreaId}
        selectedAssetRef={selectedAssetRef}
        canCreateWorkOrder={canCreateWorkOrder}
        canCreateAnalysis={canCreateAnalysis}
        scopeNotice={scopeNotice}
      />
    )}

    {mode === "compare" && areasKnown && (
      <SiteWorkspaceCompare
        sitePath={sitePath}
        areas={areas}
        selectedWorkAreaId={selectedWorkAreaId}
        assetsState={assetsState}
        baselineRequestedRef={baselineRequestedRef}
        currentRequestedRef={currentRequestedRef}
        resolution={comparison}
        canCreateAnalysis={canCreateAnalysis}
        scopedCompareHref={scopedCompareHref}
        facts={facts}
      />
    )}

    {mode === "results" && (
      <SiteWorkspaceResults
        sitePath={sitePath}
        areaLabel={areaLabel}
        areaAnalyses={areaAnalyses}
        analysesKnown={analysesKnown}
        explicitResult={explicitResult}
        explicitDetail={explicitDetail}
        canCreateAnalysis={canCreateAnalysis}
        scopedCompareHref={scopedCompareHref}
      />
    )}
  </div>;
}
