import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

const axePath = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");
const syntheticSiteId = "e2e-site-workspace";
const syntheticCivilMissionId = "e2e-civil-postprocessing-fixture";

declare global {
  interface Window {
    axe: {
      run: () => Promise<{
        violations: Array<{ id: string; impact: string | null; nodes: unknown[] }>;
      }>;
    };
  }
}

async function login(page: Page) {
  await page.goto("/");
  if (page.url().includes("/login")) {
    const primaryLogin = page.getByRole("button", {
      name: /개발 Operations Console 시작|조직 계정으로 로그인/,
    });
    await primaryLogin.click();
    const accountPicker = page.getByRole("button", { name: /기본 개발 계정으로 계속/ });
    const hasAccountPicker = await accountPicker
      .waitFor({ state: "visible", timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (hasAccountPicker) {
      await accountPicker.click();
    }
  }
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("main")).toBeVisible();
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
}

async function expectNoSeriousAxeViolations(page: Page) {
  await page.addScriptTag({ path: axePath });
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run();
    return result.violations.filter(
      (violation) => violation.impact === "critical" || violation.impact === "serious",
    );
  });
  expect(violations).toEqual([]);
}

async function expectMarkedTouchTargets(page: Page) {
  const tooSmall = await page.locator(".tap-target, .btn, .input, nav a").evaluateAll((elements) =>
    elements.flatMap((element) => {
      const node = element as HTMLElement;
      const style = window.getComputedStyle(node);
      if (
        style.display === "none" ||
        style.visibility === "hidden" ||
        node.getAttribute("aria-hidden") === "true"
      ) {
        return [];
      }
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return [];
      return rect.width + 0.5 < 44 || rect.height + 0.5 < 44
        ? [{ text: node.textContent?.trim().slice(0, 40) ?? "", width: rect.width, height: rect.height }]
        : [];
    }),
  );
  expect(tooSmall).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await login(page);
  await page.goto("/");
});

test("역할에 맞는 전역 메뉴와 반응형 셸을 유지한다", async ({ page }, testInfo) => {
  const isDesktop = testInfo.project.name.startsWith("desktop");
  const navigation = page.getByRole("navigation", {
    name: isDesktop ? "주 메뉴" : "하단 메뉴",
  });
  await expect(navigation).toBeVisible();

  const expectedLinks = isDesktop
    ? [["/", "홈"], ["/sites", "현장"], ["/field", "작업"], ["/events", "확인 항목"]]
    : [["/", "홈"], ["/sites", "현장"], ["/field", "작업"], ["/events", "확인"], ["/more", "더보기"]];
  for (const [href, label] of expectedLinks) {
    const link = navigation.locator(`a[href="${href}"]`);
    await expect(link).toBeVisible();
    await expect(link).toContainText(label);
  }

  if (!isDesktop) {
    for (const link of await navigation.getByRole("link").all()) {
      const box = await link.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
  }
  await expectNoHorizontalOverflow(page);
  // 합성 빈 데이터 스택만 결정적 snapshot 정본으로 삼는다. 외부 Tailnet/Staging은
  // 실제 원장 값이 계속 바뀌므로 레이아웃·overflow·접근성만 검증한다.
  if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    await expect(page).toHaveScreenshot("home.png", {
      animations: "disabled",
      // `mask` uses Playwright's fluorescent magenta by default. The observed
      // timestamp is intentionally volatile, but the baseline itself is also
      // used for product review, so retain the neutral footer surface instead
      // of introducing a development-only colour into the capture.
      maskColor: "#ffffff",
      fullPage: true,
      // 합성 WorkOrder도 생성 시각을 Core 원장에 기록한다. 이미지 유무에 따라
      // shrink-0 클래스가 달라지는 구현 세부에 기대지 않고, 카드의 시간 표기 전체만
      // 마스크하여 레이아웃·대비·상호작용 변화는 계속 검출한다.
      mask: [page.locator("article span.num")],
      // Linux Chromium은 카드 내부 한국어 글꼴의 서브픽셀 안티앨리어싱만으로
      // 2,000~3,200px 차이를 낼 수 있다. 이 한계는 390px 화면의 약 1%이며,
      // 카드 구조·간격·색상 같은 실제 회귀는 그보다 크게 검출된다.
      maxDiffPixels: 3_500,
    });
  }
});

