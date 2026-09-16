import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// externalResultSummary(ExternalSiteResultSummary)가 브리핑·데이터·보고서 세 탭에
// 그대로 반복돼 탭을 넘겨도 화면이 바뀌지 않는 것처럼 보였다(F11). 가장 풍부한
// 내용을 가진 "데이터" 탭 하나에만 두고, 다른 탭은 그리로 링크한다.
const PAGE = readFileSync(join(process.cwd(), "src/app/sites/[siteId]/page.tsx"), "utf8");

function tabSection(tabName: string): string {
  const marker = `{tab === "${tabName}" && (`;
  const start = PAGE.indexOf(marker);
  expect(start).toBeGreaterThan(-1);
  // The tabs are siblings inside one conditional-rendering block; the next
  // `{tab === "..."` (or the closing of the whole block) bounds this section.
  const nextTab = PAGE.indexOf('{tab === "', start + marker.length);
  return PAGE.slice(start, nextTab === -1 ? PAGE.length : nextTab);
}

describe("external result summary appears in exactly one site tab (F11)", () => {
  it("renders the full stub only in the data tab", () => {
    const briefing = tabSection("briefing");
    const data = tabSection("data");
    const reports = tabSection("reports");

    expect(data).toContain("{externalResultSummary}");
    expect(briefing).not.toContain("{externalResultSummary}");
    expect(reports).not.toContain("{externalResultSummary}");
  });

  it("links the briefing and reports tabs to the data tab instead", () => {
    const briefing = tabSection("briefing");
    const reports = tabSection("reports");

    expect(briefing).toContain("?tab=data");
    expect(reports).toContain("?tab=data");
  });
});
