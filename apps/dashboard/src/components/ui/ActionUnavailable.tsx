"use client";

// 권한이 없어 눌 수 없는 동작의 사유를 클릭할 때만 보여준다.
//
// 예전에는 disabled 버튼 옆에 사유를 상시 텍스트로 두었는데, 터치 기기엔 hover 가
// 없어 title 툴팁이 아무에게도 안 보이고, 상시 문구는 56.5px 행을 만들어 옆
// 36px 컨트롤과 어긋났다. 이 컴포넌트는 평범한 버튼 크기(.btn)를 유지하고,
// 설명은 클릭해야 열리는 비모달 팝오버에만 둔다 — 모달도 토스트도 아니다.
//
// 팝오버는 네이티브 `popover="manual"` 로 최상위 레이어에 열린다. SectionCard 의
// overflow-hidden 안에 들어가도 잘리지 않고, 왼쪽 끝 트리거에서도 화면 밖으로
// 나가지 않는다 — 열릴 때 트리거 rect 를 재서 fixed 좌표를 직접 잡고, 화면 안에
// 들어오게 고정·뒤집기한다. 스크롤·리사이즈에는 따라다닌다.
//
// - 네이티브 disabled/aria-disabled 를 쓰지 않는다: 막힌 이유를 눌러 확인할 수
//   있어야 하므로, 트리거는 항상 키보드로 포커스·클릭 가능하다.
// - 팝오버는 모달이 아니라서 뒤 화면과 계속 상호작용할 수 있다. 바깥 클릭·
//   Escape 로 닫히고, Escape·닫기 버튼으로 닫으면 트리거로 포커스가 돌아온다.
// - retry=true 일 때만 "권한 다시 확인"을 둔다. router.refresh() 는 읽기만 다시
//   하므로 쓰기가 아니다. 전환 중 중복 클릭은 막는다. 재확인 버튼은 팝오버가
//   열릴 때만 마운트되므로, 열지 않은 화면의 테스트·렌더에는 next/navigation 이
//   필요 없다.
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  useTransition,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";

export interface AnchorRect {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface PanelSize {
  width: number;
  height: number;
}

export interface ViewportSize {
  width: number;
  height: number;
}

/** 팝오버 좌표 — 오른쪽 정렬을 기본으로 화면 안에 고정하고, 아래가 막히면 위로 뒤집는다. */
export function computeUnavailablePanelPosition(
  trigger: AnchorRect,
  panel: PanelSize,
  viewport: ViewportSize,
  gap = 8,
  margin = 8,
): { top: number; left: number } {
  const width = Math.min(panel.width, Math.max(0, viewport.width - margin * 2));
  const height = panel.height;
  // 오른쪽 끝 트리거에서도 넘치지 않게 오른쪽 정렬 후 고정한다.
  let left = trigger.right - width;
  left = Math.min(Math.max(left, margin), Math.max(margin, viewport.width - width - margin));
  // 아래에 자리가 없으면 위로 뒤집는다.
  let top = trigger.bottom + gap;
  if (top + height + margin > viewport.height) {
    const above = trigger.top - gap - height;
    if (above >= margin) top = above;
  }
  top = Math.min(Math.max(top, margin), Math.max(margin, viewport.height - height - margin));
  return { top, left };
}

const PANEL_WIDTH_FALLBACK = 256; // w-64. jsdom 처럼 측정치가 0인 환경의 대체값이다.

/** 팝오버가 열릴 때만 마운트된다 — 닫힌 화면은 useRouter 를 호출하지 않는다. */
function RetryRefreshButton() {
  const [isPending, startTransition] = useTransition();
  const router = useRouter();
  return (
    <button
      type="button"
      disabled={isPending}
      onClick={() => startTransition(() => router.refresh())}
      className="btn tap-target px-3 text-[12.5px]"
    >
      {isPending ? "확인 중…" : "권한 다시 확인"}
    </button>
  );
}

export function ActionUnavailable({
  label,
  description,
  retry = false,
  className = "",
  trigger,
  triggerClassName,
}: {
  label: string;
  description: string;
  retry?: boolean;
  className?: string;
  /**
   * 기본 잠금 버튼 대신 트리거 안에 둘 내용(예: 타일 전체).
   * 버튼 요소·포커스 복귀·팝오버 위치는 그대로 두고 내용과 겉모양만 바꾼다.
   * 접근 가능 이름은 label 로 고정한다.
   */
  trigger?: ReactNode;
  triggerClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [placed, setPlaced] = useState(false);
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const openRef = useRef(false);

  const positionPanel = useCallback(() => {
    const trigger = triggerRef.current;
    const panel = panelRef.current;
    if (!trigger || !panel) return;
    const rect = trigger.getBoundingClientRect();
    const pos = computeUnavailablePanelPosition(
      { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right },
      {
        width: panel.offsetWidth || PANEL_WIDTH_FALLBACK,
        height: panel.offsetHeight || 0,
      },
      { width: window.innerWidth, height: window.innerHeight },
    );
    panel.style.top = `${pos.top}px`;
    panel.style.left = `${pos.left}px`;
  }, []);

  const closePanel = useCallback((refocus: boolean) => {
    if (!openRef.current) return;
    openRef.current = false;
    const panel = panelRef.current;
    if (panel) {
      try {
        if (typeof panel.hidePopover === "function") panel.hidePopover();
      } catch {
        // 이미 닫혀 있다 — 상태만 맞춘다.
      }
      panel.style.display = "";
    }
    setOpen(false);
    setPlaced(false);
    if (refocus) triggerRef.current?.focus();
  }, []);

  const openPanel = useCallback(() => {
    if (openRef.current) return;
    openRef.current = true;
    setOpen(true);
  }, []);

  // 열릴 때: 최상위 레이어에 보여주고 → 재고 → 배치한다. 한 동기 블록이라
  // 배치 전 프레임이 보이지 않는다.
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    try {
      if (typeof panel.showPopover === "function") panel.showPopover();
      else panel.style.display = "block";
    } catch {
      // 이미 열려 있다 — 위치만 맞춘다.
    }
    positionPanel();
    setPlaced(true);
  }, [open, positionPanel]);

