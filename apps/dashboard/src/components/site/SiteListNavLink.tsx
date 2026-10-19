"use client";

import Link from "next/link";
import type { MouseEvent, ReactNode } from "react";

/**
 * 기준 이동 의도 알림 — 현장 목록 칩·상태 되돌리기가 누르기 전에 보낸다.
 *
 * 검색 컨트롤의 대기 타이머(300ms)는 주소창·props가 늦게 오는 공백에
 * 옛 기준으로 replace 할 수 있다(느린 RSC 응답). 이동 자체는 Link가 맡고,
 * 여기서는 의도만 먼저 알려 대기 타이머를 취소한다. 입력 중 초안은
 * 건드리지 않는다 — 응답이 오면 key 리마운트가 확정 검색어로 되돌린다.
 */
export const SITE_LIST_CANCEL_EVENT = "site-list:cancel-pending";

export function SiteListNavLink({
  href,
  current,
  className,
  children,
  onClick,
}: {
  href: string;
  current?: boolean;
  className?: string;
  children: ReactNode;
  /** 이동 의도 알림 뒤에 덧붙일 정리(패널 닫기 등) — 이동 자체는 막지 않는다. */
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  return (
    <Link
      href={href}
      aria-current={current ? "true" : undefined}
      className={className}
      onClick={(event) => {
        window.dispatchEvent(new Event(SITE_LIST_CANCEL_EVENT));
        onClick?.(event);
      }}
    >
      {children}
    </Link>
  );
}
