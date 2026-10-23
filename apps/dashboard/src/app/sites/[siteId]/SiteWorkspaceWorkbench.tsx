"use client";

import { useState, type ReactNode } from "react";

import { SpatialWorkbenchFrame } from "@/components/site/SpatialWorkbenchFrame";
import { TopBarSearchTrigger } from "@/components/nav/TopBarSearchTrigger";

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
  stage,
  inspector,
  inspectorLabel,
  inspectorId,
}: {
  /** 구역·방식 등 서버가 만든 맥락 노드 — 목록 토글·검색은 래퍼가 앞에 둔다. */
  contextControls: ReactNode;
  /** 왼쪽 목록 드로어 내용(구역·관측 선택·다음 행동). 열렸을 때만 렌더된다. */
  catalog: ReactNode;
  /** 목록 드로어 이름. */
  catalogLabel: string;
  /** 중앙 시각 무대 — 단일 또는 좌·우 독립 보기. */
  stage: ReactNode;
  /** 오른쪽 정보 내용 — 열렸을 때만 둔다. */
  inspector: ReactNode;
  /** 정보 영역 이름. */
  inspectorLabel: string;
  /** 정보 영역 식별자. */
  inspectorId: string;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  return (
    <SpatialWorkbenchFrame
      contextBar={
        <>
          {contextControls}
          <TopBarSearchTrigger />
          <button
            data-workbench-info-trigger
            type="button"
            aria-expanded={infoOpen}
            aria-controls={inspectorId}
            onClick={() => setInfoOpen((open) => !open)}
            className={`tap-target shrink-0 text-[12px] underline ${infoOpen ? "font-semibold" : "text-ink-2"}`}
          >
            정보
          </button>
        </>
      }
      catalog={catalog}
      catalogLabel={catalogLabel}
      stage={stage}
      inspector={
        <>
          <div className="flex min-w-0 items-center justify-between gap-2">
            <h3 className="min-w-0 break-words text-[13px] font-bold">{inspectorLabel}</h3>
            <button
              type="button"
              data-workbench-info-close
              onClick={() => setInfoOpen(false)}
              className="tap-target shrink-0 text-[12px] underline text-ink-2"
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
    />
  );
}
