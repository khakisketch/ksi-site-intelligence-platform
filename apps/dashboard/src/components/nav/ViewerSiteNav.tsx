"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";

import { useAccountDisplayLock } from "./AccountDisplayBoundary";
import { NavIcon } from "./NavIcon";
import { useSidebarSites } from "./SiteListContext";
import {
  SITE_CONTEXT_SECTIONS,
  resolveSiteId,
  resolveSiteSection,
  siteMark,
  siteSectionHref,
  siteShortName,
  siteSwitchHref,
} from "./site-context";

/**
 * Viewer layer-panel header — current site, site switcher, and the four site
 * sections in the compact surface. This is the site context that the full
 * desktop rail owns on dense screens; the viewer rail (56px) cannot hold it.
 *
 * Reuses the same route helpers and the same minimal site summaries as
 * `SiteContextNav`. No new routes, permissions, or fetching are introduced.
 * The popover is portalled so the floating panel's overflow cannot clip it.
 */
export function ViewerSiteNav() {
  const accountDisplay = useAccountDisplayLock();
  const pathname = usePathname() ?? "";
  const searchParams = useSearchParams();
  const sites = useSidebarSites();
  const siteId = resolveSiteId(pathname);
  const current = siteId ? sites.find((site) => site.siteId === siteId) ?? null : null;
  const activeSection = resolveSiteSection(pathname, searchParams);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
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
      if (accountDisplay?.locked() || event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    const onViewportChange = () => setOpen(false);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onViewportChange);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onViewportChange);
    };
  }, [accountDisplay, open]);

  useEffect(() => {
    if (!open || !position) return;
    popoverRef.current?.querySelector<HTMLElement>("a, button")?.focus();
  }, [open, position]);

  if (!siteId || !current) return null;

  const canSwitch = sites.length > 1;
  const currentName = siteShortName(current.name);
  const sitePath = `/sites/${encodeURIComponent(current.siteId)}`;

  const openSwitcher = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    setPortalTarget(trigger.closest<HTMLElement>("[data-account-display-root]") ?? document.body);
    const rect = trigger.getBoundingClientRect();
    setPosition({
      top: Math.max(8, rect.bottom + 6),
      left: Math.min(rect.left, Math.max(8, window.innerWidth - 288)),
    });
    setOpen((value) => !value);
  };

  const closeSwitcher = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div ref={rootRef} className="border-b border-line bg-surface px-2.5 pt-2.5 pb-2" data-viewer-site-nav="true">
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="grid size-[27px] flex-none place-items-center rounded-md bg-sidebar text-[10px] font-bold text-sidebar-text ring-1 ring-black/10"
        >
          {siteMark(current.name)}
        </span>
        <div className="min-w-0 flex-1">
          {canSwitch ? (
            <button
              ref={triggerRef}
              type="button"
              aria-expanded={open}
              aria-controls="viewer-site-switcher"
              aria-haspopup="dialog"
              aria-label={`현장 변경: ${current.name}`}
              onClick={openSwitcher}
              className="tap-target flex w-full min-w-0 items-center gap-1 rounded text-left hover:bg-sunk"
            >
              <span className="min-w-0">
                <span className="block truncate text-[12.5px] leading-tight font-bold tracking-tight" title={current.name}>
                  {currentName}
                </span>
                <span className="mt-0.5 block text-[10px] leading-tight text-ink-muted">
                  {SITE_STATUS_LABEL[current.status].label}
                </span>
              </span>
              <svg
                aria-hidden="true"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                className={`ml-auto size-3 flex-none text-ink-muted transition-transform ${open ? "rotate-180" : ""}`}
              >
                <path d="m4 6 4 4 4-4" />
              </svg>
            </button>
          ) : (
            <span className="block min-w-0">
              <span className="block truncate text-[12.5px] leading-tight font-bold tracking-tight" title={current.name}>
                {currentName}
              </span>
              <span className="mt-0.5 block text-[10px] leading-tight text-ink-muted">
                {SITE_STATUS_LABEL[current.status].label}
              </span>
            </span>
          )}
        </div>
        <Link
          href={`${sitePath}?section=manage`}
          aria-label="현장 설정"
          className="tap-target flex min-h-8 shrink-0 items-center rounded-md px-1.5 text-[10.5px] font-semibold text-ink-2 hover:bg-sunk"
        >
          설정
        </Link>
      </div>

      <nav aria-label="현재 현장 메뉴" className="mt-2 grid grid-cols-4 gap-0.5 rounded-md border border-line bg-sunk p-0.5">
        {SITE_CONTEXT_SECTIONS.map((section) => {
          const active = section.key === activeSection;
          return (
            <Link
              key={section.key}
              href={siteSectionHref(current.siteId, section.key)}
              aria-current={active ? "page" : undefined}
              className={`tap-target flex min-w-0 flex-col items-center gap-0.5 rounded px-0.5 py-1 text-[10px] break-keep transition-colors ${
                active
                  ? "bg-surface font-semibold text-ink-1 shadow-sm"
                  : "text-ink-2 hover:bg-surface/70"
              }`}
            >
              <NavIcon name={section.icon} className="size-[13px] flex-none opacity-80" />
              <span className="truncate">{section.label}</span>
            </Link>
          );
        })}
      </nav>

      {open && position && portalTarget && createPortal(
        <div
          ref={popoverRef}
          id="viewer-site-switcher"
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
        portalTarget,
      )}
    </div>
  );
}
