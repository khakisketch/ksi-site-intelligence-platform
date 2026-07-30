import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import {
  EVENT_STATUS_LABEL,
  MISSION_TYPE_LABEL,
  humanizeApiError,
  SITE_STATUS_LABEL,
} from "@/lib/core-api/labels";
import { listEvents } from "@/lib/core-api/events";
import { listMissions } from "@/lib/core-api/missions";
import { getSite } from "@/lib/core-api/sites";
import type { SiteView } from "@/lib/core-api/types";

const dateFormatter = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" });

const MISSION_LIMIT = 5;
const EVENT_LIMIT = 5;

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
      <div className="mx-auto flex max-w-3xl flex-col gap-6 p-6 sm:p-10">
        <ErrorState message={errorMessage ?? "요청을 처리하지 못했습니다."} />
      </div>
    );
  }

  // 임무·이벤트 조회는 현장 조회와 독립 — 한쪽이 실패해도 다른 섹션은 계속 보여준다.
  const [missionsResult, eventsResult] = await Promise.allSettled([
    listMissions(site.siteId),
    listEvents({ siteId: site.siteId }),
  ]);
  const missions = missionsResult.status === "fulfilled" ? missionsResult.value : null;
  const events = eventsResult.status === "fulfilled" ? eventsResult.value.events : null;

  const statusLabel = SITE_STATUS_LABEL[site.status];

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8 p-6 sm:p-10">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="break-keep text-lg font-semibold">{site.name}</h1>
            <span className="text-foreground/60 text-sm">{site.siteId}</span>
          </div>
          <Link
            href={`/sites/${encodeURIComponent(site.siteId)}/surveys/new`}
            className="bg-foreground text-background inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium"
          >
            새 조사
          </Link>
        </div>

        <div>
          <StatusBadge label={statusLabel.label} tone={statusLabel.tone} />
        </div>

        {site.resumeTarget && (
          <p className="text-foreground/70 text-sm break-keep">
            복귀 예정 상태: {SITE_STATUS_LABEL[site.resumeTarget].label}
          </p>
        )}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-black/10 px-4 py-3 text-sm dark:border-white/10 sm:grid-cols-4">
          <div>
            <dt className="text-foreground/60 text-xs">좌표계(CRS)</dt>
            <dd className="break-keep">{site.siteFrame.crs}</dd>
          </div>
          <div>
            <dt className="text-foreground/60 text-xs">수직 기준면</dt>
            <dd className="break-keep">{site.siteFrame.verticalDatum}</dd>
          </div>
          <div>
            <dt className="text-foreground/60 text-xs">단위</dt>
            <dd className="break-keep">{site.siteFrame.unit}</dd>
          </div>
          <div>
            <dt className="text-foreground/60 text-xs">변환 버전</dt>
            <dd className="break-keep">{site.siteFrame.transformVersion}</dd>
          </div>
        </dl>

        <div className="text-foreground/60 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span>등록 {dateFormatter.format(new Date(site.registeredAt))}</span>
          <span>최근 갱신 {dateFormatter.format(new Date(site.updatedAt))}</span>
        </div>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold break-keep">최근 임무</h2>
        {missions === null ? (
          <p className="text-foreground/60 text-sm break-keep">임무 정보를 불러오지 못했습니다.</p>
        ) : missions.length === 0 ? (
          <p className="text-foreground/60 text-sm break-keep">아직 없습니다.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {missions.slice(0, MISSION_LIMIT).map((mission) => (
              <li key={mission.missionId}>
                <Link
                  href={`/missions/${encodeURIComponent(mission.missionId)}`}
                  className="flex min-h-11 flex-wrap items-center justify-between gap-2 rounded-lg border border-black/10 px-4 py-3 text-sm transition-colors hover:bg-black/5 dark:border-white/10 dark:hover:bg-white/5"
                >
                  <span className="break-keep">{MISSION_TYPE_LABEL[mission.missionType]}</span>
                  <span className="text-foreground/60 text-xs whitespace-nowrap">
                    {dateFormatter.format(new Date(mission.issuedAt))}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold break-keep">최근 이벤트</h2>
        {events === null ? (
          <p className="text-foreground/60 text-sm break-keep">이벤트 정보를 불러오지 못했습니다.</p>
        ) : events.length === 0 ? (
          <p className="text-foreground/60 text-sm break-keep">아직 없습니다.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {events.slice(0, EVENT_LIMIT).map((event) => {
              const eventStatusLabel = EVENT_STATUS_LABEL[event.status];
              return (
                <li key={event.eventKey}>
                  <Link
                    href={`/events/${encodeURIComponent(event.eventKey)}`}
                    className="flex min-h-11 flex-wrap items-center justify-between gap-2 rounded-lg border border-black/10 px-4 py-3 text-sm transition-colors hover:bg-black/5 dark:border-white/10 dark:hover:bg-white/5"
                  >
                    <StatusBadge label={eventStatusLabel.label} tone={eventStatusLabel.tone} />
                    <span className="text-foreground/60 text-xs whitespace-nowrap">
                      {dateFormatter.format(new Date(event.occurredAt))}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
