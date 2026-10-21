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
  // 바이트 GET·해독 중은 '준비 중'이 아니라 '자료 읽는 중'이다 — 새 연산이 아니다.
  // 서버 대기열(QUEUED/RUNNING)은 '준비 중' 그대로 둔다.
  return kind === "fetching"
    ? `자료 읽는 중 · ${area} 창의 바이트를 받고 있습니다. 가짜 내용을 채우지 않습니다.`
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
  // 준비된 출력이 아직 없는 창 — '자료 없음'이 아니라 '표시 준비 필요'다.
  // 진입·이동·확대만으로는 새 준비를 만들지 않는다(명시적 채우기에서만).
  return {
    key,
    plan,
    phase: "gap",
    detail: "표시 준비 필요 · 아직 준비된 출력이 없어 비워 둡니다. 빈칸을 메우거나 늘이지 않습니다.",
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

/**
 * S1 — 부분 커버의 정직한 라벨. 부분은 항상 부분으로 말한다(전체·완료
 * 표현 금지). 전체가 다 그려졌을 때만 진행 문구 그대로 둔다. 첫지불
 * 설계 §3.1의 진행-copy 규칙을 기존 문구로 합성한 것이며, 새로운 상태
 * 어휘를 만들지 않는다.
 */
export const MOSAIC_PARTIAL_COVER_LABEL = "부분 보기";

export function mosaicPartialCoverCopy(painted: number, total: number): string {
  return `${MOSAIC_PARTIAL_COVER_LABEL} · ${mosaicProgressCopy(painted, total)} · 나머지는 아직 표시하지 않습니다 (빈칸을 메우거나 늘이지 않음)`;
}

export function mosaicCoverStatusCopy(painted: number, total: number): string {
  if (painted >= total) return mosaicProgressCopy(painted, total);
  return mosaicPartialCoverCopy(painted, total);
}

/**
 * S1 — 가시성-중심성 순서(visibility-centrality). 뷰포트 중심에 가까운
 * 창부터 발행·수집한다. 서버 FIFO가 없으므로(GAP-06) 순서는 클라이언트가
 * 만든다. 거리 동률은 안정 정렬로 커버 순서를 유지한다. 실제 픽셀
 * 중심(actualBounds 중심)으로 재며, 정수 픽셀 창 자체는 바꾸지 않는다.
 */
export function orderCoverByVisibilityCentrality(
  cover: readonly DisplayWindowPlan[],
  viewport: DisplayViewportBounds,
): DisplayWindowPlan[] {
  const cx = (viewport[0] + viewport[2]) / 2;
  const cy = (viewport[1] + viewport[3]) / 2;
  const distanceSquared = (plan: DisplayWindowPlan): number => {
    const [minx, miny, maxx, maxy] = plan.actualBounds;
    const px = (minx + maxx) / 2 - cx;
    const py = (miny + maxy) / 2 - cy;
    return px * px + py * py;
  };
  return [...cover].sort((a, b) => distanceSquared(a) - distanceSquared(b));
}

/**
 * S1 — 대기열 핀 고정 히스테리시스(PINNED HYSTERESIS). 1픽셀 팬 같은
 * 미세 이동이 진행 중인 대기열을 버리고 다시 발행하게 두지 않는다.
 * 다음 커버의 어떤 창과도 경계 간격이 hysteresisPx보다 멀리 떨어진
 * 대기열만 버린다. 8px은 셀 경계 바로 밖의 경미한 이동까지 유지하고,
 * 실제 범위 이동은 버리게 하는 고정값이다(LOD 제안의 0.5 뷰포트와 달리
 * 작게 고정 — 1픽셀 팬은 커버 자체가 바뀌지 않아 버려지지 않는다).
 */
export const PINNED_QUEUE_HYSTERESIS_PIXELS = 8;

function rangesGap(a0: number, a1: number, b0: number, b1: number): number {
  if (a0 < b1 && b0 < a1) return 0;
  if (a1 <= b0) return b0 - a1;
  return a0 - b1;
}

/** 두 픽셀 창의 경계 간격 — 겹치거나 맞닿으면 0이다. */
export function pixelWindowEdgeGap(
  a: readonly [number, number, number, number],
  b: readonly [number, number, number, number],
): number {
  const columnGap = rangesGap(a[0], a[1], b[0], b[1]);
  const rowGap = rangesGap(a[2], a[3], b[2], b[3]);
  if (columnGap === 0 || rowGap === 0) return Math.max(columnGap, rowGap);
  return Math.hypot(columnGap, rowGap);
}

/**
 * 다음 커버 근처에 머무는 대기열 키만 유지한다. 구조를 모르는 키(과거
 * 형식 등)는 근접을 증명할 수 없어 유지하지 않는다 — 기존 버리기 동작과
 * 같다.
 */
export function selectHysteresisRetainedKeys(
  queued: readonly {
    key: string;
    pixelWindow: readonly [number, number, number, number];
  }[],
  nextCover: readonly DisplayWindowPlan[],
  hysteresisPx: number = PINNED_QUEUE_HYSTERESIS_PIXELS,
): string[] {
  return queued
    .filter((item) =>
      nextCover.some(
        (plan) =>
          pixelWindowEdgeGap(item.pixelWindow, plan.pixelWindow) <= hysteresisPx,
      ),
    )
    .map((item) => item.key);
}

export { saturatedLaneCopy };

/** 세션 보관 거부의 종류 — 실패하면 보관분을 지우고 내놓지 않는다. */
export type MosaicServeRefusal =
  | "GRANT_EXPIRED"
  | "REVOKED"
  | "PURPOSE_MISMATCH"
  | "RECEIPT_CHANGED"
  | "RIGHTS_UNAVAILABLE"
  | "FOREIGN_PRINCIPAL";

export interface MosaicPaintSlot {
  /** 슬롯 주소 — 같은 세션 주인의 같은 픽셀 창. 권리 경계는 아래 핀 동등성으로 닫는다. */
  key: string;
  outputSha256: string;
  outputSizeBytes: number;
  width: number;
  height: number;
  pixels: Uint8ClampedArray<ArrayBuffer>;
  /**
   * S2 — Console이 합법적으로 쥔 권리 핀(설계 §1.3 중 세션 보유분).
   * assetRef·purpose·observedCrsDigest는 발행·영수증에서 직접 오며,
   * 같은 픽셀 창이라도 시점·용도·위치기준이 다르면 다른 슬롯이다.
   * grant/policy 다이제스트·수혜자·회전 핀은 Core가 소유하므로
   * Console이 지어내지 않는다 — 그 검사는 Core 목록 응답의 읽기 가능
   * 존재(readable 존재 = Core의 현행 grant·회수·용도·소유 판정)와
   * ownerToken 동등성으로 닫고, 전체 DisplayCacheKeyV1은 T2(S3·별도
   * 승인)에서 바인딩한다. LOD 핀은 S5(GAP-03) 전까지 NONE이다.
   */
  assetRef: string;
  purpose: DisplayPreparePurpose;
  observedCrsDigest: string | null;
}

export interface MosaicPaintRights {
  /** Core 목록 응답에서 유도한 세션 보유 사실 — Core 현행 상태가 주인이다. */
  grantLive: boolean;
  notRevoked: boolean;
  purposeAllowed: boolean;
}

export interface MosaicPaintCurrent {
  outputSha256: string;
  outputSizeBytes: number;
  assetRef: string;
  purpose: DisplayPreparePurpose;
  observedCrsDigest: string | null;
  rights: MosaicPaintRights;
}

export type MosaicServeResult =
  | { ok: true; slot: MosaicPaintSlot }
  | { ok: false; reason: MosaicServeRefusal };

export const MOSAIC_CACHE_REFUSAL_COPY: Record<MosaicServeRefusal, string> = {
  GRANT_EXPIRED:
    "창을 볼 권한의 유효 기간이 지나 이 창을 더는 표시하지 않습니다. 담당자에게 권한 확인을 요청하세요.",
  REVOKED:
    "창을 볼 권한이 회수되어 이 창을 더는 표시하지 않습니다. 담당자에게 권한 확인을 요청하세요.",
  PURPOSE_MISMATCH:
    "이 창의 사용 용도가 달라 표시하지 않습니다. 용도에 맞는 창을 새로 요청하세요.",
  RECEIPT_CHANGED: "받은 바이트가 Core 준비 기록과 달라 화면에 표시하지 않습니다.",
  RIGHTS_UNAVAILABLE:
    "요청을 찾을 수 없거나 현재 조회할 수 없습니다. 다른 계정이 준비한 창은 이 화면에서 열 수 없습니다.",
  FOREIGN_PRINCIPAL:
    "요청을 찾을 수 없거나 현재 조회할 수 없습니다. 다른 계정이 준비한 창은 이 화면에서 열 수 없습니다.",
};

/**
 * S2 — T1 세션-tier 상한(고정, 측정 유도 — 임의 상수가 아님).
 *
 * 측정 근거(`docs/audit/SPATIAL_DISPLAY_CACHE_MEASUREMENT_EVIDENCE_2026-10-21.md` §5):
 * - 디코드 슬롯당 512×512×4 = 1,048,576 B (≈1 MiB, MEASURED).
 * - 전체 1022×915 커버 세션 상주 7,934,824 B ≈ 7.57 MiB (슬롯 4개 + 캔버스, MEASURED).
 * 작업집합 근거(R1–R5 기준 탐색): R1 전체 커버 4슬롯 + R3 팬워크 프린지
 * ~8슬롯 = 12슬롯이면 R1으로의 복귀가 적중한다. 12 × ≈1 MiB ≈ 12 MiB
 * 디코드 + 캔버스 ≈ 3.6 MiB → 최악 ≈ 15.6 MiB로, 증거 §7의 상한(≤16슬롯)
 * 안에 든다. 초과분은 충돌이 아니라 LRU 방출이다. 숫자 변경은 벤치마크
 * 소유이며, 이 문서가 근거가 아니다.
 */
export const MOSAIC_T1_MAX_SLOTS = 12;

/**
 * 같은 세션 안의 그린 창 보관 — pan-back을 새 PREPARE 없이 돌려준다.
 *
 * - 같은 탭·같은 세션의 주인 표식(ownerToken)이 맞아야 내놓는다.
 *   다른 주인의 표식으로는 존재를 드러내지 않는 같은 문구로 닫는다.
 * - 내놓을 때마다(매 paint 전) 권리 핀(assetRef·purpose·observedCrsDigest
 *   동등성 + 세션 보유 grant·회수·용도 사실)과 영수증 사실(sha/size)을
 *   다시 대조한다. 어긋나면 보관분을 지우고 내놓지 않는다 — 재검증
 *   불가 적중은 MISS이며, 조용 적중은 없다.
 * - 이 보관은 어떤 독립 권한도 만들지 않는다. 읽을 수 있는 창 목록과
 *   Core의 세션 검사(BFF→Core 매 호출 재확인)가 권리를 그대로 소유한다.
 * - 상한 초과 시 가장 오래된 슬롯부터 방출한다(LRU, 충돌 아님).
 */
export class MosaicPaintCache {
  private readonly ownerToken: string;
  private readonly maxSlots: number;
  private readonly slots = new Map<string, MosaicPaintSlot>();

  constructor(ownerToken: string, maxSlots: number = MOSAIC_T1_MAX_SLOTS) {
    this.ownerToken = ownerToken;
    this.maxSlots = maxSlots;
  }

  store(slot: MosaicPaintSlot, ownerToken: string): boolean {
    if (ownerToken !== this.ownerToken) return false;
    // LRU: 같은 키는 최신으로, 상한 초과분은 가장 오래된 것부터 방출한다.
    this.slots.delete(slot.key);
    while (this.slots.size >= this.maxSlots && this.maxSlots > 0) {
      const oldest = this.slots.keys().next();
      if (oldest.done) break;
      this.slots.delete(oldest.value);
    }
    if (this.maxSlots <= 0) return false;
    this.slots.set(slot.key, slot);
    return true;
  }

  serve(
    key: string,
    current: MosaicPaintCurrent | null,
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
    // 범위 핀 동등성(설계 §3-1): 다른 시점·용도·위치기준의 조회는
    // 존재를 드러내지 않고 닫는다.
    if (
      stored.assetRef !== current.assetRef ||
      stored.purpose !== current.purpose ||
      stored.observedCrsDigest !== current.observedCrsDigest
    ) {
      this.slots.delete(key);
      return { ok: false, reason: "FOREIGN_PRINCIPAL" };
    }
    if (!current.rights.grantLive) {
      this.slots.delete(key);
      return { ok: false, reason: "GRANT_EXPIRED" };
    }
    if (!current.rights.notRevoked) {
      this.slots.delete(key);
      return { ok: false, reason: "REVOKED" };
    }
    if (!current.rights.purposeAllowed) {
      this.slots.delete(key);
      return { ok: false, reason: "PURPOSE_MISMATCH" };
    }
    if (
      stored.outputSha256 !== current.outputSha256 ||
      stored.outputSizeBytes !== current.outputSizeBytes
    ) {
      this.slots.delete(key);
      return { ok: false, reason: "RECEIPT_CHANGED" };
    }
    // 적중도 최근 사용으로 갱신한다(LRU).
    this.slots.delete(key);
    this.slots.set(key, stored);
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

  /** M5 게이지 — 디코드 상주 바이트 합(슬롯 × 너비×높이×4). */
  get residencyBytes(): number {
    let total = 0;
    for (const slot of this.slots.values()) {
      total += slot.width * slot.height * 4;
    }
    return total;
  }
}

/** 뷰포트→창 집합 해석의 얇은 겉 — 해석 규칙은 소스 원점 기준 그대로다. */
export function resolveMosaicCover(
  grid: DisplaySourceGrid | null,
  viewport: DisplayViewportBounds,
): ReturnType<typeof resolveViewportWindows> {
  return resolveViewportWindows(grid, viewport);
}
