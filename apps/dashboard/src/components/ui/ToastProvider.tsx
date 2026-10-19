"use client";

// 단순 성공 알림 전용 토스트. 모달도, 결정도 아니다 — "됐습니다" 한 마디만 둔다.
//
// 계약:
// - ToastProvider({children}) 로 감싸고 useToast().notify(message) 로 띄운다.
// - 최신 1개만 보인다(이전 것은 교체된다). 최소 6초 유지되며, 가리키거나
//   포커스가 있거나 탭이 숨겨진 동안에는 타이머가 멈춘다.
// - role="status" aria-live="polite" 영역은 하나뿐이고, 포커스를 빼앗지 않는다.
// - 닫기 버튼 라벨은 "알림 닫기"이며 tap-target( coarse 44px )을 지킨다.
// - 모바일 하단 내비 가림은 모바일에서만(var(--mobile-bottom-nav-clearance)),
//   데스크톱에서는 본문 아래 12px(lg:bottom-3)이다. 네이티브 dialog 최상위
//   레이어는 가리지 않는다(z-index 40).
// - 탭이 숨겨져 있거나 영역에 호버·포커스가 있는 동안 notify 돼도 타이머를
//   걸지 않고 멈춘 채로 둔다 — 교체된 토스트도 최소 노출을 보장받는다.
// - Provider 없이 useToast() 를 쓰면 조용히 무시되는 기본값이다 — 레거시 독립
//   렌더 테스트가 깨지지 않게 하려는 안전망이며, 제품에서는 layout 이 항상
//   Provider 를 두므로(apps/dashboard/src/app/layout.tsx) 조용한 누락이 없다.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

const VISIBLE_MS = 6000;

interface ToastApi {
  notify: (message: string) => void;
}

const ToastContext = createContext<ToastApi>({ notify: () => {} });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

interface Toast {
  id: number;
  message: string;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const toastRef = useRef<Toast | null>(null);
  const idRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const remainingRef = useRef(VISIBLE_MS);
  const shownAtRef = useRef(0);
  const regionRef = useRef<HTMLDivElement>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const setToastState = useCallback((next: Toast | null) => {
    toastRef.current = next;
    setToast(next);
  }, []);

  const dismiss = useCallback(() => {
    clearTimer();
    setToastState(null);
  }, [clearTimer, setToastState]);

  // 남은 시간만큼만 타이머를 건다 — 일시정지 후 재개해도 최소 노출을 지킨다.
  const armTimer = useCallback(
    (ms: number) => {
      clearTimer();
      remainingRef.current = ms;
      shownAtRef.current = Date.now();
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        remainingRef.current = 0;
        setToastState(null);
      }, ms);
    },
    [clearTimer, setToastState],
  );

  // 일시정지·재개는 리스너·핸들러에서만 부른다. 모두 ref 기반이라 identity 가
  // 바뀌지 않아, 토스트가 바뀌었다고 만료 타이머를 죽이는 일이 없다.
  // 멈춤 중 notify 된 토스트는 타이머가 없으므로, 재개 조건이 되면 전체 시간으로 건다.
  const pauseTimer = useCallback(() => {
    if (timerRef.current === null) return;
    const elapsed = Date.now() - shownAtRef.current;
    remainingRef.current = Math.max(0, remainingRef.current - elapsed);
    clearTimer();
  }, [clearTimer]);

  const resumeTimer = useCallback(() => {
    if (toastRef.current === null || timerRef.current !== null) return;
    // 영역 안에 포커스·호버가 남아 있으면 재개하지 않는다.
    // (matches 미지원 환경은 호버 없음으로 간주한다.)
    try {
      if (regionRef.current?.matches(":hover, :focus-within")) return;
    } catch {
      // 무시하고 타이머를 건다.
    }
    if (document.hidden) return;
    if (remainingRef.current <= 0) {
      setToastState(null);
      return;
    }
    armTimer(remainingRef.current);
  }, [armTimer, setToastState]);

  /** 지금 타이머를 걸면 안 되는 환경인가 — 숨김 탭, 호버·포커스 중. */
  const isPausedEnvironment = () => {
    if (document.hidden) return true;
    try {
      return regionRef.current?.matches(":hover, :focus-within") ?? false;
    } catch {
      return false;
    }
  };

  const notify = useCallback(
    (message: string) => {
      idRef.current += 1;
      setToastState({ id: idRef.current, message });
      remainingRef.current = VISIBLE_MS;
      shownAtRef.current = Date.now();
      // 멈춤 환경에서 띄우면 타이머 없이 멈춘 채로 둔다 — 환경이 풀릴 때
      // 재개되면서 최소 노출이 시작된다.
      if (isPausedEnvironment()) {
        clearTimer();
        return;
      }
      armTimer(VISIBLE_MS);
    },
    [armTimer, clearTimer, setToastState],
  );

  const api = useMemo(() => ({ notify }), [notify]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) pauseTimer();
      else resumeTimer();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [pauseTimer, resumeTimer]);

  useEffect(() => {
    // 마운트 해제 때만 만료 타이머를 정리한다 — 토스트 교체 때 정리하면
    // 갓 건 타이머를 죽여 자동 닫힘이 멈춘다.
    return () => {
      clearTimer();
    };
  }, [clearTimer]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        ref={regionRef}
        role="status"
        aria-live="polite"
        onMouseEnter={pauseTimer}
        onMouseLeave={resumeTimer}
        onFocusCapture={pauseTimer}
        onBlurCapture={resumeTimer}
        className="pointer-events-none fixed left-1/2 z-40 w-max max-w-[calc(100vw-2rem)] -translate-x-1/2 bottom-[calc(var(--mobile-bottom-nav-clearance,0px)+12px)] lg:bottom-3"
      >
        {toast !== null && (
          <div
            key={toast.id}
            className="pointer-events-auto flex items-center gap-3 rounded-lg border border-line-strong bg-surface px-3.5 py-2.5 text-[13px] break-keep shadow-md"
          >
            <p className="text-ink-1">{toast.message}</p>
            <button
              type="button"
              onClick={dismiss}
              className="btn tap-target h-8 shrink-0 px-2.5 text-[12px]"
            >
              알림 닫기
            </button>
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}
