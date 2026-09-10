// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const router = { push: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { ExternalResultWorkflowPanel } from "@/app/field/ExternalResultWorkflowPanel";
import type { ExternalRelativeVolumeReportView, ExternalResultReview } from "@/lib/core-api/external-result-workflow";

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
