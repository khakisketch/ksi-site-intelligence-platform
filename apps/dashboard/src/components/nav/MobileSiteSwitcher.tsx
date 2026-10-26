"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

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
 *
 * Modality is owned by native <dialog>.showModal() (same incumbent pattern as
 * AssetRequestDialog/ConfirmDialog): focus trap, Escape, and the top layer come
 * from the browser instead of a hand-rolled div + aria-modal sheet. The dialog
 * element itself is styled as the bottom sheet so the mobile appearance does
 * not change. Closing — selection, close button, backdrop, or native cancel —
 * returns focus to the element that opened the sheet. A resize to desktop or a
 * route/site change closes the sheet so a hidden modal can never keep trapping
 * the page. Escape is wired through the native onCancel React prop (not a
 * one-time DOM listener) so the contract survives later dialog remounts, and
 * losing membership (current site gone or fewer than 2 sites) closes without
 * reopening on restore.
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
  const dialogRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<Element | null>(null);
  const uid = useId();
  const titleId = `${uid}-mobile-site-switcher-title`;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      // fireEvent.click 은 jsdom 에서 포커스를 옮기지 않으므로, 실제 개봉자인
      // 트리거를 우선 기록한다(실 브라우저의 activeElement 와도 일치).
      openerRef.current = triggerRef.current ?? document.activeElement;
      try {
        if (!dialog.open) dialog.showModal();
      } catch {
        // jsdom 등 showModal 미지원 환경 — 렌더는 유지하고 포커스만 맞춘다.
      }
      // 현재 현장을 우선으로, 없으면 첫 옵션에 포커스를 둔다.
      const target =
        dialog.querySelector<HTMLElement>('[aria-current="true"]') ??
        dialog.querySelector<HTMLElement>("[data-site-option]");
      target?.focus();
    } else {
      try {
        if (dialog.open) dialog.close();
      } catch {
        // showModal 을 못 여는 환경에서는 닫을 것도 없다.
      }
      const opener = openerRef.current;
      openerRef.current = null;
      if (opener instanceof HTMLElement && opener.isConnected) {
        // 데스크톱으로 리사이즈되어 닫힌 뒤에는 lg:hidden 트리거로
        // 포커스를 돌리지 않는다(숨은 요소 포커스 방지).
        if (
          typeof window !== "undefined" &&
          typeof window.matchMedia === "function" &&
          window.matchMedia("(min-width: 1024px)").matches
        ) {
          return;
        }
        opener.focus();
      }
    }
  }, [open ]);

  // 데스크톱(lg 이상)으로 리사이즈되면 숨은 모달이 페이지를 가두지 않게 닫는다.
  useEffect(() => {
    if (!open) return;
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(min-width: 1024px)");
    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) setOpen(false);
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [open ]);

  // 경로·현장 이동 뒤에 이전 switcher 가 남지 않게 닫는다.
  // effect + setState 대신 렌더 중 비교(React 권장 "props 변경 시 state 조정")
  // 로 처리해 cascading 없이 다음 렌더에서 닫힌 상태를 낸다.
  const routeKey = `${siteId}|${String(section)}`;
  const [seenRoute, setSeenRoute] = useState(routeKey);
  if (seenRoute !== routeKey) {
    setSeenRoute(routeKey);
    if (open) setOpen(false);
  }

  // 열려 있는 동안 현재 현장이 목록에서 빠지거나 선택지가 2개 미만으로
  // 줄면 즉시 닫는다. early return(null)이 dialog 를 언마운트하므로 open 을
  // 그대로 두면 목록 복원 시 요청 없이 다시 열리는꼴이 된다 — 같은 렌더 중
  // 조정으로 open 을 거짓으로 굳혀 재오픈을 막는다.
  if ((!current || sites.length < 2) && open) setOpen(false);

  if (!current || sites.length < 2) return null;

  if (!current || sites.length < 2) return null;

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
        <span className="sm:hidden">변경</span>
        <span className="hidden sm:inline">현장 변경</span>
      </button>

      <dialog
        ref={dialogRef}
        id="mobile-site-switcher"
        aria-labelledby={titleId}
        onCancel={(event) => {
          // 네이티브 Escape — 기본 닫힘을 막고 상태로 닫는다.
          // DOM 리스너 effect([]) 대신 React prop 으로 묶어, dialog 가 나중에
          // (재)마운트돼도 Escape 계약이 유지된다.
          event.preventDefault();
          setOpen(false);
        }}
        onClick={(event) => {
          // 배경(백드롭) 클릭은 취소와 같다 — 현장 이동을 일으키지 않는다.
          if (event.target === dialogRef.current) setOpen(false);
        }}
        // 네이티브 top-layer 다이얼로그를 그대로 하단 시트처럼 둔다:
        // m-0 + fixed bottom 으로 UA 중앙 정렬을 걷어내고, ::backdrop 이
        // 배경 스크림을 맡는다. lg:hidden 은 닫힘 전 모바일 진입점과 짝을
        // 이루고, 실제 데스크톱 잔류 방지는 위 resize effect 가 맡는다.
        className="fixed inset-x-2 bottom-[calc(var(--mobile-bottom-nav-clearance,56px)+8px)] top-auto m-0 max-h-[min(70vh,560px)] w-auto flex-col overflow-hidden rounded-2xl border border-line bg-surface p-0 text-ink-1 shadow-xl backdrop:bg-black/35 open:flex lg:hidden"
      >
        {open && (
          <>
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-4 py-3">
              <h3 id={titleId} className="text-[14px] font-bold">현장 변경</h3>
              <button
                type="button"
                onClick={() => setOpen(false)}
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
                        onClick={() => setOpen(false)}
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
                        onClick={() => setOpen(false)}
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
              onClick={() => setOpen(false)}
              className="flex shrink-0 items-center justify-between border-t border-line px-4 py-3 text-[12px] font-semibold text-ink-2 hover:bg-sunk"
            >
              <span>전체 현장</span>
              <span aria-hidden="true">→</span>
            </Link>
          </>
        )}
      </dialog>
    </>
  );
}
