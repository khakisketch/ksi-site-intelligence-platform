import { expect, test, type Page } from "@playwright/test";

// F-01 mapped bootstrap acceptance spec (local synthetic only).
//
// This spec requires an externally managed, isolated OIDC stack whose Core was
// started with a protected v2 subject registry that grants SITE_BOOTSTRAP to the
// default development account:
//
//   node apps/dashboard/scripts/run-local-oidc-stack.mjs --tailscale disabled \
//     --dashboard-port 3235 --core-port 8071 --issuer-port 9071 \
//     --core-data-dir <scratch>/core-data --identity-state-dir <scratch>/identity \
//     --dashboard-dist-dir .next-f01-d3 \
//     --oidc-subject-registry-file <protected-dir>/registry-v2.json
//
//   KSI_F01_E2E=1 KSI_DASHBOARD_E2E_BASE_URL=http://localhost:3235 \
//     npx playwright test e2e/f01-site-bootstrap.spec.ts
//
// The default auto-started dev stack has no capability account, so this spec is
// skipped in ordinary e2e runs rather than silently testing the legacy path.

const enabled =
  process.env.KSI_F01_E2E === "1" && Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL);

async function login(page: Page) {
  await page.goto("/");
  if (page.url().includes("/login")) {
    await page
      .getByRole("button", { name: /개발 Operations Console 시작|조직 계정으로 로그인/ })
      .click();
    const accountPicker = page.getByRole("button", { name: /기본 개발 계정으로 계속/ });
    const hasAccountPicker = await accountPicker
      .waitFor({ state: "visible", timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (hasAccountPicker) await accountPicker.click();
  }
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("main")).toBeVisible();
}

test.describe("F-01 mapped site bootstrap", () => {
  test.skip(!enabled, "requires KSI_F01_E2E=1 and an external v2-registry stack");

  test("creates a site without a customer site id and navigates by the server id", async ({
    page,
  }, testInfo) => {
    // The wizard is desktop-only by design (ResponsiveActionBoundary); the
    // mobile/tablet projects assert that boundary elsewhere, not this flow.
    test.skip(
      !testInfo.project.name.startsWith("desktop"),
      "registration wizard is desktop-only",
    );
    await login(page);

    await page.goto("/sites/new");
    await expect(page.getByRole("heading", { name: "현장 등록" })).toBeVisible();
    // Mapped mode hides the client-chosen id entirely.
    await expect(page.getByLabel("현장 ID")).toHaveCount(0);
    // The disabled-next reason must be visible at the standard desktop viewport,
    // not hidden below the fold.
    await expect(page.getByText("현장 이름을 입력하세요.")).toBeInViewport();

    const name = `F-01 e2e 현장 ${Date.now()}`;
    await page.getByLabel("현장 이름").fill(name);
    await page.getByRole("button", { name: "다음" }).click();

    // Draw a small quad on the AOI map: choose the polygon tool, click four
    // points, then click the first point again to finish (Leaflet.draw).
    await page.getByRole("link", { name: "현장 범위 다각형 그리기" }).click();
    const map = page.locator(".leaflet-container").first();
    const box = await map.boundingBox();
    expect(box).not.toBeNull();
    if (!box) return;
    const points: Array<[number, number]> = [
      [box.x + box.width * 0.3, box.y + box.height * 0.4],
      [box.x + box.width * 0.7, box.y + box.height * 0.4],
      [box.x + box.width * 0.7, box.y + box.height * 0.7],
      [box.x + box.width * 0.3, box.y + box.height * 0.7],
    ];
    // Leaflet.draw drops vertices when clicks arrive back-to-back; a real
    // pointer moves between clicks, so space them.
    for (const [x, y] of points) {
      await page.mouse.move(x, y);
      await page.waitForTimeout(180);
      await page.mouse.click(x, y);
      await page.waitForTimeout(300);
    }
    // Click the first vertex marker again to close the polygon (snap-finish).
    const firstMarker = await page.locator(".leaflet-editing-icon").first().boundingBox();
    expect(firstMarker).not.toBeNull();
    if (!firstMarker) return;
    await page.mouse.move(
      firstMarker.x + firstMarker.width / 2,
      firstMarker.y + firstMarker.height / 2,
    );
    await page.waitForTimeout(180);
    await page.mouse.click(
      firstMarker.x + firstMarker.width / 2,
      firstMarker.y + firstMarker.height / 2,
    );
    await expect(page.getByRole("link", { name: "완료" })).toHaveCount(0);

    await page.getByLabel("현장 좌표계").fill("EPSG:5186");
    await page.getByLabel("높이 기준").fill("KNGeoid2018");
    await page.getByRole("button", { name: "다음" }).click();

    // Confirm step: no phantom client id row in mapped mode.
    await expect(page.getByRole("heading", { name: "등록 내용을 확인하세요" })).toBeVisible();
    const summary = page.locator("main dl");
    await expect(summary).toContainText("현장 범위");
    await expect(summary).not.toContainText("현장 ID");

    await page.getByRole("button", { name: "현장 등록" }).click();

    // Success shows the receipt state; navigation happens on the explicit
    // follow-up action. The follow-up target is the server-issued id.
    const goBriefing = page.getByRole("button", { name: "현장 브리핑으로 이동" });
    await expect(goBriefing).toBeVisible({ timeout: 10_000 });
    await goBriefing.click();
    await expect(page).toHaveURL(/\/sites\/site-[0-9a-f-]{36}$/);
    const serverUrl = page.url();
    await expect(page.getByRole("heading", { name })).toBeVisible();

    await page.reload();
    await expect(page).toHaveURL(serverUrl);
    await expect(page.getByRole("heading", { name })).toBeVisible();
  });
});
