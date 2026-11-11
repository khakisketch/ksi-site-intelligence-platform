import { describe, expect, it } from "vitest";
import type { ChangeRegion } from "@/lib/core-api/types";
import {
  partitionSurveyRegionDisplay,
  unsupportedSurveyRegionsNote,
} from "@/lib/geo/survey-region-geometry";

function hullRing(lonLat: [number, number][]): GeoJSON.Polygon {
  const closed: [number, number][] = [...lonLat, lonLat[0]!];
  return { type: "Polygon", coordinates: [closed] };
}

function makeRegion(regionId: string, hull: GeoJSON.Polygon | null, reason: string | null = null): ChangeRegion {
  return {
    regionId,
    volume: { zoneId: regionId, cutM3: 10, fillM3: 2, netM3: 8, areaM2: 100, thresholdM: 0.1,
      uncertaintyM3: null, uncertaintyNote: "양쪽 epoch 검증 RMSE 없음" },
    pixelCount: 40,
    polygon: hullRing([[127, 37], [127.001, 37], [127.001, 37.001]]),
    convexHullPolygon: null,
    convexHullPolygonWgs84: hull,
    hullOvercaptureRatio: hull ? 1.2 : null,
    aoiDraftUnavailableReason: reason,
    unmeasurableRatio: 0,
  };
}

const SEOUL = hullRing([[127.0, 37.5], [127.001, 37.5], [127.001, 37.501]]);

describe("partitionSurveyRegionDisplay", () => {
  it("renders one shape per drawable region in leaflet lat/lon order", () => {
    const { supported, unsupported } = partitionSurveyRegionDisplay([
      makeRegion("r1", SEOUL),
      makeRegion("r2", SEOUL),
    ]);
    expect(supported.map((shape) => shape.regionId)).toEqual(["r1", "r2"]);
    expect(unsupported).toEqual([]);
    // GeoJSON [lon, lat] → Leaflet [lat, lon].
    expect(supported[0]!.positions[0]).toEqual([37.5, 127.0]);
  });

  it("passes the server hull-failure reason through without guessing coordinates", () => {
    const { supported, unsupported } = partitionSurveyRegionDisplay([
      makeRegion("r9", null, "hull 연산 실패: 점 2개"),
    ]);
    expect(supported).toEqual([]);
    expect(unsupported).toEqual([{ regionId: "r9", reason: "hull 연산 실패: 점 2개" }]);
  });

  it("omits out-of-mercator hulls instead of drawing them", () => {
    const polar = hullRing([[-45, 86], [-44, 86], [-44, 87]]);
    const { supported, unsupported } = partitionSurveyRegionDisplay([makeRegion("rp", polar)]);
    expect(supported).toEqual([]);
    expect(unsupported).toHaveLength(1);
    expect(unsupported[0]!.reason).toContain("배경 지도 표시 범위");
  });

  it("omits degenerate and non-polygon hulls", () => {
    const flat = { type: "Polygon", coordinates: [[[127, 37.5], [127, 37.5], [127, 37.5], [127, 37.5]]] } as unknown as GeoJSON.Polygon;
    const multi = { type: "MultiPolygon", coordinates: [] } as unknown as GeoJSON.Polygon;
    const { supported, unsupported } = partitionSurveyRegionDisplay([
      makeRegion("flat", flat),
      makeRegion("multi", multi),
    ]);
    expect(supported).toEqual([]);
    expect(unsupported.map((item) => item.regionId)).toEqual(["flat", "multi"]);
  });

  it("returns empty partitions for an empty report", () => {
    expect(partitionSurveyRegionDisplay([])).toEqual({ supported: [], unsupported: [] });
  });
});

describe("unsupportedSurveyRegionsNote", () => {
  it("is null when everything is drawable", () => {
    expect(unsupportedSurveyRegionsNote([])).toBeNull();
  });

  it("names each omitted region with its exact reason", () => {
    const note = unsupportedSurveyRegionsNote([
      { regionId: "r9", reason: "hull 연산 실패: 점 2개" },
    ]);
    expect(note).toContain("r9");
    expect(note).toContain("hull 연산 실패: 점 2개");
  });
});
