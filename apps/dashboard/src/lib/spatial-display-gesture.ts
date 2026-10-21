/**
 * 화면 표시용 이동·확대 제스처의 순수 해석 규칙 — 바이트·권한·준비 판정 없음.
 *
 * - 네이티브 격자 안의 표시 뷰포트만 움직인다. WorkArea 계산 다각형도,
 *   Core 준비 기록도, frozen 분석 입력도 건드리지 않는다.
 * - 버튼 클릭과 제스처는 같은 규칙(클램프·최소 1픽셀·전체 보기 복귀)을 쓴다.
 *   호출자가 같은 `clampViewport`/`zoomViewport`/`shiftViewport`에 태우면 된다.
 * - 이 파일은 DOM·fetch를 import하지 않는다. 순수 수치 + 키 대응만 둔다.
 *
 * Invariants: INV-020(표시 뷰포트 ≠ 계산 다각형, 네이티브 격자만)/
 * INV-040(지원하는 제스처만 힌트)/INV-051(읽기만 — 준비 POST 없음)/
 * INV-060·061(권한·이그레스 변경 없음).
 */

/** 드래그(마우스) 커밋 비율 — 화면 px 이동을 뷰포트 너비·높이 비율로 바꾼다. */
export function dragToViewportFractions(
  dxCss: number,
  dyCss: number,
  containerWidthCss: number,
  containerHeightCss: number,
): { dCol: number; dRow: number } | null {
  if (
    !Number.isFinite(dxCss) ||
    !Number.isFinite(dyCss) ||
    !(containerWidthCss > 0) ||
    !(containerHeightCss > 0)
  ) {
    return null;
  }
  // 내용은 커서를 따라간다: 오른쪽으로 끌면 왼쪽 내용이 보이므로
  // 뷰포트는 왼쪽으로(dCol 음수), 아래로 끌면 위 내용이 보이므로
  // 뷰포트는 위쪽으로(네이티브 y+ 방향, dRow 양수) 이동한다.
  return { dCol: -dxCss / containerWidthCss, dRow: dyCss / containerHeightCss };
}

/** 키보드 표시 이동 — 페이지를 가로채지 않도록 포커스된 보기 안에서만 쓴다. */
export type DisplayGestureKeyAction =
  | { kind: "pan"; dCol: number; dRow: number }
  | { kind: "zoom"; factor: number }
  | { kind: "reset" };

const PAN_STEP = 0.25;

/**
 * 표시 보기 키 대응 — 화살표·+ −·Home만 받는다. 그 밖은 null(페이지 기본 동작 유지).
 * IME 조합 중이면 호출자가 먼저 걸러야 한다.
 */
export function displayGestureKeyAction(key: string): DisplayGestureKeyAction | null {
  switch (key) {
    case "ArrowLeft": return { kind: "pan", dCol: -PAN_STEP, dRow: 0 };
    case "ArrowRight": return { kind: "pan", dCol: PAN_STEP, dRow: 0 };
    case "ArrowUp": return { kind: "pan", dCol: 0, dRow: PAN_STEP };
    case "ArrowDown": return { kind: "pan", dCol: 0, dRow: -PAN_STEP };
    case "+":
    case "=": return { kind: "zoom", factor: 0.5 };
    case "-":
    case "_": return { kind: "zoom", factor: 2 };
    case "Home": return { kind: "reset" };
    default: return null;
  }
}

/**
 * 휠 확대 의도 판정 — 포커스된 보기 안의 휠이거나 Ctrl(핀치 확대 제스처)과
 * 함께일 때만 true. 그 밖의 휠은 페이지 스크롤로 둔다(스크롤 가로채기 금지).
 */
export function isDisplayZoomWheelIntent(input: {
  focused: boolean;
  ctrlKey: boolean;
}): boolean {
  return input.focused || input.ctrlKey;
}

/** 휠 연속 확대 폭주 방지 — 마지막 적용 시각과의 최소 간격(ms)을 둔다. */
export const DISPLAY_WHEEL_THROTTLE_MS = 120;

export function displayWheelReady(lastAppliedAt: number, now: number): boolean {
  return now - lastAppliedAt >= DISPLAY_WHEEL_THROTTLE_MS;
}

/** 지원하는 제스처 안내 한 줄 — 없는 제스처(핀치·터치 드래그)는 적지 않는다. */
export const DISPLAY_GESTURE_HINT =
  "마우스로 끌거나 방향키로 이동하고, + − 키 또는 휠(그림 선택 후·Ctrl과 함께)로 확대합니다. 화면 이동·확대는 표시용이며 측정값이 아닙니다.";
