import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { SiteListControls } from "@/components/site/SiteListControls";
import { SiteListNavLink } from "@/components/site/SiteListNavLink";
import { SiteListCancelBoundary } from "@/components/site/SiteListCancelBoundary";
import { SiteListDesktopCards } from "@/components/site/SiteListDesktopCards";
import { SiteListDenseList } from "@/components/site/SiteListDenseList";
import { SiteListPager } from "@/components/site/SiteListPager";
import { SiteListCreateTile } from "@/components/site/SiteListCreateTile";
import { SiteListView } from "@/components/site/SiteListView";
import { readSiteListView } from "@/components/site/site-list-view.server";
import {
  buildSiteListHref,
  clampPage,
  normalizePageParam,
  paginateRows,
  pageRangeMeta,
  SITE_LIST_CARDS_PER_PAGE,
  SITE_LIST_LIST_PER_PAGE,
} from "@/components/site/site-list-query";
import { duplicateSiteNames, SiteIdentityDetails } from "@/components/site/SiteIdentityDetails";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError, SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import {
  getSiteRegistrationAvailability,
  hasAllPermissions,
} from "@/lib/core-api/permissions";
import { listSitesCached } from "@/lib/core-api/cached";
import {
  SITE_GROUPS,
  normalizeSiteGroup,
  siteGroupStatuses,
  siteNextAction,
} from "@/lib/core-api/site-progress";
import { formatKoreanDate } from "@/lib/datetime";
import { resolveSiteOperatorNextAction } from "@/lib/operator-next-action";
import { SITE_STATUSES, type SiteStatus, type SiteView } from "@/lib/core-api/types";

import { SiteOnboarding } from "./SiteOnboarding";
import { RegisterSiteAction } from "./RegisterSiteAction";

export const metadata = { title: "현장 · KSI" };

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

/** 링크를 유지한 채 한 파라미터만 바꾼다 — 칩을 눌러도 검색어·정렬을 잃지 않는다.
 * 실제 조립은 `site-list-query.ts` 가 맡는다(클라이언트 검색·정렬과 같은 규칙). */
function hrefWith(
  base: { q?: string; status?: string; sort?: string; group?: string },
  patch: Partial<Record<"q" | "status" | "sort" | "group", string | undefined>>,
): string {
  return buildSiteListHref(base, patch);
}



/**
 * 현장 목록 — 데스크톱 비교표와 모바일 현장 카드의 같은 projection.
 *
 * 넓은 화면에서는 여러 현장을 같은 열에서 비교하는 표가 맞다. 그러나 그 표를 폰에
 * 가로 스크롤로 남기면 이름·다음 행동이 서로 떨어져 실제 일을 시작하기 어렵다. 모바일은
 * 같은 사실을 `현장명 → 상태 → 확인할 내용 → 현장 열기` 순서의 카드로 다시 읽는다.
 *
 * 필터는 **링크**다(JS 없이 동작하고, 그대로 공유되며, 뒤로가기가 필터를 되감는다).
 * 시안의 상태 칩 4개는 10개 상태를 낱개로 고르는 대신 운영자가 실제로 묻는 묶음으로
 * 접었다 — 정의는 `site-progress.ts` 가 홈과 공유한다.
 */
