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
  continuity: string | null;
  workOrderId: string;
  // 요청 당시의 행위자. live principal prop이 마운트 중 바뀌어도 재시도
  // 검증은 동결된 이 값을 쓴다(BFF는 토큰으로 독립 검증).
  actorPrincipalId: string;
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

// 첫 시도 거부의 확정 문구 — 호출 시점의 실제 경로가 이번 키의 미기록을
// 증명하는 상태에서만 쓴다(401/403/404/409/422). 코드 없는 400 등은
// 원본 시도를 유지하므로 여기 오지 않는다.
function firstAttemptDefinitiveMessage(response: Response): string {
  if (response.status === 401) return "세션이 만료되어 저장하지 못했습니다. 이번 요청은 기록되지 않았습니다. 다시 로그인한 뒤 다시 시도하세요.";
  if (response.status === 403) return "권한 부족으로 저장하지 못했습니다. 이번 요청은 기록되지 않았습니다. 권한을 확인한 뒤 다시 시도하세요.";
  if (response.status === 404) return "대상을 찾지 못해 저장하지 못했습니다. 이번 요청은 기록되지 않았습니다. 대상을 확인한 뒤 다시 시도하세요.";
  if (response.status === 422) return "요청 내용이 확인 기준에 맞지 않아 저장하지 못했습니다. 이번 요청은 기록되지 않았습니다. 입력을 확인한 뒤 다시 시도하세요.";
  return "요청을 저장하지 못했습니다. 이번 요청은 기록되지 않았습니다. 같은 요청을 다시 시도하세요.";
}

function hasAmbiguousPersistence(response: Response): boolean {
  // A gateway timeout may arrive after Core appended the operation event. Keep
  // the frozen request so its idempotency key can reconcile that outcome.
  return response.status >= 500 || response.status === 408 || response.status === 429;
}

const CONTINUITY_FINGERPRINT_PATTERN = /^v1-[0-9a-f]{64}(?![\s\S])/;

// 읽기 전용 응답의 전체 형태·대상·범위 검사. 렌더에 필요한 필드가 실제
// 계약 타입(string|null)과 맞고 작업·조직·현장에 묶이는지 본다. 성공 확정과
// 새로고침이 같은 게이트를 쓰므로, 어느 한쪽만 느슨해질 수 없다.
function isReloadableOperationsView(
  value: unknown,
  workOrderId: string,
  scope: { organizationId: string; siteId: string } | null,
): value is ObservationWorkOrderOperationsView {
  if (!value || typeof value !== "object") return false;
  const view = value as Record<string, unknown>;
  if (view.schemaVersion !== "1.0" || view.workOrderId !== workOrderId) return false;
  if (typeof view.organizationId !== "string" || view.organizationId.length === 0) return false;
  if (typeof view.siteId !== "string" || view.siteId.length === 0) return false;
  if (scope !== null
    && (view.organizationId !== scope.organizationId || view.siteId !== scope.siteId)) return false;
  if (!Number.isInteger(view.operationsRevision)) return false;
  if (view.workflowStatus !== "OPEN" && view.workflowStatus !== "CLOSED" && view.workflowStatus !== "UNSPECIFIED") return false;
  if (!(view.assigneePrincipalId === null || typeof view.assigneePrincipalId === "string")) return false;
  if (!(view.dueAt === null || typeof view.dueAt === "string")) return false;
  if (!(view.closedAt === null || typeof view.closedAt === "string")) return false;
  if (!(view.closedBy === null || typeof view.closedBy === "string")) return false;
  if (!(view.closeNote === null || typeof view.closeNote === "string")) return false;
  if (!(view.updatedAt === null || typeof view.updatedAt === "string")) return false;
  if (!(view.updatedBy === null || typeof view.updatedBy === "string")) return false;
  return true;
}

