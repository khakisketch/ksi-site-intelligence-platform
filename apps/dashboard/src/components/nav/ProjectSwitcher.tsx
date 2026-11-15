"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";

import { useSidebarSites } from "./SiteListContext";
import { NavIcon } from "./NavIcon";
import {
  projectSwitchHref,
  resolveProjectSection,
  resolveSiteId,
  siteMark,
  siteSettingsHref,
  siteShortName,
} from "./site-context";
import { useHeaderPopover } from "./use-header-popover";

/**
 * 헤더의 프로젝트 전환(ADR-KSI-043).
 *
 * - 현재 프로젝트는 URL 에서만 정한다. 별도 "현재 프로젝트" 상태를 만들지 않는다.
 * - 다른 프로젝트를 고르면 지금 보던 섹션(공간·자료·분석)을 유지한다.
 * - 목록은 레이아웃이 내려준 접근 가능한 프로젝트만이다. 새 조회·권한을 만들지 않는다.
 * - 프로젝트가 열려 있으면 이름 옆에 그 프로젝트의 설정 입구를 둔다.
 */
export function ProjectSwitcher() {
  const pathname = usePathname() ?? "";
  const search = useSearchParams();
  const sites = useSidebarSites();
  const { open, setOpen, close, rootRef, triggerRef } = useHeaderPopover();
  const [query, setQuery] = useState("");

  const siteId = resolveSiteId(pathname);
  const current = siteId ? sites.find((site) => site.siteId === siteId) ?? null : null;
  const section = resolveProjectSection(pathname, search);
  const needle = query.trim().toLowerCase();
  const shown = needle ? sites.filter((site) => site.name.toLowerCase().includes(needle)) : sites;
  const label = current ? siteShortName(current.name) : siteId ? "프로젝트" : "프로젝트 선택";

  const moveFocus = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = [...(rootRef.current?.querySelectorAll<HTMLElement>("[data-switcher-item]") ?? [])];
    if (items.length === 0) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "ArrowDown" ? index + 1 : index - 1;
    items[Math.max(0, Math.min(items.length - 1, next))]?.focus();
  };

  return (
    <div ref={rootRef} className="relative flex items-center gap-1" data-project-switcher="true">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="project-switcher"
        aria-label={current ? `프로젝트 변경: ${current.name}` : "프로젝트 선택"}
        onClick={() => {
          setQuery("");
          setOpen((value) => !value);
        }}
        className="tap-target flex max-w-[260px] min-w-0 items-center gap-1.5 rounded-md border border-line-strong px-3 text-body font-semibold hover:bg-sunk"
      >
        <span className="truncate">{label}</span>
        <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className={`size-3 shrink-0 text-ink-muted ${open ? "rotate-180" : ""}`}>
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
      {current && (
        <Link
          href={siteSettingsHref(current.siteId)}
          aria-label="프로젝트 설정"
          title="프로젝트 설정"
          aria-current={search?.get("section") === "manage" ? "page" : undefined}
          className={`tap-target grid size-9 place-items-center rounded-md hover:bg-sunk ${search?.get("section") === "manage" ? "bg-sunk text-ink-1" : "text-ink-2"}`}
        >
          <NavIcon name="settings" className="size-4" />
        </Link>
      )}

      {open && (
        <div
          id="project-switcher"
          role="dialog"
          aria-label="프로젝트 변경"
          onKeyDown={moveFocus}
          className="absolute top-full left-0 z-[60] mt-1.5 w-[320px] rounded-lg border border-line bg-surface p-2 text-ink-1 shadow-xl"
        >
          <label htmlFor="project-switcher-search" className="sr-only">프로젝트 검색</label>
          <input
            id="project-switcher-search"
            type="search"
            autoFocus
            autoComplete="off"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="프로젝트 검색"
            className="input mb-1.5 w-full"
          />
          <ul className="flex max-h-[min(320px,calc(100vh-160px))] flex-col gap-0.5 overflow-y-auto">
            {shown.map((site) => {
              const content = (
                <>
                  <span aria-hidden="true" className="grid size-6 flex-none place-items-center rounded bg-sunk text-micro font-bold text-ink-2">
                    {siteMark(site.name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-caption font-semibold" title={site.name}>{siteShortName(site.name)}</span>
                    <span className="mt-0.5 block text-micro text-ink-muted">{SITE_STATUS_LABEL[site.status].label}</span>
                  </span>
                </>
              );
              return (
                <li key={site.siteId}>
                  {site.siteId === siteId ? (
                    <button
                      type="button"
                      data-switcher-item="true"
                      aria-current="true"
                      onClick={() => close()}
                      className="flex w-full items-start gap-2 rounded-md bg-sunk px-2 py-2 text-left"
                    >
                      {content}
                      <span aria-hidden="true" className="mt-1 text-micro text-mid-ink">✓</span>
                      <span className="sr-only">현재 프로젝트</span>
                    </button>
                  ) : (
                    <Link
                      href={projectSwitchHref(site.siteId, section)}
                      data-switcher-item="true"
                      onClick={() => close(false)}
                      className="flex w-full items-start gap-2 rounded-md px-2 py-2 text-left hover:bg-sunk"
                    >
                      {content}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
          {shown.length === 0 && (
            <p role="status" className="px-2 py-3 text-caption text-ink-2">
              {sites.length === 0 ? "접근할 수 있는 프로젝트가 없습니다." : "검색과 맞는 프로젝트가 없습니다."}
            </p>
          )}
          <Link
            href="/sites"
            data-switcher-item="true"
            onClick={() => close(false)}
            className="mt-1.5 flex items-center justify-between border-t border-line px-2 py-2 text-caption text-ink-2 hover:text-ink-1"
          >
            <span>전체 프로젝트 ({sites.length})</span>
            <span aria-hidden="true">→</span>
          </Link>
        </div>
      )}
    </div>
  );
}
