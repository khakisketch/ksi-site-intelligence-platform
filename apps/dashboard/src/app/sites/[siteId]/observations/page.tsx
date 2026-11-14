import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { PageHeader } from "@/components/ui/PageHeader";
import { ConsolePage } from "@/components/nav/ConsolePage";
import { CoreApiError } from "@/lib/core-api/client";
import { listSiteExternalVolumeHistory } from "@/lib/core-api/external-result-workflow";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { AnalysisTabs } from "@/app/sites/[siteId]/analysis/AnalysisTabs";

import { ExternalObservationHistory } from "./ExternalObservationHistory";

export const metadata = { title: "분석 · KSI" };

async function ExternalComparisonRegistration({ siteId, organizationId }: { siteId: string; organizationId: string }) {
  const orders = await listObservationWorkOrders(siteId).catch(() => null);
  if (!orders) return <ErrorState message="비교에 사용할 작업을 불러오지 못했습니다." retryable />;
  const candidates = orders.filter((order) => order.siteId === siteId && order.organizationId === organizationId
    && order.executionMode === "EXTERNAL_RECONSTRUCTION" && order.status !== "CANCELLED");
  if (candidates.length === 0) return <EmptyState title="선택할 수 있는 외부 처리 작업이 없습니다" description="자료 등록 진행을 확인하세요."
    action={{ label: "등록 진행 보기", href: `/sites/${encodeURIComponent(siteId)}?panel=intake` }} />;
  return <section aria-labelledby="external-comparison-registration" className="flex flex-col gap-3">
    <h3 id="external-comparison-registration" className="text-lead font-bold">외부 비교 등록</h3>
    <p className="text-body text-ink-2">현재 자료가 등록된 작업을 선택하세요. 작업 화면에서 기준 자료와 비교 조건을 확인한 뒤 요청할 수 있습니다.</p>
    <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
      {candidates.map((order) => <li key={order.workOrderId} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <span className="min-w-0 break-words text-body font-semibold">{order.name}</span>
        <Link className="btn" href={`/field/work-orders/${encodeURIComponent(order.workOrderId)}#external-evidence`}>작업에서 비교 조건 확인</Link>
      </li>)}
    </ul>
  </section>;
}

export default async function SiteObservationHistoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ after?: string; register?: string | string[] }>;
}) {
  const { siteId } = await params;
  const { after, register } = await searchParams;
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return <OperationsSessionFailure
      verdict={session.verdict}
      next={`/sites/${encodeURIComponent(siteId)}/observations`}
    />;
  }
  // Establish Site access before dependent reads. Their absence/denial cannot
  // establish Site absence, and a faster child error must not mask a scoped404.
  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="외부 비교 기록을 불러오지 못했습니다." retryable /></div>;
  }
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const canRegister = session.principal.permissions.includes("SITES_WRITE") && session.principal.registryScoped !== true;
  const registering = register === "1" && canRegister;
  const siteHeader = <SiteHeader
    site={site}
    selectedEpochId={null}
    tab="analysis"
  />;
  if (registering) return <>
    {siteHeader}
    <ConsolePage density="dense">
      <PageHeader title="분석" headingLevel={2} actions={<Link className="btn" href={`${sitePath}/observations`}>외부 비교 이력으로 돌아가기</Link>} />
      <AnalysisTabs siteId={siteId} active="external" />
      {await ExternalComparisonRegistration({ siteId, organizationId: session.principal.organizationId })}
    </ConsolePage>
  </>;
  // 작업구역 이름은 표시 보조일 뿐이다. 이름 조회가 실패해도 이력은 가리지
  // 않는다 — 이름 없는 행은 '작업구역'으로 표시하고, 이름 실패만 따로 알린다.
  // 이름 목록에는 권한 없는 자료가 담기지 않으므로(실패 시 빈 목록) 노출이 없다.
  let history: Awaited<ReturnType<typeof listSiteExternalVolumeHistory>> | null = null;
  let areas: Awaited<ReturnType<typeof listWorkAreas>> | null = null;
  let denied = false;
  let retryAfterSeconds: number | undefined;
  let areaNamesUnavailable = false;
  const [historyResult, areasResult] = await Promise.allSettled([
    listSiteExternalVolumeHistory(siteId, { after, limit: 50 }),
    listWorkAreas(siteId),
  ]);
  if (historyResult.status === "fulfilled") {
    history = historyResult.value;
  } else {
    const error = historyResult.reason;
    denied = error instanceof CoreApiError && error.status === 403;
    retryAfterSeconds = error instanceof CoreApiError ? error.retryAfterSeconds : undefined;
  }
  if (areasResult.status === "fulfilled") {
    areas = areasResult.value;
  } else if (history !== null) {
    areaNamesUnavailable = true;
  }
  const loaded = history !== null ? { history, areas } : null;
  const names = new Map(loaded?.areas?.workAreas.map((area) => [area.workAreaId, area.name]) ?? []);
  return <>
    {siteHeader}
    <ConsolePage density="dense">
      <PageHeader title="분석" headingLevel={2} />
      <AnalysisTabs siteId={siteId} active="external" />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lead font-bold">외부 비교 이력</h3>
        {canRegister && <Link className="btn btn-primary" href={`${sitePath}/observations?register=1`}>외부 비교 등록</Link>}
      </div>
      {areaNamesUnavailable && <InlineNotice>작업구역 이름을 불러오지 못했습니다. 이름이 없는 행은 작업구역으로 표시됩니다.</InlineNotice>}
      {loaded ? <ExternalObservationHistory siteId={siteId} items={loaded.history.items} workAreaNames={names} /> :
        <ErrorState message={denied ? "외부 비교 기록을 조회할 권한이 없습니다. 현장 담당자에게 조회 권한을 요청하세요." : "외부 비교 기록을 불러오지 못했습니다."} tone={denied ? "high" : "crit"} retryable={!denied} retryAfterSeconds={retryAfterSeconds} />}
      {loaded?.history.nextCursor && <Link className="btn w-fit" href={`/sites/${encodeURIComponent(siteId)}/observations?after=${encodeURIComponent(loaded.history.nextCursor)}`}>이전 결과 더 보기</Link>}
    </ConsolePage>
  </>;
}
