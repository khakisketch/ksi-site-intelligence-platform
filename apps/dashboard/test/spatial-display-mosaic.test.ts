import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { FOREIGN_WINDOW_COPY } from "@/lib/site-windowed-pixel-viewer";
import {
  DISPLAY_ASSEMBLY_LABEL,
  composeDisplayWindows,
  windowsAbut,
  windowsOverlap,
} from "@/lib/spatial-display-composition";
import {
  DisplayPrepareIssueError,
  DisplayPrepareScheduler,
  saturatedLaneCopy,
  stablePrepareKey,
  type DisplayIssueFn,
  type ScheduledDisplayWindow,
} from "@/lib/spatial-display-scheduler";
import { resolveFullCoverWindows, type DisplaySourceGrid } from "@/lib/spatial-display-viewport";
import {
  MOSAIC_ASSEMBLY_LABEL,
  MOSAIC_ASSEMBLY_NOTE,
  MOSAIC_CACHE_REFUSAL_COPY,
  MOSAIC_VIEWPORT_NOTE,
  MosaicPaintCache,
  checkMosaicSeamless,
  mosaicCanvasGeometry,
  mosaicCellView,
  mosaicIssueTargets,
  mosaicPlacements,
  mosaicProgressCopy,
  placeWindowPixels,
} from "@/lib/spatial-display-mosaic";

/**
 * 측정 발자국 — GAP-06 증거의 1022×915 EPSG:7850 격자 그대로다.
 * transform (0.25, 0, 382261.7296, 0, -0.25, 6467541.575).
 * 아래 픽셀 값은 이 테스트만을 위한 합성 고정값(TEST FIXTURE)이며,
 * 제품 자료·관측값이 아니다.
 */
const FLOREAT_GRID: DisplaySourceGrid = {
  transform: [0.25, 0, 382261.7296, 0, -0.25, 6467541.575],
  width: 1022,
  height: 915,
};

const DIGEST = `sha256:${"c".repeat(64)}`;
const ASSET_REF = `ksa-v1-${"b".repeat(64)}`;

function coverPlans() {
  const result = resolveFullCoverWindows(FLOREAT_GRID);
  expect(result.ok).toBe(true);
  if (!result.ok) throw new Error("측정 격자의 전체 커버를 해석하지 못했습니다.");
  return result.windows;
}

async function flush(times = 20): Promise<void> {
  for (let i = 0; i < times; i += 1) {
    await Promise.resolve();
    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  }
}

/** 합성 타일 — 각 창을 구분되는 단일 값으로 채운 테스트 고정값이다. 제품 자료가 아니다. */
function syntheticTile(width: number, height: number, gray: number): Uint8ClampedArray<ArrayBuffer> {
  const pixels = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i += 1) {
    pixels[i * 4] = gray;
    pixels[i * 4 + 1] = gray;
    pixels[i * 4 + 2] = gray;
    pixels[i * 4 + 3] = 255;
  }
  return pixels;
}

