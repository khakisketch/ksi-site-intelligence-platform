"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { SpatialDataReceipt } from "@/lib/core-api/spatial-data-types";
import {
  decodeReceiptPreview,
  fetchVerifiedReceiptBytes,
  SpatialDataPreviewError,
  type DecodedReceiptPreview,
} from "@/lib/spatial-data-preview";
import {
  displayZoomPercent,
  isDisplayViewMoved,
} from "@/lib/spatial-display-view";
import {
  useDirectViewport,
  ViewportGestureHint,
  ViewportResetButton,
} from "../DirectDisplayViewport";

/**
 * 준비된 출력의 브라우저 미리보기 — 요청 상세 화면의 일부다.
 *
 * - 바이트는 같은 세션의 준비 파일 BFF에서만 받는다. BFF→Core가 권한·현재성을
 *   매번 다시 확인하므로, 이 화면은 다운로드 권한을 새로 만들지 않는다.
 * - Core 준비 기록의 요청 식별자·출력 크기·전체 SHA-256이 모두 일치할 때만
 *   디코딩한다. 하나라도 다르면 표시하지 않고 일반 다운로드를 안내한다.
 * - 원본 픽셀을 그대로 그린다. WGS84 재해석·지도 타일·보정을 적용하지 않으며,
 *   체적·면적 등 정량 계산을 하지 않는다.
 * - 읽기는 쓰기 게이트(1024 변형 한도·노트북 경계)의 대상이 아니다 — 기존
 *   요청을 확인한 뒤에는 모바일에서도 볼 수 있다.
 */

type Phase =
  | { name: "idle" }
  | { name: "loading" }
  | { name: "ready"; width: number; height: number; color: boolean }
  | { name: "failure"; message: string };

function failureMessage(error: unknown): string {
  if (!(error instanceof SpatialDataPreviewError)) {
    return "미리보기를 표시하지 못했습니다. 아래 준비된 파일 다운로드로 받으세요.";
  }
  switch (error.kind) {
    case "CANCELLED":
      return "불러오기를 취소했습니다.";
    case "TIMEOUT":
      return "준비된 파일을 받을 수 있는 시간을 넘겨 중단했습니다. 아래 준비된 파일 다운로드로 받으세요.";
    case "TOO_LARGE":
      return "준비된 출력이 브라우저 표시 한계를 넘어 미리보기를 표시하지 않습니다. 아래 다운로드로 받으세요.";
    case "SIZE_MISMATCH":
    case "HASH_MISMATCH":
      return "받은 바이트가 Core 준비 기록(출력 크기·파일 확인값)과 달라 화면에 표시하지 않습니다. 아래 다운로드로 다시 받으세요.";
    case "BAD_RECEIPT":
    case "UNSUPPORTED":
      return error.message;
    case "HTTP": {
      if (error.status === 401) return "세션이 만료되었습니다. 다시 로그인한 뒤 시도하세요.";
      switch (error.code) {
        case "PERMISSION_DENIED":
          return "현재 계정으로 이 파일을 받을 권한이 없습니다. 권한 있는 담당자에게 요청하세요.";
        case "GRANT_REQUIRED":
          return "이 자료에 대한 명시적 사용 권리가 아직 없습니다. 관리자에게 권리 설정을 요청하세요.";
        case "ACCESS_REVOKED":
          return "이 자료의 사용 권리가 회수되어 미리보기를 표시하지 않습니다. 관리자에게 확인하세요.";
        case "ACCESS_EXPIRED":
        case "RETENTION_EXPIRED":
          return "이 파일의 접근 기한이 지나 미리보기를 표시하지 않습니다. 관리자에게 확인하세요.";
        case "ACTIVATION_UNAVAILABLE":
        case "CURRENTNESS_UNAVAILABLE":
          return "현재 권리 상태를 확인할 수 없어 미리보기를 표시하지 않습니다. 잠시 후 다시 시도하세요.";
        case "NOT_FOUND":
          return "요청을 찾을 수 없거나 현재 조회할 수 없습니다.";
        default:
          break;
      }
      if (error.status === 404) return "요청을 찾을 수 없거나 현재 조회할 수 없습니다.";
      if (error.status === 503 || (error.status !== null && error.status >= 500)) {
        return "일시적으로 불러오지 못했습니다. 잠시 후 다시 시도하세요.";
      }
      return error.serverMessage ?? "준비된 파일을 받지 못했습니다. 현재 상태를 다시 확인하세요.";
    }
    case "NETWORK":
    default:
      return error.message;
  }
}

