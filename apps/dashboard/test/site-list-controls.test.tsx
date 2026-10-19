/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocked.push, replace: mocked.replace }) }));

import { SiteListControls } from "@/components/site/SiteListControls";
import { SiteListCancelBoundary } from "@/components/site/SiteListCancelBoundary";
import { SiteListNavLink, SITE_LIST_CANCEL_EVENT } from "@/components/site/SiteListNavLink";
import { SiteListVisual } from "@/components/site/SiteListVisual";
import { buildSiteListHref, clearSearchHref } from "@/components/site/site-list-query";

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

function setLocation(path: string) {
  window.history.replaceState(null, "", path);
}

function renderControls(props: {
  query?: string;
  sort?: string;
  group?: string;
  status?: string;
  hasFilter?: boolean;
  visibleCount?: number;
  totalCount?: number;
} = {}) {
  return render(
    <SiteListControls
      query={props.query}
      sort={props.sort ?? "attention"}
      group={props.group}
      status={props.status}
      hasFilter={props.hasFilter ?? false}
      visibleCount={props.visibleCount ?? 3}
      totalCount={props.totalCount ?? 5}
    />,
  );
}

function searchbox() {
  return screen.getByRole("searchbox", { name: "현장 찾기" }) as HTMLInputElement;
}

function searchForm() {
  return screen.getByRole("search", { name: "현장 검색과 정렬" });
}

function phoneForm() {
  return screen.getByRole("form", { name: "현장 필터" });
}

function sortSelect() {
  return within(searchForm()).getByRole("combobox", { name: "정렬 기준" }) as HTMLSelectElement;
}

function phoneGroupSelect() {
  return within(phoneForm()).getByRole("combobox", { name: "현장 상태" }) as HTMLSelectElement;
}

function phoneSortSelect() {
  return within(phoneForm()).getByRole("combobox", { name: "정렬 기준" }) as HTMLSelectElement;
}

function hrefParams(href: string) {
  return new URL(href, "http://localhost").searchParams;
}

describe("site list query", () => {
  it("검색어를 바꾸면서 묶음·상태·정렬을 잃지 않는다", () => {
    const params = hrefParams(
      buildSiteListHref({ q: "서쪽", status: "UNMAPPED", sort: "name", group: "attention" }, { q: "동쪽" }),
    );
    expect(params.get("q")).toBe("동쪽");
    expect(params.get("status")).toBe("UNMAPPED");
    expect(params.get("sort")).toBe("name");
    expect(params.get("group")).toBe("attention");
  });

  it("정렬을 바꾸면서 검색어·묶음·상태를 잃지 않는다", () => {
    const params = hrefParams(
      buildSiteListHref({ q: "서쪽", status: "UNMAPPED", sort: "attention", group: "attention" }, { sort: "name" }),
    );
    expect(params.get("q")).toBe("서쪽");
    expect(params.get("sort")).toBe("name");
    expect(params.get("group")).toBe("attention");
    expect(params.get("status")).toBe("UNMAPPED");
  });

  it("검색 지우기는 q만 되돌린다", () => {
    const params = hrefParams(
      clearSearchHref({ q: "서쪽", status: "UNMAPPED", sort: "name", group: "attention" }),
    );
    expect(params.get("q")).toBeNull();
    expect(params.get("status")).toBe("UNMAPPED");
    expect(params.get("sort")).toBe("name");
    expect(params.get("group")).toBe("attention");
  });

  it("빈 조건은 URL에 남기지 않는다", () => {
    expect(buildSiteListHref({ sort: "updated" }, {})).toBe("/sites?sort=updated");
    expect(buildSiteListHref({}, { q: undefined })).toBe("/sites");
    expect(buildSiteListHref({ q: "", status: undefined }, {})).toBe("/sites");
  });
});

