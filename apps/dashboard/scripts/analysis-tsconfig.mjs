import { chmodSync, closeSync, lstatSync, openSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// Keep the clone next to tsconfig.json: TypeScript's relative include/paths retain
// their meaning. Next may add generated type inputs to this clone, never the base.
export function createAnalysisTsconfig({ projectRoot, runId, distDir, reuse = false }) {
  if (!/^[0-9a-f]{64}$/.test(runId) || distDir !== join("test-results", `analysis-next-${runId}`)) {
    throw new Error("invalid Analysis compiler run identity");
  }
  const filename = `.tsconfig-analysis-${runId}.json`;
  const target = join(projectRoot, filename);
  if (reuse) {
    const metadata = lstatSync(target);
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.uid !== process.getuid?.() || (metadata.mode & 0o777) !== 0o600) {
      throw new Error("unsafe inherited Analysis compiler configuration");
    }
    return filename;
  }
  const base = JSON.parse(readFileSync(join(projectRoot, "tsconfig.json"), "utf8"));
  const config = {
    ...base,
    include: [
      "next-env.d.ts", "src/**/*.ts", "src/**/*.tsx", "test/**/*.ts", "test/**/*.tsx",
      "e2e/**/*.ts", "analysis-e2e/**/*.ts", "*.ts", "*.mts",
      `${distDir}/types/**/*.ts`, `${distDir}/dev/types/**/*.ts`,
    ],
    exclude: ["node_modules"],
  };
  const descriptor = openSync(target, "wx", 0o600);
  try {
    writeFileSync(descriptor, `${JSON.stringify(config, null, 2)}\n`, "utf8");
  } finally {
    closeSync(descriptor);
  }
  chmodSync(target, 0o600);
  return filename;
}
