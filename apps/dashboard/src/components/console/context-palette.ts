import { SITE_TABS, type SiteTabKey } from "@/lib/site-epochs";
import { parseScopedNavQuery, type SiteHeaderScope } from "@/lib/operator-journey";
import type { WorkArea } from "@/lib/core-api/types";
import type { PaletteItem } from "./palette-items";

function tabLabel(key: SiteTabKey): string {
  return SITE_TABS.find((tab) => tab.key === key)?.label ?? key;
}

function scopedSiteHref(base: string, state: Record<string, string>, scope: SiteHeaderScope): string {
  const query = new URLSearchParams(state);
  if (scope.workAreaId) query.set("workAreaId", scope.workAreaId);
  if (scope.workAreaId && scope.assetRef) query.set("assetRef", scope.assetRef);
  const search = query.toString();
  return search ? `${base}?${search}` : base;
}

/** 이미 인가된 현장 항목에서만 현재 현장의 읽기 목적지를 만든다.
 *
 * - 라벨은 현장 영역 정의(SITE_TABS)를 그대로 쓴다 — 헤더 메뉴와 어긋나지 않게.
 * - 범위는 URL 쿼리의 허용 목록만 싣는다(작업구역+엄격한 자산 참조). 받는 화면이
 *   서버 목록과 재대조하므로, 여기서 판정·최신 추측·임의 쿼리 전달을 하지 않는다.
 * - 분석 기록 화면의 assetRef는 복귀용 항해 맥락일 뿐 선택자가 아니다.
 */
export function contextPaletteItems(
  items: readonly PaletteItem[],
  pathname: string,
  search?: string,
): PaletteItem[] {
  const site = items.find((item) => item.group === "현장" && (pathname === item.href || pathname.startsWith(`${item.href}/`)));
  if (!site) return [];
  const scope = parseScopedNavQuery(search);
  return [
    { key: `${site.key}:space`, label: tabLabel("space"), group: "현재 현장", hint: site.label, href: scopedSiteHref(site.href, {}, scope), keywords: "지도 구역 관측 시점 최근 변화 상태 공간자료" },
    { key: `${site.key}:data`, label: "자료 패널", group: "현재 현장", hint: site.label, href: scopedSiteHref(site.href, { panel: "materials" }, scope), keywords: "촬영 사진 정사영상 높이 DSM 파일 등록" },
    { key: `${site.key}:analysis`, label: tabLabel("analysis"), group: "현재 현장", hint: site.label, href: scopedSiteHref(`${site.href}/analysis`, {}, scope), keywords: "비교 기준 결과 근거 검토" },
    { key: `${site.key}:intake`, label: "등록 진행", group: "현재 현장", hint: site.label, href: scopedSiteHref(site.href, { panel: "intake" }, scope), keywords: "작업 담당 기한 이어서" },
    { key: `${site.key}:manage`, label: "현장 설정", group: "현재 현장", hint: site.label, href: scopedSiteHref(site.href, { section: "manage" }, scope), keywords: "작업구역 경계 현장 상태 설정" },
    { key: `${site.key}:measure`, label: "측정 선", group: "현재 현장", hint: site.label, href: scopedSiteHref(`${site.href}/measurements`, {}, scope), keywords: "단면 높이 선 거리 기울기 경사 표고" },
    { key: `${site.key}:prepare`, label: "구역 자료 준비", group: "현재 현장", hint: site.label, href: scopedSiteHref(`${site.href}/spatial-data-requests`, {}, scope), keywords: "내보내기 받기 다운로드 요청" },
  ];
}

/**
 * 현재 현장의 영역을 팔레트에서 바로 찾는다 — ② 영역 탭(`?panel=areas`)의 선택
 * 주소로 바로 간다. 셸이 들고 있지 않은 전역 색인이 아니라, 들어가 있는 현장의
 * 목록을 열 때 한 번 읽는다. 보관된 영역도 숨기지 않고 "보관된 영역"이라 밝힌다.
 * 읽기에 실패하면 빈 목록을 돌려준다 — 팔레트는 이동 수단이라 영역 검색 없이도
 * 화면·현장 이동은 막지 않는다.
 */
export function areaPaletteItems(
  siteId: string,
  areas: readonly WorkArea[],
): PaletteItem[] {
  const encoded = encodeURIComponent(siteId);
  return areas.map((area) => ({
    key: `area:${siteId}:${area.workAreaId}`,
    label: area.name,
    group: "영역",
    href: `/sites/${encoded}?panel=areas&workAreaId=${encodeURIComponent(area.workAreaId)}`,
    hint: area.status === "ARCHIVED" ? "보관된 영역" : undefined,
    keywords: area.workAreaId,
  }));
}
