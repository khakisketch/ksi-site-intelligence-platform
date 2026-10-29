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

import { POST as assignmentPOST } from "@/app/api/observation-work-orders/[workOrderId]/operations/assignment/route";
import { PUT as dueDatePUT } from "@/app/api/observation-work-orders/[workOrderId]/operations/due-date/route";
import { POST as closePOST } from "@/app/api/observation-work-orders/[workOrderId]/operations/close/route";
import { POST as reopenPOST } from "@/app/api/observation-work-orders/[workOrderId]/operations/reopen/route";
import { PUT as rosterPUT } from "@/app/api/organization-work-roster/[principalId]/route";

// Synthetic identity model, NOT a live Core server: opaque session tokens map to
// fixed (org, actor) pairs only inside the fetch stub below. Every Core URL is
// confined to the synthetic http://core.test host; any other host fails loudly.
const SYNTHETIC_CORE_HOST = "http://core.test";
const TOKEN_ALICE = "synthetic-opaque-token-alice-a-01";
const TOKEN_ALICE_RENEWED = "synthetic-opaque-token-alice-a-02";
const TOKEN_BOB = "synthetic-opaque-token-bob-a-01";
const TOKEN_ALICE_OTHER_ORG = "synthetic-opaque-token-alice-b-01";
const TOKEN_WHOAMI_503 = "synthetic-opaque-token-whoami-503";
const TOKEN_WHOAMI_MALFORMED = "synthetic-opaque-token-whoami-malformed";

function tokenIdentity(token: string | null): { org: string; actor: string } | null {
  if (token === TOKEN_ALICE || token === TOKEN_ALICE_RENEWED) return { org: "org-a", actor: "alice" };
  if (token === TOKEN_BOB) return { org: "org-a", actor: "bob" };
  if (token === TOKEN_ALICE_OTHER_ORG) return { org: "org-b", actor: "alice" };
  return null;
}

function jsonResponse(value: unknown, status: number): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

interface MutationCall {
  url: string;
  token: string | null;
  body: string;
  key: string;
}

let whoamiTokens: Array<string | null>;
let mutationCalls: MutationCall[];

function installSyntheticCoreMock() {
  process.env.CORE_API_BASE_URL = SYNTHETIC_CORE_HOST;
  whoamiTokens = [];
  mutationCalls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!url.startsWith(`${SYNTHETIC_CORE_HOST}/`)) {
        throw new Error(`non-synthetic Core host blocked in test: ${url}`);
      }
      const headers = new Headers(init?.headers as HeadersInit | undefined);
      const auth = headers.get("authorization") ?? "";
      const token = auth.startsWith("Bearer ") ? auth.slice("Bearer ".length) : null;
      if (url.endsWith("/v1/auth/whoami")) {
        whoamiTokens.push(token);
        if (token === TOKEN_WHOAMI_503) return jsonResponse({ detail: "unavailable" }, 503);
        if (token === TOKEN_WHOAMI_MALFORMED) {
          return jsonResponse({ organizationId: "org-a", principalId: null }, 200);
        }
        const who = tokenIdentity(token);
        if (!who) return jsonResponse({ detail: "auth required" }, 401);
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
      const rawBody = typeof init?.body === "string" ? init.body : "";
      const key = headers.get("Idempotency-Key") ?? headers.get("idempotency-key") ?? "";
      mutationCalls.push({ url, token, body: rawBody, key });
      const who = tokenIdentity(token);
      if (!who) return jsonResponse({ detail: "auth required" }, 401);
      return jsonResponse({ ok: true, seenBy: `${who.org}/${who.actor}` }, 200);
    }),
  );
}

function fingerprint(org: string, actor: string): string {
  const material = JSON.stringify(["ksi-observation-continuity-v1", org, actor]);
  return `v1-${createHash("sha256").update(material, "utf8").digest("hex")}`;
}

const ALICE_FINGERPRINT = fingerprint("org-a", "alice");

type RouteDef = {
  name: string;
  method: "POST" | "PUT";
  bffUrl: string;
  coreSuffix: string;
  body: Record<string, unknown>;
  context: { params: Promise<Record<string, string>> };
  handler: (request: NextRequest, context: never) => Promise<Response>;
};

