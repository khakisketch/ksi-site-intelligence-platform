import Link from "next/link";

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
  representativeFacts,
  workspaceCaptureLine,
} from "@/lib/site-workspace-entry";
import { visualLayersForExactSubmission, pairQueryString } from "./site-visual-pair";
import { observationPrecisionOf } from "@/lib/site-workspace-entry";
import { inspectionOutcomeLabel } from "@/lib/site-windowed-pixel-viewer";
import type {
  PreparedWindowJob,
  WindowedViewerLayer,
} from "@/lib/site-windowed-pixel-viewer";
import { capturePeriodTitle, dataKindLabel } from "@/lib/operator-language";
import { formatKoreanDate } from "@/lib/datetime";
import { SiteSpatialOverview, type SiteSpatialAssetsState } from "./SiteSpatialOverview";
import { SiteAreaNextActionNav, resolveSiteAreaNextAction } from "./SiteAreaNextAction";
import { SiteExploreCanvas, type ExploreCaptureOption } from "./SiteExploreCanvas";
import { SiteWorkspaceCompare } from "./SiteWorkspaceCompare";
import { SiteDisplayLegend } from "./SiteDisplayLegend";
import { SiteWorkspaceResults } from "./SiteWorkspaceResults";
import { SiteWindowedPixelCompare, SiteWindowedPixelViewer } from "./SiteWindowedPixelViewer";
import {
  analysesForArea,
  disambiguatedAreaNames,
  extractSimpleRing,
  selectableGeometry,
} from "./site-spatial";

