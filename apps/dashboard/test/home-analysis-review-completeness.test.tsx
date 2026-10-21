/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockedCore = vi.hoisted(() => ({
  listSitesCached: vi.fn(),
  whoAmI: vi.fn(),
  listObservationWorkOrdersForOrganization: vi.fn(),
  listObservationWorkOrderOperations: vi.fn(),
  listExternalPendingDecisions: vi.fn(),
  listWorkInbox: vi.fn(),
  listAnalyses: vi.fn(),
  getAnalysisReviewTarget: vi.fn(),
  listAnalysisReviews: vi.fn(),
  listWorkAreas: vi.fn(),
}));

vi.mock("@/lib/core-api/cached", () => ({ listSitesCached: mockedCore.listSitesCached }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mockedCore.whoAmI }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({
  listObservationWorkOrdersForOrganization: mockedCore.listObservationWorkOrdersForOrganization,
  listObservationWorkOrderOperations: mockedCore.listObservationWorkOrderOperations,
}));
vi.mock("@/lib/core-api/external-decisions", () => ({
  listExternalPendingDecisions: mockedCore.listExternalPendingDecisions,
}));
vi.mock("@/lib/core-api/work-collaboration", () => ({ listWorkInbox: mockedCore.listWorkInbox }));
vi.mock("@/lib/core-api/analysis", () => ({
  listAnalyses: mockedCore.listAnalyses,
  getAnalysisReviewTarget: mockedCore.getAnalysisReviewTarget,
  listAnalysisReviews: mockedCore.listAnalysisReviews,
}));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mockedCore.listWorkAreas }));

import type { AnalysisListItem, AnalysisReviewReceipt, AnalysisReviewTarget } from "@/lib/core-api/analysis";
import type { SiteView } from "@/lib/core-api/types";
import HomePage from "@/app/page";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function site(siteId: string, status: SiteView["status"] = "PATROL_READY", updatedAt = "2026-10-18T00:00:00Z"): SiteView {
  return {
    siteId,
    name: siteId,
    siteFrame: { crs: "EPSG:5186", verticalDatum: "LOCAL", unit: "meter", transformVersion: "1" },
    status,
    resumeTarget: null,
    registeredAt: "2026-08-01T00:00:00Z",
    updatedAt,
    aoi: null,
    dataResidency: null,
    aiEgressAllowed: false,
    modelMaxAgeDays: null,
  };
}

function analysis(analysisId: string, siteId: string, createdAt: string): AnalysisListItem {
  return {
    analysisId,
    siteId,
    workAreaId: `area-${siteId}`,
    executionState: "COMPLETED",
    suitabilityState: "EVALUATED",
    createdAt,
    resultId: `result-${analysisId}`,
    metrics: null,
    limitationCount: 0,
    analysisHref: `/sites/${siteId}/analysis?analysisId=${analysisId}`,
  };
}

function reviewTarget(identity: string): AnalysisReviewTarget {
  return {
    resultId: `result-${identity}`,
    resultRevision: 1,
    reportDigest: `report-${identity}`,
    numericResultIdentityDigest: `numeric-${identity}`,
    calculationIdentityDigest: `calculation-${identity}`,
    admissionDigest: `admission-${identity}`,
    evaluations: [
      { epoch: "BASELINE", evaluationId: `baseline-${identity}`, revision: 1, evaluationDigest: `baseline-digest-${identity}` },
      { epoch: "CURRENT", evaluationId: `current-${identity}`, revision: 1, evaluationDigest: `current-digest-${identity}` },
    ],
  };
}

function reviewReceipt(target: AnalysisReviewTarget, reviewRef: string, reviewedAt: string): AnalysisReviewReceipt {
  return {
    reviewRef,
    reviewerId: "operator",
    decision: "ACKNOWLEDGED",
    comment: "확인",
    reviewedAt,
    receiptDigest: `digest-${reviewRef}`,
    target,
    factualLimitations: [],
  };
}

