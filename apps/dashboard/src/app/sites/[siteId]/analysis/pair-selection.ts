/**
 * 분석 기준·현재 관측 선택의 화면 안내 — 표현만 담당한다.
 *
 * - 이 모듈은 순수 함수만 두며 Core 클라이언트·fetch를 import하지 않는다.
 * - 촬영 구간 판독은 목록이 이미 가진 실제 captureStartedAt/captureEndedAt만
 *   쓴다. 구간을 모르거나 어긋난 조합은 요청 전에 막되, 그 판단이 분석
 *   적합성·정확도 인증이 아님을 문구에 남긴다. 최종 입장은 Core가 소유한다
 *   (INV-053).
 * - 같은 선택을 같은 요청으로 다시 보내는 보류 재시도(멱등 키·selector 고정)
 *   경로는 건드리지 않는다. 이 검사는 새 요청 조합에만 적용한다.
 */

export type PairIssueKind =
  | "missing-area"
  | "missing-baseline"
  | "missing-current"
  | "same"
  | "reversed"
  | "overlap"
  | "invalid-capture"
  | "ready";

export interface PairCaptureWindow {
  captureStartedAt: string;
  captureEndedAt: string;
}

export interface PairIssue {
  kind: PairIssueKind;
  /** kind가 ready면 빈 문자열. 화면은 이 문구를 그대로 보여준다. */
  message: string;
}

function parseEndpoint(value: string): number {
  return Date.parse(value);
}

/**
 * 두 관측의 촬영 구간 관계만으로 요청 전 안내를 만든다.
 * sameSelection은 selector 동등(같은 관측 선택) 여부다 — 시간 판독과 무관하게
 * 먼저 가른다.
 */
export function describePairSelection(input: {
  workAreaId: string;
  baseline: PairCaptureWindow | null;
  current: PairCaptureWindow | null;
  sameSelection: boolean;
}): PairIssue {
  if (!input.workAreaId) {
    return { kind: "missing-area", message: "작업구역을 먼저 선택하세요." };
  }
  if (!input.baseline) {
    return { kind: "missing-baseline", message: "기준 관측을 선택하세요. 현재 관측보다 먼저 끝난 관측이어야 합니다." };
  }
  if (!input.current) {
    return { kind: "missing-current", message: "현재 관측을 선택하세요. 기준 관측보다 나중에 끝난 관측이어야 합니다." };
  }
  if (input.sameSelection) {
    return { kind: "same", message: "기준과 현재에 같은 관측을 골랐습니다. 서로 다른 두 관측을 선택하세요." };
  }
  const baselineStart = parseEndpoint(input.baseline.captureStartedAt);
  const baselineEnd = parseEndpoint(input.baseline.captureEndedAt);
  const currentStart = parseEndpoint(input.current.captureStartedAt);
  const currentEnd = parseEndpoint(input.current.captureEndedAt);
  if (
    !Number.isFinite(baselineStart)
    || !Number.isFinite(baselineEnd)
    || !Number.isFinite(currentStart)
    || !Number.isFinite(currentEnd)
    || baselineStart > baselineEnd
    || currentStart > currentEnd
  ) {
    return {
      kind: "invalid-capture",
      message: "선택한 관측의 촬영 구간을 확인하지 못했습니다. 목록을 새로고침한 뒤 다시 선택하세요. 이 화면은 분석 적합성을 판정하지 않습니다.",
    };
  }
  if (baselineEnd <= currentStart) {
    return { kind: "ready", message: "" };
  }
  if (baselineStart >= currentEnd) {
    return {
      kind: "reversed",
      message: "기준 관측의 촬영이 현재 관측보다 늦게 끝났습니다(시간 역전). 기준은 현재보다 먼저 끝난 관측이어야 합니다. 선택을 바꾸세요. 최종 판단은 Core가 합니다.",
    };
  }
  return {
    kind: "overlap",
    message: "두 관측의 촬영 구간이 겹칩니다. 겹치지 않는 기준·현재 조합을 선택하세요. 최종 판단은 Core가 합니다.",
  };
}

/** 요청 전에 막아야 하는 알려진 문제 조합이다. ready·미선택은 포함하지 않는다. */
export function isKnownBadPairSelection(kind: PairIssueKind): boolean {
  return kind === "same" || kind === "reversed" || kind === "overlap" || kind === "invalid-capture";
}

/** 기준 선택이 비어 있을 때만 자동 제안을 허용한다. 직접 고른 값은 보존한다. */
export function shouldAutoSuggestBaseline(baselineIndex: string): boolean {
  return baselineIndex === "";
}
