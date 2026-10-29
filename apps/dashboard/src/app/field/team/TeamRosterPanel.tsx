"use client";

import { useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { useToast } from "@/components/ui/ToastProvider";

type Member = { schemaVersion: "1.0"; organizationId: string; principalId: string; displayName: string; roleHint: "ADMIN" | "FIELD_OPERATOR" | "VIEWER"; status: "ACTIVE" | "INACTIVE"; revision: number; updatedAt: string; updatedBy: string };

type Draft = { principalId: string; displayName: string; roleHint: Member["roleHint"]; status: Member["status"]; expectedRevision: number };
const initialDraft: Draft = { principalId: "", displayName: "", roleHint: "FIELD_OPERATOR", status: "ACTIVE", expectedRevision: 0 };

function roleLabel(roleHint: Member["roleHint"]): string {
  return roleHint === "ADMIN" ? "관리자" : roleHint === "FIELD_OPERATOR" ? "현장담당" : "열람자";
}

const FINGERPRINT_PATTERN = /^v1-[0-9a-f]{64}(?![\s\S])/;

// 2xx 응답도 무조건 저장 성공으로 믿지 않는다. 렌더에 필요한 형태를 갖추고
// 동결된 원래 요청과 묶이는지 확인한 뒤에만 동결을 푼다. Core는 성공·멱등
// 재생 모두 `expectedRevision + 1`인 요청 정규화 반영본을 돌려주므로,
// 리비전이 한 칸 오르지 않거나 표시 이름·업무 구분·상태가 요청과 다르면
// 원본 시도를 유지하고 모름으로 둔다(성공 알림 없음). 형태가 깨졌거나
// 다른 팀원의 메아리여도 마찬가지다.
// 읽기 전용 목록 조회도 형태가 맞아야 화면을 교체한다. 배열이 아니거나 렌더
// 필수 항목이 깨졌거나 비어 있으면 기존 목록을 유지하고 실패로 둔다.
// 새로고침 성공은 현재 목록일 뿐, 어느 키가 반영됐는지는 증명하지 않는다.
function isReloadableRosterMember(value: unknown, organizationId: string | null): value is Member {
if (!value || typeof value !== "object") return false;
const member = value as Record<string, unknown>;
if (member.schemaVersion !== "1.0") return false;
if (typeof member.organizationId !== "string" || member.organizationId.length === 0) return false;
if (organizationId !== null && member.organizationId !== organizationId) return false;
return typeof member.principalId === "string" && member.principalId.length > 0
  && typeof member.displayName === "string" && member.displayName.length > 0
  && (member.roleHint === "ADMIN" || member.roleHint === "FIELD_OPERATOR" || member.roleHint === "VIEWER")
  && (member.status === "ACTIVE" || member.status === "INACTIVE")
  && Number.isInteger(member.revision) && (member.revision as number) >= 1
  && typeof member.updatedAt === "string" && member.updatedAt.length > 0
  && typeof member.updatedBy === "string" && member.updatedBy.length > 0;
}

function isConfirmedRosterMember(
  value: unknown,
  attempt: { key: string; draft: { principalId: string; displayName: string; roleHint: Member["roleHint"]; status: Member["status"]; expectedRevision: number }; continuity: string | null; actorPrincipalId: string; organizationId: string },
): value is Member {
  if (!isReloadableRosterMember(value, attempt.organizationId)) return false;
  const member = value as unknown as Member;
  if (member.principalId !== attempt.draft.principalId) return false;
  if (!Number.isInteger(attempt.draft.expectedRevision)
    || member.revision !== (attempt.draft.expectedRevision as number) + 1) return false;
  if (member.displayName !== attempt.draft.displayName.trim()) return false;
  if (member.roleHint !== attempt.draft.roleHint || member.status !== attempt.draft.status) return false;
  // 응답 행위자·조직은 동결 당시의 요청 범위에 묶인다. live prop이 마운트 중
  // 바뀌어도 동결된 값을 쓴다(BFF는 토큰으로 독립 검증).
  return member.updatedBy === attempt.actorPrincipalId;
}

// 동결된 재시도의 거부는 이번 재시도만 확정한다. 원래 모호한 요청이 이미 Core에
// 반영됐을 수 있으므로, 같은 키 재시도의 4xx/400을 원래 요청의 부재 증거로
// 단정하지 않고 동결을 유지한다. 첫 시도의 거부는 확정적이다.
function retryDenialMessage(status: number): string {
  if (status === 401) return "다시 보낸 요청이 세션 만료로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 다른 탭에서 같은 계정으로 다시 로그인한 뒤 같은 요청으로 다시 시도하거나, 팀원 목록을 다시 불러와 원래 요청이 이미 반영됐는지 먼저 확인하세요.";
  if (status === 403) return "다시 보낸 요청이 권한 부족으로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 권한을 확인한 뒤 같은 요청으로 다시 시도하거나, 팀원 목록을 다시 불러와 원래 요청이 이미 반영됐는지 먼저 확인하세요.";
  if (status === 404) return "다시 보낸 요청에서 대상을 찾지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 팀원 목록을 다시 불러와 원래 요청이 이미 반영됐는지 먼저 확인하세요.";
  if (status === 409) return "다시 보낸 요청이 거부되었습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 팀원 목록을 다시 불러와 반영 여부를 확인하세요. 원래 요청이 이미 반영됐다면 동결된 요청을 버리세요.";
  if (status === 422) return "다시 보낸 요청이 확인 기준에 맞지 않아 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 팀원 목록을 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요.";
  return "다시 보낸 요청이 요청 형식 확인을 통과하지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 팀원 목록을 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요.";
}

export function TeamRosterPanel({ initialMembers, canManage, currentPrincipalId, organizationId, accountIdentity = null }: { initialMembers: Member[]; canManage: boolean; currentPrincipalId: string; organizationId: string; accountIdentity?: { fingerprint: string } | null }) {
  const { notify } = useToast();
  const [members, setMembers] = useState(initialMembers);
  const [draft, setDraft] = useState(initialDraft);
  const [pending, setPending] = useState<{ key: string; draft: typeof draft; continuity: string | null; actorPrincipalId: string; organizationId: string } | null>(null);
  const [unresolved, setUnresolved] = useState<{ key: string; draft: typeof draft; continuity: string | null; actorPrincipalId: string; organizationId: string } | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [conflictedPrincipalId, setConflictedPrincipalId] = useState<string | null>(null);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
  const saveLock = useRef(false);
  const unresolvedRef = useRef<{ key: string; draft: typeof draft; continuity: string | null; actorPrincipalId: string; organizationId: string } | null>(null);
  // 첫 시도 화면의 서버 파생 신원 비교값 — 호출자 입력이 아니라 page가 서버에서
  // 읽은 값이다. 재시도는 원래 값을 그대로 보내 BFF가 현재 세션과 비교한다.
  // 비교값은 자격 증명이 아니다. 값이 없거나 깨졌으면 새 저장을 시작하지
  // 않는다(확인값 없는 재시도는 BFF 비교를 우회하므로). 이미 동결된
  // 요청의 같은 키 재시도는 원래 확인값을 그대로 보내므로 막지 않는다.
  // BFF의 헤더-없음 호환은 다른 호출부용으로 그대로 둔다.
  const boundContinuity = accountIdentity?.fingerprint;
  const boundContinuityOrNull = typeof boundContinuity === "string" && FINGERPRINT_PATTERN.test(boundContinuity)
    ? boundContinuity
    : null;
  const frozenSave = pending !== null || unresolved !== null;

  function edit(member: Member) {
    if (frozenSave) return;
    setDraft({ principalId: member.principalId, displayName: member.displayName, roleHint: member.roleHint, status: member.status, expectedRevision: member.revision });
    setFeedback(null);
  }

  async function reloadRoster() {
    try {
      const response = await fetch("/api/organization-work-roster?includeInactive=true", { cache: "no-store" });
      if (!response.ok) throw new Error("roster unavailable");
      const payload: unknown = await response.json();
      const members = payload && typeof payload === "object" && "members" in payload
        ? (payload as { members?: unknown }).members
        : undefined;
      if (!Array.isArray(members) || !members.every((member) => isReloadableRosterMember(member, organizationId))) {
        throw new Error("roster shape mismatch");
      }
      const latest = members;
      setMembers(latest);
      // 동결된 요청이 있으면 초안을 건드리지 않는다 — 초안을 바꾸면 같은 키
      // 재시도 판별이 깨져 복구 경로가 막힌다. 목록만 갱신하고 동결은 유지한다.
      if (unresolvedRef.current !== null) {
        setFeedback("최신 팀원 목록을 불러왔습니다. 동결된 요청은 그대로 있습니다. 같은 요청으로 다시 시도하거나, 원래 요청이 이미 반영됐다면 동결된 요청을 버리세요.");
        return;
      }
      const current = conflictedPrincipalId && latest.find((member) => member.principalId === conflictedPrincipalId);
      if (current && draft.principalId === current.principalId) {
        setDraft((previous) => ({ ...previous, expectedRevision: current.revision }));
        setFeedback("최신 수정 번호를 적용했습니다. 표시 이름과 업무 구분·상태 입력은 유지했습니다. 저장을 다시 선택하세요.");
      } else {
        setFeedback("최신 팀원 목록을 불러왔습니다. 충돌한 항목을 다시 선택해 확인하세요.");
      }
      setConflictedPrincipalId(null);
    } catch {
      setFeedback("최신 팀원 목록을 불러오지 못했습니다. 다시 시도하세요.");
    }
  }

  function discardUnresolved() {
    if (pending !== null || unresolvedRef.current === null) return;
    // 명시적 버리기 — 새 변이를 보내지 않고 동결만 푼다. 버린 요청이 처리
    // 되었는지는 알 수 없으니 목록을 먼저 확인해야 한다. 다음 저장은
    // 새 키의 새 요청으로 기록되며, 같은 키 재시도 보호는 사라진다.
    unresolvedRef.current = null;
    setUnresolved(null);
    setConfirmingDiscard(false);
    setFeedback("동결된 요청을 버렸습니다. 버린 요청이 처리되었는지는 알 수 없으니 목록을 먼저 확인하세요. 다음 저장은 새 요청으로 기록됩니다.");
  }

  async function save() {
    if (!canManage || pending || saveLock.current || !draft.principalId.trim() || !draft.displayName.trim()) return;
    const retry = unresolved && JSON.stringify(unresolved.draft) === JSON.stringify(draft) ? unresolved : null;
    if (unresolved && retry === null) {
      setFeedback("이전 저장 요청의 응답을 확인하지 못했습니다. 같은 요청을 먼저 다시 시도하세요.");
      return;
    }
    if (retry === null && boundContinuityOrNull === null) {
      // 새 저장은 검증된 확인값이 있을 때만 시작한다. 확인값 없이 보내면
      // BFF 비교가 생략되어 모호한 재시도의 중복 방지가 깨진다.
      setFeedback("계정을 확인하지 못해 새 저장을 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 현재 표시된 팀원 목록은 그대로 확인할 수 있습니다. 새로고침하면 입력과 동결된 요청이 사라집니다.");
      return;
    }
    const attempt = retry ?? { key: `team-roster-${crypto.randomUUID()}`, draft, continuity: boundContinuityOrNull, actorPrincipalId: currentPrincipalId, organizationId };
    saveLock.current = true;
    setPending(attempt);
    setFeedback(null);
    try {
      // 호출자 주장(principal 문자열)은 보내지 않는다. 비교값만 보내고, 현재
      // 신원은 BFF가 같은 요청의 세션 토큰 하나로 확인한다. 경로는 동결된
      // 원래 대상 식별자를 그대로 쓴다.
      const headers: Record<string, string> = {
        "content-type": "application/json",
        "Idempotency-Key": attempt.key,
      };
      if (attempt.continuity) headers["x-ksi-continuity-fingerprint"] = attempt.continuity;
      const response = await fetch(`/api/organization-work-roster/${encodeURIComponent(attempt.draft.principalId)}`, {
        method: "PUT",
        headers,
        body: JSON.stringify({ expectedRevision: attempt.draft.expectedRevision, displayName: attempt.draft.displayName.trim(), roleHint: attempt.draft.roleHint, status: attempt.draft.status }),
      });
      const body: unknown = await response.json().catch(() => null);
      const responseCode = body && typeof body === "object" && "code" in body
        ? String((body as { code?: unknown }).code ?? "")
        : "";
      // 계정이 바뀐 같은 키 재시도는 BFF가 Core 변이 없이 끊는다. 원래 키·내용을
      // 버리면 중복 기록으로 이어지므로 동결을 유지한다. 이는 중복 방지 가드이며
      // Core 권한·범위 판단을 대신하지 않는다.
      if (response.status === 409 && responseCode === "ACCOUNT_CONTINUITY_MISMATCH") {
        unresolvedRef.current = attempt;
        setUnresolved(attempt);
        setFeedback("계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 요청으로 다시 시도하세요. 먼저 팀원 목록을 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다.");
        return;
      }
      if (response.status === 400 && responseCode === "INVALID_CONTINUITY_CLAIM") {
        unresolvedRef.current = attempt;
        setUnresolved(attempt);
        setFeedback("계정 연속성 확인값이 올바르지 않아 요청을 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 팀원 목록을 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요. 화면을 새로고침하면 서버에서 새 확인값을 받아옵니다. 새로고침하면 입력과 요청이 사라집니다.");
        return;
      }
      if (!response.ok) {
        if (response.status >= 500 || response.status === 408 || response.status === 429) {
          unresolvedRef.current = attempt;
          setUnresolved(attempt);
          setFeedback("응답을 확인하지 못했습니다. 입력은 유지했습니다. 다시 시도하세요.");
          return;
        }
        if (retry !== null) {
          // 동결된 시도의 재시도가 거부를 받으면, 그 거부는 이번 재시도만
          // 확정할 뿐이다. 이전 모호한 요청이 이미 반영됐을 수 있으므로
          // 동결을 유지하고 같은 키 재시도·목록 확인 경로를 살린다.
          unresolvedRef.current = attempt;
          setUnresolved(attempt);
          if (response.status === 409) {
            setConflictedPrincipalId(attempt.draft.principalId);
          }
          setFeedback(retryDenialMessage(response.status));
          return;
        }
        unresolvedRef.current = null;
        setUnresolved(null);
        setConfirmingDiscard(false);
        // 첫 시도의 거부는 확정적이다 — 단, 실제 경로가 증명하는 상태에서만
        // 부재를 단정한다. 401/403/404/409/422는 BFF 세션 게이트·Core 권한·
        // 범위 검사가 변이보다 먼저 거부하므로 이번 키는 기록되지 않았다.
        // 상태만으로는 BFF 거절인지 Core 거절인지 증명할 수 없는 응답(예:
        // 코드 없는 400, 그 밖의 상태)은 단정하지 않고 원본 시도를 유지한다.
        if (response.status !== 401 && response.status !== 403
          && response.status !== 404 && response.status !== 409 && response.status !== 422) {
          // 읽기 전용 확인 외에 변이를 만들지 않고, 원본 키의 재시도 경로만 살린다.
          unresolvedRef.current = attempt;
          setUnresolved(attempt);
          setFeedback("요청이 거부되었습니다. 기록 여부를 확인할 수 없으니 목록을 먼저 확인하세요. 같은 요청으로 다시 시도할 수 있습니다. 입력은 그대로 있습니다.");
          return;
        }
        if (response.status === 409) {
          setConflictedPrincipalId(attempt.draft.principalId);
          setFeedback("다른 변경이 먼저 저장되었습니다. 입력은 유지했습니다. 최신 팀원 목록을 불러와 수정 번호를 확인하세요.");
        } else {
          setFeedback("팀원 정보를 저장하지 못했습니다. 입력을 확인하고 다시 시도하세요.");
        }
        return;
      }
      // 2xx라도 렌더 가능한 확정 응답이 아니면 성공으로 단정하지 않는다.
      // 다른 팀원의 메아리·깨진 JSON이면 원본 동결을 유지하고 모름으로 둔다.
      if (!isConfirmedRosterMember(body, attempt)) {
        unresolvedRef.current = attempt;
        setUnresolved(attempt);
        setFeedback("저장 응답을 확인하지 못했습니다. 기록 여부는 알 수 없습니다. 같은 요청으로 다시 시도하거나 목록을 먼저 확인하세요. 입력은 그대로 있습니다.");
        return;
      }
      const saved = body;
      // 멱등 재생은 원본 성공 기록을 그대로 돌려준다. 그 사이 진짜 업데이트가
      // 있었다면 반환본이 목록보다 과거일 수 있다 — 이때는 원래 요청의 확인으로
      // 해소하되, 더 최신인 목록을 과거로 덮어쓰지 않고 저장 완료로도 말하지 않는다.
      const known = members.find((member) => member.principalId === saved.principalId);
      if (known && saved.revision < known.revision) {
        unresolvedRef.current = null;
        setUnresolved(null);
        setConfirmingDiscard(false);
        setFeedback("원래 요청이 이미 반영된 것을 확인했습니다. 이 응답은 이전 요청의 확인용이며, 목록의 최신 상태는 그대로 둡니다.");
        return;
      }
      setMembers((current) => [...current.filter((member) => member.principalId !== saved.principalId), saved].toSorted((a, b) => a.displayName.localeCompare(b.displayName, "ko")));
      setDraft(initialDraft);
      unresolvedRef.current = null;
      setUnresolved(null);
      setConfirmingDiscard(false);
      setFeedback(null);
      notify("팀원 정보를 저장했습니다.");
    } catch {
      unresolvedRef.current = attempt;
      setUnresolved(attempt);
      setFeedback("응답을 확인하지 못했습니다. 입력은 유지했습니다. 다시 시도하세요.");
    } finally {
      setPending(null);
      saveLock.current = false;
    }
  }

  return <div className="flex flex-col gap-4">
    <section className="rounded-xl border border-line bg-surface px-4 py-3">
      <h2 className="text-[15px] font-bold">조직 작업 팀</h2>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">업무 구분은 작업 흐름 안내용 정보입니다. 계정 생성·로그인 초대·권한 부여는 여기서 하지 않습니다.</p>
      <p className="mt-2 text-[12px] text-ink-muted">현재 사용자 · {currentPrincipalId}</p>
    </section>
    <section className="overflow-hidden rounded-xl border border-line bg-surface">
      <ul className="divide-y divide-line px-4">{members.map((member) => <li key={member.principalId} className="flex flex-wrap items-center justify-between gap-2 py-3"><span><span className="block text-[14px] font-semibold">{member.displayName}</span><span className="block text-[12px] text-ink-2">{member.principalId} · 업무 구분 {roleLabel(member.roleHint)} · {member.status === "ACTIVE" ? "활성" : "비활성"}</span></span>{canManage && <button className="btn" disabled={frozenSave} onClick={() => edit(member)}>수정</button>}</li>)}</ul>
      {members.length === 0 && (canManage ? <p className="px-4 py-3 text-[13px] text-ink-2">작업 배정과 결과 공유에 쓸 팀원 정보를 추가할 수 있습니다. 이 등록은 계정이나 권한을 만들지 않습니다.</p> : <p className="px-4 py-3 text-[13px] text-ink-2">등록된 팀원 정보가 없습니다. 작업 배정·공유 대상은 관리자에게 확인하세요.</p>)}
    </section>
    <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" reason="팀원 정보는 노트북 이상의 화면에서 관리합니다.">
      {canManage ? <section className="rounded-xl border border-line bg-surface p-4"><h2 className="text-[15px] font-bold">팀원 등록 또는 수정</h2><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="flex flex-col gap-1 text-[13px] font-semibold">사용자 ID<input aria-label="사용자 ID" disabled={frozenSave} className="input" value={draft.principalId} onChange={(event) => setDraft({ ...draft, principalId: event.target.value })} /><span className="text-[12px] font-normal text-ink-muted">조직에서 쓰는 안정된 사용자 식별자입니다.</span></label><label className="flex flex-col gap-1 text-[13px] font-semibold">표시 이름<input disabled={frozenSave} className="input" value={draft.displayName} onChange={(event) => setDraft({ ...draft, displayName: event.target.value })} /></label><label className="flex flex-col gap-1 text-[13px] font-semibold">업무 구분<select disabled={frozenSave} className="input" value={draft.roleHint} onChange={(event) => setDraft({ ...draft, roleHint: event.target.value as typeof draft.roleHint })}><option value="ADMIN">관리자</option><option value="FIELD_OPERATOR">현장담당</option><option value="VIEWER">열람자</option></select></label><label className="flex flex-col gap-1 text-[13px] font-semibold">상태<select disabled={frozenSave} className="input" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as typeof draft.status })}><option value="ACTIVE">활성</option><option value="INACTIVE">비활성</option></select></label></div><div className="mt-3 flex flex-wrap gap-2"><button className="btn btn-primary" disabled={pending !== null || !draft.principalId.trim() || !draft.displayName.trim()} onClick={() => void save()}>{pending ? "저장 중" : unresolved ? "같은 요청 다시 시도" : "팀원 정보 저장"}</button>{unresolved && !confirmingDiscard && <><button className="btn" disabled={pending !== null} onClick={() => void reloadRoster()}>최신 팀원 목록 불러오기</button><button className="btn" disabled={pending !== null} onClick={() => setConfirmingDiscard(true)}>동결된 요청 버리기</button></>}{conflictedPrincipalId && !unresolved && <button className="btn" disabled={pending !== null || unresolved !== null} onClick={() => void reloadRoster()}>최신 팀원 목록 불러오기</button>}</div>{unresolved && !confirmingDiscard && <p className="mt-2 text-[12.5px] leading-5 text-ink-2">주의: 이 요청은 이미 반영됐을 수 있습니다. 버린 뒤 다시 저장하면 새 요청(새 키)으로 기록됩니다.</p>}{unresolved && confirmingDiscard && <div className="mt-2 rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] leading-5 text-ink-2"><p>정말 버릴까요? 버린 요청의 처리 여부는 알 수 없습니다. 같은 키 재시도는 사라지고, 다음 저장은 새 요청이 됩니다.</p><div className="mt-2 flex flex-wrap gap-2"><button className="btn" disabled={pending !== null} onClick={() => discardUnresolved()}>버리기 확인</button><button className="btn" disabled={pending !== null} onClick={() => setConfirmingDiscard(false)}>취소</button></div></div>}{feedback && <p role="status" className="mt-2 text-[13px] leading-5 text-ink-2">{feedback}</p>}</section> : <>{unresolved && (
        <section className="rounded-xl border border-line bg-surface p-4">
          <h2 className="text-[15px] font-bold">동결된 팀원 요청</h2>
          <p className="mt-1 text-[12.5px] leading-5 text-ink-2">이전 저장 요청의 응답을 확인하지 못했습니다. 현재 권한으로는 다시 보낼 수 없습니다.</p>
          <p className="mt-1 text-[12.5px] leading-5 text-ink-2">주의: 이 요청은 이미 반영됐을 수 있습니다. 버린 뒤 다시 저장하면 새 요청(새 키)으로 기록됩니다.</p>
          {!confirmingDiscard ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <button className="btn" disabled={pending !== null} onClick={() => void reloadRoster()}>최신 팀원 목록 불러오기</button>
              <button className="btn" disabled={pending !== null} onClick={() => setConfirmingDiscard(true)}>동결된 요청 버리기</button>
            </div>
          ) : (
            <div className="mt-2 rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] leading-5 text-ink-2">
              <p>정말 버릴까요? 버린 요청의 처리 여부는 알 수 없습니다. 같은 키 재시도는 사라지고, 다음 저장은 새 요청이 됩니다.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button className="btn" disabled={pending !== null} onClick={() => discardUnresolved()}>버리기 확인</button>
                <button className="btn" disabled={pending !== null} onClick={() => setConfirmingDiscard(false)}>취소</button>
              </div>
            </div>
          )}
          {feedback && <p role="status" className="mt-2 text-[13px] leading-5 text-ink-2">{feedback}</p>}
        </section>
      )}<ActionUnavailable label="팀원 등록/관리" description="팀 관리에는 관리자 권한이 필요합니다." /></>}
    </ResponsiveActionBoundary>
    {unresolved && (
      <div className="rounded-xl border border-line bg-surface p-4 lg:hidden">
        <p className="text-[13px] leading-5 text-ink-2">이전 저장 요청의 응답을 확인하지 못했습니다. 결과는 알 수 없습니다.</p>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">이 요청의 기억은 이 화면에만 있어 새로고침·화면 이동·기기 변경 뒤에는 같은 키로 다시 시도할 수 없습니다. 노트북의 같은 화면에서 팀원 목록의 원래 기록을 먼저 확인하세요.</p>
      </div>
    )}
  </div>;
}
