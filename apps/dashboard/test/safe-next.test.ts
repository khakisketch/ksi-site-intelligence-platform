import { describe, expect, it } from "vitest";

import { safeNextPath } from "@/lib/auth/safe-next";

const VISUAL_A = `ksa-v1-${"a".repeat(64)}`;
const VISUAL_B = `ksa-v1-${"b".repeat(64)}`;

describe("safeNextPath", () => {
  it("preserves an exact compare return with pair and area context", () => {
    const raw = `/sites/site-1?mode=compare&workAreaId=w1&visualAAssetRef=${VISUAL_A}&visualBAssetRef=${VISUAL_B}`;
    expect(safeNextPath(raw)).toBe(raw);
  });

  it("preserves a bare site path", () => {
    expect(safeNextPath("/sites/site-1")).toBe("/sites/site-1");
  });

  it("rejects external, protocol-relative and non-path returns", () => {
    expect(safeNextPath("https://evil.test/sites/site-1")).toBe("/");
    expect(safeNextPath("//evil.test/sites/site-1")).toBe("/");
    expect(safeNextPath("javascript:alert(1)")).toBe("/");
    expect(safeNextPath("")).toBe("/");
  });
});
