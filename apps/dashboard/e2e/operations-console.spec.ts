import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

const axePath = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");
const syntheticSiteId = "e2e-site-workspace";

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

async function openSiteMenu(page: Page) {
  const menu = page.locator('nav[aria-label="현장 영역 메뉴"]:visible, nav[aria-label="현재 현장 메뉴"]:visible, [role="group"][aria-label="현재 현장 메뉴"]:visible');
  await expect(menu).toBeVisible();
  return menu;
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

test("계정 행동과 도움말을 분리해도 기존 지원 경계에 도달할 수 있다", async ({ page }) => {
  await page.goto("/more");
  await expect(page.getByRole("heading", { name: "내 계정", exact: true, level: 2 })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: /Dock·Edge 지원 범위/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "로그아웃", exact: true }).first()).toBeAttached();
  await page.getByRole("main").getByRole("link", { name: "도움말·작업 안내", exact: true }).click();
  await expect(page).toHaveURL(/\/help$/);
  const supportLink = page.getByRole("main").getByRole("link", { name: /Dock·Edge 지원 범위/ });
  await expect(supportLink).toHaveCount(1);
  await expect(supportLink).toHaveAttribute("href", "/coming-soon/fleet");
  await expect(page.getByRole("region", { name: "자주 확인하는 내용" }).getByText(/장비 운용과 고객 측 재구성은 제품 범위 밖입니다\./)).toBeVisible();
  await expect(page.getByText("비행 임무·장비 연결·복구처럼 기술 운영에 필요한 화면입니다.", { exact: true })).toHaveCount(0);
  await supportLink.click();
  await expect(page).toHaveURL(/\/coming-soon\/fleet$/);
});

test("역할에 맞는 전역 메뉴와 반응형 셸을 유지한다", async ({ page }, testInfo) => {
  const isDesktop = testInfo.project.name.startsWith("desktop");
  const navigation = page.getByRole("navigation", {
    name: isDesktop ? "주 메뉴" : "하단 메뉴",
  });
  await expect(navigation).toBeVisible();

  const expectedLinks = isDesktop
    ? [["/", "홈"], ["/sites", "현장"], ["/field", "작업"], ["/more", "계정"]]
    : [["/", "홈"], ["/sites", "현장"], ["/field", "작업"], ["/more", "계정"]];
  for (const [href, label] of expectedLinks) {
    // /more 는 레일 계정 항목과 하단 사용자 블록에 각각 있다 — 레일 항목만 본다.
    const link = href === "/more" && isDesktop
      ? navigation.getByRole("link", { name: "계정", exact: true })
      : navigation.locator(`a[href="${href}"]`);
    await expect(link).toBeVisible();
    await expect(link).toContainText(label);
  }
  await expect(navigation.locator('a[href="/coming-soon/fleet"]')).toHaveCount(0);

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
    const previews = page.getByRole("region", { name: "다른 현장 바로가기" });
    const cards = previews.getByRole("article");
    for (const card of await cards.all()) {
      await card.scrollIntoViewIfNeeded();
      await expect(card.locator('[data-site-preview="card-loading"]')).toHaveCount(0);
    }
    await page.getByRole("heading", { level: 1, name: "홈", exact: true }).scrollIntoViewIfNeeded();
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
      mask: [page.locator("article .num")],
      // Linux Chromium은 카드 내부 한국어 글꼴의 서브픽셀 안티앨리어싱만으로
      // 2,000~3,200px 차이를 낼 수 있다. 이 한계는 390px 화면의 약 1%이며,
      // 카드 구조·간격·색상 같은 실제 회귀는 그보다 크게 검출된다.
      maxDiffPixels: 3_500,
    });
  }
});

