import { SITE_TABS, type SiteTabKey } from "@/lib/site-epochs";
import { parseScopedNavQuery, type SiteHeaderScope } from "@/lib/operator-journey";
import type { PaletteItem } from "./palette-items";

function tabLabel(key: SiteTabKey): string {
  return SITE_TABS.find((tab) => tab.key === key)?.label ?? key;
}

function scopedSiteHref(base: string, section: string | null, scope: SiteHeaderScope): string {
  const query = new URLSearchParams();
  if (section) query.set("section", section);
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
    { key: `${site.key}:overview`, label: tabLabel("overview"), group: "현재 현장", hint: site.label, href: scopedSiteHref(site.href, null, scope), keywords: "지도 구역 관측 시점 최근 변화 상태 공간자료" },
    { key: `${site.key}:data`, label: tabLabel("materials"), group: "현재 현장", hint: site.label, href: scopedSiteHref(`${site.href}/spatial-assets`, null, scope), keywords: "촬영 사진 정사영상 높이 DSM 파일 등록" },
    { key: `${site.key}:analysis`, label: tabLabel("analysis"), group: "현재 현장", hint: site.label, href: scopedSiteHref(`${site.href}/analysis`, null, scope), keywords: "비교 기준 결과 근거 검토" },
    { key: `${site.key}:work`, label: tabLabel("work-orders"), group: "현재 현장", hint: site.label, href: scopedSiteHref(site.href, "work-orders", scope), keywords: "관측 작업 담당 기한 이어서" },
    { key: `${site.key}:manage`, label: tabLabel("manage"), group: "현재 현장", hint: site.label, href: scopedSiteHref(site.href, "manage", scope), keywords: "작업구역 경계 현장 상태 설정" },
    { key: `${site.key}:prepare`, label: "구역 자료 준비", group: "현재 현장", hint: site.label, href: scopedSiteHref(`${site.href}/spatial-data-requests`, null, scope), keywords: "내보내기 받기 다운로드 요청" },
  ];
}
