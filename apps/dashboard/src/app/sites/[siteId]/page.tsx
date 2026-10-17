import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { SiteAoiEditor } from "./SiteAoiEditor";
import { SiteHeader } from "./SiteHeader";
import { SiteSpatialOverview, type SiteSpatialAssetsState } from "./SiteSpatialOverview";
import { SiteStartGuidance } from "./SiteStartGuidance";
import { SiteTransitionActions } from "./SiteTransitionActions";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { ExternalObservationHistory } from "./observations/ExternalObservationHistory";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { SITE_STATUS_LABEL, humanizeApiError } from "@/lib/core-api/labels";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { listSiteExternalVolumeHistory } from "@/lib/core-api/external-result-workflow";
import { getSite } from "@/lib/core-api/sites";
import { listSpatialAssets } from "@/lib/core-api/spatial-assets";
import { listAnalyses } from "@/lib/core-api/analysis";
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
    case "spatial-assets": return "spatial-assets";
    default: return "observations";
  }
}

function SiteTabLink({ siteId, tab, label, detail }: { siteId: string; tab: SiteTabKey; label: string; detail: string }) {
  return <SectionCard title={label}>
    <p className="text-[12.5px] leading-5 break-keep text-ink-2">{detail}</p>
    <Link href={`/sites/${encodeURIComponent(siteId)}/${tabHref(tab)}`} className="btn mt-3 w-fit">{label} 열기</Link>
  </SectionCard>;
}

