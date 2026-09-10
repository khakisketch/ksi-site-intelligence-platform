/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExternalObservationHistory } from "@/app/sites/[siteId]/observations/ExternalObservationHistory";
import type { ExternalResultSummaryView } from "@/lib/core-api/types";

const reportRef = `external-relative-volume-report-${"a".repeat(32)}`;
const summary: ExternalResultSummaryView = {
  reportRef,
  reportDigest: "sha256:report",
  requestRef: "request-1",
  requestDigest: "sha256:request",
  sourceWorkOrderId: "baseline-1",
  currentWorkOrderId: "work-1",
  baselineWorkOrderId: "baseline-1",
  decisionId: "decision-1",
  decisionDigest: "sha256:decision",
  workAreaId: "area-1",
  zoneDefinitionDigest: "sha256:zone",
  crs: "EPSG:5186",
  observedCrsDigest: "sha256:crs",
  verticalReferenceDigest: "sha256:vertical",
  baselineCapturedFrom: "2026-09-01T00:00:00Z",
  baselineCapturedTo: "2026-09-01T01:00:00Z",
  currentCapturedFrom: "2026-09-09T00:00:00Z",
  currentCapturedTo: "2026-09-09T01:00:00Z",
  reportedAt: "2026-09-09T02:00:00Z",
  measurementStatus: "SUCCEEDED",
  measurementReason: null,
  metrics: {
    zoneCellCount: 100,
    commonValidCellCount: 90,
    zoneAreaM2: 100,
    measuredAreaM2: 90,
    commonValidFraction: 0.9,
    cutM3: 20,
    fillM3: 30,
    netM3: 10,
    thresholdM: 0.1,
    uncertaintyM3: 1.2,
    uncertaintyNote: "표본 기반 불확실성",
  },
  executionPolicy: {
    policyId: "policy-1",
    version: 1,
    policyDigest: "sha256:policy",
    algorithmBuildDigest: "sha256:build",
    configDigest: "sha256:config",
    uncertaintyMethod: "RSS",
  },
  reviewRef: "review-1",
  reviewDigest: "sha256:review",
  reviewedAt: "2026-09-09T03:00:00Z",
  proposalCount: 0,
  approvedProposalCount: 0,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("외부 관측 이력 상세", () => {
  it("does not link an exact detail view to itself and keeps its work-management action", () => {
    render(<ExternalObservationHistory
      detailMode
      siteId="site-1"
      items={[{ reportRef, state: "AVAILABLE", result: summary }]}
      workAreaNames={new Map([["area-1", "동측 절토면"]])}
    />);

    expect(screen.getByRole("link", { name: "작업 관리" }).getAttribute("href")).toBe("/field/work-orders/work-1");
    expect(screen.getByRole("link", { name: "이 범위로 새 관측" }).getAttribute("href")).toBe(
      `/sites/site-1/observations/new?repeatReportRef=${reportRef}`,
    );
    expect(screen.queryByRole("link", { name: "상세 보기" })).toBeNull();
    expect(screen.getByText("절토")).toBeTruthy();
    expect(screen.getByText("성토")).toBeTruthy();
  });

  it("offers the exact authenticated report URL when clipboard copying fails", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("clipboard unavailable")) },
    });
    render(<ExternalObservationHistory
      siteId="site-1"
      items={[{ reportRef, state: "AVAILABLE", result: summary }]}
      workAreaNames={new Map([["area-1", "동측 절토면"]])}
    />);

    fireEvent.click(screen.getByRole("button", { name: "결과 주소 복사" }));
    await waitFor(() => expect(screen.getByLabelText("복사할 결과 주소")).toBeTruthy());
    expect(screen.getByLabelText("복사할 결과 주소").getAttribute("value")).toBe(
      `${window.location.origin}/sites/site-1/observations/${reportRef}`,
    );
  });
});
