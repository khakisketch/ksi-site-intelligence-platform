/** @vitest-environment jsdom */
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("geotiff", () => ({
  fromArrayBuffer: vi.fn(),
}));

import { fromArrayBuffer } from "geotiff";
import { SpatialDataReceiptPreview } from "@/app/sites/[siteId]/spatial-data-requests/SpatialDataReceiptPreview";

const fromArrayBufferMock = fromArrayBuffer as unknown as ReturnType<typeof vi.fn>;

const requestId = "sdj-v1-12345678-1234-1234-1234-123456789abc";
const digestOf = (bytes: Uint8Array): string => `sha256:${bytesToHex(sha256(bytes))}`;

function receiptFor(bytes: Uint8Array, overrides: Record<string, unknown> = {}) {
  return {
    jobId: requestId,
    receiptDigest: `sha256:${"a".repeat(64)}`,
    artifactKind: "ortho",
    outputSizeBytes: bytes.byteLength,
    outputSha256: digestOf(bytes),
    requestedBounds: [500000, 7100000, 501000, 7101000],
    actualBounds: [500010, 7100010, 500990, 7100990],
    pixelWindow: [20, 30, 2, 2],
    width: 2,
    height: 2,
    observedCrsIdentifier: "EPSG:7850",
    observedCrsDigest: `sha256:${"c".repeat(64)}`,
    accuracyAssessed: false,
    attribution: "KSI prepared from the registered source.",
    modificationNotice: "Windowed crop; no reprojection.",
    limitations: ["Not an accuracy assessment."],
    preparedAt: "2026-10-14T10:40:00Z",
    ...overrides,
  } as Parameters<typeof SpatialDataReceiptPreview>[0]["receipt"];
}

function renderPreview(bytes: Uint8Array | null, overrides: Record<string, unknown> = {}) {
  const receipt = receiptFor(bytes ?? new Uint8Array([0]), overrides.receipt as Record<string, unknown> | undefined);
  const fileHref = "/api/sites/site-1/work-areas/area-1/spatial-data-requests/sdj-v1-12345678-1234-1234-123456789abc/file";
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit): Promise<Response> => {
    if (bytes === null) {
      await new Promise<never>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
    }
    return new Response(bytes as unknown as BodyInit, { status: 200, headers: { "content-type": "image/tiff" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <SpatialDataReceiptPreview
      siteId="site-1"
      workAreaId="area-1"
      jobId={(overrides.jobId as string) ?? requestId}
      receipt={receipt}
      fileHref={fileHref}
      gestureControls={overrides.gestureControls === true}
    />,
  );
  return { fetchMock, fileHref };
}

function stubCanvas() {
  const putImageData = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ putImageData } as unknown as CanvasRenderingContext2D);
  vi.stubGlobal("ImageData", class {
    constructor(
      public readonly data: Uint8ClampedArray,
      public readonly width: number,
      public readonly height: number,
    ) {}
  });
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

function stubGeotiffSingleBand() {
  fromArrayBufferMock.mockResolvedValue({
    getImageCount: async () => 1,
    getImage: async () => ({
      getWidth: () => 2,
      getHeight: () => 2,
      getSamplesPerPixel: () => 1,
      getBitsPerSample: () => 32,
      readRasters: async () => new Float32Array([10, 20, 30, 40]),
    }),
  });
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); fromArrayBufferMock.mockReset(); });

