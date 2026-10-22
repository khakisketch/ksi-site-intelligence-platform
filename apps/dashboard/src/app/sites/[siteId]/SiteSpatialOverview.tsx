import Link from "next/link";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import type { AnalysisListItem } from "@/lib/core-api/analysis";
import type { ExternalRelativeVolumeHistoryItem } from "@/lib/core-api/external-result-workflow";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";
import type { SpatialAssetCatalogPage } from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { toDisplayVertices } from "@/lib/geo/display-geometry";
import { spatialAssetKindLabel } from "@/lib/human-labels";
import { assetBusinessTitles, assetLifecycleLabel, registrationVersionLabel } from "@/lib/operator-language";

import { SiteNativeExtentSvg } from "./SiteNativeExtentSvg";
import { SiteAreaNextActionNav, resolveSiteAreaNextAction } from "./SiteAreaNextAction";
import {
  analysesForArea,
  buildAreaCaptureEntries,
  disambiguatedAreaNames,
  displayName,
  extractSimpleRing,
  legacyRowsForArea,
  ordersForArea,
  parseFootprintWkt,
  pickFootprintAsset,
  planeUnitForCrs,
  ringsCoincident,
  sameDisplayPlane,
  selectableGeometry,
} from "./site-spatial";

export type SiteSpatialAssetsState =
  | { status: "ready"; page: SpatialAssetCatalogPage }
  | { status: "denied" }
  | { status: "unavailable" }
  | { status: "not-requested" };

function assetSelectionHref(sitePath: string, workAreaId: string, assetRef: string): string {
  return `${sitePath}?workAreaId=${encodeURIComponent(workAreaId)}&assetRef=${encodeURIComponent(assetRef)}`;
}

/** 서버 상태 코드를 사람 말로만 옮긴다 — 원 코드를 바꾸거나 판정하지 않는다. */
export function analysisStateLabel(item: Pick<AnalysisListItem, "executionState" | "suitabilityState">): string {
  if (item.executionState === "FAILED") return "처리 실패";
  if (item.executionState === "RUNNING") return "처리 중";
  if (item.executionState === "QUEUED") return "처리 대기 중";
  if (item.executionState === "NOT_STARTED") return "처리 시작 전";
  switch (item.suitabilityState) {
    case "EVALUATED": return "분석 조건 확인 결과 있음";
    case "BLOCKED": return "분석을 진행할 수 없음";
    case "REMEDIATION_REQUIRED": return "자료 보완 필요";
    case "PROVISIONAL_ACCURACY_UNVERIFIED": return "정확도 미확인";
    case "REASSESSMENT_REQUIRED": return "사용 조건 재확인 필요";
    default: return "분석 조건 확인 필요";
  }
}

/** 봉인 상태의 사람용 이름 — 인증이 아니라 Core 등록 상태의 옮김이다. */
/**
 * 현장 기본 탭의 읽기 전용 공간 확인 — 선택한 구역 하나를 눈으로 검증하는 자리.
 *
 * 왼쪽 넓은 칸에 실제 기하(작으면 원본 평면이 먼저, 크면 배경 지도가 먼저)와
 * 바로 아래 촬영 시점·자료 선택 목록을 둔다. 오른쪽 좁은 칸에는 선택 범위·선택
 * 파일·최신 분석 하나·다음 행동만 둔다. 바꾸는 조작은 없다.
 */
