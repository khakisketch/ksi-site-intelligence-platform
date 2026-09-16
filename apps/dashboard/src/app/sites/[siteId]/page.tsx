import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { CivilReadinessCard } from "@/components/site/CivilReadinessCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge, StatusBadge } from "@/components/ui/StatusBadge";
import { ExternalSiteResultSummary } from "@/components/external-results/ExternalSiteResultSummary";
import { ZoneVolumeBars } from "@/components/site/ZoneVolumeBars";
import { CoreApiError } from "@/lib/core-api/client";
import { listSiteProcessingJobs } from "@/lib/core-api/comparison";
import {
  EVENT_STATUS_LABEL,
  MISSION_TYPE_LABEL,
  humanizeApiError,
  humanizeEventType,
  SITE_STATUS_LABEL,
  spatialModelSummary,
} from "@/lib/core-api/labels";
import { listAllEvents } from "@/lib/core-api/events";
import { listMissions } from "@/lib/core-api/missions";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getVolumeChanges } from "@/lib/core-api/phase34";
import { formatNetVolumeM3 } from "@/lib/core-api/phase34-labels";
import { getCivilReadiness } from "@/lib/core-api/civil-readiness";
import { getSite } from "@/lib/core-api/sites";
import { getLatestSiteBriefing, getSiteWorkspace } from "@/lib/core-api/site-workspace";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { copilotCitationHref } from "@/lib/copilot-citation";
import { siteDetailDocumentTitle } from "@/lib/site-detail-title";
import { siteNextAction } from "@/lib/core-api/site-progress";
import type {
  SiteBriefing,
  SiteDetailView,
  SiteView,
  SiteWorkspaceView,
  VolumeChangeListView,
  WorkArea,
} from "@/lib/core-api/types";
import { formatKoreanDate, formatKoreanDateTime } from "@/lib/datetime";
import {
  findEpoch,
  normalizeSiteTab,
  resolveEpochId,
  toSiteEpochs,
  type SiteEpoch,
} from "@/lib/site-epochs";

import { PROCESSING_JOB_STATUS_LABEL } from "@/app/missions/mission-labels";
import { presentWorkOrder } from "@/app/field/work-order-stage";

import { SiteAoiEditor } from "./SiteAoiEditor";
import { SiteHeader } from "./SiteHeader";
import { SiteTransitionActions } from "./SiteTransitionActions";

const MISSION_LIMIT = 8;
const getSiteForDetail = cache(getSite);

