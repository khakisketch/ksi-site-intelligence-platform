import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";

import { SiteAoiEditor } from "./SiteAoiEditor";
import { SiteHeader } from "./SiteHeader";
import { ConsoleWork } from "@/components/nav/ConsolePage";
import type { SiteSpatialAssetsState } from "./SiteSpatialOverview";
import { SiteWorkspaceShell } from "./SiteWorkspaceShell";
import { buildWorkspaceServerFacts } from "./site-workspace-server-facts";
import { SiteTransitionActions } from "./SiteTransitionActions";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { EmptyState } from "@/components/ui/EmptyState";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { SITE_STATUS_LABEL, humanizeApiError } from "@/lib/core-api/labels";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { whoAmI } from "@/lib/core-api/auth";
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
  resolveExplicitVisualPair,
  resolveOrdinaryEntry,
  type ExplicitComparisonResolution,
  type ExplicitResultResolution,
  type OrdinaryEntryResolution,
  type VisualPairResolution,
} from "@/lib/site-workspace-entry";
import { analysisHandoffHref } from "./site-visual-pair";
import { toPreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { formatKoreanDate } from "@/lib/datetime";
import { SITE_DETAIL_DOCUMENT_TITLE } from "@/lib/site-detail-title";
import { normalizeSiteTab } from "@/lib/site-epochs";
import { parseScopeId, pickFootprintAsset, resolveSelectedWorkAreaId } from "./site-spatial";

import { PageHeader } from "@/components/ui/PageHeader";
import { Disclosure } from "@/components/ui/Disclosure";
import { exactMaterialsAssetRef, isMetadataOnly, materialsHref, normalizeCatalogFilters, type MaterialsSearchParams } from "./materials/materials-visual";
import { readAssetHistory, readScopedAsset, scopeMaterialsPage } from "./materials/asset-reads";

const getSiteForDetail = cache(getSite);

// The document head is outside AccountDisplayBoundary. Never put Site names or
// identifiers there; use static route metadata so Next remains the sole owner.
export const metadata: Metadata = { title: SITE_DETAIL_DOCUMENT_TITLE };

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="overflow-hidden rounded-lg border border-line bg-surface">
    <div className="border-b border-line px-4 py-2.5"><h2 className="text-lead font-bold tracking-tight break-keep">{title}</h2></div>
    <div className="px-4 py-3">{children}</div>
  </section>;
}

