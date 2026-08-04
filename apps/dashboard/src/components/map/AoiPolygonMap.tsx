"use client";

import dynamic from "next/dynamic";

import type { AoiVertex } from "@/lib/core-api/types";
import { SkeletonBlock } from "@/components/ui/Skeleton";

// leaflet/leaflet-draw 는 window/document 를 직접 참조해 SSR 불가 — 클라이언트 전용 로드.
const AoiPolygonMapInner = dynamic(
  () => import("./AoiPolygonMapInner").then((m) => m.AoiPolygonMapInner),
  { ssr: false, loading: () => <SkeletonBlock className="h-full min-h-80" /> },
);

export function AoiPolygonMap(props: {
  value: AoiVertex[];
  onChange: (vertices: AoiVertex[]) => void;
  center?: [number, number];
}) {
  return (
    <div className="h-80 w-full overflow-hidden rounded-lg border border-line sm:h-96">
      <AoiPolygonMapInner {...props} />
    </div>
  );
}
