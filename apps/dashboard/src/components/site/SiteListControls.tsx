"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { buildSiteListHref, type SiteListParams } from "./site-list-query";
import { SITE_LIST_CANCEL_EVENT } from "./SiteListNavLink";

const DEBOUNCE_MS = 300;

function MagnifierIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-muted"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" strokeLinecap="round" />
    </svg>
  );
}

function SortIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-muted"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
    >
      <path d="M5 3v10m0 0L2.5 10.5M5 13l2.5-2.5M11 13V3m0 0L8.5 5.5M11 3l2.5 2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ClearIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
    </svg>
  );
}

/**
 * 현장 목록 검색·정렬 — 보이는 검색 버튼 없는 돋보기 내장 입력 + 네이티브 정렬.
 * 정렬 아이콘도 셀 안에 둔다(밖 라벨·바깥 여백 없음 — 두 컨트롤의 언어가 같다).
 *
 * - 입력과 정렬은 같은 높이(`input tap-target` — 조밀 36 / coarse·좁은 폭 44).
 *   보이는 바깥 라벨은 두지 않고 sr 라벨만 둔다(한쪽만 위에 라벨을 두던 혼선을 없앤다).
 * - 자동 입력은 300ms 디바운스로 `replace` 한다 — 히스토리 스팸 없음.
 *   한글 IME 조합 중에는 확정하지 않는다.
 * - ENTER·정렬 변경·지우기는 의도적 이동이므로 `push` 한다.
 *   정렬을 바꿔도 입력 중 초안을 함께 보내 검색어를 잃지 않는다.
 * - URL → 초안은 뒤로/앞으로·공유·새로고침 때만 반영한다. 입력 포커스 중이거나
 *   방금 커밋한 값과 URL이 같으면 덮지 않는다 — router 응답이 오는 동안
 *   타이핑 중 텍스트를 지우지 않는다.
 * - JS가 없으면 네이티브 GET 폼으로 동작한다(ENTER 제출 + noscript 적용 버튼).
 *   검색 지우기는 q만, 초기화는 전체 조건을 되돌린다. POST 없음.
 * - 부모는 묶음·상태가 바뀌면 key를 바꿔 다시 만든다. 서버 렌더 링크
 *   (칩)를 먼저 누르고 타이머가 늦게 도는 경우, 옛날 기준으로 replace 해서
 *   새 필터를 되돌리는 일을 언마운트 정리로 막는다. 응답 전 공백(칩 클릭 직후
 *   300ms 안)은 예약 시점 조건표(ticket)와 주소창 대조, 그리고 클릭 의도
 *   이벤트(SITE_LIST_CANCEL_EVENT)로 버린다. 정렬은 key에 넣지 않는다 —
 *   정렬 변경은 안에서 타이머를 취소하고 push 하므로 리마운트 없이 끝난다.
 */
