/** @vitest-environment jsdom */
import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SpatialWorkbenchFrame } from "@/components/site/SpatialWorkbenchFrame";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function FrameCase({ delegated = true }: { delegated?: boolean }) {
  const [info, setInfo] = useState(false);
  return <>
    <input aria-label="팔레트 바깥 검색" />
    <SpatialWorkbenchFrame
      contextBar={<button data-workbench-info-trigger onClick={() => setInfo(!info)}>정보</button>}
      catalog={<a href="#selection">자료 선택</a>}
      catalogLabel="자료 목록"
      stage={<div>시각 자료</div>}
      inspector={<a href="?info=0" data-workbench-info-close onClick={(event) => { event.preventDefault(); setInfo(false); }}>정보 닫기</a>}
      inspectorOpen={info}
      onCloseInspector={delegated ? () => setInfo(false) : undefined}
      inspectorId="test-inspector"
      inspectorLabel="선택 정보"
    />
  </>;
}

describe("workbench drawer keyboard ownership", () => {
  it("uses a full-height mobile sheet instead of anchoring below the toolbar", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      return this.hasAttribute("data-workbench-context-bar")
        ? new DOMRect(0, 0, 390, 76)
        : new DOMRect(0, -150, 390, 1000);
    });
    render(<FrameCase />);
    fireEvent.click(screen.getByRole("button", { name: "정보" }));
    const sheet = screen.getByRole("region", { name: "선택 정보" });
    await waitFor(() => expect(sheet.style.top).toBe("8px"));
    expect(sheet.getAttribute("data-mobile-sheet")).toBe("inspector");
    expect(sheet.className).toContain("inset-x-2");
  });
  it("opens the catalog as a full-height mobile sheet above the context bar", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    render(<FrameCase />);
    fireEvent.click(screen.getByRole("button", { name: "목록" }));
    const sheet = screen.getByRole("region", { name: "자료 목록" });
    await waitFor(() => expect(sheet.style.top).toBe("8px"));
    expect(sheet.getAttribute("data-mobile-sheet")).toBe("catalog");
    expect(sheet.className).toContain("inset-x-2");
    expect(sheet.className).toContain("z-50");
  });

  it("starts overlays below the measured pane controls without resizing the stage", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      return this.hasAttribute("data-workbench-pane-controls")
        ? new DOMRect(0, 100, 500, 56)
        : new DOMRect(0, 100, 900, 600);
    });
    render(<SpatialWorkbenchFrame
      contextBar={<span>현재 관측</span>}
      catalog={<p>자료</p>}
      catalogLabel="자료 목록"
      stage={<div data-workbench-pane><div data-workbench-pane-controls>날짜·레이어</div><p>사진</p></div>}
      inspectorId="test-info"
      inspectorLabel="선택 정보"
    />);
    fireEvent.click(screen.getByRole("button", { name: "목록" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "자료 목록" }).style.top).toBe("64px"));
  });
  it("closes the catalog sheet from the selection footer and restores the trigger", async () => {
    render(<SpatialWorkbenchFrame
      contextBar={<span>현재 관측</span>}
      catalog={<a href="#selection">자료 선택</a>}
      catalogLabel="자료 목록"
      stage={<div>시각 자료</div>}
      inspectorId="test-info"
      inspectorLabel="선택 정보"
      defaultCatalogOpen
      catalogFooter={<p>현재 선택 · A · 정사영상</p>}
      catalogDismissLabel="이 선택으로 보기"
    />);
    const toggle = screen.getByRole("button", { name: "목록" });
    fireEvent.click(screen.getByRole("button", { name: "이 선택으로 보기" }));
    expect(screen.queryByRole("region", { name: "자료 목록" })).toBeNull();
    expect(document.activeElement).toBe(toggle);
    expect(screen.getByText("시각 자료")).toBeTruthy();
  });

  it("keeps the catalog as a persistent left column at xl and removes the drawer toggle", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("1280"),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    render(<SpatialWorkbenchFrame
      contextBar={<span>현재 관측</span>}
      catalog={<a href="#selection">자료 선택</a>}
      catalogLabel="자료 목록"
      stage={<div>시각 자료</div>}
      inspectorId="test-info"
      inspectorLabel="선택 정보"
    />);
    await waitFor(() => expect(screen.getByText("자료 선택").closest("[data-desktop-catalog]")).toBeTruthy());
    expect(screen.queryByRole("button", { name: "목록" })).toBeNull();
  });

  it("focuses the opened catalog and restores its trigger on Escape", async () => {
    render(<FrameCase />);
    const toggle = screen.getByRole("button", { name: "목록" });
    fireEvent.click(toggle);
    const region = screen.getByRole("region", { name: "자료 목록" });
    await waitFor(() => expect(document.activeElement).toBe(region));
    fireEvent.keyDown(region, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "자료 목록" })).toBeNull();
    expect(document.activeElement).toBe(toggle);
  });

  it.each([true, false])("closes delegated or URL-owned info and restores focus (%s)", async (delegated) => {
    render(<FrameCase delegated={delegated} />);
    const toggle = screen.getByRole("button", { name: "정보" });
    fireEvent.click(toggle);
    const region = screen.getByRole("region", { name: "선택 정보" });
    await waitFor(() => expect(document.activeElement).toBe(region));
    fireEvent.keyDown(region, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "선택 정보" })).toBeNull());
    expect(document.activeElement).toBe(toggle);
  });

  it("does not consume Escape from a palette outside the drawer", () => {
    render(<FrameCase />);
    fireEvent.click(screen.getByRole("button", { name: "목록" }));
    const outside = screen.getByRole("textbox", { name: "팔레트 바깥 검색" });
    outside.focus();
    fireEvent.keyDown(outside, { key: "Escape" });
    expect(screen.getByRole("region", { name: "자료 목록" })).toBeDefined();
  });
});
