import { expect, test, type Page } from "@playwright/test";

async function login(page: Page, viewer = false) {
  await page.goto("/login");
  if (viewer) {
    await page.getByText("권한별 화면 테스트", { exact: true }).click();
    await page.getByRole("button", { name: "다른 개발 계정 선택" }).click();
    await page.getByText("권한별 화면 테스트(선택)", { exact: true }).click();
    await page.getByRole("button", { name: /KSI 개발 열람자/ }).click();
  } else {
    await page.getByRole("button", { name: "개발 Operations Console 시작" }).click();
  }
  await expect(page).toHaveURL(/\/$/);
}

test("읽기 전용 작업 등록 사유는 클릭·키보드로 열고 닫으며 요청을 보내지 않는다", async ({ page }) => {
  await login(page, true);
  await page.goto("/field");
  let mutations = 0;
  await page.route("**/api/**", async (route) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(route.request().method()) && !route.request().url().includes("/api/auth/")) {
      mutations += 1;
      await route.abort();
    } else await route.continue();
  });

  const action = page.getByRole("button", { name: /관측 자료 등록/ });
  const reason = page.getByText("현재 계정으로는 관측 자료를 등록할 수 없습니다. 작업 등록 권한이 있는 담당자에게 문의하세요.", { exact: true });
  await expect(reason).toBeHidden();
  await action.focus();
  await page.keyboard.press("Enter");
  await expect(reason).toBeVisible();
  const box = await reason.boundingBox();
  const width = page.viewportSize()!.width;
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  await page.keyboard.press("Escape");
  await expect(reason).toBeHidden();
  await expect(action).toBeFocused();
  await action.click();
  await expect(reason).toBeVisible();
  await page.getByRole("main").click({ position: { x: 8, y: 8 } });
  await expect(reason).toBeHidden();
  await action.click();
  await expect(reason).toBeVisible();
  await page.getByRole("main").getByRole("link", { name: "받은 업무함", exact: true }).click();
  await expect(reason).toBeHidden();
  expect(mutations).toBe(0);
});

test("구역 보관은 확인 전·취소·Escape에 실행되지 않고 확인 한 번만 전송한다", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "구역 변경은 기존 노트북 제한을 유지합니다.");
  await login(page);
  // The normal regression stack owns these synthetic fixtures. This test never forwards a mutation.
  if (process.env.KSI_DASHBOARD_E2E_BASE_URL) {
    test.skip(true, "실제 원장의 상태 변경은 별도 read-only 시연 검증에서 가로챕니다.");
  }
  await page.goto("/sites/e2e-site-workspace/work-areas");
  let attempts = 0;
  await page.route("**/api/**", async (route) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(route.request().method()) && !route.request().url().includes("/api/auth/")) {
      attempts += 1;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "검증용 일시 장애" }) });
    } else await route.continue();
  });
  const archive = page.getByRole("button", { name: "구역 보관", exact: true }).first();
  await archive.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "취소", exact: true })).toBeFocused();
  expect(attempts).toBe(0);
  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(attempts).toBe(0);
  await archive.click();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(archive).toBeFocused();
  expect(attempts).toBe(0);
  await archive.click();
  await dialog.getByRole("button", { name: "구역 보관", exact: true }).click();
  await expect.poll(() => attempts).toBe(1);
  await expect(page.getByRole("alert").filter({ hasText: /보관|검증용|처리/ })).toBeVisible();
});

test("검증용 저장 성공은 토스트, 실패는 입력을 보존한 영역 안내로 남긴다", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "팀원 변경은 기존 노트북 제한을 유지합니다.");
  await login(page);
  await page.goto("/field/team");
  const canSave = await page.getByRole("button", { name: "팀원 정보 저장" }).isVisible();
  test.skip(!canSave, "이 계정에는 팀 관리 권한이 없습니다.");

  let attempts = 0;
  await page.route("**/api/organization-work-roster/feedback-browser-fixture", async (route) => {
    attempts += 1;
    if (attempts > 1) {
      await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
      return;
    }
    const input = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      schemaVersion: "1.0", organizationId: "org-local-pilot", principalId: "feedback-browser-fixture",
      displayName: input.displayName, roleHint: input.roleHint, status: input.status,
      revision: 1, updatedAt: "2026-10-19T00:00:00Z", updatedBy: "local-admin",
    }) });
  });
  await page.getByLabel("사용자 ID", { exact: true }).fill("feedback-browser-fixture");
  await page.getByLabel("표시 이름", { exact: true }).fill("피드백 검증 담당자");
  await page.getByRole("button", { name: "팀원 정보 저장" }).click();
  const toast = page.getByRole("status").filter({ hasText: "팀원 정보를 저장했습니다." });
  await expect(toast).toBeVisible();
  await expect(page.getByRole("button", { name: "알림 닫기", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "알림 닫기", exact: true })).not.toBeFocused();
  await page.getByRole("button", { name: "알림 닫기", exact: true }).click();
  await expect(toast).not.toBeVisible();

  await page.getByLabel("사용자 ID", { exact: true }).fill("feedback-browser-fixture");
  await page.getByLabel("표시 이름", { exact: true }).fill("보존할 수정 이름");
  await page.getByRole("button", { name: "팀원 정보 저장" }).click();
  await expect(page.getByRole("status").filter({ hasText: "응답을 확인하지 못했습니다" })).toBeVisible();
  await expect(page.getByRole("button", { name: "같은 요청 다시 시도", exact: true })).toBeVisible();
  await expect(page.getByLabel("표시 이름", { exact: true })).toHaveValue("보존할 수정 이름");
  await expect(page.getByRole("button", { name: "알림 닫기", exact: true })).toHaveCount(0);
  expect(attempts).toBe(2);
});
