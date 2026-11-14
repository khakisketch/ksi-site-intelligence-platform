"use client";

import { useId, useRef, type ReactNode } from "react";

type ActionMenuProps = {
  label?: string;
  children: ReactNode;
  className?: string;
  buttonClassName?: string;
  panelClassName?: string;
  onOpenChange?: (open: boolean) => void;
};

export function ActionMenu({
  label = "더 보기",
  children,
  className,
  buttonClassName,
  panelClassName,
  onOpenChange,
}: ActionMenuProps) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const anchor = `--action-${id.replace(/[^\w-]/g, "")}`;

  return (
    <div className={className}>
      <button
        ref={trigger}
        type="button"
        popoverTarget={id}
        data-action-menu-trigger
        className={buttonClassName ?? "btn btn-quiet btn-sm tap-target"}
        style={{ anchorName: anchor }}
      >
        {label}
      </button>
      <div
        id={id}
        popover="auto"
        aria-label={label}
        className={`action-menu-panel ${panelClassName ?? ""}`}
        style={{ positionAnchor: anchor }}
        onToggle={(event) => onOpenChange?.((event.nativeEvent as ToggleEvent).newState === "open")}
        onClick={(event) => {
          if (event.target instanceof Element && event.target.closest("a[href]")) {
            event.currentTarget.hidePopover?.();
            trigger.current?.focus();
          }
        }}
      >
        {children}
      </div>
    </div>
  );
}
