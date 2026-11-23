import Link from "next/link";
import type { ReactNode } from "react";

import { Disclosure } from "@/components/ui/Disclosure";
import { formatKoreanDateTime, formatRelativeKo } from "@/lib/datetime";

export type HomeInboxKind = "review" | "approval" | "decision" | "work" | "site" | "setup";

export interface HomeInboxItem {
  key: string;
  kind: HomeInboxKind;
  /** 해야 할 일을 동사로 — 한 줄. */
  title: string;
  siteName: string;
  /** 영역·작업·결과처럼 무엇에 대한 일인지 — 없으면 null. */
  subject: string | null;
  href: string;
  actionLabel: string;
  /** 근거 시점(ISO)과 그 뜻. 화면에는 상대 시각만 두고, 뜻은 툴팁·보조기술에 싣는다 —
   *  원장 필드마다 시점의 뜻이 달라 라벨 없는 시각은 다른 시점으로 오독된다. page.tsx가 출처 분기로 정한다. */
  observedAt: string;
  timeLabel: string;
  /** 접어 두는 기술 참조(분석·영역 ID 등). 있을 때만 키보드로 펼칠 수 있게 둔다. */
  technicalRef?: string;
}

const VISIBLE = 5;

const KIND_STYLE: Record<HomeInboxKind, string> = {
  review: "bg-mid-bg text-mid-ink",
  approval: "bg-high-bg text-high-ink",
  decision: "bg-sunk text-ink-1",
  work: "bg-safe-bg text-safe-ink",
  site: "bg-crit-bg text-crit-ink",
  setup: "bg-idle-bg text-idle-ink",
};

function KindIcon({ kind }: { kind: HomeInboxKind }) {
  const path = {
    review: <><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.2 2.5 2.5 4.5-5" /></>,
    approval: <><path d="M12 3.5 5.5 6v5.2c0 4 2.7 7 6.5 9.3 3.8-2.3 6.5-5.3 6.5-9.3V6L12 3.5Z" /><path d="m9 12 2.2 2.2L15 10.3" /></>,
    decision: <><path d="M6 20.5V4" /><path d="M6 5h11l-2.2 3.5L17 12H6" /></>,
    work: <><rect x="5.5" y="4.5" width="13" height="16" rx="2" /><path d="M9 4.5h6M9 10h6M9 14h4" /></>,
    site: <><path d="M12 20.5s6-5.1 6-10a6 6 0 0 0-12 0c0 4.9 6 10 6 10Z" /><circle cx="12" cy="10.5" r="2.2" /></>,
    setup: <><path d="M12 5v14M5 12h14" /></>,
  }[kind];
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {path}
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

function InboxRow({ item, primary }: { item: HomeInboxItem; primary: boolean }) {
  const exact = `${item.timeLabel} ${formatKoreanDateTime(item.observedAt, { dateStyle: "medium", timeStyle: "short" })}`;
  return (
    <li className="border-t border-line first:border-t-0">
      <article className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2.5 px-3.5 py-3 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
        <span aria-hidden="true" className={`grid size-9 place-items-center rounded-lg ${KIND_STYLE[item.kind]}`}>
          <KindIcon kind={item.kind} />
        </span>
        <div className="min-w-0">
          <h3 className="text-body font-bold break-keep text-ink-1">{item.title}</h3>
          <p className="truncate text-caption text-ink-2">
            {item.siteName}{item.subject ? <> <span aria-hidden="true">·</span> {item.subject}</> : null}
          </p>
          {item.technicalRef && (
            <Disclosure label="식별 상세" className="text-micro text-ink-muted">
              <p className="break-all">{item.technicalRef}</p>
            </Disclosure>
          )}
        </div>
        <div className="col-span-2 flex items-center justify-between gap-3 sm:col-span-1 sm:justify-end">
          <time dateTime={item.observedAt} title={exact} className="num text-micro whitespace-nowrap text-ink-muted">
            <span className="sr-only">{item.timeLabel} </span>{formatRelativeKo(item.observedAt)}
          </time>
          <Link href={item.href} className={`btn btn-sm shrink-0 ${primary ? "btn-primary" : ""}`}>
            {item.actionLabel}
            <ArrowIcon />
          </Link>
        </div>
      </article>
    </li>
  );
}

/**
 * 홈의 첫 영역 — "지금 내가 확인할 것"(ADR-KSI-025 D10).
 *
 * 프로젝트 목록이 아니라 확인할 일의 대기열이다. 제목은 해야 할 일, 프로젝트·영역은 보조이고 행동은 하나다.
 * 대기열은 위에서 아래로 처리하므로 읽기 좋은 폭을 넘기지 않는다(넓은 화면은 호출자가 옆 칸을 프로젝트에 준다).
 * 숫자는 보이는 줄 수와 같다. 읽지 못한 곳이 있으면 `complete=false`로 "N+"를 쓰고, 아무것도 모르면 "—"이며
 * 0이라 말하지 않는다(ADR-KSI-025 D1 unknown-not-0). 5건을 넘으면 나머지는 접어 둔다.
 */
export function HomeInbox({
  items,
  complete,
  notice,
  headerAction,
}: {
  items: readonly HomeInboxItem[];
  /** 포트폴리오를 모두 읽었는가. false면 숫자는 하한이다. */
  complete: boolean;
  /** 읽지 못한 곳 안내 — 목록 맨 아래 한 줄로 둔다. */
  notice?: ReactNode;
  /** 제목 오른쪽의 바로가기(받은 작업함 등). */
  headerAction?: ReactNode;
}) {
  const shown = items.slice(0, VISIBLE);
  const rest = items.slice(VISIBLE);
  const count = items.length === 0 && !complete ? "—" : `${items.length}${complete ? "" : "+"}`;
  return (
    <section aria-labelledby="home-inbox-heading" data-home-inbox="true" className="flex min-w-0 flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="home-inbox-heading" className="flex items-baseline gap-2.5 text-display font-extrabold tracking-[-0.03em] break-keep">
          확인할 것
          <span data-home-inbox-count="true" className="num text-accent-text">{count}</span>
        </h2>
        {headerAction}
      </div>
      <div role="region" aria-label="확인할 것 목록" className="overflow-hidden rounded-xl border border-line bg-surface">
        {items.length > 0 ? (
          <>
            <ul>
              {shown.map((item, index) => <InboxRow key={item.key} item={item} primary={index === 0} />)}
            </ul>
            {rest.length > 0 && (
              <Disclosure label={`외 ${rest.length}건 더 보기`} className="border-t border-line px-3.5 text-caption font-semibold text-ink-2">
                <ul className="-mx-3.5">
                  {rest.map((item) => <InboxRow key={item.key} item={item} primary={false} />)}
                </ul>
              </Disclosure>
            )}
          </>
        ) : (
          <p role="status" className="px-4 py-6 text-center text-body text-ink-2">
            {complete ? "지금 확인할 것이 없습니다" : "확인할 것을 찾지 못했습니다"}
          </p>
        )}
        {notice}
      </div>
    </section>
  );
}
