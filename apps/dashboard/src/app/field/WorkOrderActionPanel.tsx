"use client";

import { useActionState } from "react";

import type { ReobservationDraftView } from "@/lib/core-api/types";

import { INITIAL_FIELD_ACTION_STATE } from "./action-state";
import { approveReobservationAction, approveWorkOrderAction } from "./actions";
import type { WorkOrderPresentation } from "./work-order-stage";

export function WorkOrderActionPanel({
  workOrderId,
  version,
  presentation,
  pendingDraft,
}: {
  workOrderId: string;
  version: number;
  presentation: WorkOrderPresentation;
  pendingDraft: ReobservationDraftView | null;
}) {
  const [approveState, approveAction, approvePending] = useActionState(
    approveWorkOrderAction,
    INITIAL_FIELD_ACTION_STATE,
  );
  const [reobserveState, reobserveAction, reobservePending] = useActionState(
    approveReobservationAction,
    INITIAL_FIELD_ACTION_STATE,
  );

  if (presentation.action === "NONE") return null;
  if (presentation.action === "OPEN_RESULTS") {
    return (
      <a href="#copilot" className="btn btn-field btn-primary w-full justify-center">
        {presentation.actionLabel}
      </a>
    );
  }
  if (presentation.action === "REFRESH") {
    return (
      <button
        type="button"
        className="btn btn-field btn-primary w-full justify-center"
        onClick={() => window.location.reload()}
      >
        {presentation.actionLabel}
      </button>
    );
  }
  if (presentation.action === "APPROVE_REOBSERVATION") {
    if (!pendingDraft) {
      return (
        <p role="alert" className="rounded-lg bg-high-bg px-4 py-3 text-[13px] text-high-ink">
          승인할 재관측 초안을 불러오지 못했습니다. 상태를 새로고침하세요.
        </p>
      );
    }
    return (
      <form action={reobserveAction} className="flex flex-col gap-2">
        <input type="hidden" name="workOrderId" value={workOrderId} />
        <input type="hidden" name="draftId" value={pendingDraft.draftId} />
        <input type="hidden" name="expectedVersion" value={pendingDraft.version} />
        <button
          type="submit"
          disabled={reobservePending}
          className="btn btn-field btn-primary w-full justify-center"
        >
          {reobservePending ? "승인 중…" : presentation.actionLabel}
        </button>
        <ActionMessage state={reobserveState} />
      </form>
    );
  }
  return (
    <form action={approveAction} className="flex flex-col gap-2">
      <input type="hidden" name="workOrderId" value={workOrderId} />
      <input type="hidden" name="expectedVersion" value={version} />
      <button
        type="submit"
        disabled={approvePending}
        className="btn btn-field btn-primary w-full justify-center"
      >
        {approvePending ? "승인 중…" : presentation.actionLabel}
      </button>
      <ActionMessage state={approveState} />
    </form>
  );
}

function ActionMessage({ state }: { state: { status: string; message: string } }) {
  if (!state.message) return null;
  return (
    <p
      role={state.status === "error" ? "alert" : "status"}
      className={`rounded-lg px-3 py-2 text-[13px] ${
        state.status === "error" ? "bg-crit-bg text-crit-ink" : "bg-safe-bg text-safe-ink"
      }`}
    >
      {state.message}
    </p>
  );
}
