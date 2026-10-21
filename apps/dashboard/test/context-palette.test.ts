/** @vitest-environment jsdom */
import { createElement as h } from "react";
import { act } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { contextPaletteItems } from "@/components/console/context-palette";
import { filterPaletteItems, type PaletteItem } from "@/components/console/palette-items";

const items = [{ key: "site:one", label: "남측 현장", group: "현장", href: "/sites/site-1", keywords: "opaque-source-1", hint: "현장 자료와 작업 보기" }];

describe("current Site task vocabulary", () => {
  it("offers human tasks only for a known authorized Site, not a pathname guess", () => {
    expect(contextPaletteItems(items, "/sites/site-1").map((i) => i.label)).toEqual([
      "공간자료",
      "등록 자료",
      "분석 기록·검토",
      "현장 작업",
      "현장 설정",
      "구역 자료 준비",
    ]);
    const hrefs = contextPaletteItems(items, "/sites/site-1/analysis").map((i) => i.href);
    expect(hrefs).toContain("/sites/site-1/analysis");
    expect(hrefs).toContain("/sites/site-1?section=manage");
    expect(contextPaletteItems(items, "/sites/site-10")).toEqual([]);
    expect(contextPaletteItems([], "/sites/site-1")).toEqual([]);
    expect(contextPaletteItems(items, "/")).toEqual([]);
  });
  it("finds operator words and original identities without printing them as a hint", () => {
    expect(filterPaletteItems(contextPaletteItems(items, "/sites/site-1"), "사진")[0].label).toBe("등록 자료");
    expect(filterPaletteItems(items, "opaque-source-1")).toEqual(items);
    expect(items[0].hint).not.toContain("opaque-source-1");
  });

  it("carries only allowlisted browse scope and never forwards arbitrary queries", () => {
    const scoped = contextPaletteItems(items, "/sites/site-1", "?workAreaId=wa-a&assetRef=ksa-v1-" + "b".repeat(64));
    const hrefs = new Map(scoped.map((item) => [item.label, item.href]));
    // 헤더 메뉴와 같은 목적지·같은 범위다. 현황으로 돌아가도 관측을 잃지 않는다.
    expect(hrefs.get("공간자료")).toBe("/sites/site-1?workAreaId=wa-a&assetRef=ksa-v1-" + "b".repeat(64));
    expect(hrefs.get("등록 자료")).toBe("/sites/site-1/spatial-assets?workAreaId=wa-a&assetRef=ksa-v1-" + "b".repeat(64));
    // 분석 기록의 assetRef는 복귀용 항해 맥락일 뿐 선택자가 아니다.
    expect(hrefs.get("분석 기록·검토")).toBe("/sites/site-1/analysis?workAreaId=wa-a&assetRef=ksa-v1-" + "b".repeat(64));
  });

  it("fails closed on malformed or foreign scope instead of echoing it", () => {
    for (const search of [
      "?workAreaId=wa-a&assetRef=not-a-ref",
      "?workAreaId=wa-a&assetRef=ksa-v1-short",
      "?workAreaId=&assetRef=ksa-v1-" + "b".repeat(64),
      "?workAreaId=wa-a&workAreaId=wa-b",
      "?analysisId=a1&currentWorkOrderId=w1",
      "?workAreaId=" + "x".repeat(201),
    ]) {
      const hrefs = contextPaletteItems(items, "/sites/site-1", search).map((item) => item.href);
      expect(hrefs.every((href) => !href.includes("assetRef"))).toBe(true);
      expect(hrefs.every((href) => !href.includes("analysisId") && !href.includes("currentWorkOrderId"))).toBe(true);
      expect(hrefs.every((href) => !href.includes("x".repeat(201)))).toBe(true);
    }
    // 구역 없는 단독 참조는 버린다.
    const hrefs = contextPaletteItems(items, "/sites/site-1", "?assetRef=ksa-v1-" + "b".repeat(64)).map((item) => item.href);
    expect(hrefs.every((href) => !href.includes("assetRef"))).toBe(true);
  });

  it("drops unknown scope without touching the frozen result inputs", () => {
    // 모르는 구역도 조용히 다른 구역으로 바꾸지 않는다 — 목적지만 간다.
    const hrefs = contextPaletteItems(items, "/sites/site-1", "?workAreaId=ghost-area").map((item) => item.href);
    expect(hrefs).toContain("/sites/site-1?workAreaId=ghost-area");
  });
});

