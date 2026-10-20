import Link from "next/link";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";

import { SpatialDataRequestAction } from "./SpatialDataRequestAction";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import {
  getSpatialAsset,
  listSpatialAssets,
  type SpatialAssetCatalogItem,
  type SpatialAssetInspection,
  type SpatialAssetInspectedRasterFacts,
} from "@/lib/core-api/spatial-assets";
import { getSite } from "@/lib/core-api/sites";
import { nativeBoundsFromInspection } from "@/lib/spatial-data-request";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatCountKo } from "@/lib/number-format";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import {
  duplicateFileNames,
  resolveWorkName,
} from "@/lib/human-labels";
import {
  assetBusinessTitle,
  assetBusinessTitles,
  assetLifecycleLabel,
  dataKindLabel,
  isSupportedDataKind,
  isSupportedLifecycleState,
} from "@/lib/operator-language";
import { listWorkAreas } from "@/lib/core-api/workAreas";

export const metadata = { title: "등록 자료 · KSI" };

type SearchValue = string | string[] | undefined;
type SearchParams = { workAreaId?: SearchValue; cursor?: SearchValue; assetRef?: SearchValue };

function singleQueryValue(value: SearchValue): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function pageHref(siteId: string, workAreaId: string, values: { cursor?: string; assetRef?: string } = {}): string {
  const query = new URLSearchParams({ workAreaId });
  if (values.cursor) query.set("cursor", values.cursor);
  if (values.assetRef) query.set("assetRef", values.assetRef);
  return `/sites/${encodeURIComponent(siteId)}/spatial-assets?${query.toString()}`;
}

function errorView(error: unknown, scope: "site" | "catalog" | "detail", siteId: string, returnHref?: string) {
  if (error instanceof CoreApiError) {
    if (error.status === 404) {
      if (scope === "site") notFound();
      return <ErrorState
        message={scope === "catalog"
          ? "작업구역을 확인할 수 없거나 접근 권한이 없습니다."
          : "자산을 찾을 수 없거나 현재 조회할 수 없습니다."}
        tone="high"
        action={{ label: "등록 자료 목록으로", href: returnHref ?? `/sites/${encodeURIComponent(siteId)}/spatial-assets` }}
      />;
    }
    if (error.status === 403) {
      return <ErrorState message="현장 등록 자료 조회 권한이 없습니다. 현장 담당자에게 조회 권한을 요청하세요." tone="high" />;
    }
    if (error.status === 503 || error.status >= 500) {
      return <ErrorState message="등록 자료를 일시적으로 불러오지 못했습니다." retryable retryAfterSeconds={error.retryAfterSeconds} />;
    }
    return <ErrorState message="요청한 등록 자료 정보를 확인할 수 없습니다." tone="high" />;
  }
  return <ErrorState message="등록 자료 정보를 불러오지 못했습니다." retryable />;
}

function TechnicalFileInfo({ item, workName, areaName }: { item: SpatialAssetCatalogItem; workName?: string | null; areaName?: string }) {
  return <details className="mt-2 text-[12px] text-ink-2">
    <summary className="tap-target cursor-pointer font-semibold text-ink-muted">파일 정보·처리 상세 보기</summary>
    <div className="mt-1 flex flex-col gap-1 break-all border-l-2 border-line pl-3">
      <p>등록 파일명 · {item.declared.fileName}</p>
      {areaName && <p>작업구역명 · {areaName}</p>}
      <p>등록된 관측 작업명 · {workName ?? "확인 불가"}</p>
      <p>제출 참조 · {item.submissionRef} · 등록 버전 {item.revision}</p>
      <p>등록 버전은 제출한 자료 묶음의 버전이며 촬영 횟수와 다릅니다.</p>
      {!isSupportedDataKind(item.kind) && <p>등록 종류(원문) · {item.kind}</p>}
      {!isSupportedLifecycleState(item.lifecycleState) && <p>등록 상태(원문) · {item.lifecycleState}</p>}
      <p>자산 참조 · {item.assetRef}</p>
      <p>관측 기록 ID · {item.observationEpochId}</p>
      <p>작업 지시 ID · {item.workOrderId}</p>
      <p>원본 artifact ID · {item.artifactId}</p>
    </div>
  </details>;
}

