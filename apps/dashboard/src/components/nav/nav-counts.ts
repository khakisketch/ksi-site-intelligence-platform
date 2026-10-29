import "server-only";

import type { SiteView } from "@/lib/core-api/types";
import { listSitesCached } from "@/lib/core-api/cached";

import type { NavCounts } from "./DesktopSidebar";

/**
 * 사이드바 배지용 건수. **실패는 0 이 아니라 미표시로 떨어진다** — 집계에 실패한 화면이
 * "할 일 없음"으로 보이는 게 이 제품에서 가장 나쁜 거짓말이다.
 */
export async function getNavCounts(snapshot?: readonly SiteView[] | null): Promise<NavCounts> {
  const sites = snapshot === undefined ? await listSitesCached().catch(() => null) : snapshot;

  return {
    sites: badge(sites?.length),
  };
}

/** 0 은 배지를 그리지 않는다 — "0"이 여덟 개 늘어선 레일은 정보가 아니라 잡음이고,
 *  배지가 있다는 사실 자체가 "여기 볼 게 있다"는 신호여야 한다. */
function badge(value: number | undefined, urgentWhenPositive = false) {
  if (value === undefined || value === null || value === 0) return undefined;
  return { value, urgent: urgentWhenPositive };
}
