"use client";

import type { MouseEvent, ReactNode } from "react";

import { SITE_LIST_CANCEL_EVENT } from "./SiteListNavLink";

/**
 * 컨트롤 밖에 있는 초기화 이동(빈 상태의 `필터 초기화` 같은)을 감싼다.
 *
 * 공유 EmptyState에 현장 검색 사정을 coupling 하지 않기 위해, 캡처 단계에서
 * `/sites`로의 클릭 의도만 먼저 받아 대기 검색 타이머를 취소한다.
 * 이동 자체는 안의 링크가 그대로 맡는다.
 */
export function SiteListCancelBoundary({ children }: { children: ReactNode }) {
  function handleClickCapture(event: MouseEvent<HTMLElement>) {
    const target = event.target as HTMLElement | null;
    if (target?.closest?.('a[href="/sites"]')) {
      window.dispatchEvent(new Event(SITE_LIST_CANCEL_EVENT));
    }
  }

  return <div onClickCapture={handleClickCapture}>{children}</div>;
}
