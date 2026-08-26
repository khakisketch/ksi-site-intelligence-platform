"use client";

import Link from "next/link";
import { useState } from "react";

import type {
  ConversationDetailView,
  CopilotConversation,
  CopilotExchangeResponse,
  CopilotMessage,
} from "@/lib/core-api/types";
import { copilotCitationHref } from "@/lib/copilot-citation";
import { formatKoreanDateTime } from "@/lib/datetime";

const MISSING_DATA_LABEL: Record<string, string> = {
  PROVIDER_UNAVAILABLE: "AI 연결이 일시적으로 응답하지 않았습니다.",
  INSUFFICIENT_EVIDENCE: "답을 뒷받침할 현장 근거가 충분하지 않습니다.",
  AI_EGRESS_NOT_ALLOWED: "이 현장은 외부 AI 데이터 활용에 동의하지 않았습니다.",
};

function newClientMessageId(): string {
  return typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function responseJson<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as T & { message?: string };
  if (!response.ok) throw new Error(body.message ?? "요청을 처리하지 못했습니다.");
  return body;
}

function Message({ message }: { message: CopilotMessage }) {
  const assistant = message.role === "ASSISTANT";
  return (
    <li className={`flex ${assistant ? "justify-start" : "justify-end"}`}>
      <article
        className={`max-w-[92%] rounded-xl px-4 py-3 text-[13.5px] leading-6 sm:max-w-[78%] ${
          assistant ? "border border-line bg-surface" : "bg-ink-1 text-surface"
        }`}
      >
        <p className="whitespace-pre-wrap break-keep">{message.content}</p>
        {assistant && message.citations.length > 0 && (
          <div className="mt-3 border-t border-line pt-2">
            <p className="text-[11px] font-bold text-ink-muted">검증된 근거</p>
            <ul className="mt-1 flex flex-col gap-1">
              {message.citations.map((citation) => {
                const href = copilotCitationHref(citation);
                return (
                  <li key={citation.citationId}>
                    {href ? (
                      <Link href={href} className="tap-target inline-flex text-[12px] text-accent-text underline">
                        {citation.label}
                      </Link>
                    ) : (
                      <span className="text-[12px] text-ink-2">{citation.label}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {assistant && message.answerStatus === "BLOCKED" && (
          <div className="mt-2 text-[12px] text-high-ink">
            <p>확인 가능한 근거가 부족해 답변을 완료하지 않았습니다.</p>
            {message.missingData.length > 0 && (
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {message.missingData.map((item) => (
                  <li key={item}>{MISSING_DATA_LABEL[item] ?? "추가 현장 데이터가 필요합니다."}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </article>
    </li>
  );
}

export function SiteCopilotChat({
  siteId,
  aiEgressAllowed,
  initialConversations,
  initialDetail,
  runtimeAvailable,
}: {
  siteId: string;
  aiEgressAllowed: boolean;
  initialConversations: CopilotConversation[];
  initialDetail: ConversationDetailView | null;
  runtimeAvailable: boolean;
}) {
  const [conversations, setConversations] = useState(initialConversations);
  const [detail, setDetail] = useState(initialDetail);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startConversation() {
    setPending(true);
    setError(null);
    try {
      const conversation = await responseJson<CopilotConversation>(
        await fetch(`/api/sites/${encodeURIComponent(siteId)}/copilot`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        }),
      );
      setConversations((current) => [conversation, ...current]);
      setDetail({ conversation, messages: [] });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "대화를 시작하지 못했습니다.");
    } finally {
      setPending(false);
    }
  }

  async function openConversation(conversationId: string) {
    setPending(true);
    setError(null);
    try {
      setDetail(
        await responseJson<ConversationDetailView>(
          await fetch(`/api/copilot/${encodeURIComponent(conversationId)}`),
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "대화를 불러오지 못했습니다.");
    } finally {
      setPending(false);
    }
  }

  async function submitQuestion(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!detail || !trimmed || pending) return;
    setPending(true);
    setError(null);
    try {
      const exchange = await responseJson<CopilotExchangeResponse>(
        await fetch(`/api/copilot/${encodeURIComponent(detail.conversation.conversationId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clientMessageId: newClientMessageId(), question: trimmed }),
        }),
      );
      setDetail((current) =>
        current
          ? {
              conversation: exchange.conversation,
              messages: [...current.messages, exchange.userMessage, exchange.assistantMessage],
            }
          : current,
      );
      setQuestion("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "질문을 처리하지 못했습니다.");
    } finally {
      setPending(false);
    }
  }

  if (!runtimeAvailable) {
    return (
      <div className="rounded-xl border border-line bg-surface px-5 py-8 text-center">
        <h2 className="text-[16px] font-bold">KSI AI를 아직 사용할 수 없습니다</h2>
        <p className="mt-2 text-[13px] break-keep text-ink-2">
          기존 현장 결과·작업·보고서는 계속 사용할 수 있습니다. AI 연결이 준비되면 이곳에서 현장 데이터를 질문할 수 있습니다.
        </p>
      </div>
    );
  }

  if (!aiEgressAllowed) {
    return (
      <div className="rounded-xl border border-line bg-surface px-5 py-8 text-center">
        <h2 className="text-[16px] font-bold">이 현장에서는 AI를 아직 사용하지 않습니다</h2>
        <p className="mt-2 text-[13px] break-keep text-ink-2">
          현장 데이터의 AI 활용에 동의한 뒤에만 대화를 시작할 수 있습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="grid min-h-[560px] overflow-hidden rounded-xl border border-line bg-surface lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="border-b border-line bg-sunk p-3 lg:border-r lg:border-b-0">
        <button type="button" onClick={startConversation} disabled={pending} className="btn btn-primary tap-target w-full">
          새 대화
        </button>
        <ul className="mt-3 flex gap-2 overflow-x-auto lg:flex-col">
          {conversations.map((conversation) => (
            <li key={conversation.conversationId} className="flex-none lg:w-full">
              <button
                type="button"
                onClick={() => openConversation(conversation.conversationId)}
                className={`tap-target w-48 rounded-lg px-3 py-2 text-left text-[12px] lg:w-full ${
                  detail?.conversation.conversationId === conversation.conversationId
                    ? "bg-surface font-semibold"
                    : "text-ink-2 hover:bg-surface"
                }`}
              >
                현장 대화
                <span className="mt-0.5 block text-[11px] font-normal text-ink-muted">
                  {formatKoreanDateTime(conversation.updatedAt, { dateStyle: "short", timeStyle: "short" })}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="flex min-h-0 flex-col" aria-busy={pending}>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {detail === null ? (
            <div className="grid h-full min-h-72 place-items-center text-center">
              <div>
                <h2 className="text-[16px] font-bold">새 대화를 시작하세요</h2>
                <p className="mt-2 max-w-lg text-[13px] break-keep text-ink-2">
                  변화·물량·처리 상태처럼 검증된 현장 결과만 사용합니다. AI는 승인이나 비행 임무를 직접 만들지 않습니다.
                </p>
              </div>
            </div>
          ) : detail.messages.length === 0 ? (
            <div className="grid h-full min-h-72 place-items-center text-center text-[13px] text-ink-2">
              첫 질문을 입력해 주세요. 답변은 근거 검증이 끝난 뒤 한 번에 표시됩니다.
            </div>
          ) : (
            <ul className="flex flex-col gap-3">
              {detail.messages.map((message) => <Message key={message.messageId} message={message} />)}
            </ul>
          )}
        </div>
        <form onSubmit={submitQuestion} className="border-t border-line p-3 sm:p-4">
          {error && <p role="alert" className="mb-2 text-[12px] text-crit-ink">{error}</p>}
          <div className="flex items-end gap-2">
            <label htmlFor="site-copilot-question" className="sr-only">
              KSI AI에게 질문
            </label>
            <textarea
              id="site-copilot-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={!detail || pending}
              rows={2}
              maxLength={4000}
              placeholder="예: 지난 관측과 비교해 무엇이 달라졌나요?"
              className="min-h-14 flex-1 resize-y rounded-lg border border-line-strong bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent"
            />
            <button type="submit" disabled={!detail || !question.trim() || pending} className="btn btn-primary tap-target">
              {pending ? "확인 중" : "질문 보내기"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
