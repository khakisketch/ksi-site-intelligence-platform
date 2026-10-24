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

  useLayoutEffect(() => {
    const stageElement = stageRef.current;
    if (!stageElement || (!catalogOpen && !showInspector)) return;
    let observed: Element[] = [];
    const measure = () => {
      const desktop = typeof matchMedia !== "function" || matchMedia("(min-width: 1024px)").matches;
      if (!desktop) {
        // A narrow-screen drawer is viewport-fixed: focusing it must not scroll
        // the document away from the observation the person was viewing.
        const header = contextRef.current?.getBoundingClientRect();
        setDrawerTop(Math.max(8, Math.ceil((header?.bottom ?? 0) + 8)));
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
          className="tap-target shrink-0 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] font-semibold text-ink-2"
        >
          목록
        </button>
        {contextBar}
      </div>
      <div ref={stageRef} className="relative min-w-0 min-h-0 flex-1">
        {stage}
        {catalogOpen && (
          <>
            <div
              aria-hidden="true"
              onClick={closeCatalog}
              style={{ top: drawerTop }}
              className="fixed inset-x-0 bottom-[var(--mobile-bottom-nav-clearance)] z-20 bg-black/20 lg:absolute lg:inset-0"
            />
            <section
              ref={catalogRef}
              id="workbench-catalog"
              aria-label={catalogLabel}
              tabIndex={-1}
              onKeyDown={onCatalogKeyDown}
              style={{ top: drawerTop }}
              className="fixed bottom-[calc(var(--mobile-bottom-nav-clearance)+8px)] left-2 z-30 flex w-[min(320px,88%)] flex-col gap-2 overflow-y-auto rounded-lg border border-line bg-surface p-2 shadow-xl lg:absolute lg:bottom-2"
            >
              <div className="flex min-w-0 shrink-0 items-center justify-between gap-2 px-1.5 pt-1">
                <h3 className="min-w-0 break-words text-[13px] font-bold">{catalogLabel}</h3>
                <button
                  type="button"
                  onClick={closeCatalog}
                  className="tap-target shrink-0 text-[12px] underline text-ink-2"
                >
                  닫기
                </button>
              </div>
              {catalog}
            </section>
          </>
        )}
        {/* 정보 서랍 틀과 접힘 자리는 항상 마운트한다 — 닫힘 상태에서는
            display:none이라 자리·초점·읽기 순서에 들지 않는다. 무대 뷰어의
            접힌 상세가 포털로 들어가는 자리(detailsHostId)는 닫혀도 유지되므로,
            포털이 사라지거나 카메라·선택이 흔들리지 않는다. 본문은 열렸을
            때만 둔다. */}
        <section
          ref={inspectorRef}
          id={inspectorId}
          aria-label={inspectorLabel}
          tabIndex={-1}
          onKeyDown={onInspectorKeyDown}
          style={{ top: drawerTop, display: showInspector ? undefined : "none" }}
          className="fixed right-2 bottom-[calc(var(--mobile-bottom-nav-clearance)+8px)] z-30 flex w-[min(340px,92%)] flex-col gap-3 overflow-y-auto rounded-lg border border-line bg-surface p-3 text-[12px] leading-5 text-ink-2 shadow-xl lg:absolute lg:bottom-2"
        >
          {showInspector ? inspector : null}
          {detailsHostId ? <div id={detailsHostId} className="flex min-w-0 flex-col gap-3" /> : null}
        </section>
      </div>
    </div>
  );
}
