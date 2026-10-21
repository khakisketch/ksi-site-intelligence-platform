import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 데스크톱 표의 "바로가기" 열이 현장별 CTA(primaryAction)와 "현장 열기"를 함께
// 넣어 두 버튼이 좁은 열에서 줄바꿈됐다(F08). 그 CTA는 이미 SiteHeader.tsx가
// 현장 상세 헤더에서 보여준다 — 표 행은 열람 동작 하나만 남긴다.
// (표 본문은 SiteListDenseList.tsx 에 산다 — page.tsx 는 보기 선택기만 둔다.)
const DENSE = readFileSync(join(process.cwd(), "src/components/site/SiteListDenseList.tsx"), "utf8");
const PAGE = readFileSync(join(process.cwd(), "src/app/sites/page.tsx"), "utf8");

describe("sites table row action column (F08)", () => {
  it("keeps exactly one row action (현장 열기) in the desktop table row", () => {
    const rowStart = DENSE.indexOf("<TableRow key={site.siteId} columns={DENSE_COLUMNS}");
    const rowEnd = DENSE.indexOf("</TableRow>", rowStart);
    const row = DENSE.slice(rowStart, rowEnd);

    const actionCellStart = row.lastIndexOf('<span className="flex justify-end">');
    expect(actionCellStart).toBeGreaterThan(-1);
    const actionCell = row.slice(actionCellStart);

    expect(actionCell).toContain("현장 열기");
    expect(actionCell).not.toContain("primaryAction");
    expect(actionCell).not.toContain("ResponsiveActionBoundary");
    expect((actionCell.match(/<TableAction/g) ?? []).length).toBe(1);
  });

  it("keeps the desktop comparison table while dropping retired event and mission cells", () => {
    expect(DENSE).toContain("<TableShell");
    expect(DENSE).toContain("현장 상태");
    expect(DENSE).not.toMatch(/listAllEventsCached|listMissionsCached|getHomeEventEvidencePreview|미조치|마지막 임무 발급/);
    // 장식 미리보기 열은 밀도표에 없다 — 폭을 현장 이름에 돌린다.
    expect(DENSE).not.toContain("SiteListVisual");
    expect(DENSE).not.toContain("<img");
  });

  it("names the stage column site management, never dataset or analysis progress", () => {
    expect(DENSE).toContain("관리 단계");
    expect(DENSE).not.toContain("진행 단계");
    const bar = readFileSync(join(process.cwd(), "src/components/site/SiteProgressBar.tsx"), "utf8");
    // 막대 본문·접근성 문구는 현장 관리 상태의 위치만 말한다 — 촬영 자료량·처리
    // 진도·분석 진행률로 읽히지 않게 한다. 본선 순서·상태값·개수는 그대로다.
    expect(bar).toContain("현장 관리 단계");
    expect(bar).toContain("촬영 자료량·처리");
    expect(bar).not.toMatch(/`진행 단계/);
    expect(bar).toContain("SITE_PROGRESS_STAGES");
  });

  it("keeps the desktop page on the view selector contract", () => {
    expect(PAGE).toContain("SiteListView");
    expect(PAGE).toContain("SiteListDenseList");
    expect(PAGE).toContain("SiteListDesktopCards");
    // 보기 방식은 URL 쿼리가 아니다 — 공유·뒤로가기 대상이 아니다.
    expect(PAGE).not.toMatch(/params\.view|view\?: string/);
  });
});
