import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoreApiError } from "@/lib/core-api/client";
import type { SpatialAssetCatalogItem, SpatialAssetCatalogPage } from "@/lib/core-api/spatial-assets";
import { locateUploadedAsset, parseUploadedArtifact, uploadedArtifactHref, type UploadedArtifact } from "@/lib/uploaded-asset-locator";

const mocked = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/lib/core-api/spatial-assets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/spatial-assets")>();
  return { ...actual, listSpatialAssets: mocked.list };
});
import { GET } from "@/app/sites/[siteId]/upload/open/route";

const SUBMISSION = `ers-v1-${"1".repeat(64)}`;
const OTHER_SUBMISSION = `ers-v1-${"2".repeat(64)}`;
const target: UploadedArtifact = { workAreaId: "wa-1", workOrderId: "wo-1", submissionRef: SUBMISSION, revision: 1, artifactId: "dsm" };

function item(overrides: Partial<SpatialAssetCatalogItem>): SpatialAssetCatalogItem {
  return {
    assetRef: `ksa-v1-${"a".repeat(64)}`, siteId: "site-1", workAreaId: "wa-1", workOrderId: "wo-1",
    observationEpochId: "ep-1", submissionRef: SUBMISSION, revision: 1, artifactId: "dsm", kind: "dsm",
    ...overrides,
  } as SpatialAssetCatalogItem;
}

function page(assets: SpatialAssetCatalogItem[], nextCursor: string | null = null, scope: Partial<SpatialAssetCatalogPage> = {}): SpatialAssetCatalogPage {
  return { siteId: "site-1", workAreaId: "wa-1", assets, nextCursor, hasMore: nextCursor !== null, ...scope } as SpatialAssetCatalogPage;
}

function query(values: Record<string, string>): URLSearchParams {
  return new URLSearchParams({ workAreaId: "wa-1", workOrderId: "wo-1", submissionRef: SUBMISSION, revision: "1", artifactId: "dsm", ...values });
}

describe("parseUploadedArtifact", () => {
  it("accepts exactly what the upload screen sends", () => {
    expect(parseUploadedArtifact(query({}))).toEqual(target);
  });

  it("opens the exact corrected file even when site and work-area names need URL encoding", () => {
    const correction = { ...target, workAreaId: "구역 / 1", revision: 2 };
    const url = new URL(uploadedArtifactHref("현장/1", correction), "https://dashboard.example");
    expect(url.pathname).toBe(`/sites/${encodeURIComponent("현장/1")}/upload/open`);
    expect(parseUploadedArtifact(url.searchParams)).toEqual(correction);
  });

  it("round trips an imported file identifier independently of its raster kind", () => {
    const imported: UploadedArtifact = { ...target, revision: 2, artifactId: "구역 A/DSM (원본)", kind: "dsm" };
    const url = new URL(uploadedArtifactHref("site-1", imported), "https://dashboard.example");
    expect(parseUploadedArtifact(url.searchParams)).toEqual(imported);
    url.searchParams.set("artifactKind", "pointcloud");
    expect(parseUploadedArtifact(url.searchParams)).toBeNull();
  });

  it.each([
    ["submissionRef", "ers-v1-short"],
    ["revision", "0"],
    ["revision", "1.5"],
    ["revision", "9007199254740992"],
    ["artifactId", "pointcloud"],
    ["workOrderId", " "],
    ["workAreaId", "x".repeat(257)],
  ])("refuses a malformed %s", (key, value) => {
    expect(parseUploadedArtifact(query({ [key]: value }))).toBeNull();
  });
});

describe("locateUploadedAsset", () => {
  it("matches the stored identifier and the declared kind for a non-slot file identifier", async () => {
    const targetFile: UploadedArtifact = { ...target, artifactId: "survey tile A", kind: "dsm" };
    const wanted = item({ artifactId: targetFile.artifactId, assetRef: `ksa-v1-${"d".repeat(64)}` });
    const list = vi.fn().mockResolvedValue(page([item({ artifactId: targetFile.artifactId, kind: "ortho" }), wanted]));
    expect(await locateUploadedAsset("site-1", targetFile, list)).toEqual({ assetRef: wanted.assetRef, cursor: undefined });
  });

  it("returns the Core asset of the exact submission, revision and artifact, with the page cursor", async () => {
    const wanted = item({ assetRef: `ksa-v1-${"b".repeat(64)}` });
    const list = vi.fn()
      .mockResolvedValueOnce(page([
        item({ artifactId: "ortho", kind: "ortho" }),
        item({ revision: 2 }),
        item({ submissionRef: OTHER_SUBMISSION }),
        item({ workOrderId: "wo-2" }),
      ], "c-2"))
      .mockResolvedValueOnce(page([wanted]));
    expect(await locateUploadedAsset("site-1", target, list)).toEqual({ assetRef: wanted.assetRef, cursor: "c-2" });
    expect(list.mock.calls).toEqual([[undefined], ["c-2"]]);
  });

  it("stops at the page budget instead of reading the whole catalog", async () => {
    const list = vi.fn().mockImplementation(async () => page([item({ revision: 9 })], "more"));
    expect(await locateUploadedAsset("site-1", target, list, 3)).toBeNull();
    expect(list).toHaveBeenCalledTimes(3);
  });

  it("stops when the catalog has no more pages", async () => {
    const list = vi.fn().mockResolvedValueOnce(page([]));
    expect(await locateUploadedAsset("site-1", target, list)).toBeNull();
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("trusts no page bound to another site or work area", async () => {
    const list = vi.fn().mockResolvedValueOnce(page([item({})], null, { workAreaId: "wa-2" }));
    expect(await locateUploadedAsset("site-1", target, list)).toBeNull();
  });
});

describe("upload open route", () => {
  const params = { params: Promise.resolve({ siteId: "site-1" }) };
  const request = (values: Record<string, string>) => {
    const url = new URL(`http://console.test/sites/site-1/upload/open?${query(values).toString()}`);
    return { nextUrl: url } as never;
  };

  beforeEach(() => { vi.resetAllMocks(); });

  it("redirects to the data screen with the uploaded asset selected on its page", async () => {
    const wanted = item({ assetRef: `ksa-v1-${"c".repeat(64)}` });
    mocked.list.mockResolvedValueOnce(page([], "c-2")).mockResolvedValueOnce(page([wanted]));
    const response = await GET(request({}), params);
    expect(response.status).toBe(303);
    expect(response.headers.get("Cache-Control")).toBe("private, no-store");
    expect(response.headers.get("Location")).toBe(`/sites/site-1/data?workAreaId=wa-1&assetRef=${wanted.assetRef}&cursor=c-2#section-inspector`);
    expect(mocked.list.mock.calls).toEqual([
      ["site-1", "wa-1", { limit: 50, order: "capture-desc" }],
      ["site-1", "wa-1", { limit: 50, cursor: "c-2", order: "capture-desc" }],
    ]);
  });

  it("falls back to the work area's data list when Core refuses", async () => {
    mocked.list.mockRejectedValueOnce(new CoreApiError(403, { detail: "FORBIDDEN" }));
    const response = await GET(request({}), params);
    expect(response.headers.get("Location")).toBe("/sites/site-1/data?workAreaId=wa-1");
  });

  it("does not ask Core about a malformed request", async () => {
    const response = await GET(request({ artifactId: "x" }), params);
    expect(response.headers.get("Location")).toBe("/sites/site-1/data");
    expect(mocked.list).not.toHaveBeenCalled();
  });
});
