import Link from "next/link";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { formatKoreanDate } from "@/lib/datetime";
import { StateBadge } from "@/components/ui/StatusBadge";
import { SiteIdentityDetails } from "./SiteIdentityDetails";
import { SitePreviewThumb } from "./SitePreviewThumb";
import type { SiteListRow } from "./SiteListDesktopCards";

/** The same site identity and next action in gallery and mobile directory views. */
export function SiteDirectoryCard({ row, sameName }: { row: SiteListRow; sameName: boolean }) {
  const { site, next, primaryAction } = row;
  const status = SITE_STATUS_LABEL[site.status];
  const href = `/sites/${encodeURIComponent(site.siteId)}`;
  return <article data-site-card={site.siteId} className="site-directory-card">
    <SitePreviewThumb siteId={site.siteId} siteName={site.name} size="card" />
    <div className="flex min-w-0 flex-1 flex-col gap-4 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 text-[17px] leading-6 font-semibold tracking-[-0.02em] break-words">
          <Link href={href} className="hover:underline">{site.name}</Link>
        </h3>
        <StateBadge label={status.label} tone={status.tone} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-2">
        <span className="tabular-nums">최근 갱신 {formatKoreanDate(site.updatedAt)}</span>
        {next.actionable && <span className="font-semibold text-high-ink">조치 필요</span>}
      </div>
      <p className="text-[13px] leading-5 text-ink-2">{primaryAction?.label ?? next.label}</p>
      {sameName && <SiteIdentityDetails site={site} sameName />}
      <div className="mt-auto flex flex-wrap items-center gap-x-4 border-t border-line pt-2 text-[12px]">
        <Link href={href} className="tap-target inline-flex items-center gap-2 font-semibold">
          현장 열기
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="size-4"><path d="M4 10h12m-5-5 5 5-5 5" /></svg>
        </Link>
        <Link href={`${href}/spatial-assets`} className="tap-target ml-auto inline-flex items-center text-ink-2 hover:underline">자료</Link>
        <Link href={`${href}/analysis`} className="tap-target inline-flex items-center text-ink-2 hover:underline">결과</Link>
      </div>
    </div>
  </article>;
}