export function SiteListControls({
  query,
  sort,
  group,
  status,
  hasFilter,
  className = "",
}: {
  query?: string;
  sort: string;
  group?: string;
  status?: string;
  hasFilter: boolean;
  className?: string;
}) {
  const router = useRouter();
  const searchId = useId();
  const sortId = useId();
  const committedQuery = query ?? "";
  const [draft, setDraft] = useState(committedQuery);
  const [pending, setPending] = useState(false);
  /** URL에 반영된 마지막 검색어 — 뒤로가기 판정과 히스토리 스팸 방지의 기준. */
  const appliedRef = useRef(committedQuery);
  const composingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const base: SiteListParams = { q: query, status, sort, group };

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  function cancelPending() {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setPending(false);
  }

  useEffect(() => {
    // 뒤로/앞으로(popstate)는 명시적 브라우저 이동이다 — 포커스 중이어도
    // 주소창 기준으로 초안을 되돌리고 대기 타이머를 취소한다.
    // push/replace 는 popstate 를 일으키지 않으므로 우리 커밋과 섞이지 않는다.
    function handlePopState() {
      cancelPending();
      const next = new URLSearchParams(window.location.search).get("q") ?? "";
      appliedRef.current = next;
      setDraft(next);
    }
    // 기준 링크(칩·초기화)의 클릭 의도 — 느린 RSC 응답으로 주소창·props가
    // 늦게 와도, 대기 중이던 옛 타이머가 새 필터를 되돌리지 못하게 한다.
    function handleCancelIntent() {
      cancelPending();
    }
    window.addEventListener("popstate", handlePopState);
    window.addEventListener(SITE_LIST_CANCEL_EVENT, handleCancelIntent);
    return () => {
      window.removeEventListener("popstate", handlePopState);
      window.removeEventListener(SITE_LIST_CANCEL_EVENT, handleCancelIntent);
    };
  }, []);

  useEffect(() => {
    // 외부에서 URL이 바뀌었을 때(뒤로/앞으로·공유 링크) 초안을 따라간다.
    // 입력 중이면 손대지 않는다 — 미확정 초안을 지우는 것도,
    // in-flight 응답으로 타이핑을 덮는 것도 여기서 막는다.
    if (document.activeElement === inputRef.current) return;
    if (committedQuery === appliedRef.current) return;
    appliedRef.current = committedQuery;
    setDraft(committedQuery);
    setPending(false);
  }, [committedQuery]);

  function commit(next: string, navigation: "replace" | "push") {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (next === appliedRef.current) {
      setPending(false);
      return;
    }
    appliedRef.current = next;
    setDraft(next);
    setPending(false);
    const href = buildSiteListHref(base, { q: next || undefined });
    if (navigation === "push") router.push(href, { scroll: false });
    else router.replace(href, { scroll: false });
  }

  function scheduleCommit(next: string) {
    // 예약 시점의 묶음·상태·정렬을 표로 남긴다. 타이머가 늦게 돌 때 주소창이
    // 이미 다른 조건(칩 클릭·뒤로가기)이면 옛 기준으로 덮지 않고 버린다.
    const ticket = { group: group ?? "all", status: status ?? null, sort };
    setPending(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      const current = new URLSearchParams(window.location.search);
      const moved =
        ticket.group !== (current.get("group") ?? "all") ||
        ticket.status !== current.get("status") ||
        ticket.sort !== (current.get("sort") ?? "attention");
      if (moved) {
        setPending(false);
        return;
      }
      commit(next, "replace");
    }, DEBOUNCE_MS);
  }

  function handleSearchChange(value: string) {
    setDraft(value);
    if (composingRef.current) return;
    scheduleCommit(value);
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    // IME 조합 중 ENTER는 확정 취소가 아니라 조합 확정이므로 제출하지 않는다.
    if (composingRef.current) return;
    commit(draft, "push");
  }

  function handleSortChange(nextSort: string) {
    // 정렬을 바꾸면 입력 중 초안도 함께 확정한다 — 정렬하느라 검색어를 잃지 않는다.
    cancelPending();
    appliedRef.current = draft;
    router.push(buildSiteListHref(base, { q: draft || undefined, sort: nextSort }), {
      scroll: false,
    });
  }

  function handleClearSearch() {
    cancelPending();
    appliedRef.current = "";
    setDraft("");
    router.push(buildSiteListHref(base, { q: undefined }), { scroll: false });
    inputRef.current?.focus();
  }

  return (
    <form
      action="/sites"
      method="get"
      onSubmit={handleSubmit}
      role="search"
      aria-label="현장 검색과 정렬"
      className={`flex flex-wrap items-center gap-2 ${className}`}
    >
      {group && <input type="hidden" name="group" value={group} />}
      {status && <input type="hidden" name="status" value={status} />}
      <div className="relative min-w-40 flex-1 lg:w-64 lg:flex-none">
        <label htmlFor={searchId} className="sr-only">
          현장 찾기
        </label>
        <MagnifierIcon />
        <input
          ref={inputRef}
          id={searchId}
          name="q"
          type="search"
          value={draft}
          placeholder="현장명 또는 ID"
          autoComplete="off"
          onChange={(event) => handleSearchChange(event.target.value)}
          onCompositionStart={() => {
            composingRef.current = true;
            if (timerRef.current) {
              clearTimeout(timerRef.current);
              timerRef.current = null;
            }
          }}
          onCompositionEnd={(event) => {
            composingRef.current = false;
            scheduleCommit(event.currentTarget.value);
          }}
          // 지우개가 있을 때만 오른쪽을 비운다 — 390에서도 자리가 좁아지지 않게.
          // 브라우저 기본 지우개(webkit cancel)는 끈다. 둘이 겹치면 두 번 지워진다.
          className={`input tap-target site-list-search w-full pl-9 text-[13px] ${
            draft.length > 0 ? "pr-11" : "pr-3"
          }`}
        />
        {/* 네이티브 type=search 지우개와 커스텀 × 가 나란히 서지 않게 한다. */}
        <style>{`.site-list-search::-webkit-search-cancel-button{display:none}`}</style>
        {draft.length > 0 && (
          <button
            type="button"
            onClick={handleClearSearch}
            aria-label="검색어 지우기"
            // 좁은 폭·손가락 환경은 44 계약, 데스크톱 조밀 환경은 입력 높이에 맞춘다.
            className="absolute top-1/2 right-1 grid size-8 max-lg:size-11 -translate-y-1/2 place-items-center rounded-md text-ink-muted hover:text-ink-1 pointer-coarse:size-11"
          >
            <ClearIcon />
          </button>
        )}
      </div>
      <div className="relative">
        <label htmlFor={sortId} className="sr-only">
          정렬 기준
        </label>
        <SortIcon />
        <select
          id={sortId}
          name="sort"
          value={sort}
          onChange={(event) => handleSortChange(event.target.value)}
          className="input tap-target w-[164px] pr-8 pl-9 text-[13px]"
        >
          <option value="attention">확인 필요 순</option>
          <option value="updated">최근 갱신 순</option>
          <option value="name">이름 순</option>
        </select>
      </div>
      <noscript>
        <button type="submit" className="btn tap-target">
          검색·정렬 적용
        </button>
      </noscript>
      {hasFilter && (
        <Link
          href="/sites"
          onClick={cancelPending}
          // 좁은 폭에서는 상태 필터 서랍의 초기화가 전역 초기화를 맡는다 —
          // 여기서 한 줄을 더 쓰면 목록이 밀린다. 데스크톱에서는 같은 높이를 둔다.
          className="btn tap-target hidden lg:inline-flex"
        >
          초기화
        </Link>
      )}
      <p role="status" className="sr-only">
        {pending ? "검색어 적용 중" : ""}
      </p>
    </form>
  );
}