describe("SiteListControls", () => {
  it("보이는 검색 버튼 없이 돋보기 내장 입력 하나만 둔다", () => {
    renderControls({ query: "서쪽" });
    expect(searchbox().placeholder).toBe("현장명 또는 ID");
    expect(searchbox().value).toBe("서쪽");
    expect(screen.queryByRole("button", { name: "검색" })).toBeNull();
    expect(sortSelect()).toBeTruthy();
  });

  it("검색과 정렬이 같은 높이 체계를 쓴다", () => {
    renderControls();
    for (const element of [searchbox(), sortSelect()]) {
      expect(element.classList.contains("input")).toBe(true);
      expect(element.classList.contains("tap-target")).toBe(true);
      expect(element.className).not.toMatch(/h-11/);
    }
    expect(searchbox().className).not.toContain("h-11");
  });

  it("자동 입력은 디바운스로 replace 하고 히스토리를 쌓지 않는다", () => {
    vi.useFakeTimers();
    setLocation("/sites?group=attention&status=UNMAPPED&sort=attention");
    renderControls({ sort: "attention", group: "attention", status: "UNMAPPED" });
    fireEvent.change(searchbox(), { target: { value: "서" } });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(mocked.replace).toHaveBeenCalledTimes(1);
    expect(mocked.push).not.toHaveBeenCalled();
    const params = hrefParams(mocked.replace.mock.calls[0][0]);
    expect(params.get("q")).toBe("서쪽");
    expect(params.get("group")).toBe("attention");
    expect(params.get("status")).toBe("UNMAPPED");
    expect(params.get("sort")).toBe("attention");
  });

  it("입력 중 필터를 먼저 누르면 늦은 타이머가 옛 조건으로 되돌리지 않는다", () => {
    vi.useFakeTimers();
    setLocation("/sites?group=attention&sort=attention");
    renderControls({ sort: "attention", group: "attention" });
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    // 칩 클릭 상당: 주소창이 먼저 새 묶음으로 간다(서버 응답 전).
    setLocation("/sites?group=patrol&sort=attention");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("주소창이 늦어도 기준 클릭 의도가 먼저 오면 대기 타이머를 버린다", () => {
    vi.useFakeTimers();
    setLocation("/sites?group=attention&sort=attention");
    renderControls({ sort: "attention", group: "attention" });
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    // 느린 RSC: 주소창은 그대로인데 칩 클릭 의도만 먼저 온다.
    act(() => {
      window.dispatchEvent(new Event(SITE_LIST_CANCEL_EVENT));
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("포커스 중 뒤로가기는 URL 기준으로 초안을 되돌리고 대기를 취소한다", () => {
    vi.useFakeTimers();
    setLocation("/sites?q=%EC%84%9C%EC%AA%BD&sort=attention");
    render(
      <SiteListControls query="서쪽" sort="attention" hasFilter visibleCount={1} totalCount={1} />,
    );
    searchbox().focus();
    fireEvent.change(searchbox(), { target: { value: "서쪽x" } });
    // q만 바뀌는 뒤로가기: 주소창이 먼저 가고 응답은 뒤에 온다.
    setLocation("/sites?q=%EB%8F%99%EC%AA%BD&sort=attention");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(searchbox().value).toBe("동쪽");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("포커스 중에는 우리 옛 응답이 새 타이핑을 덮지 않는다", () => {
    vi.useFakeTimers();
    setLocation("/sites?sort=attention");
    const { rerender } = render(
      <SiteListControls query="" sort="attention" hasFilter={false} visibleCount={3} totalCount={5} />,
    );
    searchbox().focus();
    fireEvent.change(searchbox(), { target: { value: "x" } });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(mocked.replace).toHaveBeenCalledTimes(1);
    setLocation("/sites?q=x&sort=attention");
    fireEvent.change(searchbox(), { target: { value: "xy" } });
    // 커밋 전 상태의 늦은 응답 상당 — 입력 중이면 무시한다.
    rerender(<SiteListControls query="" sort="attention" hasFilter={false} visibleCount={3} totalCount={5} />);
    expect(searchbox().value).toBe("xy");
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(mocked.replace).toHaveBeenCalledTimes(2);
    expect(hrefParams(mocked.replace.mock.calls[1][0]).get("q")).toBe("xy");
  });

  it("정렬을 바꿔도 셀렉트 포커스가 남는다", () => {
    const { rerender } = renderControls({ sort: "attention" });
    sortSelect().focus();
    fireEvent.change(sortSelect(), { target: { value: "name" } });
    expect(document.activeElement).toBe(sortSelect());
    // 정렬 응답 상당 — 리마운트 없이 값만 따라간다.
    rerender(<SiteListControls sort="name" hasFilter={false} visibleCount={3} totalCount={5} />);
    expect(document.activeElement).toBe(sortSelect());
    expect(sortSelect().value).toBe("name");
  });

  it("지우개는 좁은 폭·손가락 환경에서 44를 지키고 없을 때 자리를 차지하지 않는다", () => {
    const { unmount } = renderControls({ query: "서쪽" });
    const clear = screen.getByRole("button", { name: "검색어 지우기" });
    expect(clear.className).toContain("max-lg:size-11");
    expect(clear.className).toContain("pointer-coarse:size-11");
    expect(searchbox().className).toContain("pr-11");
    expect(searchbox().className).toContain("site-list-search");
    expect(document.querySelector("style")?.textContent).toContain("::-webkit-search-cancel-button");
    unmount();
    cleanup();
    renderControls();
    expect(screen.queryByRole("button", { name: "검색어 지우기" })).toBeNull();
    expect(searchbox().className).toContain("pr-3");
    expect(searchbox().className).not.toContain("pr-11");
  });

  it("기준이 바뀌면 같은 검색어라도 확정값으로 되돌리고 대기를 버린다", () => {
    vi.useFakeTimers();
    setLocation("/sites?q=%EC%84%9C%EC%AA%BD&group=attention&sort=attention");
    const { rerender } = render(
      <SiteListControls query="서쪽" sort="attention" group="attention" hasFilter visibleCount={1} totalCount={5} />,
    );
    searchbox().focus();
    fireEvent.change(searchbox(), { target: { value: "서쪽x" } });
    // 칩 클릭 상당: 취소 의도 뒤 같은 q·새 묶음 응답이 온다.
    act(() => {
      window.dispatchEvent(new Event(SITE_LIST_CANCEL_EVENT));
    });
    rerender(
      <SiteListControls query="서쪽" sort="attention" group="patrol" hasFilter visibleCount={1} totalCount={5} />,
    );
    expect(searchbox().value).toBe("서쪽");
    expect(screen.getByRole("status").textContent).toBe("");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("q만 바뀌는 응답은 패널의 미적용 선택을 유지한다", () => {
    const { rerender } = render(
      <SiteListControls query="서쪽" sort="attention" group="attention" hasFilter visibleCount={1} totalCount={5} />,
    );
    fireEvent.change(phoneGroupSelect(), { target: { value: "patrol" } });
    fireEvent.change(searchbox(), { target: { value: "서쪽x" } });
    rerender(
      <SiteListControls query="서쪽" sort="attention" group="attention" hasFilter visibleCount={1} totalCount={5} />,
    );
    expect(phoneGroupSelect().value).toBe("patrol");
    expect(searchbox().value).toBe("서쪽x");
  });

  it("폰 초기화는 타이머와 미확정 검색어를 함께 비운다", () => {
    vi.useFakeTimers();
    setLocation("/sites");
    renderControls({ sort: "attention", hasFilter: false, visibleCount: 0, totalCount: 4 });
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    fireEvent.click(within(phoneForm()).getByRole("link", { name: "초기화" }));
    expect(searchbox().value).toBe("");
    expect(screen.getByRole("status").textContent).toBe("");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("빈 상태 초기화 클릭 의도도 대기 타이머를 버린다", () => {
    vi.useFakeTimers();
    setLocation("/sites?q=%EC%84%9C%EC%AA%BD&sort=attention");
    render(
      <>
        <SiteListControls query="서쪽" sort="attention" hasFilter visibleCount={1} totalCount={1} />
        <SiteListCancelBoundary>
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a
            href="/sites"
            onClick={(event) => event.preventDefault()}
          >
            필터 초기화
          </a>
        </SiteListCancelBoundary>
      </>,
    );
    // q만 있는 빈 상태에서 새 초안을 타이핑하다 초기화를 누른다 — 응답 전이다.
    fireEvent.change(searchbox(), { target: { value: "서쪽x" } });
    fireEvent.click(screen.getByRole("link", { name: "필터 초기화" }));
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("기준 링크 클릭은 대기 취소 의도를 알린다", () => {
    const seen: string[] = [];
    function record(event: Event) {
      seen.push(event.type);
    }
    window.addEventListener(SITE_LIST_CANCEL_EVENT, record);
    try {
      render(<SiteListNavLink href="/sites?group=patrol">확인 필요</SiteListNavLink>);
      fireEvent.click(screen.getByRole("link", { name: "확인 필요" }));
      expect(seen).toEqual([SITE_LIST_CANCEL_EVENT]);
    } finally {
      window.removeEventListener(SITE_LIST_CANCEL_EVENT, record);
    }
  });

  it("같은 검색어로는 이동하지 않는다", () => {
    vi.useFakeTimers();
    renderControls({ query: "서쪽" });
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    fireEvent.submit(searchbox().closest("form")!);
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("ENTER는 즉시 push 한다", () => {
    vi.useFakeTimers();
    renderControls({ query: "서", sort: "updated" });
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    fireEvent.submit(searchbox().closest("form")!);
    expect(mocked.push).toHaveBeenCalledTimes(1);
    const params = hrefParams(mocked.push.mock.calls[0][0]);
    expect(params.get("q")).toBe("서쪽");
    expect(params.get("sort")).toBe("updated");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    // 제출이 타이머를 취소했으므로 뒤늦은 replace 가 없다.
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).toHaveBeenCalledTimes(1);
  });

  it("IME 조합 중 ENTER 제출도 확정하지 않는다", () => {
    vi.useFakeTimers();
    renderControls();
    fireEvent.compositionStart(searchbox());
    fireEvent.change(searchbox(), { target: { value: "서" } });
    fireEvent.submit(searchbox().closest("form")!);
    expect(mocked.push).not.toHaveBeenCalled();
    expect(mocked.replace).not.toHaveBeenCalled();
    fireEvent.compositionEnd(searchbox());
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(mocked.replace).toHaveBeenCalledTimes(1);
  });

  it("정렬을 바꾸면 입력 중 초안까지 함께 push 한다", () => {
    vi.useFakeTimers();
    renderControls({ query: "", sort: "attention", group: "attention", status: "UNMAPPED" });
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    fireEvent.change(sortSelect(), { target: { value: "name" } });
    expect(mocked.push).toHaveBeenCalledTimes(1);
    const params = hrefParams(mocked.push.mock.calls[0][0]);
    expect(params.get("q")).toBe("서쪽");
    expect(params.get("sort")).toBe("name");
    expect(params.get("group")).toBe("attention");
    expect(params.get("status")).toBe("UNMAPPED");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    // 정렬이 타이머를 대신했으므로 뒤늦은 replace 가 없다.
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).toHaveBeenCalledTimes(1);
  });

  it("in-flight 응답 같은 props 로는 타이핑을 덮지 않는다", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <SiteListControls query="서쪽" sort="attention" hasFilter visibleCount={1} totalCount={1} />,
    );
    fireEvent.change(searchbox(), { target: { value: "서쪽x" } });
    rerender(<SiteListControls query="서쪽" sort="attention" hasFilter visibleCount={1} totalCount={1} />);
    expect(searchbox().value).toBe("서쪽x");
  });

  it("뒤로·앞으로·공유로 URL이 바뀌면 초안을 따라간다", () => {
    const { rerender } = render(
      <SiteListControls query="서쪽" sort="attention" hasFilter visibleCount={1} totalCount={1} />,
    );
    rerender(<SiteListControls query="동쪽" sort="updated" hasFilter visibleCount={1} totalCount={1} />);
    expect(searchbox().value).toBe("동쪽");
    expect(sortSelect().value).toBe("updated");
  });

  it("검색어 지우기는 q만 되돌리고 포커스를 돌린다", () => {
    renderControls({ query: "서쪽", sort: "name", group: "attention", hasFilter: true });
    fireEvent.click(screen.getByRole("button", { name: "검색어 지우기" }));
    expect(mocked.push).toHaveBeenCalledTimes(1);
    const params = hrefParams(mocked.push.mock.calls[0][0]);
    expect(params.get("q")).toBeNull();
    expect(params.get("sort")).toBe("name");
    expect(params.get("group")).toBe("attention");
    expect(searchbox().value).toBe("");
    expect(document.activeElement).toBe(searchbox());
  });

  it("초기화는 전체 조건을 되돌리고 조건이 없으면 보이지 않는다", () => {
    const { unmount } = renderControls({ query: "서쪽", hasFilter: true });
    expect(within(searchForm()).getByRole("link", { name: "초기화" }).getAttribute("href")).toBe("/sites");
    unmount();
    renderControls();
    // 바깥(데스크톱) 초기화는 조건이 없으면 없고, 폰 패널 초기화는 상시 있다.
    expect(within(searchForm()).queryByRole("link", { name: "초기화" })).toBeNull();
    expect(within(phoneForm()).getByRole("link", { name: "초기화" })).toBeTruthy();
  });

  it("독립 초기화는 데스크톱에서만 보인다 — 좁은 폭은 서랍 초기화가 맡는다", () => {
    renderControls({ query: "서쪽", hasFilter: true });
    const reset = within(searchForm()).getByRole("link", { name: "초기화" });
    expect(reset.className).toContain("hidden");
    expect(reset.className).toContain("lg:inline-flex");
    expect(reset.className).toContain("tap-target");
  });

  it("JS 없이도 GET 폼으로 같은 조건을 보낸다", () => {
    renderControls({ query: "서쪽", sort: "name", group: "attention", status: "UNMAPPED" });
    const form = searchbox().closest("form")!;
    expect(form.getAttribute("action")).toBe("/sites");
    expect(form.getAttribute("method")).toBe("get");
    const data = Object.fromEntries(new FormData(form));
    expect(data).toEqual({ q: "서쪽", group: "attention", status: "UNMAPPED", sort: "name" });
  });

  it("조건이 없으면 빈 숨은 조건을 추가하지 않는다", () => {
    renderControls({ sort: "updated" });
    const form = searchbox().closest("form")!;
    expect(form.querySelector("input[name='group']")).toBeNull();
    expect(form.querySelector("input[name='status']")).toBeNull();
    expect(Object.fromEntries(new FormData(form))).toEqual({ q: "", sort: "updated" });
  });

  it("초기화·뒤로가기로 URL 정렬이 바뀌면 선택 표시도 같은 값으로 복원한다", () => {
    const { rerender } = renderControls({ sort: "name" });
    rerender(
      <SiteListControls sort="attention" hasFilter={false} visibleCount={3} totalCount={5} />,
    );
    expect(sortSelect().value).toBe("attention");
  });

  it("디바운스 대기 중에는 sr 상태로 알린다", () => {
    vi.useFakeTimers();
    renderControls();
    expect(screen.getByRole("status").textContent).toBe("");
    fireEvent.change(searchbox(), { target: { value: "서" } });
    expect(screen.getByRole("status").textContent).toContain("검색어 적용 중");
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getByRole("status").textContent).toBe("");
  });
});

describe("SiteListControls phone panel", () => {
  it("건수 행과 필터·정렬 여닫이를 두고 바깥 정렬은 폰에서 숨긴다", () => {
    const { container } = renderControls({ visibleCount: 1, totalCount: 4 });
    expect(screen.getByText("필터·정렬")).toBeTruthy();
    expect(screen.getByText("1 / 4곳 표시")).toBeTruthy();
    const outerSort = sortSelect().closest("div")!;
    expect(outerSort.className).toContain("hidden");
    expect(outerSort.className).toContain("sm:block");
    expect(container.querySelector("details")?.className).toContain("sm:hidden");
  });

  it("적용은 선택한 묶음·정렬과 최신 초안을 함께 확정한다", () => {
    vi.useFakeTimers();
    setLocation("/sites?group=attention&sort=attention");
    renderControls({ query: "서", group: "attention", sort: "attention", visibleCount: 2, totalCount: 5 });
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    fireEvent.change(phoneGroupSelect(), { target: { value: "patrol" } });
    fireEvent.change(phoneSortSelect(), { target: { value: "name" } });
    fireEvent.submit(phoneForm());
    expect(mocked.push).toHaveBeenCalledTimes(1);
    const params = hrefParams(mocked.push.mock.calls[0][0]);
    expect(params.get("q")).toBe("서쪽");
    expect(params.get("group")).toBe("patrol");
    expect(params.get("sort")).toBe("name");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    // 적용이 타이머를 대신했으므로 뒤늦은 replace 가 없다.
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(mocked.push).toHaveBeenCalledTimes(1);
    expect(document.querySelector("details")?.hasAttribute("open")).toBe(false);
    expect(document.activeElement?.textContent).toContain("필터·정렬");
  });

  it("그룹이 바뀌는 적용 후에도 요약 포커스가 남는다", () => {
    vi.useFakeTimers();
    setLocation("/sites?group=attention&sort=attention");
    const { rerender } = render(
      <SiteListControls query="서" sort="attention" group="attention" hasFilter visibleCount={5} totalCount={5} />,
    );
    fireEvent.change(searchbox(), { target: { value: "서쪽" } });
    fireEvent.change(phoneGroupSelect(), { target: { value: "patrol" } });
    fireEvent.change(phoneSortSelect(), { target: { value: "name" } });
    fireEvent.submit(phoneForm());
    expect(mocked.push).toHaveBeenCalledTimes(1);
    const summary = screen.getByText("필터·정렬").closest("summary")!;
    expect(document.activeElement).toBe(summary);
    // 서버 응답 상당: 묶음·정렬 prop 갱신 — 리마운트 없이 같은 요약에 포커스 유지.
    rerender(
      <SiteListControls query="서쪽" sort="name" group="patrol" hasFilter visibleCount={1} totalCount={5} />,
    );
    expect(document.activeElement).toBe(summary);
    expect(phoneGroupSelect().value).toBe("patrol");
    expect(phoneSortSelect().value).toBe("name");
    expect(searchbox().value).toBe("서쪽");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocked.push).toHaveBeenCalledTimes(1);
  });

  it("IME 조합 중 폰 적용도 확정하지 않는다", () => {
    vi.useFakeTimers();
    setLocation("/sites?group=attention&sort=attention");
    renderControls({ group: "attention", sort: "attention" });
    fireEvent.compositionStart(searchbox());
    fireEvent.change(searchbox(), { target: { value: "서" } });
    fireEvent.change(phoneGroupSelect(), { target: { value: "patrol" } });
    fireEvent.submit(phoneForm());
    expect(mocked.push).not.toHaveBeenCalled();
    expect(mocked.replace).not.toHaveBeenCalled();
    expect(document.querySelector("details")?.hasAttribute("open")).toBe(false);
    fireEvent.compositionEnd(searchbox());
    act(() => {
      vi.advanceTimersByTime(300);
    });
    // 조합 확정분은 검색만 예약대로 가고, 미적용 묶음 선택은 그대로 둔다.
    expect(mocked.replace).toHaveBeenCalledTimes(1);
    expect(hrefParams(mocked.replace.mock.calls[0][0]).get("q")).toBe("서");
    expect(phoneGroupSelect().value).toBe("patrol");
  });

  it("적용 없이 닫으면 미확정 선택을 버린다", () => {
    renderControls({ group: "attention", sort: "attention" });
    const details = document.querySelector("details") as HTMLDetailsElement;
    fireEvent.click(screen.getByText("필터·정렬"));
    expect(details.open).toBe(true);
    fireEvent.change(phoneGroupSelect(), { target: { value: "patrol" } });
    fireEvent.change(phoneSortSelect(), { target: { value: "name" } });
    fireEvent.click(screen.getByText("필터·정렬"));
    expect(details.open).toBe(false);
    // jsdom 의 toggle 은 비동기로 올 수 있어 직접 한 번 더 알린다 — 멱등하다.
    act(() => {
      details.dispatchEvent(new Event("toggle", { bubbles: true }));
    });
    expect(phoneGroupSelect().value).toBe("attention");
    expect(phoneSortSelect().value).toBe("attention");
  });

  it("뒤로가기는 포커스 중에도 패널 조건을 복원한다", () => {
    const { rerender } = render(
      <SiteListControls query="" sort="attention" group="attention" hasFilter={false} visibleCount={3} totalCount={5} />,
    );
    searchbox().focus();
    fireEvent.change(phoneGroupSelect(), { target: { value: "patrol" } });
    rerender(
      <SiteListControls query="" sort="updated" group="patrol" hasFilter visibleCount={2} totalCount={5} />,
    );
    expect(phoneGroupSelect().value).toBe("patrol");
    expect(phoneSortSelect().value).toBe("updated");
    expect(document.activeElement).toBe(searchbox());
  });

  it("패널 초기화는 전체를 되돌리고 패널을 닫는다", () => {
    vi.useFakeTimers();
    setLocation("/sites?group=patrol&q=%EC%84%9C%EC%AA%BD&sort=name");
    renderControls({ query: "서쪽", group: "patrol", sort: "name", hasFilter: true, visibleCount: 0, totalCount: 4 });
    fireEvent.change(searchbox(), { target: { value: "서쪽x" } });
    const details = document.querySelector("details") as HTMLDetailsElement;
    details.open = true;
    fireEvent.change(phoneGroupSelect(), { target: { value: "attention" } });
    fireEvent.click(within(phoneForm()).getByRole("link", { name: "초기화" }));
    expect(details.hasAttribute("open")).toBe(false);
    expect(phoneGroupSelect().value).toBe("all");
    expect(phoneSortSelect().value).toBe("attention");
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocked.replace).not.toHaveBeenCalled();
  });
});

describe("SiteListVisual", () => {
  it("실측처럼 보이지 않는 기본 표시와 짧은 표식만 둔다", () => {
    render(<SiteListVisual siteId="site-1" />);
    expect(screen.getByText("기본 이미지")).toBeTruthy();
    const root = screen.getByText("기본 이미지").closest("div")!;
    expect(root.getAttribute("aria-hidden")).toBe("true");
    // 장식 svg 하나뿐 — img·지도 요소·측정 도형이 없다.
    expect(root.querySelector("img")).toBeNull();
    expect(root.querySelector("polygon,polyline,image,circle")).toBeNull();
    expect(root.querySelector("svg")).toBeTruthy();
  });

  it("같은 현장은 늘 같은 모양이다", () => {
    const first = render(<SiteListVisual siteId="site-7" />);
    const firstHtml = document.body.innerHTML;
    first.unmount();
    cleanup();
    render(<SiteListVisual siteId="site-7" />);
    expect(document.body.innerHTML).toBe(firstHtml);
    expect(first).toBeTruthy();
  });

  it("크기는 호출부가 정한다", () => {
    const { container } = render(<SiteListVisual siteId="site-7" className="h-16 w-20" />);
    expect(container.firstElementChild?.className).toContain("h-16 w-20");
  });
});

const PAGE = readFileSync(join(process.cwd(), "src/app/sites/page.tsx"), "utf8");
const CONTROLS = readFileSync(join(process.cwd(), "src/components/site/SiteListControls.tsx"), "utf8");

describe("sites page wiring", () => {
  it("검색·정렬을 새 컨트롤 하나로 묶고 옛 정렬 폼을 남기지 않는다", () => {
    expect(PAGE).toContain("SiteListControls");
    expect(PAGE).not.toContain("SiteListSort");
  });

  it("기준 칩은 클릭 의도를 먼저 알리고 컨트롤을 리마운트하지 않는다", () => {
    expect(PAGE).toContain("SiteListNavLink");
    expect(PAGE).toContain("SiteListCancelBoundary");
    expect(PAGE).not.toContain("controls:${group}");
  });

  it("서랍 초기화도 기준 링크로 대기 타이머를 취소한다", () => {
    expect(PAGE).toContain('<SiteListNavLink href="/sites"');
  });

  it("머리말과 썸네일 주석이 실제 동작·경로를 말한다", () => {
    expect(PAGE).toContain("300ms 디바운스");
    expect(PAGE).toContain("목록용 미리보기 경로가 없으므로");
    expect(PAGE).not.toContain("검색만 제출하며");
    expect(PAGE).not.toContain("실측 이미지가 없으므로");
  });

  it("폰 구조는 검색→건수·필터 행→썸네일 없는 카드다", () => {
    expect(PAGE).toContain('visibleCount={visibleSites.length}');
    expect(PAGE).toContain('totalCount={sites.length}');
    expect(PAGE).toMatch(/<details className="[^"]*sm:block lg:hidden"/);
    expect(CONTROLS).toContain('className="mt-2 sm:hidden"');
    expect(PAGE).toContain('className="hidden items-baseline gap-2 px-1 sm:flex"');
    expect(PAGE).toContain('className="mt-0.5 hidden h-16 w-20 sm:block sm:h-[72px] sm:w-24"');
  });

  it("보이는 검색 버튼을 두지 않는다", () => {
    expect(PAGE).not.toContain(">검색</button>");
  });

  it("작은 기본 표시는 모바일·태블릿 카드에만 둔다", () => {
    const cardStart = PAGE.indexOf("<li key={site.siteId}");
    const cardEnd = PAGE.indexOf("</li>", cardStart);
    const card = PAGE.slice(cardStart, cardEnd);
    expect(card).toContain("SiteListVisual");
    expect(card.match(/현장 열기/g)).toHaveLength(1);
    // 데스크톱은 갤러리 표지(SiteListDesktopCards) 또는 썸네일 없는 밀도표다.
    expect(PAGE).toContain("SiteListDesktopCards");
    expect(PAGE).toContain("SiteListDenseList");
  });

  it("가짜 현장 이미지를 약속하지 않는다", () => {
    expect(PAGE).not.toContain("<img");
    expect(PAGE).not.toContain("next/image");
  });
});
