import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  cancel: vi.fn(),
  download: vi.fn(),
  crossSite: vi.fn(),
  coreError: vi.fn(),
}));

vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/spatial-data-requests", () => ({
  cancelSpatialDataRequest: mocked.cancel,
  downloadSpatialDataRequestFile: mocked.download,
}));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.crossSite }));
vi.mock("@/lib/core-api/route-handler-util", () => ({ coreApiErrorResponse: mocked.coreError }));

import { POST as CancelRequest } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/spatial-data-requests/[requestId]/cancel/route";
import { GET as DownloadRequestFile } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/spatial-data-requests/[requestId]/file/route";

const requestId = "sdj-v1-12345678-1234-1234-1234-123456789abc";
const params = { siteId: "site-1", workAreaId: "area-1", requestId };

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("operator-token");
  mocked.crossSite.mockReturnValue(false);
  mocked.coreError.mockImplementation(() => Response.json({ code: "ERROR" }, { status: 500 }));
});

describe("spatial data request authenticated proxies", () => {
  it("forwards cancellation through the current session and exact scope", async () => {
    mocked.cancel.mockResolvedValue({ jobId: requestId, executionState: "CANCELED" });
    const request = new Request("http://console.test/api/cancel", { method: "POST" });
    const response = await CancelRequest(request as never, { params: Promise.resolve(params) });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ jobId: requestId, executionState: "CANCELED" });
    expect(mocked.session).toHaveBeenCalledOnce();
    expect(mocked.cancel).toHaveBeenCalledWith("site-1", "area-1", requestId);
  });

  it("rejects cross-site cancellation before session or Core mutation", async () => {
    mocked.crossSite.mockReturnValue(true);
    const request = new Request("http://console.test/api/cancel", { method: "POST" });
    const response = await CancelRequest(request as never, { params: Promise.resolve(params) });
    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();
    expect(mocked.cancel).not.toHaveBeenCalled();
  });

  it("rejects malformed request IDs before forwarding cancellation", async () => {
    const request = new Request("http://console.test/api/cancel", { method: "POST" });
    const response = await CancelRequest(request as never, {
      params: Promise.resolve({ ...params, requestId: "not-a-spatial-data-job" }),
    });
    expect(response.status).toBe(404);
    expect(mocked.cancel).not.toHaveBeenCalled();
  });

  it("returns exact authorized Core bytes as a private attachment with a safe filename", async () => {
    const bytes = new Uint8Array([0, 1, 2, 255]);
    mocked.download.mockResolvedValue({
      body: bytes.buffer,
      contentType: "image/tiff; charset=binary",
      contentDisposition: 'attachment; filename="sensitive-source-name.tif"',
    });
    const request = new Request("http://console.test/api/file");
    const response = await DownloadRequestFile(request, { params: Promise.resolve(params) });
    expect(response.status).toBe(200);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
    expect(response.headers.get("content-type")).toBe("image/tiff");
    expect(response.headers.get("content-disposition")).toBe(`attachment; filename="spatial-data-${requestId}.tif"`);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("content-disposition")).not.toContain("sensitive-source-name");
    expect(mocked.download).toHaveBeenCalledWith("site-1", "area-1", requestId);
  });
});
