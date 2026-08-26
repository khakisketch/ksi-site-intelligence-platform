import "server-only";

import {
  listAllEventsCached,
  listMissionsCached,
  listSitesCached,
} from "@/lib/core-api/cached";
import { isUnattended } from "@/lib/core-api/triage";

import type { NavCounts } from "./DesktopSidebar";

// "지금 사람이 봐야 하는" 이벤트의 정의는 **triage.ts 의 isUnattended 하나뿐이어야 한다.**
//
// 여기 있던 자체 정의(status ∈ {CANDIDATE, EVIDENCE_COLLECTION, FINDING})는 OBSERVATION 을
// 빼고 있었는데, core 의 인지 파이프라인이 실제로 발행하는 것은 OBSERVATION→CANDIDATE 까지다
// (services/core/src/ksi_core/events.py). 즉 OBSERVATION 건이 실재하고, 그 결과 사이드바는
// 배지를 안 그리는데 홈·이벤트 목록은 "미조치 3건"을 말하는 상태가 실사용에서 발생했다.
//
// 안전 화면에서 같은 것을 세는 정의가 둘이면 그중 하나는 반드시 거짓말이 된다.

/**
 * 사이드바 배지용 건수. **실패는 0 이 아니라 미표시로 떨어진다** — 집계에 실패한 화면이
 * "할 일 없음"으로 보이는 게 이 제품에서 가장 나쁜 거짓말이다.
 */
export async function getNavCounts(): Promise<NavCounts> {
  const [sites, events, missions] = await Promise.all([
    listSitesCached().catch(() => null),
    listAllEventsCached().catch(() => null),
    listMissionsCached(undefined).catch(() => null),
  ]);

  const reviewQueue = events ? events.events.filter(isUnattended).length : null;

  return {
    sites: badge(sites?.length),
    missions: badge(missions?.length),
    // 검토 대기가 하나라도 있으면 붉게 — 색을 쓰는 유일한 근거가 "안전 상태"라는
    // globals.css 의 규칙에 맞는 자리다(장식이 아니라 미조치 신호).
    review: badge(reviewQueue ?? undefined, true),
  };
}

/** 0 은 배지를 그리지 않는다 — "0"이 여덟 개 늘어선 레일은 정보가 아니라 잡음이고,
 *  배지가 있다는 사실 자체가 "여기 볼 게 있다"는 신호여야 한다. */
function badge(value: number | undefined, urgentWhenPositive = false) {
  if (value === undefined || value === null || value === 0) return undefined;
  return { value, urgent: urgentWhenPositive };
}
