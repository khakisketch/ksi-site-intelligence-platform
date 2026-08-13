"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

import { parseJsonSafe } from "@/lib/http";

const DEFAULT_ERROR_MESSAGE = "요청을 처리하지 못했습니다.";
const NETWORK_ERROR_MESSAGE = "요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.";

/**
 * 클라이언트 컴포넌트의 mutation 관용구를 뽑은 것 — `usePolling.ts` 가 폴링 관용구를
 * 이미 두 컴포넌트에서 뽑아낸 선례를 그대로 따른다(usePolling.ts 상단 docstring 참조).
 *
 * 캡슐화하는 것: 요청 전송 → `parseJsonSafe`로 안전한 JSON 파싱 → 실패 시 에러 메시지
 * 상태 → 성공 시 호출부 콜백. 409(낙관적 동시성 충돌) 응답이면 `router.refresh()`를
 * 여기서 부른다 — EventActions.tsx 가 손으로 구현했던 "토큰이 낡았으면 화면을 갱신해
 * 새 지문을 받아온다" 규약을 모든 호출부의 공통 규약으로 올린 것이다.
 *
 * pending 표시는 이 훅이 소유하지 않는다 — `usePolling`의 `onTick`처럼, 호출부마다
 * "어떤 액션이 진행 중인지"의 모양이 다르다(단일 boolean인 곳도 있고, 여러 액션 중
 * 어느 것이 진행 중인지 라벨로 구분하는 곳도 있다). 그건 호출부의 몫으로 남긴다.
 */
export function useMutation<T = unknown>() {
  const router = useRouter();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const mutate = useCallback(
    async (
      input: string,
      init: RequestInit,
      onSuccess: (payload: Partial<T>) => void,
    ): Promise<void> => {
      setErrorMessage(null);
      try {
        const response = await fetch(input, init);
        const payload = await parseJsonSafe<T>(response);
        if (!response.ok) {
          const message = (payload as { message?: unknown }).message;
          setErrorMessage(
            typeof message === "string" && message ? message : DEFAULT_ERROR_MESSAGE,
          );
          // 토큰이 낡아서 막힌 경우(낙관적 동시성 충돌)엔 화면을 갱신해 새 지문을
          // 받아온다 — 안 그러면 사용자가 같은 낡은 값으로 계속 재시도해 막다른
          // 길이 된다.
          if (response.status === 409) {
            router.refresh();
          }
          return;
        }
        onSuccess(payload);
      } catch {
        setErrorMessage(NETWORK_ERROR_MESSAGE);
      }
    },
    [router],
  );

  return { mutate, errorMessage, setErrorMessage };
}
