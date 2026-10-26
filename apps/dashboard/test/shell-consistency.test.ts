import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function readSource(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

// Product-shell regression: every authenticated desktop screen keeps the same
// full labelled rail and global top bar. There is no path-based focus mode.
describe("uniform console shell", () => {
  it("root layout always uses the full 176/232px rail and never a 64px path mode", () => {
    const layout = readSource("src/app/layout.tsx");
    expect(layout).not.toContain("isFocusModePath");
    expect(layout).not.toContain("64px");
    expect(layout).toContain("lg:grid-cols-[176px_1fr]");
    expect(layout).toContain("xl:grid-cols-[232px_1fr]");
  });

  it("client navigation restores the same full-width grid", () => {
    const boundary = readSource("src/components/nav/ShellPathBoundary.tsx");
    expect(boundary).not.toContain("isFocusModePath");
    expect(boundary).not.toContain("lg:grid-cols-[64px");
    expect(boundary).toContain('"lg:grid-cols-[176px_1fr]"');
    expect(boundary).toContain('"xl:grid-cols-[232px_1fr]"');
  });

  it("sidebar always renders the labelled global navigation", () => {
    const sidebar = readSource("src/components/nav/DesktopSidebar.tsx");
    expect(sidebar).not.toContain("isFocusModePath");
    expect(sidebar).toContain("DESKTOP_NAV_GROUPS");
    expect(sidebar).toContain("{userBlock}");
  });

  it("puts the current site context in the desktop rail and passes only minimal site summaries", () => {
    const sidebar = readSource("src/components/nav/DesktopSidebar.tsx");
    const layout = readSource("src/app/layout.tsx");
    expect(sidebar).toContain("SiteContextNav");
    expect(sidebar).toContain("sites");
    expect(layout).toContain("listSitesCached");
    expect(layout).toContain("sites={sidebarSites}");
  });

  it("top bar is present on authenticated screens and keeps auth recovery", () => {
    const topbar = readSource("src/components/nav/TopBar.tsx");
    expect(topbar).not.toContain("NormalShellTopBar");
    expect(topbar).toContain("TopBarFrame");
    expect(topbar).toContain("TopBarSearchTrigger");
    expect(topbar).toContain("세션이 만료되었습니다");
  });

  it("mobile bottom navigation is unchanged by the shell correction", () => {
    const bottomNav = readSource("src/components/nav/MobileBottomNav.tsx");
    expect(bottomNav).not.toContain("isFocusModePath");
    expect(bottomNav).toContain("isChromelessPath(");
  });
});