export default async function SitesPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string; sort?: string; group?: string; page?: string }>;
}) {
  const params = await searchParams;
  const query = normalizeQuery(params.q);
  // `status` 는 이 화면이 예전에 쓰던 낱개 필터다. UI 에서는 묶음 칩으로 바뀌었지만
  // 저장해 둔 링크를 죽이지 않으려고 계속 받는다 — 대신 눌러서 뗄 수 있는 칩으로 보인다.
  const status = isSiteStatus(params.status) ? params.status : undefined;
  const group = normalizeSiteGroup(params.group);
  const groupStatuses = siteGroupStatuses(group);
  const sort = isSortKey(params.sort) ? params.sort : "attention";
  // 보기 방식은 표현 취향이라 URL에 두지 않는다 — 기능 쿠키로 기억하고
  // 서버가 첫 렌더에 읽는다(깜빡임 없음, 공유·뒤로가기 불변).
  const view = await readSiteListView();

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

  const [registrationResult, canEditSiteResult, canCreateWorkOrderResult] = await Promise.allSettled([
    getSiteRegistrationAvailability(),
    hasAllPermissions("SITES_WRITE"),
    hasAllPermissions("WORK_ORDERS_WRITE"),
  ]);
  // 등록 게이트는 3상태를 한 번만 읽는다 — whoami 실패를 거부로 뭉뚱그리지 않는다.
  const registrationAvailability =
    registrationResult.status === "fulfilled"
      ? registrationResult.value
      : { status: "unavailable" as const };
  const canEditSite = canEditSiteResult.status === "fulfilled" && canEditSiteResult.value;
  const canCreateWorkOrder = canCreateWorkOrderResult.status === "fulfilled" && canCreateWorkOrderResult.value;

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
  const sameNameSites = duplicateSiteNames(sites ?? []);
  const siteRows = visibleSites.map((site) => {
    const next = siteNextAction(site.status);
    const primaryAction = resolveSiteOperatorNextAction(
      site,
      {
        canEditSite,
        canCreateWorkOrder,
      },
      { includeRoutineSurvey: next.survey },
    );
    return {
      site,
      next,
      primaryAction,
    };
  });
  // 데스크톱 페이지네이션 — 모드마다 크기가 달라 각각 계산한다.
  // URL page 하나를 공유하지만 카드 4행·목록 10행 기준으로 따로 자르고
  // 따로 보정한다(한쪽이 끝에 닿아도 다른 쪽 빈 페이지를 만들지 않는다).
  // 폰·태블릿은 전체 목록(siteRows)을 그대로 쓴다.
  const filteredTotal = visibleSites.length;
  const totalCount = sites?.length ?? 0;
  const cardsTotalPages = Math.max(1, Math.ceil(filteredTotal / SITE_LIST_CARDS_PER_PAGE));
  const listTotalPages = Math.max(1, Math.ceil(filteredTotal / SITE_LIST_LIST_PER_PAGE));
  const cardsPage = clampPage(normalizePageParam(params.page), cardsTotalPages);
  const listPage = clampPage(normalizePageParam(params.page), listTotalPages);
  const desktopCards = paginateRows(siteRows, cardsPage, SITE_LIST_CARDS_PER_PAGE);
  const desktopList = paginateRows(siteRows, listPage, SITE_LIST_LIST_PER_PAGE);
  const cardsMeta = pageRangeMeta(filteredTotal, totalCount, cardsPage, SITE_LIST_CARDS_PER_PAGE);
  const listMeta = pageRangeMeta(filteredTotal, totalCount, listPage, SITE_LIST_LIST_PER_PAGE);
  const pagerBase = {
    q: params.q,
    status,
    sort,
    group: group === "all" ? undefined : group,
  };
  const hasRows = siteRows.length > 0;

  return (
    // 화면 이름은 topbar 가 이미 '현장'을 찍는다 — 본문에서 h1 을 또 찍지 않는다.
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {/* 상태 선택과 검색·정렬을 다른 줄에 둔다. 검색은 300ms 디바운스 자동 적용·ENTER 확정, 정렬은 즉시 적용한다. */}
      <div className="flex flex-wrap items-start gap-3">
        {sites !== null && sites.length > 0 && (
          <>
            <details className="hidden w-full rounded-lg border border-line bg-surface sm:block lg:hidden">
              <summary className="tap-target flex cursor-pointer items-center justify-between px-3 text-[13px] font-semibold">
                <span>상태 필터</span>
                <span className="text-[11.5px] font-normal text-ink-muted">
                  {SITE_GROUPS.find((option) => option.key === group)?.label ?? "전체"}
                  {hasFilter ? " · 적용 중" : ""}
                </span>
              </summary>
              <form action="/sites" className="grid gap-2 border-t border-line p-3">
                {params.q && <input type="hidden" name="q" value={params.q} />}
                <input type="hidden" name="sort" value={sort} />
                {status && <input type="hidden" name="status" value={status} />}
                <label className="grid gap-1 text-[12px] font-medium text-ink-2">
                  현장 상태
                  <select key={group} name="group" defaultValue={group} className="input tap-target w-full text-[13px]">
                    {SITE_GROUPS.map((option) => (
                      <option key={option.key} value={option.key}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <div className="flex gap-2">
                  <button type="submit" className="btn btn-primary tap-target flex-1">적용</button>
                  {hasFilter && <SiteListNavLink href="/sites" className="btn tap-target flex-1 justify-center">초기화</SiteListNavLink>}
                </div>
              </form>
            </details>

            <div className="w-full lg:hidden">
              {/* 컨트롤은 리마운트하지 않는다 — 폰 적용 후 요약 포커스를 살린다.
                  묶음·상태 prop 변화는 패널 셀렉트의 key가 따라가고,
                  대기 타이머는 기준 링크 클릭 의도·주소창 대조·popstate가
                  취소하므로 옛 기준으로 새 필터를 되돌리지 못한다. */}
              <SiteListControls
                query={params.q}
                sort={sort}
                group={group === "all" ? undefined : group}
                status={status}
                hasFilter={hasFilter}
                visibleCount={visibleSites.length}
                totalCount={sites.length}
              />
            </div>

            <div className="hidden w-full flex-col gap-3 lg:flex">
              <div className="flex flex-wrap items-center gap-2" role="group" aria-label="현장 상태 필터">
              {SITE_GROUPS.map((option) => {
                const active = option.key === group;
                const count =
                  option.statuses === null
                    ? sites.length
                    : sites.filter((site) => option.statuses.has(site.status)).length;
                if (!active && count === 0) return null;
                return (
                  <SiteListNavLink
                    key={option.key}
                    href={hrefWith(params, { group: option.key === "all" ? undefined : option.key })}
                    current={active}
                    className={`tap-target inline-flex items-center gap-1.5 rounded-md border px-2.5 text-[12.5px] break-keep transition-colors ${
                      active
                        ? "border-line-strong bg-sunk font-bold"
                        : "border-line bg-surface hover:border-line-strong"
                    }`}
                  >
                    {option.label}
                    <span className="num text-[11px] text-ink-muted">{count}</span>
                  </SiteListNavLink>
                );
              })}

              {status && (
                <SiteListNavLink
                  href={hrefWith(params, { status: undefined })}
                  className="tap-target inline-flex items-center rounded-md border border-line-strong bg-sunk px-2.5 text-[12.5px] break-keep"
                >
                  {SITE_STATUS_LABEL[status].label} 필터 해제
                </SiteListNavLink>
              )}

                <span className="ml-auto"><RegisterSiteAction availability={registrationAvailability} /></span>
              </div>

              <SiteListView
                initialView={view}
                toolbar={
                  <SiteListControls
                    query={params.q}
                    sort={sort}
                    group={group === "all" ? undefined : group}
                    status={status}
                    hasFilter={hasFilter}
                    visibleCount={visibleSites.length}
                    totalCount={sites.length}
                    className="min-w-0 flex-1"
                  />
                }
                total={filteredTotal}
                // 걸린 행이 없으면 패널을 비운다 — 아래 EmptyState 하나만 말한다.
                cards={
                  hasRows ? (
                    <div className="w-full max-w-[920px] 2xl:max-w-[1350px]">
                      <SiteListDesktopCards
                        rows={desktopCards}
                        meta={cardsMeta}
                        sameNameSites={sameNameSites}
                        trailing={
                          cardsPage === cardsTotalPages ? (
                            <SiteListCreateTile availability={registrationAvailability} />
                          ) : null
                        }
                      />
                      <SiteListPager page={cardsPage} totalPages={cardsTotalPages} base={pagerBase} />
                    </div>
                  ) : null
                }
                cardsPage={cardsPage}
                cardsSummary={cardsMeta}
                list={
                  hasRows ? (
                    <>
                      <SiteListDenseList
                        rows={desktopList}
                        meta={listMeta}
                        sameNameSites={sameNameSites}
                      />
                      <SiteListPager page={listPage} totalPages={listTotalPages} base={pagerBase} />
                    </>
                  ) : null
                }
                listPage={listPage}
                listSummary={listMeta}
              />
            </div>
          </>
        )}
        {sites === null && (
          <span className="ml-auto hidden items-center gap-2 lg:flex">
            <RegisterSiteAction availability={registrationAvailability} />
          </span>
        )}
      </div>

      {errorMessage !== null ? (
        <ErrorState message={errorMessage} retryable />
      ) : sites !== null && sites.length === 0 ? (
        <SiteOnboarding availability={registrationAvailability} />
      ) : visibleSites.length === 0 ? (
        <SiteListCancelBoundary>
          <EmptyState
            title="조건에 맞는 현장이 없습니다"
            description="검색어나 상태 묶음을 바꿔 다시 확인하세요."
            action={hasFilter ? { label: "필터 초기화", href: "/sites" } : undefined}
          />
        </SiteListCancelBoundary>
      ) : (
        <>
          <section className="flex flex-col gap-2 lg:hidden" aria-label="현장 목록">
            {/* 폰에서는 검색 아래 건수+필터 행이 수를 말하므로 제목 줄을 두지 않는다. */}
            <div className="hidden items-baseline gap-2 px-1 sm:flex">
              <h2 className="text-[14px] font-bold">현장</h2>
              <span className="text-[11.5px] text-ink-muted">
                {sites !== null ? `${siteRows.length} / ${sites.length}곳 표시` : undefined}
              </span>
            </div>
            <ul className="overflow-hidden rounded-lg border border-line bg-surface divide-y divide-line lg:grid lg:grid-cols-2 lg:gap-3 lg:overflow-visible lg:border-0 lg:bg-transparent lg:divide-y-0">
              {siteRows.map(({ site, next, primaryAction }) => {
                const statusLabel = SITE_STATUS_LABEL[site.status];
                const nextLabel = primaryAction?.label ?? next.label;
                return (
                  <li key={site.siteId} className="px-3 py-3.5 sm:px-4 lg:gap-4 lg:overflow-hidden lg:rounded-lg lg:border lg:border-line lg:bg-surface lg:p-4 lg:only:col-span-2">
                    {/* 목록에 미리보기 경로가 없으므로 장식 칸을 두지 않고 실제 현장 요약에 폭을 쓴다. */}
                    <div className="flex min-w-0 flex-1 flex-col gap-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <Link
                            href={`/sites/${encodeURIComponent(site.siteId)}`}
                            className="block text-[14px] font-semibold break-keep hover:underline"
                          >
                            {site.name}
                          </Link>
                           <p className="mt-1 text-[12px] break-keep text-ink-2">
                             최근 갱신 {formatKoreanDate(site.updatedAt)}
                           </p>
                           {sameNameSites.has(site.name) && <SiteIdentityDetails site={site} sameName />}
                        </div>
                        <StateBadge label={statusLabel.label} tone={statusLabel.tone} />
                      </div>
                      <div className="flex items-center justify-between gap-3 rounded-md bg-sunk px-3 py-2">
                        <p className="min-w-0 text-[12.5px] font-semibold break-keep">{nextLabel}</p>
                        <span className={`shrink-0 text-[11.5px] font-bold ${next.actionable ? "text-accent" : "text-ink-muted"}`}>
                          {next.actionable ? "조치 필요" : "상태 확인"}
                        </span>
                      </div>
                      {/* 표 행과 같은 이유(F08) — 다음 행동 CTA는 현장 상세 헤더가
                          이미 1차 액션으로 보여준다. 카드는 열람 동작 하나만 둔다. */}
                      <Link
                        href={`/sites/${encodeURIComponent(site.siteId)}`}
                        className="btn tap-target justify-center"
                      >
                        현장 열기
                      </Link>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
