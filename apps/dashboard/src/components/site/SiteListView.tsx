"use client";

import { useState, useSyncExternalStore, type ReactNode } from "react";

import {
  readSiteListViewCookie,
  writeSiteListViewCookie,
  type SiteListViewMode,
} from "./site-list-view";

/**
 * 마운트 여부 — no-JS에서는 토글이 없다(죽은 버튼 대신 서버가 준 화면을 읽는다).
 * useState 초기값은 SSR과 달라질 수 없어 여기서만 쓴다.
 */
function useMounted() {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}

/**
 * 데스크톱 보기 방식 선택기 — 같은 데이터의 두 표현을 바꾼다.
 *
 * - 서버가 읽은 쿠키값(`initialView`)으로 첫 렌더를 맞춘다 — 깜빡임 없음.
 * - 전환은 로컬 상태라서 이동·refetch가 없고, 검색 초안·타이머·IME에
 *   손대지 않는다. 선택할 때만 기능 쿠키에 기억한다.
 * - 한 번에 하나의 표현만 DOM에 둔다. 숨은 쪽은 렌더하지 않으므로
 *   포커스·스크린리더에 들어갈 일이 없다.
 * - 첫 렌더는 서버와 같아야 해서 토글은 마운트 뒤에만 보인다 —
 *   JS가 없으면 서버가 준 표현 그대로 읽는다(죽은 버튼 없음).
 * - 마운트 때 살아 있는 쿠키를 한 번 다시 읽는다. 같은 탭에서 바꾼 뒤
 *   리사이즈로 다시 마운트되는 등 props가 낡았을 때를 바로잡는다.
 *   뒤로가기 캐시 복원(리마운트 없음)은 손대지 않아 기억된 선택이 남는다.
 */
export function SiteListView({
  initialView,
  toolbar,
  cards,
  list,
}: {
  initialView: SiteListViewMode;
  /** 검색·정렬 폼 — 보기 전환과 무관하게 같은 자리에 남는다. */
  toolbar: ReactNode;
  cards: ReactNode;
  list: ReactNode;
}) {
  // 첫 렌더는 서버 HTML과 같아야 한다. 같은 문서의 쿠키는 서버가 읽은 값과
  // 같으므로 지연 초기값으로 읽어도 hydration이 어긋나지 않는다. 리마운트
  // (반응형 임계값 교차 등) 때는 살아 있는 쿠키가 props보다 새로울 수 있어
  // 초기값이 곧 정답이다 — 뒤로가기 캐시 복원(리마운트 없음)은 손대지 않는다.
  const [view, setView] = useState<SiteListViewMode>(
    () => readSiteListViewCookie() ?? initialView,
  );
  const mounted = useMounted();

  function select(next: SiteListViewMode) {
    setView(next);
    writeSiteListViewCookie(next);
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
      <div data-site-list-view={view}>{view === "cards" ? cards : list}</div>
    </>
  );
}