test("Home은 합성 운영 원장의 사건·승인·결과 검토를 우선순위대로 보여 준다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 원장은 읽기 전용이며 fixture를 전제하지 않습니다.");
  await page.goto("/");
  const carousel = page.getByRole("region", { name: "확인 필요 현장 캐러셀" });
  await expect(carousel).toBeVisible();
  await expect(carousel.getByRole("article")).toHaveCount(3);
  await expect(carousel.getByText("관측 근거 · 중간", { exact: true })).toHaveCount(1);
  await expect(carousel.getByText("관측 이미지 열람 불가", { exact: true })).toHaveCount(1);
  await expect(carousel.getByText("승인 대기", { exact: true })).toHaveCount(1);
  await expect(carousel.getByText("결과 준비", { exact: true })).toHaveCount(1);
  await expect(carousel.getByRole("heading", { name: "E2E 작업 범위 승인" })).toBeVisible();
  await expect(carousel.getByRole("heading", { name: "E2E 결과와 근거 검토" })).toBeVisible();

  const initialSetup = page.getByRole("region", { name: "초기 설정이 필요한 현장" });
  await expect(initialSetup).toBeVisible();
  await expect(initialSetup.getByRole("listitem")).toHaveCount(1);
  await expect(initialSetup).toContainText("E2E 승인 검토 현장");
});

test("핵심 전역 화면은 populated 상태에서도 막히거나 가로로 넘치지 않는다", async ({ page }) => {
  for (const path of ["/sites", "/field", "/events"]) {
    await page.goto(path);
    await expect(page.getByRole("main")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
});

test("키보드는 내비게이션을 건너뛰고 화면 전환 뒤 본문 맥락을 이어 간다", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "본문으로 건너뛰기" });
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const navigation = page.getByRole("navigation", {
    name: test.info().project.name.startsWith("desktop") ? "주 메뉴" : "하단 메뉴",
  });
  await navigation.locator('a[href="/sites"]').click();
  await expect(page).toHaveURL(/\/sites$/);
  await expect(page.locator("#main-content")).toBeFocused();
});

test("모바일·태블릿의 공용 행동 표면은 44px 터치 기준을 지킨다", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.startsWith("desktop"), "coarse pointer 전용 수용 기준입니다.");
  for (const path of ["/", "/sites", "/field", "/events"]) {
    await page.goto(path);
    await expect(page.getByRole("main")).toBeVisible();
    await expectMarkedTouchTargets(page);
  }
});

test("현장 목록은 폭에 맞는 비교 표현과 현장 진입을 유지한다", async ({ page }, testInfo) => {
  await page.goto("/sites");
  const siteLink = page.locator('main a[href^="/sites/"]:not([href="/sites/new"])').first();
  const hasSite = await siteLink
    .waitFor({ state: "attached", timeout: 5_000 })
    .then(() => true)
    .catch(() => false);
  if (!hasSite) test.skip(true, "현장 목록 표현을 확인할 대상이 없습니다.");

  if (testInfo.project.name === "desktop-1440") {
    await expect(page.getByText("진행 단계", { exact: true })).toBeVisible();
  } else {
    const compactList = page.getByRole("region", { name: "현장 목록" });
    await expect(compactList).toBeVisible();
    await expect(compactList.getByRole("link", { name: "현장 열기" }).first()).toBeVisible();
    await expect(page.getByText("진행 단계", { exact: true })).toBeHidden();
  }
  await expect(page.locator("[data-site-thumbnail]:visible").first()).toBeVisible();
  if (testInfo.project.name.startsWith("desktop")) {
    await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toBeVisible();
  } else {
    await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toBeHidden();
  }
  await expectNoHorizontalOverflow(page);
});

