import type { ReactNode } from "react";

/**
 * 제목줄과 본문을 가진 면 — 서로 다른 대상이나 결정을 가를 때만 쓴다.
 *
 * 숫자 하나마다 카드를 씌우지 않는다(MASTER.md). 패널 안에 패널을 넣지 않고,
 * 안쪽 구획은 `divide-y`나 여백으로 나눈다. `flush`는 표·목록처럼 본문이 면의
 * 가장자리까지 가야 할 때 쓴다.
 */
export function Panel({
  title,
  description,
  actions,
  children,
  flush = false,
  headingLevel = 2,
  id,
  className = "",
}: {
  title?: ReactNode;
  description?: ReactNode;
  /** 제목줄 오른쪽 행동. */
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  headingLevel?: 2 | 3 | 4;
  /** 제목 요소 id — 바깥에서 aria-labelledby로 이을 때. */
  id?: string;
  className?: string;
}) {
  const Heading = `h${headingLevel}` as "h2" | "h3" | "h4";
  return (
    <section className={`min-w-0 overflow-hidden rounded-lg border border-line bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            {title && <Heading id={id} className="text-lead font-semibold break-keep">{title}</Heading>}
            {description && <p className="mt-0.5 text-caption break-keep text-ink-2">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={flush ? "min-w-0" : "min-w-0 p-4"}>{children}</div>
    </section>
  );
}
