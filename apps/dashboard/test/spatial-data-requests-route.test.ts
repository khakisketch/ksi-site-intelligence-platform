import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  create: vi.fn(),
  crossSite: vi.fn(),
  coreError: vi.fn(() => new Response(JSON.stringify({ message: "Core error" }), { status: 503 })),
}));

vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/spatial-data-requests", () => ({ createSpatialDataRequest: mocked.create }));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.crossSite }));
vi.mock("@/lib/core-api/route-handler-util", () => ({ coreApiErrorResponse: mocked.coreError }));

import { POST } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/spatial-data-requests/route";

const context = { params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1" }) };
const assetRef = `ksa-v1-${"a".repeat(64)}`;
const digest = `sha256:${"b".repeat(64)}`;
const input = {
  assetRef,
  requestedBounds: [200000, 549968, 200032, 550000],
  observedCrsDigest: digest,
  resolutionMode: "NATIVE",
  purpose: "GENERAL_DATA_USE",
};

function post(body: unknown, headers: Record<string, string> = {}) {
  return new Request("http://console.test/api/sites/site-1/work-areas/area-1/spatial-data-requests", {
    method: "POST",
    headers: {
      origin: "http://console.test",
      host: "console.test",
      "content-type": "application/json",
      "idempotency-key": "sdreq-00000000-0000-0000-0000-000000000000",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("operator-token");
  mocked.crossSite.mockReturnValue(false);
  mocked.create.mockResolvedValue({ jobId: "sdj-v1-00000000-0000-0000-0000-000000000001", executionState: "QUEUED" });
});

describe("spatial data request BFF route", () => {
  it("forwards only a shape-validated request with the caller's idempotency key", async () => {
    const response = await POST(post(input) as never, context);
    expect(response.status).toBe(200);
    expect(mocked.create).toHaveBeenCalledWith("site-1", "area-1", input, "sdreq-00000000-0000-0000-0000-000000000000");
  });

  it("rejects cross-site mutations before any Core call", async () => {
    mocked.crossSite.mockReturnValue(true);
    const response = await POST(post(input) as never, context);
    expect(response.status).toBe(403);
    expect(mocked.create).not.toHaveBeenCalled();
  });

  it("requires an idempotency key", async () => {
    const response = await POST(post(input, { "idempotency-key": "" }) as never, context);
    expect(response.status).toBe(422);
    expect(mocked.create).not.toHaveBeenCalled();
  });

  it.each([
    ["foreign asset ref", { ...input, assetRef: "ksa-v1-not-a-ref" }],
    ["bad digest", { ...input, observedCrsDigest: "sha256:zz" }],
    ["wrong resolution mode", { ...input, resolutionMode: "RESAMPLED" }],
    ["unknown purpose", { ...input, purpose: "SETTLEMENT" }],
    ["wrong bounds arity", { ...input, requestedBounds: [1, 2, 3] }],
    ["non-finite bounds", { ...input, requestedBounds: [1, 2, 3, Number.POSITIVE_INFINITY] }],
    ["array body", [input]],
  ])("rejects %s with 422 and no Core call", async (_label, body) => {
    const response = await POST(post(body) as never, context);
    expect(response.status).toBe(422);
    expect(mocked.create).not.toHaveBeenCalled();
  });

  it("maps Core failures through the shared error response", async () => {
    mocked.create.mockRejectedValue(new Error("core down"));
    const response = await POST(post(input) as never, context);
    expect(response.status).toBe(503);
    expect(mocked.coreError).toHaveBeenCalled();
  });
});
