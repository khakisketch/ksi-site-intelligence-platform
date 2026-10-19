"use client";

import type { ReactNode } from "react";

import { SiteListNavLink, SITE_LIST_PAGE_EVENT } from "./SiteListNavLink";
import { buildSiteListHref, pageWindow, type SiteListParams } from "./site-list-query";

/**
 * 데스크톱 목록 페이지 이동 — URL `page` 를 그대로 쓴다.
 *
 * 검색·필터·정렬 이동과 같은 약속이다: 기준 링크를 누르면 대기 중 검색
 * 타이머를 먼저 취소하고 확정된 조건으로만 이동한다(같은 탭 새 창 열기는
 * 브라우저가 맡고, 그때는 포커스를 옮기지 않는다). 북마크·공유·새로고침·
 * 뒤로가기는 URL이 기억하므로 별도 상태가 필요 없다.
 * 행이 한 페이지만 나오면 푸터 자체를 두지 않는다.
 */
export function SiteListPager({
  page,
  totalPages,
  base,
}: {
  page: number;
  totalPages: number;
  base: SiteListParams;
}) {
  if (totalPages <= 1) return null;
  const href = (p: number) => buildSiteListHref(base, { page: p === 1 ? undefined : String(p) });
  // 페이지 이동 의도를 먼저 알린다 — 대기 중 초안을 버리고 확정 검색어로 되돌린다.
  const announcePageIntent = () => {
    window.dispatchEvent(new Event(SITE_LIST_PAGE_EVENT));
  };
  const control = "btn tap-target min-w-9 px-2.5 text-[12.5px]";
  const current = "border-line-strong bg-sunk font-bold";
  const idle = "border-line bg-surface hover:border-line-strong";

  const numbers = pageWindow(page, totalPages);
  const windows: ReactNode[] = [];
  windows.push(
    page > 1 ? (
      <SiteListNavLink key="prev" href={href(page - 1)} onClick={announcePageIntent} className={control}>
        이전
      </SiteListNavLink>
    ) : (
      <span key="prev" aria-disabled="true" className={`${control} cursor-default opacity-40`}>
        이전
      </span>
    ),
  );
  numbers.forEach((item, index) => {
    if (item === "…") {
      windows.push(
        <span key={`gap-${index}`} aria-hidden="true" className="px-1 text-ink-muted">
          …
        </span>,
      );
      return;
    }
    windows.push(
      item === page ? (
        <SiteListNavLink key={item} href={href(item)} current="page" onClick={announcePageIntent} className={`${control} ${current}`}>
          {String(item)}
        </SiteListNavLink>
      ) : (
        <SiteListNavLink key={item} href={href(item)} onClick={announcePageIntent} className={`${control} ${idle}`}>
          {String(item)}
        </SiteListNavLink>
      ),
    );
  });
  windows.push(
    page < totalPages ? (
      <SiteListNavLink key="next" href={href(page + 1)} onClick={announcePageIntent} className={control}>
        다음
      </SiteListNavLink>
    ) : (
      <span key="next" aria-disabled="true" className={`${control} cursor-default opacity-40`}>
        다음
      </span>
    ),
  );

  return (
    <nav
      aria-label="현장 페이지"
      className="mt-4 flex flex-wrap items-center justify-center gap-1.5"
    >
      {windows}
    </nav>
  );
}
