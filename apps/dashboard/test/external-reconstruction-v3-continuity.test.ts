/** @vitest-environment node */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createHash } from "node:crypto";

const mocked = vi.hoisted(() => ({ session: vi.fn(), origin: vi.fn() }));

vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));

import { POST as registerV3 } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions-v3/route";
import { POST as requestGrants } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/upload-grants/route";
import { POST as sealRevision } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/seal/route";

const TOKEN_ALICE = "synthetic-token-alice-a";
const TOKEN_ALICE_RENEWED = "synthetic-token-alice-a-renewed";
const TOKEN_BOB = "synthetic-token-bob-a";
const TOKEN_ALICE_OTHER_ORG = "synthetic-token-alice-b";
const TOKEN_UNKNOWN = "synthetic-token-unknown";
const TOKEN_WHOAMI_DOWN = "synthetic-token-whoami-down";

function tokenIdentity(token: string | null): { org: string; actor: string } | null {
  if (token === TOKEN_ALICE || token === TOKEN_ALICE_RENEWED) return { org: "org-a", actor: "alice" };
  if (token === TOKEN_BOB) return { org: "org-a", actor: "bob" };
  if (token === TOKEN_ALICE_OTHER_ORG) return { org: "org-b", actor: "alice" };
  return null;
}

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

const FP_ALICE = fingerprint("org-a", "alice");

function jsonResponse(value: unknown, status: number): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

type StoredRecord = { submission: Record<string, unknown>; ref: string; sealed: boolean };
const store = new Map<string, StoredRecord>();
let mutationCalls = 0;
let readCalls = 0;
// Phase-boundary fault injection (test-only): commute the Core verdict and the
// transport outcome independently so the POST phase and the recovery-list phase
// can fail in different ways.
let dropRegisterResponse = false;
let failRegisterTransport = false;
let forcedRegisterFailure: { status: number; body: unknown } | null = null;
let listFailureStatus: number | null = null;
let listFailureFromCall = Number.POSITIVE_INFINITY;
let hideRecoveryList = false;
let listCalls = 0;

function submissionRefFor(org: string, workOrderId: string, submissionId: string): string {
  return `ers-v1-${createHash("sha256").update(`${org}:${workOrderId}:${submissionId}`).digest("hex")}`;
}

