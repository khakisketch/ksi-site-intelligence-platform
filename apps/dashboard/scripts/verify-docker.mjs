import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Local target-image smoke proof, NOT production/signing/customer acceptance.
// Runs the already built image with loopback-only port mapping, stripped env,
// unreachable Core and no secret files. Never pushes, never touches live Core.
export async function verifyDockerImage(image) {
  const name = `ksi-docker-verify-${process.pid}`;
  const sharedEnv = [
    "-e", "NODE_ENV=production",
    "-e", "NEXT_TELEMETRY_DISABLED=1",
    "-e", "HOSTNAME=0.0.0.0",
    "-e", "PORT=3000",
    "-e", "CORE_API_BASE_URL=http://127.0.0.1:9",
  ];
  const baseEnv = [...sharedEnv, "-e", "KSI_DASHBOARD_DEPLOYMENT_PROFILE=LOCAL"];
  const stop = () => {
    spawnSync("docker", ["rm", "-f", name], { encoding: "utf8", timeout: 15000 });
  };
  try {
    const exterior = spawnSync("docker", ["run", "--rm", `--name=${name}-exterior`, ...sharedEnv,
      "-e", "KSI_DASHBOARD_DEPLOYMENT_PROFILE=EXTERNAL_VM", image],
      { encoding: "utf8", timeout: 30000 });
    assert.notEqual(exterior.status, 0, "EXTERNAL_VM must reject incomplete auth before listening");
    assert.match(`${exterior.stdout}${exterior.stderr}`, /OIDC/);

    const child = spawn("docker", ["run", "--rm", "--name", name, "-p", `127.0.0.1::3000`, ...baseEnv, image],
      { stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    child.stdout.on("data", (bytes) => { output = (output + bytes).slice(-32768); });
    child.stderr.on("data", (bytes) => { output = (output + bytes).slice(-32768); });
    let spawnError;
    child.on("error", (error) => { spawnError = error; });
    // Resolve the host-mapped port from docker port output.
    let origin;
    for (let attempt = 0; attempt < 100; attempt++) {
      if (spawnError) throw spawnError;
      assert.equal(child.exitCode, null, `Container exited: ${output}`);
      const mapping = spawnSync("docker", ["port", name, "3000/tcp"], { encoding: "utf8", timeout: 5000 });
      const match = /127\.0\.0\.1:(\d+)/.exec(mapping.stdout || "");
      if (match) {
        origin = `http://127.0.0.1:${match[1]}`;
        try {
          const probe = await fetch(`${origin}/login`, { signal: AbortSignal.timeout(1000) });
          if (probe.status === 200) break;
        } catch { /* not ready yet */ }
      }
      await delay(300);
    }
    assert.ok(origin, `Container port was never mapped: ${output}`);
    let login;
    for (let attempt = 0; attempt < 100; attempt++) {
      try {
        login = await fetch(`${origin}/login`, { signal: AbortSignal.timeout(2000) });
        if (login.status === 200) break;
      } catch { await delay(300); }
    }
    assert.ok(login, `Container server did not become ready: ${output}`);
    assert.equal(login.status, 200);
    const html = await login.text();
    assert.match(html, /KSI Site Intelligence/);
    const assets = [...new Set([...html.matchAll(/(?:src|href)="([^"?#]*\/_next\/static\/[^"?#]+)(?:\?[^"#]*)?"/g)].map((m) => m[1]))];
    assert.ok(assets.some((n) => n.endsWith(".js")), "Login must reference its JS chunks");
    assert.ok(assets.some((n) => n.endsWith(".css")), "Login must reference its CSS");
    for (const asset of assets) {
      const response = await fetch(new URL(asset, origin), { signal: AbortSignal.timeout(5000) });
      assert.equal(response.status, 200, asset);
      assert.ok((await response.arrayBuffer()).byteLength > 0, asset);
    }
    const sites = await fetch(`${origin}/sites`, { redirect: "manual", signal: AbortSignal.timeout(5000) });
    assert.ok([303, 307, 308].includes(sites.status), "Protected pages must redirect without a session");
    assert.match(sites.headers.get("location") || "", /\/login\?/);
    const api = await fetch(`${origin}/api/sites`, {
      method: "POST", headers: { origin, "content-type": "application/json" }, body: "{",
      redirect: "manual", signal: AbortSignal.timeout(5000),
    });
    assert.equal(api.status, 401, "BFF must not use the unreachable Core without a session");
    assert.doesNotMatch(output, /MODULE_NOT_FOUND|PACKAGE_MODULE_ESCAPE/);

    const user = spawnSync("docker", ["exec", name, "whoami"], { encoding: "utf8", timeout: 10000 });
    assert.equal((user.stdout || "").trim(), "ksi-dashboard");
    const node = spawnSync("docker", ["exec", name, "node", "--version"], { encoding: "utf8", timeout: 10000 });
    assert.match(node.stdout || "", /^v22\.18\.\d+/);
    const layout = spawnSync("docker", ["exec", name, "node", "-e",
      "const fs=require('fs');console.log(JSON.stringify({server:fs.existsSync('server.js'),static:fs.existsSync('.next/static'),public:fs.existsSync('public/globe.svg'),guard:fs.existsSync('scripts/start-production.mjs')}))"],
      { encoding: "utf8", timeout: 10000 });
    assert.deepEqual(JSON.parse(layout.stdout), { server: true, static: true, public: true, guard: true });
    return { login: login.status, staticAssets: assets.length, protectedPage: sites.status, unauthenticatedApi: api.status, user: "ksi-dashboard", node: (node.stdout || "").trim(), exteriorRejected: true };
  } finally {
    stop();
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [image, ...extra] = process.argv.slice(2);
  if (!image || extra.length) throw new Error("Usage: npm run verify:docker -- <image-tag>");
  console.log(JSON.stringify(await verifyDockerImage(image), null, 2));
}
