import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ coreFetch: vi.fn() }));
vi.mock("@/lib/core-api/client", () => ({ coreFetch: mocked.coreFetch }));

import { getSpatialAsset, listSpatialAssets } from "@/lib/core-api/spatial-assets";

describe("spatial asset Core client", () => {
  beforeEach(() => mocked.coreFetch.mockReset());

  it("requests only a bounded page under the selected Site and WorkArea", async () => {
    mocked.coreFetch.mockResolvedValue({ assets: [], nextCursor: null, hasMore: false });
    await listSpatialAssets("site/one", "area one", { limit: 50, cursor: "signed cursor" });
    expect(mocked.coreFetch).toHaveBeenCalledWith(
      "/v1/sites/site%2Fone/work-areas/area%20one/spatial-assets",
      { query: { limit: 50, cursor: "signed cursor" } },
    );
  });

  it("re-requests an exact encoded opaque asset ref through Core", async () => {
    const ref = `ksa-v1-${"a".repeat(64)}`;
    await getSpatialAsset("site-1", "area-1", ref);
    expect(mocked.coreFetch).toHaveBeenCalledWith(
      `/v1/sites/site-1/work-areas/area-1/spatial-assets/${ref}`,
    );
    expect(mocked.coreFetch.mock.calls[0]?.[0]).not.toContain("objectKey");
    expect(mocked.coreFetch.mock.calls[0]?.[0]).not.toContain("download");
  });
});
