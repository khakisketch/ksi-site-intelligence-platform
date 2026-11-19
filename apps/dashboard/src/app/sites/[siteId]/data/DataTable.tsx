import Link from "next/link";

import { StateBadge } from "@/components/ui/StatusBadge";
import { assignCrsSwatches, normalizeCrs, summarizeAreaDsmCrs } from "@/lib/crs-match";
import { isAnalysisCrs } from "@/lib/geo/known-crs";
import { crsName } from "@/lib/measurement-profile";
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
/** 좌표계를 색 막대와 이름으로 보인다. 색은 이 표 안에서만 의미가 있다(같은 색끼리만 비교된다). */
function CrsSwatch({ swatch }: { swatch: number | undefined }) {
  return <span aria-hidden="true" className="inline-block h-3 w-3 shrink-0 rounded-[3px]" style={{ background: swatch ? `var(--crs-${swatch})` : "var(--idle)" }} />;
}

/**
 * 표 위 한 줄 요약 — 이 구역의 DSM이 몇 가지 좌표계로 섞여 있는지 막대와 범례로 보인다.
 * 표시만 한다. 비교·체적 허용은 Core가 같은 좌표계인지 다시 확인한다.
 */
function CrsSummary({ items, partial, swatches }: { items: readonly SpatialAssetCatalogItem[]; partial: boolean; swatches: Map<string, number> }) {
  const summary = summarizeAreaDsmCrs(items, partial);
  if (summary.total === 0) return null;
  const single = summary.groups.length === 1 ? summary.groups[0]! : null;
  const hint = single
    ? isAnalysisCrs(single.crs) ? "모두 같은 좌표계라 서로 비교할 수 있습니다." : "분석에 쓰지 않는 좌표계입니다. 보기만 됩니다."
    : "비교·체적은 같은 색끼리만 됩니다.";
  return (
    <div data-crs-summary={single ? "single" : "mixed"} className="flex flex-col gap-2 border-b border-line px-3 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="font-bold">DSM {summary.total}건 · 좌표계 {summary.groups.length}가지</p>
        <div aria-hidden="true" className="flex h-2.5 min-w-[140px] max-w-[320px] flex-1 overflow-hidden rounded-full bg-sunk">
          {summary.groups.map((group) => <i key={group.crs} className="block h-full" style={{ flex: group.count, background: swatches.has(group.crs) ? `var(--crs-${swatches.get(group.crs)})` : "var(--idle)" }} />)}
        </div>
      </div>
      <ul aria-label="좌표계별 DSM" className="flex flex-wrap gap-x-4 gap-y-1 text-caption text-ink-2">
        {summary.groups.map((group) => (
          <li key={group.crs} className="inline-flex items-center gap-1.5">
            <CrsSwatch swatch={swatches.get(group.crs)} />
            {crsName(group.crs) ?? group.crs} {group.count}건{!isAnalysisCrs(group.crs) && <span className="text-ink-muted"> · 분석 안 함</span>}
          </li>
        ))}
      </ul>
      <p className="text-caption text-ink-muted">{hint}{summary.truncated && " 이 페이지의 자료 기준입니다."}</p>
    </div>
  );
}

export function DataTable({
  siteId, workAreaId, items, selectedAssetRef, scope, jobs, canRead, summaryItems, partial = false,
}: {
  siteId: string;
  workAreaId: string;
  items: readonly SpatialAssetCatalogItem[];
  selectedAssetRef: string | null;
  scope: SiteDataScope;
  jobs: readonly PreparedWindowJob[];
  canRead: boolean;
  /** 요약은 검색·필터와 무관하게 이 페이지의 전체 자료로 계산한다. 주지 않으면 items를 쓴다. */
  summaryItems?: readonly SpatialAssetCatalogItem[];
  /** 목록이 일부 페이지다(다음 페이지가 있거나 이전 페이지에서 이어짐). */
  partial?: boolean;
}) {
  const basis = summaryItems ?? items;
  const dsmCrs = summarizeAreaDsmCrs(basis, partial).groups.map((group) => group.crs);
  const otherCrs = basis.map((item) => normalizeCrs(item.inspection.raster?.observedCrsIdentifier)).filter((crs): crs is string => crs !== null);
  // 범주 색은 분석에 쓰는 좌표계에만 준다. 비교할 수 없는 좌표계는 회색이라 "같은 색끼리 비교"로 읽히지 않는다.
  const swatches = assignCrsSwatches([...dsmCrs, ...otherCrs].filter(isAnalysisCrs));
  const thumbs = new Set(items.slice(0, 12).map((item) => item.assetRef));
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <CrsSummary items={basis} partial={partial} swatches={swatches} />
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
                  <span className="text-micro text-ink-muted md:hidden">좌표 기준 · </span>
                  {(() => {
                    const crs = normalizeCrs(item.inspection.raster?.observedCrsIdentifier);
                    if (!crs) return "확인 불가";
                    const name = crsName(crs);
                    return (
                      <span className="inline-flex items-center gap-1.5 align-middle">
                        <CrsSwatch swatch={swatches.get(crs)} />
                        <span>{name ?? crs}{name && <span className="block text-micro text-ink-muted">{crs}</span>}</span>
                      </span>
                    );
                  })()}
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
