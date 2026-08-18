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
const EVIDENCE_PATH = path.resolve(".ai/audits/2026-08-13-ui-ux/browser-evidence.json");

fs.mkdirSync(OUT_DIR, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  executablePath: "/usr/bin/google-chrome",
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: "ko-KR",
  colorScheme: "light",
});
const page = await context.newPage();
const evidence = [];
let consoleErrors = [];
let requestFailures = [];

page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
page.on("requestfailed", (request) => {
  requestFailures.push(`${request.url()} :: ${request.failure()?.errorText ?? "unknown"}`);
});

async function inspectCurrent(name, screenshotName, status = null) {
  await page.waitForTimeout(250);
  const screenshotPath = path.join(OUT_DIR, screenshotName);
  await page.screenshot({ path: screenshotPath, fullPage: true });

  const snapshot = await page.evaluate(() => {
    const controlName = (element) => {
      if (element.tagName === "BUTTON" && element.textContent?.trim()) {
        return element.textContent.trim();
      }
      const aria = element.getAttribute("aria-label") || element.getAttribute("aria-labelledby");
      if (aria) return aria;
      if (element.id) {
        const explicit = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
        if (explicit?.textContent?.trim()) return explicit.textContent.trim();
      }
      const wrapping = element.closest("label");
      if (wrapping?.textContent?.trim()) return wrapping.textContent.trim();
      return element.getAttribute("title") || element.getAttribute("placeholder") || "";
    };
    const controls = Array.from(
      document.querySelectorAll('input:not([type="hidden"]), select, textarea, button'),
    );
    return {
      title: document.title,
      bodyLength: document.body.innerText.trim().length,
      bodyExcerpt: document.body.innerText.trim().slice(0, 1800),
      headings: Array.from(document.querySelectorAll("h1, h2, h3"))
        .map((element) => ({ level: element.tagName, text: element.textContent?.trim() ?? "" }))
        .filter((item) => item.text),
      buttons: Array.from(document.querySelectorAll("button")).map((element) => ({
        text: element.textContent?.trim() ?? "",
        disabled: element.disabled,
        name: controlName(element),
      })),
      links: Array.from(document.querySelectorAll("a")).map((element) => ({
        text: element.textContent?.trim() ?? "",
        href: element.getAttribute("href"),
      })),
      controls: controls.map((element) => ({
        tag: element.tagName,
        type: element.getAttribute("type"),
        name: controlName(element),
        disabled: "disabled" in element ? element.disabled : false,
      })),
      unnamedControls: controls.filter((element) => !controlName(element)).length,
      imagesWithoutAlt: Array.from(document.querySelectorAll("img")).filter(
        (element) => !element.hasAttribute("alt"),
      ).length,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
      },
      errorOverlay: Boolean(
        document.querySelector(
          "[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay",
        ),
      ),
    };
  });

  const item = {
    name,
    screenshot: screenshotName,
    url: page.url(),
    status,
    ...snapshot,
    consoleErrors: [...consoleErrors],
    requestFailures: [...requestFailures],
  };
  evidence.push(item);
  console.log(
    JSON.stringify({
      name,
      url: item.url,
      status,
      bodyLength: item.bodyLength,
      headings: item.headings,
      buttons: item.buttons,
      unnamedControls: item.unnamedControls,
      horizontalOverflow: item.horizontalOverflow,
      errorOverlay: item.errorOverlay,
      consoleErrors: item.consoleErrors,
      requestFailures: item.requestFailures,
    }),
  );
  consoleErrors = [];
  requestFailures = [];
}

async function visit(name, route, screenshotName) {
  consoleErrors = [];
  requestFailures = [];
  const response = await page.goto(`${BASE_URL}${route}`, {
    waitUntil: "networkidle",
    timeout: 30_000,
  });
  await inspectCurrent(name, screenshotName, response?.status() ?? null);
}

async function nextWizardStep(name, screenshotName) {
  consoleErrors = [];
  requestFailures = [];
  const next = page.getByRole("button", { name: "다음", exact: true });
  if (await next.isDisabled()) throw new Error(`${name}: 다음 버튼이 비활성 상태입니다.`);
  await next.click();
  await inspectCurrent(name, screenshotName);
}

