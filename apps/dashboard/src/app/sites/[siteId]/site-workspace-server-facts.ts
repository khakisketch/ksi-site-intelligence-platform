import "server-only";

import type { AnalysisListItem } from "@/lib/core-api/analysis";
import type {
  SpatialWorkspaceCapture,
  SpatialWorkspaceObservation,
  SpatialWorkspacePage,
} from "@/lib/core-api/spatial-workspace";
import type { WorkArea } from "@/lib/core-api/types";
import type {
  WorkspaceAnalysisRef,
  WorkspaceCaptureFacts,
  WorkspaceEntryDefault,
  WorkspaceObservationFact,
  WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";
import { parseCalendarDate } from "@/lib/site-workspace-entry";

/**
 * SWX-1 서버 어댑터 — `site-workspace-entry.ts`가 먹는 사실 묶음을 Core
 * 프로젝션(`GET
 * /v1/sites/{siteId}/work-areas/{workAreaId}/spatial-workspace-observations`)
 * 에서 옮기는 유일한 자리.
 *
 * 바인딩(형태는 Core 소유):
 * - 관측 후보는 `observations[]`(관측×버전 펼침) — 자산 수준 카탈로그 목록을
 *   후보·기본값 계산에 쓰지 않는다.
 * - `entryDefault`는 그대로 옮긴다. `reason`이 관측을 가리킬 때만 일반 진입이
 *   `ready`가 되며, 그 판정은 resolver가 맡는다. 여기서 순서를 매기거나
 *   고르지 않는다.
 * - 포착 정밀도: EXACT_INTERVAL은 `capture.captureStartedAt/EndedAt`,
 *   DATE_ONLY는 `capture.captureDate`(`YYYY-MM-DD`), 둘 다 없으면 UNKNOWN.
 *   `submittedAt`/`observedAt`에서 유도하지 않는다.
 * - 카탈로그 항목의 부가 `declared.captureDate` 읽기는 `readCatalogCaptureDate`
 *   가 맡는다(자료·탐색 목록의 날짜만 표기용). 후보·기본값에는 쓰지 않는다.
 */

function readWireCapture(capture: SpatialWorkspaceCapture | null | undefined): WorkspaceCaptureFacts {
  if (!capture || typeof capture !== "object") {
    return { captureStartedAt: null, captureEndedAt: null, captureDate: null };
  }
  const startedAt = typeof capture.captureStartedAt === "string" ? capture.captureStartedAt : null;
  const endedAt = typeof capture.captureEndedAt === "string" ? capture.captureEndedAt : null;
  const date = typeof capture.captureDate === "string" ? capture.captureDate : null;
  return {
    captureStartedAt: startedAt,
    captureEndedAt: endedAt,
    // 달력 날짜는 엄격 검증 뒤에만 둔다 — 시각 합성의 자리를 없앤다.
    captureDate: parseCalendarDate(date),
  };
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function toFacts(
  siteId: string,
  workAreaId: string,
  observations: readonly SpatialWorkspaceObservation[] | null | undefined,
): WorkspaceObservationFact[] {
  if (!Array.isArray(observations)) return [];
  const out: WorkspaceObservationFact[] = [];
  for (const observation of observations) {
    if (!observation || typeof observation !== "object") continue;
    const observationEpochId = asString(observation.observationEpochId);
    const workOrderId = asString(observation.workOrderId);
    if (!observationEpochId || !workOrderId) continue;
    const versions = Array.isArray(observation.versions) ? observation.versions : [];
    const viewAssetRef = asString(observation.viewAssetRef);
    for (const version of versions) {
      if (!version || typeof version !== "object") continue;
      const assetRef = asString(version.assetRef);
      const submissionRef = asString(version.submissionRef);
      const revision = typeof version.revision === "number" ? version.revision : null;
      if (!assetRef || !submissionRef || revision === null) continue;
      out.push({
        ...readWireCapture(version.capture),
        observationEpochId,
        workAreaId,
        workOrderId,
        assetRef,
        submissionRef,
        revision,
        kind: asString(version.kind) ?? "unknown",
        displayReady: version.displayReady === true,
        inspectedRasterAvailable: version.inspectedRasterAvailable === true,
        chronologyCandidate: observation.chronologyCandidate === true,
        captureSourcesAgree: observation.captureSourcesAgree === true,
        viewAvailable: observation.viewAvailable === true,
        viewUnavailableReason: asString(observation.viewUnavailableReason),
        viewAssetRef,
        newerRevisionPending: observation.newerRevisionPending === true,
        newerRevisionState: asString(observation.newerRevisionState),
      });
    }
  }
  return out;
}

function toEntryDefault(page: SpatialWorkspacePage | null): WorkspaceEntryDefault | null {
  const entry = page?.entryDefault;
  if (!entry || typeof entry !== "object") return null;
  const reason = asString(entry.reason);
  if (
    reason !== "LATEST_EXACT_VIEW_AVAILABLE" &&
    reason !== "NO_OBSERVATIONS" &&
    reason !== "NO_VIEW_AVAILABLE_OBSERVATION" &&
    reason !== "NO_EXACT_CAPTURE_CANDIDATE" &&
    reason !== "CAPTURE_TIE_AMBIGUOUS"
  ) {
    return null;
  }
  const tied = Array.isArray(entry.tiedObservationEpochIds)
    ? entry.tiedObservationEpochIds.filter((id): id is string => typeof id === "string")
    : [];
  return {
    observationEpochId: asString(entry.observationEpochId),
    viewAssetRef: asString(entry.viewAssetRef),
    reason,
    detail: asString(entry.detail),
    tiedObservationEpochIds: tied,
  };
}

export type WorkspaceProjectionState =
  | { status: "ready"; page: SpatialWorkspacePage }
  | { status: "denied" }
  | { status: "unavailable" };

export function buildWorkspaceServerFacts({
  siteId,
  areas,
  projection,
  analyses,
  selectorsById = new Map(),
  workAreaId,
}: {
  siteId: string;
  areas: readonly WorkArea[];
  /** 선택 구역의 프로젝션 읽기 결과. 실패는 denied/unavailable로만 둔다. */
  projection: WorkspaceProjectionState;
  analyses: readonly AnalysisListItem[] | null;
  selectorsById?: ReadonlyMap<string, { baseline: WorkspaceAnalysisRef["baseline"]; current: WorkspaceAnalysisRef["current"] }>;
  workAreaId: string | null;
}): WorkspaceServerFacts {
  const page = projection.status === "ready" ? projection.page : null;
  return {
    siteId,
    authorizedWorkAreaIds: areas.filter((area) => area.status === "ACTIVE").map((area) => area.workAreaId),
    entryDefault: toEntryDefault(page),
    observations: workAreaId ? toFacts(siteId, workAreaId, page?.observations) : [],
    analyses: toAnalysisRefs(analyses, selectorsById),
  };
}

export function toAnalysisRefs(
  items: readonly AnalysisListItem[] | null,
  selectorsById: ReadonlyMap<string, { baseline: WorkspaceAnalysisRef["baseline"]; current: WorkspaceAnalysisRef["current"] }> = new Map(),
): WorkspaceAnalysisRef[] {
  if (!items) return [];
  const out: WorkspaceAnalysisRef[] = [];
  for (const item of items) {
    const selectors = selectorsById.get(item.analysisId);
    // 목록 항목에는 baseline/current 선택자가 없으므로, 상세 없이는 결과
    // 링크 복원에 쓰지 않는다 — 있는 그대로 두되 선택자는 비워 두지 않고
    // 아예 제외한다(없는 selector를 지어내지 않는다).
    if (!selectors) continue;
    out.push({
      analysisId: item.analysisId,
      workAreaId: item.workAreaId,
      baseline: selectors.baseline,
      current: selectors.current,
    });
  }
  return out;
}

/**
 * 카탈로그 항목의 부가 `declared.captureDate`(V3 DATE_ONLY) 읽기 — 자료·탐색
 * 목록의 날짜만 표기용. 후보·기본값 계산에는 쓰지 않는다.
 */
export function readCatalogCaptureDate(declared: { captureDate?: unknown }): string | null {
  return parseCalendarDate(declared.captureDate ?? null);
}
