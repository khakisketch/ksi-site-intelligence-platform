"use client";

import { useActionState } from "react";

import { INITIAL_COPILOT_ACTION_STATE } from "./action-state";
import { askCopilotAction } from "./actions";
import { copilotCitationHref } from "./copilot-citation";

export function CopilotPanel({ siteId, workOrderId }: { siteId: string; workOrderId: string }) {
  const [state, action, pending] = useActionState(
    askCopilotAction,
    INITIAL_COPILOT_ACTION_STATE,
  );

  return (
    <section id="copilot" className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-[15px] font-bold tracking-tight">현장 자료에 질문</h2>
        <p className="text-[12.5px] break-keep text-ink-2">
          검증된 변화·공정·상대 물량만 근거와 함께 답합니다. 근거가 없으면 추정하지
          않습니다.
        </p>
      </div>
      <form action={action} className="flex flex-col gap-2">
        <input type="hidden" name="siteId" value={siteId} />
        <input type="hidden" name="workOrderId" value={workOrderId} />
        <label htmlFor="field-copilot-question" className="text-[13px] font-semibold">
          무엇을 확인할까요?
        </label>
        <textarea
          id="field-copilot-question"
          name="question"
          required
          maxLength={4000}
          rows={3}
          placeholder="예: 지난주 대비 A구역 절토량은 얼마나 변했나요?"
          className="min-h-[96px] rounded-lg border border-line-strong bg-surface px-3 py-3 text-[16px]"
        />
        <button
          type="submit"
          disabled={pending}
          className="btn btn-primary w-full justify-center"
        >
          {pending ? "근거 확인 중…" : "근거에서 답 찾기"}
        </button>
      </form>

      {state.message && (
        <p
          role={state.status === "error" ? "alert" : "status"}
          className={`rounded-lg px-3 py-2 text-[13px] ${
            state.status === "error" ? "bg-high-bg text-high-ink" : "bg-safe-bg text-safe-ink"
          }`}
        >
          {state.message}
        </p>
      )}
      {state.answer && (
        <div className="flex flex-col gap-3 rounded-lg bg-sunk p-4">
          <p className="text-[14px] leading-6 break-keep">{state.answer.answer}</p>
          {state.answer.citations.length > 0 && (
            <ul aria-label="답변 근거" className="flex flex-col gap-2">
              {state.answer.citations.map((citation) => {
                const href = copilotCitationHref(citation);
                return (
                  <li key={citation.citationId} className="text-[12px] text-ink-2">
                    {href ? (
                      <a href={href} className="font-semibold underline underline-offset-2">
                        {citation.label}
                      </a>
                    ) : (
                      <span className="font-semibold">{citation.label}</span>
                    )}
                    {citation.capturedTo && <span> · 촬영 {citation.capturedTo}</span>}
                    {citation.uncertaintySummary && (
                      <span> · {citation.uncertaintySummary}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {state.answer.reobservationDraftId && (
            <p className="rounded-md bg-high-bg px-3 py-2 text-[12.5px] text-high-ink">
              재관측 초안이 만들어졌습니다. 실제 실행은 위 작업 화면에서 사람이 승인해야
              합니다.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