export default async function SiteDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<MaterialsSearchParams & { section?: string | string[]; tab?: string | string[]; panel?: string | string[]; mode?: string | string[]; baselineAssetRef?: string | string[]; currentAssetRef?: string | string[]; analysisId?: string | string[] }>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const firstValue = (value: string | string[] | undefined): string | undefined =>
    Array.isArray(value) ? value[0] : value;
  const legacySection = firstValue(query.section) ?? firstValue(query.tab);
  const tab = normalizeSiteTab(legacySection);
  const siteHref = `/sites/${encodeURIComponent(siteId)}`;
  if (tab === "work-orders") {
    const next = new URLSearchParams({ panel: "intake" });
    const area = parseScopeId(query.workAreaId);
    if (area) next.set("workAreaId", area);
    redirect(`${siteHref}?${next}`);
  }
  if (legacySection === "materials" || legacySection === "assets" || legacySection === "spatial-assets") {
    redirect(materialsHref(siteId, parseScopeId(query.workAreaId), {
      assetRef: exactMaterialsAssetRef(query.assetRef),
      ...normalizeCatalogFilters({ q: firstValue(query.q), kind: firstValue(query.kind), state: firstValue(query.state) }),
    }));
  }
  const panel = query.panel === "materials" || query.panel === "intake" ? query.panel : null;
  const cursor = typeof query.cursor === "string" && query.cursor.length <= 1024 ? query.cursor || undefined : undefined;
  const filters = normalizeCatalogFilters({
    q: typeof query.q === "string" ? query.q : undefined,
    kind: typeof query.kind === "string" ? query.kind : undefined,
    state: typeof query.state === "string" ? query.state : undefined,
  });
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

  const [canTransitionResult, canCreateResult, canApproveResult, canReadDataResult, canRequestDataResult, areasResult, ordersResult] = await Promise.allSettled([
    hasAllPermissions("SITES_WRITE"),
    hasAllPermissions("WORK_ORDERS_WRITE"),
    hasAllPermissions("SITES_AUTONOMY_APPROVE"),
    hasAllPermissions("SPATIAL_DATA_READ"),
    hasAllPermissions("SPATIAL_DATA_REQUEST"),
    listWorkAreas(site.siteId, { includeArchived: true }),
    listObservationWorkOrders(site.siteId),
  ]);
  const canTransition = canTransitionResult.status === "fulfilled" && canTransitionResult.value;
  const canCreateWorkOrder = canCreateResult.status === "fulfilled" && canCreateResult.value;
  const canApproveAutonomy = canApproveResult.status === "fulfilled" && canApproveResult.value;
  const canReadData = canReadDataResult.status === "fulfilled" && canReadDataResult.value;
  const canRequestData = canRequestDataResult.status === "fulfilled" && canRequestDataResult.value;
  const allAreas = areasResult.status === "fulfilled" ? areasResult.value.workAreas : [];
  const areas = allAreas.filter((area) => area.status === "ACTIVE");
  // hasAllPermissions deliberately collapses identity/read failures to false.
  // Only a verified permission list can distinguish denial from unknown here.
  let workAreaWrite: "allowed" | "denied" | "unknown" = canTransition ? "allowed" : "unknown";
  if (!canTransition && tab === "space" && areasResult.status === "fulfilled" && areas.length === 0) {
    try {
      const principal = await whoAmI();
      if (Array.isArray(principal.permissions) && principal.permissions.every((permission) => typeof permission === "string")) {
        workAreaWrite = principal.permissions.includes("SITES_WRITE") ? "allowed" : "denied";
      }
    } catch {
      // Unknown remains closed; do not present an outage as a permission denial.
    }
  }
  const sitePath = `/sites/${encodeURIComponent(site.siteId)}`;
  const status = SITE_STATUS_LABEL[site.status];

  // 공간 읽기는 50건 단위로 한정한다. 구역 선택은 이미 읽은 작업·분석 목록의 연결을 사용한다.
  const wantSpatial = tab === "space";
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
  const areaQueryInvalid = panel === "materials" && areasResult.status === "fulfilled" && query.workAreaId !== undefined
    && !allAreas.some((area) => area.workAreaId === parseScopeId(query.workAreaId));
  const cursorInvalid = query.cursor !== undefined && query.cursor !== "" && cursor === undefined;
  const selectionMalformed = panel === "materials" && query.assetRef !== undefined && query.assetRef !== ""
    && exactMaterialsAssetRef(query.assetRef) === null;
  const selectedWorkAreaId = wantSpatial && areasResult.status === "fulfilled" && !areaQueryInvalid
    ? resolveSelectedWorkAreaId(areasResult.value.workAreas, firstValue(query.workAreaId), {
      workOrderAreaIds: boundWorkOrderAreaIds,
      analysisAreaIds: analysesPage?.items.map((item) => item.workAreaId) ?? [],
    })
    : null;
  const assetsResult = wantSpatial && !cursorInvalid
    ? await (selectedWorkAreaId
      ? listSpatialAssets(site.siteId, selectedWorkAreaId, cursor ? { limit: 50, cursor } : { limit: 50 })
        .then((page) => scopeMaterialsPage(page, site.siteId, selectedWorkAreaId)).then(
        (page) => ({ ok: true as const, page }),
        (error: unknown) => ({ ok: false as const, denied: error instanceof CoreApiError && error.status === 403 }),
      )
      : Promise.resolve({ ok: false as const, denied: false, skipped: true as const }))
    : { ok: false as const, denied: false, skipped: true as const };
  let assetsState: SiteSpatialAssetsState = { status: "not-requested" };
  if (wantSpatial && selectedWorkAreaId && !cursorInvalid) {
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
  // Viewer-first covers spatial exploration; the workspace result-review mode
  // stays dense (decision A — 결과/검토 are list/form-first).
  const workspaceViewer = tab === "space" && mode !== "results";
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

  const catalogAssets = assetsState.status === "ready" ? assetsState.page.assets : [];
  const requestedAssetRef = parseScopeId(query.assetRef);
  const requestedRefs = mode === "results" ? [] : [query.assetRef, query.visualAAssetRef, query.visualBAssetRef];
  const outsideRefs = [...new Set(requestedRefs.map(exactMaterialsAssetRef).filter((ref): ref is string =>
    ref !== null && !catalogAssets.some((item) => item.assetRef === ref)))];
  const assetPool = assetsState.status === "ready" && selectedWorkAreaId && !selectionMalformed
    ? [...catalogAssets, ...(await Promise.all(outsideRefs.map((ref) => readScopedAsset(site.siteId, selectedWorkAreaId, ref))))
      .filter((item) => item !== null)]
    : catalogAssets;
  const hintedAssetRef = assetPool.find((item) => item.assetRef === requestedAssetRef)?.assetRef ?? null;
  const serverViewAssetRef = ordinaryEntry.status === "ready" ? ordinaryEntry.observation.viewAssetRef : null;
  const serverViewInCatalog = assetPool.some((item) => item.assetRef === serverViewAssetRef) ? serverViewAssetRef : null;
  const currentScopeAssets = mode === "explore" ? catalogAssets : assetPool;
  const selectedAssetRef = query.assetRef
    ? hintedAssetRef
    : serverViewInCatalog ?? pickFootprintAsset(currentScopeAssets, null)?.assetRef ?? currentScopeAssets[0]?.assetRef ?? null;
  const transitionalSelection = hintedAssetRef === null && serverViewInCatalog === null && selectedAssetRef !== null;
  const issue = areaQueryInvalid ? "작업구역을 확인할 수 없거나 접근 권한이 없습니다."
    : cursorInvalid ? "페이지 주소가 올바르지 않습니다. 자료 목록을 처음부터 다시 여세요."
    : selectionMalformed ? "자료 주소가 올바르지 않습니다. 자료 목록에서 다시 선택하세요."
    : query.assetRef && hintedAssetRef === null && assetsState.status === "ready"
      ? "자료를 찾을 수 없거나 현재 조회할 수 없습니다."
      : null;
  const requestedWorkAreaId = wantSpatial ? parseScopeId(query.workAreaId) : null;
  const scopeNotice = wantSpatial && !issue && requestedWorkAreaId !== null
    && !allAreas.some((area) => area.workAreaId === requestedWorkAreaId);
  // 헤더 직접 링크용 검증 범위 — 어느 탭에서도 추가 조회 없이 승인된 현행
  // 활성 구역만 싣는다. 원문 쿼리를 그대로 두지 않고, 조용히 다른 구역으로
  // 바꾸지도 않는다. 공간 탭에서는 이미 고른 선택을 그대로 쓴다.
  // 탐색으로 돌아갈 때 정확한 관측을 잃지 않도록, 자산 참조도 작업구역과
  // 함께일 때만 형식 한계 안에서 싣는다(탐색 진입에서 카탈로그와 재대조한다).
  const activeWorkAreaIds = new Set(allAreas.filter((area) => area.status === "ACTIVE").map((area) => area.workAreaId));
  const spatialSelectedValid = wantSpatial && selectedWorkAreaId && activeWorkAreaIds.has(selectedWorkAreaId)
    ? selectedWorkAreaId
    : null;
  const explicitScopeValid = (() => {
    const raw = parseScopeId(firstValue(query.workAreaId));
    return raw && activeWorkAreaIds.has(raw) ? raw : null;
  })();
  const headerWorkAreaId = spatialSelectedValid ?? explicitScopeValid;
  const headerAssetRef = !headerWorkAreaId
    ? null
    : wantSpatial && selectedWorkAreaId === headerWorkAreaId && selectedAssetRef
      ? selectedAssetRef
      : wantSpatial ? null : parseScopeId(firstValue(query.assetRef));

  if (legacySection === "external-results") redirect(`${sitePath}/observations`);
  if (tab === "analysis") {
    const target = new URLSearchParams();
    if (headerWorkAreaId) target.set("workAreaId", headerWorkAreaId);
    if (headerAssetRef) target.set("assetRef", headerAssetRef);
    const search = target.toString();
    redirect(search
      ? `${sitePath}/analysis?${search}`
      : `${sitePath}/analysis`);
  }

  const rawBaselineAssetRef = wantSpatial && mode === "compare" ? firstValue(query.baselineAssetRef) : undefined;
  const rawCurrentAssetRef = wantSpatial && mode === "compare" ? firstValue(query.currentAssetRef) : undefined;
  // 시각 쌍 쿼리는 원문 그대로 판정한다 — 반복 배열을 첫 값으로 접지 않고
  // 명시적 invalid 경로로 둔다. 표시 기본값은 별도로 다듬는다.
  const rawVisualAAssetRef = wantSpatial && selectedWorkAreaId ? query.visualAAssetRef : undefined;
  const rawVisualBAssetRef = wantSpatial && selectedWorkAreaId ? query.visualBAssetRef : undefined;
  const baselineRequestedRef = parseWorkspaceScopeId(rawBaselineAssetRef ?? null);
  const currentRequestedRef = parseWorkspaceScopeId(rawCurrentAssetRef ?? null);
  const visualARequestedRef = parseWorkspaceScopeId(typeof rawVisualAAssetRef === "string" ? rawVisualAAssetRef : null);
  const visualBRequestedRef = parseWorkspaceScopeId(typeof rawVisualBAssetRef === "string" ? rawVisualBAssetRef : null);
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
  // 시각 쌍(독립 보기) — 정량 비교와 별개의 명시 의도다. 날짜만·시점 미상
  // 관측도 나란히 둘 수 있으며, 시간 순서·봉인을 요구하지 않는다. 기존
  // strict 경로의 의미를 바꾸지 않는다. 비교·결과 모드의 복귀 맥락으로 쓰므로
  // 모드와 무관하게 같은 구역에서 판정한다. 원문 쿼리를 그대로 넘긴다.
  let visualPair: VisualPairResolution | { status: "prompt" } = { status: "prompt" };
  if (facts && selectedWorkAreaId && (rawVisualAAssetRef != null || rawVisualBAssetRef != null)) {
    visualPair = resolveExplicitVisualPair(facts, {
      workAreaId: query.workAreaId,
      visualAAssetRef: rawVisualAAssetRef,
      visualBAssetRef: rawVisualBAssetRef,
    }, assetPool.filter(isMetadataOnly));
  }
  if (mode === "compare" && (rawVisualAAssetRef != null || rawVisualBAssetRef != null)
    && (rawBaselineAssetRef != null || rawCurrentAssetRef != null)) {
    comparison = { status: "prompt" };
    visualPair = { status: "unresolvable", intent: "comparison", reason: "malformed",
      headline: "비교 선택 방식을 하나만 사용하세요",
      detail: "독립 보기 A·B와 기존 시간 순서 보기의 선택이 함께 들어왔습니다. 아래에서 한 쌍을 직접 고르세요. 다른 선택으로 바꾸지 않았습니다." };
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

  const inspectedRefs = mode === "compare"
    ? visualPair.status === "ready" ? [visualPair.sideA.assetRef, visualPair.sideB.assetRef]
      : comparison.status === "ready" ? [comparison.baseline.assetRef, comparison.current.assetRef] : []
    : mode === "explore" && selectedAssetRef ? [selectedAssetRef] : [];
  const identity = inspectedRefs.some((ref) => exactMaterialsAssetRef(ref)) ? await whoAmI().catch(() => null) : null;
  const selectedMaterialDetails = await Promise.all(inspectedRefs.map(async (assetRef) => {
    const catalogItem = assetPool.find((item) => item.assetRef === assetRef);
    const detail = selectedWorkAreaId && exactMaterialsAssetRef(assetRef) && catalogAssets.some((item) => item.assetRef === assetRef)
      ? await readScopedAsset(site.siteId, selectedWorkAreaId, assetRef)
      : catalogItem ?? null;
    return {
      assetRef,
      detail,
      history: detail && isMetadataOnly(detail) && identity?.organizationId
        ? await readAssetHistory(detail, identity.organizationId)
        : null,
    };
  }));
  const workOrderNames = new Map(
    ordersResult.status === "fulfilled" && identity
      ? ordersResult.value.filter((order) => order.siteId === site.siteId && order.organizationId === identity.organizationId)
        .map((order) => [order.workOrderId, order.name])
      : [],
  );

  return <div className="flex min-w-0 min-h-0 flex-1 flex-col">
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab={mode === "results" ? "analysis" : tab}
      scopedWorkAreaId={headerWorkAreaId}
      scopedAssetRef={headerAssetRef}
      visualContext={visualPair.status === "ready" && selectedWorkAreaId === headerWorkAreaId
        ? {
            workAreaId: visualPair.workAreaId,
            visualAAssetRef: visualPair.sideA.assetRef,
            visualBAssetRef: visualPair.sideB.assetRef,
          }
        : null}
    />
    <ConsoleWork className={tab === "space" ? `min-h-0 flex-1 overflow-x-clip${workspaceViewer ? " lg:gap-0 lg:p-0" : ""}` : "flex-1"}>
      {tab === "space" && <div className="flex min-w-0 min-h-0 flex-1 flex-col gap-2">
        {mode !== "results" && <h2 className="sr-only">공간</h2>}
        <SiteWorkspaceShell
          sitePath={sitePath}
          mode={mode}
          areas={areasResult.status === "fulfilled" ? areasResult.value.workAreas : []}
          areasKnown={areasResult.status === "fulfilled"}
          areasState={areasResult.status === "fulfilled" ? "ready" : areasResult.reason instanceof CoreApiError && areasResult.reason.status === 403 ? "denied" : "unavailable"}
          canCreateWorkArea={workAreaWrite}
          orders={ordersResult.status === "fulfilled" ? ordersResult.value : null}
          analyses={analysesPage?.items ?? null}
          analysesKnown={analysesPage !== null}
          assetsState={assetsState}
          assetPool={assetPool}
          materialPanel={panel}
          materialsScope={{
            ...filters, cursor, info: query.info === "1" ? "1" : null,
            visualA: visualARequestedRef, visualB: visualBRequestedRef,
          }}
          materialIssue={issue}
          materialDetails={selectedMaterialDetails}
          workOrderNames={workOrderNames}
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
          visualARequestedRef={visualARequestedRef}
          visualBRequestedRef={visualBRequestedRef}
          visualPair={visualPair}
          explicitResult={explicitResult}
          explicitDetail={explicitDetail}
          leadDetail={leadDetail}
          scopedCompareHref={(() => {
            if (!selectedWorkAreaId || !activeWorkAreaIds.has(selectedWorkAreaId)) return `${sitePath}/analysis`;
            // 분석 인계는 정식으로 resolve된 한 쌍의 사실 그대로만 싣는다 —
            // 힌트 6건 + 복귀 참조 2건의 정식 빌더 하나를 쓴다.
            // 기존 구역-only 주소와 호환되며, 받는 분석 화면이 후보와 재대조한다.
            const hintSource = visualPair.status === "ready"
              ? { baseline: visualPair.sideA, current: visualPair.sideB }
              : comparison.status === "ready"
                ? { baseline: comparison.baseline, current: comparison.current }
                : null;
            if (!hintSource) return `${sitePath}/analysis?workAreaId=${encodeURIComponent(selectedWorkAreaId)}`;
            return analysisHandoffHref(sitePath, selectedWorkAreaId, hintSource.baseline, hintSource.current);
          })()}
          preparedJobs={preparedJobs}
          jobsState={preparedJobsState}
          canReadData={canReadData}
          canRequestData={canRequestData}
        />
      </div>}

      {tab === "manage" && <div className="flex flex-col gap-4">
        <PageHeader title="현장 설정" headingLevel={2} />
        <SectionCard title="현장 범위">
          <div id="site-aoi" className="scroll-mt-5">
          {site.aoi ? <AoiPolygonMap value={site.aoi.vertices} readOnly /> : site.status === "UNMAPPED" && canTransition ? <ResponsiveActionBoundary action="SITE_DEVICE_TRANSITION" reason={`${site.name}의 전체 경계 편집은 노트북에서 진행하세요. 이 설정 없이도 작업구역의 관측 자료를 확인할 수 있습니다.`}><SiteAoiEditor siteId={site.siteId} siteFrame={site.siteFrame} /></ResponsiveActionBoundary> : <EmptyState compact title="현장 전체 경계는 아직 설정하지 않았습니다" description="전체 경계는 선택 설정입니다. 관측 자료는 각 작업구역에 연결해 사용합니다." />}
          </div>
        </SectionCard>
        <SectionCard title={`현장 상태 · ${status.label}`}>
          {canTransition ? <SiteTransitionActions siteId={site.siteId} status={site.status} resumeTarget={site.resumeTarget} canApproveAutonomy={canApproveAutonomy} /> : <ActionUnavailable label="현장 상태 변경" description="현재 계정으로는 현장 상태를 변경할 수 없습니다. 현장 쓰기 권한이 있는 담당자에게 문의하세요." />}
          <dl className="mt-3 grid gap-2 border-t border-line pt-3 text-caption sm:grid-cols-2"><div><dt className="text-ink-muted">등록</dt><dd>{formatKoreanDate(site.registeredAt)}</dd></div><div><dt className="text-ink-muted">최근 갱신</dt><dd>{formatKoreanDate(site.updatedAt)}</dd></div></dl>
          <Disclosure label="좌표계·변환 상세" className="mt-2"><dl className="mt-1 grid gap-1"><div><dt className="text-ink-muted">좌표계</dt><dd>{site.siteFrame.crs}</dd></div><div><dt className="text-ink-muted">변환 버전</dt><dd>{site.siteFrame.transformVersion}</dd></div></dl></Disclosure>
        </SectionCard>
        <Link href={`${sitePath}/work-areas`} className="btn w-fit">작업구역 관리</Link>
      </div>}

    </ConsoleWork>
  </div>;
}