const INSPECTION_STATE_LABEL: Record<string, string> = {
  PENDING_SEAL: "파일 제출 대기",
  INSPECTION_NOT_CONFIGURED: "검사 미설정",
  INSPECTION_NOT_QUERIED: "검사 결과 확인 전",
  INSPECTION_PENDING_SEAL: "파일 제출 대기",
  INSPECTION_PENDING_POLICY: "검사 기준 확인 중",
  INSPECTION_PENDING: "검사 대기",
  INSPECTION_QUEUED: "검사 대기",
  INSPECTION_RUNNING: "검사 중",
  INSPECTION_REPORTED: "검사 결과 기록됨",
  INSPECTION_FAILED_INCOMPLETE: "검사 미완료",
  COMPLETED: "검사 완료",
  FAILED: "검사 실패",
};

function inspectionStateLabel(state: string): string {
  return INSPECTION_STATE_LABEL[state] ?? "검사 상태 확인 필요";
}

function inspectionOutcomeLabel(outcome: SpatialAssetInspection["outcome"]): string {
  if (outcome === "MEASURED") return "파일 정보 확인됨";
  if (outcome === "REJECTED") return "거부됨";
  if (outcome === "NOT_APPLICABLE") return "적용 대상 아님";
  return "아직 확인되지 않음";
}

function kindLabel(kind: SpatialAssetCatalogItem["kind"]): string {
  return dataKindLabel(kind);
}

function exactByteCount(value: number): string {
  return Number.isSafeInteger(value) && value >= 0
    ? formatBytesKo(value)
    : "정확한 크기 표시 불가";
}

function isMetadataOnly(item: SpatialAssetCatalogItem): boolean {
  return item.dataAccess === "NOT_AVAILABLE_FROM_CATALOG"
    && item.analysisStatus === "NOT_EVALUATED"
    && item.supportedActions.length === 1
    && item.supportedActions[0] === "VIEW_METADATA";
}

function AssetSummary({ item, siteId, workName, areaName, headline, nameIsDuplicated }: {
  item: SpatialAssetCatalogItem;
  siteId: string;
  workName: string | null;
  areaName: string;
  headline: string;
  nameIsDuplicated: boolean;
}) {
  const stateClass = item.lifecycleState === "SEALED" ? "text-ink" : "text-high-ink";
  return <article className="rounded-lg border border-line bg-surface px-4 py-3">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="break-words text-[14px] font-semibold">{headline}</h3>
        <p className="mt-1 text-[12px] text-ink-2">{item.declared.format} · {exactByteCount(item.declared.sizeBytes)} (제출 정보 기준)</p>
        <p className={`mt-1 text-[12px] ${stateClass}`}>제출 상태: {assetLifecycleLabel(item.lifecycleState)}</p>
      </div>
      <Link className="btn min-h-11 shrink-0" href={pageHref(siteId, item.workAreaId, { assetRef: item.assetRef })}>상세 보기</Link>
    </div>
    {nameIsDuplicated && <p className="mt-2 rounded-md bg-sunk/70 px-3 py-2 text-[11.5px] leading-5 text-ink-2">같은 파일명이 이 목록에 여러 건 있습니다. 등록 버전·촬영 구간·아래 파일 정보로 구분하세요.</p>}
    <TechnicalFileInfo item={item} workName={workName} areaName={areaName} />
    <FactStatus item={item} compact />
  </article>;
}

function FactStatus({ item, compact = false }: { item: SpatialAssetCatalogItem; compact?: boolean }) {
  const inspectionText = inspectionOutcomeLabel(item.inspection.outcome);
  return <div className={compact ? "mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-ink-2" : "mt-3 grid gap-2 sm:grid-cols-3"}>
    <p>제출자 입력 정보 있음</p>
    <p>{item.observed ? "저장 파일 확인 기록 있음" : "저장 파일 확인 기록 없음"}</p>
    <p>파일 검사: {inspectionText}</p>
  </div>;
}

