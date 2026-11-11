// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { describeSurveyReference, SurveyRegionInspector } from "@/components/survey/SurveyRegionInspector";
import type { ChangeRegion, ChangeRegionSetReport } from "@/lib/core-api/types";

function hullRing(lonLat: [number, number][]): GeoJSON.Polygon {
  const closed: [number, number][] = [...lonLat, lonLat[0]!];
  return { type: "Polygon", coordinates: [closed] };
}

function makeRegion(regionId: string): ChangeRegion {
  return {
    regionId,
    volume: { zoneId: regionId, cutM3: 10.5, fillM3: 2.25, netM3: 8.25, areaM2: 100, thresholdM: 0.1,
      uncertaintyM3: null, uncertaintyNote: "양쪽 epoch 검증 RMSE 없음" },
    pixelCount: 40,
    polygon: hullRing([[127, 37], [127.001, 37], [127.001, 37.001]]),
    convexHullPolygon: null,
    convexHullPolygonWgs84: hullRing([[127.0, 37.5], [127.001, 37.5], [127.001, 37.501]]),
    hullOvercaptureRatio: 1.2,
    aoiDraftUnavailableReason: null,
    unmeasurableRatio: 0.05,
  };
}

function makeReport(designConformanceId: string): ChangeRegionSetReport {
  return {
    schemaVersion: "v1",
    changeRegionSetId: "crs-1",
    designConformanceId,
    diffRasterId: "diff-1",
    crs: "EPSG:5186",
    thresholdM: 0.1,
    extractionPolicy: { schemaVersion: "v1", policyVersion: "survey-extraction-policy-v1",
      minRegionAreaM2: 25, connectivity: 8 },
    regions: [makeRegion("r1"), makeRegion("r2")],
    filteredRegionCount: 0,
    unmeasurableCellRatio: 0,
    unmeasurableAreaM2: 0,
    totalCellCount: 100,
    computedAt: "2026-11-11T00:00:00Z",
  };
}

afterEach(() => { cleanup(); });

describe("describeSurveyReference", () => {
  it("treats the survey: prefix as a survey-run id, never a design report", () => {
    expect(describeSurveyReference("survey:run-7")).toEqual({ kind: "survey-run", id: "run-7" });
  });

  it("keeps non-prefixed ids on the design-conformance path", () => {
    expect(describeSurveyReference("dcr-123")).toEqual({ kind: "design-conformance", id: "dcr-123" });
  });
});

describe("SurveyRegionInspector", () => {
  it("shows the selected region metrics with the verbatim policy version", async () => {
    render(<SurveyRegionInspector report={makeReport("survey:run-7")} selectedId="r1" />);
    expect(await screen.findByText("r1")).toBeTruthy();
    expect(screen.getByText(/전수측량 실행 run-7/)).toBeTruthy();
    expect(screen.getByText(/survey-extraction-policy-v1/)).toBeTruthy();
    const section = screen.getByLabelText("후보 구역 지표");
    expect(section.textContent).toContain("10.5");
    // formatNumberKo SSOT: 소수 1자리 반올림 표기.
    expect(section.textContent).toContain("8.3");
    // 표기 통일: 측정불가율 % 기호, 껍질 비율 배율 단위와 눈금 안내.
    expect(section.textContent).toContain("5%");
    expect(section.textContent).toContain("1.2배");
    expect(section.textContent).toContain("1.0 이상입니다");
  });

  it("prompts for selection when nothing is selected", async () => {
    render(<SurveyRegionInspector report={makeReport("survey:run-7")} selectedId={null} />);
    expect(await screen.findByText(/지도에서 후보 구역을 선택하면/)).toBeTruthy();
  });

  it("reports an unknown selection instead of showing another region", async () => {
    render(<SurveyRegionInspector report={makeReport("survey:run-7")} selectedId="r9" />);
    expect(await screen.findByText(/이 계산에 없습니다/)).toBeTruthy();
  });
});
