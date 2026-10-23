import type { ReactNode } from "react";

/**
 * 공간 작업환경 공유 presentational frame — 실제 등록 자료 화면과
 * `/design-preview/materials` 예시 화면이 같은 머리/레일/무대/정보/방식
 * 관계를 쓴다. 순수 배치만 맡으며, 권한·조회·선택 판정은 호출자가 둔다.
 *
 * - 전체 너비를 쓰고 페이지 안에 카드를 겹치지 않는다. 중앙 무대가
 *   뷰포트 크기로 남고, 레일은 220/240px로 둔다. grid 자식 래퍼가 높이를
 *   채우고 넘침을 각자 스크롤하므로, 무대 흐름이 아래 도움말과 겹치지 않는다.
 * - 정보는 열렸을 때만 자리를 차지한다(닫히면 유령 열 없음). desktop(xl 이상)
 *   에서는 왼쪽 레일을 CSS로 접고 무대+정보 2열로 둔다 — 무대가 좁아지거나
 *   좌·우 보기가 세로로 꺾이지 않는다. 닫으면 레일이 돌아오고 선택·보기는
 *   그대로 둔다. 좁은 너비에서는 도킹 대신 덮개로 둔다.
 * - 휴대폰에서는 시각 무대가 목록보다 먼저다(DOM 순서: 무대 → 레일 → 정보,
 *   desktop은 grid 배치로 레일을 왼쪽에 둔다).
 *
 * Invariants: INV-020(좌표·시각 판정 없음 — 배치 전용)/INV-040(예시는 별도
 * 경로의 명시적 선택이며 실제 바이트의 fallback이 아니다 — 같은 frame을
 * 써도 바인딩·조회는 섞지 않는다)/INV-060·061(권한·이그레스 변경 없음).
 */
export function SpatialWorkbenchFrame({
  banner = null,
  toolbar,
  rail,
  stage,
  inspector = null,
  inspectorOpen = false,
  inspectorId,
  inspectorLabel,
}: {
  /** 예시 경로의 고정 안내 등, 도구모음 위에 두는 띠. 실제 경로는 두지 않는다. */
  banner?: ReactNode;
  /** 한 줄 도구모음 — 구역·보기 방식·정보·등록만 둔다. 검색·필터는 레일이 맡는다. */
  toolbar: ReactNode;
  /** 왼쪽 탐색 레일(관측·자료·층 선택). 휴대폰용 접힘 목록도 호출자가 함께 둔다. */
  rail: ReactNode;
  /** 중앙 시각 무대 — 단일 또는 좌·우 독립 보기. */
  stage: ReactNode;
  /** 오른쪽 선택 정보 — 열렸을 때만 둔다. */
  inspector?: ReactNode;
  /** 정보 열림 — false면 자리를 차지하지 않는다. */
  inspectorOpen?: boolean;
  /** 정보 영역 식별자·이름 — 열릴 때만 렌더된다. */
  inspectorId: string;
  inspectorLabel: string;
}) {
  const showInspector = inspectorOpen && inspector !== null;
  return (
    <div className="flex min-w-0 flex-col gap-2">
      {banner}
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">{toolbar}</div>
      <div className={`grid min-w-0 items-stretch gap-3 lg:h-[calc(100dvh-240px)] lg:min-h-[430px] lg:grid-cols-[220px_minmax(0,1fr)] xl:grid-cols-[240px_minmax(0,1fr)] ${showInspector ? "xl:grid-cols-[minmax(0,1fr)_320px]" : ""}`}>
        <div className={`min-w-0 lg:col-start-2 lg:row-start-1 lg:h-full lg:min-h-0 ${showInspector ? "xl:col-start-1" : ""}`}>{stage}</div>
        <div className={`min-w-0 lg:col-start-1 lg:row-start-1 lg:h-full lg:min-h-0 ${showInspector ? "xl:hidden" : ""}`}>{rail}</div>
        {showInspector ? (
          <section
            id={inspectorId}
            aria-label={inspectorLabel}
            className="flex min-w-0 scroll-mt-3 flex-col gap-3 rounded-lg border border-line bg-surface p-3 text-[12px] leading-5 text-ink-2 lg:fixed lg:inset-y-0 lg:right-0 lg:z-30 lg:w-[min(340px,92vw)] lg:overflow-y-auto lg:rounded-none lg:border-y-0 lg:border-l lg:shadow-2xl xl:static xl:z-auto xl:col-start-2 xl:row-start-1 xl:h-full xl:min-h-0 xl:w-auto xl:overflow-y-auto xl:rounded-lg xl:border xl:shadow-none"
          >
            {inspector}
          </section>
        ) : null}
      </div>
    </div>
  );
}
