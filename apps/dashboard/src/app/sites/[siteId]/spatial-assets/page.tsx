import Link from "next/link";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
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
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatCountKo } from "@/lib/number-format";
import { listWorkAreas } from "@/lib/core-api/workAreas";

export const metadata = { title: "공간 자산 · KSI" };

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

function errorView(error: unknown, scope: "site" | "catalog" | "detail", siteId: string) {
  if (error instanceof CoreApiError) {
    if (error.status === 404) {
      if (scope === "site") notFound();
      return <ErrorState
        message={scope === "catalog"
          ? "작업구역을 확인할 수 없거나 접근 권한이 없습니다."
          : "자산을 찾을 수 없거나 현재 조회할 수 없습니다."}
        tone="high"
        action={{ label: "공간 자산 목록으로", href: `/sites/${encodeURIComponent(siteId)}/spatial-assets` }}
      />;
    }
    if (error.status === 403) {
      return <ErrorState message="현장 공간 자산 조회 권한이 없습니다. 현장 담당자에게 조회 권한을 요청하세요." tone="high" />;
    }
    if (error.status === 503 || error.status >= 500) {
      return <ErrorState message="공간 자산을 일시적으로 불러오지 못했습니다." retryable retryAfterSeconds={error.retryAfterSeconds} />;
    }
    return <ErrorState message="요청한 공간 자산 정보를 확인할 수 없습니다." tone="high" />;
  }
  return <ErrorState message="공간 자산 정보를 Core에서 불러오지 못했습니다." retryable />;
}

function lifecycleLabel(state: SpatialAssetCatalogItem["lifecycleState"]): string {
  if (state === "SEALED") return "봉인됨";
  if (state === "SUPERSEDED") return "대체됨";
  return "미봉인";
}

const INSPECTION_STATE_LABEL: Record<string, string> = {
  PENDING_SEAL: "봉인 대기",
  INSPECTION_NOT_CONFIGURED: "검사 미설정",
  INSPECTION_NOT_QUERIED: "검사 결과 확인 전",
  INSPECTION_PENDING_SEAL: "봉인 대기",
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
  return INSPECTION_STATE_LABEL[state] ?? state;
}

function inspectionOutcomeLabel(outcome: SpatialAssetInspection["outcome"]): string {
  if (outcome === "MEASURED") return "측정 정보 있음";
  if (outcome === "REJECTED") return "거부됨";
  if (outcome === "NOT_APPLICABLE") return "적용 대상 아님";
  return "아직 확인되지 않음";
}

