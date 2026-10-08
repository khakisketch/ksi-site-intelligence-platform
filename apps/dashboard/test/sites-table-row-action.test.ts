import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 데스크톱 표의 "바로가기" 열이 현장별 CTA(primaryAction)와 "현장 열기"를 함께
// 넣어 두 버튼이 좁은 열에서 줄바꿈됐다(F08). 그 CTA는 이미 SiteHeader.tsx가
// 현장 상세 헤더에서 보여준다 — 표 행은 열람 동작 하나만 남긴다.
const PAGE = readFileSync(join(process.cwd(), "src/app/sites/page.tsx"), "utf8");

describe("sites table row action column (F08)", () => {
  it("keeps exactly one row action (현장 열기) in the desktop table row", () => {
    const rowStart = PAGE.indexOf("<TableRow key={site.siteId} columns={COLUMNS}");
    const rowEnd = PAGE.indexOf("</TableRow>", rowStart);
    const row = PAGE.slice(rowStart, rowEnd);

    const actionCellStart = row.lastIndexOf('<span className="flex justify-end">');
    expect(actionCellStart).toBeGreaterThan(-1);
    const actionCell = row.slice(actionCellStart);

    expect(actionCell).toContain("현장 열기");
    expect(actionCell).not.toContain("primaryAction");
    expect(actionCell).not.toContain("ResponsiveActionBoundary");
    expect((actionCell.match(/<TableAction/g) ?? []).length).toBe(1);
  });

  it("keeps the desktop comparison table while dropping retired event and mission cells", () => {
    expect(PAGE).toContain("<TableShell");
    expect(PAGE).toContain("현장 상태");
    expect(PAGE).not.toMatch(/listAllEventsCached|listMissionsCached|getHomeEventEvidencePreview|미조치|마지막 임무 발급/);
  });
});
