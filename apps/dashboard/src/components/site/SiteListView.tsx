"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { readSiteListViewCookie, writeSiteListViewCookie, type SiteListViewMode } from "./site-list-view";
import { dropSiteListPage } from "./site-list-query";

function subscribeNoop() {
  return () => {};
}

/** 마운트 여부 — no-JS에서는 토글이 없다(죽은 버튼 대신 서버 화면을 읽는다). */
function useMounted() {
  return useSyncExternalStore(subscribeNoop, () => true, () => false);
}

/**
 * 데스크톱 보기 방식 선택기 — 같은 데이터의 두 표현을 바꾼다.
 *
 * - 서버가 읽은 쿠키값(`initialView`)으로 첫 렌더를 맞춘다 — 깜빡임 없음.
 *   마운트 때 살아 있는 쿠키가 props보다 새로우면 따라간다(같은 탭 저장 후
 *   리마운트). 뒤로가기 캐시 복원(리마운트 없음)은 손대지 않는다.
 * - 전환은 로컬 상태라 이동·refetch가 없고, 대기 검색을 취소하지 않는다 —
 *   입력 중 초안은 그대로 두고 디바운스가 끝나면 확정 검색어로 간다.
 *   IME 조합 중에도 제출하지 않는다. 선택할 때만 기능 쿠키에 기억한다.
 * - 보기 전환은 페이지 크기가 달라지므로 1페이지로 되돌린다(현재 URL에만
 *   page 가 있을 때 replace — 대기 검색은 건드리지 않고 초안도 둔다).
 *   토글 버튼 포커스는 그대로 남는다.
 * - 한 번에 하나의 표현만 DOM에 둔다. 숨은 쪽은 렌더하지 않으므로
 *   포커스·스크린리더에 들어갈 일이 없다.
 * - 페이지 번호를 눌러 이동하면 새 결과의 머리글로 포커스를 옮기고
 *   스크롤·안내를 함께 준다(바닥에 남지 않는다). 뒤로가기·필터 이동과
 *   새 탭 열기는 브라우저·기존 동작에 맡기고 포커스를 빼앗지 않는다.
 * - 첫 렌더는 서버와 같아야 해서 토글은 마운트 뒤에만 보인다 —
 *   JS가 없으면 서버가 준 화면을 읽는다(죽은 버튼 없음).
 */
export function SiteListView({
  initialView,
  toolbar,
  total,
  cards,
  cardsPage,
  cardsSummary,
  list,
  listPage,
  listSummary,
}: {
  initialView: SiteListViewMode;
  /** 검색·정렬 폼 — 보기 전환과 무관하게 같은 자리에 남는다. */
  toolbar: ReactNode;
  /** 걸린 전체 행 수(유틸리티 타일 제외) — data-site-total 훅용. */
  total: number;
  /** 갤러리 패널 + 그 페이지 정보(서버가 카드 크기로 계산). */
  cards: ReactNode;
  cardsPage: number;
  cardsSummary: string;
  /** 밀도표 패널 + 그 페이지 정보(서버가 목록 크기로 계산). */
  list: ReactNode;
  listPage: number;
  listSummary: string;
}) {
  const router = useRouter();
  const [view, setView] = useState<SiteListViewMode>(
    () => readSiteListViewCookie() ?? initialView,
  );
  const [announcement, setAnnouncement] = useState("");
  const mounted = useMounted();
  const panelRef = useRef<HTMLDivElement>(null);
  const page = view === "cards" ? cardsPage : listPage;
  const pageSummary = view === "cards" ? cardsSummary : listSummary;
  const prevPageRef = useRef(page);
  /** 페이지 번호의 평범한 좌클릭에만 반응한다(새 탭 열기는 제외). */
  const pageNavRef = useRef(false);

  useEffect(() => {
    if (prevPageRef.current === page) return;
    prevPageRef.current = page;
    if (!pageNavRef.current) return;
    pageNavRef.current = false;
    setAnnouncement(`현장 목록 ${page}페이지, ${pageSummary}`);
    const panel = panelRef.current;
    const heading = panel?.querySelector("h2");
    if (heading instanceof HTMLElement) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    }
    if (typeof panel?.scrollIntoView === "function") {
      panel.scrollIntoView({ block: "start" });
    }
  }, [page, pageSummary]);

  function handlePanelClickCapture(event: ReactMouseEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    const anchor = (event.target as HTMLElement | null)?.closest?.('nav[aria-label="현장 페이지"] a[href]');
    if (!anchor) return;
    pageNavRef.current = true;
  }

  function select(next: SiteListViewMode) {
    // 이미 보고 있는 방식이면 아무 일도 없다 — 페이지도 검색도 건드리지 않는다.
    if (next === view) return;
    // 대기 검색은 취소하지 않는다 — 초안은 살리고 디바운스가 끝나면 간다.
    setView(next);
    writeSiteListViewCookie(next);
    // 페이지 크기가 달라지므로 1페이지로 되돌린다(page 가 있을 때만 이동).
    const href = dropSiteListPage(window.location.search);
    if (href) router.replace(href, { scroll: false });
  }

  const active = (mode: SiteListViewMode) =>
    `btn tap-target px-3 text-[12.5px] ${
      view === mode
        ? "border-line-strong bg-sunk font-bold"
        : "border-line bg-surface hover:border-line-strong"
    }`;

  return (
    <>
      <div className="flex w-full flex-wrap items-center gap-3 border-t border-line pt-3">
        <div className="min-w-0 flex-1">{toolbar}</div>
        {mounted && (
          <div role="group" aria-label="현장 보기 방식" className="flex shrink-0 items-center gap-1.5">
            <button type="button" aria-pressed={view === "cards"} onClick={() => select("cards")} className={active("cards")}>
              카드
            </button>
            <button type="button" aria-pressed={view === "list"} onClick={() => select("list")} className={active("list")}>
              목록
            </button>
          </div>
        )}
      </div>
      <div
        ref={panelRef}
        onClickCapture={handlePanelClickCapture}
        data-site-list-view={view}
        data-site-page={page}
        data-site-total={total}
      >
        {view === "cards" ? cards : list}
      </div>
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </>
  );
}
