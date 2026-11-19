import { describe, expect, it } from "vitest";

import { areaRingOf, coverageOfArea, fileFootprintWgs84 } from "@/lib/geo/geotiff-footprint";
import { toDisplayPolygonWgs84 } from "@/lib/geo/display-geometry";
import type { GeoTiffRawHeader } from "@/lib/geo/geotiff-header";

// EPSG:5186 중부원점 근처 1km 사각형(서울 인근). 값은 합성이다.
function header(overrides: Partial<GeoTiffRawHeader> = {}): GeoTiffRawHeader {
  return {
    width: 100, height: 100, samplesPerPixel: 1, bitsPerSample: 32, sampleFormat: 3,
    geoKeys: { ProjectedCSTypeGeoKey: 5186 }, software: null, dateTime: null, pixelSize: [10, 10],
    boundingBox: [200000, 550000, 201000, 551000],
    ...overrides,
  };
}

function polygonAround(footprintCenter: readonly [number, number], halfLon: number, halfLat: number): Record<string, unknown> {
  const [lon, lat] = footprintCenter;
  return {
    type: "Polygon",
    coordinates: [[[lon - halfLon, lat - halfLat], [lon + halfLon, lat - halfLat], [lon + halfLon, lat + halfLat], [lon - halfLon, lat + halfLat], [lon - halfLon, lat - halfLat]]],
  };
}

describe("fileFootprintWgs84", () => {
  it("converts the four corners into WGS84 lon/lat", () => {
    const footprint = fileFootprintWgs84(header());
    expect(footprint?.crs).toBe("EPSG:5186");
    expect(footprint?.ring).toHaveLength(4);
    for (const [lon, lat] of footprint!.ring) {
      expect(lon).toBeGreaterThan(126);
      expect(lon).toBeLessThan(128);
      expect(lat).toBeGreaterThan(36);
      expect(lat).toBeLessThan(40);
    }
  });

  it("returns null instead of guessing when the box or CRS is unknown", () => {
    expect(fileFootprintWgs84(header({ boundingBox: null }))).toBeNull();
    expect(fileFootprintWgs84(header({ boundingBox: undefined }))).toBeNull();
    expect(fileFootprintWgs84(header({ boundingBox: [5, 5, 1, 9] }))).toBeNull();
    expect(fileFootprintWgs84(header({ geoKeys: null }))).toBeNull();
    expect(fileFootprintWgs84(header({ geoKeys: { ProjectedCSTypeGeoKey: 5174 } }))).toBeNull();
  });

  it("draws a WGS84 UTM file (Pix4D·DJI Terra default export) in the right place", () => {
    // 왼쪽 아래 모서리의 기대값은 pyproj(EPSG:4326 → EPSG:32652)로 따로 계산했다.
    const footprint = fileFootprintWgs84(header({
      geoKeys: { ProjectedCSTypeGeoKey: 32652 },
      boundingBox: [321424.286, 4159640.641, 322424.286, 4160640.641],
    }));
    expect(footprint?.crs).toBe("EPSG:32652");
    const [lon, lat] = footprint!.ring[0]!;
    expect(lon).toBeCloseTo(126.978, 5);
    expect(lat).toBeCloseTo(37.5665, 5);
  });
});

describe("coverageOfArea", () => {
  const footprint = fileFootprintWgs84(header())!;
  const lon = footprint.ring.reduce((sum, [x]) => sum + x, 0) / 4;
  const lat = footprint.ring.reduce((sum, [, y]) => sum + y, 0) / 4;

  it("covers when the whole area sits inside the file extent", () => {
    expect(coverageOfArea(footprint, polygonAround([lon, lat], 0.001, 0.001))).toBe("covers");
  });

  it("is partial when the area only overlaps the extent", () => {
    expect(coverageOfArea(footprint, polygonAround([lon + 0.0055, lat], 0.003, 0.002))).toBe("partial");
  });

  it("is partial when the file lies wholly inside a larger area", () => {
    expect(coverageOfArea(footprint, polygonAround([lon, lat], 0.05, 0.05))).toBe("partial");
  });

  it("is partial when the edges cross without any vertex inside the other shape", () => {
    // 가로로 긴 구역과 세로로 긴 파일 범위가 십자로 겹친다.
    expect(coverageOfArea(footprint, polygonAround([lon, lat], 0.05, 0.0005))).toBe("partial");
  });

  it("is disjoint when the area is elsewhere", () => {
    expect(coverageOfArea(footprint, polygonAround([lon + 1, lat + 1], 0.001, 0.001))).toBe("disjoint");
  });

  it("returns null when the stored polygon is not readable", () => {
    expect(coverageOfArea(footprint, { type: "Polygon", coordinates: [[[1, 2], ["x", 3]]] })).toBeNull();
    expect(coverageOfArea(footprint, null)).toBeNull();
  });
});

describe("toDisplayPolygonWgs84", () => {
  it("aligns a native EPSG:32635 work area with the public DJI Terra EPSG:4326 result", () => {
    // Sofia/SAP sunflower dataset, pinned 2026-11-19. The ring is the real
    // local QA work area around the published result.tif bounds (plus 1 m).
    const workArea = {
      type: "Polygon",
      coordinates: [[
        [215843.76323177927, 4727946.649519713],
        [216109.17223298742, 4727946.649519713],
        [216109.17223298742, 4728217.935922389],
        [215843.76323177927, 4728217.935922389],
        [215843.76323177927, 4727946.649519713],
      ]],
    };
    const displayed = toDisplayPolygonWgs84(workArea, "EPSG:32635");
    const normalizedRing = areaRingOf(displayed)!;
    const publicOrtho = fileFootprintWgs84(header({
      width: 3628,
      height: 3716,
      samplesPerPixel: 4,
      bitsPerSample: 8,
      sampleFormat: 1,
      geoKeys: { GeographicTypeGeoKey: 4326 },
      boundingBox: [
        23.53348665924774,
        42.653962196501155 - 8.499409176465633e-07 * 3716,
        23.53348665924774 + 8.499409176465633e-07 * 3628,
        42.653962196501155,
      ],
    }))!;

    expect(displayed?.type).toBe("Polygon");
    expect(normalizedRing[0]![0]).toBeCloseTo(23.53348, 4);
    expect(normalizedRing[0]![1]).toBeCloseTo(42.65153, 4);
    expect(coverageOfArea(publicOrtho, displayed)).toBe("partial");
    expect(workArea.coordinates[0]![0]).toEqual([215843.76323177927, 4727946.649519713]);
  });

  it("keeps WGS84 rings and returns no display geometry for unknown or invalid projections", () => {
    const geographic = { type: "Polygon", coordinates: [[[127, 37], [127.1, 37], [127.1, 37.1], [127, 37.1], [127, 37]]] };
    expect(toDisplayPolygonWgs84(geographic, "EPSG:4326")).toEqual(geographic);
    expect(toDisplayPolygonWgs84(geographic, "EPSG:999999")).toBeNull();
    expect(toDisplayPolygonWgs84({ type: "MultiPolygon", coordinates: [] }, "EPSG:4326")).toBeNull();
  });
});

describe("areaRingOf", () => {
  it("drops the closing vertex and keeps lon/lat order", () => {
    const ring = areaRingOf({ type: "Polygon", coordinates: [[[127, 37], [127.1, 37], [127.1, 37.1], [127, 37]]] });
    expect(ring).toEqual([[127, 37], [127.1, 37], [127.1, 37.1]]);
  });
});
