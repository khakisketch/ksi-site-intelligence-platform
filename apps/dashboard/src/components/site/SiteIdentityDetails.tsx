import type { SiteView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";

export function duplicateSiteNames(sites: readonly Pick<SiteView, "name">[]): Set<string> {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const site of sites) {
    if (seen.has(site.name)) duplicates.add(site.name);
    seen.add(site.name);
  }
  return duplicates;
}

/** Same-name Sites use genuine registration context; full opaque identity stays inspectable. */
export function SiteIdentityDetails({ site, sameName = false }: {
  site: Pick<SiteView, "siteId" | "registeredAt">;
  sameName?: boolean;
}) {
  return <div className="min-w-0 text-[12px] text-ink-2">
    {sameName && <p className="mt-1 break-words">같은 이름의 현장 · 등록 {formatKoreanDateTime(site.registeredAt, { dateStyle: "medium", timeStyle: "medium" })}</p>}
    <details><summary className="tap-target cursor-pointer">현장 식별 정보</summary><p className="break-all font-mono">{site.siteId}</p></details>
  </div>;
}
