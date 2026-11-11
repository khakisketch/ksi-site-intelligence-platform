import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const capture = readFileSync(new URL("../e2e/p4-cleanup-capture.spec.ts", import.meta.url), "utf8");

describe("historical P4 capture safety", () => {
  it("never writes new captures into the checked-in historical evidence", () => {
    expect(capture).not.toContain('"p4-cleanup-evidence"');
    expect(capture).not.toContain("process.cwd()");
    expect(capture).toContain("testInfo.outputPath(");
  });

  it("requires an explicit historical phase before navigation", () => {
    const optIn = capture.indexOf('test.skip(capturePhase !== "before" && capturePhase !== "after"');
    expect(optIn).toBeGreaterThan(-1);
    expect(optIn).toBeLessThan(capture.indexOf("await login(page)"));
  });
});
