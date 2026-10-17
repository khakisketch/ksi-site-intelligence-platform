/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  it("routes an empty external-results state to the site's analysis record", () => {
    render(<ExternalObservationHistory siteId="site-1" items={[]} workAreaNames={new Map()} />);

    expect(screen.getByRole("link", { name: "변화 분석에서 결과 확인" }).getAttribute("href"))
      .toBe("/sites/site-1/analysis");
  });

  it("shows every relative metric, its common coverage, and its limitation as labeled compact facts", () => {
    render(<ExternalObservationHistory
      siteId="site-1"
      items={[{ reportRef, state: "AVAILABLE", result: summary }]}
      workAreaNames={new Map([["area-1", "동측 절토면"]])}
    />);

    expect(screen.getByTestId("relative-metric-cards")).toBeTruthy();
    expect(screen.getByTestId("relative-metric-cards").className).toContain("lg:hidden");
    expect(screen.getByTestId("relative-metric-table").className).toContain("lg:table");
    const compactFacts = within(screen.getByTestId("relative-metric-cards"));
    expect(compactFacts.getByText("공통 유효 영역")).toBeTruthy();
    expect(compactFacts.getByText("90% · 90 / 100 m²")).toBeTruthy();
    expect(compactFacts.getByText("불확실성")).toBeTruthy();
    expect(compactFacts.getByText("±1.2 m³")).toBeTruthy();
    expect(compactFacts.getByText("표본 기반 불확실성")).toBeTruthy();
    expect(screen.getByText(/측량·정산 정확도를 입증하거나 작업·비행 권한을 부여하지 않습니다/)).toBeTruthy();
  });

  it("keeps the comparison table available for desktop and omits relative-only claims for a single-epoch result", () => {
    const { container, rerender } = render(<ExternalObservationHistory
      siteId="site-1"
      items={[{ reportRef, state: "AVAILABLE", result: summary }]}
      workAreaNames={new Map([["area-1", "동측 절토면"]])}
    />);
    expect(screen.getByTestId("relative-metric-table")).toBeTruthy();

    const singleVolumeRef = `external-single-volume-report-${"b".repeat(32)}`;
    const single: ExternalResultSummaryView = {
      ...summary,
      kind: "EXTERNAL_SINGLE_VOLUME",
      reportRef: singleVolumeRef,
      baselineWorkOrderId: null,
      baselineCapturedFrom: null,
      baselineCapturedTo: null,
    };
    rerender(<ExternalObservationHistory
      detailMode
      siteId="site-1"
      items={[{ reportRef: singleVolumeRef, state: "AVAILABLE", result: single }]}
      workAreaNames={new Map([["area-1", "동측 절토면"]])}
    />);
    expect(container.querySelector("[data-testid='relative-metric-cards']")).toBeNull();
    expect(screen.queryByText(/측량·정산 정확도를 입증하거나 작업·비행 권한을 부여하지 않습니다/)).toBeNull();
  });

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
    expect(screen.getAllByText("절토")).toHaveLength(2);
    expect(screen.getAllByText("성토")).toHaveLength(2);
  });

  it("renders the baseline date range for a relative-volume result (unchanged behavior)", () => {
    const { container } = render(<ExternalObservationHistory
      siteId="site-1"
      items={[{ reportRef, state: "AVAILABLE", result: summary }]}
      workAreaNames={new Map([["area-1", "동측 절토면"]])}
    />);
    // MetricRow renders inside <article>; NetTrend's compatible-comparison summary
    // renders inside a separate <section> and must not be picked up here.
    const baselineLine = container.querySelector("article p.mt-1")?.textContent ?? "";
    expect(baselineLine).toContain("기준");
    expect(baselineLine).not.toContain("1970");
  });

  it("omits the baseline range instead of inventing a 1970 date for a single-volume result reached through the merged report detail route", () => {
    const singleVolumeRef = `external-single-volume-report-${"b".repeat(32)}`;
    const single: ExternalResultSummaryView = {
      ...summary,
      kind: "EXTERNAL_SINGLE_VOLUME",
      reportRef: singleVolumeRef,
      baselineWorkOrderId: null,
      baselineCapturedFrom: null,
      baselineCapturedTo: null,
    };
    const { container } = render(<ExternalObservationHistory
      detailMode
      siteId="site-1"
      items={[{ reportRef: singleVolumeRef, state: "AVAILABLE", result: single }]}
      workAreaNames={new Map([["area-1", "동측 절토면"]])}
    />);
    const baselineLine = container.querySelector("article p.mt-1")?.textContent ?? "";
    expect(baselineLine).not.toContain("1970");
    expect(baselineLine).not.toContain("기준");
    expect(baselineLine).toContain("현재");
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
