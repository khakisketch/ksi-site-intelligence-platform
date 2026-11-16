"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import type { WorkArea } from "@/lib/core-api/types";
import { partitionWorkAreaDisplay, unsupportedAreasNote } from "@/lib/geo/display-geometry";
import { SkeletonBlock } from "@/components/ui/Skeleton";

const Inner = dynamic(() => import("./WorkAreaChoiceMapInner").then((module) => module.WorkAreaChoiceMapInner), {
  ssr: false, loading: () => <SkeletonBlock className="h-96" />,
});

export function WorkAreaChoiceMap(props: {
  areas: WorkArea[]; selectedId: string; onSelect: (id: string) => void; disabled: boolean;
  /** 지도 상자 높이 클래스 — 기본은 선택 화면용 `h-96`. 공간 영역 보기처럼 더 큰 무대는 따로 준다. */
  heightClassName?: string;
}) {
  const { supported, unsupported } = useMemo(() => partitionWorkAreaDisplay(props.areas), [props.areas]);
  const note = unsupportedAreasNote(unsupported);
  return <div>
    <div className={`${props.heightClassName ?? "h-96"} overflow-hidden rounded-lg border border-line`}>
      <Inner shapes={supported} selectedId={props.selectedId} onSelect={props.onSelect} disabled={props.disabled} />
    </div>
    {note && <p role="note" className="mt-2 text-xs leading-5 text-ink-2">{note}</p>}
  </div>;
}
