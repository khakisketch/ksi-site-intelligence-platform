import Link from "next/link";

import { NAV_ITEMS } from "@/components/nav/nav-items";
import { StateBadge } from "@/components/ui/StatusBadge";

// TopBar 가 "/more" 경로 h1("더보기") 을 이미 렌더한다(page-title.ts) — 여기서 또 찍지 않는다.
export default function MorePage() {
  const overflowItems = NAV_ITEMS.filter((item) => !item.mobile && item.key !== "home");

  return (
    <div className="p-4 sm:p-5">
      <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
        {overflowItems.map((item) => (
          <li key={item.key}>
            <Link
              href={item.href}
              className="tap-target flex items-center justify-between gap-2 px-4 py-3 text-sm break-keep hover:bg-sunk"
            >
              {item.label}
              {!item.implemented && <StateBadge label="준비 중" tone="neutral" />}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
