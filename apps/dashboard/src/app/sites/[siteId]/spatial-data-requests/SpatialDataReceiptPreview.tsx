"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";

import type { SpatialDataReceipt } from "@/lib/core-api/spatial-data-types";
import {
  decodeReceiptPreview,
  fetchVerifiedReceiptBytes,
  SpatialDataPreviewError,
  type DecodedReceiptPreview,
} from "@/lib/spatial-data-preview";
import {
  DISPLAY_GESTURE_HINT,
  displayGestureKeyAction,
  displayWheelReady,
  isDisplayZoomWheelIntent,
} from "@/lib/spatial-display-gesture";
import {
  displayDragFractions,
  displayViewTransform,
  displayZoomPercent,
  isDisplayViewMoved,
  useDisplayViewState,
} from "@/lib/spatial-display-view";
import { DisplayControlStrip, type DisplayControlAction } from "../DisplayControlStrip";

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
}) {
  const [phase, setPhase] = useState<Phase>(() => ({ name: autoLoad ? "loading" : "idle" }));
  const [image, setImage] = useState<DecodedReceiptPreview | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // ── 부분 출력의 화면 표시 뷰 — 같은 버퍼의 CSS 표시만 바꾼다. 새 요청 없음 ──
  const display = useDisplayViewState();
  const view = display.view;
  const [viewNote, setViewNote] = useState<string | null>(null);

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

  // ── 부분 출력의 화면 표시 제스처 — CSS 변환만이며 새 요청을 만들지 않는다 ──
  const receiptViewWrapRef = useRef<HTMLDivElement | null>(null);
  const receiptDragRef = useRef<{ x: number; y: number } | null>(null);
  const receiptWheelLastRef = useRef(0);

  const receiptEdgeNote = (kind: "pan" | "zoom") => {
    setViewNote(
      kind === "pan"
        ? "부분 출력 끝이라 더 이상 옮길 수 없습니다. 원래 보기로 돌아가세요."
        : "표시 확대 한계입니다. 원래 보기로 돌아가세요.",
    );
  };

  useEffect(() => {
    if (!gestureControls) return;
    const wrap = receiptViewWrapRef.current;
    if (!wrap) return;
    const onWheel = (event: WheelEvent) => {
      const focused = wrap.contains(document.activeElement);
      if (!isDisplayZoomWheelIntent({ focused, ctrlKey: event.ctrlKey })) return;
      event.preventDefault();
      const now = Date.now();
      if (!displayWheelReady(receiptWheelLastRef.current, now)) return;
      receiptWheelLastRef.current = now;
      if (display.zoom(event.deltaY > 0 ? -1 : 1)) setViewNote(null);
      else receiptEdgeNote("zoom");
    };
    wrap.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      wrap.removeEventListener("wheel", onWheel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- display 액션은 ref 거울로 최신 상태를 쓰므로 리스너를 다시 달지 않는다
  }, [gestureControls, phase]);

  const onReceiptControlAction = (action: DisplayControlAction) => {
    switch (action) {
      case "pan-left": if (display.pan(-0.25, 0)) setViewNote(null); else receiptEdgeNote("pan"); return;
      case "pan-right": if (display.pan(0.25, 0)) setViewNote(null); else receiptEdgeNote("pan"); return;
      case "pan-up": if (display.pan(0, -0.25)) setViewNote(null); else receiptEdgeNote("pan"); return;
      case "pan-down": if (display.pan(0, 0.25)) setViewNote(null); else receiptEdgeNote("pan"); return;
      case "zoom-in": if (display.zoom(1)) setViewNote(null); else receiptEdgeNote("zoom"); return;
      case "zoom-out": if (display.zoom(-1)) setViewNote(null); else receiptEdgeNote("zoom"); return;
      case "reset": display.reset(); setViewNote(null); return;
    }
  };

  const onReceiptKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.nativeEvent.isComposing) return;
    const action = displayGestureKeyAction(event.key);
    if (!action) return;
    event.preventDefault();
    if (action.kind === "pan") {
      if (display.pan(action.dCol, -action.dRow)) setViewNote(null);
      else receiptEdgeNote("pan");
    } else if (action.kind === "zoom") {
      if (display.zoom(action.factor < 1 ? 1 : -1)) setViewNote(null);
      else receiptEdgeNote("zoom");
    } else {
      display.reset();
      setViewNote(null);
    }
  };

  const onReceiptPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    // 터치 드래그는 세로 스크롤을 위해 건드리지 않는다. 합성 환경의
    // button 미지정(언어 명세상 주 버튼)은 주 버튼으로 간주한다.
    if (event.pointerType === "touch") return;
    if (event.button !== undefined && event.button !== 0) return;
    receiptDragRef.current = { x: event.clientX, y: event.clientY };
    if (typeof event.currentTarget.setPointerCapture === "function") {
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // 캡처 실패해도 같은 요소 위의 이동·종료는 그대로 처리한다.
      }
    }
  };

  const onReceiptPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = receiptDragRef.current;
    if (!start) return;
    const wrap = receiptViewWrapRef.current;
    const rect = wrap?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return;
    const fractions = displayDragFractions(
      event.clientX - start.x,
      event.clientY - start.y,
      rect.width,
      rect.height,
    );
    if (!fractions) return;
    if (display.pan(fractions.fx, fractions.fy)) setViewNote(null);
    else receiptEdgeNote("pan");
    receiptDragRef.current = { x: event.clientX, y: event.clientY };
  };

  const onReceiptPointerEnd = () => {
    receiptDragRef.current = null;
  };

  return <section aria-label="준비된 출력 미리보기" className={compact ? "" : "border-t border-line pt-4"}>
    {!compact && <div className="flex flex-wrap items-start justify-between gap-2">
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
      <div className="mt-3 flex flex-col gap-2">
        {gestureControls ? (
          <>
            <div
              ref={receiptViewWrapRef}
              tabIndex={0}
              role="group"
              aria-label={`부분 출력 ${phase.width} × ${phase.height} 픽셀. 마우스로 끌거나 방향키로 이동하고, + − 키로 확대합니다. 휠은 그림을 선택한 후, 또는 Ctrl과 함께 사용하세요. Home 키는 원래 보기로 돌아갑니다.`}
              onPointerDown={onReceiptPointerDown}
              onPointerMove={onReceiptPointerMove}
              onPointerUp={onReceiptPointerEnd}
              onPointerCancel={onReceiptPointerEnd}
              onKeyDown={onReceiptKeyDown}
              className="overflow-hidden rounded border border-line bg-sunk/30 focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{ touchAction: "pan-y" }}
            >
              <div
                className="inline-block"
                style={{ transform: displayViewTransform(view), transformOrigin: "0 0" }}
              >
                <canvas ref={canvasRef} className="block max-w-none" style={{ imageRendering: "pixelated" }} />
              </div>
            </div>
            <DisplayControlStrip
              groupLabel="부분 출력 확대·이동"
              onAction={onReceiptControlAction}
              zoomInDisabled={view.zoom >= 4}
              zoomOutDisabled={view.zoom <= 1}
            />
            {viewNote && (
              <p className="text-[11.5px] leading-5 text-ink-2" role="status">{viewNote}</p>
            )}
            <p className="text-[11.5px] leading-5 text-ink-muted">{DISPLAY_GESTURE_HINT}</p>
            {isDisplayViewMoved(view) && (
              <p className="text-[12px] leading-5 text-ink-2" role="status">
                표시 확대 {displayZoomPercent(view)}%
                {view.cx !== 0.5 || view.cy !== 0.5 ? " · 이동한 화면" : ""} · 원본 버퍼는 그대로 둡니다.
              </p>
            )}
          </>
        ) : (
          <canvas ref={canvasRef} className="max-w-full rounded border border-line" style={{ imageRendering: "pixelated" }} />
        )}
        <p className="text-[12px] leading-5 text-ink-2">
          출력 {phase.width} × {phase.height} 픽셀 ·{" "}
          {phase.color
            ? "실제 픽셀 색상을 그대로 표시합니다. WGS84 변환·지도 타일·보정을 적용하지 않았습니다."
            : "단일 밴드를 명암으로 표시합니다(화면용 상대 음영). 이 미리보기는 수직 기준 적합성·높이 정확도를 판정하지 않습니다."}
        </p>
        {!phase.color && (
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
        <p className="text-[11.5px] leading-5 text-ink-muted">
          정확도 평가·측량·정산 근거가 아닙니다. 체적·면적 등 정량 계산을 하지 않습니다.
        </p>
      </div>
    )}
    {phase.name !== "ready" && <canvas ref={canvasRef} className="hidden" aria-hidden="true" />}
  </section>;
}
