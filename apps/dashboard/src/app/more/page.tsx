import Link from "next/link";

import { NAV_ITEMS } from "@/components/nav/nav-items";
import { NavIcon } from "@/components/nav/NavIcon";
import { StateBadge } from "@/components/ui/StatusBadge";

// TopBar 가 "/more" 경로 h1("더보기") 을 이미 렌더한다(page-title.ts) — 여기서 또 찍지 않는다.
export default function MorePage() {
  const overflowItems = NAV_ITEMS.filter((item) => !item.mobile && item.key !== "home");

  return (
    <div className="flex flex-col gap-3 p-4 sm:p-5">
      <div>
        <h2 className="text-[17px] font-bold tracking-tight">운영 지원</h2>
        <p className="mt-1 text-[12.5px] break-keep text-ink-2">
          운영 지원 범위와 아직 실장비 검증 전인 기능을 안내합니다.
        </p>
      </div>
      <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
        {overflowItems.map((item) => (
          <li key={item.key}>
            <Link
              href={item.href}
              className="tap-target flex items-center gap-3 px-4 py-3 text-sm break-keep hover:bg-sunk"
            >
              <NavIcon name={item.icon} className="size-5 flex-none text-ink-2" />
              <span className="min-w-0 flex-1">
                <span className="block font-semibold">{item.label}</span>
                {item.description && (
                  <span className="mt-0.5 block text-[12px] font-normal text-ink-muted">
                    {item.description}
                  </span>
                )}
              </span>
              {!item.implemented && <StateBadge label="실장비 검증 전" tone="neutral" />}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