function DeclaredFacts({ item }: { item: SpatialAssetCatalogItem }) {
  const declared = item.declared;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">제출자가 입력한 정보</h3>
    <dl className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
      <Fact label="파일명 / 형식" value={`${declared.fileName} · ${declared.format}`} />
      <Fact label="종류 / MIME" value={`${kindLabel(item.kind)} · ${declared.contentType}`} />
      <Fact label="신고 크기" value={exactByteCount(declared.sizeBytes)} />
      <Fact label="신고 파일 확인값(SHA-256)" value={declared.sha256} mono />
      <Fact label="신고 좌표 기준" value={declared.crs ?? "미기재"} />
      <Fact label="신고 해상도" value={declared.gsdM === null ? "미기재" : `${declared.gsdM} m/pixel`} />
      <Fact label="제출 시각" value={formatKoreanDateTime(declared.submittedAt, { dateStyle: "medium", timeStyle: "short" })} />
      <Fact label="처리 완료 신고 시각" value={declared.producerCompletedAt ? formatKoreanDateTime(declared.producerCompletedAt, { dateStyle: "medium", timeStyle: "short" }) : "미기재"} />
      <Fact label="촬영 구간" value={declared.captureStartedAt && declared.captureEndedAt ? `${formatKoreanDateTime(declared.captureStartedAt, { dateStyle: "medium", timeStyle: "short" })} – ${formatKoreanDateTime(declared.captureEndedAt, { dateStyle: "medium", timeStyle: "short" })}` : "완전한 구간 미기재"} />
      <Fact label="신고 수직 기준" value={declared.verticalReference ? `${declared.verticalReference.datum} · ${declared.verticalReference.basis}` : "미기재"} />
    </dl>
    <p className="mt-3 text-[11.5px] leading-5 text-ink-muted">이 항목은 고객이 신고한 값이며 파일에서 확인한 사실이나 정확도 보증을 뜻하지 않습니다.</p>
  </section>;
}

function ObservedFacts({ item }: { item: SpatialAssetCatalogItem }) {
  if (!item.observed) return <section className="rounded-lg border border-line bg-surface p-4"><h3 className="text-[14px] font-bold">저장 파일 확인 정보</h3><p className="mt-2 text-[12.5px] text-ink-2">제출 파일을 확인한 기록이 없습니다.</p></section>;
  const observed = item.observed;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">저장 파일 확인 정보</h3>
    <dl className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
      <Fact label="관측 크기" value={exactByteCount(observed.sizeBytes)} />
      <Fact label="관측 MIME" value={observed.contentType} />
      <Fact label="관측 파일 확인값(SHA-256)" value={observed.sha256} mono />
      <Fact label="매니페스트 확인값" value={observed.manifestDigest} mono />
      <Fact label="KSI 관측 시각" value={formatKoreanDateTime(observed.observedAt, { dateStyle: "medium", timeStyle: "short" })} />
    </dl>
    <p className="mt-3 text-[11.5px] leading-5 text-ink-muted">바이트 관측은 파일의 공간적 의미나 분석 적합성을 확인한 결과가 아닙니다.</p>
  </section>;
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="min-w-0"><dt className="text-[11px] text-ink-muted">{label}</dt><dd className={`mt-0.5 break-words text-ink-2 ${mono ? "font-mono text-[11px]" : ""}`}>{value}</dd></div>;
}

function RasterFacts({ raster }: { raster: SpatialAssetInspectedRasterFacts }) {
  return <>
    <dl className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
      <Fact label="관측 좌표 기준" value={raster.observedCrsIdentifier} />
      <Fact label="격자 크기" value={`${formatCountKo(raster.width)} × ${formatCountKo(raster.height)} pixels`} />
      <Fact label="관측 좌표 기준 확인값" value={raster.observedCrsDigest} mono />
      <Fact label="검사 보고서 확인값" value={raster.sourceReportDigest} mono />
      <Fact label="검사 도구 빌드 확인값" value={raster.inspectorBuildDigest} mono />
      <Fact label="관측 수직 기준" value={raster.observedVerticalReference ? `${raster.observedVerticalReference.identifier} · ${raster.observedVerticalReference.basis}` : "관측되지 않음"} />
    </dl>
    <details className="mt-3 text-[11.5px] text-ink-2"><summary className="cursor-pointer">격자 변환과 포함 범위 근거</summary>
      <p className="mt-2 break-all font-mono">{raster.transform.join(", ")}</p>
      <p className="mt-2 break-all font-mono">{raster.footprintWkt}</p>
      <p className="mt-1 break-all font-mono text-ink-muted">범위 확인값: {raster.footprintDigest}</p>
    </details>
  </>;
}

