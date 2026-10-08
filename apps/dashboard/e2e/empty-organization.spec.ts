import { expect, test, type Page } from "@playwright/test";

async function loginToEmptyOrganization(page: Page) {
  await page.goto("/login");
  await page.getByText("권한별 화면 테스트", { exact: true }).click();
  await page.getByRole("button", { name: "다른 개발 계정 선택" }).click();
  await expect(page).toHaveURL(/\/authorize/);
  await page.getByText("권한별 화면 테스트(선택)", { exact: true }).click();
  await page.getByRole("button", { name: /KSI 빈 조직 관리자/ }).click();
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

test("빈 조직은 Home에서 거짓 운영 안건 없이 현장 등록 다음 행동을 보여 준다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 IdP에는 로컬 빈 조직 계정이 없습니다.");
  await loginToEmptyOrganization(page);

  await expect(page.getByText("아직 등록된 현장이 없습니다", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "확인 필요 현장 캐러셀" })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("빈 조직의 현장 등록은 단일 실제 행동으로 제공한다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 IdP에는 로컬 빈 조직 계정이 없습니다.");
  await loginToEmptyOrganization(page);

  await page.goto("/sites");
  const register = page.getByRole("link", { name: "첫 현장 등록하기", exact: true });
  await expect(register).toBeVisible();
  await expect(register).toHaveAttribute("href", "/sites/new");
  await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toHaveCount(0);
  await expect(page.getByText(/DJI Pilot|KMZ|초기 매핑 비행|두 번째 조사부터 분석/)).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("권한 없는 현장 상세는 식별 정보를 노출하지 않는 제목 있는 거부 상태를 보인다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 IdP에는 로컬 빈 조직 계정이 없습니다.");
  await loginToEmptyOrganization(page);

  await page.goto("/sites/e2e-site-workspace");
  await expect(page.getByRole("heading", { level: 1, name: "현장 상세", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "현장을 찾을 수 없습니다", exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByText("요청한 현장에 접근할 수 없습니다. 현장 목록에서 접근 가능한 현장을 확인하세요.", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "현장 목록으로", exact: true })).toHaveAttribute("href", "/sites");
  await expect(page.getByText("E2E 현장 작업공간", { exact: true })).toHaveCount(0);

  await page.goto("/sites/e2e-site-workspace/analysis");
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "현장 분석", exact: true })).toHaveCount(1);
  await expect(page.getByRole("main").getByRole("heading", { level: 2, name: "현장을 찾을 수 없습니다", exact: true })).toBeVisible();
  await expect(page.getByText("요청한 현장에 접근할 수 없습니다. 현장 목록에서 접근 가능한 현장을 확인하세요.", { exact: true })).toBeVisible();
  await expect(page.getByText("E2E 현장 작업공간", { exact: true })).toHaveCount(0);

  await page.goto("/sites/e2e-site-workspace/spatial-assets");
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "현장 공간 자산", exact: true })).toHaveCount(1);
  await expect(page.getByRole("main").getByRole("heading", { level: 2, name: "현장을 찾을 수 없습니다", exact: true })).toBeVisible();
  await expect(page.getByText("요청한 현장에 접근할 수 없습니다. 현장 목록에서 접근 가능한 현장을 확인하세요.", { exact: true })).toBeVisible();
  await expect(page.getByText("E2E 현장 작업공간", { exact: true })).toHaveCount(0);
});

test("빈 조직의 Work는 typed empty와 다음 행동을 보이고 Events는 의도적으로 404다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 IdP에는 로컬 빈 조직 계정이 없습니다.");
  await loginToEmptyOrganization(page);

  await page.goto("/field");
  // EmptyState intentionally renders its title as paragraph text, not a heading.
  await expect(page.getByText("등록된 관측 작업이 없습니다", { exact: true })).toBeVisible();
  await expect(page.getByText("현장 화면에서 작업구역을 확인하고 새 관측 작업을 시작할 수 있습니다.", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "현장 보기", exact: true })).toBeVisible();
  await expect(page.locator('main a[href="/events"], main a[href="/missions"]')).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "대기열 필터" })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);

  const retiredEventsResponse = await page.goto("/events");
  expect(retiredEventsResponse?.status()).toBe(404);
});
