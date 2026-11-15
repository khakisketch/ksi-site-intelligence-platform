import type { ReactNode } from "react";

import { Disclosure } from "@/components/ui/Disclosure";

/**
 * 프로젝트 섹션 화면의 공통 틀(ADR-KSI-043의 3단 탐색 중 2·3단).
 *
 * - `context` — 섹션 안의 보기(구역·필터·유형). 넓은 화면에서는 왼쪽 열, 좁은 화면에서는 본문 위.
 * - `children` — 본문. 표·결과 같은 주 내용.
 * - `inspector` — 선택한 항목의 상세. 1280px 이상에서는 오른쪽 열, 그보다 좁으면 본문 바로 아래.
 * - `drawer` — 본문 아래에 접어 두는 보조 기록(등록 진행·이력). 기본은 접힘이다. 1280px 미만에서는
 *   선택한 항목의 상세가 서랍 머리말에 가려지지 않도록 맨 아래로 간다.
 *
 * 열마다 따로 스크롤하는 것은 1280px 이상뿐이다. 그보다 좁으면 문서 전체가 하나로 스크롤해
 * 열이 서로를 가리거나 안쪽 스크롤이 겹치지 않는다. 데이터를 읽지 않는 순수 배치 컴포넌트다.
 * (좁은 화면의 순서는 본문 열을 `display: contents`로 풀어 `order`로 정한다. 문서 순서는 그대로다.)
 */
export function SectionFrame({
  contextLabel,
  context,
  inspectorLabel,
  inspector,
  drawerLabel,
  drawer,
  drawerOpen = false,
  children,
}: {
  contextLabel: string;
  context: ReactNode;
  /** 선택한 항목의 상세가 없는 보기(목록만 있는 화면)는 비워 둔다 — 오른쪽 열 없이 본문이 넓어진다. */
  inspectorLabel?: string;
  inspector?: ReactNode;
  drawerLabel?: string;
  drawer?: ReactNode;
  drawerOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <div data-section-frame="true" className="flex min-w-0 flex-1 flex-col xl:min-h-0 xl:flex-row">
      <aside
        aria-label={contextLabel}
        data-section-context="true"
        className="order-1 flex min-w-0 flex-col gap-4 border-b border-line bg-surface p-4 xl:order-none xl:w-[248px] xl:shrink-0 xl:overflow-y-auto xl:border-r xl:border-b-0"
      >
        {context}
      </aside>

      <div className="contents xl:flex xl:min-h-0 xl:min-w-0 xl:flex-1 xl:flex-col xl:overflow-y-auto">
        <div className="order-2 flex min-w-0 flex-1 flex-col gap-4 p-4 sm:p-5 xl:order-none">{children}</div>
        {drawer && drawerLabel && (
          <Disclosure
            label={drawerLabel}
            open={drawerOpen}
            data-section-drawer="true"
            className="order-4 border-t border-line bg-surface px-4 sm:px-5 xl:order-none"
          >
            <div className="pb-4">{drawer}</div>
          </Disclosure>
        )}
      </div>

      {inspector !== undefined && inspectorLabel && (
        <aside
          aria-label={inspectorLabel}
          id="section-inspector"
          data-section-inspector="true"
          className="order-3 min-w-0 scroll-mt-4 border-t border-line bg-surface p-4 xl:order-none xl:w-[340px] xl:shrink-0 xl:overflow-y-auto xl:border-t-0 xl:border-l"
        >
          {inspector}
        </aside>
      )}
    </div>
  );
}
