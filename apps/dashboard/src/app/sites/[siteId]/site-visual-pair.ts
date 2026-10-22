/**
 * 시각 쌍(독립 보기) 표시 헬퍼 — 순수 함수만 둔다.
 *
 * - 정량 비교의 시간 순서·봉인 판정을 바꾸지 않는다. 이 파일은 기존
 *   `viewerLayersForEpoch`의 의미를 그대로 두고, 시각 쌍의 양쪽에만 쓰는
 *   정확한 제출 묶음 고정 레이어 목록을 따로 둔다.
 * - 레이어 전환은 같은 구역·작업지시·관측 epoch의 같은 제출 묶음·같은 버전
 *   안에서만 고른다(정사영상/DSM). 다른 버전으로 바꾸지 않는다.
 * - 분석 인계 힌트는 정확한 선택자 그대로만 싣는다(근사·최신·날짜 유추 없음).
 * - 후보 존재가 픽셀 가용성과 같지 않다. 실제 픽셀 가용성은 guarded 뷰어가
 *   말하며, 여기서 별도 픽셀 판정을 만들지 않는다.
 */

import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import type { WindowedViewerLayer } from "@/lib/site-windowed-pixel-viewer";
import type { WorkspaceObservationFact } from "@/lib/site-workspace-entry";
import { dataKindLabel } from "@/lib/operator-language";

export const VISUAL_PAIR_QUERY_KEYS = {
  visualA: "visualAAssetRef",
  visualB: "visualBAssetRef",
} as const;

export const EXACT_ANALYSIS_HINT_QUERY_KEYS = {
  baselineWorkOrderId: "hintBaselineWorkOrderId",
  baselineSubmissionRef: "hintBaselineSubmissionRef",
  baselineRevision: "hintBaselineRevision",
  currentWorkOrderId: "hintCurrentWorkOrderId",
  currentSubmissionRef: "hintCurrentSubmissionRef",
  currentRevision: "hintCurrentRevision",
} as const;

export type VisualAssetIdentity = Pick<WorkspaceObservationFact,
  "assetRef" | "workAreaId" | "workOrderId" | "observationEpochId" | "submissionRef" | "revision" | "kind">;

/** An equal opaque ref must not hide contradictory revision/scope facts. */
export function sameVisualAssetIdentity(a: VisualAssetIdentity, b: VisualAssetIdentity): boolean {
  return a.assetRef === b.assetRef && a.workAreaId === b.workAreaId
    && a.workOrderId === b.workOrderId && a.observationEpochId === b.observationEpochId
    && a.submissionRef === b.submissionRef && a.revision === b.revision && a.kind === b.kind;
}

/**
 * 시각 쌍 한쪽의 표시 레이어 — 고른 정확한 참조 자체에 같은 구역·작업지시·
 * 관측 epoch의 같은 제출 묶음·같은 버전의 정사영상/DSM 형제를 더한다.
 * 다른 버전으로 바꾸지 않으며, 표시 순서를 정하지 않는다(정사영상 먼저).
 * 고른 참조도 버전·범위가 맞을 때만 둔다. 충돌을 다른 버전으로 메우지 않는다.
 */
export function visualLayersForExactSubmission(
  catalogAssets: readonly SpatialAssetCatalogItem[],
  fact: VisualAssetIdentity,
): WindowedViewerLayer[] {
  const layers: WindowedViewerLayer[] = [];
  for (const item of catalogAssets) {
    if (item.workAreaId !== fact.workAreaId || item.workOrderId !== fact.workOrderId) continue;
    if (item.observationEpochId !== fact.observationEpochId) continue;
    if (item.submissionRef !== fact.submissionRef || item.revision !== fact.revision) continue;
    if (item.kind !== "ortho" && item.kind !== "dsm") continue;
    if (item.assetRef === fact.assetRef && !sameVisualAssetIdentity(item, fact)) continue;
    layers.push({
      assetRef: item.assetRef,
      observationEpochId: item.observationEpochId,
      kind: item.kind,
      kindLabel: dataKindLabel(item.kind),
      isDsm: item.kind === "dsm",
      fileName: item.declared.fileName,
      revision: item.revision,
      submissionRef: item.submissionRef,
      inspectedRaster: item.inspection.raster
        ? {
            transform: [...item.inspection.raster.transform],
            width: item.inspection.raster.width,
            height: item.inspection.raster.height,
          }
        : null,
      observedCrsIdentifier: item.inspection.raster?.observedCrsIdentifier ?? null,
      observedCrsDigest: item.inspection.raster?.observedCrsDigest ?? null,
      inspectionOutcome: item.inspection.outcome,
      verticalReference: item.inspection.raster?.observedVerticalReference
        ? `${item.inspection.raster.observedVerticalReference.identifier} · ${item.inspection.raster.observedVerticalReference.basis}`
        : null,
    });
  }
  return layers.sort((a, b) => (a.isDsm === b.isDsm ? 0 : a.isDsm ? 1 : -1));
}

