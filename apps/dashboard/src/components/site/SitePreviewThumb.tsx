"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { capturePeriodTitle, dataKindLabel } from "@/lib/operator-language";
import {
  acquirePreviewSlot,
  sanitizeSitePreviewDescriptor,
  type SitePreviewDescriptor,
} from "@/lib/site-preview";
import {
  decodeReceiptPreview,
  fetchVerifiedReceiptBytes,
  type DecodedReceiptPreview,
} from "@/lib/spatial-data-preview";
import { SiteVisualTile, useSiteVisualTile } from "@/components/site/SiteVisualTile";

/**
 * 현장 목록 미리보기 — 실제 준비된 출력의 작은 인식용 표시.
 *
 * 같은 세션 BFF 기술서(`/api/sites/[siteId]/preview`)로 현재 허용된 준비
 * 출력 하나를 찾고, 허용될 때만 같은 세션 준비 파일 BFF에서 바이트를 받아
 * 영수증 대조 후 디코딩한다. 합성·플레이스홀더·타 현장 사진은 절대 쓰지
 * 않으며, 카탈로그 해시로 원본 바이트를 직접 읽지 않는다.
 *
 * - 보이는 자리에서만 읽는다(IntersectionObserver). 기술서 조회부터 바이트·
 *   디코딩까지 같은 bounded 슬롯(최대 2개) 안에서 돌고, 페이지를 떠나면
 *   취소한다. 대기 중 취소는 큐에서 즉시 빠진다.
 * - 기술서를 다른 마운트와 공유하지 않는다. 각 마운트가 자기 취소 신호와
 *   현재 세션으로 새로 조회한다(진행 중 조회도 계정 간에 섞지 않는다).
 * - 원인을 알 때(읽기 실패·거부·미확인)는 '확인하지 못함'으로, 완전히 읽고
 *   없음이 확정될 때만 '표시할 미리보기 없음'으로 구분한다. 어느 쪽도 등록
 *   자료 부재로 말하지 않는다.
 * - 클릭은 기술서가 가리킨 정확한 구역·자산·버전의 현장 주소로 간다.
 * - 실제 픽셀이 없을 때는 현장 목록 페이지가 같은 세션으로 집계한 합성
 *   기술서(`SiteVisualTileProvider`)가 있으면, 검증 뒤 범위 도식을 대신
 *   그린다(사진이 아님을 밝힌다). 합성 기술서가 없어도 기존의 '없음·미확인'
 *   문구는 그대로다 — 픽셀이 합성을 이긴다.
 * - 조작(확대·이동·폼·스케줄러)이 없다. 링크 안에는 캔버스+설명만 둔다.
 *   출처·변경 안내는 링크 밖 접힌 정보(카드)나 접근성 설명(목록행)으로 둔다.
 * - 대표 미리보기는 언제나 부분 범위다. 단일 준비 창으로 전체 현장·전체
 *   자산을 주장하지 않는다.
 */

type Phase = { name: "pending" } | { name: "loading" } | { name: "ready" } | { name: "composed" } | { name: "unknown" } | { name: "empty" };

