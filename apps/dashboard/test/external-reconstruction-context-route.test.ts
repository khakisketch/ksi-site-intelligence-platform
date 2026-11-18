import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoreApiError } from "@/lib/core-api/client";

const mocked = vi.hoisted(() => ({ session: vi.fn(), context: vi.fn() }));
vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/external-reconstruction", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/external-reconstruction")>();
  return { ...actual, getExternalReconstructionContext: mocked.context };
});
import { GET } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-context/route";

const params = { params: Promise.resolve({ workOrderId: "work-1" }) };

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("token");
});

describe("external reconstruction context BFF", () => {
  it("returns only the identifiers registration needs, uncached", async () => {
    mocked.context.mockResolvedValue({
      workOrderId: "work-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3,
      executionMode: "EXTERNAL_RECONSTRUCTION", externalPlanningBinding: { organizationId: "secret-org" },
    });
    const response = await GET(new Request("http://console.test/api") as never, params);
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("private, no-store");
    expect(await response.json()).toEqual({ workOrderId: "work-1", siteId: "site-1", expectedEpochId: "epoch-1", executionMode: "EXTERNAL_RECONSTRUCTION" });
    expect(mocked.context).toHaveBeenCalledWith("work-1");
  });

  it("passes Core refusals through instead of inventing an epoch", async () => {
    mocked.context.mockRejectedValue(new CoreApiError(404, { detail: "NOT_FOUND" }));
    const response = await GET(new Request("http://console.test/api") as never, params);
    expect(response.status).toBe(404);
  });

  it("does not call Core without a session", async () => {
    mocked.session.mockRejectedValue(new CoreApiError(401, { detail: "auth required" }));
    const response = await GET(new Request("http://console.test/api") as never, params);
    expect(response.status).toBe(401);
    expect(mocked.context).not.toHaveBeenCalled();
  });
});
