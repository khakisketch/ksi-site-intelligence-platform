import { describe, expect, it } from "vitest";

import {
  analysesForArea,
  buildAreaCaptureEntries,
  computePlaneBounds,
  disambiguatedAreaNames,
  disambiguatedAssetHeadlines,
  displayName,
  extractSimpleRing,
  formatPlaneValue,
  legacyRowsForArea,
  ordersForArea,
  parseFootprintWkt,
  parseScopeId,
  pickFootprintAsset,
  planeUnitForCrs,
  resolveSelectedAssetRef,
  resolveSelectedWorkAreaId,
  ringsCoincident,
  sameDisplayPlane,
  selectableGeometry,
} from "@/app/sites/[siteId]/site-spatial";
import type { WorkArea } from "@/lib/core-api/types";

function area(overrides: Partial<WorkArea> & { workAreaId: string }): WorkArea {
  return {
    schemaVersion: "1.0",
    siteId: "site-1",
    name: "구역",
    polygon: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
    crs: "EPSG:4326",
    status: "ACTIVE",
    supersedes: null,
    createdAt: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

describe("site spatial scope parsing", () => {
  it("accepts exact known ids and rejects blank, oversized, or non-string input", () => {
    expect(parseScopeId(" area-1 ")).toBe("area-1");
    expect(parseScopeId("")).toBeNull();
    expect(parseScopeId("   ")).toBeNull();
    expect(parseScopeId("x".repeat(201))).toBeNull();
    expect(parseScopeId(["area-1"])).toBeNull();
    expect(parseScopeId(undefined)).toBeNull();
  });

  it("keeps an exact known selection, including long names, without truncation", () => {
    const longName = "남측 절토 구역 ".repeat(10).trim();
    const areas = [area({ workAreaId: "old", name: longName, createdAt: "2026-09-01T00:00:00Z" })];
    expect(resolveSelectedWorkAreaId(areas, "old")).toBe("old");
  });

  it("falls back to the most recent active area for unknown query values", () => {
    const areas = [
      area({ workAreaId: "archived", status: "ARCHIVED", createdAt: "2026-10-15T00:00:00Z" }),
      area({ workAreaId: "older", createdAt: "2026-09-01T00:00:00Z" }),
      area({ workAreaId: "newer", createdAt: "2026-10-10T00:00:00Z" }),
    ];
    expect(resolveSelectedWorkAreaId(areas, "no-such-area")).toBe("newer");
    expect(resolveSelectedWorkAreaId(areas, undefined)).toBe("newer");
  });

  it("prefers work-order bindings first, analysis bindings second, recency third", () => {
    const areas = [
      area({ workAreaId: "recent-empty", createdAt: "2026-10-12T00:00:00Z" }),
      area({ workAreaId: "analysis-only", createdAt: "2026-09-15T00:00:00Z" }),
      area({ workAreaId: "order-bound", createdAt: "2026-09-01T00:00:00Z" }),
    ];
    const bindings = { workOrderAreaIds: ["order-bound"], analysisAreaIds: ["analysis-only"] };
    expect(resolveSelectedWorkAreaId(areas, undefined, bindings)).toBe("order-bound");
    expect(resolveSelectedWorkAreaId(areas, undefined, { analysisAreaIds: ["analysis-only"] })).toBe("analysis-only");
    expect(resolveSelectedWorkAreaId(areas, undefined, {})).toBe("recent-empty");
    expect(resolveSelectedWorkAreaId(areas, "analysis-only", bindings)).toBe("analysis-only");
  });

  it("uses a recent archived area only when nothing active remains, else null", () => {
    const archived = [area({ workAreaId: "a1", status: "ARCHIVED" })];
    expect(resolveSelectedWorkAreaId(archived, "unknown")).toBe("a1");
    expect(resolveSelectedWorkAreaId([], "unknown")).toBeNull();
  });

  it("accepts an asset ref only when it sits on the fetched catalog page", () => {
    const page = {
      contractVersion: "spatial-asset-catalog-page.v1",
      siteId: "site-1",
      workAreaId: "area-1",
      scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY",
      scopeNote: "",
      assets: [{ assetRef: "asset-1" }],
      nextCursor: null,
      hasMore: false,
    } as never;
    expect(resolveSelectedAssetRef(page, "asset-1")).toBe("asset-1");
    expect(resolveSelectedAssetRef(page, "asset-9")).toBeNull();
    expect(resolveSelectedAssetRef(null, "asset-1")).toBeNull();
  });
});

describe("site spatial geometry guards", () => {
  it("treats CRS labels case-insensitively when deciding a shared plane", () => {
    expect(sameDisplayPlane("EPSG:5186", "epsg:5186 ")).toBe(true);
    expect(sameDisplayPlane("EPSG:5186", "EPSG:4326")).toBe(false);
  });

  it("returns null geometry instead of throwing for missing polygon or CRS", () => {
    expect(selectableGeometry({ ...area({ workAreaId: "x" }), polygon: undefined as never })).toBeNull();
    expect(selectableGeometry({ ...area({ workAreaId: "x" }), crs: "" })).toBeNull();
    expect(selectableGeometry(area({ workAreaId: "x" }))).not.toBeNull();
  });

  it("opens a closed simple ring and rejects holes, other types, and bad numbers", () => {
    const closed = {
      type: "Polygon",
      coordinates: [[[0, 0], [4, 0], [4, 3], [0, 0]]],
    };
    expect(extractSimpleRing(closed)).toEqual([[0, 0], [4, 0], [4, 3]]);
    expect(extractSimpleRing({ type: "MultiPolygon", coordinates: [] })).toBeNull();
    expect(extractSimpleRing({ type: "Polygon", coordinates: [[[[0, 0]]], [[[1, 1]]]] })).toBeNull();
    expect(extractSimpleRing({ type: "Polygon", coordinates: [[[0, 0], ["a", 0], [0, 0]]] })).toBeNull();
    expect(extractSimpleRing({ type: "Polygon", coordinates: [[[0, 0], [1, 1], [0, 0]]] })).toBeNull();
  });

  it("parses only single-ring POLYGON footprints", () => {
    expect(parseFootprintWkt("POLYGON ((200000 549999.8, 200010 549999.8, 200010 550009.8, 200000 549999.8))"))
      .toEqual([[200000, 549999.8], [200010, 549999.8], [200010, 550009.8]]);
    expect(parseFootprintWkt("MULTIPOLYGON (((0 0, 1 0, 1 1, 0 0)))")).toBeNull();
    expect(parseFootprintWkt("POLYGON ((0 0, nope 1, 0 0))")).toBeNull();
    expect(parseFootprintWkt("not a geometry")).toBeNull();
  });

  it("measures real plane bounds and formats axis values without invention", () => {
    expect(computePlaneBounds([[200000, 549999.8], [200010, 550009.8]])).toEqual({
      minX: 200000, minY: 549999.8, maxX: 200010, maxY: 550009.8,
    });
    expect(computePlaneBounds([])).toBeNull();
    expect(formatPlaneValue(200000, "meters")).toBe("200000");
    expect(formatPlaneValue(549999.8, "meters")).toBe("549999.8");
    expect(formatPlaneValue(127.123456789, "degrees")).toBe("127.123457");
    expect(formatPlaneValue(549999.8, "unknown")).toBe("549999.8");
  });

  it("certifies plane units only for known coordinate systems", () => {
    expect(planeUnitForCrs("EPSG:5186")).toBe("meters");
    expect(planeUnitForCrs("epsg:4326")).toBe("degrees");
    expect(planeUnitForCrs("EPSG:9999")).toBe("unknown");
  });

  it("detects coincident rings regardless of start point or direction", () => {
    const ring: Array<[number, number]> = [[0, 0], [4, 0], [4, 3]];
    expect(ringsCoincident(ring, [[0, 0], [4, 0], [4, 3]])).toBe(true);
    expect(ringsCoincident(ring, [[4, 0], [4, 3], [0, 0]])).toBe(true);
    expect(ringsCoincident(ring, [[0, 0], [4, 3], [4, 0]])).toBe(true);
    expect(ringsCoincident(ring, [[0, 0], [4, 0], [4, 4]])).toBe(false);
    expect(ringsCoincident(ring, [[0, 0], [4, 0]])).toBe(false);
    expect(ringsCoincident([], [])).toBe(false);
  });
});

describe("site spatial scope summaries", () => {
  it("keeps failed reads unknown instead of turning them into empty lists", () => {
    expect(ordersForArea(null, "area-1")).toBeNull();
    expect(analysesForArea(null, "area-1")).toBeNull();
    expect(legacyRowsForArea(null, "area-1")).toBeNull();
  });

  it("skips orders with missing area bindings instead of throwing", () => {
    const orders = [{ workOrderId: "w0" }, { workOrderId: "w1", workAreaIds: ["area-1"] }] as never;
    expect(ordersForArea(orders, "area-1")?.map((o) => o.workOrderId)).toEqual(["w1"]);
  });

  it("filters each family by exact work area without merging V2 and legacy", () => {
    const orders = [
      { workOrderId: "w1", workAreaIds: ["area-1"] },
      { workOrderId: "w2", workAreaIds: ["area-2"] },
    ] as never;
    const analyses = [
      { analysisId: "v1", workAreaId: "area-1" },
      { analysisId: "v2", workAreaId: "area-2" },
    ] as never;
    const legacy = [
      { reportRef: "r1", result: { workAreaId: "area-1" } },
      { reportRef: "r2", result: null },
    ] as never;
    expect(ordersForArea(orders, "area-1")?.map((o) => o.workOrderId)).toEqual(["w1"]);
    expect(analysesForArea(analyses, "area-1")?.map((a) => a.analysisId)).toEqual(["v1"]);
    expect(legacyRowsForArea(legacy, "area-1")?.map((r) => r.reportRef)).toEqual(["r1"]);
  });

  it("prefers the selected raster asset for the footprint overlay, else the first measured one", () => {
    const first = { assetRef: "a1", inspection: { raster: { footprintWkt: "POLYGON ((0 0, 1 0, 1 1, 0 0))" } } };
    const second = { assetRef: "a2", inspection: { raster: null } };
    expect(pickFootprintAsset([first, second] as never, null)?.assetRef).toBe("a1");
    expect(pickFootprintAsset([first, second] as never, "a2")).toEqual(first);
    expect(pickFootprintAsset([second] as never, null)).toBeNull();
  });

  it("lists capture entries newest-first with sources kept separate and bounded", () => {
    const entries = buildAreaCaptureEntries({
      assets: [{
        assetRef: "a1",
        kind: "dsm",
        revision: 2,
        lifecycleState: "SEALED",
        declared: { fileName: "tile.tif", captureStartedAt: "2026-10-10T00:00:00Z", captureEndedAt: "2026-10-10T01:00:00Z", submittedAt: "2026-10-11T00:00:00Z" },
      }] as never,
      legacyRows: [{
        reportRef: "r1",
        state: "AVAILABLE",
        result: { measurementStatus: "DONE", baselineCapturedFrom: null, baselineCapturedTo: null, currentCapturedFrom: "2026-10-12T00:00:00Z", currentCapturedTo: "2026-10-12T01:00:00Z", reportedAt: "2026-10-13T00:00:00Z" },
      }] as never,
      limit: 10,
    });
    expect(entries.map((entry) => entry.key)).toEqual(["legacy:r1", "asset:a1"]);
    expect(entries[0].source).toBe("legacy");
    expect(entries[1].source).toBe("asset");
    expect(entries[0].reportRef).toBe("r1");
    expect(entries[0].headline).toContain("촬영");
    expect(entries[0].headline).not.toContain("r1");
    expect(entries[1].headline).not.toMatch(/tile\.tif|revision/);
    expect(buildAreaCaptureEntries({ assets: null, legacyRows: null, limit: 10 })).toEqual([]);
  });

  it("keeps known asset dates when the legacy read failed", () => {
    const entries = buildAreaCaptureEntries({
      assets: [{
        assetRef: "a1",
        kind: "dsm",
        revision: 1,
        lifecycleState: "SEALED",
        declared: { fileName: "tile.tif", captureStartedAt: "2026-10-10T00:00:00Z", captureEndedAt: "2026-10-10T01:00:00Z", submittedAt: "2026-10-11T00:00:00Z" },
      }] as never,
      legacyRows: null,
      limit: 10,
    });
    expect(entries.map((entry) => entry.key)).toEqual(["asset:a1"]);
  });

  it("appends full ids only where names actually collide", () => {
    const areas = [
      area({ workAreaId: "dup-1", name: "같은 구역" }),
      area({ workAreaId: "dup-2", name: "같은 구역" }),
      area({ workAreaId: "solo-1", name: "홑 구역" }),
    ];
    const names = disambiguatedAreaNames(areas);
    expect(names.get("dup-1")).toEqual({ label: "같은 구역 · dup-1", disambiguated: true });
    expect(names.get("dup-2")).toEqual({ label: "같은 구역 · dup-2", disambiguated: true });
    expect(names.get("solo-1")).toEqual({ label: "홑 구역", disambiguated: false });
  });

  it("appends full asset refs only where file labels actually collide", () => {
    const declared = (fileName: string, captureStartedAt: string | null) => ({
      fileName, captureStartedAt, captureEndedAt: captureStartedAt,
    });
    const assets = [
      { assetRef: "ref-aaa", revision: 1, declared: declared("same.tif", "2026-10-10T00:00:00Z") },
      { assetRef: "ref-bbb", revision: 1, declared: declared("same.tif", "2026-10-10T00:00:00Z") },
      { assetRef: "ref-ccc", revision: 1, declared: declared("same.tif", "2026-10-11T00:00:00Z") },
    ] as never;
    const headlines = disambiguatedAssetHeadlines(assets);
    expect(headlines.get("ref-aaa")).toEqual({ label: "same.tif · revision 1 · ref-aaa", disambiguated: true });
    expect(headlines.get("ref-bbb")).toEqual({ label: "same.tif · revision 1 · ref-bbb", disambiguated: true });
    expect(headlines.get("ref-ccc")).toEqual({ label: "same.tif · revision 1", disambiguated: false });
  });

  it("truncates long names for tight slots while keeping the full name for labels", () => {
    const long = "가".repeat(100);
    expect(displayName(long, 40)).toBe(`${"가".repeat(39)}…`);
    expect(displayName("짧은 이름", 40)).toBe("짧은 이름");
    expect(displayName("   ", 40)).toBe("이름을 확인할 수 없는 구역");
  });
});