describe("mosaic placement on the measured 4-window cover", () => {
  it("tiles 1022x915 edge-to-edge with no gap or overlap", () => {
    const cover = coverPlans();
    expect(cover.map((item) => item.pixelWindow)).toEqual([
      [0, 512, 0, 512],
      [512, 1022, 0, 512],
      [0, 512, 512, 915],
      [512, 1022, 512, 915],
    ]);
    const geometry = mosaicCanvasGeometry(cover);
    expect(geometry).toEqual({ width: 1022, height: 915, originC0: 0, originR0: 0 });
    const placements = mosaicPlacements(cover, geometry!);
    expect(placements.map((item) => [item.dx, item.dy])).toEqual([
      [0, 0],
      [512, 0],
      [0, 512],
      [512, 512],
    ]);
    // 합집합 면적은 격자 전체와 같다.
    const area = placements.reduce((sum, item) => sum + item.plan.width * item.plan.height, 0);
    expect(area).toBe(1022 * 915);
    // 어느 두 창도 겹치지 않는다.
    for (let i = 0; i < cover.length; i += 1) {
      for (let j = i + 1; j < cover.length; j += 1) {
        expect(windowsOverlap(cover[i]!.pixelWindow, cover[j]!.pixelWindow)).toBe(false);
      }
    }
    // 이웃은 정수 경계를 정확히 공유한다.
    expect(cover[0]!.pixelWindow[1]).toBe(cover[1]!.pixelWindow[0]);
    expect(cover[2]!.pixelWindow[1]).toBe(cover[3]!.pixelWindow[0]);
    expect(cover[0]!.pixelWindow[3]).toBe(cover[2]!.pixelWindow[2]);
    expect(cover[1]!.pixelWindow[3]).toBe(cover[3]!.pixelWindow[2]);
    expect(windowsAbut(cover[0]!.pixelWindow, cover[1]!.pixelWindow)).toBe(true);
    expect(windowsAbut(cover[0]!.pixelWindow, cover[2]!.pixelWindow)).toBe(true);
  });

  it("reports a seamless composition with no overlap errors", () => {
    const cover = coverPlans();
    const checked = checkMosaicSeamless(
      cover,
      cover.map((item) => item.pixelWindow),
      "NOT_REQUESTED",
    );
    expect(checked.seamless).toBe(true);
    expect(checked.overlapErrors).toEqual([]);
    expect(checked.gaps).toEqual([]);
  });

  it("leaves a missing window as an explicit gap, never filled", () => {
    const cover = coverPlans();
    const painted = [cover[0]!, cover[1]!, cover[2]!];
    const checked = checkMosaicSeamless(
      painted,
      cover.map((item) => item.pixelWindow),
      "PREPARE_FAILED",
    );
    expect(checked.seamless).toBe(true);
    expect(checked.gaps).toHaveLength(1);
    expect(checked.gaps[0]!.pixelWindow).toEqual([512, 1022, 512, 915]);
    expect(checked.gaps[0]!.reason).toBe("PREPARE_FAILED");
    // 겹침 오류 없이 세 창만 둔다.
    const composed = composeDisplayWindows(
      painted.map((plan) => ({
        key: plan.pixelWindow.join(","),
        pixelWindow: plan.pixelWindow,
        actualBounds: plan.actualBounds as readonly [number, number, number, number],
        width: plan.width,
        height: plan.height,
        receiptVerified: true,
      })),
    );
    expect(composed.placed).toHaveLength(3);
  });
});

describe("placeWindowPixels", () => {
  it("assembles synthetic tiles with exact seams and no blending", () => {
    const cover = coverPlans();
    const geometry = mosaicCanvasGeometry(cover)!;
    const dest = new Uint8ClampedArray(geometry.width * geometry.height * 4);
    const grays = [10, 60, 120, 200];
    const placements = mosaicPlacements(cover, geometry);
    placements.forEach((placement, index) => {
      placeWindowPixels(
        dest,
        geometry.width,
        geometry.height,
        syntheticTile(placement.plan.width, placement.plan.height, grays[index]!),
        placement.plan.width,
        placement.plan.height,
        placement.dx,
        placement.dy,
      );
    });
    const at = (x: number, y: number): number => dest[(y * geometry.width + x) * 4]!;
    // 세로 이음새: 왼쪽 창의 마지막 열과 오른쪽 창의 첫 열이 각자의 값 그대로다.
    expect(at(511, 100)).toBe(10);
    expect(at(512, 100)).toBe(60);
    expect(at(511, 800)).toBe(120);
    expect(at(512, 800)).toBe(200);
    // 가로 이음새: 위쪽 창의 마지막 행과 아래쪽 창의 첫 행이 각자의 값 그대로다.
    expect(at(100, 511)).toBe(10);
    expect(at(100, 512)).toBe(120);
    expect(at(900, 511)).toBe(60);
    expect(at(900, 512)).toBe(200);
  });

  it("refuses to draw outside the mosaic buffer or with mismatched bytes", () => {
    const dest = new Uint8ClampedArray(1022 * 915 * 4);
    const tile = syntheticTile(512, 512, 10);
    expect(() => placeWindowPixels(dest, 1022, 915, tile, 512, 512, 600, 500)).toThrow();
    expect(() => placeWindowPixels(dest, 1022, 915, tile.subarray(0, 100), 512, 512, 0, 0)).toThrow();
  });
});

