import Link from "next/link";

import { InlineNotice } from "@/components/ui/InlineNotice";
import { StepIndicator } from "@/components/ui/StepIndicator";
import { StateBadge } from "@/components/ui/StatusBadge";
import { presentWorkOrder } from "@/app/field/work-order-stage";
import { firstReadableWindowJob, type PreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";
import type { SpatialAssetCatalogItem, SpatialAssetCatalogPage } from "@/lib/core-api/spatial-assets";
import { dataKindLabel } from "@/lib/operator-language";

import { MaterialThumb } from "../spatial-assets/MaterialThumb";
import { inspectionStateLabel } from "./asset-detail";
import { applyCatalogFilters, groupAssetsByObservation, materialsHref, observationGroupDateLine, type MaterialsScope } from "./materials-visual";

export function MaterialsPanel({
  siteId, workAreaId, page, issue, selectedAssetRef, scope, jobs, canRead, compare,
}: {
  siteId: string;
  workAreaId: string | null;
  page: SpatialAssetCatalogPage | null;
  issue: string | null;
  selectedAssetRef: string | null;
  scope: MaterialsScope;
  jobs: readonly PreparedWindowJob[];
  canRead: boolean;
  compare: boolean;
}) {
  if (issue) return <InlineNotice tone="high">{issue}</InlineNotice>;
  if (!workAreaId || !page) return <p className="text-caption text-ink-2">작업구역을 선택하면 이곳에서 자료를 확인할 수 있습니다.</p>;

  const { q = "", kind = "", state = "", ...selection } = scope;
  const filtered = applyCatalogFilters(page.assets, { q, kind, state: state === "attention" || state === "inspected" ? state : "" });
  const kinds = new Set<string>(page.assets.map((item) => item.kind));
  if (kind) kinds.add(kind);
  const href = (overrides: Partial<MaterialsScope>) => materialsHref(siteId, workAreaId, { ...scope, ...overrides });
  const selectionQuery = new URL(href({ q: "", kind: "", state: "", cursor: null }), "https://console.invalid").searchParams;
  if (compare) selectionQuery.set("mode", "compare");
  const groups = groupAssetsByObservation(filtered);
  const thumbs = new Set(filtered.slice(0, 8).map((item) => item.assetRef));
  return <section aria-label="자료 목록" className="flex min-w-0 flex-col gap-3">
    <form action={`/sites/${encodeURIComponent(siteId)}`} method="get" className="grid gap-2">
      {[...selectionQuery].map(([name, value]) => <input key={name} type="hidden" name={name} value={value} />)}
      <label className="grid gap-1 text-caption font-medium">자료 검색
        <input name="q" type="search" defaultValue={q} maxLength={80} placeholder="파일명 또는 종류" className="tap-target min-w-0 rounded-md border border-line bg-surface px-2 text-body" />
      </label>
      <div className="grid min-w-0 grid-cols-2 gap-1.5">
        <label className="grid min-w-0 gap-1 text-caption font-medium">종류
          <select name="kind" defaultValue={kind} className="tap-target min-w-0 rounded-md border border-line bg-surface px-1 text-caption">
            <option value="">모든 종류</option>
            {[...kinds].map((value) => <option key={value} value={value}>{dataKindLabel(value)}</option>)}
          </select>
        </label>
        <label className="grid min-w-0 gap-1 text-caption font-medium">검사 상태
          <select name="state" defaultValue={state} className="tap-target min-w-0 rounded-md border border-line bg-surface px-1 text-caption">
            <option value="">모든 상태</option>
            <option value="inspected">검사 완료</option>
            <option value="attention">확인 필요</option>
          </select>
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" className="btn">검색·필터 적용</button>
        {(q || kind || state) && <Link href={materialsHref(siteId, workAreaId, { ...selection, cursor: null })} className="tap-target text-caption underline">필터 초기화</Link>}
      </div>
    </form>
    {page.hasMore && <p className="text-micro text-ink-muted">불러온 {page.assets.length}개 자료에서 검색합니다.</p>}
    {groups.length ? <ul className="grid gap-3">
      {groups.map(({ epochId, items }) => {
        const capture = observationGroupDateLine(items);
        return <li key={epochId} className="min-w-0">
          <p className="break-words px-1 text-caption font-semibold">{capture ?? "관측 시점은 파일별로 확인"}</p>
          <ul className="mt-1 divide-y divide-line rounded-md border border-line">
            {items.map((item) => <RailItem key={item.assetRef}
              item={item}
              viewHref={href({ assetRef: item.assetRef, visualA: null, visualB: null, baseline: null, current: null, compare: false })}
              selected={item.assetRef === selectedAssetRef || item.assetRef === scope.visualA || item.assetRef === scope.visualB}
              showCapture={!capture}
              jobs={canRead && thumbs.has(item.assetRef) ? jobs : []}
            />)}
          </ul>
        </li>;
      })}
    </ul> : <p className="text-caption text-ink-2">{q || kind || state ? "이 페이지에 조건과 일치하는 자료가 없습니다." : "조회된 자료가 없습니다."}</p>}
    <div className="flex flex-wrap gap-2">
      {scope.cursor && <Link href={href({ cursor: null })} className="btn">첫 페이지</Link>}
      {page.hasMore && page.nextCursor && <Link href={href({ cursor: page.nextCursor })} className="btn">더 불러오기</Link>}
    </div>
  </section>;
}

function RailItem({ item, viewHref, selected, showCapture, jobs }: {
  item: SpatialAssetCatalogItem;
  viewHref: string;
  selected: boolean;
  showCapture: boolean;
  jobs: readonly PreparedWindowJob[];
}) {
  const readable = firstReadableWindowJob(jobs, item.assetRef);
  const caption = observationGroupDateLine([item]);
  return <li data-rail-item>
    <Link href={viewHref} data-workbench-catalog-select aria-current={selected ? "true" : undefined}
      className={`tap-target flex min-w-0 items-center gap-2 px-2 py-2 hover:bg-sunk ${selected ? "bg-sunk" : ""}`}>
      {readable?.receipt && <MaterialThumb siteId={item.siteId} workAreaId={item.workAreaId} jobId={readable.jobId} receipt={readable.receipt} fileName={item.declared.fileName} />}
      <span className="min-w-0 flex-1">
        <span className="block break-words text-body font-semibold">{dataKindLabel(item.kind)} · v{item.revision}</span>
        <span className="block truncate text-caption text-ink-2" title={item.declared.fileName}>{item.declared.fileName}</span>
        {showCapture && <span className="block break-words text-micro text-ink-2">{caption}</span>}
        <span className="block break-words text-micro text-ink-2">{inspectionStateLabel(item.inspection.state)}</span>
      </span>
    </Link>
  </li>;
}

const PROGRESS_STEPS = ["등록 승인", "파일 제출·검사", "결과 확인"] as const;

export function RegistrationProgressPanel({ siteId, orders }: {
  siteId: string;
  orders: readonly ObservationWorkOrderView[] | null;
}) {
  const latestById = new Map<string, ObservationWorkOrderView>();
  for (const order of orders ?? []) {
    if (order.siteId !== siteId) continue;
    const current = latestById.get(order.workOrderId);
    if (!current || order.version > current.version) latestById.set(order.workOrderId, order);
  }
  const inProgress = orders && [...latestById.values()]
    .filter((order) => order.status !== "COMPLETED" && order.status !== "CANCELLED");
  return <section aria-label="등록 진행 중인 작업" className="flex min-w-0 flex-col gap-3">
    {inProgress === null ? (
      <InlineNotice tone="high">등록 진행 상태를 확인하지 못했습니다.</InlineNotice>
    ) : inProgress.length === 0 ? (
      <p className="text-caption text-ink-2">진행 중인 작업이 없습니다.</p>
    ) : (
      <ul className="divide-y divide-line">
        {inProgress.map((order) => {
          const status = presentWorkOrder(order.status, order.executionMode);
          const current = order.executionMode === "EXTERNAL_RECONSTRUCTION"
            ? status.step === 1 ? 0 : order.status === "APPROVED" ? 1 : order.status === "REVIEW_READY" ? 2 : undefined
            : undefined;
          return <li key={order.workOrderId} className="grid min-w-0 gap-1.5 py-2">
            <Link className="tap-target break-words text-body font-semibold underline underline-offset-2" href={`/field/work-orders/${encodeURIComponent(order.workOrderId)}`}>
              {order.name || "작업명 확인 불가"}
            </Link>
            <StateBadge label={status.label} tone={status.tone} />
            {current !== undefined && <StepIndicator steps={PROGRESS_STEPS} current={current} align="start" label="등록 단계" />}
          </li>;
        })}
      </ul>
    )}
    <Link className="btn w-fit" href={`/field?site=${encodeURIComponent(siteId)}`}>전체 작업에서 보기</Link>
  </section>;
}
