"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * 자료 준비 요청 폼을 정보 패널에서 분리하는 네이티브 모달.
 *
 * - 선택 자료의 요약·상태·다음 행동은 패널에 남기고, 긴 픽셀 창 폼은 필요할 때만 연다.
 * - 네이티브 <dialog>.showModal()이 포커스 트랩·Escape·최상위 레이어를 맡는다.
 * - 닫히면 연 트리거로 포커스를 돌린다. 배경 클릭은 요청을 만들지 않는다.
 * - 폼 자체의 권한·검증·제출 로직은 `SpatialDataRequestAction`이 그대로 소유한다.
 */
export function AssetRequestDialog({
  triggerLabel = "이 자료 새로 준비 요청",
  title = "이 자료 새로 준비 요청",
  children,
}: {
  triggerLabel?: string;
  title?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const uid = useId();
  const titleId = `${uid}-title`;
  // Focus only moves on an explicit open/close transition. The closed branch
  // must not run on the initial mount — otherwise every selected-asset detail
  // steals focus to its request trigger before the reviewer has acted.
  const wasOpenRef = useRef(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const wasOpen = wasOpenRef.current;
    wasOpenRef.current = open;
    if (open && !wasOpen) {
      try {
        if (!dialog.open) dialog.showModal();
      } catch {
        // jsdom 등 showModal 미지원 환경 — 렌더는 유지한다.
      }
      closeRef.current?.focus();
      return;
    }
    if (!open && wasOpen) {
      try {
        if (dialog.open) dialog.close();
      } catch {
        // 이미 닫힌 환경.
      }
      triggerRef.current?.focus();
      return;
    }
    if (!open) {
      try {
        if (dialog.open) dialog.close();
      } catch {
        // 이미 닫힌 환경.
      }
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const onCancel = (event: Event) => {
      event.preventDefault();
      setOpen(false);
    };
    dialog.addEventListener("cancel", onCancel);
    return () => dialog.removeEventListener("cancel", onCancel);
  }, []);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(true)}
        className="btn btn-primary tap-target min-h-11 w-full"
      >
        {triggerLabel}
      </button>
      <dialog
        ref={dialogRef}
        aria-labelledby={titleId}
        onClick={(event) => {
          if (event.target === dialogRef.current) setOpen(false);
        }}
        onKeyDown={(event) => {
          // Escape은 가장 위의 이 모달만 닫는다. 버블된 키 입력이 뒤의
          // 정보 패널까지 닫아 선택 맥락을 잃지 않게 한다. 닫기 자체는
          // 네이티브 cancel이 맡으며 폼 제출은 만들지 않는다.
          if (event.key === "Escape") event.stopPropagation();
        }}
        className="m-auto max-h-[calc(100dvh-3rem)] w-[min(640px,calc(100vw-2rem))] overflow-hidden rounded-xl border border-line-strong bg-surface p-0 text-ink-1 backdrop:bg-black/40"
      >
        {open && (
          <div className="flex max-h-[calc(100dvh-3rem)] flex-col">
            <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-3">
              <h2 id={titleId} className="text-[15px] font-bold">
                {title}
              </h2>
              <button
                ref={closeRef}
                type="button"
                onClick={() => setOpen(false)}
                className="tap-target min-h-10 rounded-md border border-line px-3 text-[12px] font-semibold text-ink-2 hover:bg-sunk"
              >
                닫기
              </button>
            </header>
            <div className="min-h-0 overflow-y-auto p-4">
              {children}
            </div>
          </div>
        )}
      </dialog>
    </>
  );
}
