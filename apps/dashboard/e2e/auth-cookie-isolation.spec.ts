import { expect, test } from "@playwright/test";

test.skip(
  Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL),
  "로컬 개발 로그인 계정과 same-host cookie fixture 전용입니다.",
);

function dashboardCookieUrl(): string {
  const baseURL = test.info().project.use.baseURL;
  if (typeof baseURL !== "string") throw new Error("Playwright baseURL이 필요합니다.");
  return new URL("/", baseURL).toString();
}

test("같은 host의 다른 Auth.js state cookie가 KSI OIDC callback을 망가뜨리지 않는다", async ({ page }) => {
  await page.goto("/login");
  await page.getByText("권한별 화면 테스트", { exact: true }).click();
  await page.getByRole("button", { name: "다른 개발 계정 선택" }).click();
  await expect(page).toHaveURL(/\/authorize/);

  // Browsers scope cookies by host/path, not port.  Simulate another local
  // Auth.js app on this Tailnet host completing an authorization request while
  // KSI waits at its own account picker.  KSI must read only its namespaced
  // transient state/PKCE cookies when the callback returns.
  await page.context().addCookies([
    {
      name: "authjs.state",
      value: "foreign-authjs-state-cookie",
      url: dashboardCookieUrl(),
    },
  ]);

  await page.getByRole("button", { name: "KSI 개발 관리자" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("main")).toBeVisible();
});

test("KSI callback 검증 실패는 generic server error 대신 로그인 복구 화면으로 돌아온다", async ({ page }) => {
  await page.goto("/login");
  await page.getByText("권한별 화면 테스트", { exact: true }).click();
  await page.getByRole("button", { name: "다른 개발 계정 선택" }).click();
  await expect(page).toHaveURL(/\/authorize/);

  await page.context().addCookies([
    {
      name: "ksi_auth_v1_state",
      value: "invalid-ksi-state-cookie",
      url: dashboardCookieUrl(),
    },
  ]);
  await page.getByRole("button", { name: "KSI 개발 관리자" }).click();

  await expect(page).toHaveURL(/\/login\?error=Configuration/);
  await expect(page.getByRole("status")).toContainText("기본 개발 계정으로 다시 시작");
  expect(page.url()).not.toContain("/api/auth/error");
});
