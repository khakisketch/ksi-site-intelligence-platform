"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { buildSiteListHref, type SiteListParams } from "./site-list-query";
import { SITE_LIST_CANCEL_EVENT, SITE_LIST_PAGE_EVENT, SiteListNavLink } from "./SiteListNavLink";
import { SITE_GROUPS } from "@/lib/core-api/site-progress";

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
 * - 폰(<640)에서는 바깥 정렬 셀렉트를 숨기고(`sm:hidden` 패널이 유일한
 *   보이는 정렬), 검색 아래 건수+`필터·정렬` 행을 둔다. 패널 적용은
 *   묶음·정렬 선택과 최신 검색 초안을 함께 push 하고 닫은 뒤 요약으로
 *   포커스를 돌린다. 적용 없이 닫으면 미확정 선택을 버린다.
 * - 부모는 리마운트하지 않는다(폰 적용 후 요약 포커스를 살린다). 묶음·상태
 *   prop 변화는 패널 셀렉트의 key가 따라가고, 대기 타이머는 기준 링크 클릭
 *   의도 이벤트(SITE_LIST_CANCEL_EVENT)·예약 시점 조건표와 주소창 대조·
 *   popstate가 취소하므로 옛 기준으로 새 필터를 되돌리지 못한다.
 */
