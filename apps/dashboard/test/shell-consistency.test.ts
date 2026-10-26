import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function readSource(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

// Product-shell regression: dense authenticated screens keep the full labelled
// rail and global top bar. Site 공간/자료 use the viewer-first exception
// (decision A, 2026-10-26) — 56px icon rail, floating panels, no top bar.
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
    expect(sidebar).toContain("isViewerPath");
  });

  it("puts the current site context in the dense rail and viewer panel", () => {
    const sidebar = readSource("src/components/nav/DesktopSidebar.tsx");
    const layout = readSource("src/app/layout.tsx");
    const viewerNav = readSource("src/components/nav/ViewerSiteNav.tsx");
    expect(sidebar).toContain("SiteContextNav");
    expect(sidebar).toContain("sites");
    expect(layout).toContain("listSitesCached");
    expect(layout).toContain("sites={sidebarSites}");
    expect(layout).toContain("SiteListProvider");
    expect(viewerNav).toContain("SITE_CONTEXT_SECTIONS");
    expect(viewerNav).toContain("siteSwitchHref");
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

  it("mobile bottom navigation is unchanged by the shell correction", () => {
    const bottomNav = readSource("src/components/nav/MobileBottomNav.tsx");
    expect(bottomNav).not.toContain("isFocusModePath");
    expect(bottomNav).toContain("isChromelessPath(");
  });
});
