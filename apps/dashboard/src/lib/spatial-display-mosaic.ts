/**
 * 여러 창의 이어 보기(모자이크) 상태·배치 — 순수 함수 + 세션 범위 보관.
 *
 * 표시/LOD 계약 §3(인접 창은 정수 경계를 공유한다)과 §4(화면 구성은
 * 검증된 창의 나란한 배치이며 이음새 보정·재표본화가 없다)의 Console 측
 * 이어 보기 규칙이다. 정량 계산·보정·판정을 하지 않는다.
 *
 * - 그릴 수 있는 것은 영수증 사실(출력 크기·전체 SHA-256)이 확인된
 *   창의 바이트뿐이다. 확인되지 않은 창은 명시적 틈(explicit gap)으로
 *   남기며, 늘이거나 메우거나 겹쳐 그리지 않는다.
 * - 배치는 표시용 조립(display assembly)이며, 하나의 검증된 자료가
 *   아니고 측정 근거가 아니다 — 라벨로 밝힌다.
 * - 한 탭의 보관(MosaicPaintCache)은 같은 세션의 주인에게만 내놓는다.
 *   권리·격자·영수증의 판정은 Core가 그대로 소유하며, 이 보관은 같은
 *   세션 안에서만 반복 보기(pan-back)를 새 PREPARE 없이 돌려준다.
 * - 뷰포트는 계산 다각형이 아니며 측정값이 아니다. 같은 격자의 같은
 *   영역은 항상 같은 창 집합으로 해석되므로(소스 원점 기준 분할),
 *   뒤로 돌아온 보기는 새 PREPARE 없이 보관 적중이 된다.
 *
 * Invariants: INV-020(면적 어림 없음 — 범위 판정 없음)/INV-024(원본 식별
 * 보존)/INV-053(네이티브 격자 — 좌표 재해석 없음)/INV-060·061(권한·이그레스).
 */

export type { DisplayGapReason } from "./spatial-display-composition";
import {
  DISPLAY_ASSEMBLY_LABEL,
  DISPLAY_ASSEMBLY_NOTE,
  composeDisplayWindows,
  missingCoverCells,
  type DisplayCompositionGap,
  type DisplayGapReason,
  type DisplayHalfOpenWindow,
} from "./spatial-display-composition";
import {
  saturatedLaneCopy,
  stablePrepareKey,
  type DisplayPreparePurpose,
  type ScheduledDisplayWindow,
} from "./spatial-display-scheduler";
import {
  VIEWPORT_RESOLVE_COPY,
  resolveViewportWindows,
  type DisplaySourceGrid,
  type DisplayViewportBounds,
  type DisplayWindowPlan,
} from "./spatial-display-viewport";

/** 이어 보기의 고정 문구 — 검증된 자료로 읽히지 않게 한다. */
export const MOSAIC_ASSEMBLY_HEADING = "이어 보기 — 여러 창의 나란한 배치";
export const MOSAIC_ASSEMBLY_LABEL = DISPLAY_ASSEMBLY_LABEL;
export const MOSAIC_ASSEMBLY_NOTE = DISPLAY_ASSEMBLY_NOTE;
/** 뷰포트는 계산이 아니라는 고정 문구 — 측정으로 읽히지 않게 한다. */
export const MOSAIC_VIEWPORT_NOTE =
  "이 보기의 이동·확대는 화면 표시용이며 측정값이 아닙니다. 계산 다각형이 아닙니다.";

export { VIEWPORT_RESOLVE_COPY };

/** 한 창의 화면 상태 — "준비 중"은 가짜 내용이 아니라 이름 있는 빈칸이다. */
export type MosaicCellPhase = "waiting" | "painted" | "gap";

export interface MosaicCellView {
  key: string;
  plan: DisplayWindowPlan;
  phase: MosaicCellPhase;
  /** 사람용 한 줄 — 픽셀 창·상태·사유만 둔다. */
  detail: string;
  gapReason: DisplayGapReason | null;
}

