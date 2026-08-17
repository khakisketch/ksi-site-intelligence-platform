// PRD §7.1 taxonomy — **자리(key)와 순서**를 그대로 유지한다
// (docs/architecture/03_DASHBOARD_UX_GOALS.md §6).
// 구현된 항목만 href 를 실제 라우트로, 나머지는 /coming-soon 접두 라우트로 연결한다.
// 2026-08-08: Phase 3/4 Core API 신설로 assets(결함 후보)·world(장비 운동상태)·
// reports(변화 탐지)·settings(장비 지원단계) 4섹션이 실동작으로 전환됐다.
// fleet 은 Phase 5(Dock 하드웨어 검증 선행), data 는 데이터셋·모델 라이선스
// 레지스트리가 아직 코드로 없어 준비 중으로 남는다 — 링크를 숨기지 않는다(UX 목표 §6).
//
// 2026-08-17: **label 은 PRD 슬롯 이름이 아니라 그 자리가 지금 실제로 보여주는 것**을
// 적는다. 실동작 전환 때 두 슬롯이 이름보다 훨씬 좁은 내용으로 채워졌고, 슬롯 이름을
// 그대로 제목으로 쓰면서 화면이 약속하지 않은 범위를 약속했다 — assets 는 자산대장이
// 없는데 "자산·시설물"이었고(본문에 "이 화면은 자산대장이 아닙니다" 고지가 붙어 있었다),
// settings 는 장비 지원단계 표 하나인데 "설정"이었다(2026-08-13 UI 감사 21·24번).
// ADR-KSI-020 §5 동결로 없는 기능을 만들어 이름을 맞출 수 없으므로 이름을 내용에 맞춘다.
// key·href·순서는 그대로다 — 계정·조직 설정이 실제로 생기면 label 만 "설정"으로 되돌린다.

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
  { key: "assets", label: "결함 후보", href: "/assets", implemented: true, mobile: false },
  { key: "world", label: "2D·3D World", href: "/world", implemented: true, mobile: false },
  { key: "reports", label: "보고서", href: "/reports", implemented: true, mobile: false },
  { key: "fleet", label: "Fleet·Edge", href: "/coming-soon/fleet", implemented: false, mobile: false },
  { key: "data", label: "Data·AI", href: "/coming-soon/data", implemented: false, mobile: false },
  { key: "settings", label: "장비 지원단계", href: "/settings", implemented: true, mobile: false },
];

// 데스크톱 사이드 10항목(PRD §7.1) — "오늘"은 모바일 전용 별칭이라 데스크톱엔 제외.
export const DESKTOP_NAV_ITEMS = NAV_ITEMS.filter((item) => item.key !== "today");

// 시안(ink-mono)의 사이드바는 평평한 목록이 아니라 라벨로 묶인 그룹이다. 10항목이
// 한 덩어리로 늘어서면 어디까지가 지금 쓸 수 있는 기능인지 눈으로 구분되지 않고,
// 특히 6항목이 "준비 중"인 현 단계에서는 제품이 절반쯤 비어 보인다.
//
// PRD §7.1 은 명칭과 **순서**를 고정한다 — 그래서 순서를 바꾸지 않고 경계만 넣는다.
// (홈 · 현장/임무/이벤트 · 나머지) 는 위 NAV_ITEMS 순서를 그대로 자른 것이다.
export interface NavGroup {
  key: string;
  /** 그룹 머리말. null 이면 라벨 없이 최상단에 붙는다(홈). */
  label: string | null;
  items: NavItem[];
}

// 그룹은 **분할**이지 선별이 아니다 — 아래 GROUP_OF_KEY 는 데스크톱 항목 전부를
// 빠짐없이 한 그룹에 배정하고, `desktopNavGroups()` 가 NAV_ITEMS 순서 그대로
// 잘라 넣는다. 예전에는 그룹마다 키 화이트리스트("현장 운영"은 sites/missions/
// events, "준비 중"은 !implemented)로 골랐는데, 그러면 어느 목록에도 안 걸리는
// 항목이 **조용히 사라진다**. 실제로 2026-08-08 에 assets·world·reports·settings
// 가 준비 중 → 실동작으로 바뀌면서(implemented: false → true) "준비 중" 필터에서
// 빠졌고, 받아줄 그룹이 없어 데스크톱 사이드바에서 통째로 사라졌다 — PRD §7.1 이
// 못박은 10항목 중 6항목만 남았고, /reports 는 임무 상세 안의 버튼 말고는
// 도달할 길이 없었다. 아래 nav-items.test.ts 가 "모든 항목이 정확히 한 그룹에
// 있다"를 고정해 이 계열의 회귀를 막는다.
const GROUP_OF_KEY: Record<string, string> = {
  home: "top",
  sites: "operations",
  missions: "operations",
  events: "operations",
  assets: "insight",
  world: "insight",
  reports: "insight",
  fleet: "upcoming",
  data: "upcoming",
  settings: "bottom",
};

const GROUP_LABELS: { key: string; label: string | null }[] = [
  { key: "top", label: null },
  { key: "operations", label: "현장 운영" },
  // 현장에서 모은 것이 무엇을 말하는지 보는 자리 — 결함 후보·공간/장비 상태·
  // 변화와 물량 리포트. "현장 운영"(계획하고 내보내는 일)과 축이 다르다.
  { key: "insight", label: "분석·기록" },
  { key: "upcoming", label: "준비 중" },
  { key: "bottom", label: null },
];

export const DESKTOP_NAV_GROUPS: NavGroup[] = GROUP_LABELS.map(({ key, label }) => ({
  key,
  label,
  items: DESKTOP_NAV_ITEMS.filter((item) => GROUP_OF_KEY[item.key] === key),
})).filter((group) => group.items.length > 0);

// 모바일 하단 5탭: 오늘·임무·이벤트·현장·더보기(미구현 항목 진입점).
export const MOBILE_TAB_ITEMS: NavItem[] = [
  ...NAV_ITEMS.filter((item) => item.mobile),
  { key: "more", label: "더보기", href: "/more", implemented: true, mobile: true },
];