describe("mosaic cell states", () => {
  it("shows every uncovered window as a named waiting placeholder", () => {
    const cover = coverPlans();
    for (const plan of cover) {
      const cell = mosaicCellView({
        key: plan.pixelWindow.join(","),
        plan,
        painted: false,
        fetching: true,
        preparing: true,
        failure: null,
      });
      expect(cell.phase).toBe("waiting");
      expect(cell.detail).toMatch(/준비 중/);
      expect(cell.detail).toContain(`[${plan.pixelWindow.join(", ")}]`);
    }
  });

  it("shows an unrequested window as an explicit NOT_REQUESTED gap", () => {
    const [plan] = coverPlans();
    const cell = mosaicCellView({
      key: plan!.pixelWindow.join(","),
      plan: plan!,
      painted: false,
      fetching: false,
      preparing: false,
      failure: null,
    });
    expect(cell.phase).toBe("gap");
    expect(cell.gapReason).toBe("NOT_REQUESTED");
  });

  it("shows a failed or unavailable window as a gap with its reason", () => {
    const [plan] = coverPlans();
    const failed = mosaicCellView({
      key: plan!.pixelWindow.join(","),
      plan: plan!,
      painted: false,
      fetching: false,
      preparing: false,
      failure: { reason: "PREPARE_FAILED", message: "창 준비가 끝나지 않아 비워 둡니다." },
    });
    expect(failed.phase).toBe("gap");
    expect(failed.gapReason).toBe("PREPARE_FAILED");
    const blocked = mosaicCellView({
      key: plan!.pixelWindow.join(","),
      plan: plan!,
      painted: false,
      fetching: false,
      preparing: false,
      failure: { reason: "RIGHTS_UNAVAILABLE", message: MOSAIC_CACHE_REFUSAL_COPY.RIGHTS_UNAVAILABLE },
    });
    expect(blocked.gapReason).toBe("RIGHTS_UNAVAILABLE");
  });

  it("reports progressive arrival without waiting for all four", () => {
    expect(mosaicProgressCopy(1, 4)).toMatch(/그린 창 1 \/ 전체 4/);
    expect(mosaicProgressCopy(4, 4)).toMatch(/그린 창 4 \/ 전체 4/);
  });
});

describe("mosaic issue targets", () => {
  it("keys stably by (assetRef, pixelWindow, purpose) with exact bounds", () => {
    const cover = coverPlans();
    const targets = mosaicIssueTargets(cover, ASSET_REF, DIGEST, "GENERAL_DATA_USE");
    expect(targets).toHaveLength(4);
    for (const [index, target] of targets.entries()) {
      const plan = cover[index]!;
      expect(target.key).toBe(
        stablePrepareKey(ASSET_REF, [plan.pixelWindow[0], plan.pixelWindow[1], plan.pixelWindow[2], plan.pixelWindow[3]], "GENERAL_DATA_USE"),
      );
      // requestedBounds는 창의 정확한 네이티브 사각형 그대로 — 다시 반올림하지 않는다.
      expect(target.requestedBounds).toEqual(plan.actualBounds);
    }
  });
});

