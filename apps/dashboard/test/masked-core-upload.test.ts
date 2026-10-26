import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => {
  class MissingSessionError extends Error {
    constructor() {
      super("세션이 없습니다 — 다시 로그인하세요.");
      this.name = "MissingSessionError";
    }
  }
  return { session: vi.fn(), MissingSessionError };
});
vi.mock("@/lib/core-api/session", () => ({
  getSessionToken: mocked.session,
  MissingSessionError: mocked.MissingSessionError,
}));
vi.mock("@/lib/core-api/env", () => ({ coreApiBaseUrl: () => "https://core.test" }));

import { CoreApiError } from "@/lib/core-api/client";
import { coreMaskUploadBytes } from "@/lib/core-api/masked-core";

function deferredSource(chunkCount: number, chunkSize: number) {
  let pulls = 0;
  let cancelled = false;
  let produced = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      pulls += 1;
      if (produced < chunkCount) {
        produced += 1;
        controller.enqueue(new Uint8Array(chunkSize));
      } else {
        controller.close();
      }
    },
    cancel() {
      cancelled = true;
    },
  });
  return { stream, stats: () => ({ pulls, cancelled, produced }) };
}

function okJson(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
  mocked.session.mockResolvedValue("token-operator-1");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("coreMaskUploadBytes pull-based forwarding", () => {
  it("소비자가 당기기 전에는 업스트림을 읽지 않는다", async () => {
    const source = deferredSource(100, 1024);
    let pullsAtFetch = -1;
    vi.stubGlobal("fetch", vi.fn(async (_input: unknown, init?: { body?: ReadableStream<Uint8Array> }) => {
      pullsAtFetch = source.stats().pulls;
      const reader = (init!.body as ReadableStream<Uint8Array>).getReader();
      const first = await reader.read();
      expect(first.done).toBe(false);
      await reader.cancel();
      return okJson({ ok: true });
    }));
    const result = await coreMaskUploadBytes<{ ok: boolean }>("/v3/x", {
      stream: source.stream,
      byteLength: null,
      budgetBytes: 1 << 30,
    });
    expect(result).toEqual({ ok: true });
    // 미리 쌓아두지 않으므로 fetch 시점에는 최대 HWM 1청크까지만 읽는다.
    expect(pullsAtFetch).toBeLessThanOrEqual(1);
    // 한 청크만 소비했으므로 전체를 읽지 않는다.
    expect(source.stats().pulls).toBeLessThanOrEqual(4);
    expect(source.stats().cancelled).toBe(true);
  });

  it("상한을 넘으면 413으로 끊고 원본을 취소한다", async () => {
    const source = deferredSource(10, 1024);
    // fetch 모사는 본문을 끝까지 소비한다 — 그 과정에서 상한 오류가 터진다.
    vi.stubGlobal("fetch", vi.fn(async (_input: unknown, init?: { body?: ReadableStream<Uint8Array> }) => {
      const reader = (init!.body as ReadableStream<Uint8Array>).getReader();
      try {
        while (true) {
          const { done } = await reader.read();
          if (done) break;
        }
      } catch (error) {
        throw error;
      }
      return okJson({ ok: true });
    }));
    await expect(coreMaskUploadBytes("/v3/x", {
      stream: source.stream,
      byteLength: null,
      budgetBytes: 1500,
    })).rejects.toMatchObject({ status: 413 });
    // 2KiB째에서 끊기므로 전체 10청크를 읽지 않는다.
    expect(source.stats().pulls).toBeLessThanOrEqual(3);
    expect(source.stats().cancelled).toBe(true);
  });

  it("선언 길이와 다르면 400으로 닫는다", async () => {
    const source = deferredSource(2, 10);
    vi.stubGlobal("fetch", vi.fn(async (_input: unknown, init?: { body?: ReadableStream<Uint8Array> }) => {
      const reader = (init!.body as ReadableStream<Uint8Array>).getReader();
      try {
        while (true) {
          const { done } = await reader.read();
          if (done) break;
        }
      } catch (error) {
        throw error;
      }
      return okJson({ ok: true });
    }));
    await expect(coreMaskUploadBytes("/v3/x", {
      stream: source.stream,
      byteLength: 100,
      budgetBytes: 1 << 20,
    })).rejects.toMatchObject({ status: 400 });
  });

  it("실패 응답이 오면 업스트림 읽기를 멈춘다", async () => {
    const source = deferredSource(50, 1024);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "MASK_UPLOAD_REJECTED" }), {
      status: 409,
      headers: { "content-type": "application/json" },
    })));
    const error = await coreMaskUploadBytes("/v3/x", {
      stream: source.stream,
      byteLength: null,
      budgetBytes: 1 << 30,
    }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CoreApiError);
    expect((error as CoreApiError).status).toBe(409);
    expect(source.stats().cancelled).toBe(true);
  });

  it("타임아웃 중단이 원본 reader를 취소한다", async () => {
    vi.useFakeTimers();
    const source = deferredSource(1000, 1024);
    vi.stubGlobal("fetch", vi.fn(async (_input: unknown, init?: { signal?: AbortSignal }) => {
      await new Promise((_resolve, reject) => {
        init!.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
      return okJson({ ok: true });
    }));
    const pending = coreMaskUploadBytes("/v3/x", {
      stream: source.stream,
      byteLength: null,
      budgetBytes: 1 << 30,
    });
    const guarded = expect(pending).rejects.toMatchObject({ status: 503 });
    await vi.advanceTimersByTimeAsync(20_000);
    await guarded;
    expect(source.stats().cancelled).toBe(true);
  });
});
