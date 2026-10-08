import { mkdir } from "node:fs/promises";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

const siteId = "e2e-site-workspace";
const evidenceDirectory = join(process.cwd(), "p4-cleanup-evidence", process.env.P4_CAPTURE_PHASE ?? "before");

async function login(page: Page) {
  await page.goto("/");
  if (page.url().includes("/login")) {
    await page.getByRole("button", { name: /개발 Operations Console 시작|조직 계정으로 로그인/ }).click();
    const picker = page.getByRole("button", { name: /기본 개발 계정으로 계속/ });
    if (await picker.waitFor({ state: "visible", timeout: 5_000 }).then(() => true).catch(() => false)) {
      await picker.click();
    }
  }
  await expect(page).toHaveURL(/\/$/);
}

test("P4 surfaces render at the target viewport", async ({ page }, testInfo) => {
  const width = page.viewportSize()?.width;
  test.skip(![390, 768, 1440].includes(width ?? 0), "P4 capture uses only approved target widths.");
  await login(page);
  await mkdir(evidenceDirectory, { recursive: true });

  const paths = [
    ["home", "/"],
    ["sites", "/sites"],
    ["field", "/field"],
    ["site-workspace", `/sites/${siteId}`],
    ["site-changes", `/sites/${siteId}/changes`],
    ["site-progress", `/sites/${siteId}/progress`],
    ["site-report", `/sites/${siteId}/report`],
    ["events-retired", "/events"],
    ["missions-retired", "/missions"],
    ["settings-retired", "/settings"],
    ["reports-retired", "/reports"],
    ["assets-retired", "/assets"],
    ["world-retired", "/world"],
    ["pilot-retired", "/hil/pilot-bridge"],
    ["site-ai-retired", `/sites/${siteId}/ai`],
    ["site-design-retired", `/sites/${siteId}/design`],
    ["site-survey-retired", `/sites/${siteId}/surveys/new`],
    ["field-mission-retired", "/field/e2e-civil-postprocessing-fixture"],
  ] as const;

  for (const [name, path] of paths) {
    let observedResponse: Awaited<ReturnType<Page["goto"]>> = null;
    const onResponse = (response: Awaited<ReturnType<Page["goto"]>>) => {
      if (response && new URL(response.url()).pathname === path) observedResponse = response;
    };
    page.on("response", onResponse);
    let navigationFailed = false;
    try {
      observedResponse = await page.goto(path);
    } catch {
      // The disabled HIL route intentionally returns a bodyless 404; Chromium
      // can reject navigation even though the HTTP response is observable.
      navigationFailed = true;
    }
    page.off("response", onResponse);

    if (name === "pilot-retired") {
      const response = observedResponse;
      const status = response?.status() ?? null;
      const body = response ? await response.text().catch(() => "") : null;
      await testInfo.attach(`${name}-${width}-http`, {
        body: JSON.stringify({ path, status, bodyBytes: body === null ? null : Buffer.byteLength(body), navigationFailed }),
        contentType: "application/json",
      });
      expect(status, `${path} should preserve the disabled bodyless HIL response`).toBe(404);
      expect(body).toBe("");
      continue;
    }

    const response = observedResponse;
    if (name.endsWith("-retired")) {
      const finalPath = new URL(page.url()).pathname;
      expect(response?.status() === 404 || finalPath !== path, `${path} should 404 or redirect to a surviving surface`).toBe(true);
    } else {
      await expect(page.getByRole("main")).toBeVisible();
      await expect(page.getByRole("main")).not.toBeEmpty();
    }
    await expect(page.locator("body")).toBeVisible();
    await page.screenshot({
      path: join(evidenceDirectory, `${name}-${width}.png`),
      fullPage: true,
      animations: "disabled",
    });
    await testInfo.attach(`${name}-${width}-status`, {
      body: `${response?.status() ?? "no-response"} ${page.url()} ${await page.title()}`,
      contentType: "text/plain",
    });
  }
});
