import { describe, expect, it } from "vitest";

import {
  selectHomeAnalysisReviewSources,
  selectHomeAttentionSources,
  selectHomeActiveWorkOrders,
  selectHomeDecisionWorkOrders,
  selectHomeInitialSetupSites,
  selectHomeRecentSiteSources,
} from "@/lib/home-operations";
import type { AnalysisListItem, AnalysisReviewReceipt, AnalysisReviewTarget } from "@/lib/core-api/analysis";
import type { ExternalPendingDecision } from "@/lib/core-api/external-decisions";
import type { ObservationWorkOrderStatus, ObservationWorkOrderView, SiteView } from "@/lib/core-api/types";

function workOrder(status: ObservationWorkOrderStatus, workOrderId: string, updatedAt: string, siteId = "site-1"): ObservationWorkOrderView {
  return {
    schemaVersion: "1.0", workOrderId, organizationId: "org-local", siteId, purpose: "PROGRESS_QUANTITY",
    name: workOrderId, workAreaIds: [], scheduleId: null, executionMode: null, cycleNumber: 1, status, statusReason: null,
    missionIds: [], processingJobIds: [], reportRefs: [], version: 1, createdAt: updatedAt, updatedAt, createdBy: "operator",
    approvedAt: null, approvedBy: null,
  };
}

function site(siteId: string, status: SiteView["status"] = "PATROL_READY", updatedAt = "2026-08-22T09:00:00Z"): SiteView {
  return { siteId, name: siteId, siteFrame: { crs: "EPSG:5186", verticalDatum: "LOCAL", unit: "meter", transformVersion: "1" }, status, resumeTarget: null, registeredAt: "2026-08-01T00:00:00Z", updatedAt, aoi: null, dataResidency: null, aiEgressAllowed: false, modelMaxAgeDays: null };
}

function analysis(analysisId: string, siteId: string, createdAt: string): AnalysisListItem {
  return {
    analysisId, siteId, workAreaId: `area-${siteId}`, executionState: "COMPLETED", suitabilityState: "EVALUATED",
    createdAt, resultId: `result-${analysisId}`, metrics: null, limitationCount: 0,
    analysisHref: `/sites/${siteId}/analysis?analysisId=${analysisId}`,
  };
}

function reviewTarget(identity: string): AnalysisReviewTarget {
  return {
    resultId: `result-${identity}`, resultRevision: 1, reportDigest: `report-${identity}`,
    numericResultIdentityDigest: `numeric-${identity}`, calculationIdentityDigest: `calculation-${identity}`,
    admissionDigest: `admission-${identity}`,
    evaluations: [
      { epoch: "BASELINE", evaluationId: `baseline-${identity}`, revision: 1, evaluationDigest: `baseline-digest-${identity}` },
      { epoch: "CURRENT", evaluationId: `current-${identity}`, revision: 1, evaluationDigest: `current-digest-${identity}` },
    ],
  };
}

function reviewReceipt(target: AnalysisReviewTarget, reviewRef: string, reviewedAt: string): AnalysisReviewReceipt {
  return { reviewRef, reviewerId: "operator", decision: "ACKNOWLEDGED", comment: "확인", reviewedAt, receiptDigest: `digest-${reviewRef}`, target, factualLimitations: [] };
}

