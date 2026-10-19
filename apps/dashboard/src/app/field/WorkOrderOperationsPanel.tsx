"use client";

import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/ToastProvider";
import type { ObservationWorkOrderOperationsView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { seoulDateTimeLocalToUtc } from "@/lib/external-reconstruction-submission";

type OperationKind = "assignment" | "due-date" | "close" | "reopen";

type PendingAttempt = {
  kind: OperationKind;
  body: Record<string, unknown>;
  key: string;
};

type AssignableMember = {
  principalId: string;
  displayName: string;
  roleHint: "ADMIN" | "FIELD_OPERATOR" | "VIEWER";
  status: "ACTIVE" | "INACTIVE";
};

export function seoulDateTimeLocalValue(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  // The input label promises Korea Standard Time.  Do not let the browser's
  // host zone silently reinterpret a `datetime-local` value.
  const seoul = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const datePart = [
    seoul.getUTCFullYear().toString().padStart(4, "0"),
    (seoul.getUTCMonth() + 1).toString().padStart(2, "0"),
    seoul.getUTCDate().toString().padStart(2, "0"),
  ].join("-");
  return `${datePart}T${seoul.getUTCHours().toString().padStart(2, "0")}:${seoul.getUTCMinutes().toString().padStart(2, "0")}`;
}

function deadlineNotice(operations: ObservationWorkOrderOperationsView): string | null {
  if (operations.workflowStatus === "CLOSED" || operations.dueAt === null) return null;
  const dueAt = new Date(operations.dueAt).getTime();
  if (Number.isNaN(dueAt)) return null;
  const remaining = dueAt - Date.now();
  if (remaining < 0) return "기한이 지났습니다. 우선순위와 다음 행동을 확인하세요.";
  if (remaining <= 24 * 60 * 60 * 1000) return "마감이 24시간 안에 있습니다.";
  return null;
}

function statusLabel(status: ObservationWorkOrderOperationsView["workflowStatus"]): string {
  if (status === "CLOSED") return "업무 종료";
  if (status === "OPEN") return "운영 중";
  return "운영 상태 확인 필요";
}

function errorMessage(response: Response, payload: unknown): string {
  const detail = payload && typeof payload === "object" && "detail" in payload
    ? (payload as { detail?: unknown }).detail
    : null;
  if (response.status === 409) {
    if (detail === "EXTERNAL_WORKFLOW_CLOSED") return "이 작업은 이미 업무 종료 상태입니다. 최신 상태를 확인하세요.";
    return "다른 변경이 먼저 저장되었습니다. 최신 상태를 불러왔고 입력은 유지했습니다.";
  }
  return "요청을 저장하지 못했습니다. 같은 요청을 다시 시도하세요.";
}

function hasAmbiguousPersistence(response: Response): boolean {
  // A gateway timeout may arrive after Core appended the operation event. Keep
  // the frozen request so its idempotency key can reconcile that outcome.
  return response.status >= 500 || response.status === 408 || response.status === 429;
}

export function WorkOrderOperationsPanel({
  workOrderId,
  principalId,
  initialOperations,
  canWrite,
}: {
  workOrderId: string;
  principalId: string;
  initialOperations: ObservationWorkOrderOperationsView | null;
  canWrite: boolean;
}) {
  const router = useRouter();
  const { notify } = useToast();
  const [operations, setOperations] = useState(initialOperations);
  const [dueAt, setDueAt] = useState(() => seoulDateTimeLocalValue(initialOperations?.dueAt ?? null));
  const [closeNote, setCloseNote] = useState("");
  const [closeConfirm, setCloseConfirm] = useState<{ body: Record<string, unknown> } | null>(null);
  const [pending, setPending] = useState<PendingAttempt | null>(null);
  const [unresolvedRetry, setUnresolvedRetry] = useState<PendingAttempt | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [members, setMembers] = useState<AssignableMember[] | null>(null);
  const [membersLoading, setMembersLoading] = useState(false);
  const [rosterError, setRosterError] = useState(false);
  const [assigneePrincipalId, setAssigneePrincipalId] = useState("");
  const unresolvedRetryRef = useRef<PendingAttempt | null>(null);
  const submitLock = useRef(false);

  const notice = useMemo(
    () => (operations ? deadlineNotice(operations) : null),
    [operations],
  );
  const isClosed = operations?.workflowStatus === "CLOSED";
  const assignedToMe = operations?.assigneePrincipalId === principalId;
  const assignedElsewhere = Boolean(operations?.assigneePrincipalId && !assignedToMe);
  const retryPending = unresolvedRetry !== null;
  const dueAtUtc = seoulDateTimeLocalToUtc(dueAt);

  async function refresh({ preserveDraft = false }: { preserveDraft?: boolean } = {}) {
    const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/operations`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("operations refresh failed");
    const next = await response.json() as ObservationWorkOrderOperationsView;
    setOperations(next);
    if (!preserveDraft) setDueAt(seoulDateTimeLocalValue(next.dueAt));
  }

  async function mutate(kind: OperationKind, body: Record<string, unknown>) {
    if (!operations || pending || !canWrite || submitLock.current) return;
    const sameRetry = unresolvedRetryRef.current
      && unresolvedRetryRef.current.kind === kind
      && JSON.stringify(unresolvedRetryRef.current.body) === JSON.stringify(body)
      ? unresolvedRetryRef.current
      : null;
    if (unresolvedRetryRef.current !== null && sameRetry === null) {
      setFeedback("이전 요청의 응답을 확인하지 못했습니다. 같은 요청을 다시 시도하거나 상태를 다시 불러오세요.");
      return;
    }
    const attempt = sameRetry ?? { kind, body, key: `operations-${crypto.randomUUID()}` };
    submitLock.current = true;
    setPending(attempt);
    setFeedback(null);
    const endpoint = kind === "assignment"
      ? "assignment"
      : kind === "due-date"
        ? "due-date"
        : kind;
    const method = kind === "due-date" ? "PUT" : "POST";
    try {
      const response = await fetch(
        `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/operations/${endpoint}`,
        {
          method,
          headers: { "content-type": "application/json", "Idempotency-Key": attempt.key },
          body: JSON.stringify(body),
        },
      );
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        if (hasAmbiguousPersistence(response)) {
          unresolvedRetryRef.current = attempt;
          setUnresolvedRetry(attempt);
          setFeedback("응답을 확인하지 못했습니다. 같은 요청을 다시 시도하세요.");
          return;
        }
        const refreshed = response.status === 409
          && await refresh({ preserveDraft: true }).then(() => true).catch(() => false);
        unresolvedRetryRef.current = null;
        setUnresolvedRetry(null);
        setFeedback(refreshed
          ? errorMessage(response, payload)
          : "요청은 저장되지 않았습니다. 최신 운영 정보를 불러오지 못했습니다. 다시 불러오거나 같은 내용을 확인하세요.");
        return;
      }
      const next = payload as ObservationWorkOrderOperationsView;
      setOperations(next);
      setDueAt(seoulDateTimeLocalValue(next.dueAt));
      setCloseNote("");
      unresolvedRetryRef.current = null;
      setUnresolvedRetry(null);
      setFeedback(null);
      notify(kind === "close" ? "업무를 종료했습니다." : "운영 정보를 저장했습니다.");
      if (kind === "close" || kind === "reopen") router.refresh();
    } catch {
      unresolvedRetryRef.current = attempt;
      setUnresolvedRetry(attempt);
      setFeedback("응답을 확인하지 못했습니다. 같은 요청을 다시 시도하세요.");
    } finally {
      setPending(null);
      submitLock.current = false;
    }
  }

  async function loadAssignableMembers() {
    if (membersLoading || (members !== null && !rosterError)) return;
    setMembersLoading(true);
    setFeedback(null);
    try {
      const response = await fetch("/api/organization-work-roster?includeInactive=false", { cache: "no-store" });
      if (!response.ok) throw new Error("roster unavailable");
      const body = await response.json() as { members?: AssignableMember[] };
      const activeAssignable = (body.members ?? []).filter((member) => member.status === "ACTIVE" && member.roleHint !== "VIEWER");
      setMembers(activeAssignable);
      setRosterError(false);
    } catch {
      setFeedback("배정할 팀원 목록을 불러오지 못했습니다. 다시 시도하세요.");
      setRosterError(true);
    } finally {
      setMembersLoading(false);
    }
  }

  if (operations === null) {
    return (
      <section className="rounded-xl border border-line bg-surface px-4 py-3">
        <h2 className="text-[15px] font-bold">작업 운영 정보</h2>
        <p className="mt-1 text-[13px] leading-5 text-ink-2">
          담당·기한·업무 종료 상태를 불러오지 못했습니다.
        </p>
        <button className="btn mt-3" disabled={pending !== null} onClick={() => void refresh().then(() => setFeedback("운영 정보를 다시 불러왔습니다.")).catch(() => setFeedback("운영 정보를 다시 불러오지 못했습니다."))}>다시 불러오기</button>
        {feedback && <p role="status" className="mt-2 text-[13px] leading-5 text-ink-2">{feedback}</p>}
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-line bg-surface">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-[15px] font-bold">작업 운영</h2>
          <p className="mt-1 text-[13px] leading-5 text-ink-2">
            담당과 기한을 정하고, 끝난 작업은 업무 종료로 남깁니다.
          </p>
        </div>
        <span className={`shrink-0 rounded-full pl-0 pr-2.5 py-1 text-[12px] font-semibold ${isClosed ? "bg-sunk text-ink-2" : "bg-accent-bg text-accent-text"}`}>
          {statusLabel(operations.workflowStatus)}
        </span>
      </div>

      <div className="grid gap-4 px-4 py-4 lg:grid-cols-2">
        <div className="space-y-2 text-[13px]">
          <p><span className="font-semibold">담당</span> · {assignedToMe ? "내 작업" : assignedElsewhere ? "다른 담당자에게 배정됨" : "미배정"}</p>
          <p><span className="font-semibold">마감</span> · {operations.dueAt ? formatKoreanDateTime(operations.dueAt, { dateStyle: "medium", timeStyle: "short" }) : "설정 안 함"}</p>
          {operations.workflowStatus === "CLOSED" && operations.closedAt && (
            <p><span className="font-semibold">종료</span> · {formatKoreanDateTime(operations.closedAt, { dateStyle: "medium", timeStyle: "short" })}</p>
          )}
          {operations.closeNote && <p className="rounded-lg bg-sunk px-3 py-2 leading-5 text-ink-2">{operations.closeNote}</p>}
          {notice && <p className="rounded-lg border border-high/30 bg-high-bg px-3 py-2 leading-5 text-high-ink">{notice}</p>}
        </div>

        <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" inlineNotice={false} reason="노트북에서 같은 계정으로 이 작업 상세를 열어 담당·기한·업무 종료 변경을 이어가세요.">
          {canWrite ? (
          <div className="flex flex-col gap-3 rounded-lg bg-sunk p-3">
            {unresolvedRetry && <div className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] leading-5 text-ink-2">
              <p>이전 저장 요청의 응답을 확인하지 못했습니다. 같은 요청을 먼저 확인하세요.</p>
              <button className="btn mt-2" disabled={pending !== null} onClick={() => void mutate(unresolvedRetry.kind, unresolvedRetry.body)}>같은 요청 다시 시도</button>
            </div>}
            {!isClosed && <>
              <div className="flex flex-wrap gap-2">
                <button className="btn" disabled={!canWrite || pending !== null || retryPending || assignedToMe} onClick={() => void mutate("assignment", { expectedOperationsRevision: operations.operationsRevision, action: "ASSIGN_TO_ME" })}>
                  내게 배정
                </button>
                <button className="btn" disabled={!canWrite || pending !== null || retryPending || isClosed} onClick={() => void loadAssignableMembers()}>
                  팀원에게 배정
                </button>
                <button className="btn" disabled={!canWrite || pending !== null || retryPending || !operations.assigneePrincipalId} onClick={() => void mutate("assignment", { expectedOperationsRevision: operations.operationsRevision, action: "CLEAR" })}>
                  담당 해제
                </button>
              </div>
              {(members !== null || rosterError) && <div className="flex flex-wrap items-end gap-2 rounded-lg border border-line bg-surface p-3">{rosterError ? <><p className="w-full text-[12.5px] text-ink-2">배정할 팀원 목록을 확인하지 못했습니다.</p><button className="btn" disabled={membersLoading} onClick={() => void loadAssignableMembers()}>팀원 목록 다시 불러오기</button></> : <><label className="flex min-w-56 flex-1 flex-col gap-1 text-[13px] font-semibold">배정할 팀원<select aria-label="배정할 팀원" className="input" value={assigneePrincipalId} disabled={membersLoading || pending !== null || retryPending} onChange={(event) => setAssigneePrincipalId(event.target.value)}><option value="">팀원을 선택하세요</option>{members!.map((member) => <option key={member.principalId} value={member.principalId}>{member.displayName} · {member.principalId}</option>)}</select></label><button className="btn btn-primary" disabled={!assigneePrincipalId || pending !== null || retryPending} onClick={() => void mutate("assignment", { expectedOperationsRevision: operations.operationsRevision, action: "ASSIGN_TO_MEMBER", assigneePrincipalId })}>선택한 팀원에게 배정</button>{members!.length === 0 && <p className="w-full text-[12.5px] text-ink-2">배정 가능한 활성 팀원이 없습니다. 열람자는 결과 공유만 받을 수 있습니다.</p>}</>}</div>}
              <label className="flex flex-col gap-1 text-[13px] font-semibold">마감 시각 (한국 표준시)
                <input className="input" type="datetime-local" value={dueAt} disabled={!canWrite || pending !== null || retryPending} onChange={(event) => setDueAt(event.target.value)} />
                {dueAtUtc && <span className="font-normal text-[12px] text-ink-muted">선택: {formatKoreanDateTime(dueAtUtc, { dateStyle: "short", timeStyle: "short" })}</span>}
              </label>
              <div className="flex flex-wrap gap-2">
                <button className="btn" disabled={!canWrite || pending !== null || retryPending || dueAtUtc === null} onClick={() => void mutate("due-date", { expectedOperationsRevision: operations.operationsRevision, dueAt: dueAtUtc })}>
                  마감 저장
                </button>
                <button className="btn" disabled={!canWrite || pending !== null || retryPending || !operations.dueAt} onClick={() => void mutate("due-date", { expectedOperationsRevision: operations.operationsRevision, dueAt: null })}>
                  마감 지우기
                </button>
              </div>
              <label className="flex flex-col gap-1 text-[13px] font-semibold">종료 메모 <span className="font-normal text-ink-muted">(선택)</span>
                <textarea className="input min-h-20" maxLength={500} value={closeNote} disabled={!canWrite || pending !== null || retryPending} onChange={(event) => setCloseNote(event.target.value)} placeholder="예: 현장 확인과 결과 검토를 마쳤습니다." />
              </label>
              <button className="btn btn-primary w-fit" disabled={!canWrite || pending !== null || retryPending} onClick={() => setCloseConfirm({ body: { expectedOperationsRevision: operations.operationsRevision, note: closeNote.trim() || null } })}>
                {pending?.kind === "close" ? "업무 종료 저장 중" : "업무 종료"}
              </button>
              <ConfirmDialog
                open={closeConfirm !== null}
                title="업무를 종료할까요?"
                description="종료하면 새 산출물 등록이 멈춥니다. 이미 진행 중인 등록·측정과 기존 결과는 계속 확인할 수 있으며, 필요하면 업무를 다시 열 수 있습니다."
                confirmLabel="업무 종료"
                pending={pending !== null}
                onCancel={() => setCloseConfirm(null)}
                onConfirm={() => {
                  const target = closeConfirm;
                  setCloseConfirm(null);
                  if (target) void mutate("close", target.body);
                }}
              />
              <p className="text-[12.5px] leading-5 text-ink-2">종료하면 새 산출물 등록이 멈추고, 이미 등록한 기록과 결과는 계속 확인할 수 있습니다.</p>
            </>}
            {isClosed && <button className="btn btn-primary w-fit" disabled={!canWrite || pending !== null || retryPending} onClick={() => void mutate("reopen", { expectedOperationsRevision: operations.operationsRevision })}>
              {pending?.kind === "reopen" ? "다시 열기 저장 중" : "업무 다시 열기"}
            </button>}
            {feedback && <p role="status" className="text-[13px] leading-5 text-ink-2">{feedback}</p>}
          </div>
          ) : (
            <ActionUnavailable label="작업 운영 정보 변경" description="현재 계정으로는 담당·기한·업무 종료를 변경할 수 없습니다. 작업 담당자에게 문의하세요." />
          )}
        </ResponsiveActionBoundary>
      </div>
    </section>
  );
}