const opsContext = { params: Promise.resolve({ workOrderId: "wo-1" }) };
const rosterContext = { params: Promise.resolve({ principalId: "member-1" }) };

const ROUTES: RouteDef[] = [
  {
    name: "assignment",
    method: "POST",
    bffUrl: "http://console.test/api/observation-work-orders/wo-1/operations/assignment",
    coreSuffix: "/v1/observation-work-orders/wo-1/operations/assignment",
    body: { expectedOperationsRevision: 3, action: "ASSIGN_TO_ME" },
    context: opsContext,
    handler: assignmentPOST as unknown as RouteDef["handler"],
  },
  {
    name: "due-date",
    method: "PUT",
    bffUrl: "http://console.test/api/observation-work-orders/wo-1/operations/due-date",
    coreSuffix: "/v1/observation-work-orders/wo-1/operations/due-date",
    body: { expectedOperationsRevision: 3, dueAt: null },
    context: opsContext,
    handler: dueDatePUT as unknown as RouteDef["handler"],
  },
  {
    name: "close",
    method: "POST",
    bffUrl: "http://console.test/api/observation-work-orders/wo-1/operations/close",
    coreSuffix: "/v1/observation-work-orders/wo-1/operations/close",
    body: { expectedOperationsRevision: 3, note: null },
    context: opsContext,
    handler: closePOST as unknown as RouteDef["handler"],
  },
  {
    name: "reopen",
    method: "POST",
    bffUrl: "http://console.test/api/observation-work-orders/wo-1/operations/reopen",
    coreSuffix: "/v1/observation-work-orders/wo-1/operations/reopen",
    body: { expectedOperationsRevision: 3 },
    context: opsContext,
    handler: reopenPOST as unknown as RouteDef["handler"],
  },
  {
    name: "organization-work-roster",
    method: "PUT",
    bffUrl: "http://console.test/api/organization-work-roster/member-1",
    coreSuffix: "/v1/organization-work-roster/member-1",
    body: { expectedRevision: 0, displayName: "Alice", roleHint: "FIELD_OPERATOR", status: "ACTIVE" },
    context: rosterContext,
    handler: rosterPUT as unknown as RouteDef["handler"],
  },
];

const IDEMPOTENCY_KEY = "guard-key-1";

function callRoute(
  route: RouteDef,
  token: string,
  extraHeaders: Record<string, string> = {},
  body: Record<string, unknown> = route.body,
  key = IDEMPOTENCY_KEY,
) {
  mocked.session.mockResolvedValue(token);
  return route.handler(
    new NextRequest(route.bffUrl, {
      method: route.method,
      headers: {
        "content-type": "application/json",
        "idempotency-key": key,
        ...extraHeaders,
      },
      body: JSON.stringify(body),
    }),
    route.context as never,
  );
}

const continuityHeaders = { "x-ksi-continuity-fingerprint": ALICE_FINGERPRINT };
const legacyMatchHeaders = { "x-ksi-continuity-org": "org-a", "x-ksi-continuity-actor": "alice" };

beforeEach(() => {
  vi.clearAllMocks();
  mocked.session.mockReset();
  vi.unstubAllGlobals();
  mocked.origin.mockReturnValue(false);
  installSyntheticCoreMock();
});

describe("synthetic Core identity model (not a live server)", () => {
  it("confines every Core call to the synthetic host through a mocked fetch", async () => {
    const route = ROUTES[0];
    const response = await callRoute(route, TOKEN_ALICE, continuityHeaders);
    expect(response.status).toBe(200);
    expect(vi.isMockFunction(fetch)).toBe(true);
    const urls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) expect(url.startsWith(`${SYNTHETIC_CORE_HOST}/`)).toBe(true);
  });
});

