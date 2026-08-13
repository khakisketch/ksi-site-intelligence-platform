"use client";

import type { EventSummaryResponse } from "@/lib/core-api/types";
import { ackSlaState, formatElapsed, isUnattended, type SlaState } from "@/lib/core-api/triage";
import { useTick } from "@/hooks/useTick";

const absoluteFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
});

const SLA_TEXT: Record<Exclude<SlaState, "ok">, string> = {
  breached: "확인 목표 초과",
  "due-soon": "확인 목표 임박",
};

const SLA_CLASS: Record<Exclude<SlaState, "ok">, string> = {
  breached: "text-crit-ink font-semibold",
  "due-soon": "text-high-ink font-medium",
};

/**
 * 발생 후 흐른 시간 + 확인 SLA 상태. 서버에서는 절대 시각, 마운트 후 상대 시간.
 *
 * 왜 클라이언트인가 — 두 가지가 겹친다.
 * ① 렌더 중 `Date.now()` 는 순수하지 않다(React 규칙). 서버에서 찍으면 캐시된 페이지가
 *    낡은 "3분째"를 영원히 보여줄 수 있다.
 * ② 방치 시간은 **흘러야 의미가 있다**. 화면을 열어둔 채 회의하는 동안 "12분째"가
 *    "47분째"로 변하고 목표를 넘기는 순간 빨개지는 것이 이 지표의 존재 이유다.
 *
 * SSR·JS 미실행 시에도 빈칸이 아니라 절대 시각이 남는다.
 */
export function ElapsedTime({
  event,
  className,
}: {
  event: EventSummaryResponse;
  className?: string;
}) {
  const { occurredAt } = event;
  const unattended = isUnattended(event);
  // useTick 은 값 계산을 하지 않는다 — 60초마다 리렌더만 강제한다(hooks/useTick.ts).
  // 여기서 매 렌더마다 현재 props(event)로 새로 계산하므로, 목록 재조회로 event 가
  // 새 객체가 되어도(참조만 바뀌고 값은 같아도) 타이머 자체는 안 흔들린다 — useTick 의
  // 내부 effect 가 의존하는 건 고정값 intervalMs 뿐이다.
  const now = useTick(60_000);
  const elapsed = now === null ? null : Math.max(0, now - new Date(occurredAt).getTime());
  const text = elapsed === null ? null : formatElapsed(elapsed, { unattended });
  const slaRaw: SlaState | null = elapsed === null ? null : ackSlaState(event, elapsed);

  const absolute = absoluteFormatter.format(new Date(occurredAt));
  const sla = slaRaw && slaRaw !== "ok" ? slaRaw : null;

  return (
    // suppressHydrationWarning — 시각 표시는 서버와 클라이언트가 필연적으로 갈린다.
    // ① Node 의 ko-KR 로케일 데이터가 브라우저와 달라 같은 시각도 "AM 10:05" vs
    //    "오전 10:05" 로 찍힌다. ② 배포 서버는 보통 UTC 라 로컬 시각 자체가 다르다.
    // 값의 정본은 클라이언트(운영자가 있는 곳)이므로 서버 출력은 첫 페인트용 근사치다.
    <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
      {/* suppressHydrationWarning 은 이 요소의 **직계 텍스트 자식**에만 걸린다 —
          바깥 래퍼에 두면 여기 텍스트의 불일치를 못 덮는다(실측). */}
      <span
        className={sla ? SLA_CLASS[sla] : className}
        title={absolute}
        suppressHydrationWarning
      >
        {text ?? absolute}
      </span>
      {sla && (
        <span className={`text-xs ${sla === "breached" ? "text-crit-ink" : "text-high-ink"}`}>
          {SLA_TEXT[sla]}
        </span>
      )}
    </span>
  );
}
