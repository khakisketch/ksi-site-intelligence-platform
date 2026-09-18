// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = { push: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { ExternalResultWorkflowPanel } from "@/app/field/ExternalResultWorkflowPanel";
import type { ExternalRelativeVolumeReportView, ExternalResultReview, ExternalSingleVolumeReportView, ExternalSingleVolumeResultReview } from "@/lib/core-api/external-result-workflow";

const fetchMock = vi.fn();
const digest = (character: string) => `sha256:${character.repeat(64)}`;
const decision = {
  decisionId: `external-use-decision-${"a".repeat(32)}`,
  decisionDigest: digest("a"),
  verdict: "ELIGIBLE" as const,
  reasons: [],
  remediations: [],
};
const requestRef = `external-relative-volume-${"b".repeat(32)}`;
const reportRef = `external-relative-volume-report-${"c".repeat(32)}`;
const proposalRef = `erop-v1-${"d".repeat(64)}`;

function response(value: unknown, ok = true) {
  return { ok, json: async () => value };
}

function reportView(): ExternalRelativeVolumeReportView {
  return {
    request: {
      contractVersion: "external-relative-volume-request.v1",
      requestId: requestRef,
      currentWorkOrderId: "work-1",
      decisionId: decision.decisionId,
      decisionDigest: decision.decisionDigest,
      baseline: {
        subject: { organizationId: "org-1", siteId: "site-1", workOrderId: "baseline", submissionId: "submission-a", revision: 1, submissionDigest: digest("b"), manifestDigest: digest("c") },
        inspectionReportDigest: digest("d"), dsmArtifactId: "dsm-a", observedSha256: digest("e"), observedSizeBytes: 2, observedCrsDigest: digest("f"), observedVerticalReferenceDigest: digest("0"), capturedFrom: "2026-09-01T00:00:00Z", capturedTo: "2026-09-01T00:01:00Z",
      },
      current: {
        subject: { organizationId: "org-1", siteId: "site-1", workOrderId: "work-1", submissionId: "submission-b", revision: 2, submissionDigest: digest("1"), manifestDigest: digest("2") },
        inspectionReportDigest: digest("3"), dsmArtifactId: "dsm-b", observedSha256: digest("4"), observedSizeBytes: 2, observedCrsDigest: digest("f"), observedVerticalReferenceDigest: digest("0"), capturedFrom: "2026-09-02T00:00:00Z", capturedTo: "2026-09-02T00:01:00Z",
      },
      evidenceRecordDigests: [digest("5")], validationPolicyDigest: digest("6"), executionPolicyDigest: digest("7"),
      zoneSnapshot: { contractVersion: "external-volume-zone-snapshot.v1", organizationId: "org-1", siteId: "site-1", workAreaId: "area-1", revision: 1, polygon: {}, crs: "EPSG:5186", observedCrsDigest: digest("f"), analysisVerticalReferenceDigest: digest("0"), definitionDigest: digest("8") },
      issuedAt: "2026-09-02T01:00:00Z", idempotencyKey: "core-key", requestDigest: digest("9"),
    },
    report: {
      contractVersion: "external-relative-volume-report.v1", reportId: reportRef, requestId: requestRef, requestDigest: digest("9"),
      payload: { factClass: "OBSERVED", requestDigest: digest("9"), decisionDigest: decision.decisionDigest, baselineDsmDigest: digest("e"), currentDsmDigest: digest("4"), zoneSnapshotDigest: digest("8"), executionPolicyDigest: digest("7"), algorithmBuildDigest: digest("a"), configDigest: digest("b"), metrics: { zoneCellCount: 100, commonValidCellCount: 80, zoneAreaM2: 100, measuredAreaM2: 80, commonValidFraction: 0.8, cutM3: 4, fillM3: 10, netM3: 6, thresholdM: 0.1, uncertaintyM3: null, uncertaintyNote: "independent checkpoint RMSE is retained by Core evidence" } },
      measurementPayloadDigest: digest("c"), workerInstanceId: "worker", leaseAcquisitionId: "lease", leaseGeneration: 1, computedAt: "2026-09-02T02:00:00Z", reportedAt: "2026-09-02T02:01:00Z", reportDigest: digest("d"),
    },
    executionPolicy: { contractVersion: "external-relative-volume-execution-policy.v1", policyId: "policy", version: 1, algorithmBuildDigest: digest("a"), configDigest: digest("b"), resourceEnvelopeDigest: digest("f"), authorityRecordDigest: digest("0"), thresholdM: 0.1, minimumCommonValidFraction: 0.75, uncertaintyMethod: "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1", syntheticTestOnly: true, policyDigest: digest("e") },
    review: null,
    proposals: [],
  };
}

function reviewReceipt(): ExternalResultReview {
  const view = reportView();
  return {
    contractVersion: "external-result-review-receipt.v1",
    reviewRef: `err-v1-${"e".repeat(64)}`,
    organizationId: "org-1",
    siteId: "site-1",
    sourceWorkOrderId: "work-1",
    reportRef,
    request: view.request,
    report: view.report,
    authority: {
      contractVersion: "external-result-review-authority.v1",
      organizationId: "org-1",
      siteId: "site-1",
      currentWorkOrderId: "work-1",
      decisionId: decision.decisionId,
      decisionDigest: decision.decisionDigest,
      compatibilityMappingDigest: digest("f"),
      baseline: view.request.baseline,
      current: view.request.current,
      evidenceRecordDigests: view.request.evidenceRecordDigests,
      validationPolicyDigest: view.request.validationPolicyDigest,
      zoneSnapshot: view.request.zoneSnapshot,
      executionPolicy: view.executionPolicy,
      authorizedActorIds: ["operator-1"],
      validFrom: "2026-09-02T00:00:00Z",
      validUntil: "2026-09-03T00:00:00Z",
      historicalAuthorityDigest: digest("0"),
      baselineRmseM: 0.05,
      currentRmseM: 0.06,
      maximumZoneCellCount: 100,
      maximumZoneAreaM2: 100,
      syntheticTestOnly: true,
      authorityDigest: digest("1"),
    },
    decision: {
      contractVersion: "external-pair-use-decision.v1",
      decisionId: decision.decisionId,
      decisionDigest: decision.decisionDigest,
    } as ExternalResultReview["decision"],
    factualLimitations: ["recorded", "source only", "not current authority"],
    reviewedAt: "2026-09-02T03:00:00Z",
    reviewDigest: digest("e"),
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", { randomUUID: () => "stable-key" });
  router.push.mockReset();
  router.refresh.mockReset();
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
    throw new Error(`unexpected fetch ${url}`);
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("opens only a server-validated exact report link without inventing a request selection", async () => {
  const view = reportView();
  render(
    <ExternalResultWorkflowPanel
      workOrderId="work-1"
      siteId="site-1"
      decision={null}
      permissions={[]}
      initialReport={{ reportRef, reportDigest: digest("d"), view, workAreaName: "동측 절성토 구역" }}
    />,
  );

  expect(await screen.findByRole("heading", { name: "외부 상대 물량 비교 결과" })).toBeTruthy();
  expect(screen.getByText(/작업구역 동측 절성토 구역/)).toBeTruthy();
  expect(screen.getByText("절토")).toBeTruthy();
  expect(screen.getByText("4 m³")).toBeTruthy();
  expect(screen.getByText("순변화")).toBeTruthy();
  expect(screen.getByText("+6 m³")).toBeTruthy();
  expect(screen.getByText(/공통 유효 영역 80%/)).toBeTruthy();
  expect(screen.getByText(/기준 촬영 2026\. 9\. 1\./)).toBeTruthy();
  expect(screen.getByText(/현재 촬영 2026\. 9\. 2\./)).toBeTruthy();
  expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith(`/${reportRef}`))).toHaveLength(0);
});

