/** @vitest-environment node */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createHash } from "node:crypto";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  origin: vi.fn(),
}));

vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));

import { POST } from "@/app/api/sites/route";

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

// Production Core scopes bootstrap idempotency to (organizationId, actor,
// requestKey): the same key as a different account creates a SECOND site.
// Legacy siteId is globally unique: the same siteId anywhere is a DUPLICATE.
// This mock reproduces that scoping so the BFF guard is verified without Core.
const bootstrapSites = new Map<string, { siteId: string; digest: string }>();
const legacySiteIds = new Set<string>();
let siteCounter = 0;
let coreCreateCalls = 0;

function tokenIdentity(token: string | null): { org: string; actor: string } | null {
  if (token === "token-alice-a" || token === "token-alice-a-renewed") return { org: "org-a", actor: "alice" };
  if (token === "token-bob-a") return { org: "org-a", actor: "bob" };
  if (token === "token-alice-b") return { org: "org-b", actor: "alice" };
  return null;
}

function jsonResponse(value: unknown, status: number): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function siteView(siteId: string, body: Record<string, unknown>) {
  return {
    siteId,
    name: body.name,
    siteFrame: body.siteFrame,
    status: "UNMAPPED",
    resumeTarget: null,
    registeredAt: "2026-10-28T00:00:00Z",
    updatedAt: "2026-10-28T00:00:00Z",
    aoi: body.aoi ?? null,
    dataResidency: body.dataResidency ?? null,
    aiEgressAllowed: body.aiEgressAllowed ?? false,
    modelMaxAgeDays: null,
  };
}

function installCoreFetchMock() {
  process.env.CORE_API_BASE_URL = "http://core.test";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = new Headers(init?.headers as HeadersInit | undefined);
      const auth = headers.get("authorization") ?? "";
      const token = auth.startsWith("Bearer ") ? auth.slice("Bearer ".length) : null;
      const who = tokenIdentity(token);
      if (url.endsWith("/v1/auth/whoami")) {
        if (token === "token-whoami-503") return jsonResponse({ detail: "unavailable" }, 503);
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        return jsonResponse(
          {
            principalId: who.actor,
            organizationId: who.org,
            kind: "OPERATOR",
            role: "ADMIN",
            deviceId: null,
            permissions: ["SITES_WRITE", "MISSIONS_ISSUE"],
          },
          200,
        );
      }
      if (url.endsWith("/v1/sites") && (init?.method ?? "GET") === "POST") {
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        coreCreateCalls += 1;
        const rawBody = typeof init?.body === "string" ? init.body : "";
        const body = JSON.parse(rawBody) as Record<string, unknown>;
        if (typeof body.bootstrapRequestId === "string") {
          const mapKey = `${who.org}\0${who.actor}\0${body.bootstrapRequestId}`;
          const digest = JSON.stringify([body.name, body.siteFrame, body.aoi, body.dataResidency, body.aiEgressAllowed]);
          const existing = bootstrapSites.get(mapKey);
          if (existing) {
            if (existing.digest !== digest) {
              return jsonResponse({ verdict: "BOOTSTRAP_REQUEST_CONFLICT", detail: "conflict", site: null }, 409);
            }
            return jsonResponse({ verdict: "REGISTERED", site: siteView(existing.siteId, body), detail: null }, 201);
          }
          siteCounter += 1;
          const siteId = `site-issued-${siteCounter}`;
          bootstrapSites.set(mapKey, { siteId, digest });
          return jsonResponse({ verdict: "REGISTERED", site: siteView(siteId, body), detail: null }, 201);
        }
        const siteId = body.siteId as string;
        if (legacySiteIds.has(siteId)) {
          return jsonResponse({ verdict: "DUPLICATE_SITE_ID", detail: "이미 등록된 siteId", site: null }, 409);
        }
        legacySiteIds.add(siteId);
        return jsonResponse({ verdict: "REGISTERED", site: siteView(siteId, body), detail: null }, 201);
      }
      return jsonResponse({ detail: "not found" }, 404);
    }),
  );
}

