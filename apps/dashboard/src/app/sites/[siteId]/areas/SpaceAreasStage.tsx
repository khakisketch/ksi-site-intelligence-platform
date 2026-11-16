"use client";

import { useRouter } from "next/navigation";

import { WorkAreaChoiceMap } from "@/components/map/WorkAreaChoiceMap";
import { siteAreasHref } from "@/components/nav/site-context";
import type { WorkArea } from "@/lib/core-api/types";

/**
 * 공간의 영역 보기 무대 — 지도에 영역을 모두 그리고, 고른 영역을 강조한다.
 * 지도에서 영역을 누르면 목록에서 고른 것과 같은 주소로 옮긴다(선택은 주소가 가진다).
 * 읽기 전용이다. 그리기·등록·보관은 이 컴포넌트가 하지 않는다.
 */
export function SpaceAreasStage({ siteId, areas, selectedId }: {
  siteId: string;
  areas: WorkArea[];
  selectedId: string;
}) {
  const router = useRouter();
  return (
    <div data-space-areas-stage="true" className="min-w-0">
      <WorkAreaChoiceMap
        areas={areas}
        selectedId={selectedId}
        disabled={false}
        heightClassName="h-[56vh] min-h-80 xl:h-[calc(100vh-9rem)]"
        onSelect={(id) => router.replace(siteAreasHref(siteId, id), { scroll: false })}
      />
    </div>
  );
}
