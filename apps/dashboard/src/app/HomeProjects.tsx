import Link from "next/link";

import { SiteFootprint } from "@/components/site/SiteFootprint";
import { SITE_STATUS_LABEL, type Tone } from "@/lib/core-api/labels";
import type { SiteView } from "@/lib/core-api/types";
import { formatRelativeKo } from "@/lib/datetime";

export type HomeProjectSort = "recent" | "name" | "attention";

const SORTS: ReadonlyArray<{ key: HomeProjectSort; label: string }> = [
  { key: "recent", label: "최근 갱신순" },
  { key: "name", label: "이름순" },
  { key: "attention", label: "확인할 것 먼저" },
];

const DOT: Record<Tone, string> = {
  neutral: "text-idle-ink",
  progress: "text-mid-ink",
  caution: "text-high-ink",
  positive: "text-safe-ink",
  warning: "text-crit-ink",
};

export function parseHomeProjectSort(value: unknown): HomeProjectSort {
  const first = Array.isArray(value) ? value[0] : value;
  return first === "name" || first === "attention" ? first : "recent";
}

function sortSites(sites: readonly SiteView[], sort: HomeProjectSort, attentionBySite: ReadonlyMap<string, number>): SiteView[] {
  const byRecent = (a: SiteView, b: SiteView) => b.updatedAt.localeCompare(a.updatedAt) || a.name.localeCompare(b.name, "ko");
  const copy = [...sites];
  if (sort === "name") return copy.sort((a, b) => a.name.localeCompare(b.name, "ko") || byRecent(a, b));
  if (sort === "attention") return copy.sort((a, b) => (attentionBySite.get(b.siteId) ?? 0) - (attentionBySite.get(a.siteId) ?? 0) || byRecent(a, b));
  return copy.sort(byRecent);
}

/**
 * 홈의 프로젝트 — 이름·상태·마지막 갱신·확인할 개수만 보이는 한 줄 카드(ADR-KSI-025 D10).
 *
 * 큰 어두운 경계 타일 대신 등록 경계 도형을 작은 표지로만 둔다(D9의 "등록 사실, 영상 아님"은 그대로).
 * "확인 필요" 배지는 홈이 읽은 확인할 일이 있는 프로젝트에만 붙는다(안건 선정이 프로젝트당 한 건이라 개수는 말하지 않는다).
 * 홈의 읽기 범위(분석 검토는 3개 프로젝트)가 제한적이라 배지가 없다고 "없음"이 아니다 — 읽지 못한 곳이 있으면
 * 호출자가 확인할 것 목록 쪽에서 밝힌다.
 */
export function HomeProjects({
  sites,
  attentionBySite,
  sort,
}: {
  sites: readonly SiteView[];
  attentionBySite: ReadonlyMap<string, number>;
  sort: HomeProjectSort;
}) {
  if (sites.length === 0) return null;
  const ordered = sortSites(sites, sort, attentionBySite);
  return (
    <section aria-labelledby="home-projects-heading" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 id="home-projects-heading" className="flex items-baseline gap-2 text-title font-bold tracking-[-0.02em] break-keep">
          프로젝트 <span className="num text-ink-2">{sites.length}</span>
          <Link href="/sites" className="tap-target inline-flex items-center text-caption font-semibold text-accent-text hover:underline">전체 ›</Link>
        </h2>
        <nav aria-label="프로젝트 정렬" className="flex gap-1 rounded-md bg-sunk p-0.5">
          {SORTS.map((option) => (
            <Link
              key={option.key}
              href={option.key === "recent" ? "/" : `/?sort=${option.key}`}
              replace
              scroll={false}
              aria-current={sort === option.key ? "page" : undefined}
              className={`tap-target inline-flex items-center rounded px-2.5 text-caption break-keep ${sort === option.key ? "bg-surface font-bold shadow-sm" : "text-ink-2 hover:text-ink-1"}`}
            >{option.label}</Link>
          ))}
        </nav>
      </div>
      <ul className="grid min-w-0 grid-cols-1 gap-2.5 sm:grid-cols-[repeat(auto-fill,minmax(calc(260px*var(--ui-scale,1)),1fr))]">
        {ordered.map((site) => {
          const encoded = encodeURIComponent(site.siteId);
          const status = SITE_STATUS_LABEL[site.status];
          const needsAttention = (attentionBySite.get(site.siteId) ?? 0) > 0;
          return (
            <li key={site.siteId} className="min-w-0">
              <article className="flex h-full min-w-0 flex-col gap-2 rounded-xl border border-line bg-surface p-3 transition-colors hover:border-line-strong">
                <Link href={`/sites/${encoded}`} className="flex min-w-0 items-center gap-3 rounded-md">
                  <SiteFootprint vertices={site.aoi?.vertices ?? null} siteName={site.name} size="row" decorative />
                  <span className="min-w-0 flex-1 truncate text-body font-bold text-ink-1">{site.name}</span>
                  {needsAttention && (
                    <span className="shrink-0 rounded-full bg-crit-bg px-2 py-0.5 text-micro font-extrabold whitespace-nowrap text-crit-ink">확인 필요</span>
                  )}
                </Link>
                <div className="mt-auto flex items-center justify-between gap-3 text-caption">
                  <p className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 text-ink-2">
                    <span className="inline-flex items-center gap-1.5">
                      <span aria-hidden="true" className={`size-2 rounded-full bg-current ${DOT[status.tone]}`} />
                      {status.label}
                    </span>
                    <span className="text-ink-muted">갱신 {formatRelativeKo(site.updatedAt)}</span>
                  </p>
                  <p className="flex shrink-0 items-center gap-3">
                    <Link href={`/sites/${encoded}/data`} className="tap-target inline-flex items-center text-ink-2 hover:text-ink-1 hover:underline">자료</Link>
                    <Link href={`/sites/${encoded}/analysis`} className="tap-target inline-flex items-center text-ink-2 hover:text-ink-1 hover:underline">분석</Link>
                  </p>
                </div>
              </article>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
