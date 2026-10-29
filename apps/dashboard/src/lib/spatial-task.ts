import type { AnalysisObservationOption, AnalysisSelector, AnalysisView } from "./core-api/analysis";
import { isAnalysisReadinessView, isAnalysisReadinessViewFor, type AnalysisReadinessViewV1 } from "./analysis-readiness";

export type SpatialTaskPurpose = "CLARIFY" | "OBSERVED_CHANGE" | "DESIGN_REMAINING" | "DAILY_TARGET";
export type SpatialTaskSelection = {
  purpose: SpatialTaskPurpose;
  workAreaId: string | null;
  inputs: { baseline: AnalysisSelector; current: AnalysisSelector } | null;
};
export type SpatialTask = {
  taskId: string; siteId: string; revision: number; selection: SpatialTaskSelection;
  analysisId: string | null; executionRequested: boolean; createdAt: string; expiresAt: string;
};
export type SpatialTaskView = {
  task: SpatialTask;
  state: "PURPOSE_REQUIRED" | "UNSUPPORTED_PURPOSE" | "AREA_REQUIRED" | "OBSERVATIONS_REQUIRED" |
    "CHECK_REQUIRED" | "ANALYSIS_PENDING" | "ANALYSIS_LINKED" | "SELECTION_UNAVAILABLE";
  selectionHref: string; analysisHref: string | null;
  readiness: AnalysisReadinessViewV1 | null; analysis: AnalysisView | null;
};
export type SpatialTaskOptions = {
  siteId: string;
  areas: { workAreaId: string; name: string }[];
  observations: (AnalysisObservationOption & { workAreaIds: string[] })[];
  nextOffset: number | null;
};

export const TASK_PURPOSE_LABEL: Record<SpatialTaskPurpose, string> = {
  CLARIFY: "무엇을 확인할지 선택",
  OBSERVED_CHANGE: "두 관측 사이 변화",
  DESIGN_REMAINING: "설계까지 남은 양",
  DAILY_TARGET: "오늘의 작업 목표",
};

export function selectorKey(selector: AnalysisSelector): string {
  return JSON.stringify([selector.workOrderId, selector.submissionRef, selector.revision]);
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const id = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._~-]{0,254}$/.test(value);
const SUITABILITY_STATES: ReadonlySet<string> = new Set([
  "BLOCKED", "REMEDIATION_REQUIRED", "PROVISIONAL_ACCURACY_UNVERIFIED", "EVALUATED", "REASSESSMENT_REQUIRED",
]);
/**
 * Core 계약(`external_analysis_api_v2._result_matches_suitability`)의 수치 pairing을
 * 그대로 따른다: 수치(result)는 COMPLETED + 수치 적합성에서만 존재하고, 수치 없는
 * COMPLETED는 반드시 보류 사유 상태를 동반한다. Core가 보낼 수 없는 조합을
 * 화면이 수치로 그리지 않기 위한 fail-closed 판독이다.
 */
const NUMERIC_SUITABILITY: ReadonlySet<string> = new Set([
  "PROVISIONAL_ACCURACY_UNVERIFIED", "EVALUATED",
]);
const WITHHELD_SUITABILITY: ReadonlySet<string> = new Set([
  "BLOCKED", "REMEDIATION_REQUIRED", "REASSESSMENT_REQUIRED",
]);
const limitationCodes = (value: unknown): value is string[] =>
  Array.isArray(value) && value.length <= 128
  && value.every((code): code is string => typeof code === "string");
const selector = (value: unknown): value is AnalysisSelector => record(value)
  && id(value.workOrderId) && typeof value.submissionRef === "string"
  && /^ers-v1-[0-9a-f]{64}$/.test(value.submissionRef)
  && Number.isSafeInteger(value.revision) && Number(value.revision) > 0;

export function isTaskSelection(value: unknown): value is SpatialTaskSelection {
  return record(value) && typeof value.purpose === "string" && Object.hasOwn(TASK_PURPOSE_LABEL, value.purpose)
    && (value.workAreaId === null || id(value.workAreaId))
    && (value.inputs === null || (record(value.inputs) && selector(value.inputs.baseline)
      && selector(value.inputs.current) && selectorKey(value.inputs.baseline) !== selectorKey(value.inputs.current)));
}

