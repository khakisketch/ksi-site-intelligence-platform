"use client";

import { useEffect, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";

type Member = {
  principalId: string;
  displayName: string;
  roleHint: "ADMIN" | "FIELD_OPERATOR" | "VIEWER";
  status: "ACTIVE" | "INACTIVE";
};

type ShareAttempt = { key: string; recipientPrincipalId: string };

function roleLabel(roleHint: Member["roleHint"]): string {
  return roleHint === "ADMIN" ? "관리자" : roleHint === "FIELD_OPERATOR" ? "현장담당" : "열람자";
}

function isVerifiedShareReceipt(value: unknown, { reportRef, recipientPrincipalId, siteId, organizationId, principalId }: { reportRef: string; recipientPrincipalId: string; siteId: string; organizationId: string; principalId: string }): boolean {
  if (!value || typeof value !== "object") return false;
  const receipt = value as Record<string, unknown>;
  return receipt.schemaVersion === "1.0"
    && receipt.reportRef === reportRef
    && receipt.recipientPrincipalId === recipientPrincipalId
    && receipt.siteId === siteId
    && receipt.organizationId === organizationId
    && receipt.senderPrincipalId === principalId
    && ["shareRef", "organizationId", "senderPrincipalId", "siteId", "reportDigest", "createdAt"].every(
      (field) => typeof receipt[field] === "string" && receipt[field].trim().length > 0,
    )
    && typeof receipt.createdAt === "string" && !Number.isNaN(new Date(receipt.createdAt).getTime());
}

export function TeamReportShare({ reportRef, siteId, organizationId, principalId, canWrite }: { reportRef: string; siteId: string; organizationId: string; principalId: string; canWrite: boolean }) {
  const [members, setMembers] = useState<Member[] | null>(null);
  const [rosterError, setRosterError] = useState(false);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [recipientPrincipalId, setRecipientPrincipalId] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [pending, setPending] = useState<ShareAttempt | null>(null);
  const [unresolved, setUnresolved] = useState<ShareAttempt | null>(null);
  const pendingRef = useRef<ShareAttempt | null>(null);
  const submitLock = useRef(false);

  async function loadMembers() {
    if (rosterLoading) return;
    setRosterLoading(true);
    setRosterError(false);
    setMembers(null);
    try {
      const response = await fetch("/api/organization-work-roster?includeInactive=false", { cache: "no-store" });
      if (!response.ok) throw new Error("roster unavailable");
      const payload = await response.json() as { members?: Member[] };
      setMembers((payload.members ?? []).filter((member) => member.status === "ACTIVE"));
    } catch {
      setRosterError(true);
      setFeedback("공유할 팀원 목록을 불러오지 못했습니다. 다시 시도하세요.");
    } finally {
      setRosterLoading(false);
    }
  }

  useEffect(() => {
    if (!canWrite) return;
    let live = true;
    void fetch("/api/organization-work-roster?includeInactive=false", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() as Promise<{ members?: Member[] }> : Promise.reject())
      .then((payload) => { if (live) { setRosterError(false); setMembers((payload.members ?? []).filter((member) => member.status === "ACTIVE")); setRosterLoading(false); } })
      .catch(() => { if (live) { setRosterError(true); setFeedback("공유할 팀원 목록을 불러오지 못했습니다. 다시 시도하세요."); setRosterLoading(false); } });
    return () => { live = false; };
  }, [canWrite]);

  async function share() {
    if (!canWrite || !recipientPrincipalId || pending || submitLock.current) return;
    const attempt = unresolved ?? { key: `report-share-${crypto.randomUUID()}`, recipientPrincipalId };
    submitLock.current = true;
    setPending(attempt);
    setFeedback(null);
    try {
      const response = await fetch(`/api/external-relative-volume-reports/${encodeURIComponent(reportRef)}/shares`, {
        method: "POST",
        headers: { "content-type": "application/json", "Idempotency-Key": attempt.key },
        body: JSON.stringify({ recipientPrincipalId: attempt.recipientPrincipalId }),
      });
      if (!response.ok) {
        if (response.status >= 500 || response.status === 408 || response.status === 429) {
          pendingRef.current = attempt;
          setUnresolved(attempt);
          setFeedback("응답을 확인하지 못했습니다. 같은 요청을 다시 시도하세요.");
        } else {
          pendingRef.current = null;
          setUnresolved(null);
          setFeedback("결과를 전달하지 못했습니다. 팀원과 현장 접근 권한을 확인하세요.");
        }
        return;
      }
      const receipt: unknown = await response.json().catch(() => null);
      if (!isVerifiedShareReceipt(receipt, { reportRef, recipientPrincipalId: attempt.recipientPrincipalId, siteId, organizationId, principalId })) {
        pendingRef.current = attempt;
        setUnresolved(attempt);
        setFeedback("결과 공유 응답을 확인하지 못했습니다. 받은 업무 전달로 표시하지 않습니다.");
        return;
      }
      pendingRef.current = null;
      setUnresolved(null);
      setFeedback("받은 업무에 전달했습니다.");
    } catch {
      pendingRef.current = attempt;
      setUnresolved(attempt);
      setFeedback("응답을 확인하지 못했습니다. 같은 요청을 다시 시도하세요.");
    } finally {
      setPending(null);
      submitLock.current = false;
    }
  }

  return (
    <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" reason="결과 공유는 노트북 이상의 화면에서 확인하고 전달합니다.">
      <section className="rounded-xl border border-line bg-surface px-4 py-3" aria-labelledby="team-report-share-heading">
        <h2 id="team-report-share-heading" className="text-[15px] font-bold">팀원에게 결과 공유</h2>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">로그인 및 현장 접근 권한이 있는 팀원만 결과를 볼 수 있습니다.</p>
        {!canWrite ? <p className="mt-2 text-[13px] text-ink-2">이 계정에는 결과 공유 권한이 없습니다.</p> : (
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="flex min-w-56 flex-1 flex-col gap-1 text-[13px] font-semibold">공유할 팀원
              <select aria-label="공유할 팀원" className="input" value={recipientPrincipalId} disabled={members === null || pending !== null || unresolved !== null} onChange={(event) => setRecipientPrincipalId(event.target.value)}>
                <option value="">팀원을 선택하세요</option>
                {(members ?? []).map((member) => <option key={member.principalId} value={member.principalId}>{member.displayName} · {member.principalId} · {roleLabel(member.roleHint)}</option>)}
              </select>
            </label>
            <button className="btn btn-primary" disabled={!recipientPrincipalId || pending !== null} onClick={() => void share()}>{pending ? "결과 전달 중" : unresolved ? "같은 요청 다시 시도" : "팀원에게 결과 공유"}</button>
          </div>
        )}
        {rosterError && canWrite && <button className="btn mt-2" disabled={rosterLoading} onClick={() => void loadMembers()}>팀원 목록 다시 불러오기</button>}
        {members?.length === 0 && !rosterError && canWrite && <p className="mt-2 text-[13px] text-ink-2">공유할 활성 팀원이 없습니다. 팀 관리에서 먼저 확인하세요.</p>}
        {feedback && <p role="status" className="mt-2 text-[13px] leading-5 text-ink-2">{feedback}</p>}
      </section>
    </ResponsiveActionBoundary>
  );
}