/**
 * App Router metadata는 렌더와 같은 서버 경로에서 현장명을 읽는다. React cache로
 * 본문 조회와 합쳐, 최신 원장을 위한 no-store 정책을 약화하지 않고 같은 요청의
 * 중복 Core 왕복만 피한다.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ siteId: string }>;
}): Promise<Metadata> {
  const { siteId } = await params;
  try {
    const site = await getSiteForDetail(siteId);
    return { title: siteDetailDocumentTitle(site.name) };
  } catch {
    // 404/권한 오류의 대상 이름을 title에 남기지 않는다. 본문은 기존의 notFound 또는
    // ErrorState가 실제 상태를 정직하게 표현한다.
    return { title: "현장 상세 · KSI" };
  }
}

function SiteBriefingCard({
  site,
  outcome,
}: {
  site: SiteView;
  outcome: OptionalSectionOutcome<SiteBriefing>;
}) {
  const aiHref = `/sites/${encodeURIComponent(site.siteId)}/ai`;
  if (outcome.kind === "error" || outcome.kind === "forbidden") {
    return (
      <SectionCard title="KSI 현장 브리핑" meta="확인 불가">
        <div className="px-4 py-4">
          <SectionFallback what="저장된 현장 브리핑" outcome={outcome.kind} />
        </div>
      </SectionCard>
    );
  }
  if (outcome.kind === "empty") {
    return (
      <SectionCard
        title="KSI 현장 브리핑"
        meta={site.aiEgressAllowed ? "분석 결과 대기" : "AI 사용 전"}
        action={site.aiEgressAllowed ? { label: "KSI AI 열기", href: aiHref } : undefined}
      >
        <EmptyState
          compact
          title="아직 저장된 브리핑이 없습니다"
          description={
            site.aiEgressAllowed
              ? "외부 산출물의 상대 물량 결과가 기록되면 자동으로 만들어지고, 검증된 현장 결과가 준비되면 KSI AI가 근거와 함께 변화·중요도·결정 질문을 만듭니다."
              : "외부 산출물의 상대 물량 결과가 기록되면 근거와 함께 자동으로 만들어집니다. 이 현장은 외부 AI 데이터 활용에 동의하지 않았으므로 AI 질문은 열지 않습니다."
          }
        />
      </SectionCard>
    );
  }
  const briefing = outcome.value;
  return (
    <SectionCard
      title="KSI 현장 브리핑"
      meta={formatKoreanDateTime(briefing.generatedAt, { dateStyle: "medium", timeStyle: "short" })}
      action={site.aiEgressAllowed ? { label: "KSI AI에서 질문", href: aiHref } : undefined}
    >
      <div className="grid gap-px bg-line lg:grid-cols-3">
        <div className="bg-surface px-4 py-4">
          <p className="text-[11.5px] font-bold text-ink-muted">무엇이 달라졌나</p>
          <p className="mt-2 text-[14px] leading-6 break-keep">{briefing.whatChanged}</p>
        </div>
        <div className="bg-surface px-4 py-4">
          <p className="text-[11.5px] font-bold text-ink-muted">왜 중요한가</p>
          <p className="mt-2 text-[14px] leading-6 break-keep">{briefing.whyItMatters}</p>
        </div>
        <div className="bg-surface px-4 py-4">
          <p className="text-[11.5px] font-bold text-ink-muted">지금 검토할 결정</p>
          <p className="mt-2 text-[14px] font-semibold leading-6 break-keep">
            {briefing.decisionPrompt}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-4 py-2.5 text-[11.5px] text-ink-2">
        <StateBadge
          label={briefing.status === "READY" ? "근거 검증 완료" : "근거 부족"}
          tone={briefing.status === "READY" ? "positive" : "caution"}
        />
        <span>근거 {briefing.citations.length}건</span>
        <span>불확실성 · {briefing.uncertainty}</span>
      </div>
      {briefing.citations.length > 0 && (
        <div className="border-t border-line px-4 py-3">
          <p className="text-[11.5px] font-bold text-ink-muted">판단 근거</p>
          <ul className="mt-1.5 flex flex-col divide-y divide-line">
            {briefing.citations.map((citation) => {
              const href = copilotCitationHref(citation);
              return (
                <li key={citation.citationId} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 py-2 text-[12.5px]">
                  {href ? (
                    <Link href={href} className="tap-target inline-flex font-semibold text-accent-text underline">
                      {citation.label}
                    </Link>
                  ) : (
                    <span className="font-semibold">{citation.label}</span>
                  )}
                  {citation.capturedTo && (
                    <span className="num text-[11.5px] text-ink-muted">
                      {formatKoreanDate(citation.capturedTo)} 관측
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {briefing.missingData.length > 0 && (
        <p className="border-t border-line bg-sunk px-4 py-2.5 text-[12px] break-keep text-ink-2">
          추가 확인이 필요한 데이터 {briefing.missingData.length}건이 있어, 표시된 내용만 근거로 판단해야 합니다.
        </p>
      )}
    </SectionCard>
  );
}

/**
 * 섹션 조회 결과 — **권한 부재와 장애를 구분한다.**
 *
 * 둘을 "불러오지 못했습니다" 하나로 뭉개면, 권한이 없어서 안 보이는 것뿐인 운영자가
 * 시스템 장애로 오해해 신고하거나 새로고침을 반복한다(2026-08-04 렌더 확인에서 당시
 * 이벤트 읽기 권한이 없던 역할 계정으로 실제 재현 — ADR-KSI-015 로 역할이 3개로
 * 합쳐지며 이제 전 역할이 EVENTS_READ 를 갖는다. 패턴 자체는 다른 권한 조합에도
 * 여전히 유효하다).
 */
type SectionOutcome<T> = { kind: "ok"; value: T } | { kind: "forbidden" } | { kind: "error" };
type OptionalSectionOutcome<T> =
  | { kind: "ok"; value: T }
  | { kind: "empty" }
  | { kind: "forbidden" }
  | { kind: "error" };

function sectionOutcome<T>(result: PromiseSettledResult<T>): SectionOutcome<T> {
  if (result.status === "fulfilled") return { kind: "ok", value: result.value };
  if (result.reason instanceof CoreApiError && result.reason.status === 403) {
    return { kind: "forbidden" };
  }
  return { kind: "error" };
}

