import { Disclosure } from "@/components/ui/Disclosure";
import Link from "next/link";

import { HomeInbox, type HomeInboxItem } from "./HomeInbox";
import { HomeProjects, parseHomeProjectSort } from "./HomeProjects";
import { HomeRecentUpdates, type HomeRecentUpdateView } from "./HomeRecentUpdates";
import { presentWorkOrder } from "./field/work-order-stage";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineNotice } from "@/components/ui/InlineNotice";
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
 * 검토 대기 분석이 가리키는 실제 영역 이름. 검토 대상은 최대 3개 현장으로
 * 한정되어 있어 현장별 한 번씩만 읽는다(보관 영역 포함 — 과거 분석 맥락용).
 * 영역 ID는 현장 안에서만 유일하므로 현장별로 나눠 둔다.
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

function inboxTitleForWorkOrder(source: Extract<HomeAttentionSource, { kind: "WORK_ORDER" }>): { kind: HomeInboxItem["kind"]; title: string } {
  switch (source.workOrder.status) {
    case "DRAFT":
    case "AWAITING_APPROVAL": return { kind: "approval", title: "작업 범위를 승인하세요" };
    case "BLOCKED": return { kind: "work", title: "막힌 작업을 확인하세요" };
    case "REOBSERVATION_PENDING": return { kind: "decision", title: "추가 관측을 결정하세요" };
    case "REVIEW_READY": return { kind: "review", title: "작업 결과를 검토하세요" };
    default: return { kind: "work", title: "작업을 확인하세요" };
  }
}

/** 확인할 일 한 줄 — 제목은 해야 할 일(동사), 프로젝트·대상은 보조, 행동은 하나다. 문장형 설명은 각 화면이 말한다. */
function inboxItemView(source: HomeAttentionSource, siteById: ReadonlyMap<string, SiteView>, areaNameBySite: ReadonlyMap<string, ReadonlyMap<string, string>> = new Map()): HomeInboxItem {
  const siteName = siteById.get(source.siteId)?.name ?? "이름을 확인할 수 없는 프로젝트";
  if (source.kind === "EXTERNAL_DECISION") {
    const card = externalDecisionCardText(source.decision);
    return {
      key: source.key, kind: source.decision.stage === "AWAITING_REVIEW" ? "review" : "approval",
      title: source.decision.stage === "AWAITING_REVIEW" ? "외부 결과를 검토하세요" : "재관측 제안을 승인하세요",
      siteName, subject: card.title, href: card.href, actionLabel: "결과 보기", observedAt: source.observedAt, timeLabel: "결과 보고",
    };
  }
  if (source.kind === "ANALYSIS_REVIEW") {
    const analysis = source.analysis;
    const areaName = areaNameBySite.get(source.siteId)?.get(analysis.workAreaId) ?? null;
    return {
      key: source.key, kind: "review", title: "분석 결과를 검토하세요", siteName, subject: areaName,
      href: `/sites/${encodeURIComponent(source.siteId)}/analysis?analysisId=${encodeURIComponent(analysis.analysisId)}&workAreaId=${encodeURIComponent(analysis.workAreaId)}`,
      actionLabel: "결과 보기", observedAt: source.observedAt, timeLabel: "분석 생성",
      technicalRef: formatHomeReviewTechnicalRef(analysis.analysisId, analysis.workAreaId),
    };
  }
  if (source.kind === "WORK_ORDER") {
    const order = source.workOrder;
    const { kind, title } = inboxTitleForWorkOrder(source);
    return { key: source.key, kind, title, siteName, subject: order.name, href: `/field/work-orders/${encodeURIComponent(order.workOrderId)}`, actionLabel: "작업 보기", observedAt: source.observedAt, timeLabel: "작업 갱신" };
  }
  const status = SITE_STATUS_LABEL[source.site.status];
  return {
    key: source.key, kind: "site",
    title: source.site.status === "REMAP_REQUIRED" ? "새 기준 관측이 필요합니다" : "프로젝트 상태를 확인하세요",
    siteName, subject: status.label, href: `/sites/${encodeURIComponent(source.siteId)}`, actionLabel: "프로젝트 열기", observedAt: source.observedAt, timeLabel: "프로젝트 갱신",
  };
}

function recentUpdateView(source: HomeRecentUpdateSource, siteById: ReadonlyMap<string, SiteView>): HomeRecentUpdateView {
  const siteName = siteById.get(source.siteId)?.name ?? "이름을 확인할 수 없는 프로젝트";
  if ("site" in source) {
    return { key: source.key, siteName, label: "현재 상태", title: "대기 작업 없음", href: `/sites/${encodeURIComponent(source.site.siteId)}`, observedAt: source.observedAt, timeLabel: "프로젝트 갱신" };
  }
  if (source.kind === "RESULT_READY" || source.kind === "OBSERVATION_COMPLETED") {
    return { key: source.key, siteName, label: source.kind === "RESULT_READY" ? "새 결과" : "최근 관측", title: source.workOrder.name, href: `/field/work-orders/${encodeURIComponent(source.workOrder.workOrderId)}`, observedAt: source.observedAt, timeLabel: source.kind === "RESULT_READY" ? "결과 보고" : "작업 갱신" };
  }
  throw new Error("Unsupported Home update source");
}