export function SpatialDataReceiptPreview({
  jobId,
  receipt,
  fileHref,
  autoLoad = false,
  compact = false,
  gestureControls = false,
  presentation = "default",
}: {
  siteId: string;
  workAreaId: string;
  jobId: string;
  receipt: SpatialDataReceipt;
  fileHref: string;
  autoLoad?: boolean;
  compact?: boolean;
  /** 탐색 폴백의 부분 보기처럼, 같은 바이트의 화면 표시 제스처를 둘 때 true. */
  gestureControls?: boolean;
  /**
   * 자료 탐색 무대용 — 큰 픽셀을 먼저 두고 긴 안내·범례·진단은 펼침에 둔다.
   * 기본값 "default"는 기존 화면 그대로이며, 바이트 검증·읽기 흐름을 바꾸지 않는다.
   */
  presentation?: "default" | "canvas";
}) {
  const [phase, setPhase] = useState<Phase>(() => ({ name: autoLoad ? "loading" : "idle" }));
  const [image, setImage] = useState<DecodedReceiptPreview | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const canvasMode = presentation === "canvas";
  const abortRef = useRef<AbortController | null>(null);
  // ── 부분 출력 직접 조작 — 같은 훅 하나로 같은 규칙을 탄다 ──
  const viewport = useDirectViewport();
  const view = viewport.view;
  const attributionLine = [receipt.attribution, receipt.modificationNotice]
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .join(" ");
  const limitationLine = receipt.limitations
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .join(" ");
  const receiptNotice = (
    <>
      {attributionLine && <p className="break-words leading-5">출처 · {attributionLine}</p>}
      {limitationLine && <p className="break-words leading-5 text-ink-muted">제한 · {limitationLine}</p>}
    </>
  );

  useEffect(() => () => {
    abortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (phase.name !== "ready" || image === null) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("no-2d-context");
      context.putImageData(new ImageData(image.pixels, image.width, image.height), 0, 0);
    } catch {
      setPhase({ name: "failure", message: "이 브라우저에서 미리보기를 그릴 수 없습니다. 다운로드는 그대로 받을 수 있습니다." });
    }
  }, [phase, image]);

  const cancel = () => {
    abortRef.current?.abort();
  };

  const load = useCallback(async () => {
    if (abortRef.current) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase({ name: "loading" });
    setImage(null);
    try {
      if (receipt.jobId !== jobId) {
        throw new SpatialDataPreviewError("BAD_RECEIPT", "준비 기록의 요청 식별자가 현재 요청과 달라 표시하지 않습니다.");
      }
      const bytes = await fetchVerifiedReceiptBytes(
        fileHref,
        { outputSha256: receipt.outputSha256, outputSizeBytes: receipt.outputSizeBytes },
        controller.signal,
      );
      const decoded = await decodeReceiptPreview(bytes, { width: receipt.width, height: receipt.height });
      if (controller.signal.aborted) return;
      setImage(decoded);
      setPhase({ name: "ready", width: decoded.width, height: decoded.height, color: decoded.color });
    } catch (error) {
      if (controller.signal.aborted) {
        setPhase({ name: "idle" });
        return;
      }
      setPhase({ name: "failure", message: failureMessage(error) });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [receipt, jobId, fileHref]);

  useEffect(() => {
    if (!autoLoad) return;
    let mounted = true;
    // 표시 자리를 먼저 확보하고 읽기를 시작한다. 진입이 취소되면 미시작 읽기도 버린다.
    queueMicrotask(() => { if (mounted) void load(); });
    return () => {
      mounted = false;
      abortRef.current?.abort();
    };
  }, [autoLoad, load]);

  return <section aria-label="준비된 출력 미리보기" className={compact || canvasMode ? "" : "border-t border-line pt-4"}>
    {!compact && !canvasMode && <div className="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h3 className="text-[15px] font-bold">준비된 출력 미리보기</h3>
        <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">
          Core 준비 기록과 바이트 전체가 일치할 때만 화면에 표시합니다. 미리보기도 다운로드와 같은 권한·보관 확인을 거칩니다.
        </p>
      </div>
    </div>}
    {phase.name === "idle" && (
      <button type="button" className="btn min-h-11 mt-3" onClick={() => void load()}>
        미리보기 불러오기
      </button>
    )}
    {phase.name === "loading" && (
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <p className="text-[12px] text-ink-2" role="status">자료 읽는 중…</p>
        <button type="button" className="btn min-h-11" onClick={cancel}>
          불러오기 취소
        </button>
      </div>
    )}
    {phase.name === "failure" && (
      <div className="mt-3 flex flex-col gap-2">
        <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2" role="alert">
          {phase.message}
        </p>
        <div>
          <button type="button" className="btn min-h-11" onClick={() => void load()}>
            다시 시도
          </button>
        </div>
      </div>
    )}
    {phase.name === "ready" && (
      <div className={canvasMode ? "flex min-w-0 flex-col gap-1.5" : "mt-3 flex flex-col gap-2"}>
        {gestureControls ? (
          <>
            <div
              {...viewport.frameProps}
              aria-label={`부분 출력 ${phase.width} × ${phase.height} 픽셀. 직접 끌어서 보고, 휠·두 손가락·두 번 두드리기로 확대합니다. 그림을 선택하면 방향키·Home 키도 쓸 수 있습니다.`}
              className={`relative mx-auto ${canvasMode ? "w-full " : ""}cursor-grab overflow-hidden rounded border border-line bg-sunk/30 focus-visible:outline-2 focus-visible:outline-offset-2 active:cursor-grabbing`}
              style={canvasMode
                ? { maxWidth: `min(100%, calc(max(160px, 100dvh - 400px) * ${phase.width / phase.height}))` }
                : { maxWidth: `min(100%, calc(52dvh * ${phase.width / phase.height}))` }}
            >
              <div
                {...viewport.contentProps}
                className="relative h-full w-full"
              >
                <canvas ref={canvasRef} className="block h-auto w-full" style={{ imageRendering: "pixelated" }} />
              </div>
              <ViewportResetButton onReset={viewport.reset} />
            </div>
            {viewport.note && (
              <p className="text-[11.5px] leading-5 text-ink-2" role="status">{viewport.note}</p>
            )}
            {canvasMode ? (
              <>
                {isDisplayViewMoved(view) && (
                  <p className="text-[11.5px] leading-5 text-ink-2" role="status">
                    표시 확대 {displayZoomPercent(view)}%
                    {view.cx !== 0.5 || view.cy !== 0.5 ? " · 이동한 화면" : ""} · 원본 버퍼는 그대로 둡니다.
                  </p>
                )}
                {receipt.attribution.trim() && (
                  <p className="break-words text-[11.5px] leading-5 text-ink-2">출처 · {receipt.attribution}</p>
                )}
                <details className="text-[11.5px] text-ink-2">
                  <summary className="tap-target cursor-pointer font-semibold">표시 안내·출처</summary>
                  <div className="mt-1 flex min-w-0 flex-col gap-1">
                    <ViewportGestureHint />
                    {receiptNotice}
                    <p className="leading-5 text-ink-muted">정확도 평가·측량·정산 근거가 아닙니다. 체적·면적 등 정량 계산을 하지 않습니다.</p>
                  </div>
                </details>
              </>
            ) : (
              <>
                <ViewportGestureHint />
                {isDisplayViewMoved(view) && (
                  <p className="text-[12px] leading-5 text-ink-2" role="status">
                    표시 확대 {displayZoomPercent(view)}%
                    {view.cx !== 0.5 || view.cy !== 0.5 ? " · 이동한 화면" : ""} · 원본 버퍼는 그대로 둡니다.
                  </p>
                )}
              </>
            )}
          </>
        ) : (
          <canvas ref={canvasRef} className="max-w-full rounded border border-line" style={{ imageRendering: "pixelated" }} />
        )}
        <p className={canvasMode ? "text-[11.5px] leading-5 text-ink-2" : "text-[12px] leading-5 text-ink-2"}>
          출력 {phase.width} × {phase.height} 픽셀 ·{" "}
          {phase.color
            ? "실제 픽셀 색상을 그대로 표시합니다. WGS84 변환·지도 타일·보정을 적용하지 않았습니다."
            : "단일 밴드를 명암으로 표시합니다(화면용 상대 음영). 이 미리보기는 수직 기준 적합성·높이 정확도를 판정하지 않습니다."}
        </p>
        {!phase.color && !canvasMode && (
          <div className="flex items-center gap-2 text-[11.5px] text-ink-muted" aria-label="상대 음영 범례">
            <span>어두움</span>
            <span
              aria-hidden="true"
              className="inline-block h-2 w-24 rounded"
              style={{ background: "linear-gradient(to right, #000, #fff)" }}
            />
            <span>밝음 — 측정값 아님</span>
          </div>
        )}
        {!canvasMode && (
          <p className="text-[11.5px] leading-5 text-ink-muted">
            정확도 평가·측량·정산 근거가 아닙니다. 체적·면적 등 정량 계산을 하지 않습니다.
          </p>
        )}
      </div>
    )}
    {phase.name !== "ready" && <canvas ref={canvasRef} className="hidden" aria-hidden="true" />}
  </section>;
}
