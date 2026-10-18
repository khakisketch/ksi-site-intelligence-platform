import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const PAGE = readFileSync(join(process.cwd(), "src/app/sites/[siteId]/page.tsx"), "utf8");

describe("tabbed site workspace uses surviving platform surfaces", () => {
  it("keeps the external result history as a distinct list inside the analysis area", () => {
    expect(PAGE).toContain('{tab === "analysis"');
    expect(PAGE).toContain("<ExternalObservationHistory");
    expect(PAGE).toContain("listSiteExternalVolumeHistory");
    expect(PAGE).not.toContain('{tab === "external-results"');
  });

  it("has no retired briefing, event, mission, design, or report tab data source", () => {
    expect(PAGE).not.toMatch(/listAllEvents|listMissions|getSiteWorkspace|getLatestSiteBriefing|listSiteProcessingJobs|\/events|\/missions/);
    expect(PAGE).toContain('{tab === "overview"');
    expect(PAGE).toContain('{tab === "materials"');
    expect(PAGE).toContain('{tab === "analysis"');
    expect(PAGE).toContain('{tab === "work-orders"');
    expect(PAGE).toContain('{tab === "manage"');
  });
});
