import Link from "next/link";

import { siteAreasHref } from "@/components/nav/site-context";

/** 공간 왼쪽 패널의 첫 줄 — 자료 보기와 영역 보기를 오간다. 고른 영역은 두 보기에서 그대로 이어진다. */
export function SpaceViewTabs({ sitePath, siteId, workAreaId }: { sitePath: string; siteId: string; workAreaId: string | null }) {
  const dataHref = workAreaId ? `${sitePath}?workAreaId=${encodeURIComponent(workAreaId)}` : sitePath;
  const tab = (label: string, href: string, current: boolean) => (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className={`tap-target flex grow items-center justify-center rounded-md px-2 text-caption ${current ? "bg-surface font-bold shadow-sm" : "text-ink-2 hover:bg-surface/60"}`}
    >{label}</Link>
  );
  return (
    <nav aria-label="공간 보기" className="flex gap-1 rounded-md bg-sunk p-1">
      {tab("자료", dataHref, false)}
      {tab("영역", siteAreasHref(siteId, workAreaId), true)}
    </nav>
  );
}
