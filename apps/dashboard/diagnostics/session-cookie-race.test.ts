/**
 * Synthetic loopback diagnostic, not a full OIDC login or production evidence.
 * Run with: npx vitest run --config diagnostics/vitest.config.mts
 * A nonzero exit on the current source is the security signal, not an expected pass.
 * Synthetic login is not OIDC. Refresh/rotation, logout and multi-instance
 * behavior are not verified. Browser request filtering is not OS isolation.
 * Requires the Dashboard dependencies and a locally installed Playwright Chromium.
 */
import http from "node:http";
import { randomUUID } from "node:crypto";
import { chromium } from "@playwright/test";
import { NextRequest, type NextFetchEvent } from "next/server";
import { encode, getToken } from "next-auth/jwt";
import { expect, it, vi } from "vitest";
import { AUTH_SESSION_COOKIE_NAME as cookieName } from "@/lib/auth/auth-cookie";

const fixture = vi.hoisted(() => ({ secret: "" }));
vi.mock("@/lib/auth/runtime", () => ({
  getDashboardAuthRuntime: () => ({
    mode: "OIDC", deploymentProfile: "LOCAL", sessionSecret: fixture.secret,
    oidc: { issuer: "http://127.0.0.1:1", clientId: "synthetic", clientSecret: "synthetic" },
  }),
}));

it("does not restore A after B logs in while an A response is delayed", async () => {
  fixture.secret = randomUUID() + randomUUID();
  vi.resetModules();
  // An unexpired access token means no issuer exchange should be attempted.
  vi.stubGlobal("fetch", () => { throw new Error("Unexpected outbound fetch"); });
  const { proxy } = await import("@/proxy");
  const session = (sub: string) => encode({
    secret: fixture.secret, salt: cookieName,
    token: { sub, accessToken: "synthetic", accessTokenExpiresAt: Date.now() + 3_600_000 },
  });
  const [a, b] = await Promise.all([session("A"), session("B")]);
  let release!: () => void;
  let signalArrived!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const arrived = new Promise<void>((resolve) => { signalArrived = resolve; });
  const server = http.createServer(async (req, res) => {
    try {
      if (req.url === "/login-a" || req.url === "/login-b") {
        // This fixture sets a synthetic Auth.js JWT; it is not an OIDC flow.
        res.setHeader("Set-Cookie", `${cookieName}=${req.url === "/login-a" ? a : b}; Path=/; HttpOnly; SameSite=Lax`);
        res.end("ok");
      } else if (req.url === "/delayed") {
        const response = await proxy(new NextRequest("http://127.0.0.1/delayed", {
          headers: { cookie: req.headers.cookie ?? "" },
        }), {} as NextFetchEvent);
        signalArrived();
        await gate;
        res.setHeader("Set-Cookie", response.headers.getSetCookie());
        res.end("ok");
      } else if (req.url === "/identity") {
        const token = await getToken({
          req: { headers: new Headers({ cookie: req.headers.cookie ?? "" }) },
          secret: fixture.secret, salt: cookieName, cookieName,
        });
        res.end(token?.sub === "A" ? "A" : token?.sub === "B" ? "B" : "none");
      } else {
        res.statusCode = 404;
        res.end();
      }
    } catch {
      res.statusCode = 500;
      res.end("fixture error");
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Loopback server unavailable");
  const base = `http://127.0.0.1:${address.port}`;
  let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: "block" });
    // Block direct browser requests outside the ephemeral loopback fixture.
    // Browser routing is not OS isolation and does not cover every redirect.
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      return url.origin === base ? route.continue() : route.abort("blockedbyclient");
    });
    const first = await context.newPage();
    await first.goto(`${base}/login-a`);
    await first.evaluate(() => { (window as unknown as { pending: Promise<Response> }).pending = fetch("/delayed"); });
    await arrived;
    const second = await context.newPage();
    await second.goto(`${base}/login-b`);
    // Use a browser fetch so both tabs share the browser cookie jar.
    const identity = () => second.evaluate(async () => (await fetch("/identity", { cache: "no-store" })).text());
    expect(await identity()).toBe("B");
    release();
    await first.evaluate(async () => { await (window as unknown as { pending: Promise<Response> }).pending; });
    expect(await identity()).toBe("B");
  } finally {
    release();
    await browser?.close();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    vi.unstubAllGlobals();
  }
}, 15_000);
