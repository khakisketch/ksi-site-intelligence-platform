import { describe, expect, it } from "vitest";
import { partitionWorkAreaDisplay, unsupportedAreasNote } from "@/lib/geo/display-geometry";

const polygon = { type: "Polygon", coordinates: [[
  [127.0, 37.0], [127.1, 37.0], [127.1, 37.1], [127.0, 37.0],
]] };
const ring = [[127.0, 37.0], [127.1, 37.0], [127.1, 37.1], [127.0, 37.0]];
const holed = { type: "Polygon", coordinates: [ring, ring] };
const crowded = { type: "Polygon", coordinates: [Array.from({ length: 514 }, (_, index) => [127 + index * 0.0001, 37])] };
const outOfRange = { type: "Polygon", coordinates: [[[999.0, 37.0], [999.1, 37.0], [999.1, 37.1], [999.0, 37.0]]] };

describe("work area display partition", () => {
  it("keeps supported areas drawable and reports exact omitted names with reasons", () => {
    const areas = [
      { workAreaId: "area-ok", name: "동측 구역", polygon, crs: "EPSG:4326" },
      { workAreaId: "area-crs", name: "서측 구역", polygon, crs: "EPSG:9999" },
      { workAreaId: "area-bad", name: "북측 구역", polygon: { type: "Polygon", coordinates: [] }, crs: "EPSG:4326" },
    ];
    const partitioned = partitionWorkAreaDisplay(areas);
    expect(partitioned.supported.map((shape) => shape.id)).toEqual(["area-ok"]);
    expect(partitioned.supported[0]).toMatchObject({ name: "동측 구역" });
    expect(partitioned.unsupported.map((item) => item.workAreaId)).toEqual(["area-crs", "area-bad"]);
    expect(partitioned.unsupported[0]).toMatchObject({ name: "서측 구역" });
    expect(partitioned.unsupported.every((item) => item.reason.length > 0)).toBe(true);
    const mixedNote = unsupportedAreasNote(partitioned.unsupported);
    expect(mixedNote).toContain("지도에 표시되지 않은 구역 2개");
    expect(mixedNote).toContain("서측 구역");
    expect(mixedNote).toContain("북측 구역");
  });
  it("reports nothing omitted when every area is drawable", () => {
    const partitioned = partitionWorkAreaDisplay([
      { workAreaId: "area-ok", name: "동측 구역", polygon, crs: "EPSG:4326" },
    ]);
    expect(partitioned.supported).toHaveLength(1);
    expect(partitioned.unsupported).toEqual([]);
    expect(unsupportedAreasNote(partitioned.unsupported)).toBeNull();
  });
  it("names exact non-CRS reasons when nothing is drawable, without blaming the CRS", () => {
    const partitioned = partitionWorkAreaDisplay([
      { workAreaId: "area-hole", name: "구멍 구역", polygon: holed, crs: "EPSG:4326" },
      { workAreaId: "area-many", name: "많은 점 구역", polygon: crowded, crs: "EPSG:4326" },
      { workAreaId: "area-far", name: "범위 밖 구역", polygon: outOfRange, crs: "EPSG:4326" },
    ]);
    expect(partitioned.supported).toEqual([]);
    expect(partitioned.unsupported.map((item) => item.workAreaId))
      .toEqual(["area-hole", "area-many", "area-far"]);
    expect(partitioned.unsupported.every((item) => item.reason.length > 0)).toBe(true);
    expect(partitioned.unsupported.every((item) => !item.reason.includes("좌표계"))).toBe(true);
    const note = unsupportedAreasNote(partitioned.unsupported);
    expect(note).toContain("지도에 표시되지 않은 구역 3개");
    for (const item of partitioned.unsupported) {
      expect(note).toContain(item.name);
      expect(note).toContain(item.reason);
    }
  });
  it("returns no note for an empty area list", () => {
    const partitioned = partitionWorkAreaDisplay([]);
    expect(partitioned.supported).toEqual([]);
    expect(partitioned.unsupported).toEqual([]);
    expect(unsupportedAreasNote(partitioned.unsupported)).toBeNull();
  });
});
