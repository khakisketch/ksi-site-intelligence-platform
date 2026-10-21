import { describe, expect, it } from "vitest";

import {
  MOSAIC_PARTIAL_COVER_LABEL,
  MOSAIC_T1_MAX_SLOTS,
  MosaicPaintCache,
  mosaicCellView,
  mosaicCoverStatusCopy,
  mosaicProgressCopy,
  orderCoverByVisibilityCentrality,
  pixelWindowEdgeGap,
  selectHysteresisRetainedKeys,
  PINNED_QUEUE_HYSTERESIS_PIXELS,
  type MosaicPaintCurrent,
} from "@/lib/spatial-display-mosaic";
import {
  DisplayPrepareScheduler,
  type DisplayIssueFn,
} from "@/lib/spatial-display-scheduler";
import { resolveFullCoverWindows, type DisplaySourceGrid } from "@/lib/spatial-display-viewport";
import {
  DisplayReferenceGauges,
  MEASURED_BASIS,
  REFERENCE_PASS_THRESHOLDS,
  REFERENCE_RUN_SEQUENCE_VERSION,
  deriveM1M5,
  honestColdWarmCopy,
  type ReferencePhaseSummary,
} from "@/lib/spatial-display-reference-run";

/**
 * STAGE-1 패키지(S1/S2/S4) 집중 검사.
 *
 * 아래 합성 타임라인·픽셀값은 TEST FIXTURE이며 제품 자료·관측값이 아니다.
 * M1–M5 유도는 합성 고정값에서 계산한 예시이며 통과 기준이 아니다 —
 * 수치 기준은 벤치마크 목표(TBD)로 열려 있다.
 */
const FLOREAT_GRID: DisplaySourceGrid = {
  transform: [0.25, 0, 382261.7296, 0, -0.25, 6467541.575],
  width: 1022,
  height: 915,
};

const ASSET = `ksa-v1-${"b".repeat(64)}`;
const CRS = `sha256:${"c".repeat(64)}`;

function coverPlans() {
  const result = resolveFullCoverWindows(FLOREAT_GRID);
  expect(result.ok).toBe(true);
  if (!result.ok) throw new Error("측정 격자의 전체 커버를 해석하지 못했습니다.");
  return result.windows;
}

function fullViewport(): [number, number, number, number] {
  const [a, , c, , e, f] = FLOREAT_GRID.transform;
  return [c, f + e * FLOREAT_GRID.height, c + a * FLOREAT_GRID.width, f];
}

function syntheticTile(width: number, height: number): Uint8ClampedArray<ArrayBuffer> {
  return new Uint8ClampedArray(width * height * 4);
}

function current(): MosaicPaintCurrent {
  return {
    outputSha256: `sha256:${"f".repeat(64)}`,
    outputSizeBytes: 474427,
    assetRef: ASSET,
    purpose: "GENERAL_DATA_USE",
    observedCrsDigest: CRS,
    rights: { grantLive: true, notRevoked: true, purposeAllowed: true },
  };
}

describe("S1 — visibility-centrality issue order", () => {
  it("issues the window covering the viewport centre first", () => {
    const cover = coverPlans();
    // 전체 보기의 중심은 네 창의 모서리에 닿는다 — 오른쪽 위를 보는 뷰포트로
    // TR 창이 먼저 오게 한다.
    const [a, , c, , e, f] = FLOREAT_GRID.transform;
    const right = c + a * FLOREAT_GRID.width;
    const top = f;
    const viewport: [number, number, number, number] = [
      c + a * 600,
      top + e * 300,
      right,
      top + e * 10,
    ];
    const ordered = orderCoverByVisibilityCentrality(cover, viewport);
    expect(ordered).toHaveLength(4);
    expect(ordered[0]!.pixelWindow).toEqual([512, 1022, 0, 512]);
    // 같은 창 집합이다 — 순서만 다르다.
    expect(new Set(ordered.map((plan) => plan.pixelWindow.join(",")))).toEqual(
      new Set(cover.map((plan) => plan.pixelWindow.join(","))),
    );
    // 전체 보기에서는 중심이 네 창에 equidistant — 커버 순서를 유지한다(안정).
    const fullOrdered = orderCoverByVisibilityCentrality(cover, fullViewport());
    expect(fullOrdered.map((plan) => plan.pixelWindow)).toEqual(
      cover.map((plan) => plan.pixelWindow),
    );
  });
});