function installSyntheticCoreMock() {
  process.env.CORE_API_BASE_URL = "http://core.test";
  store.clear();
  mutationCalls = 0;
  readCalls = 0;
  dropRegisterResponse = false;
  failRegisterTransport = false;
  forcedRegisterFailure = null;
  listFailureStatus = null;
  listFailureFromCall = Number.POSITIVE_INFINITY;
  hideRecoveryList = false;
  listCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!url.startsWith("http://core.test/")) {
        throw new Error(`non-synthetic Core host blocked in test: ${url}`);
      }
      const headers = new Headers(init?.headers as HeadersInit | undefined);
      const auth = headers.get("authorization") ?? "";
      const token = auth.startsWith("Bearer ") ? auth.slice("Bearer ".length) : null;
      const method = (init?.method ?? "GET").toUpperCase();
      const who = token === TOKEN_WHOAMI_DOWN ? null : tokenIdentity(token);

      if (url.endsWith("/v1/auth/whoami")) {
        readCalls += 1;
        if (token === TOKEN_WHOAMI_DOWN) return jsonResponse({ detail: "unavailable" }, 503);
        if (!who) return jsonResponse({ detail: "auth required" }, 401);
        return jsonResponse(
          {
            principalId: who.actor,
            organizationId: who.org,
            kind: "OPERATOR",
            role: "FIELD_OPERATOR",
            deviceId: null,
            permissions: ["SITES_READ", "SITES_WRITE"],
          },
          200,
        );
      }

      const workOrderMatch = /\/v1\/observation-work-orders\/([^/]+)$/.exec(url);
      if (workOrderMatch && method === "GET") {
        readCalls += 1;
        if (!who) return jsonResponse({ detail: "auth required" }, 401);
        const workOrderId = decodeURIComponent(workOrderMatch[1]);
        if (workOrderId !== "work-1" || who.org !== "org-a") {
          return jsonResponse({ detail: "NOT_FOUND" }, 404);
        }
        return jsonResponse(
          {
            workOrderId: "work-1",
            organizationId: "org-a",
            siteId: "site-1",
            cycleNumber: 1,
            version: 2,
            executionMode: "MANAGED_ACQUISITION",
          },
          200,
        );
      }

      if (url.endsWith("/external-reconstruction-context") && method === "GET") {
        readCalls += 1;
        if (!who) return jsonResponse({ detail: "auth required" }, 401);
        if (who.org !== "org-a") return jsonResponse({ detail: "NOT_FOUND" }, 404);
        return jsonResponse(
          {
            workOrderId: "work-1",
            siteId: "site-1",
            expectedEpochId: "epoch-1",
            cycleNumber: 1,
            workOrderVersion: 2,
            executionMode: "MANAGED_ACQUISITION",
          },
          200,
        );
      }

      if (/\/external-reconstruction-submissions$/.exec(url) && method === "GET") {
        readCalls += 1;
        listCalls += 1;
        if (listFailureStatus !== null && listCalls >= listFailureFromCall) {
          return jsonResponse({ detail: "LIST_FAILED" }, listFailureStatus);
        }
        if (!who) return jsonResponse({ detail: "auth required" }, 401);
        if (hideRecoveryList && listCalls >= 2) return jsonResponse({ submissions: [] }, 200);
        const items = [...store.values()]
          .filter((record) => (record.submission.organizationId as string) === who.org)
          .map((record) => ({ submissionRef: record.ref, submission: record.submission, state: record.sealed ? "SEALED" : "REGISTERED", manifest: null }));
        return jsonResponse({ submissions: items }, 200);
      }

      if (url.endsWith("/external-reconstruction-submissions-v3") && method === "POST") {
        if (!who) return jsonResponse({ detail: "auth required" }, 401);
        if (failRegisterTransport) throw new TypeError("connection lost before commit");
        if (forcedRegisterFailure) {
          return jsonResponse(forcedRegisterFailure.body, forcedRegisterFailure.status);
        }
        const candidate = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        // Core actor semantics (read-only reference): the stored submittedBy must
        // equal the bearer principal or registration is a 422, never a silent
        // re-attribution. BFF must therefore bind whoami and mutation to one token.
        if (candidate.submittedBy !== who.actor) {
          return jsonResponse({ detail: "BAD_DECLARATION" }, 422);
        }
        if (candidate.organizationId !== who.org || candidate.siteId !== "site-1" || candidate.observationEpochId !== "epoch-1") {
          return jsonResponse({ detail: "BAD_DECLARATION" }, 422);
        }
        mutationCalls += 1;
        const key = `work-1\0${candidate.submissionId as string}`;
        const existing = store.get(key);
        if (existing) {
          if (existing.submission.submissionDigest === candidate.submissionDigest) {
            return jsonResponse(
              { submissionRef: existing.ref, submission: existing.submission, state: existing.sealed ? "SEALED" : "REGISTERED", manifest: null },
              201,
            );
          }
          return jsonResponse({ detail: "CONFLICT" }, 409);
        }
        const ref = submissionRefFor(who.org, "work-1", candidate.submissionId as string);
        store.set(key, { submission: candidate, ref, sealed: false });
        if (dropRegisterResponse) throw new TypeError("connection lost after commit");
        return jsonResponse(
          { submissionRef: ref, submission: candidate, state: "REGISTERED", manifest: null },
          201,
        );
      }

      const grantMatch = /\/revisions\/(\d+)\/upload-grants$/.exec(url);
      if (grantMatch && method === "POST") {
        if (!who) return jsonResponse({ detail: "auth required" }, 401);
        mutationCalls += 1;
        const record = [...store.values()].find(
          (item) => item.ref === decodeURIComponent(/\/([^/]+)\/revisions\//.exec(url)![1]) && (item.submission.organizationId as string) === who.org,
        );
        if (!record) return jsonResponse({ detail: "NOT_FOUND" }, 404);
        const artifacts = record.submission.artifacts as Array<{ artifactId: string }>;
        return jsonResponse(
          {
            grants: artifacts.map((artifact) => ({
              artifactId: artifact.artifactId,
              objectKey: `org-a/site-1/work-1/${artifact.artifactId}.tif`,
              uploadUrl: "https://upload.test/put",
              requiredHeaders: {},
            })),
          },
          200,
        );
      }

      const sealMatch = /\/revisions\/(\d+)\/seal$/.exec(url);
      if (sealMatch && method === "POST") {
        if (!who) return jsonResponse({ detail: "auth required" }, 401);
        mutationCalls += 1;
        const record = [...store.values()].find(
          (item) => item.ref === decodeURIComponent(/\/([^/]+)\/revisions\//.exec(url)![1]) && (item.submission.organizationId as string) === who.org,
        );
        if (!record) return jsonResponse({ detail: "NOT_FOUND" }, 404);
        record.sealed = true;
        return jsonResponse(
          { submissionRef: record.ref, submission: record.submission, state: "SEALED", manifest: { sealed: true } },
          200,
        );
      }

      return jsonResponse({ detail: "not found" }, 404);
    }),
  );
}

