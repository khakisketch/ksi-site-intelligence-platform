import { describe, expect, it, vi } from "vitest";

import {
  DisplayPrepareIssueError,
  DisplayPrepareScheduler,
  isRetryableLaneError,
  saturatedLaneCopy,
  stableIdempotencyKey,
  stablePrepareKey,
  type DisplayIssueFn,
  type ScheduledDisplayWindow,
} from "@/lib/spatial-display-scheduler";

const DIGEST = `sha256:${"c".repeat(64)}`;

function scheduled(key: string, col = 0): ScheduledDisplayWindow {
  return {
    key,
    assetRef: `ksa-v1-${"b".repeat(64)}`,
    pixelWindow: [col, col + 1, 0, 1],
    requestedBounds: [col, 0, col + 1, 1],
    observedCrsDigest: DIGEST,
    purpose: "GENERAL_DATA_USE",
  };
}

async function flush(times = 20): Promise<void> {
  for (let i = 0; i < times; i += 1) {
    await Promise.resolve();
    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  }
}

describe("stablePrepareKey", () => {
  it("keys the same window stably and separates different windows", () => {
    const assetRef = `ksa-v1-${"b".repeat(64)}`;
    expect(stablePrepareKey(assetRef, [0, 512, 0, 512], "GENERAL_DATA_USE")).toBe(
      stablePrepareKey(assetRef, [0, 512, 0, 512], "GENERAL_DATA_USE"),
    );
    expect(stablePrepareKey(assetRef, [0, 512, 0, 512], "GENERAL_DATA_USE")).not.toBe(
      stablePrepareKey(assetRef, [512, 1022, 0, 512], "GENERAL_DATA_USE"),
    );
    expect(stablePrepareKey(assetRef, [0, 512, 0, 512], "GENERAL_DATA_USE")).not.toBe(
      stablePrepareKey(assetRef, [0, 512, 0, 512], "EXTERNAL_AI"),
    );
    // Idempotency-Key 헤더 패턴에 맞는다.
    expect(stableIdempotencyKey(assetRef, [0, 512, 0, 512], "GENERAL_DATA_USE")).toMatch(
      /^[A-Za-z0-9._:-]{1,128}$/,
    );
  });
});

describe("DisplayPrepareScheduler concurrency", () => {
  it("issues at most 2 concurrent PREPAREs and names the saturated lane", async () => {
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
    const snapshot = scheduler.ensure([
      scheduled("a"),
      scheduled("b"),
      scheduled("c"),
      scheduled("d"),
    ]);
    await flush();
    expect(peak).toBeLessThanOrEqual(2);
    expect(snapshot.activeCount).toBe(2);
    expect(snapshot.queuedCount).toBe(2);
    // 포화 레인은 이름 있는 상태다 — 빈 화면·조용한 대체 금지.
    expect(snapshot.laneCopy).toBe(saturatedLaneCopy(2, 2));
    expect(snapshot.laneCopy).toMatch(/기다리는 창 2개 · 순차 처리 중/);
    releases.get("a")!();
    await flush();
    expect(peak).toBeLessThanOrEqual(2);
    const later = scheduler.snapshot();
    expect(later.done).toContain("a");
    expect(later.activeCount).toBe(2);
  });

  it("dedupes by stable key and joins in-flight requests", async () => {
    let calls = 0;
    let release!: (value: { jobId: string; executionState: string }) => void;
    const gate = new Promise<{ jobId: string; executionState: string }>((resolve) => {
      release = resolve;
    });
    const issue: DisplayIssueFn = async () => {
      calls += 1;
      return gate;
    };
    const scheduler = new DisplayPrepareScheduler(issue);
    scheduler.ensure([scheduled("a"), scheduled("b")]);
    await flush();
    expect(calls).toBe(2);
    // 반복 제스처는 새 PREPARE가 없다.
    scheduler.ensure([scheduled("a"), scheduled("b")]);
    await flush();
    expect(calls).toBe(2);
    // 진행 중 요청은 합류한다.
    const joined = scheduler.join("a");
    expect(joined).not.toBeNull();
    release({ jobId: "job-a", executionState: "QUEUED" });
    await expect(joined!).resolves.toEqual({ jobId: "job-a", executionState: "QUEUED" });
    await flush();
    expect(scheduler.snapshot().done).toContain("a");
  });
});

