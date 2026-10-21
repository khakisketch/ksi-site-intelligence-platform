"use client";

import { useCallback, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";

import {
  DISPLAY_GESTURE_HINT,
  displayGestureKeyAction,
} from "@/lib/spatial-display-gesture";
import {
  DISPLAY_VIEW_DEFAULT,
  displayDragFractions,
  displayViewTransform,
  panDisplayView,
  resetDisplayView,
  wheelZoomFactor,
  zoomDisplayViewAt,
  type DisplayViewState,
} from "@/lib/spatial-display-view";

const PAN_EDGE_NOTE = "표시 범위의 끝입니다. 전체 보기로 돌아가세요.";
const ZOOM_EDGE_NOTE = "표시 확대 한계입니다. 전체 보기로 돌아가세요.";

/**
 * 직접 조작 표시 뷰포트 — 이어 보기·낱창·부분 출력이 같은 구현을 쓴다.
 *
 * - 마우스/펜 드래그: 내용이 커서를 1:1로 따라간다(늘이기 전 그림 크기 기준).
 *   버튼을 떼기 전부터 움직이며, 새 네트워크 요청을 만들지 않는다.
 * - 휠: 그림 위에서 바로 확대한다(포커스·Ctrl 불필요). 끝에서는 막지 않고
 *   페이지 스크롤로 넘긴다. 부드러운 배율이며 원본 버퍼·한계는 그대로다.
 * - 터치: 한 손가락 이동, 두 손가락 핀치(중심 고정·부드러운 배율).
 *   그림 바깥의 페이지 스크롤·브라우저 확대는 그대로 둔다.
 * - 두 번 두드리기: 누른 자리 기준으로 한 단계 확대한다.
 * - 키보드: 그림을 선택한 뒤 화살표·+ −·Home. 입력 칸 타이핑은 가로채지 않는다.
 * - 빈 곳은 미확인 범위이지 새 데이터가 아니다.
 *
 * Invariants: INV-020(표시만 — WorkArea·좌표 연산 없음)/
 * INV-024(정량 주장 없음)/INV-040(힌트는 구현된 것만)/
 * INV-051(읽기만 — 준비 POST 없음)/INV-060·061(권한·이그레스 변경 없음).
 */
export function useDirectViewport() {
  const [view, setView] = useState<DisplayViewState>(DISPLAY_VIEW_DEFAULT);
  const [note, setNote] = useState<string | null>(null);
  // 리스너·핸들러가 오래된 렌더를 닫아도 최신 상태에서 계산한다. 읽기·쓰기는
  // 렌더가 아니라 액션 안에서만 한다.
  const latestRef = useRef<DisplayViewState>(DISPLAY_VIEW_DEFAULT);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pointersRef = useRef(new Map<number, { x: number; y: number; t0: number; x0: number; y0: number }>());
  const pinchRef = useRef<{ dist: number; cx: number; cy: number } | null>(null);
  // 터치 두 번 두드리기 감지용 — 짧고 제자리인 두 번의 접촉만 인정한다.
  // 마우스는 네이티브 dblclick을 쓰고, 터치는 여기서 직접 판정한다.
  const lastTapRef = useRef<{ t: number; x: number; y: number } | null>(null);

  const applyPan = (fx: number, fy: number) => {
    const next = panDisplayView(latestRef.current, fx, fy);
    if (next.moved) {
      latestRef.current = next.view;
      setView(next.view);
      setNote(null);
    } else {
      setNote(PAN_EDGE_NOTE);
    }
  };

  const applyZoomAt = (factor: number, kx: number, ky: number) => {
    const next = zoomDisplayViewAt(latestRef.current, factor, kx, ky);
    if (next.moved) {
      latestRef.current = next.view;
      setView(next.view);
      setNote(null);
    } else {
      setNote(ZOOM_EDGE_NOTE);
    }
  };

  const reset = () => {
    latestRef.current = resetDisplayView();
    setView(latestRef.current);
    setNote(null);
  };

  const framePoint = (clientX: number, clientY: number): { kx: number; ky: number } | null => {
    const frame = frameRef.current;
    if (!frame) return null;
    const rect = frame.getBoundingClientRect();
    if (!(rect.width > 0) || !(rect.height > 0)) return null;
    return {
      kx: Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1),
      ky: Math.min(Math.max((clientY - rect.top) / rect.height, 0), 1),
    };
  };

  // 프레임 안의 실제 조작 요소(전체 보기 단추·링크·입력 등)는 건드리지 않는다.
  // 여기서 캡처·드래그를 시작하면 pointerup/click이 프레임으로 재지정돼
  // 단추가 눌리지 않게 된다. 키보드도 가로채지 않는다.
  const isInteractiveTarget = (target: unknown): boolean => {
    // SVG 아이콘/path도 실제 단추의 자식이다. HTMLElement로 제한하면 SVG를
    // 누를 때만 프레임이 포인터를 캡처해 native click을 가로채게 된다.
    if (!(target instanceof Element)) return false;
    return target.closest("button,a[href],input,select,textarea,summary,[role='button']") !== null;
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (isInteractiveTarget(event.target)) return;
    // 마우스는 주 버튼만, 펜·터치는 접촉 그대로 둔다. 합성 환경의
    // button 미지정은 주 버튼으로 간주한다.
    if (event.pointerType === "mouse" && event.button !== undefined && event.button !== 0) return;
    if (!frameRef.current) return;
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // 캡처 실패해도 같은 요소 위의 이동·종료는 그대로 처리한다.
    }
    pointersRef.current.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
      t0: Date.now(),
      x0: event.clientX,
      y0: event.clientY,
    });
    if (pointersRef.current.size === 2) {
      // 핀치 시작 — 중심·간격을 기준으로 삼는다.
      const points = [...pointersRef.current.values()].map((point) => ({ x: point.x, y: point.y }));
      const [first, second] = points as [{ x: number; y: number }, { x: number; y: number }];
      const frame = frameRef.current.getBoundingClientRect();
      const dist = Math.hypot(second.x - first.x, second.y - first.y);
      pinchRef.current = {
        dist,
        cx: ((first.x + second.x) / 2 - frame.left) / Math.max(frame.width, 1),
        cy: ((first.y + second.y) / 2 - frame.top) / Math.max(frame.height, 1),
      };
    }
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const tracked = pointersRef.current.get(event.pointerId);
    if (!tracked) return;
    const prev = { x: tracked.x, y: tracked.y };
    tracked.x = event.clientX;
    tracked.y = event.clientY;
    if (pointersRef.current.size === 1) {
      // 한 손가락 — 1:1 직접 이동. 크기는 늘이기 전 그림 자체로 잰다.
      const content = contentRef.current;
      const width = content?.offsetWidth ?? 0;
      const height = content?.offsetHeight ?? 0;
      if (!(width > 0) || !(height > 0)) return;
      const fractions = displayDragFractions(event.clientX - prev.x, event.clientY - prev.y, width, height);
      if (!fractions) return;
      applyPan(fractions.fx, fractions.fy);
      return;
    }
    if (pointersRef.current.size >= 2) {
      // 두 손가락 — 중심 고정 확대 + 중심 이동.
      const frame = frameRef.current?.getBoundingClientRect();
      if (!frame || !(frame.width > 0) || !(frame.height > 0)) return;
      const points = [...pointersRef.current.values()].map((point) => ({ x: point.x, y: point.y }));
      const [first, second] = points as [{ x: number; y: number }, { x: number; y: number }];
      const dist = Math.hypot(second.x - first.x, second.y - first.y);
      const base = pinchRef.current;
      const cx = ((first.x + second.x) / 2 - frame.left) / frame.width;
      const cy = ((first.y + second.y) / 2 - frame.top) / frame.height;
      if (!base || !(base.dist > 0) || !(dist > 0)) {
        pinchRef.current = { dist, cx, cy };
        return;
      }
      const next = zoomDisplayViewAt(latestRef.current, dist / base.dist, base.cx, base.cy);
      if (next.moved) {
        latestRef.current = next.view;
        setView(next.view);
        setNote(null);
      }
      // 중심 이동분도 함께 둔다. 내용은 손가락 중심을 따라간다.
      applyPan(-(cx - base.cx), -(cy - base.cy));
      pinchRef.current = { dist, cx, cy };
    }
  };

  const endPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const tracked = pointersRef.current.get(event.pointerId);
    pointersRef.current.delete(event.pointerId);
    if (pointersRef.current.size < 2) pinchRef.current = null;
    // 터치 두 번 두드리기: 짧고 제자리인 접촉이 두 번이면 누른 자리 기준으로
    // 확대한다. 마우스는 네이티브 dblclick을 쓴다. 한 번만 두드리면 확대하지
    // 않는다. 취소된 접촉은 두드림으로 세지 않는다.
    if (event.pointerType === "touch" && tracked) {
      const now = Date.now();
      const held = now - tracked.t0;
      const drifted = Math.hypot(event.clientX - tracked.x0, event.clientY - tracked.y0);
      const last = lastTapRef.current;
      if (held < 400 && drifted < 14 && last && now - last.t < 350
        && Math.hypot(event.clientX - last.x, event.clientY - last.y) < 28) {
        lastTapRef.current = null;
        const point = framePoint(event.clientX, event.clientY);
        if (point) applyZoomAt(2, point.kx, point.ky);
      } else if (held < 400 && drifted < 14) {
        lastTapRef.current = { t: now, x: event.clientX, y: event.clientY };
      } else {
        lastTapRef.current = null;
      }
    }
  };

  const onPointerCancel = (event: ReactPointerEvent<HTMLDivElement>) => {
    pointersRef.current.delete(event.pointerId);
    if (pointersRef.current.size < 2) pinchRef.current = null;
    lastTapRef.current = null;
  };

  const onDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (isInteractiveTarget(event.target)) return;
    const point = framePoint(event.clientX, event.clientY);
    if (!point) return;
    applyZoomAt(2, point.kx, point.ky);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.nativeEvent.isComposing) return;
    const target = event.target as HTMLElement | null;
    // 입력 칸·링크·단추 위에서는 브라우저 기본 동작을 가로채지 않는다.
    // 키보드 대안은 그림 프레임 자체에 포커스를 둔 뒤에 쓴다.
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable || !!target.closest("button,a[href],summary,[role='button']"))) return;
    const action = displayGestureKeyAction(event.key);
    if (!action) return;
    event.preventDefault();
    if (action.kind === "pan") applyPan(action.dCol, -action.dRow);
    else if (action.kind === "zoom") applyZoomAt(action.factor < 1 ? 2 : 0.5, 0.5, 0.5);
    else reset();
  };

  // 휠 확대는 non-passive 리스너에서만 막을 수 있다. 그림 위에서만 확대하고,
  // 끝에서는 막지 않고 페이지 스크롤로 넘긴다 — 전역 가로채기 금지.
  // 콜백 ref로 달고 뗀다 — 프레임이 늦게 붙는 display(준비 완료 후 렌더)에도
  // 걸리고, unmount 때 정리된다.
  const attachWheel = useCallback((frame: HTMLDivElement | null) => {
    if (!frame) return;
    const onWheel = (event: WheelEvent) => {
      const rect = frame.getBoundingClientRect();
      if (!(rect.width > 0) || !(rect.height > 0)) return;
      const kx = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
      const ky = Math.min(Math.max((event.clientY - rect.top) / rect.height, 0), 1);
      const factor = wheelZoomFactor(event.deltaY, event.deltaMode);
      const next = zoomDisplayViewAt(latestRef.current, factor, kx, ky);
      if (!next.moved) return;
      event.preventDefault();
      latestRef.current = next.view;
      setView(next.view);
      setNote(null);
    };
    frame.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      frame.removeEventListener("wheel", onWheel);
    };
  }, []);

  return {
    view,
    note,
    frameProps: {
      ref: (node: HTMLDivElement | null) => {
        frameRef.current = node;
        return attachWheel(node);
      },
      tabIndex: 0,
      role: "group" as const,
      onPointerDown,
      onPointerMove,
      onPointerUp: endPointer,
      onPointerCancel,
      onLostPointerCapture: onPointerCancel,
      onDoubleClick,
      onKeyDown,
      style: { touchAction: "none" as const },
    },
    contentProps: {
      ref: contentRef,
      style: { transform: displayViewTransform(view), transformOrigin: "0 0" as const },
    },
    reset,
  };
}

