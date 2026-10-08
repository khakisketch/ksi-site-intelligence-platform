import "server-only";

import { cache } from "react";

import { listSites } from "./sites";

// client.ts 는 `cache: "no-store"` 로 나간다 — 실시간성이 필요한 안전 화면에서 옳은 기본값이다.
// 다만 그 탓에 같은 렌더 패스 안에서 같은 목록을 두 번 부르면 정말 두 번 나간다. 셸(사이드바
// 배지)과 본문이 같은 데이터를 보게 되면서 이 중복이 실제로 생겼다.
//
// React 의 `cache()` 는 **요청 하나** 안에서만 결과를 공유한다(요청 간 캐시가 아니다). 그래서
// no-store 의 의미를 훼손하지 않고 중복 왕복만 없앤다. 셸과 본문은 같은 스냅샷을 보게 되는데,
// 한 화면 안에서 사이드바 배지와 목록 건수가 어긋나지 않는다는 뜻이라 오히려 이쪽이 맞다.
export const listSitesCached = cache(listSites);
