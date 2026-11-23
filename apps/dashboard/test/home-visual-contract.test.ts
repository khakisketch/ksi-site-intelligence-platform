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
describe("승인된 Home 표시 계약(D7·D8)", () => {
  it("제품 정본이 D7 개정과 유지되는 책임·우선순위를 고정한다", () => {
    const adr = repositorySource("docs/architecture/ADR-KSI-025-evidence-first-portfolio-home.md");

    expect(adr).toContain("D7 — 2026-10-21 전체 Console 정보구조 개선에 따른 Home 표시 개정");
    // D6 원문은 변경 전 증거로 보존된다.
    expect(adr).toContain("D6 — 승인된 Home 시각 구조는 상태가 바뀌어도 유지한다");
    // D1 안건 선정·현장별 중복 방지와 D4 최근 업데이트 의미·중복 제외 유지.
    expect(adr).toContain("D1의 안건 선정·현장별 중복 방지와 D4의 최근 업데이트 의미·중복 제외를 유지한다");
    // D2 모바일 수동 탐색·키보드·현재 위치·reduced-motion 유지.
    expect(adr).toContain("D2의 모바일 수동 탐색·키보드·현재 위치·reduced-motion 원칙을 유지한다");
    // D8이 D2의 캐러셀 방식을 세로 목록으로 대체한다.
    expect(adr).toContain("D8 — 2026-11-14 Home 확인 목록은 캐러셀 대신 세로 목록으로 둔다");
    // D9가 미리보기 없는 표지를 등록 경계 도형으로 정한다(장식 표지가 아니라 등록 사실).
    expect(adr).toContain("D9 — 2026-11-14 미리보기가 없는 현장 표지는 등록 경계 도형으로 둔다");
    // D3 이미지 권리/출처 제한 유지.
    expect(adr).toContain("D3의 이미지 권리/출처 제한은 유지한다");
  });

  it("D10: 확인할 것을 먼저, 프로젝트는 옆에 두고, 큰 장식 없이 책임을 유지한다", () => {
    const adr = repositorySource("docs/architecture/ADR-KSI-025-evidence-first-portfolio-home.md");
    expect(adr).toContain("D10 — 2026-11-16 Home은 \"확인할 것\"을 먼저, 프로젝트는 옆에 둔다");
    expect(adr).toContain("D1의 첫 줄·본문 첫 영역을 대체한다");
    expect(adr).toContain("모름을 0이라 말하지 않는다");

    const home = repositorySource("apps/dashboard/src/app/page.tsx");
    const inbox = repositorySource("apps/dashboard/src/app/HomeInbox.tsx");
    const projects = repositorySource("apps/dashboard/src/app/HomeProjects.tsx");
    const recent = repositorySource("apps/dashboard/src/app/HomeRecentUpdates.tsx");

    // D1: 안건 선정·프로젝트별 중복 방지는 선정 코드가 그대로 맡는다. 홈은 읽은 결과를 그대로 목록에 올린다.
    expect(home).toContain("selectHomeAttentionSources");
    expect(home).toContain("프로젝트 전체 열기");
    expect(home).toContain("일부를 확인하지 못했습니다");
    // D10: 확인할 것(안건 → 초기 설정) 다음에 프로젝트·최근 소식. 확인할 것이 DOM에서 먼저다.
    expect(home.indexOf("<HomeInbox")).toBeLessThan(home.indexOf("<HomeProjects"));
    expect(home.indexOf("<HomeProjects")).toBeLessThan(home.indexOf("<HomeRecentUpdates"));
    expect(home.indexOf("...operationalAttention.map")).toBeLessThan(home.indexOf("...setupItems"));
    // 넓은 화면은 왼쪽 목록 폭을 묶고 남는 폭을 프로젝트가 쓴다 — 한 줄이 화면 폭만큼 늘어나지 않는다.
    expect(home).toContain("lg:grid-cols-[minmax(320px,560px)_minmax(0,1fr)]");
    expect(home).toContain("2xl:grid-cols-[minmax(0,640px)_minmax(0,1fr)]");
    // D7·D9: 고정 큰 시각·거대 장식 커버·기본 표지 금지 — 높이는 내용이 정한다.
    for (const source of [home, inbox, projects, recent]) {
      expect(source).not.toContain("min-h-[208px]");
      expect(source).not.toContain("lg:min-h-[330px]");
      expect(source).not.toContain("aspect-[16/7]");
      expect(source).not.toContain("DefaultSiteVisual");
      expect(source).not.toContain("기본 표지");
      expect(source).not.toContain('size="card"');
    }
    // D9: 경계 도형은 작은 표지로만(등록 사실, 영상 아님). 배경 지도 타일은 G4 전까지 쓰지 않는다.
    expect(projects).toContain('size="row"');
    for (const source of [home, inbox, projects, recent]) {
      expect(source).not.toMatch(/tile\.openstreetmap|TileLayer/);
    }
    // 시점 라벨은 구조화된 출처 분기가 정한다 — 문자열 추론·촬영일 오독 금지.
    expect(inbox).toContain("timeLabel");
    expect(inbox).not.toMatch(/촬영일|촬영 시각|관측일시/);
    for (const label of ['timeLabel: "결과 보고"', 'timeLabel: "분석 생성"', 'timeLabel: "작업 갱신"', 'timeLabel: "프로젝트 갱신"']) {
      expect(home).toContain(label);
    }
    // D8: 가로로 넘기는 캐러셀 없이 모든 폭에서 세로 목록으로 읽는다.
    for (const source of [inbox, projects, recent]) {
      expect(source).not.toContain("이전 현장");
      expect(source).not.toContain("다음 현장");
      expect(source).not.toContain("snap-x");
      expect(source).not.toContain("overflow-x-auto");
      expect(source).not.toContain("scrollTo");
    }
    // 조회하지 않은 미리보기의 부재를 등록 자료의 부재로 말하지 않는다.
    expect(home).not.toContain("표시할 관측 이미지 없음");
  });

  it("4개 viewport 기준 이미지가 D7 변경 전 증거로 보존된다", () => {
    for (const viewport of ["mobile-390", "tablet-768", "desktop-1024", "desktop-1440"]) {
      expect(
        existsSync(join(repositoryRoot, `apps/dashboard/e2e/__screenshots__/home-${viewport}.png`)),
      ).toBe(true);
    }
  });
});
