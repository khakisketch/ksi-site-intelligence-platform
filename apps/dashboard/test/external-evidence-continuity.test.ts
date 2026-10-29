/** @vitest-environment node */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createHash } from "node:crypto";

const mocked = vi.hoisted(() => ({ session: vi.fn(), origin: vi.fn() }));

vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...original, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));

import { POST as declareEvidence } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/evidence/route";
import { POST as grantUpload } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/evidence/[evidenceRef]/upload-grant/route";
import { POST as sealEvidence } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/evidence/[evidenceRef]/seal/route";

const submissionRef = `ers-v1-${"a".repeat(64)}`;
const evidenceRef = `eev-v1-${"e".repeat(64)}`;
const declareContext = {
  params: Promise.resolve({ workOrderId: "work-1", submissionRef, revision: "1" }),
} as never;
const evidenceContext = {
  params: Promise.resolve({ workOrderId: "work-1", submissionRef, revision: "1", evidenceRef }),
} as never;
const declareBody = {
  targetDsmArtifactId: "dsm",
  declaredContentDigest: `sha256:${"b".repeat(64)}`,
  declaredContentType: "text/csv",
  independenceBasis: "separate survey",
};

// Simulated Core actor-scoped idempotency: (org, actor, key) -> record.
// Production Core scopes mutations to the authenticated actor; the same raw
// key as a different account/org creates a second record. This mock
// reproduces that scoping so the BFF guard can be verified without live Core.
const coreRecords = new Map<string, string>();
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
      const evidenceMatch = /\/evidence(?!.*upload-grant)(?!.*seal)$/.exec(url);
      if (evidenceMatch && (init?.method ?? "GET") === "POST") {
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        coreCreateCalls += 1;
        const idemKey = headers.get("Idempotency-Key") ?? headers.get("idempotency-key") ?? "";
        const mapKey = `${who.org}\0${who.actor}\0${idemKey}`;
        const existing = coreRecords.get(mapKey);
        if (existing) return jsonResponse({ evidenceRef: existing, state: "DECLARED" }, 201);
        const created = `eev-v1-${String(coreCreateCalls).padStart(64, "0").slice(-64)}`;
        coreRecords.set(mapKey, created);
        return jsonResponse({ evidenceRef: created, state: "DECLARED" }, 201);
      }
      if (/\/upload-grant$/.exec(url) && (init?.method ?? "GET") === "POST") {
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        coreCreateCalls += 1;
        return jsonResponse({ evidenceRef, uploadUrl: "https://upload.test/evidence", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} }, 200);
      }
      if (/\/seal$/.exec(url) && (init?.method ?? "GET") === "POST") {
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        coreCreateCalls += 1;
        return jsonResponse({ evidenceRef, state: "SEALED_BYTE_OBSERVED" }, 200);
      }
      return jsonResponse({ detail: "not found" }, 404);
    }),
  );
}

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

function declareAs(token: string, fp: string | null, key = "evidence-key-1") {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "Idempotency-Key": key,
  };
  if (fp !== null) headers["x-ksi-continuity-fingerprint"] = fp;
  mocked.session.mockResolvedValue(token);
  return declareEvidence(
    new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submissionRef}/revisions/1/evidence`, {
      method: "POST",
      headers,
      body: JSON.stringify(declareBody),
    }),
    declareContext,
  );
}

function grantAs(token: string, fp: string | null, key = "evidence-key-2") {
  const headers: Record<string, string> = { "Idempotency-Key": key };
  if (fp !== null) headers["x-ksi-continuity-fingerprint"] = fp;
  mocked.session.mockResolvedValue(token);
  return grantUpload(
    new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submissionRef}/revisions/1/evidence/${evidenceRef}/upload-grant`, {
      method: "POST",
      headers,
      body: JSON.stringify({}),
    }),
    evidenceContext,
  );
}