export function SiteSpatialOverview({
  sitePath,
  areas,
  areasKnown,
  orders,
  analyses,
  analysesKnown,
  analysesHasMore,
  legacy,
  legacyHasMore,
  assetsState,
  selectedWorkAreaId,
  selectedAssetRef,
  canCreateWorkOrder,
  canCreateAnalysis,
  scopeNotice,
  hideAreaForm = false,
}: {
  sitePath: string;
  areas: WorkArea[];
  areasKnown: boolean;
  orders: ObservationWorkOrderView[] | null;
  analyses: AnalysisListItem[] | null;
  analysesKnown: boolean;
  analysesHasMore: boolean;
  legacy: ExternalRelativeVolumeHistoryItem[] | null;
  legacyHasMore: boolean;
  assetsState: SiteSpatialAssetsState;
  selectedWorkAreaId: string | null;
  selectedAssetRef: string | null;
  canCreateWorkOrder: boolean;
  /** SITES_WRITE — WORK_ORDERS_WRITE와 같은 것으로 보지 않는다. 비교 요청 진입에만 쓴다. */
  canCreateAnalysis: boolean;
  /** 명시된 workAreaId/assetRef 쿼리가 조회 범위 안에 없을 때 한 번만 공지한다. */
  scopeNotice: boolean;
  /** 탐색 첫 화면의 작업 막대가 구역 선택을 맡을 때 true — 중복 상자를 숨긴다. */
  hideAreaForm?: boolean;
}) {
  if (!areasKnown) {
    return <section aria-label="선택 구역 공간 확인" className="rounded-lg border border-line bg-surface px-4 py-3">
      <h2 className="text-[14px] font-bold">선택 구역 공간 확인</h2>
      <div className="mt-2"><ErrorState message="작업구역 목록을 불러오지 못했습니다. 공간 확인은 목록을 읽은 뒤에 가능합니다." retryable /></div>
    </section>;
  }

  const activeAreas = areas.filter((area) => area.status === "ACTIVE");
  const selected = areas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null;
  const geometry = selected ? selectableGeometry(selected) : null;
  // 이름 충돌은 전체 id를 덧붙여 가른다 — 번호를 지어내지 않는다.
  const areaNames = disambiguatedAreaNames(areas);

  const display = geometry ? toDisplayVertices(geometry.polygon, geometry.crs) : null;
  const ring = geometry ? extractSimpleRing(geometry.polygon) : null;
  // 아는 투영좌표계만 미터 단위로 잰다. 모르는 CRS는 단위를 단정하지 않는다.
  const planeUnit = geometry ? planeUnitForCrs(geometry.crs) : "unknown" as const;

  const assetsPage = assetsState.status === "ready" ? assetsState.page : null;
  const assetHeadlines = assetsPage ? assetBusinessTitles(assetsPage.assets) : new Map<string, string>();
  const selectedAsset = assetsPage
    ? (selectedAssetRef ? assetsPage.assets.find((item) => item.assetRef === selectedAssetRef) ?? null : null)
    : null;
  const footprintAsset = assetsPage ? pickFootprintAsset(assetsPage.assets, selectedAssetRef) : null;
  const footprintRing = footprintAsset?.inspection?.raster
    ? parseFootprintWkt(footprintAsset.inspection.raster.footprintWkt)
    : null;
  const footprintOverlaid = footprintAsset && footprintRing && geometry
    ? sameDisplayPlane(geometry.crs, footprintAsset.inspection.raster?.observedCrsIdentifier ?? "")
    : false;
  const coincident = Boolean(footprintOverlaid && footprintRing && ring && ringsCoincident(ring, footprintRing));
  // OSM 축척에서 점으로만 보이는 작은 범위는 원본 평면을 먼저 둔다(미터 단위일 때만).
  const metricSpan = ring && planeUnit === "meters"
    ? Math.max(...ring.map(([x]) => x)) - Math.min(...ring.map(([x]) => x))
    : null;
  const nativePrimary = ring !== null && (!display || !display.ok || (metricSpan !== null && metricSpan < 2000));

  const areaOrders = selected ? ordersForArea(orders, selected.workAreaId) : null;
  const areaAnalyses = selected ? analysesForArea(analyses, selected.workAreaId) : null;
  const areaLegacy = selected ? legacyRowsForArea(legacy, selected.workAreaId) : null;
  // 아는 출처는 실패한 쪽과 무관하게 그대로 둔다 — unknown은 별도 공지로만 둔다.
  const captureEntries = selected
    ? buildAreaCaptureEntries({ assets: assetsPage?.assets ?? null, legacyRows: areaLegacy })
    : [];
  const latestAnalysis = areaAnalyses?.[0] ?? null;
  const canRegisterHere = canCreateWorkOrder && selected?.status === "ACTIVE";
  const canCompareHere = canCreateAnalysis && selected?.status === "ACTIVE";
  // 다음 행동 계산은 탐색 첫 화면과 공유한다 — 같은 구역에서 서로 다른
  // 행동을 제안하지 않는다.
  const nextAction = selected
    ? resolveSiteAreaNextAction({
      sitePath,
      workAreaId: selected.workAreaId,
      workAreaStatus: selected.status,
      canCreateWorkOrder,
      canCreateAnalysis,
      latestAnalysis: latestAnalysis
        ? { workAreaId: latestAnalysis.workAreaId, analysisId: latestAnalysis.analysisId }
        : null,
    })
    : null;

  return <section aria-label="선택 구역 공간 확인" className="flex flex-col gap-3">
    {scopeNotice && (
      <p className="rounded-lg border border-line bg-surface px-4 py-2.5 text-[12px] leading-5 text-ink-2" role="status">
        요청한 대상을 확인할 수 없어 조회 가능한 구역을 표시합니다. 선택 대상을 확인하세요.
      </p>
    )}
    {areas.length > 0 ? (hideAreaForm ? null : (
      <form method="get" action={sitePath} className="flex flex-wrap items-end gap-2 rounded-lg border border-line bg-surface px-4 py-3">
        <div className="min-w-0 flex-1 basis-56">
        <label htmlFor="site-spatial-area" className="block text-[12px] font-semibold">확인할 작업구역 선택</label>
          <select
            id="site-spatial-area"
            name="workAreaId"
            defaultValue={selected?.workAreaId ?? ""}
            className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]"
          >
            {areas.map((area) => {
              const naming = areaNames.get(area.workAreaId) ?? { label: area.name || area.workAreaId, disambiguated: false };
              return <option key={area.workAreaId} value={area.workAreaId} title={naming.disambiguated ? naming.label : (area.name || area.workAreaId)}>
                {naming.disambiguated ? naming.label : displayName(naming.label)}{area.status === "ARCHIVED" ? " · 보관됨" : ""}
              </option>;
            })}
          </select>
        </div>
        <button type="submit" className="btn">구역 보기</button>
        {activeAreas.length === 0 && (
          <p className="w-full text-[12px] text-ink-2">현재 고를 수 있는(ACTIVE) 구역이 없습니다. 보관된 구역의 기록은 그대로 둡니다.</p>
        )}
      </form>
    )) : (
      <EmptyState
        title="등록된 작업구역이 없습니다"
        description="작업구역이 등록되면 이 자리에서 모양과 자료 범위를 확인할 수 있습니다."
        action={{ label: "작업구역 확인", href: `${sitePath}/work-areas` }}
      />
    )}

    {selected === null && areas.length > 0 && (
      <EmptyState
        title="등록된 작업구역이 없습니다"
        description="작업구역이 등록되면 이 자리에서 모양과 자료 범위를 확인할 수 있습니다. 구역 설정은 작업구역 관리에서 합니다."
      />
    )}

    {selected && <div className="grid gap-4 lg:grid-cols-3">
      <div className="flex min-w-0 flex-col gap-3 lg:col-span-2">
        <h2 className="sr-only">선택 구역 지도</h2>
        {nativePrimary ? <>
          {ring && <SiteNativeExtentSvg
            boundary={ring}
            footprint={footprintOverlaid && footprintRing ? footprintRing : null}
            crsLabel={geometry?.crs ?? "확인 불가"}
            footprintLabel={footprintAsset && footprintOverlaid ? assetHeadlines.get(footprintAsset.assetRef) ?? null : null}
            planeUnit={planeUnit}
            vertexCount={ring.length}
            coincident={coincident}
          />}
          <details className="rounded-lg border border-line bg-surface px-4 py-3 text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer font-semibold">배경 지도에서 위치 확인</summary>
            <div className="mt-2">
              {display && display.ok ? (
                <AoiPolygonMap value={display.vertices} readOnly />
              ) : (
                <p className="text-[12.5px] leading-5">{display ? display.reason : "이 구역의 기하를 읽지 못했습니다."} 지도에 올리지 않았습니다.</p>
              )}
            </div>
          </details>
        </> : <>
          {display && display.ok ? (
            <AoiPolygonMap value={display.vertices} readOnly />
          ) : (
            <div className="rounded-lg border border-line bg-surface px-4 py-3">
              <p className="text-[12.5px] leading-5 text-ink-2">
                {display ? display.reason : "이 구역의 기하를 읽지 못했습니다."} 지도에 올리지 않았습니다.
              </p>
            </div>
          )}
          {ring && <details className="rounded-lg border border-line bg-surface px-4 py-3 text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer font-semibold">원본 좌표 평면 보기(표시 전용 벡터 범위)</summary>
            <div className="mt-2">
              <SiteNativeExtentSvg
                boundary={ring}
                footprint={footprintOverlaid && footprintRing ? footprintRing : null}
                crsLabel={geometry?.crs ?? "확인 불가"}
                footprintLabel={footprintAsset && footprintOverlaid ? assetHeadlines.get(footprintAsset.assetRef) ?? null : null}
                planeUnit={planeUnit}
                vertexCount={ring.length}
                coincident={coincident}
              />
            </div>
          </details>}
        </>}

        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <h2 className="text-[13px] font-bold">촬영 시점 · 자료 선택</h2>
          {!assetsPage && !areaLegacy ? (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">촬영 시점·출처를 확인할 수 없습니다.</p>
          ) : (<>
            {captureEntries.length === 0 && (
              <p className="mt-1 text-[12px] leading-5 text-ink-2">{assetsPage && areaLegacy
                ? "조회된 자산·외부 비교 기록이 없습니다."
                : "확인 가능한 출처에 촬영 기록이 없습니다. 조회하지 못한 출처의 자료는 판단하지 않습니다."}</p>
            )}
            {captureEntries.length > 0 && (
              <ul className="mt-1 divide-y divide-line">
                {captureEntries.map((entry) => {
                  if (entry.source !== "asset" || !entry.assetRef) {
                    return <li key={entry.key} className="px-2 py-1.5 text-[12px]">
                      <p className="break-all font-semibold">{entry.headline}</p>
                      <p className="mt-0.5 text-ink-2">{entry.detail}</p>
                      {entry.reportRef && <details className="mt-1 text-ink-2"><summary className="tap-target cursor-pointer">결과 등록 정보</summary><p className="break-all font-mono">{entry.reportRef}</p><Link className="tap-target inline-block underline" href={`${sitePath}/observations/${encodeURIComponent(entry.reportRef)}`}>외부 비교 결과 열기</Link></details>}
                    </li>;
                  }
                  const item = assetsPage?.assets.find((candidate) => candidate.assetRef === entry.assetRef);
                  const headline = assetHeadlines.get(entry.assetRef) ?? entry.headline;
                  const isSelected = selectedAssetRef === entry.assetRef;
                  return <li key={entry.key} className="py-1.5 text-[12px]">
                    <Link
                      href={assetSelectionHref(sitePath, selected.workAreaId, entry.assetRef)}
                      aria-current={isSelected ? "true" : undefined}
                      className={`tap-target block rounded-md px-2 py-1.5 ${isSelected ? "bg-sunk font-semibold" : ""}`}
                    >
                      <span className="block break-words">{headline}</span>
                      <span className="mt-0.5 block text-ink-2">{item ? assetLifecycleLabel(item.lifecycleState) : entry.detail}{isSelected ? " · 선택 중" : ""}</span>
                    </Link>
                  </li>;
                })}
              </ul>
            )}
            {!assetsPage && <p className="mt-1 text-[11.5px] text-ink-muted">등록 자료를 조회하지 못했습니다. 확인 가능한 외부 비교 기록만 표시합니다.</p>}
            {!areaLegacy && <p className="mt-1 text-[11.5px] text-ink-muted">외부 비교 기록을 조회하지 못했습니다. 확인 가능한 등록 자료만 표시합니다.</p>}
          </>)}
        </div>
      </div>

      <aside className="flex min-w-0 flex-col gap-3" aria-label="선택 범위 상태">
        {/* 다음 행동이 칸의 첫 자리다 — 개수·식별자는 아래 펼침에 둔다. */}
        <SiteAreaNextActionNav
          sitePath={sitePath}
          workAreaId={selected.workAreaId}
          action={nextAction ?? { primary: { href: sitePath, label: "변화 분석 보기" }, secondaryRegisterHref: null, secondaryCompareHref: null }}
          archived={selected.status === "ARCHIVED"}
          canRegisterOrCompare={canRegisterHere || canCompareHere}
        />

        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <h3 className="text-[13px] font-bold">선택된 자료</h3>
          {assetsState.status === "denied" && (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">등록 자료를 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요.</p>
          )}
          {assetsState.status === "unavailable" && (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">등록 자료를 불러오지 못했습니다. 잠시 후 다시 확인하세요.</p>
          )}
          {assetsState.status === "ready" && assetsPage && (
            selectedAsset ? <>
              <p className="mt-1 break-words text-[13px] font-semibold" aria-live="polite">{assetHeadlines.get(selectedAsset.assetRef) ?? spatialAssetKindLabel(selectedAsset.kind)}</p>
              <p className="mt-0.5 text-[12px] text-ink-2">{assetLifecycleLabel(selectedAsset.lifecycleState)}</p>
              <p className="mt-0.5 text-[12px] text-ink-2">{!selectedAsset.inspection?.raster
                ? "파일의 포함 범위를 확인하지 못해 작업구역만 표시합니다."
                : footprintOverlaid
                  ? "선택한 파일이 포함하는 범위를 함께 표시합니다."
                  : "위치 기준이 맞지 않아 파일 범위를 겹쳐 표시하지 않았습니다."}</p>
              <details className="mt-1 text-[12px] text-ink-2">
                <summary className="tap-target cursor-pointer">파일 정보</summary>
                <p className="mt-1 break-all">등록 파일명 · {selectedAsset.declared.fileName}</p>
                <p className="mt-1">{registrationVersionLabel(selectedAsset.revision)}</p>
                <p className="mt-1">제출한 자료 묶음의 버전이며, 촬영 횟수와는 다릅니다.</p>
                <p className="mt-1">등록 종류 · {selectedAsset.kind}</p>
                <p className="mt-1">파일 제출 상태 코드 · {selectedAsset.lifecycleState}</p>
                <p className="mt-1 break-all font-mono">자료 식별자 · {selectedAsset.assetRef}</p>
              </details>
              <Link
                href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(selected.workAreaId)}&assetRef=${encodeURIComponent(selectedAsset.assetRef)}`}
                className="tap-target mt-0.5 inline-block text-[12px] underline"
              >
                파일 등록 정보 열기
              </Link>
            </> : assetsPage.assets.length === 0 ? (
              <p className="mt-1 text-[12px] leading-5 text-ink-2">이 구역에 조회된 등록 자료가 없습니다.</p>
            ) : (
              <p className="mt-1 text-[12px] leading-5 text-ink-2">왼쪽 목록에서 자료를 선택하세요.</p>
            )
          )}
        </div>

        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <h3 className="text-[13px] font-bold">이 구역의 최근 분석</h3>
          {!analysesKnown ? (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">분석 기록을 확인할 수 없습니다.</p>
          ) : !latestAnalysis ? (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">이 구역에 조회된 분석 결과가 없습니다.</p>
          ) : (<>
            <p className="mt-1 text-[12px] font-semibold">{analysisStateLabel(latestAnalysis)}</p>
            <p className="mt-0.5 text-[12px] text-ink-2">기록 {formatKoreanDateTime(latestAnalysis.createdAt, { dateStyle: "medium", timeStyle: "short" })}{latestAnalysis.limitationCount > 0 ? ` · 제한 ${latestAnalysis.limitationCount}건` : ""}</p>
            <p className="mt-1 flex flex-wrap gap-x-3 text-[12px]">
              <Link
                href={selected.status === "ACTIVE"
                  ? `${sitePath}/analysis?workAreaId=${encodeURIComponent(selected.workAreaId)}`
                  : `${sitePath}/analysis`}
                className="tap-target inline-block underline"
              >
                현장 분석 기록 보기
              </Link>
            </p>
          </>)}
        </div>

        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <h3 className="text-[13px] font-bold">선택한 작업구역</h3>
          <p className="mt-1 text-[12px]"><span className="text-ink-muted">상태 · </span><span className="font-semibold">{selected.status === "ACTIVE" ? "사용 중" : "보관됨"}</span></p>
          <details className="mt-1 text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer">구역 등록 정보·개수</summary>
            <p className="mt-1 break-words">등록된 구역명 · {areaNames.get(selected.workAreaId)?.label ?? selected.name}</p>
            <p className="mt-1">관측 작업 · {areaOrders === null ? "확인 불가" : `${areaOrders.length}개 연결됨`}</p>
            <p className="mt-1">분석 결과 · {areaAnalyses === null ? "확인 불가" : `${areaAnalyses.length}개${analysesHasMore ? " · 더 있음" : ""}`}</p>
            <p className="mt-1">등록 · {formatKoreanDateTime(selected.createdAt, { dateStyle: "medium", timeStyle: "short" })}</p>
            <p className="mt-1">좌표계 · {geometry?.crs ?? "확인 불가"}</p>
            <p className="mt-1">외부 비교 기록 · {areaLegacy === null ? "확인 불가" : `${areaLegacy.length}건${legacyHasMore ? " · 더 있음" : ""}`}</p>
            <p className="mt-1 break-all font-mono">{selected.workAreaId}</p>
            {selected.supersedes && <p className="mt-1 break-all font-mono">대체 전 구역 · {selected.supersedes}</p>}
          </details>
        </div>
      </aside>
    </div>}
  </section>;
}