it("hydrates a retained proposal from an exact initial report and links its Core-created successor", async () => {
  const view = reportView();
  view.review = reviewReceipt();
  view.proposals = [{
    proposal: {
      proposalRef,
      version: 1,
      reviewRef: view.review!.reviewRef,
      reviewDigest: digest("e"),
      reportRef,
      reportDigest: digest("d"),
      decisionDigest: decision.decisionDigest,
      zoneDigest: digest("8"),
      evidenceDigests: [digest("5")],
      targetWorkAreas: [{ workAreaId: "area-1", revision: 1, snapshotDigest: digest("8") }],
      reason: null,
      proposalDigest: digest("f"),
      createdAt: "2026-09-02T03:30:00Z",
    },
    approvalReceipt: { successorWorkOrderId: "successor-1", receiptDigest: digest("a"), approvedAt: "2026-09-02T04:00:00Z" },
  }];
  render(
    <ExternalResultWorkflowPanel
      workOrderId="work-1"
      siteId="site-1"
      decision={null}
      permissions={["WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]}
      initialReport={{ reportRef, reportDigest: digest("d"), view }}
    />,
  );

  expect(await screen.findByText("재관측 제안이 기록되었습니다.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "이 작업구역으로 재관측 제안" })).toBeNull();
  expect(screen.getByRole("link", { name: "후속 작업 보기" }).getAttribute("href")).toBe("/field/work-orders/successor-1");
});

it("keeps an unselected or restricted Core decision from issuing a browser authority request", async () => {
  const { rerender } = render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={[]} />);
  expect(await screen.findByText("현재 선택에서 상대 물량 비교를 요청하세요.")).toBeTruthy();
  rerender(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={{ ...decision, verdict: "BLOCKED", remediations: ["독립 검사점 증거를 보완하세요."] }} permissions={["SITES_WRITE"]} />);
  expect(await screen.findByText("현재 선택으로는 상대 물량 비교를 요청할 수 없습니다.")).toBeTruthy();
  expect(screen.getByText(/독립 검사점 증거를 보완하세요\./)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "상대 물량 비교 요청" })).toBeNull();
});

it("keeps results readable but blocks new comparison, review, and successor requests after closure", async () => {
  const view = reportView();
  render(
    <ExternalResultWorkflowPanel
      workOrderId="work-1"
      siteId="site-1"
      decision={decision}
      permissions={["SITES_WRITE", "WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]}
      initialReport={{ reportRef, reportDigest: digest("d"), view }}
      newIntentAllowed={false}
    />,
  );

  expect(await screen.findByRole("heading", { name: "외부 상대 물량 비교 결과" })).toBeTruthy();
  expect(screen.getByText(/업무 종료 상태입니다. 새 비교·검토·재관측 요청은 시작할 수 없지만/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "상대 물량 비교 요청" })).toBeNull();
  expect(screen.queryByRole("button", { name: "결과 검토 기록" })).toBeNull();
  expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toBe(false);
});

it("keeps a closed result-only view from inviting a new comparison", async () => {
  const view = reportView();
  render(
    <ExternalResultWorkflowPanel
      workOrderId="work-1"
      siteId="site-1"
      decision={null}
      permissions={[]}
      initialReport={{ reportRef, reportDigest: digest("d"), view }}
      newIntentAllowed={false}
    />,
  );

  expect(await screen.findByText("업무 종료된 작업입니다. 기존 비교 결과와 요청 기록만 확인할 수 있습니다.")).toBeTruthy();
  expect(screen.queryByText("현재 선택에서 상대 물량 비교를 요청하세요.")).toBeNull();
});

it("replays a frozen proposal after closure and a lost response", async () => {
  const view = reportView();
  view.review = reviewReceipt();
  const posts: RequestInit[] = [];
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/external-reobservation-proposals") {
      posts.push(init!);
      throw new Error("lost response");
    }
    return response({ items: [] });
  });
  const props = {
    workOrderId: "work-1",
    siteId: "site-1",
    decision: null,
    permissions: ["WORK_ORDERS_WRITE"],
    initialReport: { reportRef, reportDigest: digest("d"), view },
  };
  const { rerender } = render(<ExternalResultWorkflowPanel {...props} />);

  fireEvent.click(await screen.findByRole("button", { name: "이 작업구역으로 재관측 제안" }));
  await screen.findByText("재관측 제안 상태를 확인하지 못했습니다. 같은 보고서와 작업구역으로 재시도합니다.");
  rerender(<ExternalResultWorkflowPanel {...props} newIntentAllowed={false} />);
  fireEvent.click(screen.getByRole("button", { name: "이 작업구역으로 재관측 제안" }));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1].body).toBe(posts[0].body);
  expect(posts[1].headers).toEqual(posts[0].headers);
});

