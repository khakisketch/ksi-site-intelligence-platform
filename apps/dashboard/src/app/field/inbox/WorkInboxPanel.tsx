"use client";

import Link from "next/link";
import { useState } from "react";

import { formatKoreanDateTime } from "@/lib/datetime";

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

export function WorkInboxPanel({ initialItems, initialNextCursor, initialUnreadOnly }: { initialItems: InboxItem[]; initialNextCursor: string | null; initialUnreadOnly: boolean }) {
  const [items, setItems] = useState(initialItems);
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
      const payload = await response.json() as { items?: InboxItem[]; nextCursor?: string | null };
      setItems(reset ? (payload.items ?? []) : [...items, ...(payload.items ?? [])]);
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
    <div className="flex flex-wrap gap-2"><button className={`btn ${unreadOnly ? "btn-primary" : ""}`} disabled={loading} onClick={() => void load({ reset: true, unread: true })}>읽지 않음</button><button className={`btn ${!unreadOnly ? "btn-primary" : ""}`} disabled={loading} onClick={() => void load({ reset: true, unread: false })}>전체</button></div>
    {feedback && <p role={listLoadFailed ? "alert" : "status"} className="rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] text-ink-2">{feedback}</p>}
    <section className="overflow-hidden rounded-xl border border-line bg-surface"><ul className="divide-y divide-line px-4">{items.map((item) => <li key={item.notificationRef} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="text-[14px] font-semibold">{item.kind === "WORK_ORDER_ASSIGNED" ? "작업이 배정되었습니다" : "외부 관측 결과가 공유되었습니다"}{item.unread && <span className="ml-2 rounded-full bg-accent-bg px-2 py-0.5 text-[11px] text-accent-text">새 항목</span>}</p><p className="mt-1 text-[12px] text-ink-2">보낸 사람 · {item.senderPrincipalId || "보낸 사람 확인 필요"} · {formatKoreanDateTime(item.createdAt, { dateStyle: "short", timeStyle: "short" })}</p></div><div className="flex flex-wrap gap-2"><Link className="btn" href={targetHref(item.target)}>{targetLabel(item)}</Link>{item.unread && <button className="btn" disabled={readPending === item.notificationRef} onClick={() => void markRead(item.notificationRef)}>{readRetries[item.notificationRef] ? "같은 읽음 요청 다시 시도" : "읽음 처리"}</button>}</div></li>)}</ul>{loading && items.length === 0 && <p role="status" className="px-4 py-4 text-[13px] text-ink-2">받은 업무 목록을 불러오는 중입니다.</p>}{items.length === 0 && !loading && !listLoadFailed && <p className="px-4 py-4 text-[13px] leading-5 text-ink-2">{unreadOnly
      ? "읽지 않은 받은 업무가 없습니다. 전체 목록을 선택해 읽은 업무를 확인하거나, 새 업무가 배정·공유되면 여기서 확인하세요."
      : "받은 업무가 없습니다. 작업이 배정되거나 결과가 공유되면 이 목록에 표시됩니다."}</p>}</section>
    {nextCursor && <button className="btn w-fit" disabled={loading} onClick={() => void load({ reset: false, unread: unreadOnly })}>{loading ? "불러오는 중" : "더 보기"}</button>}
  </div>;
}