export default async function SiteDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ section?: string | string[]; tab?: string | string[]; workAreaId?: string | string[]; assetRef?: string | string[] }>;
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

  const [canTransitionResult, canCreateResult, canApproveResult, areasResult, ordersResult, historyResult] = await Promise.allSettled([
    hasAllPermissions("SITES_WRITE"),
    hasAllPermissions("WORK_ORDERS_WRITE"),
    hasAllPermissions("SITES_AUTONOMY_APPROVE"),
    listWorkAreas(site.siteId, { includeArchived: true }),
    listObservationWorkOrders(site.siteId),
    listSiteExternalVolumeHistory(site.siteId, { limit: 50 }),
  ]);
  const canTransition = canTransitionResult.status === "fulfilled" && canTransitionResult.value;
  const canCreateWorkOrder = canCreateResult.status === "fulfilled" && canCreateResult.value;
  const canApproveAutonomy = canApproveResult.status === "fulfilled" && canApproveResult.value;
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

  // 기본 탭의 읽기 전용 공간 확인은 bounded 추가 읽기 2건으로 족하다 —
  // Core 분석 목록 50건 1회, 선택 구역의 공간 자산 20건 1회. 둘 다 실패해도
  // unknown으로 두고 빈 목록으로 단정하지 않는다. 다른 탭에서는 읽지 않는다.
  // 선택 구역은 이미 읽은 관측 작업·분석 목록의 묶임으로 고른다(추가 조회 없음).
  const wantSpatial = tab === "observations";
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
  const selectedAssetRef = assetsState.status === "ready"
    ? resolveSelectedAssetRef(assetsState.page, firstValue(query.assetRef))
      // 쿼리가 없거나 이번 페이지에 없으면 첫 검사 footprint 자료를 기본으로 둔다 —
      // 어떤 footprint를 보여주는지 캡션과 선택 UI가 일치하게 한다.
      ?? pickFootprintAsset(assetsState.page.assets, null)?.assetRef
      ?? null
    : null;
  // 명시된 workAreaId/assetRef가 조회 범위 안에 없으면 알린다 — 조용히 다른
  // 대상을 보여주지 않는다. 원문 id는 그대로 두지 않고(범위 밖 값) 공지만 둔다.
  const requestedWorkAreaId = wantSpatial ? parseScopeId(firstValue(query.workAreaId)) : null;
  const requestedAssetRef = assetsState.status === "ready" ? parseScopeId(firstValue(query.assetRef)) : null;
  const scopeNotice = wantSpatial && (
    (requestedWorkAreaId !== null && !allAreas.some((area) => area.workAreaId === requestedWorkAreaId))
    || (requestedAssetRef !== null && selectedAssetRef !== requestedAssetRef)
  );

  return <div className="flex flex-col">
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab={tab}
      latestExternalReportAt={latestExternalReport}
      latestExternalReportKnown={historyResult.status === "fulfilled"}
      canCreateWorkOrder={canCreateWorkOrder}
      canEditAoi={canTransition}
    />
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {tab === "observations" && <div className="flex flex-col gap-4">
        <SiteSpatialOverview
          sitePath={sitePath}
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
          scopeNotice={scopeNotice}
        />
        <SiteStartGuidance siteId={site.siteId} {...siteStartCounts} />
      </div>}

      {tab === "analysis" && <SiteTabLink siteId={site.siteId} tab="analysis" label="변화 분석" detail="같은 구역의 기준 자료와 비교할 자료를 고르고, 계산 결과와 담당자 검토 상태를 확인합니다." />}

      {tab === "spatial-assets" && <div className="flex flex-col gap-4">
        <SectionCard title="작업구역">
          {areasResult.status === "rejected" ? <ErrorState message="작업구역을 불러오지 못했습니다." retryable /> : areas.length === 0 ? <EmptyState title="등록된 작업구역이 없습니다" description="자료를 연결할 작업구역을 먼저 확인하세요." action={{ label: "작업구역 확인", href: `${sitePath}/work-areas` }} /> : <ul className="divide-y divide-line">{areas.map((area) => <li key={area.workAreaId} className="py-3 text-[13px]">
            <p className="break-words font-semibold">{area.name || "이름을 확인할 수 없는 구역"}</p>
            <p className="mt-1 text-[12px] text-ink-2">등록 {formatKoreanDateTime(area.createdAt, { dateStyle: "medium", timeStyle: "short" })}</p>
            <details className="mt-1 text-[12px] text-ink-2"><summary className="tap-target cursor-pointer">구역 식별 정보</summary><p className="break-all font-mono">{area.workAreaId}</p></details>
          </li>)}</ul>}
          <div className="mt-3 flex flex-wrap gap-2"><Link href={`${sitePath}/work-areas`} className="btn">작업구역 관리</Link><Link href={`${sitePath}/spatial-assets`} className="btn">등록 자료 보기</Link><Link href={`${sitePath}/spatial-data-requests`} className="btn">구역 자료 준비</Link></div>
        </SectionCard>
      </div>}

      {tab === "work-orders" && <div className="flex flex-col gap-4">
        <SectionCard title="현장 전체 경계 · 선택 설정">
          <div id="site-aoi" className="scroll-mt-5">
          {site.aoi ? <AoiPolygonMap value={site.aoi.vertices} readOnly /> : site.status === "UNMAPPED" && canTransition ? <ResponsiveActionBoundary action="SITE_DEVICE_TRANSITION" reason={`${site.name}의 전체 경계 편집은 노트북에서 진행하세요. 이 설정 없이도 작업구역의 관측 자료를 확인할 수 있습니다.`}><SiteAoiEditor siteId={site.siteId} siteFrame={site.siteFrame} /></ResponsiveActionBoundary> : <EmptyState compact title="현장 전체 경계는 아직 설정하지 않았습니다" description="전체 경계는 선택 설정입니다. 관측 자료는 각 작업구역에 연결해 사용합니다." />}
          </div>
        </SectionCard>
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
        <SectionCard title={`현장 상태 · ${status.label}`}>
          {canTransition ? <details><summary className="tap-target cursor-pointer text-[13px] font-semibold">관리자 상태 전이</summary><div className="mt-3"><SiteTransitionActions siteId={site.siteId} status={site.status} resumeTarget={site.resumeTarget} canApproveAutonomy={canApproveAutonomy} /></div></details> : <p className="text-[12px] text-ink-muted">현장 상태를 전이하려면 현장 등록 권한이 필요합니다.</p>}
          <dl className="mt-3 grid gap-2 border-t border-line pt-3 text-[12px] sm:grid-cols-2"><div><dt className="text-ink-muted">등록</dt><dd>{formatKoreanDate(site.registeredAt)}</dd></div><div><dt className="text-ink-muted">최근 갱신</dt><dd>{formatKoreanDate(site.updatedAt)}</dd></div><div><dt className="text-ink-muted">좌표계</dt><dd>{site.siteFrame.crs}</dd></div><div><dt className="text-ink-muted">변환 버전</dt><dd>{site.siteFrame.transformVersion}</dd></div></dl>
        </SectionCard>
      </div>}

      {tab === "external-results" && <SectionCard title="외부 비교 기록">
        {historyResult.status === "rejected" ? <ErrorState message="외부 비교 기록을 불러오지 못했습니다." retryable /> : historyResult.value.items.length === 0 ? <EmptyState title="조회된 외부 비교 기록이 없습니다" description="시스템에서 계산한 지형 변화는 변화 분석에서 확인하세요. 이 목록은 별도로 등록된 비교 기록입니다." action={{ label: "변화 분석 보기", href: `${sitePath}/analysis` }} /> : <ExternalObservationHistory siteId={site.siteId} items={historyResult.value.items} workAreaNames={areaNames} />}
        <div className="mt-3"><Link href={`${sitePath}/observations`} className="btn">외부 비교 기록 열기</Link></div>
      </SectionCard>}
    </div>
  </div>;
}
