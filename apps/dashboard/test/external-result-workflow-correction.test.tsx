// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const router = { push: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { ExternalResultWorkflowPanel } from "@/app/field/ExternalResultWorkflowPanel";

const digest = (value: string) => `sha256:${value.repeat(64)}`;
const firstRequestRef = `external-relative-volume-${"a".repeat(32)}`;
const secondRequestRef = `external-relative-volume-${"b".repeat(32)}`;
const firstReportRef = `external-relative-volume-report-${"c".repeat(32)}`;
const secondReportRef = `external-relative-volume-report-${"d".repeat(32)}`;
const proposalRef = `erop-v1-${"e".repeat(64)}`;
const actualCoreRequestRef = "external-relative-volume-b3a804cd0b1ffb98c6d7d525f4e737f1";
const actualCoreReportRef = "external-relative-volume-report-b963854ac91e0752d57475a75e4585bc";
const actualCoreFirstProposalRef = "erop-v1-611efc5209043feb4ad87a3e373924eb7bb986321bf288e32752b89d99752b11";
const actualCoreLaterProposalRef = "erop-v1-be210c2417f0dcc7f2e5b4774c4ef5414fbee88f1f0cb00dd5771cf44e77a9b3";
const actualCoreSuccessorWorkOrderId = "obs-work-external-625c15e3808ba97bb0a2cbbc";
const response = (value: unknown, ok = true) => ({ ok, json: async () => value });

type RequestView = { requestRef: string; status: "SUCCEEDED"; reportRef: string; reportDigest: string; issuedAt: string; deadlineAt: string };

function requestView(requestRef: string, reportRef: string): RequestView {
  return { requestRef, status: "SUCCEEDED", reportRef, reportDigest: digest("9"), issuedAt: "2026-09-02T00:00:00Z", deadlineAt: "2099-01-01T00:00:00Z" };
}

function reportView(requestRef: string, reportRef: string, workAreaId: string, options: { review?: unknown; proposals?: unknown[] } = {}) {
  const baseline = {
    subject: { organizationId: "org-1", siteId: "site-1", workOrderId: "baseline-1", submissionId: "submission-a", revision: 1, submissionDigest: digest("1"), manifestDigest: digest("2") },
    inspectionReportDigest: digest("3"), dsmArtifactId: "dsm-a", observedSha256: digest("4"), observedSizeBytes: 2, observedCrsDigest: digest("5"), observedVerticalReferenceDigest: digest("6"), capturedFrom: "2026-09-01T00:00:00Z", capturedTo: "2026-09-01T00:01:00Z",
  };
  const current = {
    subject: { organizationId: "org-1", siteId: "site-1", workOrderId: "work-1", submissionId: "submission-b", revision: 2, submissionDigest: digest("7"), manifestDigest: digest("8") },
    inspectionReportDigest: digest("9"), dsmArtifactId: "dsm-b", observedSha256: digest("a"), observedSizeBytes: 2, observedCrsDigest: digest("5"), observedVerticalReferenceDigest: digest("6"), capturedFrom: "2026-09-02T00:00:00Z", capturedTo: "2026-09-02T00:01:00Z",
  };
  const request = {
    contractVersion: "external-relative-volume-request.v1", requestId: requestRef, currentWorkOrderId: "work-1", decisionId: `external-use-decision-${"f".repeat(32)}`, decisionDigest: digest("f"), baseline, current,
    evidenceRecordDigests: [digest("b")], validationPolicyDigest: digest("c"), executionPolicyDigest: digest("d"),
    zoneSnapshot: { contractVersion: "external-volume-zone-snapshot.v1", organizationId: "org-1", siteId: "site-1", workAreaId, revision: 1, polygon: {}, crs: "EPSG:5186", observedCrsDigest: digest("5"), analysisVerticalReferenceDigest: digest("6"), definitionDigest: digest("e") },
    issuedAt: "2026-09-02T01:00:00Z", idempotencyKey: "core-key", requestDigest: digest("0"),
  };
  const executionPolicy = { contractVersion: "external-relative-volume-execution-policy.v1", policyId: "policy-1", version: 1, algorithmBuildDigest: digest("1"), configDigest: digest("2"), thresholdM: 0.1, minimumCommonValidFraction: 0.9, uncertaintyMethod: "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1", resourceEnvelopeDigest: digest("3"), authorityRecordDigest: digest("4"), syntheticTestOnly: true, policyDigest: digest("d") };
  const report = {
    contractVersion: "external-relative-volume-report.v1", reportId: reportRef, requestId: requestRef, requestDigest: digest("0"),
    payload: { factClass: "OBSERVED", requestDigest: digest("0"), decisionDigest: digest("f"), baselineDsmDigest: digest("4"), currentDsmDigest: digest("a"), zoneSnapshotDigest: digest("e"), executionPolicyDigest: digest("d"), algorithmBuildDigest: digest("1"), configDigest: digest("2"), metrics: { zoneCellCount: 10, commonValidCellCount: 10, zoneAreaM2: 10, measuredAreaM2: 10, commonValidFraction: 1, cutM3: 1, fillM3: 2, netM3: 1, thresholdM: 0.1, uncertaintyM3: null, uncertaintyNote: "unknown" } },
    measurementPayloadDigest: digest("3"), workerInstanceId: "worker", leaseAcquisitionId: "lease", leaseGeneration: 1, computedAt: "2026-09-02T02:00:00Z", reportedAt: "2026-09-02T02:01:00Z", reportDigest: digest("9"),
  };
  return { request, report, executionPolicy, review: options.review ?? null, proposals: options.proposals ?? [] };
}

