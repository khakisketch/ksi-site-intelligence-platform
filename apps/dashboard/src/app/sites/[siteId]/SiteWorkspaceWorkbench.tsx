"use client";

import { useState, type ReactNode } from "react";

import { SpatialWorkbenchFrame } from "@/components/site/SpatialWorkbenchFrame";

/**
 * 실제 작업공간용 작은 클라이언트 래퍼 — 서버가 만든 맥락막대·목록·무대·
 * 정보를 같은 `SpatialWorkbenchFrame` 배치로 둔다.
 *
 * - 정보 열림은 로컬 상태다. URL 쿼리를 새로 만들지 않으므로 탐색·비교·결과
 *   선택(`workAreaId`·`assetRef`·`visual*`·`analysisId`)을 건드리지 않는다.
 * - 정보 머리(제목·닫기 단추)는 래퍼가 둔다. 호출자는 본문만 싣는다.
 *   닫기·Escape·포커스 복귀는 셸 규칙을 그대로 쓴다.
 * - 권한·조회·선택 판정을 새로 만들지 않는다. 받은 노드를 그대로 둔다.
 *
 * Invariants: INV-020(배치 전용)/INV-040(예시 바이트 fallback 없음)/
 * INV-060·061(권한·이그레스 변경 없음).
 */
export function SiteWorkspaceWorkbench({
  contextControls,
  catalog,
  catalogLabel,
  intake,
  areas,
  areasLabel = "영역",
  areasStage,
  initialPanel = null,
  initialInfoOpen = false,
  stage,
  inspector,
  inspectorLabel,
  inspectorId,
  detailsHostId,
  viewerMode = false,
}: {
  /** 구역·방식 등 서버가 만든 맥락 노드 — 목록 토글·검색은 래퍼가 앞에 둔다. */
  contextControls: ReactNode;
  /** 왼쪽 목록 드로어 내용(구역·관측 선택·다음 행동). 열렸을 때만 렌더된다. */
  catalog: ReactNode;
  /** 목록 드로어 이름. */
  catalogLabel: string;
  intake?: ReactNode;
  /** "영역" 탭 내용(목록·상세). 주면 목록 서랍의 토글에 세 번째 항목이 생긴다. */
  areas?: ReactNode;
  /** "영역" 토글 이름 — 예: `영역 3`. */
  areasLabel?: string;
  /**
   * "영역" 탭이 열려 있을 때 lg+에서 무대 자리를 대신 채우는 지도. 원래 무대는 마운트를 유지한 채 가린다
   * (뷰어 상태를 잃지 않는다). 없으면 무대는 그대로다.
   */
  areasStage?: ReactNode;
  initialPanel?: "materials" | "intake" | "areas" | null;
  initialInfoOpen?: boolean;
  /** 중앙 시각 무대 — 단일 또는 좌·우 독립 보기. */
  stage: ReactNode;
  /** 오른쪽 정보 내용 — 열렸을 때만 둔다. */
  inspector: ReactNode;
  /** 정보 영역 이름. */
  inspectorLabel: string;
  /** 정보 영역 식별자. */
  inspectorId: string;
  /** 무대 뷰어 접힘 포털 자리 식별자 — 서랍 안에 항상 마운트한다. */
  detailsHostId?: string;
  /** 공간 탐색이면 lg+에서 viewer 배치를 쓴다. 결과 검토 모드는 밀도 유지. */
  viewerMode?: boolean;
}) {
  const [infoOpen, setInfoOpen] = useState(initialInfoOpen);
  const [panel, setPanel] = useState<"materials" | "intake" | "areas">(initialPanel ?? "materials");
  const tabId = "workspace-catalog-tab";
  const toggles: Array<{ key: "materials" | "intake" | "areas"; label: string }> = [
    { key: "materials", label: "자료" },
    ...(intake ? [{ key: "intake" as const, label: "등록 진행" }] : []),
    ...(areas ? [{ key: "areas" as const, label: areasLabel }] : []),
  ];
  // 내용이 없는 항목을 가리키던 상태는 자료로 되돌린다.
  const shown = toggles.some((toggle) => toggle.key === panel) ? panel : "materials";
  const catalogBody = toggles.length > 1 ? (
    <div className="flex min-w-0 flex-col gap-3">
      <div role="group" aria-label="자료 패널 보기" className="flex flex-wrap gap-1 rounded-md bg-sunk p-1">
        {toggles.map((toggle) => (
          <button key={toggle.key} type="button" onClick={() => setPanel(toggle.key)} aria-pressed={shown === toggle.key} aria-controls={tabId}
            className={`tap-target grow rounded-md px-2 text-caption ${shown === toggle.key ? "bg-surface font-bold" : "text-ink-2"}`}>{toggle.label}</button>
        ))}
      </div>
      <div id={tabId}>{shown === "intake" ? intake : shown === "areas" ? areas : catalog}</div>
    </div>
  ) : catalog;
  const areasMapOpen = shown === "areas" && Boolean(areasStage);
  const stageBody = areasStage ? (
    <>
      {/* 영역 탭이 열려 있는 동안만 lg+에서 원래 무대를 가린다. 서랍을 닫으면(프레임의 data-catalog-open)
          뷰어가 돌아온다. 좁은 화면은 서랍 안의 작은 지도를 쓴다. */}
      <div className={areasMapOpen ? "h-full lg:in-data-[catalog-open=true]:hidden" : "contents"}>{stage}</div>
      {areasMapOpen && <div className="hidden h-full lg:in-data-[catalog-open=true]:block">{areasStage}</div>}
    </>
  ) : stage;
  return (
    <SpatialWorkbenchFrame
      contextBar={
        <>
          {contextControls}
          <button
            data-workbench-info-trigger
            type="button"
            aria-expanded={infoOpen}
            aria-controls={inspectorId}
            onClick={() => setInfoOpen((open) => !open)}
            className={`tap-target ml-auto inline-flex shrink-0 items-center text-caption underline max-sm:min-h-9 max-sm:rounded-md max-sm:border max-sm:border-line max-sm:bg-surface max-sm:px-2 max-sm:py-1 max-sm:no-underline xl:hidden ${infoOpen ? "font-semibold" : "text-ink-2"}`}
          >
            정보
          </button>
        </>
      }
      catalog={catalogBody}
      defaultCatalogOpen={initialPanel !== null}
      catalogLabel={catalogLabel}
      stage={stageBody}
      inspector={
        <>
          <div data-workbench-inspector-heading className="flex min-w-0 items-center justify-between gap-2">
            <h3 className="min-w-0 break-words text-body font-bold">{inspectorLabel}</h3>
            <button
              type="button"
              data-workbench-info-close
              onClick={() => setInfoOpen(false)}
              className="tap-target shrink-0 text-caption underline text-ink-2 xl:hidden"
            >
              닫기
            </button>
          </div>
          {inspector}
        </>
      }
      inspectorOpen={infoOpen}
      onCloseInspector={() => setInfoOpen(false)}
      inspectorId={inspectorId}
      inspectorLabel={inspectorLabel}
      detailsHostId={detailsHostId}
      viewerMode={viewerMode}
      viewerInspectorDefaultOpen={initialInfoOpen}
    />
  );
}