describe("mosaic scheduler behaviour under the measured budget", () => {
  function targets(): ScheduledDisplayWindow[] {
    return mosaicIssueTargets(coverPlans(), ASSET_REF, DIGEST, "GENERAL_DATA_USE");
  }

  it("issues at most 2 concurrent PREPAREs with a named saturated lane", async () => {
    let inFlight = 0;
    let peak = 0;
    const releases = new Map<string, () => void>();
    const issue: DisplayIssueFn = (window) =>
      new Promise((resolve) => {
        inFlight += 1;
        peak = Math.max(peak, inFlight);
        releases.set(window.key, () => {
          inFlight -= 1;
          resolve({ jobId: `job-${window.key}`, executionState: "QUEUED" });
        });
      });
    const scheduler = new DisplayPrepareScheduler(issue);
    const snapshot = scheduler.ensure(targets());
    await flush();
    expect(peak).toBeLessThanOrEqual(2);
    expect(snapshot.activeCount).toBe(2);
    expect(snapshot.queuedCount).toBe(2);
    expect(snapshot.laneCopy).toBe(saturatedLaneCopy(2, 2));
  });

  it("retries a retryable 429 with bounded back-off and names the state", async () => {
    let calls = 0;
    const issue: DisplayIssueFn = async () => {
      calls += 1;
      if (calls === 1) {
        throw new DisplayPrepareIssueError("동시 요청이 많아 순차 처리 중입니다.", {
          status: 429,
          code: "CONCURRENCY_LIMIT_EXCEEDED",
          retryable: true,
        });
      }
      return { jobId: "job-a", executionState: "QUEUED" };
    };
    let last: ReturnType<DisplayPrepareScheduler["snapshot"]> | null = null;
    const scheduler = new DisplayPrepareScheduler(issue, {
      maxRetries: 3,
      backoffMs: () => 0,
      sleep: async () => undefined,
      listener: (snapshot) => {
        last = snapshot;
      },
    });
    scheduler.ensure(targets().slice(0, 1));
    await flush(40);
    expect(calls).toBe(2);
    expect(scheduler.snapshot().done).toHaveLength(1);
    expect(last).not.toBeNull();
  });

  it("abandons queued windows outside the new viewport (cancel-on-supersede)", async () => {
    const issued: string[] = [];
    const releases = new Map<string, () => void>();
    const issue: DisplayIssueFn = (window) =>
      new Promise((resolve) => {
        issued.push(window.key);
        releases.set(window.key, () => resolve({ jobId: `job-${window.key}`, executionState: "QUEUED" }));
      });
    const scheduler = new DisplayPrepareScheduler(issue, { maxConcurrent: 1 });
    const full = targets();
    scheduler.ensure(full);
    await flush();
    expect(scheduler.snapshot().active).toHaveLength(1);
    // 뷰포트가 한 창으로 좁아졌다 — 대기열은 버린다.
    scheduler.ensure(full.slice(0, 1));
    expect(scheduler.snapshot().cancelled.length).toBeGreaterThan(0);
    releases.get(full[0]!.key)!();
    await flush();
    expect(issued).not.toContain(full[1]!.key);
    expect(issued).not.toContain(full[2]!.key);
  });

  it("treats pan-back as a cache hit with zero new PREPAREs", async () => {
    let calls = 0;
    const issue: DisplayIssueFn = async (window) => {
      calls += 1;
      return { jobId: `job-${window.key}`, executionState: "QUEUED" };
    };
    const scheduler = new DisplayPrepareScheduler(issue, { maxConcurrent: 4 });
    const full = targets();
    scheduler.ensure(full);
    await flush(40);
    expect(calls).toBe(4);
    // 같은 영역으로 돌아오면 끝난 기록이 그대로 있다 — 새 발행 없음.
    scheduler.ensure(full);
    await flush();
    expect(calls).toBe(4);
    for (const target of full) {
      expect(scheduler.completedResult(target.key)).not.toBeNull();
    }
  });
});

