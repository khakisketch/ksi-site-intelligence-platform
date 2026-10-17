import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { SiteAoiEditor } from "./SiteAoiEditor";
import { SiteHeader } from "./SiteHeader";
import { SiteStartGuidance } from "./SiteStartGuidance";
import { SiteTransitionActions } from "./SiteTransitionActions";
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
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { formatKoreanDate, formatKoreanDateTime } from "@/lib/datetime";
import { siteDetailDocumentTitle } from "@/lib/site-detail-title";
import { normalizeSiteTab, type SiteTabKey } from "@/lib/site-epochs";
import { presentWorkOrder } from "@/app/field/work-order-stage";

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
  searchParams: Promise<{ section?: string; tab?: string }>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const tab = normalizeSiteTab(query.section ?? query.tab);
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
        <SiteStartGuidance siteId={site.siteId} {...siteStartCounts} />
        <SectionCard title="외부 관측 이력">
          <p className="text-[12.5px] leading-5 text-ink-2">현장에 등록된 외부 관측 결과와 보관 근거를 확인합니다.</p>
          <Link href={`${sitePath}/observations`} className="btn mt-3 w-fit">외부 관측 이력 열기</Link>
          {canCreateWorkOrder && <Link href={`${sitePath}/observations/new`} className="btn mt-3 ml-2 w-fit">새 관측 시작</Link>}
        </SectionCard>
      </div>}

      {tab === "analysis" && <SiteTabLink siteId={site.siteId} tab="analysis" label="현장 분석" detail="현장 분석 화면에서 관측 쌍, 작업구역, 분석 기록과 근거를 확인합니다." />}

      {tab === "spatial-assets" && <div className="flex flex-col gap-4">
        <SectionCard title="작업구역">
          {areasResult.status === "rejected" ? <ErrorState message="작업구역을 불러오지 못했습니다." retryable /> : areas.length === 0 ? <EmptyState title="등록된 작업구역이 없습니다" description="작업구역은 공간 자산 화면에서 확인하고 관리할 수 있습니다." /> : <ul className="divide-y divide-line">{areas.map((area) => <li key={area.workAreaId} className="py-3 text-[13px]">
            <p className="break-words font-semibold">{area.name || "이름을 확인할 수 없는 구역"}</p>
            <p className="mt-1 text-[12px] text-ink-2">등록 {formatKoreanDateTime(area.createdAt, { dateStyle: "medium", timeStyle: "short" })}</p>
            <details className="mt-1 text-[12px] text-ink-2"><summary className="tap-target cursor-pointer">구역 식별 정보</summary><p className="break-all font-mono">{area.workAreaId}</p></details>
          </li>)}</ul>}
          <div className="mt-3 flex flex-wrap gap-2"><Link href={`${sitePath}/work-areas`} className="btn">작업구역 관리</Link><Link href={`${sitePath}/spatial-assets`} className="btn">공간 자산</Link><Link href={`${sitePath}/spatial-data-requests`} className="btn">구역 데이터 요청</Link></div>
        </SectionCard>
      </div>}

      {tab === "work-orders" && <div className="flex flex-col gap-4">
        <SectionCard title="현장 범위">
          {site.aoi ? <p className="text-[12.5px] text-ink-2">저장된 현장 범위가 있습니다.</p> : site.status === "UNMAPPED" && canTransition ? <SiteAoiEditor siteId={site.siteId} siteFrame={site.siteFrame} /> : <EmptyState compact title="현장 범위가 등록되지 않았습니다" description="현장 등록 권한이 있는 계정에서 범위를 설정할 수 있습니다." />}
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

      {tab === "external-results" && <SectionCard title="외부 결과">
        {historyResult.status === "rejected" ? <ErrorState message="외부 관측 결과를 불러오지 못했습니다." retryable /> : historyResult.value.items.length === 0 ? <EmptyState title="외부 관측 결과가 없습니다" description="결과가 기록되면 이 탭에서 보관 근거와 함께 확인할 수 있습니다." /> : <ExternalObservationHistory siteId={site.siteId} items={historyResult.value.items} workAreaNames={areaNames} />}
        <div className="mt-3"><Link href={`${sitePath}/observations`} className="btn">외부 관측 이력 열기</Link></div>
      </SectionCard>}
    </div>
  </div>;
}
