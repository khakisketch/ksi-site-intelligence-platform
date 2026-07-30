import Link from "next/link";

import { NAV_ITEMS } from "@/components/nav/nav-items";

export default function MorePage() {
  const overflowItems = NAV_ITEMS.filter((item) => !item.mobile && item.key !== "home");

  return (
    <div className="flex flex-col p-4 sm:p-6">
      <h1 className="mb-4 text-lg font-medium break-keep">더보기</h1>
      <ul className="flex flex-col divide-y divide-black/10 dark:divide-white/10">
        {overflowItems.map((item) => (
          <li key={item.key}>
            <Link
              href={item.href}
              className="flex min-h-11 items-center justify-between py-3 text-sm break-keep"
            >
              {item.label}
              {!item.implemented && <span className="text-foreground/50 text-xs">준비 중</span>}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