export interface MosaicCellInput {
  key: string;
  plan: DisplayWindowPlan;
  /** 영수증이 대조된 바이트를 보관에 두었는지. */
  painted: boolean;
  /** 바이트를 받고·푸는 중인지. */
  fetching: boolean;
  /** 준비 요청이 나가 있거나 대기열에 있는지. */
  preparing: boolean;
  failure: { reason: DisplayGapReason; message: string } | null;
}

/** 대기 중인 창의 이름 있는 빈칸 문구 — 실제 영역과 함께 둔다. */
export function mosaicWaitingCopy(
  plan: DisplayWindowPlan,
  kind: "fetching" | "preparing",
): string {
  const area = `[${plan.pixelWindow.join(", ")}]`;
  return kind === "fetching"
    ? `준비 중 · ${area} 창의 바이트를 받고 있습니다. 가짜 내용을 채우지 않습니다.`
    : `준비 중 · ${area} 창의 준비를 기다립니다. 빈칸을 메우거나 늘이지 않습니다.`;
}

export function mosaicPaintedCopy(plan: DisplayWindowPlan): string {
  return `그린 창 · ${plan.width} × ${plan.height} 픽셀 · [${plan.pixelWindow.join(", ")}]`;
}

/**
 * 한 창의 화면 상태를 고른다. 그리는(painted) 것은 호출자가 영수증
 * 대조를 마친 바이트를 보관에 두었을 때뿐이다.
 */
export function mosaicCellView(input: MosaicCellInput): MosaicCellView {
  const { key, plan, painted, fetching, preparing, failure } = input;
  if (painted) {
    return { key, plan, phase: "painted", detail: mosaicPaintedCopy(plan), gapReason: null };
  }
  if (failure) {
    return { key, plan, phase: "gap", detail: failure.message, gapReason: failure.reason };
  }
  if (fetching) {
    return { key, plan, phase: "waiting", detail: mosaicWaitingCopy(plan, "fetching"), gapReason: null };
  }
  if (preparing) {
    return { key, plan, phase: "waiting", detail: mosaicWaitingCopy(plan, "preparing"), gapReason: null };
  }
  return {
    key,
    plan,
    phase: "gap",
    detail: "아직 준비하지 않은 창이라 비워 둡니다. 빈칸을 메우거나 늘이지 않습니다.",
    gapReason: "NOT_REQUESTED",
  };
}

/** 이어 보기 한 화면의 캔버스 기하 — 정수 픽셀 크기 그대로다. */
export interface MosaicCanvasGeometry {
  width: number;
  height: number;
  originC0: number;
  originR0: number;
}

export function mosaicCanvasGeometry(cover: readonly DisplayWindowPlan[]): MosaicCanvasGeometry | null {
  if (cover.length === 0) return null;
  let minC0 = Number.POSITIVE_INFINITY;
  let maxC1 = Number.NEGATIVE_INFINITY;
  let minR0 = Number.POSITIVE_INFINITY;
  let maxR1 = Number.NEGATIVE_INFINITY;
  for (const plan of cover) {
    const [c0, c1, r0, r1] = plan.pixelWindow;
    if (c0 < minC0) minC0 = c0;
    if (c1 > maxC1) maxC1 = c1;
    if (r0 < minR0) minR0 = r0;
    if (r1 > maxR1) maxR1 = r1;
  }
  if (
    !Number.isInteger(minC0) || !Number.isInteger(maxC1) ||
    !Number.isInteger(minR0) || !Number.isInteger(maxR1) ||
    !(minC0 < maxC1) || !(minR0 < maxR1)
  ) {
    return null;
  }
  return { width: maxC1 - minC0, height: maxR1 - minR0, originC0: minC0, originR0: minR0 };
}

export interface MosaicPlacement {
  plan: DisplayWindowPlan;
  /** 캔버스 안의 정수 오프셋 — 리샘플링 없이 그대로 둔다. */
  dx: number;
  dy: number;
}

/**
 * 각 창의 캔버스 오프셋 — 커버 원점에서의 차이 그대로이며,
 * 반올림·늘이기·겹치기를 하지 않는다.
 */
