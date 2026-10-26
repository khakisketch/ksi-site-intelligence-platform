"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";

import { NavIcon } from "./NavIcon";
import {
  SITE_CONTEXT_SECTIONS,
  resolveSiteId,
  resolveSiteSection,
  siteMark,
  siteSectionHref,
  siteShortName,
  siteSwitchHref,
  type SidebarSite,
} from "./site-context";

/**
 * 데스크톱 레일의 현재 현장 블록.
 *
 * - 현재 현장 **하나만** 펼친다. 모든 현장을 트리로 늘어놓지 않는다.
 * - 현장명은 전환기다. 다른 현장을 고르면 지금 보고 있는 영역을 유지하고,
 *   그 영역이 없는 하위 화면이면 작업공간으로 돌아간다.
 * - 링크는 기존 Site 라우트만 쓴다. 새 저장소·API·권한을 만들지 않는다.
 * - 전환 팝오버는 사이드바의 overflow 밖에 두기 위해 portal로 띄운다.
 */
export function SiteContextNav({ sites }: { sites: readonly SidebarSite[] }) {
  const pathname = usePathname() ?? "";
  const searchParams = useSearchParams();
  const siteId = resolveSiteId(pathname);
  const current = siteId ? sites.find((site) => site.siteId === siteId) ?? null : null;
  const activeSection = resolveSiteSection(pathname, searchParams);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (rootRef.current?.contains(target) || popoverRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    const onViewportChange = () => setOpen(false);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open || !position) return;
    popoverRef.current?.querySelector<HTMLElement>("a, button")?.focus();
  }, [open, position]);

  if (!siteId || !current) return null;

  const canSwitch = sites.length > 1;
  const currentName = siteShortName(current.name);

  const openSwitcher = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    setPosition({
      top: Math.max(8, rect.top),
      left: Math.min(rect.right + 8, Math.max(8, window.innerWidth - 288)),
    });
    setOpen((value) => !value);
  };

  const closeSwitcher = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div
      ref={rootRef}
      className="relative mx-0.5 mt-1 mb-1 rounded-lg border border-white/10 bg-white/[0.045] p-1.5"
      data-site-context="true"
    >
      {canSwitch ? (
        <button
          ref={triggerRef}
          type="button"
          aria-expanded={open}
          aria-controls="site-context-switcher"
          aria-haspopup="dialog"
          aria-label={`현장 변경: ${current.name}`}
          onClick={openSwitcher}
          className="tap-target flex w-full items-start gap-2 rounded-md px-1.5 py-1.5 text-left hover:bg-sidebar-hover"
        >
          <span
            aria-hidden="true"
            className="mt-0.5 grid size-[22px] flex-none place-items-center rounded bg-sidebar-active text-[10px] font-bold text-sidebar-active-ink ring-1 ring-white/10"
          >
            {siteMark(current.name)}
          </span>
          <span className="min-w-0 flex-1">
            <span
              className="line-clamp-2 block text-[12px] leading-snug font-semibold tracking-tight break-keep text-sidebar-text"
              title={current.name}
            >
              {currentName}
            </span>
            <span className="mt-0.5 block text-[10px] text-[#b6c0bb]">
              {SITE_STATUS_LABEL[current.status].label}
            </span>
          </span>
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            className={`mt-1 size-3 flex-none text-sidebar-muted transition-transform ${open ? "rotate-180" : ""}`}
          >
            <path d="m4 6 4 4 4-4" />
          </svg>
        </button>
      ) : (
        <div className="flex items-start gap-2 px-1.5 py-1.5">
          <span
            aria-hidden="true"
            className="mt-0.5 grid size-[22px] flex-none place-items-center rounded bg-sidebar-active text-[10px] font-bold text-sidebar-active-ink ring-1 ring-white/10"
          >
            {siteMark(current.name)}
          </span>
          <span className="min-w-0">
            <span
              className="line-clamp-2 block text-[12px] leading-snug font-semibold tracking-tight break-keep text-sidebar-text"
              title={current.name}
            >
              {currentName}
            </span>
            <span className="mt-0.5 block text-[10px] text-[#b6c0bb]">
              {SITE_STATUS_LABEL[current.status].label}
            </span>
          </span>
        </div>
      )}

      <nav
        aria-label="현재 현장 메뉴"
        className="mt-1 flex flex-col gap-0.5 border-t border-white/10 pt-1"
      >
        {SITE_CONTEXT_SECTIONS.map((section) => {
          const active = section.key === activeSection;
          return (
            <Link
              key={section.key}
              href={siteSectionHref(current.siteId, section.key)}
              aria-current={active ? "page" : undefined}
              className={`tap-target flex min-h-8 items-center gap-2 rounded-md px-2 text-[12px] transition-colors ${
                active
                  ? "bg-sidebar-active font-semibold text-sidebar-active-ink"
                  : "text-sidebar-text hover:bg-sidebar-hover"
              }`}
            >
              <NavIcon name={section.icon} className="size-[15px] flex-none opacity-80" />
              <span>{section.label}</span>
            </Link>
          );
        })}
      </nav>

      {open && position && createPortal(
        <div
          ref={popoverRef}
          id="site-context-switcher"
          role="dialog"
          aria-label="현장 변경"
          style={{ position: "fixed", top: position.top, left: position.left }}
          className="z-[80] w-[280px] rounded-lg border border-line bg-surface p-1.5 text-ink-1 shadow-xl"
        >
          <div className="flex items-center justify-between px-2 py-1.5 font-mono text-[10px] tracking-[0.06em] text-ink-muted uppercase">
            <span>현장 변경</span>
            <span>{sites.length}</span>
          </div>
          <ul className="flex max-h-[min(320px,calc(100vh-80px))] flex-col gap-0.5 overflow-y-auto">
            {sites.map((site) => {
              const content = (
                <>
                  <span
                    aria-hidden="true"
                    className="grid size-[24px] flex-none place-items-center rounded bg-sunk text-[10px] font-bold text-ink-2"
                  >
                    {siteMark(site.name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[11.5px] font-semibold" title={site.name}>{siteShortName(site.name)}</span>
                    <span className="mt-0.5 block text-[10px] text-ink-muted">
                      {SITE_STATUS_LABEL[site.status].label}
                    </span>
                  </span>
                </>
              );
              return (
                <li key={site.siteId}>
                  {site.siteId === current.siteId ? (
                    <button
                      type="button"
                      aria-current="true"
                      onClick={closeSwitcher}
                      className="flex w-full items-start gap-2 rounded-md bg-sunk px-2 py-2 text-left"
                    >
                      {content}
                      <span aria-hidden="true" className="mt-1 text-[11px] text-mid-ink">✓</span>
                      <span className="sr-only">현재 현장</span>
                    </button>
                  ) : (
                    <Link
                      href={siteSwitchHref(site.siteId, activeSection)}
                      onClick={closeSwitcher}
                      className="flex w-full items-start gap-2 rounded-md px-2 py-2 text-left hover:bg-sunk"
                    >
                      {content}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
          <Link
            href="/sites"
            onClick={closeSwitcher}
            className="mt-1 flex items-center justify-between border-t border-line px-2 py-2 text-[11.5px] text-ink-2 hover:text-ink-1"
          >
            <span>전체 현장</span>
            <span aria-hidden="true">→</span>
          </Link>
        </div>,
        document.body,
      )}
    </div>
  );
}
