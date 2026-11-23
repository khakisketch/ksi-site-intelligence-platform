import Link from "next/link";

import { formatKoreanDateTime, formatRelativeKo } from "@/lib/datetime";

export interface HomeRecentUpdateView {
  key: string;
  siteName: string;
  /** 소식의 종류(새 결과·최근 관측·현재 등록 상태). */
  label: string;
  title: string;
  href: string;
  /** 근거 시점(ISO)과 그 뜻 — 화면에는 상대 시각만, 뜻은 툴팁에 싣는다. */
  observedAt: string;
  timeLabel: string;
}

/**
 * 확인할 일이 없는 프로젝트의 최근 소식 — 한 줄씩, 최대 몇 건만(ADR-KSI-025 D4의 의미·중복 제외는 그대로).
 * 확인할 일 목록과 프로젝트 카드가 말하지 않는 "최근에 무슨 일이 있었나"만 남기고, 설명 문단과 이미지는 두지 않는다.
 */
export function HomeRecentUpdates({ items }: { items: readonly HomeRecentUpdateView[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="home-recent-updates" className="flex min-w-0 flex-col gap-2">
      <h2 id="home-recent-updates" className="text-lead font-bold tracking-[-0.01em]">최근 소식</h2>
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {items.map((item) => (
          <li key={item.key}>
            <Link
              href={item.href}
              aria-label={`${item.siteName}, ${item.label}, ${item.title}`}
              className="flex min-w-0 items-center gap-3 px-3.5 py-2.5 text-caption transition-colors hover:bg-page focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
            >
              <span className="shrink-0 rounded-full bg-sunk px-2 py-0.5 text-micro font-bold text-ink-2">{item.label}</span>
              <span className="min-w-0 flex-1 truncate text-ink-1"><span className="font-semibold">{item.siteName}</span> <span aria-hidden="true">·</span> {item.title}</span>
              <time
                dateTime={item.observedAt}
                title={`${item.timeLabel} ${formatKoreanDateTime(item.observedAt, { dateStyle: "medium", timeStyle: "short" })}`}
                className="num shrink-0 text-micro text-ink-muted"
              >{formatRelativeKo(item.observedAt)}</time>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
