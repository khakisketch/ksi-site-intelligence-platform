import Link from "next/link";

import { HomeAttentionCarousel, type HomeAttentionCardView } from "./HomeAttentionCarousel";
import { HomeRecentUpdates, type HomeRecentUpdateView } from "./HomeRecentUpdates";
import { HomeSituationList, type HomeSituationItem } from "./HomeSituationList";
import { presentWorkOrder } from "./field/work-order-stage";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { whoAmI } from "@/lib/core-api/auth";
import { resolveSiteRegistrationMode } from "@/lib/core-api/permissions";
import { getAnalysisReviewTarget, listAnalyses, listAnalysisReviews } from "@/lib/core-api/analysis";
import { listSitesCached } from "@/lib/core-api/cached";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { listExternalPendingDecisions } from "@/lib/core-api/external-decisions";
import { listObservationWorkOrderOperations, listObservationWorkOrdersForOrganization } from "@/lib/core-api/observation-work-orders";
import { listWorkInbox } from "@/lib/core-api/work-collaboration";
import type { SiteView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { externalDecisionCardText } from "@/lib/home-external-decision";
import { selectHomeAnalysisReviewSources, selectHomeAttentionSources, selectHomeInitialSetupSites, selectHomeQuickAccessSites, selectHomeRecentSiteSources, selectHomeRecentUpdates, summarizeHomeAnalysisReviewReads, type HomeAnalysisReviewRecord, type HomeAnalysisReviewSiteRead, type HomeAnalysisReviewSource, type HomeAttentionSource, type HomeRecentSiteSource, type HomeRecentUpdateSource } from "@/lib/home-operations";
import { resolveSiteOperatorNextAction } from "@/lib/operator-next-action";
import { formatHomeReviewTechnicalRef, homeAnalysisReviewCardText, indexWorkAreaNamesBySite } from "@/lib/work-context-names";
import { TopUnattendedHeadline } from "./TopUnattendedHeadline";

export const metadata = { title: "홈 · KSI" };

const MAX_HOME_ANALYSIS_REVIEW_SITES = 3;
const MAX_HOME_ANALYSES_PER_SITE = 5;
const MAX_HOME_ANALYSIS_REVIEW_PAGE = 50;

type Settled<T> = { ok: true; value: T } | { ok: false; forbidden: boolean; message: string };

async function settle<T>(promise: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    return { ok: false, forbidden: typeof error === "object" && error !== null && "status" in error && error.status === 403, message: "요청을 처리하지 못했습니다." };
  }
}

async function loadHomeAnalysisReviewSources(siteIds: readonly string[]): Promise<{
  sources: HomeAnalysisReviewSource[];
  unknownSiteIds: string[];
}> {
  // Bound the server-side read to 3 Home-context Sites × 5 analyses. Each completed
  // analysis checked uses one target and one review-list GET: at most 33 Core calls.
  // The bound is a scope limit, never a global verdict: a site whose list/target/
  // review read fails, truncates, or falls outside the bound is unknown — failed or
  // unobserved reads never become "no pending" or "reviewed" (ADR-KSI-025 D1 unknown-not-0).
  const uniqueSiteIds = [...new Set(siteIds)];
  const boundedSiteIds = uniqueSiteIds.slice(0, MAX_HOME_ANALYSIS_REVIEW_SITES);
  const outOfScopeSiteIds = uniqueSiteIds.slice(MAX_HOME_ANALYSIS_REVIEW_SITES);
  const perSite = await Promise.all(boundedSiteIds.map(async (siteId): Promise<HomeAnalysisReviewSiteRead> => {
    let analysesPage;
    try {
      analysesPage = await listAnalyses(siteId, { limit: MAX_HOME_ANALYSES_PER_SITE });
    } catch {
      // List failure is not an empty list.
      return { status: "unknown", siteId };
    }
    const completed = analysesPage.items
      .filter((analysis) => analysis.siteId === siteId && analysis.executionState === "COMPLETED" && analysis.resultId !== null)
      .toSorted((a, b) => b.createdAt.localeCompare(a.createdAt) || a.analysisId.localeCompare(b.analysisId));
    const records: HomeAnalysisReviewRecord[] = [];

    for (const analysis of completed) {
      let currentTarget;
      let reviewPage;
      try {
        [currentTarget, reviewPage] = await Promise.all([
          getAnalysisReviewTarget(siteId, analysis.analysisId),
          // Match the detail panel's bounded page; Core review pages are not newest-first.
          listAnalysisReviews(siteId, analysis.analysisId, { limit: MAX_HOME_ANALYSIS_REVIEW_PAGE }),
        ]);
      } catch {
        // Without both current target and receipts the exact-review state is unknown —
        // never a successful empty, never a confirmed reviewed.
        return { status: "unknown", siteId };
      }
      // A matching receipt may sit beyond this bounded review page, so a truncated
      // page cannot clear — or pend — the analysis. Pending verdicts below only
      // ever rest on complete reads.
      if (reviewPage.nextCursor !== null) return { status: "unknown", siteId };
      records.push({ analysis, currentTarget, reviews: reviewPage.items });
      const candidate = selectHomeAnalysisReviewSources(records)[0];
      if (candidate) return { status: "pending", source: candidate };
    }
    // Same completeness rule for the analyses list: the unobserved rest is not global zero.
    if (analysesPage.nextCursor !== null) return { status: "unknown", siteId };
    return { status: "clear", siteId };
  }));

  return summarizeHomeAnalysisReviewReads(perSite, outOfScopeSiteIds);
}