describe("Home platform selectors", () => {
  it("작업 결정은 workflow 우선순위와 최신 갱신 순으로 고른다", () => {
    const selected = selectHomeDecisionWorkOrders([
      workOrder("REVIEW_READY", "results", "2026-08-22T09:00:00Z"),
      workOrder("AWAITING_APPROVAL", "approval-old", "2026-08-22T08:00:00Z"),
      workOrder("BLOCKED", "blocked", "2026-08-22T07:00:00Z"),
      workOrder("AWAITING_APPROVAL", "approval-new", "2026-08-22T10:00:00Z"),
    ], 4);
    expect(selected.map((item) => item.workOrderId)).toEqual(["blocked", "approval-new", "approval-old", "results"]);
  });

  it("진행 중 작업은 승인 대기·완료 작업과 분리한다", () => {
    const selected = selectHomeActiveWorkOrders([
      workOrder("PROCESSING", "processing", "2026-08-22T08:00:00Z"),
      workOrder("AWAITING_APPROVAL", "approval", "2026-08-22T11:00:00Z"),
      workOrder("COMPLETED", "completed", "2026-08-22T12:00:00Z"),
    ], 3);
    expect(selected.map((item) => item.workOrderId)).toEqual(["processing"]);
  });

  it("초기 설정 현장과 최근 현장은 사이트 원장만으로 고른다", () => {
    const sites = [site("ready"), site("newer", "UNMAPPED", "2026-08-22T09:00:00Z"), site("older", "UNMAPPED", "2026-08-21T09:00:00Z")];
    expect(selectHomeInitialSetupSites(sites, 1).map((item) => item.siteId)).toEqual(["older"]);
    expect(selectHomeRecentSiteSources(sites, 2).map((item) => item.siteId)).toEqual(["ready", "newer"]);
  });

  it("현재 결과 검토가 있는 분석은 건너뛰고 가장 최신 미검토 분석만 현장당 고른다", () => {
    const currentAnalysis = analysis("new-reviewed", "site-review", "2026-10-15T10:00:00Z");
    const newestPendingAnalysis = analysis("newest-pending", "site-review", "2026-10-14T12:00:00Z");
    const olderPendingAnalysis = analysis("older-pending", "site-review", "2026-10-14T10:00:00Z");
    const currentTarget = reviewTarget("new-reviewed");
    const selected = selectHomeAnalysisReviewSources([
      { analysis: olderPendingAnalysis, currentTarget: reviewTarget("older-pending"), reviews: [] },
      { analysis: newestPendingAnalysis, currentTarget: reviewTarget("newest-pending"), reviews: [] },
      { analysis: currentAnalysis, currentTarget, reviews: [reviewReceipt(currentTarget, "current", "2026-10-15T11:00:00Z")] },
    ]);

    expect(selected.map((item) => item.analysis.analysisId)).toEqual(["newest-pending"]);
  });

  it("기존 작업이 있는 UNMAPPED 현장을 초기 설정으로 재분류하지 않고 필터 후 개수 제한을 적용한다", () => {
    const sites = [site("existing", "UNMAPPED"), site("new", "UNMAPPED")];
    const orders = [workOrder("APPROVED", "existing-work", "2026-10-17T00:00:00Z", "existing")];
    expect(selectHomeInitialSetupSites(sites, 1, { workOrders: orders, known: true }).map((s) => s.siteId)).toEqual(["new"]);
    expect(selectHomeInitialSetupSites(sites, 3, { workOrders: [], known: false })).toEqual([]);
    expect(selectHomeInitialSetupSites(sites, 3, { workOrders: [], known: true })).toHaveLength(2);
  });

  it("가장 최근 검토가 이전 결과 대상이면 현재 분석을 검토 대기로 남긴다", () => {
    const currentTarget = reviewTarget("current");
    const earlierMatching = reviewReceipt(currentTarget, "matching", "2026-10-14T10:00:00Z");
    const latestStale = reviewReceipt(reviewTarget("previous"), "stale", "2026-10-15T10:00:00Z");
    const selected = selectHomeAnalysisReviewSources([{
      analysis: analysis("analysis-current", "site-review", "2026-10-15T09:00:00Z"),
      currentTarget,
      reviews: [latestStale, earlierMatching],
    }]);

    expect(selected.map((item) => item.analysis.analysisId)).toEqual(["analysis-current"]);
  });

  it("legacy external decisions stay first and a Site is never repeated across attention sources", () => {
    const currentTarget = reviewTarget("site-two");
    const pendingReviews = selectHomeAnalysisReviewSources([
      { analysis: analysis("site-one-analysis", "site-1", "2026-10-15T11:00:00Z"), currentTarget: reviewTarget("site-one"), reviews: [] },
      { analysis: analysis("site-two-analysis", "site-2", "2026-10-15T10:00:00Z"), currentTarget, reviews: [] },
    ]);
    const decision: ExternalPendingDecision = {
      siteId: "site-1", reportRef: "report-1", kind: "EXTERNAL_RELATIVE_VOLUME", stage: "AWAITING_REVIEW",
      reportedAt: "2026-10-15T12:00:00Z", netM3: 1, uncertaintyM3: null, workAreaId: "area-site-1",
    };
    const selected = selectHomeAttentionSources({
      workOrders: [workOrder("BLOCKED", "blocked-site-two", "2026-10-15T09:00:00Z", "site-2")],
      sites: [site("site-1"), site("site-2")],
      externalDecisions: [decision],
      analysisReviews: pendingReviews,
    }, 5);

    expect(selected.map((item) => item.kind)).toEqual(["EXTERNAL_DECISION", "ANALYSIS_REVIEW"]);
    expect(selected.map((item) => item.siteId)).toEqual(["site-1", "site-2"]);
    expect(new Set(selected.map((item) => item.siteId)).size).toBe(selected.length);
  });
});
