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

import { POST as postSingle } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/use-decisions/single/route";
import { POST as postPair } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/use-decisions/pair/route";
import { POST as postSingleVolume } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/use-decisions/single-volume/route";

const submission = `ers-v1-${"a".repeat(64)}`;
const baselineSubmission = `ers-v1-${"c".repeat(64)}`;
const context = {
  params: Promise.resolve({ workOrderId: "work-1", submissionRef: submission, revision: "1" }),
};
const BODIES = {
  single: { use: "DISPLAY" },
  pair: {
    use: "VISUAL_COMPARISON",
    baselineWorkOrderId: "work-2",
    baselineSubmissionRef: baselineSubmission,
    baselineRevision: 2,
  },
  "single-volume": { zoneId: "wa-1" },
} as const;
type RouteKind = keyof typeof BODIES;
const POSTS = { single: postSingle, pair: postPair, "single-volume": postSingleVolume } as const;
const PATHS = { single: "single", pair: "pair", "single-volume": "single-volume" } as const;

// Simulated Core actor-scoped idempotency: (org, actor, key) -> decision.
// Production Core scopes to (organization_id, actor, key_hash); the same raw
// key as a different account/org creates a second decision. This mock
// reproduces that scoping so the BFF guard can be verified without a live Core.
const coreDecisions = new Map<string, { decisionId: string; fingerprint: string }>();
let decisionCounter = 0;
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
      const decisionMatch = /\/use-decisions\/(single|pair|single-volume)$/.exec(url);
      if (decisionMatch && (init?.method ?? "GET") === "POST") {
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        coreCreateCalls += 1;
        const idemKey = headers.get("Idempotency-Key") ?? headers.get("idempotency-key") ?? "";
        const rawBody = typeof init?.body === "string" ? init.body : "";
        const mapKey = `${who.org}\0${who.actor}\0${idemKey}`;
        const existing = coreDecisions.get(mapKey);
        if (existing) {
          if (existing.fingerprint !== rawBody) {
            return jsonResponse({ detail: "Idempotency-Key가 다른 결정 본문에 이미 사용됐다" }, 409);
          }
          return jsonResponse({ decision: { decisionId: existing.decisionId } }, 201);
        }
        decisionCounter += 1;
        const createdId = `external-use-decision-${String(decisionCounter).padStart(32, "0")}`;
        coreDecisions.set(mapKey, { decisionId: createdId, fingerprint: rawBody });
        return jsonResponse({ decision: { decisionId: createdId } }, 201);
      }
      return jsonResponse({ detail: "not found" }, 404);
    }),
  );
}

