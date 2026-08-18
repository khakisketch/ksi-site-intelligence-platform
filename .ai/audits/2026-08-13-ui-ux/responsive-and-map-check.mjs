import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(
  "/home/ksi/Desktop/KSI-Projects/KSI-Safety-Platform/apps/web/node_modules/playwright",
);

const BASE_URL = process.env.AUDIT_BASE_URL ?? "http://100.116.163.1:3020";
const TOKEN = process.env.AUDIT_TOKEN ?? "dev-admin-token";
const OUT_DIR = path.resolve(".ai/audits/2026-08-13-ui-ux/screenshots");
const evidence = { map: null, responsive: [], keyboard: [] };

const browser = await chromium.launch({
  headless: true,
  executablePath: "/usr/bin/google-chrome",
});

async function login(page) {
  await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle" });
  await page.getByLabel("Bearer 토큰").fill(TOKEN);
  await Promise.all([
    page.waitForURL((url) => url.pathname === "/", { timeout: 15_000 }),
    page.getByRole("button", { name: "로그인" }).click(),
  ]);
  await page.waitForLoadState("networkidle");
}

async function visibleTargets(page) {
  return page.evaluate(() => {
    const nodes = Array.from(
      document.querySelectorAll('a[href], button, input:not([type="hidden"]), select, textarea, summary'),
    ).filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    });
    const measurements = nodes.map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        tag: element.tagName,
        text:
          element.getAttribute("aria-label") ||
          element.textContent?.trim().slice(0, 60) ||
          element.getAttribute("name") ||
          "",
        width: Math.round(rect.width * 10) / 10,
        height: Math.round(rect.height * 10) / 10,
      };
    });
    return {
      coarsePointer: matchMedia("(pointer: coarse)").matches,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      below44: measurements.filter((item) => item.width < 44 || item.height < 44),
      measurements,
    };
  });
}

async function captureResponsive(context, label, routes) {
  const page = await context.newPage();
  const errors = [];
  const failures = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("requestfailed", (request) => {
    failures.push(`${request.url()} :: ${request.failure()?.errorText ?? "unknown"}`);
  });

  await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle" });
  if (label === "mobile") {
    await page.screenshot({ path: path.join(OUT_DIR, "39-login-mobile-390.png") });
  }
  await page.getByLabel("Bearer 토큰").fill(TOKEN);
  await Promise.all([
    page.waitForURL((url) => url.pathname === "/", { timeout: 15_000 }),
    page.getByRole("button", { name: "로그인" }).click(),
  ]);
  await page.waitForLoadState("networkidle");

  for (const [route, screenshot] of routes) {
    errors.length = 0;
    failures.length = 0;
    await page.goto(`${BASE_URL}${route}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT_DIR, screenshot) });
    evidence.responsive.push({
      label,
      route,
      screenshot,
      viewport: await page.evaluate(() => ({ width: innerWidth, height: innerHeight })),
      ...(await visibleTargets(page)),
      consoleErrors: [...errors],
      requestFailures: [...failures],
    });
  }
  await page.close();
}

try {
  const desktop = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "ko-KR",
  });
  const page = await desktop.newPage();
  const mapErrors = [];
  const mapFailures = [];
  page.on("console", (message) => {
    if (message.type() === "error") mapErrors.push(message.text());
  });
  page.on("pageerror", (error) => mapErrors.push(`pageerror: ${error.message}`));
  page.on("requestfailed", (request) => {
    mapFailures.push(`${request.url()} :: ${request.failure()?.errorText ?? "unknown"}`);
  });
  await login(page);

  // Keyboard focus visibility on the authenticated home page.
  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press("Tab");
    evidence.keyboard.push(
      await page.evaluate((step) => {
        const element = document.activeElement;
        const style = element ? getComputedStyle(element) : null;
        return {
          step,
          tag: element?.tagName ?? null,
          text: element?.textContent?.trim().slice(0, 80) ?? "",
          href: element?.getAttribute("href") ?? null,
          outlineStyle: style?.outlineStyle ?? null,
          outlineWidth: style?.outlineWidth ?? null,
        };
      }, index + 1),
    );
  }

  // Re-capture the registration map only after the real Leaflet surface and controls are stable.
  await page.goto(`${BASE_URL}/sites/new?mode=full`, { waitUntil: "networkidle" });
  await page.evaluate(() => {
    sessionStorage.setItem(
      "ksi-wizard-site-registration",
      JSON.stringify({
        siteId: "audit-preview-site",
        name: "UI UX 감사 미리보기 현장",
        egressChoice: "unset",
        jurisdiction: "",
        aoi: [
          { latDeg: 37.5, lonDeg: 127.0 },
          { latDeg: 37.5, lonDeg: 127.003 },
          { latDeg: 37.502, lonDeg: 127.003 },
          { latDeg: 37.502, lonDeg: 127.0 },
        ],
        crs: "EPSG:5186",
        verticalDatum: "KNGeoid2018",
        transformVersion: "1.0.0",
        altitudeM: 40,
        excludedVolumes: [],
        frontOverlap: 0.8,
        sideOverlap: 0.7,
        autoFlightSpeedMs: 5,
        takeoffSecurityHeightM: 20,
        globalTransitionalSpeedMs: 10,
        droneEnumValue: 99,
        droneSubEnumValue: 0,
        payloadEnumValue: 65534,
        viewpointPolicyId: "default-viewpoint-policy",
        riskPolicyPackId: "default-risk-policy",
        fallbackPolicyId: "default-fallback-policy",
        capturePolicyId: "default-capture-policy",
        objectives: ["초기 매핑"],
      }),
    );
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 15_000 });
  await page.locator(".leaflet-control-zoom-in").waitFor({ state: "visible", timeout: 15_000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(OUT_DIR, "12-site-register-step-2.png"), fullPage: true });
  evidence.map = {
    leafletContainer: await page.locator(".leaflet-container").count(),
    zoomControl: await page.locator(".leaflet-control-zoom-in").count(),
    polygon: await page.locator("path.leaflet-interactive").count(),
    loadedTiles: await page.locator("img.leaflet-tile-loaded").count(),
    consoleErrors: mapErrors,
    requestFailures: mapFailures,
  };
  await desktop.close();

  const tablet = await browser.newContext({
    viewport: { width: 1024, height: 768 },
    locale: "ko-KR",
    hasTouch: true,
    isMobile: true,
  });
  await captureResponsive(tablet, "tablet", [
    ["/", "31-home-tablet-1024-viewport.png"],
    ["/events", "32-events-tablet-1024-viewport.png"],
  ]);
  await tablet.close();

  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: "ko-KR",
    hasTouch: true,
    isMobile: true,
  });
  await captureResponsive(mobile, "mobile", [
    ["/", "33-home-mobile-390-viewport.png"],
    ["/events", "34-events-mobile-390-viewport.png"],
    ["/sites/site-demo-1", "35-site-detail-mobile-390-viewport.png"],
    ["/more", "36-more-mobile-390-viewport.png"],
    ["/sites/site-demo-1/surveys/new", "37-survey-mobile-390-viewport.png"],
    ["/events/edge-dev-001%3A%3Aevt-demo-004", "38-event-detail-mobile-390.png"],
  ]);
  await mobile.close();

  fs.writeFileSync(
    path.resolve(".ai/audits/2026-08-13-ui-ux/responsive-evidence.json"),
    `${JSON.stringify(evidence, null, 2)}\n`,
    "utf8",
  );
  console.log(JSON.stringify(evidence, null, 2));
} finally {
  await browser.close();
}