test("모바일 하단 내비는 안전영역을 포함해 마지막 내용을 가리지 않는다", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("mobile-390"), "390px 모바일 셸에만 적용합니다.");
  test.skip(
    Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL),
    "작업 상세 경로는 로컬 합성 원장을 사용합니다.",
  );

  const checkBottomClearance = async (path: string) => {
    await page.goto(path);
    await expect(page.getByRole("main")).toBeVisible();
    const metrics = await page.evaluate(() => {
      // Headless Chromium has no physical safe area. Inject an iPhone-sized inset to
      // exercise the same CSS env token without changing product data or browser state.
      document.documentElement.style.setProperty("--mobile-bottom-nav-safe-area", "34px");
      window.scrollTo(0, document.documentElement.scrollHeight);

      const nav = document.querySelector<HTMLElement>('nav[aria-label="하단 메뉴"]');
      const main = document.querySelector<HTMLElement>("#main-content");
      if (!nav || !main) return null;

      const navRect = nav.getBoundingClientRect();
      const lastContent = [...main.querySelectorAll<HTMLElement>("h1,h2,h3,p,a,button,dt,dd,li")]
        .filter((element) => element.getClientRects().length && element.innerText.trim())
        .reduce<HTMLElement | null>(
          (last, element) =>
            !last || element.getBoundingClientRect().bottom > last.getBoundingClientRect().bottom
              ? element
              : last,
          null,
        );

      return {
        navDisplay: getComputedStyle(nav).display,
        navHeight: navRect.height,
        safeAreaPadding: Number.parseFloat(getComputedStyle(nav).paddingBottom),
        mainPadding: Number.parseFloat(getComputedStyle(main).paddingBottom),
        lastContentClearance: lastContent
          ? navRect.top - lastContent.getBoundingClientRect().bottom
          : null,
      };
    });

    expect(metrics).not.toBeNull();
    expect(metrics!.navDisplay).toBe("flex");
    expect(metrics!.safeAreaPadding).toBe(34);
    expect(metrics!.mainPadding).toBe(metrics!.navHeight);
    expect(metrics!.lastContentClearance).not.toBeNull();
    expect(metrics!.lastContentClearance!).toBeGreaterThanOrEqual(0);
  };

  for (const path of ["/", "/sites", "/field"]) {
    await checkBottomClearance(path);
  }

  await page.goto("/field");
  const workOrder = page.getByRole("link", { name: /E2E 과거 읽기 전용 · 작업 범위 승인/ });
  await expect(workOrder).toBeVisible();
  await checkBottomClearance((await workOrder.getAttribute("href"))!);
});

test("Home은 합성 운영 원장의 작업·현장 우선순위를 보여 준다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 원장은 읽기 전용이며 fixture를 전제하지 않습니다.");
  await page.goto("/");
  const attentionList = page.getByRole("region", { name: "확인 필요 현장 목록" });
  await expect(attentionList).toBeVisible();
  // The four historical records are excluded unless they need a decision. The
  // only two decision candidates are the awaiting-approval and review-ready rows.
  await expect(attentionList.getByRole("article")).toHaveCount(2);
  await expect(attentionList.getByRole("heading", { name: "E2E 과거 읽기 전용 · 작업 범위 승인" })).toBeVisible();
  await expect(attentionList.getByRole("heading", { name: "E2E 과거 읽기 전용 · 결과 검토 기록" })).toBeVisible();

  const initialSetup = page.getByRole("region", { name: "초기 설정이 필요한 현장" });
  // All seeded Sites already have a work order. Legacy UNMAPPED state must not
  // turn an in-use Site into an instruction to configure its optional AOI.
  await expect(initialSetup).toHaveCount(0);
});

test("핵심 전역 화면은 populated 상태에서도 막히거나 가로로 넘치지 않는다", async ({ page }) => {
  for (const path of ["/sites", "/field"]) {
    await page.goto(path);
    await expect(page.getByRole("main")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
});

test("현장 분석 목적지는 Site 접근은 유지하고 미구성 분석 API를 가용 오류로 표시한다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "미구성 분석·외부 기록은 격리된 로컬 fixture의 capability 조건입니다.");
  const siteHref = `/sites/${encodeURIComponent(syntheticSiteId)}`;
  await page.goto(`${siteHref}?section=analysis`);

  // 옛 영역 링크는 중간 설명 버튼 대신 같은 실제 owner route로 간다.
  await expect(page).toHaveURL(`${siteHref}/analysis`);
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "분석", exact: true })).toHaveCount(1);
  await expect(page.getByRole("main").getByRole("heading", { level: 2, name: "분석", exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("heading", { name: "E2E 현장 작업공간", exact: true })).toBeVisible();
  const main = page.getByRole("main");
  const history = main.getByRole("heading", { name: "변화 분석 이력", exact: true });
  const historyError = main.getByRole("alert").filter({ hasText: "분석 이력을 확인할 수 없습니다" });
  await expect(historyError).toBeVisible();
  await expect(historyError.getByRole("button", { name: "이력 다시 불러오기" })).toBeVisible();
  await expect(main.getByText(/0건|분석 결과/)).toHaveCount(0);
  await page.getByRole("button", { name: "새 분석 요청", exact: true }).click();
  await expect(page.getByRole("region", { name: "새 분석 요청", exact: true })).toBeVisible();
  await expect(history).toHaveCount(0);
  await page.getByRole("button", { name: "분석 이력으로 돌아가기", exact: true }).click();
  await expect(history).toBeVisible();
  await expect(page.getByRole("heading", { name: "현장을 찾을 수 없습니다" })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);

  await page.goto(`${siteHref}/observations`);
  await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByRole("main").getByRole("heading", { name: "외부 비교 이력" })).toBeVisible();
  const observationError = page.getByRole("main").getByRole("alert");
  await expect(observationError).toHaveCount(1);
  await expect(observationError).toBeVisible();
  await expect(observationError).toContainText("외부 비교 기록을 불러오지 못했습니다.");
  await expectNoHorizontalOverflow(page);
});

