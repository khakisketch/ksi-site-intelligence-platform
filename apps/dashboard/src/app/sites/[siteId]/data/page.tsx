import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { siteDataHref, type SiteDataScope } from "@/components/nav/site-context";
import { SectionFrame } from "@/components/section/SectionFrame";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listAnalyses } from "@/lib/core-api/analysis";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getSite } from "@/lib/core-api/sites";
import { listSpatialAssets } from "@/lib/core-api/spatial-assets";
import { listSpatialDataRequests } from "@/lib/core-api/spatial-data-requests";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { assetBusinessTitle } from "@/lib/operator-language";
import { SITE_DETAIL_DOCUMENT_TITLE } from "@/lib/site-detail-title";
import { toPreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";

import { DetailBlock } from "../materials/asset-detail";
import { readAssetHistory, readScopedAsset, scopeMaterialsPage } from "../materials/asset-reads";
import { RegistrationProgressPanel } from "../materials/MaterialsPanel";
import { applyCatalogFilters, exactMaterialsAssetRef, isMetadataOnly, normalizeCatalogFilters } from "../materials/materials-visual";
import { disambiguatedAreaNames, parseScopeId, resolveSelectedWorkAreaId } from "../site-spatial";
import { DataContextPanel } from "./DataContextPanel";
import { DataTable } from "./DataTable";

const getSiteForData = cache(getSite);

// 문서 head는 AccountDisplayBoundary 밖이다 — 현장 이름·식별자를 싣지 않는다.
export const metadata: Metadata = { title: SITE_DETAIL_DOCUMENT_TITLE };

type Query = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined): string | undefined => (Array.isArray(value) ? value[0] : value);

/**
 * 자료 섹션(ADR-KSI-043) — 프로젝트에 등록된 자료를 표로 보고, 고른 한 건의 상세와 등록 진행을 곁에서 본다.
 *
 * 새 조회·권한·판정을 만들지 않는다. 구역 단위 자료 목록, 선택 자료의 단건 읽기, 등록 이력, 작업 목록은
 * 모두 공간 뷰어의 자료 패널이 쓰던 같은 읽기다. 분석 적합성은 이 화면에서 평가하지 않는다.
 */
