import type { ReactNode } from "react";

/**
 * 라벨이 붙은 값 하나 — 건수·면적·부피·시각 같은 계측값.
 *
 * 값이 없으면 호출자가 `value`에 "—"가 아니라 사유를 넘기거나 이 부품을 그리지
 * 않는다. 없는 값을 0으로 바꾸지 않는다(도메인 불변식). 카드가 아니라 `<dl>` 안의
 * 한 쌍이며, 여러 개를 나란히 둘 때 `divide-x`로 가른다.
 */
export function Stat({
  label,
  value,
  unit,
  note,
  className = "",
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  /** 값의 근거·한계 한 줄. */
  note?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`min-w-0 ${className}`}>
      <dt className="text-caption text-ink-2">{label}</dt>
      <dd className="mt-0.5 flex flex-wrap items-baseline gap-x-1">
        <span className="num text-title font-semibold text-ink-1">{value}</span>
        {unit && <span className="text-caption text-ink-2">{unit}</span>}
      </dd>
      {note && <dd className="mt-0.5 text-micro break-keep text-ink-muted">{note}</dd>}
    </div>
  );
}
