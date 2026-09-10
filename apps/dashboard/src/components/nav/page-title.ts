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
  "/events": "확인 항목",
  "/missions": "비행 임무 이력",
  // Phase 3/4 섹션(2026-08-08) — 사이드바 라벨과 같은 말을 쓴다(NAV_ITEMS 참고).
  "/assets": "결함 후보",
  "/world": "2D·3D World",
  "/reports": "보고서",
  "/settings": "장비 연결·지원 상태",
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

  // /sites/{id}/surveys/new · /sites/{id}/design · /sites/{id}/work-areas 가
  // /sites/{id} 보다 먼저 걸려야 한다.
  if (/^\/sites\/[^/]+\/surveys\/new\/?$/.test(pathname)) return "조사 계획";
  if (/^\/sites\/[^/]+\/observations\/new\/?$/.test(pathname)) return "새 관측";
  if (/^\/sites\/[^/]+\/observations\/[^/]+\/?$/.test(pathname)) return "외부 관측 결과";
  if (/^\/sites\/[^/]+\/observations\/?$/.test(pathname)) return "외부 관측 이력";
  if (/^\/sites\/[^/]+\/design\/?$/.test(pathname)) return "설계 기준면";
  if (/^\/sites\/[^/]+\/work-areas\/?$/.test(pathname)) return "작업구역";
  if (/^\/sites\/[^/]+\/progress\/?$/.test(pathname)) return "계획 대비 진척";
  if (/^\/sites\/[^/]+\/report\/?$/.test(pathname)) return "현장 보고서";
  if (/^\/sites\/[^/]+\/ai\/?$/.test(pathname)) return "KSI AI";
  if (/^\/sites\/[^/]+\/?$/.test(pathname)) return "현장 상세";
  if (/^\/events\/[^/]+\/?$/.test(pathname)) return "확인 항목 상세";
  if (/^\/missions\/[^/]+\/?$/.test(pathname)) return "비행 임무 상세";
  if (/^\/field\/work-orders\/[^/]+\/?$/.test(pathname)) return "현장 작업";
  if (/^\/field\/[^/]+\/?$/.test(pathname)) return "임무 복구";

  return "";
}
