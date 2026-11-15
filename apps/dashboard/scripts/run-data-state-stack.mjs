#!/usr/bin/env node
/**
 * 자료가 들어 있는 화면(관측 목록·분석 결과)을 브라우저로 검토하는 전용 스택.
 *
 * 계약 테스트의 Analysis 픽스처로 합성 DSM 두 시점과 완료된 분석 한 건을 가진 Core를
 * 띄우고, Dashboard를 OPAQUE 모드(수동 Bearer 로그인)로 그 Core에 붙인다. 합성 자료이며
 * 현장·정확도·고객 수락 증거가 아니다. 기본 개발 스택(`npm run dev`)과 포트·distDir가
 * 달라 함께 띄울 수 있다. 접속 정보(Core 주소·토큰)는 --info-file(0600)에만 남는다.
 */

import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const appDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(appDirectory, "..", "..");
const bindHost = "127.0.0.1";

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  const value = process.argv[index + 1];
  if (!value || value.startsWith("--")) throw new Error(`${name} requires a value.`);
  return value;
}

const dashboardPort = Number(option("--dashboard-port", "3231"));
const infoFile = resolve(repositoryRoot, option("--info-file", ".dev-data/data-states/info.json"));
const distDir = option("--dashboard-dist-dir", ".next-data-states");
const extraOrigins = option("--allowed-dev-origins", "");
// 분석 워커는 /proc/self/fd, 검사 레인은 SO_PEERCRED를 쓰는 Linux 전용이다. macOS에서는
// Core를 Linux 컨테이너로 돌리고 Core 포트만 loopback으로 연다. 이미지에는 Python 의존성이
// 있는 /app/.venv가 있어야 하며, 저장소 소스는 읽기 전용으로 마운트한다.
const coreRuntime = option("--core-runtime", process.platform === "linux" ? "local" : "docker");
const coreImage = option("--core-image", process.env.KSI_DATA_STATE_CORE_IMAGE ?? "");
const corePort = Number(option("--core-port", "18033"));

mkdirSync(dirname(infoFile), { recursive: true });
rmSync(infoFile, { force: true });

const children = [];
let shuttingDown = false;
function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children.reverse()) if (!child.killed) child.kill("SIGTERM");
  setTimeout(() => process.exit(code), 500).unref();
}
process.on("SIGINT", () => shutdown());
process.on("SIGTERM", () => shutdown());

function start(commandName, args, cwd, env, label) {
  const child = spawn(commandName, args, { cwd, env, stdio: "inherit" });
  if (!child.pid) throw new Error(`${label} could not start.`);
  children.push(child);
  child.once("exit", (code) => {
    if (!shuttingDown) {
      console.error(`${label} stopped unexpectedly (${code ?? "signal"}).`);
      shutdown(1);
    }
  });
  return child;
}

if (coreRuntime === "docker") {
  if (!coreImage) {
    throw new Error("--core-image 또는 KSI_DATA_STATE_CORE_IMAGE가 필요합니다(Python 의존성이 든 Linux 이미지).");
  }
  const sourcePaths = ["packages", "services"]
    .flatMap((group) =>
      readdirSync(resolve(repositoryRoot, group), { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && existsSync(resolve(repositoryRoot, group, entry.name, "src")))
        .map((entry) => `/work/${group}/${entry.name}/src`),
    )
    .concat(["/work/tests/contract", "/work/tests"])
    .join(":");
  const containerName = `ksi-data-states-${process.pid}`;
  start(
    "docker",
    [
      "run", "--rm", "--name", containerName,
      "-v", `${repositoryRoot}:/work:ro`,
      "-v", `${dirname(infoFile)}:/out`,
      "-p", `127.0.0.1:${corePort}:${corePort}`,
      "-w", "/work",
      "-e", `PYTHONPATH=${sourcePaths}`,
      "--entrypoint", "/app/.venv/bin/python",
      coreImage,
      "apps/dashboard/e2e/fixtures/serve_data_states.py",
      "--info-file", `/out/${basename(infoFile)}`,
      "--publish-port", String(corePort),
      "--public-origin", `http://127.0.0.1:${corePort}`,
    ],
    repositoryRoot,
    process.env,
    "data-state Core (docker)",
  );
} else {
  start(
    "uv",
    ["run", "python", "apps/dashboard/e2e/fixtures/serve_data_states.py", "--info-file", infoFile],
    repositoryRoot,
    process.env,
    "data-state Core",
  );
}

const deadline = Date.now() + 120000;
while (!existsSync(infoFile)) {
  if (Date.now() > deadline) {
    console.error("data-state Core did not publish its info file in time.");
    shutdown(1);
    break;
  }
  await new Promise((r) => setTimeout(r, 500));
}
if (shuttingDown) await new Promise(() => {});
const info = JSON.parse(readFileSync(infoFile, "utf8"));

start(
  process.execPath,
  [resolve(appDirectory, "node_modules/next/dist/bin/next"), "dev", "--hostname", bindHost, "--port", String(dashboardPort)],
  appDirectory,
  {
    ...process.env,
    CORE_API_BASE_URL: info.coreOrigin,
    KSI_DASHBOARD_DEPLOYMENT_PROFILE: "LOCAL",
    KSI_DASHBOARD_HUMAN_AUTH_MODE: "OPAQUE",
    KSI_DASHBOARD_LEGACY_OPAQUE_LOGIN_ENABLED: "1",
    KSI_DASHBOARD_DIST_DIR: distDir,
    ...(extraOrigins ? { KSI_DASHBOARD_ALLOWED_DEV_ORIGINS: extraOrigins } : {}),
  },
  "KSI Operations Console (data states)",
);

console.log(`\n데이터 상태 검토 스택: http://${bindHost}:${dashboardPort}/login`);
console.log(`로그인 토큰·현장 ID는 ${infoFile} 에 있습니다(합성 픽스처, 0600).`);
