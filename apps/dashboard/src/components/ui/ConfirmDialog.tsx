"use client";

// 되돌리기 어려운 결정(삭제·승인·발급 등) 전용 확인 모달. 안내용이 아니다 —
// 단순 성공은 ToastProvider, 막힌 이유 설명은 ActionUnavailable 을 쓴다.
//
// - 네이티브 <dialog>.showModal() 을 쓴다: 포커스 트랩·Escape·최상위 레이어를
//   직접 만들지 않는다.
// - 기본 포커스는 취소 버튼이다(Enter 오작동으로 결정이 실행되지 않게).
//   닫히면 트리거(열릴 때 포커스를 가졌던 요소)로 포커스를 돌린다.
// - 확인 라벨은 "무엇을 하는지"를 적는다("현장 삭제", "작업 승인" — "확인" 금지).
//   취소·닫기·배경 클릭은 절대 onConfirm 을 실행하지 않는다.
// - pending 동안 확인 버튼은 막히고, 부모가 리렌더하기 전 연타(Enter·클릭)도
//   내부 확정 플래그로 한 번만 실행된다. 취소는 pending 중에도 그대로 동작하며
//   역시 실행을 일으키지 않는다.
// - 불필요한 애니메이션은 두지 않는다(ink-mono).
import { useEffect, useId, useRef, type ReactNode } from "react";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  onConfirm,
  onCancel,
  pending = false,
}: {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  pending?: boolean;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<Element | null>(null);
  const onCancelRef = useRef(onCancel);
  useEffect(() => {
    onCancelRef.current = onCancel;
  });
  // 부모 리렌더 전에 들어온 연타를 막는 내부 플래그 — pending·닫힘에 리셋된다.
  const confirmedRef = useRef(false);
  useEffect(() => {
    if (!pending) confirmedRef.current = false;
  }, [pending]);
  useEffect(() => {
    if (!open) confirmedRef.current = false;
  }, [open ]);

  const uid = useId();
  const titleId = `${uid}-title`;
  const descriptionId = `${uid}-description`;

  const handleConfirm = () => {
    if (pending || confirmedRef.current) return;
    confirmedRef.current = true;
    onConfirm();
  };

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      triggerRef.current = document.activeElement;
      try {
        if (!dialog.open) dialog.showModal();
      } catch {
        // jsdom 등 showModal 미지원 환경 — 렌더는 유지하고 포커스만 맞춘다.
      }
      cancelRef.current?.focus();
    } else {
      try {
        if (dialog.open) dialog.close();
      } catch {
        // showModal 을 못 여는 환경에서는 닫을 것도 없다.
      }
      if (triggerRef.current instanceof HTMLElement) triggerRef.current.focus();
      triggerRef.current = null;
    }
  }, [open ]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const onCancelEvent = (event: Event) => {
      event.preventDefault();
      onCancelRef.current();
    };
    dialog.addEventListener("cancel", onCancelEvent);
    return () => dialog.removeEventListener("cancel", onCancelEvent);
  }, []);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onClick={(event) => {
        // 배경(백드롭) 클릭은 취소와 같다 — 결정을 실행하지 않는다.
        if (event.target === dialogRef.current) onCancel();
      }}
      // m-auto: Tailwind preflight 가 dialog 기본 마진을 건드려도 중앙을 유지한다.
      className="m-auto rounded-lg border border-line-strong bg-surface p-0 text-ink-1 backdrop:bg-black/40"
    >
      {open && (
        <div className="flex max-h-[calc(100dvh-3rem)] w-[min(24rem,calc(100vw-2rem))] flex-col gap-3 overflow-y-auto p-4">
          <h2 id={titleId} className="text-[15px] font-bold break-keep">
            {title}
          </h2>
          <div id={descriptionId} className="text-[13px] leading-6 break-keep text-ink-2">{description}</div>
          <div className="flex justify-end gap-2">
            <button
              ref={cancelRef}
              type="button"
              onClick={onCancel}
              className="btn tap-target"
            >
              취소
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={handleConfirm}
              className="btn btn-danger tap-target"
            >
              {pending ? "처리 중…" : confirmLabel}
            </button>
          </div>
        </div>
      )}
    </dialog>
  );
}
