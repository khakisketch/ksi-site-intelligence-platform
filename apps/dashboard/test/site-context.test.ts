import { describe, expect, it } from "vitest";

import {
  resolveSiteId,
  resolveSiteSection,
  siteMark,
  siteSectionHref,
  siteShortName,
  siteSwitchHref,
} from "@/components/nav/site-context";

const query = (section?: string) => new URLSearchParams(section ? { section } : {});

describe("site context path resolution", () => {
  it("extracts the current site and excludes the directory and registration route", () => {
    expect(resolveSiteId("/sites/site-1")).toBe("site-1");
    expect(resolveSiteId("/sites/site-1/spatial-assets")).toBe("site-1");
    expect(resolveSiteId("/sites/site%201")).toBe("site 1");
    expect(resolveSiteId("/sites")).toBeNull();
    expect(resolveSiteId("/sites/")).toBeNull();
    expect(resolveSiteId("/sites/new")).toBeNull();
    expect(resolveSiteId("/")).toBeNull();
  });

  it("maps the top-level site routes to their sections", () => {
    expect(resolveSiteSection("/sites/site-1", query())).toBe("workspace");
    expect(resolveSiteSection("/sites/site-1/", query())).toBe("workspace");
    expect(resolveSiteSection("/sites/site-1", query("work-orders"))).toBe("work-orders");
    expect(resolveSiteSection("/sites/site-1", query("manage"))).toBeNull();
    expect(resolveSiteSection("/sites/site-1/spatial-assets", query())).toBe("materials");
    expect(resolveSiteSection("/sites/site-1/spatial-data-requests", query())).toBe("materials");
    expect(resolveSiteSection("/sites/site-1/analysis", query())).toBe("results");
  });

  it("does not light up a top-level tab for subpages that do not belong to one", () => {
    expect(resolveSiteSection("/sites/site-1/work-areas", query())).toBeNull();
    expect(resolveSiteSection("/sites/site-1/observations", query())).toBeNull();
    expect(resolveSiteSection("/", query())).toBeNull();
  });

  it("builds only existing site routes without carrying another site's scope", () => {
    expect(siteSectionHref("site-1", "workspace")).toBe("/sites/site-1");
    expect(siteSectionHref("site-1", "materials")).toBe("/sites/site-1/spatial-assets");
    expect(siteSectionHref("site-1", "work-orders")).toBe("/sites/site-1?section=work-orders");
    expect(siteSectionHref("site-1", "results")).toBe("/sites/site-1/analysis");
    expect(siteSectionHref("site 1", "materials")).toBe("/sites/site%201/spatial-assets");
    expect(siteSwitchHref("site-2", null)).toBe("/sites/site-2");
    expect(siteSwitchHref("site-2", "results")).toBe("/sites/site-2/analysis");
  });

  it("uses one readable mark per site name without inventing an image", () => {
    expect(siteMark("Floreat public sample")).toBe("F");
    expect(siteMark("Product Sample Field (SYNTHETIC)")).toBe("P");
    expect(siteMark("  ")).toBe("현");
  });

  it("keeps the narrow rail name readable while leaving the full name in the title", () => {
    expect(siteShortName("Floreat public sample (CC BY 4.0)")).toBe("Floreat public sample");
    expect(siteShortName("Product Sample Field (SYNTHETIC)")).toBe("Product Sample Field");
    expect(siteShortName("  ")).toBe("현장");
  });
});
