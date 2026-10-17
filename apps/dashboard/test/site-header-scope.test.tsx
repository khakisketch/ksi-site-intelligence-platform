import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import type { SiteView } from "@/lib/core-api/types";
import { siteTabHref } from "@/lib/operator-journey";

const site = { siteId: "site-1", name: "동측 현장", status: "UNMAPPED", resumeTarget: null, aoi: null } as SiteView;

function headerHtml(props: Partial<Parameters<typeof SiteHeader>[0]> = {}) {
  return renderToStaticMarkup(
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab="observations"
      latestExternalReportAt={null}
      latestExternalReportKnown={false}
      canCreateWorkOrder={false}
      canEditAoi={false}
      {...props}
    />,
  );
}

describe("siteTabHref", () => {
  it("goes direct to actual routes without scope", () => {
    const scope = { workAreaId: null, assetRef: null };
    expect(siteTabHref("site-1", "analysis", {}, scope)).toBe("/sites/site-1/analysis");
    expect(siteTabHref("site-1", "spatial-assets", {}, scope)).toBe("/sites/site-1/spatial-assets");
    expect(siteTabHref("site-1", "observations", {}, scope)).toBe("/sites/site-1");
    expect(siteTabHref("site-1", "work-orders", {}, scope)).toBe("/sites/site-1?section=work-orders");
    expect(siteTabHref("site-1", "external-results", {}, scope)).toBe("/sites/site-1?section=external-results");
  });

  it("carries a validated scope and scopes assetRef to the same catalog only", () => {
    const scope = { workAreaId: "wa-a", assetRef: "asset-1" };
    expect(siteTabHref("site-1", "analysis", {}, scope)).toBe("/sites/site-1/analysis?workAreaId=wa-a");
    expect(siteTabHref("site-1", "spatial-assets", {}, scope)).toBe(
      "/sites/site-1/spatial-assets?workAreaId=wa-a&assetRef=asset-1",
    );
    expect(siteTabHref("site-1", "observations", {}, scope)).toBe("/sites/site-1?workAreaId=wa-a");
    expect(siteTabHref("site-1", "work-orders", {}, scope)).toBe(
      "/sites/site-1?section=work-orders&workAreaId=wa-a",
    );
  });

  it("drops assetRef without its work area", () => {
    expect(siteTabHref("site-1", "spatial-assets", {}, { workAreaId: null, assetRef: "asset-1" })).toBe(
      "/sites/site-1/spatial-assets",
    );
  });
});

describe("SiteHeader scoped navigation", () => {
  it("links analysis and catalog direct with scope in both desktop and mobile navs", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a", scopedAssetRef: "asset-1" });
    // Desktop + mobile navs render the same destinations.
    expect(html.match(/\/sites\/site-1\/analysis\?workAreaId=wa-a/g)?.length).toBe(2);
    expect(html.match(/\/sites\/site-1\/spatial-assets\?workAreaId=wa-a&amp;assetRef=asset-1/g)?.length).toBe(2);
    expect(html).not.toContain("section=analysis");
    expect(html).not.toContain("section=spatial-assets");
  });

  it("keeps in-page sections and old deep-URL compat for the other tabs", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a" });
    expect(html).toContain("/sites/site-1?section=work-orders&amp;workAreaId=wa-a");
    expect(html).toContain("/sites/site-1?section=external-results&amp;workAreaId=wa-a");
  });

  it("never leaks an unverified scope (page maps it to null)", () => {
    const html = headerHtml({});
    expect(html).toContain("/sites/site-1/analysis");
    expect(html).not.toContain("workAreaId");
    expect(html).not.toContain("assetRef");
  });

  it("preserves a validated scope on the new-registration action, never on AOI setup", () => {
    const html = headerHtml({
      tab: "work-orders",
      canCreateWorkOrder: true,
      scopedWorkAreaId: "wa-a",
    });
    expect(html).toContain("/sites/site-1/observations/new?workAreaId=wa-a");
  });

  it("leaves work-area setup without a scope query", () => {
    const html = headerHtml({
      tab: "work-orders",
      canCreateWorkOrder: false,
      canEditAoi: true,
      scopedWorkAreaId: "wa-a",
    });
    expect(html).toContain("/sites/site-1/work-areas");
    expect(html).not.toContain("/sites/site-1/work-areas?workAreaId");
  });

  it("shows no preparation action without the role grant", () => {
    const ready = { ...site, status: "PATROL_READY" } as SiteView;
    const html = renderToStaticMarkup(
      <SiteHeader
        site={ready}
        selectedEpochId={null}
        tab="work-orders"
        latestExternalReportAt={null}
        latestExternalReportKnown={false}
        canCreateWorkOrder={false}
        canEditAoi={false}
        scopedWorkAreaId="wa-a"
      />,
    );
    expect(html).not.toContain("observations/new");
  });
});
