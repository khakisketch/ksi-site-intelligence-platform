/**
 * 화면 표시 뷰 상태(순수) — 이미 해독·검증된 픽셀 버퍼를 CSS로만 자르고
 * 늘이는 읽기 전용 규칙이다.
 *
 * - 준비·커버·영수증·원본 격자· frozen 분석 입력은 건드리지 않는다.
 * - zoom: 1(전체 보기)…4. 보이는 창 비율로 이동한다.
 * - cx/cy: 보이는 창의 중심(원본 버퍼 기준 정규화 0…1, y는 행 방향 아래가 +).
 * - 종횡비는 단일 zoom이라 항상 유지된다. 원본 버퍼 라벨(1022×915 등)은
 *   그대로 두고, 표시 확대율은 별도로 알린다("표시 확대 200%").
 * - 이동·확대는 네트워크 요청을 만들지 않는다. 그릴 수 없는 빈칸은
 *   영수증 판정 그대로(준비된 버퍼만 둔다) 둔다. 빈 곳은 미확인 범위이지
 *   새 데이터가 아니다.
 * - 보이는 창의 일부(최소 25%)가 원본 안에 남도록 둔다 — 전체 보기에서도
 *   자연스러운 끌기에 반응이 있고, 끝에서는 멈춘다.
 *
 * Invariants: INV-020(표시 뷰 ≠ 계산 다각형, 네이티브 버퍼만)/
 * INV-024(정량·정확도 주장 없음)/INV-040(지원하는 제스처만 힌트)/
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
/** 보이는 창이 원본과 겹쳐야 하는 최소 비율(프레임 기준) — 빈 곳은 미확인 범위다. */
export const DISPLAY_VIEW_MIN_VISIBLE = 0.25;

function clampCenter(value: number, zoom: number): number {
  const half = 0.5 / zoom;
  // 창 너비에서 최소 가시 너비를 뺀 만큼만 바깥으로 나갈 수 있다.
  const maxOver = 2 * half - DISPLAY_VIEW_MIN_VISIBLE / zoom;
  const lo = half - maxOver;
  const hi = 1 - half + maxOver;
  return Math.min(Math.max(value, lo), hi);
}

function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return DISPLAY_VIEW_MIN_ZOOM;
  return Math.min(Math.max(zoom, DISPLAY_VIEW_MIN_ZOOM), DISPLAY_VIEW_MAX_ZOOM);
}

export function clampDisplayView(view: DisplayViewState): DisplayViewState {
  const zoom = clampZoom(view.zoom);
  return { zoom, cx: clampCenter(view.cx, zoom), cy: clampCenter(view.cy, zoom) };
}

/**
 * 보이는 창 비율로 이동한다. +fx는 오른쪽을, +fy는 아래쪽을 본다.
 * 버튼·키·드래그·터치는 같은 규칙을 탄다. 끝까지 닿으면 moved=false.
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
  return zoomDisplayViewAt(view, direction === 1 ? 2 : 0.5, 0.5, 0.5);
}

/**
 * 프레임 안의 한 점(kx, ky: 0…1, y는 아래가 +)을 고정한 채 확대·축소한다.
 * 휠·핀치·두 번 두드리기·버튼이 같은 규칙을 탄다.
 */
export function zoomDisplayViewAt(
  view: DisplayViewState,
  factor: number,
  kx = 0.5,
  ky = 0.5,
): { view: DisplayViewState; moved: boolean } {
  if (!Number.isFinite(factor) || factor <= 0) return { view, moved: false };
  const zoom = clampZoom(view.zoom * factor);
  if (zoom === view.zoom) return { view, moved: false };
  const fx = Number.isFinite(kx) ? Math.min(Math.max(kx, 0), 1) : 0.5;
  const fy = Number.isFinite(ky) ? Math.min(Math.max(ky, 0), 1) : 0.5;
  // 현재 커서 아래의 원본 점을 구해 새 배율에서도 같은 자리에 둔다.
  // 표시 오프셋 t = 0.5 - c*z (프레임 단위).
  const tx = 0.5 - view.cx * view.zoom;
  const ty = 0.5 - view.cy * view.zoom;
  const sx = (fx - tx) / view.zoom;
  const sy = (fy - ty) / view.zoom;
  const ncx = (0.5 - (fx - sx * zoom)) / zoom;
  const ncy = (0.5 - (fy - sy * zoom)) / zoom;
  const next = clampDisplayView({ zoom, cx: ncx, cy: ncy });
  return { view: next, moved: true };
}

export function resetDisplayView(): DisplayViewState {
  return { ...DISPLAY_VIEW_DEFAULT };
}

/**
 * 휠 한 틱을 부드러운 배율로 바꾼다. 마우스 노치는 반 스톱, 트랙패드·핀치의
 * 작은 델타는 그대로 작은 단계가 된다. 2배 점프·드롭을 쓰지 않는다.
 */
export function wheelZoomFactor(deltaY: number, deltaMode = 0): number {
  if (!Number.isFinite(deltaY)) return 1;
  const unit = deltaMode === 1 ? deltaY * 16 : deltaY;
  const clamped = Math.max(-100, Math.min(100, unit));
  return Math.pow(2, -clamped / 200);
}

/**
 * 마우스 드래그 px를 보이는 창 비율로 바꾼다 — W/H는 보이는 그림 자체의
 * 배치 크기(늘이기 전)다. 내용은 커서를 따라 1:1로 간다.
 */
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
