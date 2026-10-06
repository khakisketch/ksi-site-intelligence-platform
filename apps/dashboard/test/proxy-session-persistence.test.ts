import { randomUUID } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse, type NextFetchEvent } from "next/server";
import { encode, getToken } from "next-auth/jwt";

import { AUTH_SESSION_COOKIE_NAME } from "@/lib/auth/auth-cookie";

const fixture = vi.hoisted(() => ({ secret: "", tokenExchanges: 0 }));
vi.mock("@/lib/auth/runtime", () => ({
  getDashboardAuthRuntime: () => ({
    mode: "OIDC",
    deploymentProfile: "LOCAL",
    sessionSecret: fixture.secret,
    oidc: {
      issuer: "http://generated-issuer.test",
      clientId: "generated-client",
      clientSecret: "generated-test-only-client-secret",
    },
  }),
}));

// The real Auth.js wrapper, JWT encryption and Next cookie transport are kept.
// Only the external issuer exchange is replaced with a single-use fixture.
async function expiredCookie(padding = "") {
  return encode({
    secret: fixture.secret,
    salt: AUTH_SESSION_COOKIE_NAME,
    token: {
      sub: "generated-field-operator",
      accessToken: "generated-old-access",
      refreshToken: randomUUID(),
      accessTokenExpiresAt: Date.now() - 1,
      padding,
    },
  });
}

function request(path: string, cookie?: string) {
  return new NextRequest(`http://dashboard.test${path}`, {
    headers: cookie ? { cookie } : undefined,
  });
}

async function navigate(path: string, cookie?: string) {
  const { proxy } = await import("@/proxy");
  return proxy(request(path, cookie), {} as NextFetchEvent);
}

async function upstreamToken(response: Response) {
  const cookie = response.headers.get("x-middleware-request-cookie") ?? "";
  return getToken({
    req: { headers: new Headers({ cookie }) },
    secret: fixture.secret,
    salt: AUTH_SESSION_COOKIE_NAME,
    cookieName: AUTH_SESSION_COOKIE_NAME,
  });
}

