import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ pathname: vi.fn(() => "/") }));
vi.mock("next/navigation", () => ({ usePathname: mocked.pathname }));

import { ShellMain, ShellViewport } from "@/components/nav/ShellPathBoundary";

function readSource(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

const VIEWPORT_CLASS =
  "flex min-h-full flex-col lg:col-start-2 lg:row-start-1 lg:min-h-0 lg:overflow-hidden";
const MAIN_CLASS =
  "flex-1 pb-[var(--mobile-bottom-nav-clearance)] lg:min-h-0 lg:overflow-y-auto lg:pb-0";

describe("uniform console viewport", () => {
  it("keeps the same viewport/main skeleton on site workspace and ordinary paths", () => {
    for (const pathname of ["/sites/floreat-01/spatial-assets", "/sites", "/login"]) {
      mocked.pathname.mockReturnValue(pathname);
      const viewport = renderToStaticMarkup(createElement(ShellViewport, null, "본문"));
      const main = renderToStaticMarkup(createElement(ShellMain, null, "본문"));
      expect(viewport).toContain(VIEWPORT_CLASS);
      expect(viewport).not.toContain("64px");
      expect(main).toContain('id="main-content"');
      expect(main).toContain(MAIN_CLASS);
    }
  });

  it("layout delegates the body skeleton and keeps the auth gate", () => {
    const layout = readSource("src/app/layout.tsx");
    expect(layout).toContain("<ShellViewport>");
    expect(layout).toContain("<ShellMain>");
    expect(layout).toContain("<TopBar />");
    expect(layout).toContain("<SessionRefresh />");
    expect(layout).not.toContain('id="main-content"');
    expect(layout).not.toContain("isFocusModePath");
  });
});

describe("workbench frame height", () => {
  it("uses the parent flex/dvh chain instead of magic viewport offsets", () => {
    const frame = readSource("src/components/site/SpatialWorkbenchFrame.tsx");
    expect(frame).not.toContain("100dvh");
    expect(frame).not.toContain("min-h-[460px]");
    expect(frame).not.toContain("min-h-[400px]");
    expect(frame).toContain("flex-1");
    expect(frame).toContain("min-h-0");
  });
});
