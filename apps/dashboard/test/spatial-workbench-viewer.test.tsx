/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SiteListProvider } from "@/components/nav/SiteListContext";
import { SpatialWorkbenchFrame } from "@/components/site/SpatialWorkbenchFrame";

vi.mock("next/navigation", () => ({
  usePathname: () => "/sites/site-1/spatial-assets",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function viewerFrame() {
  return (
    <SiteListProvider sites={[{ siteId: "site-1", name: "Floreat public sample", status: "BASELINE_MAPPING" }]}>
      <SpatialWorkbenchFrame
        viewerMode
        contextBar={<span>구역·보기 방식</span>}
        catalog={<a href="#asset">정사영상 · v1</a>}
        catalogLabel="자료 목록"
        stage={<div>실제 범위 캔버스</div>}
        inspector={<p>선택 자료 사실</p>}
        inspectorId="viewer-inspector"
        inspectorLabel="선택 자료 정보"
        detailsHostId="viewer-details"
      />
    </SiteListProvider>
  );
}

function wideMatchMedia(query: string) {
  return {
    matches: query.includes("1024") || query.includes("1280"),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
    onchange: null,
  };
}

describe("viewer-first workbench frame", () => {
  it("opens the floating layer and inspector panels at xl without resizing the stage", async () => {
    vi.stubGlobal("matchMedia", wideMatchMedia);
    render(viewerFrame());
    const catalog = await screen.findByLabelText("자료 목록");
    expect(catalog.getAttribute("data-viewer-panel")).toBe("catalog");
    expect(screen.getByText("Floreat public sample")).toBeTruthy();
    expect(screen.getByText("실제 범위 캔버스")).toBeTruthy();
    const inspector = screen.getByRole("region", { name: "선택 자료 정보" });
    await waitFor(() => expect(inspector.style.display).toBe(""));
    expect(screen.getByRole("button", { name: "정보" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("closes and reopens the floating layer panel with focus restoration", async () => {
    vi.stubGlobal("matchMedia", wideMatchMedia);
    render(viewerFrame());
    await screen.findByLabelText("자료 목록");
    fireEvent.click(screen.getByRole("button", { name: "자료 목록 닫기" }));
    expect(screen.queryByLabelText("자료 목록")).toBeNull();
    const toggle = screen.getByRole("button", { name: "레이어 패널 열기" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
    fireEvent.click(toggle);
    expect(screen.getByLabelText("자료 목록")).toBeTruthy();
  });

  it("closes the inspector card, keeps its details host mounted, and reopens it", async () => {
    vi.stubGlobal("matchMedia", wideMatchMedia);
    render(viewerFrame());
    const inspector = screen.getByRole("region", { name: "선택 자료 정보" });
    await waitFor(() => expect(inspector.style.display).toBe(""));
    fireEvent.click(screen.getByRole("button", { name: "선택 자료 정보 닫기" }));
    expect(inspector.style.display).toBe("none");
    expect(document.getElementById("viewer-details")).toBeTruthy();
    const info = screen.getByRole("button", { name: "정보" });
    expect(info.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(info);
    fireEvent.click(info);
    await waitFor(() => expect(inspector.style.display).toBe(""));
  });

  it("closes the focused layer panel with Escape", async () => {
    vi.stubGlobal("matchMedia", wideMatchMedia);
    render(viewerFrame());
    const catalog = await screen.findByLabelText("자료 목록");
    catalog.focus();
    fireEvent.keyDown(catalog, { key: "Escape" });
    expect(screen.queryByLabelText("자료 목록")).toBeNull();
  });
});
