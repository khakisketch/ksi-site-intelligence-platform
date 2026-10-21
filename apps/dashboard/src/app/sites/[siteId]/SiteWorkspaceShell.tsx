import Link from "next/link";

import type { AnalysisListItem, AnalysisView } from "@/lib/core-api/analysis";
import type { ExternalRelativeVolumeHistoryItem } from "@/lib/core-api/external-result-workflow";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";
import type { WorkArea } from "@/lib/core-api/types";
import type {
  ExplicitComparisonResolution,
  ExplicitResultResolution,
  OrdinaryEntryResolution,
  WorkspaceMode,
  WorkspaceObservationFact,
  WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";
import {
  representativeFacts,
  workspaceCaptureLine,
} from "@/lib/site-workspace-entry";
import { capturePeriodTitle } from "@/lib/operator-language";
import { formatKoreanDate } from "@/lib/datetime";
import { SiteSpatialOverview, type SiteSpatialAssetsState } from "./SiteSpatialOverview";
import { SiteWorkspaceCompare } from "./SiteWorkspaceCompare";
import { SiteWorkspaceResults } from "./SiteWorkspaceResults";
import { analysesForArea, disambiguatedAreaNames } from "./site-spatial";

const WORKSPACE_MODES: ReadonlyArray<{ key: WorkspaceMode; label: string }> = [
  { key: "explore", label: "탐색" },
  { key: "compare", label: "비교" },
  { key: "results", label: "결과" },
];

function entryCaptureLine(fact: WorkspaceObservationFact): string {
  return workspaceCaptureLine(fact, {
    intervalTitle: (startedAt, endedAt) => capturePeriodTitle(startedAt, endedAt),
    calendarDate: (date) => formatKoreanDate(date),
  });
}

function viewReasonLine(reason: string | null): string | null {
  if (reason === "NO_DISPLAY_READY_VERSION") return "표시용 출력의 봉인이 끝나지 않았습니다.";
  if (reason === "DISPLAY_NOT_CONFIGURED") return "표시 절차가 설정되지 않았습니다. 담당자에게 확인하세요.";
  return null;
}

/**
 * 일반 진입 선택 상태 — 서버의 `entryDefault` 사유를 사람 말로 옮긴다.
 * 이유 코드 자체는 감추지 않고, 서버 설명 원문은 펼침에 둔다.
 * 이 패널은 "최신"을 스스로 단언하지 않는다 — 서버가 고른 경우에만 그 규칙을 밝힌다.
 */
function SiteWorkspaceEntryPanel({
  sitePath,
  workAreaId,
  ordinaryEntry,
  projectionState,
  facts,
  canCreateWorkOrder,
  transitional,
}: {
  sitePath: string;
  workAreaId: string | null;
  ordinaryEntry: OrdinaryEntryResolution;
  projectionState: "ready" | "denied" | "unavailable" | "not-requested";
  facts: WorkspaceServerFacts;
  canCreateWorkOrder: boolean;
  /** 서버 기본이 없어 전이 선택을 보여줄 때 true — 기본인 척하지 않는다. */
  transitional: boolean;
}) {
  if (projectionState === "denied") {
    return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[13px] font-bold">관측 목록을 조회할 권한이 없습니다</p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">담당자에게 조회 권한을 요청하세요. 권한이 없어 빈 목록으로 단정하지 않습니다.</p>
    </section>;
  }
  if (projectionState === "unavailable" || projectionState === "not-requested") {
    return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[13px] font-bold">관측 목록을 확인할 수 없습니다</p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">잠시 후 다시 확인하세요. 확인할 수 없는 동안 기본 관측을 정하지 않았습니다.</p>
    </section>;
  }
  if (ordinaryEntry.status === "ready") {
    return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[13px] font-bold">보여주는 관측 · {entryCaptureLine(ordinaryEntry.observation)}</p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        표시 가능한 관측 중 실제 촬영 구간이 가장 나중인 관측입니다. 등록 순서로 고르지 않았습니다.
      </p>
      {ordinaryEntry.observation.newerRevisionPending && (
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">새로 제출된 버전이 있어 표시용 출력을 확인 중입니다. 지금 보는 버전을 바꾸지 않았습니다.</p>
      )}
      {facts.entryDefault?.detail && (
        <details className="mt-1 text-[12px] text-ink-2">
          <summary className="tap-target cursor-pointer">서버 결정 근거 확인</summary>
          <p className="mt-1">사유 코드 · {facts.entryDefault.reason}</p>
          <p className="mt-1 break-words">서버 설명 · {facts.entryDefault.detail}</p>
        </details>
      )}
    </section>;
  }
  const reason = ordinaryEntry.reason;
  if (ordinaryEntry.defaultNotOnPage) {
    return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[13px] font-bold">서버가 정한 기본 관측이 조회된 목록에 없습니다</p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">다음 페이지를 확인하거나 담당자에게 문의하세요. 다른 관측으로 바꾸지 않았습니다.</p>
    </section>;
  }
  if (reason === "NO_OBSERVATIONS") {
    return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[13px] font-bold">등록된 관측이 없습니다</p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        {canCreateWorkOrder && workAreaId
          ? "이 구역의 외부 관측이 등록되면 이 자리에서 확인할 수 있습니다."
          : "외부 관측 등록은 담당자와 확인하세요."}
      </p>
      {canCreateWorkOrder && workAreaId && (
        <p className="mt-2"><Link href={`${sitePath}/observations/new?workAreaId=${encodeURIComponent(workAreaId)}`} className="btn">관측 자료 등록</Link></p>
      )}
    </section>;
  }
  if (reason === "NO_VIEW_AVAILABLE_OBSERVATION") {
    const scopeFacts = facts.observations.filter((item) => item.workAreaId === workAreaId);
    const reasons = [...new Set(scopeFacts.map((item) => item.viewUnavailableReason))];
    const lines = reasons.map(viewReasonLine).filter((line): line is string => line !== null);
    const observationCount = new Set(scopeFacts.map((item) => item.observationEpochId)).size;
    return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[13px] font-bold">표시용 파생물이 아직 준비되지 않았습니다</p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        {observationCount > 0
          ? `확인된 관측은 ${observationCount}건입니다. `
          : "확인된 관측이 없습니다. "}
        {"파일을 보려면 아래의 구역 자료 준비에서 직접 요청하세요. 준비가 끝나면 실제 파일을 받을 수 있습니다."}
      </p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        {lines.length > 0 ? lines.join(" ") : "언제 준비되는지는 담당자에게 확인하세요."}
      </p>
      {transitional && (
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">위에는 확인된 측정 범위를 표시합니다. 서버가 정한 기본 관측이 아닙니다.</p>
      )}
      <p className="mt-2 flex flex-wrap gap-x-3 text-[12px]">
        <Link href={`${sitePath}/spatial-assets${workAreaId ? `?workAreaId=${encodeURIComponent(workAreaId)}` : ""}`} className="tap-target underline">자료 목록 보기</Link>
        <Link href={`${sitePath}/spatial-data-requests${workAreaId ? `?workAreaId=${encodeURIComponent(workAreaId)}` : ""}`} className="tap-target underline">구역 자료 준비</Link>
      </p>
    </section>;
  }
  if (reason === "NO_EXACT_CAPTURE_CANDIDATE") {
    return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[13px] font-bold">기본 관측을 정하지 않았습니다</p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        표시 가능한 관측은 있지만 실제 촬영 구간이 확인된 관측이 없어, 등록 순서로 대신 고르지 않았습니다.
        날짜만 아는 관측·시점 미상 관측은 비교에서 직접 고르세요.
      </p>
      {workAreaId && (
        <p className="mt-2"><Link href={`${sitePath}?mode=compare&workAreaId=${encodeURIComponent(workAreaId)}`} className="tap-target text-[12px] underline">비교에서 직접 고르기</Link></p>
      )}
    </section>;
  }
  if (reason === "CAPTURE_TIE_AMBIGUOUS") {
    const tiedEpochs = ordinaryEntry.tiedObservationEpochIds;
    const tiedFacts = workAreaId
      ? representativeFacts(facts, workAreaId).filter((item) => tiedEpochs.includes(item.observationEpochId))
      : [];
    return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[13px] font-bold">같은 촬영 구간의 관측이 2개 이상 있어 자동으로 고르지 않았습니다</p>
      {tiedFacts.length > 0 && (
        <ul className="mt-1 divide-y divide-line">
          {tiedFacts.map((item) => (
            <li key={item.assetRef} className="py-1 text-[12px] text-ink-2">{entryCaptureLine(item)} · 등록 버전 {item.revision}</li>
          ))}
        </ul>
      )}
      {workAreaId && (
        <p className="mt-2"><Link href={`${sitePath}?mode=compare&workAreaId=${encodeURIComponent(workAreaId)}`} className="tap-target text-[12px] underline">비교에서 직접 고르기</Link></p>
      )}
    </section>;
  }
  return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
    <p className="text-[13px] font-bold">기본 관측을 정하지 않았습니다</p>
    <p className="mt-1 text-[12.5px] leading-5 text-ink-2">관측 목록을 확인할 수 없어 기본 관측을 정하지 않았습니다. 잠시 후 다시 확인하세요.</p>
  </section>;
}

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
  ordinaryEntry,
  projectionState,
  workspaceHasMore,
  transitionalSelection,
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
  ordinaryEntry: OrdinaryEntryResolution;
  projectionState: "ready" | "denied" | "unavailable" | "not-requested";
  workspaceHasMore: boolean;
  /** 서버 기본 없이 전이 선택을 보여줄 때 true — 기본인 척하지 않는다. */
  transitionalSelection: boolean;
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

    {mode === "explore" && (<>
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
      {/* 기본 관측 선택 상태는 실제 내용 뒤에 둔다 — 화면 첫머리가 "없습니다"로
          시작하면, 자료가 있는 현장도 없는 현장처럼 읽힌다. */}
      <SiteWorkspaceEntryPanel
        sitePath={sitePath}
        workAreaId={selectedWorkAreaId}
        ordinaryEntry={ordinaryEntry}
        projectionState={projectionState}
        facts={facts}
        canCreateWorkOrder={canCreateWorkOrder}
        transitional={transitionalSelection}
      />
    </>)}

    {mode === "compare" && areasKnown && (
      <SiteWorkspaceCompare
        sitePath={sitePath}
        areas={areas}
        selectedWorkAreaId={selectedWorkAreaId}
        catalogAssets={assetsState.status === "ready" ? assetsState.page.assets : []}
        projectionState={projectionState === "not-requested" ? "unavailable" : projectionState}
        workspaceHasMore={workspaceHasMore}
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
        facts={facts}
        canCreateAnalysis={canCreateAnalysis}
        scopedCompareHref={scopedCompareHref}
      />
    )}
  </div>;
}
