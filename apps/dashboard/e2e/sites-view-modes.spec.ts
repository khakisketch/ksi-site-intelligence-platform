import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "개발 Operations Console 시작" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/sites");
}

function viewButtons(page: Page) {
  const group = page.getByRole("group", { name: "현장 보기 방식" });
  return {
    group,
    cards: group.getByRole("button", { name: "카드", exact: true }),
    list: group.getByRole("button", { name: "목록", exact: true }),
  };
}

async function capture(page: Page, name: string) {
  const dir = process.env.KSI_DESIGN_EVIDENCE_DIR;
  if (dir) await page.screenshot({ path: join(dir, `${name}.png`), animations: "disabled" });
}

test("데스크톱은 2열 카드와 장식 없는 목록, 작은 화면은 기존 목록을 제공한다", async ({ page }, testInfo) => {
  await login(page);
  const views = viewButtons(page);
  if (!testInfo.project.name.startsWith("desktop")) {
    await expect(views.group).toBeHidden();
    await expect(page.getByRole("region", { name: "현장 목록" })).toBeVisible();
    return;
  }
  await expect(views.cards).toHaveAttribute("aria-pressed", "true");
  const cards = page.locator("[data-site-card]:visible");
  const count = await cards.count();
  if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) expect(count).toBeGreaterThanOrEqual(2);
  if (count >= 2) {
    const first = await cards.nth(0).boundingBox();
    const second = await cards.nth(1).boundingBox();
    expect(first!.y).toBe(second!.y);
    expect(second!.x).toBeGreaterThan(first!.x + first!.width);
  }
  const cover = await page.locator("[data-site-cover]:visible").first().boundingBox();
  expect(cover!.height).toBeGreaterThanOrEqual(150);
  expect(cover!.width).toBeGreaterThanOrEqual(320);
  await expect(page.getByText("기본 표지", { exact: true }).first()).toBeVisible();
  await capture(page, `multiple-cards-${testInfo.project.name}`);

  await views.list.focus();
  await page.keyboard.press("Enter");
  await expect(views.list).toHaveAttribute("aria-pressed", "true");
  await expect(views.list).toBeFocused();
  await expect(page.locator("[data-site-cover]:visible")).toHaveCount(0);
  await expect(page.getByText("진행 단계", { exact: true })).toBeVisible();
  const totalRows = Number(await page.locator('[data-site-list-view="list"]').getAttribute("data-site-total"));
  await expect(page.getByRole("link", { name: "현장 열기", exact: true })).toHaveCount(Math.min(totalRows, 10));
  expect(await page.getByText("기본 이미지", { exact: true }).evaluateAll((nodes) => nodes.some((n) => n.getBoundingClientRect().width > 0))).toBe(false);
  await capture(page, `multiple-list-${testInfo.project.name}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
});

test("보기 전환은 입력 중 검색과 정렬을 유지하고 한 현장 카드를 늘리지 않는다", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "두 보기 전환은 desktop 전용입니다.");
  await login(page);
  const views = viewButtons(page);
  await expect(views.cards).toHaveAttribute("aria-pressed", "true");
  const total = Number(await page.locator('[data-site-list-view="cards"]').getAttribute("data-site-total"));
  const firstHref = await page.locator("[data-site-card]:visible").first().getByRole("link", { name: "현장 열기", exact: true }).getAttribute("href");
  const id = decodeURIComponent(new URL(firstHref!, page.url()).pathname.split("/")[2]);
  await page.goto("/sites?group=attention&sort=updated");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  const before = page.url();
  await search.fill(id);
  await views.list.click();
  await expect(views.list).toHaveAttribute("aria-pressed", "true");
  // A presentation switch is not an implicit form submission or a new URL criterion.
  expect(new URL(page.url()).searchParams.has("view")).toBe(false);
  expect(new URL(before).searchParams.get("sort")).toBe("updated");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(id);
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
  expect(new URL(page.url()).searchParams.get("sort")).toBe("updated");
  await expect(search).toHaveValue(id);
  await expect(views.list).toHaveAttribute("aria-pressed", "true");
  await views.cards.click();
  await expect(page.locator("[data-site-card]:visible")).toHaveCount(1);
  const cardBox = await page.locator("[data-site-card]:visible").boundingBox();
  const mainBox = await page.getByRole("main").boundingBox();
  expect(cardBox!.width).toBeLessThan(mainBox!.width * 0.65);
  await expect(search).toHaveValue(id);
  expect(total).toBeGreaterThanOrEqual(1);
  await expect(page.locator('[data-site-list-view="cards"]')).toHaveAttribute("data-site-total", "1");
  await expect(page.locator('[data-site-list-view="cards"]')).toHaveAttribute("data-site-page", "1");
  await capture(page, `filtered-card-${testInfo.project.name}`);
  await views.list.click();
  await search.fill("목록 보기에서 없는 현장");
  await search.press("Enter");
  await expect(page.getByText("조건에 맞는 현장이 없습니다", { exact: true })).toHaveCount(1);
  await expect(page.getByText("현장 상태", { exact: true })).toBeHidden();
  await expect(views.list).toHaveAttribute("aria-pressed", "true");
});

test("마지막 보기는 새로고침·현장 상세 왕복·서버 첫 응답에서도 유지된다", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "브라우저의 desktop 표시 설정입니다.");
  await login(page);
  const views = viewButtons(page);
  const hydrationErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /hydrat|did not match|server rendered/i.test(message.text())) hydrationErrors.push(message.text());
  });
  await views.list.click();
  await expect(views.list).toHaveAttribute("aria-pressed", "true");
  const preference = (await page.context().cookies(page.url())).find((cookie) => cookie.value === "list" && cookie.path === "/sites");
  expect(preference).toBeTruthy();
  expect(preference!.httpOnly).toBe(false); // Functional display setting, never an auth cookie.
  const open = page.getByRole("link", { name: "현장 열기", exact: true }).first();
  await open.click();
  await expect.poll(() => new URL(page.url()).pathname).not.toBe("/sites");
  await page.goBack();
  await expect(views.list).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(views.list).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("[data-site-cover]:visible")).toHaveCount(0);
  const html = await (await page.request.get("/sites")).text();
  expect(html).toContain('data-site-list-view="list"');
  expect(hydrationErrors).toEqual([]);

  await page.context().addCookies([{ ...preference!, value: "not-a-valid-view" }]);
  await page.reload();
  await expect(views.cards).toHaveAttribute("aria-pressed", "true");
});

test("설정 저장이 제한돼도 현재 탭 전환은 동작하고 phone 배치는 강제하지 않는다", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "표시 설정 실패와 desktop→phone 전환 검사입니다.");
  await login(page);
  const views = viewButtons(page);
  await expect(views.cards).toHaveAttribute("aria-pressed", "true");
  const total = Number(await page.locator('[data-site-list-view="cards"]').getAttribute("data-site-total"));
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.evaluate(() => Object.defineProperty(document, "cookie", {
    configurable: true,
    get() { throw new DOMException("Storage is blocked", "SecurityError"); },
    set() { throw new DOMException("Storage is blocked", "SecurityError"); },
  }));
  await views.list.click();
  await expect(views.list).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("진행 단계", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "현장 열기", exact: true })).toHaveCount(Math.min(total, 10));
  expect(errors).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(views.group).toBeHidden();
  const searchBox = await page.getByRole("searchbox", { name: "현장 찾기" }).boundingBox();
  expect(searchBox!.width).toBeGreaterThanOrEqual(350);
  await expect(page.getByText("필터·정렬", { exact: true }).filter({ visible: true })).toBeVisible();
  expect(await page.getByText("기본 이미지", { exact: true }).evaluateAll((nodes) => nodes.some((n) => n.getBoundingClientRect().width > 0))).toBe(false);
  await page.setViewportSize({ width: 768, height: 1000 });
  await expect(views.group).toBeHidden();
  expect(await page.getByText("기본 이미지", { exact: true }).evaluateAll((nodes) => nodes.some((n) => n.getBoundingClientRect().width > 0))).toBe(true);
});