test("현장 작업공간은 대상 맥락과 다섯 업무 영역을 유지한다", async ({ page }, testInfo) => {
  let siteHref: string | null = null;

  if (
    !process.env.KSI_DASHBOARD_E2E_BASE_URL ||
    process.env.KSI_DASHBOARD_E2E_PHASE2 === "1"
  ) {
    siteHref = `/sites/${encodeURIComponent(syntheticSiteId)}`;
  } else {
    // Tailnet/Staging 검증은 실제 원장을 절대 변경하지 않는다. 등록된 현장이
    // 있을 때만 첫 현장을 읽어 같은 화면 계약을 확인한다.
    await page.goto("/sites");
    const firstSite = page.locator('main a[href^="/sites/"]:not([href="/sites/new"])').first();
    const hasReadableSite = await firstSite
      .waitFor({ state: "attached", timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasReadableSite) {
      test.skip(true, "읽기 전용 검증 대상 현장이 없습니다.");
    }
    siteHref = await firstSite.getAttribute("href");
  }

  expect(siteHref).not.toBeNull();
  await page.goto(siteHref!);
  if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    await expect(page).toHaveTitle("E2E 현장 작업공간 · 현장 · KSI");
  }
  await expect(page.getByRole("heading", { level: 1, name: "현장 상세" })).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 2, name: "E2E 현장 작업공간" })).toBeVisible();
  await expect(page.getByRole("link", { name: "현장으로 이동" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "현장 범위" })).toHaveCount(0);
  const nextAction = page.getByRole("heading", { name: "다음 행동" });
  const briefing = page.getByRole("heading", { name: "KSI 현장 브리핑" });
  await expect(nextAction).toBeVisible();
  await expect(briefing).toBeVisible();
  await expect(
    page.getByText(
      process.env.KSI_DASHBOARD_E2E_PHASE2 === "1"
        ? "아직 저장된 브리핑이 없습니다"
        : "AI 브리핑은 아직 사용하지 않습니다",
      { exact: true },
    ),
  ).toBeVisible();
  expect(
    await page.evaluate(() => {
      const headings = Array.from(document.querySelectorAll("h2"));
      return headings.findIndex((node) => node.textContent?.includes("다음 행동"))
        < headings.findIndex((node) => node.textContent?.includes("KSI 현장 브리핑"));
    }),
  ).toBe(true);

  const labels = ["브리핑", "현장 데이터", "확인 항목", "작업·조사", "보고서"];
  if (testInfo.project.name.startsWith("desktop")) {
    const siteNavigation = page.getByRole("navigation", { name: "현장 상세 화면" });
    await expect(siteNavigation).toBeVisible();
    for (const label of labels) {
      await expect(siteNavigation.getByRole("link", { name: label, exact: true })).toBeVisible();
    }
  } else {
    const disclosure = page.locator("details summary").filter({ hasText: "현장 메뉴 · 브리핑" });
    await expect(disclosure).toBeVisible();
    await disclosure.click();
    const siteNavigation = page.getByRole("navigation", { name: "현장 메뉴" });
    for (const label of labels) {
      await expect(siteNavigation.getByRole("link", { name: label, exact: true })).toBeVisible();
    }
    await expect(page.getByText("노트북에서 계속", { exact: true })).toHaveCount(0);
    await siteNavigation.getByRole("link", { name: "작업·조사", exact: true }).click();
    await expect(page).toHaveURL(/section=work/);
    await expect(page.getByRole("heading", { name: "현장 범위" })).toBeVisible();
  }
  await page.goto(`${siteHref!}?section=reports`);
  await expect(page.getByRole("heading", { name: "현장 보고서", exact: true })).toBeVisible();
  await expect(page.getByText("근거가 없는 값은 보고서에서도 채우지 않습니다.", { exact: false })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("현장 데이터는 토목 준비도를 현장 수용과 분리해 네 화면 폭에서 보여 준다", async ({ page }) => {
  test.skip(
    Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL),
    "외부 원장은 읽기 전용이며 로컬의 첫-epoch fixture를 전제하지 않습니다.",
  );

  const browserFailures: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserFailures.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => browserFailures.push(`pageerror: ${error.message}`));

  await page.goto(`/sites/${syntheticSiteId}?section=data`);
  const readinessCard = page
    .getByRole("heading", { level: 2, name: "토목 시계열 준비" })
    .locator("xpath=ancestor::section");
  await expect(readinessCard).toBeVisible();
  // 이 브라우저 fixture는 ProcessingJob/DesignSurface 원장을 의도적으로 조립하지
  // 않는다. 따라서 404를 첫 조사 시점으로 추정하지 않고, Dashboard가 불가 상태를
  // 보이는지를 네 화면 폭에서 확인한다. 첫 epoch의 실제 projection은 Core/API와
  // presentCivilReadiness 단위 테스트가 따로 고정한다.
  await expect(readinessCard.getByText("토목 준비 상태 확인 불가", { exact: true })).toBeVisible();
  await expect(readinessCard.getByText("두 시점 판정 확인 불가", { exact: true })).toBeVisible();
  await expect(
    readinessCard.getByText(
      "이 상태는 현장 수용·측량 정확도·정산 수량·비행 또는 장비 상태를 뜻하지 않습니다.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(readinessCard.getByRole("link")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  expect(browserFailures).toEqual([]);
});

test("전역 작업 화면은 결정·진행·완료 원장을 구분하고 모호한 뒤로가기를 두지 않는다", async ({ page }) => {
  await page.goto("/field");
  await expect(page.getByRole("link", { name: "작업으로 이동" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "뒤로" })).toHaveCount(0);
  if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    await expect(page.getByText("E2E 작업 범위 승인", { exact: true })).toBeVisible();
    await expect(page.getByText("E2E 승인된 관측 작업", { exact: true })).toBeVisible();
    await expect(page.getByText("E2E 결과와 근거 검토", { exact: true })).toBeVisible();
    await expect(page.getByText("E2E 완료된 관측 작업", { exact: true })).toBeVisible();
    for (const group of ["결정 필요", "진행 중", "완료"]) {
      await expect(page.getByRole("heading", { name: group, exact: true })).toBeVisible();
    }
  }
});

