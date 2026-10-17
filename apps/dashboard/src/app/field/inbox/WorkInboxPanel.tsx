"use client";

import Link from "next/link";
import { useState } from "react";

import { formatKoreanDateTime } from "@/lib/datetime";
import { splitInboxItemContext } from "@/lib/work-context-names";

type InboxItem = {
  notificationRef: string;
  kind: "WORK_ORDER_ASSIGNED" | "EXTERNAL_REPORT_SHARED";
  target: { kind: "WORK_ORDER"; workOrderId: string } | { kind: "EXTERNAL_REPORT"; siteId: string; reportRef: string };
  senderPrincipalId: string;
  createdAt: string;
  unread: boolean;
};

function targetHref(target: InboxItem["target"]): string {
  return target.kind === "WORK_ORDER"
    ? `/field/work-orders/${encodeURIComponent(target.workOrderId)}`
    : `/sites/${encodeURIComponent(target.siteId)}/observations/${encodeURIComponent(target.reportRef)}`;
}

function targetLabel(item: InboxItem): string {
  return item.kind === "WORK_ORDER_ASSIGNED" ? "배정된 작업 열기" : "공유된 결과 열기";
}

export function WorkInboxPanel({ initialItems, initialNextCursor, initialUnreadOnly, initialContextByRef = {} }: { initialItems: InboxItem[]; initialNextCursor: string | null; initialUnreadOnly: boolean; initialContextByRef?: Record<string, { workName: string | null; siteName: string | null }> }) {
  const [items, setItems] = useState(initialItems);
  const [contextByRef, setContextByRef] = useState(initialContextByRef);
  const [nextCursor, setNextCursor] = useState(initialNextCursor);
  const [unreadOnly, setUnreadOnly] = useState(initialUnreadOnly);
  const [loading, setLoading] = useState(false);
  const [listLoadFailed, setListLoadFailed] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [readPending, setReadPending] = useState<string | null>(null);
  const [readRetries, setReadRetries] = useState<Record<string, string>>({});

  async function load({ reset, unread }: { reset: boolean; unread: boolean }) {
    if (loading) return;
    setLoading(true);
    setListLoadFailed(false);
    setFeedback(null);
    const after = reset ? null : nextCursor;
    try {
      const query = new URLSearchParams({ unreadOnly: unread ? "true" : "false" });
      if (after) query.set("after", after);
      const response = await fetch(`/api/work-inbox?${query.toString()}`, { cache: "no-store" });
      if (!response.ok) throw new Error("inbox unavailable");
      const payload = await response.json() as { items?: InboxItem[]; nextCursor?: string | null; contextByRef?: Record<string, { workName: string | null; siteName: string | null }> };
      const nextItems = payload.items ?? [];
      const nextContext = payload.contextByRef ?? {};
      // 필터 전환(reset)은 목록과 맥락을 통째로 갈아끼워 다른 대상의 낡은
      // 맥락이 남지 않게 하고, "더 보기"는 이어 붙인다. BFF가 페이지 단위로
      // 확인한 이름만 합치므로 브라우저에서 끝없이 따라가지 않는다.
      setItems(reset ? nextItems : [...items, ...nextItems]);
      setContextByRef(reset ? nextContext : { ...contextByRef, ...nextContext });
      setNextCursor(payload.nextCursor ?? null);
      setUnreadOnly(unread);
    } catch {
      setListLoadFailed(true);
      setFeedback("받은 업무를 불러오지 못했습니다. 다시 시도하세요.");
    } finally {
      setLoading(false);
    }
  }

  async function markRead(notificationRef: string) {
    if (readPending) return;
    const key = readRetries[notificationRef] ?? `inbox-read-${crypto.randomUUID()}`;
    setReadPending(notificationRef);
    try {
      const response = await fetch(`/api/work-inbox/${encodeURIComponent(notificationRef)}/read`, { method: "POST", headers: { "Idempotency-Key": key } });
      if (!response.ok) {
        if (response.status >= 500 || response.status === 408 || response.status === 429) {
          setReadRetries((current) => ({ ...current, [notificationRef]: key }));
          setFeedback("읽음 처리 응답을 확인하지 못했습니다. 같은 요청을 다시 시도하세요.");
          return;
        }
        setReadRetries((current) => { const next = { ...current }; delete next[notificationRef]; return next; });
        throw new Error("read unavailable");
      }
      setItems((current) => current.map((item) => item.notificationRef === notificationRef ? { ...item, unread: false } : item));
      setReadRetries((current) => { const next = { ...current }; delete next[notificationRef]; return next; });
    } catch {
      setReadRetries((current) => ({ ...current, [notificationRef]: key }));
      setFeedback("읽음 처리를 저장하지 못했습니다. 대상은 계속 열 수 있습니다.");
    } finally {
      setReadPending(null);
    }
  }

  return <div className="flex flex-col gap-4">
    <div className="flex flex-wrap gap-2" role="group" aria-label="받은 업무 필터"><button type="button" className={`btn ${unreadOnly ? "btn-primary" : ""}`} aria-pressed={unreadOnly} disabled={loading} onClick={() => void load({ reset: true, unread: true })}>읽지 않음</button><button type="button" className={`btn ${!unreadOnly ? "btn-primary" : ""}`} aria-pressed={!unreadOnly} disabled={loading} onClick={() => void load({ reset: true, unread: false })}>전체</button></div>
    {feedback && <p role={listLoadFailed ? "alert" : "status"} className="rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] text-ink-2">{feedback}</p>}
    <section className="overflow-hidden rounded-xl border border-line bg-surface"><ul className="divide-y divide-line px-4">{items.map((item) => {
      // 서버(BFF 포함)가 확인한 이름만 쓴다. 작업 이름과 현장을 별도 줄로
      // 감싸 긴 이름이 현장 식별자를 잘라내지 않게 한다. 맥락이 없으면 ID를
      // 산문으로 찍지 않는다. 읽음 상태·목적지 규칙은 그대로 둔다.
      const itemContext = splitInboxItemContext(item.kind, contextByRef[item.notificationRef] ?? { workName: null, siteName: null });
      return <li key={item.notificationRef} className="flex flex-col items-stretch gap-3 py-3 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><p className="text-[14px] font-semibold">{item.kind === "WORK_ORDER_ASSIGNED" ? "작업이 배정되었습니다" : "외부 관측 결과가 공유되었습니다"}{item.unread && <span className="ml-2 rounded-full bg-accent-bg px-2 py-0.5 text-[11px] text-accent-text">새 항목</span>}</p>{itemContext.title && <p className="mt-1 text-[12.5px] font-semibold break-words text-ink-1">{itemContext.title}</p>}{itemContext.siteLine && <p className="mt-0.5 text-[12px] break-words text-ink-2">{itemContext.siteLine}</p>}<p className="mt-1 text-[12px] text-ink-2">받은 시각 · {formatKoreanDateTime(item.createdAt, { dateStyle: "short", timeStyle: "short" })}</p>{item.senderPrincipalId ? <details className="mt-1 text-[11.5px] text-ink-muted"><summary className="tap-target inline-flex cursor-pointer items-center">발신 계정 정보</summary><p className="break-all pb-1">계정 ID · {item.senderPrincipalId}</p></details> : <p className="mt-1 text-[11.5px] text-ink-muted">보낸 사람 확인 필요</p>}</div><div className="flex flex-wrap gap-2 sm:shrink-0"><Link className="btn" href={targetHref(item.target)}>{targetLabel(item)}</Link>{item.unread && <button type="button" className="btn" disabled={readPending === item.notificationRef} onClick={() => void markRead(item.notificationRef)}>{readRetries[item.notificationRef] ? "같은 읽음 요청 다시 시도" : "읽음 처리"}</button>}</div></li>;
    })}</ul>{loading && items.length === 0 && <p role="status" className="px-4 py-4 text-[13px] text-ink-2">받은 업무 목록을 불러오는 중입니다.</p>}{items.length === 0 && !loading && !listLoadFailed && <p className="px-4 py-4 text-[13px] leading-5 text-ink-2">{unreadOnly
      ? "읽지 않은 받은 업무가 없습니다. 전체 목록을 선택해 읽은 업무를 확인하거나, 새 업무가 배정·공유되면 여기서 확인하세요."
      : "받은 업무가 없습니다. 작업이 배정되거나 결과가 공유되면 이 목록에 표시됩니다."}</p>}</section>
    {nextCursor && <button className="btn w-fit" disabled={loading} onClick={() => void load({ reset: false, unread: unreadOnly })}>{loading ? "불러오는 중" : "더 보기"}</button>}
  </div>;
}
