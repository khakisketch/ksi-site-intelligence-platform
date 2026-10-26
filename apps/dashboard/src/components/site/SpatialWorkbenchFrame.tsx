"use client";

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { ViewerSiteBadge } from "@/components/nav/ViewerSiteBadge";
import { ViewerSiteNav } from "@/components/nav/ViewerSiteNav";

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
  viewerMode = false,
  viewerInspectorDefaultOpen = true,
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
  /**
   * Viewer-first 배치 — lg+에서 무대를 전체 폭으로 두고 목록·정보를 떠 있는
   * 패널로 낮춘다. 모바일/태블릿은 기존 드로어 동작을 그대로 쓴다. 이 플래그는
   * 배치만 바꾸며 조회·권한·선택 판정은 호출자가 그대로 소유한다.
   */
  viewerMode?: boolean;
  /** Viewer 데스크톱에서 정보 카드를 xl+에 기본으로 연다(닫으면 기억). */
  viewerInspectorDefaultOpen?: boolean;
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
  // Viewer placement is desktop-only; mobile keeps the existing sheet behavior.
  // Two queries: lg starts the floating viewer, xl applies the default-open
  // layer/info panels decided in the design study.
  const [viewerDesktop, setViewerDesktop] = useState(false);
  const [viewerWide, setViewerWide] = useState(false);
  useEffect(() => {
    if (!viewerMode || typeof window.matchMedia !== "function") return;
    const desktop = window.matchMedia("(min-width: 1024px)");
    const wide = window.matchMedia("(min-width: 1280px)");
    const update = () => {
      setViewerDesktop(desktop.matches);
      setViewerWide(wide.matches);
    };
    update();
    desktop.addEventListener?.("change", update);
    wide.addEventListener?.("change", update);
    return () => {
      desktop.removeEventListener?.("change", update);
      wide.removeEventListener?.("change", update);
    };
  }, [viewerMode]);
  const viewerDesktopMode = viewerMode && viewerDesktop;
  const [viewerInspectorOpen, setViewerInspectorOpen] = useState(false);
  const viewerCatalogInitialized = useRef(false);
  const viewerInspectorInitialized = useRef(false);
  const catalogFocusRequested = useRef(false);
  const catalogFocusReturn = useRef(false);
  const viewerCatalogToggleRef = useRef<HTMLButtonElement>(null);
  const viewerInfoToggleRef = useRef<HTMLButtonElement>(null);
  const infoFocusRequested = useRef(false);
  useEffect(() => {
    if (!viewerDesktopMode || !viewerWide || viewerCatalogInitialized.current) return;
    viewerCatalogInitialized.current = true;
    setCatalogOpen(true);
  }, [viewerDesktopMode, viewerWide]);
  useEffect(() => {
    if (!viewerDesktopMode || !viewerWide || viewerInspectorInitialized.current) return;
    viewerInspectorInitialized.current = true;
    setViewerInspectorOpen(viewerInspectorDefaultOpen && inspector !== null);
  }, [viewerDesktopMode, viewerWide, viewerInspectorDefaultOpen, inspector]);
  const showInspectorPanel = viewerDesktopMode
    ? viewerInspectorOpen && inspector !== null
    : showInspector || persistentInspector;

  useLayoutEffect(() => {
    const stageElement = stageRef.current;
    if (viewerDesktopMode || !stageElement || (!catalogOpen && !showInspector)) return;
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
  }, [catalogOpen, showInspector, viewerDesktopMode]);

  useEffect(() => {
    if (catalogOpen && catalogFocusRequested.current) {
      catalogFocusRequested.current = false;
      catalogRef.current?.focus();
    }
  }, [catalogOpen]);

  useEffect(() => {
    if (catalogOpen || !catalogFocusReturn.current) return;
    catalogFocusReturn.current = false;
    (viewerDesktopMode ? viewerCatalogToggleRef.current : catalogToggleRef.current)?.focus();
  }, [catalogOpen, viewerDesktopMode]);

  useEffect(() => {
    const open = showInspectorPanel;
    if (open && (!viewerDesktopMode || infoFocusRequested.current)) {
      infoFocusRequested.current = false;
      inspectorRef.current?.focus();
    }
    if (!open && wasInspectorOpen.current) {
      const trigger = viewerDesktopMode
        ? viewerInfoToggleRef.current
        : rootRef.current?.querySelector<HTMLElement>("[data-workbench-info-trigger]");
      trigger?.focus();
    }
    wasInspectorOpen.current = open;
  }, [showInspectorPanel, viewerDesktopMode]);

  const closeCatalog = () => {
    setCatalogOpen(false);
    if (viewerDesktopMode) {
      // The closed-state trigger is mounted by the same state change; wait for
      // the commit instead of focusing a ref that is still null.
      catalogFocusReturn.current = true;
    } else {
      catalogToggleRef.current?.focus();
    }
  };

  const openCatalog = () => {
    catalogFocusRequested.current = true;
    setCatalogOpen(true);
  };

  const closeViewerInspector = () => {
    setViewerInspectorOpen(false);
    viewerInfoToggleRef.current?.focus();
  };

  const toggleViewerInspector = () => {
    if (viewerInspectorOpen) {
      closeViewerInspector();
      return;
    }
    infoFocusRequested.current = true;
    setViewerInspectorOpen(true);
  };

  const onCatalogKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    // 넓은 화면의 상시 열(일반 셸)에는 닫을 드로어가 없다. Viewer의 떠 있는
    // 패널은 넓은 화면에서도 닫을 수 있다.
    if (wideInspector && !viewerDesktopMode) return;
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
      if (viewerDesktopMode) closeViewerInspector();
      else if (onCloseInspector) onCloseInspector();
      else inspectorRef.current?.querySelector<HTMLElement>("[data-workbench-info-close]")?.click();
    }
  };

  if (viewerDesktopMode) {
    return (
      <div
        ref={rootRef}
        data-workbench-viewer="true"
        className="relative flex min-w-0 min-h-0 flex-1 flex-col overflow-hidden bg-page"
      >
        <div
          ref={contextRef}
          data-workbench-context-bar
          className="absolute inset-x-3 top-3 z-40 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5 rounded-xl border border-line bg-surface/95 px-2.5 py-1.5 shadow-lg backdrop-blur"
        >
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1.5">{contextBar}</div>
          {inspector !== null && (
            <button
              ref={viewerInfoToggleRef}
              type="button"
              aria-expanded={viewerInspectorOpen}
              aria-controls={inspectorId}
              onClick={toggleViewerInspector}
              className={`tap-target inline-flex min-h-9 shrink-0 items-center rounded-md border px-2.5 text-[11.5px] font-semibold transition-colors ${
                viewerInspectorOpen
                  ? "border-line-strong bg-sunk text-ink-1"
                  : "border-line bg-surface text-ink-2 hover:bg-sunk"
              }`}
            >
              정보
            </button>
          )}
        </div>

        <div className="absolute inset-x-0 bottom-0 top-[72px] min-h-0">
          <div ref={stageRef} className="relative h-full min-h-0 overflow-hidden">
            {stage}
          </div>

          {catalogOpen ? (
            <aside
              ref={catalogRef}
              id="workbench-catalog"
              aria-label={catalogLabel}
              tabIndex={-1}
              onKeyDown={onCatalogKeyDown}
              data-viewer-panel="catalog"
              className="absolute bottom-3 left-3 top-2 z-30 flex w-[300px] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-2xl"
            >
              <ViewerSiteNav />
              <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
                <div className="min-w-0">
                  <p className="font-mono text-[8.5px] uppercase tracking-[0.1em] text-ink-muted">Layer panel</p>
                  <h3 className="truncate text-[12.5px] font-bold">{catalogLabel}</h3>
                </div>
                <button
                  type="button"
                  onClick={closeCatalog}
                  aria-label={`${catalogLabel} 닫기`}
                  className="tap-target grid size-8 flex-none place-items-center rounded-md text-[15px] text-ink-muted hover:bg-sunk hover:text-ink-1"
                >
                  ×
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2">{catalog}</div>
              {catalogFooter && (
                <div className="shrink-0 border-t border-line bg-surface px-3 py-2">
                  {catalogFooter}
                  {catalogDismissLabel && (
                    <button type="button" onClick={closeCatalog} className="btn btn-primary mt-2 min-h-10 w-full text-[12px]">
                      {catalogDismissLabel}
                    </button>
                  )}
                </div>
              )}
            </aside>
          ) : (
            <button
              ref={viewerCatalogToggleRef}
              type="button"
              aria-expanded={false}
              aria-controls="workbench-catalog"
              onClick={openCatalog}
              className="absolute left-3 top-2 z-30 flex min-h-10 max-w-[min(300px,calc(100%-24px))] items-center gap-2 rounded-lg border border-line bg-surface/95 px-2.5 text-[12px] font-semibold text-ink-1 shadow-lg backdrop-blur hover:bg-surface"
            >
              <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="flex-none text-ink-2">
                <path d="m12 3 9 5-9 5-9-5Z" />
                <path d="m3 12 9 5 9-5M3 16l9 5 9-5" />
              </svg>
              <ViewerSiteBadge fallback="현장" />
              <span className="shrink-0 text-ink-muted">· {catalogLabel}</span>
            </button>
          )}

          {(inspector !== null || detailsHostId) && (
            <section
              ref={inspectorRef}
              id={inspectorId}
              aria-label={inspectorLabel}
              tabIndex={-1}
              onKeyDown={onInspectorKeyDown}
              style={{ display: showInspectorPanel ? undefined : "none" }}
              data-viewer-panel="inspector"
              className="absolute right-3 bottom-3 z-30 flex max-h-[calc(100%-16px)] w-[min(332px,calc(100%-24px))] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-2xl"
            >
              <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-1.5">
                <span className="font-mono text-[8.5px] uppercase tracking-[0.1em] text-ink-muted">Inspector</span>
                <button
                  type="button"
                  onClick={closeViewerInspector}
                  aria-label={`${inspectorLabel} 닫기`}
                  className="tap-target grid size-8 place-items-center rounded-md text-[15px] text-ink-muted hover:bg-sunk hover:text-ink-1"
                >
                  ×
                </button>
              </div>
              <div className="min-h-0 overflow-y-auto overscroll-contain p-3 text-[12px] leading-5 text-ink-2">
                {showInspectorPanel ? inspector : null}
                {detailsHostId ? <div id={detailsHostId} className="flex min-w-0 flex-col gap-3" /> : null}
              </div>
            </section>
          )}
        </div>
      </div>
    );
  }

  return (
    <div ref={rootRef} className="flex min-w-0 min-h-0 flex-1 flex-col gap-2">
      {banner}
      <div ref={contextRef} data-workbench-context-bar className="sticky top-0 z-40 flex min-w-0 shrink-0 flex-wrap items-center gap-x-2 gap-y-1.5 bg-surface max-sm:gap-y-1 lg:static lg:z-auto">
        {!wideInspector && (
          <button
            ref={catalogToggleRef}
            type="button"
            aria-expanded={catalogOpen}
            aria-controls="workbench-catalog"
            onClick={() => (catalogOpen ? closeCatalog() : openCatalog())}
            className="tap-target inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] font-semibold text-ink-2"
          >
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" className="flex-none">
              <path d="M3 4h10M3 8h10M3 12h10" />
            </svg>
            <span className="max-sm:sr-only">목록</span>
          </button>
        )}
        {contextBar}
      </div>
      <div className="relative flex min-w-0 min-h-0 flex-1 gap-3">
        {wideInspector && (
          <aside
            ref={catalogRef}
            id="workbench-catalog"
            aria-label={catalogLabel}
            tabIndex={-1}
            onKeyDown={onCatalogKeyDown}
            data-desktop-catalog="true"
            className="flex min-h-0 w-[300px] flex-none flex-col gap-2 overflow-y-auto overscroll-contain rounded-lg border border-line bg-surface p-2"
          >
            {catalog}
          </aside>
        )}
        {!wideInspector && catalogOpen && (
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
        <div ref={stageRef} className="relative min-w-0 min-h-0 flex-1">
          {stage}
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
