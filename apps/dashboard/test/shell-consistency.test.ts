import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { SITE_CONTEXT_SECTIONS } from "@/components/nav/site-context";
import { SITE_TABS } from "@/lib/site-epochs";

function readSource(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

// Product-shell regression: dense authenticated screens keep the full labelled
// rail and top bar. 공간 uses the dedicated viewer frame (ADR-KSI-042).
describe("console shell boundary", () => {
  it("keeps the full 176/232px rail as the dense default", () => {
    const layout = readSource("src/app/layout.tsx");
    expect(layout).not.toContain("isFocusModePath");
    expect(layout).not.toContain("64px");
    expect(layout).toContain("lg:grid-cols-[176px_1fr]");
    expect(layout).toContain("xl:grid-cols-[232px_1fr]");
    expect(layout).toContain("isViewerPath");
    expect(layout).toContain("viewer-shell");
  });

  it("client navigation reconciles both the dense and viewer grids", () => {
    const boundary = readSource("src/components/nav/ShellPathBoundary.tsx");
    expect(boundary).not.toContain("isFocusModePath");
    expect(boundary).not.toContain("lg:grid-cols-[64px");
    expect(boundary).toContain('"lg:grid-cols-[176px_1fr]"');
    expect(boundary).toContain('"xl:grid-cols-[232px_1fr]"');
    expect(boundary).toContain("isViewerPath");
    expect(boundary).toContain('classList.toggle("viewer-shell"');
  });

  it("viewer CSS switches only the desktop track and restores auth recovery", () => {
    const css = readSource("src/app/globals.css");
    expect(css).toContain("body.viewer-shell");
    expect(css).toContain("grid-template-columns: 56px minmax(0, 1fr)");
    expect(css).toContain("body.viewer-shell #main-content");
    expect(css).toContain("display: flex");
    expect(css).toContain('body.viewer-shell [data-shell-topbar][data-session-state="ok"]');
    expect(css).toContain("body.viewer-shell [data-site-header]");
    expect(css).not.toContain("body.viewer-shell [data-shell-topbar][data-session-state=\"expired\"]");
  });

  it("sidebar keeps the labelled rail and adds a compact viewer variant", () => {
    const sidebar = readSource("src/components/nav/DesktopSidebar.tsx");
    expect(sidebar).not.toContain("isFocusModePath");
    expect(sidebar).toContain("DESKTOP_NAV_GROUPS");
    expect(sidebar).toContain("{userBlock}");
    expect(sidebar).toContain("CompactSidebar");
    expect(sidebar).toContain("data-compact-rail");
    expect(sidebar).toContain("useDesktopNavCollapsed");
    expect(sidebar).not.toContain("isViewerPath");
  });

  it("keeps the current site context in both rail widths", () => {
    const sidebar = readSource("src/components/nav/DesktopSidebar.tsx");
    const layout = readSource("src/app/layout.tsx");
    expect(sidebar).toContain("SiteContextNav");
    expect(sidebar).toContain("sites");
    expect(layout).toContain("readRootShellSnapshot");
    expect(layout).toContain("sites={sidebarSites}");
    expect(layout).toContain("SiteListProvider");
    expect(sidebar).toContain("SITE_CONTEXT_SECTIONS");
    expect(sidebar).toContain("siteSettingsHref");
  });

  it("top bar is present on dense screens and keeps auth recovery", () => {
    const topbar = readSource("src/components/nav/TopBar.tsx");
    expect(topbar).not.toContain("NormalShellTopBar");
    expect(topbar).toContain("TopBarFrame");
    expect(topbar).toContain("TopBarSearchTrigger");
    expect(topbar).toContain("세션이 만료되었습니다");
    expect(topbar).toContain('data-shell-topbar="true"');
    expect(topbar).toContain("sessionState");
  });

  it("viewer frames keep the layer toggle in the toolbar and protect stage controls", () => {
    const frame = readSource("src/components/site/SpatialWorkbenchFrame.tsx");
    const css = readSource("src/app/globals.css");
    expect(frame).toContain("data-catalog-open");
    expect(frame).toContain("aria-label={`${catalogLabel} 열기`}");
    expect(frame).toContain("data-viewer-panel");
    expect(frame).toContain("data-viewer-columns");
    expect(frame).toContain("data-inspector-open");
    expect(css).toContain('grid-template-areas: "catalog stage inspector"');
    expect(css).not.toContain("margin-left: 312px");
    expect(css).toContain('[data-workbench-viewer][data-catalog-open="true"]');
    expect(css).toContain("[data-materials-stage]");
    expect(css).toContain("data-viewer-compact-hide");
  });

  it("shares only the space and analysis site menu entries", () => {
    expect(SITE_TABS.map(({ label }) => label)).toEqual(["공간", "분석"]);
    expect(SITE_CONTEXT_SECTIONS.map(({ label }) => label)).toEqual(["공간", "분석"]);
  });

  it("uses Disclosure for native details and removes the alternate workspace views", () => {
    const markup = readdirSync(join(process.cwd(), "src"), { recursive: true })
      .map(String)
      .filter((path) => path.endsWith(".tsx"));
    // ExternalReconstructionPanel은 TIFF 헤더 인식·폴더 보조 변경과 한 파일에 얽혀 있어
    // 그 작업이 정리될 때까지만 예외로 둔다. 새 예외는 추가하지 않는다.
    const pendingRawDetails = new Set(["app/field/ExternalReconstructionPanel.tsx"]);
    const rawDetails = markup.filter((path) => path !== "components/ui/Disclosure.tsx"
      && !pendingRawDetails.has(path)
      && /<details\b/.test(readSource(join("src", path))));
    expect(rawDetails).toEqual([]);
    const oldViews = markup.filter((path) => readSource(join("src", path)).includes("다른 보기"));
    expect(oldViews).toEqual([]);
  });

  it("mobile bottom navigation is unchanged by the shell correction", () => {
    const bottomNav = readSource("src/components/nav/MobileBottomNav.tsx");
    expect(bottomNav).not.toContain("isFocusModePath");
    expect(bottomNav).toContain("isChromelessPath(");
  });
});
