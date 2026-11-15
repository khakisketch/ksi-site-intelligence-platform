"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { isChromelessPath } from "./chromeless-path";
import { setDesktopNavCollapsed, useDesktopNavCollapsed } from "./desktop-nav-preference";
import { SHELL_HOME_ITEM, SHELL_PROJECTS_ITEM, SHELL_WORK_ITEM } from "./nav-items";
import { NavIcon, type NavIconName } from "./NavIcon";
import { useSiteListSnapshot } from "./SiteListContext";
import { PROJECT_SECTIONS, projectSectionHref, resolveProjectSection, resolveSiteId } from "./site-context";

/** 레일에 띄울 실측 건수. 값이 없으면(집계 실패 포함) 배지를 아예 그리지 않는다 —
 *  0 과 "모름"은 다른 상태이고, 안전 화면에서 그 둘을 같게 보이면 안 된다. */
export interface NavCounts {
  [navKey: string]: { value: number; urgent?: boolean } | undefined;
}

function RailLink({
  href,
  label,
  icon,
  active,
  collapsed,
  count,
}: {
  href: string;
  label: string;
  icon: NavIconName;
  active: boolean;
  collapsed: boolean;
  count?: { value: number; urgent?: boolean } | undefined;
}) {
  // 접히면(또는 1024px 미만에서 레일이 아이콘 폭이 되면) 라벨 글자가 CSS 로 사라지므로
  // 이름(과 건수)을 항상 aria-label 이 맡는다.
  const name = count ? `${label}, ${count.value}건` : label;
  return (
    <Link
      href={href}
      className="rail-link"
      aria-current={active ? "page" : undefined}
      aria-label={name}
      data-tip={label}
    >
      <NavIcon name={icon} className="size-[18px] flex-none" />
      <span className="rail-label">{label}</span>
      {count && (
        <>
          <span className="rail-count tabular" data-urgent={count.urgent ? "true" : undefined}>{count.value}</span>
          <span aria-hidden="true" className="rail-dot" data-urgent={count.urgent ? "true" : undefined} />
        </>
      )}
    </Link>
  );
}

/**
 * 좌측 주 메뉴 — 접을 수 있는 아이콘 레일(ADR-KSI-043).
 *
 * 홈·프로젝트는 어디서나 위쪽에 두고, 프로젝트 안에서는 그 아래에 현재 프로젝트의 공간·자료·분석을
 * 더한다. 작업·도움말은 어디서나 아래쪽에 둔다. 섹션 안의 세부 메뉴는 여기에 펼치지 않는다 — 화면 안의 컨텍스트
 * 패널이 맡는다. 접힘은 사용자가 고른 것이며 경로가 바뀌어도 폭을 바꾸지 않는다.
 * 계정·로그아웃은 레일 맨 아래의 계정 메뉴(`account`)가 맡는다. 현재 어느 섹션인지는 레일의 선택 표시가
 * 알려 주므로 상단바는 페이지 이름을 되풀이하지 않는다.
 */
export function DesktopSidebar({ counts, account }: { counts?: NavCounts; account?: ReactNode }) {
  // 프로젝트 수는 헤더 전환 메뉴와 같은 목록을 따른다 — 갱신된 목록이 있으면 그 값을 쓰고,
  // 0 이면 배지를 그리지 않는다(0 과 "모름"을 같게 보이지 않는다).
  const siteSnapshot = useSiteListSnapshot();
  const siteCount = siteSnapshot?.refreshed
    ? (siteSnapshot.sites.length ? { value: siteSnapshot.sites.length } : undefined)
    : counts?.sites;
  const pathname = usePathname() ?? "";
  const search = useSearchParams();
  const collapsed = useDesktopNavCollapsed();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const restoreToggleFocus = useRef(false);
  useEffect(() => {
    if (!restoreToggleFocus.current) return;
    restoreToggleFocus.current = false;
    toggleRef.current?.focus();
  }, [collapsed]);

  // 셸을 벗는 로그인 화면에는 레일 자체가 없다 — 판정은 layout.tsx 와
  // 같은 술어를 쓴다(둘이 갈리면 그리드 트랙만 남고 레일이 사라진다).
  if (isChromelessPath(pathname)) return null;

  const siteId = resolveSiteId(pathname);
  const section = siteId ? resolveProjectSection(pathname, search) : null;
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <nav
      aria-label="주 메뉴"
      id="desktop-navigation"
      data-rail="true"
      data-collapsed={collapsed ? "true" : "false"}
      data-compact-rail={collapsed ? "true" : undefined}
      className="print:hidden relative z-50 hidden gap-0.5 border-r border-line bg-rail py-2 text-rail-text md:col-start-1 md:row-start-2 md:flex md:flex-col"
    >
      {/* 홈·프로젝트 목록은 프로젝트 안에서도 그대로 둔다 — 다른 프로젝트나 홈으로 가는 길이 사라지지 않게. */}
      <RailLink href={SHELL_HOME_ITEM.href} label={SHELL_HOME_ITEM.label} icon={SHELL_HOME_ITEM.icon}
        active={!siteId && active(SHELL_HOME_ITEM.href)} collapsed={collapsed} />
      <RailLink href={SHELL_PROJECTS_ITEM.href} label={SHELL_PROJECTS_ITEM.label} icon={SHELL_PROJECTS_ITEM.icon}
        active={!siteId && active(SHELL_PROJECTS_ITEM.href)} collapsed={collapsed} count={siteCount} />
      {siteId && (
        <>
          <div className="rail-sep" aria-hidden="true" />
          <div className="rail-group">현재 프로젝트</div>
          {PROJECT_SECTIONS.map((item) => (
            <RailLink
              key={item.key}
              href={projectSectionHref(siteId, item.key)}
              label={item.label}
              icon={item.icon}
              active={section === item.key}
              collapsed={collapsed}
            />
          ))}
        </>
      )}

      <div className="mt-auto flex flex-col gap-0.5">
        <div className="rail-group">전역</div>
        <RailLink href={SHELL_WORK_ITEM.href} label={SHELL_WORK_ITEM.label} icon={SHELL_WORK_ITEM.icon}
          active={active(SHELL_WORK_ITEM.href)} collapsed={collapsed} count={counts?.work} />
        <RailLink href="/help" label="도움말" icon="help" active={pathname.startsWith("/help")} collapsed={collapsed} />
        <button
          ref={toggleRef}
          type="button"
          className="rail-link rail-toggle"
          aria-label={collapsed ? "주 메뉴 펼치기" : "주 메뉴 접기"}
          aria-expanded={!collapsed}
          aria-controls="desktop-navigation"
          data-tip={collapsed ? "메뉴 펼치기" : "메뉴 접기"}
          onClick={() => {
            restoreToggleFocus.current = true;
            setDesktopNavCollapsed(!collapsed);
          }}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="size-[18px] flex-none">
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M9 4v16" />
            <path d={collapsed ? "m13 9 3 3-3 3" : "m16 9-3 3 3 3"} />
          </svg>
          <span className="rail-label">메뉴 접기</span>
        </button>
        {account}
      </div>
    </nav>
  );
}
