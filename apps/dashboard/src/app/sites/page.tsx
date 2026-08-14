import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { SiteCard } from "@/components/site/SiteCard";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError, SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { listMissionsCached, listSitesCached } from "@/lib/core-api/cached";
import { formatKoreanDate } from "@/lib/datetime";
import { SITE_STATUSES, type SiteStatus, type SiteView } from "@/lib/core-api/types";

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

/** 권한이 없을 때 사유를 title 툴팁이 아니라 상시 텍스트로 노출한다(터치 기기엔 hover가
 * 없어 툴팁이 아무에게도 안 보인다 — UX 목표 §3.4 "어떤 권한인지 명시"). */
function RegisterSiteAction({ canRegisterSite }: { canRegisterSite: boolean }) {
  if (canRegisterSite) {
    return (
      <Link href="/sites/new" className="btn btn-primary">
        현장 등록
      </Link>
    );
  }
  return (
    <div className="flex flex-col items-end gap-1">
      <span className="btn cursor-not-allowed text-ink-muted" aria-disabled="true">
        현장 등록
      </span>
      <span className="text-[12px] break-keep text-ink-muted">현장 등록 권한이 필요합니다</span>
    </div>
  );
}

export default async function SitesPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string; sort?: string }>;
}) {
  const params = await searchParams;
  const query = normalizeQuery(params.q);
  const status = isSiteStatus(params.status) ? params.status : undefined;
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

  // 카드 하단 '발급 임무' 사실은 현장별로 개별 조회하면 N+1 이 된다 — 전체 임무를 한 번만
  // 받아 클라이언트에서 siteId 로 묶는다(홈이 이미 이 패턴을 쓴다).
  const [missionsResult, canRegisterSiteResult] = await Promise.allSettled([
    listMissionsCached(undefined),
    hasAllPermissions("SITES_WRITE"),
  ]);
  // rejected 를 빈 배열로 삼키면 "임무 0건"과 "모름"이 같은 화면이 된다 — 조회가 죽었는데
  // 카드마다 '발급 임무 0건'이 찍히면 그건 관측 실패를 사실로 렌더하는 것이다.
  // null 로 남겨 표시 단계에서 '—'로 갈라낸다(홈이 이미 이 규칙을 쓴다).
  const missions = missionsResult.status === "fulfilled" ? missionsResult.value : null;
  const canRegisterSite = canRegisterSiteResult.status === "fulfilled" && canRegisterSiteResult.value;

  const missionCountBySite = (missions ?? []).reduce<Record<string, number>>((acc, mission) => {
    acc[mission.siteId] = (acc[mission.siteId] ?? 0) + 1;
    return acc;
  }, {});

  const visibleSites = sites
    ? sortSites(
        sites.filter((site) => {
          const matchesQuery =
            query.length === 0 ||
            site.name.toLocaleLowerCase("ko-KR").includes(query) ||
            site.siteId.toLocaleLowerCase("ko-KR").includes(query);
          return matchesQuery && (!status || site.status === status);
        }),
        sort,
      )
    : [];
  const hasFilter = query.length > 0 || status !== undefined || sort !== "attention";

  return (
    // 화면 이름은 topbar 가 이미 '현장'을 찍는다 — 본문에서 h1 을 또 찍지 않는다.
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-[15px] font-bold tracking-tight break-keep">현장 상태</p>
          <p className="num mt-0.5 text-[12.5px] break-keep text-ink-2" aria-live="polite">
            {sites !== null ? `${visibleSites.length} / ${sites.length}곳 표시` : ""}
          </p>
        </div>
        {/* 등록 동선은 목록 상태와 무관하게 상시 노출(UX 목표 §2 "현장 상태 확인" 예산과 별개). */}
        <RegisterSiteAction canRegisterSite={canRegisterSite} />
      </div>

      {sites !== null && sites.length > 0 && (
        <form action="/sites" className="grid grid-cols-1 gap-3 rounded-lg border border-line bg-surface p-3 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:items-end">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-semibold break-keep text-ink-2">현장 찾기</span>
            <input
              name="q"
              type="search"
              defaultValue={params.q ?? ""}
              className="input"
              placeholder="현장명 또는 현장 ID"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-semibold break-keep text-ink-2">상태</span>
            <select name="status" defaultValue={status ?? ""} className="input min-w-36">
              <option value="">모든 상태</option>
              {SITE_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {SITE_STATUS_LABEL[value].label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-semibold break-keep text-ink-2">정렬</span>
            <select name="sort" defaultValue={sort} className="input min-w-32">
              <option value="attention">확인 필요 순</option>
              <option value="updated">최근 갱신 순</option>
              <option value="name">이름 순</option>
            </select>
          </label>
          <div className="flex gap-2">
            <button type="submit" className="btn btn-primary flex-1 sm:flex-none">
              적용
            </button>
            {hasFilter && (
              <Link href="/sites" className="btn flex-1 sm:flex-none">
                초기화
              </Link>
            )}
          </div>
        </form>
      )}

      {errorMessage !== null ? (
        <ErrorState message={errorMessage} />
      ) : sites !== null && sites.length === 0 ? (
        <EmptyState
          title="아직 등록된 현장이 없습니다"
          action={canRegisterSite ? { label: "현장 등록", href: "/sites/new" } : undefined}
          blockedReason={
            canRegisterSite ? undefined : "현장 등록은 현장 등록 권한을 가진 계정만 할 수 있습니다."
          }
        />
      ) : visibleSites.length === 0 ? (
        <EmptyState
          title="조건에 맞는 현장이 없습니다"
          description="검색어 또는 상태 필터를 바꿔 다시 확인하세요."
          action={hasFilter ? { label: "필터 초기화", href: "/sites" } : undefined}
        />
      ) : (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(238px,1fr))] gap-3">
          {visibleSites.map((site) => (
            <SiteCard
              key={site.siteId}
              site={site}
              facts={[
                {
                  key: "등록",
                  value: formatKoreanDate(site.registeredAt),
                  numeric: true,
                },
                {
                  key: "갱신",
                  value: formatKoreanDate(site.updatedAt),
                  numeric: true,
                },
                {
                  key: "발급 임무",
                  value: missions === null ? "—" : `${missionCountBySite[site.siteId] ?? 0}건`,
                  numeric: true,
                },
              ]}
            />
          ))}
        </div>
      )}
    </div>
  );
}
