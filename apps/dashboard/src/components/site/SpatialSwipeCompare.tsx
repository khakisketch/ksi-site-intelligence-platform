"use client";

import {
  useRef,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type Ref,
} from "react";

import {
  clampSwipeBoundary,
  swipeBoundaryFromPointer,
  swipeBoundaryStep,
  swipeClipInset,
  swipeGripLeft,
  swipeValueText,
} from "@/lib/spatial-swipe";

/**
 * 밀어서 비교 원시 뷰포트 — 같은 화면 맞춤의 두 사진을 한 화면에 겹쳐 둔다.
 *
 * - 카메라(표시 팬·줌)는 호출자가 `useDirectViewport` 한 번으로 쥐고, 같은
 *   transform을 두 층에 그대로 건다. 층별 독립 카메라를 두지 않는다.
 * - 클립은 변환된 층 밖에 둔다(화면 공간). 팬·줌 뒤에도 경계선은 뷰포트에
 *   고정된다. 측지 정합·수치 주장이 아니다 — 같은 FIT의 표시용 겹침이다.
 * - 경계 그립 드래그는 stopPropagation으로 지도 팬과 분리한다. 그립 밖
 *   사진 드래그·휠·키보드는 공유 뷰포트가 그대로 받는다.
 * - Core ID·API·디코더·재투영을 모른다. 호출자가 검증한 표시용 겹침 재료만 받는다.
 *   (현재 호출자는 공개 예시 경로뿐이다.)
 */
export interface SwipeViewportBinding {
  frameProps: {
    ref: (node: HTMLDivElement | null) => void | (() => void);
    tabIndex: number;
    role: "group";
    onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onPointerUp: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onPointerCancel: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onLostPointerCapture: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onDoubleClick: (event: React.MouseEvent<HTMLDivElement>) => void;
    onKeyDown: (event: ReactKeyboardEvent<HTMLDivElement>) => void;
    style: CSSProperties;
    [key: string]: unknown;
  };
  /** 공유 transform이 걸린 층을 재는 ref — 아래(B) 층에 건다. */
  contentRef: Ref<HTMLDivElement>;
  /** 두 층에 똑같이 거는 공유 transform 스타일. */
  contentStyle: CSSProperties;
}

export function SpatialSwipeCompare({
  frameProps,
  contentRef,
  contentStyle,
  aspectRatio,
  left,
  right,
  leftLabel,
  rightLabel,
  boundary,
  onBoundaryChange,
  resetControl = null,
}: {
  frameProps: SwipeViewportBinding["frameProps"];
  contentRef: SwipeViewportBinding["contentRef"];
  contentStyle: SwipeViewportBinding["contentStyle"];
  /** 두 사진의 공통 표시 종횡비(예: "1100 / 985") — 모바일 내재 높이용. */
  aspectRatio: string;
  /** 왼쪽(A) 층 노드 — 호출자가 같은 FIT으로 그린다. */
  left: ReactNode;
  /** 오른쪽(B) 층 노드. */
  right: ReactNode;
  /** A/B 읽힘 라벨 — 기준/최신 같은 우열을 붙이지 않는다. */
  leftLabel: string;
  rightLabel: string;
  /** 왼쪽이 보이는 너비 백분율 0‥100. */
  boundary: number;
  onBoundaryChange: (value: number) => void;
  /** 공유 카메라 리셋 단추(위치는 스스로 잡는다). */
  resetControl?: ReactNode;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; startBoundary: number; pointerId: number } | null>(null);
  const shown = clampSwipeBoundary(boundary);

  const setFrameRef = (node: HTMLDivElement | null) => {
    frameRef.current = node;
    // React 19 callback-ref cleanup removes the non-passive wheel listener.
    // Dropping it would accumulate listeners on every boundary-state render.
    return frameProps.ref(node);
  };

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.stopPropagation();
    dragRef.current = null;
    try {
      if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    } catch {
      // 캡처가 없으면 할 일이 없다.
    }
  };

  const onGripPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    // 그립 조작은 지도 팬과 분리한다 — 프레임 핸들러에 닿지 않게 막는다.
    event.stopPropagation();
    if (event.pointerType === "mouse" && event.button !== undefined && event.button !== 0) return;
    if (dragRef.current) return;
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // 캡처 실패해도 같은 요소 위의 이동·종료는 그대로 처리한다.
    }
    dragRef.current = { startX: event.clientX, startBoundary: boundary, pointerId: event.pointerId };
  };

  const onGripPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const width = frameRef.current?.getBoundingClientRect().width ?? 0;
    onBoundaryChange(swipeBoundaryFromPointer(drag.startBoundary, drag.startX, event.clientX, width));
  };

  const onGripKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.nativeEvent.isComposing) return;
    const next = swipeBoundaryStep(boundary, event.key, event.shiftKey);
    if (next === null) return;
    // 슬라이더 키는 지도 방향키 팬과 분리한다.
    event.preventDefault();
    event.stopPropagation();
    onBoundaryChange(next);
  };

  const { ref: _hookRef, ...restFrameProps } = frameProps;
  void _hookRef;

  return (
    <div
      {...restFrameProps}
      ref={setFrameRef}
      className="relative aspect-[var(--swipe-aspect)] w-full overflow-hidden bg-sidebar focus-visible:outline-2 focus-visible:outline-offset-2 lg:aspect-auto lg:min-h-0 lg:flex-1"
      style={{ ...restFrameProps.style, "--swipe-aspect": aspectRatio } as CSSProperties}
    >
      <div ref={contentRef} className="absolute inset-0" style={contentStyle}>
        {right}
      </div>
      <div aria-hidden="true" className="pointer-events-none absolute inset-0" style={{ clipPath: swipeClipInset(shown) }}>
        <div className="absolute inset-0" style={contentStyle}>
          {left}
        </div>
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 w-[2px] border-l border-black/70 bg-white"
        style={{ left: `${shown}%` }}
      />
      {(shown === 0 || shown === 100) && (
        <span className="pointer-events-none absolute top-2 left-2 z-10 rounded bg-surface/95 px-2 py-1 text-[11.5px] font-semibold text-ink-1">
          현재 보기 · {shown === 0 ? rightLabel : leftLabel}
        </span>
      )}
      <div
        role="slider"
        tabIndex={0}
        aria-label="비교 경계"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(shown)}
        aria-valuetext={swipeValueText(shown, leftLabel, rightLabel)}
        onPointerDown={onGripPointerDown}
        onPointerMove={onGripPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onLostPointerCapture={endDrag}
        onPointerLeave={(event) => { if (!event.currentTarget.hasPointerCapture?.(event.pointerId)) endDrag(event); }}
        onDoubleClick={(event) => { event.preventDefault(); event.stopPropagation(); }}
        onKeyDown={onGripKeyDown}
        className="absolute top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize touch-none focus-visible:outline-2 focus-visible:outline-offset-2"
        style={{ left: swipeGripLeft(shown) }}
      >
        <span
          aria-hidden="true"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-line bg-surface/90 text-ink-1 shadow hover:bg-sunk"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="size-5"
          >
            <path d="m9 6-6 6 6 6" />
            <path d="m15 6 6 6-6 6" />
          </svg>
        </span>
      </div>
      {resetControl}
    </div>
  );
}
