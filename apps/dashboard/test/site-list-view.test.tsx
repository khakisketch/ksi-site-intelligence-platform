/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
import { SiteListView } from "@/components/site/SiteListView";
import SitesPage from "@/app/sites/page";

function clearViewCookie() {
  document.cookie = `${SITE_LIST_VIEW_COOKIE}=; Max-Age=0`;
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
  function renderView(initialView: "cards" | "list") {
    return render(
      <SiteListView
        initialView={initialView}
        toolbar={<input aria-label="도구모음 검색" defaultValue="서쪽" />}
        cards={<div>카드판</div>}
        list={<div>목록판</div>}
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
    } finally {
      setter.mockRestore();
    }
  });

  it("도구모음 입력 상태는 전환에 리마운트되지 않는다", () => {
    function Harness() {
      const [value, setValue] = useState("서쪽");
      return (
        <SiteListView
          initialView="cards"
          toolbar={<input aria-label="도구모음 검색" value={value} onChange={(event) => setValue(event.target.value)} />}
          cards={<div>카드판</div>}
          list={<div>목록판</div>}
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
    expect(PAGE).toContain("searchParams: Promise<{ q?: string; status?: string; sort?: string; group?: string }>");
    expect(PAGE).not.toContain("params.view");
    // 두 패널이 같은 서버 건수를 쓴다 — 갤러리에만 수가 없어선 안 된다.
    expect(PAGE.split("meta={`${visibleSites.length} / ${sites.length}곳 표시`}").length - 1).toBe(2);
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
    expect(CARDS).toContain("<h2");
    expect(CARDS).toContain("meta: string");
    expect(CARDS.match(/<h3/g) ?? []).toHaveLength(1);
    expect(CARDS).not.toContain("only:col-span");
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
