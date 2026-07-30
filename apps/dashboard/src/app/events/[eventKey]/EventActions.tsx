"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import type { EventStatus, TriageStatus } from "@/lib/core-api/types";

type PendingAction = "confirm" | "dismiss" | "assign" | null;

export function EventActions({
  eventKey,
  status,
  triage,
}: {
  eventKey: string;
  status: EventStatus;
  triage: TriageStatus;
}) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [assignee, setAssignee] = useState("");
  const [pending, setPending] = useState<PendingAction>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // 서버 전이표(packages/domain/src/ksi_domain/enums.py _ALLOWED_EVENT_TRANSITIONS) —
  // 도달 불가능한 액션 버튼을 숨긴다(예전엔 항상 노출해 409를 반복시켰다).
  const isFinal = status === "CONFIRMED_EVENT" || status === "DISMISSED";
  // UNRESOLVED 는 CANDIDATE 로만 복귀 가능하다 — DISMISSED 는 허용 전이가 아니다
  // (독립 재검토 2차 A-1: !isFinal 만으로는 UNRESOLVED 를 걸러내지 못해 409 를 냈다).
  const canDismiss = !isFinal && status !== "UNRESOLVED";
  // CONFIRMED_EVENT 는 FINDING 에서만 도달 가능하다 — 그 외 상태에선 버튼 자체를 숨긴다.
  const canConfirm = status === "FINDING";
  // 트리아지 배정(ASSIGNED)은 CONFIRMED_EVENT 사건 + triage=NONE(아직 미배정)일 때만
  // 허용된다(events.py _apply_triage_status_transition + _ALLOWED_TRIAGE_TRANSITIONS[NONE]).
  // status 만 보고 triage 축을 안 보면 이미 배정된 사건에서도 패널이 노출돼 409 를 낸다
  // (독립 재검토 2차 A-2).
  const canAssign = status === "CONFIRMED_EVENT" && triage === "NONE";
  // CONFIRMED_EVENT/DISMISSED 전이는 서버가 reason 을 필수로 요구한다(events.py
  // _REASON_REQUIRED_STATUSES) — 예전엔 "선택"으로 표기해 빈 사유로도 제출돼 422 를 냈다.
  const reasonMissing = reason.trim().length === 0;

  async function submit(action: PendingAction, body: Record<string, unknown>) {
    setPending(action);
    setErrorMessage(null);
    try {
      const response = await fetch(`/api/events/${encodeURIComponent(eventKey)}/transitions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setErrorMessage(
          (payload && typeof payload.message === "string" && payload.message) ||
            "요청을 처리하지 못했습니다.",
        );
        return;
      }
      setReason("");
      router.refresh();
    } catch {
      setErrorMessage("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-black/10 p-4 dark:border-white/10">
      <h2 className="text-sm font-medium break-keep">트리아지 조치</h2>

      {(canConfirm || canDismiss) && (
        <label className="flex flex-col gap-1 text-sm">
          <span className="break-keep">사유 (필수)</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="border-foreground/20 rounded-md border px-3 py-2 text-sm break-keep"
            placeholder="확정/오탐 판단 근거 — 비워두면 제출할 수 없습니다."
          />
        </label>
      )}

      {isFinal ? (
        <p className="text-foreground/60 text-sm break-keep">
          이미 최종 판정된 이벤트입니다(확정/오탐 변경 불가).
        </p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {canConfirm ? (
            <button
              type="button"
              disabled={pending !== null || reasonMissing}
              onClick={() => submit("confirm", { targetStatus: "CONFIRMED_EVENT", reason })}
              className="bg-foreground text-background min-h-11 rounded-md px-4 text-sm font-medium disabled:opacity-40"
            >
              {pending === "confirm" ? "처리 중…" : "확정"}
            </button>
          ) : (
            <p className="text-foreground/60 text-sm break-keep">
              소견(FINDING) 단계에서만 확정할 수 있습니다 — 현재 상태에서는 확정을 진행할 수
              없습니다.
            </p>
          )}
          {canDismiss && (
            <button
              type="button"
              disabled={pending !== null || reasonMissing}
              onClick={() => submit("dismiss", { targetStatus: "DISMISSED", reason })}
              className="border-foreground/30 min-h-11 rounded-md border px-4 text-sm font-medium disabled:opacity-40"
            >
              {pending === "dismiss" ? "처리 중…" : "오탐"}
            </button>
          )}
        </div>
      )}

      {canAssign && (
        <div className="flex flex-col gap-2 border-t border-black/10 pt-4 dark:border-white/10">
          <label className="flex flex-col gap-1 text-sm">
            <span className="break-keep">담당자 배정</span>
            <div className="flex flex-wrap gap-2">
              <input
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                placeholder="담당자 ID"
                className="border-foreground/20 min-h-11 flex-1 rounded-md border px-3 text-sm"
              />
              <button
                type="button"
                disabled={pending !== null || !assignee.trim()}
                onClick={() =>
                  submit("assign", {
                    triageTarget: "ASSIGNED",
                    assignee: assignee.trim(),
                    reason: reason || undefined,
                  })
                }
                className="border-foreground/30 min-h-11 rounded-md border px-4 text-sm font-medium disabled:opacity-40"
              >
                {pending === "assign" ? "처리 중…" : "배정"}
              </button>
            </div>
          </label>
        </div>
      )}

      {errorMessage && (
        <p role="alert" className="break-keep text-sm text-red-700 dark:text-red-300">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
