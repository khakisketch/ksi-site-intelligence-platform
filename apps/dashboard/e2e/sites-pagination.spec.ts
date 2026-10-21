import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "개발 Operations Console 시작" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/sites");
}

function root(page: Page) { return page.locator("[data-site-list-view]:visible"); }
function cards(page: Page) { return page.locator("[data-site-card]:visible"); }
function pager(page: Page) { return page.getByRole("navigation", { name: "현장 페이지" }); }
async function capture(page: Page, name: string) {
  if (process.env.KSI_DESIGN_EVIDENCE_DIR) await page.screenshot({ path: join(process.env.KSI_DESIGN_EVIDENCE_DIR, `${name}.png`), animations: "disabled" });
}

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "번호 페이지와 생성 카드는 desktop 두 보기의 개선입니다.");
  await login(page);
});

test("카드는 실제 현장4개씩 나누고 마지막 페이지 생성 카드는 건수에서 뺀다", async ({ page }, testInfo) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "다섯 개의 명시적 격리 fixture로 페이지 경계를 확인합니다.");
  // D7 기본값은 밀도표이므로 카드 페이지 경계는 명시적 카드 보기에서 확인한다.
  await page.getByRole("group", { name: "현장 보기 방식" }).getByRole("button", { name: "카드", exact: true }).click();
  await expect(root(page)).toHaveAttribute("data-site-list-view", "cards");
  await expect(root(page)).toHaveAttribute("data-site-total", "5");
  await expect(root(page)).toHaveAttribute("data-site-page", "1");
  await expect(cards(page)).toHaveCount(4);
  await expect(page.locator("[data-site-create-card]:visible")).toHaveCount(0);
  const firstIds = await cards(page).evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-site-card")));
  await capture(page, `page1-four-${testInfo.project.name}`);
  await pager(page).getByRole("link", { name: "2", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("page")).toBe("2");
  await expect(root(page)).toHaveAttribute("data-site-page", "2");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.locator("[data-site-create-card]:visible")).toHaveCount(1);
  const gridBox = await cards(page).first().locator("..").boundingBox();
  const pageBox = await pager(page).boundingBox();
  expect(pageBox!.y - (gridBox!.y + gridBox!.height)).toBeGreaterThanOrEqual(12);
  expect(Math.abs((pageBox!.x + pageBox!.width / 2) - (gridBox!.x + gridBox!.width / 2))).toBeLessThanOrEqual(1);
  const finalId = await cards(page).first().getAttribute("data-site-card");
  expect(new Set([...firstIds, finalId]).size).toBe(5);
  await expect(pager(page).getByText("2", { exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "현장", level: 2 })).toBeInViewport();
  await capture(page, `page2-create-${testInfo.project.name}`);
  await page.reload();
  await expect(root(page)).toHaveAttribute("data-site-page", "2");
  await expect(cards(page)).toHaveCount(1);
  await page.getByRole("group", { name: "현장 보기 방식" }).getByRole("button", { name: "카드", exact: true }).click();
  await expect(root(page)).toHaveAttribute("data-site-page", "2");
  expect(new URL(page.url()).searchParams.get("page")).toBe("2");
  await page.getByRole("link", { name: "현장 열기", exact: true }).click();
  await page.goBack();
  await expect(root(page)).toHaveAttribute("data-site-page", "2");
  await expect(cards(page)).toHaveCount(1);
});

