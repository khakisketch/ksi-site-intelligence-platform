import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import type { SiteView } from "@/lib/core-api/types";

export function SiteAreaPicker({
  sites,
  title,
  description,
  section,
}: {
  sites: readonly SiteView[];
  title: string;
  description: string;
  section: "data" | "review-items" | "work" | "reports";
}) {
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <h2 className="text-[17px] font-bold tracking-tight break-keep">{title}</h2>
        <p className="text-[12.5px] break-keep text-ink-2">{description}</p>
      </div>
      {sites.length === 0 ? (
        <EmptyState
          title="등록된 현장이 없습니다"
          description="먼저 현장을 등록하면 이 영역의 데이터와 결과를 현장별로 확인할 수 있습니다."
          action={{ label: "현장 등록", href: "/sites/new" }}
        />
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {sites.map((site) => {
            const status = SITE_STATUS_LABEL[site.status];
            return (
              <li key={site.siteId}>
                <Link
                  href={`/sites/${encodeURIComponent(site.siteId)}?section=${section}`}
                  className="tap-target flex h-full min-h-24 flex-col justify-between gap-3 rounded-lg border border-line bg-surface p-4 hover:border-line-strong hover:bg-sunk"
                >
                  <span className="text-[14px] font-bold break-keep">{site.name}</span>
                  <span className="text-[12px] break-keep text-ink-2">{status.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