/**
 * 검토 대기 분석이 가리키는 실제 작업구역 이름. 검토 대상은 최대 3개 현장으로
 * 한정되어 있어 현장별 한 번씩만 읽는다(보관 구역 포함 — 과거 분석 맥락용).
 * 구역 ID는 현장 안에서만 유일하므로 현장별로 나눠 둔다.
 * 실패는 이름 확인 불가로 접고 Home을 깨뜨리지 않는다.
 */
async function loadReviewWorkAreaNames(siteIds: readonly string[]): Promise<ReadonlyMap<string, ReadonlyMap<string, string>>> {
  const uniqueSiteIds = [...new Set(siteIds)];
  const pages = await Promise.all(uniqueSiteIds.map(async (siteId) => {
    try {
      return { siteId, workAreas: (await listWorkAreas(siteId, { includeArchived: true })).workAreas };
    } catch {
      return null;
    }
  }));
  return indexWorkAreaNamesBySite(pages.filter((page) => page !== null));
}

function observedAt(value: string): string {
  return formatKoreanDateTime(value, { dateStyle: "medium", timeStyle: "short" });
}

function attentionWorkOrderDetail(source: Extract<HomeAttentionSource, { kind: "WORK_ORDER" }>): string {
  const order = source.workOrder;
  if (order.statusReason) return order.statusReason;
  if (order.status === "BLOCKED") return "작업 진행을 막은 사유와 복구 경로를 확인해야 합니다.";
  if (order.status === "DRAFT" || order.status === "AWAITING_APPROVAL") return `조사 범위 ${order.workAreaIds.length}개 구역과 목적을 검토해야 합니다.`;
  if (order.status === "REOBSERVATION_PENDING") return "부족한 근거와 추가 관측 범위를 확인한 뒤 사람이 결정합니다.";
  if (order.status === "REVIEW_READY") return "외부 결과와 보관 근거를 검토합니다.";
  return "현재 작업 상태와 확인 근거를 살펴봅니다.";
}

