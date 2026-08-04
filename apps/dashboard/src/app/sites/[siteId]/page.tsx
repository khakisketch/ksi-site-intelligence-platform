import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge, StatusBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import {
  EVENT_STATUS_LABEL,
  MISSION_TYPE_LABEL,
  humanizeApiError,
  SITE_STATUS_LABEL,
} from "@/lib/core-api/labels";
import { listEvents } from "@/lib/core-api/events";
import { listMissions } from "@/lib/core-api/missions";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getSite } from "@/lib/core-api/sites";
import type { SiteView } from "@/lib/core-api/types";

import { SiteTransitionActions } from "./SiteTransitionActions";

const dateFormatter = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" });

const MISSION_LIMIT = 5;
const EVENT_LIMIT = 5;

/**
 * 섹션 조회 결과 — **권한 부재와 장애를 구분한다.**
 *
 * 둘을 "불러오지 못했습니다" 하나로 뭉개면, 권한이 없어서 안 보이는 것뿐인 운영자가
 * 시스템 장애로 오해해 신고하거나 새로고침을 반복한다(2026-08-04 렌더 확인에서
 * DRONE_OPERATOR 계정으로 실제 재현 — 이벤트 읽기 권한이 없는 역할이다).
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
  action,
  children,
}: {
  title: string;
  action?: { label: string; href: string };
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[15px] font-bold tracking-tight break-keep">{title}</h2>
        {action && (
          <Link
            href={action.href}
            className="tap-target flex items-center text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
          >
            {action.label}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

export default async function SiteDetailPage({
  params,
}: {
  params: Promise<{ siteId: string }>;
}) {
  const { siteId } = await params;

  // 데이터 조회는 JSX 생성과 분리한다 — try/catch 안에서 JSX 를 만들면
  // eslint react-hooks/error-boundaries 가 걸린다(렌더는 즉시 실행되지 않아 실제로 못 잡는 에러다).
  let site: SiteView | null = null;
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
        <ErrorState message={errorMessage ?? "요청을 처리하지 못했습니다."} />
      </div>
    );
  }

  // 임무·이벤트·권한 조회는 현장 조회와 독립 — 하나가 실패해도 다른 섹션은 계속 보여준다.
  const [missionsResult, eventsResult, canIssueMission, canTransitionSite] = await Promise.allSettled([
    listMissions(site.siteId),
    listEvents({ siteId: site.siteId }),
    hasAllPermissions("MISSIONS_ISSUE"),
    hasAllPermissions("SITES_WRITE"),
  ]);
  const missions = sectionOutcome(missionsResult);
  const events = sectionOutcome(
    eventsResult.status === "fulfilled"
      ? { status: "fulfilled", value: eventsResult.value.events }
      : eventsResult,
  );
  const canStartSurvey = canIssueMission.status === "fulfilled" && canIssueMission.value;
  const canTransition = canTransitionSite.status === "fulfilled" && canTransitionSite.value;
  // UNMAPPED 현장은 아직 baseline 임무가 없다 — 같은 "새 조사" 화면(SurveyWizard)으로
  // 보내되(risk dashboard-wizard-rbac-mismatch 해소 경로), 라벨은 실제 목적에 맞춘다.
  const surveyActionLabel = site.status === "UNMAPPED" ? "베이스라인 임무 발급" : "새 조사";

  const statusLabel = SITE_STATUS_LABEL[site.status];

  return (
    // 지도는 그리지 않는다 — AOI가 현장에 영속되지 않아(임무 발급 요청 시 1회성) 그릴 근거가
    // 없다. 우측 패널은 대신 좌표계 사실 + 상태 전이 액션을 둔다.
    <div className="flex flex-col gap-5 p-4 sm:p-5 lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-5 xl:grid-cols-[minmax(0,1fr)_396px]">
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <p className="num break-token text-[10.5px] font-bold tracking-wide text-ink-muted uppercase">
                {site.siteId}
              </p>
              {/* topbar 가 '현장 상세' 를 이미 찍는다 — 여기 h1 은 대상 이름이라 중복이 아니다. */}
              <h1 className="break-keep text-[19px] font-bold tracking-tight">{site.name}</h1>
            </div>
            {canStartSurvey ? (
              <Link href={`/sites/${encodeURIComponent(site.siteId)}/surveys/new`} className="btn btn-primary">
                {surveyActionLabel}
              </Link>
            ) : (
              <div className="flex flex-col items-end gap-1">
                <span className="btn cursor-not-allowed text-ink-muted" aria-disabled="true">
                  {surveyActionLabel}
                </span>
                {/* 라벨을 문장에 넣지 않는다 — "베이스라인 임무 발급"(종성 있음)과
                    "새 조사"(종성 없음)가 서로 다른 조사를 요구해 "발급를" 같은
                    비문이 나온다(독립 재검토 2026-08-04 적발). */}
                <span className="text-[12px] break-keep text-ink-muted">
                  임무 발급 권한이 있어야 시작할 수 있습니다
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <StateBadge label={statusLabel.label} tone={statusLabel.tone} />
            {site.resumeTarget && (
              <span className="text-[12.5px] break-keep text-ink-2">
                복귀 예정 상태: {SITE_STATUS_LABEL[site.resumeTarget].label}
              </span>
            )}
          </div>
        </div>

        <SectionCard
          title="이 현장의 임무"
          action={{ label: "전체보기", href: `/missions?siteId=${encodeURIComponent(site.siteId)}` }}
        >
          {missions.kind !== "ok" ? (
            <SectionFallback what="임무" outcome={missions.kind} />
          ) : missions.value.length === 0 ? (
            <p className="text-[13px] break-keep text-ink-muted">아직 없습니다.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-line">
              {missions.value.slice(0, MISSION_LIMIT).map((mission) => (
                <li key={mission.missionId}>
                  <Link
                    href={`/missions/${encodeURIComponent(mission.missionId)}`}
                    className="tap-target -mx-2 flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-2 text-[13.5px] hover:bg-sunk"
                  >
                    <span className="break-keep font-medium">{MISSION_TYPE_LABEL[mission.missionType]}</span>
                    <span className="num text-[12px] whitespace-nowrap text-ink-muted">
                      {dateFormatter.format(new Date(mission.issuedAt))}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        <SectionCard
          title="이 현장의 이벤트"
          action={{ label: "전체보기", href: `/events?siteId=${encodeURIComponent(site.siteId)}` }}
        >
          {events.kind !== "ok" ? (
            <SectionFallback what="이벤트" outcome={events.kind} />
          ) : events.value.length === 0 ? (
            <p className="text-[13px] break-keep text-ink-muted">아직 없습니다.</p>
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
                      <StatusBadge label={eventStatusLabel.label} tone={eventStatusLabel.tone} />
                      <span className="num text-[12px] whitespace-nowrap text-ink-muted">
                        {dateFormatter.format(new Date(event.occurredAt))}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </SectionCard>
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-4">
          <h2 className="mb-1 text-[13.5px] font-bold break-keep">현장 좌표계</h2>
          <dl className="border-t border-line">
            <Fact label="좌표계(CRS)" value={site.siteFrame.crs} isToken />
            <Fact label="수직 기준면" value={site.siteFrame.verticalDatum} isToken />
            <Fact label="단위" value={site.siteFrame.unit} />
            <Fact label="변환 버전" value={site.siteFrame.transformVersion} isToken />
            <Fact label="등록" value={dateFormatter.format(new Date(site.registeredAt))} isToken />
            <Fact label="최근 갱신" value={dateFormatter.format(new Date(site.updatedAt))} isToken />
          </dl>
        </div>

        {canTransition ? (
          <SiteTransitionActions siteId={site.siteId} status={site.status} resumeTarget={site.resumeTarget} />
        ) : (
          <p className="text-[12px] break-keep text-ink-muted">
            현장 상태를 전이하려면 현장 등록 권한이 필요합니다.
          </p>
        )}
      </div>
    </div>
  );
}