export function isTaskView(value: unknown, siteId: string, taskId: string): value is SpatialTaskView {
  if (!record(value) || !record(value.task)) return false;
  const task = value.task;
  const shape = task.siteId === siteId && task.taskId === taskId && /^st-[0-9a-f]{32}$/.test(taskId)
    && Number.isSafeInteger(task.revision) && Number(task.revision) >= 1
    && isTaskSelection(task.selection) && typeof task.executionRequested === "boolean"
    && (task.analysisId === null || id(task.analysisId))
    && typeof task.expiresAt === "string" && Number.isFinite(Date.parse(task.expiresAt))
    && typeof task.createdAt === "string" && Number.isFinite(Date.parse(task.createdAt))
    && typeof value.state === "string" && ["PURPOSE_REQUIRED", "UNSUPPORTED_PURPOSE", "AREA_REQUIRED",
      "OBSERVATIONS_REQUIRED", "CHECK_REQUIRED", "ANALYSIS_PENDING", "ANALYSIS_LINKED", "SELECTION_UNAVAILABLE"].includes(value.state)
    && (value.readiness === null || isAnalysisReadinessView(value.readiness));
  if (!shape || !isTaskSelection(task.selection)) return false;
  const selected = task.selection;
  if (value.readiness !== null && (!selected.inputs || !selected.workAreaId
    || !isAnalysisReadinessView(value.readiness) || !isAnalysisReadinessViewFor(value.readiness, {
      siteId, workAreaId: selected.workAreaId, ...selected.inputs,
    }))) return false;
  if (value.analysis === null) return true;
  const analysis = value.analysis;
  if (!record(analysis) || !selected.inputs || analysis.analysisId !== task.analysisId
    || analysis.siteId !== siteId || analysis.workAreaId !== selected.workAreaId
    || !selector(analysis.baseline) || !selector(analysis.current)
    || selectorKey(analysis.baseline) !== selectorKey(selected.inputs.baseline)
    || selectorKey(analysis.current) !== selectorKey(selected.inputs.current)
    || typeof analysis.executionState !== "string" || !["NOT_STARTED", "QUEUED", "RUNNING", "COMPLETED", "FAILED"].includes(analysis.executionState)
    || typeof analysis.suitabilityState !== "string" || !SUITABILITY_STATES.has(analysis.suitabilityState)
    || !Array.isArray(analysis.blockers) || analysis.blockers.length > 128
    || !analysis.blockers.every((item) => record(item) && typeof item.code === "string")) return false;
  if (analysis.result === null) {
    if (analysis.executionState === "COMPLETED" && !WITHHELD_SUITABILITY.has(analysis.suitabilityState)) return false;
    return true;
  }
  const result = analysis.result;
  if (analysis.executionState !== "COMPLETED" || !NUMERIC_SUITABILITY.has(analysis.suitabilityState)
    || !record(result) || !record(result.metrics)
    || !record(result.coverage) || !id(result.resultId) || typeof result.computedAt !== "string"
    || !Number.isFinite(Date.parse(result.computedAt)) || !limitationCodes(result.limitationCodes)) return false;
  if (![result.metrics.cutM3, result.metrics.fillM3, result.metrics.netM3, result.metrics.thresholdM]
    .every((item) => typeof item === "number" && Number.isFinite(item))) return false;
  if (![result.coverage.selectedAreaM2, result.coverage.commonValidAreaM2]
    .every((item) => typeof item === "number" && Number.isFinite(item) && item >= 0)) return false;
  return [result.coverage.selectedCellCount, result.coverage.commonValidCellCount,
    result.coverage.unavailableCellCount, result.coverage.thresholdExcludedCellCount]
    .every((item) => typeof item === "number" && Number.isSafeInteger(item) && item >= 0);
}

export function spatialTaskError(code: string | undefined, status: number): string {
  if (status === 401) return "로그인이 만료되었습니다. 다시 로그인한 뒤 이 링크로 돌아오세요.";
  if (status === 403) return "이 작업의 선택·실행 권한을 확인하세요. 외부 AI에는 현장의 반출 동의도 필요합니다.";
  if (status === 404) return "이 작업을 찾을 수 없거나 접근할 수 없습니다. 외부 대화의 현장과 로그인 계정을 확인하세요.";
  if (status === 410) return "선택 링크가 만료되었습니다. 외부 대화에서 새 요청을 시작하세요. 기존 분석 결과는 삭제되지 않습니다.";
  const messages: Record<string, string> = {
    SPATIAL_TASK_REVISION_CONFLICT: "다른 화면에서 선택이 바뀌었습니다. 저장된 선택을 새로 불러온 뒤 계속하세요.",
    SPATIAL_TASK_SELECTION_UNAVAILABLE: "선택한 구역이나 자료를 현재 사용할 수 없습니다. 새로 불러온 후보에서 다시 선택하세요.",
    SPATIAL_TASK_SELECTION_LOCKED: "이미 분석을 요청한 범위입니다. 범위를 바꾸려면 외부 대화에서 새 작업을 시작하세요.",
    SPATIAL_TASK_PURPOSE_UNSUPPORTED: "이 목적의 계산은 아직 지원하지 않습니다. 두 관측 사이 변화로 자동 대체하지 않습니다.",
    ANALYSIS_ACTIVATION_UNAVAILABLE: "분석 실행 환경이 준비되지 않았습니다. 선택은 보관되어 있습니다. 운영 담당자에게 확인하세요.",
    SPATIAL_TASK_SELECTION_REQUIRED: "작업구역과 서로 다른 두 관측을 선택하세요.",
    SPATIAL_TASK_REVISION_LIMIT: "이 작업의 변경 한도에 도달했습니다. 외부 대화에서 저장된 선택을 새 작업에 이어서 사용하세요. 분석은 시작되지 않았습니다.",
  };
  return messages[code ?? ""] ?? "작업을 처리하지 못했습니다. 선택은 화면에 유지됩니다. 연결을 확인하고 다시 시도하세요.";
}