export function mosaicPlacements(
  cover: readonly DisplayWindowPlan[],
  geometry: MosaicCanvasGeometry,
): MosaicPlacement[] {
  return [...cover]
    .sort((a, b) => a.pixelWindow[2] - b.pixelWindow[2] || a.pixelWindow[0] - b.pixelWindow[0])
    .map((plan) => ({
      plan,
      dx: plan.pixelWindow[0] - geometry.originC0,
      dy: plan.pixelWindow[2] - geometry.originR0,
    }));
}

/**
 * RGBA 바이트를 캔버스 버퍼의 정확한 위치에 그대로 옮긴다.
 * 리샘플링·혼합·늘이기를 하지 않으며, 범위를 벗어나면 그리지 않고
 * 알린다(조용히 자르지 않는다).
 */
export function placeWindowPixels(
  dest: Uint8ClampedArray,
  destWidth: number,
  destHeight: number,
  src: Uint8ClampedArray,
  srcWidth: number,
  srcHeight: number,
  dx: number,
  dy: number,
): void {
  if (!Number.isInteger(dx) || !Number.isInteger(dy) || dx < 0 || dy < 0) {
    throw new Error("모자이크 배치가 정수 캔버스 위치가 아니라 그리지 않습니다.");
  }
  if (src.length !== srcWidth * srcHeight * 4) {
    throw new Error("창 바이트 크기가 창 픽셀 크기와 달라 그리지 않습니다.");
  }
  if (dest.length !== destWidth * destHeight * 4) {
    throw new Error("이어 보기 버퍼 크기가 화면 크기와 달라 그리지 않습니다.");
  }
  if (dx + srcWidth > destWidth || dy + srcHeight > destHeight) {
    throw new Error("창이 이어 보기 화면을 벗어나 그리지 않습니다.");
  }
  const rowBytes = srcWidth * 4;
  const destRowBytes = destWidth * 4;
  for (let row = 0; row < srcHeight; row += 1) {
    const from = row * rowBytes;
    const to = (dy + row) * destRowBytes + dx * 4;
    dest.set(src.subarray(from, from + rowBytes), to);
  }
}

/**
 * 커버 전체를 확인할 수 있는 합성 검사 — 겹침이 있으면 오류로
 * 알리고 겹쳐 그리지 않는다. 호출자는 composeDisplayWindows의
 * 판정을 그대로 쓴다.
 */
export function checkMosaicSeamless(
  painted: readonly DisplayWindowPlan[],
  cover: readonly DisplayHalfOpenWindow[],
  missingReason: DisplayGapReason,
): { overlapErrors: string[]; gaps: DisplayCompositionGap[]; seamless: boolean } {
  const verified = painted.map((plan) => ({
    key: plan.pixelWindow.join(","),
    pixelWindow: plan.pixelWindow,
    actualBounds: plan.actualBounds as readonly [number, number, number, number],
    width: plan.width,
    height: plan.height,
    receiptVerified: true,
  }));
  const composed = composeDisplayWindows(verified);
  const gaps = missingCoverCells(
    cover,
    verified.map((item) => ({
      key: item.key,
      pixelWindow: item.pixelWindow,
      actualBounds: item.actualBounds,
      width: item.width,
      height: item.height,
      receiptVerified: true,
    })),
    missingReason,
  );
  return { overlapErrors: composed.overlapErrors, gaps, seamless: composed.seamless };
}

/** 커버 집합을 스케줄러 요청으로 바꾼다 — requestedBounds는 창의 정확한 네이티브 사각형 그대로다. */
export function mosaicIssueTargets(
  cover: readonly DisplayWindowPlan[],
  assetRef: string,
  observedCrsDigest: string,
  purpose: DisplayPreparePurpose,
): ScheduledDisplayWindow[] {
  return cover.map((plan) => {
    const [c0, c1, r0, r1] = plan.pixelWindow;
    const pixelWindow: [number, number, number, number] = [c0, c1, r0, r1];
    return {
      key: stablePrepareKey(assetRef, pixelWindow, purpose),
      assetRef,
      pixelWindow,
      requestedBounds: [...plan.actualBounds] as [number, number, number, number],
      observedCrsDigest,
      purpose,
    };
  });
}

