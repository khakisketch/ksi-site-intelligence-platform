"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import {
  decodeReceiptPreview,
  fetchVerifiedReceiptBytes,
  SpatialDataPreviewError,
  type DecodedReceiptPreview,
} from "@/lib/spatial-data-preview";
import {
  MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM,
  PIXEL_WINDOW_BLOCKER_COPY,
  initialPixelWindowDims,
  resolveBoundedPixelWindow,
  type PixelWindowSelection,
} from "@/lib/spatial-data-request";
import {
  DisplayPrepareIssueError,
  DisplayPrepareScheduler,
  stableIdempotencyKey,
  stablePrepareKey,
  type DisplaySchedulerSnapshot,
  type ScheduledDisplayWindow,
} from "@/lib/spatial-display-scheduler";
import {
  displayZoomPercent,
  isDisplayViewMoved,
} from "@/lib/spatial-display-view";
import {
  useDirectViewport,
  ViewportGestureHint,
  ViewportResetButton,
} from "./DirectDisplayViewport";
import { WorkbenchMediaState, WorkbenchRefreshButton, DetailsPortal } from "./WorkbenchMediaState";
import {
  AUDIT_STATE_NOTE,
  DSM_RELATIVE_LEGEND_LABEL,
  DSM_RELATIVE_SHADING_NOTE,
  DSM_WINDOW_STRETCH_NOTE,
  FOREIGN_WINDOW_COPY,
  NO_COMPOSITE_FLAG_COPY,
  VALIDATION_STATE_NOTE,
  VIEWABILITY_STATE_NOTE,
  WINDOWED_VIEWER_ADAPTER_LABEL,
  WINDOWED_VIEWER_ADAPTER_NOTE,
  WINDOWED_VIEWER_READ_LABEL,
  WINDOWED_VIEWER_REQUEST_LABEL,
  adjacentWindowSelection,
  formatNativeWindowExtent,
  inspectionOutcomeLabel,
  readableWindowJobs,
  preparedWindowFallback,
  sharedPlaneForCompare,
  windowOptionLabel,
  type PreparedWindowJob,
  type WindowedViewerLayer,
} from "@/lib/site-windowed-pixel-viewer";
import { REASON_COPY as SPATIAL_DATA_REQUEST_REASON_COPY } from "@/app/sites/[siteId]/spatial-assets/SpatialDataRequestAction";
import { SiteMosaicViewport } from "@/app/sites/[siteId]/SiteMosaicViewport";
import { SpatialDataReceiptPreview } from "./spatial-data-requests/SpatialDataReceiptPreview";

/**
 * 창 단위 실제픽셀 보기 — 임시 시각화 어댑터 (SWX-2 B 단위).
 *
 * - 실제 파일의 준비된 창만 그린다. Core 준비 기록의 요청 식별자·출력 크기·
 *   전체 SHA-256이 모두 일치할 때만 디코딩한다(기존 guarded-GET + 검증 경로).
 * - 원본 좌표 평면 그대로 둔다. WGS84 재해석·외부 타일·좌표 변환을 하지
 *   않으며, EPSG:7850 같은 비-WGS84 평면도 같은 네이티브 평면의 작업구역
 *   링과 함께 그린다(지리 지도인 척하지 않는다).
 * - 브라우저 연산(확대·이동·상대 음영)은 화면 표시용이며 측정값이 아니다.
 * - 진입 시 자동으로 준비 요청을 만들지 않는다. 모든 쓰기는 작업자의 명시적
 *   버튼 클릭에서만 나간다.
 */

export interface WindowedPixelViewerProps {
  siteId: string;
  workAreaId: string;
  /** 같은 관측의 정사영상·DSM 레이어 — Core 사실의 옮김이다. */
  layers: WindowedViewerLayer[];
  /** 현재 계정이 읽을 수 있는 준비 기록(서버가 범위 확인한 것만). */
  jobs: PreparedWindowJob[];
  /** 준비 목록 읽기 상태 — 실패를 빈 목록으로 단정하지 않는다. */
  jobsState: "ready" | "denied" | "unavailable";
  canRead: boolean;
  canRequest: boolean;
  /** 기존 구역 자료 준비 화면으로 가는 링크 — 상태 확인·다운로드의 정로다. */
  requestsHref: string;
  /** 같은 네이티브 평면의 작업구역 링 — 좌표 변환 없이 겹쳐 그린다. */
  workAreaRing: Array<[number, number]> | null;
  workAreaCrs: string;
  /** 관측 표제 — 서버 사실의 정밀도 그대로(호출자가 만든다). */
  observationHeading: string | null;
  /** 같은 화면 id 충돌 방지용 접두사(비교 모드의 두 칸 등). */
  idPrefix: string;
  /** 탐색 첫 화면용 — 포착 표제·안내를 바깥 작업 막대가 맡을 때 true. */
  slimHeader?: boolean;
  /** 탐색 URL이 가리키는 정확한 층. 비교·낱창 보기의 로컬 선택과 구분한다. */
  selectedAssetRef?: string | null;
  /** 탐색에서 층을 바꿀 때 날짜 선택·Back·reload도 같은 원본을 가리키게 한다. */
  layerSelectionHref?: string;
  /** 같은 제출 묶음 안에서 층을 바꿀 때 이동할 주소 — 주면 로컬 상태 대신 링크로 둔다. */
  layerSelectHref?: string;
  layerSelectParam?: "assetRef" | "visualAAssetRef" | "visualBAssetRef";
  /** Workspace hosts the layer selector in its persistent rail. */
  hideLayerControls?: boolean;
  /** Local comparison-layer controls may be hosted in the shared rail without changing selectors. */
  layerControlsTargetId?: string;
  /**
   * 시각 탐색 기본 본문용 — 새 창 준비 요청 UI를 숨긴다. 읽기(준비 상태 다시
   * 확인·구역 자료 준비 길)와 접힌 진단(details)은 그대로 둔다. 기본 false로
   * 기존 호출의 동작을 바꾸지 않는다.
   */
  hidePrepareActions?: boolean;
  /**
   * 자료 탐색 무대용 — 큰 픽셀을 먼저 두고 긴 안내는 펼침에 둔다.
   * 기본값 "default"는 기존 화면 그대로이다.
   */
  presentation?: "default" | "canvas";
  /**
   * 작업환경 정보 서랍 안 숨김 자리 식별자 — 주면 접힌 상세를 무대가 아니라
   * 서랍으로 포털한다. 없으면 기존 자리 펼침을 둔다.
   */
  detailsTargetId?: string | null;
}

type PaintPhase =
  | { name: "idle" }
  | { name: "loading" }
  | { name: "ready"; width: number; height: number; color: boolean }
  | { name: "failure"; message: string };

