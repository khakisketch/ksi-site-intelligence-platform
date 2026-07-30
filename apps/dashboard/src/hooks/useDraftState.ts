"use client";

import { useEffect, useState } from "react";

// Wizard 이탈(뒤로가기·새로고침) 시 입력 소실을 막는다 — UX 목표 §2 "Wizard 재작업 비용이
// 완주율을 결정" 근거. sessionStorage — 브라우저 탭을 닫으면 자연 소멸(민감 정보 장기 잔존 방지).
export function useDraftState<T>(key: string, initial: T): [T, (value: T) => void, () => void] {
  const [state, setState] = useState<T>(initial);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    // sessionStorage 는 서버(SSR)에 존재하지 않아 useState 지연 초기화로는 읽을 수 없다 —
    // 마운트 후 클라이언트 전용 storage 를 React state 로 동기화하는 effect 의 정상 용례다.
    try {
      const raw = sessionStorage.getItem(key);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- SSR 불가한 외부 storage 최초 수화, key 변경마다 1회
      if (raw) setState(JSON.parse(raw) as T);
    } catch {
      // 손상된 draft 는 무시하고 initial 로 시작 — 저장 실패가 Wizard 진입을 막지 않는다.
    }
    setHydrated(true);
  }, [key]);

  useEffect(() => {
    if (!hydrated) return;
    try {
      sessionStorage.setItem(key, JSON.stringify(state));
    } catch {
      // 저장 실패(quota 등)는 침묵 무시 — 이번 세션 내 메모리 상태로는 계속 동작한다.
    }
  }, [key, state, hydrated]);

  const clear = () => {
    try {
      sessionStorage.removeItem(key);
    } catch {
      // no-op
    }
  };

  return [state, setState, clear];
}
