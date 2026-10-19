import Link from "next/link";
import { useId } from "react";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import type { OperatorNextAction } from "@/lib/operator-next-action";
import type { SiteNextAction } from "@/lib/core-api/site-progress";
import type { SiteView } from "@/lib/core-api/types";
import { formatKoreanDate } from "@/lib/datetime";
import { DefaultSiteVisual } from "@/components/site/DefaultSiteVisual";
import { SiteIdentityDetails } from "@/components/site/SiteIdentityDetails";
import { StateBadge } from "@/components/ui/StatusBadge";

/** 현장 목록 한 행의 projection — 카드·밀도표가 같은 값을 쓴다. */
export interface SiteListRow {
  site: SiteView;
  next: SiteNextAction;
  primaryAction: OperatorNextAction | null;
}

/**
 * 데스크톱 2열 갤러리(≥1024px). 작은 썸네일 대신 넓은 타이포 표지를 둔다.
 *
 * 표지는 실제 관측 이미지가 아니라 중립 장식(DefaultSiteVisual: 축·격자·
 * 폴리곤·측정점 없음) + 큰 현장명이다. 씨앗=siteId 라 같은 현장은 늘 같은
 * 모양이다. `기본 표지` 표식은 장식이 실제 모습이 아님을 밝힌다.
 * 이름은 시각적으로 자를 수 있지만(link line-clamp) DOM 문자열은 온전히
 * 두어 스크린리더·검색이 잃지 않는다. 이름은 표지에만 둔다(아래 반복 없음).
 */
export function SiteListDesktopCards({
  rows,
  meta,
  sameNameSites,
}: {
  rows: readonly SiteListRow[];
  /** 서버가 준 실제 건수 — 칩의 전체 수와 헷갈리지 않게 걸린 만큼만 말한다. */
  meta: string;
  sameNameSites: ReadonlySet<string>;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-2">
      <div className="flex items-baseline gap-2 px-1">
        <h2 id={headingId} className="text-[14px] font-bold">
          현장
        </h2>
        <span className="text-[11.5px] text-ink-muted">{meta}</span>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
      {rows.map(({ site, next, primaryAction }) => {
        const statusLabel = SITE_STATUS_LABEL[site.status];
        const nextLabel = primaryAction?.label ?? next.label;
        return (
          <article
            key={site.siteId}
            data-site-card={site.siteId}
            className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-surface"
          >
            <div data-site-cover className="relative h-[180px] overflow-hidden bg-sunk xl:h-[200px]">
              <DefaultSiteVisual seed={site.siteId} className="absolute inset-0 size-full" />
              <span className="absolute top-3 left-3 rounded border border-line bg-surface/90 px-2 py-1 text-[10.5px] font-semibold text-ink-2">
                기본 표지
              </span>
              <Link
                href={`/sites/${encodeURIComponent(site.siteId)}`}
                className="absolute inset-x-0 bottom-0 block p-4 hover:underline xl:p-5"
              >
                <h3 className="line-clamp-3 block text-[22px] leading-snug font-bold tracking-[-0.02em] break-words xl:text-[26px]">
                  {site.name}
                </h3>
              </Link>
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-3 p-4">
              <div className="flex items-center justify-between gap-3">
                <StateBadge label={statusLabel.label} tone={statusLabel.tone} />
                <span className="num text-[11.5px] whitespace-nowrap text-ink-2">
                  최근 갱신 {formatKoreanDate(site.updatedAt)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-md bg-sunk px-3 py-2">
                <p className="min-w-0 text-[12.5px] font-semibold break-keep">{nextLabel}</p>
                <span className={`shrink-0 text-[11.5px] font-bold ${next.actionable ? "text-accent" : "text-ink-muted"}`}>
                  {next.actionable ? "조치 필요" : "상태 확인"}
                </span>
              </div>
              {sameNameSites.has(site.name) && <SiteIdentityDetails site={site} sameName />}
              {/* 표 행과 같은 이유(F08) — 다음 행동 CTA는 현장 상세 헤더가
                  이미 1차 액션으로 보여준다. 카드는 열람 동작 하나만 둔다. */}
              <Link
                href={`/sites/${encodeURIComponent(site.siteId)}`}
                className="btn tap-target justify-center"
              >
                현장 열기
              </Link>
            </div>
          </article>
        );
      })}
      </div>
    </section>
  );
}
