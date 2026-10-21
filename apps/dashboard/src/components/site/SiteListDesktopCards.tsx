import Link from "next/link";
import { useId, type ReactNode } from "react";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import type { OperatorNextAction } from "@/lib/operator-next-action";
import type { SiteNextAction } from "@/lib/core-api/site-progress";
import type { SiteView } from "@/lib/core-api/types";
import { formatKoreanDate } from "@/lib/datetime";
import { SiteIdentityDetails } from "@/components/site/SiteIdentityDetails";
import { StateBadge } from "@/components/ui/StatusBadge";

/** 현장 목록 한 행의 projection — 카드·밀도표가 같은 값을 쓴다. */
export interface SiteListRow {
  site: SiteView;
  next: SiteNextAction;
  primaryAction: OperatorNextAction | null;
}

/**
 * 데스크톱 갤러리(≥1024px) — 장식 표지 없는 간결 텍스트 카드의 격자.
 *
 * 현장별 실제 관측 미리보기를 보여주는 계약이 목록에 없으므로(ADR-KSI-025 D7)
 * 큰 표지·대체 그림 칸을 두지 않는다. 현장명·실제 상태·갱신일·다음 할 일이
 * 카드의 전부이며, 씨앗 장식·측량처럼 보이는 도형은 쓰지 않는다.
 *
 * 칸은 최대 폭을 제한한 2열/아주 넓은 화면 3열이다. 본문 높이는 자연 그대로
 * 두고 버튼 줄만 아래에 맞춘다(mt-auto).
 */
export function SiteListDesktopCards({
  rows,
  meta,
  sameNameSites,
  trailing,
}: {
  rows: readonly SiteListRow[];
  /** 서버가 준 실제 건수 — 칩의 전체 수와 헷갈리지 않게 걸린 만큼만 말한다. */
  meta: string;
  sameNameSites: ReadonlySet<string>;
  /** 마지막 줄 유틸리티(새 현장 추가) — 개수·정렬·페이지 계산 밖이다. */
  trailing?: ReactNode;
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
      <div className="grid w-full max-w-[920px] gap-3 lg:grid-cols-2 2xl:max-w-[1350px] 2xl:grid-cols-3">
      {rows.map(({ site, next, primaryAction }) => {
        const statusLabel = SITE_STATUS_LABEL[site.status];
        const nextLabel = primaryAction?.label ?? next.label;
        return (
          <article
            key={site.siteId}
            data-site-card={site.siteId}
            className="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-surface p-4"
          >
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex items-start justify-between gap-3">
                <h3 className="min-w-0 flex-1 text-[17px] leading-snug font-bold tracking-[-0.015em] break-words">
                  <Link
                    href={`/sites/${encodeURIComponent(site.siteId)}`}
                    className="hover:underline"
                  >
                    {site.name}
                  </Link>
                </h3>
                <StateBadge label={statusLabel.label} tone={statusLabel.tone} />
              </div>
              <p className="num text-[11.5px] text-ink-2">
                최근 갱신 {formatKoreanDate(site.updatedAt)}
              </p>
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
              className="btn tap-target mt-auto justify-center"
            >
              현장 열기
            </Link>
          </article>
        );
      })}
      {trailing}
      </div>
    </section>
  );
}
