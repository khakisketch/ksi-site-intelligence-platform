import { useRef, useState } from "react";

/**
 * 화면 표시 뷰 상태(순수 + 작은 훅) — 이미 해독·검증된 픽셀 버퍼를 CSS로만
 * 자르고 늘이는 읽기 전용 규칙이다.
 *
 * - 준비·커버·영수증·원본 격자· frozen 분석 입력은 건드리지 않는다.
 * - zoom: 1(전체 보기)…4, 2배씩. 보이는 창 비율로 이동한다.
 * - cx/cy: 보이는 창의 중심(원본 버퍼 기준 정규화 0…1, y는 행 방향 아래가 +).
 * - 종횡비는 단일 zoom이라 항상 유지된다. 원본 버퍼 라벨(1022×915 등)은
 *   그대로 두고, 표시 확대율은 별도로 알린다("표시 확대 200%").
 * - 이동·확대는 네트워크 요청을 만들지 않는다. 그릴 수 없는 빈칸은
 *   영수증 판정 그대로(준비된 버퍼만 둔다) 둔다.
 *
 * Invariants: INV-020(표시 뷰 ≠ 계산 다각형, 네이티브 버퍼만)/
 * INV-024(정량·정확도 주장 없음)/INV-040(지원 제스처만 힌트)/
 * INV-051(읽기만 — 준비 POST 없음)/INV-060·061(권한·이그레스 변경 없음).
 */

export interface DisplayViewState {
  zoom: number;
  cx: number;
  cy: number;
}

export const DISPLAY_VIEW_DEFAULT: DisplayViewState = { zoom: 1, cx: 0.5, cy: 0.5 };
export const DISPLAY_VIEW_MIN_ZOOM = 1;
export const DISPLAY_VIEW_MAX_ZOOM = 4;

function halfWindow(zoom: number): number {
  return 0.5 / zoom;
}

function clampCenter(value: number, zoom: number): number {
  const half = halfWindow(zoom);
  if (half >= 0.5) return 0.5;
  return Math.min(Math.max(value, half), 1 - half);
}

/** 같은 단계로 돌린다 — 소수점 누적·종횡비 깨짐이 없다. */
export function clampDisplayView(view: DisplayViewState): DisplayViewState {
  const zoom = Math.min(Math.max(view.zoom, DISPLAY_VIEW_MIN_ZOOM), DISPLAY_VIEW_MAX_ZOOM);
  return { zoom, cx: clampCenter(view.cx, zoom), cy: clampCenter(view.cy, zoom) };
}

/**
 * 보이는 창 비율로 이동한다. +fx는 오른쪽을, +fy는 아래쪽을 본다.
 * 버튼·키·드래그는 같은 규칙을 탄다. 끝에 닿아 움직이지 않으면 moved=false.
 */
export function panDisplayView(
  view: DisplayViewState,
  fx: number,
  fy: number,
): { view: DisplayViewState; moved: boolean } {
  if (!Number.isFinite(fx) || !Number.isFinite(fy)) return { view, moved: false };
  const next = clampDisplayView({
    zoom: view.zoom,
    cx: view.cx + fx / view.zoom,
    cy: view.cy + fy / view.zoom,
  });
  const moved = next.cx !== view.cx || next.cy !== view.cy;
  return { view: next, moved };
}

/**
 * 같은 중심에서 2배씩 확대·축소한다. 끝에 닿으면 moved=false.
 * 축소 끝(z=1)은 전체 보기와 같다.
 */
export function zoomDisplayView(
  view: DisplayViewState,
  direction: 1 | -1,
): { view: DisplayViewState; moved: boolean } {
  const zoom = direction === 1
    ? Math.min(view.zoom * 2, DISPLAY_VIEW_MAX_ZOOM)
    : Math.max(view.zoom / 2, DISPLAY_VIEW_MIN_ZOOM);
  const next = clampDisplayView({ zoom, cx: view.cx, cy: view.cy });
  return { view: next, moved: next.zoom !== view.zoom };
}

export function resetDisplayView(): DisplayViewState {
  return { ...DISPLAY_VIEW_DEFAULT };
}

/** 마우스 드래그 px를 보이는 창 비율로 바꾼다 — 내용은 커서를 따라간다. */
export function displayDragFractions(
  dxCss: number,
  dyCss: number,
  frameWidthCss: number,
  frameHeightCss: number,
): { fx: number; fy: number } | null {
  if (
    !Number.isFinite(dxCss) ||
    !Number.isFinite(dyCss) ||
    !(frameWidthCss > 0) ||
    !(frameHeightCss > 0)
  ) {
    return null;
  }
  return { fx: -dxCss / frameWidthCss, fy: -dyCss / frameHeightCss };
}

/**
 * 원본 버퍼를 그대로 두는 CSS 변환. 보이는 중심(cx,cy)이 프레임 중앙에 오고
 * 나머지는 감싼 프레임(overflow hidden)이 자른다. 측정·리사이즈가 필요 없다.
 */
export function displayViewTransform(view: DisplayViewState): string {
  const tx = (0.5 - view.cx * view.zoom) * 100;
  const ty = (0.5 - view.cy * view.zoom) * 100;
  return `translate(${tx}% , ${ty}%) scale(${view.zoom})`;
}

/** "표시 확대 200%" 같은 별도 안내용 백분율 — 원본 버퍼 크기와 구분한다. */
export function displayZoomPercent(view: DisplayViewState): number {
  return Math.round(view.zoom * 100);
}

export function isDisplayViewMoved(view: DisplayViewState): boolean {
  return view.zoom !== 1 || view.cx !== 0.5 || view.cy !== 0.5;
}

/** 버튼·키·드래그·휠이 같은 상태를 쓰는 작은 훅 — 네트워크를 모른다. */
export function useDisplayViewState() {
  const [view, setView] = useState<DisplayViewState>(DISPLAY_VIEW_DEFAULT);
  // 리스너·핸들러가 오래된 렌더를 닫아도 최신 상태에서 계산한다. ref 읽기·
  // 쓰기는 렌더가 아니라 액션 안에서만 한다.
  const latestRef = useRef<DisplayViewState>(DISPLAY_VIEW_DEFAULT);
  const apply = (next: { view: DisplayViewState; moved: boolean }): boolean => {
    if (next.moved) {
      latestRef.current = next.view;
      setView(next.view);
    }
    return next.moved;
  };
  return {
    view,
    pan: (fx: number, fy: number): boolean => apply(panDisplayView(latestRef.current, fx, fy)),
    zoom: (direction: 1 | -1): boolean => apply(zoomDisplayView(latestRef.current, direction)),
    reset: () => {
      const next = resetDisplayView();
      latestRef.current = next;
      setView(next);
    },
  };
}
