import { mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import ts from "typescript";
import { writeConfigurationDefaults } from "next/dist/lib/typescript/writeConfigurationDefaults";

import { describe, expect, it } from "vitest";
import { createAnalysisTsconfig } from "../scripts/analysis-tsconfig.mjs";

describe("durable Analysis compiler inputs", () => {
  it("keeps per-run generated paths out of the checked-in compiler configuration", () => {
    const config = JSON.parse(readFileSync(join(process.cwd(), "tsconfig.json"), "utf8"));
    expect(config.include.some((entry: string) => entry.includes("analysis-next-") || entry.includes("analysis-e2e-red"))).toBe(false);
    expect(config.exclude).toContain("test-results");
  });

  it("selects a separate compiler file for Analysis E2E instead of mutating product config", () => {
    const nextConfig = readFileSync(join(process.cwd(), "next.config.ts"), "utf8");
    const harness = readFileSync(join(process.cwd(), "playwright.analysis.config.ts"), "utf8");
    expect(nextConfig).toContain("tsconfigPath: requestedTsconfig");
    expect(harness).toContain("KSI_DASHBOARD_TSCONFIG_PATH: dashboardTsconfig");
  });

  it("uses only current-run generated types and lets the actual Next writer mutate the clone", async () => {
    const root = mkdtempSync(join(tmpdir(), "ksi-compiler-regression-"));
    const base = readFileSync(join(process.cwd(), "tsconfig.json"), "utf8");
    writeFileSync(join(root, "tsconfig.json"), base);
    const runId = "a".repeat(64);
    const distDir = join("test-results", `analysis-next-${runId}`);
    mkdirSync(join(root, "src"));
    writeFileSync(join(root, "src", "owner.ts"), "export const owned = 1;");
    for (const name of [distDir, "test-results/analysis-next-old"]) {
      mkdirSync(join(root, name, "types"), { recursive: true });
      writeFileSync(join(root, name, "types", "routes.ts"), "export type Route = string;");
    }
    const filename = createAnalysisTsconfig({ projectRoot: root, runId, distDir });
    const target = join(root, filename);
    // Force a real generated-input update, not just an assertion on source text.
    const clone = JSON.parse(readFileSync(target, "utf8"));
    clone.include = clone.include.filter((entry: string) => !entry.startsWith(distDir));
    writeFileSync(target, JSON.stringify(clone));
    await writeConfigurationDefaults(ts.version, target, false, true, distDir, false, false);
    const updated = JSON.parse(readFileSync(target, "utf8"));
    expect(updated.compilerOptions.strict).toBe(true);
    expect(updated.include).toContain(`${distDir}/types/**/*.ts`);
    const parsed = ts.parseJsonConfigFileContent(updated, ts.sys, root);
    expect(parsed.errors).toEqual([]);
    expect(parsed.fileNames).toContain(join(root, "src", "owner.ts"));
    expect(parsed.fileNames).toContain(join(root, distDir, "types", "routes.ts"));
    expect(parsed.fileNames.some((entry) => entry.includes("analysis-next-old"))).toBe(false);
    expect(readFileSync(join(root, "tsconfig.json"), "utf8")).toBe(base);
    expect(createAnalysisTsconfig({ projectRoot: root, runId, distDir, reuse: true })).toBe(filename);
  });

  it("rejects run-path substitution and a symlinked inherited compiler file", () => {
    const root = mkdtempSync(join(tmpdir(), "ksi-compiler-identity-"));
    const runId = "b".repeat(64);
    const distDir = join("test-results", `analysis-next-${runId}`);
    expect(() => createAnalysisTsconfig({ projectRoot: root, runId: "../outside", distDir })).toThrow("identity");
    const base = join(root, "tsconfig.json");
    writeFileSync(base, "{}");
    symlinkSync(base, join(root, `.tsconfig-analysis-${runId}.json`));
    expect(() => createAnalysisTsconfig({ projectRoot: root, runId, distDir, reuse: true })).toThrow("unsafe");
    expect(readFileSync(base, "utf8")).toBe("{}");
  });
});
