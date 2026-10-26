"use client";

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

/**
 * 공간 작업환경 공유 오버레이 셸 — 실제 등록 자료 화면과
 * `/design-preview/materials` 예시 화면이 같은 머리/무대/드로어 관계를 쓴다.
 * 순수 배치만 맡으며, 권한·조회·선택 판정은 호출자가 둔다.
 *
 * - 무대는 가용 높이로 통째로 둔다. 왼쪽 목록과 오른쪽 정보는 무대 위에
 *   뜨는 드로어다 — 열어도 사진의 base bounding rect·칸 너비·카메라가
 *   바뀌지 않고, 다른 패널을 예측不能하게 숨기지도 않는다.
 * - 목록 드로어는 비모달이다: scrim 클릭·토글·Escape으로 닫히고, 닫으면
 *   포커스가 「목록」 단추로 돌아간다. 팔레트 등 바깥 포커스의 Escape에는
 *   간섭하지 않는다(드로어 안의 키 입력만 본다).
 * - 정보 드로어는 호출자의 URL/상태가 여닫는다. Escape은 예시의 상태 위임
 *   또는 실제 화면의 표시된 닫기 링크를 실행하며, URL 선택을 새로 만들지 않는다.
 * - 휴대폰에서는 두 칸이 경계 안에서 세로로 쌓이고 무대가 스크롤된다.
 *   가로 넘침을 만들지 않는다.
 *
 * Invariants: INV-020(좌표·시각 판정 없음 — 배치 전용)/INV-040(예시는 별도
 * 경로의 명시적 선택이며 실제 바이트의 fallback이 아니다 — 같은 셸을 써도
 * 바인딩·조회는 섞지 않는다)/INV-060·061(권한·이그레스 변경 없음).
 */
