import type { ReactNode } from "react";

import {
  isCompactActionAllowed,
  type ResponsiveAction,
} from "./responsive-actions";

export function ResponsiveActionBoundary({
  action,
  children,
  title = "노트북에서 계속",
  reason = "이 작업은 전체 Operations Console이 필요한 운영·승인 작업입니다.",
  className = "",
}: {
  action: ResponsiveAction;
  children: ReactNode;
  title?: string;
  reason?: string;
  className?: string;
}) {
  if (isCompactActionAllowed(action)) return <>{children}</>;

  return (
    <>
      {/* CSS가 적용되기 전에도 hidden이라 쓰기 행동이 먼저 나타나지 않는다. lg에서만
          contents로 풀어 원래 flex/grid 문맥을 유지한다. */}
      <div className="hidden lg:contents">{children}</div>
      <aside
        data-responsive-action-notice={action}
        className={`rounded-lg border border-line-strong bg-sunk px-3 py-2.5 text-[13px] lg:hidden ${className}`.trim()}
      >
        <div className="flex items-center justify-between gap-2">
          <p className="font-semibold break-keep text-ink-1">{title}</p>
          <span className="shrink-0 rounded border border-line-strong bg-surface px-1.5 py-0.5 text-[10.5px] font-semibold text-ink-muted">
            노트북 필요
          </span>
        </div>
        <p className="mt-0.5 leading-5 break-keep text-ink-2">{reason}</p>
      </aside>
    </>
  );
}
