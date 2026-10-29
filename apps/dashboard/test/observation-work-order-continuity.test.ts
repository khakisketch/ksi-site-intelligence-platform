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

import { POST } from "@/app/api/sites/[siteId]/observation-work-orders/route";

const siteContext = { params: Promise.resolve({ siteId: "site-a" }) };
const BODY = {
  name: "외부 비교",
  workAreaIds: ["wa-1"],
  scheduleId: null,
  executionMode: "EXTERNAL_RECONSTRUCTION",
};

// Simulated Core actor-scoped idempotency: (org, actor, key) -> order.
// Production Core scopes to (organization_id, actor, key_hash); the same raw
// key as a different account/org creates a second order. This mock reproduces
// that scoping so the BFF guard can be verified without a live Core.
const coreOrders = new Map<string, { workOrderId: string; fingerprint: string }>();
let orderCounter = 0;
let coreCreateCalls = 0;

function tokenIdentity(token: string | null): { org: string; actor: string } | null {
  if (token === "token-alice-a" || token === "token-alice-a-renewed") return { org: "org-a", actor: "alice" };
  if (token === "token-bob-a") return { org: "org-a", actor: "bob" };
  if (token === "token-alice-b") return { org: "org-b", actor: "alice" };
  if (token === "token-unicode") return { org: "org-a", actor: "운영자@example.com" };
  return null;
}

function jsonResponse(value: unknown, status: number): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
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
        if (token === "token-whoami-malformed") return jsonResponse({ organizationId: "org-a", principalId: null }, 200);
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        return jsonResponse(
          {
            principalId: who.actor,
            organizationId: who.org,
            kind: "OPERATOR",
            role: "FIELD_OPERATOR",
            deviceId: null,
            permissions: ["SITES_READ", "SITES_WRITE", "WORK_ORDERS_WRITE"],
          },
          200,
        );
      }
      if (url.endsWith("/v1/sites/site-a/observation-work-orders") && (init?.method ?? "GET") === "POST") {
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        coreCreateCalls += 1;
        const idemKey = headers.get("Idempotency-Key") ?? headers.get("idempotency-key") ?? "";
        const rawBody = typeof init?.body === "string" ? init.body : "";
        const mapKey = `${who.org}\0${who.actor}\0${idemKey}`;
        const existing = coreOrders.get(mapKey);
        if (existing) {
          if (existing.fingerprint !== rawBody) {
            return jsonResponse({ detail: "Idempotency-Key가 다른 생성 본문에 이미 사용됐다" }, 409);
          }
          return jsonResponse({ workOrderId: existing.workOrderId }, 201);
        }
        orderCounter += 1;
        const createdId = `obs-work-${String(orderCounter).padStart(8, "0")}`;
        coreOrders.set(mapKey, { workOrderId: createdId, fingerprint: rawBody });
        return jsonResponse({ workOrderId: createdId }, 201);
      }
      return jsonResponse({ detail: "not found" }, 404);
    }),
  );
}

function postAs(token: string, continuity: { org: string; actor: string } | null, key = "external-key-1") {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "Idempotency-Key": key,
  };
  if (continuity) {
    headers["x-ksi-continuity-org"] = continuity.org;
    headers["x-ksi-continuity-actor"] = continuity.actor;
  }
  mocked.session.mockResolvedValue(token);
  return POST(
    new NextRequest("http://console.test/api/sites/site-a/observation-work-orders", {
      method: "POST",
      headers,
      body: JSON.stringify(BODY),
    }),
    siteContext,
  );
}

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

function postFingerprint(token: string, value: string) {
  mocked.session.mockResolvedValue(token);
  return POST(new NextRequest("http://console.test/api/sites/site-a/observation-work-orders", {
    method: "POST",
    headers: { "content-type": "application/json", "Idempotency-Key": "external-key-1", "x-ksi-continuity-fingerprint": value },
    body: JSON.stringify(BODY),
  }), siteContext);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.session.mockReset();
  vi.unstubAllGlobals();
  mocked.origin.mockReturnValue(false);
  coreOrders.clear();
  orderCounter = 0;
  coreCreateCalls = 0;
  installCoreFetchMock();
});