export function SpatialWorkbenchFrame({
  banner = null,
  contextBar,
  catalog,
  catalogLabel,
  stage,
  inspector = null,
  inspectorOpen = false,
  onCloseInspector,
  inspectorId,
  inspectorLabel,
  detailsHostId,
  defaultCatalogOpen = false,
  catalogFooter = null,
  catalogDismissLabel,
}: {
  /** 예시 경로의 고정 안내 등, 맥락막대 위에 두는 띠. 실제 경로는 두지 않는다. */
  banner?: ReactNode;
  /** 한 줄 맥락·모드 막대 — 구역·보기 방식·정보·등록만 둔다. 목록 토글은 셸이 앞에 둔다. */
  contextBar: ReactNode;
  /** 왼쪽 드로어 내용(목록 탐색). 열렸을 때만 렌더된다. */
  catalog: ReactNode;
  /** 목록 드로어 이름. */
  catalogLabel: string;
  /** 중앙 시각 무대 — 단일 또는 좌·우 독립 보기. 호출자가 높이를 채운다. */
  stage: ReactNode;
  /** 오른쪽 정보 드로어 내용 — 열렸을 때만 둔다. */
  inspector?: ReactNode;
  /** 정보 열림 — false면 자리를 차지하지 않는다. */
  inspectorOpen?: boolean;
  /** 초기 목록 열림 — 기본 닫힘. 명시적 사용자 토글 전 초기 상태용이다. */
  defaultCatalogOpen?: boolean;
  /**
   * 목록 시트 하단 요약 — 현재 선택이 무엇인지 시트 안에서 한 번 더 말한다.
   * 선택이 없으면 호출자가 넘기지 않는다.
   */
  catalogFooter?: ReactNode;
  /**
   * 목록 시트 하단 닫기 동작 이름. 예: `이 선택으로 보기`. 넘기면 단추를 두고,
   * 누르면 시트만 닫아 무대를 가리지 않는다. 선택 자체는 바꾸지 않는다.
   */
  catalogDismissLabel?: string;
  /** 예시 경로의 정보 닫기 위임. 없으면 Escape을 정보에 쓰지 않는다. */
  onCloseInspector?: () => void;
  /** 정보 영역 식별자·이름 — 열릴 때만 렌더된다. */
  inspectorId: string;
  inspectorLabel: string;
  /**
   * 정보 서랍 안의 항상-마운트 숨김 자리 식별자 — 무대 뷰어의 접힌 상세가
   * 포털로 들어가는 곳이다. 서랍이 닫혀도 마운트를 유지하므로 포털이
   * 사라지지 않고, 닫힘 상태에서는 display:none이라 포커스가 새지 않는다.
   * 주지 않으면 뷰어는 기존 자리 펼침을 그대로 둔다.
   */
  detailsHostId?: string;
}) {
  const showInspector = inspectorOpen && inspector !== null;
  const [catalogOpen, setCatalogOpen] = useState(defaultCatalogOpen);
  const rootRef = useRef<HTMLDivElement>(null);
  const catalogToggleRef = useRef<HTMLButtonElement>(null);
  const catalogRef = useRef<HTMLElement>(null);
  const inspectorRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const contextRef = useRef<HTMLDivElement>(null);
  const [drawerTop, setDrawerTop] = useState(8);
  const wasInspectorOpen = useRef(false);
  // Wide screens keep the inspector as a persistent right column; narrow screens
  // keep the existing overlay drawer and its close/focus contract. The media
  // query is client-only so SSR and the drawer tests keep their original DOM.
  const [wideInspector, setWideInspector] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(min-width: 1280px)");
    const update = () => setWideInspector(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  const persistentInspector = wideInspector && inspector !== null;
  const showInspectorPanel = showInspector || persistentInspector;

  useLayoutEffect(() => {
    const stageElement = stageRef.current;
    if (!stageElement || (!catalogOpen && !showInspector)) return;
    let observed: Element[] = [];
    const measure = () => {
      const desktop = typeof matchMedia !== "function" || matchMedia("(min-width: 1024px)").matches;
      if (!desktop) {
        // A narrow-screen catalog is a full-height sheet, not a desktop card
        // floating halfway down the viewport. It starts at the safe top edge;
        // the bottom-nav clearance keeps the sheet's actions reachable.
        setDrawerTop(8);
        return;
      }
      const base = stageElement.getBoundingClientRect();
      const controls = [...stageElement.querySelectorAll<HTMLElement>("[data-workbench-pane-controls]")];
      const wide = typeof matchMedia === "function" && matchMedia("(min-width: 768px)").matches;
      const firstPane = stageElement.querySelector("[data-workbench-pane]");
      const relevant = wide ? controls : controls.filter((element) => !firstPane || element.closest("[data-workbench-pane]") === firstPane);
      const bottom = relevant.reduce((value, element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 ? Math.max(value, box.bottom - base.top) : value;
      }, 0);
      setDrawerTop(Math.max(8, Math.ceil(bottom + 8)));
    };
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    const bind = () => {
      for (const element of observed) resize?.unobserve(element);
      observed = [stageElement, ...(contextRef.current ? [contextRef.current] : []), ...stageElement.querySelectorAll("[data-workbench-pane-controls]")];
      for (const element of observed) resize?.observe(element);
      measure();
    };
    bind();
    const mutations = typeof MutationObserver === "undefined" ? null : new MutationObserver(bind);
    mutations?.observe(stageElement, { childList: true, subtree: true });
    window.addEventListener("resize", measure);
    return () => {
      mutations?.disconnect();
      resize?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [catalogOpen, showInspector]);

  useEffect(() => {
    if (catalogOpen) catalogRef.current?.focus();
  }, [catalogOpen]);

  useEffect(() => {
    if (showInspector && !wasInspectorOpen.current) inspectorRef.current?.focus();
    if (!showInspector && wasInspectorOpen.current) {
      rootRef.current?.querySelector<HTMLElement>("[data-workbench-info-trigger]")?.focus();
    }
    wasInspectorOpen.current = showInspector;
  }, [showInspector]);

  const closeCatalog = () => {
    setCatalogOpen(false);
    catalogToggleRef.current?.focus();
  };

  const onCatalogKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    // 드로어 안에 포커스가 있을 때만 닫는다 — 팔레트 등 바깥의 Escape에는
    // 손대지 않는다. 합성 중 키는 브라우저에 맡긴다.
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Escape") {
      event.stopPropagation();
      closeCatalog();
    }
  };

  const onInspectorKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Escape") {
      event.stopPropagation();
      if (onCloseInspector) onCloseInspector();
      else inspectorRef.current?.querySelector<HTMLElement>("[data-workbench-info-close]")?.click();
    }
  };

  return (
    <div ref={rootRef} className="flex min-w-0 min-h-0 flex-1 flex-col gap-2">
      {banner}
      <div ref={contextRef} data-workbench-context-bar className="sticky top-0 z-40 flex min-w-0 shrink-0 flex-wrap items-center gap-x-2 gap-y-1.5 bg-surface max-sm:gap-y-1 lg:static lg:z-auto">
        <button
          ref={catalogToggleRef}
          type="button"
          aria-expanded={catalogOpen}
          aria-controls="workbench-catalog"
          onClick={() => (catalogOpen ? closeCatalog() : setCatalogOpen(true))}
          className="tap-target inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] font-semibold text-ink-2"
        >
          <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" className="flex-none">
            <path d="M3 4h10M3 8h10M3 12h10" />
          </svg>
          <span className="max-sm:sr-only">목록</span>
        </button>
        {contextBar}
      </div>
      <div className="relative flex min-w-0 min-h-0 flex-1 gap-3">
        <div ref={stageRef} className="relative min-w-0 min-h-0 flex-1">
          {stage}
          {catalogOpen && (
            <>
              <div
                aria-hidden="true"
                onClick={closeCatalog}
                style={{ top: drawerTop }}
                className="fixed inset-x-0 bottom-[var(--mobile-bottom-nav-clearance)] z-[45] bg-black/30 lg:absolute lg:inset-0 lg:z-20"
              />
              <section
                ref={catalogRef}
                id="workbench-catalog"
                aria-label={catalogLabel}
                tabIndex={-1}
                onKeyDown={onCatalogKeyDown}
                style={{ top: drawerTop }}
                data-mobile-sheet="catalog"
                className="fixed inset-x-2 bottom-[calc(var(--mobile-bottom-nav-clearance)+8px)] z-50 flex w-auto flex-col gap-2 overflow-y-auto overscroll-contain rounded-2xl border border-line bg-surface p-3 shadow-xl sm:left-2 sm:right-auto sm:w-[min(380px,calc(100%-16px))] lg:absolute lg:bottom-2 lg:z-30 lg:w-[min(320px,88%)] lg:rounded-lg lg:p-2"
              >
                <div className="sticky -top-3 z-10 -mx-3 -mt-3 flex min-w-0 shrink-0 items-center justify-between gap-2 border-b border-line bg-surface px-3 py-3 sm:-top-3 sm:-mx-3 sm:-mt-3 lg:-top-2 lg:-mx-2 lg:-mt-2 lg:px-2 lg:py-2">
                  <div className="min-w-0">
                    <span aria-hidden="true" className="mx-auto mb-2 block h-1 w-10 rounded-full bg-line-strong sm:hidden" />
                    <h3 className="min-w-0 break-words text-[15px] font-bold lg:text-[13px]">{catalogLabel}</h3>
                  </div>
                  <button
                    type="button"
                    onClick={closeCatalog}
                    aria-label="자료 목록 닫기"
                    className="tap-target inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-[12px] font-semibold text-ink-2 lg:border-0 lg:px-1.5 lg:underline"
                  >
                    닫기
                  </button>
                </div>
                {catalog}
                {catalogFooter && (
                  <div className="sticky -bottom-3 z-10 -mx-3 -mb-3 mt-auto shrink-0 border-t border-line bg-surface px-3 pb-3 pt-2 sm:-bottom-3 sm:-mx-3 sm:-mb-3 lg:-bottom-2 lg:-mx-2 lg:-mb-2 lg:px-2 lg:pb-2">
                    {catalogFooter}
                    {catalogDismissLabel && (
                      <button
                        type="button"
                        onClick={closeCatalog}
                        className="btn btn-primary mt-2 min-h-11 w-full"
                      >
                        {catalogDismissLabel}
                      </button>
                    )}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
        <section
          ref={inspectorRef}
          id={inspectorId}
          aria-label={inspectorLabel}
          tabIndex={-1}
          onKeyDown={onInspectorKeyDown}
          style={{ top: drawerTop, display: showInspectorPanel ? undefined : "none" }}
          data-mobile-sheet="inspector"
          className={`fixed inset-x-2 bottom-[calc(var(--mobile-bottom-nav-clearance)+8px)] z-50 w-auto flex-col gap-3 overflow-y-auto overscroll-contain rounded-2xl border border-line bg-surface p-4 text-[12px] leading-5 text-ink-2 shadow-xl sm:left-auto sm:right-2 sm:w-[min(380px,92%)] lg:absolute lg:bottom-2 lg:z-30 xl:static xl:right-auto xl:bottom-auto xl:z-auto xl:max-h-none xl:w-[320px] xl:flex-none xl:self-stretch xl:rounded-xl xl:p-3 xl:shadow-none ${showInspector ? "flex" : "hidden xl:flex"}`}
        >
          {showInspectorPanel ? inspector : null}
          {detailsHostId ? <div id={detailsHostId} className="flex min-w-0 flex-col gap-3" /> : null}
        </section>
      </div>
    </div>
  );
}