function paintFailureMessage(error: unknown): string {
  if (!(error instanceof SpatialDataPreviewError)) {
    return "미리보기를 표시하지 못했습니다. 구역 자료 준비에서 준비된 파일 다운로드로 받으세요.";
  }
  switch (error.kind) {
    case "CANCELLED":
      return "불러오기를 취소했습니다.";
    case "TIMEOUT":
      return "준비된 파일을 받을 수 있는 시간을 넘겨 중단했습니다. 구역 자료 준비에서 다운로드로 받으세요.";
    case "TOO_LARGE":
      return "준비된 출력이 브라우저 표시 한계를 넘어 미리보기를 표시하지 않습니다. 구역 자료 준비에서 다운로드로 받으세요.";
    case "SIZE_MISMATCH":
    case "HASH_MISMATCH":
      return "받은 바이트가 Core 준비 기록(출력 크기·파일 확인값)과 달라 화면에 표시하지 않습니다. 구역 자료 준비에서 다운로드로 다시 받으세요.";
    case "BAD_RECEIPT":
    case "UNSUPPORTED":
      return error.message;
    case "HTTP": {
      if (error.status === 401) return "세션이 만료되었습니다. 다시 로그인한 뒤 시도하세요.";
      // 다른 주체의 창·회수·만료는 존재를 드러내지 않고 같은 문구로 닫는다.
      if (
        error.status === 404 ||
        error.status === 403 ||
        error.code === "PERMISSION_DENIED" ||
        error.code === "NOT_FOUND" ||
        error.code === "GRANT_REQUIRED" ||
        error.code === "ACCESS_REVOKED" ||
        error.code === "ACCESS_EXPIRED" ||
        error.code === "RETENTION_EXPIRED"
      ) {
        return FOREIGN_WINDOW_COPY;
      }
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

function parseNonNegativeInt(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const value = Number(text.trim());
  return Number.isSafeInteger(value) ? value : null;
}

function fileHrefFor(siteId: string, workAreaId: string, jobId: string): string {
  return `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-data-requests/${encodeURIComponent(jobId)}/file`;
}

/** 네이티브 좌표를 backing 픽셀로 — 반올림 없이 선형 대응만 한다(표시용). */
function nativeToBacking(
  x: number,
  y: number,
  actualBounds: readonly number[],
  width: number,
  height: number,
): [number, number] {
  const [minx, miny, maxx, maxy] = actualBounds as [number, number, number, number];
  const px = ((x - minx) / (maxx - minx)) * width;
  const py = ((maxy - y) / (maxy - miny)) * height;
  return [px, py];
}

/** 한 층의 보기 — 층이 바뀌면 호출자가 `key`로 다시 만든다. 층 전환에 effect로
 * 상태를 되돌리지 않는다.
 */
function WindowedLayerView({
  siteId,
  workAreaId,
  layer,
  jobs,
  canRequest,
  requestsHref,
  workAreaRing,
  workAreaCrs,
  idPrefix,
  supportingDetails,
  hidePrepareActions = false,
  presentation = "default",
  detailsTargetId = null,
}: {
  siteId: string;
  workAreaId: string;
  layer: WindowedViewerLayer;
  jobs: PreparedWindowJob[];
  canRequest: boolean;
  requestsHref: string;
  workAreaRing: Array<[number, number]> | null;
  workAreaCrs: string;
  idPrefix: string;
  supportingDetails?: ReactNode;
  /** true면 새 창 준비 요청 UI를 숨기고 읽기 길만 둔다. 기본 false. */
  hidePrepareActions?: boolean;
  /** "canvas"면 큰 픽셀을 먼저 두고 긴 안내는 펼침에 둔다. 기본 "default". */
  presentation?: "default" | "canvas";
  /** 작업환경 정보 서랍 안 숨김 자리 식별자 — 주면 접힌 상세를 서랍으로 포털한다. */
  detailsTargetId?: string | null;
}) {
  const router = useRouter();
  const grid = layer.inspectedRaster;
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [phase, setPhase] = useState<PaintPhase>({ name: "idle" });
  const [image, setImage] = useState<DecodedReceiptPreview | null>(null);
  // ── 낱창 직접 조작 — 같은 훅 하나로 같은 규칙을 탄다 ──
  // 진입·낱창 보기·준비 요청은 읽기만 하며, 어떤 경우에도 새 준비를 만들지 않는다.
  const viewport = useDirectViewport();
  const view = viewport.view;
  const [requestMessage, setRequestMessage] = useState<string | null>(null);
  const [requestBusy, setRequestBusy] = useState(false);
  const [accepted, setAccepted] = useState<{ jobId: string; state: string } | null>(null);
  const [lane, setLane] = useState<DisplaySchedulerSnapshot | null>(null);
  /**
   * 창 준비 발행 스케줄러 — 임시 어댑터의 요청 경로를 계약 규칙으로
   * 바꾼 자리다. 최대 2개 동시 발행·안정 키 중복 제거·재시도 가능
   * 429의 bounded back-off를 맡고, 권리·격자·영수증 판단은 Core가
   * 그대로 소유한다. 같은 창의 반복 요청은 새 PREPARE 없이 합류한다.
   */
  const schedulerRef = useRef<DisplayPrepareScheduler | null>(null);
  if (schedulerRef.current === null) {
    schedulerRef.current = new DisplayPrepareScheduler(
      async (target: ScheduledDisplayWindow, signal: AbortSignal) => {
        const response = await fetch(
          `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-data-requests`,
          {
            method: "POST",
            cache: "no-store",
            headers: {
              "Content-Type": "application/json",
              "Idempotency-Key": stableIdempotencyKey(target.assetRef, target.pixelWindow, target.purpose),
              Accept: "application/json",
            },
            body: JSON.stringify({
              assetRef: target.assetRef,
              requestedBounds: target.requestedBounds,
              observedCrsDigest: target.observedCrsDigest,
              resolutionMode: "NATIVE",
              purpose: target.purpose,
            }),
            signal,
          },
        );
        const body: unknown = await response.json().catch(() => null);
        if (!response.ok) {
          const reason =
            body !== null && typeof body === "object" && "reason" in body && typeof (body as { reason: unknown }).reason === "string"
              ? (body as { reason: string }).reason
              : body !== null && typeof body === "object" && "code" in body && typeof (body as { code: unknown }).code === "string"
                ? (body as { code: string }).code
                : null;
          if (response.status === 429) {
            throw new DisplayPrepareIssueError(
              "동시 요청이 많아 순차 처리 중입니다. 자동으로 다시 시도합니다.",
              { status: response.status, code: reason, retryable: true },
            );
          }
          throw new DisplayPrepareIssueError(
            (reason && SPATIAL_DATA_REQUEST_REASON_COPY[reason]) ??
              (response.status === 404
                ? "이 환경에서는 자료 준비 기능이 연결되어 있지 않거나 대상을 찾을 수 없습니다. 관리자에게 확인하세요."
                : null) ??
              "받기 요청을 만들지 못했습니다. 현재 상태를 다시 확인하세요.",
            { status: response.status, code: reason, retryable: false },
          );
        }
        const record = body as Record<string, unknown>;
        if (typeof record.jobId !== "string" || typeof record.executionState !== "string") {
          throw new DisplayPrepareIssueError("Core 응답의 요청 식별자 또는 상태를 확인할 수 없습니다. 구역 자료 준비에서 확인하세요.");
        }
        return { jobId: record.jobId, executionState: record.executionState };
      },
      { listener: (snapshot) => setLane(snapshot) },
    );
  }
  const [draft, setDraft] = useState(() => {
    const seed = grid ? initialPixelWindowDims(grid.width, grid.height) : null;
    return seed
      ? { width: String(seed.width), height: String(seed.height), col: String(seed.col), row: String(seed.row) }
      : { width: "", height: "", col: "", row: "" };
  });
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const offscreenRef = useRef<HTMLCanvasElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const readable = readableWindowJobs(jobs, layer.assetRef);
  const existingCrop = preparedWindowFallback(grid, jobs, layer.assetRef);
  const pending = jobs.filter(
    (job) =>
      job.assetRef === layer.assetRef &&
      (job.executionState === "QUEUED" || job.executionState === "RUNNING"),
  );
  const selectedJob = readable.find((job) => job.jobId === selectedJobId) ?? null;
  const receipt = selectedJob?.receipt ?? null;

  useEffect(() => () => {
    abortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (phase.name !== "ready" || image === null) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      let off = offscreenRef.current;
      if (!off) {
        off = document.createElement("canvas");
        offscreenRef.current = off;
      }
      off.width = image.width;
      off.height = image.height;
      const offCtx = off.getContext("2d");
      if (!offCtx) throw new Error("no-2d-context");
      offCtx.putImageData(new ImageData(image.pixels, image.width, image.height), 0, 0);
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("no-2d-context");
      context.imageSmoothingEnabled = false;
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(off, 0, 0);
    } catch {
      setPhase({ name: "failure", message: "이 브라우저에서 미리보기를 그릴 수 없습니다. 다운로드는 그대로 받을 수 있습니다." });
    }
  }, [phase, image]);

  const selection: PixelWindowSelection = {
    width: parseNonNegativeInt(draft.width) ?? -1,
    height: parseNonNegativeInt(draft.height) ?? -1,
    col: parseNonNegativeInt(draft.col) ?? -1,
    row: parseNonNegativeInt(draft.row) ?? -1,
  };
  const resolution = resolveBoundedPixelWindow(grid, selection);

  const load = async (job: PreparedWindowJob) => {
    if (phase.name === "loading") return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase({ name: "loading" });
    setImage(null);
    viewport.reset();
    try {
      const target = job.receipt;
      if (!target || target.jobId !== job.jobId) {
        throw new SpatialDataPreviewError("BAD_RECEIPT", "준비 기록의 요청 식별자가 현재 요청과 달라 표시하지 않습니다.");
      }
      const bytes = await fetchVerifiedReceiptBytes(
        fileHrefFor(siteId, workAreaId, job.jobId),
        { outputSha256: target.outputSha256, outputSizeBytes: target.outputSizeBytes },
        controller.signal,
      );
      const decoded = await decodeReceiptPreview(bytes, { width: target.width, height: target.height });
      if (controller.signal.aborted) return;
      setImage(decoded);
      setSelectedJobId(job.jobId);
      setPhase({ name: "ready", width: decoded.width, height: decoded.height, color: decoded.color });
    } catch (error) {
      if (controller.signal.aborted) {
        setPhase({ name: "idle" });
        return;
      }
      setPhase({ name: "failure", message: paintFailureMessage(error) });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  };

  const moveDraft = (dCol: number, dRow: number) => {
    if (!grid || !resolution.ok) return;
    const current: PixelWindowSelection = {
      width: resolution.value.width,
      height: resolution.value.height,
      col: resolution.value.window[0],
      row: resolution.value.window[1],
    };
    const next = adjacentWindowSelection(grid, current, dCol, dRow);
    if (!next) {
      setRequestMessage("격자 끝이라 더 이상 옮길 창이 없습니다. 크기를 줄이거나 원점을 직접 입력하세요.");
      return;
    }
    setDraft({ ...draft, col: String(next.col), row: String(next.row) });
    setRequestMessage(
      `이웃 창으로 초안을 옮겼습니다 · 원점 ${next.col}, ${next.row} · 너비 ${next.width} × 높이 ${next.height}. 요청을 만들려면 아래에서 받기 요청을 누르세요.`,
    );
  };

  const createRequest = async () => {
    if (!resolution.ok || !layer.observedCrsDigest) return;
    const scheduler = schedulerRef.current;
    if (!scheduler) return;
    // 안정 키는 (assetRef, pixelWindow, purpose)의 순수 함수다 — 같은 창의
    // 반복 요청은 같은 키가 되어 새 PREPARE 없이 합류·재입장한다.
    const [col, row, width, height] = resolution.value.window;
    const pixelWindow: [number, number, number, number] = [col, col + width, row, row + height];
    const target: ScheduledDisplayWindow = {
      key: stablePrepareKey(layer.assetRef, pixelWindow, "GENERAL_DATA_USE"),
      assetRef: layer.assetRef,
      pixelWindow,
      requestedBounds: resolution.value.requestedBounds,
      observedCrsDigest: layer.observedCrsDigest,
      purpose: "GENERAL_DATA_USE",
    };
    setRequestBusy(true);
    setRequestMessage(null);
    try {
      setLane(scheduler.ensure([target]));
      const already = scheduler.completedResult(target.key);
      if (already && !scheduler.join(target.key)) {
        setAccepted({ jobId: already.jobId, state: already.executionState });
        setRequestMessage(
          `같은 창의 준비 요청이 이미 있습니다 · 상태 ${already.executionState}. 처리가 끝나면 아래 목록 또는 구역 자료 준비에서 받을 수 있습니다.`,
        );
        return;
      }
      const joined = scheduler.join(target.key);
      if (!joined) {
        setRequestMessage("창 준비 요청 상태를 확인할 수 없습니다. 구역 자료 준비에서 확인하세요.");
        return;
      }
      const result = await joined;
      setAccepted({ jobId: result.jobId, state: result.executionState });
      setRequestMessage(
        `받기 요청을 만들었습니다 · 상태 ${result.executionState}. 처리가 끝나면 아래 목록 또는 구역 자료 준비에서 받을 수 있습니다.`,
      );
    } catch (error) {
      if (error instanceof DisplayPrepareIssueError) {
        setRequestMessage(error.message);
        return;
      }
      setRequestMessage("Core 응답을 받지 못했습니다. 구역 자료 준비에서 현재 상태를 다시 확인하세요.");
    } finally {
      setRequestBusy(false);
      setLane(scheduler.snapshot());
    }
  };

  const ringPoints =
    workAreaRing && receipt
      ? workAreaRing
          .map(([x, y]) => nativeToBacking(x, y, receipt.actualBounds, receipt.width, receipt.height).join(","))
          .join(" ")
      : null;
  const samePlane =
    workAreaRing !== null &&
    layer.observedCrsIdentifier !== null &&
    workAreaCrs === layer.observedCrsIdentifier;


  // 낱창 접힘 본문 — 무대 자리 펼침 또는 정보 서랍 포털이 같은 노드를 둔다.
  const layerDetailsBody = (
        <div className="mt-2 flex flex-col gap-2">
          {supportingDetails}
          <h4 className="text-[13px] font-semibold">낱창 보기 · 새 창 준비</h4>
      <h4 className="text-[13px] font-bold">{WINDOWED_VIEWER_READ_LABEL}</h4>
      {readable.length === 0 && pending.length === 0 && (
        <p className="text-[12.5px] leading-5 text-ink-2">
          이 층에서 현재 계정이 볼 수 있는 준비된 창이 없습니다. 아래에서 새 창 준비를 요청하거나, 구역 자료 준비에서 이력을 확인하세요.
        </p>
      )}
      {pending.length > 0 && (
        <ul className="flex flex-col gap-1">
          {pending.map((job) => (
            <li key={job.jobId} className="text-[12px] leading-5 text-ink-2">
              준비 중 · 상태 {job.executionState} — 끝난 뒤에 볼 수 있습니다.
            </li>
          ))}
        </ul>
      )}
      {readable.length > 0 && (
        <ul className="flex flex-col gap-1">
          {readable.map((job) => (
            <li key={job.jobId} className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <button
                type="button"
                onClick={() => void load(job)}
                aria-pressed={job.jobId === selectedJobId}
                disabled={phase.name === "loading"}
                className={`btn min-h-11 ${job.jobId === selectedJobId ? "btn-primary" : ""}`}
              >
                {job.jobId === selectedJobId && phase.name === "ready" ? "보고 있는 창" : "이 창 보기"}
              </button>
              <span className="break-words text-ink-2">{windowOptionLabel(job)}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="flex flex-wrap gap-2">
        <button type="button" className="btn min-h-11" onClick={() => router.refresh()}>
          준비 상태 다시 확인
        </button>
        <Link href={requestsHref} className="btn min-h-11">
          구역 자료 준비에서 확인
        </Link>
      </p>
      <p className="text-[11.5px] leading-5 text-ink-muted">
        같은 계정이 준비한 창만 볼 수 있습니다. 목록 새로고침·낱창 보기는 읽기만 하며 새 요청을 만들지 않습니다.
      </p>

      {phase.name === "loading" && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[12px] text-ink-2" role="status">자료 읽는 중…</p>
          <button type="button" className="btn min-h-11" onClick={() => abortRef.current?.abort()}>
            불러오기 취소
          </button>
        </div>
      )}
      {phase.name === "failure" && (
        <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2" role="alert">
          {phase.message}
        </p>
      )}
      {phase.name === "ready" && receipt && (
        <div className="flex flex-col gap-2">
          <div
            {...viewport.frameProps}
            aria-label={`준비된 창 ${receipt.width} × ${receipt.height} 픽셀. 직접 끌어서 보고, 휠·두 손가락·두 번 두드리기로 확대합니다. 그림을 선택하면 방향키·Home 키도 쓸 수 있습니다.`}
            className="relative w-full cursor-grab overflow-hidden rounded border border-line bg-sunk/30 focus-visible:outline-2 focus-visible:outline-offset-2 active:cursor-grabbing"
            style={{ ...viewport.frameProps.style, aspectRatio: `${receipt.width} / ${receipt.height}` }}
          >
            <div
              {...viewport.contentProps}
              className="relative h-full w-full"
            >
              <canvas ref={canvasRef} className="block h-auto w-full" style={{ imageRendering: "pixelated" }} role="img"
                aria-label={`준비된 창 ${receipt.width} × ${receipt.height} 픽셀 · ${formatNativeWindowExtent(receipt.actualBounds, receipt.observedCrsIdentifier)}`} />
              {ringPoints && samePlane && (
                <svg viewBox={`0 0 ${receipt.width} ${receipt.height}`} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
                  <polygon points={ringPoints} fill="none" stroke="currentColor" strokeWidth={2 / view.zoom} strokeDasharray={`${6 / view.zoom} ${4 / view.zoom}`} />
                </svg>
              )}
            </div>
            <ViewportResetButton onReset={viewport.reset} />
          </div>
          {viewport.note && (
            <p className="text-[12px] leading-5 text-ink-2" role="status">{viewport.note}</p>
          )}
          <ViewportGestureHint />
          {isDisplayViewMoved(view) && (
            <p className="text-[12px] leading-5 text-ink-2" role="status">
              표시 확대 {displayZoomPercent(view)}%
              {view.cx !== 0.5 || view.cy !== 0.5 ? " · 이동한 화면" : ""} · 원본 버퍼는 그대로 둡니다.
            </p>
          )}
          <p className="text-[12px] leading-5 text-ink-2">
            {`실제 파일 · 준비된 창 · ${receipt.width} × ${receipt.height} 픽셀 · ${formatNativeWindowExtent(receipt.actualBounds, receipt.observedCrsIdentifier)}`}
          </p>
          <p className="text-[11.5px] leading-5 text-ink-muted">
            파일 자체의 해상도·범위를 그대로 둡니다. 지도 재투영이 아닙니다.
            {ringPoints && samePlane
              ? " 점선은 같은 좌표 평면의 작업구역 경계입니다."
              : " 작업구역 경계를 겹쳐 표시하지 않았습니다(같은 평면이 아니거나 범위를 확인하지 못했습니다)."}
          </p>
          {!phase.color && (
            <>
              <p className="text-[12px] leading-5 text-ink-2">{DSM_RELATIVE_SHADING_NOTE}</p>
              <div className="flex items-center gap-2 text-[11.5px] text-ink-muted" aria-label="상대 음영 범례">
                <span>어두움</span>
                <span aria-hidden="true" className="inline-block h-2 w-24 rounded" style={{ background: "linear-gradient(to right, #000, #fff)" }} />
                <span>밝음</span>
              </div>
              <p className="text-[11.5px] leading-5 text-ink-muted">{DSM_RELATIVE_LEGEND_LABEL}</p>
              <p className="text-[11.5px] leading-5 text-ink-muted">{DSM_WINDOW_STRETCH_NOTE}</p>
            </>
          )}
          {phase.color && (
            <p className="text-[12px] leading-5 text-ink-2">
              실제 픽셀 색상을 그대로 표시합니다. WGS84 변환·지도 타일·보정을 적용하지 않았습니다.
            </p>
          )}
          <p className="text-[11.5px] leading-5 text-ink-muted">
            정확도 평가·측량·정산 근거가 아닙니다. 체적·면적 등 정량 계산을 하지 않습니다. 확대·이동은 화면 표시용이며 측정값이 아닙니다.
          </p>
        </div>
      )}

      {hidePrepareActions ? (
        <p className="text-[12px] leading-5 text-ink-2">
          새 창 준비 요청은 <Link href={requestsHref} className="tap-target underline">구역 자료 준비</Link>에서
          합니다. 이 화면에서는 준비 요청을 만들지 않습니다.
        </p>
      ) : (
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-sunk/50 px-3 py-2">
        <h4 className="text-[13px] font-bold">{WINDOWED_VIEWER_REQUEST_LABEL}</h4>
        <p className="text-[12px] leading-5 text-ink-2">
          보고 싶은 이웃 창을 고르면 같은 자료의 유한 픽셀 창으로 준비를 요청합니다. Core가 현재 명시된 사용 권리와 범위를 확인한 뒤에만 작업을 만듭니다.
        </p>
        {!grid && (
          <p className="text-[12px] leading-5 text-ink-2" role="status">{PIXEL_WINDOW_BLOCKER_COPY.NO_INSPECTION}</p>
        )}
        {grid && (
          <>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex min-w-24 flex-col gap-1 text-[12px] font-semibold" htmlFor={`${idPrefix}-window-width`}>
                너비 (1–{Math.min(grid.width, MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM)})
                <input id={`${idPrefix}-window-width`} className="input min-h-11" inputMode="numeric" value={draft.width}
                  onChange={(event) => setDraft({ ...draft, width: event.target.value })} disabled={requestBusy || accepted !== null} />
              </label>
              <label className="flex min-w-24 flex-col gap-1 text-[12px] font-semibold" htmlFor={`${idPrefix}-window-height`}>
                높이 (1–{Math.min(grid.height, MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM)})
                <input id={`${idPrefix}-window-height`} className="input min-h-11" inputMode="numeric" value={draft.height}
                  onChange={(event) => setDraft({ ...draft, height: event.target.value })} disabled={requestBusy || accepted !== null} />
              </label>
              <label className="flex min-w-24 flex-col gap-1 text-[12px] font-semibold" htmlFor={`${idPrefix}-window-col`}>
                원점 열 (0부터)
                <input id={`${idPrefix}-window-col`} className="input min-h-11" inputMode="numeric" value={draft.col}
                  onChange={(event) => setDraft({ ...draft, col: event.target.value })} disabled={requestBusy || accepted !== null} />
              </label>
              <label className="flex min-w-24 flex-col gap-1 text-[12px] font-semibold" htmlFor={`${idPrefix}-window-row`}>
                원점 행 (0부터)
                <input id={`${idPrefix}-window-row`} className="input min-h-11" inputMode="numeric" value={draft.row}
                  onChange={(event) => setDraft({ ...draft, row: event.target.value })} disabled={requestBusy || accepted !== null} />
              </label>
            </div>
            <div className="flex flex-wrap gap-2" role="group" aria-label="이웃 창으로 초안 이동">
              <button type="button" className="btn min-h-11" disabled={!resolution.ok} onClick={() => moveDraft(-1, 0)}>← 이웃 창</button>
              <button type="button" className="btn min-h-11" disabled={!resolution.ok} onClick={() => moveDraft(1, 0)}>이웃 창 →</button>
              <button type="button" className="btn min-h-11" disabled={!resolution.ok} onClick={() => moveDraft(0, -1)}>↑ 이웃 창</button>
              <button type="button" className="btn min-h-11" disabled={!resolution.ok} onClick={() => moveDraft(0, 1)}>↓ 이웃 창</button>
            </div>
            {resolution.ok ? (
              <p className="text-[12px] leading-5 text-ink-2">
                픽셀 창 · 원점 {resolution.value.window[0]}, {resolution.value.window[1]} · 너비 {resolution.value.width} × 높이 {resolution.value.height} 네이티브 픽셀
              </p>
            ) : (
              <p className="text-[12px] leading-5 text-high-ink" role="status">{PIXEL_WINDOW_BLOCKER_COPY[resolution.reason]}</p>
            )}
          </>
        )}
        {!canRequest ? (
          <div className="mt-1">
            <ActionUnavailable
              label={WINDOWED_VIEWER_REQUEST_LABEL}
              description="이 구역의 창 준비 요청은 권한 있는 담당자가 만들 수 있습니다. 필요한 창과 용도를 담당자에게 알려 주세요."
            />
          </div>
        ) : (
          <ResponsiveActionBoundary
            action="SPATIAL_DATA_REQUEST"
            reason="창 준비 요청은 노트북 이상의 화면에서 진행하세요."
            inlineNotice={false}
          >
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-primary min-h-11"
                disabled={!resolution.ok || !layer.observedCrsDigest || requestBusy || accepted !== null}
                onClick={() => void createRequest()}
              >
                {requestBusy ? "요청 만드는 중…" : accepted ? "요청 만듦" : "받기 요청 만들기"}
              </button>
            </div>
            {lane?.laneCopy && (
              <p role="status" className="mt-1 text-[12px] leading-5 text-ink-2">{lane.laneCopy}</p>
            )}
            {lane?.retryCopy && (
              <p role="status" className="mt-1 text-[12px] leading-5 text-ink-2">{lane.retryCopy}</p>
            )}
          </ResponsiveActionBoundary>
        )}
        {requestMessage && <p role="status" aria-live="polite" className="mt-1 rounded-md border border-line bg-surface px-3 py-2 text-[12px] leading-5 text-ink-2">{requestMessage}</p>}
        {accepted && (
          <p className="text-[12px] leading-5 text-ink-2">
            처리가 끝나면 <Link href={requestsHref} className="tap-target underline">구역 자료 준비</Link> 또는 위의 준비 상태 다시 확인에서 받을 수 있습니다. 준비 완료는 정확도나 분석 사용 가능 여부를 보증하지 않습니다.
          </p>
        )}
      </div>
      )}
        </div>
  );
  return (

    <div className="flex flex-col gap-2">
      {/* 실제 화면이 먼저다. 이어 보기는 진입 시 이미 준비된 창만 읽는다(읽기 전용).
          새 준비 요청은 아래의 명시적 버튼에서만 나간다. */}
      {existingCrop?.receipt ? (
        <div className="flex flex-col gap-2">
          <p className="text-[12px] leading-5 text-ink-2">{presentation === "canvas" ? "일부 범위 · 전체 관측이 아님" : "준비된 일부 범위 · 전체 관측이 아닌 현재 계정의 출력 범위를 표시합니다."}</p>
          <SpatialDataReceiptPreview
            key={existingCrop.jobId}
            siteId={siteId}
            workAreaId={workAreaId}
            jobId={existingCrop.jobId}
            receipt={existingCrop.receipt}
            fileHref={fileHrefFor(siteId, workAreaId, existingCrop.jobId)}
            autoLoad
            compact
            gestureControls
            presentation={presentation}
          />
          {layer.isDsm && <p className="text-[11.5px] leading-5 text-ink-muted">{DSM_WINDOW_STRETCH_NOTE}</p>}
        </div>
      ) : grid && (
        <SiteMosaicViewport
          siteId={siteId}
          workAreaId={workAreaId}
          assetRef={layer.assetRef}
          grid={grid}
          observedCrsDigest={layer.observedCrsDigest}
          observedCrsIdentifier={layer.observedCrsIdentifier}
          isDsm={layer.isDsm}
          jobs={jobs}
          canRequest={canRequest}
          requestsHref={requestsHref}
          workAreaRing={workAreaRing}
          workAreaCrs={workAreaCrs}
          hidePrepareActions={hidePrepareActions}
          presentation={presentation}
          detailsTargetId={detailsTargetId}
        />
      )}

      {/* 낱창 도구·수동 설정은 펼침 하나에 둔다. 보통 흐름은 이어 보기+다시 확인이면 된다. */}
      {/* 낱창 도구·수동 설정은 펼침 하나에 둔다. 보통 흐름은 이어 보기+다시 확인이면 된다. */}
      {detailsTargetId ? (
        <DetailsPortal targetId={detailsTargetId}>
          <details className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer font-semibold">보기·준비 상세</summary>
            {layerDetailsBody}
          </details>
        </DetailsPortal>
      ) : (
        <details className="rounded-lg border border-line bg-sunk/50 px-3 py-2 text-[12px] text-ink-2">
          <summary className="tap-target cursor-pointer font-semibold">{presentation === "canvas" ? "상세·준비" : "보기 상세"}</summary>
          {layerDetailsBody}
        </details>
      )}
    </div>
  );
}

export function SiteWindowedPixelViewer({
  siteId,
  workAreaId,
  layers,
  jobs,
  jobsState,
  canRead,
  canRequest,
  requestsHref,
  workAreaRing,
  workAreaCrs,
  observationHeading,
  idPrefix,
  slimHeader = false,
  selectedAssetRef = null,
  layerSelectionHref,
  layerSelectHref,
  layerSelectParam = "assetRef",
  hideLayerControls = false,
  layerControlsTargetId,
  hidePrepareActions = false,
  presentation = "default",
  detailsTargetId = null,
}: WindowedPixelViewerProps) {
  const canvasMode = presentation === "canvas";
  const router = useRouter();
  const activeLayer = layers.find((item) => item.assetRef === selectedAssetRef) ?? layers[0] ?? null;
  const [layerOverride, setLayerOverride] = useState<string | null>(null);
  const layer = layerSelectionHref ? activeLayer : layers.find((item) => item.assetRef === layerOverride) ?? activeLayer;
  const grid = layer?.inspectedRaster ?? null;
  const [controlsTarget, setControlsTarget] = useState<HTMLElement | null>(null);
  // Resolve the sibling slot after DOM commit (also works on client-side mode navigation).
  const attachControlsSlot = useCallback((node: HTMLSpanElement | null) => {
    setControlsTarget(node && layerControlsTargetId ? document.getElementById(layerControlsTargetId) : null);
  }, [layerControlsTargetId]);
  const layerControls = layers.length > 1 ? (
    <div data-workbench-pane-controls={canvasMode || undefined} className={`flex flex-wrap gap-1 ${canvasMode ? "text-[12px]" : "lg:flex-col"}`} role="group" aria-label="자료 층 전환">
      {layers.map((item) => {
        const selected = item.assetRef === layer?.assetRef;
        // URL 전환이 있으면 링크로 둔다 — Back·reload·분석 복귀가 같은 층을
        // 가리킨다. 없으면 기존 로컬 전환 그대로 둔다(동기화 없음).
        if (layerSelectHref && !layerSelectionHref) {
          const target = new URL(layerSelectHref, "https://console.invalid");
          target.searchParams.set(layerSelectParam, item.assetRef);
          const href = `${target.pathname}?${target.searchParams.toString()}${target.hash}`;
          return <Link key={item.assetRef} href={href}
            aria-current={selected ? "true" : undefined}
            className={`tap-target inline-flex items-center rounded-md px-3 py-1.5 text-[12.5px] break-keep ${selected ? "bg-sunk font-bold" : "text-ink-2"}`}>
            {item.kindLabel}
          </Link>;
        }
        return <button key={item.assetRef} type="button"
          aria-pressed={selected}
          onClick={() => {
            if (layerSelectionHref) {
              if (selected) return;
              router.push(`${layerSelectionHref}${layerSelectionHref.includes("?") ? "&" : "?"}assetRef=${encodeURIComponent(item.assetRef)}`);
            } else setLayerOverride(item.assetRef);
          }}
          className={`tap-target inline-flex items-center rounded-md px-3 py-1.5 text-[12.5px] break-keep ${selected ? "bg-sunk font-bold" : "text-ink-2"}`}>
          {item.kindLabel}
        </button>;
      })}
    </div>
  ) : null;

  // 무대용 간결 상태 — 사유 한 줄과 하나의 1차 회복만 둔다. 진입·읽기 흐름은
  // 그대로이며, 명시적 준비 요청(쓰기)은 아래 접힌 상세에만 둔다.
  const canvasMedia = !layer ? (
    <WorkbenchMediaState
      headline="이 관측에서 화면에 둘 정사영상·DSM 층을 확인하지 못했습니다."
      detail="등록 자료에서 파일 검사 상태를 확인하세요."
    />
  ) : jobsState === "denied" ? (
    <WorkbenchMediaState
      headline="준비 기록을 조회할 권한이 없습니다."
      hint="담당자에게 조회 권한을 요청하세요. 권한이 없어 빈 목록으로 단정하지 않습니다."
    />
  ) : jobsState === "unavailable" ? (
    <WorkbenchMediaState
      headline="준비 기록을 불러오지 못했습니다."
      detail="빈 목록으로 단정하지 않습니다."
      action={<WorkbenchRefreshButton />}
    />
  ) : jobsState === "ready" && !canRead ? (
    <WorkbenchMediaState
      headline="이미 준비된 창을 볼 권한이 없습니다."
      action={
        <ActionUnavailable
          label={WINDOWED_VIEWER_READ_LABEL}
          description="이미 준비된 창을 볼 권한이 없습니다. 필요한 창과 용도를 담당자에게 알려 주세요."
        />
      }
    />
  ) : null;

  const supportingDetails = (
    <details id={`${idPrefix}-display-conditions`} className="scroll-mt-5 text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold">표시 조건·근거</summary>
        <p className="mt-1">{WINDOWED_VIEWER_ADAPTER_LABEL} — {WINDOWED_VIEWER_ADAPTER_NOTE}</p>
        <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">{NO_COMPOSITE_FLAG_COPY}</p>
        <p className="mt-1"><span className="font-semibold">감사 추적</span> · {AUDIT_STATE_NOTE}</p>
        <p className="mt-1"><span className="font-semibold">데이터 검증 적합성</span> · {VALIDATION_STATE_NOTE}</p>
        <p className="mt-1"><span className="font-semibold">공간 표시 가능 여부</span> · {VIEWABILITY_STATE_NOTE}</p>
        {layer && (
          <dl className="mt-1 grid gap-1 border-l-2 border-line pl-3">
            <div><dt className="font-semibold text-ink-muted">파일 검사</dt><dd>{inspectionOutcomeLabel(layer.inspectionOutcome)}</dd></div>
            <div><dt className="font-semibold text-ink-muted">관측 위치 기준</dt><dd className="break-all font-mono">{layer.observedCrsIdentifier ?? "확인 불가"}</dd></div>
            <div><dt className="font-semibold text-ink-muted">관측 수직 기준</dt><dd className="break-all">{layer.verticalReference ?? "확인 불가"}</dd></div>
            <div><dt className="font-semibold text-ink-muted">검사 격자</dt><dd>{grid ? `${grid.width} × ${grid.height} 네이티브 픽셀` : "확인 불가"}</dd></div>
            <div><dt className="font-semibold text-ink-muted">등록 파일명</dt><dd className="break-all">{layer.fileName}</dd></div>
            <div><dt className="font-semibold text-ink-muted">등록 버전</dt><dd>revision {layer.revision} · 제출 묶음 {layer.submissionRef}</dd></div>
          </dl>
        )}
        <p className="mt-1 text-[11.5px] text-ink-muted">볼 수 있다는 뜻이 분석에 쓸 수 있다는 뜻이 아닙니다. 적합성은 검사·평가·검토 기록이 말합니다.</p>
      </details>
  );

  return (
    <section
      aria-label={`${WINDOWED_VIEWER_ADAPTER_LABEL}${observationHeading ? ` · ${observationHeading}` : ""}`}
      className={canvasMode
        ? "flex min-w-0 flex-col gap-1.5"
        : `flex min-w-0 flex-col gap-3 ${hideLayerControls ? "" : "rounded-xl border border-line bg-surface px-4 py-3"}`}
    >
      {!slimHeader && (
        <header>
          <h3 className="break-words text-[14px] font-bold">{observationHeading ?? WINDOWED_VIEWER_ADAPTER_LABEL}</h3>
          <p className="mt-1 text-[12px] leading-5 text-ink-2">실제 파일의 준비된 창을 그대로 둡니다. 지도 재투영·보정을 하지 않습니다.</p>
        </header>
      )}

      {layerControlsTargetId && <span hidden ref={attachControlsSlot} />}
      {controlsTarget ? createPortal(layerControls, controlsTarget) : !hideLayerControls && !layerControlsTargetId ? layerControls : null}

      {canvasMode && canvasMedia}

      {!canvasMode && !layer && (
        <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">
          이 관측에서 화면에 둘 정사영상·DSM 층을 확인하지 못했습니다. 등록 자료에서 파일 검사 상태를 확인하세요.
        </p>
      )}

      {!canvasMode && layer && jobsState === "denied" && (
        <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">
          준비 기록을 조회할 권한이 없습니다. 담당자에게 조회 권한을 요청하세요. 권한이 없어 빈 목록으로 단정하지 않습니다.
        </p>
      )}
      {!canvasMode && layer && jobsState === "unavailable" && (
        <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">
          준비 기록을 불러오지 못했습니다. 잠시 후 다시 확인하세요. 빈 목록으로 단정하지 않습니다.
        </p>
      )}

      {!canvasMode && layer && jobsState === "ready" && !canRead && (
        <div className="rounded-lg border border-line bg-sunk px-3 py-2">
          <ActionUnavailable
            label={WINDOWED_VIEWER_READ_LABEL}
            description="이미 준비된 창을 볼 권한이 없습니다. 필요한 창과 용도를 담당자에게 알려 주세요."
          />
        </div>
      )}

      {!(canvasMode && canvasMedia) && layer && jobsState === "ready" && canRead && (
        <WindowedLayerView
          key={layer.assetRef}
          siteId={siteId}
          workAreaId={workAreaId}
          layer={layer}
          jobs={jobs}
          canRequest={canRequest}
          requestsHref={requestsHref}
          workAreaRing={workAreaRing}
          workAreaCrs={workAreaCrs}
          idPrefix={`${idPrefix}-${layer.assetRef === layers[0]?.assetRef ? "first" : "second"}`}
          supportingDetails={supportingDetails}
          hidePrepareActions={hidePrepareActions}
          presentation={presentation}
          detailsTargetId={detailsTargetId}
        />
      )}

      {!(layer && jobsState === "ready" && canRead) && (detailsTargetId ? (
        <DetailsPortal targetId={detailsTargetId}>
          <details className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer font-semibold">보기·준비 상세</summary>
            <div className="mt-2">{supportingDetails}</div>
          </details>
        </DetailsPortal>
      ) : canvasMode ? (
        <details className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
          <summary className="tap-target cursor-pointer font-semibold">상세·준비</summary>
          <div className="mt-2">{supportingDetails}</div>
        </details>
      ) : supportingDetails)}
    </section>
  );
}

/**
 * 두 시점 나란히 보기 — 각 칸은 독립된 임시 시각화 어댑터다.
 *
 * 같은 화면 평면에 있을 때만 같은 작업구역 링과 나란히 두며, 위치 맞춤
 * (정합)이 확인된 것이 아니므로 동기화된 공간 비교로 말하지 않는다.
 * 평면이 다르면 각자 보기만 두고 이유를 밝힌다.
 */
export function SiteWindowedPixelCompare({
  siteId,
  workAreaId,
  baselineHeading,
  currentHeading,
  baselineLayers,
  currentLayers,
  baselineCrs,
  currentCrs,
  jobs,
  jobsState,
  canRead,
  canRequest,
  requestsHref,
  workAreaRing,
  workAreaCrs,
  hideLayerControls = false,
  baselineAssetRef,
  currentAssetRef,
  layerControlsInRail = false,
  baselineRoleLabel = "기준 자료",
  currentRoleLabel = "비교 자료",
  baselineLayerHref,
  currentLayerHref,
  baselineLayerParam = "assetRef",
  currentLayerParam = "assetRef",
  baselineLayerControlsTargetId,
  currentLayerControlsTargetId,
  hidePrepareActions = false,
  presentation = "default",
}: {
  siteId: string;
  workAreaId: string;
  baselineHeading: string;
  currentHeading: string;
  baselineLayers: WindowedViewerLayer[];
  currentLayers: WindowedViewerLayer[];
  baselineCrs: string | null;
  currentCrs: string | null;
  jobs: PreparedWindowJob[];
  jobsState: "ready" | "denied" | "unavailable";
  canRead: boolean;
  canRequest: boolean;
  requestsHref: string;
  workAreaRing: Array<[number, number]> | null;
  workAreaCrs: string;
  hideLayerControls?: boolean;
  baselineAssetRef?: string;
  currentAssetRef?: string;
  layerControlsInRail?: boolean;
  /** 칸 제목 앞 역할 표기 — 기본 "기준 자료"/"비교 자료", 독립 보기는 "관측 A"/"관측 B". */
  baselineRoleLabel?: string;
  currentRoleLabel?: string;
  /** 같은 제출 묶음 안에서 층을 바꿀 때 이동할 주소 — 주면 로컬 상태 대신 링크로 둔다. */
  baselineLayerHref?: string;
  baselineLayerParam?: "assetRef" | "visualAAssetRef";
  currentLayerHref?: string;
  currentLayerParam?: "assetRef" | "visualBAssetRef";
  /** 레일 포털 대상 — 기본 workspace-baseline/current-layer-controls. */
  baselineLayerControlsTargetId?: string;
  currentLayerControlsTargetId?: string;
  /** true면 두 칸 모두 새 창 준비 요청 UI를 숨긴다. 기본 false. */
  hidePrepareActions?: boolean;
  /** "canvas"면 큰 픽셀을 먼저 두고 안내 박스는 한 줄로 둔다. 기본 "default". */
  presentation?: "default" | "canvas";
}) {
  const canvasMode = presentation === "canvas";
  const verdict = sharedPlaneForCompare(baselineCrs, currentCrs);
  return (
    <div className={`flex min-w-0 flex-col ${canvasMode ? "gap-2" : "gap-3"}`}>
      {canvasMode ? (
        <p className="text-[11.5px] leading-5 text-ink-muted" role="status">
          {verdict.ok
            ? "각 칸은 독립된 보기입니다. 같은 범위 맞춤·같은 색 눈금은 지원하지 않습니다."
            : verdict.notice}
        </p>
      ) : (
        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <h3 className="text-[13px] font-bold">{baselineRoleLabel === "관측 A" ? "독립 보기 — 정합 근거 없음" : "나란히 보기 안내(창 단위 픽셀 보기)"}</h3>
          {verdict.ok ? (
            <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
              두 칸은 같은 위치 기준({verdict.crs})의 작업구역 경계와 함께 둡니다. 화면 맞춤이 실제 지형 일치를 뜻하지 않으며,
              동기화된 공간 비교(같은 범위 맞춤·같은 색 눈금)는 지원하지 않습니다. 화면을 겹쳐도 분석 근거가 되지 않습니다.
            </p>
          ) : (
            <p className="mt-1 text-[12.5px] leading-5 text-ink-2" role="status">{verdict.notice}</p>
          )}
          <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">
            각 칸의 DSM 명암은 그 창 안에서만 늘이기한 상대 음영입니다. 창이 다르면 밝기가 달라도 높이 차이로 읽지 마세요.
          </p>
        </div>
      )}
      <div className={`grid min-w-0 gap-3 ${canvasMode ? "md:grid-cols-2" : "gap-4 md:grid-cols-2"}`}>
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-[12px] font-bold">{baselineRoleLabel} · {baselineHeading}</p>
          <SiteWindowedPixelViewer
            siteId={siteId}
            workAreaId={workAreaId}
            layers={baselineLayers}
            jobs={jobs}
            jobsState={jobsState}
            canRead={canRead}
            canRequest={canRequest}
            requestsHref={requestsHref}
            workAreaRing={workAreaRing}
            workAreaCrs={workAreaCrs}
            observationHeading={baselineHeading}
            idPrefix="windowed-baseline"
            slimHeader
            hideLayerControls={hideLayerControls}
            selectedAssetRef={baselineAssetRef}
            layerSelectHref={baselineLayerHref}
            layerSelectParam={baselineLayerParam}
            layerControlsTargetId={layerControlsInRail ? (baselineLayerControlsTargetId ?? "workspace-baseline-layer-controls") : undefined}
            hidePrepareActions={hidePrepareActions}
            presentation={presentation}
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-[12px] font-bold">{currentRoleLabel} · {currentHeading}</p>
          <SiteWindowedPixelViewer
            siteId={siteId}
            workAreaId={workAreaId}
            layers={currentLayers}
            jobs={jobs}
            jobsState={jobsState}
            canRead={canRead}
            canRequest={canRequest}
            requestsHref={requestsHref}
            workAreaRing={workAreaRing}
            workAreaCrs={workAreaCrs}
            observationHeading={currentHeading}
            idPrefix="windowed-current"
            slimHeader
            hideLayerControls={hideLayerControls}
            selectedAssetRef={currentAssetRef}
            layerSelectHref={currentLayerHref}
            layerSelectParam={currentLayerParam}
            layerControlsTargetId={layerControlsInRail ? (currentLayerControlsTargetId ?? "workspace-current-layer-controls") : undefined}
            hidePrepareActions={hidePrepareActions}
            presentation={presentation}
          />
        </div>
      </div>
    </div>
  );
}