export default async function SiteDataPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<Query>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);

  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    site = await getSiteForData(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    const message = error instanceof CoreApiError
      ? humanizeApiError(error.code, error.status, error.serverMessage)
      : "요청을 처리하지 못했습니다.";
    return <div className="flex flex-col gap-4 p-4 sm:p-5"><ErrorState message={message} retryable /></div>;
  }

  const [canReadResult, canRequestResult, canCreateResult, areasResult, ordersResult, analysesResult] = await Promise.allSettled([
    hasAllPermissions("SPATIAL_DATA_READ"),
    hasAllPermissions("SPATIAL_DATA_REQUEST"),
    hasAllPermissions("WORK_ORDERS_WRITE"),
    listWorkAreas(site.siteId, { includeArchived: true }),
    listObservationWorkOrders(site.siteId),
    listAnalyses(site.siteId, { limit: 50 }),
  ]);
  const canRead = canReadResult.status === "fulfilled" && canReadResult.value;
  const canRequest = canRequestResult.status === "fulfilled" && canRequestResult.value;
  const canCreateWorkOrder = canCreateResult.status === "fulfilled" && canCreateResult.value;
  const areasKnown = areasResult.status === "fulfilled";
  const allAreas = areasKnown ? areasResult.value.workAreas : [];
  const orders = ordersResult.status === "fulfilled" ? ordersResult.value : null;

  const requestedAreaId = parseScopeId(first(query.workAreaId));
  const areaQueryInvalid = areasKnown && requestedAreaId !== null && !allAreas.some((area) => area.workAreaId === requestedAreaId);
  const cursor = typeof query.cursor === "string" && query.cursor.length <= 1024 ? query.cursor || undefined : undefined;
  const cursorInvalid = query.cursor !== undefined && query.cursor !== "" && cursor === undefined;
  const assetRefRaw = first(query.assetRef);
  const selectionMalformed = assetRefRaw !== undefined && assetRefRaw !== "" && exactMaterialsAssetRef(assetRefRaw) === null;
  const filters = normalizeCatalogFilters({ q: first(query.q), kind: first(query.kind), state: first(query.state) });

  const selectedWorkAreaId = areasKnown && !areaQueryInvalid
    ? resolveSelectedWorkAreaId(allAreas, requestedAreaId, {
      workOrderAreaIds: orders?.flatMap((order) => Array.isArray(order.workAreaIds) ? order.workAreaIds : []) ?? [],
      analysisAreaIds: analysesResult.status === "fulfilled" ? analysesResult.value.items.map((item) => item.workAreaId) : [],
    })
    : null;
  const areaLabel = selectedWorkAreaId
    ? disambiguatedAreaNames(allAreas).get(selectedWorkAreaId)?.label ?? selectedWorkAreaId
    : null;
  const selectedArea = selectedWorkAreaId ? allAreas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null : null;

  const assets = selectedWorkAreaId && !cursorInvalid
    ? await listSpatialAssets(site.siteId, selectedWorkAreaId, cursor ? { limit: 50, cursor } : { limit: 50 })
      .then((page) => scopeMaterialsPage(page, site.siteId, selectedWorkAreaId))
      .then(
        (page) => ({ status: "ready" as const, page }),
        (error: unknown) => ({ status: error instanceof CoreApiError && error.status === 403 ? "denied" as const : "unavailable" as const }),
      )
    : { status: "not-requested" as const };
  const page = assets.status === "ready" ? assets.page : null;
  const filtered = page ? applyCatalogFilters(page.assets, filters) : [];
  const kinds = page ? [...new Set([...page.assets.map((item) => item.kind), ...(filters.kind ? [filters.kind] : [])])] : [];

  // 선택 자료 — 이번에 읽은 페이지 안에 있는 자산만 받는다. 없으면 조용히 다른 자료로 바꾸지 않고 안내한다.
  const selectedAssetRef = !selectionMalformed && assetRefRaw && page?.assets.some((item) => item.assetRef === assetRefRaw)
    ? assetRefRaw
    : null;
  const detail = selectedAssetRef && selectedWorkAreaId ? await readScopedAsset(site.siteId, selectedWorkAreaId, selectedAssetRef) : null;
  const identity = detail ? await whoAmI().catch(() => null) : null;
  const history = detail && isMetadataOnly(detail) && identity?.organizationId
    ? await readAssetHistory(detail, identity.organizationId)
    : null;
  const workOrderNames = new Map(
    orders && identity
      ? orders.filter((order) => order.siteId === site.siteId && order.organizationId === identity.organizationId)
        .map((order) => [order.workOrderId, order.name])
      : [],
  );

  // 썸네일용 준비 기록 — 읽을 수 있을 때만, 읽기 실패는 썸네일 없음으로만 둔다(빈 자료로 단정하지 않는다).
  const jobs = page && selectedWorkAreaId && canRead
    ? await listSpatialDataRequests(site.siteId, selectedWorkAreaId, { limit: 50 }).then(
      (result) => result.items
        .filter((item) => item.siteId === site.siteId && item.workAreaId === selectedWorkAreaId)
        .map(toPreparedWindowJob),
      () => [],
    )
    : [];

  const sitePath = `/sites/${encodeURIComponent(site.siteId)}`;
  const requestsHref = selectedWorkAreaId
    ? `${sitePath}/spatial-data-requests?workAreaId=${encodeURIComponent(selectedWorkAreaId)}`
    : `${sitePath}/spatial-data-requests`;
  const scope: SiteDataScope = { workAreaId: selectedWorkAreaId, q: filters.q, kind: filters.kind, state: filters.state, cursor };

  const issue = areaQueryInvalid ? "작업구역을 확인할 수 없거나 접근 권한이 없습니다. 왼쪽에서 구역을 다시 고르세요."
    : cursorInvalid ? "페이지 주소가 올바르지 않습니다. 목록을 처음부터 다시 여세요."
    : selectionMalformed ? "자료 주소가 올바르지 않습니다. 표에서 다시 선택하세요."
    : assetRefRaw && page && selectedAssetRef === null ? "선택한 자료를 이번 목록에서 찾을 수 없습니다. 표에서 다시 선택하세요."
    : null;

  const main = (
    <>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-title font-bold tracking-tight break-words">{areaLabel ?? "자료"}</h2>
          <p className="mt-0.5 text-caption text-ink-2">
            {page ? `등록된 자료 ${page.assets.length}${page.hasMore ? "개 이상" : "개"}` : "등록된 자료"} · 분석 사용 여부는 분석의 실행 전 점검에서 확인합니다.
          </p>
        </div>
        {canCreateWorkOrder && selectedArea?.status === "ACTIVE" && (
          <>
            <Link href={`${sitePath}/observations/new?workAreaId=${encodeURIComponent(selectedArea.workAreaId)}`} className="btn btn-primary hidden lg:inline-flex">자료 등록</Link>
            <p className="text-caption text-ink-2 lg:hidden">자료 등록은 노트북 이상의 화면에서 진행하세요.</p>
          </>
        )}
      </header>

      {issue && <InlineNotice tone="high" role="alert">{issue}</InlineNotice>}
      {!areasKnown && <ErrorState message="작업구역을 불러오지 못했습니다. 잠시 후 다시 시도하세요." retryable />}
      {areasKnown && allAreas.length === 0 && (
        <EmptyState compact title="등록된 작업구역이 없습니다" description="작업구역을 만든 뒤 자료를 등록할 수 있습니다."
          action={{ label: "작업구역 관리", href: `${sitePath}/work-areas` }} />
      )}
      {assets.status === "denied" && <InlineNotice tone="high">이 구역의 자료를 볼 권한이 없습니다.</InlineNotice>}
      {assets.status === "unavailable" && <InlineNotice tone="high">자료 목록을 불러오지 못했습니다. 비어 있다는 뜻이 아닙니다. 잠시 후 다시 시도하세요.</InlineNotice>}
      {page && page.assets.length === 0 && (
        <EmptyState compact title="이 구역에 등록된 자료가 없습니다" description="파일을 제출하고 검사를 마치면 이곳에 나타납니다." />
      )}
      {page && page.assets.length > 0 && filtered.length === 0 && (
        <EmptyState compact title="조건과 일치하는 자료가 없습니다" description="이미 불러온 목록 안에서 찾았습니다. 조건을 바꾸거나 초기화하세요."
          action={{ label: "조건 초기화", href: siteDataHref(site.siteId, { workAreaId: selectedWorkAreaId }) }} />
      )}
      {page && selectedWorkAreaId && filtered.length > 0 && (
        <DataTable siteId={site.siteId} workAreaId={selectedWorkAreaId} items={filtered} selectedAssetRef={selectedAssetRef} scope={scope} jobs={jobs} canRead={canRead} />
      )}
      {page && (cursor || (page.hasMore && page.nextCursor)) && (
        <div className="flex flex-wrap gap-2">
          {cursor && <Link href={siteDataHref(site.siteId, { ...scope, cursor: null })} className="btn">첫 페이지</Link>}
          {page.hasMore && page.nextCursor && <Link href={siteDataHref(site.siteId, { ...scope, cursor: page.nextCursor })} className="btn">더 불러오기</Link>}
        </div>
      )}
    </>
  );

  const inspector = detail && selectedWorkAreaId && isMetadataOnly(detail)
    ? (
      <DetailBlock
        detail={detail}
        workName={workOrderNames.get(detail.workOrderId) ?? null}
        areaName={areaLabel ?? ""}
        headline={assetBusinessTitle(detail)}
        compareHref={null}
        retryHref={requestsHref}
        requestsHref={requestsHref}
        historyResult={history}
        requestProps={{ siteId: site.siteId, workAreaId: selectedWorkAreaId, inspectedRaster: detail.inspection.raster, canRequest }}
      />
    )
    : selectedAssetRef
      ? <InlineNotice tone="high">선택한 자료의 상세를 확인할 수 없습니다.</InlineNotice>
      : <p className="text-caption text-ink-2">표에서 자료를 고르면 검사 상태와 파일 정보가 여기에 나옵니다.</p>;

  return (
    <div className="flex min-w-0 flex-1 flex-col xl:h-full xl:min-h-0">
      <SectionFrame
        contextLabel="자료 보기 조건"
        context={<DataContextPanel siteId={site.siteId} areas={allAreas} selectedWorkAreaId={selectedWorkAreaId} kinds={kinds}
          q={filters.q} kind={filters.kind} state={filters.state} loadedCount={page?.assets.length ?? null} hasMore={page?.hasMore ?? false} />}
        inspectorLabel="선택한 자료 상세"
        inspector={inspector}
        drawerLabel="등록 진행"
        drawerOpen={first(query.progress) === "1"}
        drawer={<RegistrationProgressPanel siteId={site.siteId} orders={orders} />}
      >
        {main}
      </SectionFrame>
    </div>
  );
}