type LookupOutcome =
  | { status: "ready"; link: SitePreviewDescriptor }
  | { status: "empty" }
  | { status: "unknown" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

async function fetchPreviewDescriptor(siteId: string, signal: AbortSignal): Promise<LookupOutcome> {
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/preview`, {
        method: "GET",
        cache: "no-store",
        redirect: "error",
        signal,
      });
      if (!response.ok) return { status: "unknown" };
      const raw: unknown = await response.json();
      if (isRecord(raw) && raw.available === false) {
        return raw.reason === "no-output" ? { status: "empty" } : { status: "unknown" };
      }
      const link = sanitizeSitePreviewDescriptor(raw, siteId);
      return link ? { status: "ready", link } : { status: "unknown" };
    } catch {
      return { status: "unknown" };
    }
}

function captureLine(link: SitePreviewDescriptor): string {
  return capturePeriodTitle(
    link.asset.captureStartedAt,
    link.asset.captureEndedAt,
    { captureDate: link.asset.captureDate },
  );
}

function precisionLine(link: SitePreviewDescriptor): string | null {
  const parts: string[] = [];
  if (link.asset.revision !== null) parts.push(`등록 버전 ${link.asset.revision}`);
  if (link.asset.gsdM !== null && Number.isFinite(link.asset.gsdM)) {
    parts.push(`제출 GSD ${link.asset.gsdM}m`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function SitePreviewThumb({ siteId, size }: { siteId: string; size: "card" | "row" }) {
  const [phase, setPhase] = useState<Phase>({ name: "pending" });
  const [preview, setPreview] = useState<{ image: DecodedReceiptPreview; link: SitePreviewDescriptor } | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rowDescriptionId = useId();
  // 합성 기술서 — 픽셀이 없을 때만 쓰는 대체 타일. 기술서 조회(fetch)·바이트
  // 읽기를 새로 하지 않으며, 그리기 전에 모양을 다시 검증한다.
  const composedTile = useSiteVisualTile(siteId);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    let cancelled = false;
    const controller = new AbortController();

    async function load(): Promise<void> {
      setPhase({ name: "loading" });
      let release: (() => void) | null = null;
      try {
        release = await acquirePreviewSlot(controller.signal);
        if (cancelled || controller.signal.aborted) return;
        const outcome = await fetchPreviewDescriptor(siteId, controller.signal);
        if (cancelled || controller.signal.aborted) return;
        if (outcome.status !== "ready") {
          // 픽셀이 이긴다 — 합성은 픽셀이 없을 때만 대신 그린다.
          if (composedTile) {
            setPhase({ name: "composed" });
            return;
          }
          if (outcome.status === "empty") setPhase({ name: "empty" });
          else setPhase({ name: "unknown" });
          return;
        }
        const link = outcome.link;
        if (link.partial === false) {
          // 방어: 대표는 언제나 부분 범위다. 기술서가 전체를 주장하면 믿지 않는다.
          setPhase({ name: "unknown" });
          return;
        }
        const bytes = await fetchVerifiedReceiptBytes(
          link.fileHref,
          { outputSha256: link.outputSha256, outputSizeBytes: link.outputSizeBytes },
          controller.signal,
        );
        const image = await decodeReceiptPreview(bytes, { width: link.width, height: link.height });
        if (cancelled) return;
        setPreview({ image, link });
        setPhase({ name: "ready" });
      } catch {
        if (!cancelled) setPhase({ name: "unknown" });
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
    observer.observe(box);
    return () => {
      cancelled = true;
      controller.abort();
      observer.disconnect();
    };
  }, [siteId, composedTile]);

  useEffect(() => {
    if (phase.name !== "ready" || preview === null) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      canvas.width = preview.image.width;
      canvas.height = preview.image.height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("no-2d-context");
      context.putImageData(new ImageData(preview.image.pixels, preview.image.width, preview.image.height), 0, 0);
    } catch {
      setPhase({ name: "unknown" });
      setPreview(null);
    }
  }, [phase, preview]);

  const kindLabel = preview ? dataKindLabel(preview.link.artifactKind) : null;
  const figureLabel = preview
    ? `${preview.link.workAreaName} ${kindLabel} 미리보기 일부 범위 열기 · ${captureLine(preview.link)}`
    : null;
  const attributionText = preview
    ? [preview.link.asset.attribution, preview.link.asset.modificationNotice]
        .filter((line): line is string => typeof line === "string" && line.trim().length > 0)
        .join(" ")
    : null;

  if (size === "row") {
    return (
      <div ref={boxRef} data-site-preview="row" className="h-11 w-14 shrink-0 overflow-hidden rounded border border-line bg-sunk">
        {phase.name === "ready" && preview !== null ? (
          <>
            <Link
              href={preview.link.siteHref}
              aria-label={figureLabel ?? undefined}
              aria-describedby={rowDescriptionId}
              className="block size-full"
            >
              <canvas ref={canvasRef} className="block size-full object-cover" />
            </Link>
            <span id={rowDescriptionId} className="sr-only">
              {attributionText} 부분 범위이며 정확도 평가·측량·정산 근거가 아닙니다.
            </span>
          </>
        ) : phase.name === "composed" && composedTile !== null ? (
          <SiteVisualTile tile={composedTile} size="row" />
        ) : (
          <span
            role="img"
            aria-label={
              phase.name === "loading" || phase.name === "pending"
                ? "미리보기 불러오는 중"
                : phase.name === "unknown"
                  ? "미리보기를 확인하지 못함"
                  : "표시할 미리보기 없음"
            }
            className="block size-full"
          />
        )}
      </div>
    );
  }

  return (
    <div>
      <div ref={boxRef} data-site-preview="card" className="relative aspect-[16/9] overflow-hidden bg-sunk">
        {phase.name === "ready" && preview !== null ? (
          <Link
            href={preview.link.siteHref}
            aria-label={figureLabel ?? undefined}
            className="block size-full"
          >
            <figure className="relative size-full">
              <canvas ref={canvasRef} className="absolute inset-0 size-full object-cover" />
              <figcaption className="absolute right-0 bottom-0 left-0 flex flex-wrap items-end justify-between gap-x-3 gap-y-0.5 bg-accent px-4 py-2 text-accent-on">
                <span className="min-w-0 text-[12px] font-semibold break-keep">
                  {preview.link.workAreaName} · {kindLabel}
                  <span className="ml-1 rounded bg-white/20 px-1 py-px text-[10.5px]">부분 범위</span>
                  {preview.link.artifactKind === "dsm" && <span className="ml-1 rounded bg-white/20 px-1 py-px text-[10.5px]">상대 음영</span>}
                </span>
                <span className="num w-full min-w-0 text-[10.5px] break-keep">
                  {captureLine(preview.link)}
                  {precisionLine(preview.link) ? ` · ${precisionLine(preview.link)}` : ""}
                </span>
              </figcaption>
            </figure>
          </Link>
        ) : phase.name === "composed" && composedTile !== null ? (
          <SiteVisualTile tile={composedTile} size="card" />
        ) : phase.name === "loading" || phase.name === "pending" ? (
          <>
            <span aria-hidden="true" className="absolute inset-0 animate-pulse bg-line/40" />
            <span className="sr-only" role="status">미리보기 불러오는 중</span>
          </>
        ) : (
          <p className="flex h-full items-center justify-center px-4 py-3 text-center text-[12px] break-keep text-ink-2">
            {phase.name === "unknown" ? "미리보기를 확인하지 못함" : "표시할 미리보기 없음"}
            <span className="sr-only"> — 등록 자료 현황을 뜻하지 않습니다. 영역·자료는 현장 열기에서 확인하세요.</span>
          </p>
        )}
      </div>
      {phase.name === "ready" && preview !== null && attributionText && (
        <details className="border-t border-line px-4 py-1">
          <summary className="tap-target inline-flex cursor-pointer items-center text-[11.5px] font-semibold text-ink-muted">
            자료 정보
          </summary>
          <p className="pb-2 text-[11.5px] leading-5 break-keep text-ink-2">{attributionText}</p>
        </details>
      )}
    </div>
  );
}
