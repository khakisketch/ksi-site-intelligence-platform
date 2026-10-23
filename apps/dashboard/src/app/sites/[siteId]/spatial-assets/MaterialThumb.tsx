"use client";

import { useEffect, useRef, useState } from "react";

import type { SpatialDataReceipt } from "@/lib/core-api/spatial-data-types";
import { acquirePreviewSlot } from "@/lib/site-preview";
import {
  decodeReceiptPreview,
  fetchVerifiedReceiptBytes,
} from "@/lib/spatial-data-preview";

function fileHrefFor(siteId: string, workAreaId: string, jobId: string): string {
  return `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-data-requests/${encodeURIComponent(jobId)}/file`;
}

function ThumbGlyph({ fileName }: { fileName: string }) {
  const ext = fileName.includes(".") ? fileName.split(".").pop()!.toUpperCase().slice(0, 4) : "FILE";
  return <span aria-hidden="true" className="flex h-[54px] w-[72px] shrink-0 items-center justify-center rounded-md border border-line bg-sunk font-mono text-[10px] font-bold text-ink-2">{ext}</span>;
}

/**
 * 레일용 정확한 자료 썸네일 — 같은 자료의 이미 준비된 창 하나만 그린다.
 *
 * - 바이트는 같은 세션의 준비 파일 BFF에서만 받는다. 영수증(출력 크기·전체
 *   SHA-256)이 모두 일치할 때만 디코딩하며, 하나라도 다르면 그리지 않는다.
 * - 최대 2개까지만 동시에 진행한다(기존 미리보기 슬롯). 목록 진입의 이름·
 *   행동을 막지 않게 화면에 들어올 때만 읽는다.
 * - 대표 화면을 다른 자료에서 가져오지 않는다. 읽을 창이 없거나 실패하면
 *   형식 글리프로 둔다(빈칸·대체 그림을 두지 않는다).
 * - 72px 탐색용 축소이며 측정·판정의 근거가 아니다.
 */
export function MaterialThumb(props: Parameters<typeof MaterialThumbFrame>[0]) {
  // A refreshed receipt must never inherit the prior window's ready pixels or
  // failure state while its own bytes are still being verified.
  const identity = JSON.stringify([
    props.siteId, props.workAreaId, props.jobId,
    props.receipt?.outputSha256, props.receipt?.outputSizeBytes,
    props.receipt?.width, props.receipt?.height,
  ]);
  return <MaterialThumbFrame key={identity} {...props} />;
}

function MaterialThumbFrame({
  siteId,
  workAreaId,
  jobId,
  receipt,
  fileName,
}: {
  siteId: string;
  workAreaId: string;
  /** 그릴 수 있는 준비 기록이 없을 때 null — 글리프로 둔다. */
  jobId: string | null;
  receipt: SpatialDataReceipt | null;
  fileName: string;
}) {
  const boxRef = useRef<HTMLSpanElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!receipt || !jobId) return;
    let cancelled = false;
    const controller = new AbortController();

    async function load(): Promise<void> {
      let release: (() => void) | null = null;
      try {
        release = await acquirePreviewSlot(controller.signal);
        if (cancelled || controller.signal.aborted) return;
        const bytes = await fetchVerifiedReceiptBytes(
          fileHrefFor(siteId, workAreaId, jobId as string),
          { outputSha256: (receipt as SpatialDataReceipt).outputSha256, outputSizeBytes: (receipt as SpatialDataReceipt).outputSizeBytes },
          controller.signal,
        );
        const image = await decodeReceiptPreview(bytes, {
          width: (receipt as SpatialDataReceipt).width,
          height: (receipt as SpatialDataReceipt).height,
        });
        if (cancelled || controller.signal.aborted) return;
        const canvas = canvasRef.current;
        if (!canvas) return;
        const scale = Math.min(72 / image.width, 54 / image.height);
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        const context = canvas.getContext("2d");
        if (!context) throw new Error("no-2d-context");
        const off = document.createElement("canvas");
        off.width = image.width;
        off.height = image.height;
        const offContext = off.getContext("2d");
        if (!offContext) throw new Error("no-2d-context");
        offContext.putImageData(new ImageData(image.pixels, image.width, image.height), 0, 0);
        context.imageSmoothingEnabled = true;
        context.drawImage(off, 0, 0, canvas.width, canvas.height);
        setReady(true);
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        release?.();
      }
    }

    if (typeof IntersectionObserver === "undefined") {
      void load();
      return () => {
        cancelled = true;
        controller.abort();
      };
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          void load();
        }
      },
      { rootMargin: "200px" },
    );
    const box = boxRef.current;
    if (box) observer.observe(box);
    else void load();
    return () => {
      cancelled = true;
      controller.abort();
      observer.disconnect();
    };
  }, [siteId, workAreaId, jobId, receipt]);

  if (!receipt || !jobId || failed) return <ThumbGlyph fileName={fileName} />;
  return <span ref={boxRef} aria-hidden="true" className="flex h-[54px] w-[72px] shrink-0 items-center justify-center overflow-hidden rounded-md border border-line bg-sunk">
    {!ready && <span className="size-6 animate-pulse rounded bg-line" />}
    <canvas ref={canvasRef} className={ready ? "block max-h-full max-w-full" : "hidden"} />
  </span>;
}
