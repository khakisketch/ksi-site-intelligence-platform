/**
 * Site spatial workspace entry resolution (SWX-1 client half) — pure, tested.
 *
 * - 이 모듈은 순수 함수만 두며 "server-only" Core 클라이언트를 import하지
 *   않는다. 서버 컴포넌트·vitest가 함께 쓴다.
 * - 판정·재계산을 하지 않는다 — Core가 준 서버 사실(server facts)에서 "무엇을
 *   보여줄지"만 고른다. 모르는 값은 null/unknown으로 그대로 둔다.
 * - 명시적 지시(explicit result/work/context link)는 정확히 복원하거나 막는다.
 *   자동으로 다른 대상으로 바꾸지 않는다(조용한 최신 대체 금지).
 * - 일반 진입(ordinary entry)은 서버가 지정한 기본 관측만 쓴다. 클라이언트가
 *   목록을 정렬해 "최신"을 만들어내지 않는다.
 *
 * Invariants: INV-020(면적 어림 금지 — 범위 판정 없음)/INV-024(원본 식별 보존 —
 * 정확한 selector만 수용)/INV-051(시간 순서 — 포착 구간 정밀도 그대로, 합성
 * 시각 금지)/INV-053(네이티브 격자 — 좌표 재해석 없음)/INV-060·061(권한·이그레스 —
 * 승인된 구역·관측만 수용, 바이트 접근 없음).
 */

export type CapturePrecision = "interval" | "date-only" | "unknown";

/**
 * 포착 사실의 정밀도 표현.
 *
 * - EXACT_INTERVAL: 시작·종료가 모두 확인된 구간. 시간 순서 비교 후보가 된다.
 * - DATE_ONLY: 달력 날짜만 확인(시각 미상). 둘러보기는 되지만 순서 비교
 *   후보가 아니다. Core V3 intake의 `captureDate`(DATE_ONLY)가 이 자리다.
 * - UNKNOWN: 아무것도 모른다. 날짜·시각으로 그리지 않는다.
 */
export interface WorkspaceCaptureFacts {
  captureStartedAt: string | null;
  captureEndedAt: string | null;
  /**
   * 달력 날짜만 아는 포착일 (`YYYY-MM-DD`). Core가 `declared.captureDate`로
   * 줄 때만 값이 있으며, submittedAt/observedAt/등록 시각에서 유도하지 않는다.
   */
  captureDate: string | null;
}

/**
 * 서버가 준 관측 사실 하나. 어댑터(`site-workspace-server-facts.ts`)가 기존
 * Core 목록에서 옮긴다. `viewAvailable`은 서버 선언 가용성 자리이며, 권위
 * 프로젝션이 오기 전까지는 검사 래스터 사실의 전이적 옮김이다(어댑터 TODO 참조).
 */
export interface WorkspaceObservationFact extends WorkspaceCaptureFacts {
  observationEpochId: string;
  workAreaId: string;
  assetRef: string;
  kind: string;
  revision: number;
  viewAvailable: boolean;
}

export interface WorkspaceAnalysisSelector {
  workOrderId: string;
  submissionRef: string;
  revision: number;
}

export interface WorkspaceAnalysisRef {
  analysisId: string;
  workAreaId: string;
  baseline: WorkspaceAnalysisSelector;
  current: WorkspaceAnalysisSelector;
}

export interface WorkspaceServerFacts {
  siteId: string;
  authorizedWorkAreaIds: readonly string[];
  /**
   * 권위 있는 Core 기본 관측. 프로젝션이 오기 전에는 null이며, null일 때
   * 일반 진입은 `no-server-default`를 돌린다 — 클라이언트 정렬 대체가 아니라
   * 호출자가 전이 선택을 명시적으로 맡는다.
   */
  serverDefault: WorkspaceObservationFact | null;
  observations: readonly WorkspaceObservationFact[];
  analyses: readonly WorkspaceAnalysisRef[];
}

export type WorkspaceMode = "explore" | "compare" | "results";

export function parseWorkspaceMode(raw: unknown): WorkspaceMode {
  if (raw === "compare" || raw === "results") return raw;
  return "explore";
}

export function parseWorkspaceScopeId(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (trimmed.length === 0 || trimmed.length > 200) return null;
  return trimmed;
}

