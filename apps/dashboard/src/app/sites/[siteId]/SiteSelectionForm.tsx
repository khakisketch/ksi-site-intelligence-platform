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
      if (!(event.target instanceof HTMLSelectElement) || !event.target.value) return;
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
