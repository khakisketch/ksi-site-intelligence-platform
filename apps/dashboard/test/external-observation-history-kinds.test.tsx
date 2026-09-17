/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  site: vi.fn(),
  areas: vi.fn(),
  history: vi.fn(),
  relativeHistory: vi.fn(),
  projection: vi.fn(),
  detail: vi.fn(),
  pair: vi.fn(),
  operations: vi.fn(),
  share: vi.fn(),
}));

vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({
  listSiteExternalVolumeHistory: mocked.history,
  listSiteExternalRelativeVolumeHistory: mocked.relativeHistory,
  getSiteExternalRelativeVolumeReport: mocked.projection,
  getExternalRelativeVolumeReport: mocked.detail,
}));
vi.mock("@/lib/core-api/external-report-display", () => ({ resolveExactReportSafeDerivativePair: mocked.pair }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ getObservationWorkOrderOperations: mocked.operations }));
vi.mock("@/components/external-results/TeamReportShare", () => ({
  TeamReportShare: (props: unknown) => { mocked.share(props); return <p data-testid="team-share">share</p>; },
}));

import { ExternalObservationHistory } from "@/app/sites/[siteId]/observations/ExternalObservationHistory";
import SiteObservationDetailPage from "@/app/sites/[siteId]/observations/[reportRef]/page";
import SiteObservationHistoryPage from "@/app/sites/[siteId]/observations/page";
import type { ExternalResultSummaryView } from "@/lib/core-api/types";

const relativeRef = `external-relative-volume-report-${"a".repeat(32)}`;
const secondRelativeRef = `external-relative-volume-report-${"c".repeat(32)}`;
const singleRef = `external-single-volume-report-${"b".repeat(32)}`;
const unavailableRef = `external-single-volume-report-${"d".repeat(32)}`;

const relative: ExternalResultSummaryView = {
  kind: "EXTERNAL_RELATIVE_VOLUME",
  reportRef: relativeRef,
  reportDigest: "sha256:report",
  requestRef: "request-1",
  requestDigest: "sha256:request",
  sourceWorkOrderId: "work-1",
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
    zoneCellCount: 100, commonValidCellCount: 90, zoneAreaM2: 100, measuredAreaM2: 90, commonValidFraction: 0.9,
    cutM3: 20, fillM3: 30, netM3: 10, thresholdM: 0.1, uncertaintyM3: 1.2, uncertaintyNote: "표본 기반 불확실성",
  },
  executionPolicy: {
    policyId: "policy-1", version: 1, policyDigest: "sha256:policy", algorithmBuildDigest: "sha256:build",
    configDigest: "sha256:config", uncertaintyMethod: "RSS",
  },
  reviewRef: null,
  reviewDigest: null,
  reviewedAt: null,
  proposalCount: 0,
  approvedProposalCount: 0,
};

// Same zone/CRS/vertical/policy as `relative`, so it would join the relative trend
// if the kind were ignored.
const single: ExternalResultSummaryView = {
  ...relative,
  kind: "EXTERNAL_SINGLE_VOLUME",
  reportRef: singleRef,
  requestRef: "single-request-1",
  baselineWorkOrderId: null,
  baselineCapturedFrom: null,
  baselineCapturedTo: null,
  currentCapturedFrom: "2026-09-15T00:00:00Z",
  currentCapturedTo: "2026-09-15T00:30:00Z",
  reportedAt: "2026-09-15T02:00:00Z",
  metrics: {
    zoneCellCount: 100, commonValidCellCount: 95, zoneAreaM2: 100, measuredAreaM2: 95, commonValidFraction: 0.95,
    cutM3: 0.5, fillM3: 1234.5, netM3: 777, thresholdM: 0.1, uncertaintyM3: null, uncertaintyNote: "경계 기저면",
    baseRoughnessM: 0.456, boundaryCellCount: 40, boundarySampleCount: 38, boundaryValidFraction: 0.875,
  },
};

const names = new Map([["area-1", "야적장 1"]]);

afterEach(() => {
  cleanup();
});

function rows(container: HTMLElement) {
  return [...container.querySelectorAll("article")] as HTMLElement[];
}