it("reuses a frozen issue key after a lost response and clears busy ownership when selection changes", async () => {
  let firstSignal: AbortSignal | undefined;
  let attempts = 0;
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests" && !init?.method) return Promise.resolve(response({ items: [] }));
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests" && init?.method === "POST") {
      attempts += 1;
      if (attempts === 1) return Promise.resolve({ ok: false, json: async () => ({ code: "AUTHORITY_UNAVAILABLE" }) });
      if (attempts === 2) {
        firstSignal = init.signal ?? undefined;
        return new Promise(() => undefined);
      }
      return Promise.resolve(response({ verdict: "ISSUED", request: { requestRef, status: "QUEUED", reportRef: null }, detail: null }));
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  const nextDecision = { ...decision, decisionId: `external-use-decision-${"f".repeat(32)}`, decisionDigest: digest("f") };
  const { rerender } = render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={decision} permissions={["SITES_WRITE"]} />);
  fireEvent.click(await screen.findByRole("button", { name: "상대 물량 비교 요청" }));
  expect(await screen.findByText("비교에 필요한 기준이나 증거를 지금 사용할 수 없습니다. 현재 선택을 다시 확인한 뒤 재시도하세요.")).toBeTruthy();
  const firstCall = fetchMock.mock.calls.filter((call) => call[1]?.method === "POST")[0][1] as RequestInit;
  fireEvent.click(screen.getByRole("button", { name: "상대 물량 비교 요청" }));
  await waitFor(() => expect(firstSignal).toBeDefined());
  const retryCall = fetchMock.mock.calls.filter((call) => call[1]?.method === "POST")[1][1] as RequestInit;
  expect((firstCall.headers as Record<string, string>)["idempotency-key"]).toBe((retryCall.headers as Record<string, string>)["idempotency-key"]);

  rerender(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={nextDecision} permissions={["SITES_WRITE"]} />);
  expect(firstSignal?.aborted).toBe(true);
  fireEvent.click(await screen.findByRole("button", { name: "상대 물량 비교 요청" }));
  await waitFor(() => expect(attempts).toBe(3));
});

it("loads a retained work-order report without a current pair decision, renders metrics only after coverage passes, keeps unknown uncertainty unknown, and exposes immutable provenance", async () => {
  const request = { requestRef, status: "SUCCEEDED", reportRef, reportDigest: digest("d"), deadlineAt: "2000-01-01T00:00:00Z" };
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [request] });
    if (url.endsWith(`/${requestRef}`)) return response(request);
    if (url.endsWith(`/${reportRef}`)) return response(reportView());
    throw new Error(`unexpected fetch ${url}`);
  });
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={[]} />);
  fireEvent.click(await screen.findByRole("button", { name: /비교 요청 상태/ }));
  expect(screen.queryByText(/마감 시각 경과/)).toBeNull();
  expect(await screen.findByText("4 m³")).toBeTruthy();
  expect(screen.getByText("불확실성은 아직 산정되지 않았습니다. independent checkpoint RMSE is retained by Core evidence")).toBeTruthy();
  fireEvent.click(screen.getByText("전문가용 기록 및 검증 정보"));
  expect(screen.getByText(`구역 ID area-1 · rev 1 · 정의 ${digest("8")}`)).toBeTruthy();
  expect(screen.getByText(`독립 검사점 증거 기록: ${digest("5")}`)).toBeTruthy();
});

it("distinguishes a pending Core request from a failed one and keeps the failed result out of report metrics", async () => {
  const pending = { requestRef: `external-relative-volume-${"e".repeat(32)}`, status: "QUEUED", reportRef: null, reportDigest: null, issuedAt: "2026-09-02T00:00:00Z", deadlineAt: "2099-01-01T00:00:00Z" };
  const failed = { requestRef, status: "FAILED", reportRef: null, reportDigest: null, issuedAt: "2026-09-02T00:00:00Z", deadlineAt: "2099-01-01T00:00:00Z" };
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [pending, failed] });
    if (url.endsWith(`/${requestRef}`)) return response(failed);
    throw new Error(`unexpected fetch ${url}`);
  });
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={[]} />);
  expect(await screen.findByText(/대기 · 2026-09-02T00:00:00Z/)).toBeTruthy();
  expect(screen.getByText(/실패 · 2026-09-02T00:00:00Z/)).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", { name: "비교 요청 상태" })[1]);
  expect(await screen.findByText("이 상대 물량 비교를 완료하지 못했습니다. 결과 수치는 표시하지 않습니다.")).toBeTruthy();
  expect(screen.queryByText(/절토/)).toBeNull();
});

it("keeps the last verified queued request visible while it performs a bounded GET-only refresh and stops after unmount", async () => {
  let requestListReads = 0;
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") {
      requestListReads += 1;
      return response({ items: [{ requestRef, status: "QUEUED", reportRef: null, reportDigest: null, issuedAt: "2026-09-02T00:00:00Z", deadlineAt: "2099-01-01T00:00:00Z" }] });
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  const { unmount } = render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={[]} />);
  await screen.findByText(/대기 · 2026-09-02T00:00:00Z/);
  vi.useFakeTimers();
  try {
    fireEvent.click(screen.getByRole("button", { name: "목록 새로고침" }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText(/대기 · 2026-09-02T00:00:00Z/)).toBeTruthy();
    for (let attempt = 0; attempt < 12; attempt += 1) await vi.advanceTimersByTimeAsync(5_000);
    expect(requestListReads).toBe(8);
    unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(requestListReads).toBe(8);
  } finally {
    vi.useRealTimers();
  }
});

it("retains a verified list and explains an unknown request status instead of rendering it as a terminal state", async () => {
  let reads = 0;
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") {
      reads += 1;
      return response({ items: [{ requestRef, status: reads === 1 ? "QUEUED" : "UNKNOWN", reportRef: null, reportDigest: null, issuedAt: "2026-09-02T00:00:00Z", deadlineAt: "2099-01-01T00:00:00Z" }] });
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={[]} />);
  expect(await screen.findByText(/대기 · 2026-09-02T00:00:00Z/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "목록 새로고침" }));
  expect(await screen.findByText("요청 상태 형식을 확인하지 못했습니다. 마지막으로 확인한 상태를 표시합니다. 새로고침으로 다시 시도하세요.")).toBeTruthy();
  expect(screen.getByText(/대기 · 2026-09-02T00:00:00Z/)).toBeTruthy();
  expect(screen.queryByText("undefined")).toBeNull();
});

