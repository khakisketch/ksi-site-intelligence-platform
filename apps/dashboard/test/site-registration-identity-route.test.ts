/** @vitest-environment node */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
}));

vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});

import { GET } from "@/app/api/account-identity/route";

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

const coreCalls: string[] = [];

function installCoreFetchMock() {
  process.env.CORE_API_BASE_URL = "http://core.test";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      coreCalls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/v1/auth/whoami")) {
        const headers = new Headers(init?.headers as HeadersInit | undefined);
        const auth = headers.get("authorization") ?? "";
        const token = auth.startsWith("Bearer ") ? auth.slice("Bearer ".length) : null;
        if (token === "token-alice-a") {
          return new Response(
            JSON.stringify({
              principalId: "alice",
              organizationId: "org-a",
              kind: "OPERATOR",
              role: "FIELD_OPERATOR",
              deviceId: null,
              permissions: [],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (token === "token-bob-a") {
          return new Response(
            JSON.stringify({
              principalId: "bob",
              organizationId: "org-a",
              kind: "OPERATOR",
              role: "FIELD_OPERATOR",
              deviceId: null,
              permissions: [],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (token === "token-malformed") {
          return new Response(JSON.stringify({ organizationId: "org-a" }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        if (token === "token-503") {
          return new Response(JSON.stringify({ detail: "unavailable" }), {
            status: 503,
            headers: { "content-type": "application/json" },
          });
        }
        return new Response(JSON.stringify({ detail: "인증이 필요하다" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.session.mockReset();
  vi.unstubAllGlobals();
  coreCalls.length = 0;
  installCoreFetchMock();
});

describe("GET /api/account-identity (읽기 전용 신원 확인)", () => {
  it("세션 없이는 Core를 호출하지 않고 401로 끊는다", async () => {
    const { MissingSessionError } = await import("@/lib/core-api/session");
    mocked.session.mockRejectedValue(new MissingSessionError());
    const response = await GET();
    expect(response.status).toBe(401);
    expect(coreCalls.filter((call) => call.includes("/v1/"))).toHaveLength(0);
  });

  it("현재 세션의 지문만 돌려주고 저장하지 않으며 변이를 일으키지 않는다", async () => {
    mocked.session.mockResolvedValue("token-alice-a");
    const response = await GET();
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(Object.keys(body)).toEqual(["fingerprint"]);
    expect(body.fingerprint).toBe(fingerprint("org-a", "alice"));
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(coreCalls.filter((call) => !call.startsWith("GET"))).toHaveLength(0);
  });

  it("서로 다른 토큰은 서로 다른 지문을 받고 교차 노출이 없다", async () => {
    mocked.session.mockResolvedValue("token-bob-a");
    const response = await GET();
    const body = (await response.json()) as Record<string, unknown>;
    expect(body.fingerprint).toBe(fingerprint("org-a", "bob"));
    expect(body.fingerprint).not.toBe(fingerprint("org-a", "alice"));
  });

  it("whoami 실패·깨진 본문은 지문 없이 fail-closed로 끊는다", async () => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocked.session.mockResolvedValue("token-503");
    expect((await GET()).status).toBeGreaterThanOrEqual(500);

    mocked.session.mockResolvedValue("token-malformed");
    expect((await GET()).status).toBe(500);
    errorLog.mockRestore();
  });
});
