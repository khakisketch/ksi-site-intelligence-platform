/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { SiteListProvider } from "@/components/nav/SiteListContext";
import { MobileSiteSwitcher } from "@/components/nav/MobileSiteSwitcher";

beforeAll(() => {
  // jsdom 의 dialog 는 showModal 미지원 — 열림 상태만 흉내낸다.
  // 네이티브 showModal 의 포커스 트랩·inert 자체를 증명하지는 않으며,
  // 여기서는 상태 전이(열림/취소/배경/선택/복원/리사이즈/멤버십) 회귀만 본다.
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function renderSwitcher() {
  return render(
    <SiteListProvider
      sites={[
        { siteId: "site-a", name: "Floreat public sample", status: "BASELINE_MAPPING" },
        { siteId: "site-b", name: "Product Sample Field", status: "UNMAPPED" },
      ]}
    >
      <MobileSiteSwitcher siteId="site-a" section="materials" />
    </SiteListProvider>,
  );
}

function openSheet() {
  renderSwitcher();
  const trigger = screen.getByRole("button", { name: /현장 변경/ });
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "현장 변경" });
  return { trigger, dialog: dialog as HTMLDialogElement };
}

/** matchMedia('(min-width: 1024px)') 를 수동 개폐 가능한 스텁으로 둔다. */
function stubDesktopMedia() {
  const listeners = new Set<(event: { matches: boolean }) => void>();
  const mq = {
    matches: false,
    addEventListener: (_type: string, fn: (event: { matches: boolean }) => void) => {
      listeners.add(fn);
    },
    removeEventListener: (_type: string, fn: (event: { matches: boolean }) => void) => {
      listeners.delete(fn);
    },
    dispatch: (matches: boolean) => {
      mq.matches = matches;
      listeners.forEach((fn) => fn({ matches }));
    },
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => mq),
  );
  return mq;
}

describe("MobileSiteSwitcher", () => {
  it("opens a native dialog sheet and preserves the current site section", async () => {
    stubDesktopMedia();
    const { dialog } = openSheet();
    expect(dialog.tagName.toLowerCase()).toBe("dialog");
    expect(dialog.hasAttribute("open")).toBe(true);
    const link = screen.getByRole("link", { name: /Product Sample Field/ });
    expect(link.getAttribute("href")).toBe("/sites/site-b/spatial-assets");
    expect(screen.getAllByText("현재 현장").length).toBeGreaterThan(0);
  });

  it("moves first focus to the current site option", async () => {
    stubDesktopMedia();
    openSheet();
    const current = screen.getByRole("button", { name: /Floreat.*현재 현장/ });
    expect(document.activeElement).toBe(current);
  });

  it("closes with native cancel (Escape) and restores focus", async () => {
    stubDesktopMedia();
    const { trigger, dialog } = openSheet();
    act(() => {
      dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    });
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on backdrop click and restores focus", async () => {
    stubDesktopMedia();
    const { trigger, dialog } = openSheet();
    fireEvent.click(dialog);
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on site selection and restores focus", async () => {
    stubDesktopMedia();
    const { trigger } = openSheet();
    fireEvent.click(screen.getByRole("link", { name: /Product Sample Field/ }));
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on the close button and restores focus", async () => {
    stubDesktopMedia();
    const { trigger } = openSheet();
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("does not leave a hidden modal trapping the page on desktop resize", async () => {
    const mq = stubDesktopMedia();
    openSheet();
    expect(screen.getByRole("dialog", { name: "현장 변경" })).toBeTruthy();
    act(() => {
      mq.dispatch(true);
    });
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
  });

  it("does not retain the old switcher after a route/site change", async () => {
    stubDesktopMedia();
    const rendered = render(
      <SiteListProvider
        sites={[
          { siteId: "site-a", name: "Floreat public sample", status: "BASELINE_MAPPING" },
          { siteId: "site-b", name: "Product Sample Field", status: "UNMAPPED" },
        ]}
      >
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /현장 변경/ }));
    expect(screen.getByRole("dialog", { name: "현장 변경" })).toBeTruthy();
    rendered.rerender(
      <SiteListProvider
        sites={[
          { siteId: "site-a", name: "Floreat public sample", status: "BASELINE_MAPPING" },
          { siteId: "site-b", name: "Product Sample Field", status: "UNMAPPED" },
        ]}
      >
        <MobileSiteSwitcher siteId="site-b" section="materials" />
      </SiteListProvider>,
    );
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
  });

  it("closes when the current site leaves the list and does not reopen on restore", async () => {
    stubDesktopMedia();
    const two = [
      { siteId: "site-a", name: "Floreat public sample", status: "BASELINE_MAPPING" },
      { siteId: "site-b", name: "Product Sample Field", status: "UNMAPPED" },
    ] as const;
    const withoutCurrent = [
      { siteId: "site-b", name: "Product Sample Field", status: "UNMAPPED" },
      { siteId: "site-c", name: "Third Field", status: "UNMAPPED" },
    ] as const;
    const rendered = render(
      <SiteListProvider sites={[...two]}>
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /현장 변경/ }));
    expect(screen.getByRole("dialog", { name: "현장 변경" })).toBeTruthy();

    rendered.rerender(
      <SiteListProvider sites={[...withoutCurrent]}>
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();

    // 목록 복원 시 요청 없이 다시 열리면 안 된다.
    rendered.rerender(
      <SiteListProvider sites={[...two]}>
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
    // stale open=true 가 남으면 트리거가 expanded=true 로 복원된다.
    expect(
      screen.getByRole("button", { name: /현장 변경/ }).getAttribute("aria-expanded"),
    ).toBe("false");

    // 나중에 (재)마운트된 dialog 의 Escape 계약이 살아 있어야 한다.
    const trigger = screen.getByRole("button", { name: /현장 변경/ });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "현장 변경" });
    act(() => {
      dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    });
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes when the list shrinks below two sites and stays closed on restore", async () => {
    stubDesktopMedia();
    const two = [
      { siteId: "site-a", name: "Floreat public sample", status: "BASELINE_MAPPING" },
      { siteId: "site-b", name: "Product Sample Field", status: "UNMAPPED" },
    ] as const;
    const rendered = render(
      <SiteListProvider sites={[...two]}>
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /현장 변경/ }));
    expect(screen.getByRole("dialog", { name: "현장 변경" })).toBeTruthy();

    rendered.rerender(
      <SiteListProvider sites={[two[0]]}>
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();

    rendered.rerender(
      <SiteListProvider sites={[...two]}>
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
    const trigger = screen.getByRole("button", { name: /현장 변경/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    // stale open 이 없으므로 트리거가 정상 동작한다.
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "현장 변경" })).toBeTruthy();
  });

  it("supports open and Escape after growing from a single site", async () => {
    stubDesktopMedia();
    const single = [
      { siteId: "site-a", name: "Floreat public sample", status: "BASELINE_MAPPING" },
    ] as const;
    const two = [
      ...single,
      { siteId: "site-b", name: "Product Sample Field", status: "UNMAPPED" },
    ] as const;
    const rendered = render(
      <SiteListProvider sites={[...single]}>
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    expect(screen.queryByRole("button", { name: /현장 변경/ })).toBeNull();

    rendered.rerender(
      <SiteListProvider sites={[...two]}>
        <MobileSiteSwitcher siteId="site-a" section="materials" />
      </SiteListProvider>,
    );
    const trigger = screen.getByRole("button", { name: /현장 변경/ });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "현장 변경" });
    act(() => {
      dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    });
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