const WORKSPACE_MODES: ReadonlyArray<{ key: WorkspaceMode; label: string }> = [
  { key: "explore", label: "단일 시점" },
  { key: "compare", label: "두 시점 비교" },
  { key: "results", label: "분석 결과" },
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
  const baselineFact = comparison.status === "ready" ? comparison.baseline : null;
  const currentFact = comparison.status === "ready" ? comparison.current : null;
  const visualAFact = visualPair.status === "ready" ? visualPair.sideA : null;
  const visualBFact = visualPair.status === "ready" ? visualPair.sideB : null;
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
  // 시각 쌍 한쪽의 층 전환 주소 — 같은 구역에서 그쪽만 정확한 참조로
  // 바꾼다. 다른 쪽·구역·모드는 그대로 둔다(정식 쌍은 받는 쪽이 재대조한다).
  const visualLayerHref = (side: "A" | "B", assetRef: string): string => {
    if (!selectedWorkAreaId) return sitePath;
    const query = new URLSearchParams();
    query.set("mode", "compare");
    query.set("workAreaId", selectedWorkAreaId);
    if (side === "A") {
      query.set("visualAAssetRef", assetRef);
      if (visualContext) query.set("visualBAssetRef", visualContext.visualBAssetRef);
    } else {
      if (visualContext) query.set("visualAAssetRef", visualContext.visualAAssetRef);
      query.set("visualBAssetRef", assetRef);
    }
    return `${sitePath}?${query.toString()}`;
  };
  const selectedCatalog = mode === "explore" ? catalogAssets.find((item) => item.assetRef === selectedAssetRef) ?? null : null;
  const compareProps = {
    sitePath, areas, selectedWorkAreaId, catalogAssets,
    projectionState: projectionState === "not-requested" ? "unavailable" as const : projectionState,
    workspaceHasMore, baselineRequestedRef, currentRequestedRef, resolution: comparison,
    visualARequestedRef, visualBRequestedRef, visualPair,
    canCreateAnalysis, canCreateWorkOrder, scopedCompareHref, exploreHref, facts,
  };
  return <div className="flex min-w-0 flex-col gap-3">
    <SiteExploreCanvas
      sitePath={sitePath} areas={areas} selectedWorkAreaId={selectedWorkAreaId}
      captureOptions={captureOptions} selectedCaption={mode === "explore" ? selectedCaption : null}
      coverageNote={null}
      compareHref={mode === "explore" && selected ? `${sitePath}?mode=compare&workAreaId=${encodeURIComponent(selected.workAreaId)}${visualContext ? `&visualAAssetRef=${encodeURIComponent(visualContext.visualAAssetRef)}&visualBAssetRef=${encodeURIComponent(visualContext.visualBAssetRef)}` : ""}` : null}
      mode={mode}
      actions={selected && exploreNextAction ? (
        <SiteAreaNextActionNav sitePath={sitePath} workAreaId={selected.workAreaId}
          action={exploreNextAction} archived={selected.status === "ARCHIVED"}
          canRegisterOrCompare={canCreateWorkOrder && selected.status === "ACTIVE" || canCreateAnalysis && selected.status === "ACTIVE"}
          label="탐색 다음 행동" compact />
      ) : undefined}
      observationControls={mode === "compare" && areasKnown ? <SiteWorkspaceCompare {...compareProps} presentation="controls" /> : undefined}
      layers={mode === "explore" && exploreLayers.length > 0 ? <nav aria-label="자료 층 전환" className="flex flex-wrap gap-1 lg:flex-col">
        {exploreLayers.map((item) => <Link key={item.assetRef}
          href={`${sitePath}?workAreaId=${encodeURIComponent(selectedWorkAreaId!)}&assetRef=${encodeURIComponent(item.assetRef)}`}
          aria-current={item.assetRef === (selectedAssetRef ?? exploreLayers[0]?.assetRef) ? "true" : undefined}
          className={`tap-target rounded-md px-2 py-2 text-[12.5px] ${item.assetRef === (selectedAssetRef ?? exploreLayers[0]?.assetRef) ? "bg-sunk font-bold" : "text-ink-2"}`}>
          {item.kindLabel}
        </Link>)}
      </nav> : mode === "compare" && baselineFact && currentFact ? <div className="flex flex-col gap-3">
        {([{ label: "기준 자료", fact: baselineFact, id: "workspace-baseline-layer-controls" }, { label: "비교 자료", fact: currentFact, id: "workspace-current-layer-controls" }] as const).map((slot) => <nav key={slot.id} aria-label={`${slot.label} 표시 레이어`} className="flex flex-col gap-1">
          <p className="text-[12px] text-ink-muted">{slot.label}</p>
          <div id={slot.id} />
          {viewerLayersForEpoch(catalogAssets, slot.fact.observationEpochId).length === 1 && <p className="text-[12px]">{dataKindLabel(slot.fact.kind)}</p>}
          <noscript><p className="text-[12px]">레이어 전환은 JavaScript가 필요합니다. 원본 정보는 비교 자료·조건에서 확인할 수 있습니다.</p></noscript>
        </nav>)}
      </div> : mode === "compare" && visualAFact && visualBFact ? <div className="flex flex-col gap-3">
        {([{ label: "관측 A", fact: visualAFact, id: "workspace-visual-a-layer-controls" }, { label: "관측 B", fact: visualBFact, id: "workspace-visual-b-layer-controls" }] as const).map((slot) => {
          const exactLayers = visualLayersForExactSubmission(catalogAssets, slot.fact);
          return <nav key={slot.id} aria-label={`${slot.label} 표시 레이어`} className="flex flex-col gap-1">
            <p className="text-[12px] text-ink-muted">{slot.label} · {dataKindLabel(slot.fact.kind)} · 등록 버전 {slot.fact.revision}</p>
            <div id={slot.id} />
            {exactLayers.length <= 1 && <p className="text-[12px]">{dataKindLabel(slot.fact.kind)}</p>}
            <noscript><p className="text-[12px]">레이어 전환은 JavaScript가 필요합니다. 원본 정보는 비교 자료·조건에서 확인할 수 있습니다.</p></noscript>
          </nav>;
        })}
      </div> : undefined}
      detail={selectedCatalog ? <>
        <p className="break-words font-semibold">{exploreHeading ?? dataKindLabel(selectedCatalog.kind)}</p>
        <dl className="grid gap-2">
          <div><dt className="text-ink-muted">등록 파일명</dt><dd className="break-all">{selectedCatalog.declared.fileName}</dd></div>
          <div><dt className="text-ink-muted">파일 검사</dt><dd>{inspectionOutcomeLabel(selectedCatalog.inspection.outcome)}</dd></div>
          <div><dt className="text-ink-muted">관측 위치 기준</dt><dd>{selectedCatalog.inspection.raster?.observedCrsIdentifier ?? "확인 불가"}</dd></div>
          <div><dt className="text-ink-muted">수직 기준</dt><dd>{selectedCatalog.inspection.raster?.observedVerticalReference?.identifier ?? "확인 불가"}</dd></div>
          <div><dt className="text-ink-muted">분석 적합성</dt><dd>{selectedCatalog.analysisStatus === "NOT_EVALUATED" ? "자료 목록에서는 분석 적합성을 평가하지 않습니다. 결과 화면에서 입력별 조건을 확인하세요." : "분석 기록에서 확인하세요."}</dd></div>
        </dl>
        <Link className="tap-target underline" href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(selectedCatalog.workAreaId)}&assetRef=${encodeURIComponent(selectedCatalog.assetRef)}`}>원본 메타데이터 확인</Link>
        <details><summary className="tap-target cursor-pointer">버전·식별 정보</summary><p className="break-all">등록 버전 {selectedCatalog.revision} · {selectedCatalog.submissionRef}</p><p className="break-all">{selectedCatalog.assetRef}</p></details>
      </> : undefined}
      toolbar={<nav aria-label="공간 작업 방식" className="inline-flex max-w-full flex-wrap gap-1 rounded-lg bg-sunk p-1">
      {WORKSPACE_MODES.map((option) => {
        const active = option.key === mode;
        return (
          <Link
            key={option.key}
            href={modeHref(sitePath, option.key, scope, visualContext)}
            aria-current={active ? "page" : undefined}
            className={`tap-target inline-flex items-center rounded-md px-3 py-1.5 text-[13px] break-keep ${
              active ? "bg-surface font-bold" : "text-ink-2"
            }`}
          >
            {option.label}
          </Link>
        );
      })}
      </nav>}
    >

    {mode === "explore" && (<>
      {selectedCatalog && <h3 className="text-[13px] font-semibold">{dataKindLabel(selectedCatalog.kind)}</h3>}
      {/* 탐색 첫 화면은 실제 화면이 먼저다. 측정 전 2042자(390px 기준)가
          앞을 막던 기하 개요·등록 수·행동벽은 아래 '자료·범위 상세'에 둔다. */}
      {/* 다음 행동은 그림보다 위 — 그림이 길어 아래로 밀리면 처음 보는
          사람은 무엇을 할 수 있는지 화면을 끝까지 스크롤해야 안다. */}
        {selected && viewerJobsState !== "not-requested" ? (
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
          />
        ) : (
          <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
            {!selected
              ? "작업구역을 확인할 수 없어 화면을 고르지 않았습니다. 아래 상세에서 목록을 확인하세요."
              : viewerJobsState === "denied"
                ? "준비 기록을 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요."
                : "준비 기록을 불러오지 못했습니다. 잠시 후 아래 상세에서 다시 확인하세요."}
          </p>
        )}
      <SiteDisplayLegend />
      {/* 기하 개요·등록 수·행동벽은 두 번째 자리다. 정보는 지우지 않고 펼침에 둔다. */}
      <details className="rounded-lg border border-line bg-surface px-4 py-3">
        <summary className="tap-target cursor-pointer text-[13px] font-semibold">자료·범위 상세</summary>
        <div className="mt-2 flex flex-col gap-3">
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
            hideAreaForm
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
        </div>
      </details>
    </>)}

    {mode === "compare" && !areasKnown && <p role="status" className="text-[12.5px] leading-5 text-ink-2">작업구역 목록을 확인하지 못했습니다. 잠시 후 다시 확인하세요. 빈 목록으로 단정하지 않습니다.</p>}
    {mode === "compare" && areasKnown && (<>
      {comparison.status !== "ready" && visualPair.status !== "ready" && <SiteWorkspaceCompare {...compareProps} presentation="viewer" />}
      {/* 비교의 창 단위 픽셀 보기 — 두 칸은 독립된 어댑터다. 동기화 비교가
          아니라 각 창의 실제 픽셀을 같은 평면에 둔다. */}
      {selected && comparison.status === "ready" && baselineFact && currentFact && viewerJobsState !== "not-requested" && (
        <SiteWindowedPixelCompare
          siteId={facts.siteId}
          workAreaId={selected.workAreaId}
          baselineHeading={viewerHeadingFor(baselineFact)}
          currentHeading={viewerHeadingFor(currentFact)}
          baselineLayers={viewerLayersForEpoch(catalogAssets, baselineFact.observationEpochId)}
          currentLayers={viewerLayersForEpoch(catalogAssets, currentFact.observationEpochId)}
          baselineCrs={catalogAssets.find((item) => item.assetRef === baselineFact.assetRef)?.inspection.raster?.observedCrsIdentifier ?? null}
          currentCrs={catalogAssets.find((item) => item.assetRef === currentFact.assetRef)?.inspection.raster?.observedCrsIdentifier ?? null}
          jobs={[...jobs]}
          jobsState={viewerJobsState}
          canRead={viewerCanRead}
          canRequest={viewerCanRequest}
          requestsHref={requestsHref}
          workAreaRing={workAreaRing}
          workAreaCrs={workAreaCrs}
          hideLayerControls
          baselineAssetRef={baselineFact.assetRef}
          currentAssetRef={currentFact.assetRef}
          layerControlsInRail
        />
      )}
      {comparison.status === "ready" && <details className="rounded-lg border border-line p-3">
        <summary className="tap-target cursor-pointer text-[13px] font-semibold">비교 자료·조건 확인</summary>
        <div className="mt-2"><SiteWorkspaceCompare {...compareProps} presentation="viewer" /></div>
      </details>}
      {/* 시각 쌍(독립 보기) — 날짜만·시점 미상 관측도 나란히 둔다. 시간 순서·
          정합을 주장하지 않으며, 각 칸은 독립된 카메라로만 본다. */}
      {selected && visualPair.status === "ready" && visualAFact && visualBFact && viewerJobsState !== "not-requested" && (
        <SiteWindowedPixelCompare
          siteId={facts.siteId}
          workAreaId={selected.workAreaId}
          baselineRoleLabel="관측 A"
          currentRoleLabel="관측 B"
          baselineHeading={viewerHeadingFor(visualAFact)}
          currentHeading={viewerHeadingFor(visualBFact)}
          baselineLayers={visualLayersForExactSubmission(catalogAssets, visualAFact)}
          currentLayers={visualLayersForExactSubmission(catalogAssets, visualBFact)}
          baselineCrs={catalogAssets.find((item) => item.assetRef === visualAFact.assetRef)?.inspection.raster?.observedCrsIdentifier ?? null}
          currentCrs={catalogAssets.find((item) => item.assetRef === visualBFact.assetRef)?.inspection.raster?.observedCrsIdentifier ?? null}
          jobs={[...jobs]}
          jobsState={viewerJobsState}
          canRead={viewerCanRead}
          canRequest={viewerCanRequest}
          requestsHref={requestsHref}
          workAreaRing={workAreaRing}
          workAreaCrs={workAreaCrs}
          hideLayerControls
          baselineAssetRef={visualAFact.assetRef}
          currentAssetRef={visualBFact.assetRef}
          layerControlsInRail
          baselineLayerControlsTargetId="workspace-visual-a-layer-controls"
          currentLayerControlsTargetId="workspace-visual-b-layer-controls"
          baselineLayerHref={visualLayerHref("A", visualAFact.assetRef)}
          currentLayerHref={visualLayerHref("B", visualBFact.assetRef)}
          baselineLayerParam="visualAAssetRef"
          currentLayerParam="visualBAssetRef"
        />
      )}
      {visualPair.status === "ready" && <p><Link href={scopedCompareHref} className="btn">이 쌍으로 분석 조건 확인</Link></p>}
      {visualPair.status === "ready" && <details className="rounded-lg border border-line p-3">
        <summary className="tap-target cursor-pointer text-[13px] font-semibold">독립 보기 자료·조건 확인</summary>
        <div className="mt-2"><SiteWorkspaceCompare {...compareProps} presentation="viewer" /></div>
      </details>}
      <SiteDisplayLegend />
    </>)}

    {mode === "results" && (
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
    )}
    </SiteExploreCanvas>
  </div>;
}
