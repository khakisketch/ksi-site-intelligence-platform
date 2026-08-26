import Link from "next/link";

import { StateBadge } from "@/components/ui/StatusBadge";
import type { Tone } from "@/lib/core-api/labels";

export interface HomeSituationItem {
  key: string;
  siteId: string;
  siteName: string;
  statusLabel: string;
  statusTone: Tone;
  title: string;
  detail: string;
  href: string;
  actionLabel: string;
}

/** Home의 준비 카드는 현장 → 상태 → 사유 → 다음 행동 순서로 읽히는 그리드다. */
export function HomeSituationList({
  title,
  description,
  items,
  emptyMessage,
  allHref,
  allLabel,
}: {
  title: string;
  description: string;
  items: HomeSituationItem[];
  emptyMessage: string;
  allHref: string;
  allLabel: string;
}) {
  return (
    <section aria-labelledby="home-situation-heading" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11.5px] font-semibold tracking-[0.04em] text-accent uppercase">현장 준비</p>
          <h2 id="home-situation-heading" className="mt-1 text-[20px] font-bold tracking-[-0.025em] break-keep sm:text-[22px]">
            {title}
          </h2>
          <p className="mt-1 max-w-3xl text-[12.5px] leading-5 break-keep text-ink-2">{description}</p>
        </div>
        <Link href={allHref} className="tap-target text-[12px] font-semibold text-accent hover:underline">
          {allLabel}
        </Link>
      </div>

      {items.length === 0 ? (
        <p className="rounded-lg border border-line bg-surface px-4 py-5 text-[12.5px] break-keep text-ink-2">{emptyMessage}</p>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((item, index) => (
            <li key={item.key} className="flex min-w-0 flex-col rounded-lg border border-line bg-surface p-4 sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Link
                    href={`/sites/${encodeURIComponent(item.siteId)}`}
                    className="min-w-0 truncate text-[13px] font-bold hover:underline"
                  >
                    {item.siteName}
                  </Link>
                  <StateBadge label={item.statusLabel} tone={item.statusTone} />
                </div>
                <span aria-hidden="true" className="num text-[11px] font-semibold text-ink-muted">
                  {String(index + 1).padStart(2, "0")}
                </span>
              </div>
              <p className="mt-4 text-[16px] leading-snug font-bold tracking-[-0.015em] break-keep text-ink-1">{item.title}</p>
              <p className="mt-2 flex-1 text-[12.5px] leading-5 break-keep text-ink-2">{item.detail}</p>
              <Link
                href={item.href}
                className="btn mt-4 w-full justify-between sm:w-fit sm:min-w-44"
              >
                {item.actionLabel}
                <span aria-hidden="true">→</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
