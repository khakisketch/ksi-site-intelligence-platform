"use client";

import { useCallback, useEffect, useRef } from "react";

const POLL_INTERVAL_MS = 5000;

/**
 * 재귀 setTimeout 폴링 — `id`가 있는 동안 `fetchOnce(id)`를 5초 간격으로 부르고,
 * 성공한 결과를 매번 `onTick`에 넘긴다. `isTerminal(result)`가 true면 멈춘다.
 *
 * ComparisonSubmitPanel·SourceUploadPanel이 각자 손으로 짰던 동일한 골격을
 * 뽑은 것이다 — 두 곳 다 "컴포넌트가 사라진 뒤에도 setTimeout 체인이 계속
 * 도는" 누수를 reviewer 가 지적해 고친 이력이 있다. 그 수정의 핵심 두 가지를
 * 여기서 대신 강제한다:
 *
 * 1. ref 이중 참조로 재귀 호출을 건다(react-hooks/refs, react-hooks/set-state-in-effect
 *    회피) — `poll` 자신은 빈 의존성 배열로 고정되고, 최신 콜백은 매 렌더 뒤
 *    ref 에 동기화된다.
 * 2. `id` 값 자체가 바뀌는 것만이 유일한 재시작 경로다 — kickoff(0ms)와 폴링
 *    타이머 둘 다 그 effect 의 cleanup 에서 정리되므로, id 가 바뀌거나
 *    컴포넌트가 사라지는 모든 경우에 정리가 보장된다.
 *
 * `fetchOnce`가 실패(비-ok 응답·네트워크 오류)하면 `null`을 돌려주거나 예외를
 * 던지면 된다 — 두 경우 다 상태를 건드리지 않고 다음 tick 에 재시도한다.
 * 여러 setState 를 어떻게 반영할지는 훅이 정하지 않는다 — 그건 `onTick`을
 * 소유한 호출부의 몫이다(호출부마다 반영할 필드·종료 시 부가 동작이 다르다).
 */
export function usePolling<T>(
  id: string | null,
  fetchOnce: (id: string) => Promise<T | null>,
  isTerminal: (result: T) => boolean,
  onTick: (result: T) => void,
): void {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollRef = useRef<(id: string) => Promise<void>>(async () => {});
  const fetchOnceRef = useRef(fetchOnce);
  const isTerminalRef = useRef(isTerminal);
  const onTickRef = useRef(onTick);

  // 매 렌더 뒤 최신 콜백으로 동기화 — 호출부가 콜백을 useCallback 으로 감싸지
  // 않아도(매 렌더 새 함수여도) poll 자신은 재생성되지 않는다.
  useEffect(() => {
    fetchOnceRef.current = fetchOnce;
    isTerminalRef.current = isTerminal;
    onTickRef.current = onTick;
  });

  const poll = useCallback(async (pollId: string) => {
    try {
      const result = await fetchOnceRef.current(pollId);
      if (result !== null) {
        onTickRef.current(result);
        if (isTerminalRef.current(result)) return;
      }
    } catch {
      // 일시 네트워크 오류 — 폴링을 멈추지 않고 다음 tick 에 재시도한다.
    }
    timer.current = setTimeout(() => void pollRef.current(pollId), POLL_INTERVAL_MS);
  }, []);

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  useEffect(() => {
    if (!id) return undefined;
    const kickoff = setTimeout(() => void pollRef.current(id), 0);
    return () => {
      clearTimeout(kickoff);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [id]);
}