describe("merged external volume history rows", () => {
  it("labels each row by kind and renders a single-volume row without baseline, net change or repeat action", () => {
    const { container } = render(<ExternalObservationHistory
      siteId="site-1"
      items={[
        { reportRef: singleRef, state: "AVAILABLE", result: single },
        { reportRef: relativeRef, state: "AVAILABLE", result: relative },
        { reportRef: unavailableRef, state: "HISTORICAL_SOURCE_UNAVAILABLE", result: null },
      ]}
      workAreaNames={names}
    />);
    const [singleRow, relativeRow, unavailableRow] = rows(container);

    const singleScope = within(singleRow!);
    expect(singleScope.getByText("단일 시점 체적")).toBeTruthy();
    expect(singleScope.queryByText("상대 물량")).toBeNull();
    expect(singleScope.getByText("체적")).toBeTruthy();
    expect(singleScope.getByText("1,234.5 m³")).toBeTruthy();
    expect(singleScope.getByText("불확도 미산정")).toBeTruthy();
    expect(singleScope.getByText("기저면 거칠기")).toBeTruthy();
    expect(singleScope.getByText("0.46 m")).toBeTruthy();
    expect(singleScope.getByText("경계 유효 비율")).toBeTruthy();
    expect(singleScope.getByText("87.5%")).toBeTruthy();
    expect(singleRow!.textContent).toContain("현재");
    expect(singleRow!.textContent).not.toContain("기준");
    expect(singleRow!.textContent).not.toContain("순변화");
    expect(singleRow!.textContent).not.toContain("+777");
    expect(singleScope.queryByRole("link", { name: "이 범위로 새 관측" })).toBeNull();
    expect(singleScope.getByRole("link", { name: "작업 관리" }).getAttribute("href")).toBe("/field/work-orders/work-1");
    expect(singleScope.getByRole("link", { name: "상세 보기" }).getAttribute("href")).toBe(`/sites/site-1/observations/${singleRef}`);

    const relativeScope = within(relativeRow!);
    expect(relativeScope.getByText("상대 물량")).toBeTruthy();
    expect(relativeScope.getByText("순변화")).toBeTruthy();
    expect(relativeScope.getByRole("link", { name: "이 범위로 새 관측" })).toBeTruthy();

    expect(unavailableRow!.textContent).toContain("보관 근거 확인 필요");
    expect(unavailableRow!.textContent).toContain("이 결과는 이력에 남아 있지만 현재 보관 근거를 검증하지 못했습니다. 수치와 비교 차트는 표시하지 않습니다.");
    expect(within(unavailableRow!).queryByText("단일 시점 체적")).toBeNull();
  });

  it("builds the net-change trend from relative rows only", () => {
    render(<ExternalObservationHistory
      siteId="site-1"
      items={[
        { reportRef: singleRef, state: "AVAILABLE", result: single },
        { reportRef: relativeRef, state: "AVAILABLE", result: relative },
        { reportRef: secondRelativeRef, state: "AVAILABLE", result: { ...relative, reportRef: secondRelativeRef, currentCapturedTo: "2026-09-10T01:00:00Z", metrics: { ...relative.metrics!, netM3: -4 } } },
      ]}
      workAreaNames={names}
    />);
    const trend = screen.getByRole("heading", { name: "호환되는 비교의 순변화" }).closest("section")!;
    expect(trend.textContent).toContain("+10 m³");
    expect(trend.textContent).toContain("-4 m³");
    expect(trend.textContent).not.toContain("777");
    expect(trend.textContent).toContain("±10 m³");
  });

  it("shows no trend when only single-volume rows exist", () => {
    render(<ExternalObservationHistory
      siteId="site-1"
      items={[{ reportRef: singleRef, state: "AVAILABLE", result: single }]}
      workAreaNames={names}
    />);
    expect(screen.queryByRole("heading", { name: "호환되는 비교의 순변화" })).toBeNull();
  });
});

describe("site observation pages", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["WORK_ORDERS_WRITE"] } });
    mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 1" });
    mocked.areas.mockResolvedValue({ workAreas: [{ workAreaId: "area-1", name: "야적장 1" }] });
  });

  it("loads the merged volume history and keeps the nextCursor pagination", async () => {
    mocked.history.mockResolvedValue({
      items: [
        { reportRef: singleRef, state: "AVAILABLE", result: single },
        { reportRef: relativeRef, state: "AVAILABLE", result: relative },
      ],
      nextCursor: relativeRef,
    });
    render(await SiteObservationHistoryPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ after: singleRef }),
    }));
    expect(mocked.history).toHaveBeenCalledWith("site-1", { after: singleRef, limit: 50 });
    expect(mocked.relativeHistory).not.toHaveBeenCalled();
    expect(screen.getByText("단일 시점 체적")).toBeTruthy();
    expect(screen.getByText("상대 물량")).toBeTruthy();
    expect(screen.getByRole("link", { name: "이전 결과 더 보기" }).getAttribute("href")).toBe(
      `/sites/site-1/observations?after=${relativeRef}`,
    );
  });

  it("renders a single-volume detail with the single row and no pair display, share, or review trace", async () => {
    mocked.projection.mockResolvedValue({ state: "AVAILABLE", result: single });
    const { container } = render(await SiteObservationDetailPage({
      params: Promise.resolve({ siteId: "site-1", reportRef: singleRef }),
    }));
    expect(mocked.projection).toHaveBeenCalledWith("site-1", singleRef);
    expect(mocked.detail).not.toHaveBeenCalled();
    expect(mocked.pair).not.toHaveBeenCalled();
    expect(screen.queryByTestId("team-share")).toBeNull();
    const [row] = rows(container);
    expect(within(row!).getByText("단일 시점 체적")).toBeTruthy();
    expect(within(row!).getByText("1,234.5 m³")).toBeTruthy();
    expect(within(row!).getByText("0.46 m")).toBeTruthy();
    expect(within(row!).queryByRole("link", { name: "이 범위로 새 관측" })).toBeNull();
    const trace = screen.getByRole("heading", { name: "검토·재관측 흐름" }).closest("section")!;
    expect(within(trace).getByText("단일 시점 결과 검토는 준비 중입니다.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "결과 검토와 후속 작업" })).toBeNull();
    expect(container.textContent).not.toContain("기준 관측과 현재 관측을 비교한");
  });
});