it("rejects an unknown status in the first request list response with an explicit error", async () => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [{ requestRef, status: "UNKNOWN", reportRef: null, reportDigest: null }] });
    throw new Error(`unexpected fetch ${url}`);
  });
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={[]} />);
  expect(await screen.findByText("요청 상태 형식을 확인하지 못했습니다. 목록을 다시 확인하세요.")).toBeTruthy();
  expect(screen.queryByText("undefined")).toBeNull();
});

it("rejects an unknown selected request status without replacing the verified request list", async () => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [{ requestRef, status: "QUEUED", reportRef: null, reportDigest: null, issuedAt: "2026-09-02T00:00:00Z", deadlineAt: "2099-01-01T00:00:00Z" }] });
    if (url.endsWith(`/${requestRef}`)) return response({ requestRef, status: "UNKNOWN", reportRef: null, reportDigest: null });
    throw new Error(`unexpected fetch ${url}`);
  });
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={[]} />);
  fireEvent.click(await screen.findByRole("button", { name: "비교 요청 상태" }));
  expect(await screen.findByText("요청 상태 형식을 확인하지 못했습니다. 마지막으로 확인한 요청과 목록을 유지합니다. 다시 시도하세요.")).toBeTruthy();
  expect(screen.getByText(/대기 · 2026-09-02T00:00:00Z/)).toBeTruthy();
  expect(screen.queryByText("undefined")).toBeNull();
});

it("rejects an unknown status returned by a comparison issue without claiming that a request was issued", async () => {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests" && !init?.method) return response({ items: [] });
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests" && init?.method === "POST") return response({ verdict: "ISSUED", request: { requestRef, status: "UNKNOWN", reportRef: null }, detail: null });
    throw new Error(`unexpected fetch ${url}`);
  });
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={decision} permissions={["SITES_WRITE"]} />);
  fireEvent.click(await screen.findByRole("button", { name: "상대 물량 비교 요청" }));
  expect(await screen.findByText("요청 상태 형식을 확인하지 못했습니다. 같은 선택으로 다시 시도합니다.")).toBeTruthy();
  expect(screen.queryByText("외부 상대 물량 비교를 요청했습니다.")).toBeNull();
  expect(screen.queryByText("undefined")).toBeNull();
});

it("hides all volume metric cards when Core coverage is below its execution policy", async () => {
  const failed = reportView();
  failed.executionPolicy.minimumCommonValidFraction = 0.9;
  const request = { requestRef, status: "SUCCEEDED", reportRef, reportDigest: digest("d") };
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [request] });
    if (url.endsWith(`/${requestRef}`)) return response(request);
    if (url.endsWith(`/${reportRef}`)) return response(failed);
    throw new Error(`unexpected fetch ${url}`);
  });
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={decision} permissions={[]} />);
  fireEvent.click(await screen.findByRole("button", { name: /비교 요청 상태/ }));
  expect(await screen.findByText("적용 범위가 측정 기준을 충족하지 않아 수량 카드를 표시하지 않습니다.")).toBeTruthy();
  expect(screen.queryByText(/절토 4m³/)).toBeNull();
});

it("records review, proposes the exact report zone, approves separately, refreshes the real work list, and navigates only to Core's successor", async () => {
  const request = { requestRef, status: "SUCCEEDED", reportRef, reportDigest: digest("d") };
  let reported = false;
  let proposed = false;
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [request] });
    if (url.endsWith(`/${requestRef}`)) return response(request);
    if (url.endsWith(`/${reportRef}`) && !url.endsWith("/reviews")) return response({
      ...reportView(),
      review: reported ? reviewReceipt() : null,
      proposals: proposed ? [{ proposal: { proposalRef, version: 2, reportRef, targetWorkAreas: [{ workAreaId: "area-1" }] }, approvalReceipt: null }] : [],
    });
    if (url.endsWith("/reviews")) { reported = true; return response({ review: { reviewRef: "review-1" } }); }
    if (url === "/api/external-reobservation-proposals") { proposed = true; return response({ proposal: { proposalRef, version: 2, reportRef, targetWorkAreas: [{ workAreaId: "area-1" }] }, approvalReceipt: null }); }
    if (url === "/api/external-reobservation-proposals/approve") return response({ proposal: { proposalRef, version: 2, reportRef }, approvalReceipt: { successorWorkOrderId: "successor-1", receiptDigest: digest("f"), approvedAt: "2026-09-02T04:00:00Z" } });
    if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [{ workOrderId: "successor-1", name: "Core successor" }] });
    throw new Error(`unexpected fetch ${url} ${init?.method ?? "GET"}`);
  });
  render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={decision} permissions={["WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]} />);
  fireEvent.click(await screen.findByRole("button", { name: /비교 요청 상태/ }));
  fireEvent.click(await screen.findByRole("button", { name: "결과 검토 기록" }));
  await screen.findByText("결과 검토를 기록했습니다.");
  fireEvent.change(screen.getByLabelText("재관측 제안 사유"), { target: { value: "현장 확인" } });
  fireEvent.click(screen.getByRole("button", { name: "이 작업구역으로 재관측 제안" }));
  await screen.findByText("재관측 제안이 기록되었습니다.");
  const proposalCall = fetchMock.mock.calls.find(([url]) => url === "/api/external-reobservation-proposals")?.[1] as RequestInit;
  expect(JSON.parse(String(proposalCall.body))).toEqual({ reportRef, targetWorkAreaIds: ["area-1"], reason: "현장 확인" });
  fireEvent.click(screen.getByRole("button", { name: "재관측 후속 작업 승인" }));
  await waitFor(() => expect(router.push).toHaveBeenCalledWith("/field/work-orders/successor-1"));
  expect(router.refresh).toHaveBeenCalled();
});

const singleRequestRef = `external-single-volume-${"6".repeat(32)}`;
const singleReportRef = `external-single-volume-report-${"7".repeat(32)}`;
const singleDecision = {
  decisionId: `external-use-decision-${"5".repeat(32)}`,
  decisionDigest: digest("5"),
  verdict: "ELIGIBLE" as const,
  reasons: [],
  remediations: [],
};