try {
  await visit("로그인", "/login", "01-login-desktop.png");
  await page.getByLabel("Bearer 토큰").fill(TOKEN);
  await Promise.all([
    page.waitForURL((url) => url.pathname === "/", { timeout: 15_000 }),
    page.getByRole("button", { name: "로그인" }).click(),
  ]);
  await page.waitForLoadState("networkidle");
  await inspectCurrent("홈", "02-home-desktop.png", 200);

  const routes = [
    ["현장 목록", "/sites", "03-sites-desktop.png"],
    ["현장 상세", "/sites/site-demo-1", "04-site-detail-desktop.png"],
    ["작업구역", "/sites/site-demo-1/work-areas", "05-site-work-areas-desktop.png"],
    ["설계 기준", "/sites/site-progress-demo/design", "06-site-design-desktop.png"],
    ["설계 대비 진척", "/sites/site-progress-demo/progress", "07-site-progress-desktop.png"],
    ["현장 보고서", "/sites/site-progress-demo/report", "08-site-report-desktop.png"],
    ["현장 등록 방식 선택", "/sites/new", "09-new-site-choice-desktop.png"],
    ["현장만 등록", "/sites/new?mode=registration-only", "10-site-registration-only-desktop.png"],
    ["임무 목록", "/missions", "17-missions-desktop.png"],
    [
      "임무 상세",
      "/missions/site-demo-1-survey-1785916130924",
      "18-mission-detail-desktop.png",
    ],
    ["이벤트 목록", "/events", "19-events-desktop.png"],
    [
      "이벤트 상세",
      "/events/edge-dev-001%3A%3Aevt-demo-004",
      "20-event-detail-desktop.png",
    ],
    ["자산·시설물", "/assets", "21-assets-desktop.png"],
    ["2D·3D World", "/world", "22-world-desktop.png"],
    ["보고서", "/reports", "23-reports-desktop.png"],
    ["설정", "/settings", "24-settings-desktop.png"],
    ["Fleet·Edge 준비 중", "/coming-soon/fleet", "25-fleet-coming-soon-desktop.png"],
    ["Data·AI 준비 중", "/coming-soon/data", "26-data-coming-soon-desktop.png"],
  ];
  for (const [name, route, screenshot] of routes) await visit(name, route, screenshot);

  // 현장등록 1~6단계. 7단계 진입은 즉시 현장·임무를 기록하므로 감사 중에는 실행하지 않는다.
  await visit("현장 등록 1단계", "/sites/new?mode=full", "11-site-register-step-1.png");
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
  await inspectCurrent("현장 등록 1단계 입력 완료", "11-site-register-step-1-filled.png", 200);
  await nextWizardStep("현장 등록 2단계", "12-site-register-step-2.png");
  await nextWizardStep("현장 등록 3단계", "13-site-register-step-3.png");
  await nextWizardStep("현장 등록 4단계", "14-site-register-step-4.png");
  await nextWizardStep("현장 등록 5단계", "15-site-register-step-5.png");
  await nextWizardStep("현장 등록 6단계", "16-site-register-step-6.png");

  // 새 조사 1~4단계. 5단계 진입은 서명 계약을 발급하므로 감사 중에는 실행하지 않는다.
  await visit(
    "새 조사 1단계",
    "/sites/site-demo-1/surveys/new",
    "27-survey-step-1-desktop.png",
  );
  await page.getByRole("radio", { name: /현장 전체/ }).check();
  await nextWizardStep("새 조사 2단계", "28-survey-step-2-desktop.png");
  await page.locator('input[name="survey-purpose"]:not(:disabled)').first().check();
  await nextWizardStep("새 조사 3단계", "29-survey-step-3-desktop.png");
  await page.getByRole("button", { name: "표준", exact: true }).click();
  await nextWizardStep("새 조사 4단계", "30-survey-step-4-desktop.png");

  // 1024px 태블릿 가로와 390px 모바일에서 핵심 재배치·오버플로를 별도 증거로 남긴다.
  await page.setViewportSize({ width: 1024, height: 768 });
  await visit("홈 태블릿 가로", "/", "31-home-tablet-1024.png");
  await visit("이벤트 태블릿 가로", "/events", "32-events-tablet-1024.png");

  await page.setViewportSize({ width: 390, height: 844 });
  await visit("홈 모바일", "/", "33-home-mobile-390.png");
  await visit("이벤트 모바일", "/events", "34-events-mobile-390.png");
  await visit("현장 상세 모바일", "/sites/site-demo-1", "35-site-detail-mobile-390.png");
  await visit("더보기 모바일", "/more", "36-more-mobile-390.png");
  await visit(
    "새 조사 모바일",
    "/sites/site-demo-1/surveys/new",
    "37-survey-mobile-390.png",
  );

  fs.writeFileSync(EVIDENCE_PATH, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
} finally {
  await browser.close();
}