export type OrdinaryEntryResolution =
  | {
      status: "ready";
      basis: "server-default";
      workAreaId: string;
      observation: WorkspaceObservationFact;
    }
  | { status: "no-server-default" };

/**
 * 일반 진입 — 서버 기본 관측만 쓴다. 서버 기본이 없거나 승인 범위를 벗어나면
 * `no-server-default`를 돌리고, 목록 순서·제출 시각으로 최신을 골라내지 않는다.
 */
export function resolveOrdinaryEntry(facts: WorkspaceServerFacts): OrdinaryEntryResolution {
  const candidate = facts.serverDefault;
  if (
    candidate &&
    facts.authorizedWorkAreaIds.includes(candidate.workAreaId) &&
    facts.observations.some(
      (item) => item.assetRef === candidate.assetRef && item.workAreaId === candidate.workAreaId,
    )
  ) {
    return { status: "ready", basis: "server-default", workAreaId: candidate.workAreaId, observation: candidate };
  }
  return { status: "no-server-default" };
}

export type UnresolvableReason =
  | "malformed"
  | "foreign-work-area"
  | "unknown-observation"
  | "unknown-asset"
  | "unavailable"
  | "unknown-result"
  | "identical-selectors"
  | "cross-area-comparison";

export interface UnresolvableEntry {
  status: "unresolvable";
  intent: "observation" | "comparison" | "result";
  reason: UnresolvableReason;
  headline: string;
  detail: string;
}

function failClosed(
  intent: UnresolvableEntry["intent"],
  reason: UnresolvableReason,
): UnresolvableEntry {
  if (intent === "comparison") {
    return {
      status: "unresolvable",
      intent,
      reason,
      headline: "요청한 비교 대상을 확인할 수 없습니다",
      detail:
        "기준 자료와 비교 자료는 같은 구역에서 확인할 수 있는 서로 다른 두 자료여야 합니다. 자동으로 다른 자료로 바꾸지 않았습니다. 아래에서 확인할 수 있는 자료를 직접 고르세요.",
    };
  }
  if (intent === "result") {
    return {
      status: "unresolvable",
      intent,
      reason,
      headline: "요청한 분석 기록을 확인할 수 없습니다",
      detail:
        "기록이 다른 구역·삭제된 항목이거나 조회 권한이 없을 수 있습니다. 자동으로 최근 기록으로 바꾸지 않았습니다. 아래 목록에서 확인할 수 있는 기록을 직접 고르세요.",
    };
  }
  return {
    status: "unresolvable",
    intent,
    reason,
    headline: "요청한 자료를 확인할 수 없습니다",
    detail:
      "링크가 가리키는 관측 자료가 이 구역에 없거나, 조회 권한·보관 상태가 바뀌었을 수 있습니다. 자동으로 다른 자료로 바꾸지 않았습니다. 아래에서 확인할 수 있는 자료를 직접 고르세요.",
  };
}

export type ExplicitObservationResolution =
  | {
      status: "ready";
      basis: "explicit";
      workAreaId: string;
      observation: WorkspaceObservationFact;
    }
  | UnresolvableEntry;

/**
 * 명시적 관측·버전 링크 — 정확히 일치하는 승인 관측만 받는다. 어긋나면 막고
 * (fail-closed) 기본 관측·목록 첫 항목으로 조용히 바꾸지 않는다.
 */
export function resolveExplicitObservation(
  facts: WorkspaceServerFacts,
  raw: { workAreaId: unknown; observationEpochId: unknown; assetRef?: unknown },
): ExplicitObservationResolution {
  const workAreaId = parseWorkspaceScopeId(raw.workAreaId);
  const observationEpochId = parseWorkspaceScopeId(raw.observationEpochId);
  const assetRef = raw.assetRef === undefined ? null : parseWorkspaceScopeId(raw.assetRef);
  if (!workAreaId || !observationEpochId || (raw.assetRef !== undefined && assetRef === null)) {
    return failClosed("observation", "malformed");
  }
  if (!facts.authorizedWorkAreaIds.includes(workAreaId)) {
    return failClosed("observation", "foreign-work-area");
  }
  const epochMatches = facts.observations.filter(
    (item) => item.workAreaId === workAreaId && item.observationEpochId === observationEpochId,
  );
  if (epochMatches.length === 0) {
    return failClosed("observation", "unknown-observation");
  }
  if (assetRef !== null) {
    const exact = epochMatches.find((item) => item.assetRef === assetRef);
    if (!exact) return failClosed("observation", "unknown-asset");
    if (!exact.viewAvailable) return failClosed("observation", "unavailable");
    return { status: "ready", basis: "explicit", workAreaId, observation: exact };
  }
  const viewable = epochMatches.find((item) => item.viewAvailable) ?? null;
  if (!viewable) return failClosed("observation", "unavailable");
  return { status: "ready", basis: "explicit", workAreaId, observation: viewable };
}