function mockWorld(sites: SiteView[]) {
  mockedCore.listSitesCached.mockResolvedValue(sites);
  mockedCore.whoAmI.mockResolvedValue({
    principalId: "operator",
    organizationId: "org-local",
    kind: "OPERATOR",
    role: "VIEWER",
    deviceId: null,
    permissions: [],
    registryScoped: false,
  });
  mockedCore.listObservationWorkOrdersForOrganization.mockResolvedValue([]);
  mockedCore.listObservationWorkOrderOperations.mockResolvedValue([]);
  mockedCore.listExternalPendingDecisions.mockResolvedValue({ items: [] });
  mockedCore.listWorkInbox.mockResolvedValue({ items: [], nextCursor: null });
  mockedCore.listWorkAreas.mockResolvedValue({ workAreas: [] });
}

function mockAnalysisReads(options: {
  itemsBySite?: Record<string, AnalysisListItem[]>;
  analysesCursor?: string | null;
  target?: AnalysisReviewTarget;
  reviews?: AnalysisReviewReceipt[];
  failList?: boolean;
  failTarget?: boolean;
  failReviews?: boolean;
  reviewsCursor?: string | null;
} = {}) {
  if (options.failList) {
    mockedCore.listAnalyses.mockRejectedValue(new Error("Core unavailable"));
  } else {
    mockedCore.listAnalyses.mockImplementation(async (siteId: string) => ({
      siteId,
      items: options.itemsBySite?.[siteId] ?? [],
      nextCursor: options.analysesCursor ?? null,
    }));
  }
  if (options.failTarget) {
    mockedCore.getAnalysisReviewTarget.mockRejectedValue(new Error("Core unavailable"));
  } else {
    mockedCore.getAnalysisReviewTarget.mockImplementation(async (_siteId: string, analysisId: string) => options.target ?? reviewTarget(analysisId));
  }
  if (options.failReviews) {
    mockedCore.listAnalysisReviews.mockRejectedValue(new Error("Core unavailable"));
  } else {
    mockedCore.listAnalysisReviews.mockResolvedValue({
      items: options.reviews ?? [],
      nextCursor: options.reviewsCursor ?? null,
    });
  }
}

