import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SPATIAL_DATA_PREVIEW_MAX_BYTES,
  fetchVerifiedReceiptBytes,
  SpatialDataPreviewError,
} from "@/lib/spatial-data-preview";

const digestOf = (bytes: Uint8Array): string => `sha256:${bytesToHex(sha256(bytes))}`;

const FILE_HREF = "/api/sites/site-1/work-areas/area-1/spatial-data-requests/sdj-v1-12345678-1234-1234-1234-123456789abc/file";

function okResponse(bytes: Uint8Array): Response {
  return new Response(bytes as unknown as BodyInit, {
    status: 200,
    headers: { "content-type": "image/tiff" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("fetchVerifiedReceiptBytes", () => {
  it("returns bytes only when size and full SHA-256 match the Core receipt", async () => {
    const bytes = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]);
    vi.stubGlobal("fetch", vi.fn(async () => okResponse(bytes)));

    const result = await fetchVerifiedReceiptBytes(FILE_HREF, {
      outputSha256: digestOf(bytes),
      outputSizeBytes: bytes.byteLength,
    });

    expect(new Uint8Array(result)).toEqual(bytes);
  });

  it("rejects a hash mismatch without exposing bytes", async () => {
    const bytes = new Uint8Array([9, 9, 9]);
    vi.stubGlobal("fetch", vi.fn(async () => okResponse(bytes)));

    const failure = await fetchVerifiedReceiptBytes(FILE_HREF, {
      outputSha256: `sha256:${"0".repeat(64)}`,
      outputSizeBytes: bytes.byteLength,
    }).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("HASH_MISMATCH");
  });

  it("rejects a size mismatch without exposing bytes", async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    vi.stubGlobal("fetch", vi.fn(async () => okResponse(bytes)));

    const failure = await fetchVerifiedReceiptBytes(FILE_HREF, {
      outputSha256: digestOf(bytes),
      outputSizeBytes: bytes.byteLength + 1,
    }).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("SIZE_MISMATCH");
  });

  it("refuses oversized receipts before any fetch", async () => {
    const fetchSpy = vi.fn(async () => okResponse(new Uint8Array([1])));
    vi.stubGlobal("fetch", fetchSpy);

    const failure = await fetchVerifiedReceiptBytes(FILE_HREF, {
      outputSha256: `sha256:${"0".repeat(64)}`,
      outputSizeBytes: SPATIAL_DATA_PREVIEW_MAX_BYTES + 1,
    }).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("TOO_LARGE");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("refuses a malformed receipt digest before any fetch", async () => {
    const fetchSpy = vi.fn(async () => okResponse(new Uint8Array([1])));
    vi.stubGlobal("fetch", fetchSpy);

    const failure = await fetchVerifiedReceiptBytes(FILE_HREF, {
      outputSha256: "not-a-digest",
      outputSizeBytes: 1,
    }).catch((error: unknown) => error);

    expect((failure as SpatialDataPreviewError).kind).toBe("BAD_RECEIPT");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it.each([
    "//evil.test/x",
    "/\\evil.test/x",
    "https://evil.test/api/sites/s/work-areas/w/spatial-data-requests/j/file",
    `${FILE_HREF}?x=1`,
    `${FILE_HREF}#f`,
    "/api/sites/a/../b/work-areas/w/spatial-data-requests/j/file",
    "/api/sites/si te/work-areas/w/spatial-data-requests/j/file",
    "/api/sites/s/work-areas/w/spatial-data-requests/j/other",
    "/api/sites/s/work-areas/w/spatial-data-requests/file",
  ])("rejects an unsafe href without fetching: %s", async (href) => {
    const fetchSpy = vi.fn(async () => okResponse(new Uint8Array([1])));
    vi.stubGlobal("fetch", fetchSpy);

    const failure = await fetchVerifiedReceiptBytes(href, {
      outputSha256: `sha256:${"0".repeat(64)}`,
      outputSizeBytes: 1,
    }).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("BAD_RECEIPT");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("carries the Core status and typed code on HTTP failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ code: "ACCESS_REVOKED", message: "revoked" }), {
        status: 403,
        headers: { "content-type": "application/json" },
      })),
    );

    const failure = await fetchVerifiedReceiptBytes(FILE_HREF, {
      outputSha256: `sha256:${"0".repeat(64)}`,
      outputSizeBytes: 8,
    }).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    const typed = failure as SpatialDataPreviewError;
    expect(typed.kind).toBe("HTTP");
    expect(typed.status).toBe(403);
    expect(typed.code).toBe("ACCESS_REVOKED");
  });

  it("treats cancellation as a cancel, not a download failure", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchSpy = vi.fn(async () => okResponse(new Uint8Array([1])));
    vi.stubGlobal("fetch", fetchSpy);

    const failure = await fetchVerifiedReceiptBytes(
      FILE_HREF,
      { outputSha256: `sha256:${"0".repeat(64)}`, outputSizeBytes: 1 },
      controller.signal,
    ).catch((error: unknown) => error);

    expect((failure as SpatialDataPreviewError).kind).toBe("CANCELLED");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("maps an aborted fetch to cancellation", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        controller.abort();
        throw new DOMException("aborted", "AbortError");
      }),
    );

    const failure = await fetchVerifiedReceiptBytes(
      FILE_HREF,
      { outputSha256: `sha256:${"0".repeat(64)}`, outputSizeBytes: 1 },
      controller.signal,
    ).catch((error: unknown) => error);

    expect((failure as SpatialDataPreviewError).kind).toBe("CANCELLED");
  });

  it("times out a hanging read as a timeout, distinct from cancel", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => new Promise<never>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      })),
    );

    const failure = await fetchVerifiedReceiptBytes(
      FILE_HREF,
      { outputSha256: `sha256:${"0".repeat(64)}`, outputSizeBytes: 1 },
      undefined,
      { timeoutMs: 20 },
    ).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("TIMEOUT");
  });

  it("rejects non-same-session hrefs without fetching", async () => {
    const fetchSpy = vi.fn(async () => okResponse(new Uint8Array([1])));
    vi.stubGlobal("fetch", fetchSpy);

    const failure = await fetchVerifiedReceiptBytes("https://example.test/file.bin", {
      outputSha256: `sha256:${"0".repeat(64)}`,
      outputSizeBytes: 1,
    }).catch((error: unknown) => error);

    expect((failure as SpatialDataPreviewError).kind).toBe("BAD_RECEIPT");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
