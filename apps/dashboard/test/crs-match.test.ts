import { describe, expect, it } from "vitest";

import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import { assignCrsSwatches, matchFileToArea, normalizeCrs, summarizeAreaDsmCrs, type AreaDsmCrs } from "@/lib/crs-match";

function asset(overrides: {
  kind?: SpatialAssetCatalogItem["kind"];
  crs?: string | null;
  outcome?: "MEASURED" | "REJECTED" | null;
  lifecycleState?: SpatialAssetCatalogItem["lifecycleState"];
  captureDate?: string | null;
  captureStartedAt?: string | null;
}): SpatialAssetCatalogItem {
  const crs = overrides.crs === undefined ? "EPSG:5186" : overrides.crs;
  return {
    kind: overrides.kind ?? "dsm",
    lifecycleState: overrides.lifecycleState ?? "SEALED",
    declared: { captureDate: overrides.captureDate ?? null, captureStartedAt: overrides.captureStartedAt ?? null },
    inspection: {
      outcome: overrides.outcome === undefined ? "MEASURED" : overrides.outcome,
      raster: crs ? { observedCrsIdentifier: crs } : null,
    },
  } as unknown as SpatialAssetCatalogItem;
}

const area = (groups: Array<[string, number]>, truncated = false): AreaDsmCrs => ({
  groups: groups.map(([crs, count]) => ({ crs, count, firstDate: null, lastDate: null })),
  total: groups.reduce((sum, [, count]) => sum + count, 0),
  truncated,
});

describe("summarizeAreaDsmCrs", () => {
  it("groups sealed, measured DSMs by observed CRS, most frequent first", () => {
    const summary = summarizeAreaDsmCrs(
      [
        asset({ crs: "EPSG:32652", captureDate: "2026-11-18" }),
        asset({ crs: "EPSG:5186", captureDate: "2026-10-02" }),
        asset({ crs: "EPSG:5186", captureDate: "2026-11-04" }),
        asset({ crs: "EPSG:5186", captureDate: "2026-10-20" }),
      ],
      false,
    );
    expect(summary).toEqual({
      groups: [
        { crs: "EPSG:5186", count: 3, firstDate: "2026-10-02", lastDate: "2026-11-04" },
        { crs: "EPSG:32652", count: 1, firstDate: "2026-11-18", lastDate: "2026-11-18" },
      ],
      total: 4,
      truncated: false,
    });
  });

  it("ignores other kinds, superseded versions, and files without a measured CRS", () => {
    const summary = summarizeAreaDsmCrs(
      [
        asset({ kind: "ortho" }),
        asset({ lifecycleState: "SUPERSEDED" }),
        asset({ outcome: "REJECTED" }),
        asset({ outcome: null }),
        asset({ crs: null }),
        asset({ crs: "EPSG:5186" }),
      ],
      true,
    );
    expect(summary.total).toBe(1);
    expect(summary.groups.map((group) => group.crs)).toEqual(["EPSG:5186"]);
    expect(summary.truncated).toBe(true);
  });

  it("derives the capture day from a timestamp in Korean calendar time and tolerates unknown dates", () => {
    const summary = summarizeAreaDsmCrs(
      [asset({ captureStartedAt: "2026-11-17T16:30:00Z" }), asset({ captureDate: null, captureStartedAt: null })],
      false,
    );
    expect(summary.groups[0]).toMatchObject({ count: 2, firstDate: "2026-11-18", lastDate: "2026-11-18" });
  });
});

describe("matchFileToArea", () => {
  it("says nothing when the file CRS or the area is unknown", () => {
    expect(matchFileToArea(null, area([["EPSG:5186", 1]]))).toBeNull();
    expect(matchFileToArea("  ", area([["EPSG:5186", 1]]))).toBeNull();
    expect(matchFileToArea("EPSG:5186", null)).toBeNull();
    expect(matchFileToArea("EPSG:5186", undefined)).toBeNull();
  });

  it.each([
    ["same CRS for every existing DSM", "epsg:5186", [["EPSG:5186", 3]], "same", 3],
    ["no existing DSM in an analysis CRS", "EPSG:5186", [], "first", 0],
    ["a different analysis CRS", "EPSG:32652", [["EPSG:5186", 3]], "different", 0],
    ["a mix of same and different", "EPSG:5186", [["EPSG:5186", 1], ["EPSG:32652", 2]], "mixed", 1],
  ] as const)("%s", (_name, file, groups, verdict, sameCount) => {
    const match = matchFileToArea(file, area(groups.map(([crs, count]) => [crs, count] as [string, number])));
    expect(match?.verdict).toBe(verdict);
    expect(match?.sameCount).toBe(sameCount);
    expect(match?.fileCrs).toBe(normalizeCrs(file));
  });

  it("never calls a CRS outside analysis support comparable, even if every existing DSM shares it", () => {
    // Sofia sample data: both dates in EPSG:32634, which the analysis does not accept.
    const match = matchFileToArea("EPSG:32634", area([["EPSG:32634", 2]]));
    expect(match?.verdict).toBe("not-analysis");
    expect(matchFileToArea("EPSG:5174", area([]))?.verdict).toBe("not-analysis");
  });

  it("keeps the truncation flag so the screen can say it looked at recent files only", () => {
    expect(matchFileToArea("EPSG:5186", area([["EPSG:5186", 50]], true))?.truncated).toBe(true);
  });
});

describe("assignCrsSwatches", () => {
  it("gives each CRS one stable color number in first-seen order and wraps after five", () => {
    const map = assignCrsSwatches(["A", "B", "A", "C", "D", "E", "F"]);
    expect([...map.entries()]).toEqual([["A", 1], ["B", 2], ["C", 3], ["D", 4], ["E", 5], ["F", 1]]);
  });
});
