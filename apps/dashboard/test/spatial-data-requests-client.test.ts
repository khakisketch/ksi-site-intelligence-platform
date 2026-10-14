import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ coreFetch: vi.fn(), coreFetchBinary: vi.fn() }));
vi.mock("server-only", () => ({}));
vi.mock("@/lib/core-api/client", () => mocked);

import {
  cancelSpatialDataRequest,
  downloadSpatialDataRequestFile,
  getSpatialDataRequest,
  listSpatialDataRequests,
} from "@/lib/core-api/spatial-data-requests";

const requestId = "sdj-v1-12345678-1234-1234-1234-123456789abc";

describe("spatial data request Core client", () => {
  beforeEach(() => {
    mocked.coreFetch.mockReset();
    mocked.coreFetchBinary.mockReset();
  });

  it("lists a bounded cursor page within exactly one encoded Site and WorkArea", async () => {
    mocked.coreFetch.mockResolvedValue({ items: [], nextCursor: null });
    await listSpatialDataRequests("site/one", "area one", { limit: 50, cursor: "opaque cursor" });
    expect(mocked.coreFetch).toHaveBeenCalledWith(
      "/v1/sites/site%2Fone/work-areas/area%20one/spatial-data-requests",
      { query: { limit: 50, cursor: "opaque cursor" } },
    );
  });

  it("re-reads and cancels the exact Core request without adding a body or authority inputs", async () => {
    await getSpatialDataRequest("site-1", "area-1", requestId);
    expect(mocked.coreFetch).toHaveBeenLastCalledWith(
      `/v1/sites/site-1/work-areas/area-1/spatial-data-requests/${requestId}`,
    );
    await cancelSpatialDataRequest("site-1", "area-1", requestId);
    expect(mocked.coreFetch).toHaveBeenLastCalledWith(
      `/v1/sites/site-1/work-areas/area-1/spatial-data-requests/${requestId}/cancel`,
      { method: "POST" },
    );
  });

  it("downloads only through the existing Core file route, never by object key", async () => {
    await downloadSpatialDataRequestFile("site-1", "area-1", requestId);
    expect(mocked.coreFetchBinary).toHaveBeenCalledWith(
      `/v1/sites/site-1/work-areas/area-1/spatial-data-requests/${requestId}/file`,
    );
    expect(mocked.coreFetchBinary.mock.calls[0]?.[0]).not.toMatch(/objectKey|downloadUrl/);
  });
});
