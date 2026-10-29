import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const mocked = vi.hoisted(() => ({ session: vi.fn(), action: vi.fn(), options: vi.fn(), origin: vi.fn() }));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/spatial-tasks", () => ({ spatialTaskAction: mocked.action, getSpatialTaskOptions: mocked.options }));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));
import { GET, POST } from "@/app/api/sites/[siteId]/spatial-tasks/[taskId]/[action]/route";

beforeEach(() => { vi.clearAllMocks(); mocked.session.mockResolvedValue("session"); mocked.origin.mockReturnValue(false); });
const context = (action: string) => ({ params: Promise.resolve({ siteId: "site-a", taskId: `st-${"a".repeat(32)}`, action }) });
const request = (body: string) => new NextRequest("http://localhost/api/task", { method: "POST", body });

describe("closed spatial task BFF", () => {
  it("rejects foreign-origin mutation before session or Core", async () => {
    mocked.origin.mockReturnValue(true);
    expect((await POST(request("{}"), context("selection"))).status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled(); expect(mocked.action).not.toHaveBeenCalled();
  });
  it("accepts only three explicit action paths", async () => {
    expect((await POST(request("{}"), context("../run"))).status).toBe(404);
    expect(mocked.action).not.toHaveBeenCalled();
  });
  it("bounds the consumed body even without Content-Length", async () => {
    expect((await POST(request("x".repeat(8193)), context("selection"))).status).toBe(413);
    expect(mocked.action).not.toHaveBeenCalled();
  });
  it("passes exact revision to Core and makes no optimistic execution claim", async () => {
    mocked.action.mockResolvedValue({ state: "CHECK_REQUIRED" });
    const response = await POST(request('{"expectedRevision":3}'), context("run"));
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("private, no-store");
    expect(mocked.action).toHaveBeenCalledWith("site-a", `st-${"a".repeat(32)}`, "run", { expectedRevision: 3 });
  });
  it("rejects invalid page offsets before Core", async () => {
    const response = await GET(new NextRequest("http://localhost/api/task?offset=501"), context("options"));
    expect(response.status).toBe(400); expect(mocked.options).not.toHaveBeenCalled();
  });
});
