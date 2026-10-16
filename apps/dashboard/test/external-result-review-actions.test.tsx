// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ExternalResultReviewActions } from "@/components/external-results/ExternalResultReviewActions";
import type { ExternalAnyResultReview, ExternalReobservationProposalView } from "@/lib/core-api/external-result-workflow";

const fetchMock = vi.fn();
const digest = (character: string) => `sha256:${character.repeat(64)}`;
const reportRef = `external-relative-volume-report-${"c".repeat(32)}`;
const reviewPath = `/api/external-relative-volume-reports/${reportRef}/reviews`;
const proposalRef = `erop-v1-${"d".repeat(64)}`;
const targetLabel = "대상: 이 비교에 사용한 작업구역";
const reviewReason = "비교 결과 검토 기록은 노트북 이상의 화면에서 진행합니다.";

function response(value: unknown, ok = true) {
  return { ok, json: async () => value };
}

/** Only the fields these actions read; the full receipt is Core's and is not re-derived here. */
function reviewReceipt(): ExternalAnyResultReview {
  return {
    contractVersion: "external-result-review-receipt.v1",
    reviewRef: `err-v1-${"e".repeat(64)}`,
    reportRef,
    reviewedAt: "2026-09-17T03:00:00Z",
    reviewDigest: digest("e"),
    factualLimitations: [],
  } as unknown as ExternalAnyResultReview;
}

function proposalView(approved = false): ExternalReobservationProposalView {
  return {
    proposal: {
      proposalRef,
      version: 2,
      reportRef,
      targetWorkAreas: [{ workAreaId: "area-1", revision: 1, snapshotDigest: digest("8") }],
      reason: null,
      proposalDigest: digest("f"),
      createdAt: "2026-09-17T03:30:00Z",
    },
    approvalReceipt: approved
      ? { successorWorkOrderId: "successor-1", receiptDigest: digest("a"), approvedAt: "2026-09-17T04:00:00Z" }
      : null,
  } as unknown as ExternalReobservationProposalView;
}

type Props = Parameters<typeof ExternalResultReviewActions>[0];

function props(overrides: Partial<Props> = {}): Props {
  return {
    reportRef,
    reviewPath,
    review: null,
    proposals: [],
    targetWorkAreaId: "area-1",
    targetLabel,
    reviewReason,
    newIntentAllowed: true,
    hasReviewPermission: true,
    canApprovePermission: true,
    onReviewed: vi.fn(),
    onProposal: vi.fn(),
    onApproved: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", { randomUUID: () => "stable-key" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("records a review against the given review path and hands Core's receipt upward", async () => {
  fetchMock.mockImplementation(async () => response({ review: { reviewRef: "review-1" } }));
  const onReviewed = vi.fn();
  render(<ExternalResultReviewActions {...props({ onReviewed })} />);

  fireEvent.click(screen.getByRole("button", { name: "결과 검토 기록" }));
  expect(await screen.findByText("결과 검토를 기록했습니다.")).toBeTruthy();
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe(reviewPath);
  expect(init.method).toBe("POST");
  // Core's review endpoint takes no body and no idempotency key; nothing is invented here.
  expect(init.headers).toBeUndefined();
  expect(init.body).toBeUndefined();
  expect(onReviewed).toHaveBeenCalledWith({ reviewRef: "review-1" });
});

it("retries a lost review against the same path without claiming a receipt", async () => {
  fetchMock.mockImplementation(async () => { throw new Error("lost response"); });
  const onReviewed = vi.fn();
  render(<ExternalResultReviewActions {...props({ onReviewed })} />);

  fireEvent.click(screen.getByRole("button", { name: "결과 검토 기록" }));
  expect(await screen.findByText("결과 검토를 기록하지 못했습니다. 보고서를 다시 확인하세요.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "결과 검토 기록" }));
  await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(2));
  expect(fetchMock.mock.calls.every(([called]) => called === reviewPath)).toBe(true);
  expect(onReviewed).not.toHaveBeenCalled();
});

it("freezes the proposal attempt and replays the same key and body after closure", async () => {
  const posts: RequestInit[] = [];
  fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
    posts.push(init);
    throw new Error("lost response");
  });
  const base = props({ review: reviewReceipt() });
  const { rerender } = render(<ExternalResultReviewActions {...base} />);

  fireEvent.change(screen.getByLabelText("재관측 제안 사유"), { target: { value: "현장 확인" } });
  fireEvent.click(screen.getByRole("button", { name: "이 작업구역으로 재관측 제안" }));
  expect(await screen.findByText("재관측 제안 상태를 확인하지 못했습니다. 같은 보고서와 작업구역으로 재시도합니다.")).toBeTruthy();
  expect(posts[0].method).toBe("POST");
  expect(JSON.parse(String(posts[0].body))).toEqual({ reportRef, targetWorkAreaIds: ["area-1"], reason: "현장 확인" });
  expect((posts[0].headers as Record<string, string>)["idempotency-key"]).toBe("console-stable-key");

  rerender(<ExternalResultReviewActions {...base} newIntentAllowed={false} />);
  fireEvent.click(screen.getByRole("button", { name: "이 작업구역으로 재관측 제안" }));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1].body).toBe(posts[0].body);
  expect(posts[1].headers).toEqual(posts[0].headers);
});

