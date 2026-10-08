import { NAV_ITEMS } from "./nav-items";

// 시안(ink-mono)의 topbar 는 현재 화면 이름을 갖는다 — 사이드바가 "어디로 갈 수 있나"를
// 말하고 topbar 가 "지금 어디인가"를 말하는 분업이다. 본문 h1 을 topbar 로 올리면 스크롤이
// 내려가도 위치가 사라지지 않는다(앱과 문서를 가르는 지점 중 하나).
//
// 상세 화면은 대상 이름을 모른 채 서버에서 그려지므로 종류만 적는다. 대상 이름은 본문이 갖는다.
const STATIC_TITLES: Record<string, string> = {
  "/": "홈",
  "/sites": "현장",
  "/sites/new": "현장 등록",
  "/more": "더보기",
  "/field": "작업",
  "/field/new": "새 관측",
  "/field/inbox": "받은 업무",
  "/field/team": "팀 관리",
};

export function resolvePageTitle(pathname: string | null): string {
  if (!pathname) return "";

  const exact = STATIC_TITLES[pathname];
  if (exact) return exact;

  if (pathname.startsWith("/coming-soon/")) {
    const section = pathname.slice("/coming-soon/".length);
    return NAV_ITEMS.find((item) => item.href === `/coming-soon/${section}`)?.label ?? "준비 중";
  }

  if (/^\/sites\/[^/]+\/observations\/new\/?$/.test(pathname)) return "새 관측";
  if (/^\/sites\/[^/]+\/observations\/[^/]+\/?$/.test(pathname)) return "외부 관측 결과";
  if (/^\/sites\/[^/]+\/observations\/?$/.test(pathname)) return "외부 관측 이력";
  if (/^\/sites\/[^/]+\/analysis\/?$/.test(pathname)) return "현장 분석";
  if (/^\/sites\/[^/]+\/spatial-assets\/?$/.test(pathname)) return "현장 공간 자산";
  if (/^\/sites\/[^/]+\/work-areas\/?$/.test(pathname)) return "작업구역";
  if (/^\/sites\/[^/]+\/?$/.test(pathname)) return "현장 상세";
  if (/^\/field\/work-orders\/[^/]+\/?$/.test(pathname)) return "현장 작업";

  return "";
}
