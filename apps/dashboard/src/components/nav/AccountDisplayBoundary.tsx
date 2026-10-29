"use client";

import { usePathname } from "next/navigation";
import { isChromelessPath } from "./chromeless-path";
import { completeFreshLoginDestination, loadFreshLoginDestination, manuallyReloadFreshLoginDestination } from "./fresh-login-navigation";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

// Display continuity only: this does not authorize reads, hide the DOM from its
// owner, or establish that Core permissions remain valid after the snapshot.
const BoundaryContext = createContext<{ locked: () => boolean; invalidate: () => void; generation: () => number } | null>(null);
export function useAccountDisplayLock() { return useContext(BoundaryContext); }

export function AccountDisplayBoundary({ fingerprint, children, bypass = false, ownsFreshLoginMarker = false }: {
  fingerprint: string | null; children: ReactNode; bypass?: boolean; ownsFreshLoginMarker?: boolean;
}) {
  const pathname = usePathname();
  const requestedBypass = bypass && isChromelessPath(pathname);
  const [initialFingerprint] = useState(fingerprint);
  const [initialBypass] = useState(requestedBypass);
  // A boundary that has held protected content can never become a login bypass.
  bypass = initialBypass && requestedBypass;
  const root = useRef<HTMLDivElement>(null);
  const locked = useRef(!bypass);
  const generation = useRef(0);
  const blurred = useRef(false);
  const attemptedFreshDocument = useRef(false);
  const [state, setState] = useState<"checking" | "locked" | "ready">(bypass ? "ready" : "checking");
  const lock = useCallback(() => {
    ++generation.current;
    locked.current = true;
    // Synchronous, before React's next commit. Hidden also removes descendants
    // from focus and the accessibility tree; inert prevents interactions.
    if (root.current) {
      root.current.hidden = true;
      root.current.inert = true;
      root.current.style.display = "none";
    }
    setState("checking");
  }, []);
  const check = useCallback(async () => {
    if (bypass) return;
    lock();
    const ticket = generation.current;
    try {
      if (initialBypass || fingerprint !== initialFingerprint || !fingerprint || !/^v1-[0-9a-f]{64}$/.test(fingerprint)) throw new Error("no snapshot");
      const response = await fetch("/api/account-identity", { cache: "no-store" });
      const body = response.ok ? await response.json() : null;
      if (ticket !== generation.current) return;
      if (blurred.current || !document.hasFocus() || document.visibilityState === "hidden" || body?.fingerprint !== fingerprint) throw new Error("identity unavailable");
      locked.current = false;
      if (ownsFreshLoginMarker) completeFreshLoginDestination();
      setState("ready");
    } catch {
      if (ticket === generation.current) setState("locked");
    }
  }, [bypass, fingerprint, initialBypass, initialFingerprint, lock, ownsFreshLoginMarker]);
  useEffect(() => {
    if (bypass) return;
    const onBlur = () => { blurred.current = true; lock(); };
    const onFocus = () => { blurred.current = false; void check(); };
    const onVisibility = () => { if (document.visibilityState === "hidden") lock(); else if (!blurred.current) void check(); };
    const onPageHide = () => lock();
    const onPageShow = () => { if (!blurred.current) void check(); };
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pageshow", onPageShow);
    document.addEventListener("visibilitychange", onVisibility);
    let active = true;
    void Promise.resolve().then(() => { if (active) void check(); });
    return () => {
      active = false;
      generation.current += 1;
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pageshow", onPageShow);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [bypass, check, lock]);
  useEffect(() => {
    // Only a layout born on /login has no prior protected subtree. The arriving
    // client page is already hidden; discard that never-editable snapshot and
    // request the complete original URL as a fresh same-tab document instead.
    if (!initialBypass || bypass || !pathname || isChromelessPath(pathname) || attemptedFreshDocument.current) return;
    attemptedFreshDocument.current = true;
    loadFreshLoginDestination(pathname);
  }, [bypass, initialBypass, pathname]);
  const canShow = bypass || (state === "ready" && !initialBypass && fingerprint === initialFingerprint);
  const isLocked = useCallback(() => !canShow || locked.current, [canShow]);
  const context = useMemo(() => ({ locked: isLocked, invalidate: lock, generation: () => generation.current }), [isLocked, lock]);
  return <BoundaryContext.Provider value={context}>
    <div ref={root} data-account-display-root="" hidden={!canShow} inert={!canShow} style={{ display: canShow ? "contents" : "none" }}>{initialBypass && !bypass ? null : children}</div>
    {!canShow && <div className="fixed inset-0 z-[100] overflow-auto bg-surface p-6 text-ink-1" role="status" data-account-display-state={state}>
      <h1 className="text-lg font-bold">계정 확인이 필요합니다</h1>
      {initialBypass && <p className="mt-3">로그인한 화면을 준비하고 있습니다. 이동하지 않으면 <a className="underline" href="" onClick={(event) => { event.preventDefault(); manuallyReloadFreshLoginDestination(); }}>이 탭에서 목적지 다시 열기</a>를 선택하세요.</p>}
      <p className="mt-3">기존 화면과 입력은 이 탭에 그대로 두고 숨겼습니다. 원래 계정으로 돌아온 뒤 다시 확인하세요.</p>
      <p className="mt-2">다른 페이지로 이동하거나 탭을 닫으면 저장되지 않은 입력이 사라질 수 있습니다.</p>
      <button type="button" className="btn mt-4 min-h-11" onClick={() => void check()}>계정 다시 확인</button>{" "}
      <a className="btn mt-4 inline-flex min-h-11 items-center" href="/login" target="_blank" rel="noopener noreferrer">새 탭에서 로그인</a>
      <a className="btn mt-4 inline-flex min-h-11 items-center" href="/" target="_blank" rel="noopener noreferrer">새 탭에서 홈 열기</a>
      <noscript>계정 확인을 위해 JavaScript가 필요합니다.</noscript>
    </div>}
  </BoundaryContext.Provider>;
}
