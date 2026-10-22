/** @vitest-environment jsdom */
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("geotiff", () => ({
  fromArrayBuffer: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { SiteMosaicAbsentDiagram } from "@/app/sites/[siteId]/SiteMosaicAbsentDiagram";
import { SiteMosaicViewport } from "@/app/sites/[siteId]/SiteMosaicViewport";
import type { PreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";

const assetRef = `ksa-v1-${"b".repeat(64)}`;
const otherRef = `ksa-v1-${"d".repeat(64)}`;
const crsDigest = `sha256:${"c".repeat(64)}`;
const grid = { transform: [10, 0, 100, 0, -10, 500], width: 40, height: 30 };
const BYTES = new Uint8Array(512 * 512 * 3).fill(7);
const digestOf = (bytes: Uint8Array): string => `sha256:${bytesToHex(sha256(bytes))}`;

function baseJob(overrides: Partial<PreparedWindowJob>): PreparedWindowJob {
  return {
    jobId: "sdj-v1-00000000-0000-0000-0000-000000000021",
    assetRef,
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    createdAt: "2026-10-21T00:00:00Z",
    receipt: null,
    ...overrides,
  };
}

function readableJob(): PreparedWindowJob {
  return baseJob({
    jobId: "sdj-v1-00000000-0000-0000-0000-000000000011",
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    receipt: {
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000011",
      receiptDigest: null,
      artifactKind: "ortho",
      outputSizeBytes: BYTES.byteLength,
      outputSha256: digestOf(BYTES),
      requestedBounds: [100, 200, 500, 500],
      actualBounds: [100, 200, 500, 500],
      pixelWindow: [0, 40, 0, 30],
      width: 40,
      height: 30,
      observedCrsIdentifier: "EPSG:5186",
      observedCrsDigest: crsDigest,
      accuracyAssessed: false,
      attribution: "attr",
      modificationNotice: "mod",
      limitations: [],
      preparedAt: "2026-10-21T00:00:00Z",
    },
  });
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

function renderMosaic(jobs: PreparedWindowJob[], canRequest = true) {
  return render(
    <SiteMosaicViewport
      siteId="site-1"
      workAreaId="area-1"
      assetRef={assetRef}
      grid={grid}
      observedCrsDigest={crsDigest}
      observedCrsIdentifier="EPSG:5186"
      isDsm={false}
      jobs={jobs}
      canRequest={canRequest}
      requestsHref="/sites/site-1/spatial-data-requests?workAreaId=area-1"
      workAreaRing={[[100, 200], [500, 200], [500, 500], [100, 500]]}
      workAreaCrs="EPSG:5186"
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("mosaic absent-pixel state from current jobs", () => {
  it("names retention expiry for this observation without claiming other artifacts expired", () => {
    stubCanvas();
    const fetchMock = vi.fn(async () => new Response(BYTES, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    renderMosaic([
      baseJob({ availability: "RETENTION_EXPIRED", executionState: "EXPIRED" }),
      // Another artifact stays available — the copy must not claim it expired.
      { ...readableJob(), assetRef: otherRef, jobId: "sdj-v1-00000000-0000-0000-0000-000000000099" },
    ]);

    expect(screen.getByText(/미리보기 보관 기간이 끝났습니다/)).toBeTruthy();
    // 범위 도식은 닫힌 펼침 뒤에만 둔다 — 사진 행세를 하지 않는다.
    expect(screen.getByText("자료 범위 보기").closest("details")?.open).toBe(false);
    expect(screen.getByText("범위 도식 · 사진 아님")).toBeTruthy();
    // Scoped to this observation: no blanket claim about every artifact.
    expect(screen.queryByText(/모든 자료/)).toBeNull();
    // No automatic writes or reads without prepared pixels.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not call an execution deadline retention expiry", () => {
    stubCanvas();
    vi.stubGlobal("fetch", vi.fn());
    renderMosaic([baseJob({ executionState: "EXPIRED", availability: "NOT_READY" })]);
    expect(screen.getByText(/기한을 넘겼습니다/)).toBeTruthy();
    expect(screen.queryByText(/보관 기간이 끝났습니다/)).toBeNull();
  });

  it("describes a cancellation as cancellation rather than failure", () => {
    stubCanvas();
    vi.stubGlobal("fetch", vi.fn());
    renderMosaic([baseJob({ executionState: "CANCELED", availability: "NOT_READY" })]);
    expect(screen.getByText(/표시 준비 요청이 취소됐습니다/)).toBeTruthy();
    expect(screen.queryByText(/준비 요청이 실패했습니다/)).toBeNull();
  });

  it("keeps file extents separate from the combined display bounds", () => {
    render(<SiteMosaicAbsentDiagram fileRing={[[100,200],[500,200],[500,500],[100,500]]}
      workAreaRing={[[0,0],[1000,0],[1000,1000],[0,1000]]} overlaid overlayNote={null}
      crsLabel="EPSG:5186" planeUnit="meters" filePixelSize={{width:40,height:30}} fileExtentLabel={null} />);
    expect(screen.getByText("100 – 500")).toBeTruthy();
    expect(screen.getByText("200 – 500")).toBeTruthy();
    expect(screen.queryByText("0 – 1,000")).toBeNull();
    expect(screen.getByText("좌표·검사 격자 정보").closest("details")?.open).toBe(false);
  });

  it("keeps pending windows on the canvas path instead of the expired copy", () => {
    stubCanvas();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(BYTES, { status: 200 })));
    renderMosaic([baseJob({ executionState: "QUEUED", availability: "NOT_READY" })]);

    expect(screen.queryByText(/보관 기간이 끝났습니다/)).toBeNull();
    expect(screen.queryByText("범위 도식 · 사진 아님")).toBeNull();
    expect(screen.getByRole("group", { name: /직접 끌어서 보고/ })).toBeTruthy();
  });

  it("keeps unavailable distinct from expired and empty", () => {
    stubCanvas();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(BYTES, { status: 200 })));
    renderMosaic([baseJob({ executionState: "COMPLETED", availability: "UNAVAILABLE" })]);

    expect(screen.getByText(/준비된 출력 상태를 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByText(/보관 기간이 끝났습니다/)).toBeNull();
    expect(screen.getByText("범위 도식 · 사진 아님")).toBeTruthy();
  });

  it("draws the actual measured extent, not a guessed box", () => {
    stubCanvas();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(BYTES, { status: 200 })));
    renderMosaic([]);

    // Grid transform [10,0,100,0,-10,500] 40×30 → bounds [100,200,500,500].
    expect(screen.getByText("100 – 500")).toBeTruthy();
    expect(screen.getByText("200 – 500")).toBeTruthy();
    expect(screen.getByText(/40 × 30 네이티브 픽셀/)).toBeTruthy();
  });

  it("prefers readable pixels and issues no writes on entry", async () => {
    stubCanvas();
    const posts: string[] = [];
    const gets: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") posts.push(String(url));
      else gets.push(String(url));
      return new Response(BYTES, { status: 200 });
    }));
    renderMosaic([readableJob()]);

    expect(screen.getByRole("img", { name: /이어 보기/ })).toBeTruthy();
    expect(screen.queryByText("범위 도식 · 사진 아님")).toBeNull();
    await vi.waitFor(() => expect(gets.length).toBeGreaterThan(0));
    expect(posts).toHaveLength(0);
    for (const url of gets) expect(url.startsWith("/api/")).toBe(true);
  });
});