/**
 * 시각 쌍 선택지 — 같은 구역의 관측×버전 사실 중 카탈로그에 정확히 묶인
 * 정사영상/DSM만 둔다(대표 한 줄이 아니라 모든 검사된 버전). 관측 epoch별
 * 묶음으로 돌려주며, 순서를 정하지 않는다(호출자가 서버 순서를 유지한다).
 * 최대 50건(카탈로그 페이지 상한과 동일)으로 둔다. 고른 참조도 현재
 * 카탈로그와 정확히 묶일 때만 둔다. 미확인 참조는 다른 버전으로 대체하지 않는다.
 */
export function visualPairCatalogOptions(input: {
  facts: readonly WorkspaceObservationFact[];
  workAreaId: string;
  catalogAssets: readonly SpatialAssetCatalogItem[];
  selectedRefs?: readonly (string | null | undefined)[];
}): Array<{ observationEpochId: string; options: WorkspaceObservationFact[] }> {
  const bound = input.catalogAssets.filter((item) => item.workAreaId === input.workAreaId
    && (item.kind === "ortho" || item.kind === "dsm"));
  const seen = new Set<string>();
  const perEpoch = new Map<string, WorkspaceObservationFact[]>();
  const scoped = input.facts.filter((item) => item.workAreaId === input.workAreaId);
  for (const item of scoped) {
    if (seen.has(item.assetRef)) continue;
    if (!bound.some((asset) => sameVisualAssetIdentity(asset, item))) continue;
    seen.add(item.assetRef);
    const group = perEpoch.get(item.observationEpochId) ?? [];
    group.push(item);
    perEpoch.set(item.observationEpochId, group);
    if (seen.size >= 50) break;
  }
  for (const ref of input.selectedRefs ?? []) {
    if (!ref || seen.has(ref)) continue;
    const exact = scoped.find((item) => item.assetRef === ref);
    if (!exact || seen.size >= 50 || !bound.some((asset) => sameVisualAssetIdentity(asset, exact))) continue;
    seen.add(ref);
    const group = perEpoch.get(exact.observationEpochId) ?? [];
    group.push(exact);
    perEpoch.set(exact.observationEpochId, group);
  }
  return [...perEpoch.entries()].map(([observationEpochId, options]) => ({ observationEpochId, options }));
}

/** 분석 인계용 정확한 선택자 힌트 — 호출자가 resolve한 사실 그대로만 싣는다. */
export function exactAnalysisHintParams(
  baseline: WorkspaceObservationFact | null,
  current: WorkspaceObservationFact | null,
): Record<string, string> {
  const params: Record<string, string> = {};
  if (baseline) {
    params[EXACT_ANALYSIS_HINT_QUERY_KEYS.baselineWorkOrderId] = baseline.workOrderId;
    params[EXACT_ANALYSIS_HINT_QUERY_KEYS.baselineSubmissionRef] = baseline.submissionRef;
    params[EXACT_ANALYSIS_HINT_QUERY_KEYS.baselineRevision] = String(baseline.revision);
  }
  if (current) {
    params[EXACT_ANALYSIS_HINT_QUERY_KEYS.currentWorkOrderId] = current.workOrderId;
    params[EXACT_ANALYSIS_HINT_QUERY_KEYS.currentSubmissionRef] = current.submissionRef;
    params[EXACT_ANALYSIS_HINT_QUERY_KEYS.currentRevision] = String(current.revision);
  }
  return params;
}

/**
 * 쌍 인계 쿼리 문자열 — 정식(canonical)으로 resolve된 한 쌍의 정확한 선택자
 * 힌트 6건 + 둘러보기 복귀 참조 2건을 함께 싣는다. 토큰·바이트 URL·원문
 * 쿼리 값을 그대로 옮기지 않으며, 임의 returnTo를 만들지 않는다.
 */
export function pairQueryString(
  workAreaId: string,
  sideA: WorkspaceObservationFact,
  sideB: WorkspaceObservationFact,
): string {
  const query = new URLSearchParams();
  query.set("workAreaId", workAreaId);
  const hints = exactAnalysisHintParams(sideA, sideB);
  for (const [key, value] of Object.entries(hints)) query.set(key, value);
  query.set(VISUAL_PAIR_QUERY_KEYS.visualA, sideA.assetRef);
  query.set(VISUAL_PAIR_QUERY_KEYS.visualB, sideB.assetRef);
  return query.toString();
}

/**
 * 쌍 → 분석 인계 주소(정식) — 받는 분석 화면이 후보와 재대조한다.
 * 기존 `currentWorkOrderId` 근사 경로는 건드리지 않는다(호환 유지).
 */
export function analysisHandoffHref(
  sitePath: string,
  workAreaId: string,
  baseline: WorkspaceObservationFact | null,
  current: WorkspaceObservationFact | null,
): string {
  if (!baseline || !current) {
    return `${sitePath}/analysis?workAreaId=${encodeURIComponent(workAreaId)}`;
  }
  return `${sitePath}/analysis?${pairQueryString(workAreaId, baseline, current)}`;
}
