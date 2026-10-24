import type { NavIconName } from "./NavIcon";

/** 고객의 세 가지 전역 업무와 계정·도움을 분리한다. */
export interface NavItem {
  key: string;
  label: string;
  href: string;
  implemented: boolean;
  icon: NavIconName;
  mobile: boolean;
  description?: string;
  /** 주 작업 흐름에서 숨기는 항목(기존 경로·안내용으로만 둔다). */
  demoted?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { key: "home", label: "홈", href: "/", implemented: true, icon: "home", mobile: true },
  { key: "sites", label: "현장", href: "/sites", implemented: true, icon: "sites", mobile: true },
  { key: "work", label: "업무", href: "/field", implemented: true, icon: "work", mobile: true },
  {
    key: "fleet",
    label: "Dock·Edge 지원 범위",
    href: "/coming-soon/fleet",
    implemented: false,
    icon: "support",
    mobile: false,
    // 장비 운용은 제품 범위 밖이다(ADR-KSI-039). 옛날 링크가 깨지지 않게
    // 항목과 경로는 남기되, 주 메뉴·팔레트·모바일 탭의 우선순위에서는 뺀다.
    demoted: true,
    description: "장비 운용은 현 제품 범위 밖입니다. 기존 경로의 안내만 유지합니다.",
  },
  {
    key: "more",
    label: "계정",
    href: "/more",
    implemented: true,
    icon: "more",
    // 데스크톱 레일의 계정·도움말 입구 — 모바일 넷째 탭과 같은 목적지다.
    // MOBILE_TAB_ITEMS는 별도 객체로 두므로 여기서 mobile 을 세우지 않는다.
    mobile: false,
    description: "계정·도움·지원 경계를 여는 자리다.",
  },
];

export const DESKTOP_NAV_ITEMS = NAV_ITEMS.filter((item) => !item.demoted);

export interface NavGroup {
  key: string;
  label: string | null;
  items: NavItem[];
}

const PRIMARY_KEYS = new Set(["home", "sites", "work"]);

export const DESKTOP_NAV_GROUPS: NavGroup[] = [
  {
    key: "primary",
    label: null,
    items: DESKTOP_NAV_ITEMS.filter((item) => PRIMARY_KEYS.has(item.key)),
  },
  {
    key: "account",
    label: null,
    items: DESKTOP_NAV_ITEMS.filter((item) => item.key === "more"),
  },
].filter((group) => group.items.length > 0);

export const MOBILE_TAB_ITEMS: NavItem[] = [
  ...NAV_ITEMS.filter((item) => item.mobile),
  {
    key: "more",
    // 휴대폰 넷째 탭은 계정·도움말 입구다. 범위 밖 장비 안내만 있던
    // '더보기'가 아니라, 계정·도움·지원 경계를 여는 자리다.
    label: "계정",
    href: "/more",
    implemented: true,
    icon: "more",
    mobile: true,
  },
];