export type ExplicitComparisonResolution =
  | {
      status: "ready";
      basis: "explicit";
      workAreaId: string;
      baseline: WorkspaceObservationFact;
      current: WorkspaceObservationFact;
    }
  | UnresolvableEntry;

/**
 * 명시적 비교(저장된 비교·딥링크) — 같은 구역의 서로 다른 두 승인 관측을
 * 정확히 복원한다. 하나라도 어긋나면 전체를 막는다. 남은 한쪽·기본값으로
 * 이어 그리지 않는다.
 */
export function resolveExplicitComparison(
  facts: WorkspaceServerFacts,
  raw: { workAreaId: unknown; baselineAssetRef: unknown; currentAssetRef: unknown },
): ExplicitComparisonResolution {
  const workAreaId = parseWorkspaceScopeId(raw.workAreaId);
  const baselineAssetRef = parseWorkspaceScopeId(raw.baselineAssetRef);
  const currentAssetRef = parseWorkspaceScopeId(raw.currentAssetRef);
  if (!workAreaId || !baselineAssetRef || !currentAssetRef) {
    return failClosed("comparison", "malformed");
  }
  if (!facts.authorizedWorkAreaIds.includes(workAreaId)) {
    return failClosed("comparison", "foreign-work-area");
  }
  if (baselineAssetRef === currentAssetRef) {
    return failClosed("comparison", "identical-selectors");
  }
  const baseline = facts.observations.find(
    (item) => item.workAreaId === workAreaId && item.assetRef === baselineAssetRef,
  );
  const current = facts.observations.find(
    (item) => item.workAreaId === workAreaId && item.assetRef === currentAssetRef,
  );
  if (!baseline || !current) {
    const foreign = [baselineAssetRef, currentAssetRef].some(
      (ref) =>
        facts.observations.some((item) => item.assetRef === ref) &&
        !facts.observations.some((item) => item.assetRef === ref && item.workAreaId === workAreaId),
    );
    return failClosed("comparison", foreign ? "cross-area-comparison" : "unknown-asset");
  }
  if (!baseline.viewAvailable || !current.viewAvailable) {
    return failClosed("comparison", "unavailable");
  }
  return { status: "ready", basis: "explicit", workAreaId, baseline, current };
}

export type ExplicitResultResolution =
  | {
      status: "ready";
      basis: "explicit";
      analysis: WorkspaceAnalysisRef;
    }
  | UnresolvableEntry;

/**
 * 명시적 결과 링크 — 같은 분석의 원래 입력·구역을 그대로 돌린다. 모르면
 * 막는다. 최신 결과·다른 기록으로 바꾸지 않는다.
 */
export function resolveExplicitResult(
  facts: WorkspaceServerFacts,
  raw: { analysisId: unknown },
): ExplicitResultResolution {
  const analysisId = parseWorkspaceScopeId(raw.analysisId);
  if (!analysisId) return failClosed("result", "malformed");
  const hit = facts.analyses.find((item) => item.analysisId === analysisId);
  if (!hit) return failClosed("result", "unknown-result");
  if (!facts.authorizedWorkAreaIds.includes(hit.workAreaId)) {
    return failClosed("result", "foreign-work-area");
  }
  return { status: "ready", basis: "explicit", analysis: hit };
}

function parseCaptureTime(value: string | null): number | null {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isNaN(time) ? null : time;
}

/**
 * 달력 날짜 검증 — `YYYY-MM-DD` 실제 날짜만 받는다. 시각 합성·제출 시각
 * 유추의 자리를 없앤다. 어긋나면 null이다(호출자가 unknown으로 둔다).
 */
