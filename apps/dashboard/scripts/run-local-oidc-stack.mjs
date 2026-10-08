#!/usr/bin/env node
/**
 * KSI Operations Console의 표준 로컬 개발 진입점.
 *
 * 상용과 같은 사람 인증 경로(OIDC Authorization Code + PKCE)를 Dashboard, Core,
 * local-only issuer에 함께 배선한다. 이 스크립트는 loopback에만 bind하며, issuer와
 * secret은 .dev-data 아래에만 남는다. production compose/image는 이 코드를 호출하거나
 * 포함하지 않는다.
 */

import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, openSync, closeSync, writeFileSync, chmodSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";

const appDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(appDirectory, "..", "..");
const bindHost = "127.0.0.1";
// Auth.js session cookies and browser navigation use one canonical public
// loopback host. `localhost` avoids the in-app browser's 127.0.0.1 alias
// normalization from splitting an otherwise valid OIDC session.
const publicHost = "localhost";

function choiceArgument(name, fallback, choices) {
  const value = stringArgument(name, fallback);
  if (!choices.includes(value)) {
    throw new Error(`${name} must be one of: ${choices.join(", ")}.`);
  }
  return value;
}

function numberArgument(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  const value = Number(process.argv[index + 1]);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`${name} must be a TCP port between 1 and 65535.`);
  }
  return value;
}

function stringArgument(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  const value = process.argv[index + 1];
  if (!value || value.startsWith("--")) throw new Error(`${name} requires a value.`);
  return value;
}

function protectedConfigPathArgument(name) {
  const value = stringArgument(name, undefined);
  if (value !== undefined && !isAbsolute(value)) {
    throw new Error(`${name} must be an absolute operator-provisioned path.`);
  }
  return value;
}

const dashboardPort = numberArgument("--dashboard-port", 3210);
const corePort = numberArgument("--core-port", 8012);
const issuerPort = numberArgument("--issuer-port", 9010);
const tailscaleMode = choiceArgument("--tailscale", "auto", ["required", "auto", "disabled"]);
const coreDataDirectory = resolve(
  repositoryRoot,
  stringArgument("--core-data-dir", ".dev-data/local-oidc-core"),
);
const identityStateDirectory = resolve(
  repositoryRoot,
  stringArgument("--identity-state-dir", ".dev-data/local-identity"),
);
const dashboardDistDirectory = stringArgument(
  "--dashboard-dist-dir",
  ".next-local-oidc",
);
const localAnalysisS3Endpoint = stringArgument("--s3-endpoint", undefined);
const localAnalysisS3Bucket = stringArgument("--s3-bucket", undefined);
const localAnalysisConfig = protectedConfigPathArgument("--local-analysis-config");
const externalResultWorkflowConfig = protectedConfigPathArgument(
  "--external-result-workflow-config",
);
const externalAuthorityProviderConfig = protectedConfigPathArgument(
  "--external-authority-provider-config",
);
const localAnalysisOptInValues = [
  localAnalysisS3Endpoint,
  localAnalysisS3Bucket,
  localAnalysisConfig,
  externalResultWorkflowConfig,
  externalAuthorityProviderConfig,
];
if (localAnalysisOptInValues.some((value) => value !== undefined)
  && !localAnalysisOptInValues.every((value) => value !== undefined)) {
  throw new Error(
    "local Analysis requires S3 endpoint/bucket and three protected config paths.",
  );
}
const seedOperationsConsoleE2e = process.argv.includes("--seed-operations-console-e2e");
const secretsDirectory = resolve(identityStateDirectory, "secrets");
const sessionSecretFile = resolve(secretsDirectory, "dashboard-session.secret");
const clientSecretFile = resolve(secretsDirectory, "dashboard-oidc-client.secret");
const localIssuerOrigin = `http://${publicHost}:${issuerPort}`;
const localDashboardOrigin = `http://${publicHost}:${dashboardPort}`;

