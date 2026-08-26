import Link from "next/link";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import type { ResponsiveAction } from "@/components/responsive/responsive-actions";

export function EmptyState({
  title,
  description,
  action,
  compact = false,
  inline = false,
  /** 권한이 없어 행동할 수 없을 때의 사유. 툴팁이 아니라 상시 텍스트로 보여준다. */
  blockedReason,
}: {
  title: string;
  description?: string;
  action?: {
    label: string;
    href: string;
    responsiveAction?: ResponsiveAction;
    compactReason?: string;
    desktopOnly?: boolean;
  };
  /** 목록·작업공간 안의 빈 상태는 페이지 전체 빈 상태보다 낮은 밀도로 표현한다. */
  compact?: boolean;
  /** 넓은 화면의 전역 대기열에서는 설명과 복구 행동을 한 줄 흐름으로 묶는다. */
  inline?: boolean;
  blockedReason?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface px-6 text-center ${
        compact ? "py-6" : "py-12"
      } ${inline ? "sm:flex-row sm:justify-between sm:text-left" : ""}`}
    >
      <div className={inline ? "min-w-0" : undefined}>
        <p className="text-[15px] font-bold break-keep">{title}</p>
        {description && (
          <p className={`text-[13px] break-keep text-ink-2 ${inline ? "mt-1 max-w-2xl" : "max-w-sm"}`}>
            {description}
          </p>
        )}
      </div>
      {action &&
        (action.desktopOnly ? (
          <Link href={action.href} className={`btn btn-primary mt-1 hidden lg:inline-flex ${inline ? "lg:mt-0 lg:shrink-0" : ""}`}>
            {action.label}
          </Link>
        ) : action.responsiveAction ? (
          <ResponsiveActionBoundary
            action={action.responsiveAction}
            reason={action.compactReason}
            className="mt-1 max-w-sm"
          >
            <Link href={action.href} className="btn btn-primary mt-1">
              {action.label}
            </Link>
          </ResponsiveActionBoundary>
        ) : (
          <Link href={action.href} className={`btn btn-primary mt-1 ${inline ? "sm:mt-0 sm:shrink-0" : ""}`}>
            {action.label}
          </Link>
        ))}
      {/* UX 목표 §3.4 — "어떤 권한이 필요한지 명시(막연한 접근 불가 금지)".
          title 툴팁은 터치 기기에 hover 가 없어 뜨지 않고 키보드로도 도달하지 못한다.
          이 제품의 1급 기기가 태블릿이라 툴팁은 사실상 아무에게도 안 보인다. */}
      {blockedReason && (
        <p className="text-[12.5px] break-keep text-ink-muted">{blockedReason}</p>
      )}
    </div>
  );
}
