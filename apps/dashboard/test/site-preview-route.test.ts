import { beforeEach, describe, expect, it, vi } from "vitest";

import { NextRequest } from "next/server";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  listWorkAreas: vi.fn(),
  listSpatialDataRequests: vi.fn(),
  getSpatialAsset: vi.fn(),
  coreError: vi.fn((error: unknown) => {
    const status = (error as { status?: number } | null)?.status ?? 500;
    return new Response(JSON.stringify({ message: "error" }), { status });
  }),
}));

vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.listWorkAreas }));
vi.mock("@/lib/core-api/spatial-data-requests", () => ({
  listSpatialDataRequests: mocked.listSpatialDataRequests,
}));
vi.mock("@/lib/core-api/spatial-assets", () => ({ getSpatialAsset: mocked.getSpatialAsset }));
vi.mock("@/lib/core-api/route-handler-util", () => ({ coreApiErrorResponse: mocked.coreError }));

import { GET } from "@/app/api/sites/[siteId]/preview/route";

function get(siteId: string) {
  return GET(
    new NextRequest(`http://console.test/api/sites/${encodeURIComponent(siteId)}/preview`),
    { params: Promise.resolve({ siteId }) },
  );
}

function job(jobId: string, overrides: Record<string, unknown> = {}) {
  return {
    jobId,
    assetRef: `ksa-v1-${"a".repeat(64)}`,
    siteId: "site-1",
    workAreaId: "area-1",
    createdAt: "2026-10-21T00:00:00Z",
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    reason: null,
    remediation: [],
    receipt: {
      jobId,
      receiptDigest: `sha256:${"a".repeat(64)}`,
      artifactKind: "ortho",
      outputSizeBytes: 1024,
      outputSha256: `sha256:${"b".repeat(64)}`,
      requestedBounds: [0, 0, 512, 512],
      actualBounds: [0, 0, 512, 512],
      pixelWindow: [0, 0, 512, 512],
      width: 512,
      height: 512,
      observedCrsIdentifier: "EPSG:7850",
      observedCrsDigest: `sha256:${"c".repeat(64)}`,
      accuracyAssessed: false,
      attribution: "Floreat public sample (CC BY 4.0)",
      modificationNotice: "Windowed crop; no reprojection.",
      limitations: [],
      preparedAt: "2026-10-21T00:00:00Z",
    },
    ...overrides,
  };
}

function asset() {
  return {
    assetRef: `ksa-v1-${"a".repeat(64)}`,
    siteId: "site-1",
    workAreaId: "area-1",
    revision: 3,
    declared: {
      fileName: "ortho.tif",
      gsdM: 0.05,
      captureStartedAt: "2021-08-17T00:00:00Z",
      captureEndedAt: "2021-08-17T00:10:00Z",
      captureDate: "2021-08-17",
    },
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("operator-token");
  mocked.listWorkAreas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "Floreat common-extent" }] });
});

