import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { whoAmI } from "@/lib/core-api/auth";
import { listAllEventsCached, listSitesCached } from "@/lib/core-api/cached";
import { CoreApiError } from "@/lib/core-api/client";
import {
  EVENT_SEVERITY_LABEL,
  EVENT_STATUS_LABEL,
  SEVERITY_UNSET_LABEL,
  SITE_STATUS_LABEL,
  TRIAGE_STATUS_LABEL,
  humanizeApiError,
  humanizeEventType,
} from "@/lib/core-api/labels";
import {
  listObservationWorkOrderOperations,
  listObservationWorkOrdersForOrganization,
} from "@/lib/core-api/observation-work-orders";
import type { SiteView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { getHomeEventEvidencePreview, type HomeEvidencePreview } from "@/lib/home-evidence";
import {
  selectHomeAttentionSources,
  selectHomeInitialSetupSites,
  selectHomeRecentSiteSources,
  selectHomeRecentUpdates,
  type HomeAttentionSource,
  type HomeRecentSiteSource,
  type HomeRecentUpdateSource,
} from "@/lib/home-operations";
import { resolveSiteOperatorNextAction } from "@/lib/operator-next-action";
import { listLatestSiteBriefings } from "@/lib/core-api/site-workspace";
import { listExternalPendingDecisions } from "@/lib/core-api/external-decisions";
import { externalDecisionCardText } from "@/lib/home-external-decision";

import { HomeAttentionCarousel, type HomeAttentionCardView } from "./HomeAttentionCarousel";
import { HomeRecentUpdates, type HomeRecentUpdateView } from "./HomeRecentUpdates";
import { HomeSituationList, type HomeSituationItem } from "./HomeSituationList";
import { presentWorkOrder } from "./field/work-order-stage";

export const metadata = { title: "홈 · KSI" };

type Settled<T> =
  | { ok: true; value: T }
  | { ok: false; forbidden: boolean; message: string };

type PreviewOutcome =
  | { state: "AVAILABLE"; preview: HomeEvidencePreview }
  | { state: "NOT_REGISTERED" }
  | { state: "UNAVAILABLE" };

async function settle<T>(promise: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    if (error instanceof CoreApiError) {
      return {
        ok: false,
        forbidden: error.status === 403,
        message: humanizeApiError(error.code, error.status, error.serverMessage),
      };
    }
    return { ok: false, forbidden: false, message: "요청을 처리하지 못했습니다." };
  }
}

function observedAt(value: string): string {
  return formatKoreanDateTime(value, { dateStyle: "medium", timeStyle: "short" });
}

function previewFallback(outcome: PreviewOutcome | undefined): { label: string; detail: string } {
  if (outcome?.state === "UNAVAILABLE") {
    return {
      label: "관측 이미지 열람 불가",
      detail: "기록된 관측 상태는 유지됩니다. 상세 화면에서 근거와 연결 상태를 다시 확인하세요.",
    };
  }
  if (outcome?.state === "NOT_REGISTERED") {
    return {
      label: "관측 이미지 미등록",
      detail: "이 확인 항목에는 아직 열람 가능한 이미지 근거가 연결되지 않았습니다.",
    };
  }
  return {
    label: "관측 이미지 없음",
    detail: "현장 상태는 기록되어 있습니다. 최신 관측과 맥락은 현장 화면에서 확인하세요.",
  };
}

function attentionWorkOrderDetail(source: Extract<HomeAttentionSource, { kind: "WORK_ORDER" }>): string {
  const workOrder = source.workOrder;
  if (workOrder.statusReason) return workOrder.statusReason;
  switch (workOrder.status) {
    case "BLOCKED":
      return "작업 진행을 막은 사유와 복구 경로를 확인해야 합니다.";
    case "DRAFT":
    case "AWAITING_APPROVAL":
      return `조사 범위 ${workOrder.workAreaIds.length}개 구역과 목적을 검토해야 합니다.`;
    case "REOBSERVATION_PENDING":
      return "부족한 근거와 추가 촬영 범위를 확인한 뒤 사람이 결정합니다.";
    case "REVIEW_READY":
      return "근거와 정확도 범위를 검토하고 KSI에 현장 자료를 질문할 수 있습니다.";
    default:
      return "작업 원장에 기록된 현재 상태와 근거를 확인합니다.";
  }
}