function reviewReceipt(requestRef: string, reportRef: string, workAreaId: string, baselineRmseM: number | null, currentRmseM: number | null) {
  const base = reportView(requestRef, reportRef, workAreaId);
  return {
    contractVersion: "external-result-review-receipt.v1",
    reviewRef: `err-v1-${"1".repeat(64)}`,
    organizationId: "org-1",
    siteId: "site-1",
    sourceWorkOrderId: "work-1",
    reportRef,
    request: base.request,
    report: base.report,
    authority: {
      contractVersion: "external-result-review-authority.v1", organizationId: "org-1", siteId: "site-1", currentWorkOrderId: "work-1", decisionId: base.request.decisionId, decisionDigest: base.request.decisionDigest,
      compatibilityMappingDigest: digest("7"), baseline: base.request.baseline, current: base.request.current, evidenceRecordDigests: base.request.evidenceRecordDigests, validationPolicyDigest: base.request.validationPolicyDigest, zoneSnapshot: base.request.zoneSnapshot, executionPolicy: base.executionPolicy,
      authorizedActorIds: ["operator-1"], validFrom: "2026-09-02T00:00:00Z", validUntil: "2026-09-03T00:00:00Z", historicalAuthorityDigest: digest("8"), baselineRmseM, currentRmseM, maximumZoneCellCount: 100, maximumZoneAreaM2: 100, syntheticTestOnly: true, authorityDigest: digest("9"),
    },
    decision: {
      contractVersion: "external-pair-use-decision.v1", decisionId: base.request.decisionId, baselineSubject: base.request.baseline.subject, baselineSubjectDigest: digest("a"), currentSubject: base.request.current.subject, currentSubjectDigest: digest("b"), use: "RELATIVE_VOLUME", policyDigest: base.request.validationPolicyDigest, baselineInspectionReportDigest: base.request.baseline.inspectionReportDigest, currentInspectionReportDigest: base.request.current.inspectionReportDigest, baselineSanitizedDisplayReceiptDigest: null, currentSanitizedDisplayReceiptDigest: null, evidenceRecordDigests: base.request.evidenceRecordDigests, zone: { zoneId: workAreaId, revision: 1, definitionDigest: base.request.zoneSnapshot.definitionDigest, observedCrsDigest: base.request.zoneSnapshot.observedCrsDigest, observedVerticalReferenceDigest: base.request.zoneSnapshot.analysisVerticalReferenceDigest }, compatibilityMappingDigest: digest("7"), verdict: "ELIGIBLE", reasons: ["Core 기록"], remediations: ["없음"], decidedAt: "2026-09-02T02:00:00Z", decisionDigest: base.request.decisionDigest,
    },
    factualLimitations: ["RELATIVE_VOLUME_IS_OPERATIONAL_ONLY", "ABSOLUTE_ACCURACY_NOT_CLAIMED", "NO_AUTOMATIC_REOBSERVATION_THRESHOLD"],
    reviewedAt: "2026-09-02T03:00:00Z",
    reviewDigest: digest("c"),
  };
}