function postAs(kind: RouteKind, token: string, fingerprint: string | null, key = "decision-key-1") {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "Idempotency-Key": key,
  };
  if (fingerprint !== null) headers["x-ksi-continuity-fingerprint"] = fingerprint;
  mocked.session.mockResolvedValue(token);
  return POSTS[kind](
    new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submission}/revisions/1/use-decisions/${PATHS[kind]}`, {
      method: "POST",
      headers,
      body: JSON.stringify(BODIES[kind]),
    }),
    context,
  );
}

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.session.mockReset();
  vi.unstubAllGlobals();
  mocked.origin.mockReturnValue(false);
  coreDecisions.clear();
  decisionCounter = 0;
  coreCreateCalls = 0;
  installCoreFetchMock();
});

describe.each(["single", "pair", "single-volume"] as const)("external use-decision account-continuity BFF guard (%s)", (kind) => {
  it("forwards a downstream same-code 400 without proving it was a local refusal", async () => {
    const codes: Record<RouteKind, string> = {
      single: "INVALID_EXTERNAL_USE_INTENT",
      pair: "INVALID_EXTERNAL_PAIR_INTENT",
      "single-volume": "INVALID_EXTERNAL_SINGLE_VOLUME_INTENT",
    };
    const downstream = vi.fn(async () => jsonResponse({ detail: codes[kind] }, 400));
    vi.stubGlobal("fetch", downstream);
    const result = await postAs(kind, "token-alice-a", null);
    expect(result.status).toBe(400);
    expect(await result.json()).toEqual(expect.objectContaining({ code: codes[kind] }));
    expect(downstream).toHaveBeenCalledOnce();
  });

  it("blocks a fingerprint-bound retry under another account without creating a second decision", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await postAs(kind, "token-alice-a", claim)).status).toBe(201);
    expect((await postAs(kind, "token-bob-a", claim)).status).toBe(409);
    expect(coreDecisions.size).toBe(1);
    expect(coreCreateCalls).toBe(1);
  });

  it("accepts and replays a Core-valid non-path-safe Unicode principal", async () => {
    const claim = fingerprint("org-a", "운영자@example.com");
    const first = await postAs(kind, "token-unicode", claim);
    expect(first.status).toBe(201);
    const firstBody = await first.json();
    const retry = await postAs(kind, "token-unicode", claim);
    expect(retry.status).toBe(201);
    expect(await retry.json()).toEqual(firstBody);
    expect(coreDecisions.size).toBe(1);
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.filter(([url]) => String(url).endsWith("/v1/auth/whoami")).length).toBeGreaterThanOrEqual(2);
  });

  it("refuses a malformed fingerprint before the Core mutation", async () => {
    expect((await postAs(kind, "token-alice-a", "not-a-fingerprint")).status).toBe(400);
    expect(coreCreateCalls).toBe(0);
  });

  it.each(["token-whoami-503", "token-whoami-malformed"])("fails closed if the effective identity cannot be read (%s)", async (token) => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await postAs(kind, token, fingerprint("org-a", "alice"));
    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(coreCreateCalls).toBe(0);
    errorLog.mockRestore();
  });

  it("binds identity lookup and mutation to a single captured session token", async () => {
    mocked.session.mockResolvedValueOnce("token-alice-a").mockResolvedValueOnce("token-bob-a");
    const response = await POSTS[kind](new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submission}/revisions/1/use-decisions/${PATHS[kind]}`, {
      method: "POST",
      headers: { "content-type": "application/json", "Idempotency-Key": "decision-key-1", "x-ksi-continuity-fingerprint": fingerprint("org-a", "alice") },
      body: JSON.stringify(BODIES[kind]),
    }), context);
    expect(response.status).toBe(201);
    expect(mocked.session).toHaveBeenCalledTimes(1);
    expect(coreDecisions.has("org-a\0alice\0decision-key-1")).toBe(true);
    expect(coreDecisions.has("org-a\0bob\0decision-key-1")).toBe(false);
  });

  it("blocks a fingerprint-bound retry in another organization", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await postAs(kind, "token-alice-a", claim)).status).toBe(201);
    const blocked = await postAs(kind, "token-alice-b", claim);
    expect(blocked.status).toBe(409);
    expect(blocked.headers.get("cache-control")).toBe("private, no-store");
    expect(await blocked.json()).not.toHaveProperty("continuity");
    expect(coreCreateCalls).toBe(1);
  });

  it("retains the existing no-header caller behavior", async () => {
    expect((await postAs(kind, "token-alice-a", null)).status).toBe(201);
    expect(coreCreateCalls).toBe(1);
  });

  it("rejects a mixture of the new and legacy continuity header forms", async () => {
    mocked.session.mockResolvedValue("token-alice-a");
    const response = await POSTS[kind](new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submission}/revisions/1/use-decisions/${PATHS[kind]}`, {
      method: "POST",
      headers: { "x-ksi-continuity-fingerprint": fingerprint("org-a", "alice"), "x-ksi-continuity-actor": "alice" },
    }), context);
    expect(response.status).toBe(400);
    expect(coreCreateCalls).toBe(0);
  });

  it("replays the same key/body for the same renewed account without a second Core create", async () => {
    const first = await postAs(kind, "token-alice-a", fingerprint("org-a", "alice"));
    expect(first.status).toBe(201);
    const firstBody = (await first.json()) as { decision: { decisionId: string } };

    const retry = await postAs(kind, "token-alice-a-renewed", fingerprint("org-a", "alice"));
    expect(retry.status).toBe(201);
    const retryBody = (await retry.json()) as { decision: { decisionId: string } };
    expect(retryBody.decision.decisionId).toBe(firstBody.decision.decisionId);
    // Same (org, actor, key) replays the single decision.
    expect(coreDecisions.size).toBe(1);
  });

  it("must not issue a Core create when the same frozen key is retried under a different account", async () => {
    const first = await postAs(kind, "token-alice-a", fingerprint("org-a", "alice"));
    expect(first.status).toBe(201);
    const createsAfterFirst = coreCreateCalls;

    const crossAccount = await postAs(kind, "token-bob-a", fingerprint("org-a", "alice"));
    expect(crossAccount.status).toBe(409);
    const payload = (await crossAccount.json()) as { code?: string };
    expect(payload.code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    // No second Core decision may exist for the same key under a different actor.
    expect(coreDecisions.size).toBe(1);
    expect(coreCreateCalls).toBe(createsAfterFirst);
  });

  it("does not trust an attacker-supplied principal header as the effective Core identity", async () => {
    // Attacker as bob claims to be alice in continuity headers but authenticates as bob.
    // The guard must block (mismatch) and must never create a decision owned by alice.
    const blocked = await postAs(kind, "token-bob-a", fingerprint("org-a", "alice"));
    expect(blocked.status).toBe(409);
    expect(coreDecisions.size).toBe(0);

    // Attacker matching their own identity forwards as themselves, not as the victim.
    const selfMatch = await postAs(kind, "token-bob-a", fingerprint("org-a", "bob"));
    expect(selfMatch.status).toBe(201);
    expect(coreDecisions.size).toBe(1);
    expect(coreDecisions.has("org-a\0bob\0decision-key-1")).toBe(true);
    expect(coreDecisions.has("org-a\0alice\0decision-key-1")).toBe(false);
  });

  it("fails closed without a Core mutation when identity is missing", async () => {
    const { MissingSessionError } = await import("@/lib/core-api/session");
    mocked.session.mockRejectedValue(new MissingSessionError());
    const before = coreCreateCalls;
    const response = await POSTS[kind](
      new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submission}/revisions/1/use-decisions/${PATHS[kind]}`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "Idempotency-Key": "decision-key-1",
          "x-ksi-continuity-fingerprint": fingerprint("org-a", "alice"),
        },
        body: JSON.stringify(BODIES[kind]),
      }),
      context,
    );
    expect(response.status).toBe(401);
    expect(coreDecisions.size).toBe(0);
    expect(coreCreateCalls).toBe(before);
  });
});
