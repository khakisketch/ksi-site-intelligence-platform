// @vitest-environment node
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { dashboardBuildRoot } from "../scripts/dashboard-build-root.mjs";
import { packageStandalone } from "../scripts/package-standalone.mjs";

const temporary: string[] = [];
function scratch() {
  const root = mkdtempSync(join(tmpdir(), "ksi-standalone-test-"));
  temporary.push(root);
  return root;
}
function put(filename: string, content = "fixture") {
  mkdirSync(dirname(filename), { recursive: true });
  writeFileSync(filename, content);
}
function fixture(nested = false) {
  const root = scratch();
  const appRelative = nested ? ".worktrees/candidate/apps/dashboard" : "";
  const app = join(root, "source", appRelative);
  const dist = join(app, ".next");
  const standalone = join(dist, "standalone");
  const traceRoot = join(root, "source");
  const appOutput = join(standalone, appRelative);
  put(join(dist, "required-server-files.json"), JSON.stringify({ appDir: app, relativeAppDir: appRelative, config: { distDir: ".next", outputFileTracingRoot: traceRoot, output: "standalone" } }));
  put(join(appOutput, "server.js"), "// generated server");
  put(join(appOutput, ".next/server/page.js"));
  put(join(dist, "server/page.js"));
  put(join(dist, "server/page.js.nft.json"), JSON.stringify({ files: ["page.js"] }));
  put(join(dist, "static/chunk.js"), "client chunk");
  put(join(app, "public/marker.txt"), "public asset");
  put(join(app, "scripts/start-production.mjs"), "// production guard");
  return { root, app, dist, standalone, appOutput, destination: join(root, "package") };
}
afterEach(() => temporary.splice(0).forEach((root) => rmSync(root, { recursive: true, force: true })));

describe("Dashboard standalone packaging", () => {
  it("keeps ordinary installs rooted at the app", () => {
    const root = scratch();
    mkdirSync(join(root, "node_modules"));
    expect(dashboardBuildRoot(root)).toBe(root);
  });

  it("includes linked worktree dependencies without changing their link", () => {
    const root = scratch();
    const app = join(root, ".worktrees/candidate/apps/dashboard");
    const modules = join(root, "apps/dashboard/node_modules");
    mkdirSync(app, { recursive: true });
    mkdirSync(modules, { recursive: true });
    symlinkSync(modules, join(app, "node_modules"));
    expect(dashboardBuildRoot(app)).toBe(root);
  });

  it.each([false, true])("copies assets and the guarded launcher with nested=%s", (nested) => {
    const f = fixture(nested);
    const manifest = packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination });
    const runtime = join(f.destination, manifest.appRelative);
    expect(readFileSync(join(runtime, ".next/static/chunk.js"), "utf8")).toBe("client chunk");
    expect(readFileSync(join(runtime, "public/marker.txt"), "utf8")).toBe("public asset");
    expect(readFileSync(join(runtime, "scripts/start-production.mjs"), "utf8")).toBe("// production guard");
    expect(readFileSync(join(f.destination, "start.mjs"), "utf8")).toContain("start-production.mjs");
    expect(manifest.tracedFiles).toBe(1);
  });

  it("rejects the real missing-outside-root trace pattern before publishing a package", () => {
    const f = fixture();
    put(join(f.root, "dependency.js"));
    put(join(f.dist, "next-server.js.nft.json"), JSON.stringify({ files: ["../../dependency.js"] }));
    expect(() => packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination })).toThrow(/traced file/i);
    expect(existsSync(f.destination)).toBe(false);
  });

  it("rejects a missing in-root dependency", () => {
    const f = fixture();
    put(join(f.dist, "next-server.js.nft.json"), JSON.stringify({ files: ["../node_modules/missing.js"] }));
    expect(() => packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination })).toThrow(/traced file/i);
  });

  it("rejects escaping or broken runtime links but keeps relocatable internal links", () => {
    const f = fixture();
    symlinkSync(f.app, join(f.standalone, "escape"));
    expect(() => packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination })).toThrow(/symlink/i);
    rmSync(join(f.standalone, "escape"));
    symlinkSync("absent", join(f.standalone, "broken"));
    expect(() => packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination })).toThrow(/symlink/i);
    rmSync(join(f.standalone, "broken"));
    symlinkSync("server.js", join(f.standalone, "internal"));
    packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination });
    expect(readFileSync(join(f.destination, "internal"), "utf8")).toBe("// generated server");
  });

  it("does not overwrite existing output or permit recursive output inside the build", () => {
    const f = fixture();
    mkdirSync(f.destination);
    put(join(f.destination, "keep"), "original");
    expect(() => packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination })).toThrow(/exist/i);
    expect(readFileSync(join(f.destination, "keep"), "utf8")).toBe("original");
    expect(() => packageStandalone({ projectRoot: f.app, distDir: ".next", destination: join(f.standalone, "recursive") })).toThrow(/overlap/i);
  });

  it("rejects changed traced bytes, not only absent filenames", () => {
    const f = fixture();
    cpSync(join(f.appOutput, ".next/server/page.js"), join(f.dist, "server/page.js"));
    put(join(f.appOutput, ".next/server/page.js"), "stale output");
    expect(() => packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination })).toThrow(/traced file/i);
  });

  it("checks NFT directory entries without treating them as file bytes", () => {
    const f = fixture();
    mkdirSync(join(f.app, "node_modules"));
    mkdirSync(join(f.standalone, "node_modules"));
    put(join(f.dist, "next-server.js.nft.json"), JSON.stringify({ files: ["../node_modules"] }));
    expect(packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination }).tracedFiles).toBe(2);
  });

  it("does not ship build-time environment files", () => {
    const f = fixture();
    put(join(f.standalone, ".env.production"), "NOT_A_REAL_SECRET=fixture");
    expect(() => packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination })).toThrow(/\.env/);
    expect(existsSync(f.destination)).toBe(false);
  });

  it("restores omitted pnpm resolver aliases only to already traced package targets", () => {
    const f = fixture();
    for (const name of ["runtime", "dev-only"]) {
      put(join(f.app, `node_modules/.pnpm/${name}/node_modules/${name}/package.json`), "{}");
      symlinkSync(`.pnpm/${name}/node_modules/${name}`, join(f.app, `node_modules/${name}`));
    }
    cpSync(join(f.app, "node_modules/.pnpm/runtime"), join(f.standalone, "node_modules/.pnpm/runtime"), { recursive: true });
    const manifest = packageStandalone({ projectRoot: f.app, distDir: ".next", destination: f.destination });
    expect(manifest.restoredAliases).toBe(1);
    expect(readFileSync(join(f.destination, "node_modules/runtime/package.json"), "utf8")).toBe("{}");
    expect(existsSync(join(f.destination, "node_modules/dev-only"))).toBe(false);
  });
});
