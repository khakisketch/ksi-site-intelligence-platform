/** @vitest-environment node */
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createHash } from "node:crypto";
const mocked = vi.hoisted(() => ({session: vi.fn(), origin: vi.fn()}));
vi.mock("@/lib/core-api/session", async (original) => ({...await original<typeof import("@/lib/core-api/session")>(), getSessionToken: mocked.session}));
vi.mock("@/lib/core-api/origin-guard", () => ({isCrossSiteMutation: mocked.origin}));
import { MissingSessionError } from "@/lib/core-api/session";
import { POST } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/archive/route";
const fp = (org: string, principal: string) => `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1",org,principal])).digest("hex")}`;
const context = {params: Promise.resolve({siteId: "site%20a", workAreaId: "area%20a"})};
let mutation: string[];
let tokens: string[];
function setup() {
  process.env.CORE_API_BASE_URL = "http://core.test";
  mutation = []; tokens = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); const token = new Headers(init?.headers).get("authorization") ?? "";
    tokens.push(token);
    if (url.endsWith("/v1/auth/whoami")) {
      if (token === "Bearer unavailable") return Response.json({detail:"unavailable"}, {status:503});
      if (token === "Bearer malformed") return Response.json({organizationId:"org-a", principalId:null});
      return Response.json({organizationId: token === "Bearer other-org" ? "org-b" : "org-a", principalId: token === "Bearer bob" ? "bob" : "alice"});
    }
    mutation.push(url);
    return Response.json({workArea:{workAreaId:"area a",siteId:"site a",status:"ARCHIVED"}});
  }));
}
function request(claim: string | null) {
  const headers = new Headers(); if (claim !== null) headers.set("x-ksi-continuity-fingerprint", claim);
  return POST(new NextRequest("http://console.test/api/sites/site%20a/work-areas/area%20a/archive", {method:"POST", headers}), context);
}
beforeEach(() => {vi.clearAllMocks(); mocked.session.mockReset(); mocked.origin.mockReturnValue(false); setup();});
afterEach(() => {vi.unstubAllGlobals(); vi.restoreAllMocks();});
describe("archive continuity", () => {
  it.each(["bob", "other-org"])("blocks %s before Core mutation", async (token) => {
    mocked.session.mockResolvedValue(token);
    const response = await request(fp("org-a","alice"));
    expect(response.status).toBe(409); expect((await response.json()).code).toBe("ACCOUNT_CONTINUITY_MISMATCH"); expect(mutation).toEqual([]);
  });
  it("uses exactly the checked token for encoded site and area", async () => {
    mocked.session.mockResolvedValueOnce("alice").mockResolvedValueOnce("bob");
    expect((await request(fp("org-a","alice"))).status).toBe(200);
    expect(mocked.session).toHaveBeenCalledTimes(1);
    expect(tokens).toEqual(["Bearer alice", "Bearer alice"]);
    expect(mutation).toEqual(["http://core.test/v1/sites/site%20a/work-areas/area%20a/archive"]);
  });
  it("accepts the legacy headerless call without whoami", async () => {
    mocked.session.mockResolvedValue("bob"); expect((await request(null)).status).toBe(200);
    expect(tokens).toEqual(["Bearer bob"]); expect(mutation).toHaveLength(1);
  });
  it("rejects malformed claims before mutation", async () => {
    mocked.session.mockResolvedValue("alice"); expect((await request("bad")).status).toBe(400); expect(mutation).toEqual([]);
  });
  it.each(["unavailable", "malformed"])("fails closed on whoami %s", async (token) => {
    vi.spyOn(console,"error").mockImplementation(() => undefined);
    mocked.session.mockResolvedValue(token); expect((await request(fp("org-a","alice"))).status).toBeGreaterThanOrEqual(500); expect(mutation).toEqual([]);
  });
  it("rejects cross-site before session or Core", async () => {
    mocked.origin.mockReturnValue(true); expect((await request(fp("org-a","alice"))).status).toBe(403); expect(mocked.session).not.toHaveBeenCalled(); expect(tokens).toEqual([]);
  });
  it("runs the real Origin guard before session lookup", async () => {
    const actual = await vi.importActual<typeof import("@/lib/core-api/origin-guard")>("@/lib/core-api/origin-guard");
    mocked.origin.mockImplementation(actual.isCrossSiteMutation);
    const response = await POST(new NextRequest("http://console.test/api/sites/site-a/work-areas/area-a/archive", {
      method: "POST", headers: {host: "console.test", origin: "https://attacker.test"},
    }), context);
    expect(response.status).toBe(403); expect(mocked.session).not.toHaveBeenCalled(); expect(tokens).toEqual([]);
  });
  it("passes Core authorization refusal through without treating the fingerprint as permission", async () => {
    mocked.session.mockResolvedValue("alice");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/whoami")
      ? Response.json({organizationId: "org-a", principalId: "alice"})
      : Response.json({detail: "forbidden"}, {status: 403})));
    expect((await request(fp("org-a", "alice"))).status).toBe(403);
  });
  it("rejects missing session before Core", async () => {
    vi.spyOn(console,"error").mockImplementation(() => undefined);
    mocked.session.mockRejectedValue(new MissingSessionError()); expect((await request(fp("org-a","alice"))).status).toBe(401); expect(tokens).toEqual([]);
  });
});