it("records the proposal for the exact target work area and stops offering a second one", async () => {
  fetchMock.mockImplementation(async () => response(proposalView()));
  const onProposal = vi.fn();
  render(<ExternalResultReviewActions {...props({ review: reviewReceipt(), onProposal })} />);

  fireEvent.click(screen.getByRole("button", { name: "이 작업구역으로 재관측 제안" }));
  expect(await screen.findByText("재관측 제안이 기록되었습니다.")).toBeTruthy();
  const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/external-reobservation-proposals");
  // The proposal form and the recorded proposal both name the same Core-bound target.
  expect(screen.getAllByText(targetLabel)).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "이 작업구역으로 재관측 제안" })).toBeNull();
  expect(onProposal).toHaveBeenCalledWith(proposalView());
});

it("approves the retained proposal with a frozen key and the exact version, then reports Core's successor", async () => {
  fetchMock.mockImplementation(async () => response(proposalView(true)));
  const onApproved = vi.fn();
  render(<ExternalResultReviewActions {...props({ review: reviewReceipt(), proposals: [proposalView()], onApproved })} />);

  fireEvent.click(screen.getByRole("button", { name: "재관측 후속 작업 승인" }));
  expect(await screen.findByText("후속 작업이 생성되었습니다.")).toBeTruthy();
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/external-reobservation-proposals/approve");
  expect(JSON.parse(String(init.body))).toEqual({ proposalRef, expectedVersion: 2 });
  expect((init.headers as Record<string, string>)["idempotency-key"]).toBe("console-stable-key");
  expect(onApproved.mock.calls[0][0]).toEqual(proposalView(true));
  expect(onApproved.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
  expect(screen.getByRole("link", { name: "후속 작업 보기" }).getAttribute("href")).toBe("/field/work-orders/successor-1");
});

it("refuses an approval response that does not bind the exact proposal version", async () => {
  fetchMock.mockImplementation(async () => response({
    proposal: { ...proposalView(true).proposal, version: 3 },
    approvalReceipt: proposalView(true).approvalReceipt,
  }));
  const onApproved = vi.fn();
  render(<ExternalResultReviewActions {...props({ review: reviewReceipt(), proposals: [proposalView()], onApproved })} />);

  fireEvent.click(screen.getByRole("button", { name: "재관측 후속 작업 승인" }));
  expect(await screen.findByText("후속 작업 승인 상태를 확인하지 못했습니다. 같은 제안과 버전으로 재시도합니다.")).toBeTruthy();
  expect(onApproved).not.toHaveBeenCalled();
  expect(screen.queryByText("후속 작업이 생성되었습니다.")).toBeNull();
});

it("renders the retained review through the family's own detail renderer", async () => {
  render(<ExternalResultReviewActions {...props({
    review: reviewReceipt(),
    renderReviewDetail: (review) => <p>검토 상세 {review.reviewRef}</p>,
  })} />);

  expect(await screen.findByText("결과 검토 기록이 있습니다. · 2026. 9. 17. 12:00")).toBeTruthy();
  expect(screen.getByText(`검토 상세 err-v1-${"e".repeat(64)}`)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "결과 검토 기록" })).toBeNull();
});

it("names the missing permission for each action without offering it", async () => {
  const { rerender } = render(<ExternalResultReviewActions {...props({ hasReviewPermission: false })} />);
  expect(await screen.findByText("결과 검토를 기록할 권한이 없습니다. 현장 담당자에게 확인하세요.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "결과 검토 기록" })).toBeNull();

  rerender(<ExternalResultReviewActions {...props({
    review: reviewReceipt(),
    proposals: [proposalView()],
    hasReviewPermission: false,
    canApprovePermission: false,
  })} />);
  expect(await screen.findByText("재관측 제안을 기록할 권한이 없습니다. 현장 담당자에게 확인하세요.")).toBeTruthy();
  expect(screen.getByText("후속 작업을 승인할 권한이 없습니다. 현장 담당자에게 확인하세요.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "이 작업구역으로 재관측 제안" })).toBeNull();
  expect(screen.queryByRole("button", { name: "재관측 후속 작업 승인" })).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("keeps a closed workflow readable while refusing every new intent", async () => {
  const { rerender } = render(<ExternalResultReviewActions {...props({ newIntentAllowed: false })} />);
  expect(await screen.findByText("업무 종료 상태에서는 새 결과 검토를 기록할 수 없습니다.")).toBeTruthy();

  rerender(<ExternalResultReviewActions {...props({
    review: reviewReceipt(),
    proposals: [proposalView()],
    newIntentAllowed: false,
  })} />);
  expect(await screen.findByText("업무 종료 상태에서는 새 재관측 제안을 기록할 수 없습니다.")).toBeTruthy();
  expect(screen.getByText("업무 종료 상태에서는 새 후속 작업 승인을 시작할 수 없습니다.")).toBeTruthy();
  expect(screen.getByText("재관측 제안이 기록되었습니다.")).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});
