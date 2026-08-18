"use client";

import { useEffect, useState } from "react";

import { resolveLiveStatus } from "./live-status";

/** 상단바의 라이브 수신 표시(디자인 §0).
 *
 * **무엇을 세는가**: 이 컴포넌트가 마운트된 뒤 흐른 시간이다. 즉 "이 화면이 마지막으로
 * 서버 데이터를 받은 뒤 얼마나 지났나"를 근사한다 — 서버 컴포넌트가 렌더된 시점이
 * 곧 데이터 시점이기 때문이다. 진짜 스트림 수신 시각이 생기면 그 값을 prop 으로
 * 받아 대체하면 된다.
 *
 * **왜 근사인데 표시하는가**: 이 화면들은 갱신되는 값(처리 진행률·이벤트 수)을 보여준다.
 * 사용자가 낡은 숫자를 최신으로 읽는 것이 이 제품에서 가장 나쁜 실패라, 경과를 밝히는
 * 쪽이 침묵보다 안전하다. 다만 근사라는 사실을 title 로 밝힌다 — 모르는 것을 아는 것처럼
 * 보이지 않는다(INV-040).
 */
export function LiveIndicator() {
  const [elapsed, setElapsed] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const timer = setInterval(() => setElapsed((prev) => prev + 5), 5000);
    return () => clearInterval(timer);
  }, [paused]);

  // 탭이 다시 보이면 경과를 리셋하지 않는다 — 백그라운드에 있던 동안 데이터가
  // 낡은 것은 사실이고, 돌아왔다고 최신이 되지 않는다.
  const status = resolveLiveStatus(elapsed, paused);

  return (
    <button
      type="button"
      onClick={() => {
        setPaused((prev) => !prev);
        if (paused) setElapsed(0);
      }}
      title="이 화면이 마지막으로 서버 데이터를 받은 뒤 흐른 시간입니다(근사). 눌러서 갱신 표시를 끄거나 켭니다."
      className="tap-target hidden items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 text-[12px] text-ink-2 hover:bg-sunk sm:inline-flex"
    >
      <span className="relative grid size-[7px] flex-none place-items-center">
        <span className={`absolute inset-0 rounded-full ${status.dotClass}`} />
        {status.pulse && (
          <span
            aria-hidden="true"
            className={`ksi-pulse absolute inset-0 rounded-full ${status.dotClass}`}
          />
        )}
      </span>
      <span className="tabular whitespace-nowrap">{status.label}</span>
    </button>
  );
}
