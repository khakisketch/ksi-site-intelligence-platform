// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/survey/SurveyRegionMapInner", () => ({
  SurveyRegionMapInner: ({ shapes, onSelect }: {
    shapes: { regionId: string }[]; selectedId: string | null; onSelect: (id: string | null) => void;
  }) => (
    <div data-testid="map-inner" data-count={shapes.length}>
      {shapes.map((shape) => (
        <button key={shape.regionId} type="button" onClick={() => onSelect(shape.regionId)}>
          {shape.regionId}
        </button>
      ))}
    </div>
  ),
}));

import { SurveyRegionMap } from "@/components/survey/SurveyRegionMap";
import type { ChangeRegion, ChangeRegionSetReport } from "@/lib/core-api/types";

function hullRing(lonLat: [number, number][]): GeoJSON.Polygon {
  const closed: [number, number][] = [...lonLat, lonLat[0]!];
  return { type: "Polygon", coordinates: [closed] };
}

function makeRegion(regionId: string): ChangeRegion {
  return {
    regionId,
    volume: { zoneId: regionId, cutM3: 10, fillM3: 2, netM3: 8, areaM2: 100, thresholdM: 0.1,
      uncertaintyM3: null, uncertaintyNote: "양쪽 epoch 검증 RMSE 없음" },
    pixelCount: 40,
    polygon: hullRing([[127, 37], [127.001, 37], [127.001, 37.001]]),
    convexHullPolygon: null,
    convexHullPolygonWgs84: hullRing([[127.0, 37.5], [127.001, 37.5], [127.001, 37.501]]),
    hullOvercaptureRatio: 1.2,
    aoiDraftUnavailableReason: null,
    unmeasurableRatio: 0,
  };
}

function makeReport(regions: ChangeRegion[], filteredRegionCount = 0): ChangeRegionSetReport {
  return {
    schemaVersion: "v1",
    changeRegionSetId: "crs-1",
    designConformanceId: "survey:run-7",
    diffRasterId: "diff-1",
    crs: "EPSG:5186",
    thresholdM: 0.1,
    extractionPolicy: { schemaVersion: "v1", policyVersion: "survey-extraction-policy-v1",
      minRegionAreaM2: 25, connectivity: 8 },
    regions,
    filteredRegionCount,
    unmeasurableCellRatio: 0,
    unmeasurableAreaM2: 0,
    totalCellCount: 100,
    computedAt: "2026-11-11T00:00:00Z",
  };
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("SurveyRegionMap", () => {
  it("renders one polygon per drawable region", async () => {
    render(<SurveyRegionMap report={makeReport([makeRegion("r1"), makeRegion("r2")])} selectedId={null} onSelect={() => {}} />);
    const inner = await screen.findByTestId("map-inner");
    expect(inner.getAttribute("data-count")).toBe("2");
  });

  it("binds polygon click to selection", async () => {
    const onSelect = vi.fn();
    render(<SurveyRegionMap report={makeReport([makeRegion("r1"), makeRegion("r2")])} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(await screen.findByRole("button", { name: "r2" }));
    expect(onSelect).toHaveBeenCalledWith("r2");
  });

  it("shows the empty state when no regions were extracted", async () => {
    render(<SurveyRegionMap report={makeReport([])} selectedId={null} onSelect={() => {}} />);
    expect(await screen.findByText(/후보 구역이 없습니다/)).toBeTruthy();
    expect(screen.queryByTestId("map-inner")).toBeNull();
  });

  it("shows the limited state when candidates were filtered by min area", async () => {
    render(<SurveyRegionMap report={makeReport([makeRegion("r1")], 3)} selectedId={null} onSelect={() => {}} />);
    await screen.findByTestId("map-inner");
    const notes = await screen.findAllByRole("note");
    expect(notes.some((note) => note.textContent?.includes("제외된 후보 3개"))).toBe(true);
  });

  it("names hull-unavailable regions instead of drawing them", async () => {
    const failed: ChangeRegion = { ...makeRegion("r9"), convexHullPolygonWgs84: null,
      hullOvercaptureRatio: null, aoiDraftUnavailableReason: "hull 연산 실패" };
    render(<SurveyRegionMap report={makeReport([makeRegion("r1"), failed])} selectedId={null} onSelect={() => {}} />);
    const inner = await screen.findByTestId("map-inner");
    expect(inner.getAttribute("data-count")).toBe("1");
    const notes = await screen.findAllByRole("note");
    expect(notes.some((note) => note.textContent?.includes("r9")
      && note.textContent?.includes("hull 연산 실패"))).toBe(true);
  });
});
