import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function source(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

describe("Operations Console 접근성 셸", () => {
  it("skip link와 client route focus가 같은 main landmark를 사용한다", () => {
    const layout = source("src/app/layout.tsx");
    const focusManager = source("src/components/nav/RouteFocusManager.tsx");
    const pageTitle = source("src/components/nav/PageTitle.tsx");

    expect(layout).toContain('href="#main-content"');
    expect(layout).toContain('id="main-content"');
    expect(layout).toContain("tabIndex={-1}");
    expect(layout).toContain("<RouteFocusManager />");
    expect(layout).toContain("<MainPageTitle fallback={currentPageTitle} />");
    expect(pageTitle).toContain('<h1 className="sr-only">');
    expect(pageTitle).toContain("usePathname()");
    expect(pageTitle).toContain("return title ?");
    expect(focusManager).toContain('getElementById("main-content")');
    expect(focusManager).toContain("focus({ preventScroll: true })");
    expect(focusManager).toContain("previousPathname.current === pathname");
  });

  it("전역 핵심 화면은 브라우저 탭에서도 현재 화면 이름을 밝힌다", () => {
    expect(source("src/app/page.tsx")).toContain('title: "홈 · KSI"');
    expect(source("src/app/sites/page.tsx")).toContain('title: "현장 · KSI"');
    expect(source("src/app/field/page.tsx")).toContain('title: "작업 · KSI"');
  });

  it("touch 프로젝트는 실제 coarse-pointer CSS를 실행한다", () => {
    const config = source("playwright.config.ts");
    expect(config.match(/hasTouch: true/g)).toHaveLength(2);
    expect(config).toContain('name: "mobile-390"');
    expect(config).toContain('name: "tablet-768"');
  });
});
