import { afterEach, describe, expect, it, vi } from "vitest";

import { coalescedRefresh } from "@/lib/auth/coalesced-refresh";

describe("OIDC refresh single-flight", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("같은 refresh token의 동시 실행을 하나로 합친다", async () => {
    let calls = 0;
    let release!: (value: string) => void;
    const pending = new Promise<string>((resolve) => {
      release = resolve;
    });
    const operation = async () => {
      calls += 1;
      return pending;
    };

    const first = coalescedRefresh("refresh-token-single-flight", operation);
    const second = coalescedRefresh("refresh-token-single-flight", operation);
    release("rotated-token");

    await expect(Promise.all([first, second])).resolves.toEqual([
      "rotated-token",
      "rotated-token",
    ]);
    expect(calls).toBe(1);
  });

  it("Next 서버 bundle 사이에서도 process global registry를 공유한다", async () => {
    let calls = 0;
    let release!: (value: string) => void;
    const pending = new Promise<string>((resolve) => {
      release = resolve;
    });
    const firstModule = await import("@/lib/auth/coalesced-refresh");
    const first = firstModule.coalescedRefresh("refresh-token-cross-bundle", async () => {
      calls += 1;
      return pending;
    });

    vi.resetModules();
    const secondModule = await import("@/lib/auth/coalesced-refresh");
    const second = secondModule.coalescedRefresh("refresh-token-cross-bundle", async () => {
      calls += 1;
      return "unexpected-second-refresh";
    });
    release("rotated-token");

    await expect(Promise.all([first, second])).resolves.toEqual([
      "rotated-token",
      "rotated-token",
    ]);
    expect(calls).toBe(1);
  });

  it("완료 후에는 다음 갱신을 막지 않는다", async () => {
    let calls = 0;
    const operation = async () => {
      calls += 1;
      return calls;
    };

    await expect(coalescedRefresh("refresh-token-reusable", operation)).resolves.toBe(1);
    await expect(coalescedRefresh("refresh-token-reusable", operation)).resolves.toBe(2);
    expect(calls).toBe(2);
  });

  it("회전 직후의 후발 요청은 성공 결과를 짧게 재사용한다", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const operation = async () => {
      calls += 1;
      return `rotated-token-${calls}`;
    };

    await expect(
      coalescedRefresh("refresh-token-rotation-grace", operation, { reuseForMs: 5_000 }),
    ).resolves.toBe("rotated-token-1");
    await expect(
      coalescedRefresh("refresh-token-rotation-grace", operation, { reuseForMs: 5_000 }),
    ).resolves.toBe("rotated-token-1");
    expect(calls).toBe(1);

    await vi.advanceTimersByTimeAsync(5_000);
    await expect(
      coalescedRefresh("refresh-token-rotation-grace", operation, { reuseForMs: 5_000 }),
    ).resolves.toBe("rotated-token-2");
    expect(calls).toBe(2);
  });
});
