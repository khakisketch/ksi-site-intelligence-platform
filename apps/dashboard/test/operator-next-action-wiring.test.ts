import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function source(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

describe("운영자 다음 행동 화면 배선", () => {
  it("Home은 고정 작업 CTA 대신 현장별 근거와 최근 업데이트 projection을 사용한다", () => {
    const home = source("src/app/page.tsx");
    expect(home).toMatch(/selectHomeAttentionSources/);
    expect(home).toMatch(/selectHomeInitialSetupSites/);
    expect(home).toMatch(/selectHomeRecentSiteSources/);
    expect(home).toMatch(/selectHomeRecentUpdates/);
    expect(home).toMatch(/getHomeEventEvidencePreview/);
    expect(home).toMatch(/HomeAttentionCarousel/);
    expect(home).toMatch(/HomeRecentUpdates/);
    expect(home).toContain("const attentionItems = attentionSources.map");
    expect(home).toContain("const initialSetupSites = selectHomeInitialSetupSites");
    expect(home).toContain("const operationalAttentionSiteIds = new Set");
    expect(home).toContain("operationalAttentionSiteIds.size");
    expect(home).toContain("초기 설정이 필요한 현장");
    expect(home).toContain("HomeSituationList");
    expect(home).toContain('source.site.status !== "UNMAPPED"');
    expect(home).toContain("const recentSiteItems = recentSiteSources.map");
    expect(home).toContain('regionLabel="최근 현장 캐러셀"');
    expect(home).toContain("새로 확인할 운영 안건이 없습니다");
    expect(home).not.toContain("지금 살펴볼 새 안건이 없습니다");
    expect(home).toContain("현장 전체의 정상이나 안전을 보증하지 않습니다");
    expect(home).not.toContain("오늘 작업 선택 → 승인 → 자동 수집·처리");
    expect(home).not.toContain('href="/field"');
  });

  it("Home 작업 원장은 현장별 N+1 대신 Core의 조직 범위 큐를 한 번 조회한다", () => {
    const home = source("src/app/page.tsx");
    const workOrders = source("src/lib/core-api/observation-work-orders.ts");

    expect(home).toContain("listObservationWorkOrdersForOrganization()");
    expect(home).not.toContain("listObservationWorkOrdersAcrossSites");
    expect(workOrders).toContain('"/v1/observation-work-orders"');
    expect(workOrders).not.toContain("listObservationWorkOrdersAcrossSites");
  });

  it("Home 시각 자료는 합성 asset이 아니라 Event evidence resolver만 사용한다", () => {
    const home = source("src/app/page.tsx");
    const evidence = source("src/lib/home-evidence.ts");
    const carousel = source("src/app/HomeAttentionCarousel.tsx");
    const updates = source("src/app/HomeRecentUpdates.tsx");
    const combined = `${home}\n${evidence}\n${carousel}\n${updates}`;

    expect(evidence).toMatch(/getEvent/);
    expect(evidence).toMatch(/getEvidenceViewUrl/);
    expect(combined).not.toMatch(/prototype\/|synthetic|합성 데이터|placehold\.co/);
    expect(home).toContain("관측 이미지 미등록");
    expect(home).toContain("관측 이미지 열람 불가");
  });

  it("모바일 캐러셀은 자동 재생 없이 swipe·버튼·pagination·reduced motion을 제공한다", () => {
    const carousel = source("src/app/HomeAttentionCarousel.tsx");
    expect(carousel).toContain("snap-mandatory");
    expect(carousel).toContain('aria-label="이전 현장"');
    expect(carousel).toContain('aria-label="다음 현장"');
    expect(carousel).toContain("prefers-reduced-motion: reduce");
    expect(carousel).toContain('window.addEventListener("resize"');
    expect(carousel).not.toContain("HomeAttentionComparisonGrid");
    expect(carousel).not.toContain("data-home-attention-comparison");
    expect(carousel).not.toMatch(/setInterval|setTimeout/);
  });

  it("작업 빈 상태는 같은 결정기를 쓰되 모바일 제한 안내를 반복하지 않는다", () => {
    const field = source("src/app/field/page.tsx");
    expect(field).toMatch(/resolveOperatorNextAction/);
    expect(field).toContain("desktopOnly: true");
    expect(field).toContain("현재 진행할 작업이 없습니다");
    expect(field).toContain("inline");
    expect(field).not.toContain("ResponsiveActionBoundary");
    expect(field).not.toContain("파일 복구와 수동 전달은 노트북");
    expect(field).not.toContain("사무실에서 반복 관측 작업을 만들면");
  });

  it("현장 헤더는 현장 범위와 조사 계획을 구분하고 옛 발급 CTA를 쓰지 않는다", () => {
    const header = source("src/app/sites/[siteId]/SiteHeader.tsx");
    const detail = source("src/app/sites/[siteId]/page.tsx");
    const resolver = source("src/lib/operator-next-action.ts");
    expect(header).toMatch(/resolveSiteOperatorNextAction/);
    expect(resolver).toContain("현장 범위 설정");
    expect(resolver).toContain("베이스라인 조사 계획하기");
    expect(header).toContain('className="ml-auto hidden flex-wrap items-center gap-1.5 lg:flex"');
    expect(header).not.toContain("베이스라인 임무 발급");
    expect(detail).toContain('id="site-aoi"');
    expect(detail.indexOf('{tab === "work"')).toBeLessThan(detail.indexOf('id="site-aoi"'));
    expect(detail.indexOf("다음 행동")).toBeLessThan(detail.indexOf("<SiteBriefingCard"));
    expect(detail).toContain("모바일에서는 편집기를 숨기고 작업 맥락만 유지한다");
  });

  it("이벤트가 없으면 선택 안내 패널까지 함께 그리지 않는다", () => {
    const events = source("src/app/events/page.tsx");
    expect(events).toMatch(/const showDetailPanel =/);
    expect(events).toMatch(/\{showDetailPanel && \(/);
    expect(events).toMatch(/const showFilters =/);
    expect(events).toContain('label="처리 상태"');
    expect(events).toContain("event.evidenceCount");
    expect(events).toContain("근거 없음");
    expect(events).toContain("inline");
    expect(events).toContain("listAllEvents");
    expect(events).not.toContain('label="트리아지"');
  });

  it("확인 항목 수를 말하는 화면은 Core 500건 상한에서 조용히 잘리지 않는다", () => {
    const cached = source("src/lib/core-api/cached.ts");
    const consumers = [
      "src/app/page.tsx",
      "src/app/sites/page.tsx",
      "src/app/field/page.tsx",
      "src/components/nav/nav-counts.ts",
    ].map(source).join("\n");
    const siteDetail = source("src/app/sites/[siteId]/page.tsx");

    expect(cached).toContain("listAllEventsCached");
    expect(consumers).toContain("listAllEventsCached");
    expect(consumers).not.toContain("listEventsCached");
    expect(siteDetail).toContain("listAllEvents({ siteId: site.siteId })");
  });

  it("Home은 근거 이미지가 없어도 정직한 썸네일 비율을 유지하고 전역 셸에는 불필요한 지표를 두지 않는다", () => {
    const carousel = source("src/app/HomeAttentionCarousel.tsx");
    const updates = source("src/app/HomeRecentUpdates.tsx");
    const topBar = source("src/components/nav/TopBar.tsx");
    expect(carousel).toMatch(/item\.image\s*\?/);
    expect(carousel).toContain('className="relative min-h-[208px] overflow-hidden bg-sunk');
    expect(carousel).toContain("item.imageFallback.label");
    expect(carousel).toContain("item.imageFallback.detail");
    expect(updates).toContain("if (items.length === 0) return null");
    expect(topBar).not.toContain("LiveIndicator");
    expect(topBar).not.toContain("todayLabel");
  });

  it("현장 목록은 실제 Event 근거 우선의 공통 썸네일을 모든 폭에서 유지한다", () => {
    const sites = source("src/app/sites/page.tsx");
    const thumbnail = source("src/components/site/SiteThumbnail.tsx");

    expect(sites).toContain("getHomeEventEvidencePreview");
    expect(sites).toContain("latestEventBySite");
    expect(sites.match(/<SiteThumbnail/g)).toHaveLength(2);
    expect(thumbnail).toContain("대표 이미지 없음");
    expect(thumbnail).toContain("최근 근거 이미지");
    expect(thumbnail).not.toMatch(/placehold\.co|unsplash|prototype\//);
  });

  it("조사 Wizard 제목은 계획이고 계약 발급은 마지막 행동으로 남는다", () => {
    const wizard = source("src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx");
    expect(wizard).toContain("베이스라인 조사 계획");
    expect(wizard).toContain('nextLabel = "계약 발급"');
    expect(wizard).not.toContain('title={`${site.status === "UNMAPPED" ? "베이스라인 임무 발급"');
  });
});
