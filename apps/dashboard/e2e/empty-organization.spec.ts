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

test("빈 조직의 Work와 Events는 필터보다 단일 다음 행동을 먼저 보여 준다", async ({ page }, testInfo) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 IdP에는 로컬 빈 조직 계정이 없습니다.");
  await loginToEmptyOrganization(page);

  await page.goto("/field");
  await expect(page.getByText("현재 진행할 작업이 없습니다", { exact: true })).toBeVisible();
  const fieldRegistration = page.getByRole("link", { name: "현장 등록", exact: true });
  if (testInfo.project.name.startsWith("desktop")) {
    await expect(fieldRegistration).toBeVisible();
  } else {
    await expect(fieldRegistration).toHaveCount(0);
  }
  await expectNoHorizontalOverflow(page);

  await page.goto("/events");
  await expect(page.getByText("검토할 확인 항목이 없습니다", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "대기열 필터" })).toHaveCount(0);
  await expect(page.getByText("처리 상태", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "현장 상태 보기" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
