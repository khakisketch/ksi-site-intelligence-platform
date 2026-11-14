import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import type { SiteView } from "@/lib/core-api/types";

const site = { siteId: "site-1", name: "동측 현장", status: "UNMAPPED", resumeTarget: null, aoi: null } as SiteView;

describe("Site header analysis responsibility", () => {
  it("leaves external reports and registration actions in their owning surfaces", () => {
    const html = renderToStaticMarkup(<SiteHeader site={site} selectedEpochId={null} tab="analysis" />);
    expect(html).not.toContain("최근 외부 비교 보고");
    expect(html).not.toContain("/observations/new");
    expect(html).toMatch(/<a[^>]*aria-current="page"[^>]*href="\/sites\/site-1\/analysis"/);
  });
});
