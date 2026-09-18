"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import type {
  ExternalAnyResultReview,
  ExternalReobservationProposalView,
} from "@/lib/core-api/external-result-workflow";

type BusyOperation = "review" | "proposal" | "approval";
type FrozenProposal = { reportRef: string; workAreaId: string; reason: string | null; idempotencyKey: string };
type FrozenApproval = { proposalRef: string; reportRef: string; expectedVersion: number; idempotencyKey: string };

function makeKey(): string {
  return `console-${crypto.randomUUID()}`;
}

async function responseJson<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown } | null;
  const code = typeof body?.code === "string" ? body.code : undefined;
  const message = typeof body?.message === "string" ? body.message : undefined;
  throw new Error(code ?? message ?? `HTTP_${response.status}`);
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Core's retained proposals are the authority; a proposal recorded in this session stays selected. */
function retainedProposal(
  proposals: readonly ExternalReobservationProposalView[],
  preferred: ExternalReobservationProposalView | null = null,
): ExternalReobservationProposalView | null {
  return proposals.find((item) =>
    item.proposal.proposalRef === preferred?.proposal.proposalRef
    && item.proposal.version === preferred.proposal.version,
  ) ?? proposals[0] ?? null;
}

/**
 * Result review, reobservation proposal and successor approval for one retained external
 * volume report. The component owns the frozen idempotency attempts, the single-flight
 * busy state and the abort handling for these three mutations; it never derives a Core
 * fact. The caller owns the report family: it supplies the exact review path, the review
 * receipt and proposals Core retained, the target wording and the durable reload or
 * navigation that follows each recorded mutation.
 *
 * Remounting this component (a caller `key` bound to the selection) retires any in-flight
 * attempt: the unmount aborts it and its response can no longer reach the caller.
 */
