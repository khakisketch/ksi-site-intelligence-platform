import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { SiteAoiEditor } from "./SiteAoiEditor";
import { SiteHeader } from "./SiteHeader";
import type { SiteSpatialAssetsState } from "./SiteSpatialOverview";
import { SiteWorkspaceShell } from "./SiteWorkspaceShell";
import { buildWorkspaceServerFacts } from "./site-workspace-server-facts";
import { SiteStartGuidance } from "./SiteStartGuidance";
import { SiteTransitionActions } from "./SiteTransitionActions";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { ExternalObservationHistory } from "./observations/ExternalObservationHistory";
import { EmptyState } from "@/components/ui/EmptyState";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { SITE_STATUS_LABEL, humanizeApiError } from "@/lib/core-api/labels";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { listSiteExternalVolumeHistory } from "@/lib/core-api/external-result-workflow";
import { getSite } from "@/lib/core-api/sites";
import { listSpatialAssets } from "@/lib/core-api/spatial-assets";
import { getAnalysis, listAnalyses, type AnalysisView } from "@/lib/core-api/analysis";
import { listSpatialDataRequests } from "@/lib/core-api/spatial-data-requests";
import { listSpatialWorkspaceObservations, type SpatialWorkspacePage } from "@/lib/core-api/spatial-workspace";
import {
  parseWorkspaceMode,
  parseWorkspaceScopeId,
  resolveExplicitComparison,
  resolveExplicitResult,
  resolveOrdinaryEntry,
  type ExplicitComparisonResolution,
  type ExplicitResultResolution,
  type OrdinaryEntryResolution,
} from "@/lib/site-workspace-entry";
import { toPreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { formatKoreanDate, formatKoreanDateTime } from "@/lib/datetime";
import { siteDetailDocumentTitle } from "@/lib/site-detail-title";
import { normalizeSiteTab, type SiteTabKey } from "@/lib/site-epochs";
import { presentWorkOrder } from "@/app/field/work-order-stage";
import { parseScopeId, pickFootprintAsset, resolveSelectedAssetRef, resolveSelectedWorkAreaId } from "./site-spatial";

const getSiteForDetail = cache(getSite);

export async function generateMetadata({ params }: { params: Promise<{ siteId: string }> }): Promise<Metadata> {
  const { siteId } = await params;
  try {
    const site = await getSiteForDetail(siteId);
    return { title: siteDetailDocumentTitle(site.name) };
  } catch {
    return { title: "현장 상세 · KSI" };
  }
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="overflow-hidden rounded-lg border border-line bg-surface">
    <div className="border-b border-line px-4 py-2.5"><h2 className="text-[13.5px] font-bold tracking-tight break-keep">{title}</h2></div>
    <div className="px-4 py-3">{children}</div>
  </section>;
}

function tabHref(tab: SiteTabKey): string {
  switch (tab) {
    case "analysis": return "analysis";
    case "materials": return "spatial-assets";
    default: return "";
  }
}

function SiteTabLink({ siteId, tab, label, detail, href }: { siteId: string; tab: SiteTabKey; label: string; detail: string; href?: string }) {
  return <SectionCard title={label}>
    <p className="text-[12.5px] leading-5 break-keep text-ink-2">{detail}</p>
    <Link href={href ?? `/sites/${encodeURIComponent(siteId)}/${tabHref(tab)}`} className="btn mt-3 w-fit">{label} 열기</Link>
  </SectionCard>;
}

export default async function SiteDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ section?: string | string[]; tab?: string | string[]; workAreaId?: string | string[]; assetRef?: string | string[]; mode?: string | string[]; baselineAssetRef?: string | string[]; currentAssetRef?: string | string[]; analysisId?: string | string[] }>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const firstValue = (value: string | string[] | undefined): string | undefined =>
    Array.isArray(value) ? value[0] : value;
  const tab = normalizeSiteTab(firstValue(query.section) ?? firstValue(query.tab));
  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    site = await getSiteForDetail(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    const message = error instanceof CoreApiError
      ? humanizeApiError(error.code, error.status, error.serverMessage)
      : "요청을 처리하지 못했습니다.";
    return <div className="flex flex-col gap-4 p-4 sm:p-5"><ErrorState message={message} retryable /></div>;
  }

  const [canTransitionResult, canCreateResult, canApproveResult, canReadDataResult, canRequestDataResult, areasResult, ordersResult, historyResult] = await Promise.allSettled([
    hasAllPermissions("SITES_WRITE"),
    hasAllPermissions("WORK_ORDERS_WRITE"),
    hasAllPermissions("SITES_AUTONOMY_APPROVE"),
    hasAllPermissions("SPATIAL_DATA_READ"),
    hasAllPermissions("SPATIAL_DATA_REQUEST"),
    listWorkAreas(site.siteId, { includeArchived: true }),
    listObservationWorkOrders(site.siteId),
    listSiteExternalVolumeHistory(site.siteId, { limit: 50 }),
  ]);
  const canTransition = canTransitionResult.status === "fulfilled" && canTransitionResult.value;
  const canCreateWorkOrder = canCreateResult.status === "fulfilled" && canCreateResult.value;
  const canApproveAutonomy = canApproveResult.status === "fulfilled" && canApproveResult.value;
  const canReadData = canReadDataResult.status === "fulfilled" && canReadDataResult.value;
  const canRequestData = canRequestDataResult.status === "fulfilled" && canRequestDataResult.value;
  const allAreas = areasResult.status === "fulfilled" ? areasResult.value.workAreas : [];
  const areas = allAreas.filter((area) => area.status === "ACTIVE");
  const areaNames = new Map(allAreas.map((area) => [area.workAreaId, area.name]));
  const siteStartCounts = {
    workAreaCount: areasResult.status === "fulfilled" ? areas.length : null,
    observationWorkOrderCount: ordersResult.status === "fulfilled" ? ordersResult.value.length : null,
    externalResultCount: historyResult.status === "fulfilled" ? historyResult.value.items.length : null,
    hasMoreExternalResults: historyResult.status === "fulfilled" ? historyResult.value.nextCursor !== null : null,
  };
  const latestExternalReport = historyResult.status === "fulfilled"
    ? historyResult.value.items.flatMap((item) => item.result ? [item.result.reportedAt] : []).toSorted().at(-1) ?? null
    : null;
  const sitePath = `/sites/${encodeURIComponent(site.siteId)}`;
  const status = SITE_STATUS_LABEL[site.status];

  // 기본 탭(현황)의 읽기 전용 공간 확인은 bounded 추가 읽기 2건으로 족하다 —
  // Core 분석 목록 50건 1회, 선택 구역의 공간 자산 20건 1회. 둘 다 실패해도
  // unknown으로 두고 빈 목록으로 단정하지 않는다. 다른 탭에서는 읽지 않는다.
  // 선택 구역은 이미 읽은 관측 작업·분석 목록의 묶임으로 고른다(추가 조회 없음).
  const wantSpatial = tab === "overview";
  const analysesResult = wantSpatial
    ? await listAnalyses(site.siteId, { limit: 50 }).then(
      (page) => ({ ok: true as const, page }),
      () => ({ ok: false as const }),
    )
    : { ok: false as const };
  const analysesPage = analysesResult.ok ? analysesResult.page : null;
  const boundWorkOrderAreaIds = ordersResult.status === "fulfilled"
    ? ordersResult.value.flatMap((order) => Array.isArray(order.workAreaIds) ? order.workAreaIds : [])
    : [];
  const selectedWorkAreaId = wantSpatial && areasResult.status === "fulfilled"
    ? resolveSelectedWorkAreaId(areasResult.value.workAreas, firstValue(query.workAreaId), {
      workOrderAreaIds: boundWorkOrderAreaIds,
      analysisAreaIds: analysesPage?.items.map((item) => item.workAreaId) ?? [],
    })
    : null;
  const assetsResult = wantSpatial
    ? await (selectedWorkAreaId
      ? listSpatialAssets(site.siteId, selectedWorkAreaId, { limit: 50 }).then(
        (page) => ({ ok: true as const, page }),
        (error: unknown) => ({ ok: false as const, denied: error instanceof CoreApiError && error.status === 403 }),
      )
      : Promise.resolve({ ok: false as const, denied: false, skipped: true as const }))
    : { ok: false as const, denied: false, skipped: true as const };
  let assetsState: SiteSpatialAssetsState = { status: "not-requested" };
  if (wantSpatial && selectedWorkAreaId) {
    if (assetsResult.ok) assetsState = { status: "ready", page: assetsResult.page };
    else if (!("skipped" in assetsResult)) assetsState = { status: assetsResult.denied ? "denied" : "unavailable" };
  }
  // SWX-1 프로젝션 읽기 — 선택 구역의 관측×버전 사실과 서버 기본 진입.
  // 실패해도 unknown으로 두고 빈 목록으로 단정하지 않는다. 권한 거부는
  // denied로만 둔다. 이 읽기는 바이트 권한을 만들지 않는다.
  const workspaceResult = wantSpatial
    ? await (selectedWorkAreaId
      ? listSpatialWorkspaceObservations(site.siteId, selectedWorkAreaId, { limit: 50 }).then(
        (page) => ({ ok: true as const, page }),
        (error: unknown) => ({ ok: false as const, denied: error instanceof CoreApiError && error.status === 403 }),
      )
      : Promise.resolve({ ok: false as const, denied: false, skipped: true as const }))
    : { ok: false as const, denied: false, skipped: true as const };
  let workspacePage: SpatialWorkspacePage | null = null;
  if (wantSpatial && selectedWorkAreaId && workspaceResult.ok) workspacePage = workspaceResult.page;
  const projectionState = !wantSpatial || !selectedWorkAreaId
    ? "not-requested" as const
    : workspaceResult.ok
      ? "ready" as const
      : "skipped" in workspaceResult
        ? "not-requested" as const
        : workspaceResult.denied
          ? "denied" as const
          : "unavailable" as const;

  // 창 단위 픽셀 보기(임시 시각화 어댑터)의 준비 기록 — 현재 계정이 읽을 수
  // 있을 때만 최대 50건을 읽는다. 읽기 실패는 denied/unavailable로만 두고
  // 빈 목록으로 단정하지 않는다. 이 읽기는 바이트 권한을 만들지 않으며,
  // 새 준비 요청을 만들지도 않는다.
  const preparedJobsResult = wantSpatial && selectedWorkAreaId && canReadData
    ? await listSpatialDataRequests(site.siteId, selectedWorkAreaId, { limit: 50 }).then(
      (page) => ({ ok: true as const, page }),
      (error: unknown) => ({ ok: false as const, denied: error instanceof CoreApiError && error.status === 403 }),
    )
    : { ok: false as const, denied: false, skipped: true as const };
  const preparedJobsState = !wantSpatial || !selectedWorkAreaId
    ? "not-requested" as const
    : !canReadData
      ? "denied" as const
      : preparedJobsResult.ok
        ? "ready" as const
        : "skipped" in preparedJobsResult
          ? "not-requested" as const
          : preparedJobsResult.denied
            ? "denied" as const
            : "unavailable" as const;
  const preparedJobs = preparedJobsResult.ok
    ? preparedJobsResult.page.items
      .filter((item) => item.siteId === site.siteId && item.workAreaId === selectedWorkAreaId)
      .map(toPreparedWindowJob)
    : [];

  // SWX-1 명시적 진입 — 일반 둘러보기 힌트(workAreaId/assetRef)와 달리,
  // 비교·결과 지시는 정확히 복원하거나 막는다. 조용히 다른 대상으로 바꾸지 않는다.
  const mode = wantSpatial ? parseWorkspaceMode(firstValue(query.mode)) : "explore" as const;
  const facts = wantSpatial
    ? buildWorkspaceServerFacts({
      siteId: site.siteId,
      areas: areasResult.status === "fulfilled" ? areasResult.value.workAreas : [],
      projection: workspacePage
        ? { status: "ready", page: workspacePage }
        : projectionState === "denied"
          ? { status: "denied" }
          : { status: "unavailable" },
      analyses: analysesPage?.items ?? null,
      workAreaId: selectedWorkAreaId,
    })
    : null;
  const ordinaryEntry: OrdinaryEntryResolution = facts
    ? resolveOrdinaryEntry(facts)
    : { status: "no-server-default", reason: "NO_PROJECTION", detail: null, tiedObservationEpochIds: [], defaultNotOnPage: false };

  // 선택 자료 — 명시 힌트가 있으면 그대로, 없으면 서버 기본의 표시 버전을
  // 카탈로그에서 확인하고, 그것도 없으면 첫 검사 footprint(전이 선택)로 둔다.
  // 전이 선택은 기본인 척하지 않는다(진입 패널이 밝힌다).
  const hintedAssetRef = assetsState.status === "ready"
    ? resolveSelectedAssetRef(assetsState.page, firstValue(query.assetRef))
    : null;
  const serverViewAssetRef = ordinaryEntry.status === "ready" ? ordinaryEntry.observation.viewAssetRef : null;
  const serverViewInCatalog = serverViewAssetRef !== null && assetsState.status === "ready"
    && assetsState.page.assets.some((item) => item.assetRef === serverViewAssetRef)
    ? serverViewAssetRef
    : null;
  const selectedAssetRef = hintedAssetRef
    ?? serverViewInCatalog
    ?? (assetsState.status === "ready"
      ? pickFootprintAsset(assetsState.page.assets, null)?.assetRef ?? null
      : null);
  const transitionalSelection = hintedAssetRef === null && serverViewInCatalog === null && selectedAssetRef !== null;
  // 명시된 workAreaId/assetRef가 조회 범위 안에 없으면 알린다 — 조용히 다른
  // 대상을 보여주지 않는다. 원문 id는 그대로 두지 않고(범위 밖 값) 공지만 둔다.
  const requestedWorkAreaId = wantSpatial ? parseScopeId(firstValue(query.workAreaId)) : null;
  const requestedAssetRef = assetsState.status === "ready" ? parseScopeId(firstValue(query.assetRef)) : null;
  const scopeNotice = wantSpatial && (
    (requestedWorkAreaId !== null && !allAreas.some((area) => area.workAreaId === requestedWorkAreaId))
    || (requestedAssetRef !== null && selectedAssetRef !== requestedAssetRef)
  );
  // 헤더 직접 링크용 검증 범위 — 어느 탭에서도 추가 조회 없이 승인된 현행
  // 활성 구역만 싣는다. 원문 쿼리를 그대로 두지 않고, 조용히 다른 구역으로
  // 바꾸지도 않는다. 공간 탭에서는 이미 고른 선택을 그대로 쓴다.
  const activeWorkAreaIds = new Set(allAreas.filter((area) => area.status === "ACTIVE").map((area) => area.workAreaId));
  const spatialSelectedValid = wantSpatial && selectedWorkAreaId && activeWorkAreaIds.has(selectedWorkAreaId)
    ? selectedWorkAreaId
    : null;
  const explicitScopeValid = (() => {
    const raw = parseScopeId(firstValue(query.workAreaId));
    return raw && activeWorkAreaIds.has(raw) ? raw : null;
  })();
  const headerWorkAreaId = spatialSelectedValid ?? explicitScopeValid;
  const headerAssetRef = wantSpatial && headerWorkAreaId && selectedWorkAreaId === headerWorkAreaId
    ? selectedAssetRef
    : null;

  const rawBaselineAssetRef = wantSpatial && mode === "compare" ? firstValue(query.baselineAssetRef) : undefined;
  const rawCurrentAssetRef = wantSpatial && mode === "compare" ? firstValue(query.currentAssetRef) : undefined;
  const baselineRequestedRef = parseWorkspaceScopeId(rawBaselineAssetRef ?? null);
  const currentRequestedRef = parseWorkspaceScopeId(rawCurrentAssetRef ?? null);
  let comparison: ExplicitComparisonResolution | { status: "prompt" } = { status: "prompt" };
  // 프로젝션 준비 여부와 무관하게 명시 지시는 판정한다 — 실패하면 막는다.
  // 준비되지 않은 목록으로 조용히 바꾸지 않는다.
  if (facts && mode === "compare" && selectedWorkAreaId) {
    if (rawBaselineAssetRef != null || rawCurrentAssetRef != null) {
      comparison = resolveExplicitComparison(facts, {
        workAreaId: selectedWorkAreaId,
        baselineAssetRef: rawBaselineAssetRef,
        currentAssetRef: rawCurrentAssetRef,
      });
    }
  }
  const rawAnalysisId = wantSpatial && mode === "results" ? firstValue(query.analysisId) : undefined;
  let explicitResult: ExplicitResultResolution | null = null;
  let explicitDetail: AnalysisView | null = null;
  // 결과 모드의 첫 기록이 '무엇과 무엇을 비교했나'를 말할 수 있게, 목록에
  // 없는 정확한 선택자를 기존 상세 경로로 한 건만 읽는다. N+1 전체 조회를
  // 하지 않으며, 실패·불일치는 조용히 내려놓고 목록 렌더로 둔다(막지 않는다).
  let leadDetail: AnalysisView | null = null;
  if (facts && mode === "results" && rawAnalysisId == null && selectedWorkAreaId) {
    const areaItems = analysesPage?.items.filter((item) => item.workAreaId === selectedWorkAreaId) ?? [];
    const leadId = areaItems[0]?.analysisId ?? null;
    if (leadId) {
      try {
        const detail = await getAnalysis(site.siteId, leadId);
        if (detail.analysisId === leadId && detail.siteId === site.siteId && detail.workAreaId === selectedWorkAreaId) {
          leadDetail = detail;
        }
      } catch {
        leadDetail = null;
      }
    }
  }
  if (facts && rawAnalysisId != null) {
    // 목록 항목에는 정확한 선택자가 없어 상세(Core 기존 경로)로 복원한다.
    // 실패하면 막는다 — 최신·다른 기록으로 바꾸지 않는다.
    try {
      const parsed = parseWorkspaceScopeId(rawAnalysisId);
      if (!parsed) {
        explicitResult = resolveExplicitResult({ ...facts, analyses: [] }, { analysisId: rawAnalysisId });
      } else {
        const detail = await getAnalysis(site.siteId, parsed);
        explicitDetail = detail;
        explicitResult = resolveExplicitResult({
          ...facts,
          analyses: [{
            analysisId: detail.analysisId,
            workAreaId: detail.workAreaId,
            baseline: detail.baseline,
            current: detail.current,
          }],
        }, { analysisId: parsed });
        if (explicitResult.status !== "ready") explicitDetail = null;
      }
    } catch {
      explicitResult = resolveExplicitResult({ ...facts, analyses: [] }, { analysisId: rawAnalysisId });
      explicitDetail = null;
    }
  }

  return <div className="flex flex-col">
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab={tab}
      latestExternalReportAt={latestExternalReport}
      latestExternalReportKnown={historyResult.status === "fulfilled"}
      canCreateWorkOrder={canCreateWorkOrder}
      canEditAoi={canTransition}
      scopedWorkAreaId={headerWorkAreaId}
      scopedAssetRef={headerAssetRef}
    />
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {tab === "overview" && <div className="flex flex-col gap-4">
        <SiteWorkspaceShell
          sitePath={sitePath}
          mode={mode}
          areas={areasResult.status === "fulfilled" ? areasResult.value.workAreas : []}
          areasKnown={areasResult.status === "fulfilled"}
          orders={ordersResult.status === "fulfilled" ? ordersResult.value : null}
          analyses={analysesPage?.items ?? null}
          analysesKnown={analysesPage !== null}
          analysesHasMore={analysesPage?.nextCursor !== null && analysesPage !== null}
          legacy={historyResult.status === "fulfilled" ? historyResult.value.items : null}
          legacyHasMore={historyResult.status === "fulfilled" && historyResult.value.nextCursor !== null}
          assetsState={assetsState}
          selectedWorkAreaId={selectedWorkAreaId}
          selectedAssetRef={selectedAssetRef}
          canCreateWorkOrder={canCreateWorkOrder}
          // canTransition은 SITES_WRITE 승인 — 분석 요청 진입에만 쓰고 등록 권한과 섞지 않는다.
          canCreateAnalysis={canTransition}
          scopeNotice={scopeNotice}
          facts={facts ?? { siteId: site.siteId, authorizedWorkAreaIds: [], entryDefault: null, observations: [], analyses: [] }}
          ordinaryEntry={ordinaryEntry}
          projectionState={projectionState}
          workspaceHasMore={workspacePage?.hasMore ?? false}
          transitionalSelection={transitionalSelection}
          baselineRequestedRef={baselineRequestedRef}
          currentRequestedRef={currentRequestedRef}
          comparison={comparison}
          explicitResult={explicitResult}
          explicitDetail={explicitDetail}
          leadDetail={leadDetail}
          scopedCompareHref={selectedWorkAreaId && activeWorkAreaIds.has(selectedWorkAreaId) ? `${sitePath}/analysis?workAreaId=${encodeURIComponent(selectedWorkAreaId)}` : `${sitePath}/analysis`}
          preparedJobs={preparedJobs}
          jobsState={preparedJobsState}
          canReadData={canReadData}
          canRequestData={canRequestData}
        />
        <SiteStartGuidance
          siteId={site.siteId}
          {...siteStartCounts}
          // 실제 공간 작업공간 선택이 있을 때만 건수 요약을 둔다 — 다음 행동은
          // 작업공간이 이미 안내한다. unknown·빈 목록 복구는 그대로 둔다.
          hasWorkspaceActions={selectedWorkAreaId !== null}
        />
      </div>}

      {tab === "analysis" && <div className="flex flex-col gap-4">
        <SiteTabLink siteId={site.siteId} tab="analysis" label="분석·검토" detail="같은 구역의 기준 자료와 비교할 자료를 고르고, 계산 결과와 담당자 검토 상태를 확인합니다." href={headerWorkAreaId ? `${sitePath}/analysis?workAreaId=${encodeURIComponent(headerWorkAreaId)}` : `${sitePath}/analysis`} />
        {/* 외부 비교 기록은 시스템이 계산한 변화 분석과 다른 출처의 별도 목록이다 —
            한 카드 안에서 합치지 않고 구분된 하위 기록으로만 둔다. */}
        <SectionCard title="외부 비교 기록">
          <p className="text-[12.5px] leading-5 text-ink-2">별도로 등록된 외부 비교 결과입니다. 시스템에서 계산한 지형 변화는 분석·검토에서 확인하세요. 두 기록은 서로 다른 결과입니다.</p>
          {historyResult.status === "rejected" ? <ErrorState message="외부 비교 기록을 불러오지 못했습니다." retryable /> : historyResult.value.items.length === 0 ? <EmptyState title="조회된 외부 비교 기록이 없습니다" description="시스템에서 계산한 지형 변화는 분석·검토에서 확인하세요. 이 목록은 별도로 등록된 비교 기록입니다." action={{ label: "분석·검토 열기", href: `${sitePath}/analysis` }} /> : <ExternalObservationHistory siteId={site.siteId} items={historyResult.value.items} workAreaNames={areaNames} />}
          <div className="mt-3"><Link href={`${sitePath}/observations`} className="btn">외부 비교 기록 열기</Link></div>
        </SectionCard>
      </div>}

      {tab === "materials" && <SiteTabLink siteId={site.siteId} tab="materials" label="자료" detail="자료 종류와 촬영 시점으로 파일을 찾고, 제출·파일 검사 상태를 확인합니다. 파일 받기와 분석 사용 가능 여부는 별도로 확인합니다." href={`${sitePath}/spatial-assets${headerWorkAreaId ? `?workAreaId=${encodeURIComponent(headerWorkAreaId)}${headerAssetRef ? `&assetRef=${encodeURIComponent(headerAssetRef)}` : ""}` : ""}`} />}

      {tab === "manage" && <div className="flex flex-col gap-4">
        <SectionCard title="작업구역">
          {areasResult.status === "rejected" ? <ErrorState message="작업구역을 불러오지 못했습니다." retryable /> : areas.length === 0 ? <EmptyState title="등록된 작업구역이 없습니다" description="자료를 연결할 작업구역을 먼저 확인하세요." action={{ label: "작업구역 확인", href: `${sitePath}/work-areas` }} /> : <ul className="divide-y divide-line">{areas.map((area) => <li key={area.workAreaId} className="py-3 text-[13px]">
            <p className="break-words font-semibold">{area.name || "이름을 확인할 수 없는 구역"}</p>
            <p className="mt-1 text-[12px] text-ink-2">등록 {formatKoreanDateTime(area.createdAt, { dateStyle: "medium", timeStyle: "short" })}</p>
            <details className="mt-1 text-[12px] text-ink-2"><summary className="tap-target cursor-pointer">구역 식별 정보</summary><p className="break-all font-mono">{area.workAreaId}</p></details>
          </li>)}</ul>}
          <div className="mt-3 flex flex-wrap gap-2"><Link href={`${sitePath}/work-areas`} className="btn">작업구역 관리</Link><Link href={`${sitePath}/spatial-assets`} className="btn">자료 보기</Link><Link href={`${sitePath}/spatial-data-requests`} className="btn">구역 자료 준비</Link></div>
        </SectionCard>
        <SectionCard title="현장 전체 경계 · 선택 설정">
          <div id="site-aoi" className="scroll-mt-5">
          {site.aoi ? <AoiPolygonMap value={site.aoi.vertices} readOnly /> : site.status === "UNMAPPED" && canTransition ? <ResponsiveActionBoundary action="SITE_DEVICE_TRANSITION" reason={`${site.name}의 전체 경계 편집은 노트북에서 진행하세요. 이 설정 없이도 작업구역의 관측 자료를 확인할 수 있습니다.`}><SiteAoiEditor siteId={site.siteId} siteFrame={site.siteFrame} /></ResponsiveActionBoundary> : <EmptyState compact title="현장 전체 경계는 아직 설정하지 않았습니다" description="전체 경계는 선택 설정입니다. 관측 자료는 각 작업구역에 연결해 사용합니다." />}
          </div>
        </SectionCard>
        <SectionCard title={`현장 상태 · ${status.label}`}>
          {canTransition ? <details><summary className="tap-target cursor-pointer text-[13px] font-semibold">관리자 상태 전이</summary><div className="mt-3"><SiteTransitionActions siteId={site.siteId} status={site.status} resumeTarget={site.resumeTarget} canApproveAutonomy={canApproveAutonomy} /></div></details> : <ActionUnavailable label="현장 상태 변경" description="현재 계정으로는 현장 상태를 변경할 수 없습니다. 현장 쓰기 권한이 있는 담당자에게 문의하세요." />}
          <dl className="mt-3 grid gap-2 border-t border-line pt-3 text-[12px] sm:grid-cols-2"><div><dt className="text-ink-muted">등록</dt><dd>{formatKoreanDate(site.registeredAt)}</dd></div><div><dt className="text-ink-muted">최근 갱신</dt><dd>{formatKoreanDate(site.updatedAt)}</dd></div></dl>
          <details className="mt-2 text-[12px] text-ink-2"><summary className="tap-target cursor-pointer font-semibold">좌표계·변환 정보</summary><dl className="mt-1 grid gap-1"><div><dt className="text-ink-muted">좌표계</dt><dd>{site.siteFrame.crs}</dd></div><div><dt className="text-ink-muted">변환 버전</dt><dd>{site.siteFrame.transformVersion}</dd></div></dl></details>
        </SectionCard>
      </div>}

      {tab === "work-orders" && <div className="flex flex-col gap-4">
        <SectionCard title="관측 작업">
          {ordersResult.status === "rejected" ? <ErrorState message="관측 작업을 불러오지 못했습니다." retryable /> : ordersResult.value.length === 0 ? <EmptyState title="등록된 관측 작업이 없습니다" description="새 관측 작업이 생성되면 이 목록에 표시됩니다." /> : <ul className="divide-y divide-line">{ordersResult.value.map((order) => {
            const presentation = presentWorkOrder(order.status, order.executionMode);
            const names = order.workAreaIds.map((id) => areaNames.get(id) || "이름을 확인할 수 없는 구역");
            return <li key={order.workOrderId} className="py-3">
              <Link href={`/field/work-orders/${encodeURIComponent(order.workOrderId)}`} className="tap-target flex flex-wrap items-start justify-between gap-3">
                <span className="min-w-0 flex-1 break-words"><span className="block text-[13px] font-semibold">{order.name || "이름을 확인할 수 없는 관측 작업"}</span><span className="mt-1 block text-[12px] text-ink-2">{names.length ? names.join(" · ") : "연결된 작업구역 없음"} · {order.cycleNumber}회차</span><span className="mt-1 block text-[12px] text-ink-muted">갱신 {formatKoreanDateTime(order.updatedAt, { dateStyle: "medium", timeStyle: "short" })}</span></span>
                <StateBadge label={presentation.label} tone={presentation.tone} />
              </Link>
              <details className="text-[12px] text-ink-2"><summary className="tap-target cursor-pointer">작업 식별 정보</summary><p className="break-all font-mono">{order.workOrderId}</p></details>
            </li>;
          })}</ul>}
        </SectionCard>
      </div>}
    </div>
  </div>;
}
