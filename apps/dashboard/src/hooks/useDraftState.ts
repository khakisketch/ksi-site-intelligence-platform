"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type DraftStorageStatus = "loading" | "ready" | "unreadable" | "unavailable" | "write-failed";

// Wizard 이탈(뒤로가기·새로고침) 시 입력 소실을 막는다 — UX 목표 §2 "Wizard 재작업 비용이
// 완주율을 결정" 근거. sessionStorage — 브라우저 탭을 닫으면 자연 소멸(민감 정보 장기 잔존 방지).
export function useDraftState<T>(
  key: string,
  initial: T,
  migrate?: (stored: unknown) => T,
): [T, (value: T) => void, () => void, DraftStorageStatus] {
  const [state, setState] = useState<T>(initial);
  const [dirty, setDirty] = useState(false);
  const initialRef = useRef(initial);
  // key를 상태에 결속한다. key가 바뀌는 렌더와 새 저장소 수화 사이에 이전
  // state가 새 키를 덮어쓰지 않아야 한다.
  const [storage, setStorage] = useState<{ key: string; status: DraftStorageStatus }>({
    key,
    status: "loading",
  });
  const storageStatus = storage.key === key ? storage.status : "loading";

  useEffect(() => {
    // sessionStorage 는 서버(SSR)에 존재하지 않아 useState 지연 초기화로는 읽을 수 없다 —
    // 마운트 후 클라이언트 전용 storage 를 React state 로 동기화하는 effect 의 정상 용례다.
    let raw: string | null;
    // 수화는 사용자의 편집이 아니다. 원래 문자열은 편집이 일어나기 전까지
    // 다시 직렬화하지 않는다(알 수 없는 이전 필드·원문 보존).
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 외부 저장소의 새 키/수화 경계
    setDirty(false);
    try {
      raw = sessionStorage.getItem(key);
    } catch {
      // 읽을 수 없다면 기존 기록의 존재 여부도 알 수 없다. 추측해서 덮지 않는다.
      setStorage({ key, status: "unavailable" });
      return;
    }
    if (raw !== null) {
      try {
        const stored: unknown = JSON.parse(raw);
        setState(migrate ? migrate(stored) : (stored as T));
      } catch {
        // 잘못된 JSON이나 migration 실패는 빈 초안으로 바꾸지 않는다. 원래
        // 문자열은 그대로 두고 자동 저장을 잠가 caller가 상태를 안내하게 한다.
        setStorage({ key, status: "unreadable" });
        return;
      }
    } else {
      // 새 키에 저장된 초안이 없다면 이전 키의 내용을 복사하지 않는다.
      setState(initialRef.current);
    }
    setStorage({ key, status: "ready" });
  }, [key, migrate]);

  useEffect(() => {
    if (storageStatus !== "ready" || !dirty) return;
    try {
      sessionStorage.setItem(key, JSON.stringify(state));
    } catch {
      // 저장 실패(quota 등)는 사용자에게 알릴 수 있게 상태를 남긴다.
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 외부 저장소의 실제 쓰기 실패 결과
      setStorage({ key, status: "write-failed" });
    }
  }, [key, state, storageStatus, dirty]);

  const setDraft = useCallback((value: T) => {
    setState(value);
    setDirty(true);
  }, []);

  const clear = () => {
    try {
      sessionStorage.removeItem(key);
    } catch {
      // no-op
    }
  };

  return [state, setDraft, clear, storageStatus];
}
