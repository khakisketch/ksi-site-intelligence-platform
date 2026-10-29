import { expect, test } from "@playwright/test";
import { createServer, request as httpRequest } from "node:http";
import { connect, type AddressInfo } from "node:net";

// This diagnostic is never part of the external-base suite. A skip is reported
// explicitly instead of aborting discovery of other tests in that suite.
test.skip(
  process.env.KSI_DASHBOARD_E2E_BASE_URL !== undefined,
  "Synthetic-only title diagnostic is excluded from external-base runs.",
);
test.skip(
  process.env.KSI_DASHBOARD_E2E_BASE_URL === undefined,
  "Synthetic-only title diagnostic is excluded until a verified network-none fixture launcher exists.",
);

test.beforeAll(() => {
  // Neither a loopback URL nor the browser proxy proves the Node/Core/issuer
  // fixture is task-owned or network-isolated. The shared Playwright config
  // cannot establish that boundary from this test. Fail before creating the
  // browser until a verified network-none fixture launcher is available.
  throw new Error("Site title diagnostic requires a verified task-owned network-none fixture; no verified fixture launcher is configured.");
});

function isLoopback(url: URL, protocols: readonly string[]): boolean {
  return protocols.includes(url.protocol) && !url.username && !url.password &&
    ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
}

test("site client navigation never leaves an empty document title (synthetic-only; isolated runner unavailable)", async ({ browser }, testInfo) => {
  // Guard custom configs too, without echoing any supplied URL or userinfo.
  let base: URL;
  try {
    base = new URL(String(testInfo.project.use.baseURL ?? ""));
  } catch {
    throw new Error("Site title diagnostic requires a loopback synthetic fixture.");
  }
  if (!isLoopback(base, ["http:", "https:"])) {
    throw new Error("Site title diagnostic requires a loopback synthetic fixture.");
  }
  // Redirects are not re-routed by Playwright. A private HTTP proxy therefore
  // refuses non-loopback redirect targets as well as direct requests. It never
  // accepts CONNECT; local WebSocket upgrades are needed by the dev fixture.
  const proxy = createServer((incoming, outgoing) => {
    let target: URL;
    try { target = new URL(incoming.url ?? ""); } catch { outgoing.writeHead(403).end(); return; }
    if (!isLoopback(target, ["http:"])) { outgoing.writeHead(403).end(); return; }
    const headers = { ...incoming.headers };
    delete headers["proxy-authorization"];
    delete headers["proxy-connection"];
    const upstream = httpRequest(target, { method: incoming.method, headers }, (response) => {
      outgoing.writeHead(response.statusCode ?? 502, response.headers);
      response.pipe(outgoing);
    });
    upstream.on("error", () => { if (!outgoing.headersSent) outgoing.writeHead(502); outgoing.end(); });
    incoming.pipe(upstream);
  });
  proxy.on("connect", (_request, socket) => socket.destroy());
  proxy.on("upgrade", (incoming, socket, head) => {
    let target: URL;
    try { target = new URL(incoming.url ?? "", `http://${incoming.headers.host ?? ""}`); }
    catch { socket.destroy(); return; }
    if (!isLoopback(target, ["http:"])) { socket.destroy(); return; }
    const upstream = connect(Number(target.port || 80), target.hostname);
    upstream.on("error", () => socket.destroy());
    socket.on("error", () => upstream.destroy());
    upstream.once("connect", () => {
      const headers = Object.entries(incoming.headers)
        .filter(([name]) => name !== "proxy-authorization" && name !== "proxy-connection")
        .flatMap(([name, value]) => value === undefined ? [] : [`${name}: ${Array.isArray(value) ? value.join(", ") : value}\r\n`]);
      upstream.write(`${incoming.method} ${target.pathname}${target.search} HTTP/${incoming.httpVersion}\r\n${headers.join("")}\r\n`);
      if (head.length) upstream.write(head);
      socket.pipe(upstream).pipe(socket);
    });
  });
  await new Promise<void>((resolve, reject) => {
    proxy.once("error", reject);
    proxy.listen(0, "127.0.0.1", resolve);
  });
  const port = (proxy.address() as AddressInfo).port;
  let context;
  try {
    context = await browser.newContext({
      baseURL: base.toString(),
      viewport: { width: 1440, height: 1000 },
      serviceWorkers: "block",
      // Remove Chromium's implicit bypasses (including link-local addresses),
      // then explicitly bypass only the fixture's loopback hosts.
      proxy: { server: `http://127.0.0.1:${port}`, bypass: "<-loopback>,localhost,127.0.0.1,[::1]" },
    });
    // Browser-request filtering only; this does not isolate the OS or fixture
    // processes from the network. Install before the first navigation.
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      return isLoopback(url, ["http:", "https:"]) ? route.continue() : route.abort("blockedbyclient");
    });
    await context.routeWebSocket((url) => !isLoopback(url, ["ws:", "wss:"]), (socket) => socket.close());
    const page = await context.newPage();
    await page.goto("/login");
    await page.getByRole("button", { name: /개발 Operations Console 시작/ }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.bringToFront();
    await page.locator("[data-account-display-root]:not([hidden])").waitFor({ state: "attached" });
    await page.goto("/field/new");
    const siteLink = page.getByRole("link", { name: /E2E 현장 작업공간/ });
    await expect(siteLink).toBeVisible();
    await page.evaluate(() => {
      const samples: { path: string; title: string; at: number }[] = [];
      (window as unknown as { titleSamples: typeof samples }).titleSamples = samples;
      const observer = new MutationObserver(() => samples.push({ path: location.pathname, title: document.title, at: performance.now() }));
      observer.observe(document.head, { childList: true, subtree: true, characterData: true });
    });
    await siteLink.click();
    await expect(page).toHaveURL(/\/sites\/e2e-site-workspace\/observations\/new$/);
    await page.getByRole("link", { name: "현장으로 돌아가기" }).click();
    await expect(page).toHaveURL(/\/sites\/e2e-site-workspace\?/);
    await expect(page).toHaveTitle("현장 상세 · KSI");
    const samples = await page.evaluate(() => (window as unknown as { titleSamples: { path: string; title: string; at: number }[] }).titleSamples);
    expect(samples.length).toBeGreaterThan(0);
    expect(samples.some((sample) => sample.path === "/sites/e2e-site-workspace")).toBe(true);
    expect(samples.some((sample) => sample.title.includes("E2E 현장 작업공간"))).toBe(false);
    expect(samples.filter((sample) => !sample.title.trim()), JSON.stringify(samples)).toEqual([]);
  } finally {
    try {
      await context?.close();
    } finally {
      await new Promise<void>((resolve, reject) => proxy.close((error) => error ? reject(error) : resolve()));
    }
  }
});