function attentionView(
  source: HomeAttentionSource,
  siteById: ReadonlyMap<string, SiteView>,
  previews: ReadonlyMap<string, PreviewOutcome>,
): HomeAttentionCardView {
  const siteName = siteById.get(source.siteId)?.name ?? source.siteId;
  if (source.kind === "EVENT") {
    const event = source.event;
    const severity = event.severity ? EVENT_SEVERITY_LABEL[event.severity] : SEVERITY_UNSET_LABEL;
    const outcome = previews.get(event.eventKey);
    return {
      key: source.key,
      siteName,
      label: `관측 근거 · ${severity.label}`,
      title: `${humanizeEventType(event.eventType)} 관측을 살펴보세요.`,
      detail: "발생 범위와 촬영 근거를 확인한 뒤 실제 공정·물량 업무에 미치는 영향을 판단할 수 있습니다.",
      observedAt: observedAt(source.observedAt),
      href: `/events/${encodeURIComponent(event.eventKey)}`,
      actionLabel: "근거와 맥락 보기",
      image:
        outcome?.state === "AVAILABLE"
          ? { src: outcome.preview.src, alt: `${siteName}의 ${humanizeEventType(event.eventType)} 관측 근거` }
          : null,
      imageFallback: previewFallback(outcome),
    };
  }

  if (source.kind === "EXTERNAL_DECISION") {
    const text = externalDecisionCardText(source.decision);
    return {
      key: source.key,
      siteName,
      label: text.label,
      title: text.title,
      detail: text.detail,
      observedAt: observedAt(source.observedAt),
      href: text.href,
      actionLabel: text.actionLabel,
      image: null,
      imageFallback: previewFallback(undefined),
    };
  }

  if (source.kind === "WORK_ORDER") {
    const workOrder = source.workOrder;
    const presentation = presentWorkOrder(workOrder.status, workOrder.executionMode);
    return {
      key: source.key,
      siteName,
      label: presentation.label,
      title: workOrder.name,
      detail: attentionWorkOrderDetail(source),
      observedAt: observedAt(source.observedAt),
      href: `/field/work-orders/${encodeURIComponent(workOrder.workOrderId)}`,
      actionLabel: workOrder.status === "REVIEW_READY" ? "결과와 근거 보기" : "작업 맥락 보기",
      image: null,
      imageFallback: previewFallback(undefined),
    };
  }

  const site = source.site;
  const status = SITE_STATUS_LABEL[site.status];
  const title =
    site.status === "UNMAPPED"
      ? "초기 관측 범위를 준비해야 합니다."
      : site.status === "REMAP_REQUIRED"
        ? "새 기준 관측이 필요합니다."
        : "최근 현장 상태를 다시 관측해야 합니다.";
  return {
    key: source.key,
    siteName,
    label: status.label,
    title,
    detail: "현장 상태와 조사할 공사 구역을 확인한 뒤 필요한 조사 범위를 결정할 수 있습니다.",
    observedAt: observedAt(source.observedAt),
    href: `/sites/${encodeURIComponent(site.siteId)}`,
    actionLabel: "현장 맥락 보기",
    image: null,
    imageFallback: previewFallback(undefined),
  };
}

