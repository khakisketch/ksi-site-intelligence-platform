/** @vitest-environment jsdom */
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const JOB_BYTES = new Map<string, Uint8Array<ArrayBuffer>>();

function windowBytes(width: number, height: number, seed: number): Uint8Array<ArrayBuffer> {
  return new Uint8Array(new ArrayBuffer(width * height * 3)).fill(seed);
}

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

function coverPlans() {
  const cover = resolveMosaicCover(grid, [0, 0, 1022, 915]);
  if (!cover.ok) throw new Error("cover must resolve");
  return cover.windows;
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

function stubReads(jobs: PreparedWindowJob[], posts: string[], gets: string[]) {
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
    return new Response(JOB_BYTES.get(jobId) ?? new Uint8Array(0), { status: 200, headers: { "content-type": "image/tiff" } });
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

/** jsdom은 pointer init 값을 싣지 않으므로 버블링되는 합성 이벤트에 직접 싣는다.
 * React 상태 반영을 위해 act로 감싼다. */
function pointerOn(element: Element, type: string, x: number, y: number, extra: Record<string, unknown> = {}) {
  act(() => {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.assign(event, { pointerType: "mouse", button: 0, clientX: x, clientY: y, pointerId: 1, ...extra });
    element.dispatchEvent(event);
  });
}

/** 보이는 그림의 배치 크기를 고정한다 — jsdom offsetWidth는 0이다. */
function mockFittedSize(frame: Element, width: number, height: number) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    width, height, x: 0, y: 0, top: 0, left: 0, right: width, bottom: height, toJSON: () => {},
  } as unknown as DOMRect);
  const content = frame.firstElementChild as HTMLElement;
  Object.defineProperty(content, "offsetWidth", { value: width, configurable: true });
  Object.defineProperty(content, "offsetHeight", { value: height, configurable: true });
  return content;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fromArrayBufferMock.mockReset();
  JOB_BYTES.clear();
});

