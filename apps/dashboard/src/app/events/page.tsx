import Link from "next/link";

import { listAllEvents } from "@/lib/core-api/events";
import { listSitesCached } from "@/lib/core-api/cached";
import { CoreApiError } from "@/lib/core-api/client";
import { EVENT_SEVERITIES, EVENT_STATUSES, TRIAGE_STATUSES } from "@/lib/core-api/types";
import type {
  EventSeverity,
  EventStatus,
  EventSummaryResponse,
  TriageStatus,
} from "@/lib/core-api/types";
import {
  EVENT_SEVERITY_LABEL,
  EVENT_STATUS_LABEL,
  SEVERITY_UNSET_LABEL,
  TRIAGE_STATUS_LABEL,
  humanizeApiError,
  humanizeEventType,
} from "@/lib/core-api/labels";
import { groupForTriage, isUnattended } from "@/lib/core-api/triage";
import { StateBadge, StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatStrip } from "@/components/ui/StatStrip";
import { formatKoreanDateTime } from "@/lib/datetime";
import { DwellBar } from "./DwellBar";
import { EventDetailPanel } from "./EventDetailPanel";
import { EventRowLink } from "./EventRowLink";
import { FilterSelect, type FilterSelectParams } from "./FilterSelect";

export const metadata = { title: "확인 항목 · KSI" };

interface EventsSearchParams {
  siteId?: string;
  missionId?: string;
  edgeDeviceId?: string;
  status?: string;
  severity?: string;
  triage?: string;
  queue?: string;
  /** 마스터-디테일 선택 상태 — 클라이언트 상태가 아니라 URL 이 정본이다(딥링크·새로고침·
   *  뒤로가기가 그대로 동작해야 하므로). lg(1024) 미만에서는 쓰이지 않는다(그 아래는
   *  행이 곧장 상세 페이지로 이동한다 — EventRowLink 참고). */
  selected?: string;
}

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

// 행 선택(`?selected=`) href — 다른 쿼리(status/severity/triage/siteId 등)는 그대로 두고
// selected 만 갈아 끼운다. buildFilterHref 와 달리 토글하지 않는다(같은 행을 다시 눌러도
// 열려 있던 패널이 사라지면 안 된다 — 닫기는 별도 명시적 링크로 둔다).
function buildSelectedHref(current: EventsSearchParams, eventKey: string): string {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(current)) {
    if (typeof v === "string" && v) next.set(k, v);
  }
  next.set("selected", eventKey);
  return `/events?${next.toString()}`;
}

/** 패널 "닫기" 링크 — 다른 필터는 보존한 채 `selected` 만 뗀다. */
function buildClearSelectedHref(current: EventsSearchParams): string {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(current)) {
    if (typeof v === "string" && v && k !== "selected") next.set(k, v);
  }
  const qs = next.toString();
  return qs ? `/events?${qs}` : "/events";
}

// 내부 트리아지 여섯 값을 고객이 판단할 수 있는 세 갈래로 묶는다.
const REVIEW_QUEUES = [
  { key: "needs-action", label: "처리 필요", statuses: ["NONE", "ASSIGNED"] },
  {
    key: "in-review",
    label: "검토 중",
    statuses: ["ACTION_IN_PROGRESS", "REINSPECTION_REQUESTED"],
  },
  { key: "settled", label: "정리됨", statuses: ["RESOLVED", "CLOSED"] },
] as const satisfies ReadonlyArray<{
  key: string;
  label: string;
  statuses: readonly TriageStatus[];
}>;

type ReviewQueueKey = (typeof REVIEW_QUEUES)[number]["key"];

function isReviewQueue(value?: string): value is ReviewQueueKey {
  return REVIEW_QUEUES.some((queue) => queue.key === value);
}

// 좌측 심각도 띠 — 색만으로 구분하지 않는다(옆에 라벨 배지가 항상 함께 선다).
// 미판정은 회색으로 두되 띠 자체는 그린다: 자리를 비우면 행마다 들여쓰기가 어긋난다.
const SEVERITY_STRIPE: Record<EventSeverity, string> = {
  CRITICAL: "bg-crit",
  HIGH: "bg-high",
  MEDIUM: "bg-mid",
  CANDIDATE: "bg-idle",
};

