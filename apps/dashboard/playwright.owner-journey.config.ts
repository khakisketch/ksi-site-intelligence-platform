import { networkInterfaces } from "node:os";

import { defineConfig, devices } from "@playwright/test";

import { hasOnlyLoopbackAddresses } from "./e2e/fixtures/owner-journey-network-guard";

// Retained diagnostic configuration, not an approved runnable fixture.
// A loopback-only interface check cannot establish isolation or the ownership
// of other local services and build outputs. Refuse at config load before any
// webServer starts. The recipe below is preserved for review only.
const verifiedIsolatedRunnerAvailable = false;
if (!verifiedIsolatedRunnerAvailable) {
  throw new Error(
    "Owner-journey diagnostic is disabled: no verified task-owned network-isolated runner is configured.",
  );
}

// Historical candidate configuration (not currently executable):
// It was intended to avoid relying on the shared Playwright config:
// - It ignores KSI_DASHBOARD_E2E_BASE_URL entirely: the base URL is pinned
//   to the fixture this config itself launches. A custom `--config` pointing
//   elsewhere is a different file and gets none of this config's fixture.
// - It matches ONLY the owner-journey specs; nothing else can be collected
//   through this config.
// - BEFORE any webServer starts, it measures the real OS interfaces and
//   throws unless every address is loopback. On a normal host this fails
//   fast here — no server boots, no browser launches, no navigation, no
//   mutation. Actual runs happen in a network-isolated task-owned container
//   (docker --network none). Passing the check proves no isolation and
//   infers no ownership; it is a fail-closed tripwire, and the container
//   boundary is established by the operator.
// - The launched fixture is a fresh per-process seeded synthetic stack
//   (per-PID data dir; seeding refuses non-empty ledgers;
//   `reuseExistingServer: false` fails closed on port conflict instead of
//   latching onto someone else's server).
// - Recipe mirrors the shared config's seeded-stack invocation as of
//   2026-10-29; re-check if that recipe changes. This file duplicates it
//   deliberately so shared-config edits can never redirect this runner.

if (!hasOnlyLoopbackAddresses(networkInterfaces())) {
  const names = Object.keys(networkInterfaces()).sort().join(",");
  throw new Error(
    `refusing owner-journey dedicated run: non-loopback interface present (${names}); ` +
      "this mutating probe reproduces only in a network-isolated task-owned " +
      "container (e.g. docker --network none). No server was started and no " +
      "test ran.",
  );
}

const runStateDir = `test-results/runtime-owner-journey-${process.pid}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["zz-owner-journey-probe.spec.ts", "zz-owner-journey-refusal.spec.ts"],
  fullyParallel: false,
  // Single worker: the cold `next dev` fixture server intermittently resets
  // a first navigation when four fresh browsers hit it at once (observed:
  // tablet-768 /login interrupted twice in parallel runs, green alone and
  // green in an earlier parallel run). Serial execution keeps this safety
  // runner deterministic; it is runner tuning for a dev-mode fixture
  // server, not a product assertion, and production serves a built server.
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{-projectName}{ext}",
  use: {
    baseURL: "http://localhost:3230",
    colorScheme: "light",
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command:
      "node scripts/run-local-oidc-stack.mjs --tailscale disabled " +
      "--dashboard-port 3230 --core-port 8032 --issuer-port 9030 " +
      `--core-data-dir ${runStateDir}/core ` +
      `--identity-state-dir ${runStateDir}/identity ` +
      "--dashboard-dist-dir .next-e2e " +
      "--seed-operations-console-e2e",
    url: "http://localhost:3230/login",
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