describe("MosaicPaintCache rights and receipt re-check", () => {
  const TOKEN_A = "session-owner-a";
  const TOKEN_B = "session-owner-b";
  const ASSET = `ksa-v1-${"b".repeat(64)}`;
  const OTHER_ASSET = `ksa-v1-${"d".repeat(64)}`;
  const CRS = `sha256:${"c".repeat(64)}`;

  function currentFor(
    sha = `sha256:${"f".repeat(64)}`,
    size = 474427,
    overrides: Partial<{
      assetRef: string;
      purpose: "GENERAL_DATA_USE" | "EXTERNAL_AI";
      observedCrsDigest: string | null;
      grantLive: boolean;
      notRevoked: boolean;
      purposeAllowed: boolean;
    }> = {},
  ) {
    return {
      outputSha256: sha,
      outputSizeBytes: size,
      assetRef: overrides.assetRef ?? ASSET,
      purpose: overrides.purpose ?? ("GENERAL_DATA_USE" as const),
      // null은 명시적 다른 값이다 — ??가 삼키지 않게 `in`으로 본다.
      observedCrsDigest:
        "observedCrsDigest" in overrides ? (overrides.observedCrsDigest as string | null) : CRS,
      rights: {
        grantLive: overrides.grantLive ?? true,
        notRevoked: overrides.notRevoked ?? true,
        purposeAllowed: overrides.purposeAllowed ?? true,
      },
    };
  }

  function slotFor(key: string, sha = `sha256:${"f".repeat(64)}`, size = 474427) {
    return {
      key,
      outputSha256: sha,
      outputSizeBytes: size,
      width: 512,
      height: 512,
      pixels: syntheticTile(2, 2, 10),
      assetRef: ASSET,
      purpose: "GENERAL_DATA_USE" as const,
      observedCrsDigest: CRS,
    };
  }

  it("serves a stored window only while receipt facts still match", () => {
    const cache = new MosaicPaintCache(TOKEN_A);
    const key = "0,512,0,512";
    expect(cache.store(slotFor(key), TOKEN_A)).toBe(true);
    expect(cache.serve(key, currentFor(), TOKEN_A).ok).toBe(true);
    // 영수증이 바뀌면 내놓지 않고 보관분을 지운다.
    const changed = cache.serve(
      key,
      currentFor(`sha256:${"e".repeat(64)}`),
      TOKEN_A,
    );
    expect(changed).toEqual({ ok: false, reason: "RECEIPT_CHANGED" });
    expect(cache.size).toBe(0);
  });

  it("stops serving a window the account can no longer read", () => {
    const cache = new MosaicPaintCache(TOKEN_A);
    const key = "0,512,0,512";
    cache.store(slotFor(key), TOKEN_A);
    expect(cache.serve(key, null, TOKEN_A)).toEqual({ ok: false, reason: "RIGHTS_UNAVAILABLE" });
    expect(cache.size).toBe(0);
    expect(MOSAIC_CACHE_REFUSAL_COPY.RIGHTS_UNAVAILABLE).toBe(FOREIGN_WINDOW_COPY);
  });

  it("never lets one principal read another principal's window", () => {
    const cache = new MosaicPaintCache(TOKEN_A);
    const key = "0,512,0,512";
    expect(cache.store(slotFor(key), TOKEN_B)).toBe(false);
    cache.store(slotFor(key), TOKEN_A);
    expect(cache.serve(key, currentFor(), TOKEN_B)).toEqual({ ok: false, reason: "FOREIGN_PRINCIPAL" });
    expect(cache.size).toBe(0);
  });

  it("treats another asset, purpose, or CRS on the same pixels as a miss", () => {
    const cache = new MosaicPaintCache(TOKEN_A);
    const key = "0,512,0,512";
    cache.store(slotFor(key), TOKEN_A);
    expect(
      cache.serve(key, currentFor(undefined, undefined, { assetRef: OTHER_ASSET }), TOKEN_A),
    ).toEqual({ ok: false, reason: "FOREIGN_PRINCIPAL" });
    expect(cache.size).toBe(0);
    cache.store(slotFor(key), TOKEN_A);
    expect(
      cache.serve(key, currentFor(undefined, undefined, { purpose: "EXTERNAL_AI" }), TOKEN_A),
    ).toEqual({ ok: false, reason: "FOREIGN_PRINCIPAL" });
    expect(cache.size).toBe(0);
    cache.store(slotFor(key), TOKEN_A);
    expect(
      cache.serve(key, currentFor(undefined, undefined, { observedCrsDigest: null }), TOKEN_A),
    ).toEqual({ ok: false, reason: "FOREIGN_PRINCIPAL" });
    expect(cache.size).toBe(0);
  });

  it("stops serving on expired, revoked, or purpose-mismatched rights", () => {
    const cache = new MosaicPaintCache(TOKEN_A);
    const key = "0,512,0,512";
    cache.store(slotFor(key), TOKEN_A);
    expect(cache.serve(key, currentFor(undefined, undefined, { grantLive: false }), TOKEN_A)).toEqual({
      ok: false,
      reason: "GRANT_EXPIRED",
    });
    expect(cache.size).toBe(0);
    cache.store(slotFor(key), TOKEN_A);
    expect(cache.serve(key, currentFor(undefined, undefined, { notRevoked: false }), TOKEN_A)).toEqual({
      ok: false,
      reason: "REVOKED",
    });
    expect(cache.size).toBe(0);
    cache.store(slotFor(key), TOKEN_A);
    expect(
      cache.serve(key, currentFor(undefined, undefined, { purposeAllowed: false }), TOKEN_A),
    ).toEqual({ ok: false, reason: "PURPOSE_MISMATCH" });
    expect(cache.size).toBe(0);
  });
});