// 아래는 렌더 회귀 — 순수 판정 위 describe 와 달리 모달 동작(포커스·키보드·배경 잠금)을
// 본다. next/navigation 은 목으로, scrollIntoView 는 jsdom 에 없어 스텁한다.
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/sites/site-1",
}));

import { CommandPalette, PALETTE_OPEN_EVENT } from "@/components/console/CommandPalette";
import { TopBarSearchTrigger } from "@/components/nav/TopBarSearchTrigger";

const paletteItems: PaletteItem[] = [
  { key: "site:one", label: "남측 현장", group: "현장", href: "/sites/site-1", keywords: "opaque-source-1", hint: "현장 자료와 작업 보기" },
  { key: "screen:sites", label: "현장 목록", group: "화면", href: "/sites" },
];

function openPalette() {
  act(() => {
    window.dispatchEvent(new CustomEvent(PALETTE_OPEN_EVENT));
  });
}

describe("palette modal interaction", () => {
  afterEach(() => {
    cleanup();
    push.mockClear();
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "";
  });

  it("opens via the palette event and focuses the search field with its labels intact", () => {
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    render(h(CommandPalette, { items: paletteItems }));
    expect(screen.queryByRole("dialog")).toBeNull();
    openPalette();
    expect(screen.getByRole("dialog", { name: "검색 및 이동" })).toBeTruthy();
    const input = screen.getByLabelText("화면 또는 현장 검색");
    expect(input.getAttribute("placeholder")).toBe("화면 · 현장 검색");
    expect(document.activeElement).toBe(input);
    expect(input.getAttribute("role")).toBe("combobox");
    const listbox = document.getElementById(input.getAttribute("aria-controls") ?? "");
    expect(listbox?.getAttribute("role")).toBe("listbox");
    // 첫 항목이 가리켜지고 입력창이 그 id 를 가리킨다.
    const options = screen.getAllByRole("option");
    expect(options.length).toBeGreaterThan(0);
    expect(input.getAttribute("aria-activedescendant")).toBe(options[0].id);
    expect(options[0].getAttribute("aria-selected")).toBe("true");
  });

  it("traps Tab and Shift+Tab between input and close button", () => {
    render(h(CommandPalette, { items: paletteItems }));
    openPalette();
    const input = screen.getByLabelText("화면 또는 현장 검색");
    const close = screen.getByRole("button", { name: "팔레트 닫기" });
    // jsdom 은 Tab 기본 이동을 구현하지 않으므로 핸들러가 직접 움직이는
    // 경계(막→처음, 처음→막 Shift)만 단언한다. 중간 이동은 브라우저 기본 동작이다.
    close.focus();
    fireEvent.keyDown(close, { key: "Tab" });
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(close);
  });

  it("recovers pointer focus on a result button instead of leaking to the background", () => {
    render(
      h(
        "div",
        null,
        h("button", { type: "button" }, "배경 버튼"),
        h(CommandPalette, { items: paletteItems }),
      ),
    );
    openPalette();
    const options = screen.getAllByRole("option");
    options[1].focus();
    expect(document.activeElement).toBe(options[1]);
    // Tab 정지가 아닌 곳에서 Tab 을 치면 첫 정지로 회수하고 기본 이동을 막는다.
    const prevented = !fireEvent.keyDown(options[1], { key: "Tab" });
    expect(prevented).toBe(true);
    expect(document.activeElement).toBe(screen.getByLabelText("화면 또는 현장 검색"));
  });

  it("locks background siblings inert and scroll while open, restores both on Escape with focus", () => {
    render(
      h(
        "div",
        null,
        h("main", { id: "main-content" }, h("button", { type: "button" }, "열기 트리거")),
        h(CommandPalette, { items: paletteItems }),
      ),
    );
    const trigger = screen.getByRole("button", { name: "열기 트리거" });
    trigger.focus();
    const main = document.getElementById("main-content") as HTMLElement;
    const inertBefore = main.inert;
    openPalette();
    expect(main.inert).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(screen.getByLabelText("화면 또는 현장 검색"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(main.inert).toBe(inertBefore);
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(trigger);
  });

  it("moves with arrows and routes with Enter", () => {
    render(h(CommandPalette, { items: paletteItems }));
    openPalette();
    const input = screen.getByLabelText("화면 또는 현장 검색");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    // pathname /sites/site-1 의 두 번째 맥락 항목 = 자료.
    expect(push).toHaveBeenCalledWith("/sites/site-1/spatial-assets");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps a valid listbox on empty results and recovers when the query clears", () => {
    render(h(CommandPalette, { items: paletteItems }));
    openPalette();
    const input = screen.getByLabelText("화면 또는 현장 검색");
    fireEvent.change(input, { target: { value: "ㅁㅁㅁㅁㅁ" } });
    expect(screen.getByText("일치하는 화면이나 현장이 없습니다.")).toBeTruthy();
    expect(screen.getByRole("listbox")).toBeTruthy();
    expect(screen.queryByRole("option")).toBeNull();
    expect(document.getElementById(input.getAttribute("aria-controls") ?? "")).toBeTruthy();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getAllByRole("option").length).toBeGreaterThan(0);
  });

  it("opens help with ? and focuses its close button", () => {
    render(h(CommandPalette, { items: paletteItems }));
    fireEvent.keyDown(document.body, { key: "?" });
    expect(screen.getByRole("dialog", { name: "단축키 도움말" })).toBeTruthy();
    const helpClose = screen.getByRole("button", { name: "닫기" });
    expect(document.activeElement).toBe(helpClose);
    fireEvent.click(helpClose);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("mobile opener dispatches the palette event to open the dialog", () => {
    const opener = render(
      h("div", null, h(TopBarSearchTrigger), h(CommandPalette, { items: paletteItems })),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "검색 · 이동" }));
    expect(screen.getByRole("dialog", { name: "검색 및 이동" })).toBeTruthy();
    // lg 미만 전용 래퍼 — 데스크톱 사이드바와 중복 노출되지 않는다.
    expect(opener.container.querySelector(".lg\\:hidden")).toBeTruthy();
    opener.unmount();
  });
});

describe("palette scoped cross-screen round trip", () => {
  const ref = `ksa-v1-${"c".repeat(64)}`;
  afterEach(() => {
    cleanup();
    push.mockClear();
    window.history.replaceState({}, "", "/");
  });

  it("carries the current browse scope into Site destinations and reads nothing new", () => {
    window.history.replaceState({}, "", `/sites/site-1?workAreaId=wa-a&assetRef=${ref}`);
    render(h(CommandPalette, { items: paletteItems }));
    openPalette();
    // 같은 구역·관측으로 Header와 같은 목적지에 간다 — 새 읽기 없이 주소만 싣는다.
    const options = screen.getAllByRole("option");
    const labels = options.map((option) => option.textContent);
    expect(labels.some((text) => text?.includes("공간자료"))).toBe(true);
    const scoped = options.find((option) => option.textContent?.includes("등록 자료"));
    fireEvent.click(scoped!);
    expect(push).toHaveBeenCalledWith(`/sites/site-1/spatial-assets?workAreaId=wa-a&assetRef=${ref}`);
    // 목적지로 이동하면 팔레트는 닫힌다.
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("announces the carried Site scope instead of implying a full index", () => {
    window.history.replaceState({}, "", `/sites/site-1?workAreaId=wa-a&assetRef=${ref}`);
    render(h(CommandPalette, { items: paletteItems }));
    openPalette();
    expect(screen.getByText(/현재 현장 범위를 함께 이동합니다/)).toBeTruthy();
  });

  it("drops a malformed query from destinations instead of echoing it", () => {
    window.history.replaceState({}, "", "/sites/site-1?workAreaId=wa-a&assetRef=bogus");
    render(h(CommandPalette, { items: paletteItems }));
    openPalette();
    const scoped = screen.getAllByRole("option").find((option) => option.textContent?.includes("등록 자료"));
    fireEvent.click(scoped!);
    expect(push).toHaveBeenCalledWith("/sites/site-1/spatial-assets?workAreaId=wa-a");
  });

  it("closes with Escape and returns focus to the trigger", () => {
    render(
      h(
        "div",
        null,
        h("button", { type: "button" }, "열기 트리거"),
        h(CommandPalette, { items: paletteItems }),
      ),
    );
    const trigger = screen.getByRole("button", { name: "열기 트리거" });
    trigger.focus();
    openPalette();
    expect(screen.queryByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
