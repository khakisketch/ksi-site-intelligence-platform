import { expect, test, type Page } from "@playwright/test";

const workspaceSite = "e2e-site-workspace";
const optOutSite = "e2e-site-review";
const eventKey = "e2e-edge-fixture::event-open-with-evidence";

test.skip(
  process.env.KSI_DASHBOARD_E2E_PHASE2 !== "1",
  "Phase 2 synthetic staging에서만 실행합니다.",
);

async function login(page: Page) {
  await page.goto("/");
  if (page.url().includes("/login")) {
    await page.getByRole("button", { name: "조직 계정으로 로그인" }).click();
    await page.getByRole("button", { name: "기본 개발 계정으로 계속" }).click();
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

async function startConversation(page: Page) {
  await page.goto(`/sites/${workspaceSite}/ai`);
  await page.getByRole("button", { name: "새 대화" }).click();
  await expect(page.getByText("첫 질문을 입력해 주세요", { exact: false })).toBeVisible();
}

async function ask(page: Page, question: string) {
  await page.getByLabel("KSI AI에게 질문").fill(question);
  await page.getByRole("button", { name: "질문 보내기" }).click();
  await expect(page.locator('section[aria-busy="false"]')).toBeVisible({ timeout: 15_000 });
}

test.beforeEach(async ({ page }) => {
  await login(page);
});

test("TLS·OIDC·합성 운영 원장이 네 핵심 화면에서 유지된다", async ({ page }) => {
  expect(new URL(page.url()).protocol).toBe("https:");
  await expect(page.getByRole("region", { name: "확인 필요 현장 캐러셀" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "E2E 작업 범위 승인" })).toBeVisible();
  for (const path of ["/", "/sites", "/field", "/events", `/sites/${workspaceSite}`]) {
    await page.goto(path);
    await expect(page.getByRole("main")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    expect(new URL(page.url()).protocol).toBe("https:");
  }
  await expect(page.getByRole("heading", { level: 2, name: "E2E 현장 작업공간" })).toBeVisible();
});

test("S3 실바이트를 presigned URL로 열고 근거 검증된 AI 답변을 표시한다", async ({ page }) => {
  await page.goto(`/events/${encodeURIComponent(eventKey)}`);
  await page.getByRole("button", { name: "열어보기" }).click();
  const image = page.getByRole("img", { name: "증거 e2e-evidence-image-001" });
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth))
    .toBeGreaterThan(0);

  await startConversation(page);
  await ask(page, "이 현장의 최신 상태를 합성 근거로만 알려주세요.");
  await expect(page.getByText("합성 Staging 근거만 설명", { exact: false })).toBeVisible();
  await expect(page.getByText("검증된 근거", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "E2E 현장 작업공간 현장 최신 상태" })).toBeVisible();
});

test("AI 미동의·provider 오류·허위 citation을 모두 fail-closed 처리한다", async ({ page }) => {
  await page.goto(`/sites/${optOutSite}/ai`);
  await expect(
    page.getByRole("heading", { name: "이 현장에서는 AI를 아직 사용하지 않습니다" }),
  ).toBeVisible();

  await startConversation(page);
  await ask(page, "[fixture:provider-500] provider 실패 경계를 확인합니다.");
  await expect(page.getByText("확인 가능한 근거가 부족해 답변을 완료하지 않았습니다.")).toBeVisible();
  await expect(page.getByText("AI 연결이 일시적으로 응답하지 않았습니다.")).toBeVisible();

  await startConversation(page);
  await ask(page, "[fixture:unknown-citation] 허용되지 않은 citation을 확인합니다.");
  await expect(page.getByText("확인 가능한 근거가 부족해 답변을 완료하지 않았습니다.")).toBeVisible();
  await expect(page.getByText("검증된 근거만으로 답을 만들 수 없습니다.")).toBeVisible();
  await expect(page.getByRole("link", { name: /cross-site-forbidden/ })).toHaveCount(0);
});
