/** @vitest-environment jsdom */
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("geotiff", () => ({
  fromArrayBuffer: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { fromArrayBuffer } from "geotiff";
import { SiteMosaicViewport } from "@/app/sites/[siteId]/SiteMosaicViewport";
import type { PreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";

const fromArrayBufferMock = fromArrayBuffer as unknown as ReturnType<typeof vi.fn>;
const digestOf = (bytes: Uint8Array): string => `sha256:${bytesToHex(sha256(bytes))}`;
const assetRef = `ksa-v1-${"b".repeat(64)}`;
const crsDigest = `sha256:${"c".repeat(64)}`;

/** 작은 합성 격자 — 1022×915, 1 m, 북위. 값은 테스트 고정값이며 제품 자료가 아니다. */
const grid = { transform: [1, 0, 0, 0, -1, 915], width: 1022, height: 915 };

const BYTES = new Uint8Array(512 * 512 * 3).fill(7);

function readableJob(): PreparedWindowJob {
  return {
    jobId: "sdj-v1-00000000-0000-0000-0000-000000000011",
    assetRef,
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    createdAt: "2026-10-21T00:00:00Z",
    receipt: {
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000011",
      receiptDigest: null,
      artifactKind: "ortho",
      outputSizeBytes: BYTES.byteLength,
      outputSha256: digestOf(BYTES),
      requestedBounds: [0, 403, 512, 915],
      actualBounds: [0, 403, 512, 915],
      pixelWindow: [0, 512, 0, 512],
      width: 512,
      height: 512,
      observedCrsIdentifier: "EPSG:7850",
      observedCrsDigest: crsDigest,
      accuracyAssessed: false,
      attribution: "attr",
      modificationNotice: "mod",
      limitations: [],
      preparedAt: "2026-10-21T00:00:00Z",
    },
  };
}

function stubCanvas() {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    putImageData: vi.fn(),
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    imageSmoothingEnabled: true,
  } as unknown as CanvasRenderingContext2D);
  vi.stubGlobal("ImageData", class {
    constructor(
      public readonly data: Uint8ClampedArray,
      public readonly width: number,
      public readonly height: number,
    ) {}
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fromArrayBufferMock.mockReset();
});

function renderMosaic(jobs: PreparedWindowJob[]) {
  return render(
    <SiteMosaicViewport
      siteId="site-1"
      workAreaId="area-1"
      assetRef={assetRef}
      grid={grid}
      observedCrsDigest={crsDigest}
      observedCrsIdentifier="EPSG:7850"
      isDsm={false}
      jobs={jobs}
      canRequest
      requestsHref="/sites/site-1/spatial-data-requests?workAreaId=area-1"
    />,
  );
}

describe("site mosaic viewport fill gate", () => {
  it("issues no writes on entry while authorized reads load automatically", async () => {
    stubCanvas();
    const posts: string[] = [];
    const gets: string[] = [];
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") posts.push(url);
      else gets.push(String(url));
      return new Response(BYTES, { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderMosaic([readableJob()]);

    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(screen.getByText("준비 과정·상세 상태")).toBeTruthy();
    expect(screen.getByText(/이음새 보정·재표본화 없음/)).toBeTruthy();
    expect(screen.getByText(/계산 다각형이 아닙니다/)).toBeTruthy();
    // 진입만으로는 준비 요청(POST)이 나가지 않는다 — 쓰기는 명시적 채우기에서만 나간다.
    // 이미 준비된 창의 읽기(GET)는 같은 세션 경로로 진입 시 나간다.
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(posts).toHaveLength(0);
    expect(gets.length).toBeGreaterThan(0);
    for (const url of gets) expect(url.startsWith("/api/")).toBe(true);
  });

  it("fills only missing windows on explicit action with exact native bounds", async () => {
    stubCanvas();
    fromArrayBufferMock.mockResolvedValue({
      getImageCount: async () => 1,
      getImage: async () => ({
        getWidth: () => 512,
        getHeight: () => 512,
        getSamplesPerPixel: () => 3,
        getBitsPerSample: () => 8,
        getGDALNoData: () => null,
        readRasters: async () => BYTES,
      }),
    });
    const posts: Array<{ url: string; body: Record<string, unknown>; key: string | null }> = [];
    const gets: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        posts.push({ url, body, key: new Headers(init?.headers).get("Idempotency-Key") });
        return new Response(
          JSON.stringify({ jobId: `sdj-v1-posted-${posts.length}`, executionState: "QUEUED" }),
          { status: 201, headers: { "content-type": "application/json" } },
        );
      }
      gets.push(url);
      return new Response(BYTES, { status: 200, headers: { "content-type": "image/tiff" } });
    }));
    renderMosaic([readableJob()]);

    // 읽을 수 있는 한 창을 빼고 세 창이 모자라다.
    fireEvent.click(screen.getByRole("button", { name: /미리보기 다시 준비/ }));
    await screen.findByText(/창 3개의 준비 요청을 만들었습니다/);

    expect(posts).toHaveLength(3);
    for (const post of posts) {
      expect(post.url).toBe("/api/sites/site-1/work-areas/area-1/spatial-data-requests");
      expect(post.body.assetRef).toBe(assetRef);
      expect(post.body.resolutionMode).toBe("NATIVE");
      expect(post.body.purpose).toBe("GENERAL_DATA_USE");
      expect(post.key).toMatch(/^[A-Za-z0-9._:-]{1,128}$/);
    }
    const postedBounds = posts.map((post) => JSON.stringify(post.body.requestedBounds));
    // 이미 읽을 수 있는 [0,512,0,512] 창은 다시 요청하지 않는다.
    expect(postedBounds).not.toContain(JSON.stringify([0, 403, 512, 915]));
    expect(new Set(posts.map((post) => post.key)).size).toBe(3);
    // 읽을 수 있는 창의 바이트는 같은 세션 경로로만 받는다.
    expect(gets.length).toBeGreaterThan(0);
    for (const url of gets) expect(url.startsWith("/api/")).toBe(true);
  });
});
