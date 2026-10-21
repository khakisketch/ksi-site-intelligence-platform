/**
 * 화면 표시용 이동·확대 제스처의 순수 해석 규칙 — 바이트·권한·준비 판정 없음.
 *
 * - 이미 해독·검증된 버퍼의 CSS 표시만 움직인다. WorkArea 계산 다각형도,
 *   Core 준비 기록도, frozen 분석 입력도 건드리지 않는다.
 * - 버튼 클릭과 제스처는 `spatial-display-view`의 같은 표시 뷰 규칙을 쓴다.
 * - 이 파일은 DOM·fetch를 import하지 않는다. 순수 수치 + 키 대응만 둔다.
 *
 * Invariants: INV-020(표시 뷰 ≠ 계산 다각형, 네이티브 격자만)/
 * INV-040(지원하는 제스처만 힌트)/INV-051(읽기만 — 준비 POST 없음)/
 * INV-060·061(권한·이그레스 변경 없음).
 */

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

/** 지원하는 제스처 안내 한 줄 — 구현된 것만 적는다. */
export const DISPLAY_GESTURE_HINT =
  "그림을 직접 끌어서 보고, 휠·두 손가락·두 번 두드리기 또는 + − 키로 확대합니다. 그림을 선택하면 방향키·Home 키도 쓸 수 있습니다. 화면 이동·확대는 표시용이며 측정값이 아닙니다.";
