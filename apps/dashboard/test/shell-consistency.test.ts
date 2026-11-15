import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { PROJECT_SECTIONS, SITE_CONTEXT_SECTIONS } from "@/components/nav/site-context";
import { SITE_TABS } from "@/lib/site-epochs";

function readSource(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

// Product-shell regression (ADR-KSI-043): a global header spans the top, a collapsible
// icon rail sits on the left, and the viewport fills the rest. 공간 uses the
// dedicated viewer frame.
describe("console shell boundary", () => {
  it("keeps the header row and a 188px rail as the dense default", () => {
    const layout = readSource("src/app/layout.tsx");
    expect(layout).not.toContain("isFocusModePath");
    expect(layout).not.toContain("64px");
    expect(layout).toContain("md:grid-cols-[56px_1fr]");
    expect(layout).toContain("lg:grid-cols-[188px_1fr]");
    expect(layout).toContain("md:grid-rows-[auto_minmax(0,1fr)]");
    expect(layout).not.toContain("176px");
    expect(layout).not.toContain("232px");
    expect(layout).toContain("isViewerPath");
    expect(layout).toContain("viewer-shell");
  });

  it("renders the header before the rail and the viewport, outside the viewport", () => {
    const layout = readSource("src/app/layout.tsx");
    const header = layout.indexOf("<TopBar />");
    const rail = layout.indexOf("<DesktopSidebar");
    const viewport = layout.indexOf("<ShellViewport>");
    expect(header).toBeGreaterThan(-1);
    expect(header).toBeLessThan(rail);
    expect(rail).toBeLessThan(viewport);
    const viewportBlock = layout.slice(viewport, layout.indexOf("</ShellViewport>"));
    expect(viewportBlock).not.toContain("<TopBar");
    expect(layout).not.toContain("SidebarUserBlock");
  });

  it("client navigation reconciles both the dense and viewer grids", () => {
    const boundary = readSource("src/components/nav/ShellPathBoundary.tsx");
    expect(boundary).not.toContain("isFocusModePath");
    expect(boundary).not.toContain("lg:grid-cols-[64px");
    expect(boundary).toContain('"md:grid-cols-[56px_1fr]"');
    expect(boundary).toContain('"lg:grid-cols-[188px_1fr]"');
    expect(boundary).toContain('"md:grid-rows-[auto_minmax(0,1fr)]"');
    expect(boundary).toContain("md:col-start-2 md:row-start-2");
    expect(boundary).toContain("isViewerPath");
    expect(boundary).toContain('classList.toggle("viewer-shell"');
  });

  it("viewer CSS switches only the desktop track and never hides the global header", () => {
    const css = readSource("src/app/globals.css");
    expect(css).toContain("body.viewer-shell");
    expect(css).toContain("grid-template-columns: 56px minmax(0, 1fr)");
    expect(css).toContain("body.viewer-shell #main-content");
    expect(css).toContain("display: flex");
    expect(css).toContain("body.viewer-shell [data-site-header]");
    expect(css).not.toContain("body.viewer-shell [data-shell-topbar]");
  });

  it("rail is one collapsible nav with its own light tokens", () => {
    const sidebar = readSource("src/components/nav/DesktopSidebar.tsx");
    const css = readSource("src/app/globals.css");
    expect(sidebar).not.toContain("isFocusModePath");
    expect(sidebar).toContain("PROJECT_SECTIONS");
    expect(sidebar).toContain("data-rail");
    expect(sidebar).toContain("data-compact-rail");
    expect(sidebar).toContain("useDesktopNavCollapsed");
    expect(sidebar).not.toContain("isViewerPath");
    expect(sidebar).not.toContain("userBlock");
    // 레일은 어두운 무대 면이 쓰는 --sidebar* 를 건드리지 않고 전용 토큰을 쓴다.
    expect(css).toContain("--rail:");
    expect(css).toContain("--color-rail:");
    expect(sidebar).not.toContain("bg-sidebar");
  });

  it("header keeps the project switcher, search, account menu and auth recovery", () => {
    const topbar = readSource("src/components/nav/TopBar.tsx");
    expect(topbar).not.toContain("NormalShellTopBar");
    expect(topbar).toContain("TopBarFrame");
    expect(topbar).toContain("ProjectSwitcher");
    expect(topbar).toContain("HeaderSearchTrigger");
    expect(topbar).toContain("TopBarSearchTrigger");
    expect(topbar).toContain("AccountMenu");
    expect(topbar).toContain("세션이 만료되었습니다");
    expect(topbar).toContain('data-shell-topbar="true"');
    expect(topbar).toContain("sessionState");
    // 만료·거절에서는 정상 도구를 그리지 않는다.
    expect(topbar).toContain('sessionState !== "expired"');
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

  it("project sections are space, data and analysis; the legacy site tabs stay space and analysis", () => {
    expect(PROJECT_SECTIONS.map(({ label }) => label)).toEqual(["공간", "자료", "분석"]);
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

  it("mobile bottom navigation follows the project context and stays out of login", () => {
    const bottomNav = readSource("src/components/nav/MobileBottomNav.tsx");
    expect(bottomNav).not.toContain("isFocusModePath");
    expect(bottomNav).toContain("isChromelessPath(");
    expect(bottomNav).toContain("projectMobileTabItems");
    expect(bottomNav).toContain("MOBILE_TAB_ITEMS");
  });
});