export default async function HomePage({ searchParams }: { searchParams?: Promise<{ sort?: string | string[] }> } = {}) {
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
  // 가장 위에 오르는 안건의 프로젝트는 "최근 소식"과 겹치지 않게 뺀다(D4 중복 제외).
  const primaryAttention = operationalAttention.slice(0, 3);
  const attentionSiteIds = new Set(allAttention.map((source) => source.siteId));
  const primarySiteIds = new Set((primaryAttention.length ? primaryAttention : recentSiteSources).map((source) => source.siteId));
  const recentSources = selectHomeRecentUpdates({ workOrders, sites, excludedSiteIds: new Set([...attentionSiteIds, ...primarySiteIds]) });
  const siteById = new Map(sites.map((site) => [site.siteId, site]));
  const siteActionPermissions = { canEditSite: permissions.includes("SITES_WRITE"), canCreateWorkOrder: permissions.includes("WORK_ORDERS_WRITE") };
  // 확인할 것 = 확인 안건 + 초기 설정. 안건이 앞이고 초기 설정이 뒤다(D1 순서).
  const setupItems: HomeInboxItem[] = initialSetupSites.map((site) => {
    const nextAction = resolveSiteOperatorNextAction(site, siteActionPermissions);
    return {
      key: `initial-setup:${site.siteId}`, kind: "setup", title: "첫 관측 자료를 연결하세요", siteName: site.name, subject: null,
      href: nextAction?.href ?? `/sites/${encodeURIComponent(site.siteId)}`, actionLabel: nextAction?.label ?? "프로젝트 열기",
      observedAt: site.updatedAt, timeLabel: "프로젝트 갱신",
    };
  });
  const inboxItems = [...operationalAttention.map((source) => inboxItemView(source, siteById, reviewAreaNameById)), ...setupItems];
  // 프로젝트 카드의 "확인 N" — 홈이 읽은 확인할 일을 프로젝트별로 센 값이다.
  const attentionBySite = new Map<string, number>();
  for (const source of operationalAttention) attentionBySite.set(source.siteId, (attentionBySite.get(source.siteId) ?? 0) + 1);
  for (const site of initialSetupSites) attentionBySite.set(site.siteId, (attentionBySite.get(site.siteId) ?? 0) + 1);
  const recentItems = recentSources.slice(0, 3).map((source) => recentUpdateView(source, siteById));
  const portfolioComplete = sitesResult.ok && workOrdersResult.ok && !operationsUnavailable && !decisionsUnavailable && !analysisReviewsUnknown;
  // 부분 읽기 복구는 하나의 간결한 안내로 묶는다 — 사유별 문구는 그대로 두되 접힌 `자세히` 안에만 둔다.
  // 알려진 안건과 건수는 가리지 않는다(건수는 하한이므로 "N+"로 쓴다).
  const unknownReasons = [
    ...(operationsUnavailable ? [{ key: "operations", message: "외부 작업의 담당·마감·작업 종료 상태를 확인할 수 없습니다. 해당 작업을 확인 필요나 진행 중으로 분류하지 않았습니다." }] : []),
    ...(decisionsUnavailable ? [{ key: "decisions", message: "외부 결과의 검토·승인 대기 여부를 확인할 수 없습니다. 확인할 결과가 없다는 뜻이 아닙니다." }] : []),
    ...(analysisReviewsUnknown ? [{ key: "analysis-reviews", message: "분석 결과의 검토 대기 여부를 확인할 수 없습니다. 확인할 결과가 없다는 뜻이 아닙니다." }] : []),
  ];
  const sort = parseHomeProjectSort((await searchParams)?.sort);

  return <div className="console-page">
    {!sitesResult.ok && <ErrorState message={sitesResult.message} retryable />}
    {sitesResult.ok && sites.length === 0 && <EmptyState title="현재 계정에서 볼 수 있는 프로젝트가 없습니다" description="찾는 프로젝트가 이미 있다면 관리자에게 이 계정의 프로젝트 접근 권한을 확인해 주세요." action={canRegisterSite ? { label: "프로젝트 등록", href: "/sites/new" } : { label: "프로젝트 목록", href: "/sites" }} />}

    {sites.length > 0 && (
      <div className="grid min-w-0 gap-8 lg:grid-cols-[minmax(320px,560px)_minmax(0,1fr)] lg:items-start lg:gap-10 2xl:grid-cols-[minmax(0,640px)_minmax(0,1fr)]">
        <HomeInbox
          items={inboxItems}
          complete={portfolioComplete}
          headerAction={(
            <Link href="/field/inbox" className="tap-target inline-flex items-center text-caption font-semibold whitespace-nowrap text-ink-2 hover:underline">
              <TopUnattendedHeadline pendingCount={inboxResult.ok ? inboxResult.value.items.length : null} />
            </Link>
          )}
          notice={!portfolioComplete ? (
            <section aria-label="일부 정보를 확인하지 못했습니다" className="border-t border-line bg-sunk px-3.5 py-2.5 text-caption text-ink-2">
              <p>
                일부를 확인하지 못했습니다. 확인할 것이 이보다 많을 수 있습니다.{" "}
                <Link href="/sites" className="tap-target inline-flex items-center font-semibold text-ink-1 underline underline-offset-2">프로젝트 전체 열기</Link>
              </p>
              {unknownReasons.length > 0 && <Disclosure className="mt-0.5" label={`자세히 (${unknownReasons.length}건)`}>
                <ul className="flex flex-col gap-1 pb-1">
                  {unknownReasons.map((reason) => <li key={reason.key} className="leading-5 break-keep">{reason.message}</li>)}
                </ul>
              </Disclosure>}
            </section>
          ) : null}
        />
        <div className="flex min-w-0 flex-col gap-6">
          <HomeProjects sites={sites} attentionBySite={attentionBySite} sort={sort} />
          <HomeRecentUpdates items={recentItems} />
        </div>
      </div>
    )}
  </div>;
}
