"use client";

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";

import { SkeletonBlock } from "@/components/ui/Skeleton";
import type { LoadState } from "./OrthophotoOverlayInner";

// leaflet·georaster 는 window/document/canvas 를 직접 참조해 SSR 불가 — 클라이언트 전용 로드
// (AoiPolygonMap.tsx 와 같은 관용구).
const OrthophotoOverlayInner = dynamic(
  () => import("./OrthophotoOverlayInner").then((m) => m.OrthophotoOverlayInner),
  { ssr: false, loading: () => <SkeletonBlock className="h-full min-h-80" /> },
);

/**
 * 정사영상 오버레이 — 마운트 시점에 `/api/processing-jobs/{jobId}/artifacts/
 * {artifactId}/download` 를 직접 호출해 짧은 수명의 presigned URL 을 받고,
 * 그 URL 에서 GeoTIFF 를 직접 받아 클라이언트에서 파싱·렌더한다(Core 를 거치지
 * 않는다 — Task C2/D2 와 같은 "바이트는 Core 프로세스를 통과하지 않는다" 원칙).
 * 어느 산출물이 정사영상인지(artifactId)는 호출부가 미리 골라 넘긴다 — 이
 * 컴포넌트는 검색하지 않는다.
 */
export function OrthophotoOverlay({
  jobId,
  artifactId,
  center = [37.5665, 126.978],
}: {
  jobId: string;
  artifactId: string;
  center?: [number, number];
}) {
  const [state, setState] = useState<LoadState>({ phase: "loading" });
  const onState = useCallback((s: LoadState) => setState(s), []);

  return (
    <section className="rounded-lg border border-line p-4">
      <h3 className="text-sm font-semibold">정사영상</h3>
      {state.phase === "unavailable" && (
        <p className="mt-1 text-sm text-amber-700">
          정사영상을 불러오지 못했습니다 — {state.detail}
        </p>
      )}
      <div className="mt-2 h-80 w-full overflow-hidden rounded-lg border border-line sm:h-96">
        <OrthophotoOverlayInner jobId={jobId} artifactId={artifactId} center={center} onState={onState} />
      </div>
    </section>
  );
}
