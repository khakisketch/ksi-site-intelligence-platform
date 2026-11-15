"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAccountDisplayLock } from "./AccountDisplayBoundary";

/**
 * 헤더 드롭다운(프로젝트 전환·계정)이 같이 쓰는 열고 닫는 규칙.
 *
 * - 바깥을 누르면 닫는다(포커스는 옮기지 않는다 — 사용자가 이미 다른 곳을 눌렀다).
 * - Esc 로 닫으면 트리거로 포커스를 돌린다. 계정 표시가 잠긴 동안(계정 전환 확인 중)에는
 *   Esc 를 가로채지 않는다.
 * - 창 크기가 바뀌면 닫는다. 목록 안 스크롤은 닫지 않는다.
 */
export function useHeaderPopover() {
  const accountDisplay = useAccountDisplayLock();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const close = useCallback((returnFocus = true) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && rootRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (accountDisplay?.locked() || event.key !== "Escape") return;
      close();
    };
    const onResize = () => setOpen(false);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
    };
  }, [accountDisplay, close, open]);

  return { open, setOpen, close, rootRef, triggerRef };
}
