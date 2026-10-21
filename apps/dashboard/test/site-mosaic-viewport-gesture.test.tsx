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

function stubReads(posts: string[]) {
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
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "POST") posts.push(url);
    return new Response(BYTES, { status: 200, headers: { "content-type": "image/tiff" } });
  }));
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fromArrayBufferMock.mockReset();
});

function renderMosaic() {
  return render(
    <SiteMosaicViewport
      siteId="site-1"
      workAreaId="area-1"
      assetRef={assetRef}
      grid={grid}
      observedCrsDigest={crsDigest}
      observedCrsIdentifier="EPSG:7850"
      isDsm={false}
      jobs={[readableJob()]}
      canRequest
      requestsHref="/sites/site-1/spatial-data-requests?workAreaId=area-1"
    />,
  );
}

describe("mosaic display gestures", () => {
  it("moves and zooms by keyboard through the same rule without any writes", async () => {
    stubCanvas();
    const posts: string[] = [];
    stubReads(posts);
    renderMosaic();

    const view = screen.getByRole("group", { name: /마우스로 끌거나/ });
    expect(view.getAttribute("tabindex")).toBe("0");
    view.focus();
    // 전체 범위에서는 이동이 경계에 막혀 같은 규칙의 안내가 나온다.
    fireEvent.keyDown(view, { key: "ArrowRight" });
    expect(await screen.findByText(/격자 끝이라 더 이상 옮길 수 없습니다/)).toBeTruthy();
    expect(posts).toHaveLength(0);
    // 확대·전체 보기는 같은 줌 규칙을 탄다.
    fireEvent.keyDown(view, { key: "+" });
    fireEvent.keyDown(view, { key: "Home" });
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(posts).toHaveLength(0);
    // 지원하지 않는 키는 페이지에 그대로 둔다.
    fireEvent.keyDown(view, { key: "Enter" });
    expect(posts).toHaveLength(0);
  });

  it("commits a mouse drag on pointerup with a bounded preview, never a per-move request", async () => {
    stubCanvas();
    const posts: string[] = [];
    stubReads(posts);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 400, height: 300, x: 0, y: 0, top: 0, left: 0, right: 400, bottom: 300, toJSON: () => {},
    } as unknown as DOMRect);
    renderMosaic();

    const view = screen.getByRole("group", { name: /마우스로 끌거나/ });
    // jsdom은 pointer init 값을 싣지 않으므로 버블링되는 합성 이벤트에 직접 싣는다.
    const pointer = (type: string, x: number, y: number) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.assign(event, { pointerType: "mouse", button: 0, clientX: x, clientY: y, pointerId: 1 });
      view.dispatchEvent(event);
    };
    pointer("pointerdown", 200, 150);
    pointer("pointermove", 260, 150);
    // 이동 중에는 새 네트워크 요청이 나가지 않는다 — CSS 미리보기만 둔다.
    expect(posts).toHaveLength(0);
    pointer("pointerup", 260, 150);
    // 전체 범위 드래그는 같은 클램프 규칙의 안내로 닫힌다.
    expect(await screen.findByText(/격자 끝이라 더 이상 옮길 수 없습니다/)).toBeTruthy();
    expect(posts).toHaveLength(0);
  });

  it("ignores touch drags so vertical page scroll is preserved", async () => {
    stubCanvas();
    const posts: string[] = [];
    stubReads(posts);
    renderMosaic();

    const view = screen.getByRole("group", { name: /마우스로 끌거나/ });
    fireEvent.pointerDown(view, { pointerType: "touch", button: 0, clientX: 200, clientY: 150 });
    fireEvent.pointerMove(view, { pointerType: "touch", button: 0, clientX: 200, clientY: 50 });
    fireEvent.pointerUp(view, { pointerType: "touch", button: 0, clientX: 200, clientY: 50 });
    expect(screen.queryByText(/격자 끝이라/)).toBeNull();
    expect(posts).toHaveLength(0);
  });

  it("zooms by wheel only with focus or Ctrl and never traps a plain scroll", async () => {
    stubCanvas();
    const posts: string[] = [];
    stubReads(posts);
    renderMosaic();

    const view = screen.getByRole("group", { name: /마우스로 끌거나/ });
    // 포커스 없는 일반 휠은 페이지 스크롤로 둔다 — preventDefault 없음, 상태 변화 없음.
    fireEvent.wheel(view, { deltaY: -100 });
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(posts).toHaveLength(0);
    // 포커스된 휠은 같은 줌 규칙을 탄다.
    view.focus();
    fireEvent.wheel(view, { deltaY: -100 });
    fireEvent.wheel(view, { deltaY: -100 });
    // Home으로 전체 보기에 복귀한다.
    fireEvent.keyDown(view, { key: "Home" });
    expect(screen.getByRole("img", { name: /이어 보기 1022 × 915 픽셀/ })).toBeTruthy();
    expect(posts).toHaveLength(0);
  });

  it("names missing windows as display-preparation-needed without auto-preparing them", async () => {
    stubCanvas();
    const posts: string[] = [];
    stubReads(posts);
    renderMosaic();

    // 읽을 수 있는 1창을 뺀 나머지는 '표시 준비 필요'로 둔다 — 자동 준비 없음.
    expect((await screen.findAllByText("표시 준비 필요")).length).toBeGreaterThan(0);
    expect(screen.queryByText("이어 보기 채우기")).toBeNull();
    expect(posts).toHaveLength(0);
  });
});
