import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { TableAction, TableRow, TableShell } from "@/components/ui/TableShell";
import { SiteProgressBar } from "@/components/site/SiteProgressBar";
import { SiteListSort } from "@/components/site/SiteListSort";
import { duplicateSiteNames, SiteIdentityDetails } from "@/components/site/SiteIdentityDetails";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError, SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { getSiteRegistrationMode, hasAllPermissions } from "@/lib/core-api/permissions";
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

// 고정폭 합(438) + 간격(50) + 좌우 여백(32) + 현장 열 최소폭(200) = 720.
const COLUMNS = "minmax(200px,1.5fr) 112px 92px 104px 112px 118px";
const MIN_WIDTH = 720;

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

  const [registrationModeResult, canEditSiteResult, canCreateWorkOrderResult] = await Promise.allSettled([
    getSiteRegistrationMode(),
    hasAllPermissions("SITES_WRITE"),
    hasAllPermissions("WORK_ORDERS_WRITE"),
  ]);
  const canRegisterSite = registrationModeResult.status === "fulfilled" && registrationModeResult.value !== "DENIED";
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

  return (
    // 화면 이름은 topbar 가 이미 '현장'을 찍는다 — 본문에서 h1 을 또 찍지 않는다.
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {/* 상태 선택과 검색·정렬을 다른 줄에 둔다. 검색만 제출하며 정렬은 즉시 적용한다. */}
      <div className="flex flex-wrap items-start gap-3">
        {sites !== null && sites.length > 0 && (
          <>
            <details className="w-full rounded-lg border border-line bg-surface lg:hidden">
              <summary className="tap-target flex cursor-pointer items-center justify-between px-3 text-[13px] font-semibold">
                <span>필터·정렬</span>
                <span className="text-[11.5px] font-normal text-ink-muted">
                  {SITE_GROUPS.find((option) => option.key === group)?.label ?? "전체"}
                  {hasFilter ? " · 적용 중" : ""}
                </span>
              </summary>
              <form action="/sites" className="grid gap-2 border-t border-line p-3">
                {status && <input type="hidden" name="status" value={status} />}
                <label className="grid gap-1 text-[12px] font-medium text-ink-2">
                  현장 상태
                  <select key={group} name="group" defaultValue={group} className="input h-11 w-full text-[13px]">
                    {SITE_GROUPS.map((option) => (
                      <option key={option.key} value={option.key}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-[12px] font-medium text-ink-2">
                  현장명·ID 검색
                  <input
                    key={params.q ?? ""}
                    name="q"
                    type="search"
                    defaultValue={params.q ?? ""}
                    placeholder="현장명 또는 ID"
                    className="input h-11 w-full min-w-0 text-[13px]"
                  />
                </label>
                <label className="grid gap-1 text-[12px] font-medium text-ink-2">
                  정렬
                  <select key={sort} name="sort" defaultValue={sort} className="input h-11 w-full text-[13px]">
                    <option value="attention">확인 필요 순</option>
                    <option value="updated">최근 갱신 순</option>
                    <option value="name">이름 순</option>
                  </select>
                </label>
                <div className="flex gap-2">
                  <button type="submit" className="btn btn-primary tap-target flex-1">적용</button>
                  {hasFilter && <Link href="/sites" className="btn tap-target flex-1 justify-center">초기화</Link>}
                </div>
              </form>
            </details>

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
                  className="tap-target inline-flex items-center rounded-md border border-line-strong bg-sunk px-2.5 text-[12.5px] break-keep"
                >
                  {SITE_STATUS_LABEL[status].label} 필터 해제
                </Link>
              )}

                <span className="ml-auto"><RegisterSiteAction canRegisterSite={canRegisterSite} /></span>
              </div>

              <div className="flex flex-wrap items-end justify-between gap-3 border-t border-line pt-3">
              <form action="/sites" className="flex items-end gap-2">
                {group !== "all" && <input type="hidden" name="group" value={group} />}
                {status && <input type="hidden" name="status" value={status} />}
                <input type="hidden" name="sort" value={sort} />
                <label className="grid gap-1 text-[12px] font-medium text-ink-2">
                  현장명·ID 검색
                <input
                  key={params.q ?? ""}
                  name="q"
                  type="search"
                  defaultValue={params.q ?? ""}
                  aria-label="현장 찾기"
                  placeholder="현장명 또는 ID"
                  className="input h-11 w-56 min-w-0 text-[12.5px]"
                />
                </label>
                <button type="submit" className="btn tap-target">검색</button>
                {hasFilter && <Link href="/sites" className="btn tap-target">초기화</Link>}
              </form>
              <SiteListSort sort={sort} query={params.q} group={group === "all" ? undefined : group} status={status} />
              </div>
            </div>
          </>
        )}
        {sites === null && (
          <span className="ml-auto hidden items-center gap-2 lg:flex">
            <RegisterSiteAction canRegisterSite={canRegisterSite} />
          </span>
        )}
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
        <>
          <section className="flex flex-col gap-2 xl:hidden" aria-label="현장 목록">
            <div className="flex items-baseline gap-2 px-1">
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
                  <li key={site.siteId} className="flex gap-3 px-3 py-3.5 sm:px-4 lg:flex-col lg:gap-0 lg:overflow-hidden lg:rounded-lg lg:border lg:border-line lg:bg-surface lg:p-0 lg:only:col-span-2">
                    {/* 대표 이미지 계약이 없으므로 가짜 지도 대신 실제 현장 요약에 폭을 쓴다. */}
                    <div className="flex min-w-0 flex-1 flex-col gap-3 lg:p-4">
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

          <div className="hidden xl:block">
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
                <span>갱신</span>
                <span>다음 할 일</span>
                <span className="text-right">바로가기</span>
              </TableRow>

              {siteRows.map(({ site, next, primaryAction }) => {
                const statusLabel = SITE_STATUS_LABEL[site.status];
                return (
                  <TableRow key={site.siteId} columns={COLUMNS} minWidth={MIN_WIDTH}>
                <div className="flex min-w-0 items-center gap-3">
                  <div className="min-w-0">
                  <Link
                    href={`/sites/${encodeURIComponent(site.siteId)}`}
                    className="block break-words text-[13.5px] font-semibold hover:underline"
                  >
                    {site.name}
                  </Link>
                  {sameNameSites.has(site.name) && <SiteIdentityDetails site={site} sameName />}
                  </div>
                </div>

                <span>
                  <StateBadge label={statusLabel.label} tone={statusLabel.tone} />
                </span>

                <SiteProgressBar status={site.status} />

                <span className="num text-[11.5px] whitespace-nowrap text-ink-2">
                  {formatKoreanDate(site.updatedAt)}
                </span>

                <span
                  className={`text-[11.5px] break-keep ${
                    next.actionable ? "font-semibold" : "text-ink-muted"
                  }`}
                >
                  {primaryAction?.label ?? next.label}
                </span>

                {/* 현장별 다음 행동 CTA는 SiteHeader.tsx가 현장 상세에서 이미 1차
                    액션으로 보여준다(primaryAction/preparationAction) — 표 행에
                    같은 버튼을 또 두면 좁은 열에서 줄바꿈된다(F08). 이 열은
                    열람 동작 하나만 남긴다. */}
                <span className="flex justify-end">
                  <TableAction
                    href={`/sites/${encodeURIComponent(site.siteId)}`}
                    label="현장 열기"
                  />
                </span>
              </TableRow>
                );
              })}
            </TableShell>
          </div>
        </>
      )}
    </div>
  );
}
