import { describe, expect, it } from "vitest";

import { siteDetailDocumentTitle } from "@/lib/site-detail-title";

describe("현장 상세 문서 제목", () => {
  it("현장명을 먼저 두어 같은 종류의 현장을 여러 탭에서 구분한다", () => {
    expect(siteDetailDocumentTitle("송도 A3 현장")).toBe("송도 A3 현장 · 현장 · KSI");
  });
});