export function SiteListControls({
  query,
  sort,
  group,
  status,
  hasFilter,
  visibleCount,
  totalCount,
  className = "",
}: {
  query?: string;
  sort: string;
  group?: string;
  status?: string;
  hasFilter: boolean;
  /** 서버가 준 실제 건수 — 안전·정상 판단이 아니라 목록 수다. */
  visibleCount: number;
  totalCount: number;
  className?: string;
}) {
  const router = useRouter();
  const searchId = useId();
  const sortId = useId();
  const phoneGroupId = useId();
  const phoneSortId = useId();
  const committedQuery = query ?? "";
  const committedGroup = group ?? "all";
  const [draft, setDraft] = useState(committedQuery);
  const [pending, setPending] = useState(false);
  /** URL에 반영된 마지막 검색어 — 뒤로가기 판정과 히스토리 스팸 방지의 기준. */
  const appliedRef = useRef(committedQuery);
  /** 마지막으로 본 묶음·상태 — q가 같아도 기준이 바뀌면 입력을 확정값으로 되돌린다. */
  const criteriaRef = useRef({ group, status });
  /** 마지막 키 입력 때의 주소창 — 늦게 도착한 이전 내비게이션 응답이
      방금 타이핑을 지우지 않게 대조한다. 칩 클릭처럼 주소창이 먼저
      바뀌는 이동 뒤의 응답은 확정값 되돌리기를 그대로 둔다. */
  const typeSearchRef = useRef<string | null>(null);
  const composingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const phoneDetailsRef = useRef<HTMLDetailsElement>(null);
  const phoneSummaryRef = useRef<HTMLElement>(null);
  const phoneGroupRef = useRef<HTMLSelectElement>(null);
  const phoneSortRef = useRef<HTMLSelectElement>(null);
  /** 적용 버튼으로 닫을 때는 닫힘 정리를 건너뛴다(적용한 값을 유지한다). */
  const phoneAppliedRef = useRef(false);
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
    // 페이지 번호의 클릭 의도 — 타이머를 버리고 확정 검색어로 되돌린다.
    // 같은 q 응답은 입력 동기화를 일으키지 않으므로 여기서 맞춘다.
    function handlePageIntent() {
      cancelPending();
      appliedRef.current = committedQuery;
      setDraft(committedQuery);
    }
    window.addEventListener("popstate", handlePopState);
    window.addEventListener(SITE_LIST_CANCEL_EVENT, handleCancelIntent);
    window.addEventListener(SITE_LIST_PAGE_EVENT, handlePageIntent);
    return () => {
      window.removeEventListener("popstate", handlePopState);
      window.removeEventListener(SITE_LIST_CANCEL_EVENT, handleCancelIntent);
      window.removeEventListener(SITE_LIST_PAGE_EVENT, handlePageIntent);
    };
  }, [committedQuery]);

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

  useEffect(() => {
    // 기준(묶음·상태)이 바뀌면 q가 같아도 결과와 입력이 어긋난다 —
    // 포커스 중이어도 대기 타이머를 버리고 확정 검색어로 되돌린다.
    // q만 바뀌는 자체 ack(group/status 동일)는 여기서 손대지 않는다.
    // 단, 주소창이 마지막 키 입력 때와 같으면 그 입력은 지금 기준에서 친
    // 것이다 — 아직 도착하지 않은 이전 내비게이션의 늦은 응답으로 지우지
    // 않는다(칩 클릭은 주소창을 먼저 바꾸므로 되돌리기를 그대로 둔다).
    // 이때 대기 타이머는 이미 버린 상태이므로, 최신 기준으로 다시 예약해
    // 입력만 남고 확정이 사라지는 반쪽 상태를 만들지 않는다. 조합 중에는
    // 확정하지 않는다(조합 확정이 예약한다).
    const prev = criteriaRef.current;
    if (prev.group === group && prev.status === status) return;
    criteriaRef.current = { group, status };
    cancelPending();
    if (typeSearchRef.current !== null && typeSearchRef.current === window.location.search) {
      if (!composingRef.current) {
        scheduleCommit(draft);
      }
      return;
    }
    appliedRef.current = committedQuery;
    setDraft(committedQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 기준 변경 가드에만 반응한다. draft·scheduleCommit은 최신 렌더 값을 의도적으로 읽는다
  }, [group, status, committedQuery]);

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
    typeSearchRef.current = window.location.search;
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

  function closePhonePanel() {
    phoneDetailsRef.current?.removeAttribute("open");
    phoneSummaryRef.current?.focus();
  }

  function resetPhoneSelects(groupValue: string, sortValue: string) {
    if (phoneGroupRef.current) phoneGroupRef.current.value = groupValue;
    if (phoneSortRef.current) phoneSortRef.current.value = sortValue;
  }

  function handlePhoneToggle() {
    const details = phoneDetailsRef.current;
    if (!details || details.open) return;
    // 적용으로 닫은 게 아니면 미확정 선택을 버리고 확정 조건으로 되돌린다.
    if (phoneAppliedRef.current) {
      phoneAppliedRef.current = false;
      return;
    }
    resetPhoneSelects(committedGroup, sort);
  }

  function handlePhoneApply(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // IME 조합 중 적용은 확정 취소가 아니라 조합 확정이므로 제출하지 않는다.
    // 보통 탭하면 조합이 끝나지만, 키보드·프로그래밍 제출은 여기서 막는다.
    if (composingRef.current) return;
    // 패널 선택 + 최신 검색 초안을 원자적으로 확정한다. 숨은 q가 아니라
    // 방금 타이핑한 draft를 쓴다 — 대기 타이머는 먼저 취소한다.
    const data = new FormData(event.currentTarget);
    const nextGroup = data.get("group");
    const nextSort = data.get("sort");
    cancelPending();
    phoneAppliedRef.current = true;
    appliedRef.current = draft;
    setPending(false);
    const href = buildSiteListHref(base, {
      q: draft || undefined,
      group:
        typeof nextGroup === "string" && nextGroup !== "all" ? nextGroup : undefined,
      sort: typeof nextSort === "string" && nextSort ? nextSort : undefined,
    });
    if (href !== `${window.location.pathname}${window.location.search}`) {
      router.push(href, { scroll: false });
    }
    closePhonePanel();
  }

  function handlePhoneReset() {
    // 전체 초기화는 확정 조건으로 되돌린다 — 패널이 열린 채 낡은 선택을 두지 않는다.
    // URL이 이미 /sites 면 응답이 와도 q effect가 돌지 않으므로 초안도 여기서 비운다.
    phoneAppliedRef.current = true;
    cancelPending();
    appliedRef.current = "";
    setDraft("");
    resetPhoneSelects("all", "attention");
    closePhonePanel();
  }

  return (
    <>
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
      <div className="relative hidden sm:block">
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

    {/* 폰(<640) 전용 건수+필터 행 — 검색 아래 같은 줄에 붙는다.
        바깥 정렬 셀렉트는 폰에서 숨으므로(중복 포커스 방지) 묶음·정렬 선택은
        여기서만 보인다. 폼을 나누어 중첩 폼을 만들지 않는다. */}
    <details ref={phoneDetailsRef} onToggle={handlePhoneToggle} className="mt-2 sm:hidden">
      <summary
        ref={phoneSummaryRef}
        className="flex cursor-pointer items-center justify-between gap-2 px-1 py-2 text-[12.5px]"
      >
        <span className="num text-ink-muted">
          {visibleCount} / {totalCount}곳 표시
        </span>
        <span className="inline-flex items-center gap-1 font-semibold">
          필터·정렬
          <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="m4 6 4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </summary>
      <form
        action="/sites"
        method="get"
        aria-label="현장 필터"
        onSubmit={handlePhoneApply}
        className="grid gap-2 rounded-lg border border-line bg-surface p-3"
      >
        {/* noJS 대체용. JS 적용은 최신 draft를 직접 쓰므로 낡은 값을 쓰지 않는다. */}
        {committedQuery && <input type="hidden" name="q" value={committedQuery} />}
        {status && <input type="hidden" name="status" value={status} />}
        <label htmlFor={phoneGroupId} className="grid gap-1 text-[12px] font-medium text-ink-2">
          현장 상태
          <select
            ref={phoneGroupRef}
            key={committedGroup}
            id={phoneGroupId}
            name="group"
            defaultValue={committedGroup}
            className="input tap-target w-full text-[13px]"
          >
            {SITE_GROUPS.map((option) => (
              <option key={option.key} value={option.key}>{option.label}</option>
            ))}
          </select>
        </label>
        <label htmlFor={phoneSortId} className="grid gap-1 text-[12px] font-medium text-ink-2">
          정렬 기준
          <select
            ref={phoneSortRef}
            key={sort}
            id={phoneSortId}
            name="sort"
            defaultValue={sort}
            className="input tap-target w-full text-[13px]"
          >
            <option value="attention">확인 필요 순</option>
            <option value="updated">최근 갱신 순</option>
            <option value="name">이름 순</option>
          </select>
        </label>
        <div className="flex gap-2">
          <button type="submit" className="btn btn-primary tap-target flex-1">적용</button>
          <SiteListNavLink href="/sites" onClick={handlePhoneReset} className="btn tap-target flex-1 justify-center">
            초기화
          </SiteListNavLink>
        </div>
      </form>
    </details>
    </>
  );
}
