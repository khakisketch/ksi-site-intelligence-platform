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

import { SiteNativeExtentSvg } from "./SiteNativeExtentSvg";
import {
  analysesForArea,
  buildAreaCaptureEntries,
  disambiguatedAreaNames,
  disambiguatedAssetHeadlines,
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
function analysisStateLabel(item: AnalysisListItem): string {
  if (item.executionState === "FAILED") return "처리 실패";
  if (item.executionState === "RUNNING") return "처리 중";
  if (item.executionState === "QUEUED") return "처리 대기 중";
  if (item.executionState === "NOT_STARTED") return "처리 시작 전";
  switch (item.suitabilityState) {
    case "EVALUATED": return "판정 기록됨";
    case "BLOCKED": return "분석 불가";
    case "REMEDIATION_REQUIRED": return "보완 필요";
    case "PROVISIONAL_ACCURACY_UNVERIFIED": return "정확도 미확인";
    case "REASSESSMENT_REQUIRED": return "재평가 필요";
    default: return `적합성 ${item.suitabilityState}`;
  }
}

function captureWindowLabel(from: string | null, to: string | null): string {
  if (from && to) {
    return `${formatKoreanDateTime(from, { dateStyle: "medium", timeStyle: "short" })} – ${formatKoreanDateTime(to, { dateStyle: "medium", timeStyle: "short" })}`;
  }
  return "촬영 구간 미기재";
}

/** 봉인 상태의 사람용 이름 — 인증이 아니라 Core 등록 상태의 옮김이다. */
function assetLifecycleLabel(state: string): string {
  if (state === "SEALED") return "봉인됨";
  if (state === "SUPERSEDED") return "대체됨";
  return "미봉인";
}

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
  scopeNotice,
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
  /** 명시된 workAreaId/assetRef 쿼리가 조회 범위 안에 없을 때 한 번만 공지한다. */
  scopeNotice: boolean;
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
  const assetHeadlines = assetsPage ? disambiguatedAssetHeadlines(assetsPage.assets) : new Map<string, { label: string; disambiguated: boolean }>();
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
  const primaryAction = canCreateWorkOrder
    ? { href: `${sitePath}/observations/new`, label: "새 관측 시작" }
    : { href: `${sitePath}/analysis`, label: "현장 분석에서 관측 쌍·근거 확인" };

  return <section aria-label="선택 구역 공간 확인" className="flex flex-col gap-3">
    {scopeNotice && (
      <p className="rounded-lg border border-line bg-surface px-4 py-2.5 text-[12px] leading-5 text-ink-2" role="status">
        요청한 대상을 확인할 수 없어 조회 가능한 구역을 표시합니다. 선택 대상을 확인하세요.
      </p>
    )}
    {areas.length > 0 ? (
      <form method="get" action={sitePath} className="flex flex-wrap items-end gap-2 rounded-lg border border-line bg-surface px-4 py-3">
        <div className="min-w-0 flex-1 basis-56">
          <label htmlFor="site-spatial-area" className="block text-[12px] font-semibold">선택 구역 — 한 번에 하나씩 확인합니다</label>
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
    ) : (
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
            footprintLabel={footprintAsset && footprintOverlaid ? footprintAsset.declared.fileName : null}
            planeUnit={planeUnit}
            vertexCount={ring.length}
            coincident={coincident}
          />}
          <details className="rounded-lg border border-line bg-surface px-4 py-3 text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer font-semibold">배경 지도에서 위치 보기(표시 전용 · 작은 범위는 점으로 보일 수 있음)</summary>
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
                footprintLabel={footprintAsset && footprintOverlaid ? footprintAsset.declared.fileName : null}
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
                      <p className="mt-0.5 text-ink-2">외부 비교 기록 · {entry.detail}</p>
                    </li>;
                  }
                  const item = assetsPage?.assets.find((candidate) => candidate.assetRef === entry.assetRef);
                  const naming = assetHeadlines.get(entry.assetRef);
                  const headline = naming?.disambiguated ? naming.label : displayName(naming?.label ?? entry.headline);
                  const isSelected = selectedAssetRef === entry.assetRef;
                  return <li key={entry.key} className="py-1.5 text-[12px]">
                    <Link
                      href={assetSelectionHref(sitePath, selected.workAreaId, entry.assetRef)}
                      aria-current={isSelected ? "true" : undefined}
                      className={`tap-target block rounded-md px-2 py-1.5 ${isSelected ? "bg-sunk font-semibold" : ""}`}
                    >
                      <span className="block break-all" title={naming?.label ?? entry.headline}>{headline}</span>
                      <span className="mt-0.5 block text-ink-2">{item ? spatialAssetKindLabel(item.kind) : entry.detail} · 촬영 {entry.capturedFrom && entry.capturedTo
                        ? `${formatKoreanDateTime(entry.capturedFrom, { dateStyle: "medium", timeStyle: "short" })} – ${formatKoreanDateTime(entry.capturedTo, { dateStyle: "medium", timeStyle: "short" })}`
                        : "구간 미기재"}{isSelected ? " · 선택 중" : ""}</span>
                    </Link>
                  </li>;
                })}
              </ul>
            )}
            {!assetsPage && <p className="mt-1 text-[11.5px] text-ink-muted">공간 자산 목록 확인 불가 — 외부 비교 기록만 표시합니다.</p>}
            {!areaLegacy && <p className="mt-1 text-[11.5px] text-ink-muted">외부 비교 이력 확인 불가 — 공간 자산만 표시합니다.</p>}
          </>)}
        </div>
      </div>

      <aside className="flex min-w-0 flex-col gap-3" aria-label="선택 범위 상태">
        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <h2 className="break-words text-[14px] font-bold" title={selected.name || selected.workAreaId}>
            {(() => {
              const naming = areaNames.get(selected.workAreaId);
              if (naming?.disambiguated) return naming.label;
              return displayName(naming?.label ?? selected.name ?? selected.workAreaId, 60);
            })()}
          </h2>
          <dl className="mt-2 grid gap-1.5 text-[12px]">
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">상태</dt><dd className="break-words text-right font-semibold">{selected.status === "ACTIVE" ? "사용 중" : "보관됨"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">좌표계</dt><dd className="break-all text-right font-mono">{geometry?.crs ?? "확인 불가"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">등록</dt><dd className="text-right">{formatKoreanDateTime(selected.createdAt, { dateStyle: "medium", timeStyle: "short" })}</dd></div>
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">관측 작업</dt><dd className="text-right font-semibold">{areaOrders === null ? "확인 불가" : `${areaOrders.length}개 연결됨`}</dd></div>
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">분석 결과</dt><dd className="text-right font-semibold">{areaAnalyses === null ? "확인 불가" : `${areaAnalyses.length}개${analysesHasMore ? " · 더 있음" : ""}`}</dd></div>
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">외부 비교 이력</dt><dd className="text-right font-semibold">{areaLegacy === null ? "확인 불가" : `${areaLegacy.length}개${legacyHasMore ? " · 더 있음" : ""}`}</dd></div>
          </dl>
          <details className="mt-2 text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer">구역 식별 정보</summary>
            <p className="mt-1 break-all font-mono">{selected.workAreaId}</p>
            {selected.supersedes && <p className="mt-1 break-all font-mono">대체 전 구역 · {selected.supersedes}</p>}
          </details>
        </div>

        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <h3 className="text-[13px] font-bold">선택된 자료</h3>
          {assetsState.status === "denied" && (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">공간 자산을 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요.</p>
          )}
          {assetsState.status === "unavailable" && (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">공간 자산을 일시적으로 불러오지 못했습니다.</p>
          )}
          {assetsState.status === "ready" && assetsPage && (
            selectedAsset ? <>
              <p className="mt-1 break-all text-[12px] font-semibold" aria-live="polite">{assetHeadlines.get(selectedAsset.assetRef)?.label ?? `${selectedAsset.declared.fileName} · rev ${selectedAsset.revision}`}</p>
              <p className="mt-0.5 text-[12px] text-ink-2">{spatialAssetKindLabel(selectedAsset.kind)} · {assetLifecycleLabel(selectedAsset.lifecycleState)} · 촬영 {captureWindowLabel(selectedAsset.declared.captureStartedAt, selectedAsset.declared.captureEndedAt)}</p>
              <p className="mt-0.5 text-[12px] text-ink-2">{!selectedAsset.inspection?.raster
                ? "검사된 footprint가 없어 경계만 표시합니다"
                : footprintOverlaid
                  ? "검사된 footprint를 평면에 표시합니다"
                  : "검사된 footprint의 기하·좌표계를 함께 표시할 수 없어 작업구역 경계만 표시합니다"}</p>
              <Link
                href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(selected.workAreaId)}&assetRef=${encodeURIComponent(selectedAsset.assetRef)}`}
                className="tap-target mt-0.5 inline-block text-[12px] underline"
              >
                메타데이터 보기
              </Link>
            </> : assetsPage.assets.length === 0 ? (
              <p className="mt-1 text-[12px] leading-5 text-ink-2">이 구역에 조회된 공간 자산이 없습니다.</p>
            ) : (
              <p className="mt-1 text-[12px] leading-5 text-ink-2">왼쪽 목록에서 자료를 선택하세요.</p>
            )
          )}
        </div>

        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <h3 className="text-[13px] font-bold">분석 결과</h3>
          {!analysesKnown ? (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">분석 기록을 확인할 수 없습니다.</p>
          ) : !latestAnalysis ? (
            <p className="mt-1 text-[12px] leading-5 text-ink-2">이 구역에 조회된 분석 결과가 없습니다.</p>
          ) : (<>
            <p className="mt-1 text-[12px] font-semibold">{analysisStateLabel(latestAnalysis)}</p>
            <p className="mt-0.5 text-[12px] text-ink-2">기록 {formatKoreanDateTime(latestAnalysis.createdAt, { dateStyle: "medium", timeStyle: "short" })}{latestAnalysis.limitationCount > 0 ? ` · 제한 ${latestAnalysis.limitationCount}건` : ""}</p>
            <p className="mt-1 flex flex-wrap gap-x-3 text-[12px]">
              <Link href={latestAnalysis.analysisHref} className="tap-target inline-block underline">이 결과 열기</Link>
              <Link href={`${sitePath}/analysis`} className="tap-target inline-block underline">결과 {areaAnalyses?.length ?? 0}개 모두 보기</Link>
            </p>
          </>)}
        </div>

        <nav className="flex flex-col gap-2" aria-label="선택 구역 다음 확인">
          <Link href={primaryAction.href} className="btn btn-primary w-fit">{primaryAction.label}</Link>
          <p className="flex flex-wrap gap-x-3 text-[12px]">
            <Link href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="tap-target underline">이 구역의 공간 자산</Link>
            <Link href={`${sitePath}/observations`} className="tap-target underline">외부 관측 이력</Link>
          </p>
        </nav>
      </aside>
    </div>}
  </section>;
}