export function ExternalResultReviewActions<TReview extends ExternalAnyResultReview>({
  reportRef,
  reviewPath,
  review,
  proposals,
  targetWorkAreaId,
  targetLabel,
  reviewReason,
  newIntentAllowed,
  hasReviewPermission,
  canApprovePermission,
  onReviewed,
  onProposal,
  onApproved,
  renderReviewDetail,
}: {
  /** The exact retained report these actions bind to. */
  reportRef: string;
  /** The family's own review endpoint for `reportRef`. */
  reviewPath: string;
  /** Core's retained review receipt for this report, or `null` when it has none yet. */
  review: TReview | null;
  /** Core's retained proposals for this report. */
  proposals: readonly ExternalReobservationProposalView[];
  /** The work area a reobservation proposal targets, exactly as the report binds it. */
  targetWorkAreaId: string;
  /** The family's operator wording for that target, rendered verbatim. */
  targetLabel: string;
  /** The family's reason shown when the review action needs a larger screen. */
  reviewReason: string;
  newIntentAllowed: boolean;
  hasReviewPermission: boolean;
  canApprovePermission: boolean;
  /** Core recorded the review; the caller reloads the durable report. */
  onReviewed: (review: unknown) => void | Promise<void>;
  /** Core recorded the proposal; the caller reloads the durable report. */
  onProposal: (view: ExternalReobservationProposalView) => void | Promise<void>;
  /**
   * Core approved the proposal and bound a successor. The caller finishes the approval
   * (work list refresh, navigation) and must stop as soon as `signal` is aborted, which
   * happens when this attempt is retired.
   */
  onApproved: (view: ExternalReobservationProposalView, signal: AbortSignal) => void | Promise<void>;
  /** The family's own review receipt detail; the component renders no receipt fields itself. */
  renderReviewDetail?: (review: TReview) => ReactNode;
}) {
  const activeMutation = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState<BusyOperation | null>(null);
  const [proposalAttempt, setProposalAttempt] = useState<FrozenProposal | null>(null);
  const [approvalAttempt, setApprovalAttempt] = useState<FrozenApproval | null>(null);
  const [proposal, setProposal] = useState<ExternalReobservationProposalView | null>(() => retainedProposal(proposals));
  // Core's reload is the authority for the proposal list; a proposal recorded in
  // this session stays selected across that reload.
  const [syncedProposals, setSyncedProposals] = useState(proposals);
  if (syncedProposals !== proposals) {
    setSyncedProposals(proposals);
    setProposal((current) => retainedProposal(proposals, current));
  }
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  // Proposing and approving have retained idempotency attempts. A closed task may
  // reconcile that exact durable request, but cannot begin a replacement intent.
  const canReview = hasReviewPermission && newIntentAllowed;
  const canProposal = hasReviewPermission && (newIntentAllowed || proposalAttempt !== null);
  const canApprove = canApprovePermission && (newIntentAllowed || approvalAttempt !== null);

  useEffect(() => () => {
    activeMutation.current?.abort();
    activeMutation.current = null;
  }, []);

  const beginMutation = (operation: BusyOperation) => {
    activeMutation.current?.abort();
    const controller = new AbortController();
    activeMutation.current = controller;
    setBusy(operation);
    return controller;
  };

  const ownsMutation = (controller: AbortController) =>
    activeMutation.current === controller && !controller.signal.aborted;

  const finishMutation = (controller: AbortController) => {
    if (activeMutation.current === controller) {
      activeMutation.current = null;
      setBusy(null);
    }
  };

  const submitReview = async () => {
    if (!canReview || busy) return;
    const controller = beginMutation("review");
    setMessage(null);
    try {
      const response = await fetch(reviewPath, {
        method: "POST",
        signal: controller.signal,
      });
      const value = await responseJson<{ review: unknown }>(response);
      if (!ownsMutation(controller)) return;
      setMessage("결과 검토를 기록했습니다.");
      await onReviewed(value.review);
    } catch (error) {
      if (!isAbort(error) && ownsMutation(controller)) setMessage("결과 검토를 기록하지 못했습니다. 보고서를 다시 확인하세요.");
    } finally {
      finishMutation(controller);
    }
  };

  const createProposal = async () => {
    if (!review || !canProposal || busy) return;
    const normalizedReason = reason.trim() || null;
    let attempt = proposalAttempt;
    const matchesProposal = attempt?.reportRef === reportRef
      && attempt.workAreaId === targetWorkAreaId && attempt.reason === normalizedReason;
    if (!newIntentAllowed && !matchesProposal) {
      setMessage("업무 종료 상태에서는 새 재관측 제안을 기록할 수 없습니다.");
      return;
    }
    if (!matchesProposal) {
      attempt = { reportRef, workAreaId: targetWorkAreaId, reason: normalizedReason, idempotencyKey: makeKey() };
      setProposalAttempt(attempt);
    }
    if (!attempt) return;
    const controller = beginMutation("proposal");
    setMessage(null);
    try {
      const response = await fetch("/api/external-reobservation-proposals", {
        method: "POST",
        headers: { "content-type": "application/json", "idempotency-key": attempt.idempotencyKey },
        body: JSON.stringify({ reportRef: attempt.reportRef, targetWorkAreaIds: [attempt.workAreaId], reason: attempt.reason }),
        signal: controller.signal,
      });
      const value = await responseJson<ExternalReobservationProposalView>(response);
      if (!ownsMutation(controller)) return;
      setProposal(value);
      setMessage("재관측 제안을 기록했습니다.");
      await onProposal(value);
    } catch (error) {
      if (!isAbort(error) && ownsMutation(controller)) setMessage("재관측 제안 상태를 확인하지 못했습니다. 같은 보고서와 작업구역으로 재시도합니다.");
    } finally {
      finishMutation(controller);
    }
  };

  const approve = async () => {
    const currentProposal = proposal;
    if (!currentProposal || !canApprove || busy) return;
    let attempt = approvalAttempt;
    const matchesApproval = attempt?.proposalRef === currentProposal.proposal.proposalRef
      && attempt.reportRef === currentProposal.proposal.reportRef
      && attempt.expectedVersion === currentProposal.proposal.version;
    if (!newIntentAllowed && !matchesApproval) {
      setMessage("업무 종료 상태에서는 새 후속 작업 승인을 시작할 수 없습니다.");
      return;
    }
    if (!matchesApproval) {
      attempt = {
        proposalRef: currentProposal.proposal.proposalRef,
        reportRef: currentProposal.proposal.reportRef,
        expectedVersion: currentProposal.proposal.version,
        idempotencyKey: makeKey(),
      };
      setApprovalAttempt(attempt);
    }
    if (!attempt) return;
    const controller = beginMutation("approval");
    setMessage(null);
    try {
      const response = await fetch("/api/external-reobservation-proposals/approve", {
        method: "POST",
        headers: { "content-type": "application/json", "idempotency-key": attempt.idempotencyKey },
        body: JSON.stringify({ proposalRef: attempt.proposalRef, expectedVersion: attempt.expectedVersion }),
        signal: controller.signal,
      });
      const value = await responseJson<ExternalReobservationProposalView>(response);
      if (!ownsMutation(controller)) return;
      const receipt = value.approvalReceipt;
      if (!receipt) throw new Error("MISSING_SUCCESSOR_RECEIPT");
      if (
        value.proposal.proposalRef !== attempt.proposalRef
        || value.proposal.reportRef !== attempt.reportRef
        || value.proposal.version !== attempt.expectedVersion
      ) throw new Error("MISMATCHED_APPROVAL_PROPOSAL");
      setProposal(value);
      await onApproved(value, controller.signal);
    } catch (error) {
      if (!isAbort(error) && ownsMutation(controller)) setMessage("후속 작업 승인 상태를 확인하지 못했습니다. 같은 제안과 버전으로 재시도합니다.");
    } finally {
      finishMutation(controller);
    }
  };

  const currentProposal = proposal;
  const approvalReceipt = currentProposal?.approvalReceipt ?? null;

  return (
    <>
      {review ? <><p>결과 검토 기록이 있습니다. · {review.reviewedAt}</p>{renderReviewDetail?.(review)}</> : canReview ? <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" reason={reviewReason}><button className="btn w-fit" disabled={busy !== null} onClick={() => void submitReview()}>{busy === "review" ? "결과 검토 기록 중" : "결과 검토 기록"}</button></ResponsiveActionBoundary> : <p className="text-ink-2">{newIntentAllowed ? "보고서 검토에는 WORK_ORDERS_WRITE 권한이 필요합니다." : "업무 종료 상태에서는 새 결과 검토를 기록할 수 없습니다."}</p>}
      {review && (canProposal ? <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" reason="재관측 제안은 노트북 이상의 화면에서 기록합니다."><div className="flex flex-col gap-2"><label className="flex flex-col gap-1">재관측 제안 사유<input className="input" aria-label="재관측 제안 사유" value={reason} disabled={busy !== null || !newIntentAllowed} onChange={(event) => { setReason(event.target.value); setProposalAttempt(null); }} /></label><p className="text-ink-2">{targetLabel}</p>{!currentProposal && <button className="btn w-fit" disabled={busy !== null} onClick={() => void createProposal()}>{busy === "proposal" ? "제안 기록 중" : "이 작업구역으로 재관측 제안"}</button>}</div></ResponsiveActionBoundary> : <p className="text-ink-2">{newIntentAllowed ? "재관측 제안에는 WORK_ORDERS_WRITE 권한이 필요합니다." : "업무 종료 상태에서는 새 재관측 제안을 기록할 수 없습니다."}</p>)}
      {currentProposal && <div className="rounded border border-line p-3"><p>재관측 제안이 기록되었습니다.</p><p className="mt-1 text-ink-2">{targetLabel}</p>{approvalReceipt ? <div className="mt-2 flex flex-wrap items-center gap-2"><p>후속 작업이 생성되었습니다.</p><Link href={`/field/work-orders/${encodeURIComponent(approvalReceipt.successorWorkOrderId)}`} className="btn">후속 작업 보기</Link></div> : canApprove ? <ResponsiveActionBoundary action="REOBSERVATION_APPROVE" reason="후속 작업 승인은 노트북 이상의 화면에서 별도로 기록합니다."><button className="btn mt-2 w-fit" disabled={busy !== null} onClick={() => void approve()}>{busy === "approval" ? "승인 기록 중" : "재관측 후속 작업 승인"}</button></ResponsiveActionBoundary> : <p className="mt-2 text-ink-2">{newIntentAllowed ? "후속 작업 승인에는 REOBSERVATION_APPROVE 권한이 필요합니다." : "업무 종료 상태에서는 새 후속 작업 승인을 시작할 수 없습니다."}</p>}<details className="mt-2 text-[12px] text-ink-2"><summary className="cursor-pointer font-semibold">전문가 정보</summary><p className="mt-1 break-all">제안 {currentProposal.proposal.proposalRef} · v{currentProposal.proposal.version} · 대상 {currentProposal.proposal.targetWorkAreas?.map((item) => item.workAreaId).join(", ") || "기록 없음"}{approvalReceipt ? ` · 후속 작업 ${approvalReceipt.successorWorkOrderId}` : ""}</p></details></div>}
      {message && <p role="status">{message}</p>}
    </>
  );
}