function attentionView(source: HomeAttentionSource, siteById: ReadonlyMap<string, SiteView>, areaNameBySite: ReadonlyMap<string, ReadonlyMap<string, string>> = new Map()): HomeAttentionCardView {
  const siteName = siteById.get(source.siteId)?.name ?? "이름을 확인할 수 없는 현장";
  if (source.kind === "EXTERNAL_DECISION") {
    const card = externalDecisionCardText(source.decision);
    return { key: source.key, siteName, label: card.label, title: card.title, detail: card.detail, timeLabel: "결과 보고", observedAt: observedAt(source.observedAt), href: card.href, actionLabel: card.actionLabel, image: null };
  }
  if (source.kind === "ANALYSIS_REVIEW") {
    const analysis = source.analysis;
    const areaName = areaNameBySite.get(source.siteId)?.get(analysis.workAreaId) ?? null;
    const card = homeAnalysisReviewCardText({ siteName: siteById.get(source.siteId)?.name ?? null, workAreaId: analysis.workAreaId, areaName });
    return {
      key: source.key,
      siteName,
      label: "분석 검토 대기",
      title: card.title,
      detail: card.detail,
      timeLabel: "분석 생성",
      observedAt: observedAt(source.observedAt),
      href: `/sites/${encodeURIComponent(source.siteId)}/analysis?analysisId=${encodeURIComponent(analysis.analysisId)}&workAreaId=${encodeURIComponent(analysis.workAreaId)}`,
      actionLabel: "분석 결과 검토",
      image: null,
      technicalRef: formatHomeReviewTechnicalRef(analysis.analysisId, analysis.workAreaId),
    };
  }
  if (source.kind === "WORK_ORDER") {
    const order = source.workOrder;
    const presentation = presentWorkOrder(order.status, order.executionMode);
    return { key: source.key, siteName, label: presentation.label, title: order.name, detail: attentionWorkOrderDetail(source), timeLabel: "작업 갱신", observedAt: observedAt(source.observedAt), href: `/field/work-orders/${encodeURIComponent(order.workOrderId)}`, actionLabel: order.status === "REVIEW_READY" ? "결과와 근거 보기" : "작업 맥락 보기", image: null };
  }
  const status = SITE_STATUS_LABEL[source.site.status];
  const title = source.site.status === "UNMAPPED" ? "초기 관측 범위를 준비해야 합니다." : source.site.status === "REMAP_REQUIRED" ? "새 기준 관측이 필요합니다." : "최근 현장 상태를 다시 관측해야 합니다.";
  return { key: source.key, siteName, label: status.label, title, detail: "현장 상태와 조사할 공사 구역을 확인한 뒤 필요한 관측 범위를 결정할 수 있습니다.", timeLabel: "현장 갱신", observedAt: observedAt(source.observedAt), href: `/sites/${encodeURIComponent(source.siteId)}`, actionLabel: "현장 맥락 보기", image: null };
}

function recentUpdateView(source: HomeRecentUpdateSource, siteById: ReadonlyMap<string, SiteView>): HomeRecentUpdateView {
  const siteName = siteById.get(source.siteId)?.name ?? "이름을 확인할 수 없는 현장";
  if ("site" in source) {
    return { key: source.key, siteName, label: "현재 등록 상태", title: "등록된 대기 작업 없음", detail: "현재 조회된 작업 기준입니다. 현장 전체의 정상이나 안전을 의미하지 않습니다.", observedAt: `현장 갱신 ${observedAt(source.observedAt)}`, href: `/sites/${encodeURIComponent(source.site.siteId)}`, image: null, imageFallbackLabel: "연결된 미리보기 없음" };
  }
  if (source.kind === "RESULT_READY" || source.kind === "OBSERVATION_COMPLETED") {
    return { key: source.key, siteName, label: source.kind === "RESULT_READY" ? "새 결과" : "최근 관측", title: source.workOrder.name, detail: source.kind === "RESULT_READY" ? "외부 결과와 보관 근거를 검토합니다." : "관측 결과가 작업 기록에 등록되었습니다.", observedAt: observedAt(source.observedAt), href: `/field/work-orders/${encodeURIComponent(source.workOrder.workOrderId)}`, image: null, imageFallbackLabel: "연결된 미리보기 없음" };
  }
  throw new Error("Unsupported Home update source");
}

function recentSiteView(source: HomeRecentSiteSource): HomeAttentionCardView {
  const status = SITE_STATUS_LABEL[source.site.status];
  return { key: source.key, siteName: source.site.name, label: source.site.status === "UNMAPPED" ? "등록 자료 확인" : `현장 관리 상태 · ${status.label}`, title: "현장의 자료와 분석 기록을 확인하세요.", detail: "현장을 열어 작업구역·등록 자료·분석 기록을 확인하세요.", timeLabel: "현장 갱신", observedAt: observedAt(source.site.updatedAt), href: `/sites/${encodeURIComponent(source.siteId)}`, actionLabel: "현장 보기", image: null };
}