describe("S1 — pinned hysteresis for off-screen queue drop", () => {
  it("keeps an in-progress queued window across a 1-pixel pan", () => {
    const cover = coverPlans();
    const queued = cover.map((plan) => ({
      key: plan.pixelWindow.join(","),
      pixelWindow: plan.pixelWindow,
    }));
    // 1픽셀 이동한 커버 — 같은 셀 집합이므로 전원 유지된다.
    const retained = selectHysteresisRetainedKeys(queued, cover);
    expect(retained).toHaveLength(4);
    expect(PINNED_QUEUE_HYSTERESIS_PIXELS).toBeGreaterThan(1);
  });

  it("drops a queued window far outside the next cover", () => {
    const cover = coverPlans();
    // 격자 밖에 있는 창 — 다음 커버의 어떤 창과도 멀리 떨어져 있다.
    const far = {
      key: "far",
      pixelWindow: [2000, 2512, 2000, 2512] as readonly [number, number, number, number],
    };
    expect(
      cover.every(
        (plan) => pixelWindowEdgeGap(far.pixelWindow, plan.pixelWindow) > PINNED_QUEUE_HYSTERESIS_PIXELS,
      ),
    ).toBe(true);
    expect(selectHysteresisRetainedKeys([far], cover)).toEqual([]);
    // 맞닿은 이웃은 유지된다 — 바로 돌아오는 팬이 적중한다.
    const abutting = {
      key: "near",
      pixelWindow: [0, 512, 0, 512] as readonly [number, number, number, number],
    };
    expect(selectHysteresisRetainedKeys([abutting], cover)).toEqual(["near"]);
  });

  it("scheduler retains hysteresis keys and still drops the rest", async () => {
    const releases = new Map<string, () => void>();
    const issue: DisplayIssueFn = (window) =>
      new Promise((resolve) => {
        releases.set(window.key, () =>
          resolve({ jobId: `job-${window.key}`, executionState: "QUEUED" }),
        );
      });
    const scheduler = new DisplayPrepareScheduler(issue, { maxConcurrent: 1 });
    const keyOf = (window: readonly [number, number, number, number]): string =>
      `${ASSET}|${window.join(",")}|GENERAL_DATA_USE`;
    const near: [number, number, number, number] = [0, 512, 0, 512];
    const far: [number, number, number, number] = [0, 1, 0, 1];
    const mk = (window: [number, number, number, number]) => ({
      key: keyOf(window),
      assetRef: ASSET,
      pixelWindow: window,
      requestedBounds: [0, 0, 1, 1] as [number, number, number, number],
      observedCrsDigest: CRS,
      purpose: "GENERAL_DATA_USE" as const,
    });
    scheduler.ensure([mk(near), mk(far)]);
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
    // near 활성, far 대기.
    expect(scheduler.snapshot().active).toEqual([keyOf(near)]);
    // 다음 집합에 far가 없어도 히스테리시스로 유지한다.
    const other: [number, number, number, number] = [512, 1022, 0, 512];
    const retained = selectHysteresisRetainedKeys(
      [{ key: keyOf(far), pixelWindow: far }],
      [{ pixelWindow: other, actualBounds: [0, 0, 1, 1], width: 510, height: 512 }],
    );
    expect(retained).toEqual([]);
    scheduler.ensure([mk(other)], { retainKeys: [keyOf(far)] });
    expect(scheduler.snapshot().queued).toContain(keyOf(far));
    // 유지 지정이 없으면 버린다(기존 동작).
    scheduler.ensure([mk(other)]);
    expect(scheduler.snapshot().queued).not.toContain(keyOf(far));
    expect(scheduler.snapshot().cancelled).toContain(keyOf(far));
  });
});

