"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { isSpatialDataExecutionState, type SpatialDataExecutionState } from "@/lib/core-api/spatial-data-types";

const STATE_LABEL: Record<SpatialDataExecutionState, string> = {
  QUEUED: "대기",
  RUNNING: "처리 중",
  COMPLETED: "완료",
  FAILED: "실패",
  CANCELED: "취소됨",
  EXPIRED: "기한 만료",
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
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [isRefreshing, startTransition] = useTransition();

  if (!canCancel) {
    return <p className="text-[12px] leading-5 text-ink-muted">취소하려면 Core의 SPATIAL_DATA_REQUEST 권한이 필요합니다.</p>;
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
        const detail = isRecord(body) && typeof body.message === "string" ? body.message : null;
        setMessage(code ? `Core 거부: ${code}` : detail ?? "취소 요청을 Core에서 확인하지 못했습니다.");
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
      setMessage(state === "COMPLETED"
        ? `Core 응답 상태: ${label} (${state}) · 취소 전에 요청이 완료되었습니다.`
        : `Core 응답 상태: ${label} (${state})`);
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
    {!confirming
      ? <button className="btn btn-danger mt-3 min-h-11" type="button" disabled={busy || isRefreshing} onClick={() => { setMessage(null); setConfirming(true); }}>요청 취소</button>
      : <div className="mt-3 flex flex-wrap items-center gap-2">
        <button className="btn btn-danger min-h-11" type="button" disabled={busy} onClick={() => void cancel()}>{busy ? "Core에 확인 중…" : "취소를 확인"}</button>
        <button className="btn min-h-11" type="button" disabled={busy} onClick={() => setConfirming(false)}>돌아가기</button>
      </div>}
    {message && <p className="mt-3 rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2" role="status" aria-live="polite">{message}</p>}
  </section>;
}
