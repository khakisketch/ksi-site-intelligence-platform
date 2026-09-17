/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ExternalSiteResultSummary } from "@/components/external-results/ExternalSiteResultSummary";
import type { ExternalResultProjectionView } from "@/lib/core-api/types";

afterEach(cleanup);

const digest = (character: string) => `sha256:${character.repeat(64)}`;

function available(overrides: Partial<NonNullable<ExternalResultProjectionView["result"]>> = {}): ExternalResultProjectionView {
  return {
    state: "AVAILABLE",
    result: {
      reportRef: `external-relative-volume-report-${"a".repeat(32)}`,
      reportDigest: digest("a"),
      requestRef: `external-relative-volume-${"b".repeat(32)}`,
      requestDigest: digest("b"),
      sourceWorkOrderId: "work-baseline",
      currentWorkOrderId: "work-current",
      baselineWorkOrderId: "work-baseline",
      decisionId: "decision-1",
      decisionDigest: digest("c"),
      workAreaId: "area-east",
      zoneDefinitionDigest: digest("d"),
      crs: "EPSG:5186",
      observedCrsDigest: digest("e"),
      verticalReferenceDigest: digest("f"),
      baselineCapturedFrom: "2026-09-01T01:00:00Z",
      baselineCapturedTo: "2026-09-01T01:30:00Z",
      currentCapturedFrom: "2026-09-08T01:00:00Z",
      currentCapturedTo: "2026-09-08T01:30:00Z",
      reportedAt: "2026-09-08T03:00:00Z",
      measurementStatus: "SUCCEEDED",
      measurementReason: null,
      metrics: {
        zoneCellCount: 100,
        commonValidCellCount: 90,
        zoneAreaM2: 1_000,
        measuredAreaM2: 900,
        commonValidFraction: 0.9,
        cutM3: 13,
        fillM3: 21,
        netM3: 8,
        thresholdM: 0.1,
        uncertaintyM3: 3,
        uncertaintyNote: "독립 검사점 검증 기준",
      },
      executionPolicy: {
        policyId: "policy-1",
        version: 1,
        policyDigest: digest("a"),
        algorithmBuildDigest: digest("b"),
        configDigest: digest("c"),
        uncertaintyMethod: "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
      },
      reviewRef: null,
      reviewDigest: null,
      reviewedAt: null,
      proposalCount: 0,
      approvedProposalCount: 0,
      ...overrides,
    },
  };
}

