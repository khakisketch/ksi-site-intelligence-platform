import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { isChromelessPath } from "@/components/nav/chromeless-path";

// 이 술어가 갈리면 화면이 **반쪽 셸**을 얻는다 — 레일은 사라졌는데 그리드 트랙은
// 남아 본문이 176px 로 눌리거나, 그리드는 풀렸는데 사이드바가 남아 중첩 스크롤러가
// 된다. 셋(layout·DesktopSidebar·MobileBottomNav)이 같은 함수를 쓴다는 것 자체가
// 이 파일이 지키는 대상이다.

describe("셸을 벗는 경로", () => {
  it.each(["/login", "/login/", "/field", "/field/", "/field/mission-1", "/field/mission-1/"])(
    "%s 는 셸 없이 그린다",
    (pathname) => {
      expect(isChromelessPath(pathname)).toBe(true);
    },
  );
});

describe("셸을 유지하는 경로", () => {
  it.each(["/", "/missions", "/missions/mission-1", "/sites", "/events"])(
    "%s 는 앱 셸을 그대로 쓴다",
    (pathname) => {
      expect(isChromelessPath(pathname)).toBe(false);
    },
  );

  it("접두가 같기만 한 경로를 끌어들이지 않는다 — 세그먼트 경계까지 본다", () => {
    // /fieldwork·/logins 같은 경로가 나중에 생겼을 때 "/field 로 시작한다"는
    // 이유만으로 조용히 사이드바를 잃으면 안 된다.
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
  ])("%s 가 isChromelessPath 를 호출해 조건부로 그린다", (relativePath) => {
    const source = readSource(relativePath);
    expect(source).toMatch(/isChromelessPath\(/);
  });
});

describe("/field 는 리다이렉트가 아니라 인라인 로그인으로 막힌다", () => {
  // field-session.ts 의 설계 이유(모듈 docstring): Pilot 2 웹뷰가 302 를 따라간다는
  // 보장이 없다. 그래서 세션 없음을 리다이렉트가 아니라 화면 상태로 다룬다 — 이
  // 성질이 조용히 redirect() 로 되돌아가면 그 보장이 깨진다.
  it.each(["src/app/field/page.tsx", "src/app/field/[missionId]/page.tsx"])(
    "%s 가 FieldInlineLogin 을 그리고 redirect() 를 쓰지 않는다",
    (relativePath) => {
      const source = readSource(relativePath);
      expect(source).toMatch(/FieldInlineLogin/);
      expect(source).not.toMatch(/\bredirect\(/);
    },
  );
});

describe("현장 44px 터치 치수 — 정적 검사", () => {
  const css = readSource("src/app/globals.css");

  it(".btn-field 는 pointer 판별 없이 항상 44px 이다", () => {
    const match = /\.btn-field\s*\{([^}]*)\}/.exec(css);
    expect(match, ".btn-field 규칙을 찾지 못했다").not.toBeNull();
    expect(match![1]).toMatch(/min-height:\s*44px/);
    expect(match![1]).toMatch(/min-width:\s*44px/);
  });

  it(".field-controls .tap-target 는 @layer components 블록 밖에 있다 — 레이어 안에 두면 " +
    "레이어 밖의 .tap-target(36px)에 특이도와 무관하게 져서 44px 규칙이 조용히 무효화된다 " +
    "(파일 내 주석에 실측 회귀로 기록돼 있다)", () => {
    const layerStart = css.indexOf("@layer components {");
    expect(layerStart, "@layer components 블록을 찾지 못했다").toBeGreaterThan(-1);

    // layerStart 에서 시작해 중괄호 깊이로 이 @layer 블록의 끝을 찾는다.
    let depth = 0;
    let layerEnd = -1;
    for (let i = layerStart; i < css.length; i += 1) {
      if (css[i] === "{") depth += 1;
      else if (css[i] === "}") {
        depth -= 1;
        if (depth === 0) {
          layerEnd = i;
          break;
        }
      }
    }
    expect(layerEnd, "@layer components 블록의 닫는 중괄호를 찾지 못했다").toBeGreaterThan(-1);

    const ruleIndex = css.indexOf(".field-controls .tap-target");
    expect(ruleIndex, ".field-controls .tap-target 규칙을 찾지 못했다").toBeGreaterThan(-1);

    const insideLayer = ruleIndex > layerStart && ruleIndex < layerEnd;
    expect(insideLayer, ".field-controls .tap-target 가 @layer components 안으로 들어갔다").toBe(false);
  });
});
