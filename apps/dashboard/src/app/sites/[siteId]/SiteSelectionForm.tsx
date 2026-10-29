"use client";

import Form from "next/form";
import { useEffect, useRef, useSyncExternalStore, type ReactNode, type RefObject } from "react";

function subscribeNoop() { return () => {}; }

/**
 * 제출이 일으킨 이동이 끝난 뒤 초점을 되돌리는 최소 인계값.
 *
 * - 같은 화면의 GET 쿼리만 바꾸는 폼이므로, 인계는 같은 pathname 에서
 *   주인 폼이 한 번만 쓴다. Back/앞으로(popstate)로는 절대 쓰지 않는다.
 * - 저장소(localStorage/sessionStorage/cookie)를 쓰지 않는다 — 같은 문서의
 *   메모리에만 두고, 새 제출·초점 이탈·이동·소비 때 버린다.
 * - next/navigation 을 쓰지 않으므로 호출자의 Suspense 경계나 기존 목에
 *   영향을 주지 않는다. 완료 신호는 호출자의 다시 그리기(마운트)다.
 */
type PendingFocus = {
  controlId: string;
  pathname: string;
  submitUrl: string;
};

let pendingFocus: PendingFocus | null = null;

function focusWasLost(): boolean {
  const active = document.activeElement;
  return active === null || active === document.body || active === document.documentElement;
}

/**
 * 이동 완료 뒤 초점 연속성 — 제출을 낸 폼 안에서만 동작한다.
 *
 * - 마운트 때 한 번만 확인한다. 호출자는 새 선택값으로 폼을 다시 그리므로
 *   (key 교체), 다시 그려진 폼의 마운트가 곧 이동 완료 신호다. 같은 자리에
 *   그대로 있는 폼(초점이 살아 있음)은 건드리지 않는다.
 * - 첫 렌더·Back/앞으로 에서는 pending 이 없어 아무 것도 하지 않는다.
 * - 초점을 잃었을 때만 제출을 낸 바로 그 컨트롤로 돌리고, 스크롤은 움직이지
 *   않는다. 새 위치(h1 등)로 보내거나 알림(live region)으로 알리지 않는다.
 *   같은 화면 쿼리 변경이므로 원래 컨트롤에 머무는 것이 맞다.
 */
function FocusContinuity({ formRef }: { formRef: RefObject<HTMLFormElement | null> }) {
  useEffect(() => {
    const onPopState = () => { pendingFocus = null; };
    window.addEventListener("popstate", onPopState);
    const pending = pendingFocus;
    if (pending) {
      // 이동이 아직 끝나지 않았으면(같은 URL) 둔다.
      if (window.location.href !== pending.submitUrl) {
        // 다른 화면으로 갔으면 이 인계는 끝이다 — 돌아올 때 훔치지 않는다.
        if (window.location.pathname !== pending.pathname) {
          pendingFocus = null;
        } else {
          const form = formRef.current;
          const control = form?.ownerDocument.getElementById(pending.controlId) as HTMLElement | null;
          // 이 폼의 컨트롤이 아니면 주인이 아니다 — 주인 폼이 가져가게 둔다.
          if (control && form?.contains(control)) {
            if (!form.contains(document.activeElement)) {
              if (focusWasLost()) {
                control.focus({ preventScroll: true });
              }
              pendingFocus = null;
            }
            // 초점이 살아 있으면(같은 폼 안에 있으면) 건드리지 않고 둔다 —
            // 느린 이동 뒤의 다시 그리기가 가져가게 한다.
          }
        }
      }
    }
    return () => {
      window.removeEventListener("popstate", onPopState);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

/**
 * 점진 향상 GET 폼. JS가 없으면 네이티브 GET 제출(히스토리·쿼리 그대로)이고,
 * JS가 있으면 같은 URL로의 클라이언트 이동이라 문서 전체를 다시 읽지 않는다.
 * `scroll={false}` 로 이동 때 페이지 위로 올리지 않는다.
 */
export function SiteSelectionForm({
  action,
  children,
  className,
}: { action: string; children: ReactNode; className?: string }) {
  const mounted = useSyncExternalStore(subscribeNoop, () => true, () => false);
  const composing = useRef(false);
  const changedDuringComposition = useRef(false);
  const formRef = useRef<HTMLFormElement | null>(null);
  const lastChangedControlId = useRef<string | null>(null);
  useEffect(() => {
    // next/form 은 문자열 action 을 항상 GET 으로 다루므로 method prop 을
    // 금지한다. no-JS 제출·문서 계약용 GET 표시는 DOM 속성에 직접 둔다 —
    // 클라이언트 이동 방식은 바꾸지 않는다.
    formRef.current?.setAttribute("method", "get");
  }, []);
  return <Form
    ref={formRef}
    action={action}
    scroll={false}
    className={className}
    onCompositionStart={() => { composing.current = true; }}
    onCompositionEnd={(event) => {
      composing.current = false;
      if (changedDuringComposition.current) {
        changedDuringComposition.current = false;
        event.currentTarget.requestSubmit();
      }
    }}
    onChange={(event) => {
      // 선택 즉시 반영한다. 필수 선택(작업구역)에서 빈 값으로 되돌리는 경우만
      // 제출하지 않는다 — 그 밖의 "전체" 필터는 빈 값도 유효한 선택이다.
      if (!(event.target instanceof HTMLSelectElement)) return;
      if (!event.target.value && event.target.required) return;
      if (composing.current || (event.nativeEvent as InputEvent).isComposing) {
        changedDuringComposition.current = true;
        return;
      }
      lastChangedControlId.current = event.target.id || null;
      event.currentTarget.requestSubmit();
    }}
    onBlur={(event) => {
      // 사용자가 폼 밖으로 초점을 옮겼으면 인계를 버린다 — 느린 이동 뒤에
      // 전에 쓰던 컨트롤로 끌어오지 않는다. 마운트 해제 때의 blur
      // (relatedTarget null)는 둔다.
      if (event.relatedTarget === null) return;
      if (event.relatedTarget instanceof Node && formRef.current?.contains(event.relatedTarget)) return;
      pendingFocus = null;
    }}
    onSubmit={(event) => {
      if (composing.current) {
        event.preventDefault();
        return;
      }
      // 이동 뒤 초점을 되돌릴 주인을 기록한다. Form 은 이어서 같은 URL로의
      // 클라이언트 이동을 수행한다(방지하지 않았으므로).
      const form = event.currentTarget;
      const active = form.ownerDocument.activeElement;
      let controlId: string | null = null;
      if (active instanceof HTMLElement && form.contains(active) && active.id) {
        controlId = active.id;
      } else if (lastChangedControlId.current) {
        const candidate = form.ownerDocument.getElementById(lastChangedControlId.current);
        if (candidate && form.contains(candidate)) controlId = lastChangedControlId.current;
      }
      lastChangedControlId.current = null;
      pendingFocus = controlId
        ? { controlId, pathname: window.location.pathname, submitUrl: window.location.href }
        : null;
    }}
  >
    {children}
    <FocusContinuity formRef={formRef} />
    <button type="submit" className="btn" hidden={mounted} disabled={mounted}>보기</button>
  </Form>;
}
