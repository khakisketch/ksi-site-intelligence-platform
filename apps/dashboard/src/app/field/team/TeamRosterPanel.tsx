"use client";

import { useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";

type Member = { principalId: string; displayName: string; roleHint: "ADMIN" | "FIELD_OPERATOR" | "VIEWER"; status: "ACTIVE" | "INACTIVE"; revision: number; updatedAt: string; updatedBy: string };

type Draft = { principalId: string; displayName: string; roleHint: Member["roleHint"]; status: Member["status"]; expectedRevision: number };
const initialDraft: Draft = { principalId: "", displayName: "", roleHint: "FIELD_OPERATOR", status: "ACTIVE", expectedRevision: 0 };

function roleLabel(roleHint: Member["roleHint"]): string {
  return roleHint === "ADMIN" ? "관리자" : roleHint === "FIELD_OPERATOR" ? "현장담당" : "열람자";
}

export function TeamRosterPanel({ initialMembers, canManage, currentPrincipalId }: { initialMembers: Member[]; canManage: boolean; currentPrincipalId: string }) {
  const [members, setMembers] = useState(initialMembers);
  const [draft, setDraft] = useState(initialDraft);
  const [pending, setPending] = useState<{ key: string; draft: typeof draft } | null>(null);
  const [unresolved, setUnresolved] = useState<{ key: string; draft: typeof draft } | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [conflictedPrincipalId, setConflictedPrincipalId] = useState<string | null>(null);
  const saveLock = useRef(false);
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
      const payload = await response.json() as { members?: Member[] };
      const latest = payload.members ?? [];
      setMembers(latest);
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

  async function save() {
    if (!canManage || pending || saveLock.current || !draft.principalId.trim() || !draft.displayName.trim()) return;
    const retry = unresolved && JSON.stringify(unresolved.draft) === JSON.stringify(draft) ? unresolved : null;
    if (unresolved && retry === null) {
      setFeedback("이전 저장 요청의 응답을 확인하지 못했습니다. 같은 요청을 먼저 다시 시도하세요.");
      return;
    }
    const attempt = retry ?? { key: `team-roster-${crypto.randomUUID()}`, draft };
    saveLock.current = true;
    setPending(attempt);
    setFeedback(null);
    try {
      const response = await fetch(`/api/organization-work-roster/${encodeURIComponent(attempt.draft.principalId)}`, {
        method: "PUT",
        headers: { "content-type": "application/json", "Idempotency-Key": attempt.key },
        body: JSON.stringify({ expectedRevision: attempt.draft.expectedRevision, displayName: attempt.draft.displayName.trim(), roleHint: attempt.draft.roleHint, status: attempt.draft.status }),
      });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        if (response.status >= 500 || response.status === 408 || response.status === 429) {
          setUnresolved(attempt);
          setFeedback("응답을 확인하지 못했습니다. 같은 요청을 다시 시도하세요.");
          return;
        }
        setUnresolved(null);
        if (response.status === 409) {
          setConflictedPrincipalId(attempt.draft.principalId);
          setFeedback("다른 변경이 먼저 저장되었습니다. 입력은 유지했습니다. 최신 팀원 목록을 불러와 수정 번호를 확인하세요.");
        } else {
          setFeedback("팀원 정보를 저장하지 못했습니다. 입력을 확인하고 다시 시도하세요.");
        }
        return;
      }
      const saved = body as Member;
      setMembers((current) => [...current.filter((member) => member.principalId !== saved.principalId), saved].toSorted((a, b) => a.displayName.localeCompare(b.displayName, "ko")));
      setDraft(initialDraft);
      setUnresolved(null);
      setFeedback("팀원 정보를 저장했습니다. 이 등록은 계정을 만들거나 권한을 부여하지 않습니다.");
    } catch {
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
      {members.length === 0 && <p className="px-4 py-3 text-[13px] text-ink-2">작업 배정과 결과 공유에 쓸 팀원 정보를 추가할 수 있습니다. 이 등록은 계정이나 권한을 만들지 않습니다.</p>}
    </section>
    <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" reason="팀원 정보는 노트북 이상의 화면에서 관리합니다.">
      {canManage ? <section className="rounded-xl border border-line bg-surface p-4"><h2 className="text-[15px] font-bold">팀원 등록 또는 수정</h2><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="flex flex-col gap-1 text-[13px] font-semibold">사용자 ID<input aria-label="사용자 ID" disabled={frozenSave} className="input" value={draft.principalId} onChange={(event) => setDraft({ ...draft, principalId: event.target.value })} /><span className="text-[12px] font-normal text-ink-muted">조직에서 쓰는 안정된 사용자 식별자입니다.</span></label><label className="flex flex-col gap-1 text-[13px] font-semibold">표시 이름<input disabled={frozenSave} className="input" value={draft.displayName} onChange={(event) => setDraft({ ...draft, displayName: event.target.value })} /></label><label className="flex flex-col gap-1 text-[13px] font-semibold">업무 구분<select disabled={frozenSave} className="input" value={draft.roleHint} onChange={(event) => setDraft({ ...draft, roleHint: event.target.value as typeof draft.roleHint })}><option value="ADMIN">관리자</option><option value="FIELD_OPERATOR">현장담당</option><option value="VIEWER">열람자</option></select></label><label className="flex flex-col gap-1 text-[13px] font-semibold">상태<select disabled={frozenSave} className="input" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as typeof draft.status })}><option value="ACTIVE">활성</option><option value="INACTIVE">비활성</option></select></label></div><div className="mt-3 flex flex-wrap gap-2"><button className="btn btn-primary" disabled={pending !== null || !draft.principalId.trim() || !draft.displayName.trim()} onClick={() => void save()}>{pending ? "저장 중" : unresolved ? "같은 요청 다시 시도" : "팀원 정보 저장"}</button>{conflictedPrincipalId && <button className="btn" disabled={pending !== null || unresolved !== null} onClick={() => void reloadRoster()}>최신 팀원 목록 불러오기</button>}</div>{feedback && <p role="status" className="mt-2 text-[13px] leading-5 text-ink-2">{feedback}</p>}</section> : <p className="rounded-xl border border-line bg-sunk px-4 py-3 text-[13px] text-ink-2">팀 관리에는 관리자 권한이 필요합니다.</p>}
    </ResponsiveActionBoundary>
  </div>;
}