describe("proxy refresh persistence", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function setupIssuer() {
    fixture.secret = randomUUID() + randomUUID();
    fixture.tokenExchanges = 0;
    vi.resetModules();
    const consumed = new Set<string>();
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url.endsWith("/.well-known/openid-configuration")) {
        return Response.json({ token_endpoint: "http://generated-issuer.test/token" });
      }
      if (url !== "http://generated-issuer.test/token") throw new Error("Unexpected fixture URL");
      fixture.tokenExchanges += 1;
      const token = new URLSearchParams(init?.body as URLSearchParams).get("refresh_token")!;
      if (consumed.has(token)) return Response.json({ error: "invalid_grant" }, { status: 400 });
      consumed.add(token);
      return Response.json({
        access_token: "generated-fresh-access",
        refresh_token: randomUUID(),
        expires_in: 300,
      });
    });
  }

  it("persists rotation to the browser AND the same upstream request before a later navigation", async () => {
    await setupIssuer();
    const response = await navigate("/sites/generated/observations", `${AUTH_SESSION_COOKIE_NAME}=${await expiredCookie()}; unrelated=keep`);
    const persisted = new NextResponse(null, { headers: response.headers }).cookies.get(AUTH_SESSION_COOKIE_NAME);
    expect(persisted?.httpOnly).toBe(true);
    expect(persisted?.sameSite).toBe("lax");
    expect(persisted?.path).toBe("/");
    expect(await upstreamToken(response)).toMatchObject({ sub: "generated-field-operator", accessToken: "generated-fresh-access" });
    expect(response.headers.get("x-middleware-request-cookie")).toContain("unrelated=keep");
    expect(await response.text()).not.toContain("generated-fresh-access");
    expect(response.headers.get("x-middleware-request-x-pathname")).toBe("/sites/generated/observations");

    const now = Date.now();
    vi.spyOn(Date, "now").mockReturnValue(now + 6_000);
    const later = await navigate("/sites/generated", `${AUTH_SESSION_COOKIE_NAME}=${persisted!.value}`);
    expect(await upstreamToken(later)).toMatchObject({ sub: "generated-field-operator", accessToken: "generated-fresh-access" });
    expect(fixture.tokenExchanges).toBe(1);
  });

  it("replaces stale chunked session cookies without removing unrelated cookies", async () => {
    await setupIssuer();
    const encrypted = await expiredCookie();
    const half = Math.floor(encrypted.length / 2);
    const response = await navigate("/sites/generated", `${AUTH_SESSION_COOKIE_NAME}.0=${encrypted.slice(0, half)}; ${AUTH_SESSION_COOKIE_NAME}.1=${encrypted.slice(half)}; unrelated=keep`);
    expect(await upstreamToken(response)).toMatchObject({ accessToken: "generated-fresh-access" });
    const cookie = response.headers.get("x-middleware-request-cookie")!;
    expect(cookie).not.toContain(`${AUTH_SESSION_COOKIE_NAME}.0=`);
    expect(cookie).not.toContain(`${AUTH_SESSION_COOKIE_NAME}.1=`);
    expect(cookie).toContain("unrelated=keep");
    for (const name of [`${AUTH_SESSION_COOKIE_NAME}.0`, `${AUTH_SESSION_COOKIE_NAME}.1`]) {
      expect(response.headers.getSetCookie().find((entry) => entry.startsWith(`${name}=`))).toMatch(/Max-Age=0/i);
    }
  });

  it("coalesces concurrent requests bearing the same stale single-use refresh token", async () => {
    await setupIssuer();
    const cookie = `${AUTH_SESSION_COOKIE_NAME}=${await expiredCookie()}`;
    const responses = await Promise.all([
      navigate("/sites/generated/observations", cookie),
      navigate("/sites/generated", cookie),
    ]);
    for (const response of responses) {
      expect(await upstreamToken(response)).toMatchObject({ accessToken: "generated-fresh-access" });
      expect(new NextResponse(null, { headers: response.headers }).cookies.get(AUTH_SESSION_COOKIE_NAME)?.httpOnly).toBe(true);
    }
    expect(fixture.tokenExchanges).toBe(1);
  });

  it("keeps the actual session GET handler closed without returning session JSON", async () => {
    await setupIssuer();
    const { GET } = await import("@/app/api/auth/[...nextauth]/route");
    const response = await GET(request("/api/auth/session", `${AUTH_SESSION_COOKIE_NAME}=${await expiredCookie()}`));
    expect(response.status).toBe(404);
    expect(await response.text()).toBe("");
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(fixture.tokenExchanges).toBe(0);
  });

  it("keeps the actual unauthenticated refresh handler JSON 401 rather than an HTML redirect", async () => {
    await setupIssuer();
    const { POST } = await import("@/app/api/auth/refresh/route");
    const response = await POST(request("/api/auth/refresh"), { params: Promise.resolve({}) });
    if (!response) throw new Error("Expected authentication response");
    expect(response.status).toBe(401);
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(await response.json()).toEqual({ code: "OIDC_SESSION_EXPIRED" });
    expect(fixture.tokenExchanges).toBe(0);
  });

  it("forwards all rotated chunks when the encrypted session exceeds one cookie", async () => {
    await setupIssuer();
    const response = await navigate("/sites/generated", `${AUTH_SESSION_COOKIE_NAME}=${await expiredCookie("x".repeat(6_000))}`);
    const persisted = new NextResponse(null, { headers: response.headers }).cookies.getAll();
    expect(persisted.filter((cookie) => cookie.value && cookie.name.startsWith(`${AUTH_SESSION_COOKIE_NAME}.`)).length).toBeGreaterThan(1);
    expect(await upstreamToken(response)).toMatchObject({ accessToken: "generated-fresh-access" });
  });

  it("removes an invalid encrypted session from the upstream request and browser", async () => {
    await setupIssuer();
    // Auth.js reports the deliberately malformed synthetic JWE to its logger.
    vi.spyOn(console, "error").mockImplementation(() => {});
    const response = await navigate("/sites/generated", `${AUTH_SESSION_COOKIE_NAME}=invalid; unrelated=keep`);
    expect(await upstreamToken(response)).toBeNull();
    expect(response.headers.get("x-middleware-request-cookie")).not.toContain(`${AUTH_SESSION_COOKIE_NAME}=`);
    expect(response.headers.getSetCookie().find((cookie) => cookie.startsWith(`${AUTH_SESSION_COOKIE_NAME}=`))).toMatch(/Max-Age=0/i);
    expect(fixture.tokenExchanges).toBe(0);
  });

  it.each(["/login", "/api/auth/callback/ksi-oidc", "/api/auth/session", "/api/auth/refresh"])("leaves %s to its existing auth route without consuming a refresh token", async (path) => {
    await setupIssuer();
    const response = await navigate(path, `${AUTH_SESSION_COOKIE_NAME}=${await expiredCookie()}`);
    expect(response.status).toBe(200);
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(fixture.tokenExchanges).toBe(0);
  });

  it("retains protected-page redirect, API JSON ownership and disabled HIL 404", async () => {
    await setupIssuer();
    const page = await navigate("/sites/generated?view=history");
    expect(page.headers.get("location")).toBe("http://dashboard.test/login?next=%2Fsites%2Fgenerated%3Fview%3Dhistory");
    expect((await navigate("/api/sites")).headers.get("location")).toBeNull();
    expect((await navigate("/hil/private")).status).toBe(404);
  });
});