describe("spatial data receipt preview", () => {
  it("fits the whole prepared crop before local zoom and keeps one reset control in the frame", async () => {
    const bytes = new Uint8Array([7, 7, 7, 7]);
    const paint = stubCanvas();
    stubGeotiffRgb();
    const { fetchMock } = renderPreview(bytes, { gestureControls: true });
    fireEvent.click(screen.getByRole("button", { name: "미리보기 불러오기" }));
    await screen.findByText(/실제 픽셀 색상을 그대로 표시합니다/);
    const frame = screen.getByRole("group", { name: /^부분 출력 2 × 2 픽셀/ });
    const canvas = frame.querySelector("canvas")!;
    expect(canvas.classList.contains("w-full")).toBe(true);
    await waitFor(() => {
      expect(canvas.width).toBe(2);
      expect(canvas.height).toBe(2);
      expect(paint).toHaveBeenCalled();
    });
    // 7버튼 띠는 없다 — 모서리의 전체 보기 하나만 둔다.
    const reset = screen.getByRole("button", { name: "전체 보기" });
    expect(reset.closest("[role=group]")).toBe(frame);
    expect(reset.className).toContain("h-11");
    expect(screen.queryByRole("button", { name: "확대" })).toBeNull();
    expect(screen.queryByRole("button", { name: "축소" })).toBeNull();
    const painted = paint.mock.calls.length;
    // 프레임에 직접 포커스 없이도 휠로 확대된다.
    const content = canvas.parentElement!;
    Object.defineProperty(content, "offsetWidth", { value: 400, configurable: true });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 400, height: 300, x: 0, y: 0, top: 0, left: 0, right: 400, bottom: 300, toJSON: () => {},
    } as unknown as DOMRect);
    fireEvent.wheel(frame, { deltaY: -100, clientX: 10, clientY: 10 });
    await waitFor(() => expect(content.style.transform).toContain("scale(1.4"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(paint).toHaveBeenCalledTimes(painted);
    fireEvent.click(reset);
    expect(content.style.transform).toContain("scale(1)");
  });

  it("renders verified RGB pixels without reinterpretation claims", async () => {
    const bytes = new Uint8Array([7, 7, 7, 7]);
    stubCanvas();
    stubGeotiffRgb();
    renderPreview(bytes);

    fireEvent.click(screen.getByRole("button", { name: "미리보기 불러오기" }));
    await screen.findByText(/실제 픽셀 색상을 그대로 표시합니다/);
    expect(screen.getByText(/WGS84 변환·지도 타일·보정을 적용하지 않았습니다/)).toBeTruthy();
    expect(screen.getByText(/정량 계산을 하지 않습니다/)).toBeTruthy();
    expect(screen.queryByText(/측정값/)).toBeNull();
  });

  it("renders single-band output with an honest relative-shading legend, not a measurement", async () => {
    const bytes = new Uint8Array([7, 7, 7, 7]);
    stubCanvas();
    stubGeotiffSingleBand();
    renderPreview(bytes);

    fireEvent.click(screen.getByRole("button", { name: "미리보기 불러오기" }));
    await screen.findByText(/단일 밴드를 명암으로 표시합니다/);
    expect(screen.getByText(/이 미리보기는 수직 기준 적합성·높이 정확도를 판정하지 않습니다/)).toBeTruthy();
    expect(screen.getByLabelText("상대 음영 범례")).toBeTruthy();
  });

  it("blocks the preview on a hash mismatch while keeping the ordinary download available", async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    stubCanvas();
    stubGeotiffRgb();
    const { fetchMock } = renderPreview(bytes, {
      receipt: { outputSha256: `sha256:${"0".repeat(64)}` },
    });

    fireEvent.click(screen.getByRole("button", { name: "미리보기 불러오기" }));
    await screen.findByText(/Core 준비 기록\(출력 크기·파일 확인값\)과 달라/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fromArrayBufferMock).not.toHaveBeenCalled();
  });

  it("maps a revoked grant to a truthful message without inventing bytes", async () => {
    stubCanvas();
    const revoked = new Response(JSON.stringify({ code: "ACCESS_REVOKED", message: "revoked" }), {
      status: 403,
      headers: { "content-type": "application/json" },
    });
    vi.stubGlobal("fetch", vi.fn(async () => revoked));
    render(
      <SpatialDataReceiptPreview
        siteId="site-1"
        workAreaId="area-1"
        jobId={requestId}
        receipt={receiptFor(new Uint8Array([1]))}
        fileHref="/api/sites/site-1/work-areas/area-1/spatial-data-requests/x/file"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "미리보기 불러오기" }));
    await screen.findByText(/사용 권리가 회수되어 미리보기를 표시하지 않습니다/);
  });

  it("keeps an undecodable output as a persistent error with the download path intact", async () => {
    const bytes = new Uint8Array([5, 5, 5, 5]);
    stubCanvas();
    fromArrayBufferMock.mockRejectedValue(new Error("not a tiff"));
    renderPreview(bytes);

    fireEvent.click(screen.getByRole("button", { name: "미리보기 불러오기" }));
    await screen.findByText(/브라우저에서 해석하지 못했습니다/);
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
  });

  it("refuses to preview when the receipt identity does not match the open request", async () => {
    const fetchMock = vi.fn(async () => new Response(new Uint8Array([1]) as unknown as BodyInit, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <SpatialDataReceiptPreview
        siteId="site-1"
        workAreaId="area-1"
        jobId="sdj-v1-99999999-9999-9999-9999-999999999999"
        receipt={receiptFor(new Uint8Array([1]))}
        fileHref="/api/sites/site-1/work-areas/area-1/spatial-data-requests/x/file"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "미리보기 불러오기" }));
    await screen.findByText(/요청 식별자가 현재 요청과 달라/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("cancels an in-flight load and releases it on unmount", async () => {
    stubCanvas();
    stubGeotiffRgb();
    const { fetchMock } = renderPreview(null);

    fireEvent.click(screen.getByRole("button", { name: "미리보기 불러오기" }));
    await screen.findByText(/자료 읽는 중/);
    fireEvent.click(screen.getByRole("button", { name: "불러오기 취소" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "미리보기 불러오기" })).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    cleanup();
  });
});
