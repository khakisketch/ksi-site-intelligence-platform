# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: empty-organization.spec.ts >> 빈 조직의 Work는 typed empty와 다음 행동을 보이고 Events는 의도적으로 404다
- Location: e2e/empty-organization.spec.ts:32:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: '등록된 관측 작업이 없습니다', exact: true })
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for getByRole('heading', { name: '등록된 관측 작업이 없습니다', exact: true })

```

```yaml
- link "본문으로 건너뛰기":
  - /url: "#main-content"
- navigation "주 메뉴":
  - text: 현장 지능
  - button "검색 · 이동 CtrlK"
  - link "홈":
    - /url: /
  - link "현장":
    - /url: /sites
  - link "작업":
    - /url: /field
  - text: 운영 지원
  - link "Dock·Edge 지원 범위":
    - /url: /coming-soon/fleet
  - text: local-empty-org-admin 관리자
  - button "로그아웃"
- banner:
  - paragraph: 작업
- main:
  - heading "작업" [level=1]
  - paragraph: 플랫폼 작업 원장에 기록된 관측 작업과 외부 결과 흐름입니다.
  - link "받은 업무":
    - /url: /field/inbox
  - link "팀 관리":
    - /url: /field/team
  - link "새 관측 시작":
    - /url: /field/new
  - paragraph: 등록된 관측 작업이 없습니다
  - paragraph: 현장 화면에서 작업구역을 확인하고 새 관측 작업을 시작할 수 있습니다.
  - link "현장 보기":
    - /url: /sites
- alert
```

# Test source

```ts
  1  | import { expect, test, type Page } from "@playwright/test";
  2  | 
  3  | async function loginToEmptyOrganization(page: Page) {
  4  |   await page.goto("/login");
  5  |   await page.getByText("권한별 화면 테스트", { exact: true }).click();
  6  |   await page.getByRole("button", { name: "다른 개발 계정 선택" }).click();
  7  |   await expect(page).toHaveURL(/\/authorize/);
  8  |   await page.getByText("권한별 화면 테스트(선택)", { exact: true }).click();
  9  |   await page.getByRole("button", { name: /KSI 빈 조직 관리자/ }).click();
  10 |   await expect(page).toHaveURL(/\/$/);
  11 |   await expect(page.getByRole("main")).toBeVisible();
  12 | }
  13 | 
  14 | async function expectNoHorizontalOverflow(page: Page) {
  15 |   const overflow = await page.evaluate(() => ({
  16 |     documentWidth: document.documentElement.scrollWidth,
  17 |     viewportWidth: document.documentElement.clientWidth,
  18 |   }));
  19 |   expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
  20 | }
  21 | 
  22 | test("빈 조직은 Home에서 거짓 운영 안건 없이 현장 등록 다음 행동을 보여 준다", async ({ page }) => {
  23 |   test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 IdP에는 로컬 빈 조직 계정이 없습니다.");
  24 |   await loginToEmptyOrganization(page);
  25 | 
  26 |   await expect(page.getByText("아직 등록된 현장이 없습니다", { exact: true })).toBeVisible();
  27 |   await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toBeVisible();
  28 |   await expect(page.getByRole("region", { name: "확인 필요 현장 캐러셀" })).toHaveCount(0);
  29 |   await expectNoHorizontalOverflow(page);
  30 | });
  31 | 
  32 | test("빈 조직의 Work는 typed empty와 다음 행동을 보이고 Events는 의도적으로 404다", async ({ page }) => {
  33 |   test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 IdP에는 로컬 빈 조직 계정이 없습니다.");
  34 |   await loginToEmptyOrganization(page);
  35 | 
  36 |   await page.goto("/field");
> 37 |   await expect(page.getByRole("heading", { name: "등록된 관측 작업이 없습니다", exact: true })).toBeVisible();
     |                                                                                     ^ Error: expect(locator).toBeVisible() failed
  38 |   await expect(page.getByText("현장 화면에서 작업구역을 확인하고 새 관측 작업을 시작할 수 있습니다.", { exact: true })).toBeVisible();
  39 |   await expect(page.getByRole("link", { name: "현장 보기", exact: true })).toBeVisible();
  40 |   await expect(page.locator('main a[href="/events"], main a[href="/missions"]')).toHaveCount(0);
  41 |   await expect(page.getByRole("navigation", { name: "대기열 필터" })).toHaveCount(0);
  42 |   await expectNoHorizontalOverflow(page);
  43 | 
  44 |   const retiredEventsResponse = await page.goto("/events");
  45 |   expect(retiredEventsResponse?.status()).toBe(404);
  46 | });
  47 | 
```