import { describe, expect, it } from "vitest";

import { copilotCitationHref } from "../src/app/field/copilot-citation";
import type { CopilotCitationView } from "../src/lib/core-api/types";

function citation(sourcePath: string): CopilotCitationView {
  return {
    citationId: "citation-1",
    objectType: "test",
    objectId: "object-1",
    label: "근거",
    sourcePath,
    capturedFrom: null,
    capturedTo: null,
    modelVersion: null,
    geometryRef: null,
    uncertaintySummary: null,
  };
}

describe("copilotCitationHref", () => {
  it.each([
    ["/v1/sites/site-1", "/sites/site-1"],
    ["/v1/missions/mission:1/volume-changes", "/missions/mission%3A1"],
    ["/v1/events/event-1", "/events/event-1"],
    [
      "/v1/observation-work-orders/work-order-1",
      "/field/work-orders/work-order-1",
    ],
  ])("maps a supported Core path", (sourcePath, expected) => {
    expect(copilotCitationHref(citation(sourcePath))).toBe(expected);
  });

  it.each([
    "/v1/unknown/object-1",
    "/v1/sites/../admin",
    "/v1/sites/site%2Fescape",
    "https://example.com/v1/sites/site-1",
  ])("does not turn an untrusted source into a link", (sourcePath) => {
    expect(copilotCitationHref(citation(sourcePath))).toBeNull();
  });
});

it("maps a site observation citation to the exact observation page", () => {
  expect(
    copilotCitationHref({
      citationId: "site-observation:r-1",
      objectType: "site-observation",
      objectId: "r-1",
      label: "현장 관측 결과 보기",
      sourcePath: "/v1/sites/site-a/observations/external-relative-volume-report-abc",
      capturedFrom: null,
      capturedTo: null,
      modelVersion: null,
      geometryRef: null,
      uncertaintySummary: null,
    }),
  ).toBe("/sites/site-a/observations/external-relative-volume-report-abc");
});

