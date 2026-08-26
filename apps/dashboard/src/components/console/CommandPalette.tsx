"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  filterPaletteItems,
  moveActiveIndex,
  type PaletteItem,
} from "./palette-items";
import { useCommandModifierLabel } from "./command-modifier";
import { resolveShortcut } from "./shortcuts";

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
  const commandModifier = useCommandModifierLabel();
  const [open, setOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const results = useMemo(() => filterPaletteItems(items, query), [items, query]);
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

  const openPalette = useCallback(() => {
    setHelpOpen(false);
    setOpen(true);
    setQuery("");
    setActive(0);
  }, []);

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

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

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

  if (!open && !helpOpen) return null;

  return (
    <div
      className="print:hidden fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh]"
      // 바깥을 누르면 닫힌다. 안쪽 클릭이 여기까지 올라오지 않게 컨테이너에서 멈춘다.
      onMouseDown={close}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={helpOpen ? "단축키 도움말" : "검색 및 이동"}
        className="ksi-rise w-full max-w-[560px] overflow-hidden rounded-[10px] border border-line bg-surface shadow-[0_24px_64px_rgba(0,0,0,.4)]"
        onMouseDown={(event) => event.stopPropagation()}
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
            <button type="button" onClick={close} className="btn mt-4 w-full">
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
                className="min-h-11 w-full border-0 bg-transparent py-3 text-[14px] outline-none placeholder:text-ink-muted"
              />
            </div>

            {results.length === 0 ? (
              <p className="px-4 py-8 text-center text-[13px] break-keep text-ink-muted">
                일치하는 화면이나 현장이 없습니다.
              </p>
            ) : (
              <ul ref={listRef} className="max-h-[46vh] overflow-y-auto py-1.5">
                {results.map((item, index) => (
                  <li key={item.key}>
                    <button
                      type="button"
                      onMouseEnter={() => setActive(index)}
                      onClick={() => goTo(item)}
                      aria-current={index === active ? "true" : undefined}
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
                ))}
              </ul>
            )}

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
