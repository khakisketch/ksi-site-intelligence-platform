import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { isChromelessPath } from "@/components/nav/chromeless-path";

// 이 술어가 갈리면 화면이 **반쪽 셸**을 얻는다 — 레일은 사라졌는데 그리드 트랙은
// 남아 본문이 176px 로 눌리거나, 그리드는 풀렸는데 사이드바가 남아 중첩 스크롤러가
// 된다. 셋(layout·DesktopSidebar·MobileBottomNav)이 같은 함수를 쓴다는 것 자체가
// 이 파일이 지키는 대상이다.

describe("셸을 벗는 경로", () => {
  it.each(["/login", "/login/"])(
    "%s 는 셸 없이 그린다",
    (pathname) => {
      expect(isChromelessPath(pathname)).toBe(true);
    },
  );
});

describe("셸을 유지하는 경로", () => {
  it.each(["/", "/field", "/field/mission-1", "/missions", "/missions/mission-1", "/sites", "/events"])(
    "%s 는 앱 셸을 그대로 쓴다",
    (pathname) => {
      expect(isChromelessPath(pathname)).toBe(false);
    },
  );

  it("접두가 같기만 한 경로를 끌어들이지 않는다 — 세그먼트 경계까지 본다", () => {
    // /field는 이제 일반 셸이고, /logins 같은 유사 경로도 로그인 예외에 들어가면 안 된다.
    expect(isChromelessPath("/fieldwork")).toBe(false);
    expect(isChromelessPath("/field-notes")).toBe(false);
    expect(isChromelessPath("/logins")).toBe(false);
  });

  it("경로를 모르면 셸을 벗지 않는다 — 모를 때 기본값은 평소 화면이다", () => {
    expect(isChromelessPath(null)).toBe(false);
    expect(isChromelessPath(undefined)).toBe(false);
    expect(isChromelessPath("")).toBe(false);
  });
});

// ── 실제 화면 동작 회귀 시험 ──────────────────────────────────────────────
//
// 이 위까지는 술어(isChromelessPath) 자체만 본다. 하지만 이 술어가 화면에
// **실제로 배선돼 있는지**, 그리고 그 배선이 기대는 CSS 특성(레이어 밖 선언이
// 안 선언을 특이도 무관하게 이긴다)이 유지되는지는 어느 시험도 고정하지 않았다.
// 세 컴포넌트(layout·DesktopSidebar·MobileBottomNav)는 "use client" 서버/클라이언트
// 컴포넌트라 이 프로젝트의 vitest(환경 node, jsdom 없음 — 파일 상단 주석)로는 렌더할
// 수 없다. 그래서 소스에서 배선 지점을 확인한다(event-actions-token.test.ts 와 같은
// 관습).
function readSource(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

describe("셸 벗기 판정이 실제로 배선돼 있다", () => {
  it.each([
    "src/app/layout.tsx",
    "src/components/nav/DesktopSidebar.tsx",
    "src/components/nav/MobileBottomNav.tsx",
    "src/components/nav/ShellPathBoundary.tsx",
  ])("%s 가 isChromelessPath 를 호출해 조건부로 그린다", (relativePath) => {
    const source = readSource(relativePath);
    expect(source).toMatch(/isChromelessPath\(/);
  });

  it("client redirect에서도 body grid와 서버 shell 조각을 현재 경로에 맞춘다", () => {
    const layout = readSource("src/app/layout.tsx");
    const boundary = readSource("src/components/nav/ShellPathBoundary.tsx");

    expect(layout).toContain("<ShellLayoutMode />");
    expect(layout).toContain("<ShellOnly>");
    expect(boundary).toContain("document.body.classList.toggle");
    expect(boundary).toContain('"lg:grid-cols-[176px_1fr]"');
    expect(boundary).toContain('"xl:grid-cols-[232px_1fr]"');
  });
});

describe("/field 는 일반 Operations Console 화면이다", () => {
  it.each([
    "src/app/field/page.tsx",
    "src/app/field/[missionId]/page.tsx",
    "src/app/field/work-orders/[workOrderId]/page.tsx",
  ])(
    "%s 에 RC 전용 로그인·헤더·Bridge가 없다",
    (relativePath) => {
      const source = readSource(relativePath);
      expect(source).not.toMatch(/FieldInlineLogin|FieldHeader|PilotBridgeProbe/);
      expect(source).toMatch(/Operations/);
    },
  );

  it("proxy는 /field를 공개 경로로 예외 처리하지 않는다", () => {
    const source = readSource("src/proxy.ts");
    expect(source).toContain('const PUBLIC_PATHS = ["/login"]');
  });

  it("Pilot Bridge 진단은 비-production 명시 flag에서만 열린다", () => {
    const source = readSource("src/app/hil/pilot-bridge/page.tsx");
    expect(source).toContain('process.env.NODE_ENV === "production"');
    expect(source).toContain('KSI_DASHBOARD_HIL_TOOLS_ENABLED !== "1"');
    expect(source).toContain("notFound()");
  });

  it("비활성 HIL 경로는 로그인 redirect가 아니라 실제 404 route로 보낸다", () => {
    const source = readSource("src/proxy.ts");
    expect(source).toContain("function isUnavailableHilPath");
    expect(source).toContain("if (isUnavailableHilPath(pathname))");
    expect(source).toMatch(/isUnavailableHilPath[\s\S]*status: 404/);
  });
});
