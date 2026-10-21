import Link from "next/link";

import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";
import { capturePeriodTitle, dataKindLabel } from "@/lib/operator-language";
import { formatKoreanDate } from "@/lib/datetime";
import { spatialAssetKindLabel } from "@/lib/human-labels";
import type {
  ExplicitComparisonResolution,
  WorkspaceObservationFact,
  WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";
import { workspaceCaptureLine } from "@/lib/site-workspace-entry";
import { SiteNativeExtentSvg } from "./SiteNativeExtentSvg";
import type { SiteSpatialAssetsState } from "./SiteSpatialOverview";
import {
  disambiguatedAreaNames,
  extractSimpleRing,
  parseFootprintWkt,
  planeUnitForCrs,
  ringsCoincident,
  sameDisplayPlane,
  selectableGeometry,
} from "./site-spatial";

function factByRef(
  assets: readonly SpatialAssetCatalogItem[],
  assetRef: string,
): SpatialAssetCatalogItem | null {
  return assets.find((item) => item.assetRef === assetRef) ?? null;
}

function precisionNote(fact: WorkspaceObservationFact): string {
  return workspaceCaptureLine(fact, {
    intervalTitle: (startedAt, endedAt) => capturePeriodTitle(startedAt, endedAt),
    calendarDate: (date) => formatKoreanDate(date),
  });
}

/** 선택지 표기 — 선언된 정밀도 그대로. 날짜만 아는 항목은 날짜+시각 미상으로, 미상은 날짜를 그리지 않는다. */
function candidateOptionLabel(
  item: SpatialAssetCatalogItem,
  fact: WorkspaceObservationFact | null,
): string {
  const line = fact
    ? precisionNote(fact)
    : capturePeriodTitle(item.declared.captureStartedAt, item.declared.captureEndedAt);
  return `${dataKindLabel(item.kind)} · ${line} · 등록 버전 ${item.revision}`;
}

function CompareSlot({
  slotLabel,
  sitePath,
  workAreaId,
  ring,
  areaCrs,
  planeUnit,
  coincident,
  assets,
  fact,
  emptyNote,
}: {
  slotLabel: "기준 자료" | "비교 자료";
  sitePath: string;
  workAreaId: string;
  ring: Array<[number, number]> | null;
  areaCrs: string;
  planeUnit: ReturnType<typeof planeUnitForCrs>;
  coincident: (footprint: Array<[number, number]>) => boolean;
  assets: readonly SpatialAssetCatalogItem[];
  fact: WorkspaceObservationFact | null;
  emptyNote: string;
}) {
  const item = fact ? factByRef(assets, fact.assetRef) : null;
  const footprintRing = item?.inspection?.raster ? parseFootprintWkt(item.inspection.raster.footprintWkt) : null;
  const overlaid = Boolean(
    footprintRing && ring && item?.inspection?.raster &&
      sameDisplayPlane(areaCrs, item.inspection.raster.observedCrsIdentifier),
  );
  const raster = item?.inspection?.raster ?? null;
  return <section aria-label={slotLabel} className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface px-3 py-3">
    <h3 className="text-[13.5px] font-bold">{slotLabel}</h3>
    {!fact || !item ? (
      <p className="text-[12.5px] leading-5 text-ink-2">{emptyNote}</p>
    ) : (<>
      {/* 제목은 선언된 정밀도 그대로 — 날짜만 아는 항목을 구간 미기재로 뭉개지 않는다. */}
      <p className="break-words text-[13px] font-semibold">{dataKindLabel(item.kind)} · {precisionNote(fact)}</p>
      <p className="text-[12px] text-ink-2">등록 버전 {fact.revision} · {spatialAssetKindLabel(item.kind)}</p>
      {ring ? (
        <SiteNativeExtentSvg
          boundary={ring}
          footprint={overlaid && footprintRing ? footprintRing : null}
          crsLabel={areaCrs}
          footprintLabel={overlaid ? `${dataKindLabel(item.kind)} · ${precisionNote(fact)}` : null}
          planeUnit={planeUnit}
          vertexCount={ring.length}
          coincident={footprintRing ? coincident(footprintRing) : false}
        />
      ) : (
        <p className="text-[12.5px] leading-5 text-ink-2">구역 기하를 읽지 못해 범위를 그리지 않았습니다.</p>
      )}
      {footprintRing && !overlaid && (
        <p className="text-[12px] leading-5 text-ink-2">위치 기준이 맞지 않아 파일 범위를 겹쳐 표시하지 않았습니다.</p>
      )}
      <dl className="grid gap-1 text-[12px] text-ink-2">
        <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">자료 격자</dt><dd className="text-right">{raster ? `${raster.width} × ${raster.height}` : "확인 불가"}</dd></div>
        <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">관측 위치 기준</dt><dd className="break-words text-right">{raster?.observedCrsIdentifier ?? "확인 불가"}</dd></div>
        <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">수직 기준</dt><dd className="text-right">{raster?.observedVerticalReference ? raster.observedVerticalReference.identifier : "확인 불가"}</dd></div>
      </dl>
      <details className="text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer">파일 정보</summary>
        <p className="mt-1 break-all">등록 파일명 · {item.declared.fileName}</p>
        <p className="mt-1 break-all font-mono">자료 식별자 · {item.assetRef}</p>
      </details>
      <p><Link href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(workAreaId)}&assetRef=${encodeURIComponent(item.assetRef)}`} className="tap-target inline-block text-[12px] underline">파일 등록 정보 열기</Link></p>
    </>)}
  </section>;
}

/**
 * 비교 모드 — 두 개의 동등한 지도 자리 + 정직한 미지원 고지.
 *
 * - 두 자리는 같은 무게다. 한쪽이 썸네일이 되지 않는다.
 * - 같은 화면 맞춤·같은 색 눈금·위치 맞춤(정합)은 확인된 바 없으므로 보장하지
 *   않는다고 밝힌다. 어림 겹침·WGS84 재해석·자동 늘이기로 높낮이 차이를
 *   암시하지 않는다.
 * - 바이트 보기는 이 화면에서 열지 않고, 기존의 권한 확인된 준비·다운로드 경로로만
 *   연결한다.
 */
export function SiteWorkspaceCompare({
  sitePath,
  areas,
  selectedWorkAreaId,
  assetsState,
  baselineRequestedRef,
  currentRequestedRef,
  resolution,
  canCreateAnalysis,
  scopedCompareHref,
  facts,
}: {
  sitePath: string;
  areas: WorkArea[];
  selectedWorkAreaId: string | null;
  assetsState: SiteSpatialAssetsState;
  baselineRequestedRef: string | null;
  currentRequestedRef: string | null;
  resolution: ExplicitComparisonResolution | { status: "prompt" };
  canCreateAnalysis: boolean;
  scopedCompareHref: string;
  facts: WorkspaceServerFacts;
}) {
  const selected = areas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null;
  const areaLabel = selected
    ? (disambiguatedAreaNames(areas).get(selected.workAreaId)?.label ?? selected.workAreaId)
    : null;
  const geometry = selected ? selectableGeometry(selected) : null;
  const ring = geometry ? extractSimpleRing(geometry.polygon) : null;
  const planeUnit = geometry ? planeUnitForCrs(geometry.crs) : ("unknown" as const);
  const areaCrs = geometry?.crs ?? "확인 불가";
  const coincident = (footprint: Array<[number, number]>) =>
    Boolean(ring && ringsCoincident(ring, footprint));

  const assetsPage = assetsState.status === "ready" ? assetsState.page : null;
  const viewableAssets = (assetsPage?.assets ?? []).filter((item) => item.inspection?.raster);
  const hiddenCount = (assetsPage?.assets ?? []).length - viewableAssets.length;
  const baselineFact = resolution.status === "ready" ? resolution.baseline : null;
  const currentFact = resolution.status === "ready" ? resolution.current : null;
  const baselineItem = baselineFact && assetsPage ? factByRef(assetsPage.assets, baselineFact.assetRef) : null;
  const currentItem = currentFact && assetsPage ? factByRef(assetsPage.assets, currentFact.assetRef) : null;
  const samePlane = Boolean(
    baselineItem?.inspection?.raster && currentItem?.inspection?.raster &&
      sameDisplayPlane(
        baselineItem.inspection.raster.observedCrsIdentifier,
        currentItem.inspection.raster.observedCrsIdentifier,
      ),
  );
  const verticalUnknown = resolution.status === "ready" && (
    !baselineItem?.inspection?.raster?.observedVerticalReference ||
    !currentItem?.inspection?.raster?.observedVerticalReference
  );
  const formAction = selected ? `${sitePath}?` : sitePath;

  return <div className="flex flex-col gap-3">
    {selected === null && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
        비교할 작업구역이 없습니다. 작업구역이 등록되면 같은 구역의 두 자료를 나란히 둘 수 있습니다.
      </p>
    )}
    {selected && (
      <p className="text-[12.5px] leading-5 text-ink-2">
        {areaLabel} · 같은 구역의 기준 자료와 비교 자료를 나란히 둡니다.
      </p>
    )}
    {resolution.status === "unresolvable" && (
      <div role="alert" className="rounded-lg border border-line bg-surface px-4 py-3">
        <p className="text-[13px] font-bold">{resolution.headline}</p>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">{resolution.detail}</p>
        <p className="mt-2 flex flex-wrap gap-x-3 text-[12px]">
          <Link href={`${sitePath}/spatial-assets${selected ? `?workAreaId=${encodeURIComponent(selected.workAreaId)}` : ""}`} className="tap-target underline">자료 목록 보기</Link>
          <Link href={sitePath} className="tap-target underline">탐색으로 돌아가기</Link>
        </p>
      </div>
    )}
    {resolution.status === "prompt" && selected && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
        비교할 기준 자료와 비교 자료를 아래에서 고르세요. 자동으로 고르지 않았습니다.
      </p>
    )}

    {selected && assetsState.status === "denied" && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
        등록 자료를 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요.
      </p>
    )}
    {selected && assetsState.status === "unavailable" && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
        등록 자료를 불러오지 못했습니다. 잠시 후 다시 확인하세요.
      </p>
    )}

    {selected && assetsState.status === "ready" && assetsPage && (
      <form method="get" action={formAction} className="flex flex-wrap items-end gap-2 rounded-lg border border-line bg-surface px-4 py-3">
        <input type="hidden" name="mode" value="compare" />
        <input type="hidden" name="workAreaId" value={selected.workAreaId} />
        <div className="min-w-0 flex-1 basis-56">
          <label htmlFor="workspace-compare-baseline" className="block text-[12px] font-semibold">기준 자료</label>
          <select id="workspace-compare-baseline" name="baselineAssetRef" required defaultValue={baselineRequestedRef ?? ""} className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]">
            <option value="">기준 자료 선택</option>
            {viewableAssets.map((item) => (
              <option key={item.assetRef} value={item.assetRef}>{candidateOptionLabel(item, facts.observations.find((fact) => fact.assetRef === item.assetRef) ?? null)}</option>
            ))}
          </select>
        </div>
        <div className="min-w-0 flex-1 basis-56">
          <label htmlFor="workspace-compare-current" className="block text-[12px] font-semibold">비교 자료</label>
          <select id="workspace-compare-current" name="currentAssetRef" required defaultValue={currentRequestedRef ?? ""} className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]">
            <option value="">비교 자료 선택</option>
            {viewableAssets.map((item) => (
              <option key={item.assetRef} value={item.assetRef}>{candidateOptionLabel(item, facts.observations.find((fact) => fact.assetRef === item.assetRef) ?? null)}</option>
            ))}
          </select>
        </div>
        <button type="submit" className="btn">나란히 보기</button>
        {hiddenCount > 0 && (
          <p className="w-full text-[12px] text-ink-2">표시할 수 없는 자료 {hiddenCount}건은 선택지에 두지 않았습니다.</p>
        )}
      </form>
    )}

    {selected && <div className="grid gap-4 md:grid-cols-2">
      <CompareSlot
        slotLabel="기준 자료"
        sitePath={sitePath}
        workAreaId={selected.workAreaId}
        ring={ring}
        areaCrs={areaCrs}
        planeUnit={planeUnit}
        coincident={coincident}
        assets={assetsPage?.assets ?? []}
        fact={baselineFact}
        emptyNote="기준 자료를 아직 고르지 않았습니다. 위에서 직접 고르세요."
      />
      <CompareSlot
        slotLabel="비교 자료"
        sitePath={sitePath}
        workAreaId={selected.workAreaId}
        ring={ring}
        areaCrs={areaCrs}
        planeUnit={planeUnit}
        coincident={coincident}
        assets={assetsPage?.assets ?? []}
        fact={currentFact}
        emptyNote="비교 자료를 아직 고르지 않았습니다. 위에서 직접 고르세요."
      />
    </div>}

    {selected && <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <h3 className="text-[13px] font-bold">나란히 보기 안내</h3>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        두 지도는 같은 크기로 나란히 둡니다. 동기화된 공간 비교(같은 범위 맞춤·같은 색 눈금)는 지원하지 않습니다.
        두 자료의 위치 맞춤이 확인되지 않아 같은 범위를 가리킨다고 보장하지 않으며, 화면을 겹쳐도 분석 근거가 되지 않습니다.
      </p>
      {resolution.status === "ready" && (
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
          {samePlane
            ? "두 자료는 같은 위치 기준 표기입니다. 그래도 화면 맞춤이 실제 지형 일치를 뜻하지 않으며, 높낮이 차이로 읽지 마세요."
            : "두 자료의 위치 기준 표기가 달라 같은 평면에 겹쳐 놓지 않았습니다. 각각의 범위만 확인하세요."}
        </p>
      )}
      {verticalUnknown && (
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
          자료 열람 가능 · 체적 비교 제한 — 수직 기준을 확인할 수 없습니다.{" "}
          <Link href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="tap-target underline">제한 근거 확인</Link>
        </p>
      )}
      <p className="mt-2 flex flex-wrap gap-2">
        {canCreateAnalysis ? (
          <Link href={scopedCompareHref} className="btn">이 구역 변화 비교</Link>
        ) : (
          <span className="text-[12px] text-ink-2">현재 계정으로는 비교를 요청할 수 없습니다. 권한 있는 담당자에게 문의하세요.</span>
        )}
        <Link href={`${sitePath}/spatial-data-requests?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="btn">구역 자료 준비</Link>
      </p>
      <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">실제 파일은 권한 확인 뒤 준비·다운로드로만 받습니다. 이 화면에서 바이트를 직접 열지 않습니다.</p>
    </div>}
  </div>;
}
