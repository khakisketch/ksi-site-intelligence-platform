/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const mockedCookies = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/headers", () => ({
  cookies: () =>
    Promise.resolve({
      get: () =>
        mockedCookies.value === undefined ? undefined : { value: mockedCookies.value },
    }),
}));

const mockedSites = vi.hoisted(() => ({ items: [] as unknown[] }));
vi.mock("@/lib/core-api/cached", () => ({
  listSitesCached: () => Promise.resolve(mockedSites.items),
}));
vi.mock("@/lib/core-api/permissions", () => ({
  getSiteRegistrationAvailability: () => Promise.resolve({ status: "denied" }),
  hasAllPermissions: () => Promise.resolve(false),
}));

import { useState } from "react";
import type { SiteView } from "@/lib/core-api/types";

import {
  SITE_LIST_VIEW_COOKIE,
  SITE_LIST_VIEW_DEFAULT,
  parseSiteListView,
  readSiteListViewCookie,
  siteListViewCookieHeader,
  writeSiteListViewCookie,
} from "@/components/site/site-list-view";
import {
  SITE_LIST_CARDS_PER_PAGE,
  SITE_LIST_LIST_PER_PAGE,
  buildSiteListHref,
  clampPage,
  dropSiteListPage,
  normalizePageParam,
  paginateRows,
  pageRangeMeta,
} from "@/components/site/site-list-query";
import { SiteListView } from "@/components/site/SiteListView";
import { SiteListControls } from "@/components/site/SiteListControls";
import { SiteListPager } from "@/components/site/SiteListPager";
import { SiteListCreateTile } from "@/components/site/SiteListCreateTile";
import { SITE_LIST_PAGE_EVENT } from "@/components/site/SiteListNavLink";
import SitesPage from "@/app/sites/page";

function clearViewCookie() {
  document.cookie = `${SITE_LIST_VIEW_COOKIE}=; Max-Age=0`;
}

function setLocation(path: string) {
  window.history.replaceState(null, "", path);
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
  mockedCookies.value = undefined;
  clearViewCookie();
});

function siteFixture(siteId: string, name: string, status: "UNMAPPED" | "PATROL_READY"): SiteView {
  return {
    siteId,
    name,
    status,
    resumeTarget: null,
    aoi: null,
    siteFrame: { crs: "EPSG:5186", verticalDatum: "LOCAL", unit: "meter", transformVersion: "1" },
    registeredAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-10-18T00:00:00Z",
    dataResidency: null,
    aiEgressAllowed: false,
    modelMaxAgeDays: null,
  } as SiteView;
}

describe("site list view preference", () => {
  it("모르는 값·빈 값은 카드 기본값으로 떨어진다", () => {
    expect(SITE_LIST_VIEW_DEFAULT).toBe("cards");
    expect(parseSiteListView("cards")).toBe("cards");
    expect(parseSiteListView("list")).toBe("list");
    expect(parseSiteListView("gallery")).toBe("cards");
    expect(parseSiteListView("")).toBe("cards");
    expect(parseSiteListView(undefined)).toBe("cards");
    expect(parseSiteListView(null)).toBe("cards");
  });

  it("쿠키는 보기 값만 담고 /sites 로 좁히며 장기 보관한다", () => {
    expect(SITE_LIST_VIEW_COOKIE).toBe("ksi-sites-view");
    const plain = siteListViewCookieHeader("list", false);
    expect(plain).toContain("ksi-sites-view=list");
    expect(plain).toContain("Path=/sites");
    expect(plain).toContain("SameSite=Lax");
    expect(plain).toContain("Max-Age=");
    expect(plain).not.toContain("Secure");
    expect(plain).not.toMatch(/siteId|analysisId|token|auth/i);
    expect(siteListViewCookieHeader("cards", true)).toContain("Secure");
  });

  it("저장된 선택을 읽고 깨진 값은 null 로 둔다", () => {
    document.cookie = "ksi-sites-view=list";
    expect(readSiteListViewCookie()).toBe("list");
    document.cookie = "ksi-sites-view=gallery";
    expect(readSiteListViewCookie()).toBe(null);
    clearViewCookie();
    expect(readSiteListViewCookie()).toBe(null);
  });

  it("읽기가 막혀도 기본값으로 떨어진다", () => {
    const throwing = {};
    Object.defineProperty(throwing, "cookie", {
      configurable: true,
      get() {
        throw new Error("denied");
      },
    });
    expect(readSiteListViewCookie(throwing as { cookie: string })).toBe(null);
  });

  it("저장이 막혀도 throw 하지 않는다", () => {
    const setter = vi.spyOn(document, "cookie", "set").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      expect(() => writeSiteListViewCookie("list")).not.toThrow();
    } finally {
      setter.mockRestore();
    }
  });
});