function actualCoreProposalView(
  proposalRefValue: string,
  reason: string,
  approvalReceipt: object | null = null,
) {
  return {
    proposal: {
      contractVersion: "external-reobservation-proposal.v1",
      proposalRef: proposalRefValue,
      version: 1,
      organizationId: "org-a",
      siteId: "site-a",
      sourceWorkOrderId: "obs-work-00000001",
      reviewRef: `err-v1-${"0".repeat(64)}`,
      reviewDigest: digest("1"),
      reportRef: actualCoreReportRef,
      reportDigest: digest("2"),
      decisionDigest: digest("3"),
      zoneDigest: digest("4"),
      evidenceDigests: [digest("5"), digest("6")],
      targetWorkAreas: [{ workAreaId: "wa-site-a-0001", revision: 1, snapshotDigest: digest("7") }],
      reason,
      createdBy: "operator-a",
      createdAt: "2026-09-09T12:00:00Z",
      proposalDigest: digest("8"),
    },
    approvalReceipt,
  };
}

function actualCoreApprovalReceipt() {
  return {
    contractVersion: "external-reobservation-approval-receipt.v1",
    approvalId: "external-reobs-approval-4be651b164335175e7fdfa2e",
    organizationId: "org-a",
    siteId: "site-a",
    sourceWorkOrderId: "obs-work-00000001",
    successorWorkOrderId: actualCoreSuccessorWorkOrderId,
    proposalId: actualCoreLaterProposalRef,
    proposalVersion: 1,
    proposalDigest: digest("8"),
    approvalInputDigest: digest("9"),
    bindingDigest: digest("a"),
    idempotencyKey: "approval",
    approvedBy: "operator-a",
    approvedAt: "2026-09-09T12:00:00Z",
    receiptDigest: digest("b"),
  };
}

async function select(index: number) {
  fireEvent.click((await screen.findAllByRole("button", { name: "비교 요청 상태" }))[index]);
}

beforeEach(() => {
  vi.stubGlobal("crypto", { randomUUID: () => "stable" });
  router.push.mockReset();
  router.refresh.mockReset();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("retires a delayed old review when a different retained request is selected", async () => {
  let resolveReview!: () => void;
  let resolveNewReview!: () => void;
  const delayedReview = new Promise<void>((resolve) => { resolveReview = resolve; });
  const delayedNewReview = new Promise<void>((resolve) => { resolveNewReview = resolve; });
  const first = requestView(firstRequestRef, firstReportRef);
  const second = requestView(secondRequestRef, secondReportRef);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/relative-volume-requests")) return response({ items: [first, second] });
    if (url.endsWith(firstRequestRef)) return response(first);
    if (url.endsWith(secondRequestRef)) return response(second);
    if (url.endsWith(`${firstReportRef}/reviews`)) { await delayedReview; return response({ review: reviewReceipt(firstRequestRef, firstReportRef, "old-area", 0.1, 0.2) }); }
    if (url.endsWith(`${secondReportRef}/reviews`)) { await delayedNewReview; return response({ review: reviewReceipt(secondRequestRef, secondReportRef, "new-area", 0.3, 0.4) }); }
    if (url.endsWith(firstReportRef)) return response(reportView(firstRequestRef, firstReportRef, "old-area"));
    if (url.endsWith(secondReportRef)) return response(reportView(secondRequestRef, secondReportRef, "new-area"));
    throw new Error(`unexpected ${url}`);
  }));
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={["WORK_ORDERS_WRITE"]} />);
  await select(0);
  fireEvent.click(await screen.findByRole("button", { name: "결과 검토 기록" }));
  await select(1);
  expect(await screen.findByText(/작업구역 new-area/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "결과 검토 기록" }));
  expect(await screen.findByText("결과 검토 기록 중")).toBeTruthy();
  resolveReview();
  await waitFor(() => expect(screen.getByText("결과 검토 기록 중")).toBeTruthy());
  expect(screen.queryByText(/작업구역 old-area/)).toBeNull();
  resolveNewReview();
  expect(await screen.findByText("결과 검토를 기록했습니다.")).toBeTruthy();
});