function singleReportView(overrides: { uncertaintyM3?: number | null; boundaryValidFraction?: number } = {}): ExternalSingleVolumeReportView {
  return {
    request: {
      contractVersion: "external-single-volume-request.v1",
      requestId: singleRequestRef,
      currentWorkOrderId: "work-1",
      decisionId: singleDecision.decisionId,
      decisionDigest: singleDecision.decisionDigest,
      target: {
        subject: { organizationId: "org-1", siteId: "site-1", workOrderId: "work-1", submissionId: "submission-s", revision: 1, submissionDigest: digest("1"), manifestDigest: digest("2") },
        inspectionReportDigest: digest("3"), dsmArtifactId: "dsm-s", observedSha256: digest("4"), observedSizeBytes: 2, observedCrsDigest: digest("f"), observedVerticalReferenceDigest: digest("0"), capturedFrom: "2026-09-15T00:00:00Z", capturedTo: "2026-09-15T00:30:00Z",
      },
      evidenceRecordDigests: [digest("5")], validationPolicyDigest: digest("6"), executionPolicyDigest: digest("7"),
      zoneSnapshot: { contractVersion: "external-volume-zone-snapshot.v1", organizationId: "org-1", siteId: "site-1", workAreaId: "pile-1", revision: 1, polygon: {}, crs: "EPSG:5186", observedCrsDigest: digest("f"), analysisVerticalReferenceDigest: digest("0"), definitionDigest: digest("8") },
      issuedAt: "2026-09-15T01:00:00Z", idempotencyKey: "core-key", requestDigest: digest("9"),
    },
    report: {
      contractVersion: "external-single-volume-report.v1", reportId: singleReportRef, requestId: singleRequestRef, requestDigest: digest("9"),
      payload: {
        factClass: "OBSERVED", requestDigest: digest("9"), decisionDigest: singleDecision.decisionDigest, targetDsmDigest: digest("4"), zoneSnapshotDigest: digest("8"), executionPolicyDigest: digest("7"), algorithmBuildDigest: digest("a"), configDigest: digest("b"),
        metrics: {
          zoneCellCount: 100, commonValidCellCount: 95, zoneAreaM2: 100, measuredAreaM2: 95, commonValidFraction: 0.95,
          cutM3: 0.5, fillM3: 1234.5, netM3: 1234, thresholdM: 0.1,
          uncertaintyM3: overrides.uncertaintyM3 === undefined ? 12.25 : overrides.uncertaintyM3,
          uncertaintyNote: "boundary base RSS bound",
          baseRoughnessM: 0.123, boundaryCellCount: 40, boundarySampleCount: 38,
          boundaryValidFraction: overrides.boundaryValidFraction ?? 0.95,
        },
      },
      measurementPayloadDigest: digest("c"), workerInstanceId: "worker", leaseAcquisitionId: "lease", leaseGeneration: 1, computedAt: "2026-09-15T02:00:00Z", reportedAt: "2026-09-15T02:01:00Z", reportDigest: digest("d"),
    },
    executionPolicy: {
      contractVersion: "external-single-volume-execution-policy.v1", policyId: "single-policy", version: 1, algorithmBuildDigest: digest("a"), configDigest: digest("b"),
      thresholdM: 0.1, minimumCommonValidFraction: 0.75, minimumBoundaryValidFraction: 0.8,
      uncertaintyMethod: "SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1", baseSurfaceMethod: "BOUNDARY_LINEAR_INTERPOLATION_V1",
      resourceEnvelopeDigest: digest("f"), authorityRecordDigest: digest("0"), syntheticTestOnly: true, policyDigest: digest("e"),
    },
  };
}

function singleRequest(status: "QUEUED" | "SUCCEEDED" | "FAILED") {
  return {
    requestRef: singleRequestRef,
    status,
    currentWorkOrderId: "work-1",
    decisionDigest: singleDecision.decisionDigest,
    issuedAt: "2026-09-15T01:00:00Z",
    deadlineAt: "2099-01-01T00:00:00Z",
    reportRef: status === "SUCCEEDED" ? singleReportRef : null,
    reportDigest: status === "SUCCEEDED" ? digest("d") : null,
  };
}

function singleReviewReceipt(targetRmseM: number | null = 0.04): ExternalSingleVolumeResultReview {
  const view = singleReportView();
  return {
    contractVersion: "external-single-volume-result-review-receipt.v1",
    reviewRef: `err-v1-${"e".repeat(64)}`,
    organizationId: "org-1",
    siteId: "site-1",
    sourceWorkOrderId: "work-1",
    reportRef: singleReportRef,
    request: view.request,
    report: view.report,
    authority: {
      contractVersion: "external-single-volume-result-review-authority.v1",
      organizationId: "org-1",
      siteId: "site-1",
      currentWorkOrderId: "work-1",
      decisionId: singleDecision.decisionId,
      decisionDigest: singleDecision.decisionDigest,
      compatibilityMappingDigest: digest("f"),
      target: view.request.target,
      evidenceRecordDigests: view.request.evidenceRecordDigests,
      validationPolicyDigest: view.request.validationPolicyDigest,
      zoneSnapshot: view.request.zoneSnapshot,
      executionPolicy: view.executionPolicy,
      authorizedActorIds: ["operator-1"],
      validFrom: "2026-09-15T00:00:00Z",
      validUntil: "2026-09-16T00:00:00Z",
      historicalAuthorityDigest: digest("0"),
      targetRmseM,
      maximumZoneCellCount: 100,
      maximumZoneAreaM2: 100,
      syntheticTestOnly: true,
      authorityDigest: digest("1"),
    },
    decision: {
      contractVersion: "external-single-volume-decision.v1",
      decisionId: singleDecision.decisionId,
      subject: view.request.target.subject,
      subjectDigest: digest("2"),
      use: "SINGLE_VOLUME",
      policyDigest: null,
      inspectionReportDigest: digest("3"),
      evidenceRecordDigests: view.request.evidenceRecordDigests,
      zone: null,
      compatibilityMappingDigest: digest("f"),
      verdict: "ELIGIBLE",
      reasons: [],
      remediations: [],
      decidedAt: "2026-09-15T00:00:00Z",
      decisionDigest: singleDecision.decisionDigest,
    },
    factualLimitations: ["recorded", "source only", "not current authority"],
    reviewedAt: "2026-09-15T03:00:00Z",
    reviewDigest: digest("e"),
  };
}