  // 외부에서 닫혔으면 상태만 맞춘다(포커스를 빼앗지 않는다).
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    const onToggle = (event: Event) => {
      if ((event as ToggleEvent).newState === "closed" && openRef.current) {
        openRef.current = false;
        panel.style.display = "";
        setOpen(false);
        setPlaced(false);
      }
    };
    panel.addEventListener("toggle", onToggle);
    return () => panel.removeEventListener("toggle", onToggle);
  }, []);

  // 마운트 해제 때 최상위 레이어를 정리한다.
  useEffect(() => {
    const panel = panelRef.current;
    return () => {
      try {
        panel?.hidePopover?.();
      } catch {
        // 닫을 것이 없다.
      }
    };
  }, []);

  // 열리는 동안 스크롤·리사이즈에 따라다닌다.
  useEffect(() => {
    if (!open) return;
    const onScroll = () => positionPanel();
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("scroll", onScroll, { capture: true });
      window.removeEventListener("resize", onScroll);
    };
  }, [open, positionPanel]);

  // 바깥 클릭으로 닫는다 — 단, 닫았다고 포커스를 빼앗지 않는다(사용자가 다른
  // 곳을 눌렀다는 뜻이므로 그 포커스를 둔다). Escape 는 트리거로 돌린다.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (
        target &&
        !triggerRef.current?.contains(target) &&
        !panelRef.current?.contains(target)
      ) {
        closePanel(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        closePanel(true);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, closePanel]);

  const onTriggerClick = (event: ReactMouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (openRef.current) closePanel(false);
    else openPanel();
  };

  return (
    <span className={`inline-flex ${className}`.trim()}>
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={trigger ? label : undefined}
        onClick={onTriggerClick}
        className={triggerClassName ?? "btn tap-target"}
      >
        {trigger ?? (
          <>
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              aria-hidden="true"
            >
              <rect x="3" y="7" width="10" height="6.5" rx="1.5" />
              <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
            </svg>
            {label}
          </>
        )}
      </button>
      <div
        ref={panelRef}
        id={panelId}
        popover="manual"
        style={{ top: 0, left: 0, right: "auto", bottom: "auto", margin: 0 }}
        className={`fixed z-40 m-0 w-64 max-w-[calc(100vw-1rem)] rounded-lg border border-line-strong bg-surface p-3 shadow-md ${
          placed ? "" : "invisible"
        }`}
      >
        {open && (
          <>
            <p className="text-[12.5px] leading-5 break-keep text-ink-2">{description}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {retry && <RetryRefreshButton />}
              <button
                type="button"
                onClick={() => closePanel(true)}
                className="btn tap-target px-3 text-[12.5px]"
              >
                안내 닫기
              </button>
            </div>
          </>
        )}
      </div>
    </span>
  );
}
