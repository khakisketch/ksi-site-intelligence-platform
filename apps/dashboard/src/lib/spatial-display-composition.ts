/**
 * 영수증 검증된 창들의 화면 배치(순수 함수).
 *
 * 표시/LOD 계약 §3(인접 창은 정수 경계를 공유한다)과 §4(화면 구성은
 * 검증된 창의 나란한 배치이며 이음새 보정·재표본화가 없다)의 Console
 * 측 배치 규칙이다. 정량 계산·보정·판정을 하지 않는다.
 *
 * - 그릴 수 있는のは 영수증 사실(pixelWindow/actualBounds/sha/size)이
 *   확인된 창뿐이다. 확인되지 않은 창은 명시적 틈(explicit gap)으로
 *   남기며, 늘이거나 메우지 않는다.
 * - 배치는 표시용 조립(display assembly)이며, 하나의 검증된 자료가
 *   아니고 측정 근거가 아니다 — 라벨로 밝힌다.
 * - 세 상태(감사 무결성·검증 적합성·화면 표시 가능성)는 합성 깃발로
 *   묶지 않는다. 이 모듈은 표시 가능성 배치만 말한다.
 */

export type DisplayHalfOpenWindow = [number, number, number, number];

export interface ReceiptVerifiedWindow {
  key: string;
  pixelWindow: DisplayHalfOpenWindow;
  actualBounds: readonly [number, number, number, number];
  width: number;
  height: number;
  /** 영수증 대조를 통과했는지 — 호출자가 그린다는 뜻이다. */
  receiptVerified: boolean;
}

export type DisplayGapReason =
  | "NOT_REQUESTED"
  | "PREPARE_FAILED"
  | "RECEIPT_MISMATCH"
  | "RIGHTS_UNAVAILABLE";

export interface DisplayCompositionGap {
  pixelWindow: DisplayHalfOpenWindow;
  reason: DisplayGapReason;
  message: string;
}

export interface DisplayCompositionPlan {
  placed: ReceiptVerifiedWindow[];
  gaps: DisplayCompositionGap[];
  /** 겹침이 없고 배치된 창이 있으면 true다. */
  seamless: boolean;
  overlapErrors: string[];
}

/** 표시 조립의 고정 문구 — 검증된 자료로 읽히지 않게 한다. */
export const DISPLAY_ASSEMBLY_LABEL = "검증된 준비 창의 나란한 배치 — 이음새 보정·재표본화 없음";
export const DISPLAY_ASSEMBLY_NOTE =
  "각 창은 Core 준비 기록과 바이트가 일치할 때만 그린 독립 영수증의 화면 배치입니다. 하나의 검증된 자료가 아니며, 정확도 평가·측량·정산 근거가 아닙니다. 체적·면적 등 정량 계산을 하지 않습니다.";

export const DISPLAY_GAP_COPY: Record<DisplayGapReason, string> = {
  NOT_REQUESTED: "아직 준비하지 않은 창이라 비워 둡니다. 빈칸을 메우거나 늘이지 않습니다.",
  PREPARE_FAILED: "창 준비가 끝나지 않아 비워 둡니다. 준비가 끝나면 그때 그립니다.",
  RECEIPT_MISMATCH: "받은 바이트가 Core 준비 기록과 달라 그리지 않고 비워 둡니다.",
  RIGHTS_UNAVAILABLE: "요청을 찾을 수 없거나 현재 조회할 수 없습니다. 다른 계정이 준비한 창은 이 화면에서 열 수 없습니다.",
};

function rangesOverlap(a0: number, a1: number, b0: number, b1: number): boolean {
  return a0 < b1 && b0 < a1;
}

export function windowsOverlap(
  a: DisplayHalfOpenWindow,
  b: DisplayHalfOpenWindow,
): boolean {
  return rangesOverlap(a[0], a[1], b[0], b[1]) && rangesOverlap(a[2], a[3], b[2], b[3]);
}

/**
 * 두 창이 한 변을 정확히 공유하는지 — 정수 경계가 같아야 한다.
 * 부동소수 actualBounds가 아니라 정수 pixelWindow로만 본다.
 */
export function windowsAbut(a: DisplayHalfOpenWindow, b: DisplayHalfOpenWindow): boolean {
  const horizontalShare = a[0] === b[1] || a[1] === b[0];
  const horizontalRowsOverlap = rangesOverlap(a[2], a[3], b[2], b[3]);
  const verticalShare = a[2] === b[3] || a[3] === b[2];
  const verticalColsOverlap = rangesOverlap(a[0], a[1], b[0], b[1]);
  return (horizontalShare && horizontalRowsOverlap) || (verticalShare && verticalColsOverlap);
}

/**
 * 검증된 창들을 나란히 둔다. 겹침은 오류로 보고하고, 호출자가
 * 기대 범위에서 빠졌다고 알린 창은 명시적 틈으로 남긴다.
 */
export function composeDisplayWindows(
  windows: readonly ReceiptVerifiedWindow[],
  gaps: readonly DisplayCompositionGap[] = [],
): DisplayCompositionPlan {
  const placed = [...windows]
    .filter((item) => item.receiptVerified)
    .sort((a, b) => a.pixelWindow[2] - b.pixelWindow[2] || a.pixelWindow[0] - b.pixelWindow[0]);
  const overlapErrors: string[] = [];
  for (let i = 0; i < placed.length; i += 1) {
    for (let j = i + 1; j < placed.length; j += 1) {
      const a = placed[i] as ReceiptVerifiedWindow;
      const b = placed[j] as ReceiptVerifiedWindow;
      if (windowsOverlap(a.pixelWindow, b.pixelWindow)) {
        overlapErrors.push(`창 ${a.key}와(과) 창 ${b.key}의 픽셀 범위가 겹칩니다. 겹쳐 그리지 않습니다.`);
      }
    }
  }
  const unverified = windows.filter((item) => !item.receiptVerified);
  const allGaps: DisplayCompositionGap[] = [
    ...unverified.map((item) => ({
      pixelWindow: item.pixelWindow,
      reason: "RECEIPT_MISMATCH" as DisplayGapReason,
      message: DISPLAY_GAP_COPY.RECEIPT_MISMATCH,
    })),
    ...gaps,
  ];
  return {
    placed,
    gaps: allGaps,
    seamless: overlapErrors.length === 0 && placed.length > 0,
    overlapErrors,
  };
}

/** 배치된 창 집합이 기대 범위를 빠짐없이 덮는지 — 모자라면 틈이다. */
export function missingCoverCells(
  cover: readonly DisplayHalfOpenWindow[],
  placed: readonly ReceiptVerifiedWindow[],
  reason: DisplayGapReason,
): DisplayCompositionGap[] {
  const placedKeys = new Set(
    placed.map((item) => item.pixelWindow.join(",")),
  );
  return cover
    .filter((cell) => !placedKeys.has(cell.join(",")))
    .map((cell) => ({ pixelWindow: cell, reason, message: DISPLAY_GAP_COPY[reason] }));
}