describe("ExternalSiteResultSummary", () => {
  it("shows a retained successful result with its resolved work-area name and exact work-report link", () => {
    render(<ExternalSiteResultSummary externalResult={available()} workAreaName="동측 절성토 구역" />);

    expect(screen.getByRole("heading", { name: "외부 관측 비교 결과" })).toBeTruthy();
    expect(screen.getByText(/작업구역\s+동측 절성토 구역/)).toBeTruthy();
    expect(screen.getByText("절토")).toBeTruthy();
    expect(screen.getByText("13 m³")).toBeTruthy();
    expect(screen.getByText("성토")).toBeTruthy();
    expect(screen.getByText("21 m³")).toBeTruthy();
    expect(screen.getByText("순변화")).toBeTruthy();
    expect(screen.getByText("+8 m³")).toBeTruthy();
    expect(screen.getByText("절토는 깎아낸 양, 성토는 채워 넣은 양입니다.")).toBeTruthy();
    expect(screen.getByText(/측정 영역 900 m²/)).toBeTruthy();
    expect(screen.getByText(/불확실성 ±3 m³/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "비교 결과 보기" }).getAttribute("href")).toBe(
      `/field/work-orders/work-current?reportRef=external-relative-volume-report-${"a".repeat(32)}#external-result`,
    );
  });

  it("renders the baseline date range for a relative-volume result (unchanged behavior)", () => {
    const { container } = render(<ExternalSiteResultSummary externalResult={available()} workAreaName="동측 절성토 구역" />);
    const copy = container.querySelector("h3 + p")?.textContent ?? "";
    expect(copy).toContain("와");
    expect(copy).not.toContain("1970");
  });

  it("summarizes a single-volume result as a pile volume at one capture time, without comparison wording or review actions", () => {
    const single = available({
      kind: "EXTERNAL_SINGLE_VOLUME",
      reportRef: `external-single-volume-report-${"a".repeat(32)}`,
      baselineWorkOrderId: null,
      baselineCapturedFrom: null,
      baselineCapturedTo: null,
      metrics: {
        zoneCellCount: 100,
        commonValidCellCount: 95,
        zoneAreaM2: 1_000,
        measuredAreaM2: 950,
        commonValidFraction: 0.95,
        cutM3: 1,
        fillM3: 1234.5,
        netM3: 1233.5,
        thresholdM: 0.1,
        uncertaintyM3: 12.25,
        uncertaintyNote: "경계 기저면 기준",
        baseRoughnessM: 0.1,
        boundaryCellCount: 40,
        boundarySampleCount: 38,
        boundaryValidFraction: 0.9,
      },
    });
    const { container } = render(<ExternalSiteResultSummary externalResult={single} workAreaName="야적장 1" />);
    const text = container.textContent ?? "";
    expect(screen.getByRole("heading", { name: "단일 시점 체적 결과" })).toBeTruthy();
    expect(screen.getByText("단일 시점 체적")).toBeTruthy();
    expect(screen.getByText(/작업구역\s+야적장 1/)).toBeTruthy();
    expect(screen.getByText("체적")).toBeTruthy();
    expect(screen.getByText("1,234.5 m³")).toBeTruthy();
    expect(screen.getByText("±12.25 m³")).toBeTruthy();
    expect(screen.getByText("0.10 m")).toBeTruthy();
    expect(screen.getByText("90%")).toBeTruthy();
    expect(text).toContain("촬영 2026. 9. 8.");
    expect(text).not.toContain("1970");
    expect(text).not.toContain("비교");
    expect(text).not.toContain("순변화");
    expect(text).not.toContain("+1,233.5");
    expect(screen.getByText("단일 시점 결과 검토는 준비 중입니다.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "체적 측정 기록 보기" }).getAttribute("href")).toBe(
      "/field/work-orders/work-current#external-volume",
    );
  });

  it("shows an unestimated single-volume uncertainty as not estimated", () => {
    const base = available().result!;
    const single = available({
      kind: "EXTERNAL_SINGLE_VOLUME",
      baselineWorkOrderId: null,
      baselineCapturedFrom: null,
      baselineCapturedTo: null,
      metrics: { ...base.metrics!, uncertaintyM3: null, baseRoughnessM: 0.2, boundaryValidFraction: 0.8 },
    });
    render(<ExternalSiteResultSummary externalResult={single} compact />);
    expect(screen.getByText("불확도 미산정")).toBeTruthy();
    expect(screen.getByText("21 m³")).toBeTruthy();
  });

  it("keeps a retained non-success result distinct and never presents aggregate values as a result", () => {
    render(
      <ExternalSiteResultSummary
        externalResult={available({ measurementStatus: "FAILED", measurementReason: "INSUFFICIENT_COVERAGE" })}
      />,
    );

    expect(screen.getByText(/비교를 완료하지 못했습니다\./)).toBeTruthy();
    expect(screen.queryByText("13 m³")).toBeNull();
    expect(screen.queryByText("8 m³")).toBeNull();
    expect(screen.getByRole("link", { name: "비교 결과 보기" })).toBeTruthy();
  });

  it.each([
    ["NOT_CONFIGURED", "외부 관측 결과 연결이 아직 설정되지 않았습니다."],
    ["NO_RESULT", "외부 관측 결과가 아직 없습니다."],
    ["HISTORICAL_SOURCE_UNAVAILABLE", "외부 관측 결과의 보관 근거를 현재 확인할 수 없습니다."],
  ] as const)("keeps %s separate from a zero or failed result", (state, message) => {
    render(<ExternalSiteResultSummary externalResult={{ state }} />);

    expect(screen.getByText(message)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "비교 결과 보기" })).toBeNull();
  });
});