it("retires a delayed old proposal rather than restoring it after selection changes", async () => {
  let resolveProposal!: () => void;
  const delayedProposal = new Promise<void>((resolve) => { resolveProposal = resolve; });
  const first = requestView(firstRequestRef, firstReportRef);
  const second = requestView(secondRequestRef, secondReportRef);
  const firstReview = reviewReceipt(firstRequestRef, firstReportRef, "old-area", 0.1, 0.2);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/relative-volume-requests")) return response({ items: [first, second] });
    if (url.endsWith(firstRequestRef)) return response(first);
    if (url.endsWith(secondRequestRef)) return response(second);
    if (url === "/api/external-reobservation-proposals") { await delayedProposal; return response({ proposal: { proposalRef, version: 1, reportRef: firstReportRef, targetWorkAreas: [{ workAreaId: "old-area" }] }, approvalReceipt: null }); }
    if (url.endsWith(firstReportRef)) return response(reportView(firstRequestRef, firstReportRef, "old-area", { review: firstReview }));
    if (url.endsWith(secondReportRef)) return response(reportView(secondRequestRef, secondReportRef, "new-area"));
    throw new Error(`unexpected ${url}`);
  }));
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={["WORK_ORDERS_WRITE"]} />);
  await select(0);
  fireEvent.click(await screen.findByRole("button", { name: "이 작업구역으로 재관측 제안" }));
  await select(1);
  expect(await screen.findByText(/작업구역 new-area/)).toBeTruthy();
  resolveProposal();
  await waitFor(() => expect(screen.getByText(/작업구역 new-area/)).toBeTruthy());
  expect(screen.queryByText(`제안 ${proposalRef} · v1`)).toBeNull();
});

it("retires a delayed old approval without navigating after selection changes", async () => {
  let resolveApproval!: () => void;
  const delayedApproval = new Promise<void>((resolve) => { resolveApproval = resolve; });
  const first = requestView(firstRequestRef, firstReportRef);
  const second = requestView(secondRequestRef, secondReportRef);
  const firstReview = reviewReceipt(firstRequestRef, firstReportRef, "old-area", 0.1, 0.2);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/relative-volume-requests")) return response({ items: [first, second] });
    if (url.endsWith(firstRequestRef)) return response(first);
    if (url.endsWith(secondRequestRef)) return response(second);
    if (url === "/api/external-reobservation-proposals/approve") { await delayedApproval; return response({ proposal: { proposalRef, version: 1, reportRef: firstReportRef, targetWorkAreas: [{ workAreaId: "old-area" }] }, approvalReceipt: { successorWorkOrderId: "old-successor", receiptDigest: digest("d"), approvedAt: "2026-09-02T04:00:00Z" } }); }
    if (url.endsWith(firstReportRef)) return response(reportView(firstRequestRef, firstReportRef, "old-area", { review: firstReview, proposals: [{ proposal: { proposalRef, version: 1, reportRef: firstReportRef, targetWorkAreas: [{ workAreaId: "old-area" }] }, approvalReceipt: null }] }));
    if (url.endsWith(secondReportRef)) return response(reportView(secondRequestRef, secondReportRef, "new-area"));
    throw new Error(`unexpected ${url}`);
  }));
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={["WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]} />);
  await select(0);
  fireEvent.click(await screen.findByRole("button", { name: "재관측 후속 작업 승인" }));
  await select(1);
  expect(await screen.findByText(/작업구역 new-area/)).toBeTruthy();
  resolveApproval();
  await waitFor(() => expect(screen.getByText(/작업구역 new-area/)).toBeTruthy());
  expect(router.push).not.toHaveBeenCalled();
  expect(router.refresh).not.toHaveBeenCalled();
});