function InspectionFacts({ inspection }: { inspection: SpatialAssetInspection }) {
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">파일 검사 결과</h3>
    <p className="mt-2 text-[12.5px] text-ink-2">상태: {inspectionStateLabel(inspection.state)} · 결과: {inspectionOutcomeLabel(inspection.outcome)}</p>
    {inspection.reason && <p className="mt-1 text-[12px] text-ink-2">사유: {inspection.reason}</p>}
    <details className="mt-2 text-[12px] text-ink-2"><summary className="tap-target cursor-pointer">좌표·격자와 검사 근거</summary>
    <p className="mt-1">검사 상태 코드 · {inspection.state}</p>
    {inspection.raster ? <RasterFacts raster={inspection.raster} /> : <p className="mt-2 text-[12px] text-ink-muted">파일에서 확인한 위치·격자 정보가 없습니다.</p>}
    {inspection.reportDigest && <p className="mt-2 break-all font-mono text-[10.5px] text-ink-muted">검사 보고서 확인값: {inspection.reportDigest}</p>}
    </details>
    <p className="mt-3 text-[11.5px] leading-5 text-ink-muted">형식·격자 정보 검사만 나타냅니다. 정확도, 좌표 기준의 현장 검증, 분석 적합성은 판정하지 않습니다.</p>
  </section>;
}

function AssetDetail({ item, workName, areaName, headline, compareHref }: {
  item: SpatialAssetCatalogItem;
  workName: string | null;
  areaName: string;
  headline: string;
  /** 분석 요청 권한이 있고 이 자료의 관측 작업을 실제로 지목할 수 있을 때만 넘긴다. */
  compareHref: string | null;
}) {
  return <section className="flex flex-col gap-3 rounded-xl border border-line bg-sunk/50 p-3 sm:p-4">
    <header>
      <h2 className="text-[16px] font-bold">선택한 자료</h2>
      <p className="mt-1 break-words text-[13.5px] font-semibold">{headline}</p>
      <p className="mt-1 text-[12px] text-ink-2">촬영 시점은 제출자가 입력한 정보 기준입니다.</p>
      <TechnicalFileInfo item={item} workName={workName} areaName={areaName} />
      {compareHref && <div className="mt-2">
        <Link href={compareHref} className="btn w-fit">이 자료를 현재 관측으로 선택</Link>
        <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">분석·검토 화면에서 이 관측이 비교 후보인지와 기준 관측 선택을 확인합니다. 여기서 분석을 실행하지 않습니다.</p>
      </div>}
    </header>
    <FactStatus item={item} />
    <details className="rounded-lg border border-line bg-surface p-3 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">제출자 입력 정보 상세</summary><DeclaredFacts item={item} /></details>
    <details className="rounded-lg border border-line bg-surface p-3 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">저장 파일 확인 상세</summary><ObservedFacts item={item} /></details>
    <InspectionFacts inspection={item.inspection} />
    <section className="rounded-lg border border-high/30 bg-high-bg px-4 py-3 text-[12px] leading-5 text-high-ink">
      <p className="font-semibold">데이터 사용 제한</p>
      <p className="mt-1">이 화면은 파일의 등록 정보만 제공합니다. 파일이 필요하면 아래에서 받기 요청을 만들고, 준비 상태는 구역 자료 준비에서 확인하세요.</p>
      <p className="mt-1">분석 적합성은 평가되지 않았습니다. 이 자산을 분석 입력으로 사용할 수 있다고 판단하지 않습니다.</p>
      {item.lifecycleState !== "SEALED" && <p className="mt-1">현재 제출 상태가 {assetLifecycleLabel(item.lifecycleState)}이므로 유효한 분석 입력으로 취급하지 않습니다.</p>}
    </section>
  </section>;
}

