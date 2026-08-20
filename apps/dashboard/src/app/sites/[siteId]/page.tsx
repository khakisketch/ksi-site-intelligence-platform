import Link from "next/link";
import { notFound } from "next/navigation";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge, StatusBadge } from "@/components/ui/StatusBadge";
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
import { listEvents } from "@/lib/core-api/events";
import { listMissions } from "@/lib/core-api/missions";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getVolumeChanges } from "@/lib/core-api/phase34";
import { formatNetVolumeM3 } from "@/lib/core-api/phase34-labels";
import { getSite } from "@/lib/core-api/sites";
import { siteNextAction } from "@/lib/core-api/site-progress";
import type { SiteDetailView, SiteView, VolumeChangeListView } from "@/lib/core-api/types";
import { formatKoreanDate, formatKoreanDateTime } from "@/lib/datetime";
import {
  findEpoch,
  normalizeSiteTab,
  resolveEpochId,
  toSiteEpochs,
  type SiteEpoch,
} from "@/lib/site-epochs";

import { PROCESSING_JOB_STATUS_LABEL } from "@/app/missions/mission-labels";

import { SiteAoiEditor } from "./SiteAoiEditor";
import { SiteHeader } from "./SiteHeader";
import { SiteTransitionActions } from "./SiteTransitionActions";

const MISSION_LIMIT = 8;
const EVENT_LIMIT = 8;