test("페이지·보기·정렬을 바꿔도 검색 범위를 잃거나 이전 검색 타이머를 실행하지 않는다", async ({ page }) => {
  await page.goto("/sites?q=e2e-site&sort=name");
  await expect(root(page)).toHaveAttribute("data-site-total", "5");
  // D7 기본값은 밀도표다 — 페이지 경계는 명시적 카드 보기에서 확인한다.
  await expect(root(page)).toHaveAttribute("data-site-list-view", "list");
  const modes = page.getByRole("group", { name: "현장 보기 방식" });
  await modes.getByRole("button", { name: "카드", exact: true }).click();
  await expect(root(page)).toHaveAttribute("data-site-list-view", "cards");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  await search.fill("아직 적용되지 않은 검색");
  await pager(page).getByRole("link", { name: "2", exact: true }).click();
  await expect(root(page)).toHaveAttribute("data-site-page", "2");
  await expect(search).toHaveValue("e2e-site");
  await page.waitForTimeout(450);
  expect(new URL(page.url()).searchParams.get("q")).toBe("e2e-site");
  expect(new URL(page.url()).searchParams.get("sort")).toBe("name");
  await modes.getByRole("button", { name: "목록", exact: true }).click();
  await expect(root(page)).toHaveAttribute("data-site-page", "1");
  await expect(root(page)).toHaveAttribute("data-site-list-view", "list");
  await expect(pager(page)).toBeHidden(); // Five rows fit in the ten-row list page.
  expect(new URL(page.url()).searchParams.get("q")).toBe("e2e-site");
  await modes.getByRole("button", { name: "카드", exact: true }).click();
  await pager(page).getByRole("link", { name: "2", exact: true }).click();
  await page.getByRole("combobox", { name: "정렬 기준" }).selectOption("updated");
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("updated");
  await expect(root(page)).toHaveAttribute("data-site-page", "1");
  await expect(cards(page)).toHaveCount(4);
  await pager(page).getByRole("link", { name: "2", exact: true }).click();
  await page.getByRole("group", { name: "현장 상태 필터" }).getByRole("link", { name: /^전체/ }).click();
  await expect(root(page)).toHaveAttribute("data-site-page", "1");
  expect(new URL(page.url()).searchParams.has("page")).toBe(false);
  expect(new URL(page.url()).searchParams.get("q")).toBe("e2e-site");
});

test("잘못된 페이지는 실제 범위로 보정하고 등록 권한 없는 생성 카드는 설명만 연다", async ({ page }) => {
  await page.goto("/sites?page=9999");
  await expect(root(page)).toHaveAttribute("data-site-total", "5");
  // 기본값 밀도표(10행)에서는 5행이 한 페이지에 든다.
  await expect(root(page)).toHaveAttribute("data-site-list-view", "list");
  await expect(root(page)).toHaveAttribute("data-site-page", "1");
  // 카드 보기(4행)에서는 같은 URL이 실제 마지막 페이지로 보정된다.
  const modes = page.getByRole("group", { name: "현장 보기 방식" });
  await modes.getByRole("button", { name: "카드", exact: true }).click();
  await expect(root(page)).toHaveAttribute("data-site-list-view", "cards");
  await page.goto("/sites?page=9999");
  await expect(root(page)).toHaveAttribute("data-site-page", "2");
  await expect(root(page)).toHaveAttribute("data-site-total", "5");
  await expect(cards(page)).toHaveCount(1);
  let writes = 0;
  await page.route("**/api/**", async (route) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(route.request().method()) && !route.request().url().includes("/api/auth/")) {
      writes += 1;
      await route.abort();
    } else await route.continue();
  });
  await expect(page.getByRole("link", { name: "새 현장 추가", exact: true })).toHaveCount(0);
  const trigger = page.getByRole("button", { name: "새 현장 추가", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("현재 계정으로는 현장을 등록할 수 없습니다. 관리자에게 문의하세요.", { exact: true })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/sites");
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  expect(writes).toBe(0);
  await page.goto("/sites?page=-2");
  await expect(root(page)).toHaveAttribute("data-site-page", "1");
  await expect(cards(page)).toHaveCount(4);
});

test("카드 폭은 제한되고 장식 없이 현장 식별 정보가 먼저 읽힌다", async ({ page }) => {
  // D7 기본값은 밀도표이므로 카드 치수는 명시적 카드 보기에서 확인한다.
  await page.getByRole("group", { name: "현장 보기 방식" }).getByRole("button", { name: "카드", exact: true }).click();
  await expect(root(page)).toHaveAttribute("data-site-list-view", "cards");
  for (const width of [1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    const first = cards(page).first();
    const cardBox = await first.boundingBox();
    expect(cardBox!.width).toBeLessThanOrEqual(480);
    // 표지 커버 대신 현장명·상태·다음 행동·열기 동작이 카드의 전부다.
    await expect(first.getByRole("heading", { level: 3 })).toBeVisible();
    await expect(first.getByRole("link", { name: "현장 열기", exact: true })).toBeVisible();
    await expect(first.locator("[data-site-cover]")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
  }
  await expect(page.getByText("기본 표지", { exact: true })).toHaveCount(0);
});
