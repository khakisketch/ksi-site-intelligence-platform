import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import type { SiteView } from "@/lib/core-api/types";

const site = { siteId: "site-1", name: "동측 현장", status: "UNMAPPED", resumeTarget: null, aoi: null } as SiteView;

describe("Site header report-time semantics", () => {
  it.each([
    [true, "2026-10-15T10:00:00Z", "2026"],
    [true, null, "아직 없음"],
    [false, null, "알 수 없음"],
  ])("labels result reporting independently from capture (%s, %s)", (known, at, expected) => {
    const html = renderToStaticMarkup(<SiteHeader site={site} selectedEpochId={null} tab="overview" latestExternalReportAt={at} latestExternalReportKnown={known} canCreateWorkOrder={false} canEditAoi={false} />);
    expect(html).toContain("최근 외부 비교 보고");
    expect(html).toContain(expected);
    expect(html).not.toContain("최신 관측");
  });
});
