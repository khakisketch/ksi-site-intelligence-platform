"use client";

import { useRef, useSyncExternalStore, type ReactNode } from "react";

function subscribeNoop() { return () => {}; }

/** Additive GET enhancement. Native submission keeps URL/history and the no-JS path. */
export function SiteSelectionForm({
  action,
  children,
  className,
}: { action: string; children: ReactNode; className?: string }) {
  const mounted = useSyncExternalStore(subscribeNoop, () => true, () => false);
  const composing = useRef(false);
  const changedDuringComposition = useRef(false);
  return <form
    action={action}
    method="get"
    className={className}
    onCompositionStart={() => { composing.current = true; }}
    onCompositionEnd={(event) => {
      composing.current = false;
      if (changedDuringComposition.current) {
        changedDuringComposition.current = false;
        event.currentTarget.requestSubmit();
      }
    }}
    onChange={(event) => {
      // 선택 즉시 반영한다. 필수 선택(작업구역)에서 빈 값으로 되돌리는 경우만
      // 제출하지 않는다 — 그 밖의 "전체" 필터는 빈 값도 유효한 선택이다.
      if (!(event.target instanceof HTMLSelectElement)) return;
      if (!event.target.value && event.target.required) return;
      if (composing.current || (event.nativeEvent as InputEvent).isComposing) {
        changedDuringComposition.current = true;
        return;
      }
      event.currentTarget.requestSubmit();
    }}
    onSubmit={(event) => { if (composing.current) event.preventDefault(); }}
  >
    {children}
    <button type="submit" className="btn" hidden={mounted} disabled={mounted}>보기</button>
  </form>;
}
