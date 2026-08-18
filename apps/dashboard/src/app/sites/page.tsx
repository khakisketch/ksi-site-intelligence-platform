import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { TableAction, TableRow, TableShell } from "@/components/ui/TableShell";
import { SiteProgressBar } from "@/components/site/SiteProgressBar";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError, SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { listEventsCached, listMissionsCached, listSitesCached } from "@/lib/core-api/cached";
import {
  SITE_GROUPS,
  normalizeSiteGroup,
  siteGroupStatuses,
  siteNextAction,
} from "@/lib/core-api/site-progress";
import { isUnattended } from "@/lib/core-api/triage";
import { formatKoreanDate } from "@/lib/datetime";
import { SITE_STATUSES, type SiteStatus, type SiteView } from "@/lib/core-api/types";

import { SiteOnboarding } from "./SiteOnboarding";

type SortKey = "attention" | "updated" | "name";

const ATTENTION_ORDER: Record<SiteStatus, number> = {
  REMAP_REQUIRED: 0,
  UNMAPPED: 1,
  MODEL_STALE: 2,
  SUSPENDED: 3,
  MODEL_VALIDATION: 4,
  MODEL_PROCESSING: 5,
  BASELINE_MAPPING: 6,
  PROVISIONAL_AUTONOMY: 7,
  PATROL_READY: 8,
  PATROL_ACTIVE: 9,
};

// 고정폭 합(688) + 간격(70) + 좌우 여백(32) + 현장 열 최소폭(200) = 990.
const COLUMNS =
  "minmax(200px,1.5fr) 112px 92px 62px 104px 88px 112px 118px";
const MIN_WIDTH = 990;

function isSiteStatus(value: string | undefined): value is SiteStatus {
  return value !== undefined && (SITE_STATUSES as readonly string[]).includes(value);
}

function isSortKey(value: string | undefined): value is SortKey {
  return value === "attention" || value === "updated" || value === "name";
}

function normalizeQuery(value: string | undefined): string {
  return value?.trim().toLocaleLowerCase("ko-KR") ?? "";
}

function sortSites(sites: readonly SiteView[], sort: SortKey): SiteView[] {
  return [...sites].sort((a, b) => {
    if (sort === "name") return a.name.localeCompare(b.name, "ko");
    if (sort === "updated") return b.updatedAt.localeCompare(a.updatedAt);
    const attention = ATTENTION_ORDER[a.status] - ATTENTION_ORDER[b.status];
    return attention !== 0 ? attention : b.updatedAt.localeCompare(a.updatedAt);
  });
}

/** 링크를 유지한 채 한 파라미터만 바꾼다 — 칩을 눌러도 검색어·정렬을 잃지 않는다. */
function hrefWith(
  base: { q?: string; status?: string; sort?: string; group?: string },
  patch: Partial<Record<"q" | "status" | "sort" | "group", string | undefined>>,
): string {
  const params = new URLSearchParams();
  const merged = { ...base, ...patch };
  for (const key of ["q", "status", "sort", "group"] as const) {
    const value = merged[key];
    if (value) params.set(key, value);
  }
  const search = params.toString();
  return search ? `/sites?${search}` : "/sites";
}

/** 권한이 없을 때 사유를 title 툴팁이 아니라 상시 텍스트로 노출한다(터치 기기엔 hover가
 * 없어 툴팁이 아무에게도 안 보인다 — UX 목표 §3.4 "어떤 권한인지 명시"). */
function RegisterSiteAction({ canRegisterSite }: { canRegisterSite: boolean }) {
  if (canRegisterSite) {
    return (
      <Link href="/sites/new" className="btn btn-primary tap-target">
        현장 등록
      </Link>
    );
  }
  return (
    <span className="flex flex-col items-end gap-0.5">
      <span className="btn cursor-not-allowed text-ink-muted" aria-disabled="true">
        현장 등록
      </span>
      <span className="text-[11px] break-keep text-ink-muted">현장 등록 권한이 필요합니다</span>
    </span>
  );
}

/**
 * 현장 목록 — 카드 격자에서 표로(Console v2 §2).
 *
 * 카드는 현장 하나를 보여주는 데는 좋지만 **여러 현장을 비교하는 데는 나쁘다**: 값이
 * 카드마다 다른 자리에 있어서 "어디가 제일 밀렸나"를 눈으로 훑을 수 없다. 이 화면의
 * 질문이 정확히 그것이라 표로 바꾼다(홈 포트폴리오와 같은 뼈대를 쓴다 — 두 화면에서
 * 같은 대상이 다르게 생기면 운영자가 두 번 학습한다).
 *
 * 필터는 **링크**다(JS 없이 동작하고, 그대로 공유되며, 뒤로가기가 필터를 되감는다).
 * 시안의 상태 칩 4개는 10개 상태를 낱개로 고르는 대신 운영자가 실제로 묻는 묶음으로
 * 접었다 — 정의는 `site-progress.ts` 가 홈과 공유한다.
 */
