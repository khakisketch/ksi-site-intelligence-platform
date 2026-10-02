import {
  chmodSync,
  closeSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { randomBytes } from "node:crypto";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { createAnalysisTsconfig } from "./scripts/analysis-tsconfig.mjs";

function assertPrivateFile(path: string, mode: number): void {
  const metadata = lstatSync(path);
  if (
    !metadata.isFile()
    || metadata.isSymbolicLink()
    || metadata.uid !== process.getuid?.()
    || (metadata.mode & 0o777) !== mode
  ) {
    throw new Error(`unsafe Analysis E2E runtime file: ${path}`);
  }
}

type AnalysisE2EScenario = "normal" | "missing-vertical-reference" | "overlapping-current-nodata-cell" | "viewer-readonly" | "weekly-reuse";
const scenarioValue = process.env.KSI_ANALYSIS_E2E_SCENARIO ?? "normal";
if (
  scenarioValue !== "normal"
  && scenarioValue !== "missing-vertical-reference"
  && scenarioValue !== "overlapping-current-nodata-cell"
  && scenarioValue !== "viewer-readonly"
  && scenarioValue !== "weekly-reuse"
) {
  throw new Error(`unsupported Analysis E2E scenario: ${scenarioValue}`);
}
const scenario: AnalysisE2EScenario = scenarioValue;

function validateInheritedRuntime(root: string, runId: string): void {
  const expectedParent = realpathSync(tmpdir());
  const canonicalRoot = realpathSync(root);
  const metadata = lstatSync(root);
  if (
    canonicalRoot !== root
    || metadata.isSymbolicLink()
    || !metadata.isDirectory()
    || metadata.uid !== process.getuid?.()
    || (metadata.mode & 0o777) !== 0o700
    || resolve(root, "..") !== expectedParent
    || !root.split(/[\\/]/).at(-1)?.startsWith("ksi-analysis-e2e-")
  ) {
    throw new Error("inherited Analysis E2E runtime directory is unsafe or outside its private temp root");
  }
  const marker = join(root, "run-identity");
  assertPrivateFile(marker, 0o600);
  if (readFileSync(marker, "utf8") !== runId) {
    throw new Error("inherited Analysis E2E run identity does not match its owner marker");
  }
}

const inheritedRoot = process.env.KSI_ANALYSIS_E2E_DATA_DIR;
const inheritedRunId = process.env.KSI_ANALYSIS_E2E_RUN_ID;
if (Boolean(inheritedRoot) !== Boolean(inheritedRunId)) {
  throw new Error("incomplete inherited Analysis E2E runtime identity");
}
const ownsRuntimeRoot = inheritedRoot === undefined;
const runtimeRoot = ownsRuntimeRoot
  ? mkdtempSync(join(tmpdir(), "ksi-analysis-e2e-"))
  : inheritedRoot;
const runId = ownsRuntimeRoot ? randomBytes(32).toString("hex") : inheritedRunId!;
if (ownsRuntimeRoot) {
  chmodSync(runtimeRoot, 0o700);
  const ownerFile = openSync(join(runtimeRoot, "run-identity"), "wx", 0o600);
  try {
    writeFileSync(ownerFile, runId, "utf8");
  } finally {
    closeSync(ownerFile);
  }
} else {
  validateInheritedRuntime(runtimeRoot, runId);
}
const secretsDirectory = join(runtimeRoot, "secrets");
if (ownsRuntimeRoot) {
  mkdirSync(secretsDirectory, { mode: 0o700 });
  chmodSync(secretsDirectory, 0o700);
} else {
  const metadata = lstatSync(secretsDirectory);
  if (
    metadata.isSymbolicLink()
    || !metadata.isDirectory()
    || metadata.uid !== process.getuid?.()
    || (metadata.mode & 0o777) !== 0o700
  ) {
    throw new Error("inherited Analysis E2E secrets directory is unsafe");
  }
}

function createSecret(path: string): void {
  const file = openSync(path, "wx", 0o600);
  try {
    writeFileSync(file, randomBytes(48).toString("base64url"), "utf8");
  } finally {
    closeSync(file);
  }
  chmodSync(path, 0o600);
}

const clientSecretFile = join(secretsDirectory, "oidc-client.secret");
const sessionSecretFile = join(secretsDirectory, "dashboard-session.secret");
const globalSetupFile = join(runtimeRoot, "global-setup.cjs");
if (ownsRuntimeRoot) {
  createSecret(clientSecretFile);
  createSecret(sessionSecretFile);
  writeFileSync(
    globalSetupFile,
    `module.exports = async function setupAnalysisE2EEnvironment() {\n  const values = ${JSON.stringify({
      KSI_ANALYSIS_E2E_CORE_ORIGIN: "http://127.0.0.1:8033",
      KSI_ANALYSIS_E2E_ISSUER_ORIGIN: "http://localhost:9031",
      KSI_ANALYSIS_E2E_DASHBOARD_ORIGIN: "http://localhost:3231",
      KSI_ANALYSIS_E2E_CLIENT_ID: "ksi-operations-console",
      KSI_ANALYSIS_E2E_CLIENT_SECRET_FILE: clientSecretFile,
      KSI_ANALYSIS_E2E_DATA_DIR: runtimeRoot,
      KSI_ANALYSIS_E2E_RUN_ID: runId,
      KSI_ANALYSIS_E2E_SCENARIO: scenario,
    })};\n  for (const [key, value] of Object.entries(values)) process.env[key] = value;\n};\n`,
    { flag: "wx", mode: 0o600 },
  );
  chmodSync(globalSetupFile, 0o600);
} else {
  assertPrivateFile(clientSecretFile, 0o600);
  assertPrivateFile(sessionSecretFile, 0o600);
  assertPrivateFile(globalSetupFile, 0o600);
}

const coreOrigin = "http://127.0.0.1:8033";
const issuerOrigin = "http://localhost:9031";
const dashboardOrigin = "http://localhost:3231";
const dashboardDistDirectory = join("test-results", `analysis-next-${runId}`);
const dashboardTsconfig = createAnalysisTsconfig({
  projectRoot: process.cwd(), runId, distDir: dashboardDistDirectory, reuse: !ownsRuntimeRoot,
});
const nextExecutable = resolve("node_modules/next/dist/bin/next");
const quote = (value: string) => `'${value.replaceAll("'", "'\\''")}'`;

export default defineConfig({
  testDir: "./analysis-e2e",
  outputDir: `test-results/analysis-playwright-${process.pid}`,
  globalSetup: globalSetupFile,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: dashboardOrigin,
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: [
        "uv",
        "run",
        "--locked",
        "python",
        "analysis-e2e/run_core_fixture.py",
        "--data-dir",
        runtimeRoot,
        "--run-id",
        runId,
        "--client-secret-file",
        clientSecretFile,
        "--dashboard-origin",
        dashboardOrigin,
        "--core-port",
        "8033",
        "--issuer-port",
        "9031",
        "--scenario",
        scenario,
      ].map(quote).join(" "),
      url: `${coreOrigin}/ready`,
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGINT", timeout: 5_000 },
      env: { PYTHONUNBUFFERED: "1" },
    },
    {
      command: [
        process.execPath,
        nextExecutable,
        "dev",
        "--hostname",
        "127.0.0.1",
        "--port",
        "3231",
      ].map(quote).join(" "),
      url: `${dashboardOrigin}/login`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        CORE_API_BASE_URL: coreOrigin,
        KSI_DASHBOARD_DEPLOYMENT_PROFILE: "LOCAL",
        KSI_DASHBOARD_HUMAN_AUTH_MODE: "OIDC",
        KSI_DASHBOARD_LOCAL_IDENTITY_ENABLED: "1",
        KSI_DASHBOARD_OIDC_ISSUER: issuerOrigin,
        KSI_DASHBOARD_OIDC_CLIENT_ID: "ksi-operations-console",
        KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE: clientSecretFile,
        KSI_DASHBOARD_SESSION_SECRET_FILE: sessionSecretFile,
        KSI_DASHBOARD_DIST_DIR: dashboardDistDirectory,
        KSI_DASHBOARD_TSCONFIG_PATH: dashboardTsconfig,
        KSI_DASHBOARD_PUBLIC_APP_ORIGIN: dashboardOrigin,
        KSI_DASHBOARD_ALLOWED_DEV_ORIGINS: "127.0.0.1",
        AUTH_URL: dashboardOrigin,
        AUTH_TRUST_HOST: "true",
      },
    },
  ],
});
