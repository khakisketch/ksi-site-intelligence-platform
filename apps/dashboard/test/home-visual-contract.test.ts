import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const repositoryRoot = join(process.cwd(), "../..");

function repositorySource(relativePath: string): string {
  return readFileSync(join(repositoryRoot, relativePath), "utf8");
}

describe("승인된 Home Visual Contract", () => {
  it("제품 정본과 수용기준이 같은 시각 위계와 변경 게이트를 고정한다", () => {
    const adr = repositorySource("docs/architecture/ADR-KSI-025-evidence-first-portfolio-home.md");
    const prd = repositorySource("docs/product/MASTER_PRD_v3.0.md");
    const acceptance = repositorySource("docs/acceptance/OPERATIONS_CONSOLE_PHASE_1_ACCEPTANCE.md");

    for (const authority of [adr, prd, acceptance]) {
      expect(authority).toContain("초기 설정이 필요한 현장");
      expect(authority).toMatch(/390\/768\/1024\/1440/);
    }
    expect(adr).toContain("D6 — 승인된 Home 시각 구조는 상태가 바뀌어도 유지한다");
    expect(adr).toMatch(/제품책임자의 명시 승인 없이 변경할\s+수 없다/);
    expect(prd).toContain("안건 유무와 무관하게 큰 시각 캐러셀 영역 유지");
    expect(acceptance).toContain("UX-01b");
    expect(acceptance).toContain("텍스트 빈 상태로 축소되지 않고");
  });

  it("구현과 4개 viewport 기준 이미지가 승인된 구조를 지킨다", () => {
    const home = repositorySource("apps/dashboard/src/app/page.tsx");
    const carousel = repositorySource("apps/dashboard/src/app/HomeAttentionCarousel.tsx");

    expect(home).toContain("attentionItems.length > 0");
    expect(home).toContain("recentSiteItems.length > 0");
    expect(home).toContain('regionLabel="최근 현장 캐러셀"');
    expect(home).toContain("초기 설정이 필요한 현장");
    expect(home.indexOf("<HomeAttentionCarousel")).toBeLessThan(home.indexOf("<HomeSituationList"));
    expect(carousel).toContain("lg:grid-cols-[minmax(0,1.25fr)_minmax(300px,0.75fr)]");

    for (const viewport of ["mobile-390", "tablet-768", "desktop-1024", "desktop-1440"]) {
      expect(
        existsSync(join(repositoryRoot, `apps/dashboard/e2e/__screenshots__/home-${viewport}.png`)),
      ).toBe(true);
    }
  });
});
