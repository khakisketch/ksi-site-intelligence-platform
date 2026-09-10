"use client";

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";

import { SkeletonBlock } from "@/components/ui/Skeleton";
import type { ExternalSanitizedOrthophotoLoadState } from "./ExternalSanitizedOrthophotoInner";

const ExternalSanitizedOrthophotoInner = dynamic(
  () => import("./ExternalSanitizedOrthophotoInner").then((module) => module.ExternalSanitizedOrthophotoInner),
  { ssr: false, loading: () => <SkeletonBlock className="h-full min-h-80" /> },
);

/** A display-only view of one Core-authorized sanitized derivative, never a submitted source raster. */
export function ExternalSanitizedOrthophoto({
  workOrderId,
  submissionRef,
  revision,
  sanitizedDisplayRef,
  receiptDigest,
  onDismiss,
}: {
  workOrderId: string;
  submissionRef: string;
  revision: number;
  sanitizedDisplayRef: string;
  receiptDigest: string;
  onDismiss: () => void;
}) {
  const [state, setState] = useState<ExternalSanitizedOrthophotoLoadState>({ phase: "loading" });
  const onState = useCallback((next: ExternalSanitizedOrthophotoLoadState) => setState(next), []);

  return (
    <section className="mt-2 rounded-lg border border-line bg-sunk p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">정제 정사영상</h3>
          <p className="mt-0.5 text-[12px] text-ink-2">검사 완료된 표시용 파생본입니다. 높이·면적·물량 수치를 계산하거나 표시하지 않습니다.</p>
        </div>
        <button className="btn" onClick={onDismiss}>표시 닫기</button>
      </div>
      {state.phase === "unavailable" && <p role="alert" className="mt-2 text-sm break-keep text-high-ink">정제 정사영상을 표시할 수 없습니다 — {state.detail}</p>}
      <div className="mt-2 h-80 w-full overflow-hidden rounded-lg border border-line sm:h-96">
        <ExternalSanitizedOrthophotoInner
          workOrderId={workOrderId}
          submissionRef={submissionRef}
          revision={revision}
          sanitizedDisplayRef={sanitizedDisplayRef}
          receiptDigest={receiptDigest}
          onState={onState}
        />
      </div>
    </section>
  );
}
