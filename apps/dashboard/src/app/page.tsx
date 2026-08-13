import Link from "next/link";

import { whoAmI } from "@/lib/core-api/auth";
import {
  listEventsCached,
  listMissionsCached,
  listSitesCached,
} from "@/lib/core-api/cached";
import { CoreApiError } from "@/lib/core-api/client";
import {
  EVENT_SEVERITY_LABEL,
  MISSION_TYPE_LABEL,
  TRIAGE_STATUS_LABEL,
  humanizeApiError,
  humanizeEventType,
} from "@/lib/core-api/labels";
import { ackSlaState, formatElapsed, isSettled, isUnattended, sortForTriage } from "@/lib/core-api/triage";
import type { EventSeverity, SiteStatus, SiteView } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge, StatusBadge } from "@/components/ui/StatusBadge";
import { SiteCard, type SiteFact } from "@/components/site/SiteCard";
import { TopUnattendedHeadline } from "./TopUnattendedHeadline";

// 홈은 여러 독립 카드로 구성된다 — 하나의 Core API 호출이 실패해도 나머지 카드는 정상 표시되어야
// 하므로(각 fetch를 개별 격리), 개별 실패를 던지지 않고 결과로 감싸는 얕은 헬퍼를 쓴다.
//
// 실패 중 **권한 부재(403)는 장애와 분리한다** — 둘을 같은 빨간 배너 + "다시 시도" 로
// 내면, 애초에 그 데이터를 볼 자격이 없는 역할에게 시스템이 고장난 것처럼 보이고
// 눌러도 소용없는 버튼을 준다(2026-08-04 렌더 확인에서 당시 이벤트 읽기 권한이 없던
// 역할로 실제 재현 — ADR-KSI-015 로 역할이 3개로 합쳐지며 이제 전 역할이 EVENTS_READ
// 를 갖는다. 패턴 자체는 다른 권한 조합에도 여전히 유효하다). sites/[siteId]/page.tsx
// 의 sectionOutcome 과 같은 규칙.
type Settled<T> =
  | { ok: true; value: T }
  | { ok: false; forbidden: boolean; message: string };

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

/** 지표 타일의 보조문구 — 값을 못 구한 이유를 구분해서 말한다. */
function unavailableNote(result: { ok: false; forbidden: boolean }): string {
  return result.forbidden ? "볼 권한이 없습니다" : "불러오지 못했습니다";
}

// 이 두 상태는 '기준 지도가 없어 순찰을 시작할 수 없다'는 같은 뜻이다 — 현장 카드를
// '할 일' 모양으로 바꾸고, 콜아웃·지표 타일이 같은 정의를 공유하도록 한 곳에 둔다.
const BLOCKED_SITE_STATUSES = new Set<SiteStatus>(["UNMAPPED", "REMAP_REQUIRED"]);

// "순찰 가능"은 **화이트리스트로만** 정의한다.
//
// 이걸 `전체 − 순찰불가`로 빼서 구하면 10개 상태 중 나머지 7개가 전부 '가능'으로 넘어온다 —
// 준비 단계(BASELINE_MAPPING·MODEL_PROCESSING·MODEL_VALIDATION)와 모델 노후(MODEL_STALE),
// 심지어 **운영 중단(SUSPENDED)** 까지 순찰 가능으로 세어진다. 운영을 정식으로 멈춘 현장을
// 현황판이 "순찰 가능"이라 말하는 건 그냥 거짓말이다.
//
// 뺄셈은 새 상태가 추가될 때도 조용히 '가능' 쪽으로 흡수한다. 안전 화면의 파생 지표는
// 열거를 늘리는 쪽이 틀렸을 때 눈에 띈다.
const PATROLLABLE_SITE_STATUSES = new Set<SiteStatus>([
  "PATROL_READY",
  "PATROL_ACTIVE",
  "PROVISIONAL_AUTONOMY",
]);
const HIGH_SEVERITY = new Set<EventSeverity>(["HIGH", "CRITICAL"]);
const TIMELINE_LIMIT = 8;

// 현장은 한국이고 서버는 어디서든 돈다 — TopBar.tsx 와 같은 근거로 시간대를 고정한다.
// 이걸 빼면 UTC 서버에서 한국시간 00:00~09:00 이벤트가 '오늘'로 잡히지 않아, 상단바가
// 말하는 날짜와 본문 타임라인이 어긋난다.
const SEOUL = "Asia/Seoul";

