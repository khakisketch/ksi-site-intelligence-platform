"use client";

import dynamic from "next/dynamic";

import type { AoiVertex } from "@/lib/core-api/types";
import { SkeletonBlock } from "@/components/ui/Skeleton";
import type { AoiMapPendingState, AoiRawSnapshot } from "./AoiPolygonMapInner";

// leaflet/leaflet-draw 는 window/document 를 직접 참조해 SSR 불가 — 클라이언트 전용 로드.
const AoiPolygonMapInner = dynamic(
  () => import("./AoiPolygonMapInner").then((m) => m.AoiPolygonMapInner),
  { ssr: false, loading: () => <SkeletonBlock className="h-full min-h-80" /> },
);

// 미반영 키보드 입력의 부모 차단 알림 — Inner의 동일 이름 계약을 겉에서
// 다시 내보낸다(호출자는 이 파일에서만 import한다). 타입 재내보내라
// 런타임 순환이 없다.
export type { AoiMapPendingState, AoiRawSnapshot };

export function AoiPolygonMap(props: {
  value: AoiVertex[];
  /** readOnly 가 아니면 필수. */
  onChange?: (vertices: AoiVertex[]) => void;
  /** 미반영 키보드 입력이 있으면 부모 제출을 막는 알림 — 선택, 없으면 오늘과 같다. */
  onPendingChange?: (pending: AoiMapPendingState) => void;
  initialSnapshot?: AoiRawSnapshot;
  onSnapshotChange?: (snapshot: AoiRawSnapshot) => void;
  center?: [number, number];
  /** true 면 편집 컨트롤 없이 폴리곤만 표시한다(현장 상세처럼 보여주기 전용 자리). */
  readOnly?: boolean;
}) {
  return (
    <div className="w-full">
      <AoiPolygonMapInner {...props} />
    </div>
  );
}