describe("S1 — paint-on-verify and partial-cover labelling", () => {
  it("paints only a verified window and labels partial cover as partial", () => {
    const [plan] = coverPlans();
    const painted = mosaicCellView({
      key: "k",
      plan: plan!,
      painted: true,
      fetching: false,
      preparing: false,
      failure: null,
    });
    expect(painted.phase).toBe("painted");
    const waiting = mosaicCellView({
      key: "k",
      plan: plan!,
      painted: false,
      fetching: true,
      preparing: true,
      failure: null,
    });
    // 검증 전에는 그리지 않는다 — waiting은 빈칸이다. 바이트 수신은 '자료 읽는 중',
    // 서버 대기열은 '준비 중'이다.
    expect(waiting.phase).toBe("waiting");
    expect(waiting.detail).toMatch(/자료 읽는 중/);
    const queued = mosaicCellView({
      key: "k",
      plan: plan!,
      painted: false,
      fetching: false,
      preparing: true,
      failure: null,
    });
    expect(queued.phase).toBe("waiting");
    expect(queued.detail).toMatch(/준비 중/);
    // 부분 커버는 항상 부분으로 말한다.
    expect(mosaicCoverStatusCopy(1, 4)).toMatch(new RegExp(MOSAIC_PARTIAL_COVER_LABEL));
    expect(mosaicCoverStatusCopy(1, 4)).toMatch(/그린 창 1 \/ 전체 4/);
    expect(mosaicCoverStatusCopy(1, 4)).not.toMatch(/완료/);
    // 전체가 다 그려졌을 때만 진행 문구 그대로다.
    expect(mosaicCoverStatusCopy(4, 4)).toBe(mosaicProgressCopy(4, 4));
  });
});

describe("S2 — T1 cap, LRU eviction, and re-validate-before-paint", () => {
  it("derives the slot cap from the measured memory basis", () => {
    // 1,048,576 B/슬롯 MEASURED × 12슬롯 ≈ 12 MiB + 캔버스 ≈ 15.6 MiB.
    expect(MOSAIC_T1_MAX_SLOTS).toBe(12);
    expect(MOSAIC_T1_MAX_SLOTS * 1048576).toBeLessThanOrEqual(16 * 1048576);
  });

  it("evicts least-recently-used beyond the cap instead of crashing", () => {
    const cache = new MosaicPaintCache("owner", 3);
    for (let i = 0; i < 3; i += 1) {
      cache.store(
        {
          key: `k${i}`,
          outputSha256: `sha256:${"f".repeat(64)}`,
          outputSizeBytes: 474427,
          width: 2,
          height: 2,
          pixels: syntheticTile(2, 2),
          assetRef: ASSET,
          purpose: "GENERAL_DATA_USE",
          observedCrsDigest: CRS,
        },
        "owner",
      );
    }
    expect(cache.size).toBe(3);
    // k0을 적중시켜 최근 사용으로 만든다.
    expect(cache.serve("k0", current(), "owner").ok).toBe(true);
    cache.store(
      {
        key: "k3",
        outputSha256: `sha256:${"f".repeat(64)}`,
        outputSizeBytes: 474427,
        width: 2,
        height: 2,
        pixels: syntheticTile(2, 2),
        assetRef: ASSET,
        purpose: "GENERAL_DATA_USE",
        observedCrsDigest: CRS,
      },
      "owner",
    );
    expect(cache.size).toBe(3);
    // 가장 오래된 k1이 방출되고 k0은 산다.
    expect(cache.serve("k1", current(), "owner").ok).toBe(false);
    expect(cache.serve("k0", current(), "owner").ok).toBe(true);
    expect(cache.serve("k3", current(), "owner").ok).toBe(true);
  });

  it("reports residency bytes for the M5 gauge", () => {
    const cache = new MosaicPaintCache("owner");
    cache.store(
      {
        key: "k",
        outputSha256: `sha256:${"f".repeat(64)}`,
        outputSizeBytes: 100,
        width: 512,
        height: 512,
        pixels: syntheticTile(2, 2),
        assetRef: ASSET,
        purpose: "GENERAL_DATA_USE",
        observedCrsDigest: CRS,
      },
      "owner",
    );
    expect(cache.residencyBytes).toBe(512 * 512 * 4);
  });

  it("treats a stale or foreign receipt as a miss and evicts", () => {
    const cache = new MosaicPaintCache("owner");
    cache.store(
      {
        key: "k",
        outputSha256: `sha256:${"f".repeat(64)}`,
        outputSizeBytes: 100,
        width: 2,
        height: 2,
        pixels: syntheticTile(2, 2),
        assetRef: ASSET,
        purpose: "GENERAL_DATA_USE",
        observedCrsDigest: CRS,
      },
      "owner",
    );
    expect(
      cache.serve("k", { ...current(), outputSha256: `sha256:${"e".repeat(64)}` }, "owner"),
    ).toEqual({ ok: false, reason: "RECEIPT_CHANGED" });
    expect(cache.size).toBe(0);
  });
});

