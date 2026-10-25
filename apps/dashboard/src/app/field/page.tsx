import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listSitesCached } from "@/lib/core-api/cached";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { formatKoreanDateTime } from "@/lib/datetime";
import {
  listObservationWorkOrderOperations,
  listObservationWorkOrdersForOrganization,
} from "@/lib/core-api/observation-work-orders";
import { resolveFieldSession } from "./resolve-session";
import { OperationsSessionFailure } from "./OperationsSessionFailure";
import { FieldWorkNav } from "./FieldWorkNav";
import { WorkQueueOperationsNotices } from "./WorkQueueOperationsNotices";
import { deriveWorkQueueOperationalNotices, summarizeWorkQueue } from "./work-queue";
import { presentWorkOrder } from "./work-order-stage";
import { SITE_NAME_UNAVAILABLE, formatWorkAreaTechnicalRefs, formatWorkQueueRowContext, indexWorkAreaNamesBySite, isWorkQueueContextMissing, orderWorkQueueGroupsForDisplay, selectWorkQueueRowsNeedingTechnicalRef } from "@/lib/work-context-names";

export const metadata = { title: "작업 · KSI" };

const GROUPS = [
  ["decisionRequired", "결정 필요", "범위 검토와 결과 확인이 필요한 작업"],
  ["inFlight", "진행 중", "등록·검사 상태와 다음 분석을 확인할 작업"],
  ["operationsUnavailable", "운영 상태 확인 필요", "담당·기한을 불러오지 못했거나 운영 상태가 정해지지 않은 작업"],
  ["completed", "완료", "완료되거나 종료된 작업"],
] as const;

const SUMMARY_GROUPS = [
  ["decisionRequired", "결정 필요"],
  ["inFlight", "진행 중"],
  ["operationsUnavailable", "운영 상태 확인 필요"],
  ["completed", "완료"],
] as const;

