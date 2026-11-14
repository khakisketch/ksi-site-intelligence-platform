import Link from "next/link";

import { SitePreviewThumb } from "@/components/site/SitePreviewThumb";
import { StateBadge } from "@/components/ui/StatusBadge";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import type { SiteView } from "@/lib/core-api/types";

/**
 * 홈의 다른 현장 — 등록된 경계 도형(영상이 있으면 영상)을 앞세운 카드 줄.
 *
 * 확인 목록에 이미 나온 현장은 호출자가 빼고 넘긴다(ADR-KSI-025 D1 중복 방지).
 * 카드는 현장 목록과 같은 표지 문법을 쓴다: 영상이 준비됐으면 영상, 아니면 등록 경계
 * 도형이고 영상·측량·정확도 근거가 아님을 밝힌다. 상태는 배지의 텍스트가 전한다.
 */
export function HomeSiteGrid({ sites }: { sites: readonly SiteView[] }) {
  if (sites.length === 0) return null;
  return (
    <section aria-label="다른 현장 바로가기" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-title font-bold tracking-[-0.02em] break-keep sm:text-display">다른 현장</h2>
        <div className="flex flex-wrap items-center gap-x-4 text-caption font-semibold">
          <Link href="/sites" className="tap-target inline-flex items-center text-accent-text hover:underline">전체 목록</Link>
          <Link href="/field" className="tap-target inline-flex items-center text-ink-2 hover:text-ink-1 hover:underline">작업 목록</Link>
        </div>
      </div>
      <ul className="grid min-w-0 grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-4">
        {sites.map((site) => {
          const encoded = encodeURIComponent(site.siteId);
          const status = SITE_STATUS_LABEL[site.status];
          return (
            <li key={site.siteId} className="min-w-0">
              <article className="flex h-full min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-surface">
                <SitePreviewThumb siteId={site.siteId} siteName={site.name} size="card" footprint={site.aoi?.vertices ?? null} />
                <div className="flex min-w-0 flex-1 flex-col gap-2 p-2.5 sm:p-3">
                  <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-2 gap-y-1.5">
                    <h3 className="min-w-0 text-body font-semibold break-keep sm:text-lead">{site.name}</h3>
                    <StateBadge label={status.label} tone={status.tone} />
                  </div>
                  <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-caption">
                    <Link href={`/sites/${encoded}`} aria-label={`${site.name} 열기`} className="tap-target font-semibold text-accent-text hover:underline">열기</Link>
                    <span aria-hidden="true" className="text-line-strong">·</span>
                    <Link href={`/sites/${encoded}?panel=materials`} className="tap-target text-ink-2 hover:text-ink-1 hover:underline">자료</Link>
                    <span aria-hidden="true" className="text-line-strong">·</span>
                    <Link href={`/sites/${encoded}/analysis`} className="tap-target text-ink-2 hover:text-ink-1 hover:underline">분석</Link>
                  </div>
                </div>
              </article>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