describe("SiteListView", () => {
  function renderView(initialView: "cards" | "list", props?: { initialPage?: number; total?: number; pageSummary?: string }) {
    const page = props?.initialPage ?? 1;
    const summary = props?.pageSummary ?? "3 / 5곳 표시";
    return render(
      <SiteListView
        initialView={initialView}
        toolbar={<input aria-label="도구모음 검색" defaultValue="서쪽" />}
        total={props?.total ?? 5}
        cards={<div>카드판</div>}
        cardsPage={page}
        cardsSummary={summary}
        list={<div>목록판</div>}
        listPage={page}
        listSummary={summary}
      />,
    );
  }

  it("서버 초기값으로 첫 렌더를 맞추고 하나만 보여준다", () => {
    renderView("list");
    expect(screen.getByText("목록판")).toBeTruthy();
    expect(screen.queryByText("카드판")).toBeNull();
    const group = screen.getByRole("group", { name: "현장 보기 방식" });
    expect(within(group).getByRole("button", { name: "카드" }).getAttribute("aria-pressed")).toBe("false");
    expect(within(group).getByRole("button", { name: "목록" }).getAttribute("aria-pressed")).toBe("true");
    const root = document.querySelector('[data-site-list-view="list"]') as HTMLElement;
    expect(root.getAttribute("data-site-page")).toBe("1");
    expect(root.getAttribute("data-site-total")).toBe("5");
  });

  it("전환은 이동·refetch 없이 즉시 바뀌고 포커스는 버튼에 남는다", () => {
    const setter = vi.spyOn(document, "cookie", "set").mockImplementation(() => {});
    try {
      renderView("cards");
      const listButton = screen.getByRole("button", { name: "목록" });
      listButton.focus();
      fireEvent.click(listButton);
      expect(screen.getByText("목록판")).toBeTruthy();
      expect(screen.queryByText("카드판")).toBeNull();
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "목록" }));
      expect(setter).toHaveBeenCalledWith(expect.stringContaining("ksi-sites-view=list"));
      expect(router.replace).not.toHaveBeenCalled();
      expect(router.push).not.toHaveBeenCalled();
    } finally {
      setter.mockRestore();
    }
  });

  it("보기 전환은 대기 검색을 취소하지 않고 page만 떼고 URL을 되돌린다", () => {
    vi.useFakeTimers();
    const setter = vi.spyOn(document, "cookie", "set").mockImplementation(() => {});
    try {
      setLocation("/sites?q=%EC%84%9C%EC%AA%BD&group=attention&sort=attention&page=2");
      render(
        <SiteListView
          initialView="cards"
          toolbar={
            <SiteListControls
              query="서쪽"
              sort="attention"
              group="attention"
              hasFilter
              visibleCount={3}
              totalCount={5}
              className="min-w-0 flex-1"
            />
          }
          total={5}
          cards={<div>카드판</div>}
          cardsPage={2}
          cardsSummary="5–5 / 5곳 표시"
          list={<div>목록판</div>}
          listPage={1}
          listSummary="1–5 / 5곳 표시"
        />,
      );
      const box = screen.getByRole("searchbox", { name: "현장 찾기" }) as HTMLInputElement;
      fireEvent.change(box, { target: { value: "서쪽x" } });
      const listButton = screen.getByRole("button", { name: "목록" });
      listButton.focus();
      fireEvent.click(listButton);
      // 토글은 page 정리 replace 한 번, 초안은 손대지 않는다.
      expect(router.replace).toHaveBeenCalledTimes(1);
      expect(new URL(router.replace.mock.calls[0][0] as string, "http://localhost").searchParams.get("page")).toBeNull();
      expect(box.value).toBe("서쪽x");
      expect(document.activeElement).toBe(listButton);
      act(() => {
        vi.advanceTimersByTime(300);
      });
      // 디바운스가 끝나면 예약된 검색이 확정 검색어로 간다 — 취소되지 않는다.
      expect(router.replace).toHaveBeenCalledTimes(2);
      const committed = new URL(router.replace.mock.calls[1][0] as string, "http://localhost").searchParams;
      expect(committed.get("q")).toBe("서쪽x");
      expect(committed.get("page")).toBeNull();
      expect(setter).toHaveBeenCalledWith(expect.stringContaining("ksi-sites-view=list"));
    } finally {
      setter.mockRestore();
    }
  });

  it("이미 보고 있는 방식을 다시 눌러도 페이지를 되돌리지 않는다", () => {
    vi.useFakeTimers();
    setLocation("/sites?q=%EC%84%9C%EC%AA%BD&group=attention&sort=attention&page=2");
    render(
      <SiteListView
        initialView="cards"
        toolbar={
          <SiteListControls
            query="서쪽"
            sort="attention"
            group="attention"
            hasFilter
            visibleCount={3}
            totalCount={5}
            className="min-w-0 flex-1"
          />
        }
        total={5}
        cards={<div>카드판</div>}
        cardsPage={2}
        cardsSummary="5–5 / 5곳 표시"
        list={<div>목록판</div>}
        listPage={1}
        listSummary="1–5 / 5곳 표시"
      />,
    );
    const box = screen.getByRole("searchbox", { name: "현장 찾기" }) as HTMLInputElement;
    fireEvent.change(box, { target: { value: "서쪽x" } });
    const cardsButton = screen.getByRole("button", { name: "카드" });
    cardsButton.focus();
    fireEvent.click(cardsButton);
    expect(router.replace).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
    expect(box.value).toBe("서쪽x");
    expect(document.activeElement).toBe(cardsButton);
    act(() => {
      vi.advanceTimersByTime(300);
    });
    // 대기 검색은 그대로 확정된다 — 페이지 유지.
    expect(router.replace).toHaveBeenCalledTimes(1);
    expect(new URL(router.replace.mock.calls[0][0] as string, "http://localhost").searchParams.get("q")).toBe("서쪽x");
  });

  it("IME 조합 중 전환해도 확정분은 예약대로 간다", () => {
    vi.useFakeTimers();
    const setter = vi.spyOn(document, "cookie", "set").mockImplementation(() => {});
    try {
      setLocation("/sites?group=attention&sort=attention");
      render(
        <SiteListView
          initialView="cards"
          toolbar={
            <SiteListControls
              query=""
              sort="attention"
              group="attention"
              hasFilter={false}
              visibleCount={3}
              totalCount={5}
              className="min-w-0 flex-1"
            />
          }
          total={5}
          cards={<div>카드판</div>}
          cardsPage={1}
          cardsSummary="1–4 / 5곳 표시"
          list={<div>목록판</div>}
          listPage={1}
          listSummary="1–5 / 5곳 표시"
        />,
      );
      const box = screen.getByRole("searchbox", { name: "현장 찾기" }) as HTMLInputElement;
      fireEvent.compositionStart(box);
      fireEvent.change(box, { target: { value: "서" } });
      fireEvent.click(screen.getByRole("button", { name: "목록" }));
      expect(router.replace).not.toHaveBeenCalled();
      fireEvent.compositionEnd(box);
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(router.replace).toHaveBeenCalledTimes(1);
      expect(new URL(router.replace.mock.calls[0][0] as string, "http://localhost").searchParams.get("q")).toBe("서");
    } finally {
      setter.mockRestore();
    }
  });

  it("페이지 번호 이동은 머리글로 포커스를 옮기고 알린다", () => {
    const { rerender } = render(
      <SiteListView
        initialView="list"
        toolbar={<div />}
        total={5}
        cards={<div>카드판</div>}
        cardsPage={1}
        cardsSummary="1–4 / 5곳 표시"
        list={
          <div>
            <h2>현장 상태</h2>
            <p>목록판</p>
            <SiteListPager page={1} totalPages={2} base={{ sort: "attention" }} />
          </div>
        }
        listPage={1}
        listSummary="1–4 / 5곳 표시"
      />,
    );
    const footer = screen.getByRole("navigation", { name: "현장 페이지" });
    fireEvent.click(within(footer).getByRole("link", { name: "2" }));
    rerender(
      <SiteListView
        initialView="list"
        toolbar={<div />}
        total={5}
        cards={<div>카드판</div>}
        cardsPage={2}
        cardsSummary="5–5 / 5곳 표시"
        list={
          <div>
            <h2>현장 상태</h2>
            <p>목록판</p>
            <SiteListPager page={2} totalPages={2} base={{ sort: "attention" }} />
          </div>
        }
        listPage={2}
        listSummary="5–5 / 5곳 표시"
      />,
    );
    expect(document.activeElement?.textContent).toContain("현장 상태");
    expect(screen.getByRole("status").textContent).toContain("2페이지");
  });

  it("새 탭 열기는 포커스를 옮기지 않는다", () => {
    const { rerender } = render(
      <SiteListView
        initialView="list"
        toolbar={<div />}
        total={5}
        cards={<div>카드판</div>}
        cardsPage={1}
        cardsSummary="1–4 / 5곳 표시"
        list={
          <div>
            <h2>현장 상태</h2>
            <p>목록판</p>
            <SiteListPager page={1} totalPages={2} base={{ sort: "attention" }} />
          </div>
        }
        listPage={1}
        listSummary="1–4 / 5곳 표시"
      />,
    );
    fireEvent.click(screen.getByRole("link", { name: "2" }), { ctrlKey: true });
    expect(router.push).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
    rerender(
      <SiteListView
        initialView="list"
        toolbar={<div />}
        total={5}
        cards={<div>카드판</div>}
        cardsPage={2}
        cardsSummary="5–5 / 5곳 표시"
        list={
          <div>
            <h2>현장 상태</h2>
            <p>목록판</p>
            <SiteListPager page={2} totalPages={2} base={{ sort: "attention" }} />
          </div>
        }
        listPage={2}
        listSummary="5–5 / 5곳 표시"
      />,
    );
    expect(document.activeElement).toBe(document.body);
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("페이지 링크 클릭은 확정 검색어 복귀 의도를 알린다", () => {
    const seen: string[] = [];
    const record = () => {
      seen.push("page");
    };
    window.addEventListener(SITE_LIST_PAGE_EVENT, record);
    try {
      render(<SiteListPager page={1} totalPages={2} base={{ sort: "attention" }} />);
      fireEvent.click(screen.getByRole("link", { name: "2" }));
      expect(seen).toEqual(["page"]);
    } finally {
      window.removeEventListener(SITE_LIST_PAGE_EVENT, record);
    }
  });

  it("새 탭 열기·뒤로가기는 포커스를 빼앗지 않는다", () => {
    const { rerender } = renderView("list", { initialPage: 2, total: 5, pageSummary: "1–4 / 5곳 표시" });
    rerender(
      <SiteListView
        initialView="list"
        toolbar={<div />}
        total={5}
        cards={<div>카드판</div>}
        cardsPage={2}
        cardsSummary="1–4 / 5곳 표시"
        list={<div>목록판</div>}
        listPage={2}
        listSummary="5–5 / 5곳 표시"
      />,
    );
    expect(document.activeElement).toBe(document.body);
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("도구모음 입력 상태는 전환에 리마운트되지 않는다", () => {
    function Harness() {
      const [value, setValue] = useState("서쪽");
      return (
        <SiteListView
          initialView="cards"
          toolbar={<input aria-label="도구모음 검색" value={value} onChange={(event) => setValue(event.target.value)} />}
          total={5}
          cards={<div>카드판</div>}
          cardsPage={1}
          cardsSummary="3 / 5곳 표시"
          list={<div>목록판</div>}
          listPage={1}
          listSummary="3 / 5곳 표시"
        />
      );
    }
    render(<Harness />);
    const input = screen.getByRole("textbox", { name: "도구모음 검색" }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "서쪽x" } });
    fireEvent.click(screen.getByRole("button", { name: "목록" }));
    expect((screen.getByRole("textbox", { name: "도구모음 검색" }) as HTMLInputElement).value).toBe("서쪽x");
  });

  it("마운트 때 살아 있는 쿠키가 props 보다 새로우면 따라간다", () => {
    document.cookie = "ksi-sites-view=list";
    renderView("cards");
    expect(screen.getByText("목록판")).toBeTruthy();
    expect(screen.getByRole("button", { name: "목록" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("깨진 쿠키는 서버 초기값을 유지한다", () => {
    document.cookie = "ksi-sites-view=gallery";
    renderView("cards");
    expect(screen.getByText("카드판")).toBeTruthy();
  });

  it("읽기 차단 마운트도 서버 초기값으로 렌더한다", () => {
    const getter = vi.spyOn(document, "cookie", "get").mockImplementation(() => {
      throw new Error("denied");
    });
    try {
      renderView("cards");
      expect(screen.getByText("카드판")).toBeTruthy();
      expect(screen.queryByText("목록판")).toBeNull();
    } finally {
      getter.mockRestore();
    }
  });
});

const PAGE = readFileSync(join(process.cwd(), "src/app/sites/page.tsx"), "utf8");
const CARDS = readFileSync(join(process.cwd(), "src/components/site/SiteListDesktopCards.tsx"), "utf8");
const DENSE = readFileSync(join(process.cwd(), "src/components/site/SiteListDenseList.tsx"), "utf8");
const VIEW = readFileSync(join(process.cwd(), "src/components/site/SiteListView.tsx"), "utf8");

describe("sites desktop view wiring", () => {
  it("서버가 쿠키로 첫 화면을 정하고 URL 쿼리에 보기를 넣지 않는다", () => {
    expect(PAGE).toContain("readSiteListView");
    expect(PAGE).toContain("initialView={view}");
    expect(PAGE).toContain("searchParams: Promise<{ q?: string; status?: string; sort?: string; group?: string; page?: string }>");
    expect(PAGE).not.toContain("params.view");
    // 두 패널이 각자 모드의 서버 건수를 쓴다 — 갤러리에만 수가 없어선 안 된다.
    expect(PAGE).toContain("meta={cardsMeta}");
    expect(PAGE).toContain("meta={listMeta}");
  });

  it("보기 전환기는 의미 그대로 노출된다", () => {
    expect(VIEW).toContain('aria-label="현장 보기 방식"');
    expect(VIEW).toMatch(/>\s*카드\s*</);
    expect(VIEW).toMatch(/>\s*목록\s*</);
    expect(VIEW).toContain("aria-pressed");
    expect(VIEW).toContain("data-site-list-view={view}");
  });

  it("갤러리 카드는 넓은 타이포 표지에 테스트 훅을 둔다", () => {
    expect(CARDS).toContain("data-site-card");
    expect(CARDS).toContain("data-site-cover");
    expect(CARDS).toContain("기본 표지");
    expect(CARDS).toContain("DefaultSiteVisual");
    expect(CARDS).toContain("line-clamp-3");
    expect(CARDS).toContain("text-[22px]");
    expect(CARDS).toContain("lg:grid-cols-2");
    expect(CARDS).toContain("2xl:grid-cols-3");
    expect(CARDS).toContain("max-w-[920px]");
    expect(CARDS).toContain("2xl:max-w-[1350px]");
    expect(CARDS).not.toContain("mx-auto");
    expect(CARDS).toContain("aspect-[16/7]");
    expect(CARDS).toContain("mt-auto");
    expect(CARDS).toContain("trailing");
    expect(CARDS).toContain("<h2");
    expect(CARDS).toContain("meta: string");
    expect(CARDS.match(/<h3/g) ?? []).toHaveLength(1);
    expect(CARDS).not.toContain("only:col-span");
    expect(CARDS).not.toContain("h-[180px]");
    expect(CARDS).not.toMatch(/위성|항공|실측 이미지|현장 사진|미리보기 없음/);
    expect((CARDS.match(/현장 열기/g) ?? []).length).toBe(1);
  });

  it("밀도표는 썸네일 없이 좁은 열에 든다", () => {
    expect(DENSE).toContain("minmax(180px");
    expect(DENSE).not.toContain("SiteListVisual");
  });

  it("폰·태블릿 목록은 그대로 두고 데스크톱만 보기를 바꾼다", () => {
    expect(PAGE).toContain('className="flex flex-col gap-2 lg:hidden"');
    expect(PAGE).not.toContain("hidden xl:block");
  });
});

describe("sites page initial view", () => {
  function mockSites() {
    mockedSites.items = [
      siteFixture("e2e-1", "첫째 현장", "UNMAPPED"),
      siteFixture("e2e-2", "둘째 현장", "PATROL_READY"),
    ];
  }

  it("쿠키 list 면 밀도표로 시작한다", async () => {
    mockedCookies.value = "list";
    mockSites();
    render(await SitesPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole("heading", { name: "현장 상태" })).toBeTruthy();
    expect(screen.queryByText("기본 표지")).toBeNull();
    expect(screen.getByRole("button", { name: "목록" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("쿠키가 없으면 카드로 시작한다", async () => {
    mockSites();
    render(await SitesPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getAllByText("기본 표지")).toHaveLength(2);
    expect(screen.queryByRole("heading", { name: "현장 상태" })).toBeNull();
    expect(screen.getByRole("button", { name: "카드" }).getAttribute("aria-pressed")).toBe("true");
    const gallery = document.querySelector('[data-site-list-view="cards"]') as HTMLElement;
    expect(within(gallery).getByRole("heading", { name: "현장" })).toBeTruthy();
    expect(within(gallery).getByText("2 / 2곳 표시")).toBeTruthy();
    expect(within(gallery).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "첫째 현장",
      "둘째 현장",
    ]);
  });

  it("깨진 쿠키 값은 카드로 떨어진다", async () => {
    mockedCookies.value = "gallery";
    mockSites();
    render(await SitesPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getAllByText("기본 표지")).toHaveLength(2);
  });

  it("걸린 행이 없으면 목록 모드도 표 없이 빈 상태 하나만 말한다", async () => {
    mockedCookies.value = "list";
    mockSites();
    render(await SitesPage({ searchParams: Promise.resolve({ q: "없는현장" }) }));
    expect(screen.queryByRole("heading", { name: "현장 상태" })).toBeNull();
    expect(screen.getAllByText("조건에 맞는 현장이 없습니다")).toHaveLength(1);
    // 도구모음·전환기는 그대로 쓸 수 있다(반응형 두 벌 중 보이는 쪽).
    expect(screen.getAllByRole("searchbox", { name: "현장 찾기" }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("group", { name: "현장 보기 방식" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "카드" })).toBeTruthy();
  });
});

describe("site list paging math", () => {
  it("페이지 크기는 카드 4·목록 10이다", () => {
    expect(SITE_LIST_CARDS_PER_PAGE).toBe(4);
    expect(SITE_LIST_LIST_PER_PAGE).toBe(10);
  });

  it("page 파라미터는 1 이상 정수로 읽는다", () => {
    expect(normalizePageParam(undefined)).toBe(1);
    expect(normalizePageParam("")).toBe(1);
    expect(normalizePageParam("abc")).toBe(1);
    expect(normalizePageParam("0")).toBe(1);
    expect(normalizePageParam("-3")).toBe(1);
    expect(normalizePageParam("2.7")).toBe(2);
    expect(normalizePageParam("3")).toBe(3);
  });

  it("벗어난 페이지는 끝으로 당긴다", () => {
    expect(clampPage(9, 2)).toBe(2);
    expect(clampPage(0, 3)).toBe(1);
    expect(clampPage(2, 3)).toBe(2);
    expect(clampPage(1, 1)).toBe(1);
  });

  it("해당 페이지 행만 자른다", () => {
    const rows = [1, 2, 3, 4, 5];
    expect(paginateRows(rows, 1, 4)).toEqual([1, 2, 3, 4]);
    expect(paginateRows(rows, 2, 4)).toEqual([5]);
    expect(paginateRows(rows, 3, 4)).toEqual([]);
  });

  it("머리말은 걸린 범위와 전체를 말한다", () => {
    expect(pageRangeMeta(5, 5, 1, 4)).toBe("1–4 / 5곳 표시");
    expect(pageRangeMeta(5, 5, 2, 4)).toBe("5–5 / 5곳 표시");
    expect(pageRangeMeta(5, 5, 1, 10)).toBe("5 / 5곳 표시");
    expect(pageRangeMeta(1, 5, 1, 4)).toBe("1 / 5곳 표시");
    expect(pageRangeMeta(0, 5, 1, 4)).toBe("0 / 5곳 표시");
  });

  it("검색·필터·정렬 이동은 page 를 붙이지 않는다", () => {
    const href = buildSiteListHref({ q: "서쪽", sort: "name", group: "attention" }, { sort: "updated" });
    expect(href).not.toContain("page");
    // page 는 페이지 이동에서만 명시한다. 지우면 1페이지라 파라미터가 없다.
    expect(buildSiteListHref({ q: "서쪽", sort: "name" }, { page: "2" })).toContain("page=2");
    expect(buildSiteListHref({ q: "서쪽", page: "2" }, { page: undefined })).toBe("/sites?q=%EC%84%9C%EC%AA%BD");
    expect(buildSiteListHref({ page: "2" }, { page: undefined })).toBe("/sites");
  });

  it("보기 전환용 page 제거는 현재 검색식을 살린다", () => {
    expect(dropSiteListPage("?q=%EC%84%9C%EC%AA%BD&page=2")).toBe("/sites?q=%EC%84%9C%EC%AA%BD");
    expect(dropSiteListPage("?q=%EC%84%9C%EC%AA%BD")).toBe(null);
    expect(dropSiteListPage("")).toBe(null);
  });
});

describe("SiteListPager", () => {
  const base = { sort: "attention" };

  it("한 페이지면 푸터를 그리지 않는다", () => {
    const { container } = render(<SiteListPager page={1} totalPages={1} base={base} />);
    expect(container.innerHTML).toBe("");
  });

  it("이전·번호·다음을 두고 현재 페이지를 표시한다", () => {
    render(<SiteListPager page={2} totalPages={3} base={base} />);
    const nav = screen.getByRole("navigation", { name: "현장 페이지" });
    expect(within(nav).getByRole("link", { name: "이전" }).getAttribute("href")).not.toContain("page=");
    expect(within(nav).getByRole("link", { name: "다음" }).getAttribute("href")).toContain("page=3");
    expect(within(nav).getByRole("link", { name: "2" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "1" }).getAttribute("href")).not.toContain("page=");
  });

  it("끝 페이지에서는 다음이 실행 불가하고 1페이지는 page 를 뺀다", () => {
    render(<SiteListPager page={3} totalPages={3} base={base} />);
    const nav = screen.getByRole("navigation", { name: "현장 페이지" });
    const next = within(nav).getByText("다음");
    expect(next.tagName).not.toBe("A");
    expect(next.getAttribute("aria-disabled")).toBe("true");
    expect(within(nav).getByRole("link", { name: "1" }).getAttribute("href")).not.toContain("page");
  });

  it("검색·묶음 조건을 유지한 채 페이지만 바꾼다", () => {
    render(
      <SiteListPager
        page={1}
        totalPages={2}
        base={{ q: "서쪽", sort: "name", group: "attention" }}
      />,
    );
    const href = screen.getByRole("link", { name: "2" }).getAttribute("href") ?? "";
    const params = new URL(href, "http://localhost").searchParams;
    expect(params.get("q")).toBe("서쪽");
    expect(params.get("sort")).toBe("name");
    expect(params.get("group")).toBe("attention");
    expect(params.get("page")).toBe("2");
  });
});

describe("SiteListCreateTile", () => {
  it("허용이면 새 현장 링크 타일이다", () => {
    render(<SiteListCreateTile availability={{ status: "allowed", mode: "MAPPED_BOOTSTRAP" }} />);
    const link = screen.getByRole("link", { name: "새 현장 추가" });
    expect(link.getAttribute("href")).toBe("/sites/new");
    expect(link.getAttribute("data-site-create-card")).toBe("new");
  });

  it("거부면 이동 없이 사유만 연다", () => {
    render(<SiteListCreateTile availability={{ status: "denied" }} />);
    expect(screen.queryByRole("link", { name: "새 현장 추가" })).toBeNull();
    const trigger = screen.getByRole("button", { name: "새 현장 추가" });
    expect(trigger.querySelector('[data-site-create-card="new"]')).toBeTruthy();
    fireEvent.click(trigger);
    expect(screen.getByText(/현재 계정으로는 현장을 등록할 수 없습니다/)).toBeTruthy();
    expect(document.querySelector('a[href="/sites/new"]')).toBeNull();
    expect(trigger.textContent).toContain("새 현장 추가");
  });

  it("확인 실패면 재시도와 함께 사유를 연다", () => {
    render(<SiteListCreateTile availability={{ status: "unavailable" }} />);
    fireEvent.click(screen.getByRole("button", { name: "새 현장 추가" }));
    expect(screen.getByText(/확인할 수 없었습니다/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "권한 다시 확인" })).toBeTruthy();
  });

  it("닫으면 트리거로 포커스가 돌아온다", () => {
    render(<SiteListCreateTile availability={{ status: "denied" }} />);
    const trigger = screen.getByRole("button", { name: "새 현장 추가" });
    fireEvent.click(trigger);
    expect(screen.getByText(/현재 계정으로는/)).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText(/현재 계정으로는/)).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("sites desktop pagination", () => {
  const NAMES = ["첫째", "둘째", "셋째", "넷째", "다섯째"];

  function mockFiveSites() {
    mockedSites.items = NAMES.map(
      (name, index) =>
        siteFixture(`e2e-${index + 1}`, `${name} 현장`, index % 2 === 0 ? "UNMAPPED" : "PATROL_READY"),
    );
  }

  function desktopPanel() {
    return document.querySelector('[data-site-list-view="cards"],[data-site-list-view="list"]') as HTMLElement;
  }

  it("카드는 4개씩 끊고 마지막 페이지만 타일을 둔다", async () => {
    mockFiveSites();
    render(await SitesPage({ searchParams: Promise.resolve({ q: "" }) }));
    const panel = desktopPanel();
    expect(within(panel).getAllByText("기본 표지")).toHaveLength(4);
    expect(within(panel).queryByText("새 현장 추가")).toBeNull();
    expect(within(panel).getByText("1–4 / 5곳 표시")).toBeTruthy();
    const pager = screen.getByRole("navigation", { name: "현장 페이지" });
    expect(within(pager).getByRole("link", { name: "2" })).toBeTruthy();
    expect(within(pager).getByRole("link", { name: "1" }).getAttribute("aria-current")).toBe("page");
  });

  it("마지막 카드는 남은 행과 타일을 함께 둔다", async () => {
    mockFiveSites();
    render(await SitesPage({ searchParams: Promise.resolve({ page: "2" }) }));
    const panel = desktopPanel();
    expect(within(panel).getAllByText("기본 표지")).toHaveLength(1);
    expect(within(panel).getByText("새 현장 추가")).toBeTruthy();
    expect(within(panel).getByText("5–5 / 5곳 표시")).toBeTruthy();
    expect(screen.getByRole("link", { name: "2" }).getAttribute("aria-current")).toBe("page");
  });

  it("벗어난 페이지는 끝으로 당긴다", async () => {
    mockFiveSites();
    render(await SitesPage({ searchParams: Promise.resolve({ page: "99" }) }));
    const panel = desktopPanel();
    expect(within(panel).getAllByText("기본 표지")).toHaveLength(1);
    expect(within(panel).getByText("새 현장 추가")).toBeTruthy();
  });

  it("깨진 페이지 값은 1페이지로 떨어진다", async () => {
    mockFiveSites();
    render(await SitesPage({ searchParams: Promise.resolve({ page: "abc" }) }));
    expect(desktopPanel().textContent).toContain("1–4 / 5곳 표시");
  });

  it("목록은 10개씩 끊고 한 페이지면 푸터를 그리지 않는다", async () => {
    mockedCookies.value = "list";
    mockFiveSites();
    render(await SitesPage({ searchParams: Promise.resolve({}) }));
    expect(screen.queryByRole("navigation", { name: "현장 페이지" })).toBeNull();
    const panel = document.querySelector('[data-site-list-view="list"]') as HTMLElement;
    expect(within(panel).getByText("5 / 5곳 표시")).toBeTruthy();
    expect(within(panel).getAllByText("현장 열기")).toHaveLength(5);
  });

  it("카드 빈 결과는 EmptyState 하나만 말한다", async () => {
    mockFiveSites();
    render(await SitesPage({ searchParams: Promise.resolve({ q: "없는현장" }) }));
    expect(screen.queryByText("기본 표지")).toBeNull();
    expect(screen.getAllByText("조건에 맞는 현장이 없습니다")).toHaveLength(1);
    expect(screen.getByRole("group", { name: "현장 보기 방식" })).toBeTruthy();
  });

  it("폰·태블릿 목록은 페이지를 무시하고 전체를 둔다", async () => {
    mockFiveSites();
    render(await SitesPage({ searchParams: Promise.resolve({ page: "2" }) }));
    const mobile = document.querySelector('section[aria-label="현장 목록"]') as HTMLElement;
    expect(within(mobile).getAllByRole("link", { name: "현장 열기" })).toHaveLength(5);
  });
});
