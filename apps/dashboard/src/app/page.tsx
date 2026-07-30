import Link from "next/link";

import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { listEvents } from "@/lib/core-api/events";
import {
  EVENT_SEVERITY_LABEL,
  EVENT_STATUS_LABEL,
  MISSION_TYPE_LABEL,
  SITE_STATUS_LABEL,
  humanizeApiError,
} from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import { listSites } from "@/lib/core-api/sites";
import { SITE_STATUSES } from "@/lib/core-api/types";
import type {
  EventSummaryResponse,
  MissionRecordResponse,
  SiteStatus,
} from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";

// 홈은 여러 독립 카드로 구성된다 — 하나의 Core API 호출이 실패해도 나머지 카드는 정상 표시되어야
// 하므로(각 fetch를 개별 격리), 개별 실패를 던지지 않고 결과로 감싸는 얕은 헬퍼를 쓴다.
type Settled<T> = { ok: true; value: T } | { ok: false; message: string };

async function settle<T>(promise: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    if (error instanceof CoreApiError) {
      return { ok: false, message: humanizeApiError(error.code, error.status, error.serverMessage) };
    }
    return { ok: false, message: "요청을 처리하지 못했습니다." };
  }
}

const REVIEW_QUEUE_STATUSES = new Set(["CANDIDATE", "EVIDENCE_COLLECTION", "FINDING"]);
const UNRESOLVED_TRIAGE = new Set(["NONE", "ASSIGNED", "ACTION_IN_PROGRESS", "REINSPECTION_REQUESTED"]);
const HIGH_SEVERITY = new Set(["HIGH", "CRITICAL"]);
const MY_ACTION_TRIAGE = new Set(["ASSIGNED", "ACTION_IN_PROGRESS"]);
const CARD_LIST_LIMIT = 5;

function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

function byOccurredAtDesc(a: EventSummaryResponse, b: EventSummaryResponse): number {
  return new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime();
}

