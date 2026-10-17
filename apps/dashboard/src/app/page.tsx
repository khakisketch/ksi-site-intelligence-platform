import Link from "next/link";

import { HomeAttentionCarousel, type HomeAttentionCardView } from "./HomeAttentionCarousel";
import { HomeRecentUpdates, type HomeRecentUpdateView } from "./HomeRecentUpdates";
import { HomeSituationList, type HomeSituationItem } from "./HomeSituationList";
import { presentWorkOrder } from "./field/work-order-stage";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { whoAmI } from "@/lib/core-api/auth";
import { getAnalysisReviewTarget, listAnalyses, listAnalysisReviews } from "@/lib/core-api/analysis";
import { listSitesCached } from "@/lib/core-api/cached";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { listExternalPendingDecisions } from "@/lib/core-api/external-decisions";
import { listObservationWorkOrderOperations, listObservationWorkOrdersForOrganization } from "@/lib/core-api/observation-work-orders";
import { listWorkInbox } from "@/lib/core-api/work-collaboration";
import type { SiteView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { externalDecisionCardText } from "@/lib/home-external-decision";
import { selectHomeAnalysisReviewSources, selectHomeAttentionSources, selectHomeInitialSetupSites, selectHomeRecentSiteSources, selectHomeRecentUpdates, type HomeAnalysisReviewRecord, type HomeAnalysisReviewSource, type HomeAttentionSource, type HomeRecentSiteSource, type HomeRecentUpdateSource } from "@/lib/home-operations";
import { resolveSiteOperatorNextAction } from "@/lib/operator-next-action";
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

async function loadHomeAnalysisReviewSources(siteIds: readonly string[]): Promise<HomeAnalysisReviewSource[]> {
  // Bound the server-side read to 3 Home-context Sites × 5 analyses. Each completed
  // analysis checked uses one target and one review-list GET: at most 33 Core calls.
  const boundedSiteIds = [...new Set(siteIds)].slice(0, MAX_HOME_ANALYSIS_REVIEW_SITES);
  const perSite = await Promise.all(boundedSiteIds.map(async (siteId) => {
    try {
      const page = await listAnalyses(siteId, { limit: MAX_HOME_ANALYSES_PER_SITE });
      const completed = page.items
        .filter((analysis) => analysis.siteId === siteId && analysis.executionState === "COMPLETED" && analysis.resultId !== null)
        .toSorted((a, b) => b.createdAt.localeCompare(a.createdAt) || a.analysisId.localeCompare(b.analysisId));
      const records: HomeAnalysisReviewRecord[] = [];

      for (const analysis of completed) {
        try {
          const [currentTarget, reviewPage] = await Promise.all([
            getAnalysisReviewTarget(siteId, analysis.analysisId),
            // Match the detail panel's bounded page; Core review pages are not newest-first.
            listAnalysisReviews(siteId, analysis.analysisId, { limit: MAX_HOME_ANALYSIS_REVIEW_PAGE }),
          ]);
          records.push({ analysis, currentTarget, reviews: reviewPage.items });
          const candidate = selectHomeAnalysisReviewSources(records)[0];
          if (candidate) return candidate;
        } catch {
          // Without both current target and receipts the exact-review state is unknown.
          return null;
        }
      }
    } catch {
      // Analysis is an optional Home source: a missing/denied Core read never breaks Home.
    }
    return null;
  }));

  return perSite.filter((source): source is HomeAnalysisReviewSource => source !== null);
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
  return "작업 원장에 기록된 현재 상태와 근거를 확인합니다.";
}

function fallback() {
  return { label: "연결된 이미지 없음", detail: "현장 원장에 등록된 관측 이미지가 없습니다." };
}

function attentionView(source: HomeAttentionSource, siteById: ReadonlyMap<string, SiteView>): HomeAttentionCardView {
  const siteName = siteById.get(source.siteId)?.name ?? "이름을 확인할 수 없는 현장";
  if (source.kind === "EXTERNAL_DECISION") {
    const card = externalDecisionCardText(source.decision);
    return { key: source.key, siteName, label: card.label, title: card.title, detail: card.detail, observedAt: observedAt(source.observedAt), href: card.href, actionLabel: card.actionLabel, image: null, imageFallback: fallback() };
  }
  if (source.kind === "ANALYSIS_REVIEW") {
    const analysis = source.analysis;
    return {
      key: source.key,
      siteName,
      label: "분석 검토 대기",
      title: "완료된 분석 결과를 검토하세요.",
      detail: "완료된 분석 결과에 현재 결과를 대상으로 한 검토 기록이 없습니다. 결과와 근거를 확인하세요.",
      observedAt: observedAt(source.observedAt),
      href: `/sites/${encodeURIComponent(source.siteId)}/analysis?analysisId=${encodeURIComponent(analysis.analysisId)}`,
      actionLabel: "분석 결과 검토",
      image: null,
      imageFallback: fallback(),
    };
  }
  if (source.kind === "WORK_ORDER") {
    const order = source.workOrder;
    const presentation = presentWorkOrder(order.status, order.executionMode);
    return { key: source.key, siteName, label: presentation.label, title: order.name, detail: attentionWorkOrderDetail(source), observedAt: observedAt(source.observedAt), href: `/field/work-orders/${encodeURIComponent(order.workOrderId)}`, actionLabel: order.status === "REVIEW_READY" ? "결과와 근거 보기" : "작업 맥락 보기", image: null, imageFallback: fallback() };
  }
  const status = SITE_STATUS_LABEL[source.site.status];
  const title = source.site.status === "UNMAPPED" ? "초기 관측 범위를 준비해야 합니다." : source.site.status === "REMAP_REQUIRED" ? "새 기준 관측이 필요합니다." : "최근 현장 상태를 다시 관측해야 합니다.";
  return { key: source.key, siteName, label: status.label, title, detail: "현장 상태와 조사할 공사 구역을 확인한 뒤 필요한 관측 범위를 결정할 수 있습니다.", observedAt: observedAt(source.observedAt), href: `/sites/${encodeURIComponent(source.siteId)}`, actionLabel: "현장 맥락 보기", image: null, imageFallback: fallback() };
}

function recentUpdateView(source: HomeRecentUpdateSource, siteById: ReadonlyMap<string, SiteView>): HomeRecentUpdateView {
  const siteName = siteById.get(source.siteId)?.name ?? "이름을 확인할 수 없는 현장";
  if ("site" in source) {
    return { key: source.key, siteName, label: "현재 원장", title: "등록된 대기 작업 없음", detail: "현재 KSI 작업 원장 기준이며 현장 전체의 정상이나 안전을 의미하지 않습니다.", observedAt: `현장 갱신 ${observedAt(source.observedAt)}`, href: `/sites/${encodeURIComponent(source.site.siteId)}`, image: null, imageFallbackLabel: "연결된 미리보기 없음" };
  }
  if (source.kind === "RESULT_READY" || source.kind === "OBSERVATION_COMPLETED") {
    return { key: source.key, siteName, label: source.kind === "RESULT_READY" ? "새 결과" : "최근 조사", title: source.workOrder.name, detail: source.kind === "RESULT_READY" ? "외부 결과와 보관 근거를 검토합니다." : "조사 결과가 작업 원장에 기록되었습니다.", observedAt: observedAt(source.observedAt), href: `/field/work-orders/${encodeURIComponent(source.workOrder.workOrderId)}`, image: null, imageFallbackLabel: "연결된 미리보기 없음" };
  }
  throw new Error("Unsupported Home update source");
}

function recentSiteView(source: HomeRecentSiteSource): HomeAttentionCardView {
  const status = SITE_STATUS_LABEL[source.site.status];
  return { key: source.key, siteName: source.site.name, label: source.site.status === "UNMAPPED" ? "초기 설정" : `현재 원장 · ${status.label}`, title: source.site.status === "UNMAPPED" ? "최근 등록한 현장 맥락을 확인하세요." : "최근 현장 맥락을 살펴보세요.", detail: source.site.status === "UNMAPPED" ? "현장 범위와 상태를 확인하고 필요한 준비 작업을 이어가세요." : "현장 원장과 다음 관측 준비 상황을 직접 확인할 수 있습니다.", observedAt: `현장 갱신 ${observedAt(source.site.updatedAt)}`, href: `/sites/${encodeURIComponent(source.siteId)}`, actionLabel: "현장 보기", image: null, imageFallback: fallback() };
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
  const canRegisterSite = permissions.includes("SITES_WRITE");
  const baseAttention = selectHomeAttentionSources({ workOrders, sites, operationsByWorkOrderId, externalDecisions: decisions }, Number.MAX_SAFE_INTEGER);
  const initialSetupSites = selectHomeInitialSetupSites(sites);
  const recentSiteSources = selectHomeRecentSiteSources(sites);
  const externalDecisionSiteIds = new Set(decisions.map((decision) => decision.siteId));
  const analysisReviewSiteIds = [...new Set([
    ...baseAttention
      .filter((source) => source.kind !== "EXTERNAL_DECISION" && !(source.kind === "SITE" && source.site.status === "UNMAPPED"))
      .map((source) => source.siteId),
    ...recentSiteSources.filter((source) => !externalDecisionSiteIds.has(source.siteId)).map((source) => source.siteId),
  ])].slice(0, MAX_HOME_ANALYSIS_REVIEW_SITES);
  const analysisReviewSources = await loadHomeAnalysisReviewSources(analysisReviewSiteIds);
  const allAttention = selectHomeAttentionSources({ workOrders, sites, operationsByWorkOrderId, externalDecisions: decisions, analysisReviews: analysisReviewSources }, Number.MAX_SAFE_INTEGER);
  const operationalAttention = allAttention.filter((source) => source.kind !== "SITE" || source.site.status !== "UNMAPPED");
  const attentionSources = operationalAttention.slice(0, 3);
  const attentionSiteIds = new Set(allAttention.map((source) => source.siteId));
  const primarySiteIds = new Set((attentionSources.length ? attentionSources : recentSiteSources).map((source) => source.siteId));
  const recentSources = selectHomeRecentUpdates({ workOrders, sites, excludedSiteIds: new Set([...attentionSiteIds, ...primarySiteIds]) });
  const siteById = new Map(sites.map((site) => [site.siteId, site]));
  const attentionItems = attentionSources.map((source) => attentionView(source, siteById));
  const recentSiteItems = recentSiteSources.map(recentSiteView);
  const siteActionPermissions = { canEditSite: permissions.includes("SITES_WRITE"), canCreateWorkOrder: permissions.includes("WORK_ORDERS_WRITE") };
  const initialSetupItems: HomeSituationItem[] = initialSetupSites.map((site) => {
    const nextAction = resolveSiteOperatorNextAction(site, siteActionPermissions);
    const hasAoi = site.aoi !== null;
    return { key: `initial-setup:${site.siteId}`, siteId: site.siteId, siteName: site.name, statusLabel: SITE_STATUS_LABEL[site.status].label, statusTone: SITE_STATUS_LABEL[site.status].tone, title: hasAoi ? "첫 기준 관측을 준비하세요." : "첫 관측 전에 현장 범위를 설정하세요.", detail: hasAoi ? "현장 범위가 준비되었습니다. 관측 작업을 만들 수 있습니다." : "아직 관측 범위가 없습니다. 먼저 현장 경계를 저장하세요.", href: nextAction?.href ?? `/sites/${encodeURIComponent(site.siteId)}`, actionLabel: nextAction?.label ?? "현장 맥락 보기" };
  });
  const recentItems = recentSources.map((source) => recentUpdateView(source, siteById));
  const portfolioComplete = sitesResult.ok && workOrdersResult.ok && !operationsUnavailable && !decisionsUnavailable;
  const attentionCount = new Set(operationalAttention.map((source) => source.siteId)).size;

  return <div className="flex flex-col gap-5 p-4 sm:p-5 lg:gap-6 lg:p-6">
    <header className="flex items-center justify-between gap-4 border-b border-line pb-3">
      <p className="text-[14px] font-bold tracking-[-0.015em] break-keep">전체 {sitesResult.ok ? `${sites.length}곳` : "—"}<span aria-hidden="true" className="mx-2 text-line-strong">·</span><span className={portfolioComplete && attentionCount > 0 ? "text-accent" : "text-ink-2"}>확인 필요 {portfolioComplete ? `${attentionCount}곳` : "—"}</span></p>
      <div className="flex items-center gap-4"><Link href="/field/inbox" className="tap-target text-[12px] font-semibold text-ink-2 hover:underline"><TopUnattendedHeadline pendingCount={inboxResult.ok ? inboxResult.value.items.length : null} /></Link><span aria-hidden="true" className="hidden h-4 w-px bg-line sm:block" /><Link href="/sites" className="tap-target hidden items-center text-[12px] font-semibold text-accent hover:underline sm:inline-flex">현장 전체</Link></div>
    </header>

    {!sitesResult.ok && <ErrorState message={sitesResult.message} retryable />}
    {sitesResult.ok && sites.length === 0 && <EmptyState title="아직 등록된 현장이 없습니다" description={canRegisterSite ? "첫 현장을 등록하면 관측과 변화 기록을 시작할 수 있습니다." : "현장 등록 권한이 있는 계정에서 시작할 수 있습니다."} action={canRegisterSite ? { label: "현장 등록", href: "/sites/new" } : undefined} />}
    {sites.length > 0 && !portfolioComplete && <section className="rounded-lg border border-line bg-sunk px-4 py-3"><p className="text-[12.5px] leading-5 break-keep text-ink-2">일부 현장 또는 작업 원장을 불러오지 못해 확인 필요 건수를 추측하지 않습니다.</p><Link href="/sites" className="mt-1 inline-flex min-h-11 items-center font-semibold text-ink-1 underline underline-offset-2">현장 전체를 열어 직접 확인하세요.</Link></section>}
    {operationsUnavailable && <p className="rounded-lg border border-line bg-sunk px-4 py-3 text-[12.5px] leading-5 break-keep text-ink-2">외부 작업의 담당·마감·업무 종료 상태를 확인할 수 없습니다. 해당 작업을 확인 필요나 진행 중으로 분류하지 않았습니다.</p>}
    {decisionsUnavailable && <p className="rounded-lg border border-line bg-sunk px-4 py-3 text-[12.5px] leading-5 break-keep text-ink-2">외부 결과의 검토·승인 대기 여부를 확인할 수 없습니다. 확인할 결과가 없다는 뜻이 아닙니다.</p>}

    {attentionItems.length > 0 ? <HomeAttentionCarousel items={attentionItems} /> : recentSiteItems.length > 0 ? <HomeAttentionCarousel items={recentSiteItems} title={portfolioComplete ? "새로 확인할 운영 안건이 없습니다." : "최근 현장을 직접 확인하세요."} description={portfolioComplete ? "현재 KSI 원장 기준이며 현장 전체의 정상이나 안전을 보증하지 않습니다. 최근 현장을 선택해 관측 맥락을 살펴보세요." : "일부 원장을 불러오지 못해 새 안건 여부를 판단하지 않습니다. 현장을 선택해 상태를 직접 확인하세요."} regionLabel="최근 현장 캐러셀" /> : null}

    {initialSetupItems.length > 0 && <HomeSituationList title="초기 설정이 필요한 현장" description="첫 관측을 시작하기 위해 현장 범위 설정이나 작업 준비가 필요합니다." items={initialSetupItems} emptyMessage="초기 설정이 필요한 현장이 없습니다." allHref="/sites" allLabel="현장 전체" />}
    {sites.length > 0 && <HomeRecentUpdates items={recentItems} />}
  </div>;
}
