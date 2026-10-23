import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const PAGE = readFileSync(join(process.cwd(), "src/app/sites/[siteId]/page.tsx"), "utf8");

describe("tabbed site workspace uses surviving platform surfaces", () => {
  it("keeps the external result history as a distinct list outside computed results", () => {
    // '분석·검토 기록' 영역은 실제 분석 라우트가 주인이다 — 중간 진입 화면을
    // 두지 않고 범위만 실어 보낸다. 옛 section 분기는 남기지 않는다.
    expect(PAGE).toContain("redirect(");
    expect(PAGE).toContain("`${sitePath}/analysis");
    expect(PAGE).not.toContain('{tab === "analysis"');
    expect(PAGE).not.toContain("<ExternalObservationHistory");
    expect(PAGE).not.toContain('{tab === "external-results"');
    // 외부 비교 기록은 observations 경로의 별도 목록으로 둔다.
    const OBS = readFileSync(join(process.cwd(), "src/app/sites/[siteId]/observations/page.tsx"), "utf8");
    expect(OBS).toContain("<ExternalObservationHistory");
  });

  it("has no retired briefing, event, mission, design, or report tab data source", () => {
    expect(PAGE).not.toMatch(/listAllEvents|listMissions|getSiteWorkspace|getLatestSiteBriefing|listSiteProcessingJobs|\/events|\/missions/);
    expect(PAGE).toContain('{tab === "workspace"');
    expect(PAGE).toContain('{tab === "work-orders"');
    expect(PAGE).toContain('{tab === "manage"');
  });
});
