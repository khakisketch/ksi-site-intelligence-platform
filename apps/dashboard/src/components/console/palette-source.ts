import "server-only";

import { listSitesCached } from "@/lib/core-api/cached";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";

import { DESKTOP_NAV_ITEMS } from "../nav/nav-items";
import type { PaletteItem } from "./palette-items";

/** 팔레트에 실을 항목을 모은다(화면 + 현장).
 *
 * `listSitesCached()` 를 쓰는 것은 사이드바 배지와 **같은 스냅샷**을 보기 위해서다 —
 * 요청 단위 공유가 성립하려면 인자까지 같아야 한다(nav-counts.ts 와 동일 규약).
 * 배지가 3인데 팔레트에 4곳이 나오면 그 화면은 신뢰를 잃는다(README "셸과 본문은
 * 같은 스냅샷을 봐야 한다").
 *
 * 현장 조회가 실패하면 **화면 항목만으로 연다**. 팔레트는 이동 수단이라, 현장을 못
 * 불러왔다고 이동 자체를 막으면 사용자가 갇힌다. 실패를 0건으로 위장하지도 않는다 —
 * 그냥 그 갈래가 비어 있고, 사용자는 현장 목록에서 확인할 수 있다.
 */
export async function buildPaletteItems(): Promise<PaletteItem[]> {
  const screens: PaletteItem[] = DESKTOP_NAV_ITEMS.map((item) => ({
    key: `screen:${item.key}`,
    label: item.label,
    group: "화면",
    href: item.href,
    // 주 메뉴에 없는 항목(제품 범위 밖 안내)은 팔레트 이동 대상으로 올리지
    // 않는다(ADR-KSI-039). 범위 안내는 계정·도움말 화면에서 연결한다.
    pending: !item.implemented,
    hint: item.description,
  }));

  const sites = await listSitesCached().catch(() => null);
  const siteItems: PaletteItem[] = (sites ?? []).map((site) => ({
    key: `site:${site.siteId}`,
    label: site.name,
    group: "현장",
    href: `/sites/${encodeURIComponent(site.siteId)}`,
    // 원문 식별자 검색은 유지하지만, 기술 코드를 보조 설명으로 반복하지 않는다.
    hint: "현장 자료와 작업 보기",
    keywords: `${site.siteId} ${SITE_STATUS_LABEL[site.status]?.label ?? site.status}`,
  }));

  return [...screens, ...siteItems];
}
