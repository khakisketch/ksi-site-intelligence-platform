import type { AnalysisSelector } from "./core-api/analysis";

/**
 * 더 새 관측 존재 알림 — 읽기 시점 파생 투영.
 *
 * Core에 쓰지 않고, 이전 기록을 다시 쓰지도 않는다. 호출자가 이미 조회한
 * 읽기 전용 기록(관측 후보, 불러온 분석 상세)만으로 "같은 작업구역에 현재
 * 결과보다 늦게 끝난 관측이 있는가"를 판단한다.
 *
 * 강제하는 경계:
 * - 이 판단은 정량 적합성 판정이 아니다. 반환값에는 suitability/execution/
 *   수치 필드가 없으며, 호출자는 이 알림으로 이전 결과의 수치·상태·검토를
 *   바꾸지 않는다 (3층 판정 분리).
 * - 이전 기록에 새 상태를 부여하지 않는다. "대체됨/구버전" 같은 표현을
 *   만들지 않으며, 알림 문안은 호출자(UI)가 중립 문구로만 둔다.
 * - 조직·현장 범위는 호출자가 이미 강제한다. 이 함수는 전달받은 후보만
 *   비교하고 범위 밖 존재를 추론·노출하지 않는다 (INV-060).
 * - 결과 자신의 epoch 시각은 Site 범위 목록에서 선택자 일치로만 찾는다.
 *   작업구역 귀속이 없어도 시각을 추측하지 않으며, 찾지 못하면 알림을
 *   만들지 않는다. "더 새 관측" 후보 집합은 해당 작업구역에 귀속된 관측으로
 *   유지한다 — "이 작업구역에 더 새 관측이 있습니다"가 문자 그대로 참이다.
 * - 새 관측의 바이트·수치를 이전 결과의 정정으로 제시하지 않는다 (INV-051).
 *   링크는 새 분석의 결과 화면 이동일 뿐이다.
 */

export type NewerObservationCandidate = {
  selector: AnalysisSelector;
  captureStartedAt: string;
  captureEndedAt: string;
  workAreaIds: readonly string[];
};

export type NewerAnalysisCandidate = {
  analysisId: string;
  workAreaId: string;
  currentSelector: AnalysisSelector;
  /** 새 분석의 결과가 실제로 존재할 때만 참이다. */
  hasResult: boolean;
};

export type NewerObservationNotice = {
  /** 화면에 표시할 새 관측의 종료 시각(원문 ISO). */
  captureEndedAt: string;
  workOrderId: string;
  submissionRef: string;
  revision: number;
  /**
   * 더 새 관측을 현재 관측으로 삼은 분석 중 결과가 있는 가장 최근 분석의 ID.
   * 그런 분석을 읽지 못했으면 null이며, 이때는 링크 없이 사실만 말한다.
   */
  analysisId: string | null;
};

/**
 * Core 읽기 투영의 공유 epoch 연결을 단일 중립 링크로 고른다.
 *
 * Core는 같은 작업구역에서 이 기록의 현재 선택자와 정확히 같은 기준
 * 선택자를 가진 분석 ID를 `newerSiblingAnalysisIds`로 내놓는다(쓰기 없음,
 * 수치·적합성 판단 없음). 시간 파생 알림이 불가할 때만 이 값을 써서 같은
 * 자리에 한 줄로 알린다. 자기 자신은 제외하고, 결정적 순서(생성 시각,
 * ID — Core가 이미 정렬해 전달)를 유지한다. 대체·구버전 표현을 만들지
 * 않으며, 호출자는 이 ID로 새 분석 상세를 읽어 이동만 한다.
 */
export function selectCoreNewerSiblingId(
  siblingIds: readonly string[] | null | undefined,
  selfAnalysisId: string,
): string | null {
  if (!siblingIds) return null;
  for (const candidate of siblingIds) {
    if (typeof candidate !== "string" || candidate.length === 0) continue;
    if (candidate === selfAnalysisId) continue;
    return candidate;
  }
  return null;
}