function optionalSectionOutcome<T>(result: PromiseSettledResult<T>): OptionalSectionOutcome<T> {
  if (result.status === "fulfilled") return { kind: "ok", value: result.value };
  if (result.reason instanceof CoreApiError && result.reason.status === 404) {
    return { kind: "empty" };
  }
  if (result.reason instanceof CoreApiError && result.reason.status === 403) {
    return { kind: "forbidden" };
  }
  return { kind: "error" };
}

function SectionFallback({ what, outcome }: { what: string; outcome: "forbidden" | "error" }) {
  return (
    <p className="text-[13px] break-keep text-ink-muted">
      {outcome === "forbidden"
        ? `이 계정은 ${what}를 볼 권한이 없습니다.`
        : `${what} 정보를 불러오지 못했습니다.`}
    </p>
  );
}

function analysisStatusLabel(status: string): string {
  if (status === "UNAVAILABLE") return "아직 분석 결과 없음";
  return PROCESSING_JOB_STATUS_LABEL[status]?.label ?? "상태 확인 필요";
}

/** 시안 `.facts`/`.fact` — 고정폭 라벨열 + 행마다 하단 보더. 식별자 값은 break-token. */
function Fact({ label, value, isToken = false }: { label: string; value: string; isToken?: boolean }) {
  return (
    <div className="grid grid-cols-[92px_minmax(0,1fr)] items-baseline gap-2.5 border-b border-line py-2 last:border-b-0">
      <dt className="text-[12px] break-keep text-ink-muted">{label}</dt>
      <dd className={`min-w-0 text-[13px] ${isToken ? "num break-token" : "break-keep"}`}>{value}</dd>
    </div>
  );
}

