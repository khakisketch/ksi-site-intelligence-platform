/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("geotiff", () => ({ fromArrayBuffer: vi.fn() }));

import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { fromArrayBuffer } from "geotiff";
import { SitePreviewThumb } from "@/components/site/SitePreviewThumb";

const fromArrayBufferMock = fromArrayBuffer as unknown as ReturnType<typeof vi.fn>;

const digestOf = (bytes: Uint8Array): string => `sha256:${bytesToHex(sha256(bytes))}`;

function descriptor(overrides: Record<string, unknown> = {}) {
  const siteId = (overrides.siteId as string | undefined) ?? "site-1";
  return {
    available: true,
    siteId,
    workAreaId: "area-1",
    workAreaName: "Floreat common-extent",
    requestId: "sdj-v1-00000000-0000-0000-0000-000000000001",
    assetRef: `ksa-v1-${"a".repeat(64)}`,
    artifactKind: "ortho",
    fileHref:
      `/api/sites/${siteId}/work-areas/area-1/spatial-data-requests/sdj-v1-00000000-0000-0000-0000-000000000001/file`,
    outputSha256: digestOf(new Uint8Array([7, 7, 7, 7])),
    outputSizeBytes: 4,
    width: 2,
    height: 2,
    preparedAt: "2026-10-21T00:00:00Z",
    asset: {
      revision: 1,
      gsdM: 0.05,
      captureStartedAt: "2021-08-17T00:00:00Z",
      captureEndedAt: "2021-08-17T00:10:00Z",
      captureDate: null,
      attribution: "Floreat public sample (CC BY 4.0)",
      modificationNotice: "Windowed crop; no reprojection.",
    },
    partial: true,
    siteHref: `/sites/${siteId}?workAreaId=area-1&assetRef=${`ksa-v1-${"a".repeat(64)}`}`,
    ...overrides,
  };
}

function fireVisible() {
  observerApi.fire();
}

let observerApi: { fire(): void } = { fire() {} };

function stubObserver() {
  let fire: (() => void) | null = null;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe = vi.fn();
      disconnect = vi.fn();
      unobserve = vi.fn();
      constructor(callback: IntersectionObserverCallback) {
        fire = () => callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
      }
    },
  );
  const api = {
    fire() {
      fire?.();
    },
  };
  observerApi = api;
  return api;
}

function stubCanvas() {
  const putImageData = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ putImageData } as unknown as CanvasRenderingContext2D);
  vi.stubGlobal(
    "ImageData",
    class {
      constructor(
        public readonly data: Uint8ClampedArray,
        public readonly width: number,
        public readonly height: number,
      ) {}
    },
  );
  return putImageData;
}

function stubGeotiffRgb() {
  fromArrayBufferMock.mockResolvedValue({
    getImageCount: async () => 1,
    getImage: async () => ({
      getWidth: () => 2,
      getHeight: () => 2,
      getSamplesPerPixel: () => 3,
      getBitsPerSample: () => 8,
      readRasters: async () => new Uint8Array([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255]),
    }),
  });
}

beforeEach(() => {
  stubCanvas();
  stubGeotiffRgb();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fromArrayBufferMock.mockReset();
});

