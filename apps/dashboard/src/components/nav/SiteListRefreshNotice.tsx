"use client";
import { useSiteListSnapshot } from "./SiteListContext";

/** Persistent, non-modal recovery; does not replace or reload the page subtree. */
export function SiteListRefreshNotice() {
  const snapshot = useSiteListSnapshot();
  return <div aria-live="polite" aria-atomic="true">
    {snapshot?.state === "pending" && <p className="px-4 py-2 text-sm">현장 메뉴를 확인하고 있습니다.</p>}
    {snapshot?.state === "error" && <div className="m-3 rounded border border-line bg-surface p-3 text-sm text-ink-1">
      <p>현장 메뉴를 확인하지 못했습니다. 등록 결과나 현장이 없다는 뜻은 아닙니다. 현재 계정과 접근 권한을 확인한 뒤 다시 시도하세요.</p>
      <button type="button" className="btn mt-2 min-h-11" onClick={() => void snapshot.refresh()}>현장 메뉴 다시 확인</button>
    </div>}
  </div>;
}
