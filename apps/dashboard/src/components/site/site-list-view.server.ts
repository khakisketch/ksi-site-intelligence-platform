import "server-only";

import { cookies } from "next/headers";

import {
  SITE_LIST_VIEW_COOKIE,
  parseSiteListView,
  type SiteListViewMode,
} from "./site-list-view";

/**
 * 요청 쿠키에서 데스크톱 보기 방식을 읽는다. 값 검증은
 * `parseSiteListView` 가 맡는다 — 모르는 값은 카드 기본값으로 떨어진다.
 * 헤더 문맥이 없으면(단위 테스트 등) throw 하므로 호출부 테스트는
 * 이 모듈을 mock 한다.
 */
export async function readSiteListView(): Promise<SiteListViewMode> {
  const value = (await cookies()).get(SITE_LIST_VIEW_COOKIE)?.value;
  return parseSiteListView(value);
}