describe("S4 — reference-run gauges on a synthetic timeline fixture", () => {
  function fixtureSummaries(): ReferencePhaseSummary[] {
    // TEST FIXTURE — 합성 고정값이며 제품 측정값이 아니다.
    const gauges = new DisplayReferenceGauges();
    gauges.markViewportCommit("R1", 0);
    gauges.recordRequest("R1", 4);
    gauges.recordMiss("R1", 4);
    gauges.recordPrepare("R1", 4);
    gauges.markFirstPaintVerified("R1", 5800);
    gauges.markStabilised("R1", 23000);
    gauges.sampleResidency("R1", 7934824);
    gauges.markViewportCommit("R2", 30000);
    gauges.recordRequest("R2", 4);
    gauges.recordHit("R2", "T1", 4);
    gauges.markFirstPaintVerified("R2", 30700);
    gauges.markStabilised("R2", 30700);
    gauges.markViewportCommit("R3", 40000);
    gauges.recordRequest("R3", 6);
    gauges.recordHit("R3", "T1", 4);
    gauges.recordMiss("R3", 2);
    gauges.recordPrepare("R3", 2);
    gauges.markStabilised("R3", 52000);
    gauges.markViewportCommit("R5", 60000);
    gauges.recordRequest("R5", 4);
    gauges.recordMiss("R5", 4);
    return gauges.snapshot();
  }

  it("collects only counters/marks and derives M1–M5 from the fixture", () => {
    const derived = deriveM1M5(fixtureSummaries());
    // R1–R3: 요청 14 중 적중 8.
    expect(derived.m1.requested).toBe(14);
    expect(derived.m1.hits).toBe(8);
    expect(derived.m1.overall).toBeCloseTo(8 / 14);
    expect(derived.m1.t1).toBeCloseTo(8 / 14);
    expect(derived.m1.t2).toBe(0);
    expect(derived.m2.coldMs).toBe(5800);
    expect(derived.m2.warmMs).toBe(700);
    expect(derived.m3.coldMs).toBe(23000);
    // R5는 적중률에서 제외하고 불변식으로 센다.
    expect(derived.r5ServedFromTier).toBe(0);
    expect(derived.m4.failed429).toBe(0);
    expect(derived.m5.peakResidencyBytes).toBe(7934824);
  });

  it("keeps numeric pass thresholds open and reports honest cold/warm copy", () => {
    expect(REFERENCE_RUN_SEQUENCE_VERSION).toBe("R1-R5-v1");
    expect(REFERENCE_PASS_THRESHOLDS.status).toBe("TBD_BY_BENCHMARK");
    expect(MEASURED_BASIS.coldFirstPixelMs).toBe(5800);
    expect(MEASURED_BASIS.coldStabiliseMs).toBe(23000);
    expect(MEASURED_BASIS.warmRevisitMs).toBe(700);
    const copy = honestColdWarmCopy();
    expect(copy).toMatch(/5\.8초/);
    expect(copy).toMatch(/0\.7초/);
    expect(copy).toMatch(/미확정/);
    expect(copy).toMatch(/표현 없음/);
    expect(copy).not.toMatch(/완료 보장/);
    expect(copy).not.toMatch(/100ms 달성/);
  });
});
