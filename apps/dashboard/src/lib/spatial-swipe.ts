/**
 * 밀어서 비교 경계의 순수 규칙 — 표시 전용, 측량·정합 판정 없음(INV-053).
 *
 * 경계값은 왼쪽(A)이 보이는 너비의 백분율이다. 0이면 전부 오른쪽(B),
 * 100이면 전부 왼쪽(A)이다. A/B 우열·기준/최신 같은 시간 서열을 짓지 않는다.
 */

/** 경계를 0‥100에 둔다. 수가 아니면 중립 50으로 둔다. */
export function clampSwipeBoundary(value: number): number {
  if (!Number.isFinite(value)) return 50;
  if (value < 0) return 0;
  if (value > 100) return 100;
  return value;
}

/**
 * 그립 드래그 경계 — 잡은 자리 기준 상대 이동분만 쓴다. 가장자리에서
 * 그립 표시 위치가 잘려 있어도 점프하지 않는다.
 */
export function swipeBoundaryFromPointer(
  startBoundary: number,
  startClientX: number,
  clientX: number,
  frameWidthPx: number,
): number {
  if (!(frameWidthPx > 0)) return clampSwipeBoundary(startBoundary);
  return clampSwipeBoundary(startBoundary + ((clientX - startClientX) / frameWidthPx) * 100);
}

/**
 * 슬라이더 키보드 한 칸 — 화살표 1, coarse(Page/Shift) 10, Home/End 양끝.
 * 비교 경계 키가 아니면 null(호출자가 브라우저 기본 동작에 맡긴다).
 */
export function swipeBoundaryStep(
  current: number,
  key: string,
  coarse: boolean,
): number | null {
  const base = clampSwipeBoundary(current);
  if (key === "ArrowLeft" || key === "ArrowDown") return clampSwipeBoundary(base - (coarse ? 10 : 1));
  if (key === "ArrowRight" || key === "ArrowUp") return clampSwipeBoundary(base + (coarse ? 10 : 1));
  if (key === "PageDown") return clampSwipeBoundary(base - 10);
  if (key === "PageUp") return clampSwipeBoundary(base + 10);
  if (key === "Home") return 0;
  if (key === "End") return 100;
  return null;
}

/** 왼쪽 레이어가 보이는 화면공간 클립 — 변환된 레이어 밖에 둔다. */
export function swipeClipInset(boundary: number): string {
  return `inset(0 ${100 - clampSwipeBoundary(boundary)}% 0 0)`;
}

/**
 * 그립 표시 위치 — 클립 경계는 양끝까지 가되, 44px 그립은 무대 안에
 * 둔다. 4px 여유는 그림자·키보드 포커스 링까지 보존한다.
 */
export function swipeGripLeft(boundary: number): string {
  return `clamp(26px, ${clampSwipeBoundary(boundary)}%, calc(100% - 26px))`;
}

/** 슬라이더 읽힘값 — A/B 백분율만 말하고 우열을 붙이지 않는다. */
export function swipeValueText(boundary: number, leftLabel: string, rightLabel: string): string {
  const left = Math.round(clampSwipeBoundary(boundary));
  return `${leftLabel} ${left}% · ${rightLabel} ${100 - left}%`;
}
