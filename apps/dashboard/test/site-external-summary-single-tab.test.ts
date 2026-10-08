import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const PAGE = readFileSync(join(process.cwd(), "src/app/sites/[siteId]/page.tsx"), "utf8");

describe("tabbed site workspace uses surviving platform surfaces", () => {
  it("keeps the external result history in its dedicated tab", () => {
    expect(PAGE).toContain('{tab === "external-results"');
    expect(PAGE).toContain("<ExternalObservationHistory");
    expect(PAGE).toContain("listSiteExternalVolumeHistory");
  });

  it("has no retired briefing, event, mission, design, or report tab data source", () => {
    expect(PAGE).not.toMatch(/listAllEvents|listMissions|getSiteWorkspace|getLatestSiteBriefing|listSiteProcessingJobs|\/events|\/missions/);
    expect(PAGE).toContain('{tab === "observations"');
    expect(PAGE).toContain('{tab === "analysis"');
    expect(PAGE).toContain('{tab === "spatial-assets"');
    expect(PAGE).toContain('{tab === "work-orders"');
  });
});
