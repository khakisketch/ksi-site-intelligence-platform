/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";

import { putExternalReconstructionFile } from "@/lib/external-reconstruction-upload";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("external reconstruction direct upload progress", () => {
  it("reports only verified zero and completed byte counts while retaining the direct PUT request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    const progress: number[] = [];
    const file = new File(["raster"], "ortho.tif", { type: "application/octet-stream" });

    await putExternalReconstructionFile(
      { artifactId: "ortho", uploadUrl: "https://storage.example.test/opaque", requiredHeaders: { "x-upload": "grant" } },
      file,
      undefined,
      (bytes) => progress.push(bytes),
    );

    expect(progress).toEqual([0, file.size]);
    expect(fetchMock).toHaveBeenCalledWith("https://storage.example.test/opaque", expect.objectContaining({
      method: "PUT",
      body: file,
      redirect: "error",
    }));
  });

  it("does not report completed bytes when the Core-issued upload URL rejects the request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    const file = new File(["raster"], "ortho.tif");
    const progress: number[] = [];

    await expect(putExternalReconstructionFile(
      { artifactId: "ortho", uploadUrl: "https://storage.example.test/opaque", requiredHeaders: {} },
      file,
      undefined,
      (bytes) => progress.push(bytes),
    )).rejects.toThrow("external artifact upload failed (503)");

    expect(progress).toEqual([0]);
  });
});