function EventRow({
  event,
  siteName,
  isSelected,
  selectedHref,
}: {
  event: EventSummaryResponse;
  siteName: string;
  /** lg 이상에서 지금 우측 패널에 열려 있는 행인가(시안 `.row.is-open`). */
  isSelected: boolean;
  /** lg 이상 좌클릭 시 실제로 이동할 곳 — 다른 필터를 보존한 `?selected=`. */
  selectedHref: string;
}) {
  const severity = event.severity
    ? EVENT_SEVERITY_LABEL[event.severity]
    : SEVERITY_UNSET_LABEL;

  return (
    <li>
      <EventRowLink
        detailHref={`/events/${encodeURIComponent(event.eventKey)}`}
        selectedHref={selectedHref}
        ariaCurrent={isSelected}
        className={`grid grid-cols-[3px_minmax(0,1fr)] gap-x-3 py-3 transition-colors hover:bg-sunk sm:grid-cols-[3px_minmax(0,1fr)_auto] ${
          // 좌측 = 심각도 띠, 우측 = 지금 열려 있는 행 — 두 신호가 같은 변에서
          // 싸우지 않게 나눈다(시안 .row.is-open 주석 그대로).
          isSelected ? "bg-accent-tint shadow-[inset_-3px_0_0_var(--accent)]" : ""
        }`}
      >
        <span
          aria-hidden="true"
          className={`row-span-full rounded-full ${event.severity ? SEVERITY_STRIPE[event.severity] : "bg-line-strong"}`}
        />
        <div className="max-w-2xl min-w-0">
          {/* 행의 변별 축은 이벤트 종류가 아니라 현장명·방치시간·발생시각이다 —
              eventType 은 지금 PERSON_PRESENT 하나뿐이라 그것만으론 행을 구분 못 한다.
              max-w — 2열이 되기 전(lg 미만) · 초광폭 모니터에서도 방치 막대가 650px
              눈금자처럼 늘어지지 않게 상한을 둔다. */}
          <p className="font-medium break-keep">{siteName}</p>
          <p className="text-ink-2 mt-0.5 flex flex-wrap items-center gap-x-2 text-sm break-keep">
            <span>{humanizeEventType(event.eventType)}</span>
            <span aria-hidden="true" className="text-ink-muted">
              ·
            </span>
            <span className="num">
              {formatKoreanDateTime(event.occurredAt, { dateStyle: "short", timeStyle: "short" })}
            </span>
            <span aria-hidden="true" className="text-ink-muted">
              ·
            </span>
            <span className={event.evidenceCount > 0 ? "text-ink-2" : "text-ink-muted"}>
              {event.evidenceCount > 0 ? `근거 ${event.evidenceCount}건` : "근거 없음"}
            </span>
          </p>
          <div className="mt-1.5">
            <DwellBar event={event} />
          </div>
        </div>
        <div className="col-start-2 mt-2 flex flex-wrap items-center gap-1.5 sm:col-start-3 sm:mt-0 sm:justify-end">
          <StatusBadge label={severity.label} tone={severity.tone} />
          <StatusBadge
            label={EVENT_STATUS_LABEL[event.status].label}
            tone={EVENT_STATUS_LABEL[event.status].tone}
          />
          {/* 트리아지는 워크플로 진행 상태 — StatusBadge(속성) 가 아니라 StateBadge(진행)로
              축을 가른다. 셋 다 StatusBadge 였을 때 "후보·후보·미배정"이 같은 알약으로
              보여 구분이 안 됐다. */}
          <StateBadge
            label={TRIAGE_STATUS_LABEL[event.triage].label}
            tone={TRIAGE_STATUS_LABEL[event.triage].tone}
          />
        </div>
      </EventRowLink>
    </li>
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

  // 대기열 3칸이 서로의 카운트를 동시에 보여줘야 한다 — 트리아지로 필터링된 응답만
  // 받으면 나머지 칸이 0으로 보인다. 트리아지를 뺀 넓은 집합을 페이지 끝까지 받아
  // 카운트를 로컬로 내고, 트리아지가 선택돼 있으면 화면에 보여줄 목록만 다시 좁힌다.
  const baseFilter = {
    siteId: filter.siteId,
    missionId: filter.missionId,
    edgeDeviceId: filter.edgeDeviceId,
    status: filter.status,
    severity: filter.severity,
  };

  let baseEvents: EventSummaryResponse[] | null = null;
  let errorMessage: string | null = null;

  // 현장 이름은 부가 정보다 — 조회가 실패해도 대기열은 보여야 한다(안전 경로).
  // 실패 시 siteId 원문으로 낮춰 표시한다.
  const [eventsSettled, sitesSettled] = await Promise.allSettled([
    listAllEvents(baseFilter),
    listSitesCached(),
  ]);

  if (eventsSettled.status === "fulfilled") {
    baseEvents = eventsSettled.value.events;
  } else {
    const error: unknown = eventsSettled.reason;
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  const siteNames = new Map<string, string>(
    sitesSettled.status === "fulfilled"
      ? sitesSettled.value.map((site) => [site.siteId, site.name])
      : [],
  );
  const siteOptions =
    sitesSettled.status === "fulfilled"
      ? sitesSettled.value.map((site) => ({
          value: site.siteId,
          label: site.name,
        }))
      : [];

  const triageCounts = new Map<TriageStatus, number>();
  if (baseEvents) {
    for (const event of baseEvents) {
      triageCounts.set(event.triage, (triageCounts.get(event.triage) ?? 0) + 1);
    }
  }

  const queue = isReviewQueue(sp.queue)
    ? REVIEW_QUEUES.find((item) => item.key === sp.queue)
    : undefined;
  const events = baseEvents
    ? baseEvents.filter(
        (event) =>
          (!filter.triage || event.triage === filter.triage) &&
          (!queue || (queue.statuses as readonly TriageStatus[]).includes(event.triage)),
      )
    : null;

  const groups = events ? groupForTriage(events) : [];
  const unattendedCount = events ? events.filter(isUnattended).length : 0;

  const hasPassthroughFilter = Boolean(sp.siteId || sp.missionId || sp.edgeDeviceId);
  const hasAnyFilter =
    hasPassthroughFilter || Boolean(filter.status || filter.severity || filter.triage || queue);
  const showFilters = baseEvents === null || baseEvents.length > 0 || hasAnyFilter;

  const filterSelectParams: FilterSelectParams = sp;

  // 마스터-디테일 선택 — URL 이 정본이다(클라이언트 상태 없음). 빈 문자열은 미선택과
  // 같게 취급한다(`?selected=` 처럼 값 없이 남은 경우 방어).
  const selectedEventKey =
    typeof sp.selected === "string" && sp.selected.length > 0 ? sp.selected : undefined;
  // "현재 필터 결과에 없다"는 events(트리아지까지 적용된 최종 목록) 기준으로 판단한다 —
  // baseEvents 조회 자체가 실패했을 때는 판단 근거가 없으므로 거짓 알림을 내지 않는다
  // (EventDetailPanel 은 이 값과 무관하게 독립적으로 getEvent 를 부른다).
  const selectedInFilter =
    selectedEventKey && events ? events.some((event) => event.eventKey === selectedEventKey) : true;
  const clearSelectedHref = buildClearSelectedHref(sp);
  const showDetailPanel = Boolean(selectedEventKey) || Boolean(events && events.length > 0);

  return (
    // 화면 이름은 topbar h1("이벤트")이 이미 갖는다 — 본문에서 다시 찍지 않는다.
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {hasPassthroughFilter && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm break-keep text-ink-2">
          <p>
            {sp.siteId
              ? `${siteNames.get(sp.siteId) ?? "선택한 현장"}의 확인 항목`
              : "공유된 운영 링크의 확인 항목"}
          </p>
          <Link href="/events" className="tap-target inline-flex font-semibold underline">
            전체 확인 항목 보기
          </Link>
          {(sp.missionId || sp.edgeDeviceId) && (
            <details className="basis-full text-[12px] text-ink-muted">
              <summary className="tap-target cursor-pointer font-semibold">전문가 필터 정보</summary>
              <p className="num break-token pt-1">
                {[sp.missionId && `비행 임무 ${sp.missionId}`, sp.edgeDeviceId && `장치 ${sp.edgeDeviceId}`]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </details>
          )}
        </div>
      )}

      {/* 고객의 처리 흐름은 내부 enum 여섯 개를 세 갈래로 묶어 먼저 보여준다.
          홈의 지표 띠와 **같은 컴포넌트**를 쓴다: 같은 자리에 같은 모양으로 수치가
          놓이지 않으면 화면마다 다시 읽게 된다. 선택 상태(aria-current 포함)는 그
          컴포넌트가 `active` 로 받는다 — 그 근거는 StatStrip 쪽 주석에 있다. */}
      {showFilters && (
        <>
          <nav aria-label="대기열 필터">
            <StatStrip
              items={REVIEW_QUEUES.map((tile) => ({
                key: tile.key,
                label: tile.label,
                value: tile.statuses.reduce((sum, status) => sum + (triageCounts.get(status) ?? 0), 0),
                unit: "건",
                href: buildFilterHref(sp, "queue", tile.key),
                active: queue?.key === tile.key,
              }))}
            />
          </nav>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <FilterSelect
              label="현장"
              paramKey="siteId"
              value={sp.siteId ?? ""}
              options={siteOptions}
              currentParams={filterSelectParams}
            />
            <FilterSelect
              label="판정 단계"
              paramKey="status"
              value={filter.status ?? ""}
              options={EVENT_STATUSES.map((status) => ({
                value: status,
                label: EVENT_STATUS_LABEL[status].label,
              }))}
              currentParams={filterSelectParams}
            />
            <FilterSelect
              label="중요도"
              paramKey="severity"
              value={filter.severity ?? ""}
              options={EVENT_SEVERITIES.map((severity) => ({
                value: severity,
                label: EVENT_SEVERITY_LABEL[severity].label,
              }))}
              currentParams={filterSelectParams}
            />
            <FilterSelect
              label="처리 상태"
              paramKey="triage"
              value={filter.triage ?? ""}
              options={TRIAGE_STATUSES.map((triage) => ({
                value: triage,
                label: TRIAGE_STATUS_LABEL[triage].label,
              }))}
              currentParams={filterSelectParams}
            />
          </div>
        </>
      )}

      {/* 시안 .work — lg(1024) 이상에서만 좌 목록 · 우 396px(1024~1279 는 340px) 상세로
          나뉜다. 그 미만은 한 열이고 행 클릭이 곧장 상세 페이지로 이동한다(EventRowLink) —
          396px 패널이 태블릿 세로·폰에서는 본문을 잡아먹을 뿐 의미가 없기 때문이다. */}
      <div
        className={
          showDetailPanel
            ? "lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-5 xl:grid-cols-[minmax(0,1fr)_396px]"
            : undefined
        }
      >
        <div className="flex flex-col gap-4">
          {errorMessage && <ErrorState message={errorMessage} />}

          {!errorMessage && events && events.length === 0 && (
            <EmptyState
              compact
              inline
              title="검토할 확인 항목이 없습니다"
              description={
                hasAnyFilter
                  ? "이 조건에 해당하는 확인 항목이 없습니다. 필터를 바꿔 다시 확인하세요."
                  : "새 관측에서 확인할 내용이 생기면 현장명·근거·필요한 판단이 이곳에 표시됩니다."
              }
              action={
                hasAnyFilter
                  ? { label: "필터 초기화", href: "/events" }
                  : { label: "현장 상태 보기", href: "/sites" }
              }
            />
          )}

          {!errorMessage && events && events.length > 0 && (
            <div className="flex flex-col rounded-lg border border-line bg-surface">
              <p className="text-ink-2 border-b border-line px-4 py-2.5 text-sm break-keep">
                총 {events.length}건
                {unattendedCount > 0 && (
                  <>
                    {" · "}
                    <span className="text-crit-ink font-medium">
                      아직 판단되지 않은 건 {unattendedCount}건
                    </span>
                  </>
                )}
              </p>
              {groups.map((group) => (
                <section key={group.key} className="flex flex-col">
                  {/* 순서를 만든 규칙을 화면에 드러낸다 — 규칙이 안 보이면 목록을 믿을 수 없다. */}
                  {group.heading && (
                    <h2 className="bg-sunk text-ink-2 border-b border-line px-4 py-1.5 text-[11px] font-semibold tracking-wide break-keep">
                      {group.heading}
                    </h2>
                  )}
                  <ul className="flex flex-col divide-y divide-line px-4">
                    {group.events.map((event) => (
                      <EventRow
                        key={event.eventKey}
                        event={event}
                        siteName={siteNames.get(event.siteId) ?? event.siteId}
                        isSelected={event.eventKey === selectedEventKey}
                        selectedHref={buildSelectedHref(sp, event.eventKey)}
                      />
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* lg 미만에서는 CSS 로 숨긴다 — 서버는 뷰포트를 모르므로 selected 가 있으면
            데이터 조회 자체는 뷰포트와 무관하게 한 번 일어나지만(getEvent 1회, N+1 아님),
            그 폭에서는 행이 상세 페이지로 이동해 이 패널이 화면에 나타날 일이 없다
            (EventRowLink 의 lg 분기와 대칭). */}
        {showDetailPanel && (
          <div className="hidden lg:sticky lg:top-4 lg:block">
            <EventDetailPanel
              eventKey={selectedEventKey}
              inCurrentFilter={selectedInFilter}
              clearHref={clearSelectedHref}
            />
          </div>
        )}
      </div>
    </div>
  );
}