/** 그린 창의 진행 문구 — 끝난 창부터 차례로 그렸음을 밝힌다. */
export function mosaicProgressCopy(painted: number, total: number): string {
  return `그린 창 ${painted} / 전체 ${total} · 끝난 창부터 차례로 그립니다`;
}

export { saturatedLaneCopy };

/** 세션 보관 거부의 종류 — 실패하면 보관분을 지우고 내놓지 않는다. */
export type MosaicServeRefusal = "RECEIPT_CHANGED" | "RIGHTS_UNAVAILABLE" | "FOREIGN_PRINCIPAL";

export interface MosaicPaintSlot {
  key: string;
  outputSha256: string;
  outputSizeBytes: number;
  width: number;
  height: number;
  pixels: Uint8ClampedArray<ArrayBuffer>;
}

export type MosaicServeResult =
  | { ok: true; slot: MosaicPaintSlot }
  | { ok: false; reason: MosaicServeRefusal };

export const MOSAIC_CACHE_REFUSAL_COPY: Record<MosaicServeRefusal, string> = {
  RECEIPT_CHANGED: "받은 바이트가 Core 준비 기록과 달라 화면에 표시하지 않습니다.",
  RIGHTS_UNAVAILABLE:
    "요청을 찾을 수 없거나 현재 조회할 수 없습니다. 다른 계정이 준비한 창은 이 화면에서 열 수 없습니다.",
  FOREIGN_PRINCIPAL:
    "요청을 찾을 수 없거나 현재 조회할 수 없습니다. 다른 계정이 준비한 창은 이 화면에서 열 수 없습니다.",
};

/**
 * 같은 세션 안의 그린 창 보관 — pan-back을 새 PREPARE 없이 돌려준다.
 *
 * - 같은 탭·같은 세션의 주인 표식(ownerToken)이 맞아야 내놓는다.
 *   다른 주인의 표식으로는 존재를 드러내지 않는 같은 문구로 닫는다.
 * - 내놓을 때마다 지금 볼 수 있는 영수증 사실(sha/size)과 대조한다.
 *   어긋나면 보관분을 지우고 내놓지 않는다.
 * - 이 보관은 어떤 독립 권한도 만들지 않는다. 읽을 수 있는 창 목록과
 *   Core의 세션 검사(BFF→Core 매 호출 재확인)가 권리를 그대로 소유한다.
 */
export class MosaicPaintCache {
  private readonly ownerToken: string;
  private readonly slots = new Map<string, MosaicPaintSlot>();

  constructor(ownerToken: string) {
    this.ownerToken = ownerToken;
  }

  store(slot: MosaicPaintSlot, ownerToken: string): boolean {
    if (ownerToken !== this.ownerToken) return false;
    this.slots.set(slot.key, slot);
    return true;
  }

  serve(
    key: string,
    current: { outputSha256: string; outputSizeBytes: number } | null,
    ownerToken: string,
  ): MosaicServeResult {
    if (ownerToken !== this.ownerToken) {
      this.slots.delete(key);
      return { ok: false, reason: "FOREIGN_PRINCIPAL" };
    }
    if (current === null) {
      this.slots.delete(key);
      return { ok: false, reason: "RIGHTS_UNAVAILABLE" };
    }
    const stored = this.slots.get(key);
    if (!stored) return { ok: false, reason: "RECEIPT_CHANGED" };
    if (
      stored.outputSha256 !== current.outputSha256 ||
      stored.outputSizeBytes !== current.outputSizeBytes
    ) {
      this.slots.delete(key);
      return { ok: false, reason: "RECEIPT_CHANGED" };
    }
    return { ok: true, slot: stored };
  }

  evict(key: string): void {
    this.slots.delete(key);
  }

  clear(): void {
    this.slots.clear();
  }

  get size(): number {
    return this.slots.size;
  }
}

/** 뷰포트→창 집합 해석의 얇은 겉 — 해석 규칙은 소스 원점 기준 그대로다. */
export function resolveMosaicCover(
  grid: DisplaySourceGrid | null,
  viewport: DisplayViewportBounds,
): ReturnType<typeof resolveViewportWindows> {
  return resolveViewportWindows(grid, viewport);
}