export default async function SitesPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string; sort?: string; group?: string }>;
}) {
  const params = await searchParams;
  const query = normalizeQuery(params.q);
  // `status` 는 이 화면이 예전에 쓰던 낱개 필터다. UI 에서는 묶음 칩으로 바뀌었지만
  // 저장해 둔 링크를 죽이지 않으려고 계속 받는다 — 대신 눌러서 뗄 수 있는 칩으로 보인다.
  const status = isSiteStatus(params.status) ? params.status : undefined;
  const group = normalizeSiteGroup(params.group);
  const groupStatuses = siteGroupStatuses(group);
  const sort = isSortKey(params.sort) ? params.sort : "attention";

  // 데이터 조회는 JSX 생성과 분리한다 — try/catch 안에서 JSX 를 만들면
  // eslint react-hooks/error-boundaries 가 걸린다(렌더는 즉시 실행되지 않아 실제로 못 잡는 에러다).
  let sites: SiteView[] | null = null;
  let errorMessage: string | null = null;
  try {
    sites = await listSitesCached();
  } catch (error) {
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  // 현장별로 개별 조회하면 N+1 이 된다 — 전체를 한 번만 받아 siteId 로 묶는다
  // (홈이 이미 이 패턴을 쓴다. *Cached 라 셸 배지와 같은 스냅샷을 본다).
  const [missionsResult, eventsResult, canRegisterSiteResult] = await Promise.allSettled([
    listMissionsCached(undefined),
    listEventsCached(500),
    hasAllPermissions("SITES_WRITE"),
  ]);
  // rejected 를 빈 배열로 삼키면 "0건"과 "모름"이 같은 화면이 된다 — 조회가 죽었는데
  // 행마다 0 이 찍히면 그건 관측 실패를 사실로 렌더하는 것이다. null 로 남겨 '—' 로 가른다.
  const missions = missionsResult.status === "fulfilled" ? missionsResult.value : null;
  const events = eventsResult.status === "fulfilled" ? eventsResult.value.events : null;
  const canRegisterSite = canRegisterSiteResult.status === "fulfilled" && canRegisterSiteResult.value;
  const canPlanSurvey = await hasAllPermissions("MISSIONS_ISSUE");

  const lastMissionBySite = new Map<string, string>();
  for (const mission of missions ?? []) {
    const previous = lastMissionBySite.get(mission.siteId);
    if (!previous || new Date(mission.issuedAt).getTime() > new Date(previous).getTime()) {
      lastMissionBySite.set(mission.siteId, mission.issuedAt);
    }
  }

  const unattendedBySite = new Map<string, number>();
  for (const event of (events ?? []).filter(isUnattended)) {
    unattendedBySite.set(event.siteId, (unattendedBySite.get(event.siteId) ?? 0) + 1);
  }

  const visibleSites = sites
    ? sortSites(
        sites.filter((site) => {
          const matchesQuery =
            query.length === 0 ||
            site.name.toLocaleLowerCase("ko-KR").includes(query) ||
            site.siteId.toLocaleLowerCase("ko-KR").includes(query);
          const matchesGroup = !groupStatuses || groupStatuses.has(site.status);
          return matchesQuery && matchesGroup && (!status || site.status === status);
        }),
        sort,
      )
    : [];
  const hasFilter = query.length > 0 || status !== undefined || group !== "all" || sort !== "attention";

  return (
    // 화면 이름은 topbar 가 이미 '현장'을 찍는다 — 본문에서 h1 을 또 찍지 않는다.
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {/* 조작줄 — 칩·검색·정렬·등록이 한 줄에 있고, 스크롤해도 표 머리 위에 남는다. */}
      <div className="flex flex-wrap items-center gap-2">
        {sites !== null && sites.length > 0 && (
          <>
            {SITE_GROUPS.map((option) => {
              const active = option.key === group;
              const count =
                option.statuses === null
                  ? sites.length
                  : sites.filter((site) => option.statuses.has(site.status)).length;
              return (
                <Link
                  key={option.key}
                  href={hrefWith(params, { group: option.key === "all" ? undefined : option.key })}
                  aria-current={active ? "true" : undefined}
                  className={`tap-target inline-flex items-center gap-1.5 rounded-md border px-2.5 text-[12.5px] break-keep transition-colors ${
                    active
                      ? "border-line-strong bg-sunk font-bold"
                      : "border-line bg-surface hover:border-line-strong"
                  }`}
                >
                  {option.label}
                  <span className="num text-[11px] text-ink-muted">{count}</span>
                </Link>
              );
            })}

            {status && (
              <Link
                href={hrefWith(params, { status: undefined })}
                className="tap-target inline-flex items-center gap-1.5 rounded-md border border-line-strong bg-sunk px-2.5 text-[12.5px] break-keep"
              >
                지정 상태 · {SITE_STATUS_LABEL[status].label}
                <span aria-hidden="true" className="text-ink-muted">
                  ✕
                </span>
                <span className="sr-only">이 상태 필터 해제</span>
              </Link>
            )}

            <form action="/sites" className="flex items-center gap-2">
              {/* 칩·정렬은 hidden 으로 실어 보낸다 — 검색이 다른 조건을 지우지 않는다. */}
              {group !== "all" && <input type="hidden" name="group" value={group} />}
              {status && <input type="hidden" name="status" value={status} />}
              <input
                name="q"
                type="search"
                defaultValue={params.q ?? ""}
                aria-label="현장 찾기"
                placeholder="현장명 · 현장 ID"
                className="input h-9 w-44 text-[12.5px]"
              />
              <select
                name="sort"
                defaultValue={sort}
                aria-label="정렬 기준"
                className="input h-9 w-32 text-[12.5px]"
              >
                <option value="attention">확인 필요 순</option>
                <option value="updated">최근 갱신 순</option>
                <option value="name">이름 순</option>
              </select>
              <button type="submit" className="btn tap-target">
                적용
              </button>
              {hasFilter && (
                <Link href="/sites" className="btn tap-target">
                  초기화
                </Link>
              )}
            </form>
          </>
        )}
        <span className="ml-auto flex items-center gap-2">
          <RegisterSiteAction canRegisterSite={canRegisterSite} />
        </span>
      </div>

      {errorMessage !== null ? (
        <ErrorState message={errorMessage} retryable />
      ) : sites !== null && sites.length === 0 ? (
        <SiteOnboarding canRegisterSite={canRegisterSite} />
      ) : visibleSites.length === 0 ? (
        <EmptyState
          title="조건에 맞는 현장이 없습니다"
          description="검색어나 상태 묶음을 바꿔 다시 확인하세요."
          action={hasFilter ? { label: "필터 초기화", href: "/sites" } : undefined}
        />
      ) : (
        <TableShell
          title="현장 상태"
          meta={
            sites !== null
              ? `${visibleSites.length} / ${sites.length}곳 표시`
              : undefined
          }
        >
          <TableRow columns={COLUMNS} minWidth={MIN_WIDTH} head>
            <span>현장</span>
            <span>상태</span>
            <span>진행 단계</span>
            <span className="text-right">미조치</span>
            <span>마지막 임무 발급</span>
            <span>갱신</span>
            <span>다음 할 일</span>
            <span className="text-right">바로가기</span>
          </TableRow>

          {visibleSites.map((site) => {
            const statusLabel = SITE_STATUS_LABEL[site.status];
            const next = siteNextAction(site.status);
            const unattended = events === null ? null : (unattendedBySite.get(site.siteId) ?? 0);
            const lastMission = lastMissionBySite.get(site.siteId) ?? null;

            return (
              <TableRow key={site.siteId} columns={COLUMNS} minWidth={MIN_WIDTH}>
                <span className="min-w-0">
                  <Link
                    href={`/sites/${encodeURIComponent(site.siteId)}`}
                    className="block truncate text-[13.5px] font-semibold hover:underline"
                  >
                    {site.name}
                  </Link>
                  <span className="num block truncate text-[11px] text-ink-muted">{site.siteId}</span>
                </span>

                <span>
                  <StateBadge label={statusLabel.label} tone={statusLabel.tone} />
                </span>

                <SiteProgressBar status={site.status} />

                <span
                  className={`num text-right text-[12px] font-bold ${
                    (unattended ?? 0) > 0 ? "text-crit" : "text-ink-2"
                  }`}
                >
                  {unattended ?? "—"}
                </span>

                {/* "마지막 조사"가 아니라 **발급**이다 — 이 목록만으로는 그 비행이 실제로
                    끝났는지 알 수 없다(홈 포트폴리오와 같은 규칙). */}
                <span className="num text-[11.5px] whitespace-nowrap text-ink-2">
                  {lastMission ? (
                    formatKoreanDate(lastMission)
                  ) : missions === null ? (
                    <span className="text-ink-muted">—</span>
                  ) : (
                    <span className="text-ink-muted">발급 없음</span>
                  )}
                </span>

                <span className="num text-[11.5px] whitespace-nowrap text-ink-2">
                  {formatKoreanDate(site.updatedAt)}
                </span>

                <span
                  className={`text-[11.5px] break-keep ${
                    next.actionable ? "font-semibold" : "text-ink-muted"
                  }`}
                >
                  {next.label}
                </span>

                <span className="flex justify-end gap-1.5">
                  {next.survey && canPlanSurvey && (
                    <TableAction
                      href={`/sites/${encodeURIComponent(site.siteId)}/surveys/new`}
                      label="조사"
                      primary
                    />
                  )}
                  <TableAction
                    href={`/world?siteId=${encodeURIComponent(site.siteId)}`}
                    label="World"
                  />
                </span>
              </TableRow>
            );
          })}
        </TableShell>
      )}
    </div>
  );
}