function detectTailscale() {
  if (tailscaleMode === "disabled") return null;
  const status = spawnSync("tailscale", ["status", "--json"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  });
  if (status.status !== 0) {
    if (tailscaleMode === "required") {
      throw new Error(`Tailscale status를 읽을 수 없습니다: ${status.stderr.trim() || "tailscale unavailable"}`);
    }
    return null;
  }

  let payload;
  try {
    payload = JSON.parse(status.stdout);
  } catch {
    throw new Error("Tailscale status JSON을 해석할 수 없습니다.");
  }
  const dnsName = typeof payload?.Self?.DNSName === "string"
    ? payload.Self.DNSName.replace(/\.$/, "").toLowerCase()
    : "";
  const ipv4 = Array.isArray(payload?.TailscaleIPs)
    ? payload.TailscaleIPs.find((value) => typeof value === "string" && /^100\./.test(value))
    : undefined;
  if (payload?.BackendState !== "Running" || !payload?.Self?.Online || !dnsName.endsWith(".ts.net")) {
    if (tailscaleMode === "required") {
      throw new Error("Tailscale이 Running/Online 상태이고 MagicDNS 이름을 가져야 합니다.");
    }
    return null;
  }
  return { dnsName, ipv4 };
}

function configureTailscaleHttp(port, target, label) {
  const configured = spawnSync(
    "tailscale",
    ["serve", `--http=${port}`, "--bg", "--yes", target],
    { cwd: repositoryRoot, encoding: "utf8" },
  );
  if (configured.status !== 0) {
    throw new Error(`${label} Tailscale Serve 설정 실패: ${configured.stderr.trim() || configured.stdout.trim()}`);
  }
}

const tailscale = detectTailscale();
const issuerOrigin = tailscale
  ? `http://${tailscale.dnsName}:${issuerPort}`
  : localIssuerOrigin;
const dashboardOrigin = tailscale
  ? `http://${tailscale.dnsName}:${dashboardPort}`
  : localDashboardOrigin;

function ensureSecret(path) {
  if (existsSync(path)) return;
  mkdirSync(dirname(path), { recursive: true });
  const descriptor = openSync(path, "wx", 0o600);
  try {
    writeFileSync(descriptor, randomBytes(48).toString("base64url"), "utf8");
  } finally {
    closeSync(descriptor);
  }
  chmodSync(path, 0o600);
}

