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

describe("집중 모드 뷰포트 래퍼", () => {
  it("집중 경로에서 dvh bound 체인으로 묶고 다른 경로는 예전 클래스를 그대로 둔다", () => {
    mocked.pathname.mockReturnValue("/sites/floreat-01/spatial-assets");
    const viewport = renderToStaticMarkup(createElement(ShellViewport, null, "본문"));
    expect(viewport).toContain("min-h-dvh");
    expect(viewport).toContain("lg:h-dvh");
    expect(viewport).not.toContain("176px");
    const main = renderToStaticMarkup(createElement(ShellMain, null, "본문"));
    expect(main).toContain('id="main-content"');
    expect(main).toContain("flex-col");
    expect(main).toContain("lg:overflow-y-auto");

    mocked.pathname.mockReturnValue("/sites");
    const normalViewport = renderToStaticMarkup(createElement(ShellViewport, null, "본문"));
    expect(normalViewport).toContain("flex min-h-full flex-col lg:col-start-2 lg:row-start-1 lg:min-h-0 lg:overflow-hidden");
    const normalMain = renderToStaticMarkup(createElement(ShellMain, null, "본문"));
    expect(normalMain).toContain('id="main-content"');
    expect(normalMain).toContain("flex-1 pb-[var(--mobile-bottom-nav-clearance)] lg:min-h-0 lg:overflow-y-auto lg:pb-0");

    mocked.pathname.mockReturnValue("/login");
    expect(renderToStaticMarkup(createElement(ShellViewport, null, "본문"))).toContain("flex min-h-full flex-col");
    expect(renderToStaticMarkup(createElement(ShellMain, null, "본문"))).toContain("flex-1 pb-[var(--mobile-bottom-nav-clearance)]");
  });

  it("layout이 래퍼에 본문 골격을 위임하고 인증 게이트는 그대로 둔다", () => {
    const layout = readSource("src/app/layout.tsx");
    expect(layout).toContain("<ShellViewport>");
    expect(layout).toContain("<ShellMain>");
    expect(layout).toContain("<TopBar />");
    expect(layout).toContain("<SessionRefresh />");
    expect(layout).not.toContain('id="main-content"');
  });
});

describe("작업환경 프레임 높이", () => {
  it("magic calc 오프셋으로 무대를 재지 않는다", () => {
    const frame = readSource("src/components/site/SpatialWorkbenchFrame.tsx");
    expect(frame).not.toContain("100dvh");
    expect(frame).not.toContain("min-h-[460px]");
    expect(frame).not.toContain("min-h-[400px]");
    // 부모 dvh 체인에 붙는 flex-1/min-h-0만 둔다.
    expect(frame).toContain("flex-1");
    expect(frame).toContain("min-h-0");
  });
});