// 2xx라도 무조건 저장 성공으로 믿지 않는다. 먼저 위 전체 형태 검사를 통과하고,
// 동결된 원래 요청의 변이 의도와 묶이는지 확인한 뒤에만 동결을 푼다. Core는
// 성공·멱등 재생 모두 `expectedOperationsRevision + 1`인 정확한 연산본을
// 돌려주므로, 리비전이 한 칸 오르지 않거나 액션 효과가 다르면 원본 시도를
// 유지하고 모름으로 둔다(성공 알림 없음). dueAt 비교는 Core 정규화 서식에
// 기대지 않고 UTC 동시각으로 견준다. 행위자(updatedBy·담당·종료자) 결박은
// Core가 변이마다 행위자를 기록한다는 보장에 기대며, 멱등 재생본도 그
// 기록을 그대로 돌려주므로 유효한 재생을 막지 않는다.
function sameUtcInstant(a: string | null, b: string | null): boolean {
  if (a === null || b === null) return a === null && b === null;
  const left = Date.parse(a);
  const right = Date.parse(b);
  return Number.isFinite(left) && Number.isFinite(right) && left === right;
}

function isConfirmedOperationsView(
  value: unknown,
  attempt: PendingAttempt,
  scope: { organizationId: string; siteId: string; actorPrincipalId: string },
): value is ObservationWorkOrderOperationsView {
  if (!isReloadableOperationsView(value, attempt.workOrderId, scope)) return false;
  const view = value as unknown as Record<string, unknown>;
  const body = attempt.body as Record<string, unknown>;
  const expected = body.expectedOperationsRevision;
  if (!Number.isInteger(expected) || view.operationsRevision !== (expected as number) + 1) return false;
  if (view.updatedBy !== scope.actorPrincipalId) return false;
  if (typeof view.updatedAt !== "string") return false;
  if (attempt.kind === "assignment") {
    if (view.workflowStatus !== "OPEN") return false;
    if (body.action === "ASSIGN_TO_ME") return view.assigneePrincipalId === scope.actorPrincipalId;
    if (body.action === "CLEAR") return view.assigneePrincipalId === null;
    if (body.action === "ASSIGN_TO_MEMBER") {
      return typeof body.assigneePrincipalId === "string" && body.assigneePrincipalId.length > 0
        && view.assigneePrincipalId === body.assigneePrincipalId;
    }
    return false;
  }
  if (attempt.kind === "due-date") {
    if (view.workflowStatus !== "OPEN") return false;
    if (typeof body.dueAt === "string") {
      return typeof view.dueAt === "string" && sameUtcInstant(view.dueAt, body.dueAt);
    }
    return body.dueAt == null && view.dueAt === null;
  }
  if (attempt.kind === "close") {
    if (view.workflowStatus !== "CLOSED") return false;
    if (typeof body.note === "string") {
      if (view.closeNote !== body.note) return false;
    } else if (body.note != null || view.closeNote !== null) {
      return false;
    }
    return view.closedBy === scope.actorPrincipalId;
  }
  if (attempt.kind === "reopen") return view.workflowStatus === "OPEN";
  return false;
}

// 동결된 재시도의 거부는 이번 재시도만 확정한다. 원래 모호한 요청이 이미 Core에
// 반영됐을 수 있으므로, 같은 키 재시도의 4xx/400을 원래 요청의 부재 증거로
// 단정하지 않고 동결을 유지한다. 첫 시도의 거부는 확정적이다.
function retryDenialMessage(response: Response): string {
  if (response.status === 401) return "다시 보낸 요청이 세션 만료로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 다른 탭에서 같은 계정으로 다시 로그인한 뒤 같은 요청으로 다시 시도하거나, 현재 상태를 다시 불러와 원래 요청이 이미 반영됐는지 먼저 확인하세요.";
  if (response.status === 403) return "다시 보낸 요청이 권한 부족으로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 권한을 확인한 뒤 같은 요청으로 다시 시도하거나, 현재 상태를 다시 불러와 원래 요청이 이미 반영됐는지 먼저 확인하세요.";
  if (response.status === 404) return "다시 보낸 요청에서 대상을 찾지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 현재 상태를 다시 불러와 원래 요청이 이미 반영됐는지 먼저 확인하세요.";
  if (response.status === 409) return "다시 보낸 요청이 거부되었습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 현재 상태를 다시 불러와 반영 여부를 확인하세요. 원래 요청이 이미 반영됐다면 동결된 요청을 버리세요.";
  if (response.status === 422) return "다시 보낸 요청이 확인 기준에 맞지 않아 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 현재 상태를 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요.";
  return "다시 보낸 요청이 요청 형식 확인을 통과하지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 현재 상태를 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요.";
}

