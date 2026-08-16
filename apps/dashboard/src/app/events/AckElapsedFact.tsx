"use client";

import type { EventSummaryResponse } from "@/lib/core-api/types";
import {
  ackSlaMs,
  ackSlaState,
  formatElapsed,
  formatTargetDuration,
  isUnattended,
} from "@/lib/core-api/triage";
import { useTick } from "@/hooks/useTick";

/**
 * EventDetailPanel 의 "확인 경과" Fact 값 — 원래 서버 렌더 시점에 고정된 스냅샷이던 것을
 * 마운트 후 60초마다 갱신한다(목록의 DwellBar 처럼). 텍스트·SLA 조건은 이 컴포넌트가
 * 대체하기 전 EventDetailPanel.tsx 의 서버 계산과 완전히 동일한 로직(ackSlaMs/ackSlaState/
 * formatElapsed)을 그대로 재사용한다 — 판정을 새로 만들지 않는다.
 *
 * `initialElapsedMs` 는 서버가 렌더 시점에 계산해 넘긴 값 — 마운트 전(SSR·최초 페인트)엔
 * 이 값으로 계산한 텍스트를 그대로 보여준다. formatElapsed·ackSlaState 는 로케일 포매터를
 * 쓰지 않는 순수 계산이라 첫 렌더에서 서버·클라이언트가 갈릴 이유가 없다.
 */
export function AckElapsedFact({
  event,
  initialElapsedMs,
}: {
  event: EventSummaryResponse;
  initialElapsedMs: number;
}) {
  const now = useTick(60_000);
  const unattended = isUnattended(event);
  const elapsedMs =
    now === null ? initialElapsedMs : Math.max(0, now - new Date(event.occurredAt).getTime());
  const elapsedText = formatElapsed(elapsedMs, { unattended });
  const slaState = ackSlaState(event, elapsedMs);
  const slaTarget = ackSlaMs(event.severity);

  return (
    <span>
      <span className="num">{elapsedText}</span>
      {unattended && (
        <span
          className={
            slaState === "breached"
              ? "text-crit-ink ml-1.5 font-semibold"
              : slaState === "due-soon"
                ? "text-high-ink ml-1.5 font-medium"
                : "text-ink-muted ml-1.5"
          }
        >
          · 목표 {formatTargetDuration(slaTarget)}
          {slaState === "breached" && " · 확인 목표 초과"}
          {slaState === "due-soon" && " · 확인 목표 임박"}
        </span>
      )}
    </span>
  );
}