describe("SINGLE_VOLUME measurement", () => {
  it("issues an ELIGIBLE single-volume decision, polls the request, and mounts review on the single review path", async () => {
    const posts: Array<{ url: string; body: unknown; key: string }> = [];
    let itemReads = 0;
    let reported = false;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests" && !init?.method) return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests" && init?.method === "POST") {
        posts.push({ url, body: JSON.parse(String(init.body)), key: (init.headers as Record<string, string>)["idempotency-key"] });
        return response({ verdict: "ISSUED", request: singleRequest("QUEUED"), detail: null });
      }
      if (url === `/api/observation-work-orders/work-1/single-volume-requests/${singleRequestRef}`) {
        itemReads += 1;
        return response(singleRequest(itemReads === 1 ? "QUEUED" : "SUCCEEDED"));
      }
      if (url === `/api/external-single-volume-reports/${singleReportRef}/reviews`) {
        reported = true;
        return response({ review: { reviewRef: "review-1" } });
      }
      if (url === `/api/external-single-volume-reports/${singleReportRef}`) {
        return response({ ...singleReportView(), review: reported ? singleReviewReceipt() : null, proposals: [] });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["SITES_WRITE", "WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]} />);
    const issueButton = await screen.findByRole("button", { name: "단일 시점 체적 측정 요청" });
    vi.useFakeTimers();
    try {
      // act() flushes React's passive effects, whose scheduler is not driven by fake timers.
      await act(async () => { fireEvent.click(issueButton); });
      await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
      expect(posts).toEqual([{ url: "/api/observation-work-orders/work-1/single-volume-requests", body: { decisionRef: singleDecision.decisionId }, key: "console-stable-key" }]);
      expect(itemReads).toBe(1);
      expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith("/api/external-single-volume-reports/"))).toBe(false);
      await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
      expect(itemReads).toBe(2);
    } finally {
      vi.useRealTimers();
    }

    expect(await screen.findByText("1,234.5 m³")).toBeTruthy();
    expect(screen.getByText("체적")).toBeTruthy();
    expect(screen.getByText("±12.25 m³")).toBeTruthy();
    expect(screen.getByText("기저면 거칠기")).toBeTruthy();
    expect(screen.getByText("0.12 m")).toBeTruthy();
    expect(screen.getByText("경계 유효 비율")).toBeTruthy();
    expect(screen.getByText("95%")).toBeTruthy();
    expect(document.body.textContent ?? "").not.toContain("준비 중");
    expect(screen.queryByText("순변화")).toBeNull();
    expect(screen.queryByText(/기준 촬영/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "결과 검토 기록" }));
    await screen.findByText("결과 검토를 기록했습니다.");
    expect(fetchMock.mock.calls.some(([url]) => String(url) === `/api/external-single-volume-reports/${singleReportRef}/reviews`)).toBe(true);
    expect(screen.getByText("대상: 이 측정에 사용한 작업구역")).toBeTruthy();
    expect(screen.queryByText("대상: 이 비교에 사용한 작업구역")).toBeNull();
  });

  it("proposes the exact single report zone, approves the successor, and shows only the target audit detail", async () => {
    const request = singleRequest("SUCCEEDED");
    const singleProposalRef = `erop-v1-${"d".repeat(64)}`;
    let proposed: { proposal: Record<string, unknown>; approvalReceipt: Record<string, unknown> | null } | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests") return response({ items: [request] });
      if (url === `/api/observation-work-orders/work-1/single-volume-requests/${singleRequestRef}`) return response(request);
      if (url === `/api/external-single-volume-reports/${singleReportRef}`) {
        return response({ ...singleReportView(), review: singleReviewReceipt(), proposals: proposed ? [proposed] : [] });
      }
      if (url === "/api/external-reobservation-proposals") {
        proposed = { proposal: { proposalRef: singleProposalRef, version: 1, reportRef: singleReportRef, targetWorkAreas: [{ workAreaId: "pile-1" }] }, approvalReceipt: null };
        return response(proposed);
      }
      if (url === "/api/external-reobservation-proposals/approve") {
        proposed = { ...proposed!, approvalReceipt: { successorWorkOrderId: "successor-1", receiptDigest: digest("f"), approvedAt: "2026-09-15T04:00:00Z" } };
        return response(proposed);
      }
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [{ workOrderId: "successor-1", name: "Core successor" }] });
      throw new Error(`unexpected fetch ${url} ${init?.method ?? "GET"}`);
    });
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["WORK_ORDERS_WRITE", "REOBSERVATION_APPROVE"]} />);
    fireEvent.click(await screen.findByRole("button", { name: "체적 요청 상태" }));
    expect(await screen.findByText("대상: 이 측정에 사용한 작업구역")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("재관측 제안 사유"), { target: { value: "현장 확인" } });
    fireEvent.click(screen.getByRole("button", { name: "이 작업구역으로 재관측 제안" }));
    await screen.findByText("재관측 제안이 기록되었습니다.");
    const proposalCall = fetchMock.mock.calls.find(([url]) => url === "/api/external-reobservation-proposals")?.[1] as RequestInit;
    expect(JSON.parse(String(proposalCall.body))).toEqual({ reportRef: singleReportRef, targetWorkAreaIds: ["pile-1"], reason: "현장 확인" });
    fireEvent.click(screen.getByRole("button", { name: "재관측 후속 작업 승인" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/field/work-orders/successor-1"));
    expect(router.refresh).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "후속 작업 보기" }).getAttribute("href")).toBe("/field/work-orders/successor-1");
    fireEvent.click(screen.getByText("전문가용 검토 기록"));
    const audit = screen.getByText(/대상 독립 검사점 RMSE/).closest("details")!;
    expect(audit.textContent).toContain("대상 촬영");
    expect(audit.textContent).toContain("0.04m");
    expect(audit.textContent).not.toContain("기준");
    expect(document.body.textContent ?? "").not.toContain("준비 중");
  });

  it("shows an unrecorded single target RMSE as 기록 없음 without baseline fields", async () => {
    const request = singleRequest("SUCCEEDED");
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests") return response({ items: [request] });
      if (url === `/api/observation-work-orders/work-1/single-volume-requests/${singleRequestRef}`) return response(request);
      if (url === `/api/external-single-volume-reports/${singleReportRef}`) {
        return response({ ...singleReportView(), review: singleReviewReceipt(null), proposals: [] });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["WORK_ORDERS_WRITE"]} />);
    fireEvent.click(await screen.findByRole("button", { name: "체적 요청 상태" }));
    await screen.findByText(/결과 검토 기록이 있습니다\./);
    fireEvent.click(screen.getByText("전문가용 검토 기록"));
    const audit = screen.getByText(/대상 독립 검사점 RMSE/).closest("details")!;
    expect(audit.textContent).toContain("기록 없음");
    expect(audit.textContent).not.toContain("기준");
  });

  it("shows unknown uncertainty as not estimated and hides the volume when boundary coverage is below policy", async () => {
    let view = singleReportView({ uncertaintyM3: null });
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests") return response({ items: [singleRequest("SUCCEEDED")] });
      if (url === `/api/observation-work-orders/work-1/single-volume-requests/${singleRequestRef}`) return response(singleRequest("SUCCEEDED"));
      if (url === `/api/external-single-volume-reports/${singleReportRef}`) return response(view);
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={null} permissions={[]} />);
    expect(await screen.findByText("현재 선택에서 단일 시점 체적 결정을 요청하세요.")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "체적 요청 상태" }));
    expect(await screen.findByText("불확도 미산정")).toBeTruthy();
    expect(screen.getByText("1,234.5 m³")).toBeTruthy();

    view = singleReportView({ boundaryValidFraction: 0.5 });
    fireEvent.click(screen.getByRole("button", { name: "체적 요청 상태" }));
    expect(await screen.findByText("적용 범위가 측정 기준을 충족하지 않아 체적을 표시하지 않습니다.")).toBeTruthy();
    expect(screen.queryByText("1,234.5 m³")).toBeNull();
  });

  it("keeps a blocked single-volume decision from issuing and does not load single requests unless wired", async () => {
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} permissions={["SITES_WRITE"]} />);
    expect(await screen.findByText("현재 선택에서 상대 물량 비교를 요청하세요.")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("single-volume"))).toBe(false);
    cleanup();

    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/relative-volume-requests") || url.endsWith("/single-volume-requests")) return response({ items: [] });
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={{ ...singleDecision, verdict: "BLOCKED", reasons: ["SINGLE_VOLUME_MAPPING_UNAVAILABLE"], remediations: ["AUTHORIZE_SINGLE_VOLUME_MAPPING"] }} permissions={["SITES_WRITE"]} />);
    expect(await screen.findByText("현재 선택으로는 단일 시점 체적 측정을 요청할 수 없습니다.")).toBeTruthy();
    expect(screen.getByText("단일 시점 체적 매핑이 없습니다")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "단일 시점 체적 측정 요청" })).toBeNull();
  });

  it("treats a missing single-volume router (404) as not configured instead of a read failure", async () => {
    const listError = "체적 측정 요청 목록을 읽지 못했습니다. 새로고침으로 다시 시도하세요.";
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests") return { ok: false, status: 404, json: async () => ({ code: "NOT_FOUND" }) };
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["SITES_WRITE"]} />);

    expect(await screen.findByText("이 환경에는 단일 시점 체적 측정이 구성되지 않았습니다.")).toBeTruthy();
    expect(screen.queryByText(listError)).toBeNull();
    expect(screen.queryByRole("button", { name: "단일 시점 체적 측정 요청" })).toBeNull();
    expect(screen.queryByRole("button", { name: "체적 목록 새로고침" })).toBeNull();
    expect(screen.queryByText("체적 측정 요청 목록")).toBeNull();
    const singleReads = () => fetchMock.mock.calls.filter(([url]) => String(url).includes("single-volume")).length;
    expect(singleReads()).toBe(1);
    vi.useFakeTimers();
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    } finally {
      vi.useRealTimers();
    }
    expect(singleReads()).toBe(1);
    expect(screen.getByText("현재 선택에서 상대 물량 비교를 요청하세요.")).toBeTruthy();
  });

  it("keeps the list read-failure text for a non-404 single-volume list failure", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests") return { ok: false, status: 500, json: async () => ({ code: "INTERNAL" }) };
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["SITES_WRITE"]} />);

    expect(await screen.findByText("체적 측정 요청 목록을 읽지 못했습니다. 새로고침으로 다시 시도하세요.")).toBeTruthy();
    expect(screen.queryByText("이 환경에는 단일 시점 체적 측정이 구성되지 않았습니다.")).toBeNull();
    expect(screen.getByRole("button", { name: "단일 시점 체적 측정 요청" })).toBeTruthy();
  });

  it("explains a refused single-volume issue with the mapped reason instead of the same-selection retry text", async () => {
    const retryText = "단일 시점 체적 요청 상태를 확인하지 못했습니다. 같은 선택으로 다시 시도합니다.";
    const refuse = (issueResponse: () => unknown) => fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests" && !init?.method) return response({ items: [] });
      if (url === "/api/observation-work-orders/work-1/single-volume-requests" && init?.method === "POST") return issueResponse();
      throw new Error(`unexpected fetch ${url}`);
    });

    refuse(() => response({ verdict: "REFUSED", request: null, detail: "DEADLINE_EXPIRED" }));
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["SITES_WRITE"]} />);
    fireEvent.click(await screen.findByRole("button", { name: "단일 시점 체적 측정 요청" }));
    expect(await screen.findByText("이 요청의 마감 시간이 지났습니다. 현재 선택을 다시 확인해 새 요청을 만드세요.")).toBeTruthy();
    expect(screen.queryByText(retryText)).toBeNull();
    expect(screen.queryByText("단일 시점 체적 측정을 요청했습니다.")).toBeNull();
    cleanup();

    refuse(() => response({ code: "AUTHORITY_UNAVAILABLE" }, false));
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["SITES_WRITE"]} />);
    fireEvent.click(await screen.findByRole("button", { name: "단일 시점 체적 측정 요청" }));
    expect(await screen.findByText("측정에 필요한 대상이나 증거를 지금 사용할 수 없습니다. 현재 선택을 다시 확인한 뒤 재시도하세요.")).toBeTruthy();
    expect(screen.queryByText(retryText)).toBeNull();
    expect(document.body.textContent).not.toContain("비교에 필요한");
    cleanup();

    refuse(() => response({ code: "RETRY_EXHAUSTED" }, false));
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["SITES_WRITE"]} />);
    fireEvent.click(await screen.findByRole("button", { name: "단일 시점 체적 측정 요청" }));
    expect(await screen.findByText("이 요청의 재시도 한도에 도달했습니다. 요청 상태를 새로고침하고 원인을 확인하세요.")).toBeTruthy();
    expect(screen.queryByText(retryText)).toBeNull();
  });

  describe("selected request polling", () => {
    let visibility: DocumentVisibilityState = "visible";
    let itemReads = 0;

    beforeEach(() => {
      visibility = "visible";
      itemReads = 0;
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
      fetchMock.mockImplementation(async (url: string) => {
        if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return response({ items: [] });
        if (url === "/api/observation-work-orders/work-1/single-volume-requests") return response({ items: [singleRequest("QUEUED")] });
        if (url === `/api/observation-work-orders/work-1/single-volume-requests/${singleRequestRef}`) {
          itemReads += 1;
          return response(singleRequest("QUEUED"));
        }
        throw new Error(`unexpected fetch ${url}`);
      });
    });

    afterEach(() => {
      Reflect.deleteProperty(document, "visibilityState");
    });

    const stopNotice = "자동 상태 확인을 멈췄습니다. 마지막으로 확인한 요청 상태를 표시합니다. 수동 새로고침으로 다시 확인하세요.";

    it("pauses while the tab is hidden and resumes the read when it becomes visible", async () => {
      render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={null} permissions={[]} />);
      const select = await screen.findByRole("button", { name: "체적 요청 상태" });
      vi.useFakeTimers();
      try {
        await act(async () => { fireEvent.click(select); });
        await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
        expect(itemReads).toBe(1);
        visibility = "hidden";
        await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
        expect(itemReads).toBe(1);
        visibility = "visible";
        await act(async () => {
          document.dispatchEvent(new Event("visibilitychange"));
          await vi.advanceTimersByTimeAsync(0);
        });
        expect(itemReads).toBe(2);
        await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
        expect(itemReads).toBe(3);
        expect(screen.queryByText(stopNotice)).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    it("stops after the bounded budget, says so with the relative stop notice, and restarts on a manual status read", async () => {
      render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={null} permissions={[]} />);
      const select = await screen.findByRole("button", { name: "체적 요청 상태" });
      vi.useFakeTimers();
      try {
        await act(async () => { fireEvent.click(select); });
        await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
        expect(itemReads).toBe(1);
        for (let attempt = 0; attempt < 12; attempt += 1) {
          await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
        }
        expect(itemReads).toBe(7);
        expect(screen.getByText(stopNotice)).toBeTruthy();
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(itemReads).toBe(7);

        await act(async () => { fireEvent.click(screen.getByRole("button", { name: "체적 요청 상태" })); });
        await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
        expect(itemReads).toBe(8);
        expect(screen.queryByText(stopNotice)).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });
  });

  it("keeps a stale single reload from overwriting a newer selection", async () => {
    const secondRequestRef = `external-single-volume-${"8".repeat(32)}`;
    const secondReportRef = `external-single-volume-report-${"9".repeat(32)}`;
    const firstRequest = { ...singleRequest("SUCCEEDED") };
    const secondRequest = {
      ...singleRequest("SUCCEEDED"),
      requestRef: secondRequestRef,
      reportRef: secondReportRef,
      reportDigest: digest("e"),
    };
    const viewFor = (requestId: string, reportId: string, fillM3: number) => {
      const base = singleReportView();
      return {
        ...base,
        request: { ...base.request, requestId },
        report: {
          ...base.report,
          reportId,
          requestId,
          payload: { ...base.report.payload, metrics: { ...base.report.payload.metrics, fillM3 } },
        },
      };
    };
    const firstView = viewFor(singleRequestRef, singleReportRef, 1234.5);
    const secondView = viewFor(secondRequestRef, secondReportRef, 5555.5);
    let reportAReads = 0;
    let resolveStaleReload: ((value: unknown) => void) | null = null;
    fetchMock.mockImplementation((url: string) => {
      if (url === "/api/observation-work-orders/work-1/relative-volume-requests") return Promise.resolve(response({ items: [] }));
      if (url === "/api/observation-work-orders/work-1/single-volume-requests") {
        return Promise.resolve(response({ items: [firstRequest, secondRequest] }));
      }
      if (url === `/api/observation-work-orders/work-1/single-volume-requests/${singleRequestRef}`) {
        return Promise.resolve(response(firstRequest));
      }
      if (url === `/api/observation-work-orders/work-1/single-volume-requests/${secondRequestRef}`) {
        return Promise.resolve(response(secondRequest));
      }
      if (url === `/api/external-single-volume-reports/${singleReportRef}/reviews`) {
        return Promise.resolve(response({ review: { reviewRef: "review-1" } }));
      }
      if (url === `/api/external-single-volume-reports/${singleReportRef}`) {
        reportAReads += 1;
        if (reportAReads === 1) return Promise.resolve(response(firstView));
        return new Promise((resolve) => {
          resolveStaleReload = resolve;
        }).then(() => response({ ...firstView, review: singleReviewReceipt() })) as Promise<unknown> as Promise<Response>;
      }
      if (url === `/api/external-single-volume-reports/${secondReportRef}`) {
        return Promise.resolve(response(secondView));
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<ExternalResultWorkflowPanel workOrderId="work-1" siteId="site-1" decision={null} singleVolumeDecision={singleDecision} permissions={["WORK_ORDERS_WRITE"]} />);
    const selects = await screen.findAllByRole("button", { name: "체적 요청 상태" });
    fireEvent.click(selects[0]!);
    expect(await screen.findByText("1,234.5 m³")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "결과 검토 기록" }));
    await screen.findByText("결과 검토를 기록했습니다.");
    await waitFor(() => expect(reportAReads).toBe(2));
    fireEvent.click(screen.getAllByRole("button", { name: "체적 요청 상태" })[1]!);
    expect(await screen.findByText("5,555.5 m³", {}, { timeout: 3000 })).toBeTruthy();
    await act(async () => {
      resolveStaleReload?.(undefined);
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.getByText("5,555.5 m³")).toBeTruthy(), { timeout: 3000 });
    expect(screen.queryByText("1,234.5 m³")).toBeNull();
    expect(screen.queryByText("체적 결과를 읽지 못했습니다. 완료로 추정하지 않습니다.")).toBeNull();
  });
});