describe("site preview BFF aggregate", () => {
  it("returns a same-origin descriptor for the currently allowed ortho output", async () => {
    mocked.listSpatialDataRequests.mockResolvedValue({ items: [job("sdj-v1-00000000-0000-0000-0000-000000000001")], nextCursor: null });
    mocked.getSpatialAsset.mockResolvedValue(asset());

    const response = await get("site-1");
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toContain("private");
    const body = (await response.json()) as Record<string, unknown>;
    expect(body.available).toBe(true);
    expect(body.siteHref).toContain("/sites/site-1?workAreaId=area-1&assetRef=");
    expect(body.fileHref).toBe(
      "/api/sites/site-1/work-areas/area-1/spatial-data-requests/sdj-v1-00000000-0000-0000-0000-000000000001/file",
    );
    expect(body.partial).toBe(true);
    expect((body.asset as Record<string, unknown>).revision).toBe(3);
  });

  it("skips retention-expired output and takes the next available window", async () => {
    mocked.listSpatialDataRequests.mockResolvedValue({
      items: [
        job("sdj-v1-00000000-0000-0000-0000-00000000000e", { availability: "RETENTION_EXPIRED", reason: "RETENTION_EXPIRED" }),
        job("sdj-v1-00000000-0000-0000-0000-00000000000a"),
      ],
      nextCursor: null,
    });
    mocked.getSpatialAsset.mockResolvedValue(asset());

    const body = (await (await get("site-1")).json()) as Record<string, unknown>;
    expect(body.available).toBe(true);
    expect(body.requestId).toBe("sdj-v1-00000000-0000-0000-0000-00000000000a");
  });

  it("reports no-output when the bounded read is complete and empty, not missing data", async () => {
    mocked.listSpatialDataRequests.mockResolvedValue({ items: [], nextCursor: null });

    const response = await get("site-1");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ available: false, reason: "no-output" });
  });

  it("reports unknown on truncated scope instead of a global zero", async () => {
    mocked.listSpatialDataRequests.mockResolvedValue({ items: [], nextCursor: "next-page" });

    expect(await (await get("site-1")).json()).toEqual({ available: false, reason: "unknown" });
  });

  it("reports unknown when an area list read fails", async () => {
    mocked.listSpatialDataRequests.mockRejectedValue(new Error("Core unavailable"));

    expect(await (await get("site-1")).json()).toEqual({ available: false, reason: "unknown" });
  });

  it("propagates Core rights/currentness without inventing payload", async () => {
    mocked.listWorkAreas.mockRejectedValue(Object.assign(new Error("denied"), { status: 403 }));

    const response = await get("site-1");
    expect(response.status).toBe(403);
    expect(mocked.coreError).toHaveBeenCalled();
  });

  it("rejects malformed site segments without calling Core", async () => {
    const response = await get("site-1/evil");
    expect(response.status).toBe(404);
    expect(mocked.listWorkAreas).not.toHaveBeenCalled();
  });

  it("exposes no storage keys, signed URLs, or tokens", async () => {
    mocked.listSpatialDataRequests.mockResolvedValue({ items: [job("sdj-v1-00000000-0000-0000-0000-000000000001")], nextCursor: null });
    mocked.getSpatialAsset.mockResolvedValue(asset());

    const serialized = JSON.stringify(await (await get("site-1")).json());
    expect(serialized).not.toMatch(/s3|signed|token|secret/i);
  });

  it("degrades labels when asset detail is denied but keeps the allowed output", async () => {
    mocked.listSpatialDataRequests.mockResolvedValue({ items: [job("sdj-v1-00000000-0000-0000-0000-000000000001")], nextCursor: null });
    mocked.getSpatialAsset.mockRejectedValue(Object.assign(new Error("denied"), { status: 403 }));

    const body = (await (await get("site-1")).json()) as Record<string, unknown>;
    expect(body.available).toBe(true);
    expect((body.asset as Record<string, unknown>).revision).toBeNull();
  });

  it("is read-only — no mutation handler", async () => {
    const route = await import("@/app/api/sites/[siteId]/preview/route");
    expect("POST" in route).toBe(false);
    expect("PUT" in route).toBe(false);
    expect("DELETE" in route).toBe(false);
  });

  it("treats unscanned areas beyond the bound as unknown, not no-output", async () => {
    mocked.listWorkAreas.mockResolvedValue({
      workAreas: Array.from({ length: 8 }, (_, index) => ({ workAreaId: `area-${index + 1}`, name: `구역 ${index + 1}` })),
    });
    mocked.listSpatialDataRequests.mockResolvedValue({ items: [], nextCursor: null });

    const body = await (await get("site-1")).json();
    expect(body).toEqual({ available: false, reason: "unknown" });
  });

  it("skips jobs bound to another site or area instead of building cross-scope URLs", async () => {
    mocked.listSpatialDataRequests.mockImplementation(async (_siteId: string, workAreaId: string) => ({
      items: [
        job("sdj-v1-00000000-0000-0000-0000-000000000001", { siteId: "site-9", workAreaId }),
        job("sdj-v1-00000000-0000-0000-0000-000000000002", { siteId: "site-1", workAreaId: "area-9" }),
      ],
      nextCursor: null,
    }));

    const body = await (await get("site-1")).json();
    expect(body).toEqual({ available: false, reason: "no-output" });
  });

  it("degrades labels when the asset detail belongs to another scope", async () => {
    mocked.listSpatialDataRequests.mockResolvedValue({ items: [job("sdj-v1-00000000-0000-0000-0000-000000000001")], nextCursor: null });
    mocked.getSpatialAsset.mockResolvedValue({
      ...asset(),
      siteId: "site-9",
      assetRef: `ksa-v1-${"9".repeat(64)}`,
    });

    const body = (await (await get("site-1")).json()) as Record<string, unknown>;
    expect(body.available).toBe(true);
    expect((body.asset as Record<string, unknown>).revision).toBeNull();
  });
});
