import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const repositoryRoot = join(process.cwd(), "../..");

function repositorySource(relativePath: string): string {
  return readFileSync(join(repositoryRoot, relativePath), "utf8");
}

/**
 * 승인된 Home 표시 계약 — ADR-KSI-025 D7(2026-10-21 전체 Console 정보구조 개선).
 *
 * D6의 고정 큰 시각 영역·카드 비율 강제와 `기본 표지` 구조는 D7이 supersede
 * 한다(과거 문구·기준 이미지는 변경 전 증거로 보존). 이 검사는 D7의 내용 우선·
 * 사실 우선순위·D1/D2/D3/D4 유지를 고정한다 — 승인 없이 거대 장식 커버로
 * 돌아가지 못하게 한다. Core·projection 로직 변경의 구실이 아니다.
 */
describe("승인된 Home 표시 계약(D7)", () => {
  it("제품 정본이 D7 개정과 유지되는 책임·우선순위를 고정한다", () => {
    const adr = repositorySource("docs/architecture/ADR-KSI-025-evidence-first-portfolio-home.md");

    expect(adr).toContain("D7 — 2026-10-21 전체 Console 정보구조 개선에 따른 Home 표시 개정");
    // D6 원문은 변경 전 증거로 보존된다.
    expect(adr).toContain("D6 — 승인된 Home 시각 구조는 상태가 바뀌어도 유지한다");
    // D1 안건 선정·현장별 중복 방지와 D4 최근 업데이트 의미·중복 제외 유지.
    expect(adr).toContain("D1의 안건 선정·현장별 중복 방지와 D4의 최근 업데이트 의미·중복 제외를 유지한다");
    // D2 모바일 수동 탐색·키보드·현재 위치·reduced-motion 유지.
    expect(adr).toContain("D2의 모바일 수동 탐색·키보드·현재 위치·reduced-motion 원칙을 유지한다");
    // D3 이미지 권리/출처 제한 유지.
    expect(adr).toContain("D3의 이미지 권리/출처 제한은 유지한다");
  });

  it("구현이 큰 장식 커버 없이 책임·순서를 유지한다", () => {
    const home = repositorySource("apps/dashboard/src/app/page.tsx");
    const carousel = repositorySource("apps/dashboard/src/app/HomeAttentionCarousel.tsx");

    // D1: 포트폴리오 요약 → 확인할 현장 → 초기 설정 → 최근 업데이트.
    expect(home).toContain("attentionItems.length > 0");
    expect(home).toContain("recentSiteItems.length > 0");
    expect(home).toContain('regionLabel="최근 현장 캐러셀"');
    expect(home).toContain("초기 설정이 필요한 현장");
    expect(home).toContain("현장 전체를 열어 직접 확인하세요.");
    expect(home).toContain('<Link href="/sites"');
    expect(home.indexOf("<HomeAttentionCarousel")).toBeLessThan(home.indexOf("<HomeSituationList"));
    // D7: 고정 큰 시각·거대 장식 커버 금지 — 높이는 내용이 정한다.
    for (const source of [home, carousel]) {
      expect(source).not.toContain("min-h-[208px]");
      expect(source).not.toContain("lg:min-h-[330px]");
      expect(source).not.toContain("aspect-[16/7]");
      expect(source).not.toContain("DefaultSiteVisual");
      expect(source).not.toContain("기본 표지");
    }
    expect(carousel).not.toContain("lg:grid-cols-[minmax(0,1.25fr)_minmax(300px,0.75fr)]");
    // 조회하지 않은 미리보기의 부재를 등록 자료의 부재로 말하지 않는다.
    expect(home).not.toContain("표시할 관측 이미지 없음");
    expect(carousel).not.toContain("imageFallbackLabel");
    // D3: 허용된 실제 이미지만 — 합성·고정 placeholder·타 현장 사진 금지 문구 유지.
    expect(carousel).toContain("합성·고정");
    // 시점 라벨은 구조화된 출처 분기가 정한다 — 문자열 추론·촬영일 오독 금지.
    expect(carousel).toContain("timeLabel");
    expect(carousel).not.toMatch(/촬영일|촬영 시각|관측일시/);
    for (const label of ['timeLabel: "결과 보고"', 'timeLabel: "분석 생성"', 'timeLabel: "작업 갱신"', 'timeLabel: "현장 갱신"']) {
      expect(home).toContain(label);
    }
    // D2: 모바일 수동 탐색·현재 위치·reduced-motion 유지, 데스크톱은 전부 펼친다.
    expect(carousel).toContain("이전 현장");
    expect(carousel).toContain("다음 현장");
    expect(carousel).toContain("prefers-reduced-motion");
    expect(carousel).toContain("lg:grid");
    expect(carousel).toContain("lg:hidden");
  });

  it("4개 viewport 기준 이미지가 D7 변경 전 증거로 보존된다", () => {
    for (const viewport of ["mobile-390", "tablet-768", "desktop-1024", "desktop-1440"]) {
      expect(
        existsSync(join(repositoryRoot, `apps/dashboard/e2e/__screenshots__/home-${viewport}.png`)),
      ).toBe(true);
    }
  });
});