function nextActionFor(site: SiteView): { title: string; description: string } {
  switch (site.status) {
    case "UNMAPPED":
      return {
        title: "현장 외곽을 확인한 뒤 초기 매핑을 계획하세요",
        description: "기준 지도가 없어 순찰을 시작할 수 없습니다. 외곽(AOI)을 저장하고 베이스라인 임무를 검토하세요.",
      };
    case "REMAP_REQUIRED":
    case "MODEL_STALE":
      return {
        title: "새 조사로 현장 모델을 최신 상태로 만드세요",
        description: "이전 모델로는 현재 현장을 단정할 수 없습니다. 재조사 임무를 계획한 뒤 결과를 검토하세요.",
      };
    case "BASELINE_MAPPING":
    case "MODEL_PROCESSING":
    case "MODEL_VALIDATION":
      return {
        title: "처리·검증 결과를 기다리는 중입니다",
        description: "자동으로 순찰 가능 상태가 되었다고 가정하지 않습니다. 완료된 임무의 CoverageReport와 현장 상태를 함께 확인하세요.",
      };
    case "SUSPENDED":
      return {
        title: "운영 중단 사유와 복귀 조건을 검토하세요",
        description: "중단 상태에서는 새 자율운영을 시작하지 않습니다. 관리자가 상태 이력과 복귀 조건을 확인해야 합니다.",
      };
    default:
      return {
        title: "현장 상태를 확인하고 필요한 조사를 계획하세요",
        description: "발급된 임무와 검토 대기 이벤트를 확인해 다음 행동을 결정하세요.",
      };
  }
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

function sectionOutcome<T>(result: PromiseSettledResult<T>): SectionOutcome<T> {
  if (result.status === "fulfilled") return { kind: "ok", value: result.value };
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
  searchParams: Promise<{ tab?: string; epoch?: string }>;
}) {
  const { siteId } = await params;
  const { tab: rawTab, epoch: rawEpoch } = await searchParams;
  const tab = normalizeSiteTab(rawTab);

  // 데이터 조회는 JSX 생성과 분리한다 — try/catch 안에서 JSX 를 만들면
  // eslint react-hooks/error-boundaries 가 걸린다(렌더는 즉시 실행되지 않아 실제로 못 잡는 에러다).
  let site: SiteDetailView | null = null;
  let errorMessage: string | null = null;
  try {
    site = await getSite(siteId);
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
    canApproveAutonomySite,
    jobsResult,
  ] = await Promise.allSettled([
    listMissions(site.siteId),
    listEvents({ siteId: site.siteId }),
    hasAllPermissions("MISSIONS_ISSUE"),
    hasAllPermissions("SITES_WRITE"),
    hasAllPermissions("SITES_AUTONOMY_APPROVE"),
    // 조사 기록(시점) — 같은 이유로 표면이 없으면 줄 자체가 비고, 그 사실을 머리가 말한다.
    listSiteProcessingJobs(site.siteId),
  ]);
  const missions = sectionOutcome(missionsResult);
  const events = sectionOutcome(
    eventsResult.status === "fulfilled"
      ? { status: "fulfilled", value: eventsResult.value.events }
      : eventsResult,
  );
  const canStartSurvey = canIssueMission.status === "fulfilled" && canIssueMission.value;
  const canTransition = canTransitionSite.status === "fulfilled" && canTransitionSite.value;
  const canApproveAutonomy =
    canApproveAutonomySite.status === "fulfilled" && canApproveAutonomySite.value;

  const epochs = jobsResult.status === "fulfilled" ? toSiteEpochs(jobsResult.value.jobs) : [];
  const selectedEpochId = resolveEpochId(epochs, rawEpoch);
  const selectedEpoch = findEpoch(epochs, selectedEpochId);

  // 물량은 그 탭을 볼 때만 부른다 — 개요를 열 때마다 계산 결과를 두드릴 이유가 없다.
  // 404 는 "아직 계산되지 않음"이지 장애가 아니다(reports 화면과 같은 규약).
  let volume: VolumeChangeListView | null = null;
  if (tab === "volume" && selectedEpoch) {
    volume = await getVolumeChanges(selectedEpoch.missionId).catch(() => null);
  }
  // 최신 리포트 하나만 그린다. 전 구역 합은 **서버가 계산해 실어 보낸 값**을 쓴다
  // (`latestTotalNetM3`) — 화면이 구역을 더하면 합산 규칙이 두 곳에 생긴다.
  const latestVolume = volume?.reports?.[0] ?? null;

  const statusLabel = SITE_STATUS_LABEL[site.status];
  const nextAction = nextActionFor(site);
  const nextStep = siteNextAction(site.status);
  const spatialSummary = spatialModelSummary(site.spatialModel);
  const sitePath = `/sites/${encodeURIComponent(site.siteId)}`;

  return (
    <div className="flex flex-col">
      <SiteHeader
        site={site}
        epochs={epochs}
        selectedEpochId={selectedEpochId}
        tab={tab}
        canStartSurvey={canStartSurvey}
      />

      <div className="flex flex-col gap-4 p-4 sm:p-5">
        {tab === "overview" && (
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-4">
              <section className="rounded-lg border border-line border-l-4 border-l-line-strong bg-surface px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[13px] font-bold break-keep">다음 행동</h2>
                  <StateBadge label={nextStep.label} tone={nextStep.actionable ? "caution" : "neutral"} />
                </div>
                <p className="mt-1 text-[13.5px] font-semibold break-keep">{nextAction.title}</p>
                <p className="mt-1 text-[12.5px] break-keep text-ink-2">{nextAction.description}</p>
              </section>

              <SectionCard title="현장 외곽(AOI)">
                <div className="p-4">
                  {site.aoi ? (
                    <AoiPolygonMap value={site.aoi.vertices} readOnly />
                  ) : site.status === "UNMAPPED" && canTransition ? (
                    // AOI 는 UNMAPPED 상태에서만 설정할 수 있다(서버 게이트, SiteStore.set_aoi
                    // 와 동일 조건) — 편집 권한도 그 게이트를 요구하는 SITES_WRITE 로 같다
                    // (canTransition 이 이미 그 권한을 대변한다, 새 permission 조회 불필요).
                    <SiteAoiEditor siteId={site.siteId} siteFrame={site.siteFrame} />
                  ) : (
                    <EmptyState
                      title="아직 외곽이 등록되지 않았습니다"
                      description={
                        site.status === "UNMAPPED"
                          ? "이 현장의 AOI를 설정하려면 현장 등록 권한이 필요합니다."
                          : "이 현장의 AOI는 UNMAPPED 상태에서만 설정할 수 있습니다 — 매핑이 이미 시작돼 더는 이 화면에서 설정할 수 없습니다."
                      }
                    />
                  )}
                </div>
              </SectionCard>
            </div>

            <div className="flex min-w-0 flex-col gap-4">
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
                      : "이 서버에는 사진 처리(재구성) 표면이 없어 조사 시점을 확인할 수 없습니다."}
                  </p>
                )}
              </SectionCard>

              <SectionCard title="현장 좌표계">
                <dl className="px-4 py-1">
                  <Fact label="좌표계(CRS)" value={site.siteFrame.crs} isToken />
                  <Fact label="수직 기준면" value={site.siteFrame.verticalDatum} isToken />
                  <Fact label="단위" value={site.siteFrame.unit} />
                  <Fact label="변환 버전" value={site.siteFrame.transformVersion} isToken />
                </dl>
              </SectionCard>
            </div>
          </div>
        )}

        {tab === "volume" && (
          <div className="flex flex-col gap-4">
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
                action={{ label: "열기", href: `${sitePath}/progress` }}
              >
                <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                  등록해 둔 작업구역 위에서 설계 기준면과 견줘, 구역마다 얼마나 남았는지를
                  계산합니다.
                </p>
              </SectionCard>
              <SectionCard
                title="현장 보고서"
                action={{ label: "열기", href: `${sitePath}/report` }}
              >
                <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                  이 현장의 변화·물량·진척을 한 번에 내보냅니다.
                </p>
              </SectionCard>
            </div>
          </div>
        )}

        {tab === "design" && (
          <div className="grid gap-4 sm:grid-cols-2">
            {/* 설계 기준면은 현장 자산이지 임무 산출물이 아니다 — 한 번 올려 검증되면
                이후 모든 임무가 같은 기준으로 잔량을 낸다. 그래서 임무가 아니라 현장
                화면에 자리를 둔다. */}
            <SectionCard title="설계 기준면" action={{ label: "관리", href: `${sitePath}/design` }}>
              <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                완성된 지형의 계획고를 올려두면, 이후 촬영한 현재 지형과 견줘 구역별로 얼마나
                더 깎고 더 쌓아야 하는지 계산할 수 있습니다.
              </p>
            </SectionCard>

            {/* 작업구역도 설계 기준면과 같은 이유로 현장 화면에 산다 — 비교할 때마다
                새로 그리지 않고 한 번 등록해두는 자산이라서다(M4-C). */}
            <SectionCard title="작업구역" action={{ label: "관리", href: `${sitePath}/work-areas` }}>
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
              action={{ label: "보기", href: `${sitePath}/changes` }}
            >
              <p className="px-4 py-3 text-[12.5px] break-keep text-ink-2">
                설계 대비 잔량이 크게 달라진 곳을 자동으로 찾아 지도에 보여줍니다. 영역을 골라
                다음 비행의 촬영 범위로 바로 넘길 수 있습니다.
              </p>
            </SectionCard>
          </div>
        )}

        {tab === "records" && (
          <div className="grid items-start gap-4 xl:grid-cols-2">
            <SectionCard
              title="이 현장의 임무"
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

            <SectionCard
              title="이 현장의 이벤트"
              action={{ label: "전체보기", href: `/events?siteId=${encodeURIComponent(site.siteId)}` }}
            >
              <div className="px-4 py-2">
                {events.kind !== "ok" ? (
                  <SectionFallback what="이벤트" outcome={events.kind} />
                ) : events.value.length === 0 ? (
                  <p className="py-2 text-[13px] break-keep text-ink-muted">아직 없습니다.</p>
                ) : (
                  <ul className="flex flex-col divide-y divide-line">
                    {events.value.slice(0, EVENT_LIMIT).map((event) => {
                      const eventStatusLabel = EVENT_STATUS_LABEL[event.status];
                      return (
                        <li key={event.eventKey}>
                          <Link
                            href={`/events/${encodeURIComponent(event.eventKey)}`}
                            className="tap-target -mx-2 flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-2 text-[13.5px] hover:bg-sunk"
                          >
                            {/* 배지와 날짜만 있으면 "무슨 일이 있었나"가 목록에서 빠진다 —
                                종류를 함께 싣는다(라벨 없는 종류는 원문 그대로, labels.ts). */}
                            <span className="min-w-0 flex-1 truncate break-keep font-medium">
                              {humanizeEventType(event.eventType)}
                            </span>
                            <StatusBadge label={eventStatusLabel.label} tone={eventStatusLabel.tone} />
                            <span className="num text-[12px] whitespace-nowrap text-ink-muted">
                              {formatKoreanDate(event.occurredAt)}
                            </span>
                          </Link>
                        </li>
                      );
                    })}
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
        )}
      </div>
    </div>
  );
}