/** 전체 보기 — 그림 모서리의 작은 44px 단추 하나. 7버튼 띠는 두지 않는다. */
export function ViewportResetButton({ onReset }: { onReset: () => void }) {
  return (
    <button
      type="button"
      onClick={onReset}
      aria-label="전체 보기"
      title="전체 보기"
      className="absolute right-2 top-2 z-10 flex h-11 w-11 items-center justify-center rounded-md border border-line bg-surface/90 text-ink-1 hover:bg-sunk"
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="size-5"
      >
        <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
      </svg>
    </button>
  );
}

/** 짧은 한 줄 + 펼침 — AT가 조작을 찾을 수 있게 둔다. 숨은 조작은 두지 않는다. */
export function ViewportGestureHint() {
  return (
    <>
      <p className="text-[11.5px] leading-5 text-ink-muted">{DISPLAY_GESTURE_HINT}</p>
      <details className="text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold">조작 안내</summary>
        <ul className="mt-1 flex list-disc flex-col gap-1 pl-5 leading-5">
          <li>마우스·펜·한 손가락으로 끌면 그림이 따라옵니다.</li>
          <li>휠·두 손가락·두 번 두드리기로 누른 자리부터 확대합니다.</li>
          <li>그림을 선택한 뒤 방향키·+ −·Home 키를 쓸 수 있습니다.</li>
          <li>빈 곳은 아직 준비되지 않은 범위이며, 새 자료가 아닙니다.</li>
        </ul>
      </details>
    </>
  );
}
