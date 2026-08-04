"use client";

// 시그니처: 방치 시간 막대. 이 화면 전용 — 홈의 ElapsedTime 과 텍스트 자리는 같지만
// 여긴 SLA 대비 진행률 막대까지 그린다(events/page.tsx EventRow 전용, ElapsedTime.tsx 는
// 건드리지 않는다 — 공용 원시요소다).
//
// 세 상태가 다르게 행동한다(triage-d-ink-mono.html §시그니처 주석):
//   미조치  isUnattended — SLA 대비 진행률을 심각도 색으로 채운다. 차오를수록 나쁨.
//   검토중  !unattended && !settled — 지금 도메인 규칙상 도달 불가능하다(트리아지
//           배정은 CONFIRMED_EVENT 이후에만 허용되고, 그 상태는 이미 isSettled다).
//           그래도 막대는 그리지 않고 텍스트만 중립색으로 — 조치(triage) SLA 는
//           아직 측정 대상이 없다(triage.ts 주석). 없는 데이터로 진행률을 지어내지 않는다.
//   종결    isSettled — 막대를 아예 안 그린다. "확정 시각"이 응답에 없어 지금 시각
//           기준 경과를 "N분 만에 확정"처럼 보여주면 시간이 갈수록 틀린 숫자가 된다.

import { useEffect, useState } from "react";

import type { EventSeverity, EventSummaryResponse } from "@/lib/core-api/types";
import {
  ackSlaMs,
  ackSlaState,
  formatElapsed,
  isSettled,
  isUnattended,
  type SlaState,
} from "@/lib/core-api/triage";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function formatTargetDuration(ms: number): string {
  if (ms >= DAY) return `${Math.round(ms / DAY)}일`;
  if (ms >= HOUR) return `${Math.round(ms / HOUR)}시간`;
  return `${Math.max(1, Math.round(ms / MINUTE))}분`;
}

const FILL_CLASS: Record<EventSeverity, string> = {
  CRITICAL: "bg-crit",
  HIGH: "bg-high",
  MEDIUM: "bg-mid",
  CANDIDATE: "bg-idle",
};

const SLA_SUFFIX: Record<Exclude<SlaState, "ok">, string> = {
  breached: "확인 목표 초과",
  "due-soon": "확인 목표 임박",
};

const absoluteFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
});

interface DwellState {
  text: string;
  sla: SlaState | null;
  pct: number | null; // null = 막대를 그리지 않는다
}

export function DwellBar({ event }: { event: EventSummaryResponse }) {
  const [state, setState] = useState<DwellState | null>(null);

  useEffect(() => {
    const occurred = new Date(event.occurredAt).getTime();
    const settled = isSettled(event);

    function update() {
      const elapsed = Math.max(0, Date.now() - occurred);
      const unattended = isUnattended(event);
      const text = formatElapsed(elapsed, { unattended });
      if (!unattended) {
        setState({ text, sla: null, pct: null });
        return;
      }
      const target = ackSlaMs(event.severity);
      setState({
        text,
        sla: ackSlaState(event, elapsed),
        pct: Math.min(100, (elapsed / target) * 100),
      });
    }

    update();
    if (settled) return; // 종결 이후엔 시계가 멈춘다 — 다시 그릴 이유가 없다.
    const timer = setInterval(update, 60_000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event.occurredAt, event.severity, event.status, event.triage]);

  const fallbackText = absoluteFormatter.format(new Date(event.occurredAt));
  const text = state?.text ?? fallbackText;
  const showBar = state !== null && state.pct !== null;
  const sla = state?.sla ?? null;

  const textClass =
    sla === "breached"
      ? "text-crit-ink font-semibold"
      : sla === "due-soon"
        ? "text-high-ink font-medium"
        : showBar
          ? "text-ink-1 font-medium"
          : "text-ink-2";

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className={`num text-[11.5px] whitespace-nowrap ${textClass}`} suppressHydrationWarning>
        {text}
      </span>
      {showBar && state && (
        <>
          <span className="h-[3px] min-w-[60px] flex-1 basis-24 overflow-hidden rounded-full bg-sunk">
            <span
              aria-hidden="true"
              className={`block h-full rounded-full ${event.severity ? FILL_CLASS[event.severity] : "bg-idle"}`}
              style={{ width: `${state.pct}%` }}
            />
          </span>
          <span className="text-ink-muted text-[10.5px] whitespace-nowrap">
            목표 {formatTargetDuration(ackSlaMs(event.severity))}
          </span>
          {sla && sla !== "ok" && (
            <span
              className={`text-[10.5px] whitespace-nowrap ${sla === "breached" ? "text-crit-ink" : "text-high-ink"}`}
            >
              {SLA_SUFFIX[sla]}
            </span>
          )}
        </>
      )}
    </div>
  );
}