function sealAs(token: string, fp: string | null, key = "evidence-key-3") {
  const headers: Record<string, string> = { "Idempotency-Key": key };
  if (fp !== null) headers["x-ksi-continuity-fingerprint"] = fp;
  mocked.session.mockResolvedValue(token);
  return sealEvidence(
    new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submissionRef}/revisions/1/evidence/${evidenceRef}/seal`, {
      method: "POST",
      headers,
      body: JSON.stringify({}),
    }),
    evidenceContext,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.session.mockReset();
  vi.unstubAllGlobals();
  mocked.origin.mockReturnValue(false);
  coreRecords.clear();
  coreCreateCalls = 0;
  installCoreFetchMock();
});

describe("external evidence account-continuity BFF guard", () => {
  it("blocks a fingerprint-bound declaration retry under another account without a second Core record", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await declareAs("token-alice-a", claim)).status).toBe(201);
    expect((await declareAs("token-bob-a", claim)).status).toBe(409);
    expect(coreRecords.size).toBe(1);
    expect(coreCreateCalls).toBe(1);
  });

  it("blocks fingerprint-bound grant and seal retries under another account without Core mutations", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await grantAs("token-alice-a", claim)).status).toBe(200);
    expect((await sealAs("token-alice-a", claim)).status).toBe(200);
    const createsAfterFirst = coreCreateCalls;
    expect((await grantAs("token-bob-a", claim)).status).toBe(409);
    expect((await sealAs("token-bob-a", claim)).status).toBe(409);
    expect(coreCreateCalls).toBe(createsAfterFirst);
  });

  it("blocks a grant-stage account switch after a lost grant response without a second Core grant", async () => {
    // BFF 직접 경계 테스트. fetch mock은 actor 범위로 묶인 Core를 흉내낸다.
    // PUT는 클라이언트→스토리지 경로라 여기서 증명하지 않는다 — PUT/seal
    // 미발생은 화면층 테스트에서 확인한다.
    const claim = fingerprint("org-a", "alice");
    // 원래 계정의 선언·승인. 승인 응답은 화면에 닿기 전에 유실됐다고 가정하고,
    // 같은 키의 재시도부터 실행한다.
    expect((await declareAs("token-alice-a", claim, "declare-chain-1")).status).toBe(201);
    expect((await grantAs("token-alice-a", claim, "grant-chain-1")).status).toBe(200);
    expect(coreCreateCalls).toBe(2);
    // 같은 키 grant 재시도 직전에 세션이 다른 계정으로 바뀌었다. BFF는 Core
    // 승인 없이 409로 끊고 원래 키·내용을 살린다.
    const blocked = await grantAs("token-bob-a", claim, "grant-chain-1");
    expect(blocked.status).toBe(409);
    expect((await blocked.json()).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(coreCreateCalls).toBe(2);
    expect(coreRecords.has("org-a\0bob\0grant-chain-1")).toBe(false);
    // 원래 계정으로 돌아오면 같은 선언·키로 이어간다.
    expect((await grantAs("token-alice-a-renewed", claim, "grant-chain-1")).status).toBe(200);
    expect((await sealAs("token-alice-a", claim, "seal-chain-1")).status).toBe(200);
    expect(coreCreateCalls).toBe(4);
  });

  it("blocks a grant retry under a changed organization without a Core mutation", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await declareAs("token-alice-a", claim, "declare-org-1")).status).toBe(201);
    expect((await grantAs("token-alice-a", claim, "grant-org-1")).status).toBe(200);
    const createsAfterFirst = coreCreateCalls;
    // 같은 행위자 이름이라도 조직이 바뀌면 다른 연속성이다.
    const blocked = await grantAs("token-alice-b", claim, "grant-org-1");
    expect(blocked.status).toBe(409);
    expect((await blocked.json()).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(coreCreateCalls).toBe(createsAfterFirst);
  });

  it("fails closed without a Core grant when the session identity is unavailable", async () => {
    const claim = fingerprint("org-a", "alice");
    mocked.session.mockResolvedValue("token-unknown");
    const response = await grantUpload(
      new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submissionRef}/revisions/1/evidence/${evidenceRef}/upload-grant`, {
        method: "POST",
        headers: { "Idempotency-Key": "grant-unknown-1", "x-ksi-continuity-fingerprint": claim },
        body: JSON.stringify({}),
      }),
      evidenceContext,
    );
    expect(response.status).toBe(401);
    expect(coreCreateCalls).toBe(0);
  });

  it("refuses a malformed fingerprint before any Core mutation", async () => {
    expect((await declareAs("token-alice-a", "not-a-fingerprint")).status).toBe(400);
    expect((await grantAs("token-alice-a", "not-a-fingerprint")).status).toBe(400);
    expect((await sealAs("token-alice-a", "not-a-fingerprint")).status).toBe(400);
    expect(coreCreateCalls).toBe(0);
  });

  it("retains the existing no-header caller behavior", async () => {
    expect((await declareAs("token-alice-a", null)).status).toBe(201);
    expect((await grantAs("token-alice-a", null)).status).toBe(200);
    expect((await sealAs("token-alice-a", null)).status).toBe(200);
  });

  it("replays the same key for the same renewed account without a second Core record", async () => {
    const claim = fingerprint("org-a", "alice");
    const first = await declareAs("token-alice-a", claim);
    expect(first.status).toBe(201);
    const retry = await declareAs("token-alice-a-renewed", claim);
    expect(retry.status).toBe(201);
    expect(coreRecords.size).toBe(1);
  });

  it("binds identity lookup and mutation to a single captured session token", async () => {
    mocked.session.mockResolvedValueOnce("token-alice-a").mockResolvedValueOnce("token-bob-a");
    const response = await declareEvidence(
      new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${submissionRef}/revisions/1/evidence`, {
        method: "POST",
        headers: { "content-type": "application/json", "Idempotency-Key": "evidence-key-1", "x-ksi-continuity-fingerprint": fingerprint("org-a", "alice") },
        body: JSON.stringify(declareBody),
      }),
      declareContext,
    );
    expect(response.status).toBe(201);
    expect(mocked.session).toHaveBeenCalledTimes(1);
    expect(coreRecords.has("org-a\0alice\0evidence-key-1")).toBe(true);
    expect(coreRecords.has("org-a\0bob\0evidence-key-1")).toBe(false);
  });
});
