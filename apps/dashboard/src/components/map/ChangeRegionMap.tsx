"use client";

import dynamic from "next/dynamic";

import { SkeletonBlock } from "@/components/ui/Skeleton";
import type { AoiVertex, ChangeRegion } from "@/lib/core-api/types";

// leaflet 은 window/document 를 직접 참조해 SSR 불가 — AoiPolygonMap 과 같은 관용구.
const ChangeRegionMapInner = dynamic(
  () => import("./ChangeRegionMapInner").then((m) => m.ChangeRegionMapInner),
  { ssr: false, loading: () => <SkeletonBlock className="h-full min-h-80" /> },
);

export function ChangeRegionMap(props: {
  siteAoi: AoiVertex[];
  regions: ChangeRegion[];
  selectedRegionId: string | null;
  onSelectRegion: (regionId: string) => void;
  center?: [number, number];
}) {
  return (
    <div className="h-80 w-full overflow-hidden rounded-lg border border-line sm:h-[28rem]">
      <ChangeRegionMapInner {...props} />
    </div>
  );
}