const MAPPED_BODY = {
  bootstrapRequestId: "11111111-2222-4333-8444-555555555555",
  name: "현장 A",
  siteFrame: { crs: "EPSG:5186", verticalDatum: "KNGeoid2018", unit: "meter", transformVersion: "1.0.0" },
  aoi: { vertices: [{ latDeg: 37.5, lonDeg: 127 }, { latDeg: 37.51, lonDeg: 127 }, { latDeg: 37.51, lonDeg: 127.01 }] },
  aiEgressAllowed: false,
};

function postSites(token: string, fp: string | null, body: unknown = MAPPED_BODY) {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (fp !== null) headers["x-ksi-continuity-fingerprint"] = fp;
  mocked.session.mockResolvedValue(token);
  return POST(
    new NextRequest("http://console.test/api/sites", {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.session.mockReset();
  vi.unstubAllGlobals();
  mocked.origin.mockReturnValue(false);
  bootstrapSites.clear();
  legacySiteIds.clear();
  siteCounter = 0;
  coreCreateCalls = 0;
  installCoreFetchMock();
});

describe("POST /api/sites account-continuity BFF guard", () => {
  it("blocks a fingerprint-bound retry under another account without a Core POST", async () => {
    const claim = fingerprint("org-a", "alice");
    const first = await postSites("token-alice-a", claim);
    expect(first.status).toBe(201);
    const blocked = await postSites("token-bob-a", claim);
    expect(blocked.status).toBe(409);
    expect(((await blocked.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(coreCreateCalls).toBe(1);
    expect(bootstrapSites.size).toBe(1);
  });

  it("blocks a fingerprint-bound retry from another organization", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await postSites("token-alice-a", claim)).status).toBe(201);
    const blocked = await postSites("token-alice-b", claim);
    expect(blocked.status).toBe(409);
    expect(blocked.headers.get("cache-control")).toBe("private, no-store");
    expect(coreCreateCalls).toBe(1);
    expect(bootstrapSites.size).toBe(1);
  });

  it("replays the same key for the same renewed account without a second site", async () => {
    const claim = fingerprint("org-a", "alice");
    const first = await postSites("token-alice-a", claim);
    expect(first.status).toBe(201);
    const firstBody = (await first.json()) as { site: { siteId: string } };
    const retry = await postSites("token-alice-a-renewed", claim);
    expect(retry.status).toBe(201);
    expect(((await retry.json()) as { site: { siteId: string } }).site.siteId).toBe(firstBody.site.siteId);
    expect(bootstrapSites.size).toBe(1);
  });

  it("refuses a malformed fingerprint before the Core mutation", async () => {
    const response = await postSites("token-alice-a", "not-a-fingerprint");
    expect(response.status).toBe(400);
    expect(coreCreateCalls).toBe(0);
  });

  it("fails closed when the effective identity cannot be read", async () => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await postSites("token-whoami-503", fingerprint("org-a", "alice"));
    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(coreCreateCalls).toBe(0);
    errorLog.mockRestore();
  });

  it("binds identity lookup and mutation to a single captured session token", async () => {
    mocked.session.mockResolvedValueOnce("token-alice-a").mockResolvedValueOnce("token-bob-a");
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-ksi-continuity-fingerprint": fingerprint("org-a", "alice"),
    };
    const response = await POST(
      new NextRequest("http://console.test/api/sites", {
        method: "POST",
        headers,
        body: JSON.stringify(MAPPED_BODY),
      }),
    );
    expect(response.status).toBe(201);
    expect(mocked.session).toHaveBeenCalledTimes(1);
    expect(bootstrapSites.has("org-a\x00alice\x0011111111-2222-4333-8444-555555555555")).toBe(true);
  });

  it("retains the existing no-header caller behavior (unprotected, as before)", async () => {
    expect((await postSites("token-alice-a", null)).status).toBe(201);
    expect(coreCreateCalls).toBe(1);
  });

  it("does not trust a caller-supplied identity as the effective identity", async () => {
    const blocked = await postSites("token-bob-a", fingerprint("org-a", "alice"));
    expect(blocked.status).toBe(409);
    expect(bootstrapSites.size).toBe(0);
    const selfMatch = await postSites("token-bob-a", fingerprint("org-a", "bob"));
    expect(selfMatch.status).toBe(201);
    expect(bootstrapSites.has("org-a\x00bob\x0011111111-2222-4333-8444-555555555555")).toBe(true);
  });
});
