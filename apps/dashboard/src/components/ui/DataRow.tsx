import type { ReactNode } from "react";

/**
 * 목록의 한 행 — 제목, 한 줄 메타, 상태, 행동을 같은 자리에 둔다.
 *
 * 화면마다 행 구조가 다르면 운영자가 목록마다 "상태가 어디 있지"를 다시 찾는다.
 * 값이 없는 메타는 넘기지 않는다 — "미정·미배정"으로 줄을 채우지 않는다.
 * 넓은 화면에서는 한 줄, 좁은 화면에서는 제목·메타 아래로 상태·행동이 내려간다.
 * `<ul>`/`<ol>` 안에서 쓴다.
 */
export function DataRow({
  title,
  meta,
  status,
  actions,
  leading,
  className = "",
}: {
  title: ReactNode;
  /** 보조 사실들 — 가운뎃점으로 이어 한 줄로 둔다. 빈 값은 걸러진다. */
  meta?: ReadonlyArray<ReactNode | null | undefined | false>;
  status?: ReactNode;
  actions?: ReactNode;
  /** 썸네일·표식 등 앞쪽 고정 요소. */
  leading?: ReactNode;
  className?: string;
}) {
  const facts = (meta ?? []).filter((item) => item !== null && item !== undefined && item !== false && item !== "");
  return (
    <li className={`flex min-w-0 flex-col gap-x-4 gap-y-2 px-4 py-3 sm:flex-row sm:items-center ${className}`}>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {leading && <div className="flex-none">{leading}</div>}
        <div className="min-w-0 flex-1">
          <div className="text-lead font-semibold break-keep">{title}</div>
          {facts.length > 0 && (
            <p className="mt-0.5 flex min-w-0 flex-wrap gap-x-1.5 text-caption text-ink-2">
              {facts.map((item, index) => (
                <span key={index} className="min-w-0 break-keep">
                  {index > 0 && <span aria-hidden="true" className="mr-1.5 text-ink-muted">·</span>}
                  {item}
                </span>
              ))}
            </p>
          )}
        </div>
      </div>
      {(status || actions) && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
          {status}
          {actions}
        </div>
      )}
    </li>
  );
}