test("작업 상세는 근거가 없을 때 분석 준비를 fail-closed로 표현한다", async ({ page }) => {
  test.skip(
    Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL),
    "외부 원장은 읽기 전용이며 로컬 합성 evidence gap을 전제하지 않습니다.",
  );

  const browserFailures: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserFailures.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => browserFailures.push(`pageerror: ${error.message}`));

  await page.goto("/field");
  const workOrderLink = page.locator('main a[href^="/field/work-orders/"]').first();
  await expect(workOrderLink).toBeVisible();
  const workOrderHref = await workOrderLink.getAttribute("href");
  expect(workOrderHref).toMatch(/^\/field\/work-orders\/[^/]+$/);

  await page.goto(workOrderHref!);
  const progressCard = page
    .getByText("Acquisition progress", { exact: true })
    .locator("xpath=ancestor::section");
  await expect(progressCard.getByText("분석 준비", { exact: true })).toBeVisible();
  await expect(progressCard.getByText("분석 준비 확인 불가", { exact: true })).toBeVisible();
  await expect(
    progressCard.getByText("Analysis Readiness 증거 projection이 이 Core 조립에 장착되지 않았습니다.", {
      exact: true,
    }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(browserFailures).toEqual([]);
});

test("토목 후처리 패널은 기존 흐름 안에서 일관된 프로필과 다음 행동을 보여 준다", async ({ page }, testInfo) => {
  test.skip(
    Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL),
    "외부 원장은 읽기 전용이며 로컬 합성 Mission을 전제하지 않습니다.",
  );

  const browserFailures: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserFailures.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => browserFailures.push(`pageerror: ${error.message}`));

  await page.goto(`/missions/${syntheticCivilMissionId}`);
  if (testInfo.project.name.startsWith("desktop")) {
    await expect(page.getByRole("heading", { name: "사진 업로드 · 재구성" })).toBeVisible();
    await expect(page.getByText("KSI 표준 처리 v1", { exact: true })).toBeVisible();
    const resourcePolicy = page
      .getByText(/처리 자원 정책 · ksi-civil-pilot-r1/)
      .locator("xpath=../..");
    await expect(resourcePolicy).toContainText("5,000장");
    await expect(resourcePolicy).toContainText("1 GiB");
    await expect(resourcePolicy).toContainText("1 TiB");
    await expect(resourcePolicy).toContainText("150,000 MP");
    await expect(resourcePolicy).toContainText("20건");
    await expect(resourcePolicy).toContainText("처리 성공, 비용, 정확도를 보장하지 않습니다.");
  } else {
    const laptopBoundary = page
      .getByText("원본 업로드·봉인과 처리 시작은 노트북의 전체 Operations Console에서 수행합니다.", {
        exact: true,
      })
      .locator("xpath=ancestor::aside");
    await expect(laptopBoundary.getByText("노트북에서 계속", { exact: true })).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "두 시점 비교" })).toBeVisible();
  await expect(page.getByText("비교 가능한 결과 0건", { exact: true })).toBeVisible();
  await expect(
    page.getByText("비교하려면 이 현장에서 완료된 재구성이 두 개 이상 있어야 합니다", {
      exact: false,
    }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(`/sites/${syntheticSiteId}/design`);
  await expect(
    page.getByRole("heading", { level: 2, name: "설계 기준면", exact: true }),
  ).toBeVisible();
  const landxml = page.getByRole("radio", { name: /LandXML TIN Surface/ });
  await landxml.focus();
  await expect(landxml).toBeFocused();
  await landxml.check();
  await expect(
    page.getByLabel(/사용할 TIN Surface 이름/),
  ).toBeVisible();
  await expect(page.getByText(/DWG\/DXF는 직접 받지 않으므로/)).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(browserFailures).toEqual([]);
});

test("확인 항목은 등록 근거 수와 상세 진입을 보존한다", async ({ page }) => {
  await page.goto("/events");
  if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    const eventRow = page.locator("main li").filter({ hasText: "E2E 현장 작업공간" }).first();
    await expect(eventRow).toBeVisible();
    await expect(eventRow).toContainText("근거 1건");
    await page.goto(`/events/${encodeURIComponent("e2e-edge-fixture::event-open-with-evidence")}`);
    await expect(page.getByRole("heading", { name: "근거", exact: true })).toBeVisible();
  }
  await expectNoHorizontalOverflow(page);
});

test("핵심 화면에 중대 접근성 위반이 없고 reduced-motion 설정을 존중한다", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const path of ["/", "/sites", "/field", "/events"]) {
    await page.goto(path);
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 10_000 });
    await expectNoSeriousAxeViolations(page);
  }
});