export default async function FieldWorkListPage({ searchParams }: {
  searchParams?: Promise<{ q?: string | string[]; group?: string | string[]; site?: string | string[] }>;
} = {}) {
  const rawParams = await searchParams ?? {};
  const params = {
    q: typeof rawParams.q === "string" ? rawParams.q : undefined,
    group: typeof rawParams.group === "string" ? rawParams.group : undefined,
    site: typeof rawParams.site === "string" ? rawParams.site : undefined,
  };
  const query = (params.q ?? "").trim();
  const groupKey = GROUPS.some(([key]) => key === params.group) ? params.group : undefined;
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next="/field" />;
  let workOrders;
  try {
    workOrders = await listObservationWorkOrdersForOrganization();
  } catch (error) {
    const message = error instanceof CoreApiError
      ? humanizeApiError(error.code, error.status, error.serverMessage)
      : "요청을 처리하지 못했습니다.";
    return <div className="p-4 sm:p-5"><ErrorState message={message} retryable /></div>;
  }
  const operations = session.principal.permissions.includes("WORK_ORDERS_WRITE")
    ? await listObservationWorkOrderOperations().catch(() => null)
    : null;
  const byId = new Map((operations ?? []).map((item) => [item.workOrderId, item]));
  const summary = summarizeWorkQueue(workOrders, byId);
  // 행 맥락용 이름은 이미 권한이 확인된 목록 API로 현장별 한 번씩만 읽는다
  // (보관 구역 포함 — 과거 작업 맥락용). 구역 ID는 현장 안에서만 유일하므로
  // 현장별로 나눠 둔다. 실패는 확인 불가로 접고 큐를 깨뜨리지 않는다.
  const siteIds = [...new Set(workOrders.map((order) => order.siteId))];
  const [sites, areaPages] = await Promise.all([
    listSitesCached().catch(() => null),
    Promise.all(siteIds.map(async (siteId) => {
      try {
        return { siteId, workAreas: (await listWorkAreas(siteId, { includeArchived: true })).workAreas };
      } catch {
        return null;
      }
    })),
  ]);
  const siteById = new Map((sites ?? []).map((site) => [site.siteId, site]));
  const areaNameBySite = indexWorkAreaNamesBySite(areaPages.filter((page) => page !== null));
  // 행 파일 정보는 겹치거나 빠진 맥락에만 둔다. 유일한 행은 compact하게 두고
  // 전체 ID는 작업 상세 화면에서 계속 볼 수 있다.
  const rowsNeedingTechnicalRef = selectWorkQueueRowsNeedingTechnicalRef(workOrders.map((order) => {
    const siteName = siteById.get(order.siteId)?.name ?? null;
    const nameById = areaNameBySite.get(order.siteId) ?? new Map<string, string>();
    return {
      rowKey: order.workOrderId,
      name: order.name,
      contextLine: formatWorkQueueRowContext({
        siteName,
        workAreaIds: order.workAreaIds,
        nameById,
        cycleNumber: order.cycleNumber,
        updatedAt: order.updatedAt,
      }),
      missingContext: isWorkQueueContextMissing({ name: order.name, siteName, workAreaIds: order.workAreaIds, nameById }),
    };
  }));
  const groups = orderWorkQueueGroupsForDisplay(GROUPS.map(([key, label, description]) => ({
    key, label, description, rows: summary[key],
  })));
  const matching = groups.flatMap(({ key, rows }) => rows.map((order) => ({ key, order })))
    .filter(({ key, order }) => (!groupKey || key === groupKey)
      && (!params.site || order.siteId === params.site)
      && (!query || `${order.name} ${siteById.get(order.siteId)?.name ?? ""}`.toLocaleLowerCase("ko-KR").includes(query.toLocaleLowerCase("ko-KR"))));
  const filterHref = (group?: string) => {
    const next = new URLSearchParams();
    if (query) next.set("q", query);
    if (params.site) next.set("site", params.site);
    if (group) next.set("group", group);
    return `/field${next.size ? `?${next}` : ""}`;
  };
  const notices = operations
    ? deriveWorkQueueOperationalNotices(workOrders, byId, session.principal.principalId, new Date())
    : [];
  const canCreateObservation = session.principal.permissions.includes("WORK_ORDERS_WRITE");
  const showTeam = session.principal.role === "ADMIN" || canCreateObservation;

  return (
      <div className="console-page">
        <header className="flex flex-col gap-2.5">
          <FieldWorkNav active="orders" showTeam={showTeam} />
          <div className="console-work-heading pt-1">
            <div className="min-w-0 flex-1">
              <h2 className="console-page-title">관측 작업</h2>
            </div>
            {canCreateObservation ? (
              <Link href="/field/new" className="btn btn-primary tap-target">관측 자료 등록</Link>
            ) : (
              <ActionUnavailable label="관측 자료 등록" description="현재 계정으로는 관측 자료를 등록할 수 없습니다. 작업 등록 권한이 있는 담당자에게 문의하세요." />
            )}
            <p className="console-page-description !mt-0 basis-full">조직의 전체 관측 작업 기록입니다.</p>
          </div>
        </header>
        <WorkQueueOperationsNotices notices={notices} />
        {workOrders.length === 0 ? (
          <EmptyState title="등록된 관측 작업이 없습니다" description="현장 화면에서 작업구역을 확인하고 관측 자료 등록을 시작할 수 있습니다." action={{ label: "현장 보기", href: "/sites" }} />
        ) : (
          <>
            <nav className="flex items-center gap-1 overflow-x-auto border-b border-line pb-3" aria-label="작업 요약">
              <Link href={filterHref()} aria-current={!groupKey ? "page" : undefined} className="console-filter-link">전체 <span className="tabular-nums text-ink-muted">{workOrders.length}</span></Link>
              {SUMMARY_GROUPS.map(([key, label]) => (
                <Link key={key} href={filterHref(key)} aria-current={groupKey === key ? "page" : undefined} className="console-filter-link">{label}<span className="tabular-nums text-ink-muted">{summary[key].length}</span></Link>
              ))}
            </nav>
            <form action="/field" className="flex flex-wrap items-end gap-3" role="search" aria-label="관측 작업 검색">
              {groupKey && <input type="hidden" name="group" value={groupKey} />}
              <label className="grid min-w-0 flex-1 basis-56 gap-1.5 text-[12px] font-medium sm:max-w-md">작업 검색<input className="input w-full" type="search" name="q" defaultValue={query} placeholder="작업명 또는 현장명" /></label>
              <label className="grid min-w-0 gap-1.5 text-[12px] font-medium">현장<select className="input w-full sm:max-w-64" name="site" defaultValue={params.site ?? ""}><option value="">전체 현장</option>{[...siteById.values()].filter((site) => siteIds.includes(site.siteId)).map((site) => <option key={site.siteId} value={site.siteId}>{site.name}</option>)}</select></label>
              <button className="btn" type="submit">검색</button>
              {(query || params.site || groupKey) && <Link href="/field" className="tap-target inline-flex items-center px-2 text-[12px] underline">필터 초기화</Link>}
            </form>
            <section aria-label="관측 작업 목록" className="overflow-hidden rounded-lg border border-line bg-surface">
              <div className="flex items-center justify-between border-b border-line px-4 py-3 text-[12px] text-ink-2"><span>{groupKey ? GROUPS.find(([key]) => key === groupKey)?.[1] : "전체 작업"}</span><span role="status" className="tabular-nums">{matching.length}건 표시</span></div>
              <div className="hidden grid-cols-[minmax(0,1fr)_140px_110px_150px] gap-4 border-b border-line bg-page px-4 py-2.5 text-[12px] text-ink-muted xl:grid" aria-hidden="true"><span>작업 · 현장</span><span>담당</span><span>기한</span><span>상태</span></div>
              {matching.length === 0 ? <EmptyState title="조건에 맞는 작업이 없습니다" description="검색어나 상태·현장 필터를 바꿔 보세요." action={{ label: "필터 초기화", href: "/field" }} /> : <ul className="divide-y divide-line">
                      {matching.map(({ key, order }) => {
                        const state = presentWorkOrder(order.status, order.executionMode);
                        const siteName = siteById.get(order.siteId)?.name ?? null;
                        const operation = byId.get(order.workOrderId);
                        const context = formatWorkQueueRowContext({
                          siteName,
                          workAreaIds: order.workAreaIds,
                          nameById: areaNameBySite.get(order.siteId) ?? new Map(),
                          cycleNumber: order.cycleNumber,
                          updatedAt: order.updatedAt,
                        });
                        return (
                          <li key={order.workOrderId}>
                            <Link href={`/field/work-orders/${encodeURIComponent(order.workOrderId)}`} className="tap-target grid grid-cols-2 gap-x-4 gap-y-2 px-4 py-4 hover:bg-page xl:grid-cols-[minmax(0,1fr)_140px_110px_150px] xl:items-center">
                              <span className="col-span-2 min-w-0 flex-1 xl:col-span-1">
                                <span className="block break-words break-keep text-[14px] font-semibold">{order.name}</span>
                                <span className="mt-1 block break-words break-keep text-[12px] leading-5 text-ink-2">{context}</span>
                              </span>
                              <span className="min-w-0 break-words text-[12px] text-ink-2"><span className="xl:hidden">담당 · </span>{operation ? operation.assigneePrincipalId === session.principal.principalId ? "나" : operation.assigneePrincipalId ?? "미배정" : "확인 불가"}</span>
                              <span className="text-[12px] text-ink-2 tabular-nums"><span className="xl:hidden">기한 · </span>{operation ? operation.dueAt ? formatKoreanDateTime(operation.dueAt, { dateStyle: "short", timeStyle: "short" }) : "미정" : "확인 불가"}</span>
                              <span className="col-span-2 xl:col-span-1">
                              <StateBadge label={key === "completed" ? "이력 보기" : key === "operationsUnavailable" ? "담당·기한 상태 확인" : state.label} tone={key === "completed" ? "neutral" : key === "operationsUnavailable" ? "warning" : state.tone} />
                              </span>
                            </Link>
                            {rowsNeedingTechnicalRef.has(order.workOrderId) && <details className="px-4 pb-2 text-[11.5px] text-ink-muted">
                              <summary className="tap-target inline-flex cursor-pointer items-center font-semibold">파일 정보</summary>
                              <p className="mt-1 break-all">작업 {order.workOrderId} · 현장 {siteName ?? SITE_NAME_UNAVAILABLE} ({order.siteId}) · 구역 {formatWorkAreaTechnicalRefs(order.workAreaIds)} · {formatKoreanDateTime(order.updatedAt, { dateStyle: "medium", timeStyle: "short" })} 갱신</p>
                            </details>}
                          </li>
                        );
                      })}
                    </ul>}
            </section>
          </>
        )}
      </div>
  );
}
