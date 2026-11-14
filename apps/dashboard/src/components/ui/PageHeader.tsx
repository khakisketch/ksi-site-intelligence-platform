import type { ReactNode } from "react";

/**
 * 목록·양식 화면의 머리 — 제목, 한 줄 설명, 주 행동.
 *
 * 상단바가 이미 같은 이름을 보여 주는 화면에서는 `title`이 화면의 질문을 말하게
 * 한다(같은 낱말을 두 번 쓰지 않는다). 주 행동은 하나만 `btn-primary`로 둔다.
 * `.console-page-heading` 리듬을 그대로 쓴다.
 */
export function PageHeader({
  title,
  description,
  actions,
  headingLevel = 1,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  headingLevel?: 1 | 2;
  id?: string;
}) {
  const Heading = `h${headingLevel}` as "h1" | "h2";
  return (
    <header className="console-page-heading">
      <div className="min-w-0">
        <Heading id={id} className="console-page-title break-keep">{title}</Heading>
        {description && <p className="console-page-description break-keep">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
