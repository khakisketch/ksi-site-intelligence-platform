import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ session: vi.fn(), coverage: vi.fn() }));
vi.mock("@/lib/core-api/session", async (original) => ({ ...await original<typeof import("@/lib/core-api/session")>(), getSessionToken: mocks.session }));
vi.mock("@/lib/core-api/analysis-coverage", () => ({ getAnalysisCoverage: mocks.coverage }));
import { GET } from "@/app/api/sites/[siteId]/analyses/[analysisId]/coverage/route";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";

const context = { params: Promise.resolve({ siteId: "site-1", analysisId: "analysis-1" }) };
const url = "http://console.test/api/sites/site-1/analyses/analysis-1/coverage";
afterEach(() => vi.resetAllMocks());

describe("human-only authenticated coverage BFF", () => {
  it("returns private, uncached exact-result coverage using the current human session", async () => {
    mocks.session.mockResolvedValue("human"); mocks.coverage.mockResolvedValue({ resultId: "same-result" });
    const response = await GET(new Request(url) as never, context);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ resultId: "same-result" });
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(mocks.coverage).toHaveBeenCalledWith("site-1", "analysis-1", expect.any(AbortSignal));
  });
  it("refuses anonymous callers before opening Core", async () => {
    mocks.session.mockRejectedValue(new MissingSessionError());
    const response = await GET(new Request(url) as never, context);
    expect(response.status).toBe(401);
    expect(mocks.coverage).not.toHaveBeenCalled();
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });
  it.each(["?url=https://untrusted.test", "?limit=1", "?offset=1"])('refuses unbounded client parameters: %s', async (query) => {
    mocks.session.mockResolvedValue("human");
    expect((await GET(new Request(url + query) as never, context)).status).toBe(400);
    expect(mocks.coverage).not.toHaveBeenCalled();
  });
  it("refuses browser-supplied byte ranges and preserves Core's scoped refusal", async () => {
    mocks.session.mockResolvedValue("human");
    expect((await GET(new Request(url, { headers: { Range: "bytes=0-9" } }) as never, context)).status).toBe(400);
    mocks.coverage.mockRejectedValue(new CoreApiError(404, {}));
    expect((await GET(new Request(url) as never, context)).status).toBe(404);
  });
});
