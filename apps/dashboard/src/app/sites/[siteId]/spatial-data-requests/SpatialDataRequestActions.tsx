"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { useToast } from "@/components/ui/ToastProvider";
import { isSpatialDataExecutionState, type SpatialDataExecutionState } from "@/lib/core-api/spatial-data-types";

const STATE_LABEL: Record<SpatialDataExecutionState, string> = {
  QUEUED: "대기",
  RUNNING: "처리 중",
  COMPLETED: "완료",
  FAILED: "실패",
  CANCELED: "취소됨",
  EXPIRED: "기한 만료",
};

const CANCEL_ERROR_COPY: Record<string, string> = {
  PERMISSION_DENIED: "요청을 취소할 권한이 없습니다. 권한이 있는 담당자에게 요청하세요.",
  REPORT_CONFLICT: "요청 상태가 바뀌어 취소하지 못했습니다. 현재 상태를 다시 확인하세요.",
  NOT_FOUND: "요청을 찾을 수 없거나 현재 접근할 수 없습니다.",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function SpatialDataRequestActions({
  siteId,
  workAreaId,
  requestId,
  canCancel,
}: {
  siteId: string;
  workAreaId: string;
  requestId: string;
  canCancel: boolean;
}) {
  const router = useRouter();
  const { notify } = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [isRefreshing, startTransition] = useTransition();

  if (!canCancel) {
    return <ActionUnavailable label="요청 취소" description="요청을 취소할 권한이 없습니다. 권한이 있는 담당자에게 요청하세요." />;
  }

  const cancel = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-data-requests/${encodeURIComponent(requestId)}/cancel`,
        { method: "POST", cache: "no-store", headers: { Accept: "application/json" } },
      );
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const code = isRecord(body) && typeof body.code === "string" ? body.code : null;
        setMessage(code ? CANCEL_ERROR_COPY[code] ?? "요청을 취소하지 못했습니다. 현재 상태를 다시 확인하세요." : "요청을 취소하지 못했습니다. 현재 상태를 다시 확인하세요.");
        setConfirming(false);
        return;
      }
      if (!isRecord(body) || body.jobId !== requestId || !isSpatialDataExecutionState(body.executionState)) {
        setMessage("Core 응답의 요청 식별자 또는 상태를 확인할 수 없습니다. 화면을 새로 고쳐 다시 확인하세요.");
        setConfirming(false);
        startTransition(() => router.refresh());
        return;
      }
      const state = body.executionState;
      const label = STATE_LABEL[state];
      if (state === "CANCELED") {
        setMessage(`요청 상태를 확인했습니다: ${label}.`);
        notify("자료 준비 요청을 취소했습니다.");
      } else {
        setMessage(state === "COMPLETED"
          ? "요청이 취소되지 않았습니다. 취소 요청 전에 처리가 완료됐습니다."
          : `요청 상태를 확인했습니다: ${label}.`);
      }
      setConfirming(false);
      startTransition(() => router.refresh());
    } catch {
      setMessage("Core 응답을 받지 못했습니다. 현재 요청 상태를 다시 조회하세요.");
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  return <section className="rounded-lg border border-line bg-surface px-4 py-3">
    <h3 className="text-[13px] font-semibold">요청 취소</h3>
    <p className="mt-1 text-[12px] leading-5 text-ink-2">대기 또는 처리 중인 요청만 Core에서 취소할 수 있습니다. 상태가 바뀌었으면 Core 응답을 다시 확인합니다.</p>
    <button className="btn btn-danger mt-3 min-h-11" type="button" disabled={busy || isRefreshing} onClick={() => { setMessage(null); setConfirming(true); }}>요청 취소</button>
    <ConfirmDialog
      open={confirming}
      title="자료 준비 요청을 취소할까요?"
      description="취소하면 대기 또는 처리 중인 준비가 중단됩니다. 이미 완료된 준비는 취소되지 않으며, 상태가 바뀌었으면 Core 응답을 다시 확인하세요."
      confirmLabel="요청 취소"
      pending={busy}
      onCancel={() => { if (!busy) setConfirming(false); }}
      onConfirm={() => void cancel()}
    />
    {message && <p className="mt-3 rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2" role="status" aria-live="polite">{message}</p>}
  </section>;
}
