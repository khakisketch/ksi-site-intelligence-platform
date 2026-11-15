import type { NavIconName } from "./NavIcon";
import { PROJECT_SECTIONS, projectSectionHref } from "./site-context";

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
  { key: "work", label: "작업", href: "/field", implemented: true, icon: "work", mobile: true },
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

/**
 * 새 셸(ADR-KSI-043)의 전역 입구. 라벨은 셸의 용어(프로젝트)를 쓰고, 팔레트가 쓰는
 * NAV_ITEMS 의 라벨(현장)은 화면별 용어 전환 때 함께 바꾼다.
 */
export const SHELL_HOME_ITEM: NavItem = NAV_ITEMS.find((item) => item.key === "home")!;
export const SHELL_PROJECTS_ITEM: NavItem = {
  key: "sites",
  label: "프로젝트",
  href: "/sites",
  implemented: true,
  icon: "projects",
  mobile: true,
};
export const SHELL_WORK_ITEM: NavItem = NAV_ITEMS.find((item) => item.key === "work")!;
export const SHELL_ACCOUNT_ITEM: NavItem = {
  key: "more",
  label: "계정",
  href: "/more",
  implemented: true,
  icon: "more",
  mobile: true,
};

/** 프로젝트 밖(홈·목록 등)의 휴대폰 하단 탭. */
export const MOBILE_TAB_ITEMS: NavItem[] = [
  SHELL_HOME_ITEM,
  SHELL_PROJECTS_ITEM,
  SHELL_WORK_ITEM,
  SHELL_ACCOUNT_ITEM,
];

/** 프로젝트 안의 휴대폰 하단 탭 — 공간·자료·분석과 전역 작업. */
export function projectMobileTabItems(siteId: string): NavItem[] {
  return [
    ...PROJECT_SECTIONS.map<NavItem>((section) => ({
      key: `project-${section.key}`,
      label: section.label,
      href: projectSectionHref(siteId, section.key),
      implemented: true,
      icon: section.icon,
      mobile: true,
    })),
    SHELL_WORK_ITEM,
  ];
}
