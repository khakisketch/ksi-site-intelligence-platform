"use client";

import { useEffect, useState } from "react";

/**
 * 브라우저 연결 상태 — 오프라인·재시도 안내의 단일 출처.
 *
 * `navigator.onLine` + window online/offline 이벤트만 본다. 연결 품질· captive
 * portal·실제 도달 가능성은 판단하지 않는다 — "연결 끊김"만 알리고, 그 외의
 * 실패(401/503/타임아웃)는 각 호출부의 기존 판정에 맡긴다.
 *
 * SSR·최초 페인트 전에는 `true`를 돌려준다. 서버는 연결 상태를 모르고, 이때
 * `false`를 내놓으면 하이드레이션 순간 오프라인 배너가 깜빡인다. 마운트 후
 * 실제 값으로 갈아탄다(`useTick`의 null-스냅샷 패턴과 같은 이유).
 */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const sync = () => setOnline(navigator.onLine);
    sync();
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  return online;
}
