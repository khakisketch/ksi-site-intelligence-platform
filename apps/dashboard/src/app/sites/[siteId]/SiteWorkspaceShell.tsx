import Link from "next/link";
import type { ReactNode } from "react";

import type { AnalysisListItem, AnalysisView } from "@/lib/core-api/analysis";
import type { ExternalRelativeVolumeHistoryItem } from "@/lib/core-api/external-result-workflow";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";
import type { WorkArea } from "@/lib/core-api/types";
import type {
  ExplicitComparisonResolution,
  ExplicitResultResolution,
  OrdinaryEntryResolution,
  VisualPairResolution,
  WorkspaceMode,
  WorkspaceObservationFact,
  WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";
import {
  compareSlotCandidates,
  representativeFacts,
  workspaceCaptureLine,
} from "@/lib/site-workspace-entry";
import { visualLayersForExactSubmission, pairQueryString, visualPairCatalogOptions } from "./site-visual-pair";
import { observationPrecisionOf } from "@/lib/site-workspace-entry";
import { inspectionOutcomeLabel, isKnownExpiredAsset } from "@/lib/site-windowed-pixel-viewer";
import type {
  PreparedWindowJob,
  WindowedViewerLayer,
} from "@/lib/site-windowed-pixel-viewer";
import { capturePeriodTitle, dataKindLabel } from "@/lib/operator-language";
import { formatKoreanDate } from "@/lib/datetime";
import { SiteSpatialOverview, type SiteSpatialAssetsState } from "./SiteSpatialOverview";
import { SiteAreaNextActionNav, resolveSiteAreaNextAction } from "./SiteAreaNextAction";
import { SiteSelectionForm } from "./SiteSelectionForm";
import { SiteWorkspaceWorkbench } from "./SiteWorkspaceWorkbench";
import type { ExploreCaptureOption } from "./SiteExploreCanvas";
import { SiteWorkspaceCompare, candidateLabel } from "./SiteWorkspaceCompare";
import { WorkbenchMediaState, WorkbenchRefreshButton } from "./WorkbenchMediaState";
import { SiteDisplayLegend } from "./SiteDisplayLegend";
import { SiteWorkspaceResults } from "./SiteWorkspaceResults";
import { SiteWindowedPixelViewer } from "./SiteWindowedPixelViewer";
import {
  analysesForArea,
  disambiguatedAreaNames,
  extractSimpleRing,
  selectableGeometry,
} from "./site-spatial";

const WORKSPACE_MODES: ReadonlyArray<{ key: WorkspaceMode; label: string }> = [
  { key: "explore", label: "단일 시점" },
  { key: "compare", label: "두 시점 비교" },
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
  compactRecovery = false,
  expiredKnown = false,
  recoveryHint = null,
}: {
  sitePath: string;
  workAreaId: string | null;
  ordinaryEntry: OrdinaryEntryResolution;
  projectionState: "ready" | "denied" | "unavailable" | "not-requested";
  facts: WorkspaceServerFacts;
  canCreateWorkOrder: boolean;
  /** 서버 기본이 없어 전이 선택을 보여줄 때 true — 기본인 척하지 않는다. */
  transitional: boolean;
  /**
   * 무대 보기가 이미 같은 사유의 회복 안내와 다음 행동을 둬서 진입 패널이
   * 준비 길을 반복하지 않을 때 true — 상태·원인 한 줄만 둔다. 이동 길은
   * 무대의 회복 단추와 정보 서랍이 맡는다.
   */
  compactRecovery?: boolean;
  /**
   * 무대에 올린 표시 층의 준비 기록이 모두 보관 만료로 확인될 때 true —
   * '표시 불가'가 아니라 '준비됐다가 보관 기간이 끝남'을 말한다. 준비된
   * 적 없는 자료를 만료로 단정하지 않으며, 진행 중으로 암시하지도 않는다.
   */
  expiredKnown?: boolean;
  /**
   * 무대 회복 안내를 가리키는 한 줄 — 무대 상태(만료·거부·불가)에 맞는
   * 명시 동작을 적는다. 호출자가 같은 분기로 계산한다.
   */
  recoveryHint?: string | null;
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
    if (compactRecovery) {
      if (expiredKnown) {
        return <section aria-label="기본 관측 선택 상태" className="border-t border-line pt-2">
          <p className="text-[12px] leading-5 text-ink-2">
            보관 만료는 등록 자료·검사 기록을 삭제하지 않았습니다. 복구는 위의 구역 자료 준비에서 확인하세요.
          </p>
        </section>;
      }
      return <section aria-label="기본 관측 선택 상태" className="rounded-lg border border-line bg-surface px-4 py-3">
        <p className="text-[13px] font-bold">표시용 파생물이 아직 준비되지 않았습니다</p>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
          {observationCount > 0
            ? `확인된 관측은 ${observationCount}건입니다. `
            : "확인된 관측이 없습니다. "}
          {recoveryHint ?? "준비 상태와 다음 확인은 위의 보기 안내를 따릅니다."}
        </p>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
          {lines.length > 0 ? lines.join(" ") : "언제 준비되는지는 담당자에게 확인하세요."}
        </p>
        {transitional && (
          <p className="mt-1 text-[12.5px] leading-5 text-ink-2">위에는 확인된 측정 범위를 표시합니다. 서버가 정한 기본 관측이 아닙니다.</p>
        )}
      </section>;
    }
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
  visual?: { visualAAssetRef: string | null; visualBAssetRef: string | null } | null,
): string {
  const query = new URLSearchParams();
  if (mode !== "explore") query.set("mode", mode);
  if (scope.workAreaId) query.set("workAreaId", scope.workAreaId);
  if (scope.assetRef) query.set("assetRef", scope.assetRef);
  // 시각 쌍 맥락은 모드를 옮겨도 유지한다. 구역이 바뀌면 싣지 않는다 —
  // 받는 화면이 같은 구역에서 재대조하고, 어긋나면 막는다.
  if (visual?.visualAAssetRef && visual?.visualBAssetRef && scope.workAreaId) {
    query.set("visualAAssetRef", visual.visualAAssetRef);
    query.set("visualBAssetRef", visual.visualBAssetRef);
  }
  const search = query.toString();
  return search ? `${sitePath}?${search}` : sitePath;
}

/**
 * 같은 관측의 창 보기 레이어 — 정사영상·DSM만 싣는다. 카탈로그 사실의
 * 옮김이며, 표시 순서를 정하거나 버전을 고르지 않는다(첫 항목이 ortho).
 */
function viewerLayersForEpoch(
  catalogAssets: readonly SpatialAssetCatalogItem[],
  observationEpochId: string,
): WindowedViewerLayer[] {
  const layers: WindowedViewerLayer[] = [];
  for (const item of catalogAssets) {
    if (item.observationEpochId !== observationEpochId) continue;
    if (item.kind !== "ortho" && item.kind !== "dsm") continue;
    layers.push({
      assetRef: item.assetRef,
      observationEpochId: item.observationEpochId,
      kind: item.kind,
      kindLabel: dataKindLabel(item.kind),
      isDsm: item.kind === "dsm",
      fileName: item.declared.fileName,
      revision: item.revision,
      submissionRef: item.submissionRef,
      inspectedRaster: item.inspection.raster
        ? {
            transform: [...item.inspection.raster.transform],
            width: item.inspection.raster.width,
            height: item.inspection.raster.height,
          }
        : null,
      observedCrsIdentifier: item.inspection.raster?.observedCrsIdentifier ?? null,
      observedCrsDigest: item.inspection.raster?.observedCrsDigest ?? null,
      inspectionOutcome: item.inspection.outcome,
      verticalReference: item.inspection.raster?.observedVerticalReference
        ? `${item.inspection.raster.observedVerticalReference.identifier} · ${item.inspection.raster.observedVerticalReference.basis}`
        : null,
    });
  }
  return layers.sort((a, b) => (a.isDsm === b.isDsm ? 0 : a.isDsm ? 1 : -1));
}

function viewerHeadingFor(fact: WorkspaceObservationFact): string {
  return `${dataKindLabel(fact.kind)} · ${entryCaptureLine(fact)} · 등록 버전 ${fact.revision}`;
}

/**
 * 탐색 촬영 시점 선택지 — 같은 구역 관측별 대표 한 줄의 순수 선택 규칙.
 *
 * - 순서는 서버 프로젝션 그대로 두며, 최신 단언·날짜 추측을 하지 않는다.
 * - 목표 층(`currentKind`)이 그 관측에 있으면 유지하고, 없으면 그 관측의
 *   대표 층으로 두되 바꾼 뜻을 밝힌다. 카탈로그에 층이 없으면 표시 버전
 *   사실을 그대로 쓴다.
 * - 선택 표시는 정확한 `assetRef` 일치이거나, 같은 관측(선택 epoch)일 때만 둔다.
 */
export function buildExploreCaptureOptions({
  facts,
  workAreaId,
  catalogAssets,
  selectedAssetRef,
  currentKind,
  selectedEpochId,
}: {
  facts: WorkspaceServerFacts;
  workAreaId: string;
  catalogAssets: readonly SpatialAssetCatalogItem[];
  selectedAssetRef: string | null;
  currentKind: string | null;
  selectedEpochId: string | null;
}): ExploreCaptureOption[] {
  return representativeFacts(facts, workAreaId).map((fact) => {
    const epochLayers = viewerLayersForEpoch(catalogAssets, fact.observationEpochId);
    const target = (currentKind ? epochLayers.find((item) => item.kind === currentKind) : undefined)
      ?? epochLayers[0]
      ?? null;
    const targetRef = target?.assetRef ?? fact.viewAssetRef ?? fact.assetRef;
    const targetCatalog = catalogAssets.find((item) => item.assetRef === targetRef) ?? null;
    const kindChanged = target !== null && currentKind !== null && target.kind !== currentKind;
    return {
      assetRef: targetRef,
      label: `${entryCaptureLine(fact)}${kindChanged ? ` · ${target.kindLabel}으로 둠` : ""}`,
      title: targetCatalog
        ? `${entryCaptureLine(fact)} · 등록 버전 ${fact.revision} · ${targetCatalog.declared.fileName}`
        : `${entryCaptureLine(fact)} · 등록 버전 ${fact.revision}`,
      selected: targetRef === selectedAssetRef || fact.observationEpochId === selectedEpochId,
    };
  });
}

/**
 * 현장 공간 작업공간 겉틀 (SWX-2 구조) — 탐색·비교·결과의 작업 방식만 나눈다.
 *
 * - 네 현장 영역 아래 하나의 선택 레일·뷰어 프레임을 공유한다.
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
  visualARequestedRef = null,
  visualBRequestedRef = null,
  visualPair = { status: "prompt" } as VisualPairResolution | { status: "prompt" },
  explicitResult,
  explicitDetail,
  leadDetail,
  scopedCompareHref,
  inspectorStatus = null,
  preparedJobs,
  jobsState,
  canReadData,
  canRequestData,
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
  visualARequestedRef?: string | null;
  visualBRequestedRef?: string | null;
  visualPair?: VisualPairResolution | { status: "prompt" };
  explicitResult: ExplicitResultResolution | null;
  explicitDetail: AnalysisView | null;
  /** 결과 목록 첫 기록의 상세(선택자 복원용, 1건만) — 없으면 조용히 둔다. */
  leadDetail?: AnalysisView | null;
  scopedCompareHref: string;
  /** 정보 서랍 맨 위에 두는 현장 현황(건수·다음 확인) — 호출자가 만든 노드 그대로. */
  inspectorStatus?: ReactNode;
  /** 현재 계정이 읽을 수 있는 준비 기록(범위 확인된 것만 호출자가 싣는다). */
  preparedJobs?: readonly PreparedWindowJob[];
  /** 준비 목록 읽기 상태 — 실패를 빈 목록으로 단정하지 않는다. */
  jobsState?: "ready" | "denied" | "unavailable" | "not-requested";
  /** SPATIAL_DATA_READ — 이미 준비된 창 보기. */
  canReadData?: boolean;
  /** SPATIAL_DATA_REQUEST — 새 창 준비 요청(쓰기). */
  canRequestData?: boolean;
}) {
  const scope = { workAreaId: selectedWorkAreaId, assetRef: selectedAssetRef };
  const selected = areas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null;
  const areaLabel = selected
    ? (disambiguatedAreaNames(areas).get(selected.workAreaId)?.label ?? selected.workAreaId)
    : null;
  const areaAnalyses = selected ? analysesForArea(analyses, selected.workAreaId) : null;
  const catalogAssets = assetsState.status === "ready" ? assetsState.page.assets : [];
  const jobs = preparedJobs ?? [];
  const viewerJobsState = jobsState ?? "not-requested";
  const viewerCanRead = canReadData ?? false;
  const viewerCanRequest = canRequestData ?? false;
  const requestsHref = selected
    ? `${sitePath}/spatial-data-requests?workAreaId=${encodeURIComponent(selected.workAreaId)}`
    : `${sitePath}/spatial-data-requests`;
  const selectedGeometry = selected ? selectableGeometry(selected) : null;
  const workAreaRing = selectedGeometry ? extractSimpleRing(selectedGeometry.polygon) : null;
  const workAreaCrs = selectedGeometry?.crs ?? "확인 불가";
  const browseAsset = selectedAssetRef ? catalogAssets.find((item) => item.assetRef === selectedAssetRef
    && item.workAreaId === selectedWorkAreaId) ?? null : null;
  const exploreFact = selectedAssetRef
    ? (facts.observations.find((item) => item.assetRef === selectedAssetRef) ?? null)
    : null;
  const exploreEpochId = exploreFact?.observationEpochId
    ?? (ordinaryEntry.status === "ready" ? ordinaryEntry.observation.observationEpochId : null);
  // 탐색 층은 고른 정확한 제출 묶음·버전 안에서만 둔다. epoch 전체로 넓혀
  // 다른 버전을 조용히 섞지 않는다. 일반 둘러보기의 고른 참조는 현재
  // 카탈로그의 버전으로 고정하며, 명시 비교의 프로젝션 충돌은 별도로 막는다.
  const exploreLayers = browseAsset
    ? visualLayersForExactSubmission(catalogAssets, browseAsset)
    : exploreFact
      ? visualLayersForExactSubmission(catalogAssets, exploreFact)
      : exploreEpochId ? viewerLayersForEpoch(catalogAssets, exploreEpochId) : [];
  const exploreHeading = exploreFact
    ? viewerHeadingFor(exploreFact)
    : ordinaryEntry.status === "ready"
      ? viewerHeadingFor(ordinaryEntry.observation)
      : null;
  // 선택 줄은 짧게 둔다 — 날짜는 선택 상자에, 층은 층 전환에 이미 있다.
  // 버전과 미상 정밀도만 여기에 남기고, 파일명 파싱·새 ID를 만들지 않는다.
  const captionFact = exploreFact
    ?? (ordinaryEntry.status === "ready" ? ordinaryEntry.observation : null);
  const selectedCaption = captionFact
    ? observationPrecisionOf(captionFact) === "interval"
      ? `등록 버전 ${captionFact.revision}`
      : observationPrecisionOf(captionFact) === "date-only"
        ? "날짜만 확인 · 시각 미상"
        : "관측 시점 미상"
    : null;
  // 촬영 시점 선택지 — 같은 구역 관측별 대표 한 줄. 순서는 서버 그대로 두며,
  // 층(정사영상/DSM)은 고른 층을 그 관측에서 유지하고, 없으면 그 관측의
  // 대표 층으로 두되 바꾼 뜻을 밝힌다. 최신 단언·날짜 추측을 하지 않는다.
  const currentKind = catalogAssets.find((item) => item.assetRef === selectedAssetRef)?.kind
    ?? exploreLayers[0]?.kind
    ?? null;
  const captureOptions = selected
    ? buildExploreCaptureOptions({
      facts,
      workAreaId: selected.workAreaId,
      catalogAssets,
      selectedAssetRef,
      currentKind,
      selectedEpochId: exploreFact?.observationEpochId ?? null,
    })
    : [];
  // 비교 빈손 회복용 돌아가기 — 같은 구역·선택 자료 그대로 탐색으로 둔다.
  const exploreHref = selectedWorkAreaId
    ? `${sitePath}?workAreaId=${encodeURIComponent(selectedWorkAreaId)}${selectedAssetRef ? `&assetRef=${encodeURIComponent(selectedAssetRef)}` : ""}`
    : sitePath;
  // 칸 머리 관측 선택 — 같은 쪽만 바꾸는 직접 GET이다. 반대쪽·다른 쌍 family
  // 참조는 hidden으로 그대로 싣고, 조용히 다른 자료로 바꾸지 않는다. 선택이
  // 바뀌면 SiteSelectionForm이 즉시 제출하므로 큰 제출 단추를 두지 않는다.
  // 라벨은 서버 사실의 정밀도 그대로(날짜만·시점 미상을 꾸미지 않는다).
  const pairSideSelect = (
    sideParam: "visualAAssetRef" | "visualBAssetRef" | "baselineAssetRef" | "currentAssetRef",
    sideLabel: string,
    currentRef: string | null,
    options: Array<{ assetRef: string; label: string }>,
    placeholder: string,
  ): ReactNode => {
    if (!selected) return null;
    const siblingParam = sideParam === "visualAAssetRef" ? "visualBAssetRef"
      : sideParam === "visualBAssetRef" ? "visualAAssetRef"
        : sideParam === "baselineAssetRef" ? "currentAssetRef" : "baselineAssetRef";
    const siblingRef = sideParam === "visualAAssetRef"
      ? (visualBFact?.assetRef ?? visualBRequestedRef)
      : sideParam === "visualBAssetRef"
        ? (visualAFact?.assetRef ?? visualARequestedRef)
        : sideParam === "baselineAssetRef"
          ? (currentFact?.assetRef ?? currentRequestedRef)
          : (baselineFact?.assetRef ?? baselineRequestedRef);
    const keepBaseline = baselineFact?.assetRef ?? baselineRequestedRef;
    const keepCurrent = currentFact?.assetRef ?? currentRequestedRef;
    const keepVisualA = visualAFact?.assetRef ?? visualARequestedRef;
    const keepVisualB = visualBFact?.assetRef ?? visualBRequestedRef;
    const selectId = `workspace-pair-${sideParam}`;
    return (
      <SiteSelectionForm action={sitePath} className="min-w-0 flex-1">
        <input type="hidden" name="mode" value="compare" />
        <input type="hidden" name="workAreaId" value={selected.workAreaId} />
        {siblingRef && <input type="hidden" name={siblingParam} value={siblingRef} />}
        {sideParam === "visualAAssetRef" || sideParam === "visualBAssetRef" ? (
          <>
            {keepBaseline && <input type="hidden" name="baselineAssetRef" value={keepBaseline} />}
            {keepCurrent && <input type="hidden" name="currentAssetRef" value={keepCurrent} />}
          </>
        ) : (
          <>
            {keepVisualA && <input type="hidden" name="visualAAssetRef" value={keepVisualA} />}
            {keepVisualB && <input type="hidden" name="visualBAssetRef" value={keepVisualB} />}
          </>
        )}
        <label className="sr-only" htmlFor={selectId}>{sideLabel} 관측 선택</label>
        <select
          id={selectId}
          name={sideParam}
          defaultValue={currentRef ?? ""}
          required
          className="input min-w-0 w-full text-[12.5px]"
        >
          <option value="">{placeholder}</option>
          {options.map((option) => (
            <option key={option.assetRef} value={option.assetRef} title={option.label}>
              {option.label}
            </option>
          ))}
        </select>
      </SiteSelectionForm>
    );
  };
  // 시각 쌍 선택지 — 카탈로그에 정확히 묶인 모든 검사 버전(대표 한 줄이
  // 아니라 모든 정사영상/DSM 개정)을 둔다. 정밀도 표기는 그대로 두며,
  // 순서·최신을 단정하지 않는다.
  const visualGroups = selected && areasKnown
    ? visualPairCatalogOptions({
      facts: facts.observations,
      workAreaId: selected.workAreaId,
      catalogAssets,
      selectedRefs: [visualARequestedRef, visualBRequestedRef],
    })
    : [];
  const visualOptions = visualGroups.flatMap((group) =>
    group.options.map((item) => ({ assetRef: item.assetRef, label: candidateLabel(item, true) })),
  );
  // 시간 순서 선택지 — 서버 프로젝션의 순서 가능 관측만 둔다. 날짜만·시점
  // 미상 관측은 순서 후보가 아니므로 싣지 않는다.
  const { eligible: compareEligible } = selected && areasKnown
    ? compareSlotCandidates(facts, selected.workAreaId)
    : { eligible: [] as WorkspaceObservationFact[] };
  const compareOptions = compareEligible.map((item) => ({ assetRef: item.assetRef, label: candidateLabel(item) }));
  // 나란히 두기 한 칸 — 칸 머리(역할+관측 선택+층 전환)와 그 그림을 둔다.
  // 층 전환은 칸 머리의 직접 GET 링크이며, 드로어 개폐와 무관하게 항상 그
  // 칸에 붙는다. 카메라는 칸마다 독립이며 동기화·정합 주장을 하지 않는다(무대 위 한 줄 고지만 둔다).
  const pairPane = (
    badge: string,
    select: ReactNode,
    fact: WorkspaceObservationFact,
    layers: WindowedViewerLayer[],
    idPrefix: string,
    layerParam: "visualAAssetRef" | "visualBAssetRef" | "baselineAssetRef" | "currentAssetRef",
    shared: ReactNode,
  ) => (
    <div data-workbench-pane className="min-w-0">
      <div data-workbench-pane-controls className="flex min-w-0 shrink-0 flex-col gap-y-1">
        <div className="flex min-w-0 items-center gap-x-2">
          <span aria-hidden="true" className="flex h-6 min-w-6 shrink-0 items-center justify-center rounded bg-sunk px-1 text-[11px] font-bold">{badge}</span>
          {select}
        </div>
        <p className="min-w-0 break-words text-[11.5px] leading-4 text-ink-2 max-sm:text-[11px]">{pairDateCaption(fact)}</p>
        {layers.length > 1 && (
          <div role="group" aria-label="자료 층 전환" data-workbench-pane-controls className="flex min-w-0 shrink-0 flex-nowrap gap-1 overflow-x-auto">
            {layers.map((item) => (
              <Link key={item.assetRef}
                href={pairLayerHref(layerParam, item.assetRef)}
                aria-current={item.assetRef === fact.assetRef ? "true" : undefined}
                className={`tap-target inline-flex items-center rounded-md px-3 py-1.5 text-[12.5px] break-keep ${item.assetRef === fact.assetRef ? "bg-sunk font-bold" : "text-ink-2"}`}>
                {item.kindLabel}
              </Link>
            ))}
          </div>
        )}
      </div>
      {shared ? null : (
      <SiteWindowedPixelViewer
        siteId={facts.siteId}
        workAreaId={selected!.workAreaId}
        layers={layers}
        jobs={[...jobs]}
        jobsState={viewerJobsState === "not-requested" ? "unavailable" : viewerJobsState}
        canRead={viewerCanRead}
        canRequest={viewerCanRequest}
        requestsHref={requestsHref}
        workAreaRing={workAreaRing}
        workAreaCrs={workAreaCrs}
        observationHeading={viewerHeadingFor(fact)}
        idPrefix={idPrefix}
        slimHeader
        hideLayerControls
        selectedAssetRef={fact.assetRef}
        presentation="canvas"
        showAbsentExtentCanvas
        detailsTargetId="workspace-inspector-details"
      />
      )}
    </div>
  );
  // 칸 머리 날짜 한 줄 — 선택 상자가 잘려도 전체 날짜+정밀도가 칸 옆에 남는다.
  // 390px에서도 날짜·정밀도 한정자는 정보 서랍을 열지 않고 보인다.
  const pairDateCaption = (fact: WorkspaceObservationFact): string => {
    const line = entryCaptureLine(fact);
    const precision = observationPrecisionOf(fact);
    const qualifier = precision === "date-only"
      ? "날짜만 확인 · 시각 미상"
      : precision === "unknown"
        ? "관측 시점 미상"
        : null;
    const base = qualifier && !line.includes(qualifier) ? `${line} · ${qualifier}` : line;
    return `${base} · 등록 버전 ${fact.revision}`;
  };
  // 쌍 한쪽의 층 전환 주소 — 같은 구역에서 그쪽만 정확한 참조로
  // 바꾼다. 다른 쪽·다른 쌍 family·구역·모드는 그대로 둔다(정식 쌍은 받는 쪽이 재대조한다).
  const pairLayerHref = (
    param: "visualAAssetRef" | "visualBAssetRef" | "baselineAssetRef" | "currentAssetRef",
    assetRef: string,
  ): string => {
    if (!selectedWorkAreaId) return sitePath;
    const query = new URLSearchParams();
    query.set("mode", "compare");
    query.set("workAreaId", selectedWorkAreaId);
    const keep = (key: string, value: string | null | undefined) => {
      if (value && key !== param) query.set(key, value);
    };
    keep("visualAAssetRef", visualAFact?.assetRef ?? visualARequestedRef);
    keep("visualBAssetRef", visualBFact?.assetRef ?? visualBRequestedRef);
    keep("baselineAssetRef", baselineFact?.assetRef ?? baselineRequestedRef);
    keep("currentAssetRef", currentFact?.assetRef ?? currentRequestedRef);
    query.set(param, assetRef);
    return `${sitePath}?${query.toString()}`;
  };
  // 첫 방문 빈 상태 — 관측·층 선택지가 없고 프로젝션·카탈로그가 모두
  // 확인됐을 때만 true. 거부·실패(unknown/denied/unavailable)는 빈 상태가
  // 아니므로 등록 길로 단정하지 않는다. 준비 요청을 새로 만들지 않으며,
  // 기존 다음-행동만 무대 1차 영역으로 옮긴다.
  const exploreIsEmpty = selected !== null
    && captureOptions.length === 0
    && exploreLayers.length === 0
    && projectionState === "ready"
    && assetsState.status === "ready";
  // 카탈로그 읽기 실패 — 픽셀 NoLayer 일반론보다 먼저 밝힌다. 조회 실패는
  // 빈 목록이 아니며 등록 길로도 바꾸지 않는다.
  const catalogStatus = selected && (assetsState.status === "denied" || assetsState.status === "unavailable") ? (
    <p role="status" className="shrink-0 rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2">
      {assetsState.status === "denied"
        ? "등록 자료 목록을 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요. 권한이 없어 빈 목록으로 단정하지 않습니다."
        : "등록 자료 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요. 빈 목록으로 단정하지 않습니다."}
    </p>
  ) : null;
  // 무대 보기가 같은 사유의 회복 안내를 이미 두면 진입 패널은 준비 길을
  // 반복하지 않는다 — 상태·원인 한 줄만 둔다. 이동 길은 무대의 회복 단추와
  // 정보 서랍이 맡는다. 위 무대 분기와 같은 조건을 쓴다.
  const viewerRendered = selected !== null
    && !exploreIsEmpty
    && catalogStatus === null
    && viewerJobsState !== "not-requested"
    && (exploreLayers.length > 0 || viewerJobsState === "ready");
  // 같은 사유 회복은 하나로 모은다 — 준비 기록 조회 실패·읽기 권한 없음은
  // 두 칸에 똑같이 걸리므로 칸마다 단추를 두지 않는다. 서로 다른 칸 실패
  // (바이트 수신 실패 등)는 각자 정직하게 둔다.
  const entryNoView = ordinaryEntry.status === "no-server-default"
    && ordinaryEntry.reason === "NO_VIEW_AVAILABLE_OBSERVATION";
  // 같은 관측의 표시 층이 모두 보관 만료로 확인되면 만료 사실을 말한다.
  // 프로젝션의 표시 불가와 준비 기록의 보존 만료는 다른 사실이므로, 알려진
  // 만료가 아니면 만료를 단정하지 않고 준비 중·미확인으로 두지 않는다.
  // 읽을 수 있는 창이 하나라도 있으면 픽셀이 보일 수 있어 패널을 줄이지 않는다.
  const exploreExpiredKnown = viewerRendered
    && viewerJobsState === "ready"
    && exploreLayers.length > 0
    && exploreLayers.every((layer) => isKnownExpiredAsset(jobs, layer.assetRef));
  const exploreBlockedKnown = viewerRendered
    && (viewerJobsState === "denied" || viewerJobsState === "unavailable");
  const entryRecoveryCompact = entryNoView && (exploreBlockedKnown || exploreExpiredKnown);
  const recoveryPointer = !entryRecoveryCompact
    ? null
    : exploreExpiredKnown
      ? "위의 보기(구역 자료 준비에서 확인)를 따릅니다"
      : viewerJobsState === "denied"
        ? "위의 보기 안내(준비 기록 조회 권한 요청)를 따릅니다"
        : "위의 보기 안내(다시 불러오기)를 따릅니다";
  const pairJobsBlocked = viewerJobsState === "denied" || viewerJobsState === "unavailable" || !viewerCanRead;
  const baselineFact = comparison.status === "ready" ? comparison.baseline : null;
  const currentFact = comparison.status === "ready" ? comparison.current : null;
  const visualAFact = visualPair.status === "ready" ? visualPair.sideA : null;
  const visualBFact = visualPair.status === "ready" ? visualPair.sideB : null;
  // 무대에 직접 두는 쌍 — 선택·거부가 끝난 정식 사실만 둔다. 요청 문자열은
  // 받지 않으며, 받는 화면이 재대조한다.
  const comparisonReady = baselineFact !== null && currentFact !== null;
  const visualReady = visualAFact !== null && visualBFact !== null;
  // 알려진 선택 출력 만료는 스캔하지 않은 부재와 섞지 않는다 — 선택한 두 층의
  // 준비 기록이 모두 RETENTION_EXPIRED일 때만 같은 사유로 묶는다. 한쪽만
  // 만료면 각 칸이 정직하게 따로 둔다.
  const bothVisualExpired = visualReady && viewerJobsState === "ready"
    && isKnownExpiredAsset(jobs, visualAFact!.assetRef) && isKnownExpiredAsset(jobs, visualBFact!.assetRef);
  const bothOrderedExpired = comparisonReady && viewerJobsState === "ready"
    && isKnownExpiredAsset(jobs, baselineFact!.assetRef) && isKnownExpiredAsset(jobs, currentFact!.assetRef);
  // 워크스페이스 예시 화면 복귀 주소 — 선택 쌍을 그대로 싣는다.
  const workspaceExampleReturnTo = (() => {
    const query = new URLSearchParams();
    query.set("mode", "compare");
    if (selectedWorkAreaId) query.set("workAreaId", selectedWorkAreaId);
    if (visualAFact) query.set("visualAAssetRef", visualAFact.assetRef);
    if (visualBFact) query.set("visualBAssetRef", visualBFact.assetRef);
    const search = query.toString();
    return search ? `${sitePath}?${search}` : sitePath;
  })();
  const sharedExpiredMedia = (
    <WorkbenchMediaState
      tone="absence"
      headline="미리보기 보관 기간이 끝났습니다."
      detail="두 칸의 불러온 준비 기록이 모두 보관 기간이 끝났습니다."
      action={
        <Link href={requestsHref} className="btn btn-primary min-h-11">
          구역 자료 준비에서 확인
        </Link>
      }
      hint={
        <>무대 구성을 먼저 보려면 <Link className="font-semibold text-ink-1 underline" href={`/design-preview/materials?returnTo=${encodeURIComponent(workspaceExampleReturnTo)}`}>예시 화면으로 미리 보기</Link></>
      }
    />
  );
  // 목록 실패·읽기 권한 없음은 두 체계에 똑같이 걸리므로 무대에 한 번만 둔다.
  const jobsSharedBar = selected && (comparisonReady || visualReady)
    && viewerJobsState !== "not-requested" && catalogStatus === null && pairJobsBlocked ? (
    viewerJobsState === "denied" ? (
      <WorkbenchMediaState
        headline="준비 기록을 조회할 권한이 없습니다."
        hint="담당자에게 조회 권한을 요청하세요. 권한이 없어 빈 목록으로 단정하지 않습니다."
      />
    ) : !viewerCanRead ? (
      <WorkbenchMediaState
        headline="이미 준비된 창을 볼 권한이 없습니다."
        hint="필요한 창과 용도를 담당자에게 알려 주세요. 같은 계정이 준비한 창만 볼 수 있습니다."
      />
    ) : (
      <WorkbenchMediaState
        headline="준비 기록을 불러오지 못했습니다."
        detail="빈 목록으로 단정하지 않습니다."
        action={<WorkbenchRefreshButton />}
      />
    )
  ) : null;
  const sharedOrderedRecovery = comparisonReady && bothOrderedExpired && !pairJobsBlocked ? sharedExpiredMedia : null;
  const sharedVisualRecovery = visualReady && bothVisualExpired && !pairJobsBlocked ? sharedExpiredMedia : null;
  // 둘러보기 맥락은 정식 resolve된 사실에서만 싣는다. 요청 문자열(미확인·
  // 실패·거부된 값)은 전파하지 않는다 — 받는 화면이 재대조한다.
  const visualContext = visualAFact && visualBFact && selectedWorkAreaId
    ? { visualAAssetRef: visualAFact.assetRef, visualBAssetRef: visualBFact.assetRef }
    : null;
  // 탐색 첫 화면의 다음 행동 — 구역 상세 화면과 같은 계산을 공유한다.
  // 자료·범위 상세(펼침) 안에만 있으면 처음 보는 사람은 무엇을 할 수
  // 있는지 펼치기 전까지 모른다.
  const exploreAreaAnalyses = selected ? analysesForArea(analyses, selected.workAreaId) : null;
  const exploreLatestAnalysis = exploreAreaAnalyses?.[0] ?? null;
  const exploreNextAction = selected
    ? resolveSiteAreaNextAction({
      sitePath,
      workAreaId: selected.workAreaId,
      workAreaStatus: selected.status,
      canCreateWorkOrder,
      canCreateAnalysis,
      latestAnalysis: exploreLatestAnalysis
        ? { workAreaId: exploreLatestAnalysis.workAreaId, analysisId: exploreLatestAnalysis.analysisId }
        : null,
      pairQuery: visualAFact && visualBFact && selected.workAreaId === visualAFact.workAreaId
        ? pairQueryString(selected.workAreaId, visualAFact, visualBFact)
        : baselineFact && currentFact && comparison.status === "ready" && selected.workAreaId === comparison.workAreaId
          ? pairQueryString(selected.workAreaId, baselineFact, currentFact)
          : null,
    })
    : null;
  // 쌍 고르기 전 빈 칸 — 차단이 아니라 비어 있음이므로 밝은 면에 둔다.
  // 어두운 면은 매체·차단 전용이며, 빈 프롬프트를 차단처럼 읽히지 않게 한다.
  const pairPromptPane = (badge: string, select: ReactNode, hint: string) => (
    <div data-workbench-pane className="min-w-0">
      <div data-workbench-pane-controls className="flex min-w-0 shrink-0 items-center gap-x-2 gap-y-1">
        <span aria-hidden="true" className="flex h-6 min-w-6 shrink-0 items-center justify-center rounded bg-sunk px-1 text-[11px] font-bold">{badge}</span>
        {select}
      </div>
      <p role="status" className="rounded-lg border border-dashed border-line bg-surface px-4 py-6 text-center text-[12.5px] leading-5 text-ink-2">{hint}</p>
    </div>
  );
  const selectedCatalog = mode === "explore" ? catalogAssets.find((item) => item.assetRef === selectedAssetRef) ?? null : null;
  const compareProps = {
    sitePath, areas, selectedWorkAreaId, catalogAssets,
    projectionState: projectionState === "not-requested" ? "unavailable" as const : projectionState,
    workspaceHasMore, baselineRequestedRef, currentRequestedRef, resolution: comparison,
    visualARequestedRef, visualBRequestedRef, visualPair,
    canCreateAnalysis, canCreateWorkOrder, scopedCompareHref, exploreHref, facts,
  };
  const areaNames = disambiguatedAreaNames(areas);
  // 선택 고지 — 목록 드로어가 닫혀 있어도 보여야 하므로 무대 1차 영역에 둔다.
  // 무엇을 보여주는지 정확히 밝힌다. 조용히 다른 대상으로 바꾸지 않았다는
  // 말은 범위 밖 요청을 기본으로 둔 경우에만 쓴다(기본이 실제로 바뀐 전이
  // 선택에는 서버 기본이 아니라는 말만 둔다).
  const selectionNotice = (scopeNotice || (mode === "explore" && transitionalSelection)) ? (
    <p role="status" data-workbench-stage-inset="true" className="shrink-0 rounded-md border border-line bg-sunk/40 px-3 py-1.5 text-[12px] leading-5 text-ink-2 max-sm:hidden">
      {scopeNotice ? "요청한 구역·자료가 조회 범위에 없어 아래 선택을 보여줍니다. " : ""}
      {selected ? `작업구역 · ${areaLabel}. ` : ""}
      {mode === "explore" && transitionalSelection
        ? "서버 기본이 없어 확인된 측정 범위를 보여줍니다. 서버가 정한 기본 관측이 아닙니다."
        : scopeNotice
          ? "조용히 다른 대상으로 바꾸지 않았습니다."
          : ""}
    </p>
  ) : null;
  // 맥락막대 — 한 줄 맥락(목록·구역) + 작은 보기 방식 전환 + 한 줄 용도만 둔다.
  // 보기 방식은 탭이 아니라 세그먼트다. 목록 토글·검색·정보는 셸이 앞에 둔다.
  const contextControls = (<>
    {selected ? (
      <span className="min-w-0 flex-1 truncate text-[12px]">
        <span className="text-ink-muted">작업구역 · </span>
        <span className="font-semibold">{areaLabel}{selected.status === "ARCHIVED" ? " (보관됨)" : ""}</span>
      </span>
    ) : (
      <span className="text-[12px] text-ink-2">작업구역을 확인하지 못했습니다</span>
    )}
    <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span id="workspace-view-mode-label" data-viewer-compact-hide="true" className="sr-only sm:not-sr-only sm:shrink-0 sm:text-[11.5px] sm:text-ink-muted">보기 방식</span>
      <nav aria-labelledby="workspace-view-mode-label" className="flex shrink-0 items-center gap-0.5 rounded-full border border-line bg-sunk p-0.5">
        {WORKSPACE_MODES.map((option) => {
          const active = option.key === mode;
          return (
            <Link
              key={option.key}
              href={modeHref(sitePath, option.key, scope, visualContext)}
              aria-current={active ? "page" : undefined}
              className={`tap-target inline-flex items-center rounded-full px-2.5 py-1 text-[12px] break-keep ${
                active ? "bg-sidebar-active font-semibold text-sidebar-active-ink shadow-sm" : "text-ink-2"
              }`}
            >
              {option.label}
            </Link>
          );
        })}
      </nav>
    </div>
    {mode === "compare" && (
      <p data-viewer-compact-hide="true" className="min-w-0 shrink-0 basis-full break-words text-[11.5px] leading-4 text-ink-muted lg:basis-auto">두 시점 비교 · 관측을 둘러보고 비교</p>
    )}
  </>);

  // 목록 드로어 — 구역 선택과 이동 길만 둔다. 관측·층 선택과 포털 대상은
  // 무대 위에 그대로 두어, 드로어가 닫혀도 포털이 사라지지 않게 한다.
  const catalog = (<div className="flex min-w-0 flex-col gap-3">
    {areas.length > 1 ? (
      <SiteSelectionForm action={sitePath} className="flex w-full min-w-0 flex-col gap-2">
        {mode !== "explore" && <input type="hidden" name="mode" value={mode} />}
        <div className="min-w-0 flex-1">
          <label htmlFor="workspace-catalog-area" className="block text-[12px] font-semibold">작업구역</label>
          <select
            id="workspace-catalog-area"
            name="workAreaId"
            defaultValue={selected?.workAreaId ?? ""}
            className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]"
          >
            {areas.map((area) => {
              const naming = areaNames.get(area.workAreaId) ?? { label: area.name || area.workAreaId };
              return <option key={area.workAreaId} value={area.workAreaId}>
                {naming.label}{area.status === "ARCHIVED" ? " · 보관됨" : ""}
              </option>;
            })}
          </select>
        </div>
      </SiteSelectionForm>
    ) : selected && areaLabel ? (
      <p className="break-words text-[13px] font-semibold">작업구역 · {areaLabel}</p>
    ) : (
      <p className="text-[12.5px] text-ink-2" role="status">작업구역을 확인할 수 없습니다. 아래 상세에서 목록을 확인하세요.</p>
    )}
    {mode === "explore" && <p className="text-[12px] leading-5 text-ink-2">관측 시점·층 선택은 무대의 그림 바로 위에서 합니다.</p>}
    {mode === "compare" && <p className="text-[12px] leading-5 text-ink-2">두 시점 선택은 무대 위에서 합니다. 각 칸의 층은 각 그림 바로 위에서 바꿉니다.</p>}
    {mode === "results" && <p className="text-[12px] leading-5 text-ink-2">결과 선택은 무대에서 합니다. 탐색 중이던 두 자료와 결과의 계산 입력은 구분합니다.</p>}
    <nav aria-label="작업공간 이동" className="flex min-w-0 flex-col gap-1 text-[12px]">
      <Link href={`${sitePath}/spatial-assets${selected ? `?workAreaId=${encodeURIComponent(selected.workAreaId)}` : ""}`} className="tap-target underline">자료 목록 보기</Link>
      <Link href={requestsHref} className="tap-target underline">구역 자료 준비</Link>
      <Link href={`${sitePath}/observations`} className="tap-target underline">외부 비교 기록</Link>
      <Link href={`${sitePath}/analysis${selected ? `?workAreaId=${encodeURIComponent(selected.workAreaId)}` : ""}`} className="tap-target underline">분석 기록·요청</Link>
      <Link href={`${sitePath}/work-areas${selected ? `?workAreaId=${encodeURIComponent(selected.workAreaId)}` : ""}`} className="tap-target underline">작업구역 관리</Link>
    </nav>
    {workspaceHasMore && <p className="text-[12px] text-ink-2">조회된 목록 뒤에 관측이 더 있습니다. 찾는 관측이 없으면 담당자에게 문의하세요.</p>}
  </div>);

  // 오른쪽 정보 본문 — 머리(제목·닫기)는 래퍼가 둔다. 선택한 자료 사실과
  // 범위 한계만 둔다. 오류·만료 본문은 무대(1차 영역)에 그대로 두어
  // 시야에서 밀려나지 않게 한다.
  const inspector = (<>
    {inspectorStatus}
    {mode === "explore" && transitionalSelection && (
      <p className="text-[11.5px] leading-4 text-ink-muted sm:hidden">표시 범위는 서버 기본이 아니라 확인된 측정 범위입니다.</p>
    )}
    {mode === "explore" && selectedCatalog && (
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-sunk/35 p-2.5">
        <div className="flex items-start justify-between gap-2">
          <p className="min-w-0 flex-1 break-words text-[12.5px] font-semibold text-ink-1">{exploreHeading ?? dataKindLabel(selectedCatalog.kind)}</p>
          <Link className="tap-target shrink-0 text-[11.5px] font-semibold underline" href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(selectedCatalog.workAreaId)}&assetRef=${encodeURIComponent(selectedCatalog.assetRef)}`}>원본 메타데이터 확인</Link>
        </div>
        <dl className="grid grid-cols-3 gap-2 rounded-md border border-line bg-surface px-2.5 py-2 text-[11.5px]">
          <div className="min-w-0"><dt className="text-[11px] text-ink-muted">파일 검사</dt><dd className="mt-0.5 font-semibold break-keep text-ink-1">{inspectionOutcomeLabel(selectedCatalog.inspection.outcome)}</dd></div>
          <div className="min-w-0"><dt className="text-[11px] text-ink-muted">관측 위치 기준</dt><dd className="mt-0.5 font-mono font-semibold break-all text-ink-1">{selectedCatalog.inspection.raster?.observedCrsIdentifier ?? "확인 불가"}</dd></div>
          <div className="min-w-0"><dt className="text-[11px] text-ink-muted">수직 기준</dt><dd className="mt-0.5 font-semibold break-keep text-ink-1">{selectedCatalog.inspection.raster?.observedVerticalReference?.identifier ?? "확인 불가"}</dd></div>
        </dl>
        <details className="text-[11.5px]">
          <summary className="tap-target cursor-pointer font-semibold text-ink-2">버전·식별·적합성 상세</summary>
          <dl className="mt-1.5 grid gap-1.5 rounded-md border border-line bg-surface p-2">
            <div><dt className="text-ink-muted">등록 파일명</dt><dd className="break-all font-mono">{selectedCatalog.declared.fileName}</dd></div>
            <div><dt className="text-ink-muted">분석 적합성</dt><dd>{selectedCatalog.analysisStatus === "NOT_EVALUATED" ? "자료 목록에서는 분석 적합성을 평가하지 않습니다. 결과 화면에서 입력별 조건을 확인하세요." : "분석 기록에서 확인하세요."}</dd></div>
            <div><dt className="text-ink-muted">등록 버전</dt><dd className="break-all font-mono">{selectedCatalog.revision} · {selectedCatalog.submissionRef}</dd></div>
            <div><dt className="text-ink-muted">자료 식별자</dt><dd className="break-all font-mono">{selectedCatalog.assetRef}</dd></div>
          </dl>
        </details>
      </div>
    )}
    {mode === "explore" && !selectedCatalog && <p>선택한 자료 사실이 없습니다. 무대에서 관측을 고르세요.</p>}
    {mode === "explore" && (
      <section aria-label="자료·범위·다음 행동" className="flex min-w-0 flex-col gap-3">
        {selected && exploreNextAction && !exploreIsEmpty && (
          <SiteAreaNextActionNav sitePath={sitePath} workAreaId={selected.workAreaId}
            action={exploreNextAction} archived={selected.status === "ARCHIVED"}
            canRegisterOrCompare={canCreateWorkOrder && selected.status === "ACTIVE" || canCreateAnalysis && selected.status === "ACTIVE"}
            label="탐색 다음 행동" compact />
        )}
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
          scopeNotice={false}
          hideAreaForm
          compact
        />
      </section>
    )}
    {mode === "compare" && selected && areasKnown && (
      <SiteWorkspaceCompare {...compareProps} presentation="inspector" />
    )}
    <SiteDisplayLegend />
    {mode === "results" && <>
      <p className="break-words font-semibold">결과와 근거{areaLabel ? ` · ${areaLabel}` : ""}</p>
      <p>이 화면은 기록된 값을 옮긴 것이며 다시 계산하지 않습니다. 계산에 쓰인 자료·조건·근거는 분석 기록에 있습니다.</p>
      <Link className="tap-target underline" href={`${sitePath}/analysis${selected?.workAreaId ? `?workAreaId=${encodeURIComponent(selected.workAreaId)}` : ""}`}>분석 기록·요청 열기</Link>
    </>}
  </>);

  // 무대 — 실제 화면이 먼저다. 무대는 내용 높이 그대로 쌓고 페이지
  // 스크롤에 맡긴다. flex-1 강제 높이를 두지 않으므로 실제 화면과 뒤따르는
  // 안내가 겹치지 않으며, 빈 상태·오류에도 가짜 빈 높이를 두지 않는다.
  // 오류·만료·복구는 이 1차 영역에 둔다.
  const stage = (<>
    {mode === "explore" && (
      <section aria-label="선택 관측 보기" className="flex h-full min-w-0 min-h-0 flex-col gap-2">
        {selectionNotice}
        {selected && captureOptions.length > 0 && (
          <div data-workbench-pane-controls className="flex min-w-0 shrink-0 flex-wrap items-center gap-x-2 gap-y-1.5">
            <SiteSelectionForm
              key={captureOptions.find((option) => option.selected)?.assetRef ?? "unselected"}
              action={sitePath}
              className="flex min-w-0 min-w-44 flex-1 items-center gap-1.5"
            >
              <input type="hidden" name="workAreaId" value={selected.workAreaId} />
              <label htmlFor="workspace-capture" className="shrink-0 text-[12px] font-semibold">관측 시점</label>
              <select
                id="workspace-capture"
                name="assetRef"
                defaultValue={captureOptions.find((option) => option.selected)?.assetRef ?? ""}
                aria-describedby="workspace-capture-help"
                className="tap-target min-w-0 flex-1 rounded-md border border-line bg-surface px-2 text-[13px]"
              >
                {captureOptions.find((option) => option.selected) === undefined && <option value="">관측 시점 선택</option>}
                {captureOptions.map((option) => (
                  <option key={option.assetRef} value={option.assetRef} title={option.title}>
                    {option.label}
                  </option>
                ))}
              </select>
            </SiteSelectionForm>
            {exploreLayers.length > 1 && (
              <nav aria-label="자료 층 전환" className="flex shrink-0 flex-wrap gap-1">
                {exploreLayers.map((item) => <Link key={item.assetRef}
                  href={`${sitePath}?workAreaId=${encodeURIComponent(selected.workAreaId)}&assetRef=${encodeURIComponent(item.assetRef)}`}
                  aria-current={item.assetRef === (selectedAssetRef ?? exploreLayers[0]?.assetRef) ? "true" : undefined}
                  className={`tap-target rounded-md px-2.5 py-1.5 text-[12.5px] ${item.assetRef === (selectedAssetRef ?? exploreLayers[0]?.assetRef) ? "bg-sunk font-bold" : "text-ink-2"}`}>
                  {item.kindLabel}
                </Link>)}
              </nav>
            )}
            {exploreLayers.length <= 1 && exploreLayers[0] && (
              <p className="shrink-0 text-[12px] text-ink-2">{exploreLayers[0].kindLabel}</p>
            )}
          </div>
        )}
        {mode === "explore" && captureOptions.length > 0 && <p id="workspace-capture-help" className="sr-only">관측을 선택하면 표시가 바뀝니다.</p>}
        {mode === "explore" && !exploreIsEmpty && selectedCaption && captionFact && (
          <p data-workbench-stage-inset="true" className="shrink-0 break-words text-[12px] leading-5 text-ink-2">
            선택 중 · {(() => {
              const line = entryCaptureLine(captionFact);
              const version = `등록 버전 ${captionFact.revision}`;
              if (line.includes(selectedCaption)) return `${line} · ${version}`;
              return selectedCaption === version ? `${line} · ${version}` : `${line} · ${selectedCaption} · ${version}`;
            })()}
          </p>
        )}
        {exploreIsEmpty && selected && exploreNextAction && (
          <div className="shrink-0 rounded-lg border border-line bg-surface px-4 py-3">
            <p className="text-[13px] font-bold">이 구역에 확인할 관측이 없습니다</p>
            <p className="mt-1 text-[12.5px] leading-5 text-ink-2">외부 관측이 등록되면 이 자리에서 확인할 수 있습니다.</p>
            <div className="mt-2">
              <SiteAreaNextActionNav sitePath={sitePath} workAreaId={selected.workAreaId}
                action={exploreNextAction} archived={selected.status === "ARCHIVED"}
                canRegisterOrCompare={canCreateWorkOrder && selected.status === "ACTIVE" || canCreateAnalysis && selected.status === "ACTIVE"}
                label="탐색 다음 행동" compact />
            </div>
          </div>
        )}
        {catalogStatus}
        {viewerRendered ? (
          <div data-workbench-pane className="flex min-h-0 min-w-0 flex-1 flex-col">
            <SiteWindowedPixelViewer
              siteId={facts.siteId}
              workAreaId={selected.workAreaId}
              layers={exploreLayers}
              jobs={[...jobs]}
              jobsState={viewerJobsState}
              canRead={viewerCanRead}
              canRequest={viewerCanRequest}
              requestsHref={requestsHref}
              workAreaRing={workAreaRing}
              workAreaCrs={workAreaCrs}
              observationHeading={exploreHeading}
              idPrefix="windowed-explore"
              slimHeader
              hideLayerControls
              selectedAssetRef={selectedAssetRef}
              layerSelectionHref={`${sitePath}?workAreaId=${encodeURIComponent(selected.workAreaId)}`}
              presentation="canvas"
              showAbsentExtentCanvas
              detailsTargetId="workspace-inspector-details"
            />
          </div>
        ) : !exploreIsEmpty && catalogStatus === null ? (
          <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
            {!selected
              ? "작업구역을 확인할 수 없어 화면을 고르지 않았습니다. 목록에서 구역을 고르세요."
              : viewerJobsState === "denied"
                ? "준비 기록을 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요."
                : "준비 기록을 불러오지 못했습니다. 잠시 후 목록에서 다시 확인하세요."}
          </p>
        ) : null}
        {/* 참 빈 상태의 1차 빈 블록이 사실·행동을 이미 둔다 — 같은 등록 길과
            같은 고지를 두 번 내지 않는다. 서버 기본·전이·범위밖·거부 등 다른
            사유는 그대로 둔다. */}
        {!(exploreIsEmpty && selected && exploreNextAction
          && ordinaryEntry.status === "no-server-default" && ordinaryEntry.reason === "NO_OBSERVATIONS") && (
          <SiteWorkspaceEntryPanel
            sitePath={sitePath}
            workAreaId={selectedWorkAreaId}
            ordinaryEntry={ordinaryEntry}
            projectionState={projectionState}
            facts={facts}
            canCreateWorkOrder={canCreateWorkOrder}
            transitional={transitionalSelection}
            compactRecovery={entryRecoveryCompact}
            expiredKnown={exploreExpiredKnown}
            recoveryHint={recoveryPointer}
          />
        )}
      </section>
    )}

    {mode === "compare" && (
      <section aria-label="두 시점 비교" className="flex h-full min-w-0 min-h-0 flex-col gap-2 max-sm:gap-1.5">
        {selectionNotice}
        {!areasKnown && <p role="status" className="shrink-0 text-[12.5px] leading-5 text-ink-2">작업구역 목록을 확인하지 못했습니다. 잠시 후 다시 확인하세요. 빈 목록으로 단정하지 않습니다.</p>}
        {areasKnown && selected && (comparisonReady || visualReady) && viewerJobsState !== "not-requested" && catalogStatus === null && (
          <>
            <p className="shrink-0 text-[11.5px] leading-5 text-ink-muted max-sm:text-[11px] max-sm:leading-4">각 칸은 독립된 보기입니다. 같은 범위 맞춤·같은 색 눈금은 지원하지 않습니다.</p>
            {(comparisonReady || visualReady) && (
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {sharedOrderedRecovery || sharedVisualRecovery || jobsSharedBar ? (
                  <Link href={scopedCompareHref} className="btn w-fit">이 쌍으로 분석 조건 확인</Link>
                ) : (
                  <Link href={scopedCompareHref} className="btn btn-primary w-fit">이 쌍으로 분석 조건 확인</Link>
                )}
                <span className="text-[11.5px] leading-5 text-ink-muted">수치 계산이 필요할 때만 씁니다. 위 기록은 바뀌지 않으며, 요청하지 않으면 아무 계산도 시작하지 않습니다.</span>
              </div>
            )}
            {comparisonReady && (
              <div className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2 md:gap-0 md:divide-x md:divide-line">
                {pairPane("1",
                  pairSideSelect("baselineAssetRef", "기준 자료", baselineFact!.assetRef, compareOptions, "기준 자료 선택"),
                  baselineFact!, viewerLayersForEpoch(catalogAssets, baselineFact!.observationEpochId), "windowed-baseline", "baselineAssetRef", sharedOrderedRecovery ?? jobsSharedBar)}
                {pairPane("2",
                  pairSideSelect("currentAssetRef", "비교 자료", currentFact!.assetRef, compareOptions, "비교 자료 선택"),
                  currentFact!, viewerLayersForEpoch(catalogAssets, currentFact!.observationEpochId), "windowed-current", "currentAssetRef", sharedOrderedRecovery ?? jobsSharedBar)}
              </div>
            )}
            {sharedOrderedRecovery}
            {visualReady && (
              <div className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2 md:gap-0 md:divide-x md:divide-line">
                {pairPane("A",
                  pairSideSelect("visualAAssetRef", "관측 A", visualAFact!.assetRef, visualOptions, "관측 A 선택"),
                  visualAFact!, visualLayersForExactSubmission(catalogAssets, visualAFact!), "windowed-visual-a", "visualAAssetRef", sharedVisualRecovery ?? jobsSharedBar)}
                {pairPane("B",
                  pairSideSelect("visualBAssetRef", "관측 B", visualBFact!.assetRef, visualOptions, "관측 B 선택"),
                  visualBFact!, visualLayersForExactSubmission(catalogAssets, visualBFact!), "windowed-visual-b", "visualBAssetRef", sharedVisualRecovery ?? jobsSharedBar)}
              </div>
            )}
            {sharedVisualRecovery}
            {jobsSharedBar}
          </>
        )}
        {areasKnown && selected && !comparisonReady && !visualReady && catalogStatus === null && (visualOptions.length >= 2 || compareOptions.length >= 2) && (
          <div className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2 md:gap-0 md:divide-x md:divide-line">
            {visualOptions.length >= 2 ? (
              <>
                {pairPromptPane("A",
                  pairSideSelect("visualAAssetRef", "관측 A", visualARequestedRef, visualOptions, "관측 A 선택"),
                  "관측 A를 고르면 이 자리에서 봅니다.")}
                {pairPromptPane("B",
                  pairSideSelect("visualBAssetRef", "관측 B", visualBRequestedRef, visualOptions, "관측 B 선택"),
                  "관측 B를 고르면 이 자리에서 봅니다.")}
              </>
            ) : (
              <>
                {pairPromptPane("1",
                  pairSideSelect("baselineAssetRef", "기준 자료", baselineRequestedRef, compareOptions, "기준 자료 선택"),
                  "기준 자료를 고르면 이 자리에서 봅니다.")}
                {pairPromptPane("2",
                  pairSideSelect("currentAssetRef", "비교 자료", currentRequestedRef, compareOptions, "비교 자료 선택"),
                  "비교 자료를 고르면 이 자리에서 봅니다.")}
              </>
            )}
          </div>
        )}
        {selected && catalogStatus !== null && (comparison.status === "ready" || visualPair.status === "ready") && viewerJobsState !== "not-requested" && catalogStatus}
        {areasKnown && (
          <SiteWorkspaceCompare {...compareProps} presentation="viewer" />
        )}
      </section>
    )}

    {mode === "results" && (
      <section aria-label="분석 결과 검토" className="flex min-w-0 flex-col gap-2">
        {selectionNotice}
        <SiteWorkspaceResults
          sitePath={sitePath}
          areaLabel={areaLabel}
          areaAnalyses={areaAnalyses}
          analysesKnown={analysesKnown}
          explicitResult={explicitResult}
          explicitDetail={explicitDetail}
          leadDetail={leadDetail ?? null}
          facts={facts}
          canCreateAnalysis={canCreateAnalysis}
          scopedCompareHref={scopedCompareHref}
          visualContext={selectedWorkAreaId && visualContext ? { workAreaId: selectedWorkAreaId, ...visualContext } : null}
        />
      </section>
    )}
  </>);

  return <SiteWorkspaceWorkbench
    contextControls={contextControls}
    catalog={catalog}
    catalogLabel="작업공간 목록"
    stage={stage}
    inspector={inspector}
    inspectorId="workspace-inspector"
    inspectorLabel="작업공간 정보"
    detailsHostId="workspace-inspector-details"
    viewerMode={mode !== "results"}
  />;
}
