/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/site-preview", () => ({
  acquirePreviewSlot: vi.fn(async () => () => {}),
}));

const decodeMock = vi.fn();
const fetchMock = vi.fn();

vi.mock("@/lib/spatial-data-preview", () => ({
  fetchVerifiedReceiptBytes: (...args: unknown[]) => fetchMock(...args),
  decodeReceiptPreview: (...args: unknown[]) => decodeMock(...args),
}));

import { acquirePreviewSlot } from "@/lib/site-preview";
import { MaterialThumb } from "@/app/sites/[siteId]/spatial-assets/MaterialThumb";
import { firstReadableWindowJob } from "@/lib/site-windowed-pixel-viewer";
import type { PreparedWindowJob } from "@/lib/site-windowed-pixel-viewer";

const acquireMock = acquirePreviewSlot as unknown as ReturnType<typeof vi.fn>;

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    jobId: "job-1",
    receiptDigest: `sha256:${"a".repeat(64)}`,
    artifactKind: "ortho",
    outputSizeBytes: 4,
    outputSha256: `sha256:${"b".repeat(64)}`,
    requestedBounds: [0, 0, 2, 2] as [number, number, number, number],
    actualBounds: [0, 0, 2, 2] as [number, number, number, number],
    pixelWindow: [0, 2, 0, 2] as [number, number, number, number],
    width: 2,
    height: 2,
    observedCrsIdentifier: "EPSG:7850",
    observedCrsDigest: `sha256:${"c".repeat(64)}`,
    accuracyAssessed: false,
    attribution: "attr",
    modificationNotice: "mod",
    limitations: [],
    preparedAt: "2026-10-14T10:40:00Z",
    ...overrides,
  } as Parameters<typeof MaterialThumb>[0]["receipt"];
}

function job(assetRef: string, overrides: Partial<PreparedWindowJob> & { jobId?: string } = {}): PreparedWindowJob {
  const { jobId = "job-1", ...rest } = overrides;
  return {
    jobId,
    assetRef,
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    createdAt: "2026-10-23T00:00:00Z",
    receipt: receipt({ jobId }) as PreparedWindowJob["receipt"],
    ...rest,
  } as PreparedWindowJob;
}

function stubCanvas() {
  const putImageData = vi.fn();
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ putImageData, drawImage } as unknown as CanvasRenderingContext2D);
  vi.stubGlobal("ImageData", class {
    constructor(
      public readonly data: Uint8ClampedArray,
      public readonly width: number,
      public readonly height: number,
    ) {}
  });
  return { putImageData, drawImage };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
  decodeMock.mockReset();
});

describe("firstReadableWindowJob", () => {
  const ref = `ksa-v1-${"a".repeat(64)}`;
  it("picks the first completed available receipt job for the exact asset", () => {
    const pending = job(ref, { jobId: "job-pending", executionState: "RUNNING" });
    const other = job(`ksa-v1-${"b".repeat(64)}`, { jobId: "job-other" });
    const readable = job(ref, { jobId: "job-readable" });
    expect(firstReadableWindowJob([pending, other, readable], ref)?.jobId).toBe("job-readable");
  });

  it("returns null when nothing is readable", () => {
    expect(firstReadableWindowJob([job(ref, { availability: "NOT_READY" })], ref)).toBeNull();
    expect(firstReadableWindowJob([], ref)).toBeNull();
  });

  it("never borrows another asset's prepared window", () => {
    expect(firstReadableWindowJob([job(`ksa-v1-${"b".repeat(64)}`)], ref)).toBeNull();
  });
});

describe("MaterialThumb", () => {
  it("renders a format glyph when no prepared window exists", () => {
    render(<MaterialThumb siteId="site-1" workAreaId="area-1" jobId={null} receipt={null} fileName="north.tif" />);
    expect(screen.getByText("TIF")).toBeDefined();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(acquireMock).not.toHaveBeenCalled();
  });

  it("fetches the exact receipt with verification and draws a downscaled canvas", async () => {
    stubCanvas();
    const bytes = new Uint8Array([7, 7, 7, 7]);
    fetchMock.mockResolvedValue(bytes);
    decodeMock.mockResolvedValue({ pixels: new Uint8ClampedArray(16), width: 2, height: 2, color: true });
    const { container } = render(
      <MaterialThumb siteId="site-1" workAreaId="area-1" jobId="job-1" receipt={receipt() as never} fileName="north.tif" />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [href, verification] = fetchMock.mock.calls[0] as [string, Record<string, unknown>];
    expect(href).toContain("/api/sites/site-1/work-areas/area-1/spatial-data-requests/job-1/file");
    expect(verification).toEqual({ outputSha256: `sha256:${"b".repeat(64)}`, outputSizeBytes: 4 });
    await waitFor(() => expect(container.querySelector("canvas:not(.hidden)")).not.toBeNull());
  });

  it("falls back to the glyph when the bytes do not verify", async () => {
    stubCanvas();
    fetchMock.mockRejectedValue(new Error("HASH_MISMATCH"));
    render(<MaterialThumb siteId="site-1" workAreaId="area-1" jobId="job-1" receipt={receipt() as never} fileName="north.tif" />);
    await waitFor(() => expect(screen.getByText("TIF")).toBeDefined());
  });

  it("does not retain ready pixels while a replacement receipt is being verified", async () => {
    stubCanvas();
    fetchMock.mockResolvedValueOnce(new Uint8Array([7, 7, 7, 7]));
    decodeMock.mockResolvedValue({ pixels: new Uint8ClampedArray(16), width: 2, height: 2, color: true });
    const { container, rerender } = render(
      <MaterialThumb siteId="site-1" workAreaId="area-1" jobId="job-1" receipt={receipt() as never} fileName="north.tif" />,
    );
    await waitFor(() => expect(container.querySelector("canvas:not(.hidden)")).not.toBeNull());
    let finishRead!: (bytes: Uint8Array) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Uint8Array>((resolve) => { finishRead = resolve; }));
    rerender(
      <MaterialThumb siteId="site-1" workAreaId="area-1" jobId="job-2" receipt={receipt({ jobId: "job-2", outputSha256: `sha256:${"c".repeat(64)}` }) as never} fileName="north.tif" />,
    );
    expect(container.querySelector("canvas:not(.hidden)")).toBeNull();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    finishRead(new Uint8Array([8, 8, 8, 8]));
    await waitFor(() => expect(container.querySelector("canvas:not(.hidden)")).not.toBeNull());
  });
});