function kindLabel(kind: SpatialAssetCatalogItem["kind"]): string {
  const labels: Record<SpatialAssetCatalogItem["kind"], string> = {
    point_cloud: "포인트 클라우드",
    camera_poses: "카메라 자세 자료",
    ortho: "정사영상",
    dsm: "DSM 지표면 모델",
    dtm: "DTM 지면 모델",
    mesh: "3D Mesh",
    tiles_3d: "3D 타일",
    report: "처리 보고서",
  };
  return labels[kind];
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

function AssetSummary({ item, siteId }: { item: SpatialAssetCatalogItem; siteId: string }) {
  const stateClass = item.lifecycleState === "SEALED" ? "text-ink" : "text-high-ink";
  return <article className="rounded-lg border border-line bg-surface px-4 py-3">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 className="text-[14px] font-semibold">{item.declared.fileName}</h3>
        <p className="mt-1 text-[12px] text-ink-2">{kindLabel(item.kind)} · {item.declared.format} · {item.declared.contentType}</p>
        <p className={`mt-1 text-[12px] ${stateClass}`}>Core 등록 상태: {lifecycleLabel(item.lifecycleState)}</p>
      </div>
      <Link className="btn" href={pageHref(siteId, item.workAreaId, { assetRef: item.assetRef })}>상세 보기</Link>
    </div>
    <p className="mt-2 text-[12px] leading-5 text-ink-muted">관측 epoch: {item.observationEpochId} · 수정 {item.revision}</p>
    <FactStatus item={item} compact />
  </article>;
}

function FactStatus({ item, compact = false }: { item: SpatialAssetCatalogItem; compact?: boolean }) {
  const inspectionText = inspectionOutcomeLabel(item.inspection.outcome);
  return <div className={compact ? "mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-ink-2" : "mt-3 grid gap-2 sm:grid-cols-3"}>
    <p>{compact ? "고객 신고 정보 있음" : "고객 신고 정보"}</p>
    <p>{item.observed ? "KSI 바이트 관측 있음" : "KSI 바이트 관측 없음"}</p>
    <p>KSI 검사 결과: {inspectionText}</p>
  </div>;
}

function DeclaredFacts({ item }: { item: SpatialAssetCatalogItem }) {
  const declared = item.declared;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">고객 신고 정보 <span className="text-[11px] font-normal text-ink-muted">업로더가 제출</span></h3>
    <dl className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
      <Fact label="파일명 / 형식" value={`${declared.fileName} · ${declared.format}`} />
      <Fact label="종류 / MIME" value={`${kindLabel(item.kind)} · ${declared.contentType}`} />
      <Fact label="신고 크기" value={exactByteCount(declared.sizeBytes)} />
      <Fact label="신고 SHA-256" value={declared.sha256} mono />
      <Fact label="신고 CRS" value={declared.crs ?? "미기재"} />
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
  if (!item.observed) return <section className="rounded-lg border border-line bg-surface p-4"><h3 className="text-[14px] font-bold">KSI 바이트 관측 (OBSERVED)</h3><p className="mt-2 text-[12.5px] text-ink-2">KSI가 봉인한 바이트 매니페스트가 없습니다.</p></section>;
  const observed = item.observed;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">KSI 바이트 관측 <span className="text-[11px] font-normal text-ink-muted">봉인된 저장 바이트</span></h3>
    <dl className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
      <Fact label="관측 크기" value={exactByteCount(observed.sizeBytes)} />
      <Fact label="관측 MIME" value={observed.contentType} />
      <Fact label="관측 SHA-256" value={observed.sha256} mono />
      <Fact label="매니페스트 digest" value={observed.manifestDigest} mono />
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
      <Fact label="관측 CRS" value={raster.observedCrsIdentifier} />
      <Fact label="격자 크기" value={`${formatCountKo(raster.width)} × ${formatCountKo(raster.height)} pixels`} />
      <Fact label="관측 CRS digest" value={raster.observedCrsDigest} mono />
      <Fact label="검사 보고서 digest" value={raster.sourceReportDigest} mono />
      <Fact label="검사기 build digest" value={raster.inspectorBuildDigest} mono />
      <Fact label="관측 수직 기준" value={raster.observedVerticalReference ? `${raster.observedVerticalReference.identifier} · ${raster.observedVerticalReference.basis}` : "관측되지 않음"} />
    </dl>
    <details className="mt-3 text-[11.5px] text-ink-2"><summary className="cursor-pointer">격자 변환과 범위 근거</summary>
      <p className="mt-2 break-all font-mono">{raster.transform.join(", ")}</p>
      <p className="mt-2 break-all font-mono">{raster.footprintWkt}</p>
      <p className="mt-1 break-all font-mono text-ink-muted">범위 digest: {raster.footprintDigest}</p>
    </details>
  </>;
}

function InspectionFacts({ inspection }: { inspection: SpatialAssetInspection }) {
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">KSI 검사 결과 <span className="text-[11px] font-normal text-ink-muted">파일 구조 검사</span></h3>
    <p className="mt-2 text-[12.5px] text-ink-2">상태: {inspectionStateLabel(inspection.state)} · 결과: {inspectionOutcomeLabel(inspection.outcome)}</p>
    {inspection.reason && <p className="mt-1 text-[12px] text-ink-2">사유: {inspection.reason}</p>}
    {inspection.raster ? <RasterFacts raster={inspection.raster} /> : <p className="mt-2 text-[12px] text-ink-muted">검사된 래스터 공간 정보가 없습니다.</p>}
    {inspection.reportDigest && <p className="mt-2 break-all font-mono text-[10.5px] text-ink-muted">검사 보고서: {inspection.reportDigest}</p>}
    <p className="mt-3 text-[11.5px] leading-5 text-ink-muted">형식·격자 정보 검사만 나타냅니다. 정확도, 좌표 기준의 현장 검증, 분석 적합성은 판정하지 않습니다.</p>
  </section>;
}

function AssetDetail({ item }: { item: SpatialAssetCatalogItem }) {
  return <section className="flex flex-col gap-3 rounded-xl border border-line bg-sunk/50 p-3 sm:p-4">
    <header><h2 className="text-[16px] font-bold">선택한 자산 상세</h2><p className="mt-1 text-[12px] text-ink-2">관측 epoch: {item.observationEpochId} · 작업 지시: {item.workOrderId} · 제출 revision {item.revision}</p></header>
    <FactStatus item={item} />
    <DeclaredFacts item={item} />
    <ObservedFacts item={item} />
    <InspectionFacts inspection={item.inspection} />
    <section className="rounded-lg border border-high/30 bg-high-bg px-4 py-3 text-[12px] leading-5 text-high-ink">
      <p className="font-semibold">데이터 사용 제한</p>
      <p className="mt-1">다운로드는 이 목록에서 제공되지 않습니다. Core에 등록된 메타데이터만 볼 수 있습니다.</p>
      <p className="mt-1">분석 적합성은 평가되지 않았습니다. 이 자산을 분석 입력으로 사용할 수 있다고 판단하지 않습니다.</p>
      {item.lifecycleState !== "SEALED" && <p className="mt-1">현재 생애주기 상태가 {lifecycleLabel(item.lifecycleState)}이므로 유효한 분석 입력으로 취급하지 않습니다.</p>}
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

  const basePath = `/sites/${encodeURIComponent(siteId)}/spatial-assets`;
  const areaParam = query.workAreaId;
  if (Array.isArray(areaParam)) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="작업구역을 하나만 선택하세요." tone="high" action={{ label: "목록으로 돌아가기", href: basePath }} /></div>;
  }
  const workAreaId = singleQueryValue(areaParam);
  const selectedArea = areas.workAreas.find((area) => area.workAreaId === workAreaId);
  const cursorParam = query.cursor;
  const assetRefParam = query.assetRef;
  if (workAreaId && !selectedArea) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="작업구역을 확인할 수 없거나 접근 권한이 없습니다." tone="high" action={{ label: "다른 작업구역 선택", href: basePath }} /></div>;
  }
  if (Array.isArray(cursorParam) || (typeof cursorParam === "string" && cursorParam.length > 1024)) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="페이지 커서가 올바르지 않습니다. 목록을 처음부터 다시 열어 주세요." tone="high" action={{ label: "처음부터 보기", href: workAreaId ? pageHref(siteId, workAreaId) : basePath }} /></div>;
  }
  if (Array.isArray(assetRefParam) || (typeof assetRefParam === "string" && !/^ksa-v1-[0-9a-f]{64}$/.test(assetRefParam))) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="자산 참조가 올바르지 않습니다." tone="high" action={{ label: "목록으로 돌아가기", href: workAreaId ? pageHref(siteId, workAreaId) : basePath }} /></div>;
  }
  const cursor = singleQueryValue(cursorParam);
  const assetRef = singleQueryValue(assetRefParam);

  let page: Awaited<ReturnType<typeof listSpatialAssets>> | null = null;
  let pageError: unknown = null;
  if (workAreaId) {
    try {
      page = await listSpatialAssets(siteId, workAreaId, { limit: 50, cursor });
    } catch (error) {
      pageError = error;
    }
  }

  let detail: Awaited<ReturnType<typeof getSpatialAsset>> | null = null;
  let detailError: unknown = null;
  if (assetRef && workAreaId && !pageError) {
    try {
      detail = await getSpatialAsset(siteId, workAreaId, assetRef);
    } catch (error) {
      detailError = error;
    }
  }

  return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">
    <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
      <div>
        <p className="text-[12.5px] text-ink-2">{site.name}</p>
        <h2 className="mt-1 text-[22px] font-bold tracking-tight">현장 공간 자산</h2>
        <p className="mt-1 max-w-3xl text-[13px] leading-5 text-ink-2">Core에 등록된 관측의 공간 데이터 메타데이터를 확인합니다. 고객 신고, KSI 바이트 관측, 형식 검사를 별도 근거로 표시합니다.</p>
      </div>
      <div className="flex flex-wrap gap-2"><Link href={`/sites/${encodeURIComponent(siteId)}/spatial-data-requests${workAreaId ? `?workAreaId=${encodeURIComponent(workAreaId)}` : ""}`} className="btn">구역 데이터 요청</Link><Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="btn">외부 관측 이력</Link><Link href={`/sites/${encodeURIComponent(siteId)}`} className="btn">현장으로 돌아가기</Link></div>
    </header>

    <section className="rounded-lg border border-line bg-surface px-4 py-3">
      <form action={basePath} method="get" className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-56 flex-col gap-1 text-[12px] font-semibold" htmlFor="spatial-work-area">작업구역 선택
          <select id="spatial-work-area" name="workAreaId" className="input" defaultValue={workAreaId ?? ""} required>
            <option value="" disabled>작업구역을 선택하세요</option>
            {areas.workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}{area.status === "ARCHIVED" ? " · 보관됨" : ""}</option>)}
          </select>
        </label>
        <button className="btn btn-primary" type="submit">자산 불러오기</button>
      </form>
      {areas.workAreas.length === 0 && <p className="mt-3 text-[12.5px] leading-5 text-ink-2">현장에 등록된 작업구역이 없습니다. 자산을 조회하려면 작업구역을 먼저 등록해야 합니다.</p>}
      {!workAreaId && <p className="mt-3 text-[12.5px] text-ink-2">현장 안의 작업구역 하나를 선택하면 그 범위에 귀속된 자산 목록을 Core에서 조회합니다.</p>}
      {workAreaId && selectedArea && <p className="mt-2 text-[12px] text-ink-muted">선택: {selectedArea.name}{selectedArea.status === "ARCHIVED" ? " · 보관됨" : ""} · 한 번에 최대 50건을 표시합니다.</p>}
    </section>

    {pageError !== null && <div>{errorView(pageError, "catalog", siteId)}</div>}
    {page && <>
      {page.workAreaId !== workAreaId || page.siteId !== siteId ? <ErrorState message="Core 응답의 현장·작업구역 범위가 요청과 일치하지 않아 자산을 표시하지 않았습니다." tone="high" /> : <>
        <p className="rounded-lg border border-line bg-sunk px-4 py-2 text-[11.5px] leading-5 text-ink-muted">한 작업구역에만 연결된 작업 지시의 자료를 표시합니다. 여러 작업구역에 함께 연결된 기록은 여기서 조회하지 않습니다.</p>
        {assetRef && detailError && <div>{errorView(detailError, "detail", siteId)}</div>}
        {assetRef && detail && (detail.assetRef !== assetRef || detail.siteId !== siteId || detail.workAreaId !== workAreaId)
          ? <ErrorState message="Core 응답 자산의 ID 또는 현장·작업구역 범위가 요청과 일치하지 않아 상세를 표시하지 않았습니다." tone="high" />
          : null}
        {detail && detail.assetRef === assetRef && detail.siteId === siteId && detail.workAreaId === workAreaId
          ? isMetadataOnly(detail)
            ? <AssetDetail item={detail} />
            : <ErrorState message="Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 상세를 표시하지 않았습니다." tone="high" />
          : null}
        <section className="flex flex-col gap-3">
          <header><h2 className="text-[16px] font-bold">공간 자산 목록</h2><p className="mt-1 text-[12px] text-ink-muted">이 목록은 메타데이터 조회이며 파일 다운로드나 분석 가능 판정을 제공하지 않습니다.</p></header>
          {page.assets.length === 0
            ? <EmptyState compact title="이 작업구역에 등록된 공간 자산이 없습니다" description="외부 관측 자료가 이 작업구역에 등록되면 해당 자산의 메타데이터가 여기에 표시됩니다." />
            : page.assets.map((item) => {
              if (item.siteId !== siteId || item.workAreaId !== workAreaId) {
                return <ErrorState key={item.assetRef} message="Core 응답 자산의 현장·작업구역 범위가 일치하지 않아 해당 항목을 숨겼습니다." tone="high" />;
              }
              if (!isMetadataOnly(item)) {
                return <ErrorState key={item.assetRef} message="Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 해당 항목을 숨겼습니다." tone="high" />;
              }
              return <AssetSummary key={item.assetRef} item={item} siteId={siteId} />;
            })}
        </section>
        <nav aria-label="공간 자산 페이지" className="flex flex-wrap gap-2">
          {cursor && <Link className="btn" href={pageHref(siteId, workAreaId!)}>처음부터 보기</Link>}
          {page.hasMore && page.nextCursor && <Link className="btn btn-primary" href={pageHref(siteId, workAreaId!, { cursor: page.nextCursor })}>다음 자산 보기</Link>}
        </nav>
      </>}
    </>}
  </div>;
}