function sameSelector(left: AnalysisSelector, right: AnalysisSelector): boolean {
  return (
    left.workOrderId === right.workOrderId &&
    left.submissionRef === right.submissionRef &&
    left.revision === right.revision
  );
}

function selectorKey(selector: AnalysisSelector): string {
  return `${selector.workOrderId}|${selector.submissionRef}|${selector.revision}`;
}

function parseTime(value: string): number {
  return Date.parse(value);
}

export type EpochCaptureIdentity = {
  selector: AnalysisSelector;
  captureEndedAt: string;
};

/**
 * 결과 자신의 epoch 종료 시각을 Site 범위 관측 목록에서 찾는다.
 * 작업구역 귀속 여부와 무관하게 선택자 일치만 본다 — 귀속이 없는 epoch라도
 * 시각 추측 없이 원문 기록에서 읽는다. 찾지 못하면 null이며, 호출자는
 * 그때 알림을 만들지 않는다 (추측 금지).
 */
export function findEpochCaptureEndedAt(
  siteObservations: readonly EpochCaptureIdentity[],
  selector: AnalysisSelector,
): string | null {
  const found = siteObservations.find((option) => sameSelector(option.selector, selector));
  return found ? found.captureEndedAt : null;
}

export function deriveNewerObservationNotice(args: {
  workAreaId: string;
  currentSelector: AnalysisSelector;
  currentCaptureEndedAt: string;
  observations: readonly NewerObservationCandidate[];
  analyses: readonly NewerAnalysisCandidate[];
}): NewerObservationNotice | null {
  const currentEnd = parseTime(args.currentCaptureEndedAt);
  if (!Number.isFinite(currentEnd)) return null;

  const newer = args.observations.filter((option) => {
    if (!option.workAreaIds.includes(args.workAreaId)) return false;
    if (sameSelector(option.selector, args.currentSelector)) return false;
    const end = parseTime(option.captureEndedAt);
    if (!Number.isFinite(end)) return false;
    // 엄격히 더 늦게 끝난 관측만 "더 새 관측"이다. 같은 시각은 제외한다.
    return end > currentEnd;
  });
  if (newer.length === 0) return null;

  const byRecency = [...newer].sort((left, right) => {
    const timeDelta = parseTime(right.captureEndedAt) - parseTime(left.captureEndedAt);
    if (timeDelta !== 0) return timeDelta;
    return selectorKey(left.selector) < selectorKey(right.selector) ? -1 : 1;
  });

  // 링크는 "결과가 실제로 있는 새 분석"에만 건다. 같은 작업구역에서 결과를
  // 가진 분석 중, 더 새 관측을 현재 관측으로 삼은 가장 최근 분석을 고른다.
  // 관측 후보와 선택자가 이어지지 않는 분석(읽지 못한 상세 등)은 링크하지
  // 않는다 — 가짜 결과 링크를 만들지 않기 위해서다.
  const completedBySelector = new Map<string, string>();
  for (const analysis of args.analyses) {
    if (analysis.workAreaId !== args.workAreaId) continue;
    if (!analysis.hasResult) continue;
    const key = selectorKey(analysis.currentSelector);
    if (!completedBySelector.has(key)) completedBySelector.set(key, analysis.analysisId);
  }
  let linked: { option: NewerObservationCandidate; analysisId: string } | null = null;
  for (const option of byRecency) {
    const analysisId = completedBySelector.get(selectorKey(option.selector));
    if (analysisId) {
      linked = { option, analysisId };
      break;
    }
  }

  // 알림이 가리키는 관측과 링크 대상은 항상 같은 관측이다. 더 새 관측 중
  // 결과 있는 분석이 하나도 없으면 가장 최근 관측을 링크 없이 말한다.
  const shown = linked?.option ?? byRecency[0]!;
  return {
    captureEndedAt: shown.captureEndedAt,
    workOrderId: shown.selector.workOrderId,
    submissionRef: shown.selector.submissionRef,
    revision: shown.selector.revision,
    analysisId: linked?.analysisId ?? null,
  };
}
