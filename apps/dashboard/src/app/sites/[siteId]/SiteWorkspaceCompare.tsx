import Link from "next/link";

import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";
import { dataKindLabel } from "@/lib/operator-language";
import { formatKoreanDate } from "@/lib/datetime";
import { spatialAssetKindLabel } from "@/lib/human-labels";
import type {
  ExplicitComparisonResolution,
  VisualPairResolution,
  WorkspaceObservationFact,
  WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";
import {
  compareSlotCandidates,
  representativeFacts,
  splitCompareCandidates,
  workspaceCaptureLine,
} from "@/lib/site-workspace-entry";
import { visualPairCatalogOptions } from "./site-visual-pair";
import { capturePeriodTitle } from "@/lib/operator-language";
import { SiteNativeExtentSvg } from "./SiteNativeExtentSvg";
import {
  disambiguatedAreaNames,
  extractSimpleRing,
  parseFootprintWkt,
  planeUnitForCrs,
  ringsCoincident,
  sameDisplayPlane,
  selectableGeometry,
} from "./site-spatial";

function precisionNote(fact: WorkspaceObservationFact): string {
  return workspaceCaptureLine(fact, {
    intervalTitle: (startedAt, endedAt) => capturePeriodTitle(startedAt, endedAt),
    calendarDate: (date) => formatKoreanDate(date),
  });
}

/** 선택지·칸 제목 — 서버 사실의 정밀도 그대로. 날짜만 알면 날짜+시각 미상, 미상은 날짜를 그리지 않는다. */
export function candidateLabel(fact: WorkspaceObservationFact, dateFirst = false): string {
  const identity = dateFirst ? `${precisionNote(fact)} · ${dataKindLabel(fact.kind)}`
    : `${dataKindLabel(fact.kind)} · ${precisionNote(fact)}`;
  return `${identity} · 등록 버전 ${fact.revision}`;
}

function CompareSlot({
  slotLabel,
  sitePath,
  workAreaId,
  ring,
  areaCrs,
  planeUnit,
  coincident,
  catalogAssets,
  fact,
  emptyNote,
}: {
  slotLabel: "기준 자료" | "비교 자료" | "관측 A" | "관측 B";
  sitePath: string;
  workAreaId: string;
  ring: Array<[number, number]> | null;
  areaCrs: string;
  planeUnit: ReturnType<typeof planeUnitForCrs>;
  coincident: (footprint: Array<[number, number]>) => boolean;
  catalogAssets: readonly SpatialAssetCatalogItem[];
  fact: WorkspaceObservationFact | null;
  emptyNote: string;
}) {
  const catalogItem = fact ? (catalogAssets.find((item) => item.assetRef === fact.assetRef) ?? null) : null;
  const footprintRing = catalogItem?.inspection?.raster ? parseFootprintWkt(catalogItem.inspection.raster.footprintWkt) : null;
  const overlaid = Boolean(
    footprintRing && ring && catalogItem?.inspection?.raster &&
      sameDisplayPlane(areaCrs, catalogItem.inspection.raster.observedCrsIdentifier),
  );
  const raster = catalogItem?.inspection?.raster ?? null;
  return <section aria-label={slotLabel} className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface px-3 py-3">
    <h3 className="text-[13.5px] font-bold">{slotLabel}</h3>
    {!fact ? (
      <p className="text-[12.5px] leading-5 text-ink-2">{emptyNote}</p>
    ) : (<>
      <p className="break-words text-[13px] font-semibold">{candidateLabel(fact)}</p>
      <p className="text-[12px] text-ink-2">{spatialAssetKindLabel(fact.kind)} · {fact.assetRef === fact.viewAssetRef ? "이 관측의 표시 버전" : "이전 표시 버전(명시적 선택)"}</p>
      {!fact.captureSourcesAgree && (
        <p className="text-[12px] leading-5 text-ink-2">이 관측의 버전들이 서로 다른 관측 시점을 가리켜 시간 순서 비교 후보에서 제외됩니다.</p>
      )}
      {fact.newerRevisionPending && (
        <p className="text-[12px] leading-5 text-ink-2">새로 제출된 버전이 있어 표시용 출력을 확인 중입니다. 지금 보는 버전을 바꾸지 않았습니다.</p>
      )}
      {/* 측정 범위 도형은 펼침에 둔다 — 실제 화면(아래 창 단위 픽셀 보기)이 먼저다. */}
      <details className="text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold">측정 범위·격자 확인</summary>
        <div className="mt-1 flex flex-col gap-2">
          {ring ? (
            <SiteNativeExtentSvg
              boundary={ring}
              footprint={overlaid && footprintRing ? footprintRing : null}
              crsLabel={areaCrs}
              footprintLabel={overlaid ? candidateLabel(fact) : null}
              planeUnit={planeUnit}
              vertexCount={ring.length}
              coincident={footprintRing ? coincident(footprintRing) : false}
            />
          ) : (
            <p className="text-[12.5px] leading-5 text-ink-2">구역 기하를 읽지 못해 범위를 그리지 않았습니다.</p>
          )}
          {!catalogItem && (
            <p className="text-[12px] leading-5 text-ink-2">측정 범위 정보를 조회하지 못해 관측 범위를 겹쳐 표시하지 않았습니다. 선택한 버전 자체는 그대로 둡니다.</p>
          )}
          {footprintRing && !overlaid && (
            <p className="text-[12px] leading-5 text-ink-2">위치 기준이 맞지 않아 파일 범위를 겹쳐 표시하지 않았습니다.</p>
          )}
          <dl className="grid gap-1 text-[12px] text-ink-2">
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">자료 격자</dt><dd className="text-right">{raster ? `${raster.width} × ${raster.height}` : "확인 불가"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">관측 위치 기준</dt><dd className="break-words text-right">{raster?.observedCrsIdentifier ?? "확인 불가"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="shrink-0 text-ink-muted">수직 기준</dt><dd className="text-right">{raster?.observedVerticalReference ? raster.observedVerticalReference.identifier : "확인 불가"}</dd></div>
          </dl>
        </div>
      </details>
      <details className="text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer">선택 버전 정보</summary>
        <p className="mt-1">등록 버전 · {fact.revision}</p>
        <p className="mt-1 break-all">제출 묶음 · {fact.submissionRef}</p>
        {catalogItem && <p className="mt-1 break-all">등록 파일명 · {catalogItem.declared.fileName}</p>}
        <p className="mt-1 break-all font-mono">자료 식별자 · {fact.assetRef}</p>
      </details>
      <p><Link href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(workAreaId)}&assetRef=${encodeURIComponent(fact.assetRef)}`} className="tap-target inline-block text-[12px] underline">파일 등록 정보 열기</Link></p>
    </>)}
  </section>;
}

/**
 * 비교 모드 — 두 개의 동등한 지도 자리 + 정직한 미지원 고지.
 *
 * - 후보는 프로젝션의 관측×버전 사실에서 온다. 순서 가능 + 표시 준비된 관측만
 *   칸에 올린다. 표시 준비가 안 된 순서 후보·날짜만·미상 관측은 막되 감추지
 *   않고 사유와 함께 둔다.
 * - 두 자리는 같은 무게다. 같은 화면 맞춤·같은 색 눈금·위치 맞춤(정합)은
 *   확인된 바 없으므로 보장하지 않는다고 밝힌다.
 * - 바이트 보기는 이 화면에서 열지 않고, 기존의 권한 확인된 준비·다운로드 경로로만
 *   연결한다.
 */
export function SiteWorkspaceCompare({
  sitePath,
  areas,
  selectedWorkAreaId,
  catalogAssets,
  projectionState,
  workspaceHasMore,
  baselineRequestedRef,
  currentRequestedRef,
  resolution,
  visualARequestedRef = null,
  visualBRequestedRef = null,
  visualPair = { status: "prompt" } as VisualPairResolution | { status: "prompt" },
  canCreateAnalysis,
  canCreateWorkOrder: canCreateWorkOrderHere,
  scopedCompareHref,
  exploreHref,
  facts,
  presentation = "full",
}: {
  sitePath: string;
  areas: WorkArea[];
  selectedWorkAreaId: string | null;
  catalogAssets: readonly SpatialAssetCatalogItem[];
  projectionState: "ready" | "denied" | "unavailable";
  workspaceHasMore: boolean;
  baselineRequestedRef: string | null;
  currentRequestedRef: string | null;
  resolution: ExplicitComparisonResolution | { status: "prompt" };
  visualARequestedRef?: string | null;
  visualBRequestedRef?: string | null;
  visualPair?: VisualPairResolution | { status: "prompt" };
  canCreateAnalysis: boolean;
  /** 관측 자료 등록(쓰기) 가능 여부 — 펼침의 등록 경로 안내에만 쓴다. */
  canCreateWorkOrder: boolean;
  scopedCompareHref: string;
  /** 비교할 후보가 없을 때 돌아갈 탐색 주소 — 같은 구역·선택 자료 그대로 둔다. */
  exploreHref: string;
  facts: WorkspaceServerFacts;
  /** Same comparison logic, with its observation controls hosted by the workspace rail. */
  presentation?: "full" | "controls" | "viewer" | "inspector";
}) {
  // 무대(viewer)는 짧은 고지·막힘·다음 행동만 둔다. 칸 카드·조건 펼침·
  // 장문 안내는 정보 서랍(inspector)이 맡는다 — 무대는 매체와 선택이 먼저다.
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

  const { eligible, blocked } = selected ? compareSlotCandidates(facts, selected.workAreaId) : { eligible: [], blocked: [] };
  const groups = selected ? splitCompareCandidates(facts, selected.workAreaId) : null;
  const representatives = selected ? representativeFacts(facts, selected.workAreaId) : [];
  const tiedEpochs = facts.entryDefault?.reason === "CAPTURE_TIE_AMBIGUOUS"
    ? (facts.entryDefault.tiedObservationEpochIds ?? [])
    : [];
  const tiedFacts = tiedEpochs
    .map((epochId) => representatives.find((item) => item.observationEpochId === epochId) ?? null)
    .filter((item): item is WorkspaceObservationFact => item !== null);
  const baselineFact = resolution.status === "ready" ? resolution.baseline : null;
  const currentFact = resolution.status === "ready" ? resolution.current : null;
  const visualAFact = visualPair.status === "ready" ? visualPair.sideA : null;
  const visualBFact = visualPair.status === "ready" ? visualPair.sideB : null;
  const formAction = selected ? `${sitePath}?` : sitePath;
  const hasOptions = eligible.length > 0;
  const showNoOptionBox = selected !== null
    && projectionState === "ready"
    && !hasOptions
    && resolution.status !== "ready"
    && resolution.status !== "unresolvable";
  // 선택지가 하나도 없을 때의 한 줄 사유 — 기존 typed 사실에서만 고른다.
  // 순서 후보가 없으면 무엇이 있어야 하는지(촬영 시간이 정확한 관측)를
  // 함께 밝힌다 — 막힌 이유만 말하면 사용자는 무엇을 해야 할지 모른다.
  const noOptionReason = (() => {
    if (!showNoOptionBox || !selected) return null;
    if (representatives.length === 0) {
      return "이 구역에 확인된 관측이 없습니다. 관측이 등록되면 같은 구역의 두 시점을 나란히 둘 수 있습니다.";
    }
    const browsableCount = (groups?.browsableDateOnly.length ?? 0) + (groups?.browsableUnknown.length ?? 0);
    if (blocked.length > 0 && browsableCount === 0 && tiedFacts.length === 0) {
      return "시간 순서는 정해졌으나 표시용 출력이 봉인되지 않아 나란히 둘 후보가 없습니다.";
    }
    if (browsableCount > 0 && blocked.length === 0 && tiedFacts.length === 0) {
      return (groups?.browsableUnknown.length ?? 0) > 0
        ? "촬영 시각을 확인하지 못한 관측이 있어, 두 시점의 순서를 확정할 수 없습니다. 날짜만 확인된 관측과 시점 미상 관측은 상세에서 구분합니다."
        : "이 구역의 관측은 촬영 시각 대신 날짜만 확인되어, 두 시점의 순서를 확정할 수 없습니다.";
    }
    if (tiedFacts.length > 0 && blocked.length === 0 && browsableCount === 0) {
      return "같은 촬영 구간의 관측이 2개 이상 있어 자동으로 고르지 않았습니다.";
    }
    return "나란히 둘 수 있는 비교 후보가 아직 없습니다.";
  })();

  const comparisonForm = selected && projectionState === "ready" && eligible.length > 0 ? (
    <form method="get" action={formAction} className="flex min-w-0 flex-col gap-3">
      <input type="hidden" name="mode" value="compare" />
      <input type="hidden" name="workAreaId" value={selected.workAreaId} />
      <div className="min-w-0">
        <label htmlFor="workspace-compare-baseline" className="block text-[12px] font-semibold">기준 자료</label>
        <select id="workspace-compare-baseline" name="baselineAssetRef" required defaultValue={baselineRequestedRef ?? ""} className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]">
          <option value="">기준 자료 선택</option>
          {eligible.map((item) => <option key={item.assetRef} value={item.assetRef}>{candidateLabel(item)}</option>)}
        </select>
      </div>
      <div className="min-w-0">
        <label htmlFor="workspace-compare-current" className="block text-[12px] font-semibold">비교 자료</label>
        <select id="workspace-compare-current" name="currentAssetRef" required defaultValue={currentRequestedRef ?? ""} className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]">
          <option value="">비교 자료 선택</option>
          {eligible.map((item) => <option key={item.assetRef} value={item.assetRef}>{candidateLabel(item)}</option>)}
        </select>
      </div>
      <button type="submit" className="btn">나란히 보기</button>
      {workspaceHasMore && <p className="text-[12px] text-ink-2">조회된 목록 뒤에 관측이 더 있습니다. 찾는 관측이 없으면 담당자에게 문의하세요.</p>}
    </form>
  ) : null;
  // 시각 쌍(독립 보기) 선택지 — 카탈로그에 정확히 묶인 모든 검사 버전
  // (대표 한 줄이 아니라 모든 정사영상/DSM 개정)을 둔다. 정밀도 표기는
  // 그대로 두며, 순서·최신을 단정하지 않는다. 후보 존재가 픽셀 가용성과
  // 같지 않다 — 실제 픽셀은 guarded 뷰어가 말한다.
  const visualGroups = selected && projectionState === "ready"
    ? visualPairCatalogOptions({
      facts: facts.observations,
      workAreaId: selected.workAreaId,
      catalogAssets,
      selectedRefs: [visualARequestedRef, visualBRequestedRef],
    })
    : [];
  const visualOptionCount = visualGroups.reduce((total, group) => total + group.options.length, 0);
  const visualForm = selected && projectionState === "ready" && visualOptionCount >= 2 ? (
    <form key={`${selected.workAreaId}:${visualARequestedRef ?? ""}:${visualBRequestedRef ?? ""}`} method="get" action={formAction} className="flex min-w-0 flex-col gap-2">
      <input type="hidden" name="mode" value="compare" />
      <input type="hidden" name="workAreaId" value={selected.workAreaId} />
      <div className="grid min-w-0 gap-2 sm:grid-cols-2">
        <div className="min-w-0">
          <label htmlFor="workspace-visual-a" className="block text-[12px] font-semibold">관측 A</label>
          <select id="workspace-visual-a" name="visualAAssetRef" required defaultValue={visualARequestedRef ?? ""} className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]">
            <option value="">관측 A 선택</option>
            {visualGroups.map((group) => <optgroup key={group.observationEpochId} label={group.options[0] ? candidateLabel(group.options[0], true) : group.observationEpochId}>
              {group.options.map((item) => <option key={item.assetRef} value={item.assetRef}>{candidateLabel(item, true)}</option>)}
            </optgroup>)}
          </select>
        </div>
        <div className="min-w-0">
          <label htmlFor="workspace-visual-b" className="block text-[12px] font-semibold">관측 B</label>
          <select id="workspace-visual-b" name="visualBAssetRef" required defaultValue={visualBRequestedRef ?? ""} className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]">
            <option value="">관측 B 선택</option>
            {visualGroups.map((group) => <optgroup key={group.observationEpochId} label={group.options[0] ? candidateLabel(group.options[0], true) : group.observationEpochId}>
              {group.options.map((item) => <option key={item.assetRef} value={item.assetRef}>{candidateLabel(item, true)}</option>)}
            </optgroup>)}
          </select>
        </div>
      </div>
      <button type="submit" className="btn tap-target">독립 보기로 나란히 두기</button>
      {workspaceHasMore && <p className="text-[12px] text-ink-2">조회된 목록 뒤에 관측이 더 있습니다. 찾는 관측이 없으면 담당자에게 문의하세요.</p>}
    </form>
  ) : null;
  if (presentation === "controls") return <div className="min-w-0"><h3 className="mb-2 text-[12px] font-semibold">관측 시점</h3>{visualForm ?? <p className="text-[12px] leading-5 text-ink-2">{selected === null ? "비교할 작업구역이 없습니다. 목록에서 구역을 고르세요." : projectionState === "denied" ? "관측 목록을 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요." : projectionState === "ready" ? "독립 보기로 둘 관측이 아직 없습니다. 뷰어에서 사유를 확인하세요." : "관측 목록을 불러오지 못했습니다. 잠시 후 뷰어에서 조회 상태를 확인하세요."}</p>}{comparisonForm && <details className="mt-2 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">기존 시간 순서 보기</summary><div className="mt-2">{comparisonForm}</div></details>}</div>;
  if (presentation === "inspector") return <div className="flex min-w-0 flex-col gap-3">
    {visualPair.status === "ready" && visualAFact && visualBFact && (
      <div className="rounded-lg border border-line bg-surface px-4 py-3">
        <h3 className="text-[13px] font-bold">독립 보기 — 정합 근거 없음</h3>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
          A·B는 고른 순서일 뿐 촬영 순서를 뜻하지 않습니다. 동기화 비교는 지원하지 않으며, 각 보기는 독립된 카메라로만 움직입니다.
        </p>
        <details className="mt-1 text-[12px] text-ink-2">
          <summary className="tap-target cursor-pointer font-semibold">정합 근거 없음 — 자세히</summary>
          <p className="mt-1 leading-5">
            화면 맞춤이 실제 지형 일치를 뜻하지 않으며, 같은 범위 맞춤·같은 색 눈금 비교는 지원하지 않습니다.
            화면을 겹쳐도 분석 근거가 되지 않으며, 높낮이 차이로 읽지 마세요.
          </p>
        </details>
        <p className="mt-2">
          <Link href={scopedCompareHref} className="btn">이 쌍으로 분석 조건 확인</Link>
        </p>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">수치 계산이 필요할 때만 씁니다. 위 기록은 바뀌지 않으며, 요청하지 않으면 아무 계산도 시작하지 않습니다.</p>
      </div>
    )}

    {selected && resolution.status === "ready" && <div className="grid gap-4 md:grid-cols-2">
      <CompareSlot
        slotLabel="기준 자료"
        sitePath={sitePath}
        workAreaId={selected.workAreaId}
        ring={ring}
        areaCrs={areaCrs}
        planeUnit={planeUnit}
        coincident={coincident}
        catalogAssets={catalogAssets}
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
        catalogAssets={catalogAssets}
        fact={currentFact}
        emptyNote="비교 자료를 아직 고르지 않았습니다. 위에서 직접 고르세요."
      />
    </div>}

    {selected && visualPair.status === "ready" && <div className="grid gap-4 md:grid-cols-2">
      <CompareSlot
        slotLabel="관측 A"
        sitePath={sitePath}
        workAreaId={selected.workAreaId}
        ring={ring}
        areaCrs={areaCrs}
        planeUnit={planeUnit}
        coincident={coincident}
        catalogAssets={catalogAssets}
        fact={visualAFact}
        emptyNote="관측 A를 아직 고르지 않았습니다. 위 독립 보기 선택에서 직접 고르세요."
      />
      <CompareSlot
        slotLabel="관측 B"
        sitePath={sitePath}
        workAreaId={selected.workAreaId}
        ring={ring}
        areaCrs={areaCrs}
        planeUnit={planeUnit}
        coincident={coincident}
        catalogAssets={catalogAssets}
        fact={visualBFact}
        emptyNote="관측 B를 아직 고르지 않았습니다. 위 독립 보기 선택에서 직접 고르세요."
      />
    </div>}

    {selected && projectionState === "ready" && resolution.status !== "ready" && (
      <details className="rounded-lg border border-line bg-surface px-4 py-3">
        <summary className="tap-target cursor-pointer text-[13px] font-bold">비교 조건과 다른 작업 확인</summary>
        <div className="mt-1 flex flex-col gap-2 text-[12.5px] leading-5 text-ink-2">
          {blocked.length > 0 && (
            <div>
              <p>시간 순서는 정해졌으나 표시용 출력이 봉인되지 않아 칸에 올리지 않았습니다.</p>
              <ul className="mt-1 divide-y divide-line">
                {blocked.map((item) => (
                  <li key={item.assetRef} className="py-1 text-[12px] text-ink-2">{candidateLabel(item)}</li>
                ))}
              </ul>
            </div>
          )}
          {tiedFacts.length > 0 && (
            <div>
              <p>같은 촬영 구간의 관측이 2개 이상 있어 자동으로 고르지 않았습니다. 직접 고르세요.</p>
              <ul className="mt-1 divide-y divide-line">
                {tiedFacts.map((item) => (
                  <li key={item.assetRef} className="py-1 text-[12px] text-ink-2">{candidateLabel(item)}</li>
                ))}
              </ul>
            </div>
          )}
          {groups && (groups.browsableDateOnly.length > 0 || groups.browsableUnknown.length > 0) && (
            <div>
              <p>시간 순서 비교 후보는 아니지만 둘러볼 수 있습니다. 정밀도 그대로 둡니다.</p>
              <ul className="mt-1 divide-y divide-line">
                {[...groups.browsableDateOnly, ...groups.browsableUnknown].map((item) => (
                  <li key={item.assetRef} className="py-1 text-[12px] text-ink-2">{candidateLabel(item)}</li>
                ))}
              </ul>
            </div>
          )}
          <p>시간 순서가 확인된 관측이 2개 이상 있어야 나란히 둘 수 있습니다. 날짜만 아는 관측은 순서 후보가 아닙니다. 순서 없이 나란히 두려면 위의 독립 보기 선택을 쓰세요 — 시간 순서를 주장하지 않습니다.</p>
          <div>
            <p className="font-semibold">지원하지 않는 동기화 비교</p>
            <p className="mt-1">
              동기화된 공간 비교(같은 범위 맞춤·같은 색 눈금)는 지원하지 않습니다.
              두 자료의 위치 맞춤이 확인되지 않아 같은 범위를 가리킨다고 보장하지 않으며, 화면을 겹쳐도 분석 근거가 되지 않습니다.
            </p>
          </div>
          <p>
            수치가 필요할 때만{" "}
            {canCreateAnalysis ? (
              <Link href={scopedCompareHref} className="tap-target underline">변화량 분석</Link>
            ) : (
              <span>변화량 분석 — 현재 계정으로는 요청할 수 없어 권한 있는 담당자에게 문의하세요.</span>
            )}
            을 요청하세요. 준비를 더 한다고 시간 순서·표시 조건이 생기지는 않습니다.
          </p>
          <p>
            <Link href={`${sitePath}/spatial-data-requests?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="tap-target underline">구역 자료 준비</Link>
            <span className="text-ink-muted"> · 자료 준비는 보는 범위를 넓힐 뿐, 시간 순서·표시 봉인 조건을 보장하지 않습니다.</span>
          </p>
          <p>
            {canCreateWorkOrderHere ? (
              <Link href={`${sitePath}/observations/new?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="tap-target underline">관측 자료 등록</Link>
            ) : (
              <span>관측 자료 등록 — 외부 관측 등록은 권한 있는 담당자와 확인하세요.</span>
            )}
            <span className="text-ink-muted"> 새 관측이 등록되면 같은 구역의 두 시점을 나란히 둘 수 있습니다.</span>
          </p>
        </div>
      </details>
    )}

    {comparisonForm && (
      <details className="rounded-lg border border-line bg-surface px-4 py-3">
        <summary className="tap-target cursor-pointer text-[13px] font-semibold">기존 시간 순서 보기</summary>
        <div className="mt-2">{comparisonForm}</div>
      </details>
    )}

    {selected && resolution.status === "ready" && <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <h3 className="text-[13px] font-bold">나란히 보기 안내</h3>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        두 지도는 같은 크기로 나란히 둡니다. 동기화된 공간 비교(같은 범위 맞춤·같은 색 눈금)는 지원하지 않습니다.
        두 자료의 위치 맞춤이 확인되지 않아 같은 범위를 가리킨다고 보장하지 않으며, 화면을 겹쳐도 분석 근거가 되지 않습니다.
      </p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        화면 맞춤이 실제 지형 일치를 뜻하지 않으며, 높낮이 차이로 읽지 마세요. 측정 범위 표시이며 정확도를 보증하지 않습니다.
      </p>
      <div className="mt-2 border-t border-line pt-2">
        <p className="text-[12.5px] font-semibold leading-5">수치 계산이 필요할 때 — 변화량 분석</p>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">
          나란히 두는 독립 열람과 별개로, 두 시점의 변화량을 계산 요청할 때만 씁니다. 위 기록은 바뀌지 않습니다.
        </p>
        <p className="mt-2">
          {canCreateAnalysis ? (
            <Link href={scopedCompareHref} className="btn">변화량 분석</Link>
          ) : (
            <span className="text-[12px] text-ink-2">현재 계정으로는 변화량 분석을 요청할 수 없습니다. 권한 있는 담당자에게 문의하세요.</span>
          )}
        </p>
      </div>
      <p className="mt-2 text-[12px] leading-5">
        <Link href={`${sitePath}/spatial-data-requests?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="tap-target underline">구역 자료 준비</Link>
        <span className="text-ink-muted"> · 자료 준비는 보는 범위를 넓힐 뿐, 시간 순서·표시 봉인 조건을 보장하지 않습니다.</span>
      </p>
      <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">실제 파일은 권한 확인 뒤 준비·다운로드로만 받습니다. 이 화면에서 바이트를 직접 열지 않습니다.</p>
    </div>}
  </div>;
  return <div className="flex min-w-0 flex-col gap-3">
    {selected === null && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2">
        비교할 작업구역이 없습니다. 작업구역이 등록되면 같은 구역의 두 자료를 나란히 둘 수 있습니다.
      </p>
    )}
    {selected && (
      <p className="text-[12.5px] leading-5 text-ink-2">
        {areaLabel} · 같은 구역의 두 자료를 독립 보기로 나란히 둡니다.{" "}
        <span className="font-semibold">독립 보기 — 정합 근거 없음</span>
        {presentation === "full" && (visualPair.status === "ready" && visualAFact && visualBFact
          ? ` · 관측 A(${candidateLabel(visualAFact)}) · 관측 B(${candidateLabel(visualBFact)})`
          : visualPair.status === "unresolvable"
            ? " · 요청한 쌍을 확인하지 못했습니다"
            : " · 쌍을 고르세요")}
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
    {resolution.status === "prompt" && selected && hasOptions && visualOptionCount < 2 && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
        비교할 기준 자료와 비교 자료를 관측 시점 선택에서 고르세요. 자동으로 고르지 않았습니다.
        먼저 둘러보려면 <Link href={exploreHref} className="tap-target underline">탐색에서 날짜·층별로 확인</Link>하세요.
      </p>
    )}
    {visualPair.status === "prompt" && selected && visualOptionCount >= 2 && resolution.status !== "ready" && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
        독립 보기로 둘 관측 A·B를 위 선택에서 고르세요. 자동으로 고르지 않았습니다.
      </p>
    )}
    {visualPair.status === "unresolvable" && (
      <div role="alert" className="rounded-lg border border-line bg-surface px-4 py-3">
        <p className="text-[13px] font-bold">{visualPair.headline}</p>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">{visualPair.detail}</p>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">독립 보기 지시는 자동으로 다른 자료로 바꾸지 않습니다. 아래 독립 보기 선택에서 확인할 수 있는 자료를 직접 고르세요.</p>
        <p className="mt-2 flex flex-wrap gap-x-3 text-[12px]">
          <Link href={`${sitePath}/spatial-assets${selected ? `?workAreaId=${encodeURIComponent(selected.workAreaId)}` : ""}`} className="tap-target underline">자료 목록 보기</Link>
          <Link href={exploreHref} className="tap-target underline">탐색으로 돌아가기</Link>
        </p>
      </div>
    )}

    {presentation !== "viewer" && visualPair.status === "ready" && visualAFact && visualBFact && (
      <div className="rounded-lg border border-line bg-surface px-4 py-3">
        <h3 className="text-[13px] font-bold">독립 보기 — 정합 근거 없음</h3>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
          A·B는 고른 순서일 뿐 촬영 순서를 뜻하지 않습니다. 동기화 비교는 지원하지 않으며, 각 보기는 독립된 카메라로만 움직입니다.
        </p>
        <details className="mt-1 text-[12px] text-ink-2">
          <summary className="tap-target cursor-pointer font-semibold">정합 근거 없음 — 자세히</summary>
          <p className="mt-1 leading-5">
            화면 맞춤이 실제 지형 일치를 뜻하지 않으며, 같은 범위 맞춤·같은 색 눈금 비교는 지원하지 않습니다.
            화면을 겹쳐도 분석 근거가 되지 않으며, 높낮이 차이로 읽지 마세요.
          </p>
        </details>
        <p className="mt-2">
          <Link href={scopedCompareHref} className="btn">이 쌍으로 분석 조건 확인</Link>
        </p>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">수치 계산이 필요할 때만 씁니다. 위 기록은 바뀌지 않으며, 요청하지 않으면 아무 계산도 시작하지 않습니다.</p>
      </div>
    )}

    {selected && projectionState === "denied" && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2">
        관측 목록을 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요.
      </p>
    )}
    {selected && projectionState === "unavailable" && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2">
        관측 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요. 빈 목록으로 단정하지 않습니다.
      </p>
    )}

    {showNoOptionBox && visualOptionCount < 2 && (
      <div className="rounded-lg border border-line bg-surface px-4 py-3" role="status">
        <p className="text-[13px] font-bold">{noOptionReason}</p>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
          같은 구역의 실제 관측부터 둘러보세요.{" "}
          <Link href={exploreHref} className="tap-target underline">탐색에서 날짜·층별로 확인</Link>
        </p>
        {/* 무엇을 하면 비교가 되는지 — 막힌 이유만 말하고 끝내지 않는다.
            준비는 보는 범위만 넓히고 순서 조건은 만들지 않으므로, 시간이
            필요할 때의 수치 계산 경로와 새 관측 등록을 함께 제시한다. */}
        <p className="mt-2 border-t border-line pt-2 text-[12px] leading-5 text-ink-2">
          나란히 두려면 <span className="font-semibold text-ink-1">촬영 시간이 정확히 기록된 관측 2개</span>가
          같은 구역에 있어야 합니다. 각 관측의 표시 조건도 별도로 확인해야 합니다.
        </p>
        <p className="mt-1.5 flex flex-wrap gap-2 text-[12px]">
          {canCreateWorkOrderHere && (
            <Link href={`${sitePath}/observations/new?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="btn w-fit">
              촬영 시각이 있는 관측 등록
            </Link>
          )}
          {canCreateAnalysis && (
            <Link href={scopedCompareHref} className="btn w-fit">
              변화량 분석 요청
            </Link>
          )}
        </p>
      </div>
    )}

    {presentation === "full" && visualForm}
    {presentation === "full" && comparisonForm && (
      <details className="rounded-lg border border-line bg-surface px-4 py-3">
        <summary className="tap-target cursor-pointer text-[13px] font-semibold">기존 시간 순서 보기</summary>
        <div className="mt-2">{comparisonForm}</div>
      </details>
    )}

    {presentation !== "viewer" && selected && resolution.status === "ready" && <div className="grid gap-4 md:grid-cols-2">
      <CompareSlot
        slotLabel="기준 자료"
        sitePath={sitePath}
        workAreaId={selected.workAreaId}
        ring={ring}
        areaCrs={areaCrs}
        planeUnit={planeUnit}
        coincident={coincident}
        catalogAssets={catalogAssets}
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
        catalogAssets={catalogAssets}
        fact={currentFact}
        emptyNote="비교 자료를 아직 고르지 않았습니다. 위에서 직접 고르세요."
      />
    </div>}

    {presentation !== "viewer" && selected && visualPair.status === "ready" && <div className="grid gap-4 md:grid-cols-2">
      <CompareSlot
        slotLabel="관측 A"
        sitePath={sitePath}
        workAreaId={selected.workAreaId}
        ring={ring}
        areaCrs={areaCrs}
        planeUnit={planeUnit}
        coincident={coincident}
        catalogAssets={catalogAssets}
        fact={visualAFact}
        emptyNote="관측 A를 아직 고르지 않았습니다. 위 독립 보기 선택에서 직접 고르세요."
      />
      <CompareSlot
        slotLabel="관측 B"
        sitePath={sitePath}
        workAreaId={selected.workAreaId}
        ring={ring}
        areaCrs={areaCrs}
        planeUnit={planeUnit}
        coincident={coincident}
        catalogAssets={catalogAssets}
        fact={visualBFact}
        emptyNote="관측 B를 아직 고르지 않았습니다. 위 독립 보기 선택에서 직접 고르세요."
      />
    </div>}

    {presentation !== "viewer" && selected && projectionState === "ready" && resolution.status !== "ready" && (
      <details className="rounded-lg border border-line bg-surface px-4 py-3">
        <summary className="tap-target cursor-pointer text-[13px] font-bold">비교 조건과 다른 작업 확인</summary>
        <div className="mt-1 flex flex-col gap-2 text-[12.5px] leading-5 text-ink-2">
          {blocked.length > 0 && (
            <div>
              <p>시간 순서는 정해졌으나 표시용 출력이 봉인되지 않아 칸에 올리지 않았습니다.</p>
              <ul className="mt-1 divide-y divide-line">
                {blocked.map((item) => (
                  <li key={item.assetRef} className="py-1 text-[12px] text-ink-2">{candidateLabel(item)}</li>
                ))}
              </ul>
            </div>
          )}
          {tiedFacts.length > 0 && (
            <div>
              <p>같은 촬영 구간의 관측이 2개 이상 있어 자동으로 고르지 않았습니다. 직접 고르세요.</p>
              <ul className="mt-1 divide-y divide-line">
                {tiedFacts.map((item) => (
                  <li key={item.assetRef} className="py-1 text-[12px] text-ink-2">{candidateLabel(item)}</li>
                ))}
              </ul>
            </div>
          )}
          {groups && (groups.browsableDateOnly.length > 0 || groups.browsableUnknown.length > 0) && (
            <div>
              <p>시간 순서 비교 후보는 아니지만 둘러볼 수 있습니다. 정밀도 그대로 둡니다.</p>
              <ul className="mt-1 divide-y divide-line">
                {[...groups.browsableDateOnly, ...groups.browsableUnknown].map((item) => (
                  <li key={item.assetRef} className="py-1 text-[12px] text-ink-2">{candidateLabel(item)}</li>
                ))}
              </ul>
            </div>
          )}
          <p>시간 순서가 확인된 관측이 2개 이상 있어야 나란히 둘 수 있습니다. 날짜만 아는 관측은 순서 후보가 아닙니다. 순서 없이 나란히 두려면 위의 독립 보기 선택을 쓰세요 — 시간 순서를 주장하지 않습니다.</p>
          <div>
            <p className="font-semibold">지원하지 않는 동기화 비교</p>
            <p className="mt-1">
              동기화된 공간 비교(같은 범위 맞춤·같은 색 눈금)는 지원하지 않습니다.
              두 자료의 위치 맞춤이 확인되지 않아 같은 범위를 가리킨다고 보장하지 않으며, 화면을 겹쳐도 분석 근거가 되지 않습니다.
            </p>
          </div>
          <p>
            수치가 필요할 때만{" "}
            {canCreateAnalysis ? (
              <Link href={scopedCompareHref} className="tap-target underline">변화량 분석</Link>
            ) : (
              <span>변화량 분석 — 현재 계정으로는 요청할 수 없어 권한 있는 담당자에게 문의하세요.</span>
            )}
            을 요청하세요. 준비를 더 한다고 시간 순서·표시 조건이 생기지는 않습니다.
          </p>
          <p>
            <Link href={`${sitePath}/spatial-data-requests?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="tap-target underline">구역 자료 준비</Link>
            <span className="text-ink-muted"> · 자료 준비는 보는 범위를 넓힐 뿐, 시간 순서·표시 봉인 조건을 보장하지 않습니다.</span>
          </p>
          <p>
            {canCreateWorkOrderHere ? (
              <Link href={`${sitePath}/observations/new?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="tap-target underline">관측 자료 등록</Link>
            ) : (
              <span>관측 자료 등록 — 외부 관측 등록은 권한 있는 담당자와 확인하세요.</span>
            )}
            <span className="text-ink-muted"> 새 관측이 등록되면 같은 구역의 두 시점을 나란히 둘 수 있습니다.</span>
          </p>
        </div>
      </details>
    )}

    {presentation !== "viewer" && selected && resolution.status === "ready" && <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <h3 className="text-[13px] font-bold">나란히 보기 안내</h3>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        두 지도는 같은 크기로 나란히 둡니다. 동기화된 공간 비교(같은 범위 맞춤·같은 색 눈금)는 지원하지 않습니다.
        두 자료의 위치 맞춤이 확인되지 않아 같은 범위를 가리킨다고 보장하지 않며, 화면을 겹쳐도 분석 근거가 되지 않습니다.
      </p>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        화면 맞춤이 실제 지형 일치를 뜻하지 않으며, 높낮이 차이로 읽지 마세요. 측정 범위 표시이며 정확도를 보증하지 않습니다.
      </p>
      <div className="mt-2 border-t border-line pt-2">
        <p className="text-[12.5px] font-semibold leading-5">수치 계산이 필요할 때 — 변화량 분석</p>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">
          나란히 두는 독립 열람과 별개로, 두 시점의 변화량을 계산 요청할 때만 씁니다. 위 기록은 바뀌지 않습니다.
        </p>
        <p className="mt-2">
          {canCreateAnalysis ? (
            <Link href={scopedCompareHref} className="btn">변화량 분석</Link>
          ) : (
            <span className="text-[12px] text-ink-2">현재 계정으로는 변화량 분석을 요청할 수 없습니다. 권한 있는 담당자에게 문의하세요.</span>
          )}
        </p>
      </div>
      <p className="mt-2 text-[12px] leading-5">
        <Link href={`${sitePath}/spatial-data-requests?workAreaId=${encodeURIComponent(selected.workAreaId)}`} className="tap-target underline">구역 자료 준비</Link>
        <span className="text-ink-muted"> · 자료 준비는 보는 범위를 넓힐 뿐, 시간 순서·표시 봉인 조건을 보장하지 않습니다.</span>
      </p>
      <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">실제 파일은 권한 확인 뒤 준비·다운로드로만 받습니다. 이 화면에서 바이트를 직접 열지 않습니다.</p>
    </div>}
  </div>;
}