const hex = (value: string) => value.repeat(64);
const orthoArtifact = {
  artifactId: "ortho",
  kind: "ortho",
  fileName: "ortho.tif",
  format: "GeoTIFF",
  contentType: "application/octet-stream",
  declaredSha256: hex("a"),
  declaredSizeBytes: 1,
  declaredCrs: null,
  declaredVerticalReference: null,
  declaredGsdM: null,
};
const v3Body = {
  softwareName: "ODM",
  softwareVersion: "1.2.3",
  sourceNote: null,
  producerKnowledge: "DECLARED",
  submissionId: "attempt-1",
  expectedEpochId: "epoch-1",
  submittedAt: "2026-09-08T01:02:03Z",
  captureBasis: "EXACT_INTERVAL",
  captureStartedAt: "2026-09-08T01:00:00Z",
  captureEndedAt: "2026-09-08T01:10:00Z",
  captureDate: null,
  originalRetentionLocus: "customer_workstation",
  originalRetentionDetail: null,
  upstreamSource: null,
  derivativeExport: null,
  artifacts: [orthoArtifact],
};

const v3Context = { params: Promise.resolve({ workOrderId: "work-1" }) } as never;

function postV3(token: string | null, fp: string | null, payload: unknown = v3Body) {
  if (token !== null) mocked.session.mockResolvedValue(token);
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (fp !== null) headers["x-ksi-continuity-fingerprint"] = fp;
  return registerV3(
    new NextRequest("http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions-v3", {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    }),
    v3Context,
  );
}

function grantsContextFor(ref: string) {
  return { params: Promise.resolve({ workOrderId: "work-1", submissionRef: ref, revision: "1" }) } as never;
}

function postGrants(token: string, fp: string | null, ref: string) {
  mocked.session.mockResolvedValue(token);
  const headers: Record<string, string> = {};
  if (fp !== null) headers["x-ksi-continuity-fingerprint"] = fp;
  return requestGrants(
    new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${ref}/revisions/1/upload-grants`, {
      method: "POST",
      headers,
      body: JSON.stringify({}),
    }),
    grantsContextFor(ref),
  );
}

function postSeal(token: string, fp: string | null, ref: string) {
  mocked.session.mockResolvedValue(token);
  const headers: Record<string, string> = {};
  if (fp !== null) headers["x-ksi-continuity-fingerprint"] = fp;
  return sealRevision(
    new NextRequest(`http://console.test/api/observation-work-orders/work-1/external-reconstruction-submissions/${ref}/revisions/1/seal`, {
      method: "POST",
      headers,
      body: JSON.stringify({}),
    }),
    grantsContextFor(ref),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.session.mockReset();
  vi.unstubAllGlobals();
  mocked.origin.mockReturnValue(false);
  installSyntheticCoreMock();
});