for (const route of ROUTES) {
  describe(`${route.name} continuity guard`, () => {
    it("forwards the same verified account with the single captured token and unchanged path/body/key", async () => {
      const response = await callRoute(route, TOKEN_ALICE, continuityHeaders);
      expect(response.status).toBe(200);
      expect(mocked.session).toHaveBeenCalledTimes(1);
      expect(whoamiTokens).toEqual([TOKEN_ALICE]);
      expect(mutationCalls).toHaveLength(1);
      const mutation = mutationCalls[0];
      expect(mutation.token).toBe(TOKEN_ALICE);
      expect(mutation.url).toBe(`${SYNTHETIC_CORE_HOST}${route.coreSuffix}`);
      expect(mutation.body).toBe(JSON.stringify(route.body));
      expect(mutation.key).toBe(IDEMPOTENCY_KEY);
      const payload = await response.json();
      expect(JSON.stringify(payload)).not.toContain(TOKEN_ALICE);
      expect(JSON.stringify(payload)).not.toContain(ALICE_FINGERPRINT);
    });

    it("rotates to a fresh token for the same actor without a mismatch", async () => {
      const response = await callRoute(route, TOKEN_ALICE_RENEWED, continuityHeaders);
      expect(response.status).toBe(200);
      expect(whoamiTokens).toEqual([TOKEN_ALICE_RENEWED]);
      expect(mutationCalls).toHaveLength(1);
      expect(mutationCalls[0].token).toBe(TOKEN_ALICE_RENEWED);
    });

    it("blocks a changed actor with 409 and issues no Core mutation", async () => {
      const response = await callRoute(route, TOKEN_BOB, continuityHeaders);
      expect(response.status).toBe(409);
      const payload = (await response.json()) as { code?: string };
      expect(payload.code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(mutationCalls).toHaveLength(0);
    });

    it("blocks a changed organization with 409 and issues no Core mutation", async () => {
      const response = await callRoute(route, TOKEN_ALICE_OTHER_ORG, continuityHeaders);
      expect(response.status).toBe(409);
      expect(((await response.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
      expect(mutationCalls).toHaveLength(0);
    });

    it("fails closed without a mutation when whoami is unavailable", async () => {
      const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
      const response = await callRoute(route, TOKEN_WHOAMI_503, continuityHeaders);
      expect(response.status).toBeGreaterThanOrEqual(500);
      expect(mutationCalls).toHaveLength(0);
      errorLog.mockRestore();
    });

    it("fails closed without a mutation when whoami is malformed", async () => {
      const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
      const response = await callRoute(route, TOKEN_WHOAMI_MALFORMED, continuityHeaders);
      expect(response.status).toBeGreaterThanOrEqual(500);
      expect(mutationCalls).toHaveLength(0);
      errorLog.mockRestore();
    });

    it("rejects a malformed fingerprint with 400 and issues no Core mutation", async () => {
      const response = await callRoute(route, TOKEN_ALICE, {
        "x-ksi-continuity-fingerprint": "not-a-fingerprint",
      });
      expect(response.status).toBe(400);
      expect(mutationCalls).toHaveLength(0);
      expect(whoamiTokens).toHaveLength(0);
    });

    it("rejects conflicting fingerprint and legacy headers with 400 and no mutation", async () => {
      const response = await callRoute(route, TOKEN_ALICE, {
        "x-ksi-continuity-fingerprint": ALICE_FINGERPRINT,
        "x-ksi-continuity-actor": "alice",
      });
      expect(response.status).toBe(400);
      expect(mutationCalls).toHaveLength(0);
    });

    it("keeps absent-header compatibility and forwards with the session token", async () => {
      const response = await callRoute(route, TOKEN_ALICE, {});
      expect(response.status).toBe(200);
      expect(whoamiTokens).toHaveLength(0);
      expect(mutationCalls).toHaveLength(1);
      expect(mutationCalls[0].token).toBe(TOKEN_ALICE);
      expect(mutationCalls[0].url).toBe(`${SYNTHETIC_CORE_HOST}${route.coreSuffix}`);
    });

    it("accepts the legacy org/actor pair for the same verified account", async () => {
      const response = await callRoute(route, TOKEN_ALICE, legacyMatchHeaders);
      expect(response.status).toBe(200);
      expect(whoamiTokens).toEqual([TOKEN_ALICE]);
      expect(mutationCalls).toHaveLength(1);
      expect(mutationCalls[0].token).toBe(TOKEN_ALICE);
    });

    it("blocks a legacy pair that names a different account than the session token", async () => {
      const response = await callRoute(route, TOKEN_BOB, legacyMatchHeaders);
      expect(response.status).toBe(409);
      expect(mutationCalls).toHaveLength(0);
    });
  });
}
