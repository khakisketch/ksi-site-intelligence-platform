import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function readSource(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

// 집중 모드 배선 회귀 시험 — chromeless-path.test.ts 와 같은 관습(환경 node,
// 렌더 없이 소스에서 배선 지점을 고정한다). 경로 판정 자체는
// focus-mode-path.test.ts 가 맡는다.
describe("집중 모드 셸 배선", () => {
  it("루트 레이아웃이 SSR 첫 페인트부터 집중 폭을 고른다", () => {
    const layout = readSource("src/app/layout.tsx");
    expect(layout).toContain("isFocusModePath(");
    expect(layout).toContain("lg:grid-cols-[64px_minmax(0,1fr)]");
    // 다른 경로는 기존 176/232px 그대로다.
    expect(layout).toContain("lg:grid-cols-[176px_1fr]");
  });

  it("클라이언트 네비게이션에서도 같은 술어로 셸 폭을 복원한다", () => {
    const boundary = readSource("src/components/nav/ShellPathBoundary.tsx");
    expect(boundary).toContain("isFocusModePath(");
    expect(boundary).toContain("document.body.classList.toggle");
    expect(boundary).toContain('"lg:grid-cols-[64px_minmax(0,1fr)]"');
    // 기존 chromeless 복원 약속을 그대로 둔다.
    expect(boundary).toContain('"lg:grid-cols-[176px_1fr]"');
    expect(boundary).toContain('"xl:grid-cols-[232px_1fr]"');
  });

  it("사이드바가 집중 경로에서 같은 항목의 64px 레일로만 바뀐다", () => {
    const sidebar = readSource("src/components/nav/DesktopSidebar.tsx");
    expect(sidebar).toContain("isFocusModePath(");
    expect(sidebar).toContain("isChromelessPath(");
    // 전역 내비를 복제하지 않는다 — 같은 그룹·같은 링크를 쓴다.
    expect(sidebar).toContain("DESKTOP_NAV_GROUPS");
    // 계정·로그아웃은 기존 서버 블록을 그대로 싣는다.
    expect(sidebar).toContain("{userBlock}");
  });

  it("상단바가 집중 모드에서 정상행만 숨기고 인증 경보는 유지한다", () => {
    const topbar = readSource("src/components/nav/TopBar.tsx");
    expect(topbar).toContain("NormalShellTopBar");
    // 만료·거부·도달 불가 분기는 집중 모드보다 먼저 return 된다.
    const focusAt = topbar.indexOf("<NormalShellTopBar>");
    const expiredAt = topbar.indexOf("세션이 만료되었습니다");
    expect(focusAt).toBeGreaterThan(-1);
    expect(expiredAt).toBeGreaterThan(-1);
    expect(expiredAt).toBeLessThan(focusAt);
  });

  it("모바일 하단 메뉴는 집중 모드에서도 그대로 둔다", () => {
    const bottomNav = readSource("src/components/nav/MobileBottomNav.tsx");
    expect(bottomNav).not.toContain("isFocusModePath(");
    expect(bottomNav).toContain("isChromelessPath(");
  });
});