describe("V3 registration cross-account defect and guard", () => {
  it("documents the legacy gap: without a fingerprint, B mints a B-owned record under A's frozen submissionId", async () => {
    // A의 첫 요청이 Core에 닿기 전 유실됐다고 가정하고 B가 같은 동결 body로 재시도한다.
    const created = await postV3(TOKEN_BOB, null);
    expect(created.status).toBe(201);
    const stored = store.get("work-1\0attempt-1")!;
    expect(stored.submission.submittedBy).toBe("bob");
    // A가 원래 계정으로 같은 식별자를 살리려 하면 영구 CONFLICT가 된다.
    const poisoned = await postV3(TOKEN_ALICE, null);
    expect(poisoned.status).toBe(409);
  });

  it("binds identity lookup and mutation to a single captured session token", async () => {
    mocked.session.mockResolvedValueOnce(TOKEN_ALICE).mockResolvedValue(TOKEN_BOB);
    const response = await postV3(TOKEN_ALICE, FP_ALICE);
    expect(response.status).toBe(201);
    expect(mocked.session).toHaveBeenCalledTimes(1);
    expect(store.get("work-1\0attempt-1")!.submission.submittedBy).toBe("alice");
  });

  it("blocks a frozen-fingerprint retry under another account before any Core mutation", async () => {
    expect((await postV3(TOKEN_ALICE, FP_ALICE)).status).toBe(201);
    const mutationsAfterAlice = mutationCalls;
    // 동결 시점의 A 지문을 그대로 들고 B 세션으로 재시도한다.
    const blocked = await postV3(TOKEN_BOB, FP_ALICE);
    expect(blocked.status).toBe(409);
    expect(((await blocked.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(blocked.headers.get("cache-control")).toBe("private, no-store");
    expect(mutationCalls).toBe(mutationsAfterAlice);
    expect(store.get("work-1\0attempt-1")!.submission.submittedBy).toBe("alice");
    // 원래 계정(토큰만 갱신)으로 돌아오면 같은 식별자로 이어간다 — prior가
    // 그대로 있으므로 새 Core 변이 없이 200으로 복구되는 것이 정상이다.
    const resumed = await postV3(TOKEN_ALICE_RENEWED, FP_ALICE);
    expect(resumed.status).toBe(200);
    expect(store.get("work-1\0attempt-1")!.submission.submittedBy).toBe("alice");
    expect(mutationCalls).toBe(mutationsAfterAlice);
  });

  it("blocks a changed organization before any Core mutation", async () => {
    expect((await postV3(TOKEN_ALICE, FP_ALICE)).status).toBe(201);
    const mutationsAfterAlice = mutationCalls;
    const blocked = await postV3(TOKEN_ALICE_OTHER_ORG, FP_ALICE);
    expect(blocked.status).toBe(409);
    expect(((await blocked.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(mutationCalls).toBe(mutationsAfterAlice);
  });

  it("refuses a malformed fingerprint before any Core call", async () => {
    const response = await postV3(TOKEN_ALICE, "not-a-fingerprint");
    expect(response.status).toBe(400);
    expect(mutationCalls).toBe(0);
    expect(readCalls).toBe(0);
  });

  it("fails closed without a Core mutation when the session identity is unavailable", async () => {
    mocked.session.mockResolvedValue(TOKEN_UNKNOWN);
    const response = await postV3(TOKEN_UNKNOWN, FP_ALICE);
    expect(response.status).toBe(401);
    expect(mutationCalls).toBe(0);
  });

  it("fails closed without a Core mutation when whoami is unavailable", async () => {
    const response = await postV3(TOKEN_WHOAMI_DOWN, FP_ALICE);
    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(mutationCalls).toBe(0);
  });

  it("keeps the legacy no-header caller contract", async () => {
    expect((await postV3(TOKEN_ALICE, null)).status).toBe(201);
    expect(store.get("work-1\0attempt-1")!.submission.submittedBy).toBe("alice");
  });

  it("recovers a committed-but-unanswered POST through the digest instead of the POST error", async () => {
    dropRegisterResponse = true;
    const response = await postV3(TOKEN_ALICE, FP_ALICE);
    expect(response.status).toBe(200);
    expect(store.get("work-1\0attempt-1")!.submission.submittedBy).toBe("alice");
  });

  it("returns an explicit unknown instead of the recovery list's 401 when the POST outcome is unknowable", async () => {
    dropRegisterResponse = true;
    // Prior 목록(등록 전)은 성공하고, 복구 목록만 실패한다.
    listFailureStatus = 401;
    listFailureFromCall = 2;
    const response = await postV3(TOKEN_ALICE, FP_ALICE);
    expect(response.status).toBe(503);
    expect(((await response.json()) as { code?: string }).code).toBe("EXTERNAL_RECONSTRUCTION_RESULT_UNKNOWN");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    // The mutation did commit — the caller must not read this as "not received".
    expect(store.get("work-1\0attempt-1")!.submission.submittedBy).toBe("alice");
  });

  it("lets a definitive POST rejection stand when the recovery list also fails", async () => {
    forcedRegisterFailure = { status: 422, body: { detail: "BAD_DECLARATION" } };
    listFailureStatus = 403;
    listFailureFromCall = 2;
    const response = await postV3(TOKEN_ALICE, FP_ALICE);
    expect(response.status).toBe(422);
    expect(((await response.json()) as { code?: string }).code).toBe("BAD_DECLARATION");
    expect(store.has("work-1\0attempt-1")).toBe(false);
  });

  it.each([FP_ALICE, null])("keeps a transport outcome unknown when the recovery list has no matching record (fingerprint %s)", async (fingerprint) => {
    failRegisterTransport = true;
    const response = await postV3(TOKEN_ALICE, fingerprint);
    expect(response.status).toBe(503);
    expect(((await response.json()) as { code?: string }).code).toBe("EXTERNAL_RECONSTRUCTION_RESULT_UNKNOWN");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    // This fixture knows the transport failed before commit, but the BFF does
    // not: an absent record in a read is not proof that the POST never landed.
    expect(store.has("work-1\0attempt-1")).toBe(false);
  });

  it("keeps the outcome unknown when a committed POST is missing from the recovery read", async () => {
    dropRegisterResponse = true;
    hideRecoveryList = true;
    const response = await postV3(TOKEN_ALICE, FP_ALICE);
    expect(store.get("work-1\0attempt-1")!.submission.submittedBy).toBe("alice");
    expect(response.status).toBe(503);
    expect(((await response.json()) as { code?: string }).code).toBe("EXTERNAL_RECONSTRUCTION_RESULT_UNKNOWN");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });
});

describe("upload-grants and seal cross-account guard", () => {
  async function registeredRef(): Promise<string> {
    const response = await postV3(TOKEN_ALICE, FP_ALICE);
    expect(response.status).toBe(201);
    return ((await response.json()) as { submissionRef: string }).submissionRef;
  }

  it("documents the legacy gap: without a fingerprint, another same-org account mints grants and seals A's revision", async () => {
    const ref = await registeredRef();
    expect((await postGrants(TOKEN_BOB, null, ref)).status).toBe(200);
    expect((await postSeal(TOKEN_BOB, null, ref)).status).toBe(200);
    expect(store.get("work-1\0attempt-1")!.sealed).toBe(true);
  });

  it("blocks fingerprint-bound grant and seal retries under another account without Core mutations", async () => {
    const ref = await registeredRef();
    expect((await postGrants(TOKEN_ALICE, FP_ALICE, ref)).status).toBe(200);
    expect((await postSeal(TOKEN_ALICE, FP_ALICE, ref)).status).toBe(200);
    store.get("work-1\0attempt-1")!.sealed = false;
    const mutationsAfterAlice = mutationCalls;
    const blockedGrant = await postGrants(TOKEN_BOB, FP_ALICE, ref);
    expect(blockedGrant.status).toBe(409);
    expect(((await blockedGrant.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    const blockedSeal = await postSeal(TOKEN_BOB, FP_ALICE, ref);
    expect(blockedSeal.status).toBe(409);
    expect(((await blockedSeal.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(mutationCalls).toBe(mutationsAfterAlice);
    // 원래 계정으로 돌아오면 같은 개정으로 이어간다.
    expect((await postGrants(TOKEN_ALICE_RENEWED, FP_ALICE, ref)).status).toBe(200);
    expect((await postSeal(TOKEN_ALICE, FP_ALICE, ref)).status).toBe(200);
  });

  it("blocks a grant-stage account switch after a lost grant response without a second Core grant", async () => {
    const ref = await registeredRef();
    const mutationsAfterRegister = mutationCalls;
    // 원래 계정의 승인. 응답은 화면에 닿기 전 유실됐다고 가정한다.
    expect((await postGrants(TOKEN_ALICE, FP_ALICE, ref)).status).toBe(200);
    expect(mutationCalls).toBe(mutationsAfterRegister + 1);
    // 같은 승인 재시도 직전에 세션이 다른 계정으로 바뀌었다.
    const blocked = await postGrants(TOKEN_BOB, FP_ALICE, ref);
    expect(blocked.status).toBe(409);
    expect(((await blocked.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(mutationCalls).toBe(mutationsAfterRegister + 1);
    // 원래 계정으로 돌아오면 이어간다.
    expect((await postGrants(TOKEN_ALICE_RENEWED, FP_ALICE, ref)).status).toBe(200);
    expect((await postSeal(TOKEN_ALICE, FP_ALICE, ref)).status).toBe(200);
  });

  it("refuses malformed fingerprints on grants and seal before any Core call", async () => {
    const ref = await registeredRef();
    const mutationsAfterRegister = mutationCalls;
    expect((await postGrants(TOKEN_ALICE, "not-a-fingerprint", ref)).status).toBe(400);
    expect((await postSeal(TOKEN_ALICE, "not-a-fingerprint", ref)).status).toBe(400);
    expect(mutationCalls).toBe(mutationsAfterRegister);
  });

  it("binds grant and seal identity lookup plus mutation to a single captured session token", async () => {
    const ref = await registeredRef();
    mocked.session.mockClear();
    mocked.session.mockResolvedValueOnce(TOKEN_ALICE).mockResolvedValue(TOKEN_BOB);
    const response = await postGrants(TOKEN_ALICE, FP_ALICE, ref);
    expect(response.status).toBe(200);
    expect(mocked.session).toHaveBeenCalledTimes(1);
  });
});
