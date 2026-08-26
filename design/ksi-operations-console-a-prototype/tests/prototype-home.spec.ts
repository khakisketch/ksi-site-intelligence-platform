import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/?legacy=1");
});

test("portfolio home presents evidence-backed site cases instead of a safety task queue", async ({ page }) => {
  const home = page.getByTestId("portfolio-home");
  await expect(home).toBeVisible();
  await expect(page.getByRole("heading", { name: "4개 현장" })).toBeVisible();
  await expect(home.getByText("이번 관측에서는")).toBeVisible();
  await expect(page.getByRole("heading", { name: "지금 볼 안건" })).toBeVisible();

  const rows = home.locator(".insight-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("서초 복합물류센터");
  await expect(rows.nth(0)).toContainText("추가 근거가 필요합니다");
  await expect(rows.nth(1)).toContainText("김포 제조공장");
  await expect(rows.nth(1)).toContainText("공정 의미를 확인해야 합니다");

  await expect(page.getByText(/장애물|안전 확인|자동 진행 중/)).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "주요 메뉴" })).toContainText("안건");
});

test("portfolio home has no horizontal overflow and keeps primary targets touch-sized", async ({ page }) => {
  await expect(page.getByTestId("portfolio-home")).toBeVisible();

  const layout = await page.evaluate(() => {
    const viewport = document.querySelector<HTMLElement>('[data-testid="mobile-app-viewport"]')!;
    const scroll = document.querySelector<HTMLElement>('[data-testid="mobile-scroll"]')!;
    const targets = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".insight-row, .portfolio-cover__heading button, .coverage-row, .ask-entry, .bottom-nav button",
      ),
    );
    return {
      viewportWidth: viewport.clientWidth,
      scrollWidth: scroll.scrollWidth,
      smallestTarget: Math.min(...targets.map((target) => target.getBoundingClientRect().height)),
    };
  });

  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.viewportWidth + 1);
  expect(layout.smallestTarget).toBeGreaterThanOrEqual(44);
});

test("site navigation owns spatial results, reports, and observation history", async ({ page }) => {
  await page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("button", { name: "현장" }).click();
  await expect(page.getByTestId("site-list")).toBeVisible();
  await page.getByRole("button", { name: /서초 복합물류센터/ }).click();

  await expect(page.getByTestId("site-home")).toBeVisible();
  await expect(page.getByRole("heading", { name: "서초 복합물류센터" })).toBeVisible();
  await expect(page.getByRole("button", { name: /2D·3D 공간뷰/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /보고서/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /조사·재관측/ })).toBeVisible();
});

test("a site case exposes claim, uncertainty, evidence, and a human follow-up", async ({ page }) => {
  await page.getByRole("button", { name: /서초 복합물류센터, 남측 토공 구역/ }).click();
  await expect(page.getByTestId("case-detail")).toBeVisible();
  await expect(page.getByRole("heading", { name: "남측 토공 구역은 추가 근거가 필요합니다" })).toBeVisible();
  await expect(page.getByText("불확실성과 제한")).toBeVisible();
  await expect(page.getByRole("heading", { name: "판단 근거" })).toBeVisible();
  await expect(page.getByText("검증된 원본 184장 · 누락 구간 2곳")).toBeVisible();

  await page.getByRole("button", { name: "결정 옵션 보기" }).click();
  await expect(page.getByRole("heading", { name: "이 안건의 다음 단계" })).toBeVisible();
  await expect(page.getByRole("button", { name: /추가 관측 초안 검토/ })).toContainText("노트북");
  await page.getByRole("button", { name: /현장 담당자에게 확인 요청/ }).click();
  await expect(page.getByRole("status")).toHaveText("현장 담당자 확인 요청을 기록했습니다");
  await expect(page.getByRole("button", { name: "결정 내용 보기" })).toBeVisible();
});

test("grounded questions state evidence and product limitations", async ({ page }) => {
  await page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("button", { name: "질문" }).click();
  await expect(page.getByTestId("ai-screen")).toBeVisible();
  await page.getByRole("button", { name: "근거가 부족한 현장은 어디인가요?" }).click();

  await expect(page.getByText(/유효 촬영 범위가 61%/)).toBeVisible();
  await expect(page.getByText(/추가 관측은 아직 승인되지 않았습니다/)).toBeVisible();
  await expect(page.getByRole("button", { name: /촬영 범위 보고 · 61%/ })).toBeVisible();
  await expect(page.getByText(/AI는 비행·승인·계약 수량을 결정하지 않습니다/)).toBeVisible();
});
