/** @vitest-environment jsdom */
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("geotiff", () => ({
  fromArrayBuffer: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { fromArrayBuffer } from "geotiff";
import { SiteMosaicViewport } from "@/app/sites/[siteId]/SiteMosaicViewport";
import { resolveMosaicCover } from "@/lib/spatial-display-mosaic";
import type { PreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";

const fromArrayBufferMock = fromArrayBuffer as unknown as ReturnType<typeof vi.fn>;
const assetRef = `ksa-v1-${"b".repeat(64)}`;
const crsDigest = `sha256:${"c".repeat(64)}`;

/** 작은 합성 격자 — 1022×915, 1 m, 북위. 값은 테스트 고정값이며 제품 자료가 아니다. */
const grid = { transform: [1, 0, 0, 0, -1, 915], width: 1022, height: 915 };

function coverPlans() {
  const cover = resolveMosaicCover(grid, [0, 0, 1022, 915]);
  if (!cover.ok) throw new Error("cover must resolve");
  return cover.windows;
}

function windowBytes(width: number, height: number, seed: number): Uint8Array<ArrayBuffer> {
  return new Uint8Array(new ArrayBuffer(width * height * 3)).fill(seed);
}

/** 영수증과 같은 바이트를 그대로 내놓는다 — SHA·크기 대조가 성립해야 그린다. */
const JOB_BYTES = new Map<string, Uint8Array<ArrayBuffer>>();

function jobForWindow(plan: { pixelWindow: [number, number, number, number] }, index: number): PreparedWindowJob {
  const [c0, c1, r0, r1] = plan.pixelWindow;
  const width = c1 - c0;
  const height = r1 - r0;
  const bytes = windowBytes(width, height, 7 + index);
  const jobId = `sdj-v1-00000000-0000-0000-0000-0000000000${String(index + 1).padStart(2, "0")}`;
  JOB_BYTES.set(jobId, bytes);
  return {
    jobId,
    assetRef,
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    createdAt: "2026-10-21T00:00:00Z",
    receipt: {
      jobId,
      receiptDigest: null,
      artifactKind: "ortho",
      outputSizeBytes: bytes.byteLength,
      outputSha256: `sha256:${bytesToHex(sha256(bytes))}`,
      requestedBounds: [c0, 915 - r1, c1, 915 - r0],
      actualBounds: [c0, 915 - r1, c1, 915 - r0],
      pixelWindow: plan.pixelWindow,
      width,
      height,
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

function stubCanvas(putImageData: ReturnType<typeof vi.fn>) {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    putImageData,
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
  JOB_BYTES.clear();
});

function bytesByJobId(): Map<string, Uint8Array<ArrayBuffer>> {
  return JOB_BYTES;
}

function stubReads(jobs: PreparedWindowJob[], posts: string[], gets: string[]) {
  const byJobId = bytesByJobId();
  const dimsByLength = new Map<number, [number, number]>();
  for (const job of jobs) {
    const receipt = job.receipt;
    if (receipt) dimsByLength.set(receipt.outputSizeBytes, [receipt.width, receipt.height]);
  }
  fromArrayBufferMock.mockImplementation(async (buffer: ArrayBuffer) => {
    const dims = dimsByLength.get(buffer.byteLength) ?? [512, 512];
    const [width, height] = dims;
    const out = windowBytes(width, height, 7);
    return {
      getImageCount: async () => 1,
      getImage: async () => ({
        getWidth: () => width,
        getHeight: () => height,
        getSamplesPerPixel: () => 3,
        getBitsPerSample: () => 8,
        getGDALNoData: () => null,
        readRasters: async () => out,
      }),
    };
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "POST") {
      posts.push(url);
      return new Response("{}", { status: 200 });
    }
    gets.push(url);
    const jobId = url.match(/spatial-data-requests\/([^/]+)\/file/)?.[1] ?? "";
    const bytes = byJobId.get(jobId) ?? new Uint8Array(0);
    return new Response(bytes, { status: 200, headers: { "content-type": "image/tiff" } });
  }));
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

/** jsdom은 pointer init 값을 싣지 않으므로 버블링되는 합성 이벤트에 직접 싣는다. */
function pointerOn(element: Element, type: string, x: number, y: number) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(event, { pointerType: "mouse", button: 0, clientX: x, clientY: y, pointerId: 1 });
  element.dispatchEvent(event);
}

describe("mosaic display view keeps verified buffers", () => {
  it("paints all prepared windows once, then zooms/pans/resets without new reads or writes", async () => {
    const putImageData = vi.fn();
    stubCanvas(putImageData);
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    expect(jobs.length).toBeGreaterThanOrEqual(4);
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);

    // 준비된 창 수만큼만 읽는다 — 진입·표시 제스처는 읽기를 만들지 않는다.
    await waitFor(() => expect(gets).toHaveLength(jobs.length));
    for (const url of gets) expect(url.startsWith("/api/")).toBe(true);
    expect(posts).toHaveLength(0);
    // 원본 버퍼 라벨은 소스 그대로 둔다.
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(screen.getByText(/그린 창 4 \/ 전체 4/)).toBeTruthy();
    expect(screen.queryByText("표시 준비 필요")).toBeNull();
    const painted = putImageData.mock.calls.length;
    expect(painted).toBeGreaterThanOrEqual(jobs.length);

    const view = screen.getByRole("group", { name: /마우스로 끌거나/ });
    view.focus();
    // 확대: 표시만 200%가 되고, 바이트를 다시 읽지도 새로 그리지도 않는다.
    fireEvent.keyDown(view, { key: "+" });
    expect(screen.getByText(/표시 확대 200%/)).toBeTruthy();
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    expect(putImageData.mock.calls.length).toBe(painted);
    // 이동: 같은 버퍼 안에서만 움직이고, 요청은 그대로 없다.
    fireEvent.keyDown(view, { key: "ArrowRight" });
    expect(screen.getByText(/이동한 화면/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    expect(putImageData.mock.calls.length).toBe(painted);
    // 전체 보기: 표시만 원점으로 돌아간다.
    fireEvent.keyDown(view, { key: "Home" });
    expect(screen.queryByText(/표시 확대/)).toBeNull();
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    expect(putImageData.mock.calls.length).toBe(painted);
  });

  it("clamps at the source edge with the same rule for buttons, keys, drag and wheel", async () => {
    const putImageData = vi.fn();
    stubCanvas(putImageData);
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 400, height: 300, x: 0, y: 0, top: 0, left: 0, right: 400, bottom: 300, toJSON: () => {},
    } as unknown as DOMRect);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const view = screen.getByRole("group", { name: /마우스로 끌거나/ });
    view.focus();
    // 전체 보기에서는 이동이 성립하지 않는다 — 같은 격자 끝 안내다.
    fireEvent.keyDown(view, { key: "ArrowRight" });
    expect(await screen.findByText(/격자 끝이라 더 이상 옮길 수 없습니다/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    // 확대 한계에서도 버퍼를 바꾸지 않는다.
    fireEvent.keyDown(view, { key: "+" });
    fireEvent.keyDown(view, { key: "+" });
    fireEvent.keyDown(view, { key: "+" });
    expect(screen.getByText(/표시 확대 한계입니다/)).toBeTruthy();
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    // 드래그는 같은 클램프 규칙을 탄다 — 새 요청 없이 안내로 닫힌다.
    fireEvent.keyDown(view, { key: "Home" });
    pointerOn(view, "pointerdown", 200, 150);
    pointerOn(view, "pointermove", 260, 150);
    pointerOn(view, "pointerup", 260, 150);
    expect(await screen.findByText(/격자 끝이라 더 이상 옮길 수 없습니다/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    // 포커스 없는 일반 휠은 페이지 스크롤로 둔다.
    (document.activeElement as HTMLElement | null)?.blur?.();
    fireEvent.wheel(view, { deltaY: -100 });
    expect(screen.queryByText(/표시 확대/)).toBeNull();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    // 포커스된 휠은 같은 표시 규칙을 탄다.
    view.focus();
    fireEvent.wheel(view, { deltaY: -100 });
    expect(screen.getByText(/표시 확대 200%/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("ignores touch drags so vertical page scroll is preserved", async () => {
    const putImageData = vi.fn();
    stubCanvas(putImageData);
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const view = screen.getByRole("group", { name: /마우스로 끌거나/ });
    const event = new Event("pointerdown", { bubbles: true, cancelable: true });
    Object.assign(event, { pointerType: "touch", button: 0, clientX: 200, clientY: 150, pointerId: 2 });
    view.dispatchEvent(event);
    expect(screen.queryByText(/격자 끝이라/)).toBeNull();
    expect(screen.queryByText(/표시 확대/)).toBeNull();
    expect(posts).toHaveLength(0);
  });

  it("names missing windows as display-preparation-needed without auto-preparing them", async () => {
    const putImageData = vi.fn();
    stubCanvas(putImageData);
    const first = coverPlans()[0]!;
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads([jobForWindow(first, 0)], posts, gets);
    renderMosaic([jobForWindow(first, 0)]);

    // 읽을 수 없는 창은 '표시 준비 필요'로 둔다 — 자동 준비 없음.
    expect((await screen.findAllByText("표시 준비 필요")).length).toBeGreaterThan(0);
    expect(posts).toHaveLength(0);
  });
});
