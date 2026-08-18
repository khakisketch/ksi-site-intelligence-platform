import Link from "next/link";

import { whoAmI } from "@/lib/core-api/auth";
import {
  listEventsCached,
  listMissionsCached,
  listSitesCached,
} from "@/lib/core-api/cached";
import { CoreApiError } from "@/lib/core-api/client";
import { listSiteProcessingJobs } from "@/lib/core-api/comparison";
import {
  EVENT_SEVERITY_LABEL,
  SEVERITY_UNSET_LABEL,
  humanizeApiError,
  humanizeEventType,
} from "@/lib/core-api/labels";
import { listRegionExtraction } from "@/lib/core-api/region-extraction";
// 순찰 가능 화이트리스트는 현장 목록의 '순찰 가능' 칩과 **같은 집합**이어야 한다 —
// 두 화면이 서로 다른 수를 말하면 어느 쪽도 못 믿는다(그쪽 모듈 docstring).
import { PATROLLABLE_SITE_STATUSES } from "@/lib/core-api/site-progress";
import { ackSlaState, formatElapsed, isSettled, isUnattended, sortForTriage } from "@/lib/core-api/triage";
import type { MissionRecordResponse, SiteStatus, SiteView } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { ReobsSuggestions, type ReobsSuggestion } from "@/components/site/ReobsSuggestions";
import { StatStrip } from "@/components/ui/StatStrip";

import { PortfolioTable } from "./PortfolioTable";
import { ProcessingCard, type ProcessingCardItem } from "./ProcessingCard";
import { TopUnattendedHeadline } from "./TopUnattendedHeadline";
import { normalizePortfolioSort, sortPortfolio, type PortfolioRow } from "./portfolio";

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

/** 지표 칸의 보조문구 — 값을 못 구한 이유를 구분해서 말한다. */
function unavailableNote(result: { ok: false; forbidden: boolean }): string {
  return result.forbidden ? "볼 권한이 없습니다" : "불러오지 못했습니다";
}

// 이 두 상태는 '기준 지도가 없어 순찰을 시작할 수 없다'는 같은 뜻이다 — 헤드라인·지표·
// 포트폴리오 표가 같은 정의를 공유하도록 한 곳에 둔다.
const BLOCKED_SITE_STATUSES = new Set<SiteStatus>(["UNMAPPED", "REMAP_REQUIRED"]);

/** 헤드라인 아래 '다음에 할 일' 칩 수 — 네 개를 넘기면 한 줄에서 훑히지 않는다. */
const NEXT_PILL_LIMIT = 3;

// ── 홈이 추가로 두드리는 표면의 범위 ────────────────────────────────────────
//
// 처리 작업은 현장 단위, 변화 영역은 임무 단위 조회다 — 전 현장·전 임무를 훑으면
// 홈 한 번에 수십 번 왕복한다. 상위 몇 건으로 자르고, **자른 범위를 화면에 밝힌다**
// (카드의 scopeNote). 범위를 숨기면 "처리 중 0건"이 전 현장을 다 본 결과처럼 읽힌다.
const PROCESSING_SITE_LIMIT = 4;
const PROCESSING_ITEM_LIMIT = 5;
const REOBS_MISSION_LIMIT = 6;
const REOBS_ITEM_LIMIT = 5;

/** 아직 끝나지 않았거나 실패한 것만 — 완료·취소된 작업은 '기다리는 일'이 아니다. */
const PENDING_JOB_STATUSES = new Set(["QUEUED", "RUNNING", "FAILED"]);

/**
 * 헤드라인 — "지금 무엇을 해야 하나"에 답하는 화면 최상단 한 장(Console v2 §1).
 *
 * 왼쪽 4px 색띠와 태그 칩만으로 상태를 말하고, 본문에는 그 판단의 근거(범위·건수)를
 * 둔다. 오른쪽은 행동 열이다 — 읽고 나서 손이 가는 자리가 항상 같은 곳이어야 한다.
 */