function formatShortDate(iso: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    timeZone: SEOUL,
  }).format(new Date(iso));
}

/** 서울 기준 연-월-일. 문자열 비교로 '같은 날'을 판정하려고 쓴다 —
 *  getFullYear/getMonth/getDate 는 **서버 로컬** 시간대를 읽으므로 여기서는 쓸 수 없다. */
function seoulDayKey(date: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: SEOUL,
  }).format(date);
}

function formatTimelineTime(iso: string): string {
  const date = new Date(iso);
  const sameDay = seoulDayKey(date) === seoulDayKey(new Date());
  return sameDay
    ? new Intl.DateTimeFormat("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: SEOUL,
      }).format(date)
    : formatShortDate(iso);
}

function Callout({
  tone,
  title,
  sub,
  cta,
}: {
  tone: "crit" | "neutral";
  // ReactNode — topUnattended 분기는 여기에 실시간으로 갈아타는 client 컴포넌트
  // (TopUnattendedHeadline)를 싣는다. 다른 분기는 여전히 고정 문자열을 준다.
  title: React.ReactNode;
  sub: string;
  cta?: { label: string; href: string };
}) {
  return (
    <div
      className={`flex flex-wrap items-center gap-4 rounded-lg border border-line bg-surface p-4 ${
        tone === "crit" ? "border-l-4 border-l-crit" : ""
      }`}
    >
      <span
        aria-hidden="true"
        className={`flex size-10 flex-none items-center justify-center rounded-lg text-lg font-extrabold ${
          tone === "crit" ? "bg-crit-bg text-crit" : "bg-sunk text-ink-2"
        }`}
      >
        {tone === "crit" ? "!" : "✓"}
      </span>
      <div className="min-w-0 flex-1">
        <p className="break-keep text-[15.5px] font-bold tracking-tight">{title}</p>
        <p className="break-keep text-[13px] text-ink-2">{sub}</p>
      </div>
      {cta && (
        <Link href={cta.href} className="btn btn-primary tap-target flex-none">
          {cta.label}
        </Link>
      )}
    </div>
  );
}

function StatTile({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  note?: string;
  tone?: "crit";
}) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-line bg-surface p-3.5">
      <span className="break-keep text-xs font-semibold text-ink-2">{label}</span>
      <span className={`num text-[26px] leading-tight font-bold tracking-tight ${tone === "crit" ? "text-crit" : ""}`}>
        {value}
      </span>
      {note && <span className="break-keep text-[11.5px] text-ink-muted">{note}</span>}
    </div>
  );
}

type TimelineItem = {
  key: string;
  at: string;
  content: React.ReactNode;
  badge?: React.ReactNode;
};

function TimelineRow({ item }: { item: TimelineItem }) {
  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-3 border-b border-line py-2.5 last:border-b-0">
      <span className="num text-xs whitespace-nowrap text-ink-muted">{formatTimelineTime(item.at)}</span>
      <span className="min-w-0 break-keep text-[13.5px]">{item.content}</span>
      <span className="justify-self-end">{item.badge}</span>
    </div>
  );
}

