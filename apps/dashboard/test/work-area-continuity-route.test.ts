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

import { POST } from "@/app/api/sites/[siteId]/work-areas/route";

const siteContext = { params: Promise.resolve({ siteId: "site-a" }) };
const BODY = {
  name: "3공구",
  polygon: { type: "Polygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] },
  crs: "EPSG:4326",
  supersedes: null,
};

// 작업구역 Core 등록에는 멱등 키가 없다 — 같은 내용의 POST마다 새 sequence 구역이
// 생긴다. 이 mock은 그 계약을 재현한다(같은 계정의 재시도도 새 구역을 만든다).
// BFF 가드는 중복 생성을 막지 않고, 다른 계정의 조용한 재전송만 Core 호출 없이
// 끊는다.
let areaCounter = 0;
let coreCreateCalls = 0;
const createdIds: string[] = [];

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
            permissions: ["SITES_READ", "SITES_WRITE"],
          },
          200,
        );
      }
      if (url.endsWith("/v1/sites/site-a/work-areas") && (init?.method ?? "GET") === "POST") {
        if (!who) return jsonResponse({ detail: "인증이 필요하다" }, 401);
        coreCreateCalls += 1;
        const rawBody = typeof init?.body === "string" ? JSON.parse(init.body) : {};
        areaCounter += 1;
        const createdId = `wa-site-a-${String(areaCounter).padStart(4, "0")}`;
        createdIds.push(createdId);
        return jsonResponse(
          {
            verdict: "REGISTERED",
            detail: null,
            workArea: {
              schemaVersion: "1",
              workAreaId: createdId,
              siteId: "site-a",
              name: rawBody.name,
              polygon: rawBody.polygon,
              crs: rawBody.crs,
              status: "ACTIVE",
              supersedes: rawBody.supersedes ?? null,
              createdAt: "2026-10-29T00:00:00Z",
            },
          },
          201,
        );
      }
      return jsonResponse({ detail: "not found" }, 404);
    }),
  );
}

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

function postAs(token: string, fp: string | null) {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (fp !== null) headers["x-ksi-continuity-fingerprint"] = fp;
  mocked.session.mockResolvedValue(token);
  return POST(
    new NextRequest("http://console.test/api/sites/site-a/work-areas", {
      method: "POST",
      headers,
      body: JSON.stringify(BODY),
    }),
    siteContext,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.session.mockReset();
  vi.unstubAllGlobals();
  mocked.origin.mockReturnValue(false);
  areaCounter = 0;
  coreCreateCalls = 0;
  createdIds.length = 0;
  installCoreFetchMock();
});

describe("work-area account-continuity BFF guard", () => {
  it("A 불명 뒤 B의 지문 재전송을 Core 호출 없이 409로 끊는다", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await postAs("token-alice-a", claim)).status).toBe(201);
    const blocked = await postAs("token-bob-a", claim);
    expect(blocked.status).toBe(409);
    expect(((await blocked.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    // B의 요청으로 Core 구역이 하나도 더 생기지 않는다
    expect(coreCreateCalls).toBe(1);
    expect(createdIds).toHaveLength(1);
  });

  it("같은 계정의 재전송은 명시적 새 POST로 통과한다 (멱등 없음 유지)", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await postAs("token-alice-a", claim)).status).toBe(201);
    expect((await postAs("token-alice-a", claim)).status).toBe(201);
    // 같은 계정·같은 내용도 새 구역이다 — 계약 변경 없음
    expect(coreCreateCalls).toBe(2);
    expect(createdIds).toHaveLength(2);
    expect(createdIds[0]).not.toBe(createdIds[1]);
  });

  it("다른 조직의 지문 재전송을 Core 호출 없이 409로 끊는다", async () => {
    const claim = fingerprint("org-a", "alice");
    expect((await postAs("token-alice-a", claim)).status).toBe(201);
    const blocked = await postAs("token-alice-b", claim);
    expect(blocked.status).toBe(409);
    expect(((await blocked.json()) as { code?: string }).code).toBe("ACCOUNT_CONTINUITY_MISMATCH");
    expect(coreCreateCalls).toBe(1);
  });

  it("깨진 확인값은 Core 호출 없이 400으로 끊는다", async () => {
    expect((await postAs("token-alice-a", "not-a-fingerprint")).status).toBe(400);
    expect(coreCreateCalls).toBe(0);
  });

  it.each(["token-whoami-503", "token-whoami-malformed"])("신원을 읽지 못하면 Core 호출 없이 끊는다 (%s)", async (token) => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await postAs(token, fingerprint("org-a", "alice"));
    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(coreCreateCalls).toBe(0);
    errorLog.mockRestore();
  });

  it("헤더 없는 호출자는 기존 계약 그대로 Core에 닿는다 (가드 보호 밖)", async () => {
    // 지문 없이는 계정 연속성을 확인할 방법이 없어 기존 동작을 유지한다.
    // 이 경로는 가드 보호 밖임을 기록한다 — 다른 계정 재전송 중복을 막지 않는다.
    const response = await postAs("token-bob-a", null);
    expect(response.status).toBe(201);
    expect(coreCreateCalls).toBe(1);
  });

  it("검사와 변이에 같은 세션 토큰 하나를 쓴다", async () => {
    mocked.session.mockResolvedValueOnce("token-alice-a").mockResolvedValueOnce("token-bob-a");
    const claim = fingerprint("org-a", "alice");
    const response = await POST(
      new NextRequest("http://console.test/api/sites/site-a/work-areas", {
        method: "POST",
        headers: { "content-type": "application/json", "x-ksi-continuity-fingerprint": claim },
        body: JSON.stringify(BODY),
      }),
      siteContext,
    );
    expect(response.status).toBe(201);
    expect(mocked.session).toHaveBeenCalledTimes(1);
    expect(createdIds).toHaveLength(1);
  });
});