function recentUpdateView(
  source: HomeRecentUpdateSource,
  siteById: ReadonlyMap<string, SiteView>,
  previews: ReadonlyMap<string, PreviewOutcome>,
): HomeRecentUpdateView {
  const siteName = siteById.get(source.siteId)?.name ?? source.siteId;
  if (source.kind === "RESULT_READY" || source.kind === "OBSERVATION_COMPLETED") {
    return {
      key: source.key,
      siteName,
      label: source.kind === "RESULT_READY" ? "새 결과" : "최근 조사",
      title: source.workOrder.name,
      detail:
        source.kind === "RESULT_READY"
          ? "근거와 정확도 범위를 검토하고 KSI에 현장 자료를 질문할 수 있습니다."
          : "조사 결과가 원장에 기록되었습니다. 세부 결과는 작업 화면에서 확인합니다.",
      observedAt: observedAt(source.observedAt),
      href: `/field/work-orders/${encodeURIComponent(source.workOrder.workOrderId)}${source.kind === "RESULT_READY" ? "#copilot" : ""}`,
      image: null,
      imageFallbackLabel: "관측 이미지 없음",
    };
  }

  if (source.kind === "EVENT_SETTLED") {
    const event = source.event;
    const outcome = previews.get(event.eventKey);
    const settledLabel =
      event.status === "DISMISSED" ? EVENT_STATUS_LABEL.DISMISSED.label : TRIAGE_STATUS_LABEL[event.triage].label;
    return {
      key: source.key,
      siteName,
      label: "정리된 안건",
      title: `${humanizeEventType(event.eventType)} · ${settledLabel}`,
      detail: "사람이 기록한 상태를 표시합니다. 현장 전체의 정상이나 안전을 의미하지 않습니다.",
      observedAt: observedAt(source.observedAt),
      href: `/events/${encodeURIComponent(event.eventKey)}`,
      image:
        outcome?.state === "AVAILABLE"
          ? { src: outcome.preview.src, alt: `${siteName}의 정리된 ${humanizeEventType(event.eventType)} 근거` }
          : null,
      imageFallbackLabel: previewFallback(outcome).label,
    };
  }

  if (source.kind === "EXTERNAL_RESULT_BRIEFED") {
    const briefing = source.briefing;
    const report = briefing.citations.find(
      (citation) => citation.objectType === "external-relative-volume-report",
    );
    const firstSentence = briefing.whatChanged.split(/(?<=\.)\s/)[0] ?? briefing.whatChanged;
    return {
      key: source.key,
      siteName,
      label: "새 결과",
      title: firstSentence.length > 60 ? `${firstSentence.slice(0, 59)}…` : firstSentence,
      detail: briefing.decisionPrompt,
      observedAt: observedAt(source.observedAt),
      href: report
        ? `/sites/${encodeURIComponent(source.siteId)}/observations/${encodeURIComponent(report.objectId)}`
        : `/sites/${encodeURIComponent(source.siteId)}`,
      image: null,
      imageFallbackLabel: "관측 이미지 없음",
    };
  }

  if (source.kind === "CURRENT_LEDGER_CLEAR") {
    return {
      key: source.key,
      siteName,
      label: "현재 원장",
      title: "등록된 미조치 관측 없음",
      detail: "현재 KSI 원장 기준이며 현장 전체의 정상이나 안전을 의미하지 않습니다.",
      observedAt: observedAt(source.observedAt),
      href: `/sites/${encodeURIComponent(source.site.siteId)}`,
      image: null,
      imageFallbackLabel: "연결된 미리보기 없음",
    };
  }

  throw new Error(`Unsupported Home update source: ${source satisfies never}`);
}

