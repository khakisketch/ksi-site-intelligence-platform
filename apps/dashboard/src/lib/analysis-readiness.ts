import type {
  AnalysisBlocker,
  AnalysisSelector,
  AnalysisView,
} from "./core-api/analysis";

/**
 * 목적별 조건 확인 읽기 뷰(V1)의 화면·서버 공용 판독 검사 — 순수 함수이며
 * 서버 전용 모듈을运行时에 들여오지 않으므로 BFF와 브라우저가 같은
 * 검사를 공유한다. 모양·범위·상태 규칙·UTC·반향이 하나라도 어긋나면
 * 실패로 닫는다(적합하다고 추정하지 않는다).
 */

export type AnalysisReadinessViewV1 = {
  contractVersion: "analysis-readiness.v1";
  siteId: string;
  workAreaId: string;
  baseline: AnalysisSelector;
  current: AnalysisSelector;
  suitabilityState: AnalysisView["suitabilityState"];
  blockers: AnalysisBlocker[];
  limitationCodes: string[];
  checkedAt: string;
  calculationIdentityDigest: string | null;
  coverageCheck: "REQUIRES_WORKER_VALIDATION";
};

export type AnalysisReadinessRequest = {
  baseline: AnalysisSelector;
  current: AnalysisSelector;
};

const SUBMISSION_REF_PATTERN = /^ers-v1-[0-9a-f]{64}$/;
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;
const REASON_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,127}$/;
const UTC_DESIGNATOR_PATTERN = /(Z|[+-]00:?00)$/;
const MAX_TEXT_LENGTH = 255;
const MAX_LIST_LENGTH = 128;

const SUITABILITY_STATES: ReadonlySet<string> = new Set([
  "BLOCKED",
  "REMEDIATION_REQUIRED",
  "PROVISIONAL_ACCURACY_UNVERIFIED",
  "EVALUATED",
  "REASSESSMENT_REQUIRED",
]);

const NEEDS_BLOCKERS: ReadonlySet<string> = new Set([
  "BLOCKED",
  "REMEDIATION_REQUIRED",
  "REASSESSMENT_REQUIRED",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isBoundedText(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= MAX_TEXT_LENGTH && value === value.trim();
}

function isReadinessSelector(value: unknown): value is AnalysisSelector {
  if (!isRecord(value)) return false;
  return Object.keys(value).length === 3
    && isBoundedText(value.workOrderId)
    && typeof value.submissionRef === "string"
    && SUBMISSION_REF_PATTERN.test(value.submissionRef)
    && typeof value.revision === "number"
    && Number.isSafeInteger(value.revision)
    && value.revision > 0;
}

function isReadinessBlocker(value: unknown): value is AnalysisBlocker {
  if (!isRecord(value)) return false;
  if (typeof value.code !== "string" || value.code.trim() !== value.code || !REASON_CODE_PATTERN.test(value.code)) return false;
  if (value.epoch !== null && value.epoch !== "BASELINE" && value.epoch !== "CURRENT") return false;
  if (value.evidenceRef !== null && value.evidenceRef !== undefined && !isBoundedText(value.evidenceRef)) return false;
  if (value.detail !== null && value.detail !== undefined
    && (typeof value.detail !== "string" || value.detail.length === 0 || value.detail.length > 512 || value.detail !== value.detail.trim())) return false;
  return true;
}

function isUtcInstant(value: string): boolean {
  if (!UTC_DESIGNATOR_PATTERN.test(value)) return false;
  return !Number.isNaN(Date.parse(value));
}

export function isAnalysisReadinessView(value: unknown): value is AnalysisReadinessViewV1 {
  if (!isRecord(value)) return false;
  if (value.contractVersion !== "analysis-readiness.v1") return false;
  if (!isBoundedText(value.siteId) || !isBoundedText(value.workAreaId)) return false;
  if (!isReadinessSelector(value.baseline) || !isReadinessSelector(value.current)) return false;
  if (typeof value.suitabilityState !== "string" || !SUITABILITY_STATES.has(value.suitabilityState)) return false;
  if (!Array.isArray(value.blockers) || value.blockers.length > MAX_LIST_LENGTH || !value.blockers.every(isReadinessBlocker)) return false;
  if (!Array.isArray(value.limitationCodes) || value.limitationCodes.length > MAX_LIST_LENGTH
    || !value.limitationCodes.every((code): code is string => typeof code === "string")) return false;
  if (typeof value.checkedAt !== "string" || !isUtcInstant(value.checkedAt)) return false;
  if (value.calculationIdentityDigest !== null
    && (typeof value.calculationIdentityDigest !== "string" || !DIGEST_PATTERN.test(value.calculationIdentityDigest))) return false;
  if (value.coverageCheck !== "REQUIRES_WORKER_VALIDATION") return false;
  // Core `_readiness_state_matches_blockers`와 같은 규칙 — 어긋난 판독은
  // ready가 아니라 실패다.
  if (NEEDS_BLOCKERS.has(value.suitabilityState) && value.blockers.length === 0) return false;
  if (!NEEDS_BLOCKERS.has(value.suitabilityState) && value.blockers.length > 0) return false;
  if (value.suitabilityState !== "PROVISIONAL_ACCURACY_UNVERIFIED" && value.limitationCodes.length > 0) return false;
  return true;
}

function sameSelector(left: AnalysisSelector, right: AnalysisSelector): boolean {
  return left.workOrderId === right.workOrderId
    && left.submissionRef === right.submissionRef
    && left.revision === right.revision;
}

/**
 * Core 판독이 요청한 쌍을 그대로 되돌렸는지 확인한다. 사이트·구역·
 * 기준·현재 선택자가 하나라도 다르면 현재 쌍의 조건으로 보여주지 않는다.
 */
export function isAnalysisReadinessViewFor(
  view: AnalysisReadinessViewV1,
  expected: { siteId: string; workAreaId: string } & AnalysisReadinessRequest,
): boolean {
  return view.siteId === expected.siteId
    && view.workAreaId === expected.workAreaId
    && sameSelector(view.baseline, expected.baseline)
    && sameSelector(view.current, expected.current);
}
