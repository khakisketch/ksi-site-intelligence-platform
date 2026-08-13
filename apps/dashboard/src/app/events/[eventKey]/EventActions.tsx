"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useMutation } from "@/hooks/useMutation";
import type { EventStatus, TriageStatus } from "@/lib/core-api/types";

type PendingAction = "confirm" | "dismiss" | "assign" | null;

// 서버 SSOT: packages/domain/src/ksi_domain/enums.py _ALLOWED_EVENT_TRANSITIONS.
// CONFIRMED_EVENT 로 전이 가능한 출발 EventStatus 집합 — 이 상태에서만 확정 버튼을
// 보인다(그 외 상태에서 확정을 시도하면 서버가 IllegalEventTransitionError 로 막는다).
const CONFIRMABLE_EVENT_STATUSES: ReadonlySet<EventStatus> = new Set(["FINDING"]);

// 서버 SSOT: packages/domain/src/ksi_domain/enums.py _ALLOWED_TRIAGE_TRANSITIONS.
// ASSIGNED 로 전이 가능한 출발 TriageStatus 집합 — 이미 배정된(NONE 이 아닌) 사건은
// 배정 패널을 숨긴다.
const ASSIGNABLE_TRIAGE_STATUSES: ReadonlySet<TriageStatus> = new Set(["NONE"]);

// 트리아지 배정은 대응 사건이 CONFIRMED_EVENT 일 때만 허용된다(events.py
// _apply_triage_status_transition — EventStatus·TriageStatus 결합 규칙이라
// enums.py 의 단일 전이표에는 없다. 이 표와는 별도로 store 계층이 집행한다).
const ASSIGNABLE_EVENT_STATUS: EventStatus = "CONFIRMED_EVENT";

export function EventActions({
  eventKey,
  status,
  triage,
  bundleDigest,
}: {
  eventKey: string;
  status: EventStatus;
  triage: TriageStatus;
  /**
   * 이 화면이 렌더될 때의 사건 내용 지문. 모든 전이 요청에 함께 보낸다 —
   * 그 사이 장비가 내용을 갱신했으면 서버가 409(STALE_EVENT_VIEW)로 막는다.
   * 확정은 **그 시점 내용**으로 증거 게이트를 통과시키고 스냅샷을 굳히므로,
   * 운영자가 본 것과 실제로 굳는 것이 달라지면 감사 기록이 사람의 판단을
   * 대표하지 않게 된다.
   */
  bundleDigest: string;
}) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [assignee, setAssignee] = useState("");
  const [pending, setPending] = useState<PendingAction>(null);
  const { mutate, errorMessage } = useMutation();

  // 서버 전이표(packages/domain/src/ksi_domain/enums.py _ALLOWED_EVENT_TRANSITIONS) —
  // 도달 불가능한 액션 버튼을 숨긴다(예전엔 항상 노출해 409를 반복시켰다).
  const isFinal = status === "CONFIRMED_EVENT" || status === "DISMISSED";
  // UNRESOLVED 는 CANDIDATE 로만 복귀 가능하다 — DISMISSED 는 허용 전이가 아니다
  // (독립 재검토 2차 A-1: !isFinal 만으로는 UNRESOLVED 를 걸러내지 못해 409 를 냈다).
  const canDismiss = !isFinal && status !== "UNRESOLVED";
  // CONFIRMED_EVENT 는 FINDING 에서만 도달 가능하다 — 그 외 상태에선 버튼 자체를 숨긴다.
  const canConfirm = CONFIRMABLE_EVENT_STATUSES.has(status);
  // 트리아지 배정(ASSIGNED)은 CONFIRMED_EVENT 사건 + triage=NONE(아직 미배정)일 때만
  // 허용된다. status 만 보고 triage 축을 안 보면 이미 배정된 사건에서도 패널이 노출돼
  // 409 를 낸다(독립 재검토 2차 A-2).
  const canAssign = status === ASSIGNABLE_EVENT_STATUS && ASSIGNABLE_TRIAGE_STATUSES.has(triage);
  // CONFIRMED_EVENT/DISMISSED 전이는 서버가 reason 을 필수로 요구한다(events.py
  // _REASON_REQUIRED_STATUSES) — 예전엔 "선택"으로 표기해 빈 사유로도 제출돼 422 를 냈다.
  const reasonMissing = reason.trim().length === 0;

  async function submit(action: PendingAction, body: Record<string, unknown>) {
    setPending(action);
    await mutate(
      `/api/events/${encodeURIComponent(eventKey)}/transitions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // 낙관적 동시성 토큰을 모든 전이에 싣는다 — 개별 호출부가 빠뜨릴 수
        // 없도록 여기 한 곳에서 붙인다.
        body: JSON.stringify({ ...body, expectedBundleDigest: bundleDigest }),
      },
      () => {
        setReason("");
        router.refresh();
      },
    );
    setPending(null);
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-4">
      <h2 className="text-sm font-medium break-keep">트리아지 조치</h2>

      {(canConfirm || canDismiss) && (
        <label className="flex flex-col gap-1 text-sm">
          <span className="break-keep">사유 (필수)</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="input break-keep"
            placeholder="확정/오탐 판단 근거 — 비워두면 제출할 수 없습니다."
          />
        </label>
      )}

      {isFinal ? (
        <p className="text-ink-2 text-sm break-keep">
          이미 최종 판정된 이벤트입니다(확정/오탐 변경 불가).
        </p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {canConfirm ? (
            <button
              type="button"
              disabled={pending !== null || reasonMissing}
              onClick={() => submit("confirm", { targetStatus: "CONFIRMED_EVENT", reason })}
              className="btn btn-primary"
            >
              {pending === "confirm" ? "처리 중…" : "확정"}
            </button>
          ) : (
            <p className="text-ink-2 text-sm break-keep">
              소견(FINDING) 단계에서만 확정할 수 있습니다 — 현재 상태에서는 확정을 진행할 수
              없습니다.
            </p>
          )}
          {canDismiss && (
            // 되돌릴 수 없는 최종 판정(오탐 종결) — 확정(btn-primary)과 색으로 구분돼야
            // 손이 먼저 가지 않는다. 예전엔 중립 버튼과 같아 확정/오탐을 색으로 구분 못 했다.
            <button
              type="button"
              disabled={pending !== null || reasonMissing}
              onClick={() => submit("dismiss", { targetStatus: "DISMISSED", reason })}
              className="btn btn-danger"
            >
              {pending === "dismiss" ? "처리 중…" : "오탐으로 종결"}
            </button>
          )}
        </div>
      )}

      {canAssign && (
        <div className="flex flex-col gap-2 border-t border-line pt-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="break-keep">담당자 배정</span>
            <div className="flex flex-wrap gap-2">
              <input
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                placeholder="담당자 ID"
                className="input flex-1"
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
                className="btn"
              >
                {pending === "assign" ? "처리 중…" : "배정"}
              </button>
            </div>
          </label>
        </div>
      )}

      {errorMessage && (
        <p role="alert" className="break-keep text-sm text-crit-ink">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
