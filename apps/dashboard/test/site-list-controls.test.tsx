/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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
} = {}) {
  return render(
    <SiteListControls
      query={props.query}
      sort={props.sort ?? "attention"}
      group={props.group}
      status={props.status}
      hasFilter={props.hasFilter ?? false}
    />,
  );
}

function searchbox() {
  return screen.getByRole("searchbox", { name: "현장 찾기" }) as HTMLInputElement;
}

function sortSelect() {
  return screen.getByRole("combobox", { name: "정렬 기준" }) as HTMLSelectElement;
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
      <SiteListControls query="서쪽" sort="attention" hasFilter />,
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
      <SiteListControls query="" sort="attention" hasFilter={false} />,
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
    rerender(<SiteListControls query="" sort="attention" hasFilter={false} />);
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
    rerender(<SiteListControls sort="name" hasFilter={false} />);
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

  it("빈 상태 초기화 클릭 의도도 대기 타이머를 버린다", () => {
    vi.useFakeTimers();
    setLocation("/sites?q=%EC%84%9C%EC%AA%BD&sort=attention");
    render(
      <>
        <SiteListControls query="서쪽" sort="attention" hasFilter />
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
      <SiteListControls query="서쪽" sort="attention" hasFilter />,
    );
    fireEvent.change(searchbox(), { target: { value: "서쪽x" } });
    rerender(<SiteListControls query="서쪽" sort="attention" hasFilter />);
    expect(searchbox().value).toBe("서쪽x");
  });

  it("뒤로·앞으로·공유로 URL이 바뀌면 초안을 따라간다", () => {
    const { rerender } = render(
      <SiteListControls query="서쪽" sort="attention" hasFilter />,
    );
    rerender(<SiteListControls query="동쪽" sort="updated" hasFilter />);
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
    expect(screen.getByRole("link", { name: "초기화" }).getAttribute("href")).toBe("/sites");
    unmount();
    renderControls();
    expect(screen.queryByRole("link", { name: "초기화" })).toBeNull();
  });

  it("독립 초기화는 데스크톱에서만 보인다 — 좁은 폭은 서랍 초기화가 맡는다", () => {
    renderControls({ query: "서쪽", hasFilter: true });
    const reset = screen.getByRole("link", { name: "초기화" });
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
      <SiteListControls sort="attention" hasFilter={false} />,
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

describe("sites page wiring", () => {
  it("검색·정렬을 새 컨트롤 하나로 묶고 옛 정렬 폼을 남기지 않는다", () => {
    expect(PAGE).toContain("SiteListControls");
    expect(PAGE).not.toContain("SiteListSort");
  });

  it("기준 칩은 클릭 의도를 먼저 알리고 정렬은 리마운트하지 않는다", () => {
    expect(PAGE).toContain("SiteListNavLink");
    expect(PAGE).toContain("SiteListCancelBoundary");
    expect(PAGE).toContain('key={`controls:${group}:${status ?? "-"}`}');
    expect(PAGE).not.toContain(":${sort}");
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

  it("보이는 검색 버튼을 두지 않는다", () => {
    expect(PAGE).not.toContain(">검색</button>");
  });

  it("카드와 표에 같은 기본 표시를 쓴다", () => {
    const cardStart = PAGE.indexOf("<li key={site.siteId}");
    const cardEnd = PAGE.indexOf("</li>", cardStart);
    const card = PAGE.slice(cardStart, cardEnd);
    expect(card).toContain("SiteListVisual");
    expect(card.match(/현장 열기/g)).toHaveLength(1);
    const tableStart = PAGE.indexOf("<TableRow key={site.siteId} columns={COLUMNS}");
    expect(PAGE.slice(tableStart, tableStart + 2000)).toContain("SiteListVisual");
  });

  it("가짜 현장 이미지를 약속하지 않는다", () => {
    expect(PAGE).not.toContain("<img");
    expect(PAGE).not.toContain("next/image");
  });
});