export default async function HomePage() {
  const [sitesResult, whoResult, workOrdersResult, operationsResult, decisionsResult, inboxResult] = await Promise.all([
    settle(listSitesCached()),
    settle(whoAmI()),
    settle(listObservationWorkOrdersForOrganization()),
    settle(listObservationWorkOrderOperations()),
    settle(listExternalPendingDecisions()),
    settle(listWorkInbox({ unreadOnly: true })),
  ]);
  const sites = sitesResult.ok ? sitesResult.value : [];
  const workOrders = workOrdersResult.ok ? workOrdersResult.value : [];
  const decisions = decisionsResult.ok ? decisionsResult.value.items : [];
  const operationsByWorkOrderId = new Map((operationsResult.ok ? operationsResult.value : []).map((item) => [item.workOrderId, item]));
  const externalWorkOrders = workOrders.some((item) => item.executionMode === "EXTERNAL_RECONSTRUCTION");
  const operationsUnavailable = externalWorkOrders && !operationsResult.ok;
  const decisionsUnavailable = externalWorkOrders && !decisionsResult.ok;
  const permissions = whoResult.ok ? whoResult.value.permissions : [];
  const canRegisterSite = whoResult.ok && resolveSiteRegistrationMode(whoResult.value) !== "DENIED";
  const baseAttention = selectHomeAttentionSources({ workOrders, sites, operationsByWorkOrderId, externalDecisions: decisions }, Number.MAX_SAFE_INTEGER);
  const initialSetupSites = selectHomeInitialSetupSites(sites, 3, { workOrders, known: workOrdersResult.ok });
  const recentSiteSources = selectHomeRecentSiteSources(sites);
  const externalDecisionSiteIds = new Set(decisions.map((decision) => decision.siteId));
  // 검토 읽기 범위를 3개 현장으로 묶는 slice 는 loader 가 맡는다 — 묶음 밖 현장은
  // unknown 으로 보고하고 0으로 단정하지 않는다.
  const analysisReviewSiteIds = [...new Set([
    ...baseAttention
      .filter((source) => source.kind !== "EXTERNAL_DECISION" && !(source.kind === "SITE" && source.site.status === "UNMAPPED"))
      .map((source) => source.siteId),
    ...recentSiteSources.filter((source) => !externalDecisionSiteIds.has(source.siteId)).map((source) => source.siteId),
  ])];
  const analysisReviewRead = await loadHomeAnalysisReviewSources(analysisReviewSiteIds);
  const analysisReviewSources = analysisReviewRead.sources;
  const analysisReviewsUnknown = analysisReviewRead.unknownSiteIds.length > 0;
  const reviewAreaNameById = await loadReviewWorkAreaNames(analysisReviewSources.map((source) => source.siteId));
  const allAttention = selectHomeAttentionSources({ workOrders, sites, operationsByWorkOrderId, externalDecisions: decisions, analysisReviews: analysisReviewSources }, Number.MAX_SAFE_INTEGER);
  const operationalAttention = allAttention.filter((source) => source.kind !== "SITE" || source.site.status !== "UNMAPPED");
  const attentionSources = operationalAttention.slice(0, 3);
  const attentionSiteIds = new Set(allAttention.map((source) => source.siteId));
  const primarySiteIds = new Set((attentionSources.length ? attentionSources : recentSiteSources).map((source) => source.siteId));
  const recentSources = selectHomeRecentUpdates({ workOrders, sites, excludedSiteIds: new Set([...attentionSiteIds, ...primarySiteIds]) });
  const siteById = new Map(sites.map((site) => [site.siteId, site]));
  const attentionItems = attentionSources.map((source) => attentionView(source, siteById, reviewAreaNameById));
  const recentSiteItems = recentSiteSources.map(recentSiteView);
  const siteActionPermissions = { canEditSite: permissions.includes("SITES_WRITE"), canCreateWorkOrder: permissions.includes("WORK_ORDERS_WRITE") };
  const initialSetupItems: HomeSituationItem[] = initialSetupSites.map((site) => {
    const nextAction = resolveSiteOperatorNextAction(site, siteActionPermissions);
    return { key: `initial-setup:${site.siteId}`, siteId: site.siteId, siteName: site.name, statusLabel: SITE_STATUS_LABEL[site.status].label, statusTone: SITE_STATUS_LABEL[site.status].tone, title: "작업구역에 첫 관측 자료를 연결하세요.", detail: "관측 자료 등록에서 작업구역을 선택합니다. 현장 전체 경계는 선택 설정입니다.", href: nextAction?.href ?? `/sites/${encodeURIComponent(site.siteId)}`, actionLabel: nextAction?.label ?? "현장 맥락 보기" };
  });
  // 대기열에 오르지 않은 실제 현장 바로가기 — 캐러셀·초기 설정에 이미 나온
  // 현장은 빼고, 남는 현장이 있을 때만 한 줄씩 둔다. 장식 이미지·가짜 요약은 두지 않는다.
  const surfacedSiteIds = new Set([
    ...attentionSources.map((source) => source.siteId),
    ...initialSetupItems.map((item) => item.siteId),
  ]);
  const otherSites = selectHomeQuickAccessSites(sites, surfacedSiteIds);
  const recentItems = recentSources.map((source) => recentUpdateView(source, siteById));
  const portfolioComplete = sitesResult.ok && workOrdersResult.ok && !operationsUnavailable && !decisionsUnavailable && !analysisReviewsUnknown;
  const attentionCount = new Set(operationalAttention.map((source) => source.siteId)).size;
  // 부분 읽기 복구는 하나의 간결한 안내로 묶는다 — 사유별 문구는 그대로 두되
  // 접힌 `확인하지 못한 항목` 안에만 둔다. 알려진 안건 카드·건수 표시는 가리지 않는다.
  const unknownReasons = [
    ...(operationsUnavailable ? [{ key: "operations", message: "외부 작업의 담당·마감·업무 종료 상태를 확인할 수 없습니다. 해당 작업을 확인 필요나 진행 중으로 분류하지 않았습니다." }] : []),
    ...(decisionsUnavailable ? [{ key: "decisions", message: "외부 결과의 검토·승인 대기 여부를 확인할 수 없습니다. 확인할 결과가 없다는 뜻이 아닙니다." }] : []),
    ...(analysisReviewsUnknown ? [{ key: "analysis-reviews", message: "분석 결과의 검토 대기 여부를 확인할 수 없습니다. 확인할 결과가 없다는 뜻이 아닙니다." }] : []),
  ];

  return <div className="flex flex-col gap-5 p-4 sm:p-5 lg:gap-6 lg:p-6">
    <header className="flex items-center justify-between gap-4 border-b border-line pb-3">
      <p className="text-[14px] font-bold tracking-[-0.015em] break-keep">전체 {sitesResult.ok ? `${sites.length}곳` : "—"}<span aria-hidden="true" className="mx-2 text-line-strong">·</span><span className={portfolioComplete && attentionCount > 0 ? "text-accent" : "text-ink-2"}>확인 필요 {portfolioComplete ? `${attentionCount}곳` : "—"}</span></p>
      <div className="flex items-center gap-4"><Link href="/field/inbox" className="tap-target text-[12px] font-semibold text-ink-2 hover:underline"><TopUnattendedHeadline pendingCount={inboxResult.ok ? inboxResult.value.items.length : null} /></Link><span aria-hidden="true" className="hidden h-4 w-px bg-line sm:block" /><Link href="/sites" className="tap-target hidden items-center text-[12px] font-semibold text-accent hover:underline sm:inline-flex">현장 전체</Link></div>
    </header>

    {!sitesResult.ok && <ErrorState message={sitesResult.message} retryable />}
    {sitesResult.ok && sites.length === 0 && <EmptyState title="아직 등록된 현장이 없습니다" description={canRegisterSite ? "첫 현장을 등록하면 관측과 변화 기록을 시작할 수 있습니다." : "현장 등록 권한이 있는 계정에서 시작할 수 있습니다."} action={canRegisterSite ? { label: "현장 등록", href: "/sites/new" } : undefined} />}
    {sites.length > 0 && !portfolioComplete && <section aria-label="일부 정보를 확인하지 못했습니다" className="rounded-lg border border-line bg-sunk px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <p className="text-[12.5px] leading-5 break-keep text-ink-2">일부 현장 또는 작업 원장을 불러오지 못해 확인 필요 건수를 추측하지 않습니다.</p>
        <Link href="/sites" className="tap-target inline-flex min-h-11 items-center font-semibold text-ink-1 underline underline-offset-2">현장 전체를 열어 직접 확인하세요.</Link>
      </div>
      {unknownReasons.length > 0 && <details className="mt-1 border-t border-line pt-1">
        <summary className="tap-target inline-flex cursor-pointer items-center text-[12.5px] font-semibold text-ink-2">확인하지 못한 항목 {unknownReasons.length}건</summary>
        <ul className="mt-1 flex flex-col gap-1">
          {unknownReasons.map((reason) => <li key={reason.key} className="text-[12.5px] leading-5 break-keep text-ink-2">{reason.message}</li>)}
        </ul>
      </details>}
    </section>}

    {attentionItems.length > 0 ? <HomeAttentionCarousel items={attentionItems} /> : recentSiteItems.length > 0 ? <HomeAttentionCarousel items={recentSiteItems} title={portfolioComplete ? "조회된 범위에 새 운영 안건이 없습니다." : "최근 현장을 직접 확인하세요."} description={portfolioComplete ? "현재 조회된 현장·작업과 최근 분석 기록 기준입니다. 전체 기록의 확인 완료나 현장의 정상·안전을 뜻하지 않습니다. 현장을 선택해 자료와 작업 이력을 확인하세요." : "일부 원장을 불러오지 못해 새 안건 여부를 판단하지 않습니다. 현장을 선택해 상태를 직접 확인하세요."} regionLabel="최근 현장 캐러셀" /> : null}

    {otherSites.length > 0 && (
      <section aria-label="다른 현장 바로가기" className="flex min-w-0 flex-col gap-2">
        <h2 className="text-[16px] font-bold tracking-[-0.015em] break-keep">다른 현장</h2>
        <ul className="flex min-w-0 flex-col gap-1.5">
          {otherSites.map((site) => (
            <li key={site.siteId} className="flex min-w-0 items-center gap-3 rounded-lg border border-line bg-surface px-4 py-2.5">
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold break-keep">{site.name}</span>
              <span className="shrink-0 text-[11.5px] text-ink-2">{SITE_STATUS_LABEL[site.status].label}</span>
              <Link href={`/sites/${encodeURIComponent(site.siteId)}`} aria-label={`${site.name} 열기`} className="tap-target shrink-0 text-[12px] font-semibold text-accent hover:underline">열기</Link>
            </li>
          ))}
        </ul>
      </section>
    )}

    {initialSetupItems.length > 0 && <HomeSituationList title="초기 설정이 필요한 현장" description="작업구역을 확인하고 고객이 준비한 관측 자료를 등록하세요." items={initialSetupItems} emptyMessage="초기 설정이 필요한 현장이 없습니다." allHref="/sites" allLabel="현장 전체" />}
    {sites.length > 0 && <HomeRecentUpdates items={recentItems} />}
    {/* 닫는 안내문은 두지 않는다 — 상단의 건수와 각 카드가 이미 "조회된 범위" 기준임을 말하고,
        같은 취지의 문장을 페이지 끝에 한 번 더 두면 매번 읽어야 하는 잔소리가 된다. */}
    {sites.length > 0 && <footer className="flex justify-end border-t border-line pt-3 text-[12px]"><Link href="/sites" className="tap-target inline-flex items-center font-semibold hover:underline">현장 자료·작업 보기</Link></footer>}
  </div>;
}
