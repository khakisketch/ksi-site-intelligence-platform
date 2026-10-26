"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";

import { useSidebarSites } from "./SiteListContext";
import {
  siteMark,
  siteShortName,
  siteSwitchHref,
  type SiteSection,
} from "./site-context";

/**
 * Mobile site switcher — the site header's compact entry point below lg.
 *
 * Desktop already has the full rail (dense screens) or the viewer layer panel
 * (site 공간/자료). Below lg neither exists, so this sheet is the one place to
 * change the current site while preserving the active section. It renders no
 * new data and reuses the same minimal site summaries and route helpers.
 */
export function MobileSiteSwitcher({
  siteId,
  section,
}: {
  siteId: string;
  section: SiteSection | null;
}) {
  const sites = useSidebarSites();
  const current = sites.find((site) => site.siteId === siteId) ?? null;
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    sheetRef.current?.querySelector<HTMLElement>("[data-site-option]")?.focus();
  }, [open]);

  if (!current || sites.length < 2) return null;

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls="mobile-site-switcher"
        aria-label={`현장 변경: ${current.name}`}
        onClick={() => setOpen(true)}
        className="tap-target inline-flex h-9 shrink-0 items-center gap-1 rounded-md border border-line bg-surface px-2 text-[11.5px] font-semibold text-ink-2 hover:bg-sunk lg:hidden"
      >
        <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="size-4">
          <path d="M4 7h11l-2.5-2.5M16 13H5l2.5 2.5" />
        </svg>
        <span className="hidden sm:inline">현장 변경</span>
      </button>

      {open && createPortal(
        <div className="fixed inset-0 z-[70] lg:hidden">
          <button
            type="button"
            aria-label="현장 변경 닫기"
            onClick={close}
            className="absolute inset-0 bg-black/35"
          />
          <div
            ref={sheetRef}
            id="mobile-site-switcher"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mobile-site-switcher-title"
            className="absolute inset-x-2 bottom-[calc(var(--mobile-bottom-nav-clearance)+8px)] flex max-h-[min(70vh,560px)] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-xl"
          >
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-4 py-3">
              <h3 id="mobile-site-switcher-title" className="text-[14px] font-bold">현장 변경</h3>
              <button
                type="button"
                onClick={close}
                className="tap-target rounded-md px-2 py-1 text-[12px] font-semibold text-ink-2 hover:bg-sunk"
              >
                닫기
              </button>
            </div>
            <ul className="min-h-0 flex-1 overflow-y-auto p-2">
              {sites.map((site) => {
                const content = (
                  <>
                    <span
                      aria-hidden="true"
                      className="grid size-8 flex-none place-items-center rounded-md bg-sunk text-[11px] font-bold text-ink-2"
                    >
                      {siteMark(site.name)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12.5px] font-semibold" title={site.name}>
                        {siteShortName(site.name)}
                      </span>
                      <span className="mt-0.5 block text-[10.5px] text-ink-muted">
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
                        data-site-option="true"
                        onClick={close}
                        className="flex w-full items-center gap-2.5 rounded-md bg-sunk px-2 py-2.5 text-left"
                      >
                        {content}
                        <span aria-hidden="true" className="text-[11px] text-mid-ink">✓</span>
                        <span className="sr-only">현재 현장</span>
                      </button>
                    ) : (
                      <Link
                        href={siteSwitchHref(site.siteId, section)}
                        data-site-option="true"
                        onClick={close}
                        className="flex w-full items-center gap-2.5 rounded-md px-2 py-2.5 text-left hover:bg-sunk"
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
              onClick={close}
              className="flex shrink-0 items-center justify-between border-t border-line px-4 py-3 text-[12px] font-semibold text-ink-2 hover:bg-sunk"
            >
              <span>전체 현장</span>
              <span aria-hidden="true">→</span>
            </Link>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