function Headline({
  tone,
  tag,
  scope,
  title,
  sub,
  pills = [],
  actions = [],
}: {
  tone: "crit" | "neutral";
  tag: string;
  scope?: string;
  // ReactNode — topUnattended 분기는 여기에 실시간으로 갈아타는 client 컴포넌트
  // (TopUnattendedHeadline)를 싣는다. 다른 분기는 여전히 고정 문자열을 준다.
  title: React.ReactNode;
  sub?: string;
  pills?: { key: string; label: string; href: string; tone: "crit" | "high" | "neutral" }[];
  actions?: { key: string; label: string; href: string; primary?: boolean }[];
}) {
  const dotClass = { crit: "bg-crit", high: "bg-high", neutral: "bg-ink-muted" };

  return (
    <section
      className={`flex flex-wrap items-stretch overflow-hidden rounded-lg border border-line border-l-4 bg-surface ${
        tone === "crit" ? "border-l-crit" : "border-l-line-strong"
      }`}
    >
      <div className="min-w-[260px] flex-1 px-4 py-3">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-[4px] px-1.5 py-0.5 text-[11px] font-bold whitespace-nowrap ${
              tone === "crit" ? "bg-crit-bg text-crit-ink" : "bg-idle-bg text-idle-ink"
            }`}
          >
            <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
            {tag}
          </span>
          {scope && <span className="text-[11.5px] break-keep text-ink-muted">{scope}</span>}
        </div>
        <p className="text-[18.5px] leading-tight font-bold tracking-tight break-keep">{title}</p>
        {sub && <p className="mt-1 text-[12.5px] break-keep text-ink-2">{sub}</p>}
        {pills.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {pills.map((pill) => (
              <Link
                key={pill.key}
                href={pill.href}
                className="tap-target inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 text-[11.5px] break-keep transition-colors hover:border-line-strong hover:bg-sunk"
              >
                <span aria-hidden="true" className={`size-1.5 rounded-full ${dotClass[pill.tone]}`} />
                {pill.label}
              </Link>
            ))}
          </div>
        )}
      </div>
      {actions.length > 0 && (
        <div className="flex flex-none flex-wrap items-center gap-2 border-line bg-sunk px-4 py-3 sm:border-l">
          {actions.map((action) => (
            <Link
              key={action.key}
              href={action.href}
              className={`btn tap-target ${action.primary ? "btn-primary" : ""}`}
            >
              {action.label}
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * 처리 중·대기 작업 — 상위 현장 몇 곳만 훑는다(`PROCESSING_SITE_LIMIT`).
 *
 * 현장별로 실패를 격리한다: 한 현장의 조회가 죽어도 나머지 현장의 작업은 그대로
 * 보여야 한다. 전부 실패했을 때만 카드가 사유를 말한다 — 일부 실패를 "없음"으로
 * 뭉개면 진행 중인 작업이 화면에서 사라진다.
 *
 * **404 는 장애가 아니다.** Core 는 오브젝트 스토리지가 없는 조립에서 재구성 표면을
 * 아예 장착하지 않는다(app.py: "없는 편이 정직하다"). 그 배포에서 이 카드가 "불러오지
 * 못했습니다"라고 하면 고칠 수 없는 오류를 매일 보게 된다 — 그건 이 배포에 그 기능이
 * 없다는 사실이고, 그렇게 말해야 한다.
 */
async function loadProcessing(
  sites: SiteView[],
): Promise<{ items: ProcessingCardItem[]; unavailable: "absent" | "failed" | null }> {
  if (sites.length === 0) return { items: [], unavailable: null };

  const settled = await Promise.allSettled(
    sites.map((site) => listSiteProcessingJobs(site.siteId, PROCESSING_ITEM_LIMIT * 2)),
  );

  const items: ProcessingCardItem[] = [];
  let failures = 0;
  let notFound = 0;
  settled.forEach((result, index) => {
    if (result.status !== "fulfilled") {
      failures += 1;
      if (result.reason instanceof CoreApiError && result.reason.status === 404) notFound += 1;
      return;
    }
    const site = sites[index];
    for (const job of result.value.jobs) {
      if (!PENDING_JOB_STATUSES.has(job.status)) continue;
      items.push({
        jobId: job.jobId,
        siteId: site.siteId,
        siteName: site.name,
        status: job.status,
        issuedAt: job.issuedAt,
        detail: job.detail,
      });
    }
  });

  items.sort((a, b) => new Date(b.issuedAt).getTime() - new Date(a.issuedAt).getTime());
  const unavailable =
    failures < sites.length ? null : notFound === sites.length ? "absent" : "failed";
  return { items: items.slice(0, PROCESSING_ITEM_LIMIT), unavailable };
}

/**
 * 재관측 제안 — 최근 임무 몇 건의 변화 영역 추출 결과를 모은다.
 *
 * 계산된 적이 없는 임무는 404 다(대부분이 그렇다) — 그건 오류가 아니라 빈 결과이므로
 * 조용히 건너뛴다. 순변화가 큰 순으로 자르되 **부호는 버리지 않는다**: 쌓인 곳과 깎인
 * 곳은 같은 크기라도 다른 사실이고, 화면은 그 값을 그대로 옮긴다.
 */
async function loadReobs(
  missions: MissionRecordResponse[],
  siteById: Map<string, SiteView>,
): Promise<ReobsSuggestion[]> {
  if (missions.length === 0) return [];

  const settled = await Promise.allSettled(
    missions.map((mission) => listRegionExtraction(mission.missionId)),
  );

  const items: ReobsSuggestion[] = [];
  settled.forEach((result, index) => {
    if (result.status !== "fulfilled") return;
    const mission = missions[index];
    const latest = result.value.reports[0];
    if (!latest) return;
    for (const region of latest.report.regions) {
      items.push({
        regionId: region.regionId,
        siteId: mission.siteId,
        siteName: siteById.get(mission.siteId)?.name ?? mission.siteId,
        missionId: mission.missionId,
        changeRegionSetId: latest.report.changeRegionSetId,
        netM3: region.volume.netM3,
      });
    }
  });

  items.sort((a, b) => Math.abs(b.netM3) - Math.abs(a.netM3));
  return items.slice(0, REOBS_ITEM_LIMIT);
}

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; sort?: string }>;
}) {
  const { q, sort } = await searchParams;

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

  const triaged = eventsResult.ok ? sortForTriage(unattendedEvents) : [];
  const topUnattended = triaged[0] ?? null;

  // /sites/new 는 SITES_WRITE·MISSIONS_ISSUE 를 둘 다 요구한다(ADR-KSI-015 이후
  // 실제로는 두 권한이 항상 같이 붙어 있지만, 표가 갈려도 반쪽 상태를 안 만들려고
  // fail-closed AND 를 유지한다) — 여기서 링크 노출 여부도 같은 기준으로 맞춘다.
  // SITES_WRITE 만 보고 버튼을 보여주면, 두 권한이 갈린 미래 역할에게 눌러도
  // "권한이 없습니다"만 보이는 막다른 링크를 주게 된다.
  const permissions = whoAmIResult.ok ? whoAmIResult.value.permissions : [];
  const canIssueMissions = permissions.includes("MISSIONS_ISSUE");
  const canRegisterSite = permissions.includes("SITES_WRITE") && canIssueMissions;

  // ── 포트폴리오 행 ────────────────────────────────────────────────────
  //
  // 미조치 수는 이벤트 조회가 성공했을 때만 숫자다 — 실패·권한부재면 `null` 로 두어
  // 표가 "0건"이라 말하지 않게 한다(그 칸은 "—" 로 그려진다).
  const lastMissionBySite = new Map<string, string>();
  for (const mission of missions) {
    const previous = lastMissionBySite.get(mission.siteId);
    if (!previous || new Date(mission.issuedAt).getTime() > new Date(previous).getTime()) {
      lastMissionBySite.set(mission.siteId, mission.issuedAt);
    }
  }

  const portfolioRows: PortfolioRow[] = sites.map((site) => ({
    siteId: site.siteId,
    name: site.name,
    status: site.status,
    registeredAt: site.registeredAt,
    lastMissionAt: missionsResult.ok ? (lastMissionBySite.get(site.siteId) ?? null) : null,
    unattendedCount: eventsResult.ok
      ? unattendedEvents.filter((e) => e.siteId === site.siteId).length
      : null,
    blocked: BLOCKED_SITE_STATUSES.has(site.status),
  }));

  // 오른쪽 카드들이 훑을 현장·임무는 표의 기본 정렬(확인 필요한 순)과 같은 기준으로
  // 고른다 — 표 맨 위 현장과 옆 카드가 서로 다른 현장을 말하면 두 번 읽게 된다.
  const attentionOrder = sortPortfolio(portfolioRows, "attention");
  const processingSites = attentionOrder
    .slice(0, PROCESSING_SITE_LIMIT)
    .map((row) => siteById.get(row.siteId))
    .filter((site): site is SiteView => site !== undefined);

  const recentMissions = [...missions]
    .sort((a, b) => new Date(b.issuedAt).getTime() - new Date(a.issuedAt).getTime())
    .slice(0, REOBS_MISSION_LIMIT);

  const [processing, reobsItems] = await Promise.all([
    loadProcessing(processingSites),
    loadReobs(recentMissions, siteById),
  ]);

  // ── 헤드라인 ─────────────────────────────────────────────────────────
  const nextPills: { key: string; label: string; href: string; tone: "crit" | "high" | "neutral" }[] = [];
  for (const event of triaged.slice(0, NEXT_PILL_LIMIT)) {
    const siteName = siteById.get(event.siteId)?.name ?? event.siteId;
    const elapsed = formatElapsed(now.getTime() - new Date(event.occurredAt).getTime(), {
      unattended: true,
    });
    nextPills.push({
      key: `event-${event.eventKey}`,
      label: `${siteName} · ${humanizeEventType(event.eventType)} · ${elapsed}`,
      href: `/events/${encodeURIComponent(event.eventKey)}`,
      tone: event.severity === "CRITICAL" || event.severity === "HIGH" ? "crit" : "high",
    });
  }
  for (const site of blockedSites.slice(0, NEXT_PILL_LIMIT - nextPills.length)) {
    nextPills.push({
      key: `site-${site.siteId}`,
      label: `${site.name} · ${site.status === "UNMAPPED" ? "초기 조사 필요" : "재조사 필요"}`,
      href: `/sites/${encodeURIComponent(site.siteId)}`,
      tone: "neutral",
    });
  }

  let headlineNode: React.ReactNode = null;
  if (!eventsResult.ok && eventsResult.forbidden) {
    // 권한이 없어 이벤트를 못 보는 역할에게 헤드라인은 "장애"가 아니라 "여긴 네 일이
    // 아니다"여야 한다 — 재시도 버튼도 주지 않는다(눌러도 결과가 같다).
    headlineNode = (
      <p className="rounded-lg border border-line bg-surface p-4 text-[13px] break-keep text-ink-2">
        이 계정은 이벤트를 볼 권한이 없어 미조치 이벤트 현황을 표시하지 않습니다.
      </p>
    );
  } else if (!eventsResult.ok) {
    headlineNode = <ErrorState message={eventsResult.message} retryable />;
  } else if (topUnattended) {
    const site = siteById.get(topUnattended.siteId);
    const siteName = site?.name ?? topUnattended.siteId;
    const severity = topUnattended.severity
      ? EVENT_SEVERITY_LABEL[topUnattended.severity]
      : SEVERITY_UNSET_LABEL;
    const elapsedLabel = formatElapsed(now.getTime() - new Date(topUnattended.occurredAt).getTime(), {
      unattended: true,
    });
    const initialTitle =
      elapsedLabel === "방금 들어옴" ? "방금 들어온 미조치 이벤트가 있습니다" : `${elapsedLabel} 이벤트가 있습니다`;
    headlineNode = (
      <Headline
        tone="crit"
        tag={`지금 확인 · ${severity.label}`}
        scope={`미조치 ${unattendedEvents.length}건 · 열린 이벤트 ${openEventsCount}건`}
        // 서버 렌더 시점에 고정된 initialTitle 은 SSR·마운트 전 페인트용 스냅샷이다 —
        // 마운트 후 TopUnattendedHeadline 이 60초마다 실제 경과로 갈아탄다(하드코딩된
        // "12분째"가 화면을 열어둔 채로 안 바뀌던 문제, ElapsedTime.tsx 참고).
        title={<TopUnattendedHeadline occurredAt={topUnattended.occurredAt} initialText={initialTitle} />}
        sub={`${siteName} ${humanizeEventType(topUnattended.eventType)} · 담당자가 없는 이벤트입니다`}
        pills={nextPills}
        actions={[
          {
            key: "open-event",
            label: "지금 확인하기",
            href: `/events/${encodeURIComponent(topUnattended.eventKey)}`,
            primary: true,
          },
          ...(site
            ? [{ key: "open-site", label: "현장 열기", href: `/sites/${encodeURIComponent(site.siteId)}` }]
            : []),
        ]}
      />
    );
  } else if (blockedSites.length > 0) {
    const target = blockedSites[0];
    const names = blockedSites.length > 1 ? `${target.name} 외 ${blockedSites.length - 1}곳` : target.name;
    headlineNode = (
      <Headline
        tone="crit"
        tag="조사 필요"
        scope={`등록 현장 ${sites.length}곳`}
        title={`순찰을 시작할 수 없는 현장 ${blockedSites.length}곳`}
        sub={`${names} · 기준 지도를 만들 조사 비행부터 필요합니다`}
        pills={nextPills}
        actions={[
          { key: "open-site", label: "현장 열기", href: `/sites/${encodeURIComponent(target.siteId)}` },
          ...(canIssueMissions
            ? [
                {
                  key: "plan",
                  label: "조사 계획하기",
                  href: `/sites/${encodeURIComponent(target.siteId)}/surveys/new`,
                  primary: true,
                },
              ]
            : []),
        ]}
      />
    );
  } else if (sites.length > 0) {
    headlineNode = (
      <Headline
        tone="neutral"
        tag="확인 대기 없음"
        // "모두 순찰 가능"이라 단언하지 않는다 — 이 분기는 '조사 비행이 필요한 현장이
        // 없다'는 뜻일 뿐, 준비 중·모델 노후·운영 중단 현장이 남아 있을 수 있다.
        // 실제 순찰 가능 대수는 아래 지표 띠가 화이트리스트로 세어 말한다.
        scope={`등록 현장 ${sites.length}곳`}
        title="지금 확인이 필요한 이벤트가 없습니다"
        sub="현장별 최신 상태는 아래 포트폴리오에서 확인하세요."
      />
    );
  }

  return (
    // 화면 이름은 topbar 가 갖는다(스크롤해도 남는 자리) — 여기서 h1 을 또 찍으면
    // 같은 말이 두 번 나오고 본문 첫 화면이 그만큼 밀린다.
    <div className="flex flex-col gap-4 p-4 sm:p-5">
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

      {headlineNode}

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <StatStrip
            items={[
              {
                key: "unattended",
                label: "미조치 이벤트",
                value: eventsResult.ok ? unattendedEvents.length : "—",
                unit: eventsResult.ok ? "건" : undefined,
                tone: eventsResult.ok && unattendedEvents.length > 0 ? "crit" : undefined,
                note: eventsResult.ok ? `열린 이벤트 ${openEventsCount}건 중` : unavailableNote(eventsResult),
                href: eventsResult.ok ? "/events" : undefined,
              },
              {
                key: "sla",
                label: "확인 목표 초과",
                value: eventsResult.ok ? slaBreachedCount : "—",
                unit: eventsResult.ok ? "건" : undefined,
                tone: eventsResult.ok && slaBreachedCount > 0 ? "crit" : undefined,
                note: eventsResult.ok ? "즉시 확인이 필요합니다" : unavailableNote(eventsResult),
                href: eventsResult.ok ? "/events" : undefined,
              },
              {
                key: "patrol",
                label: "순찰 가능 현장",
                value: sitesResult.ok ? `${patrolReadyCount}/${sites.length}` : "—",
                note: sitesResult.ok ? "등록 현장 중" : unavailableNote(sitesResult),
                href: sitesResult.ok ? "/sites" : undefined,
              },
            ]}
          />

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
              <PortfolioTable
                rows={portfolioRows}
                initialQuery={q ?? ""}
                initialSort={normalizePortfolioSort(sort)}
                canPlanSurvey={canIssueMissions}
                meta={
                  missionsResult.ok
                    ? `${sites.length}곳 · 발급 임무 ${missions.length}건`
                    : `${sites.length}곳 · 임무 이력을 불러오지 못했습니다`
                }
              />
            )
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <ProcessingCard
            items={processing.items}
            scopeNote={
              processingSites.length === 0
                ? "훑을 현장이 없습니다"
                : `상위 ${processingSites.length}개 현장 기준`
            }
            unavailableNote={
              processing.unavailable === "absent"
                ? "이 서버에는 사진 처리(재구성) 표면이 없습니다. 처리 결과를 쓰려면 저장소 연결이 필요합니다."
                : processing.unavailable === "failed"
                  ? "처리 작업 목록을 불러오지 못했습니다."
                  : undefined
            }
          />
          <ReobsSuggestions
            items={reobsItems}
            scopeNote={
              recentMissions.length === 0
                ? "변화 탐지를 돌린 임무가 아직 없습니다."
                : `최근 임무 ${recentMissions.length}건 기준입니다.`
            }
            canIssueMissions={canIssueMissions}
          />
        </div>
      </div>
    </div>
  );
}