test("키보드는 내비게이션을 건너뛰고 화면 전환 뒤 본문 맥락을 이어 간다", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("region", { name: "확인 필요 현장 목록" })).toBeVisible();
  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "본문으로 건너뛰기" });
  await expect(skipLink).toBeFocused();
  const [skipBounds, mainBounds] = await Promise.all([
    skipLink.boundingBox(),
    page.locator("#main-content").boundingBox(),
  ]);
  expect(skipBounds).not.toBeNull();
  expect(mainBounds).not.toBeNull();
  expect(skipBounds!.x).toBeGreaterThanOrEqual(mainBounds!.x);
  expect(skipBounds!.x + skipBounds!.width).toBeLessThanOrEqual(mainBounds!.x + mainBounds!.width);
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
  for (const path of ["/", "/sites", "/field"]) {
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
  if (!hasSite && process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    test.skip(true, "읽기 전용 외부 원장에 표시할 현장이 없습니다.");
  }
  if (!hasSite) await expect(siteLink).toBeVisible();

  if (testInfo.project.name.startsWith("desktop")) {
    const views = page.getByRole("group", { name: "현장 보기 방식" });
    await expect(views).toBeVisible();
    // Human의 시각 식별 피드백: 새 사용자는 카드로, 저장된 목록 선호는 별도
    // view-modes 회귀에서 보존한다. 기본 표지 대신 실제 허용된 미리보기만 쓴다.
    await expect(views.getByRole("button", { name: "카드", exact: true })).toHaveAttribute("aria-pressed", "true");
    await views.getByRole("button", { name: "목록", exact: true }).click();
    await expect(page.getByText("관리 단계", { exact: true })).toBeVisible();
  } else {
    const compactList = page.getByRole("region", { name: "현장 목록" });
    await expect(compactList).toBeVisible();
    await expect(compactList.getByRole("link", { name: "현장 열기" }).first()).toBeVisible();
    await expect(page.getByText("관리 단계", { exact: true })).toBeHidden();
  }
  // D7: 실제 Home/Site 미리보기가 없는 자리를 장식 이미지로 채우지 않는다.
  // 대상 식별·상태·열기 동작은 모든 폭에서 그대로 남는다.
  const defaultVisualLabels = page.getByRole("main").getByText("기본 이미지", { exact: true });
  await expect(defaultVisualLabels).toHaveCount(0);
  await expect(page.getByRole("main").getByText("기본 표지", { exact: true })).toHaveCount(0);
  await expect(page.locator("[data-site-cover]")).toHaveCount(0);
  await expect(page.locator('main a[href^="/sites/"]:not([href="/sites/new"]) >> visible=true').first()).toBeVisible();
  if (testInfo.project.name.startsWith("desktop") && !process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    // This fixture has no Site-bootstrap capability. Do not advertise a link
    // that the exact registration-mode check rejects after navigation.
    await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toHaveCount(0);
    const unavailableAction = page.getByRole("button", { name: /현장 등록/ });
    const reason = page.getByText("현재 계정으로는 현장을 등록할 수 없습니다. 관리자에게 문의하세요.", { exact: true });
    await expect(reason).toBeHidden();
    await unavailableAction.click();
    await expect(reason).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(reason).toBeHidden();
    await expect(unavailableAction).toBeFocused();
  } else if (testInfo.project.name.startsWith("desktop")) {
    await expect(page.getByRole("link", { name: "현장 등록", exact: true }).or(page.getByRole("button", { name: /현장 등록/ }))).toBeVisible();
  } else {
    await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toBeHidden();
  }
  await expectNoHorizontalOverflow(page);
});