describe("mosaic labelling honesty", () => {
  it("keeps the composition wording free of composite ready/verified claims", () => {
    expect(MOSAIC_ASSEMBLY_LABEL).toBe(DISPLAY_ASSEMBLY_LABEL);
    expect(MOSAIC_ASSEMBLY_LABEL).toMatch(/이음새 보정·재표본화 없음/);
    expect(MOSAIC_ASSEMBLY_NOTE).toMatch(/하나의 검증된 자료가 아니/);
    for (const copy of [MOSAIC_ASSEMBLY_LABEL, MOSAIC_ASSEMBLY_NOTE, MOSAIC_VIEWPORT_NOTE]) {
      expect(copy).not.toMatch(/검증됨/);
      expect(copy).not.toMatch(/준비됨/);
      expect(copy).not.toMatch(/하나의 검증된 자료이/);
    }
  });

  it("never presents the viewport as the calculation polygon or a measurement", () => {
    expect(MOSAIC_VIEWPORT_NOTE).toMatch(/계산 다각형이 아닙니다/);
    expect(MOSAIC_VIEWPORT_NOTE).toMatch(/측정값이 아닙니다/);
  });
});

describe("mosaic render path stays resample-free", () => {
  const mosaicLib = readFileSync(
    fileURLToPath(new URL("../src/lib/spatial-display-mosaic.ts", import.meta.url)),
    "utf8",
  );
  const mosaicView = readFileSync(
    fileURLToPath(new URL("../src/app/sites/[siteId]/SiteMosaicViewport.tsx", import.meta.url)),
    "utf8",
  );

  it("paints with smoothing disabled and no blending or scaled blits", () => {
    expect(mosaicView).toContain("imageSmoothingEnabled = false");
    for (const source of [mosaicLib, mosaicView]) {
      expect(source).not.toMatch(/globalAlpha/);
      expect(source).not.toMatch(/drawImage\(/);
      expect(source).not.toMatch(/\.filter\s*=/);
    }
  });

  it("never pulls a geographic basemap or tile path into the mosaic bundle", () => {
    for (const source of [mosaicLib, mosaicView]) {
      expect(source).not.toMatch(/from ["']leaflet["']/);
      expect(source).not.toMatch(/from ["']react-leaflet["']/);
      expect(source).not.toMatch(/proj4/);
      expect(source).not.toMatch(/ImageOverlay/);
    }
  });
});
