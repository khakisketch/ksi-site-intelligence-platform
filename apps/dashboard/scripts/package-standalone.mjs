import { createHash } from "node:crypto";
import { cpSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, readlinkSync, realpathSync, renameSync, rmSync, statSync, symlinkSync, writeFileSync, mkdtempSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

function inside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`));
}

function digest(filename) {
  return createHash("sha256").update(readFileSync(filename)).digest("hex");
}

function files(root) {
  // Never descend into symlinked directories: a runtime link that escapes the
  // root (or loops back into it) must be reported by checkRuntimeTree as a
  // non-relocatable symlink, not followed into synthetic deep paths that
  // surface as ELOOP/ENAMETOOLONG or exhaust memory on large trees.
  // Dirent.isDirectory() is lstat-based, so symlinks to directories are
  // listed (and still rejected) but never traversed.
  const result = [];
  const stack = [root];
  while (stack.length > 0) {
    const dir = stack.pop();
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const filename = path.join(dir, entry.name);
      result.push(filename);
      if (entry.isDirectory()) stack.push(filename);
    }
  }
  return result;
}

function checkRuntimeTree(root) {
  for (const filename of files(root)) {
    const stat = lstatSync(filename);
    if (/^\.env(?:\.|$)/.test(path.basename(filename))) {
      throw new Error("Runtime package must not contain build-time .env files; provide secrets at runtime.");
    }
    if (!stat.isSymbolicLink()) continue;
    const link = readlinkSync(filename);
    if (path.isAbsolute(link) || !existsSync(filename) || !inside(root, realpathSync(filename))) {
      throw new Error(`Non-relocatable runtime symlink: ${path.relative(root, filename)}`);
    }
  }
}

function restoreTracedPackageAliases(traceRoot, staging) {
  let restored = 0;
  // Webpack NFT may trace real pnpm package files but omit their resolver aliases.
  // Restore only aliases whose target package was ALREADY copied by Next. Never
  // copy untraced dependencies, glob the repository, or hard-code package names.
  for (const output of files(staging).filter((name) => path.basename(name) === "node_modules" && lstatSync(name).isDirectory())) {
    const source = path.join(traceRoot, path.relative(staging, output));
    const entries = readdirSync(source, { withFileTypes: true });
    const aliases = entries.flatMap((entry) => entry.name.startsWith("@") && entry.isDirectory()
      ? readdirSync(path.join(source, entry.name)).map((name) => path.join(source, entry.name, name))
      : [path.join(source, entry.name)]);
    for (const alias of aliases) {
      if (!lstatSync(alias).isSymbolicLink() || !existsSync(alias)) continue;
      const real = realpathSync(alias);
      const target = path.resolve(staging, path.relative(traceRoot, real));
      const destination = path.join(output, path.relative(source, alias));
      if (!inside(traceRoot, real) || !inside(staging, target) || existsSync(destination) || !existsSync(path.join(target, "package.json"))) continue;
      mkdirSync(path.dirname(destination), { recursive: true });
      symlinkSync(path.relative(path.dirname(destination), target), destination);
      restored++;
    }
  }
  return restored;
}

// Uses the build's own root/layout, not current config or a hand-maintained list
// of dependencies. A successful compilation alone is not a package acceptance.
export function packageStandalone({ projectRoot, distDir = ".next", destination }) {
  projectRoot = realpathSync(projectRoot);
  const dist = path.resolve(projectRoot, distDir);
  if (!inside(projectRoot, dist) || dist === projectRoot) throw new Error("distDir must be inside the Dashboard project.");
  const standalone = path.join(dist, "standalone");
  destination = path.resolve(destination);
  const parent = realpathSync(path.dirname(destination));
  destination = path.join(parent, path.basename(destination));
  if (inside(projectRoot, destination) || inside(destination, projectRoot)) throw new Error("Package destination must not overlap the project/build.");
  if (existsSync(destination)) throw new Error("Package destination already exists; choose a fresh directory.");
  const metadata = JSON.parse(readFileSync(path.join(dist, "required-server-files.json"), "utf8"));
  if (metadata.config.output !== "standalone" || path.resolve(metadata.appDir) !== projectRoot) {
    throw new Error("Standalone build metadata does not belong to this project.");
  }
  const traceRoot = path.resolve(metadata.config.outputFileTracingRoot || projectRoot);
  const appRelative = path.relative(traceRoot, projectRoot);
  if (!inside(traceRoot, projectRoot) || appRelative !== metadata.relativeAppDir || metadata.config.distDir !== distDir) {
    throw new Error("Standalone build layout does not match its metadata.");
  }
  checkRuntimeTree(standalone);
  let tracedFiles = 0;
  // next-minimal-server is the separate serverless/minimal runtime, not the
  // generated standalone server (Next copies next-server.js.nft.json instead).
  for (const trace of files(dist).filter((name) => name.endsWith(".nft.json") && name !== path.join(dist, "next-minimal-server.js.nft.json") && !inside(standalone, name))) {
    for (const entry of JSON.parse(readFileSync(trace, "utf8")).files) {
      const source = path.resolve(path.dirname(trace), entry);
      const output = path.resolve(standalone, path.relative(traceRoot, source));
      if (!inside(traceRoot, source) || !inside(standalone, output) || !existsSync(source) || !existsSync(output)) {
        throw new Error(`Missing or changed traced file: ${path.relative(traceRoot, source)}`);
      }
      // NFT also lists directory symlinks (e.g. a worktree's node_modules).
      // Only traced files, not every untraced sibling in that directory, ship.
      const sourceStat = statSync(source);
      const outputStat = statSync(output);
      const matches = sourceStat.isDirectory()
        ? outputStat.isDirectory()
        : sourceStat.isFile() && outputStat.isFile() && digest(source) === digest(output);
      if (!matches) throw new Error(`Missing or changed traced file: ${path.relative(traceRoot, source)}`);
      tracedFiles++;
    }
  }
  if (!tracedFiles) throw new Error("Standalone build contains no traced files.");
  if (!existsSync(path.join(standalone, appRelative, "server.js"))) throw new Error("Standalone server.js is missing.");
  const staging = mkdtempSync(path.join(parent, ".ksi-package-"));
  try {
    cpSync(standalone, staging, { recursive: true, verbatimSymlinks: true });
    const restoredAliases = restoreTracedPackageAliases(traceRoot, staging);
    const app = path.join(staging, appRelative);
    cpSync(path.join(dist, "static"), path.join(app, distDir, "static"), { recursive: true });
    if (existsSync(path.join(projectRoot, "public"))) {
      cpSync(path.join(projectRoot, "public"), path.join(app, "public"), { recursive: true, verbatimSymlinks: true });
    }
    mkdirSync(path.join(app, "scripts"), { recursive: true });
    cpSync(path.join(projectRoot, "scripts/start-production.mjs"), path.join(app, "scripts/start-production.mjs"));
    const launcher = `./${path.join(appRelative, "scripts/start-production.mjs").split(path.sep).join("/")}`;
    writeFileSync(path.join(staging, "start.mjs"), `// Retain LOCAL/EXTERNAL_VM validation before importing the generated server.\nawait import(${JSON.stringify(launcher)});\n`);
    const manifest = { format: 1, appRelative: appRelative || ".", distDir, tracedFiles, restoredAliases, platform: process.platform, arch: process.arch, node: process.version };
    writeFileSync(path.join(staging, "ksi-package.json"), `${JSON.stringify(manifest, null, 2)}\n`);
    checkRuntimeTree(staging);
    // Never replace a caller's existing directory, even if created during copy.
    mkdirSync(destination);
    renameSync(staging, destination);
    return manifest;
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [destination, ...extra] = process.argv.slice(2);
  if (!destination || extra.length) throw new Error("Usage: npm run package:standalone -- /existing-parent/new-package-directory");
  console.log(JSON.stringify(packageStandalone({
    projectRoot: fileURLToPath(new URL("..", import.meta.url)),
    distDir: process.env.KSI_DASHBOARD_DIST_DIR?.trim() || ".next",
    destination,
  }), null, 2));
}