it("retires an old approval worklist refresh after selection changes", async () => {
  let signalWorklistStarted!: () => void;
  let resolveWorklist!: () => void;
  const worklistStarted = new Promise<void>((resolve) => { signalWorklistStarted = resolve; });
  const delayedWorklist = new Promise<void>((resolve) => { resolveWorklist = resolve; });
  const first = requestView(firstRequestRef, firstReportRef);
  const second = requestView(secondRequestRef, secondReportRef);
  const firstReview = reviewReceipt(firstRequestRef, firstReportRef, "old-area", 0.1, 0.2);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/relative-volume-requests")) return response({ items: [first, second] });
    if (url.endsWith(firstRequestRef)) return response(first);
    if (url.endsWith(secondRequestRef)) return response(second);
    if (url === "/api/external-reobservation-proposals/approve") return response({ proposal: { proposalRef, version: 1, reportRef: firstReportRef, targetWorkAreas: [{ workAreaId: "old-area" }] }, approvalReceipt: { successorWorkOrderId: "old-successor", receiptDigest: digest("d"), approvedAt: "2026-09-02T04:00:00Z" } });
    if (url === "/api/sites/site-1/observation-work-orders") {
      signalWorklistStarted();
      await delayedWorklist;
      return response({ workOrders: [{ workOrderId: "old-successor" }] });
    }
    if (url.endsWith(firstReportRef)) return response(reportView(firstRequestRef, firstReportRef, "old-area", { review: firstReview, proposals: [{ proposal: { proposalRef, version: 1, reportRef: firstReportRef, targetWorkAreas: [{ workAreaId: "old-area" }] }, approvalReceipt: null }] }));
    if (url.endsWith(secondReportRef)) return response(reportView(secondRequestRef, secondReportRef, "new-area"));
    throw new Error(`unexpected ${url}`);
  }));
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={["WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]} />);
  await select(0);
  fireEvent.click(await screen.findByRole("button", { name: "재관측 후속 작업 승인" }));
  await worklistStarted;
  await select(1);
  expect(await screen.findByText(/작업구역 new-area/)).toBeTruthy();
  resolveWorklist();
  await waitFor(() => expect(screen.getByText(/작업구역 new-area/)).toBeTruthy());
  expect(screen.queryByText("Core 작업 목록에서 후속 작업을 새로 고쳤습니다.")).toBeNull();
  expect(router.push).not.toHaveBeenCalled();
});