export default async function HomePage() {
  const [sitesResult, eventsResult, missionsResult, whoAmIResult] = await Promise.all([
    // *Cached 를 쓰는 이유는 캐싱 자체가 아니라 **셸과 본문이 같은 스냅샷을 보게** 하기
    // 위해서다 — 사이드바 배지가 "검토 3"인데 아래 카드가 4건이면 그 화면은 못 믿는다.
    settle(listSitesCached()),
    settle(listEventsCached(500)),
    settle(listMissionsCached(undefined)),
    settle(whoAmI()),
  ]);

  const sites = sitesResult.ok ? sitesResult.value : [];
  const events = eventsResult.ok ? eventsResult.value.events : [];
  const missions = missionsResult.ok ? missionsResult.value : [];
  // react-hooks/purity: `Date.now()` 는 known-impure 로 렌더 중 호출이 금지된다
  // (TopBar.tsx 관례대로 `new Date()` + `.getTime()` 을 쓴다 — 서버 컴포넌트 규칙은
  // 그쪽만 허용한다).
  const now = new Date();

  const siteById = new Map<string, SiteView>(sites.map((s) => [s.siteId, s]));

  const unattendedEvents = eventsResult.ok ? events.filter(isUnattended) : [];
  const openEventsCount = eventsResult.ok ? events.filter((e) => !isSettled(e)).length : 0;
  const slaBreachedCount = eventsResult.ok
    ? unattendedEvents.filter((e) => ackSlaState(e, now.getTime() - new Date(e.occurredAt).getTime()) === "breached")
        .length
    : 0;

  const blockedSites = sitesResult.ok ? sites.filter((s) => BLOCKED_SITE_STATUSES.has(s.status)) : [];
  const patrolReadyCount = sitesResult.ok
    ? sites.filter((s) => PATROLLABLE_SITE_STATUSES.has(s.status)).length
    : 0;

  const topUnattended =
    eventsResult.ok && unattendedEvents.length > 0 ? sortForTriage(unattendedEvents)[0] : null;

  // /sites/new 는 SITES_WRITE·MISSIONS_ISSUE 를 둘 다 요구한다(ADR-KSI-015 이후
  // 실제로는 두 권한이 항상 같이 붙어 있지만, 표가 갈려도 반쪽 상태를 안 만들려고
  // fail-closed AND 를 유지한다) — 여기서 링크 노출 여부도 같은 기준으로 맞춘다.
  // SITES_WRITE 만 보고 버튼을 보여주면, 두 권한이 갈린 미래 역할에게 눌러도
  // "권한이 없습니다"만 보이는 막다른 링크를 주게 된다.
  const canRegisterSite =
    whoAmIResult.ok &&
    whoAmIResult.value.permissions.includes("SITES_WRITE") &&
    whoAmIResult.value.permissions.includes("MISSIONS_ISSUE");

  // ── 콜아웃 — "오늘 뭘 해야 하나"에 답하는 단일 헤드라인 ─────────────────
  let calloutNode: React.ReactNode = null;
  if (!eventsResult.ok && eventsResult.forbidden) {
    // 권한이 없어 이벤트를 못 보는 역할에게 헤드라인은 "장애"가 아니라 "여긴 네 일이
    // 아니다"여야 한다 — 재시도 버튼도 주지 않는다(눌러도 결과가 같다).
    calloutNode = (
      <p className="rounded-lg border border-line bg-surface p-4 text-[13px] break-keep text-ink-2">
        이 계정은 이벤트를 볼 권한이 없어 미조치 이벤트 현황을 표시하지 않습니다.
      </p>
    );
  } else if (!eventsResult.ok) {
    calloutNode = <ErrorState message={eventsResult.message} retryable />;
  } else if (topUnattended) {
    const siteName = siteById.get(topUnattended.siteId)?.name ?? topUnattended.siteId;
    const elapsedLabel = formatElapsed(now.getTime() - new Date(topUnattended.occurredAt).getTime(), {
      unattended: true,
    });
    const initialTitle =
      elapsedLabel === "방금 들어옴" ? "방금 들어온 미조치 이벤트가 있습니다" : `${elapsedLabel} 이벤트가 있습니다`;
    calloutNode = (
      <Callout
        tone="crit"
        // 서버 렌더 시점에 고정된 initialTitle 은 SSR·마운트 전 페인트용 스냅샷이다 —
        // 마운트 후 TopUnattendedHeadline 이 60초마다 실제 경과로 갈아탄다(하드코딩된
        // "12분째"가 화면을 열어둔 채로 안 바뀌던 문제, ElapsedTime.tsx 참고).
        title={<TopUnattendedHeadline occurredAt={topUnattended.occurredAt} initialText={initialTitle} />}
        sub={`${siteName} ${humanizeEventType(topUnattended.eventType)} · 담당자가 없는 이벤트가 모두 ${unattendedEvents.length}건입니다`}
        cta={{ label: "지금 확인하기", href: `/events/${encodeURIComponent(topUnattended.eventKey)}` }}
      />
    );
  } else if (blockedSites.length > 0) {
    const target = blockedSites[0];
    const names = blockedSites.length > 1 ? `${target.name} 외 ${blockedSites.length - 1}곳` : target.name;
    calloutNode = (
      <Callout
        tone="crit"
        title={`순찰을 시작할 수 없는 현장 ${blockedSites.length}곳`}
        sub={`${names} · 조사 비행부터 필요합니다`}
        cta={{ label: "현장 확인하기", href: `/sites/${encodeURIComponent(target.siteId)}` }}
      />
    );
  } else if (sites.length > 0) {
    calloutNode = (
      <Callout
        tone="neutral"
        title="미조치 이벤트가 없습니다"
        // "모두 순찰 가능"이라 단언하지 않는다 — 이 분기는 '조사 비행이 필요한 현장이
        // 없다'는 뜻일 뿐, 준비 중·모델 노후·운영 중단 현장이 남아 있을 수 있다.
        // 실제 순찰 가능 대수는 아래 지표 타일이 화이트리스트로 세어 말한다.
        sub={`등록 현장 ${sites.length}곳 · 지금 확인이 필요한 이벤트는 없습니다.`}
      />
    );
  }

  // ── 현장 카드 그리드 ─────────────────────────────────────────────────
  const sortedSites = [...sites].sort((a, b) => {
    const aBlocked = BLOCKED_SITE_STATUSES.has(a.status);
    const bBlocked = BLOCKED_SITE_STATUSES.has(b.status);
    if (aBlocked !== bBlocked) return aBlocked ? -1 : 1;
    return a.name.localeCompare(b.name, "ko");
  });

  function riskBadgeFor(siteId: string): React.ReactNode {
    const risky = unattendedEvents.filter((e) => e.siteId === siteId && e.severity && HIGH_SEVERITY.has(e.severity));
    if (risky.length === 0) return null;
    const severity: EventSeverity = risky.some((e) => e.severity === "CRITICAL") ? "CRITICAL" : "HIGH";
    const label = EVENT_SEVERITY_LABEL[severity];
    return <StatusBadge label={`${label.label} ${risky.length}`} tone={label.tone} />;
  }

  function factsFor(site: SiteView): SiteFact[] {
    const facts: SiteFact[] = [{ key: "등록일", value: formatShortDate(site.registeredAt), numeric: true }];
    if (missionsResult.ok) {
      facts.push({
        key: "발급 임무",
        value: String(missions.filter((m) => m.siteId === site.siteId).length),
        numeric: true,
      });
    }
    if (eventsResult.ok) {
      facts.push({
        key: "미조치 이벤트",
        value: String(unattendedEvents.filter((e) => e.siteId === site.siteId).length),
        numeric: true,
      });
    }
    if (BLOCKED_SITE_STATUSES.has(site.status)) {
      facts.push({
        key: "다음 할 일",
        value: site.status === "UNMAPPED" ? "조사 비행 계획" : "재조사 비행 계획",
        emphasis: true,
      });
    }
    return facts;
  }

  function todoMessageFor(site: SiteView): string | undefined {
    if (site.status === "UNMAPPED") {
      return "기준 지도가 없어 순찰을 시작할 수 없습니다. 조사 비행을 하면 구역을 그릴 수 있습니다.";
    }
    if (site.status === "REMAP_REQUIRED") {
      return "현장 모델이 최신이 아니어서 재매핑이 필요합니다. 재조사 비행을 계획하세요.";
    }
    return undefined;
  }

  // ── 타임라인 — 이벤트 발생·현장 등록·임무 발급을 하나의 시간순 로그로 ───
  const timelineItems: TimelineItem[] = [];
  if (eventsResult.ok) {
    for (const event of events) {
      const triageLabel = TRIAGE_STATUS_LABEL[event.triage];
      timelineItems.push({
        key: `event-${event.eventKey}`,
        at: event.occurredAt,
        content: (
          <>
            <b className="font-semibold">{humanizeEventType(event.eventType)}</b> 감지 —{" "}
            {siteById.get(event.siteId)?.name ?? event.siteId}
          </>
        ),
        badge: <StateBadge label={triageLabel.label} tone={triageLabel.tone} />,
      });
    }
  }
  if (sitesResult.ok) {
    for (const site of sites) {
      timelineItems.push({
        key: `site-${site.siteId}`,
        at: site.registeredAt,
        content: (
          <>
            <b className="font-semibold">{site.name}</b> 현장 등록
          </>
        ),
      });
    }
  }
  if (missionsResult.ok) {
    for (const mission of missions) {
      timelineItems.push({
        key: `mission-${mission.missionId}`,
        at: mission.issuedAt,
        content: (
          <>
            <b className="font-semibold">{MISSION_TYPE_LABEL[mission.missionType]}</b> 임무 발급 —{" "}
            {siteById.get(mission.siteId)?.name ?? mission.siteId}
          </>
        ),
      });
    }
  }
  timelineItems.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  const recentTimeline = timelineItems.slice(0, TIMELINE_LIMIT);

  return (
    // 화면 이름은 topbar 가 갖는다(스크롤해도 남는 자리) — 여기서 h1 을 또 찍으면
    // 같은 말이 두 번 나오고 본문 첫 화면이 그만큼 밀린다.
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      {sitesResult.ok && sites.length === 0 && (
        <EmptyState
          title="아직 등록된 현장이 없습니다"
          description={
            canRegisterSite
              ? "현장을 등록하면 홈에서 상태와 위험을 추적할 수 있습니다."
              : "현장 등록은 현장 등록 권한을 가진 계정만 할 수 있습니다."
          }
          action={canRegisterSite ? { label: "현장 등록", href: "/sites/new" } : undefined}
        />
      )}

      {calloutNode}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="미조치 이벤트"
          value={eventsResult.ok ? unattendedEvents.length : "—"}
          tone={eventsResult.ok && unattendedEvents.length > 0 ? "crit" : undefined}
          note={eventsResult.ok ? `전체 열린 이벤트 ${openEventsCount}건 중` : unavailableNote(eventsResult)}
        />
        <StatTile
          label="확인 SLA 초과"
          value={eventsResult.ok ? slaBreachedCount : "—"}
          tone={eventsResult.ok && slaBreachedCount > 0 ? "crit" : undefined}
          note={eventsResult.ok ? "즉시 확인이 필요합니다" : unavailableNote(eventsResult)}
        />
        <StatTile
          label="순찰 가능 현장"
          value={sitesResult.ok ? `${patrolReadyCount}/${sites.length}` : "—"}
          note={sitesResult.ok ? "등록 현장 중" : unavailableNote(sitesResult)}
        />
        <StatTile
          label="발급된 임무"
          value={missionsResult.ok ? missions.length : "—"}
          note={missionsResult.ok ? "누적 발급 건수" : unavailableNote(missionsResult)}
        />
      </div>

      {!sitesResult.ok ? (
        sitesResult.forbidden ? (
          <p className="rounded-lg border border-line bg-surface p-4 text-[13px] break-keep text-ink-2">
            이 계정은 현장 목록을 볼 권한이 없습니다.
          </p>
        ) : (
          <ErrorState message={sitesResult.message} retryable />
        )
      ) : (
        sites.length > 0 && (
          <div className="flex flex-col gap-3">
            <div className="flex items-baseline gap-2.5">
              <h2 className="text-[15px] font-bold tracking-tight break-keep">현장</h2>
              <span className="break-keep text-[12.5px] text-ink-muted">
                {sites.length}곳
                {blockedSites.length > 0 && ` · ${blockedSites.length}곳은 아직 순찰할 수 없습니다`}
              </span>
              <Link href="/sites" className="ml-auto text-[12.5px] font-semibold break-keep text-accent-text hover:underline">
                전체 보기
              </Link>
            </div>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(238px,1fr))] gap-3">
              {sortedSites.map((site) => (
                <SiteCard
                  key={site.siteId}
                  site={site}
                  facts={factsFor(site)}
                  todoMessage={todoMessageFor(site)}
                  riskSlot={riskBadgeFor(site.siteId)}
                />
              ))}
            </div>
          </div>
        )
      )}

      <div className="flex flex-col gap-3">
        <div className="flex items-baseline gap-2.5">
          {/* 시안 제목은 "오늘 있었던 일"이지만 그건 항목이 전부 당일이라는 목업 전제 위에
              있다. 여기 목록은 날짜 필터 없이 최신 8건이라, 조용한 현장에서는 몇 달 전
              '현장 등록'이 그 제목 아래 뜬다. 제목이 내용보다 강하게 주장하면 안 된다. */}
          <h2 className="text-[15px] font-bold tracking-tight break-keep">최근 활동</h2>
          <Link href="/events" className="ml-auto text-[12.5px] font-semibold break-keep text-accent-text hover:underline">
            이벤트 이력
          </Link>
        </div>
        <div className="rounded-lg border border-line bg-surface px-4 py-1">
          {recentTimeline.length === 0 ? (
            <p className="py-3 text-sm break-keep text-ink-muted">최근 활동이 없습니다.</p>
          ) : (
            recentTimeline.map((item) => <TimelineRow key={item.key} item={item} />)
          )}
        </div>
      </div>
    </div>
  );
}