function Card({
  title,
  action,
  children,
}: {
  title: string;
  action?: { label: string; href: string };
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-black/10 p-4 dark:border-white/10">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-medium break-keep">{title}</h2>
        {action && (
          <Link
            href={action.href}
            className="text-foreground/70 flex min-h-11 items-center text-sm break-keep hover:underline"
          >
            {action.label}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

function EventRow({ event }: { event: EventSummaryResponse }) {
  const statusLabel = EVENT_STATUS_LABEL[event.status];
  const severityLabel = event.severity ? EVENT_SEVERITY_LABEL[event.severity] : null;
  return (
    <li>
      <Link
        href={`/events/${encodeURIComponent(event.eventKey)}`}
        className="flex min-h-11 flex-col gap-1.5 rounded-md px-2 py-2 text-sm hover:bg-black/5 dark:hover:bg-white/10 sm:flex-row sm:items-center sm:justify-between"
      >
        <span className="flex flex-col gap-0.5">
          <span className="break-keep font-medium">{event.siteId}</span>
          <span className="text-foreground/60 text-xs break-keep">
            {formatDateTime(event.occurredAt)}
          </span>
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          <StatusBadge label={statusLabel.label} tone={statusLabel.tone} />
          {severityLabel && <StatusBadge label={severityLabel.label} tone={severityLabel.tone} />}
        </span>
      </Link>
    </li>
  );
}

function MissionRow({ mission }: { mission: MissionRecordResponse }) {
  return (
    <li>
      <Link
        href={`/missions/${encodeURIComponent(mission.missionId)}`}
        className="flex min-h-11 flex-col gap-0.5 rounded-md px-2 py-2 text-sm hover:bg-black/5 dark:hover:bg-white/10"
      >
        <span className="flex items-center justify-between gap-2">
          <span className="break-keep font-medium">{mission.missionId}</span>
          <span className="text-foreground/60 text-xs break-keep">
            {formatDateTime(mission.issuedAt)}
          </span>
        </span>
        <span className="text-foreground/60 text-xs break-keep">
          {mission.siteId} · {MISSION_TYPE_LABEL[mission.missionType]}
        </span>
      </Link>
    </li>
  );
}

export default async function HomePage() {
  const [sitesResult, eventsResult, missionsResult, whoAmIResult] = await Promise.all([
    settle(listSites()),
    // 카드 1·2·5가 모두 이벤트 파생 뷰라 severity/triage OR 조합을 서버 필터 하나로 표현할 수
    // 없다 — 넓게 한 번 받아 홈에서 로컬로 파생시킨다(허용 최대 500건, S3 규모에서 충분).
    settle(listEvents({ limit: 500 })),
    settle(listMissions()),
    settle(whoAmI()),
  ]);

  const sites = sitesResult.ok ? sitesResult.value : [];
  const events = eventsResult.ok ? eventsResult.value.events : [];
  const missions = missionsResult.ok ? missionsResult.value : [];

  const reviewQueue = events
    .filter((e) => e.triage === "NONE" && REVIEW_QUEUE_STATUSES.has(e.status))
    .sort(byOccurredAtDesc)
    .slice(0, CARD_LIST_LIMIT);

  const unaddressedRisk = events
    .filter((e) => e.severity && HIGH_SEVERITY.has(e.severity) && UNRESOLVED_TRIAGE.has(e.triage))
    .sort(byOccurredAtDesc);

  const myActions =
    whoAmIResult.ok
      ? events
          .filter(
            (e) =>
              e.assignee === whoAmIResult.value.principalId && MY_ACTION_TRIAGE.has(e.triage),
          )
          .sort(byOccurredAtDesc)
      : [];

  const recentMissions = [...missions]
    .sort((a, b) => new Date(b.issuedAt).getTime() - new Date(a.issuedAt).getTime())
    .slice(0, CARD_LIST_LIMIT);

  const siteStatusCounts = sites.reduce<Record<string, number>>((acc, site) => {
    acc[site.status] = (acc[site.status] ?? 0) + 1;
    return acc;
  }, {});
  const staleOrRemapSites = sites.filter(
    (s) => s.status === "MODEL_STALE" || s.status === "REMAP_REQUIRED",
  );

  return (
    <div className="flex flex-col gap-6 p-4 sm:p-6 lg:p-8">
      <div>
        <h1 className="text-lg font-medium break-keep">홈</h1>
        <p className="text-foreground/60 break-keep text-sm">
          현장·이벤트·임무 현황을 한눈에 확인하세요.
        </p>
      </div>

      {sitesResult.ok && sites.length === 0 && (
        <EmptyState
          title="아직 등록된 현장이 없습니다"
          description="현장을 등록하면 홈에서 상태와 위험을 추적할 수 있습니다."
          action={{ label: "현장 등록", href: "/sites/new" }}
        />
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card title="검토 필요 이벤트" action={{ label: "전체보기", href: "/events?triage=NONE" }}>
          {!eventsResult.ok ? (
            <ErrorState message={eventsResult.message} />
          ) : reviewQueue.length === 0 ? (
            <p className="text-foreground/60 break-keep text-sm">검토할 이벤트가 없습니다.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-black/10 dark:divide-white/10">
              {reviewQueue.map((event) => (
                <EventRow key={event.eventKey} event={event} />
              ))}
            </ul>
          )}
        </Card>

        <Card title="미조치 위험">
          {!eventsResult.ok ? (
            <ErrorState message={eventsResult.message} />
          ) : unaddressedRisk.length === 0 ? (
            <p className="text-foreground/60 break-keep text-sm">
              조치가 필요한 고위험 이벤트가 없습니다.
            </p>
          ) : (
            <>
              <p className="break-keep text-sm">
                <span className="text-lg font-semibold">{unaddressedRisk.length}</span>건 미조치
              </p>
              <ul className="flex flex-col divide-y divide-black/10 dark:divide-white/10">
                {unaddressedRisk.slice(0, CARD_LIST_LIMIT).map((event) => (
                  <EventRow key={event.eventKey} event={event} />
                ))}
              </ul>
            </>
          )}
        </Card>

        <Card title="현장 모델 최신도" action={{ label: "전체보기", href: "/sites" }}>
          {!sitesResult.ok ? (
            <ErrorState message={sitesResult.message} />
          ) : sites.length === 0 ? (
            <p className="text-foreground/60 break-keep text-sm">등록된 현장이 없습니다.</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {SITE_STATUSES.filter((status) => siteStatusCounts[status] > 0).map((status) => (
                  <span key={status} className="inline-flex items-center gap-1">
                    <StatusBadge
                      label={SITE_STATUS_LABEL[status as SiteStatus].label}
                      tone={SITE_STATUS_LABEL[status as SiteStatus].tone}
                    />
                    <span className="text-foreground/60 text-xs">
                      {siteStatusCounts[status]}
                    </span>
                  </span>
                ))}
              </div>
              {staleOrRemapSites.length > 0 && (
                <p className="text-foreground/70 break-keep text-sm">
                  모델 최신도 점검이 필요한 현장 {staleOrRemapSites.length}곳
                </p>
              )}
            </>
          )}
        </Card>

        <Card title="최근 발급된 임무" action={{ label: "전체보기", href: "/missions" }}>
          {!missionsResult.ok ? (
            <ErrorState message={missionsResult.message} />
          ) : recentMissions.length === 0 ? (
            <p className="text-foreground/60 break-keep text-sm">발급된 임무가 없습니다.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-black/10 dark:divide-white/10">
              {recentMissions.map((mission) => (
                <MissionRow key={mission.missionId} mission={mission} />
              ))}
            </ul>
          )}
        </Card>

        <Card title="내 담당 조치">
          {!whoAmIResult.ok ? (
            <ErrorState message={whoAmIResult.message} />
          ) : !eventsResult.ok ? (
            <ErrorState message={eventsResult.message} />
          ) : myActions.length === 0 ? (
            <p className="text-foreground/60 break-keep text-sm">배정된 조치가 없습니다.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-black/10 dark:divide-white/10">
              {myActions.slice(0, CARD_LIST_LIMIT).map((event) => (
                <EventRow key={event.eventKey} event={event} />
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
