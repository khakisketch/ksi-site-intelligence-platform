// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function parseStages(dockerfile: string): string[][] {
  return dockerfile
    .split(/^FROM /m)
    .slice(1)
    .map((stage) => stage.split("\n").map((line) => line.trim()));
}

function stageText(lines: string[]): string {
  return lines.join("\n");
}

describe("Dashboard Docker target image", () => {
  const dockerfile = readFileSync(join(process.cwd(), "Dockerfile"), "utf8");
  const stages = parseStages(dockerfile);

  it("pins all Node stages by digest and locks dependencies", () => {
    expect(stages.length).toBe(3);
    for (const stage of stages) {
      expect(stage[0]).toMatch(/^node:22\.18-alpine@sha256:[0-9a-f]{64} AS /);
    }
    const dependencies = stageText(stages[0]);
    expect(dependencies).toContain("COPY package.json package-lock.json ./");
    expect(dependencies).toContain("RUN npm ci");
    expect(dependencies).not.toMatch(/npm install(?! ci)/);
  });

  it("builds standalone output and ships only runtime artifacts as non-root", () => {
    const builder = stageText(stages[1]);
    expect(builder).toContain("COPY --from=dependencies /app/node_modules ./node_modules");
    expect(builder).toContain("RUN npm run build");
    const runtime = stageText(stages[2]);
    expect(runtime).toContain("adduser --system --uid 10001");
    expect(runtime).toContain("COPY --from=builder --chown=ksi-dashboard:ksi-dashboard /app/public ./public");
    expect(runtime).toContain("COPY --from=builder --chown=ksi-dashboard:ksi-dashboard /app/.next/standalone ./");
    expect(runtime).toContain("COPY --from=builder --chown=ksi-dashboard:ksi-dashboard /app/.next/static ./.next/static");
    expect(runtime).toContain("COPY --chown=ksi-dashboard:ksi-dashboard scripts/start-production.mjs ./scripts/start-production.mjs");
    expect(runtime).toContain("USER ksi-dashboard");
    expect(runtime).toContain('CMD ["node", "scripts/start-production.mjs"]');
    expect(runtime).not.toMatch(/COPY .*\.env/);
  });

  it("rejects plausible regressions instead of only describing the current file", () => {
    const brokenBase = dockerfile.replace(/node:22\.18-alpine@sha256:[0-9a-f]{64}/g, "node:22-alpine");
    expect(brokenBase).not.toMatch(/^FROM node:22\.18-alpine@sha256:[0-9a-f]{64} AS /m);
    const brokenInstall = dockerfile.replace("RUN npm ci", "RUN npm install");
    expect(brokenInstall).toMatch(/npm install(?! ci)/);
    const brokenRoot = dockerfile.replace("USER ksi-dashboard\n", "");
    expect(brokenRoot).not.toContain("USER ksi-dashboard");
  });

  it("keeps build secrets and local state out of the image context", () => {
    const ignore = readFileSync(join(process.cwd(), ".dockerignore"), "utf8");
    for (const entry of ["node_modules", ".next*", "test-results", ".env.local"]) {
      expect(ignore.split("\n").map((line) => line.trim())).toContain(entry);
    }
  });
});