function SectionCard({
  title,
  meta,
  action,
  children,
}: {
  title: string;
  meta?: string;
  action?: { label: string; href: string };
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-line px-4 py-2.5">
        <h2 className="text-[13.5px] font-bold tracking-tight break-keep">{title}</h2>
        {meta && <span className="text-[11.5px] break-keep text-ink-muted">{meta}</span>}
        {action && (
          <Link
            href={action.href}
            className="tap-target ml-auto flex items-center text-[12px] font-semibold break-keep text-accent-text hover:underline"
          >
            {action.label}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

/** 고른 시점이 실제로 무엇을 만들었는지 — 산출물 종류를 그대로 옮긴다. */
function EpochSummary({ epoch }: { epoch: SiteEpoch }) {
  const status = PROCESSING_JOB_STATUS_LABEL[epoch.status] ?? {
    label: epoch.status,
    tone: "neutral" as const,
  };
  return (
    <div className="flex flex-col gap-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge label={status.label} tone={status.tone} />
        <span className="num text-[12px] text-ink-2">
          {formatKoreanDateTime(epoch.issuedAt, { dateStyle: "medium", timeStyle: "short" })} 처리 요청
        </span>
      </div>
      <p className="text-[12px] break-keep text-ink-2">
        {epoch.artifactKinds.length === 0
          ? "이 시점에서 등록된 산출물이 아직 없습니다."
          : `산출물 ${epoch.artifactKinds.length}종 · ${epoch.artifactKinds.join(" · ")}`}
      </p>
      <Link
        href={`/missions/${encodeURIComponent(epoch.missionId)}`}
        className="tap-target inline-flex w-fit items-center text-[12px] font-semibold break-keep text-accent-text hover:underline"
      >
        이 시점을 만든 임무 열기
      </Link>
    </div>
  );
}

export default async function SiteDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ section?: string; tab?: string; epoch?: string }>;
}) {
  const { siteId } = await params;
  const { section: rawSection, tab: rawTab, epoch: rawEpoch } = await searchParams;
  const tab = normalizeSiteTab(rawSection ?? rawTab);

  // 데이터 조회는 JSX 생성과 분리한다 — try/catch 안에서 JSX 를 만들면
  // eslint react-hooks/error-boundaries 가 걸린다(렌더는 즉시 실행되지 않아 실제로 못 잡는 에러다).
  let site: SiteDetailView | null = null;
  let errorMessage: string | null = null;
  try {
    site = await getSiteForDetail(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      notFound();
    }
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  if (errorMessage !== null || site === null) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState message={errorMessage ?? "요청을 처리하지 못했습니다."} retryable />
      </div>
    );
  }

  // 임무·이벤트·권한 조회는 현장 조회와 독립 — 하나가 실패해도 다른 섹션은 계속 보여준다.
  const [
    missionsResult,
    eventsResult,
    canIssueMission,
    canTransitionSite,
    canCreateWorkOrder,
    canApproveAutonomySite,
    jobsResult,
    workspaceResult,
    briefingResult,
    workOrdersResult,
    civilReadinessResult,
    workAreasResult,
  ] = await Promise.allSettled([
    listMissions(site.siteId),
    listAllEvents({ siteId: site.siteId }),
    hasAllPermissions("MISSIONS_ISSUE"),
    hasAllPermissions("SITES_WRITE"),
    hasAllPermissions("WORK_ORDERS_WRITE"),
    hasAllPermissions("SITES_AUTONOMY_APPROVE"),
    // 조사 기록(시점) — 같은 이유로 표면이 없으면 줄 자체가 비고, 그 사실을 머리가 말한다.
    listSiteProcessingJobs(site.siteId),
    getSiteWorkspace(site.siteId),
    getLatestSiteBriefing(site.siteId),
    listObservationWorkOrders(site.siteId),
    getCivilReadiness(site.siteId),
    listWorkAreas(site.siteId),
  ]);
  const missions = sectionOutcome(missionsResult);
  const events = sectionOutcome(
    eventsResult.status === "fulfilled"
      ? { status: "fulfilled", value: eventsResult.value.events }
      : eventsResult,
  );
  const canStartSurvey = canIssueMission.status === "fulfilled" && canIssueMission.value;
  const canTransition = canTransitionSite.status === "fulfilled" && canTransitionSite.value;
  const canCreateObservation = canCreateWorkOrder.status === "fulfilled" && canCreateWorkOrder.value;
  const canApproveAutonomy =
    canApproveAutonomySite.status === "fulfilled" && canApproveAutonomySite.value;
  const workspaceOutcome = sectionOutcome(workspaceResult);
  const workspace: SiteWorkspaceView | null =
    workspaceOutcome.kind === "ok" ? workspaceOutcome.value : null;
  const briefingOutcome = optionalSectionOutcome(briefingResult);
  const workOrders = sectionOutcome(workOrdersResult);
  const civilReadinessOutcome = sectionOutcome(civilReadinessResult);
  const workAreas: readonly WorkArea[] =
    workAreasResult.status === "fulfilled" ? workAreasResult.value.workAreas : [];
  const workAreaNameById = new Map(workAreas.map((area) => [area.workAreaId, area.name]));
  const externalResultSummary = workspaceOutcome.kind === "ok" ? (
    <ExternalSiteResultSummary
      externalResult={workspaceOutcome.value.externalResult}
      workAreaName={workspaceOutcome.value.externalResult.result
        ? workAreaNameById.get(workspaceOutcome.value.externalResult.result.workAreaId) ?? null
        : null}
    />
  ) : (
    <SectionFallback what="외부 관측 결과" outcome={workspaceOutcome.kind} />
  );

  const epochs = jobsResult.status === "fulfilled" ? toSiteEpochs(jobsResult.value.jobs) : [];
  const selectedEpochId = resolveEpochId(epochs, rawEpoch);
  const selectedEpoch = findEpoch(epochs, selectedEpochId);

  // 물량은 그 탭을 볼 때만 부른다 — 개요를 열 때마다 계산 결과를 두드릴 이유가 없다.
  // 404 는 "아직 계산되지 않음"이지 장애가 아니다(reports 화면과 같은 규약).
  let volume: VolumeChangeListView | null = null;
  if (tab === "data" && selectedEpoch) {
    volume = await getVolumeChanges(selectedEpoch.missionId).catch(() => null);
  }
  // 최신 리포트 하나만 그린다. 전 구역 합은 **서버가 계산해 실어 보낸 값**을 쓴다
  // (`latestTotalNetM3`) — 화면이 구역을 더하면 합산 규칙이 두 곳에 생긴다.
  const latestVolume = volume?.reports?.[0] ?? null;

  const statusLabel = SITE_STATUS_LABEL[site.status];
  const nextStep = siteNextAction(site.status);
  const spatialSummary = spatialModelSummary(site.spatialModel);
  const sitePath = `/sites/${encodeURIComponent(site.siteId)}`;
  const externalObservationHistoryLink = (
    <Link
      href={`${sitePath}/observations`}
      className="tap-target inline-flex items-center text-[12px] font-semibold text-accent-text hover:underline"
    >
      외부 관측 결과 이력
    </Link>
  );

  return (
    <div className="flex flex-col">
      <SiteHeader
        site={site}
        selectedEpochId={selectedEpochId}
        tab={tab}
        latestObservationAt={workspace?.latestObservationAt ?? null}
        latestObservationKnown={workspaceOutcome.kind === "ok"}
        canStartSurvey={canStartSurvey}
        canEditAoi={canTransition}
      />

      <div className="flex flex-col gap-4 p-4 sm:p-5">
        {tab === "briefing" && (
          <div className="flex flex-col gap-4">
            <section className="rounded-lg border border-line border-l-4 border-l-line-strong bg-surface px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[13px] font-bold break-keep">다음 행동</h2>
                {workspace !== null && (
                  <StateBadge label={nextStep.label} tone={nextStep.actionable ? "caution" : "neutral"} />
                )}
              </div>
              {workspace !== null ? (
                <>
                  <p className="mt-1 text-[14px] font-semibold break-keep">
                    {workspace.nextAction.label}
                  </p>
                  <p className="mt-1 text-[12.5px] break-keep text-ink-2">
                    {workspace.nextAction.reason}
                  </p>
                </>
              ) : (
                <p className="mt-1 text-[12.5px] break-keep text-ink-2">
                  작업과 확인 항목을 불러오지 못해 지금 할 일을 정할 수 없습니다. 잠시 후 다시 확인하세요.
                </p>
              )}
              {workspace !== null && workspace.nextAction.href && (
                <Link
                  href={workspace.nextAction.href}
                  className="tap-target mt-2 inline-flex items-center text-[12px] font-semibold text-accent-text hover:underline"
                >
                  {workspace.nextAction.label}
                </Link>
              )}
            </section>
            <SiteBriefingCard site={site} outcome={briefingOutcome} />
            {externalResultSummary}
            {externalObservationHistoryLink}
          </div>
        )}

        {tab === "data" && (
          <div className="flex flex-col gap-4">
            <div className="grid items-start gap-4 lg:grid-cols-3">
              {/* 단일 site detail 응답에 함께 온 파생 판정 — 화면이 두 요청을 합성하지 않는다. */}
              <SectionCard title="공간모델">
                <div className="flex flex-col gap-1.5 px-4 py-3">
                  <StatusBadge label={spatialSummary.label} tone={spatialSummary.tone} />
                  <p className="text-[12.5px] break-keep text-ink-2">{spatialSummary.detail}</p>
                </div>
              </SectionCard>

              <SectionCard title="고른 조사 시점">
                {selectedEpoch ? (
                  <EpochSummary epoch={selectedEpoch} />
                ) : (
                  <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                    {jobsResult.status === "fulfilled"
                      ? "아직 처리된 조사 시점이 없습니다."
                      : "사진 처리 원장이 연결되지 않아 조사 시점을 확인할 수 없습니다."}
                  </p>
                )}
              </SectionCard>

              <SectionCard title="공간 기준">
                <details className="px-4 py-2">
                  <summary className="tap-target cursor-pointer text-[12.5px] font-semibold">
                    좌표계와 변환 정보
                  </summary>
                  <dl className="border-t border-line pt-1">
                    <Fact label="좌표계(CRS)" value={site.siteFrame.crs} isToken />
                    <Fact label="수직 기준면" value={site.siteFrame.verticalDatum} isToken />
                    <Fact label="단위" value={site.siteFrame.unit} />
                    <Fact label="변환 버전" value={site.siteFrame.transformVersion} isToken />
                  </dl>
                </details>
              </SectionCard>
            </div>

            <CivilReadinessCard
              readiness={
                civilReadinessOutcome.kind === "ok" ? civilReadinessOutcome.value : null
              }
            />

            {externalResultSummary}
            {externalObservationHistoryLink}

            <SectionCard
              title="구역별 순변화"
              meta={
                selectedEpoch
                  ? volume && volume.latestTotalNetM3 !== null
                    ? `${formatKoreanDate(selectedEpoch.issuedAt)} 시점 · 전 구역 합 ${formatNetVolumeM3(volume.latestTotalNetM3)}`
                    : `${formatKoreanDate(selectedEpoch.issuedAt)} 시점 기준`
                  : "고른 시점이 없습니다"
              }
              action={{ label: "변화 영역 보기", href: `${sitePath}/changes` }}
            >
              {!selectedEpoch ? (
                <p className="px-4 py-4 text-[12.5px] break-keep text-ink-2">
                  조사 시점이 없어 물량을 계산할 수 없습니다. 매핑 비행과 사진 처리가 끝나면 이
                  자리에 구역별 변화가 나타납니다.
                </p>
              ) : latestVolume === null ? (
                <p className="px-4 py-4 text-[12.5px] break-keep text-ink-2">
                  이 시점에는 아직 계산된 물량이 없습니다. 물량은 두 시점을 비교해야 나오므로,
                  이전 시점과의 비교를 임무 화면에서 요청하세요.
                </p>
              ) : (
                <ZoneVolumeBars
                  zones={latestVolume.report.zones}
                  computedNote={`문턱 ${latestVolume.report.zones[0]?.thresholdM ?? "—"} m · ${formatKoreanDateTime(
                    latestVolume.recordedAt,
                    { dateStyle: "medium", timeStyle: "short" },
                  )} 기록`}
                />
              )}
            </SectionCard>

            <div className="grid gap-4 sm:grid-cols-2">
              <SectionCard
                title="계획 대비 진척"
                action={{ label: "진척 보기", href: `${sitePath}/progress` }}
              >
                <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                  등록해 둔 작업구역 위에서 설계 기준면과 견줘, 구역마다 얼마나 남았는지를
                  계산합니다.
                </p>
              </SectionCard>
              <SectionCard
                title="현장 보고서"
                action={{ label: "현장 보고서 보기", href: `${sitePath}/report` }}
              >
                <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                  이 현장의 변화·물량·진척을 한 번에 내보냅니다.
                </p>
              </SectionCard>
            </div>
          </div>
        )}

        {tab === "data" && (
          <div className="grid gap-4 sm:grid-cols-2">
            {/* 설계 기준면은 현장 자산이지 임무 산출물이 아니다 — 한 번 올려 검증되면
                이후 모든 임무가 같은 기준으로 잔량을 낸다. 그래서 임무가 아니라 현장
                화면에 자리를 둔다. */}
            <SectionCard title="설계 기준면" action={{ label: "설계 기준면 관리", href: `${sitePath}/design` }}>
              <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                완성된 지형의 계획고를 올려두면, 이후 촬영한 현재 지형과 견줘 구역별로 얼마나
                더 깎고 더 쌓아야 하는지 계산할 수 있습니다.
              </p>
            </SectionCard>

            {/* 작업구역도 설계 기준면과 같은 이유로 현장 화면에 산다 — 비교할 때마다
                새로 그리지 않고 한 번 등록해두는 자산이라서다(M4-C). */}
            <SectionCard title="작업구역" action={{ label: "작업구역 관리", href: `${sitePath}/work-areas` }}>
              <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                이름을 붙여 등록해두면 이후 잔량·진척을 낼 때마다 지도에 새로 그리는 대신 이
                구역을 고르기만 하면 됩니다 — 지난번과 이번이 같은 범위라야 계획 대비 진척을
                계산할 수 있습니다.
              </p>
            </SectionCard>

            {/* 변화 영역도 설계 대비 잔량 위에서 계산되지만(M4-E), 목적이 다르다 —
                "지금 몇 %인가"가 아니라 "어디를 다시 봐야 하나·다음엔 어디를 찍나"다. */}
            <SectionCard
              title="변화 영역 · 재확인 필요"
              action={{ label: "변화 영역 보기", href: `${sitePath}/changes` }}
            >
              <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                설계 대비 잔량이 크게 달라진 곳을 자동으로 찾아 지도에 보여줍니다. 영역을 골라
                다음 비행의 촬영 범위로 바로 넘길 수 있습니다.
              </p>
            </SectionCard>
          </div>
        )}

        {tab === "review-items" && (
          <SectionCard
            title="이 현장의 확인 항목"
            meta={events.kind === "ok" ? `${events.value.length}건` : undefined}
            action={{ label: "전체 화면으로 보기", href: `/events?siteId=${encodeURIComponent(site.siteId)}` }}
          >
            <div className="px-4 py-2">
              {events.kind !== "ok" ? (
                <SectionFallback what="확인 항목" outcome={events.kind} />
              ) : events.value.length === 0 ? (
                <EmptyState
                  title="현재 확인할 항목이 없습니다"
                  description="새 관측이 들어오면 근거와 사람의 판단 상태가 이곳에 표시됩니다."
                />
              ) : (
                <ul className="flex flex-col divide-y divide-line">
                  {events.value.map((event) => {
                    const eventStatusLabel = EVENT_STATUS_LABEL[event.status];
                    return (
                      <li key={event.eventKey}>
                        <Link
                          href={`/events/${encodeURIComponent(event.eventKey)}`}
                          className="tap-target -mx-2 grid gap-1 rounded-md px-2 py-3 hover:bg-sunk sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                        >
                          <span>
                            <span className="block text-[14px] font-semibold break-keep">
                              {humanizeEventType(event.eventType)}
                            </span>
                            <span className="mt-0.5 block text-[12px] text-ink-muted">
                              {formatKoreanDateTime(event.occurredAt, { dateStyle: "medium", timeStyle: "short" })}
                            </span>
                          </span>
                          <StatusBadge label={eventStatusLabel.label} tone={eventStatusLabel.tone} />
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </SectionCard>
        )}

        {tab === "work" && (
          <div className="flex flex-col gap-4">
            <div id="site-aoi" className="scroll-mt-20">
              <SectionCard title="현장 범위">
                <div className="p-4">
                  {site.aoi ? (
                    <AoiPolygonMap value={site.aoi.vertices} readOnly />
                  ) : site.status === "UNMAPPED" && canTransition ? (
                    <>
                      <div className="rounded-lg border border-line bg-sunk px-4 py-3 lg:hidden">
                        <p className="text-[13px] font-semibold break-keep">현장 범위가 아직 설정되지 않았습니다</p>
                        <p className="mt-1 text-[12.5px] break-keep text-ink-2">
                          지도에서 조사할 공사 구역을 지정하는 작업은 노트북에서 시작할 수 있습니다.
                        </p>
                      </div>
                      <div className="hidden lg:block">
                        {/* AOI 는 UNMAPPED 상태에서만 설정할 수 있다(서버 게이트, SiteStore.set_aoi
                            와 동일 조건). 모바일에서는 편집기를 숨기고 작업 맥락만 유지한다. */}
                        <SiteAoiEditor siteId={site.siteId} siteFrame={site.siteFrame} />
                      </div>
                    </>
                  ) : (
                    <EmptyState
                      compact
                      title="아직 현장 범위가 등록되지 않았습니다"
                      description={
                        site.status === "UNMAPPED"
                          ? "현장 범위를 설정하려면 현장 등록 권한이 필요합니다."
                          : "현장 매핑이 시작된 뒤에는 이 화면에서 현장 범위를 바꿀 수 없습니다."
                      }
                    />
                  )}
                </div>
              </SectionCard>
            </div>

            <div className="grid items-start gap-4 xl:grid-cols-2">
            <SectionCard title="현장 작업" meta={workOrders.kind === "ok" ? `${workOrders.value.length}건` : undefined}>
              <div className="px-4 py-2">
                {canCreateObservation && <Link href={`${sitePath}/observations/new`} className="btn mb-2 hidden w-fit lg:inline-flex">새 관측 시작</Link>}
                {workOrders.kind !== "ok" ? (
                  <SectionFallback what="작업" outcome={workOrders.kind} />
                ) : workOrders.value.length === 0 ? (
                  <p className="py-2 text-[13px] break-keep text-ink-muted">아직 계획된 작업이 없습니다.</p>
                ) : (
                  <ul className="flex flex-col divide-y divide-line">
                    {workOrders.value.map((workOrder) => {
                      const presentation = presentWorkOrder(workOrder.status, workOrder.executionMode);
                      return (
                        <li key={workOrder.workOrderId}>
                          <Link
                            href={`/field/work-orders/${encodeURIComponent(workOrder.workOrderId)}`}
                            className="tap-target -mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-3 hover:bg-sunk"
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-[14px] font-semibold">{workOrder.name}</span>
                              <span className="mt-0.5 block text-[12px] text-ink-muted">
                                {formatKoreanDateTime(workOrder.updatedAt, { dateStyle: "medium", timeStyle: "short" })} 업데이트
                              </span>
                            </span>
                            <StateBadge label={presentation.label} tone={presentation.tone} />
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </SectionCard>

            <SectionCard
              title="비행 임무 이력"
              action={{ label: "전체보기", href: `/missions?siteId=${encodeURIComponent(site.siteId)}` }}
            >
              <div className="px-4 py-2">
                {missions.kind !== "ok" ? (
                  <SectionFallback what="임무" outcome={missions.kind} />
                ) : missions.value.length === 0 ? (
                  <p className="py-2 text-[13px] break-keep text-ink-muted">아직 없습니다.</p>
                ) : (
                  <ul className="flex flex-col divide-y divide-line">
                    {missions.value.slice(0, MISSION_LIMIT).map((mission) => (
                      <li key={mission.missionId}>
                        <Link
                          href={`/missions/${encodeURIComponent(mission.missionId)}`}
                          className="tap-target -mx-2 flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-2 text-[13.5px] hover:bg-sunk"
                        >
                          <span className="break-keep font-medium">
                            {MISSION_TYPE_LABEL[mission.missionType]}
                          </span>
                          <span className="num text-[12px] whitespace-nowrap text-ink-muted">
                            {formatKoreanDate(mission.issuedAt)}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </SectionCard>

            <SectionCard title="현장 상태 · 관리" meta={statusLabel.label}>
              <div className="px-4 py-3">
                {canTransition ? (
                  <details>
                    <summary className="tap-target flex cursor-pointer items-center text-[13px] font-semibold break-keep">
                      관리자 상태 전이
                    </summary>
                    <p className="mt-2 text-[12px] break-keep text-ink-muted">
                      현장 상태 전이는 운용 가능 여부를 바꿉니다. 현재 상태와 전이 사유를 확인한 뒤
                      진행하세요.
                    </p>
                    <div className="mt-3">
                      <SiteTransitionActions
                        siteId={site.siteId}
                        status={site.status}
                        resumeTarget={site.resumeTarget}
                        canApproveAutonomy={canApproveAutonomy}
                      />
                    </div>
                  </details>
                ) : (
                  <p className="text-[12px] break-keep text-ink-muted">
                    현장 상태를 전이하려면 현장 등록 권한이 필요합니다.
                  </p>
                )}
              </div>
            </SectionCard>

            <SectionCard title="등록 정보">
              <dl className="px-4 py-1">
                <Fact label="등록" value={formatKoreanDate(site.registeredAt)} isToken />
                <Fact label="최근 갱신" value={formatKoreanDate(site.updatedAt)} isToken />
                <Fact label="좌표계(CRS)" value={site.siteFrame.crs} isToken />
                <Fact label="변환 버전" value={site.siteFrame.transformVersion} isToken />
              </dl>
            </SectionCard>
            </div>
          </div>
        )}

        {tab === "reports" && (
          <div className="flex flex-col gap-4">
            {externalResultSummary}
            {externalObservationHistoryLink}
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
            <SectionCard
              title="현장 보고서"
              action={{ label: "보고서 열기", href: `${sitePath}/report` }}
            >
              <div className="px-4 py-4">
                <p className="text-[15px] font-semibold break-keep">
                  변화·공정·상대 물량·확인 항목·결정·다음 관측을 한 문서에서 봅니다.
                </p>
                <p className="mt-2 text-[12.5px] leading-6 break-keep text-ink-2">
                  화면과 내보내기는 같은 서버 값을 사용합니다. 근거가 없는 값은 보고서에서도 채우지 않습니다.
                </p>
              </div>
            </SectionCard>
            <SectionCard title="최신 근거 상태">
              <dl className="px-4 py-1">
                <Fact
                  label="관측 시점"
                  value={
                    workspace === null
                      ? "알 수 없음"
                      : workspace.latestObservationAt
                        ? formatKoreanDate(workspace.latestObservationAt)
                        : "아직 없음"
                  }
                />
                <Fact
                  label="확인 항목"
                  value={workspace !== null ? `${workspace.reviewItemCount}건` : "알 수 없음"}
                />
                <Fact
                  label="분석 상태"
                  value={workspace !== null ? analysisStatusLabel(workspace.latestAnalysis.status) : "알 수 없음"}
                />
              </dl>
            </SectionCard>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
