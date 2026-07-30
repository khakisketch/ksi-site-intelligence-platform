import Link from "next/link";

import { listEvents } from "@/lib/core-api/events";
import { CoreApiError } from "@/lib/core-api/client";
import { EVENT_SEVERITIES, EVENT_STATUSES, TRIAGE_STATUSES } from "@/lib/core-api/types";
import type { EventSeverity, EventStatus, TriageStatus } from "@/lib/core-api/types";
import {
  EVENT_SEVERITY_LABEL,
  EVENT_STATUS_LABEL,
  TRIAGE_STATUS_LABEL,
  humanizeApiError,
} from "@/lib/core-api/labels";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

interface EventsSearchParams {
  siteId?: string;
  missionId?: string;
  edgeDeviceId?: string;
  status?: string;
  severity?: string;
  triage?: string;
}

const dateFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
});

function isEventStatus(value?: string): value is EventStatus {
  return value !== undefined && (EVENT_STATUSES as readonly string[]).includes(value);
}

function isEventSeverity(value?: string): value is EventSeverity {
  return value !== undefined && (EVENT_SEVERITIES as readonly string[]).includes(value);
}

function isTriageStatus(value?: string): value is TriageStatus {
  return value !== undefined && (TRIAGE_STATUSES as readonly string[]).includes(value);
}

function buildFilterHref(
  current: EventsSearchParams,
  key: keyof EventsSearchParams,
  value: string,
): string {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(current)) {
    if (typeof v === "string" && v) next.set(k, v);
  }
  if (next.get(key) === value) {
    next.delete(key);
  } else {
    next.set(key, value);
  }
  const qs = next.toString();
  return qs ? `/events?${qs}` : "/events";
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-foreground/60 text-xs font-medium break-keep">{label}</span>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

function FilterChip({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex min-h-11 items-center rounded-full border px-3 text-sm break-keep whitespace-nowrap ${
        active
          ? "bg-foreground text-background border-foreground"
          : "border-black/15 dark:border-white/15"
      }`}
    >
      {children}
    </Link>
  );
}

export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<EventsSearchParams>;
}) {
  const sp = await searchParams;

  const filter = {
    siteId: sp.siteId,
    missionId: sp.missionId,
    edgeDeviceId: sp.edgeDeviceId,
    status: isEventStatus(sp.status) ? sp.status : undefined,
    severity: isEventSeverity(sp.severity) ? sp.severity : undefined,
    triage: isTriageStatus(sp.triage) ? sp.triage : undefined,
  };

  let result: Awaited<ReturnType<typeof listEvents>> | null = null;
  let errorMessage: string | null = null;

  try {
    result = await listEvents(filter);
  } catch (error) {
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  const hasPassthroughFilter = Boolean(sp.siteId || sp.missionId || sp.edgeDeviceId);
  const hasAnyFilter =
    hasPassthroughFilter || Boolean(filter.status || filter.severity || filter.triage);

  return (
    <div className="flex flex-col gap-6 p-4 sm:p-6">
      <div>
        <h1 className="text-lg font-medium break-keep">이벤트 트리아지</h1>
        {hasPassthroughFilter && (
          <p className="text-foreground/70 mt-1 text-sm break-keep">
            {[
              sp.siteId && `현장 ${sp.siteId}`,
              sp.missionId && `임무 ${sp.missionId}`,
              sp.edgeDeviceId && `장치 ${sp.edgeDeviceId}`,
            ]
              .filter(Boolean)
              .join(" · ")}{" "}
            <Link href="/events" className="underline">
              필터 해제
            </Link>
          </p>
        )}
      </div>

      <div className="flex flex-col gap-4">
        <FilterGroup label="상태">
          {EVENT_STATUSES.map((status) => (
            <FilterChip
              key={status}
              href={buildFilterHref(sp, "status", status)}
              active={filter.status === status}
            >
              {EVENT_STATUS_LABEL[status].label}
            </FilterChip>
          ))}
        </FilterGroup>
        <FilterGroup label="심각도">
          {EVENT_SEVERITIES.map((severity) => (
            <FilterChip
              key={severity}
              href={buildFilterHref(sp, "severity", severity)}
              active={filter.severity === severity}
            >
              {EVENT_SEVERITY_LABEL[severity].label}
            </FilterChip>
          ))}
        </FilterGroup>
        <FilterGroup label="트리아지">
          {TRIAGE_STATUSES.map((triage) => (
            <FilterChip
              key={triage}
              href={buildFilterHref(sp, "triage", triage)}
              active={filter.triage === triage}
            >
              {TRIAGE_STATUS_LABEL[triage].label}
            </FilterChip>
          ))}
        </FilterGroup>
      </div>

      {errorMessage && <ErrorState message={errorMessage} />}

      {!errorMessage && result && result.events.length === 0 && (
        <EmptyState
          title="검토할 이벤트가 없습니다"
          description={hasAnyFilter ? "이 필터에 해당하는 이벤트가 없습니다." : undefined}
        />
      )}

      {!errorMessage && result && result.events.length > 0 && (
        <>
          <p className="text-foreground/60 text-sm break-keep">총 {result.count}건</p>
          <ul className="flex flex-col divide-y divide-black/10 dark:divide-white/10">
            {result.events.map((event) => (
              <li key={event.eventKey}>
                <Link
                  href={`/events/${encodeURIComponent(event.eventKey)}`}
                  className="flex min-h-11 flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      label={EVENT_STATUS_LABEL[event.status].label}
                      tone={EVENT_STATUS_LABEL[event.status].tone}
                    />
                    {event.severity && (
                      <StatusBadge
                        label={EVENT_SEVERITY_LABEL[event.severity].label}
                        tone={EVENT_SEVERITY_LABEL[event.severity].tone}
                      />
                    )}
                    <StatusBadge
                      label={TRIAGE_STATUS_LABEL[event.triage].label}
                      tone={TRIAGE_STATUS_LABEL[event.triage].tone}
                    />
                  </div>
                  <div className="text-foreground/70 flex flex-wrap gap-x-3 gap-y-1 text-sm break-keep">
                    <span>{dateFormatter.format(new Date(event.occurredAt))}</span>
                    <span>현장 {event.siteId}</span>
                    <span>장치 {event.edgeDeviceId}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