describe("DisplayPrepareScheduler retry", () => {
  it("backs off and retries a retryable 429 with bounded attempts", async () => {
    let calls = 0;
    const sleeps: number[] = [];
    const issue: DisplayIssueFn = async () => {
      calls += 1;
      if (calls <= 2) {
        throw new DisplayPrepareIssueError("동시 요청이 많아 순차 처리 중입니다.", {
          status: 429,
          code: "CONCURRENCY_LIMIT_EXCEEDED",
          retryable: true,
        });
      }
      return { jobId: "job-a", executionState: "QUEUED" };
    };
    const scheduler = new DisplayPrepareScheduler(issue, {
      maxRetries: 3,
      backoffMs: (attempt) => attempt * 10,
      sleep: async (ms) => {
        sleeps.push(ms);
      },
    });
    scheduler.ensure([scheduled("a")]);
    await flush(40);
    const snapshot = scheduler.snapshot();
    expect(calls).toBe(3);
    expect(sleeps).toEqual([10, 20]);
    expect(snapshot.done).toContain("a");
    expect(snapshot.failed).toEqual({});
  });

  it("fails honestly after bounded retries instead of spinning forever", async () => {
    let calls = 0;
    const issue: DisplayIssueFn = async () => {
      calls += 1;
      throw new DisplayPrepareIssueError("동시 요청이 많아 순차 처리 중입니다.", {
        status: 429,
        code: "CONCURRENCY_LIMIT_EXCEEDED",
        retryable: true,
      });
    };
    const scheduler = new DisplayPrepareScheduler(issue, {
      maxRetries: 2,
      backoffMs: () => 0,
      sleep: async () => undefined,
    });
    scheduler.ensure([scheduled("a")]);
    await flush(40);
    // 첫 발행 + 2회 재시도 = 3회, 그 이상은 발행하지 않는다.
    expect(calls).toBe(3);
    expect(scheduler.snapshot().failed["a"]).toBeTruthy();
    expect(scheduler.snapshot().done).not.toContain("a");
  });

  it("does not retry non-retryable failures", async () => {
    const issue: DisplayIssueFn = vi.fn(async () => {
      throw new DisplayPrepareIssueError("출력 픽셀 한계를 넘었습니다.", {
        status: 422,
        code: "OUTPUT_PIXEL_LIMIT_EXCEEDED",
        retryable: false,
      });
    });
    const scheduler = new DisplayPrepareScheduler(issue, { sleep: async () => undefined });
    scheduler.ensure([scheduled("a")]);
    await flush();
    expect(issue).toHaveBeenCalledTimes(1);
    expect(isRetryableLaneError(new DisplayPrepareIssueError("x", { status: 429 }))).toBe(true);
    expect(
      isRetryableLaneError(new DisplayPrepareIssueError("x", { status: 422, retryable: false })),
    ).toBe(false);
  });
});

describe("DisplayPrepareScheduler supersede", () => {
  it("abandons queued windows outside the new viewport and lets active ones finish", async () => {
    const issued: string[] = [];
    const releases = new Map<string, () => void>();
    const issue: DisplayIssueFn = (window) =>
      new Promise((resolve) => {
        issued.push(window.key);
        releases.set(window.key, () => resolve({ jobId: `job-${window.key}`, executionState: "QUEUED" }));
      });
    const scheduler = new DisplayPrepareScheduler(issue, { maxConcurrent: 1 });
    scheduler.ensure([scheduled("a"), scheduled("b"), scheduled("c")]);
    await flush();
    expect(scheduler.snapshot().active).toEqual(["a"]);
    // 뷰포트가 moved on — 대기 b·c는 버리고(포기), d를 둔다.
    const snapshot = scheduler.ensure([scheduled("a"), scheduled("d")]);
    expect(snapshot.cancelled).toContain("b");
    expect(snapshot.cancelled).toContain("c");
    releases.get("a")!();
    await flush();
    // 끝난 a는 기록에 남고, 버려진 b·c는 발행되지 않으며 d가 발행된다.
    expect(scheduler.snapshot().done).toContain("a");
    expect(issued).toContain("d");
    expect(issued).not.toContain("b");
    expect(issued).not.toContain("c");
  });
});