async function waitFor(url, label, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1500) });
      if (response.ok) return;
      lastError = new Error(`${response.status} ${response.statusText}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
  }
  throw new Error(`${label} did not become ready: ${lastError instanceof Error ? lastError.message : String(lastError)}`);
}

function command(commandName, args, options) {
  const child = spawn(commandName, args, {
    cwd: options.cwd,
    env: options.env,
    stdio: "inherit",
  });
  if (!child.pid) throw new Error(`${options.label} could not start.`);
  return child;
}

function stop(child) {
  if (child && !child.killed) child.kill("SIGTERM");
}

ensureSecret(sessionSecretFile);
ensureSecret(clientSecretFile);
mkdirSync(coreDataDirectory, { recursive: true });

if (seedOperationsConsoleE2e) {
  const seed = spawnSync(
    "uv",
    [
      "run",
      "python",
      "apps/dashboard/e2e/fixtures/seed_operations_console.py",
      "--data-dir",
      coreDataDirectory,
    ],
    { cwd: repositoryRoot, env: process.env, encoding: "utf8" },
  );
  if (seed.status !== 0) {
    throw new Error(
      `Operations Console E2E fixture seeding failed: ${seed.stderr.trim() || seed.stdout.trim()}`,
    );
  }
}

const commonEnvironment = { ...process.env };
const children = [];
let shuttingDown = false;

function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children.reverse()) stop(child);
  setTimeout(() => process.exit(exitCode), 500).unref();
}

process.on("SIGINT", () => shutdown());
process.on("SIGTERM", () => shutdown());

try {
  const issuer = command(
    "uv",
    [
      "run",
      "python",
      "tools/run_local_oidc_issuer.py",
      "--host",
      bindHost,
      "--port",
      String(issuerPort),
      "--issuer-origin",
      issuerOrigin,
      "--dashboard-origin",
      dashboardOrigin,
      "--client-id",
      "ksi-operations-console",
      "--client-secret-file",
      clientSecretFile,
      "--state-dir",
      identityStateDirectory,
      "--core-audience",
      "ksi-core",
      ...(tailscale ? ["--allow-tailnet-origin"] : []),
    ],
    { cwd: repositoryRoot, env: commonEnvironment, label: "KSI Local Identity" },
  );
  children.push(issuer);
  issuer.once("exit", (code) => {
    if (!shuttingDown) {
      console.error(`KSI Local Identity stopped unexpectedly (${code ?? "signal"}).`);
      shutdown(1);
    }
  });
  await waitFor(`http://${bindHost}:${issuerPort}/healthz`, "KSI Local Identity");
  if (tailscale) {
    configureTailscaleHttp(
      issuerPort,
      `http://${bindHost}:${issuerPort}`,
      "KSI Local Identity",
    );
    await waitFor(`${issuerOrigin}/healthz`, "Tailnet KSI Local Identity");
  }

  const core = command(
    "uv",
    [
      "run",
      "python",
      "scripts/run_core_dev.py",
      "--host",
      bindHost,
      "--port",
      String(corePort),
      "--data-dir",
      coreDataDirectory,
      "--human-auth-mode",
      "OIDC",
      "--oidc-issuer",
      issuerOrigin,
      "--oidc-audience",
      "ksi-core",
      "--oidc-jwks-url",
      `http://${bindHost}:${issuerPort}/jwks.json`,
      ...(seedOperationsConsoleE2e ? ["--oidc-operations-console-e2e"] : []),
      ...(localAnalysisConfig ? [
        "--s3-endpoint",
        localAnalysisS3Endpoint,
        "--s3-bucket",
        localAnalysisS3Bucket,
        "--local-analysis-config",
        localAnalysisConfig,
        "--external-result-workflow-config",
        externalResultWorkflowConfig,
        "--external-authority-provider-config",
        externalAuthorityProviderConfig,
      ] : []),
    ],
    { cwd: repositoryRoot, env: commonEnvironment, label: "KSI Core" },
  );
  children.push(core);
  core.once("exit", (code) => {
    if (!shuttingDown) {
      console.error(`KSI Core stopped unexpectedly (${code ?? "signal"}).`);
      shutdown(1);
    }
  });
  await waitFor(`http://${bindHost}:${corePort}/ready`, "KSI Core");

  const dashboard = command(
    process.execPath,
    [resolve(appDirectory, "node_modules/next/dist/bin/next"), "dev", "--hostname", bindHost, "--port", String(dashboardPort)],
    {
      cwd: appDirectory,
      env: {
        ...commonEnvironment,
        CORE_API_BASE_URL: `http://${bindHost}:${corePort}`,
        KSI_DASHBOARD_DEPLOYMENT_PROFILE: "LOCAL",
        KSI_DASHBOARD_HUMAN_AUTH_MODE: "OIDC",
        KSI_DASHBOARD_LOCAL_IDENTITY_ENABLED: "1",
        KSI_DASHBOARD_OIDC_ISSUER: issuerOrigin,
        KSI_DASHBOARD_OIDC_CLIENT_ID: "ksi-operations-console",
        KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE: clientSecretFile,
        KSI_DASHBOARD_SESSION_SECRET_FILE: sessionSecretFile,
        KSI_DASHBOARD_DIST_DIR: dashboardDistDirectory,
        KSI_DASHBOARD_PUBLIC_APP_ORIGIN: dashboardOrigin,
        KSI_DASHBOARD_ALLOWED_DEV_ORIGINS: [
          process.env.KSI_DASHBOARD_ALLOWED_DEV_ORIGINS,
          tailscale?.dnsName,
          tailscale?.ipv4,
        ].filter(Boolean).join(","),
        // Auth.js가 authorization과 token 교환에서 같은 loopback callback origin을
        // 쓰도록 고정한다. 브라우저의 localhost alias가 섞이면 PKCE 코드는 맞아도
        // 등록 redirect URI 대조가 실패한다.
        AUTH_URL: dashboardOrigin,
        AUTH_TRUST_HOST: "true",
      },
      label: "KSI Operations Console",
    },
  );
  children.push(dashboard);
  dashboard.once("exit", (code) => {
    if (!shuttingDown) {
      console.error(`KSI Operations Console stopped unexpectedly (${code ?? "signal"}).`);
      shutdown(1);
    }
  });
  await waitFor(`http://${bindHost}:${dashboardPort}/login`, "KSI Operations Console", 60000);
  if (tailscale) {
    configureTailscaleHttp(
      dashboardPort,
      `http://${bindHost}:${dashboardPort}`,
      "KSI Operations Console",
    );
    await waitFor(`${dashboardOrigin}/login`, "Tailnet KSI Operations Console", 60000);
  }

  console.log("\nKSI local OIDC stack is ready.");
  console.log(`Operations Console: ${dashboardOrigin}/login`);
  if (tailscale) {
    console.log(`Tailnet Identity: ${issuerOrigin}`);
    console.log("Tailscale Serve는 background 설정으로 유지되며 서비스 자체는 loopback에만 bind됩니다.");
  }
  console.log("Login flow: KSI Identity redirect → default development operator → Console.");
  console.log(`Core durable data: ${coreDataDirectory}`);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  shutdown(1);
}
