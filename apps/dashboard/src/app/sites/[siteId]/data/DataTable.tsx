import Link from "next/link";

import { StateBadge } from "@/components/ui/StatusBadge";
import { siteDataHref, type SiteDataScope } from "@/components/nav/site-context";
import { assetLifecycleLabel, capturePeriodTitle, dataKindLabel } from "@/lib/operator-language";
import { firstReadableWindowJob, type PreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";

import { MaterialThumb } from "../spatial-assets/MaterialThumb";
import { inspectionDisplayLabel, inspectionTone } from "../materials/asset-detail";

const HEAD = "px-3 py-2 text-left text-micro font-bold break-keep text-ink-muted";

/**
 * 자료 섹션의 표 — 한 줄이 등록된 자료 한 건이다. 열은 사람이 고르는 순서(무엇인지 → 언제 → 어떤 좌표 → 검사)로
 * 두고, 좁은 화면(768px 미만)에서는 열 머리를 감추고 줄마다 항목 이름을 앞에 붙여 세로로 쌓는다.
 * 선택은 주소(`assetRef`)가 갖는다 — 서버가 상세를 그린다. 썸네일은 이미 준비된 창이 있을 때만 그린다.
 */
export function DataTable({
  siteId, workAreaId, items, selectedAssetRef, scope, jobs, canRead,
}: {
  siteId: string;
  workAreaId: string;
  items: readonly SpatialAssetCatalogItem[];
  selectedAssetRef: string | null;
  scope: SiteDataScope;
  jobs: readonly PreparedWindowJob[];
  canRead: boolean;
}) {
  const thumbs = new Set(items.slice(0, 12).map((item) => item.assetRef));
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full border-collapse text-body">
        <caption className="sr-only">등록된 자료 목록</caption>
        <thead className="max-md:sr-only">
          <tr className="border-b border-line bg-sunk">
            <th scope="col" className={HEAD}>자료</th>
            <th scope="col" className={HEAD}>취득 시점</th>
            <th scope="col" className={HEAD}>좌표 기준</th>
            <th scope="col" className={HEAD}>파일 검사</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const selected = item.assetRef === selectedAssetRef;
            const readable = canRead && thumbs.has(item.assetRef) ? firstReadableWindowJob(jobs, item.assetRef) : null;
            const capture = capturePeriodTitle(item.declared.captureStartedAt, item.declared.captureEndedAt, {
              captureDate: item.declared.captureDate ?? null,
            });
            return (
              <tr
                key={item.assetRef}
                data-asset-row="true"
                data-selected={selected ? "true" : undefined}
                className={`border-b border-line last:border-b-0 hover:bg-sunk max-md:block max-md:px-3 max-md:py-2 ${selected ? "bg-sunk" : ""}`}
              >
                <td className="px-3 py-2 max-md:block max-md:p-0">
                  <Link
                    href={`${siteDataHref(siteId, { ...scope, workAreaId, assetRef: item.assetRef })}#section-inspector`}
                    aria-current={selected ? "true" : undefined}
                    className="tap-target flex min-w-0 items-center gap-3"
                  >
                    {readable?.receipt && (
                      <MaterialThumb siteId={item.siteId} workAreaId={item.workAreaId} jobId={readable.jobId} receipt={readable.receipt} fileName={item.declared.fileName} />
                    )}
                    <span className="min-w-0">
                      <span className="block break-words font-semibold">{dataKindLabel(item.kind)} · v{item.revision}{item.lifecycleState === "SUPERSEDED" && <span className="font-normal text-ink-muted"> · {assetLifecycleLabel(item.lifecycleState)}</span>}</span>
                      <span className="block max-w-[28ch] truncate text-caption text-ink-2" title={item.declared.fileName}>{item.declared.fileName}</span>
                    </span>
                  </Link>
                </td>
                <td className="px-3 py-2 text-caption text-ink-2 max-md:block max-md:p-0 max-md:pt-1">
                  <span className="text-micro text-ink-muted md:hidden">취득 시점 · </span>{capture}
                </td>
                <td className="px-3 py-2 text-caption text-ink-2 max-md:block max-md:p-0">
                  <span className="text-micro text-ink-muted md:hidden">좌표 기준 · </span>{item.inspection.raster?.observedCrsIdentifier ?? "확인 불가"}
                </td>
                <td className="px-3 py-2 max-md:block max-md:p-0 max-md:pt-1">
                  <StateBadge label={inspectionDisplayLabel(item.inspection)} tone={inspectionTone(item.inspection)} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