test("현장의 공간과 분석 메뉴가 자료 패널, 비교, 설정과 옛 주소를 연결한다", async ({ page }) => {
  const sitePath = `/sites/${encodeURIComponent(syntheticSiteId)}`;
  if (process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    test.skip(true, "이 테스트는 합성 현장과 작업을 사용합니다.");
  }
  await page.goto(sitePath);
  const siteNavigation = await openSiteMenu(page);
  await expect(siteNavigation.getByRole("link")).toHaveCount(2);
  await expect(siteNavigation.getByRole("link", { name: "공간", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(siteNavigation.getByRole("link", { name: "분석", exact: true })).toHaveAttribute("href", /\/analysis(?:\?|$)/);
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "공간", exact: true })).toHaveCount(1);

  const stage = page.getByRole("region", { name: "선택 관측 보기", exact: true });
  await expect(stage).toBeVisible();
  await expect(stage.getByRole("list", { name: "자료 등록 순서" })).toBeVisible();
  await expect(stage.getByText("다른 보기", { exact: true })).toHaveCount(0);

  const catalog = page.locator("#workbench-catalog");
  await page.getByRole("button", { name: "자료 패널 열기", exact: true }).click();
  await expect(catalog).toBeVisible();
  await expect(catalog.getByRole("button", { name: "자료", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(catalog.getByRole("searchbox", { name: "자료 검색" })).toBeVisible();
  await catalog.getByRole("button", { name: "등록 진행", exact: true }).click();
  await expect(catalog.getByRole("link", { name: "전체 작업에서 보기", exact: true })).toHaveAttribute("href", `/field?site=${encodeURIComponent(syntheticSiteId)}`);
  await page.keyboard.press("Escape");
  await expect(catalog).toBeHidden();

  const areaMenu = page.getByRole("button", { name: /^작업구역 · / });
  await areaMenu.click();
  await expect(page.getByRole("link", { name: "작업구역 관리", exact: true })).toHaveAttribute("href", /\/work-areas\?workAreaId=/);
  await page.keyboard.press("Escape");
  await expect(areaMenu).toBeFocused();

  const info = page.getByRole("region", { name: "자료 정보", exact: true });
  await page.getByRole("button", { name: "정보", exact: true }).click();
  await expect(info).toBeVisible();

  await page.goto(`${sitePath}/spatial-assets?kind=dsm`);
  await expect(page).toHaveURL(/panel=materials.*kind=dsm/);
  await expect(catalog.getByRole("combobox", { name: "종류" })).toHaveValue("dsm");
  await expectNoHorizontalOverflow(page);

  await page.goto(`${sitePath}?section=work-orders`);
  await expect(page).toHaveURL(/panel=intake/);
  await expect(catalog.getByRole("button", { name: "등록 진행", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(catalog.getByRole("region", { name: "등록 진행 중인 작업" }).getByRole("link", { name: "E2E 외부 산출물 등록", exact: true })).toBeVisible();

  await page.goto(`${sitePath}?section=manage`);
  await expect(page.getByRole("heading", { name: "현장 범위", exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "작업구역 관리", exact: true })).toHaveAttribute("href", `${sitePath}/work-areas`);
  await expectNoHorizontalOverflow(page);

  await page.goto(`${sitePath}?mode=results`);
  const resultsStage = page.getByRole("region", { name: "분석 결과 검토", exact: true });
  await expect(resultsStage).toBeVisible();
  await expect((await openSiteMenu(page)).getByRole("link", { name: "분석", exact: true })).toHaveAttribute("aria-current", "page");
  await expectNoHorizontalOverflow(page);

  await page.goto(`${sitePath}?mode=compare`);
  const compareStage = page.getByRole("region", { name: "두 시점 비교", exact: true });
  await expect(compareStage).toBeVisible();
  await expect(compareStage.getByRole("link", { name: "이 쌍으로 분석 조건 확인", exact: true })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("전역 작업 화면은 결정·진행·완료 원장을 구분하고 모호한 뒤로가기를 두지 않는다", async ({ page }) => {
  await page.goto("/field");
  await expect(page.getByRole("link", { name: "작업으로 이동" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "뒤로" })).toHaveCount(0);
  if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    const list = page.getByRole("region", { name: "작업 목록" });
    await expect(list.getByText("E2E 과거 읽기 전용 · 작업 범위 승인", { exact: true })).toBeVisible();
    await expect(list.getByText("E2E 과거 읽기 전용 · 승인 기록", { exact: true })).toBeVisible();
    await expect(list.getByText("E2E 과거 읽기 전용 · 결과 검토 기록", { exact: true })).toBeVisible();
    await expect(list.getByText("E2E 과거 읽기 전용 · 완료 기록", { exact: true })).toBeVisible();
    await expect(list.getByText("E2E 외부 산출물 등록", { exact: true })).toBeVisible();
    for (const [group, key, count] of [["결정 필요", "decisionRequired", 2], ["진행 중", "inFlight", 2], ["완료", "completed", 1]] as const) {
      await page.getByRole("navigation", { name: "작업 요약" }).getByRole("link", { name: new RegExp(`^${group}`) }).click();
      await expect.poll(() => new URL(page.url()).searchParams.get("group")).toBe(key);
      await expect(list.locator("li")).toHaveCount(count);
    }
  }
});

test("작업 상세는 실행 근거가 없으면 관리형 실행을 fail-closed로 숨긴다", async ({ page }) => {
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
  const workOrderLink = page.getByRole("link", {
    name: /E2E 과거 읽기 전용 · 작업 범위 승인/,
  });
  await expect(workOrderLink).toBeVisible();
  const workOrderHref = await workOrderLink.getAttribute("href");
  expect(workOrderHref).toMatch(/^\/field\/work-orders\/[^/]+$/);

  await page.goto(workOrderHref!);
  const main = page.getByRole("main");
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "E2E 과거 읽기 전용 · 작업 범위 승인" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "플랫폼 작업 상태", exact: true })).toBeVisible();
  await expect(main.getByText("승인 대기", { exact: true })).toBeVisible();
  await expect(main.getByText("이 작업에는 현재 플랫폼이 제공하는 외부 산출물 등록 흐름이 없습니다.", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "작업 운영" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "관측 자료 등록" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /승인|거절|작업 종료|내게 배정/ })).toHaveCount(0);
  await expect(main.getByText("Acquisition progress", { exact: true })).toHaveCount(0);
  await expect(main.getByText("전문가 복구 정보", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "수동 임무 복구 열기", exact: true })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  expect(browserFailures).toEqual([]);
});

test("외부 재구성 작업은 승인·운영 중 상태와 등록 UI를 제공한다", async ({ page }, testInfo) => {
  test.skip(
    Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL),
    "외부 원장은 읽기 전용이며 로컬 합성 외부 작업을 전제하지 않습니다.",
  );

  await page.goto("/field");
  const externalWorkOrder = page.getByRole("link", { name: /E2E 외부 산출물 등록/ });
  await expect(externalWorkOrder).toBeVisible();
  await externalWorkOrder.click();
  const main = page.getByRole("main");

  await expect(page.getByRole("heading", { level: 2, name: "관측 자료와 검사 확인" })).toBeVisible();
  await expect(page.getByRole("main").getByText("등록된 작업명 · E2E 외부 산출물 등록", { exact: true })).toBeVisible();
  const operations = page.locator("#work-operations");
  await expect(operations.getByRole("heading", { name: "작업 운영" })).toBeVisible();
  await expect(page.getByRole("link", { name: "공간의 등록 진행 보기" })).toContainText("등록 진행");
  await expect(main.getByText("운영 중", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "관측 자료 등록" })).toBeVisible();
  await expect(main.getByText("아직 등록된 관측 자료가 없습니다.", { exact: true })).toBeVisible();
  await expect(main.getByText(/측정 성공|정확도 검증 완료|산출물 검증 완료/)).toHaveCount(0);

  if (testInfo.project.name.startsWith("desktop")) {
    await expect(page.getByLabel("정사영상 GeoTIFF")).toBeVisible();
    await expect(page.getByRole("button", { name: "자료 등록 마치기" })).toBeDisabled();
  } else {
    await expect(main.getByText("노트북에서 계속", { exact: true }).first()).toBeVisible();
    await expect(page.getByLabel("정사영상 GeoTIFF")).toBeHidden();
  }

  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: "관측 자료와 검사 확인" })).toBeVisible();
  await expect(page.getByRole("main").getByText("등록된 작업명 · E2E 외부 산출물 등록", { exact: true })).toBeVisible();
  await expect(operations.getByRole("heading", { name: "작업 운영" })).toBeVisible();
  await expect(main.getByText("운영 중", { exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("핵심 화면에 중대 접근성 위반이 없고 reduced-motion 설정을 존중한다", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const path of ["/", "/sites", "/field"]) {
    await page.goto(path);
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 10_000 });
    await expectNoSeriousAxeViolations(page);
  }
});
