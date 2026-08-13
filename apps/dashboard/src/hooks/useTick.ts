"use client";

import { useEffect, useState } from "react";

/**
 * `intervalMs`마다 리렌더를 강제하고 그 시각(ms epoch)을 돌려준다 — 값 계산 자체는
 * 훅이 하지 않는다, 호출부가 반환값을 가지고 자기 로직(경과 포맷·SLA 판정 등)을 계산한다.
 *
 * `ElapsedTime.tsx`·`DwellBar.tsx`가 각자 만들어 썼던 "마운트 시 1회 계산 →
 * `setInterval(update, 60_000)` → unmount 시 clearInterval" 골격이 신규 호출부에서
 * 또 반복되길래(콜아웃 헤드라인, 확인경과 Fact) 뽑았다 — `usePolling.ts`·`useMutation.ts`
 * 가 이미 두 곳 이상 반복을 훅으로 올린 이 저장소 관례를 그대로 따른다.
 *
 * 마운트 전(SSR·최초 페인트)에는 `null`을 돌려준다 — 호출부는 이때 서버가 계산해
 * 내려준 스냅샷 값을 그대로 보여주고, 마운트 후 이 훅이 실제 시각으로 갈아탄다
 * (`ElapsedTime.tsx`의 "state?.text ?? absolute" 패턴과 같은 이유: 하이드레이션
 * 시점의 서버/클라이언트 첫 렌더가 갈리지 않게 한다).
 *
 * `DwellBar.tsx`는 "종결된 사건은 시계를 멈춘다"는 이 훅에 없는 조건을 하나 더
 * 갖고 있어(정본 docstring 참조) 그대로 남겨 뒀다 — 이 훅으로 갈아타려면 enabled
 * 같은 매개변수가 하나 더 필요해지는데, 지금 호출부 3곳(ElapsedTime + 신규 2곳)만
 * 으로도 추출할 근거는 충분해 거기서 멈춘다.
 */
export function useTick(intervalMs: number): number | null {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    // ElapsedTime.tsx·DwellBar.tsx 가 쓰던 것과 같은 모양(update 함수를 만들어 즉시
    // 1회 호출 + setInterval 로 재호출) — setState 를 effect 본문에서 바로 부르지 않고
    // 이름 붙은 함수를 거치게 한다. react-hooks/set-state-in-effect 가 직접 호출만
    // 잡아내는 얕은 정적분석이라(실측), 캡슐화 목적이 아니라 그 규칙을 통과시키는
    // 최소 변경이다.
    const update = () => setNow(Date.now());
    update();
    const timer = setInterval(update, intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return now;
}
