// PRD §7.1 taxonomy — 명칭·순서를 그대로 유지한다(docs/architecture/03_DASHBOARD_UX_GOALS.md §6).
// S3 구현 항목만 href 를 실제 라우트로, 나머지는 /coming-soon 접두 라우트로 연결한다.

export interface NavItem {
  key: string;
  label: string;
  href: string;
  implemented: boolean;
  /** 모바일 하단 5탭에 노출할지 (PRD §7.1 모바일 taxonomy) */
  mobile: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { key: "home", label: "홈", href: "/", implemented: true, mobile: false },
  { key: "today", label: "오늘", href: "/", implemented: true, mobile: true },
  { key: "sites", label: "현장", href: "/sites", implemented: true, mobile: true },
  { key: "missions", label: "임무", href: "/missions", implemented: true, mobile: true },
  { key: "events", label: "이벤트", href: "/events", implemented: true, mobile: true },
  { key: "assets", label: "자산·시설물", href: "/coming-soon/assets", implemented: false, mobile: false },
  { key: "world", label: "2D·3D World", href: "/coming-soon/world", implemented: false, mobile: false },
  { key: "reports", label: "보고서", href: "/coming-soon/reports", implemented: false, mobile: false },
  { key: "fleet", label: "Fleet·Edge", href: "/coming-soon/fleet", implemented: false, mobile: false },
  { key: "data", label: "Data·AI", href: "/coming-soon/data", implemented: false, mobile: false },
  { key: "settings", label: "설정", href: "/coming-soon/settings", implemented: false, mobile: false },
];

// 데스크톱 사이드 10항목(PRD §7.1) — "오늘"은 모바일 전용 별칭이라 데스크톱엔 제외.
export const DESKTOP_NAV_ITEMS = NAV_ITEMS.filter((item) => item.key !== "today");

// 모바일 하단 5탭: 오늘·임무·이벤트·현장·더보기(미구현 항목 진입점).
export const MOBILE_TAB_ITEMS: NavItem[] = [
  ...NAV_ITEMS.filter((item) => item.mobile),
  { key: "more", label: "더보기", href: "/more", implemented: true, mobile: true },
];