function recentSiteView(
  source: HomeRecentSiteSource,
  previews: ReadonlyMap<string, PreviewOutcome>,
): HomeAttentionCardView {
  const event = source.latestEvent;
  const outcome = event ? previews.get(event.eventKey) : undefined;
  const status = SITE_STATUS_LABEL[source.site.status];
  const imageFallback = event
    ? previewFallback(outcome)
    : {
        label: "최근 관측 이미지 없음",
        detail: "현장 원장은 등록되어 있습니다. 첫 관측 또는 최신 현장 맥락은 현장 화면에서 확인하세요.",
      };

  return {
    key: source.key,
    siteName: source.site.name,
    label: source.site.status === "UNMAPPED" ? "초기 설정" : `현재 원장 · ${status.label}`,
    title: source.site.status === "UNMAPPED" ? "최근 등록한 현장 맥락을 확인하세요." : "최근 현장 맥락을 살펴보세요.",
    detail: event
      ? `최근 ${humanizeEventType(event.eventType)} 관측이 기록되어 있습니다. 새 운영 안건이 없는 동안 현장별 근거와 맥락을 살펴볼 수 있습니다.`
      : source.site.status === "UNMAPPED"
        ? "아직 관측 근거가 없습니다. 등록한 범위와 상태를 확인하고, 구체적인 준비 작업은 현장 준비 목록에서 이어가세요."
        : "연결된 최근 관측 근거가 없습니다. 현장 상태와 다음 관측 준비 상황을 직접 확인할 수 있습니다.",
    observedAt: event ? `관측 ${observedAt(event.occurredAt)}` : `현장 갱신 ${observedAt(source.site.updatedAt)}`,
    href: `/sites/${encodeURIComponent(source.siteId)}`,
    actionLabel: "현장 보기",
    image:
      event && outcome?.state === "AVAILABLE"
        ? { src: outcome.preview.src, alt: `${source.site.name}의 최근 ${humanizeEventType(event.eventType)} 관측 근거` }
        : null,
    imageFallback,
  };
}

