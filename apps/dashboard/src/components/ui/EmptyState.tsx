import Link from "next/link";

export function EmptyState({
  title,
  description,
  action,
  /** 권한이 없어 행동할 수 없을 때의 사유. 툴팁이 아니라 상시 텍스트로 보여준다. */
  blockedReason,
}: {
  title: string;
  description?: string;
  action?: { label: string; href: string };
  blockedReason?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface px-6 py-12 text-center">
      <p className="text-[15px] font-bold break-keep">{title}</p>
      {description && (
        <p className="max-w-sm text-[13px] break-keep text-ink-2">{description}</p>
      )}
      {action && (
        <Link href={action.href} className="btn btn-primary mt-1">
          {action.label}
        </Link>
      )}
      {/* UX 목표 §3.4 — "어떤 권한이 필요한지 명시(막연한 접근 불가 금지)".
          title 툴팁은 터치 기기에 hover 가 없어 뜨지 않고 키보드로도 도달하지 못한다.
          이 제품의 1급 기기가 태블릿이라 툴팁은 사실상 아무에게도 안 보인다. */}
      {blockedReason && (
        <p className="text-[12.5px] break-keep text-ink-muted">{blockedReason}</p>
      )}
    </div>
  );
}
