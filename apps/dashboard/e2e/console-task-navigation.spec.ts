import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: /개발 Operations Console 시작/ }).click();
  await expect(page).toHaveURL(/\/$/);
}

test.beforeEach(async ({ page }) => { await login(page); });

test("업무 검색과 상태 범위는 새로고침·뒤로가기에도 유지된다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "격리된 합성 원장의 이름과 건수를 검증합니다.");
  await page.goto("/field");
  const list = page.getByRole("region", { name: "관측 작업 목록", exact: true });
  await expect(list.locator("li")).toHaveCount(5);
  await expect(page.getByText("이 구분에 표시할 작업이 없습니다.")).toHaveCount(0);
  await page.getByRole("searchbox", { name: "작업 검색" }).fill("외부 산출물");
  await page.getByRole("search", { name: "관측 작업 검색" }).getByRole("button", { name: "검색", exact: true }).click();
  await expect(list.locator("li")).toHaveCount(1);
  await expect(list).toContainText("E2E 외부 산출물 등록");
  await page.reload();
  await expect(page.getByRole("searchbox", { name: "작업 검색" })).toHaveValue("외부 산출물");
  await expect(list.locator("li")).toHaveCount(1);
  await page.getByRole("navigation", { name: "작업 요약" }).getByRole("link", { name: /^완료/ }).click();
  await expect(page.getByText("조건에 맞는 작업이 없습니다", { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("q")).toBe("외부 산출물");
  await page.goBack();
  await expect(list.locator("li")).toHaveCount(1);
  await page.getByRole("link", { name: "필터 초기화", exact: true }).click();
  await expect(list.locator("li")).toHaveCount(5);
});

test("도움말은 계정에서 접근하며 FAQ를 키보드로 열 수 있다", async ({ page }) => {
  await page.goto("/more");
  await expect(page.getByRole("heading", { name: "내 계정" })).toBeVisible();
  await page.getByRole("main").getByRole("link", { name: "도움말·작업 안내" }).click();
  await expect(page).toHaveURL(/\/help$/);
  const question = page.locator("summary").filter({ hasText: "화면을 볼 수 있으면 물량 분석도 가능한가요?" });
  await question.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/열람·분석 적합성·정확도 평가·사람 검토는 서로 다릅니다/)).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/열람·분석 적합성·정확도 평가·사람 검토는 서로 다릅니다/)).not.toBeVisible();
  await page.getByRole("main").getByRole("link", { name: "내 계정", exact: true }).click();
  await expect(page).toHaveURL(/\/more$/);
});

test("자료 등록의 범위 선택은 현장 맥락을 유지하고 모바일 쓰기를 열지 않는다", async ({ page }) => {
  test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "격리된 합성 현장의 등록 진입입니다.");
  await page.goto("/field/new");
  await expect(page.getByRole("heading", { name: "어느 현장의 자료인가요?" })).toBeVisible();
  await page.getByRole("link", { name: /E2E 현장 작업공간/ }).click();
  await expect(page).toHaveURL(/\/sites\/e2e-site-workspace\/observations\/new$/);
  await expect(page.getByRole("heading", { name: "관측 자료 등록", exact: true, level: 2 })).toBeVisible();
  await expect(page.getByRole("list", { name: "자료 등록 흐름" })).toBeVisible();
  if ((page.viewportSize()?.width ?? 0) < 1024) {
    await expect(page.getByRole("button", { name: "관측 자료 등록 계속", exact: true })).not.toBeVisible();
  } else {
    await expect(page.getByRole("button", { name: "관측 자료 등록 계속", exact: true })).toBeDisabled();
    await page.getByRole("textbox", { name: "작업 이름", exact: true }).fill("범위 확인 — 제출하지 않음");
    await expect(page.getByRole("button", { name: "관측 자료 등록 계속", exact: true })).toBeEnabled();
  }
  await page.getByRole("link", { name: "현장으로 돌아가기", exact: true }).click();
  await expect(page).toHaveURL(/\/sites\/e2e-site-workspace\?workAreaId=/);
  expect(new URL(page.url()).searchParams.get("workAreaId")).toBeTruthy();
});
