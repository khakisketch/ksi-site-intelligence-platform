import { describe, expect, it } from "vitest";

import type { EquipmentStateItem } from "@/lib/core-api/types";
import { formatObservationAge, summarizeWorldFreshness } from "@/lib/world-status";

function item(
  entityId: string,
  observedAt: string,
  recordedAt: string,
  reportedBy: string | null,
): EquipmentStateItem {
  return {
    state: {
      entityId,
      observedAt,
      siteFrame: "EPSG:5186",
      position: [0, 0, 0],
      positionCovariance: [1, 0, 0, 0, 1, 0, 0, 0, 1],
      velocity: [0, 0, 0],
      velocityCovariance: [1, 0, 0, 0, 1, 0, 0, 0, 1],
      headingDeg: null,
      sourceClass: "Person",
    },
    reportedBy,
    recordedAt,
    positionUncertaintyM: 1.7,
  };
}

describe("World freshness", () => {
  it("summarizes actual observation and Core receipt timestamps without online inference", () => {
    const now = Date.parse("2026-08-14T00:00:00Z");
    const summary = summarizeWorldFreshness(
      [
        item("a", "2026-08-13T23:55:00Z", "2026-08-13T23:55:02Z", "edge-1"),
        item("b", "2026-08-13T23:58:00Z", "2026-08-13T23:58:05Z", "edge-1"),
        item("c", "2026-08-14T00:00:01Z", "2026-08-13T23:59:59Z", "edge-2"),
      ],
      now,
    );

    expect(summary.latestObservedAt).toBe("2026-08-14T00:00:01Z");
    expect(summary.oldestObservedAt).toBe("2026-08-13T23:55:00Z");
    expect(summary.latestRecordedAt).toBe("2026-08-13T23:59:59Z");
    expect(summary.clockSkewCount).toBe(1);
    expect(summary.reportingDeviceCount).toBe(2);
  });

  it("reports elapsed age without inventing a freshness threshold", () => {
    const now = Date.parse("2026-08-14T00:00:00Z");
    expect(formatObservationAge("2026-08-13T23:59:40Z", now)).toBe("20초 전");
    expect(formatObservationAge("2026-08-13T22:00:00Z", now)).toBe("2시간 전");
    expect(formatObservationAge("2026-08-14T00:00:01Z", now)).toContain("장비 시계");
  });

  it("returns explicit empty values for a layer with no observations", () => {
    expect(summarizeWorldFreshness([], Date.now())).toEqual({
      latestObservedAt: null,
      latestRecordedAt: null,
      oldestObservedAt: null,
      clockSkewCount: 0,
      reportingDeviceCount: 0,
    });
  });
});