describe("SitePreviewThumb", () => {
  it("loads only when visible and links the exact area-asset address", async () => {
    stubObserver();
    const bytes = new Uint8Array([7, 7, 7, 7]);
    const seen: Array<{ url: string; method?: string }> = [];
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      seen.push({ url, method: init?.method });
      if (url.endsWith("/preview")) {
        return new Response(JSON.stringify(descriptor()), { status: 200 });
      }
      return new Response(bytes as unknown as BodyInit, { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId="site-1" size="card" />);
    // Nothing loads before the box is visible.
    expect(fetchMock).not.toHaveBeenCalled();
    fireVisible();

    const link = await screen.findByRole("link", { name: /Floreat common-extent 정사영상 미리보기 일부 범위 열기/ });
    expect(link.getAttribute("href")).toBe(
      `/sites/site-1?workAreaId=area-1&assetRef=${`ksa-v1-${"a".repeat(64)}`}`,
    );
    // Exact source labels, never latest/whole-site claims.
    expect(link.textContent).toContain("Floreat common-extent · 정사영상");
    expect(link.textContent).toContain("부분 범위");
    expect(link.textContent).toContain("제출 GSD 0.05m");
    expect(link.textContent).not.toMatch(/최신|전체 현장/);
    // Attribution is available OUTSIDE the link — hover-only title is not the path.
    expect(link.hasAttribute("title")).toBe(false);
    expect(link.querySelector("details,summary")).toBeNull();
    const info = screen.getByText("자료 정보").closest("details")!;
    expect(link.contains(info)).toBe(false);
    expect(info.textContent).toContain("Floreat public sample (CC BY 4.0)");
    await waitFor(() => {
      const canvas = link.querySelector("canvas")!;
      expect(canvas.width).toBe(2);
      expect(canvas.height).toBe(2);
    });
    // Read-only: every call is GET.
    expect(seen.length).toBeGreaterThanOrEqual(2);
    expect(seen.every((call) => !call.method || call.method === "GET")).toBe(true);
    expect(link.querySelector("input,button,select,textarea")).toBeNull();
  });

  it("labels single-band output as relative shading, not a measurement", async () => {
    stubObserver();
    const siteId = "site-2";
    const bytes = new Uint8Array([9, 9, 9, 9]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/preview")) {
          return new Response(
            JSON.stringify(
              descriptor({
                siteId,
                artifactKind: "dsm",
                outputSha256: digestOf(bytes),
              }),
            ),
            { status: 200 },
          );
        }
        return new Response(bytes as unknown as BodyInit, { status: 200 });
      }),
    );
    fromArrayBufferMock.mockResolvedValue({
      getImageCount: async () => 1,
      getImage: async () => ({
        getWidth: () => 2,
        getHeight: () => 2,
        getSamplesPerPixel: () => 1,
        getBitsPerSample: () => 8,
        readRasters: async () => new Uint8Array([10, 20, 30, 40]),
        getGDALNoData: () => null,
      }),
    });

    render(<SitePreviewThumb siteId={siteId} size="card" />);
    fireVisible();
    const link = await screen.findByRole("link", { name: /미리보기 일부 범위 열기/ });
    expect(link.textContent).toContain("상대 음영");
    expect(link.textContent).not.toMatch(/정확도|측량|정산/);
  });

  it("shows an honest unavailable state without touching bytes when nothing is allowed", async () => {
    stubObserver();
    const siteId = "site-3";
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ available: false, reason: "no-output" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId={siteId} size="card" />);
    fireVisible();
    await screen.findByText("표시할 미리보기 없음");
    // Descriptor only — no byte read attempted.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link")).toBeNull();
    // Honesty is about display availability, never about holdings.
    expect(document.body.textContent).not.toMatch(/자료 없음|등록된 자료가 없|관측자료 없음/);
  });

  it("says cannot-verify on denial instead of pretending no output", async () => {
    stubObserver();
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/preview")) {
        return new Response(JSON.stringify({ message: "denied" }), { status: 403 });
      }
      return new Response("denied", { status: 403 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId="site-4" size="card" />);
    fireVisible();
    await screen.findByText("미리보기를 확인하지 못함");
    expect(screen.queryByText("표시할 미리보기 없음")).toBeNull();
    expect(document.querySelector("canvas")).toBeNull();
  });

  it("fetches fresh on remount and does not hold a success across mounts", async () => {
    stubObserver();
    const bytes = new Uint8Array([7, 7, 7, 7]);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/preview")) {
        return new Response(JSON.stringify(descriptor({ siteId: "site-5" })), { status: 200 });
      }
      return new Response(bytes as unknown as BodyInit, { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const first = render(<SitePreviewThumb siteId="site-5" size="card" />);
    fireVisible();
    await screen.findByRole("link", { name: /미리보기 일부 범위 열기/ });
    const descriptorCalls = fetchMock.mock.calls.filter(([url]) => (url as string).endsWith("/preview")).length;
    expect(descriptorCalls).toBe(1);
    first.unmount();
    cleanup();
    render(<SitePreviewThumb siteId="site-5" size="card" />);
    fireVisible();
    await screen.findByRole("link", { name: /미리보기 일부 범위 열기/ });
    expect(fetchMock.mock.calls.filter(([url]) => (url as string).endsWith("/preview")).length).toBe(2);
  });

  it("row cue carries partial, source, and capture info without implying whole data", async () => {
    stubObserver();
    const siteId = "site-6";
    const bytes = new Uint8Array([7, 7, 7, 7]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/preview")) {
          return new Response(JSON.stringify(descriptor({ siteId })), { status: 200 });
        }
        return new Response(bytes as unknown as BodyInit, { status: 200 });
      }),
    );

    render(<SitePreviewThumb siteId={siteId} size="row" />);
    fireVisible();
    const link = await screen.findByRole("link", { name: /Floreat common-extent 정사영상 미리보기 일부 범위 열기/ });
    expect(link.getAttribute("aria-label")).toContain("2021");
    // Attribution lives outside the link, reachable by assistive tech.
    const described = document.getElementById(link.getAttribute("aria-describedby")!);
    expect(described?.textContent).toContain("Floreat public sample (CC BY 4.0)");
    expect(link.querySelector("details,summary,input,button")).toBeNull();
  });

  it("does not share an old in-flight descriptor or abort signal with a new mount", async () => {
    stubObserver();
    let finishOld!: (response: Response) => void;
    const oldReply = new Promise<Response>((resolve) => { finishOld = resolve; });
    let lookups = 0;
    let oldSignal: AbortSignal | undefined;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/preview")) {
        lookups += 1;
        if (lookups === 1) {
          oldSignal = init?.signal as AbortSignal;
          return oldReply;
        }
        return new Response(JSON.stringify({ available: false, reason: "no-output" }), { status: 200 });
      }
      throw new Error("No bytes are allowed for the new mount");
    });
    vi.stubGlobal("fetch", fetchMock);
    const first = render(<SitePreviewThumb siteId="site-8" size="card" />);
    fireVisible();
    await waitFor(() => expect(lookups).toBe(1));
    first.unmount();
    expect(oldSignal?.aborted).toBe(true);
    render(<SitePreviewThumb siteId="site-8" size="card" />);
    fireVisible();
    await screen.findByText("표시할 미리보기 없음");
    expect(lookups).toBe(2);
    finishOld(new Response(JSON.stringify(descriptor({ siteId: "site-8" })), { status: 200 }));
    await waitFor(() => expect(screen.queryByRole("link")).toBeNull());
    expect(fetchMock.mock.calls.every(([url]) => url.endsWith("/preview"))).toBe(true);
  });

  it("row loading state never claims unavailable", async () => {
    stubObserver();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        await new Promise(() => undefined);
        return new Response("never", { status: 200 });
      }),
    );

    render(<SitePreviewThumb siteId="site-7" size="row" />);
    fireVisible();
    const pending = await screen.findByRole("img", { name: "미리보기 불러오는 중" });
    expect(pending.getAttribute("aria-label")).not.toMatch(/없음|확인하지 못함/);
  });
});
