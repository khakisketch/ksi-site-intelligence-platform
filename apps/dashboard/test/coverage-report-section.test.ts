import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SECTION = readFileSync(
  join(process.cwd(), "src/components/missions/CoverageReportSection.tsx"),
  "utf8",
);

describe("커버리지 귀속·대사 표시", () => {
  it("[핵심] 귀속 캡션을 상시 렌더한다(대사 가능 여부와 무관)", () => {
    expect(SECTION).toContain("ratioAttributionNote");
  });

  it("계획값 숫자를 비행 결과 캡션에 반복하지 않는다", () => {
    // page.tsx:239 의 기존 원칙 — 발급 메타의 '계획 커버리지' 필드와 나란히
    // 두지 않는다. plannedGeneralCoverageRatio 를 읽어서 조건 분기에는 쓰되
    // 화면에 그 숫자를 그대로 찍지는 않는다.
    expect(SECTION).not.toMatch(/plannedGeneralCoverageRatio\}/);
  });

  it("거부 이력이 있으면 비율 타일보다 먼저 렌더한다", () => {
    expect(SECTION).toContain("rejections");
    const tilesIndex = SECTION.indexOf("필수 위험구역");
    const rejectionsIndex = SECTION.indexOf("거부");
    expect(rejectionsIndex).toBeGreaterThan(-1);
    expect(rejectionsIndex).toBeLessThan(tilesIndex);
  });
});
