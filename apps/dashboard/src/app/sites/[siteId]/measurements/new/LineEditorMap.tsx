"use client";

import dynamic from "next/dynamic";

import { SkeletonBlock } from "@/components/ui/Skeleton";
import type { LineVertex } from "@/lib/measurement-line";

// leaflet은 window를 직접 참조해 서버에서 그릴 수 없다. 클라이언트에서만 불러온다.
const LineEditorMapInner = dynamic(
  () => import("./LineEditorMapInner").then((module) => module.LineEditorMapInner),
  { ssr: false, loading: () => <SkeletonBlock className="h-full min-h-80" /> },
);

export interface LineEditorMapProps {
  vertices: LineVertex[];
  /** 작업구역 바깥 경계([경도, 위도]). 모르면 null이며 구역을 그리지 않는다. */
  ring: LineVertex[] | null;
  disabled: boolean;
  onAdd: (vertex: LineVertex) => void;
  onMove: (index: number, vertex: LineVertex) => void;
}

export function LineEditorMap(props: LineEditorMapProps) {
  return <LineEditorMapInner {...props} />;
}
