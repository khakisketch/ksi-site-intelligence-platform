import { describe, expect, it } from "vitest";

import {
  approxAreaSquareMeters,
  areaCrsVerdict,
  assignAreaMarks,
  buildAreaMap,
  formatApproxArea,
  layoutCaptureStrip,
  summarizeAreaAssets,
} from "@/app/sites/[siteId]/areas/area-summary";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";
import { summarizeAreaDsmCrs } from "@/lib/crs-match";

const square = (x: number, y: number, w: number, h = w) => ({
  type: "Polygon",
  coordinates: [[[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]],
});

function area(id: string, polygon: Record<string, unknown>, crs: string, extra: Partial<WorkArea> = {}): WorkArea {
  return {
    schemaVersion: "work-area.v1", workAreaId: id, siteId: "site-1", name: id, polygon, crs,
    status: "ACTIVE", supersedes: null, createdAt: "2026-11-01T00:00:00Z", ...extra,
  };
}

let counter = 0;
function dsm(crs: string | null, captureDate: string | null = "2026-11-04", extra: Record<string, unknown> = {}): SpatialAssetCatalogItem {
  counter += 1;
  return {
    assetRef: `ksa-v1-${String(counter).padStart(64, "0")}`, siteId: "site-1", workAreaId: "a", kind: "dsm", revision: 1,
    lifecycleState: "SEALED",
    declared: { fileName: `dsm-${counter}.tif`, captureStartedAt: null, captureEndedAt: null, captureDate },
    inspection: { state: "INSPECTION_REPORTED", outcome: "MEASURED", reason: null, raster: crs ? { observedCrsIdentifier: crs } : null },
    ...extra,
  } as unknown as SpatialAssetCatalogItem;
}

describe("approxAreaSquareMeters", () => {
  it("reads a projected metre square exactly (shoelace)", () => {
    expect(approxAreaSquareMeters(square(200000, 550000, 100, 50), "EPSG:5186")).toBeCloseTo(5000, 6);
    expect(approxAreaSquareMeters(square(300000, 4000000, 10), "EPSG:32652")).toBeCloseTo(100, 6);
  });

  it("flattens longitude/latitude at the centre latitude (about 9,870 m2 for 0.001 deg at 37N, within 1%)", () => {
    const value = approxAreaSquareMeters(square(127, 37, 0.001), "EPSG:4326")!;
    const expected = 111_194.9 * 111_194.9 * Math.cos(((37 + 0.0005) * Math.PI) / 180) * 1e-6;
    expect(Math.abs(value - expected) / expected).toBeLessThan(0.01);
    expect(value).toBeGreaterThan(9_800);
    expect(value).toBeLessThan(9_950);
  });

  it("returns null instead of guessing for holes, MultiPolygon, unreadable shapes, unknown units and zero area", () => {
    const hole = { type: "Polygon", coordinates: [square(0, 0, 100).coordinates[0], square(10, 10, 20).coordinates[0]] };
    const multi = { type: "MultiPolygon", coordinates: [square(0, 0, 100).coordinates] };
    expect(approxAreaSquareMeters(hole, "EPSG:5186")).toBeNull();
    expect(approxAreaSquareMeters(multi, "EPSG:5186")).toBeNull();
    expect(approxAreaSquareMeters({ type: "Polygon", coordinates: [[["a", 1], [2, 3], [4, 5]]] }, "EPSG:5186")).toBeNull();
    expect(approxAreaSquareMeters({}, "EPSG:5186")).toBeNull();
    expect(approxAreaSquareMeters(square(0, 0, 100), "EPSG:3857")).toBeNull();
    expect(approxAreaSquareMeters(square(0, 0, 100), "")).toBeNull();
    expect(approxAreaSquareMeters(square(127, 95, 0.001), "EPSG:4326")).toBeNull();
    expect(approxAreaSquareMeters({ type: "Polygon", coordinates: [[[0, 0], [1, 1], [2, 2], [0, 0]]] }, "EPSG:5186")).toBeNull();
    expect(approxAreaSquareMeters(null, "EPSG:5186")).toBeNull();
  });

  it("formats as a rounded approximate figure", () => {
    expect(formatApproxArea(12_483)).toBe("약 12,480 ㎡");
    expect(formatApproxArea(742.4)).toBe("약 742 ㎡");
    // 아주 작은 값을 "약 0 ㎡"로 반올림해 모르는 값처럼 보이게 하지 않는다.
    expect(formatApproxArea(0.4)).toBe("1 ㎡ 미만");
    expect(formatApproxArea(null)).toBeNull();
  });
});

describe("buildAreaMap", () => {
  const a = area("a", square(200000, 550000, 100), "EPSG:5186");
  const b = area("b", square(200200, 550000, 100), "EPSG:5186");
  const utm = area("utm", square(300000, 4000000, 100), "EPSG:32652");
  const multi = area("multi", { type: "MultiPolygon", coordinates: [square(0, 0, 10).coordinates] }, "EPSG:5186");
  const marks = (areas: WorkArea[]) => assignAreaMarks(areas.filter((x) => x.status === "ACTIVE"));

  it("puts only areas on the same coordinate plane on one map and counts the rest", () => {
    const all = [a, b, utm, multi];
    const model = buildAreaMap(all, "a", marks(all));
    expect(model.shapes.map((shape) => shape.workAreaId).sort()).toEqual(["a", "b"]);
    expect(model.planeCrs).toBe("EPSG:5186");
    expect(model.omitted).toEqual(expect.arrayContaining([
      { workAreaId: "utm", reason: "other-plane" },
      { workAreaId: "multi", reason: "unreadable" },
    ]));
    expect(model.omitted).toHaveLength(2);
  });

  it("follows the selected area's plane, and falls back to the most common plane", () => {
    const all = [a, b, utm];
    expect(buildAreaMap(all, "utm", marks(all)).shapes.map((shape) => shape.workAreaId)).toEqual(["utm"]);
    expect(buildAreaMap(all, null, marks(all)).planeCrs).toBe("EPSG:5186");
  });

  it("keeps marks and the selected flag aligned with the list, and fits inside the viewBox", () => {
    const all = [a, b];
    const model = buildAreaMap(all, "b", marks(all));
    const shapeB = model.shapes.find((shape) => shape.workAreaId === "b")!;
    expect(shapeB.selected).toBe(true);
    expect(shapeB.mark).toEqual({ ordinal: 2, swatch: 2 });
    for (const shape of model.shapes) {
      const numbers = shape.d.match(/-?\d+(\.\d+)?/g)!.map(Number);
      expect(Math.min(...numbers)).toBeGreaterThanOrEqual(0);
      expect(Math.max(...numbers)).toBeLessThanOrEqual(600);
    }
  });

  it("draws a longitude/latitude pair with the same latitude correction (wider in y than x)", () => {
    const geo = area("geo", square(127, 37, 0.001), "EPSG:4326");
    const model = buildAreaMap([geo], "geo", marks([geo]));
    const nums = model.shapes[0].d.match(/-?\d+(\.\d+)?/g)!.map(Number);
    const xs = nums.filter((_, i) => i % 2 === 0);
    const ys = nums.filter((_, i) => i % 2 === 1);
    const width = Math.max(...xs) - Math.min(...xs);
    const height = Math.max(...ys) - Math.min(...ys);
    expect(width / height).toBeGreaterThan(0.78);
    expect(width / height).toBeLessThan(0.82);
  });

  it("only plots an archived area when it is the selected one, and marks it archived", () => {
    const old = area("old", square(200400, 550000, 100), "EPSG:5186", { status: "ARCHIVED" });
    const all = [a, old];
    expect(buildAreaMap(all, "a", marks(all)).shapes.map((shape) => shape.workAreaId)).toEqual(["a"]);
    const withOld = buildAreaMap(all, "old", marks(all));
    expect(withOld.shapes.find((shape) => shape.workAreaId === "old")).toMatchObject({ archived: true, mark: null });
  });

  it("returns an empty model when nothing is readable", () => {
    const model = buildAreaMap([multi], "multi", marks([multi]));
    expect(model.shapes).toEqual([]);
    expect(model.omitted).toEqual([{ workAreaId: "multi", reason: "unreadable" }]);
  });
});

describe("assignAreaMarks", () => {
  it("numbers in list order and cycles the five category colours", () => {
    const list = Array.from({ length: 6 }, (_, i) => area(`x${i}`, square(0, 0, 1), "EPSG:5186"));
    const marks = assignAreaMarks(list);
    expect(marks.get("x0")).toEqual({ ordinal: 1, swatch: 1 });
    expect(marks.get("x4")).toEqual({ ordinal: 5, swatch: 5 });
    expect(marks.get("x5")).toEqual({ ordinal: 6, swatch: 1 });
  });
});

describe("areaCrsVerdict", () => {
  const verdict = (items: SpatialAssetCatalogItem[]) => areaCrsVerdict(summarizeAreaDsmCrs(items, false));

  it("none: no DSM, or DSM not inspected yet, reads as not-yet-known (neutral)", () => {
    expect(verdict([])).toMatchObject({ kind: "none", tone: "neutral", label: "좌표계 확인 전" });
    const pending = dsm("EPSG:5186", "2026-11-04", { inspection: { state: "PENDING", outcome: null, reason: null, raster: null } });
    expect(verdict([pending]).kind).toBe("none");
  });

  it("single: positive for an analysis CRS, neutral for one analysis does not accept", () => {
    expect(verdict([dsm("EPSG:5186"), dsm("EPSG:5186")])).toMatchObject({ kind: "single", tone: "positive", label: "같은 좌표계 · EPSG:5186" });
    expect(verdict([dsm("EPSG:32634")])).toMatchObject({ kind: "single", tone: "neutral" });
  });

  it("mixed: amber (caution), never the failure colour, and does not declare comparison impossible", () => {
    const mixed = verdict([dsm("EPSG:5186"), dsm("EPSG:32652")]);
    expect(mixed).toMatchObject({ kind: "mixed", tone: "caution", label: "좌표계 섞임" });
    expect(mixed.tone).not.toBe("warning");
    // 같은 좌표계 자료끼리는 비교할 수 있으므로 "불가"를 단정하지 않는다. 판정은 Core가 한다.
    expect(mixed.label).not.toMatch(/불가/);
  });

  it("single but only partly inspected: does not claim the whole area shares one CRS", () => {
    const partial = areaCrsVerdict(summarizeAreaDsmCrs([dsm("EPSG:5186")], false), true);
    expect(partial).toMatchObject({ kind: "single", tone: "neutral", label: "검사된 DSM은 EPSG:5186 · 일부만 확인" });
    expect(partial.label).not.toContain("같은 좌표계");
  });
});

describe("summarizeAreaAssets", () => {
  it("leaves superseded versions out and reports the newest capture date", () => {
    const summary = summarizeAreaAssets([
      dsm("EPSG:5186", "2026-09-14"),
      dsm("EPSG:5186", "2026-11-12"),
      dsm("EPSG:5186", "2026-12-30", { lifecycleState: "SUPERSEDED" }),
      dsm("EPSG:5186", null),
    ], true);
    expect(summary.count).toBe(3);
    expect(summary.captureDates).toEqual(["2026-09-14", "2026-11-12"]);
    expect(summary.latestDate).toBe("2026-11-12");
    expect(summary.truncated).toBe(true);
    expect(summary.crs.kind).toBe("single");
  });

  it("does not turn an empty page into dates", () => {
    expect(summarizeAreaAssets([], false)).toMatchObject({ count: 0, captureDates: [], latestDate: null });
  });

  it("downgrades the CRS verdict when some DSMs are not inspected, and reports the basis", () => {
    const pending = dsm("EPSG:5186", "2026-10-02", { inspection: { state: "PENDING", outcome: null, reason: null, raster: null } });
    const partial = summarizeAreaAssets([dsm("EPSG:5186", "2026-09-14"), pending], false);
    expect(partial.crsBasis).toEqual({ dsm: 2, measured: 1 });
    expect(partial.crs).toMatchObject({ kind: "single", tone: "neutral" });
    expect(partial.crs.label).toContain("일부만 확인");
    const full = summarizeAreaAssets([dsm("EPSG:5186", "2026-09-14"), dsm("EPSG:5186", "2026-10-02")], false);
    expect(full.crsBasis).toEqual({ dsm: 2, measured: 2 });
    expect(full.crs).toMatchObject({ kind: "single", tone: "positive", label: "같은 좌표계 · EPSG:5186" });
  });
});

describe("layoutCaptureStrip", () => {
  it("returns null without dates and centres a single date", () => {
    expect(layoutCaptureStrip([])).toBeNull();
    expect(layoutCaptureStrip(["2026-11-12"])!.points[0].x).toBe(150);
  });

  it("keeps at most the 8 newest dates, flags the latest, and never lets labels overlap", () => {
    const dates = Array.from({ length: 10 }, (_, i) => `2026-11-${String(i + 1).padStart(2, "0")}`);
    const strip = layoutCaptureStrip([...dates, dates[0]])!;
    expect(strip.total).toBe(10);
    expect(strip.points.map((point) => point.date)).toEqual(dates.slice(2));
    expect(strip.points[strip.points.length - 1].latest).toBe(true);
    for (let i = 1; i < strip.points.length; i += 1) {
      expect(strip.points[i].x - strip.points[i - 1].x).toBeGreaterThanOrEqual(34 - 0.2);
    }
    expect(strip.points[strip.points.length - 1].x).toBeLessThanOrEqual(278);
  });

  it("spaces by elapsed time when there is room, and names the dates for assistive tech", () => {
    const strip = layoutCaptureStrip(["2026-09-14", "2026-10-02", "2026-11-12"])!;
    const [a, b, c] = strip.points.map((point) => point.x);
    expect(b - a).toBeLessThan(c - b);
    expect(strip.spoken).toBe("9월 14일, 10월 2일, 11월 12일");
  });
});