describe("Home 분석-검토 읽기 완전성 (D1 unknown-not-0)", () => {
  beforeEach(() => {
    mockWorld([site("site-1")]);
  });

  it("성공적 빈 읽기는 0건을 안다 — 무안건 결론과 함께 알림이 없다", async () => {
    mockAnalysisReads();
    render(await HomePage());

    expect(screen.getByText("확인 필요 0곳")).toBeTruthy();
    expect(screen.getByText("조회된 범위에 새 운영 안건이 없습니다.")).toBeTruthy();
    expect(screen.queryByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeNull();
  });

  it("분석 목록 읽기가 실패하면 0으로 낮추지 않는다", async () => {
    mockAnalysisReads({ failList: true });
    render(await HomePage());

    expect(screen.queryByText("확인 필요 0곳")).toBeNull();
    expect(screen.queryByText("조회된 범위에 새 운영 안건이 없습니다.")).toBeNull();
    expect(screen.getByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.getByText("최근 현장을 직접 확인하세요.")).toBeTruthy();
  });

  it("검토 대상 읽기가 실패하면 검토 완료로 보지 않는다", async () => {
    mockAnalysisReads({
      itemsBySite: { "site-1": [analysis("a1", "site-1", "2026-10-15T10:00:00Z")] },
      failTarget: true,
    });
    render(await HomePage());

    expect(screen.queryByText("확인 필요 0곳")).toBeNull();
    expect(screen.queryByText(/검토 기록이 없습니다/)).toBeNull();
    expect(screen.getByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeTruthy();
  });

  it("영수증 목록 읽기가 실패하면 검토 완료로 보지 않는다", async () => {
    mockAnalysisReads({
      itemsBySite: { "site-1": [analysis("a1", "site-1", "2026-10-15T10:00:00Z")] },
      failReviews: true,
    });
    render(await HomePage());

    expect(screen.queryByText("확인 필요 0곳")).toBeNull();
    expect(screen.queryByText(/검토 기록이 없습니다/)).toBeNull();
    expect(screen.getByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeTruthy();
  });

  it("일부 현장이 미확인이어도 알려진 보류는 사실대로 보여주고 건수는 미완으로 둔다", async () => {
    mockWorld([site("site-1"), site("site-2")]);
    mockedCore.listAnalyses.mockImplementation(async (siteId: string) => {
      if (siteId === "site-2") throw new Error("Core unavailable");
      return {
        siteId,
        items: siteId === "site-1" ? [analysis("a1", "site-1", "2026-10-15T10:00:00Z")] : [],
        nextCursor: null,
      };
    });
    mockedCore.getAnalysisReviewTarget.mockImplementation(async (_siteId: string, analysisId: string) => reviewTarget(analysisId));
    mockedCore.listAnalysisReviews.mockResolvedValue({ items: [], nextCursor: null });

    render(await HomePage());

    // 알려진 보류 카드는 그대로, 같은 deep CTA에 실제 작업구역을 함께 싣는다.
    const action = screen.getByRole("link", { name: "분석 결과 검토" });
    expect(action.getAttribute("href")).toBe("/sites/site-1/analysis?analysisId=a1&workAreaId=area-site-1");
    expect(screen.queryByText("확인 필요 0곳")).toBeNull();
    expect(screen.getByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeTruthy();
  });

  it("현재 대상과 일치하는 실제 검토 영수증은 보류에서 지운다", async () => {
    const target = reviewTarget("a1");
    mockAnalysisReads({
      itemsBySite: { "site-1": [analysis("a1", "site-1", "2026-10-15T10:00:00Z")] },
      target,
      reviews: [reviewReceipt(target, "r1", "2026-10-15T11:00:00Z")],
    });
    render(await HomePage());

    expect(screen.queryByRole("link", { name: "분석 결과 검토" })).toBeNull();
    expect(screen.getByText("확인 필요 0곳")).toBeTruthy();
    expect(screen.queryByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeNull();
  });

  it("분석 목록이 잘리면 범위 밖 나머지를 0이라 단정하지 않는다", async () => {
    mockAnalysisReads({ analysesCursor: "next-page" });
    render(await HomePage());

    expect(screen.queryByText("확인 필요 0곳")).toBeNull();
    expect(screen.getByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeTruthy();
  });

  it("영수증 페이지가 잘리면 범위 밖 일치를 검토 완료라 단정하지 않는다", async () => {
    mockAnalysisReads({
      itemsBySite: { "site-1": [analysis("a1", "site-1", "2026-10-15T10:00:00Z")] },
      reviews: [],
      reviewsCursor: "next-page",
    });
    render(await HomePage());

    expect(screen.queryByText("확인 필요 0곳")).toBeNull();
    expect(screen.queryByText(/검토 기록이 없습니다/)).toBeNull();
    expect(screen.getByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeTruthy();
  });

  it("읽기 묶음(3현장) 밖 후보 현장이 있으면 미확인으로 둔다", async () => {
    mockWorld([
      site("site-1", "REMAP_REQUIRED", "2026-10-18T00:00:00Z"),
      site("site-2", "REMAP_REQUIRED", "2026-10-17T00:00:00Z"),
      site("site-3", "REMAP_REQUIRED", "2026-10-16T00:00:00Z"),
      site("site-4", "REMAP_REQUIRED", "2026-10-15T00:00:00Z"),
    ]);
    mockAnalysisReads();
    render(await HomePage());

    // 4곳 모두 실제 안건 카드로 보이되, 검토 범위를 다 읽지 못했으므로 건수는 미완이다.
    expect(screen.getByText("확인 필요 —")).toBeTruthy();
    expect(screen.getByText(/분석 결과의 검토 대기 여부를 확인할 수 없습니다/)).toBeTruthy();
  });
});
