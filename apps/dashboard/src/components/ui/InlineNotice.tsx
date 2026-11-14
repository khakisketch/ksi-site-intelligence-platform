import type { ReactNode } from "react";

/**
 * 한 줄 상태 안내 — 화면의 주 내용을 밀어내지 않고 사실과 복구 행동을 전한다.
 *
 * 일부 조회 실패·범위 안내처럼 "알아야 하지만 화면의 주제는 아닌" 사실에 쓴다.
 * 페이지 전체가 실패했을 때는 `ErrorState`, 내용이 없을 때는 `EmptyState`다.
 * 뜻은 문장이 전하고 색은 보조다. `crit`·`high`만 의미색을 쓴다.
 */
const TONE = {
  info: "border-line bg-sunk text-ink-2",
  high: "border-high/40 bg-high-bg text-high-ink",
  crit: "border-crit/40 bg-crit-bg text-crit-ink",
} as const;

export function InlineNotice({
  children,
  action,
  tone = "info",
  role = "status",
  className = "",
}: {
  children: ReactNode;
  /** 복구·이동 행동(링크나 단추) — 오른쪽에 붙는다. */
  action?: ReactNode;
  tone?: keyof typeof TONE;
  role?: "status" | "alert" | "note";
  className?: string;
}) {
  return (
    <div
      role={role}
      className={`flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1.5 rounded-md border px-3 py-2 text-caption ${TONE[tone]} ${className}`}
    >
      <div className="min-w-0 flex-1 break-keep">{children}</div>
      {action && <div className="flex shrink-0 items-center gap-2 font-semibold">{action}</div>}
    </div>
  );
}