describe("mosaic direct manipulation keeps verified buffers", () => {
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
    // 7버튼 띠는 없다 — 모서리의 전체 보기 하나만 둔다.
    expect(screen.queryByRole("button", { name: "확대" })).toBeNull();
    expect(screen.queryByRole("button", { name: "축소" })).toBeNull();
    const reset = screen.getByRole("button", { name: "전체 보기" });
    expect(reset.className).toContain("h-11");

    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    view.focus();
    // 확대: 표시만 200%가 되고, 바이트를 다시 읽지도 새로 그리지 않는다.
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
    fireEvent.click(reset);
    expect(screen.queryByText(/표시 확대/)).toBeNull();
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    expect(putImageData.mock.calls.length).toBe(painted);
  });

  it("stops at the visible edge with a note instead of shrinking the buffer", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    mockFittedSize(view, 400, 300);
    view.focus();
    // 전체 보기에서도 같은 방향으로 계속 밀면 보이는 끝에서 멈춘다.
    for (let i = 0; i < 10; i += 1) fireEvent.keyDown(view, { key: "ArrowRight" });
    expect(screen.getByText(/표시 범위의 끝입니다/)).toBeTruthy();
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("moves the picture 1:1 with the pointer during the drag, before mouseup", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    const content = mockFittedSize(view, 400, 300);
    // 바깥 프레임이 1134px이어도 보이는 그림 400px 기준으로 1:1로 간다.
    pointerOn(view, "pointerdown", 200, 150);
    pointerOn(view, "pointermove", 260, 150);
    // mouseup 전 — 이동 중에 이미 같은 비율로 표시된다.
    const during = Number.parseFloat(/translate\(([^%]+)%/.exec(content.style.transform)?.[1] ?? "NaN");
    expect(during).toBeCloseTo(15, 5);
    expect(content.style.transform).toContain("scale(1)");
    expect(screen.getByText(/이동한 화면/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    pointerOn(view, "pointerup", 260, 150);
    expect(content.style.transform).toContain("scale(1)");
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("zooms an unfocused wheel with smooth steps and lets edge wheels scroll past", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    mockFittedSize(view, 400, 300);
    // 포커스 없이 휠만으로 확대된다 — 예전의 선택·Ctrl 전제와 다르다.
    // 한 노치는 반 스텝이다(2배 점프·120ms 드롭 없음).
    expect(document.activeElement).not.toBe(view);
    const takenOver = fireEvent.wheel(view, { deltaY: -100, clientX: 40, clientY: 150 });
    expect(takenOver).toBe(false);
    expect(screen.getByText(/표시 확대 141%/)).toBeTruthy();
    fireEvent.wheel(view, { deltaY: -100, clientX: 40, clientY: 150 });
    expect(screen.getByText(/표시 확대 200%/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    // 한계에 닿으면 막지 않고 넘긴다(페이지 스크롤 가로채기 금지).
    fireEvent.wheel(view, { deltaY: -100, clientX: 40, clientY: 150 });
    fireEvent.wheel(view, { deltaY: -100, clientX: 40, clientY: 150 });
    expect(screen.getByText(/표시 확대 400%/)).toBeTruthy();
    const passedThrough = fireEvent.wheel(view, { deltaY: -100, clientX: 40, clientY: 150 });
    expect(passedThrough).toBe(true);
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("zooms on double click at the pointer without any writes", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    mockFittedSize(view, 400, 300);
    fireEvent.doubleClick(view, { clientX: 100, clientY: 75 });
    expect(screen.getByText(/표시 확대 200%/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("zooms on a real touch double tap at the tapped point", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    mockFittedSize(view, 400, 300);
    const tap = (x: number, y: number, id: number) => {
      pointerOn(view, "pointerdown", x, y, { pointerType: "touch", pointerId: id });
      pointerOn(view, "pointerup", x, y, { pointerType: "touch", pointerId: id });
    };
    tap(200, 150, 21);
    // 한 번만 두드리면 확대하지 않는다.
    expect(screen.queryByText(/표시 확대/)).toBeNull();
    tap(202, 152, 22);
    expect(screen.getByText(/표시 확대 200%/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("leaves the reset button clickable and never traps its pointer", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const reset = screen.getByRole("button", { name: "전체 보기" });
    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    const capture = vi.fn();
    Object.defineProperty(view, "setPointerCapture", { configurable: true, value: capture });
    fireEvent.keyDown(view, { key: "+" });
    expect(screen.getByText(/표시 확대 200%/)).toBeTruthy();
    const icon = reset.querySelector("path")!;
    // SVG 자식에 닿은 포인터도 단추 동작이다 — 프레임 캡처가 없어야 한다.
    act(() => {
      const down = new Event("pointerdown", { bubbles: true, cancelable: true });
      Object.assign(down, { pointerType: "mouse", button: 0, clientX: 10, clientY: 10, pointerId: 9 });
      icon.dispatchEvent(down);
      const up = new Event("pointerup", { bubbles: true, cancelable: true });
      Object.assign(up, { pointerType: "mouse", button: 0, clientX: 10, clientY: 10, pointerId: 9 });
      icon.dispatchEvent(up);
    });
    expect(capture).not.toHaveBeenCalled();
    fireEvent.click(icon);
    expect(screen.queryByText(/표시 확대/)).toBeNull();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("supports one-finger pan and two-finger pinch with cleanup on cancel", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    const content = mockFittedSize(view, 400, 300);
    // 한 손가락 이동.
    pointerOn(view, "pointerdown", 200, 150, { pointerType: "touch", pointerId: 11 });
    pointerOn(view, "pointermove", 240, 150, { pointerType: "touch", pointerId: 11 });
    const movedTx = Number.parseFloat(/translate\(([^%]+)%/.exec(content.style.transform)?.[1] ?? "NaN");
    expect(movedTx).toBeCloseTo(10, 5);
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    pointerOn(view, "pointerup", 240, 150, { pointerType: "touch", pointerId: 11 });
    // 두 손가락 핀치: 간격이 두 배가 되면 같은 비율로 확대된다.
    pointerOn(view, "pointerdown", 200, 150, { pointerType: "touch", pointerId: 11 });
    pointerOn(view, "pointerdown", 200, 250, { pointerType: "touch", pointerId: 12 });
    pointerOn(view, "pointermove", 200, 350, { pointerType: "touch", pointerId: 12 });
    expect(screen.getByText(/표시 확대 200%/)).toBeTruthy();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
    // 취소는 조용히 끝나고 추가 요청을 만들지 않는다.
    pointerOn(view, "pointercancel", 200, 350, { pointerType: "touch", pointerId: 12 });
    pointerOn(view, "pointercancel", 240, 150, { pointerType: "touch", pointerId: 11 });
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("does not trap page wheel outside the picture and leaves typing alone", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    // 그림 밖의 휠은 페이지 스크롤로 둔다.
    fireEvent.wheel(document.body, { deltaY: -300 });
    expect(screen.queryByText(/표시 확대/)).toBeNull();
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("keeps failed windows honest and gesture-safe without new reads", async () => {
    stubCanvas(vi.fn());
    const jobs = coverPlans().map((plan, index) => jobForWindow(plan, index));
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads(jobs, posts, gets);
    // 영수증과 다른 바이트를 내놓는 한 창 — 그리지 않는다.
    const broken = jobs[0]!;
    JOB_BYTES.set(broken.jobId, windowBytes(8, 8, 1));
    renderMosaic(jobs);
    await waitFor(() => expect(gets).toHaveLength(jobs.length));

    await waitFor(() => expect(screen.getByText(/이어 보기 조건·창별 상태/).closest("details")?.textContent).toContain("받은 바이트가 Core 준비 기록과 달라 화면에 표시하지 않습니다."));
    const view = screen.getByRole("group", { name: /직접 끌어서 보고/ });
    expect(view.textContent).not.toContain("그리지 않음");
    view.focus();
    fireEvent.keyDown(view, { key: "+" });
    fireEvent.keyDown(view, { key: "ArrowRight" });
    mockFittedSize(view, 400, 300);
    fireEvent.wheel(view, { deltaY: -100 });
    expect(gets).toHaveLength(jobs.length);
    expect(posts).toHaveLength(0);
  });

  it("names missing windows as display-preparation-needed without auto-preparing them", async () => {
    stubCanvas(vi.fn());
    const first = coverPlans()[0]!;
    const posts: string[] = [];
    const gets: string[] = [];
    stubReads([jobForWindow(first, 0)], posts, gets);
    renderMosaic([jobForWindow(first, 0)]);

    // 준비되지 않은 창의 이유는 상세에만 둔다 — 지도에 문구·가짜 픽셀 없음.
    expect(screen.getByText(/이어 보기 조건·창별 상태/).closest("details")?.textContent).toContain("표시 준비 필요");
    expect(screen.getByRole("group", { name: /직접 끌어서 보고/ }).textContent).not.toContain("표시 준비 필요");
    expect(posts).toHaveLength(0);
  });
});