describe("observation work-order account-continuity BFF guard (RED→GREEN)", () => {
  it("blocks a fingerprint-bound retry under another account without creating a second order", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await postFingerprint("token-alice-a", claim)).status).toBe(201);
    expect((await postFingerprint("token-bob-a", claim)).status).toBe(409);
    expect(coreOrders.size).toBe(1);
    expect(coreCreateCalls).toBe(1);
  });

  it("accepts and replays a Core-valid non-path-safe Unicode principal", async () => {
    const claim = fingerprint("org-a", "운영자@example.com");
    const first = await postFingerprint("token-unicode", claim);
    expect(first.status).toBe(201);
    const firstBody = await first.json();
    const retry = await postFingerprint("token-unicode", claim);
    expect(retry.status).toBe(201);
    expect(await retry.json()).toEqual(firstBody);
    expect(coreOrders.size).toBe(1);
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.filter(([url]) => String(url).endsWith("/v1/auth/whoami"))).toHaveLength(2);
  });

  it("refuses a malformed fingerprint before the Core mutation", async () => {
    expect((await postFingerprint("token-alice-a", "not-a-fingerprint")).status).toBe(400);
    expect(coreCreateCalls).toBe(0);
  });

  it.each(["token-whoami-503", "token-whoami-malformed"])("fails closed if the effective identity cannot be read (%s)", async (token) => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await postFingerprint(token, fingerprint("org-a", "alice"));
    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(coreCreateCalls).toBe(0);
    errorLog.mockRestore();
  });

  it("binds identity lookup and mutation to a single captured session token", async () => {
    mocked.session.mockResolvedValueOnce("token-alice-a").mockResolvedValueOnce("token-bob-a");
    const response = await POST(new NextRequest("http://console.test/api/sites/site-a/observation-work-orders", {
      method: "POST",
      headers: { "content-type": "application/json", "Idempotency-Key": "external-key-1", "x-ksi-continuity-fingerprint": fingerprint("org-a", "alice") },
      body: JSON.stringify(BODY),
    }), siteContext);
    expect(response.status).toBe(201);
    expect(mocked.session).toHaveBeenCalledTimes(1);
    expect(coreOrders.has("org-a\0alice\0external-key-1")).toBe(true);
    expect(coreOrders.has("org-a\0bob\0external-key-1")).toBe(false);
  });

  it("blocks a fingerprint-bound retry in another organization", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await postFingerprint("token-alice-a", claim)).status).toBe(201);
    const blocked = await postFingerprint("token-alice-b", claim);
    expect(blocked.status).toBe(409);
    expect(blocked.headers.get("cache-control")).toBe("private, no-store");
    expect(await blocked.json()).not.toHaveProperty("continuity");
    expect(coreCreateCalls).toBe(1);
  });

  it("retains the existing no-header caller behavior", async () => {
    expect((await postAs("token-alice-a", null)).status).toBe(201);
    expect(coreCreateCalls).toBe(1);
  });

  it("rejects a mixture of the new and legacy continuity header forms", async () => {
    mocked.session.mockResolvedValue("token-alice-a");
    const response = await POST(new NextRequest("http://console.test/api/sites/site-a/observation-work-orders", {
      method: "POST",
      headers: { "x-ksi-continuity-fingerprint": fingerprint("org-a", "alice"), "x-ksi-continuity-actor": "alice" },
    }), siteContext);
    expect(response.status).toBe(400);
    expect(coreCreateCalls).toBe(0);
  });

  it("replays the same key/body for the same renewed account without a second Core create", async () => {
    const first = await postAs("token-alice-a", { org: "org-a", actor: "alice" });
    expect(first.status).toBe(201);
    const firstBody = (await first.json()) as { workOrderId: string };

    const retry = await postAs("token-alice-a-renewed", { org: "org-a", actor: "alice" });
    expect(retry.status).toBe(201);
    const retryBody = (await retry.json()) as { workOrderId: string };
    expect(retryBody.workOrderId).toBe(firstBody.workOrderId);
    // Same (org, actor, key) replays the single order.
    expect(coreOrders.size).toBe(1);
  });

  it("must not issue a Core create when the same frozen key is retried as a different account", async () => {
    const first = await postAs("token-alice-a", { org: "org-a", actor: "alice" });
    expect(first.status).toBe(201);
    const createsAfterFirst = coreCreateCalls;

    const crossAccount = await postAs("token-bob-a", { org: "org-a", actor: "alice" });
    expect(crossAccount.status).toBe(409);
    const payload = (await crossAccount.json()) as { code?: string };
    expect(payload.code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    // No second Core order may exist for the same key under a different actor.
    expect(coreOrders.size).toBe(1);
    expect(coreCreateCalls).toBe(createsAfterFirst);
  });

  it("must not issue a Core create when the same frozen key is retried from a different organization", async () => {
    const first = await postAs("token-alice-a", { org: "org-a", actor: "alice" });
    expect(first.status).toBe(201);
    const createsAfterFirst = coreCreateCalls;

    const crossOrg = await postAs("token-alice-b", { org: "org-a", actor: "alice" });
    expect(crossOrg.status).toBe(409);
    expect(((await crossOrg.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(coreOrders.size).toBe(1);
    expect(coreCreateCalls).toBe(createsAfterFirst);
  });

  it("does not trust an attacker-supplied principal header as the effective Core identity", async () => {
    // Attacker as bob claims to be alice in continuity headers but authenticates as bob.
    // The guard must block (mismatch) and must never create an order owned by alice.
    const blocked = await postAs("token-bob-a", { org: "org-a", actor: "alice" });
    expect(blocked.status).toBe(409);
    expect(coreOrders.size).toBe(0);

    // Attacker matching their own identity forwards as themselves, not as the victim.
    const selfMatch = await postAs("token-bob-a", { org: "org-a", actor: "bob" });
    expect(selfMatch.status).toBe(201);
    expect(coreOrders.size).toBe(1);
    expect(coreOrders.has("org-a\0bob\0external-key-1")).toBe(true);
    expect(coreOrders.has("org-a\0alice\0external-key-1")).toBe(false);
  });

  it("fails closed without a Core mutation when identity is missing", async () => {
    const { MissingSessionError } = await import("@/lib/core-api/session");
    mocked.session.mockRejectedValue(new MissingSessionError());
    const before = coreCreateCalls;
    const response = await POST(
      new NextRequest("http://console.test/api/sites/site-a/observation-work-orders", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "Idempotency-Key": "external-key-1",
          "x-ksi-continuity-org": "org-a",
          "x-ksi-continuity-actor": "alice",
        },
        body: JSON.stringify(BODY),
      }),
      siteContext,
    );
    expect(response.status).toBe(401);
    expect(coreOrders.size).toBe(0);
    expect(coreCreateCalls).toBe(before);
  });
});
