import type { NavIconName } from "./NavIcon";

/** 고객의 네 가지 전역 업무와 기술 운영 지원을 분리한다. */
export interface NavItem {
  key: string;
  label: string;
  href: string;
  implemented: boolean;
  icon: NavIconName;
  mobile: boolean;
  description?: string;
}

export const NAV_ITEMS: NavItem[] = [
  { key: "home", label: "홈", href: "/", implemented: true, icon: "home", mobile: true },
  { key: "sites", label: "현장", href: "/sites", implemented: true, icon: "sites", mobile: true },
  { key: "work", label: "작업", href: "/field", implemented: true, icon: "work", mobile: true },
  {
    key: "fleet",
    label: "Dock·Edge 지원 범위",
    href: "/coming-soon/fleet",
    implemented: false,
    icon: "support",
    mobile: false,
    description: "장비 운용은 현 제품 범위 밖입니다. 기존 경로의 안내만 유지합니다.",
  },
];

export const DESKTOP_NAV_ITEMS = NAV_ITEMS;

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
    key: "support",
    label: "운영 지원",
    items: DESKTOP_NAV_ITEMS.filter((item) => !PRIMARY_KEYS.has(item.key)),
  },
].filter((group) => group.items.length > 0);

export const MOBILE_TAB_ITEMS: NavItem[] = [
  ...NAV_ITEMS.filter((item) => item.mobile),
  {
    key: "more",
    label: "더보기",
    href: "/more",
    implemented: true,
    icon: "more",
    mobile: true,
  },
];
