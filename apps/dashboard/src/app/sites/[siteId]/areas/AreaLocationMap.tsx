"use client";

import { useState } from "react";

import { Disclosure } from "@/components/ui/Disclosure";
import { WorkAreaChoiceMap } from "@/components/map/WorkAreaChoiceMap";
import type { WorkArea } from "@/lib/core-api/types";

/**
 * 고른 영역이 배경 지도의 어디인지 — 자료 뷰어 아래의 접힘 지도.
 *
 * 자료가 아직 준비되지 않았거나 불러오지 못해도 "지금 어느 영역을 보고 있는지"는 항상 말할 수 있다.
 * 그리는 것은 등록된 영역 경계뿐이며, 자료(DSM)가 지도의 이 자리에 놓인다고 단정하지 않는다.
 * 지도 라이브러리는 펼칠 때만 불러온다.
 */
export function AreaLocationMap({ area, defaultOpen }: { area: WorkArea; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Disclosure
      label="영역 위치 지도"
      open={defaultOpen}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      data-area-location="true"
      className="shrink-0 rounded-lg border border-line bg-surface px-3"
      summaryClassName="font-semibold"
    >
      {open && (
        <div className="pb-3">
          <WorkAreaChoiceMap areas={[area]} selectedId={area.workAreaId} onSelect={() => {}} disabled heightClassName="h-64" />
          <p className="mt-1.5 text-caption text-ink-muted">등록된 영역 경계입니다. 자료가 이 자리에 놓인다는 뜻은 아닙니다.</p>
        </div>
      )}
    </Disclosure>
  );
}
