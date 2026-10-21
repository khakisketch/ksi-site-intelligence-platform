"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  filterPaletteItems,
  moveActiveIndex,
  type PaletteItem,
} from "./palette-items";
import { parseScopedNavQuery, parseSiteNavBridge } from "@/lib/operator-journey";
import { useCommandModifierLabel } from "./command-modifier";
import { resolveShortcut } from "./shortcuts";
import { contextPaletteItems } from "./context-palette";

/** 사이드바의 검색 버튼이 팔레트를 여는 신호. 컨텍스트 대신 이벤트를 쓰는 이유는
 *  셸의 절반이 서버 컴포넌트라, 프로바이더로 감싸면 그 경계가 통째로 클라이언트가
 *  되기 때문이다(레일·상단바가 서버에서 세션·집계를 읽는 구조를 깨뜨린다). */
export const PALETTE_OPEN_EVENT = "ksi:palette-open";

function KeyCap({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="tabular rounded border border-line-strong bg-surface px-1.5 py-0.5 font-mono text-[11.5px] text-ink-2">
      {children}
    </kbd>
  );
}

export function CommandPalette({ items }: { items: PaletteItem[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const commandModifier = useCommandModifierLabel();
  const [open, setOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  // 현재 현장 범위(작업구역·관측)는 열 때마다 주소창에서 읽는다. 브라우저
  // 기록·localStorage에 남기지 않으며, 받는 화면이 서버 목록과 재대조한다.
  const [scopeSearch, setScopeSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  // 포커스 복원용 — 팔레트를 연 시점에 포커스를 갖고 있던 트리거(사이드바·상단바 버튼,
  // 단축키 입력 자리)를 닫을 때 되돌린다. 키보드 사용자가 "어디에 있는지"를 잃지 않게.
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const listboxId = "ksi-palette-listbox";

  const results = useMemo(
    () => filterPaletteItems([...contextPaletteItems(items, pathname ?? "", scopeSearch), ...items], query),
    [items, pathname, query, scopeSearch],
  );
  const scopedSite = scopeSearch ? parseScopedNavQuery(scopeSearch) : null;
  const shortcutRows: Array<{ keys: string[]; desc: string }> = [
    { keys: [commandModifier, "K"], desc: "검색 · 이동 팔레트 열기" },
    { keys: ["?"], desc: "이 도움말 열기" },
    { keys: ["Esc"], desc: "팔레트 · 도움말 닫기" },
    { keys: ["↑", "↓"], desc: "팔레트 항목 이동" },
    { keys: ["Enter"], desc: "선택한 항목으로 이동" },
  ];

  const close = useCallback(() => {
    setOpen(false);
    setHelpOpen(false);
  }, []);

  // 서버 확인 범위의 읽기 전용 브리지 — 현장 헤더가 싣는다. URL 쿼리에는
  // 없는 bare deep link(분석 기록 직접 연결 등)에서도 헤더와 같은 목적지로
  // 간다. 판정이 아니라 힌트이며, 받는 화면이 서버 목록과 재대조한다.
  function readSiteNavBridge(): { siteId: string; workAreaId: string | null; assetRef: string | null } | null {
    if (typeof document === "undefined") return null;
    const root = document.querySelector('header[data-site-nav="true"]');
    if (!(root instanceof HTMLElement)) return null;
    return parseSiteNavBridge({
      siteId: root.dataset.siteId,
      workAreaId: root.dataset.workAreaId,
      assetRef: root.dataset.assetRef,
    });
  }

  const openPalette = useCallback(() => {
    setHelpOpen(false);
    setOpen(true);
    setQuery("");
    setActive(0);
    const search = typeof window === "undefined" ? "" : window.location.search;
    const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
    const explicitAreas = params.getAll("workAreaId");
    const explicitAssets = params.getAll("assetRef");
    const urlScope = parseScopedNavQuery(search);
    // 명시된 URL 범위를 조용히 덮어쓰지 않는다 — 브리지는 빈칸만 메운다.
    // - bare deep link(구역 없음): 서버 확인 브리지가 구역·관측을 모두 메운다.
    // - 구역만 있고 관측 없음: 같은 구역의 헤더 확인 관측만 메운다. 명시된
    //   관측(깨진 값·빈값·복수 포함)이 있으면 손대지 않고 도착 화면이 닫는다.
    // - 다른 구역·사이트의 관측은 절대 가져오지 않는다.
    const bridge = readSiteNavBridge();
    const path = pathname ?? "";
    const bridgeUsable = (() => {
      if (!bridge || !bridge.workAreaId) return null;
      const siteHref = `/sites/${encodeURIComponent(bridge.siteId)}`;
      const authorized = items.some((item) => item.group === "현장" && item.href === siteHref);
      if (!authorized) return null;
      if (!(path === siteHref || path.startsWith(`${siteHref}/`))) return null;
      return bridge;
    })();
    if (urlScope.workAreaId && explicitAssets.length === 0 && bridgeUsable?.workAreaId === urlScope.workAreaId && bridgeUsable.assetRef) {
      setScopeSearch(`?workAreaId=${encodeURIComponent(urlScope.workAreaId)}&assetRef=${encodeURIComponent(bridgeUsable.assetRef)}`);
      return;
    }
    if (!urlScope.workAreaId && explicitAreas.length === 0 && bridgeUsable?.workAreaId) {
      const filled = new URLSearchParams();
      filled.set("workAreaId", bridgeUsable.workAreaId);
      if (bridgeUsable.assetRef) filled.set("assetRef", bridgeUsable.assetRef);
      setScopeSearch(`?${filled.toString()}`);
      return;
    }
    setScopeSearch(search);
  }, [items, pathname]);

  const isOpen = open || helpOpen;

  // 전역 단축키 — 판정은 순수 함수(shortcuts.ts)가 하고 여기서는 결과만 실행한다.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const action = resolveShortcut({
        key: event.key,
        metaKey: event.metaKey,
        ctrlKey: event.ctrlKey,
        altKey: event.altKey,
        target: event.target as HTMLElement | null,
      });
      if (action === "palette") {
        event.preventDefault();
        openPalette();
      } else if (action === "help") {
        event.preventDefault();
        setOpen(false);
        setHelpOpen((prev) => !prev);
      } else if (action === "close") {
        close();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close, openPalette]);

  useEffect(() => {
    function onOpenRequest() {
      openPalette();
    }
    window.addEventListener(PALETTE_OPEN_EVENT, onOpenRequest);
    return () => window.removeEventListener(PALETTE_OPEN_EVENT, onOpenRequest);
  }, [openPalette]);

  // 열림 전환에만 트리거 포커스를 기억한다(닫힘→열림 경계). 팔레트 안에서 이동한
  // 포커스를 덮어쓰면 닫을 때 언마운트된 노드로 복원하려 한다. 닫힘 전환에는
  // 기억해 둔 트리거로 포커스를 되돌린다 — 키보드 사용자가 위치를 잃지 않게.
  const prevOpenRef = useRef(false);
  useEffect(() => {
    const wasOpen = prevOpenRef.current;
    prevOpenRef.current = isOpen;
    if (isOpen && !wasOpen) {
      restoreFocusRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    if (!isOpen && wasOpen) {
      restoreFocusRef.current?.focus?.();
      restoreFocusRef.current = null;
    }
  }, [isOpen]);

  // 초기 포커스 — 검색 모드는 입력창, 도움말 모드는 닫기 버튼. 도움말은 목록이
  // 없어 입력창에 두면 Tab 첫 정지가 허공이 된다.
  useEffect(() => {
    if (!isOpen) return;
    if (helpOpen) closeButtonRef.current?.focus();
    else inputRef.current?.focus();
  }, [isOpen, helpOpen]);

  // 배경 스크롤 잠금 — 모달이 열린 동안 뒷면이 밀리지 않게. body 만 잠그면
  // 부족하다: 데스크톱(lg+)에서는 <main id="main-content"> 이 별도 스크롤
  // 컨테이너라 그대로 밀린다(layout.tsx). 세 자리(body·html·main)의 이전 값을
  // 기억해 복원한다. main 이 없으면(셸 밖 렌더) 조용히 건너뛴다.
  useEffect(() => {
    if (!isOpen) return;
    const main = document.getElementById("main-content");
    const targets = [document.body, document.documentElement, ...(main ? [main] : [])];
    const prev = targets.map((node) => node.style.overflow);
    targets.forEach((node) => {
      node.style.overflow = "hidden";
    });
    return () => {
      targets.forEach((node, index) => {
        node.style.overflow = prev[index];
      });
    };
  }, [isOpen]);

  // 배경 비활성화 — 오버레이의 뒷면 형제(셸 본문)를 inert 로 잠가 뒷면으로의
  // Tab·AT·프로그래밍 포커스와 포인터 조작을 막는다. 기존 inert 값을 기억해
  // 닫을 때 그대로 복원한다(원래 inert 였던 형제는 inert 로 둔다).
  useEffect(() => {
    if (!isOpen) return;
    const overlay = overlayRef.current;
    const parent = overlay?.parentElement;
    if (!parent) return;
    const siblings = Array.from(parent.children).filter((node) => node !== overlay);
    const prev = siblings.map((node) => (node as HTMLElement).inert);
    siblings.forEach((node) => {
      (node as HTMLElement).inert = true;
    });
    return () => {
      siblings.forEach((node, index) => {
        (node as HTMLElement).inert = prev[index];
      });
    };
  }, [isOpen]);

  // 포커스 회수 — inert 를 강제하지 않는 AT·오래된 브라우저에서 뒷면으로 간
  // 포커스를 다이얼로그로 되돌린다. 닫힘 복원(trigger.focus)과는 겹치지 않는다:
  // 이 리스너는 열린 동안만 살아있고, 복원은 닫힘 전환 효과에서 일어난다.
  useEffect(() => {
    if (!isOpen) return;
    function onFocusIn(event: FocusEvent) {
      const root = dialogRef.current;
      if (!root) return;
      if (event.target instanceof HTMLElement && !root.contains(event.target)) {
        (helpOpen ? closeButtonRef.current : inputRef.current)?.focus();
      }
    }
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, [isOpen, helpOpen]);

  // 선택 항목이 보이는 자리에 있게 한다 — 키보드로만 훑을 때 화면 밖으로 나가면
  // "아무 일도 안 일어난다"로 읽힌다.
  useEffect(() => {
    if (!open) return;
    const node = listRef.current?.children[active] as HTMLElement | undefined;
    node?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  function goTo(item: PaletteItem | undefined) {
    if (!item) return;
    close();
    router.push(item.href);
  }

  function onInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((prev) => moveActiveIndex(prev, 1, results.length));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((prev) => moveActiveIndex(prev, -1, results.length));
    } else if (event.key === "Enter") {
      event.preventDefault();
      goTo(results[active]);
    }
  }

  // Tab 트랩 — 모달이 열린 동안 Tab/Shift+Tab 이 뒷면으로 새지 않게 다이얼로그
  // 안에서 순환시킨다. 정지 목록에 없는 곳에 포커스가 있으면(결과 버튼을 포인터로
  // 눌러 tabindex -1 버튼에 포커스가 갔거나, 프로그래밍·AT 가 뒷면에 뒀거나)
  // 방향에 맞는 첫/마지막 정지로 회수한다 — current===last 만 보는 검사는
  // 그 경우를 놓치고 뒷면으로 샌다. 결과 버튼은 tabindex -1 로 정지에서
  // 제외한다(콤보박스 패턴: 목록 이동은 ↑↓가 맡고 포커스는 입력창에 둔다).
  function onDialogKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return;
    const root = dialogRef.current;
    if (!root) return;
    const stops = Array.from(
      root.querySelectorAll<HTMLElement>("button:not([disabled]), input, a[href]"),
    ).filter((node) => node.tabIndex >= 0);
    if (stops.length === 0) {
      event.preventDefault();
      return;
    }
    const first = stops[0];
    const last = stops[stops.length - 1];
    const index = stops.indexOf(document.activeElement as HTMLElement);
    if (index === -1) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
      return;
    }
    if (event.shiftKey && index === 0) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && index === stops.length - 1) {
      event.preventDefault();
      first.focus();
    }
  }

  const activeId = results.length > 0 ? `ksi-palette-option-${active}` : undefined;

  if (!open && !helpOpen) return null;

  return (
    <div
      ref={overlayRef}
      className="print:hidden fixed inset-0 z-50 flex max-h-dvh justify-center overflow-y-auto bg-black/40 px-4 py-[4dvh]"
      // 바깥을 누르면 닫힌다. 안쪽 클릭이 여기까지 올라오지 않게 컨테이너에서 멈춘다.
      // 가상 키보드가 올라와 보이는 높이가 줄면 오버레이 자체가 스크롤되게 해
      // 푸터가 화면 밖으로 잘려 닫을 수단을 잃지 않게 한다(my-auto + max-h-full).
      onMouseDown={close}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={helpOpen ? "단축키 도움말" : "검색 및 이동"}
        className="ksi-rise my-auto max-h-full w-full max-w-[560px] flex-none overflow-hidden rounded-[10px] border border-line bg-surface shadow-[0_24px_64px_rgba(0,0,0,.4)]"
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={onDialogKeyDown}
      >
        {helpOpen ? (
          <div className="p-4">
            <h2 className="mb-3 text-[14px] font-bold">단축키</h2>
            <ul className="flex flex-col gap-2">
              {shortcutRows.map((row) => (
                <li key={row.desc} className="flex items-center gap-3 text-[13px]">
                  <span className="flex flex-none gap-1">
                    {row.keys.map((key) => (
                      <KeyCap key={key}>{key}</KeyCap>
                    ))}
                  </span>
                  <span className="break-keep text-ink-2">{row.desc}</span>
                </li>
              ))}
            </ul>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={close}
              className="btn tap-target mt-4 min-h-11 w-full"
            >
              닫기
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2.5 border-b border-line px-3.5">
              <svg
                aria-hidden="true"
                width="15"
                height="15"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                className="flex-none text-ink-muted"
              >
                <circle cx="7" cy="7" r="4.4" />
                <path d="M10.4 10.4 14 14" />
              </svg>
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setActive(0);
                }}
                onKeyDown={onInputKeyDown}
                placeholder="화면 · 현장 검색"
                aria-label="화면 또는 현장 검색"
                role="combobox"
                aria-expanded={results.length > 0}
                aria-controls={listboxId}
                aria-activedescendant={activeId}
                aria-autocomplete="list"
                className="min-h-11 w-full border-0 bg-transparent py-3 text-[14px] outline-none placeholder:text-ink-muted"
              />
              {/* 보이는 닫기 — 백드롭 클릭만으로는 터치·키보드 사용자가 닫을 수단을
                  찾기 어렵다. 44px 탭 타겟. */}
              <button
                ref={closeButtonRef}
                type="button"
                onClick={close}
                aria-label="팔레트 닫기"
                className="tap-target my-1 flex min-h-11 min-w-11 flex-none items-center justify-center rounded-md text-ink-2 hover:bg-sunk"
              >
                <svg
                  aria-hidden="true"
                  width="14"
                  height="14"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                >
                  <path d="M4 4l8 8M12 4l-8 8" />
                </svg>
              </button>
            </div>
            {/* 정직한 범위 — 팔레트는 셸이 쥔 화면·현장 이름만 찾는다. 파일·작업
                기록은 각 현장 화면에서 확인한다(없는 범위를 암시하지 않는다).
                현재 현장 범위(작업구역·관측)가 있으면 같은 범위로 이동한다. */}
            <p className="border-b border-line bg-sunk px-3.5 py-1.5 text-[11.5px] break-keep text-ink-muted">
              화면·현장 이름 검색이며 파일·작업 기록은 각 현장에서 확인
              {scopedSite?.workAreaId ? " · 현재 현장 범위를 함께 이동합니다" : ""}
            </p>

            {/* 결과 목록은 항상 렌더한다 — 0건일 때 목록을 치워버리면 입력창의
                aria-controls 가 존재하지 않는 id 를 가리킨다. 빈 메시지는
                리스트박스 안의 표현용 항목으로 둔다. */}
            <ul
              ref={listRef}
              id={listboxId}
              role="listbox"
              aria-label="검색 결과"
              className="max-h-[46dvh] overflow-y-auto py-1.5"
            >
              {results.length === 0 ? (
                <li role="presentation" className="px-4 py-8 text-center text-[13px] break-keep text-ink-muted">
                  일치하는 화면이나 현장이 없습니다.
                </li>
              ) : (
                results.map((item, index) => (
                  // li 는 표현용으로 투명화하고 버튼이 role=option 을 진다 —
                  // li[option] 안에 button 을 넣으면 중첩 인터랙티브로 걸린다.
                  <li key={item.key} role="presentation">
                    <button
                      type="button"
                      id={`ksi-palette-option-${index}`}
                      role="option"
                      aria-selected={index === active}
                      tabIndex={-1}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => goTo(item)}
                      className={`tap-target flex w-full items-center gap-3 px-3.5 text-left text-[13px] ${
                        index === active ? "bg-accent-tint" : ""
                      }`}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{item.label}</span>
                        {item.hint && (
                          <span className="block truncate text-[12px] text-ink-muted">
                            {item.hint}
                          </span>
                        )}
                      </span>
                      {item.pending && (
                        <span className="flex-none rounded bg-sunk px-1.5 py-px text-[11.5px] text-ink-2">
                          준비 중
                        </span>
                      )}
                      <span className="flex-none text-[11.5px] text-ink-muted">{item.group}</span>
                    </button>
                  </li>
                ))
              )}
            </ul>

            <div className="flex items-center gap-2 border-t border-line bg-sunk px-3.5 py-2 text-[11.5px] text-ink-muted">
              <KeyCap>↑</KeyCap>
              <KeyCap>↓</KeyCap>
              <span>이동</span>
              <KeyCap>Enter</KeyCap>
              <span>열기</span>
              <span className="flex-1" />
              <KeyCap>?</KeyCap>
              <span>단축키</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