export function parseCalendarDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || month < 1 || month > 12 || day < 1 || day > 31) return null;
  const check = new Date(Date.UTC(year, month - 1, day));
  if (
    check.getUTCFullYear() !== year ||
    check.getUTCMonth() !== month - 1 ||
    check.getUTCDate() !== day
  ) {
    return null;
  }
  return value;
}

/**
 * 포착 정밀도 — 선언된 그대로만 말한다.
 *
 * - 시작·종료가 모두 파싱되면 "interval"(시간 순서 비교 후보).
 * - 달력 날짜만 확인되면 "date-only"(둘러보기만, 날짜+시각 미상 표기).
 * - 한쪽 구간만 있거나 파싱 불가·미상은 "unknown" — 구간으로 보지 않고
 *   날짜·시각으로도 그리지 않는다.
 * 파일명·제출/관측/등록 시각에서 연도·구간을 추론하지 않는다.
 */
export function observationPrecisionOf(fact: WorkspaceCaptureFacts): CapturePrecision {
  const from = parseCaptureTime(fact.captureStartedAt);
  const to = parseCaptureTime(fact.captureEndedAt);
  if (from !== null && to !== null) return "interval";
  if (parseCalendarDate(fact.captureDate) !== null) return "date-only";
  return "unknown";
}

/**
 * 관측 항목의 정밀도 표기 한 줄 — 선언된 정밀도 그대로만 말한다.
 *
 * - interval: 기존 구간 제목(연도 포함, 시각까지) 그대로.
 * - date-only: 달력 날짜 + "(날짜만 확인 · 시각 미상)". 시각을 붙이지 않는다.
 * - unknown: 날짜·시각을 그리지 않는다. "포착 시점을 확인할 수 없습니다" —
 *   없는 기록을 단정하지 않고, 가짜 타임스탬프를 만들지 않는다.
 */
export function workspaceCaptureLine(
  fact: WorkspaceCaptureFacts,
  options?: { intervalTitle?: (startedAt: string, endedAt: string) => string; calendarDate?: (date: string) => string },
): string {
  if (
    fact.captureStartedAt &&
    fact.captureEndedAt &&
    parseCaptureTime(fact.captureStartedAt) !== null &&
    parseCaptureTime(fact.captureEndedAt) !== null
  ) {
    if (options?.intervalTitle) return options.intervalTitle(fact.captureStartedAt, fact.captureEndedAt);
    return `${fact.captureStartedAt} – ${fact.captureEndedAt} 촬영`;
  }
  const calendar = parseCalendarDate(fact.captureDate);
  if (calendar !== null) {
    const rendered = options?.calendarDate ? options.calendarDate(calendar) : calendar;
    return `${rendered} 촬영 (날짜만 확인 · 시각 미상)`;
  }
  return "포착 시점을 확인할 수 없습니다";
}

export interface CompareCandidateGroups {
  /** 시간 순서 비교 후보 — 시작·종료가 모두 확인된 구간 관측만. */
  comparable: WorkspaceObservationFact[];
  /** 구간 한쪽만 아는 관측 — 둘러보기는 되지만 순서 비교 후보가 아니다. */
  browsableDateOnly: WorkspaceObservationFact[];
  /** 포착 시점을 모르는 관측 — 둘러보기는 되지만 순서 비교 후보가 아니다. */
  browsableUnknown: WorkspaceObservationFact[];
}

/**
 * 비교 후보 나눔 — 시간 순서 비교는 정확한 구간 관측끼리만. 날짜 일부·미상
 * 관측은 후보에서 빼되 목록에서 감추지 않는다(정밀도 그대로 표기).
 */
export function splitCompareCandidates(
  facts: WorkspaceServerFacts,
  workAreaId: string,
): CompareCandidateGroups {
  const scoped = facts.observations.filter(
    (item) => item.workAreaId === workAreaId && facts.authorizedWorkAreaIds.includes(item.workAreaId),
  );
  const comparable: WorkspaceObservationFact[] = [];
  const browsableDateOnly: WorkspaceObservationFact[] = [];
  const browsableUnknown: WorkspaceObservationFact[] = [];
  for (const item of scoped) {
    const precision = observationPrecisionOf(item);
    if (precision === "interval") comparable.push(item);
    else if (precision === "date-only") browsableDateOnly.push(item);
    else browsableUnknown.push(item);
  }
  return { comparable, browsableDateOnly, browsableUnknown };
}