export default async function HomePage() {
  const [sitesResult, eventsResult, whoAmIResult, workOrdersResult, operationsResult, briefingsResult, externalDecisionsResult] = await Promise.all([
    settle(listSitesCached()),
    settle(listAllEventsCached()),
    settle(whoAmI()),
    settle(listObservationWorkOrdersForOrganization()),
    settle(listObservationWorkOrderOperations()),
    settle(listLatestSiteBriefings()),
    settle(listExternalPendingDecisions()),
  ]);

  const sites = sitesResult.ok ? sitesResult.value : [];
  const events = eventsResult.ok ? eventsResult.value.events : [];
  const workOrders = workOrdersResult.ok ? workOrdersResult.value : [];
  const operationsByWorkOrderId = new Map(
    (operationsResult.ok ? operationsResult.value : []).map((operations) => [operations.workOrderId, operations]),
  );
  const hasExternalWorkOrders = workOrders.some(
    (workOrder) => workOrder.executionMode === "EXTERNAL_RECONSTRUCTION",
  );
  const operationsUnavailable = hasExternalWorkOrders && !operationsResult.ok;
  // AX-4: 외부 결과 결정 대기를 읽지 못하면 "결정할 것이 없다"로 보이지 않게 따로 알린다.
  const externalDecisionsUnavailable = hasExternalWorkOrders && !externalDecisionsResult.ok;
  const permissions = whoAmIResult.ok ? whoAmIResult.value.permissions : [];
  const canRegisterSite = permissions.includes("SITES_WRITE") && permissions.includes("MISSIONS_ISSUE");

  const allAttentionSources = selectHomeAttentionSources(
    {
      events,
      workOrders,
      sites,
      operationsByWorkOrderId,
      externalDecisions: externalDecisionsResult.ok ? externalDecisionsResult.value.items : [],
    },
    Number.MAX_SAFE_INTEGER,
  );
  // 상단은 큰 이미지 중심의 운영 브리핑을 유지한다. 최초 설정만 남은 UNMAPPED
  // Site fallback은 아래 준비 구역으로 내리되, 같은 현장의 실제 Event·WorkOrder는
  // 운영상 중요한 근거이므로 상단 우선 카드에서 숨기지 않는다.
  const operationalAttentionSources = allAttentionSources.filter(
    (source) => source.kind !== "SITE" || source.site.status !== "UNMAPPED",
  );
  const attentionSources = operationalAttentionSources.slice(0, 3);
  const initialSetupSites = selectHomeInitialSetupSites(sites);
  const recentSiteSources = selectHomeRecentSiteSources({ events, sites });
  const attentionSiteIds = new Set(allAttentionSources.map((source) => source.siteId));
  const operationalAttentionSiteIds = new Set(
    operationalAttentionSources.map((source) => source.siteId),
  );
  const primarySiteIds = new Set(
    attentionSources.length > 0
      ? attentionSources.map((source) => source.siteId)
      : recentSiteSources.map((source) => source.siteId),
  );
  const recentSources = selectHomeRecentUpdates({
    events,
    workOrders,
    sites,
    briefings: briefingsResult.ok ? briefingsResult.value.items : [],
    excludedSiteIds: new Set([...attentionSiteIds, ...primarySiteIds]),
  });

  const previewEventKeys = new Set<string>();
  for (const source of [...attentionSources, ...recentSources]) {
    if (source.kind === "EVENT" || source.kind === "EVENT_SETTLED") {
      previewEventKeys.add(source.event.eventKey);
    }
  }
  for (const source of recentSiteSources) {
    if (source.latestEvent) previewEventKeys.add(source.latestEvent.eventKey);
  }
  const previewEntries = await Promise.all(
    [...previewEventKeys].map(async (eventKey): Promise<[string, PreviewOutcome]> => {
      try {
        const preview = await getHomeEventEvidencePreview(eventKey);
        return [eventKey, preview ? { state: "AVAILABLE", preview } : { state: "NOT_REGISTERED" }];
      } catch {
        return [eventKey, { state: "UNAVAILABLE" }];
      }
    }),
  );
  const previews = new Map(previewEntries);
  const siteById = new Map(sites.map((site) => [site.siteId, site]));
  const attentionItems = attentionSources.map((source) => attentionView(source, siteById, previews));
  const recentSiteItems = recentSiteSources.map((source) => recentSiteView(source, previews));
  const siteActionPermissions = {
    canRegisterSite,
    canEditSite: permissions.includes("SITES_WRITE"),
    canIssueMission: permissions.includes("MISSIONS_ISSUE"),
  };
  const initialSetupItems: HomeSituationItem[] = initialSetupSites.map((site) => {
    const nextAction = resolveSiteOperatorNextAction(site, siteActionPermissions);
    const hasAoi = site.aoi !== null;
    return {
      key: `initial-setup:${site.siteId}`,
      siteId: site.siteId,
      siteName: site.name,
      statusLabel: SITE_STATUS_LABEL[site.status].label,
      statusTone: SITE_STATUS_LABEL[site.status].tone,
      title: hasAoi ? "첫 베이스라인 조사를 계획하세요." : "첫 조사 전에 현장 범위를 설정하세요.",
      detail: hasAoi
        ? "현장 범위가 준비되었습니다. 기준 관측을 계획하면 이후 변화 비교를 시작할 수 있습니다."
        : "아직 기준 관측 범위가 없습니다. 현장 경계를 먼저 저장해야 조사 계획을 만들 수 있습니다.",
      href: nextAction?.href ?? `/sites/${encodeURIComponent(site.siteId)}`,
      actionLabel: nextAction?.label ?? "현장 맥락 보기",
    };
  });
  const recentItems = recentSources.map((source) => recentUpdateView(source, siteById, previews));
  const portfolioComplete = sitesResult.ok && eventsResult.ok && workOrdersResult.ok && !operationsUnavailable && !externalDecisionsUnavailable;

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5 lg:gap-6 lg:p-6">
      <header className="flex items-center justify-between gap-4 border-b border-line pb-3">
        <p className="text-[14px] font-bold tracking-[-0.015em] break-keep">
          전체 {sitesResult.ok ? `${sites.length}곳` : "—"}
          <span aria-hidden="true" className="mx-2 text-line-strong">·</span>
          <span className={portfolioComplete && operationalAttentionSiteIds.size > 0 ? "text-accent" : "text-ink-2"}>
            확인 필요 {portfolioComplete ? `${operationalAttentionSiteIds.size}곳` : "—"}
          </span>
        </p>
        <Link href="/sites" className="tap-target hidden items-center text-[12px] font-semibold text-accent hover:underline sm:inline-flex">
          현장 전체
        </Link>
      </header>

      {!sitesResult.ok && <ErrorState message={sitesResult.message} retryable />}
      {sitesResult.ok && sites.length === 0 && (
        <EmptyState
          title="아직 등록된 현장이 없습니다"
          description={canRegisterSite ? "첫 현장을 등록하면 관측과 변화 기록을 시작할 수 있습니다." : "현장 등록 권한이 있는 계정에서 시작할 수 있습니다."}
          action={canRegisterSite ? { label: "현장 등록", href: "/sites/new" } : undefined}
        />
      )}

      {sites.length > 0 && !portfolioComplete && (
        <p className="rounded-lg border border-line bg-sunk px-4 py-3 text-[12.5px] leading-5 break-keep text-ink-2">
          일부 현장 원장을 불러오지 못해 확인 필요 건수를 추측하지 않습니다. 각 현장 화면에서 다시 확인하세요.
        </p>
      )}

      {operationsUnavailable && (
        <p className="rounded-lg border border-line bg-sunk px-4 py-3 text-[12.5px] leading-5 break-keep text-ink-2">
          {operationsResult.forbidden
            ? "외부 작업의 담당·마감·업무 종료 상태를 볼 권한이 없습니다. 권한이 있는 계정에서 작업 운영을 확인하세요."
            : "외부 작업의 담당·마감·업무 종료 상태를 불러오지 못했습니다. 해당 작업은 확인 필요나 진행 중으로 분류하지 않았습니다."}
        </p>
      )}

      {externalDecisionsUnavailable && (
        <p className="rounded-lg border border-line bg-sunk px-4 py-3 text-[12.5px] leading-5 break-keep text-ink-2">
          {externalDecisionsResult.ok || !externalDecisionsResult.forbidden
            ? "외부 결과의 검토·승인 대기 여부를 불러오지 못했습니다. 확인할 결과가 없다는 뜻이 아닙니다."
            : "외부 결과의 검토·승인 대기 여부를 볼 권한이 없습니다. 권한이 있는 계정에서 확인하세요."}
        </p>
      )}

      {attentionItems.length > 0 ? (
        <HomeAttentionCarousel items={attentionItems} />
      ) : recentSiteItems.length > 0 ? (
        <HomeAttentionCarousel
          items={recentSiteItems}
          title={portfolioComplete ? "새로 확인할 운영 안건이 없습니다." : "최근 현장을 직접 확인하세요."}
          description={
            portfolioComplete
              ? "현재 KSI 원장 기준이며 현장 전체의 정상이나 안전을 보증하지 않습니다. 최근 현장을 선택해 관측 맥락을 살펴보세요."
              : "일부 원장을 불러오지 못해 새 안건 여부를 판단하지 않습니다. 현장을 선택해 상태를 직접 확인하세요."
          }
          regionLabel="최근 현장 캐러셀"
        />
      ) : null}

      {initialSetupItems.length > 0 && (
        <HomeSituationList
          title="초기 설정이 필요한 현장"
          description="첫 기준 관측을 시작하기 위해 현장 범위 또는 베이스라인 조사 계획이 필요합니다."
          items={initialSetupItems}
          emptyMessage="초기 설정이 필요한 현장이 없습니다."
          allHref="/sites"
          allLabel="현장 전체"
        />
      )}

      {sites.length > 0 && <HomeRecentUpdates items={recentItems} />}
    </div>
  );
}