it("keeps the initial actual-Core first unapproved proposal separate from a later approved proposal", async () => {
  const request = requestView(actualCoreRequestRef, actualCoreReportRef);
  const first = actualCoreProposalView(actualCoreFirstProposalRef, "reason-0");
  const later = actualCoreProposalView(actualCoreLaterProposalRef, "reason-1", actualCoreApprovalReceipt());
  const view = reportView(actualCoreRequestRef, actualCoreReportRef, "wa-site-a-0001", {
    review: reviewReceipt(actualCoreRequestRef, actualCoreReportRef, "wa-site-a-0001", 0.3, 0.4),
    proposals: [first, later],
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/relative-volume-requests")) return response({ items: [request] });
    if (url.endsWith(actualCoreRequestRef)) return response(request);
    if (url.endsWith(actualCoreReportRef)) return response(view);
    throw new Error(`unexpected ${url}`);
  }));
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={["WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]} />);
  await select(0);
  await screen.findByText("재관측 제안이 기록되었습니다.");
  fireEvent.click(screen.getByText("전문가 정보"));
  const firstCard = await screen.findByText((_, element) => element?.tagName === "P" && element.textContent?.includes(`제안 ${actualCoreFirstProposalRef} · v1`) === true);
  await waitFor(() => expect(firstCard.parentElement?.textContent).not.toContain(actualCoreSuccessorWorkOrderId));
  expect(screen.getByRole("button", { name: "재관측 후속 작업 승인" })).toBeTruthy();
});

it("retains a just-created nonfirst actual-Core proposal through refresh and approves that exact proposal", async () => {
  const request = requestView(actualCoreRequestRef, actualCoreReportRef);
  const first = actualCoreProposalView(actualCoreFirstProposalRef, "reason-0");
  const later = actualCoreProposalView(actualCoreLaterProposalRef, "reason-1");
  const approvedLater = actualCoreProposalView(actualCoreLaterProposalRef, "reason-1", actualCoreApprovalReceipt());
  const reviewed = reportView(actualCoreRequestRef, actualCoreReportRef, "wa-site-a-0001", {
    review: reviewReceipt(actualCoreRequestRef, actualCoreReportRef, "wa-site-a-0001", 0.3, 0.4),
    proposals: [],
  });
  const refreshed = { ...reviewed, proposals: [first, later] };
  let reportReads = 0;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/relative-volume-requests")) return response({ items: [request] });
    if (url.endsWith(actualCoreRequestRef)) return response(request);
    if (url.endsWith(actualCoreReportRef)) {
      reportReads += 1;
      return response(reportReads === 1 ? reviewed : refreshed);
    }
    if (url === "/api/external-reobservation-proposals") return response(later);
    if (url === "/api/external-reobservation-proposals/approve") return response(approvedLater);
    if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [{ workOrderId: actualCoreSuccessorWorkOrderId }] });
    throw new Error(`unexpected ${url} ${init?.method ?? "GET"}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={["WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]} />);
  await select(0);
  fireEvent.click(await screen.findByRole("button", { name: "이 작업구역으로 재관측 제안" }));
  await waitFor(() => expect(reportReads).toBe(2));
  await waitFor(() => expect(screen.queryByText((_, element) => element?.tagName === "P" && element.textContent?.includes(`제안 ${actualCoreFirstProposalRef} · v1`) === true)).toBeNull());
  expect(screen.getByText((_, element) => element?.tagName === "P" && element.textContent?.includes(`제안 ${actualCoreLaterProposalRef} · v1`) === true)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "재관측 후속 작업 승인" }));
  await waitFor(() => {
    const approvalCall = fetchMock.mock.calls.find(([url]) => url === "/api/external-reobservation-proposals/approve")?.[1] as RequestInit;
    expect(JSON.parse(String(approvalCall.body))).toEqual({ proposalRef: actualCoreLaterProposalRef, expectedVersion: 1 });
  });
  await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/field/work-orders/${actualCoreSuccessorWorkOrderId}`));
});

it("renders a full retained Core review receipt with known and unknown RMSE values and source bindings", async () => {
  const request = requestView(firstRequestRef, firstReportRef);
  const known = reviewReceipt(firstRequestRef, firstReportRef, "audit-area", 0.12, null);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/relative-volume-requests")) return response({ items: [request] });
    if (url.endsWith(firstRequestRef)) return response(request);
    if (url.endsWith(firstReportRef)) return response(reportView(firstRequestRef, firstReportRef, "audit-area", { review: known }));
    throw new Error(`unexpected ${url}`);
  }));
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={[]} />);
  await select(0);
  fireEvent.click(await screen.findByText("전문가용 검토 기록"));
  expect(screen.getByText(`검토 다이제스트: ${digest("c")}`)).toBeTruthy();
  expect(screen.getByText("기준 독립 검사점 RMSE: 0.12m")).toBeTruthy();
  expect(screen.getByText("현재 독립 검사점 RMSE: 기록 없음")).toBeTruthy();
  expect(screen.getByText("검토 원본: 조직 org-1 · 현장 site-1 · 작업 work-1")).toBeTruthy();
  expect(screen.getByText(`검토 보고서: ${firstReportRef} · 요청 ${firstRequestRef}`)).toBeTruthy();
  expect(screen.getByText(`검토 결정: external-use-decision-${"f".repeat(32)} · ${digest("f")}`)).toBeTruthy();
  expect(screen.getByText("검토 한계: RELATIVE_VOLUME_IS_OPERATIONAL_ONLY")).toBeTruthy();
});
