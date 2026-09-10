import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EXTERNAL_SANITIZED_DISPLAY_MAX_BYTES,
  fetchVerifiedSanitizedDisplay,
  type ExternalSanitizedDisplayCapability,
} from "@/lib/external-sanitized-display";

const bytes = utf8ToBytes("sanitized KSI orthophoto");
const digest = `sha256:${bytesToHex(sha256(bytes))}`;

function capability(overrides: Partial<ExternalSanitizedDisplayCapability> = {}): ExternalSanitizedDisplayCapability {
  return {
    sanitizedDisplayRef: "sda-v1-synthetic-display",
    receiptDigest: `sha256:${"a".repeat(64)}`,
    observedDerivativeSha256: digest,
    observedDerivativeSizeBytes: bytes.byteLength,
    observedDerivativeContentType: "image/tiff",
    downloadUrl: "https://storage.example.test/sanitized.tif?capability=opaque",
    expiresAt: "2030-01-01T00:00:00Z",
    requiredHeaders: {},
    ...overrides,
  };
}

function openResponse({
  ok = true,
  status = 200,
  contentType = "image/tiff",
  firstChunk,
  cancelError,
}: {
  ok?: boolean;
  status?: number;
  contentType?: string;
  firstChunk?: Uint8Array;
  cancelError?: Error;
} = {}) {
  let cancelCount = 0;
  const body = new ReadableStream<Uint8Array>({
    start(controller) { if (firstChunk) controller.enqueue(firstChunk); },
    cancel() {
      cancelCount += 1;
      return cancelError ? Promise.reject(cancelError) : undefined;
    },
  });
  return {
    response: { ok, status, redirected: false, type: "basic", headers: new Headers({ "content-type": contentType }), body },
    cancelled: () => cancelCount,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("sanitized external display byte boundary", () => {
  it("rejects an expired capability before any object request", async () => {
    const objectFetch = vi.fn();
    vi.stubGlobal("fetch", objectFetch);

    await expect(fetchVerifiedSanitizedDisplay(capability({ expiresAt: "2020-01-01T00:00:00Z" }))).rejects.toThrow("만료");
    expect(objectFetch).not.toHaveBeenCalled();
  });

  it("downloads only the declared byte count with omitted credentials and verifies its exact SHA-256", async () => {
    const objectFetch = vi.fn(async (_url: string, init: RequestInit) => {
      if (init.credentials !== "omit" || init.redirect !== "error" || init.referrerPolicy !== "no-referrer") {
        throw new Error("unsafe object request");
      }
      return new Response(bytes, { headers: { "content-type": "image/tiff" } });
    });
    vi.stubGlobal("fetch", objectFetch);

    await expect(fetchVerifiedSanitizedDisplay(capability())).resolves.toEqual(bytes.buffer);
  });

  it("refuses malformed capabilities, redirects, and mismatched derivative bytes before a raster parser can receive them", async () => {
    const objectFetch = vi.fn(async () => ({
      ok: true,
      redirected: true,
      headers: new Headers({ "content-type": "image/tiff" }),
      body: new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(bytes); controller.close(); } }),
    }));
    vi.stubGlobal("fetch", objectFetch);

    await expect(fetchVerifiedSanitizedDisplay(capability({ downloadUrl: "ftp://unsafe.example.test/file" }))).rejects.toThrow("주소");
    expect(objectFetch).not.toHaveBeenCalled();
    await expect(fetchVerifiedSanitizedDisplay(capability())).rejects.toThrow("리디렉션");
    await expect(fetchVerifiedSanitizedDisplay(capability({ observedDerivativeSizeBytes: EXTERNAL_SANITIZED_DISPLAY_MAX_BYTES + 1 }))).rejects.toThrow("크기");
  });

  it("cancels open response bodies for non-OK and MIME rejection", async () => {
    const unavailable = openResponse({ ok: false, status: 503 });
    const wrongMime = openResponse({ contentType: "application/octet-stream" });
    const objectFetch = vi.fn()
      .mockResolvedValueOnce(unavailable.response)
      .mockResolvedValueOnce(wrongMime.response);
    vi.stubGlobal("fetch", objectFetch);

    await expect(fetchVerifiedSanitizedDisplay(capability())).rejects.toThrow("HTTP 503");
    await expect(fetchVerifiedSanitizedDisplay(capability())).rejects.toThrow("형식");
    await Promise.resolve();
    expect(unavailable.cancelled()).toBe(1);
    expect(wrongMime.cancelled()).toBe(1);
  });

  it("cancels an open oversized stream without masking the primary byte-integrity error when cancellation fails", async () => {
    const oversized = openResponse({ firstChunk: bytes, cancelError: new Error("cancel failed") });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(oversized.response));

    await expect(fetchVerifiedSanitizedDisplay(capability({ observedDerivativeSizeBytes: 1 }))).rejects.toThrow("바이트 크기");
    await Promise.resolve();
    expect(oversized.cancelled()).toBe(1);
  });

  it("cancels a slow open stream when the caller aborts", async () => {
    let cancelCount = 0;
    const body = new ReadableStream<Uint8Array>({
      pull: () => new Promise<void>(() => undefined),
      cancel: () => { cancelCount += 1; },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, redirected: false, type: "basic", headers: new Headers({ "content-type": "image/tiff" }), body }));
    const controller = new AbortController();
    const result = fetchVerifiedSanitizedDisplay(capability(), controller.signal);
    await Promise.resolve();
    controller.abort();

    await expect(result).rejects.toThrow("취소");
    expect(cancelCount).toBe(1);
  });
});