export default async function SpatialAssetsPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={`/sites/${encodeURIComponent(siteId)}/spatial-assets`} />;

  let site: Awaited<ReturnType<typeof getSite>>;
  let areas: Awaited<ReturnType<typeof listWorkAreas>>;
  try {
    [site, areas] = await Promise.all([getSite(siteId), listWorkAreas(siteId, { includeArchived: true })]);
  } catch (error) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5">{errorView(error, "site", siteId)}</div>;
  }

  // 작업 지시 이름은 사람용 표시 전용이다. 이 조회가 실패해도 목록·상세는
  // "작업명 확인 불가"로 그대로 표시되며, 존재·권한·적합성을 추정하지 않는다.
  let workOrderNames: Record<string, string> | null = null;
  try {
    const workOrders = await listObservationWorkOrders(siteId);
    const names: Record<string, string> = {};
    for (const order of workOrders) {
      if (order.siteId !== siteId || order.organizationId !== session.principal.organizationId) continue;
      if (typeof order.name === "string" && order.name.trim().length > 0) names[order.workOrderId] = order.name;
    }
    workOrderNames = names;
  } catch {
    workOrderNames = null;
  }

  const basePath = `/sites/${encodeURIComponent(siteId)}/spatial-assets`;
  const areaParam = query.workAreaId;
  if (Array.isArray(areaParam)) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="작업구역을 하나만 선택하세요." tone="high" action={{ label: "목록으로 돌아가기", href: basePath }} /></div>;
  }
  const workAreaId = singleQueryValue(areaParam);
  // 작업구역이 하나뿐이면 같은 구역으로 이어간다. 여러 구역이면 직접 선택을 둔다.
  const activeAreas = areas.workAreas.filter((area) => area.status === "ACTIVE");
  const effectiveWorkAreaId = workAreaId
    ?? (activeAreas.length === 1 && activeAreas[0] ? activeAreas[0].workAreaId : undefined);
  const effectiveAreaNotice = !workAreaId && effectiveWorkAreaId
    ? "현장에 등록된 작업구역이 하나뿐이라 해당 구역의 자료를 표시합니다."
    : null;
  const selectedArea = areas.workAreas.find((area) => area.workAreaId === effectiveWorkAreaId);
  const cursorParam = query.cursor;
  const assetRefParam = query.assetRef;
  if (workAreaId && !selectedArea) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="작업구역을 확인할 수 없거나 접근 권한이 없습니다." tone="high" action={{ label: "다른 작업구역 선택", href: basePath }} /></div>;
  }
  if (Array.isArray(cursorParam) || (typeof cursorParam === "string" && cursorParam.length > 1024)) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="페이지 커서가 올바르지 않습니다. 목록을 처음부터 다시 열어 주세요." tone="high" action={{ label: "처음부터 보기", href: effectiveWorkAreaId ? pageHref(siteId, effectiveWorkAreaId) : basePath }} /></div>;
  }
  if (Array.isArray(assetRefParam) || (typeof assetRefParam === "string" && !/^ksa-v1-[0-9a-f]{64}$/.test(assetRefParam))) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="자산 참조가 올바르지 않습니다." tone="high" action={{ label: "목록으로 돌아가기", href: effectiveWorkAreaId ? pageHref(siteId, effectiveWorkAreaId) : basePath }} /></div>;
  }
  const cursor = singleQueryValue(cursorParam);
  const assetRef = singleQueryValue(assetRefParam);

  let page: Awaited<ReturnType<typeof listSpatialAssets>> | null = null;
  let pageError: unknown = null;
  if (effectiveWorkAreaId) {
    try {
      page = await listSpatialAssets(siteId, effectiveWorkAreaId, { limit: 50, cursor });
    } catch (error) {
      pageError = error;
    }
  }

  let detail: Awaited<ReturnType<typeof getSpatialAsset>> | null = null;
  let detailError: unknown = null;
  if (assetRef && effectiveWorkAreaId && !pageError) {
    try {
      detail = await getSpatialAsset(siteId, effectiveWorkAreaId, assetRef);
    } catch (error) {
      detailError = error;
    }
  }

  const duplicatedNames = page
    ? duplicateFileNames(page.assets.map((asset) => asset.declared.fileName))
    : new Set<string>();
  const businessTitles = page ? assetBusinessTitles(page.assets) : new Map<string, string>();
  const businessTitleFor = (item: SpatialAssetCatalogItem): string =>
    businessTitles.get(item.assetRef) ?? assetBusinessTitle(item);
  const areaDisplayName = selectedArea?.name ?? effectiveWorkAreaId ?? "";
  const canRequestAnalysis = session.principal.permissions.includes("SITES_WRITE");
  const canRequestData = session.principal.permissions.includes("SPATIAL_DATA_REQUEST");
  const inspectedRaster = detail?.inspection.raster ?? null;
  const dataRequestBounds = inspectedRaster ? nativeBoundsFromInspection(inspectedRaster) : null;
  const compareHref = canRequestAnalysis && effectiveWorkAreaId && selectedArea && detail?.workOrderId
    ? `/sites/${encodeURIComponent(siteId)}/analysis?workAreaId=${encodeURIComponent(effectiveWorkAreaId)}&currentWorkOrderId=${encodeURIComponent(detail.workOrderId)}#new-analysis-request`
    : null;

  return <div className="flex flex-col">
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab="materials"
      canCreateWorkOrder={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
      canEditAoi={canRequestAnalysis}
      scopedWorkAreaId={effectiveWorkAreaId && selectedArea ? effectiveWorkAreaId : null}
      scopedAssetRef={detail && assetRef && detail.assetRef === assetRef ? assetRef : null}
    />
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 sm:p-5">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
        <div>
          <h2 className="mt-1 text-[22px] font-bold tracking-tight">현장 등록 자료</h2>
          <p className="mt-1 max-w-3xl text-[13px] leading-5 text-ink-2">자료 종류와 촬영 시점으로 파일을 찾고, 제출·파일 검사 상태를 확인하세요. 제출자가 입력한 정보와 파일에서 확인한 결과는 구분해 표시합니다.</p>
        </div>
        <div className="flex flex-wrap gap-2"><Link href={`/sites/${encodeURIComponent(siteId)}/spatial-data-requests${effectiveWorkAreaId ? `?workAreaId=${encodeURIComponent(effectiveWorkAreaId)}` : ""}`} className="btn">구역 자료 준비</Link><Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="btn">외부 비교 기록</Link></div>
      </header>

      <section className="rounded-lg border border-line bg-surface px-4 py-3">
        <form action={basePath} method="get" className="flex flex-wrap items-end gap-2">
          <label className="flex min-w-56 flex-col gap-1 text-[12px] font-semibold" htmlFor="spatial-work-area">작업구역 선택
            <select id="spatial-work-area" name="workAreaId" className="input" defaultValue={effectiveWorkAreaId ?? ""} required>
              <option value="" disabled>작업구역을 선택하세요</option>
              {areas.workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}{area.status === "ARCHIVED" ? " · 보관됨" : ""}</option>)}
            </select>
          </label>
              <button className="btn btn-primary" type="submit">등록 자료 보기</button>
        </form>
        {areas.workAreas.length === 0 && <p className="mt-3 text-[12.5px] leading-5 text-ink-2">현장에 등록된 작업구역이 없습니다. 자료를 확인하려면 작업구역을 먼저 등록하세요.</p>}
        {!effectiveWorkAreaId && areas.workAreas.length > 0 && <p className="mt-3 text-[12.5px] text-ink-2">작업구역을 선택해 해당 구역에 연결된 자료를 확인하세요.</p>}
        {effectiveAreaNotice && <p className="mt-2 text-[12px] text-ink-muted" role="status">{effectiveAreaNotice}</p>}
        {effectiveWorkAreaId && selectedArea && <p className="mt-2 text-[12px] text-ink-muted">선택: {selectedArea.name}{selectedArea.status === "ARCHIVED" ? " · 보관됨" : ""} · 한 번에 최대 50건을 표시합니다.</p>}
      </section>

      {pageError !== null && <div>{errorView(pageError, "catalog", siteId, effectiveWorkAreaId ? pageHref(siteId, effectiveWorkAreaId) : undefined)}</div>}
      {page && <>
        {page.workAreaId !== effectiveWorkAreaId || page.siteId !== siteId ? <ErrorState message="Core 응답의 현장·작업구역 범위가 요청과 일치하지 않아 자산을 표시하지 않았습니다." tone="high" /> : <>
          <p className="rounded-lg border border-line bg-sunk px-4 py-2 text-[11.5px] leading-5 text-ink-muted">한 작업구역에만 연결된 작업 지시의 자료를 표시합니다. 여러 작업구역에 함께 연결된 기록은 여기서 조회하지 않습니다.</p>
          {assetRef && detailError && <div>{errorView(detailError, "detail", siteId, effectiveWorkAreaId ? pageHref(siteId, effectiveWorkAreaId) : undefined)}</div>}
          {assetRef && detail && (detail.assetRef !== assetRef || detail.siteId !== siteId || detail.workAreaId !== effectiveWorkAreaId)
            ? <ErrorState message="Core 응답 자산의 ID 또는 현장·작업구역 범위가 요청과 일치하지 않아 상세를 표시하지 않았습니다." tone="high" />
            : null}
          {detail && detail.assetRef === assetRef && detail.siteId === siteId && detail.workAreaId === effectiveWorkAreaId
            ? isMetadataOnly(detail)
              ? <>
                <AssetDetail
                  item={detail}
                  workName={resolveWorkName(detail.workOrderId, workOrderNames)}
                  areaName={areaDisplayName}
                  headline={businessTitleFor(detail)}
                  compareHref={compareHref}
                />
                {dataRequestBounds && inspectedRaster && (
                  <SpatialDataRequestAction
                    siteId={siteId}
                    workAreaId={effectiveWorkAreaId!}
                    assetRef={detail.assetRef}
                    requestedBounds={dataRequestBounds}
                    observedCrsDigest={inspectedRaster.observedCrsDigest}
                    canRequest={canRequestData}
                  />
                )}
              </>
              : <ErrorState message="Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 상세를 표시하지 않았습니다." tone="high" />
            : null}
          <section className="flex flex-col gap-3">
            <header><h2 className="text-[16px] font-bold">등록 자료 목록</h2><p className="mt-1 text-[12px] text-ink-muted">파일의 등록 정보만 보여줍니다. 파일 받기와 분석 사용 가능 여부는 별도로 확인합니다.</p></header>
            {page.assets.length === 0
              ? <EmptyState compact title="이 작업구역에 등록된 자료가 없습니다" description="관측 자료가 이 작업구역에 등록되면 해당 자료의 메타데이터가 여기에 표시됩니다." />
              : page.assets.map((item) => {
                if (item.siteId !== siteId || item.workAreaId !== effectiveWorkAreaId) {
                  return <ErrorState key={item.assetRef} message="Core 응답 자산의 현장·작업구역 범위가 일치하지 않아 해당 항목을 숨겼습니다." tone="high" />;
                }
                if (!isMetadataOnly(item)) {
                  return <ErrorState key={item.assetRef} message="Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 해당 항목을 숨겼습니다." tone="high" />;
                }
                return <AssetSummary
                  key={item.assetRef}
                  item={item}
                  siteId={siteId}
                  workName={resolveWorkName(item.workOrderId, workOrderNames)}
                  areaName={areaDisplayName}
                  headline={businessTitleFor(item)}
                  nameIsDuplicated={duplicatedNames.has(item.declared.fileName)}
                />;
              })}
          </section>
          <nav aria-label="등록 자료 페이지" className="flex flex-wrap gap-2">
            {cursor && effectiveWorkAreaId && <Link className="btn" href={pageHref(siteId, effectiveWorkAreaId)}>처음부터 보기</Link>}
            {page.hasMore && page.nextCursor && effectiveWorkAreaId && <Link className="btn btn-primary" href={pageHref(siteId, effectiveWorkAreaId, { cursor: page.nextCursor })}>다음 자산 보기</Link>}
          </nav>
        </>}
      </>}
    </div>
  </div>;
}