export function WorkOrderOperationsPanel({
  workOrderId,
  principalId,
  initialOperations,
  canWrite,
  accountIdentity = null,
}: {
  workOrderId: string;
  principalId: string;
  initialOperations: ObservationWorkOrderOperationsView | null;
  canWrite: boolean;
  accountIdentity?: { fingerprint: string } | null;
}) {
  const router = useRouter();
  const { notify } = useToast();
  const [operations, setOperations] = useState(initialOperations);
  const [dueAt, setDueAt] = useState(() => seoulDateTimeLocalValue(initialOperations?.dueAt ?? null));
  const [closeNote, setCloseNote] = useState("");
  const [closeConfirm, setCloseConfirm] = useState<{ body: Record<string, unknown> } | null>(null);
  const [pending, setPending] = useState<PendingAttempt | null>(null);
  const [unresolvedRetry, setUnresolvedRetry] = useState<PendingAttempt | null>(null);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
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
  // 첫 시도 화면의 서버 파생 신원 비교값 — 호출자 입력이 아니라 page가 서버에서
  // 읽은 값이다. 재시도는 원래 값을 그대로 보내 BFF가 현재 세션과 비교한다.
  // 원문 식별자는 클라이언트에 내보내지 않는다. 값이 없거나 깨졌으면 새 변경을
  // 시작하지 않는다(확인값 없는 재시도는 BFF 비교를 우회하므로). 이미 동결된
  // 요청의 같은 키 재시도는 원래 확인값을 그대로 보내므로 막지 않는다.
  // BFF의 헤더-없음 호환은 다른 호출부용으로 그대로 둔다.
  const boundContinuity = accountIdentity?.fingerprint;
  const boundContinuityOrNull = typeof boundContinuity === "string" && CONTINUITY_FINGERPRINT_PATTERN.test(boundContinuity)
    ? boundContinuity
    : null;

  async function refresh({ preserveDraft = false }: { preserveDraft?: boolean } = {}) {
    const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/operations`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("operations refresh failed");
    const data: unknown = await response.json();
    // 읽기 전용 조회라도 형태·대상·범위가 맞아야 화면을 교체한다. 깨진 JSON이나
    // 다른 작업의 메아리면 기존 표시를 유지하고 실패로 둔다. 새로고침 성공은
    // 현재 상태일 뿐, 어느 키가 반영됐는지는 증명하지 않는다.
    if (!isReloadableOperationsView(data, workOrderId, operations ? { organizationId: operations.organizationId, siteId: operations.siteId } : null)) {
      throw new Error("operations refresh shape mismatch");
    }
    const next = data;
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
    if (sameRetry !== null && sameRetry.workOrderId !== workOrderId) {
      // 동결된 요청은 원래 작업 경로에 묶인다. 마운트 유지 채 다른 작업으로
      // 바뀌어도 경로를 옮겨 보내지 않고, 동결도 풀지 않는다. 이 동결은 이
      // 화면의 기억에만 있어 이동·새로고침하면 사라지며, 같은 키 재시도는
      // 다른 화면으로 이어지지 않는다.
      setFeedback(`동결된 요청은 다른 작업(${sameRetry.workOrderId})의 것으로, 이 화면의 작업이 바뀌어 다시 보내지 않았습니다. 다른 작업 경로로 옮겨 보내지도 않습니다. 이 동결은 이 화면의 기억에만 있어 이동·새로고침하면 사라지며, 같은 키 재시도는 이어지지 않습니다. 원래 작업 화면에서 기록 여부를 먼저 확인하세요. 확인 뒤에는 여기에서 동결된 요청을 버리세요.`);
      return;
    }
    if (sameRetry === null && boundContinuityOrNull === null) {
      // 새 변경은 검증된 확인값이 있을 때만 시작한다. 확인값 없이 보내면
      // BFF 비교가 생략되어 모호한 재시도의 중복 방지가 깨진다.
      setFeedback("계정을 확인하지 못해 새 변경을 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 현재 표시된 운영 상태는 그대로 확인할 수 있습니다. 새로고침하면 입력과 동결된 요청이 사라집니다.");
      return;
    }
    const attempt = sameRetry ?? { kind, body, key: `operations-${crypto.randomUUID()}`, continuity: boundContinuityOrNull, workOrderId, actorPrincipalId: principalId };
    submitLock.current = true;
    setPending(attempt);
    setFeedback(null);
    const endpoint = kind === "assignment"
      ? "assignment"
      : kind === "due-date"
        ? "due-date"
        : kind;
    const method = kind === "due-date" ? "PUT" : "POST";
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "Idempotency-Key": attempt.key,
    };
    // 호출자 주장(principal 문자열)은 보내지 않는다. 비교값만 보내고, 현재
    // 신원은 BFF가 같은 요청의 세션 토큰 하나로 확인한다.
    if (attempt.continuity) headers["x-ksi-continuity-fingerprint"] = attempt.continuity;
    try {
      const response = await fetch(
        `/api/observation-work-orders/${encodeURIComponent(attempt.workOrderId)}/operations/${endpoint}`,
        {
          method,
          headers,
          body: JSON.stringify(body),
        },
      );
      const payload: unknown = await response.json().catch(() => null);
      const responseCode = payload && typeof payload === "object" && "code" in payload
        ? String((payload as { code?: unknown }).code ?? "")
        : "";
      // 계정이 바뀐 같은 키 재시도는 BFF가 Core 변이 없이 끊는다. 원래 키·내용을
      // 버리면 중복 기록으로 이어지므로 동결을 유지한다. 이는 중복 방지 가드이며
      // Core 권한·범위 판단을 대신하지 않는다.
      if (response.status === 409 && responseCode === "ACCOUNT_CONTINUITY_MISMATCH") {
        unresolvedRetryRef.current = attempt;
        setUnresolvedRetry(attempt);
        setFeedback("계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 요청으로 다시 시도하세요. 먼저 현재 상태를 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다.");
        return;
      }
      if (response.status === 400 && responseCode === "INVALID_CONTINUITY_CLAIM") {
        unresolvedRetryRef.current = attempt;
        setUnresolvedRetry(attempt);
        setFeedback("계정 연속성 확인값이 올바르지 않아 요청을 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 현재 상태를 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요. 화면을 새로고침하면 서버에서 새 확인값을 받아옵니다. 새로고침하면 입력과 요청이 사라집니다.");
        return;
      }
      if (!response.ok) {
        if (hasAmbiguousPersistence(response)) {
          unresolvedRetryRef.current = attempt;
          setUnresolvedRetry(attempt);
          setFeedback("응답을 확인하지 못했습니다. 같은 요청을 다시 시도하세요.");
          return;
        }
        if (sameRetry !== null) {
          // 동결된 시도(attempt.posted相当)의 재시도가 거부를 받으면, 그 거부는
          // 이번 재시도만 확정할 뿐이다. 이전 모호한 요청이 이미 반영됐을 수
          // 있으므로 동결을 유지하고 같은 키 재시도·상태 확인 경로를 살린다.
          // 409(수정 번호 충돌·상태 충돌 등)는 읽기 전용 새로고침으로 현재
          // 상태를 보여주되, 동결은 풀지 않는다.
          const refreshed = response.status === 409
            && await refresh({ preserveDraft: true }).then(() => true).catch(() => false);
          unresolvedRetryRef.current = attempt;
          setUnresolvedRetry(attempt);
          setFeedback(refreshed
            ? `${retryDenialMessage(response)} 현재 상태를 다시 불러왔습니다.`
            : retryDenialMessage(response));
          return;
        }
        // 첫 시도의 거부는 확정적이다 — 단, 실제 경로가 증명하는 상태에서만
        // 부재를 단정한다. 401/403/404/409/422는 BFF 세션 게이트·Core 권한·
        // 범위 검사가 변이보다 먼저 거부하므로 이번 키는 기록되지 않았다.
        // 상태만으로는 BFF 거절인지 Core 거절인지 증명할 수 없는 응답(예:
        // 코드 없는 400, 그 밖의 상태)은 단정하지 않고 원본 시도를 유지한다.
        const provenDefinitive = response.status === 401 || response.status === 403
          || response.status === 404 || response.status === 409 || response.status === 422;
        if (!provenDefinitive) {
          // 읽기 전용 확인 외에 변이를 만들지 않고, 원본 키의 재시도 경로만 살린다.
          unresolvedRetryRef.current = attempt;
          setUnresolvedRetry(attempt);
          setFeedback(`요청이 거부되었습니다(상태 ${response.status}). 기록 여부를 확인할 수 없으니 현재 상태를 먼저 확인하세요. 같은 요청으로 다시 시도할 수 있습니다. 입력과 선택은 그대로 있습니다.`);
          return;
        }
        const refreshed = response.status === 409
          && await refresh({ preserveDraft: true }).then(() => true).catch(() => false);
        unresolvedRetryRef.current = null;
        setUnresolvedRetry(null);
        setConfirmingDiscard(false);
        if (response.status === 409) {
          setFeedback(refreshed
            ? errorMessage(response, payload)
            : "요청은 저장되지 않았습니다. 최신 운영 정보를 불러오지 못했습니다. 다시 불러오거나 같은 내용을 확인하세요.");
          return;
        }
        setFeedback(firstAttemptDefinitiveMessage(response));
        return;
      }
      // 2xx라도 렌더 가능한 확정 응답이 아니면 성공으로 단정하지 않는다.
      // 다른 작업의 메아리·깨진 JSON이면 원본 동결을 유지하고 모름으로 둔다.
      if (!isConfirmedOperationsView(payload, attempt, { organizationId: operations.organizationId, siteId: operations.siteId, actorPrincipalId: attempt.actorPrincipalId })) {
        unresolvedRetryRef.current = attempt;
        setUnresolvedRetry(attempt);
        setFeedback("저장 응답을 확인하지 못했습니다. 기록 여부는 알 수 없습니다. 같은 요청으로 다시 시도하거나 현재 상태를 먼저 확인하세요.");
        return;
      }
      const next = payload;
      // 멱등 재생은 원본 성공 리비전을 그대로 돌려준다. 그 사이 진짜 업데이트가
      // 있었다면 반환본이 화면보다 과거일 수 있다 — 이때는 원래 요청의 확인으로
      // 해소하되, 더 최신인 화면을 과거로 덮어쓰지 않고 저장 완료로도 말하지 않는다.
      if (operations && next.operationsRevision < operations.operationsRevision) {
        unresolvedRetryRef.current = null;
        setUnresolvedRetry(null);
        setConfirmingDiscard(false);
        setFeedback("원래 요청이 이미 반영된 것을 확인했습니다. 이 응답은 이전 요청의 확인용이며, 화면의 최신 상태는 그대로 둡니다.");
        return;
      }
      setOperations(next);
      setDueAt(seoulDateTimeLocalValue(next.dueAt));
      setCloseNote("");
      unresolvedRetryRef.current = null;
      setUnresolvedRetry(null);
      setConfirmingDiscard(false);
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

  async function reloadState() {
    if (pending !== null || unresolvedRetry === null) return;
    if (unresolvedRetry.workOrderId !== workOrderId) {
      setFeedback(`동결된 요청은 다른 작업(${unresolvedRetry.workOrderId})의 것입니다. 이 화면에서는 상태를 다시 불러오지 않았습니다. 이 동결은 이 화면의 기억에만 있어 이동·새로고침하면 사라집니다. 원래 작업 화면에서 기록 여부를 먼저 확인하세요.`);
      return;
    }
    try {
      await refresh({ preserveDraft: true });
      setFeedback("현재 상태를 다시 불러왔습니다. 동결된 요청은 그대로 있습니다. 같은 요청으로 다시 시도하거나, 원래 요청이 이미 반영됐다면 동결된 요청을 버리세요.");
    } catch {
      setFeedback("현재 상태를 다시 불러오지 못했습니다. 동결된 요청은 그대로 있습니다. 같은 요청으로 다시 시도하세요.");
    }
  }

  function discardUnresolved() {
    if (pending !== null || unresolvedRetryRef.current === null) return;
    // 명시적 버리기 — 새 변이를 보내지 않고 동결만 푼다. 버린 요청이 처리
    // 되었는지는 알 수 없으니 현재 상태를 먼저 확인해야 한다. 다음 저장은
    // 새 키의 새 요청으로 기록되며, 같은 키 재시도 보호는 사라진다.
    unresolvedRetryRef.current = null;
    setUnresolvedRetry(null);
    setConfirmingDiscard(false);
    setFeedback("동결된 요청을 버렸습니다. 버린 요청이 처리되었는지는 알 수 없으니 현재 상태를 먼저 확인하세요. 다음 저장은 새 요청으로 기록됩니다.");
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

  // 동결 복구 상자. allowRetry가 거짓이면(쓰기 권한 상실) 변이 재시도 단추를
  // 내놓지 않고 읽기 전용 새로고침·확정 버리기만 둔다. 어느 쪽도 새 변이를
  // 만들지 않으며, 같은 키 재시도는 쓰기 권한이 있을 때만 가능하다.
  const renderFrozenBox = (allowRetry: boolean) => (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] leading-5 text-ink-2">
      <p>이전 저장 요청의 응답을 확인하지 못했습니다. 같은 요청을 먼저 확인하세요.</p>
      <p className="mt-1">주의: 이 요청은 이미 기록됐을 수 있습니다. 버린 뒤 다시 저장하면 새 요청(새 키)으로 기록됩니다.</p>
      <p className="mt-1">이 요청의 기억은 이 화면에만 있어 새로고침·화면 이동·기기 변경 뒤에는 같은 키로 다시 시도할 수 없습니다. 현재 상태를 먼저 확인하세요.</p>
      {!confirmingDiscard ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {allowRetry && <button className="btn" disabled={pending !== null} onClick={() => void mutate(unresolvedRetry!.kind, unresolvedRetry!.body)}>같은 요청 다시 시도</button>}
          <button className="btn" disabled={pending !== null} onClick={() => void reloadState()}>현재 상태 다시 불러오기</button>
          <button className="btn" disabled={pending !== null} onClick={() => setConfirmingDiscard(true)}>동결된 요청 버리기</button>
        </div>
      ) : (
        <div className="mt-2">
          <p>정말 버릴까요? 버린 요청의 처리 여부는 알 수 없습니다. 같은 키 재시도는 사라지고, 다음 저장은 새 요청이 됩니다.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button className="btn" disabled={pending !== null} onClick={() => discardUnresolved()}>버리기 확인</button>
            <button className="btn" disabled={pending !== null} onClick={() => setConfirmingDiscard(false)}>취소</button>
          </div>
        </div>
      )}
    </div>
  );

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
            {unresolvedRetry && renderFrozenBox(true)}
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
            <>
              {unresolvedRetry && (
                <div className="flex flex-col gap-3 rounded-lg bg-sunk p-3">
                  {renderFrozenBox(false)}
                  {feedback && <p role="status" className="text-[13px] leading-5 text-ink-2">{feedback}</p>}
                </div>
              )}
              <ActionUnavailable label="작업 운영 정보 변경" description="현재 계정으로는 담당·기한·업무 종료를 변경할 수 없습니다. 작업 담당자에게 문의하세요." />
            </>
          )}
        </ResponsiveActionBoundary>
        {unresolvedRetry && (
          <div className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] leading-5 text-ink-2 lg:hidden">
            <p>이전 저장 요청의 응답을 확인하지 못했습니다. 결과는 알 수 없습니다.</p>
            <p className="mt-1">이 요청의 기억은 이 화면에만 있어 새로고침·화면 이동·기기 변경 뒤에는 같은 키로 다시 시도할 수 없습니다. 노트북의 같은 화면에서 원래 기록을 먼저 확인하세요.</p>
          </div>
        )}
      </div>
    </section>
  );
}
