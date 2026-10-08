import { describe, expect, it } from "vitest";

import { resolveSiteOperatorNextAction } from "@/lib/operator-next-action";
import type { SiteView } from "@/lib/core-api/types";

function site(status: SiteView["status"], aoi: SiteView["aoi"]): SiteView {
  return {
    siteId: "site-1",
    name: "테스트 현장",
    siteFrame: { crs: "EPSG:5186", verticalDatum: "KNGeoid2018", unit: "meter", transformVersion: "1.0.0" },
    status,
    resumeTarget: null,
    registeredAt: "2026-10-01T00:00:00Z",
    updatedAt: "2026-10-01T00:00:00Z",
    aoi,
    dataResidency: null,
    aiEgressAllowed: false,
    modelMaxAgeDays: null,
  };
}

describe("site operator next action", () => {
  it("links an editable unmapped site to its AOI section", () => {
    expect(resolveSiteOperatorNextAction(site("UNMAPPED", null), {
      canEditSite: true,
      canCreateWorkOrder: true,
    })).toMatchObject({ href: "/sites/site-1#site-aoi", label: "현장 범위 설정" });
  });

  it("offers the mounted observation flow when a site has an AOI", () => {
    const aoi = { vertices: [
      { latDeg: 37.5, lonDeg: 127 },
      { latDeg: 37.5, lonDeg: 127.1 },
      { latDeg: 37.6, lonDeg: 127.1 },
    ] };
    expect(resolveSiteOperatorNextAction(site("PATROL_READY", aoi), {
      canEditSite: false,
      canCreateWorkOrder: true,
    }, { includeRoutineSurvey: true })).toMatchObject({
      kind: "CREATE_OBSERVATION",
      href: "/sites/site-1/observations/new",
      responsiveAction: "WORK_ORDERS_WRITE",
    });
  });

  it("does not invent a write action when work-order permission is absent", () => {
    const aoi = { vertices: [
      { latDeg: 37.5, lonDeg: 127 },
      { latDeg: 37.5, lonDeg: 127.1 },
      { latDeg: 37.6, lonDeg: 127.1 },
    ] };
    expect(resolveSiteOperatorNextAction(site("PATROL_READY", aoi), {
      canEditSite: false,
      canCreateWorkOrder: false,
    }, { includeRoutineSurvey: true })).toBeNull();
  });
});
