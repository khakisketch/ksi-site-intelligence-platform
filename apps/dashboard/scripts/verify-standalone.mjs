import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

// Local same-platform smoke proof, NOT an OS sandbox or production acceptance.
// Only run trusted build output. No inherited credentials, live Core or issuer.
export async function verifyStandalone(packageDirectory) {
  const temporary = mkdtempSync(path.join(tmpdir(), "ksi-package-verify-"));
  const relocated = path.join(temporary, "relocated");
  let child;
  let output = "";
  try {
    cpSync(packageDirectory, relocated, { recursive: true, verbatimSymlinks: true });
    const guard = path.join(temporary, "resolution-guard.cjs");
    writeFileSync(guard, `
const Module = require('node:module');
const fs = require('node:fs');
const path = require('node:path');
const root = fs.realpathSync(process.env.KSI_PACKAGE_VERIFY_ROOT);
const original = Module._resolveFilename;
Module._resolveFilename = function(...args) {
  const result = original.apply(this, args);
  if (path.isAbsolute(result)) {
    const relative = path.relative(root, fs.realpathSync(result));
    if (path.isAbsolute(relative) || relative === '..' || relative.startsWith('..' + path.sep)) {
      throw new Error('PACKAGE_MODULE_ESCAPE: ' + result);
    }
  }
  return result;
};
`);
    const reservation = createServer();
    reservation.listen(0, "127.0.0.1");
    await once(reservation, "listening");
    const port = reservation.address().port;
    await new Promise((resolve, reject) => reservation.close((error) => error ? reject(error) : resolve()));
    const env = {
      PATH: path.dirname(process.execPath), HOME: temporary, TMPDIR: temporary,
      NODE_ENV: "production", NEXT_TELEMETRY_DISABLED: "1", HOSTNAME: "127.0.0.1", PORT: String(port),
      KSI_DASHBOARD_DEPLOYMENT_PROFILE: "LOCAL", CORE_API_BASE_URL: "http://127.0.0.1:9",
      KSI_PACKAGE_VERIFY_ROOT: relocated,
    };
    const blocked = spawnSync(process.execPath, ["start.mjs"], {
      cwd: relocated, env: { ...env, KSI_DASHBOARD_DEPLOYMENT_PROFILE: "EXTERNAL_VM" }, encoding: "utf8", timeout: 10000,
    });
    assert.equal(blocked.status, 1, "EXTERNAL_VM must reject incomplete auth before listening");
    assert.match(blocked.stderr, /OIDC/);
    child = spawn(process.execPath, ["--require", guard, "start.mjs"], { cwd: relocated, env, stdio: ["ignore", "pipe", "pipe"] });
    child.stdout.on("data", (bytes) => { output = (output + bytes).slice(-32768); });
    child.stderr.on("data", (bytes) => { output = (output + bytes).slice(-32768); });
    let spawnError;
    child.on("error", (error) => { spawnError = error; });
    const origin = `http://127.0.0.1:${port}`;
    let login;
    for (let attempt = 0; attempt < 100; attempt++) {
      if (spawnError) throw spawnError;
      assert.equal(child.exitCode, null, `Relocated server exited: ${output}`);
      try {
        login = await fetch(`${origin}/login`, { signal: AbortSignal.timeout(1000) });
        break;
      } catch { await delay(100); }
    }
    assert.ok(login, `Relocated server did not become ready: ${output}`);
    assert.equal(login.status, 200);
    const html = await login.text();
    assert.match(html, /KSI Site Intelligence/);
    const assets = [...new Set([...html.matchAll(/(?:src|href)="([^"?#]*\/_next\/static\/[^"?#]+)(?:\?[^"#]*)?"/g)].map((match) => match[1]))];
    assert.ok(assets.some((name) => name.endsWith(".js")), "Login must reference its JS chunks");
    assert.ok(assets.some((name) => name.endsWith(".css")), "Login must reference its CSS");
    for (const asset of assets) {
      const response = await fetch(new URL(asset, origin), { signal: AbortSignal.timeout(5000) });
      assert.equal(response.status, 200, asset);
      assert.ok((await response.arrayBuffer()).byteLength > 0, asset);
    }
    const sites = await fetch(`${origin}/sites`, { redirect: "manual", signal: AbortSignal.timeout(5000) });
    assert.ok([303, 307, 308].includes(sites.status), "Protected pages must redirect without a session");
    assert.match(sites.headers.get("location") || "", /\/login\?/);
    // Existing proxy deliberately gates public/ too; do not weaken it just for
    // the smoke test. Check copied bytes and preserve the anonymous redirect.
    const manifest = JSON.parse(readFileSync(path.join(relocated, "ksi-package.json"), "utf8"));
    assert.match(readFileSync(path.join(relocated, manifest.appRelative, "public/globe.svg"), "utf8"), /<svg/);
    const publicAsset = await fetch(`${origin}/globe.svg`, { redirect: "manual", signal: AbortSignal.timeout(5000) });
    assert.equal(publicAsset.status, 307);
    const api = await fetch(`${origin}/api/sites`, { method: "POST", headers: { origin, "content-type": "application/json" }, body: "{", redirect: "manual", signal: AbortSignal.timeout(5000) });
    assert.equal(api.status, 401, "BFF must not use the unreachable Core without a session");
    assert.doesNotMatch(output, /PACKAGE_MODULE_ESCAPE|MODULE_NOT_FOUND/);
    return { node: process.version, platform: process.platform, arch: process.arch, tracedFiles: manifest.tracedFiles, login: login.status, staticAssets: assets.length, publicAssetRedirect: publicAsset.status, protectedPage: sites.status, unauthenticatedApi: api.status, externalProfileRejected: true, moduleResolutionGuard: "CommonJS paths confined to relocated package; not OS containment" };
  } finally {
    if (child && child.exitCode === null && child.pid) {
      const exited = once(child, "exit");
      child.kill("SIGTERM");
      const force = setTimeout(() => child.kill("SIGKILL"), 5000);
      try { await exited; } finally { clearTimeout(force); }
    }
    rmSync(temporary, { recursive: true, force: true });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [directory, ...extra] = process.argv.slice(2);
  if (!directory || extra.length) throw new Error("Usage: npm run verify:standalone -- /path/to/trusted-package");
  console.log(JSON.stringify(await verifyStandalone(path.resolve(directory)), null, 2));
}
