/** @vitest-environment jsdom */
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("geotiff", () => ({
  fromArrayBuffer: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { fromArrayBuffer } from "geotiff";
import { SiteMosaicViewport } from "@/app/sites/[siteId]/SiteMosaicViewport";
import type { PreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";

const assetRef = `ksa-v1-${"b".repeat(64)}`;
const crsDigest = `sha256:${"c".repeat(64)}`;
const grid = { transform: [1, 0, 0, 0, -1, 915], width: 1022, height: 915 };
const BYTES = new Uint8Array(512 * 512 * 3).fill(7);
const digestOf = (bytes: Uint8Array): string => `sha256:${bytesToHex(sha256(bytes))}`;
const fromArrayBufferMock = fromArrayBuffer as unknown as ReturnType<typeof vi.fn>;

function stubGeotiffRgb() {
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
}

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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fromArrayBufferMock.mockReset();
});

describe("site mosaic clean map", () => {
  it("renders canvas-only map frame without per-tile status or dashed boundaries", async () => {
    stubCanvas();
    stubGeotiffRgb();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(BYTES, { status: 200 })));
    renderMosaic([readableJob()]);

    const frame = await screen.findByRole("group", { name: /직접 끌어서 보고/ });
    // Valid canvas pixels only — no per-window status sentences inside the map.
    expect(within(frame).queryByText("그리지 않음")).toBeNull();
    expect(within(frame).queryByText("표시 준비 필요")).toBeNull();
    expect(within(frame).queryByText("자료 읽는 중")).toBeNull();
    expect(within(frame).queryByText("준비 중")).toBeNull();
    // No dashed per-window boundaries inside the map.
    expect(frame.querySelector(".border-dashed")).toBeNull();
    expect(frame.querySelector("[aria-hidden='true'].absolute")).toBeNull();
    // Canvas itself remains with native pixel label.
    expect(await within(frame).findByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    // Aggregate honesty stays outside the map.
    expect(screen.getByText("준비 과정·상세 상태")).toBeTruthy();
    expect(screen.getAllByText(/그린 창|부분 보기/).length).toBeGreaterThan(0);
  });

  it("frames full width with pixel-proportion aspect ratio and no max-width cap", async () => {
    stubCanvas();
    stubGeotiffRgb();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(BYTES, { status: 200 })));
    renderMosaic([readableJob()]);

    const frame = (await screen.findByRole("group", { name: /직접 끌어서 보고/ })) as HTMLElement;
    expect(frame.className).toContain("w-full");
    expect(frame.className).not.toContain("mx-auto");
    expect(frame.style.maxWidth).toBe("");
    expect(frame.style.aspectRatio).toBe("1022 / 915");
  });

  it("replaces the oversized blank with a compact extent diagram, never a photo", () => {
    stubCanvas();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(BYTES, { status: 200 })));
    const ring: Array<[number, number]> = [[0, 0], [1022, 0], [1022, 915], [0, 915]];
    render(
      <SiteMosaicViewport
        siteId="site-1"
        workAreaId="area-1"
        assetRef={assetRef}
        grid={grid}
        observedCrsDigest={crsDigest}
        observedCrsIdentifier="EPSG:7850"
        isDsm={false}
        jobs={[]}
        canRequest
        requestsHref="/sites/site-1/spatial-data-requests?workAreaId=area-1"
        workAreaRing={ring}
        workAreaCrs="EPSG:7850"
      />,
    );

    // No client-only diagnostic toggle — no authorization is passed.
    expect(screen.queryAllByRole("checkbox").length).toBe(0);
    expect(screen.queryByText(/진단/)).toBeNull();
    expect(screen.queryByText(/디버그/i)).toBeNull();
    expect(screen.queryByText(/diagnostic/i)).toBeNull();
    // No oversized empty hero remains.
    const statusBox = screen.getByText(/준비된 표시 자료가 없습니다/).closest("div");
    expect(statusBox?.className ?? "").not.toContain("min-h-64");
    expect(statusBox?.className ?? "").not.toContain("lg:min-h-[55dvh]");
    // Same-plane work area is overlaid; the diagram is labelled as a sketch, not a photo.
    expect(screen.getByText("범위 도식 · 사진 아님")).toBeTruthy();
    expect(screen.getByText(/실선은 작업구역 경계이며, 점선은 파일 전체 범위입니다/)).toBeTruthy();
    // Never pretend NoData-free coverage — the rectangle is the file extent, not valid pixels.
    expect(screen.getByText(/빈틈 없는 유효 픽셀로 읽지 마세요/)).toBeTruthy();
    expect(screen.getByText(/사진이 아니며 정확도를 보증하지 않습니다/)).toBeTruthy();
    // Actual measured extent from the grid transform [1,0,0,0,-1,915] 1022×915.
    expect(screen.getByText("0 – 1022")).toBeTruthy();
    expect(screen.getByText("0 – 915")).toBeTruthy();
    expect(screen.getByText(/1022 × 915 네이티브 픽셀/)).toBeTruthy();
    // Aggregate honesty stays outside the map.
    expect(screen.getByText("준비 과정·상세 상태")).toBeTruthy();
  });

  it("does not overlay the work area across differing planes and says so", () => {
    stubCanvas();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(BYTES, { status: 200 })));
    const ring: Array<[number, number]> = [[0, 0], [10, 0], [10, 10], [0, 10]];
    render(
      <SiteMosaicViewport
        siteId="site-1"
        workAreaId="area-1"
        assetRef={assetRef}
        grid={grid}
        observedCrsDigest={crsDigest}
        observedCrsIdentifier="EPSG:7850"
        isDsm={false}
        jobs={[]}
        canRequest={false}
        requestsHref="/sites/site-1/spatial-data-requests?workAreaId=area-1"
        workAreaRing={ring}
        workAreaCrs="EPSG:4326"
      />,
    );

    expect(screen.getByText("범위 도식 · 사진 아님")).toBeTruthy();
    expect(screen.getByText(/작업구역 경계를 겹쳐 표시하지 않았습니다/)).toBeTruthy();
    expect(screen.getByText(/위치 기준이 달라/)).toBeTruthy();
    expect(screen.queryByText(/실선은 작업구역 경계이며, 점선은 파일 전체 범위입니다/)).toBeNull();
    // File extent itself is still drawn from the measured transform.
    expect(screen.getByText("0 – 1022")).toBeTruthy();
  });
});
