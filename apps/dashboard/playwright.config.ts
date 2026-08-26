import { defineConfig, devices } from "@playwright/test";

const externalBaseUrl = process.env.KSI_DASHBOARD_E2E_BASE_URL;
const baseURL = externalBaseUrl ?? "http://localhost:3230";
const localRunState = `apps/dashboard/test-results/runtime-${process.pid}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{-projectName}{ext}",
  use: {
    baseURL,
    colorScheme: "light",
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: externalBaseUrl
    ? undefined
    : {
        command:
          "node scripts/run-local-oidc-stack.mjs --tailscale disabled " +
          "--dashboard-port 3230 --core-port 8032 --issuer-port 9030 " +
          `--core-data-dir ${localRunState}/core ` +
          `--identity-state-dir ${localRunState}/identity ` +
          "--dashboard-dist-dir .next-e2e " +
          "--seed-operations-console-e2e",
        url: `${baseURL}/login`,
        reuseExistingServer: false,
        timeout: 120_000,
      },
  projects: [
    {
      name: "mobile-390",
      use: { ...devices["Desktop Chrome"], hasTouch: true, viewport: { width: 390, height: 844 } },
    },
    {
      name: "tablet-768",
      use: { ...devices["Desktop Chrome"], hasTouch: true, viewport: { width: 768, height: 1024 } },
    },
    { name: "desktop-1024", use: { ...devices["Desktop Chrome"], viewport: { width: 1024, height: 900 } } },
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
  ],
});
