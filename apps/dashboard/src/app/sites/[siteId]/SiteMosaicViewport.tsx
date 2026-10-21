"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";

import {
  decodeReceiptPreview,
  fetchVerifiedReceiptBytes,
  SpatialDataPreviewError,
  type DecodedReceiptPreview,
} from "@/lib/spatial-data-preview";
import {
  DisplayPrepareIssueError,
  DisplayPrepareScheduler,
  stableIdempotencyKey,
  type DisplaySchedulerSnapshot,
  type ScheduledDisplayWindow,
} from "@/lib/spatial-display-scheduler";
import {
  MOSAIC_ASSEMBLY_HEADING,
  MOSAIC_ASSEMBLY_LABEL,
  MOSAIC_ASSEMBLY_NOTE,
  MOSAIC_CACHE_REFUSAL_COPY,
  MOSAIC_VIEWPORT_NOTE,
  MosaicPaintCache,
  mosaicCanvasGeometry,
  mosaicCellView,
  mosaicCoverStatusCopy,
  mosaicIssueTargets,
  mosaicPlacements,
  orderCoverByVisibilityCentrality,
  resolveMosaicCover,
  selectHysteresisRetainedKeys,
  type DisplayGapReason,
} from "@/lib/spatial-display-mosaic";
import { VIEWPORT_RESOLVE_COPY } from "@/lib/spatial-display-viewport";
import type { DisplayViewportBounds } from "@/lib/spatial-display-viewport";
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
import { DisplayControlStrip, type DisplayControlAction } from "./DisplayControlStrip";
import {
  DSM_RELATIVE_SHADING_NOTE,
  DSM_WINDOW_STRETCH_NOTE,
  FOREIGN_WINDOW_COPY,
  readableWindowJobs,
  type PreparedWindowJob,
} from "@/lib/site-windowed-pixel-viewer";
import { REASON_COPY as SPATIAL_DATA_REQUEST_REASON_COPY } from "@/app/sites/[siteId]/spatial-assets/SpatialDataRequestAction";

/**
 * 여러 창의 이어 보기 — 임시 시각화 어댑터의 모자이크 자리.
 *
 * - 뷰포트를 소스 원점 기준 창 집합으로 해석하고, 모자란 창은 기존
 *   스케줄러(최대 2개 동시·안정 키·재시도 가능 429의 bounded back-off·
 *   뷰포트 supersede)로 준비 요청한다. 권리·격자·영수증 판정은 Core가
 *   그대로 소유한다.
 * - 영수증 대조를 마친 바이트만 네이티브 평면의 한 캔버스에 정수
 *   오프셋으로 나란히 둔다. 이음새 보정·재표본화·혼합을 하지 않으며,
 *   겹침이 있으면 겹쳐 그리지 않는다.
 * - 아직 오지 않은 창은 실제 영역의 이름 있는 "준비 중" 빈칸으로 두고,
 *   실패·권리 없음은 사유와 함께 빈칸으로 둔다. 가짜 내용을 채우지 않는다.
 * - 이 화면의 이동·확대는 표시용이며 측정값이 아니고, 계산 다각형이 아니다.
 */

export interface MosaicViewportProps {
  siteId: string;
  workAreaId: string;
  assetRef: string;
  grid: { transform: readonly number[]; width: number; height: number };
  observedCrsDigest: string | null;
  observedCrsIdentifier: string | null;
  isDsm: boolean;
  jobs: PreparedWindowJob[];
  canRequest: boolean;
  requestsHref: string;
}

type MosaicFailure = { reason: DisplayGapReason; message: string };

function fileHrefFor(siteId: string, workAreaId: string, jobId: string): string {
  return `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-data-requests/${encodeURIComponent(jobId)}/file`;
}

function pixelKeyOf(pixelWindow: readonly [number, number, number, number]): string {
  return pixelWindow.join(",");
}

function mosaicFailureMessage(error: unknown): MosaicFailure {
  if (error instanceof SpatialDataPreviewError) {
    switch (error.kind) {
      case "CANCELLED":
        return { reason: "PREPARE_FAILED", message: "불러오기를 취소했습니다." };
      case "TIMEOUT":
        return { reason: "PREPARE_FAILED", message: "준비된 파일을 받을 수 있는 시간을 넘겨 중단했습니다. 준비 상태 다시 확인 뒤에 다시 시도하세요." };
      case "TOO_LARGE":
        return { reason: "PREPARE_FAILED", message: "준비된 출력이 브라우저 표시 한계를 넘어 그리지 않습니다. 구역 자료 준비에서 다운로드로 받으세요." };
      case "SIZE_MISMATCH":
      case "HASH_MISMATCH":
      case "BAD_RECEIPT":
        return { reason: "RECEIPT_MISMATCH", message: MOSAIC_CACHE_REFUSAL_COPY.RECEIPT_CHANGED };
      case "UNSUPPORTED":
        return { reason: "RECEIPT_MISMATCH", message: error.message };
      case "HTTP": {
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
          return { reason: "RIGHTS_UNAVAILABLE", message: FOREIGN_WINDOW_COPY };
        }
        return { reason: "PREPARE_FAILED", message: "준비된 파일을 받지 못했습니다. 준비 상태 다시 확인 뒤에 다시 시도하세요." };
      }
      case "NETWORK":
      default:
        return { reason: "PREPARE_FAILED", message: error.message };
    }
  }
  if (error instanceof DisplayPrepareIssueError) {
    return { reason: "PREPARE_FAILED", message: error.message };
  }
  return { reason: "PREPARE_FAILED", message: "창을 준비하지 못했습니다. 준비 상태 다시 확인 뒤에 다시 시도하세요." };
}

export function SiteMosaicViewport({
  siteId,
  workAreaId,
  assetRef,
  grid,
  observedCrsDigest,
  observedCrsIdentifier,
  isDsm,
  jobs,
  canRequest,
  requestsHref,
}: MosaicViewportProps) {
  const router = useRouter();
  const ownerToken = useId();
  const footprint = useMemo<DisplayViewportBounds>(() => {
    const [a, , c, , e, f] = grid.transform;
    return [c, f + e * grid.height, c + a * grid.width, f];
  }, [grid]);
  // 표시 뷰 상태 — 이미 그린 버퍼의 CSS 표시만 바꾼다. 준비·커버·영수증·
  // 원본 격자는 그대로 두며, 새 타일 해석·새 네트워크 요청을 만들지 않는다.
  const display = useDisplayViewState();
  const view = display.view;
  const [viewportNote, setViewportNote] = useState<string | null>(null);
  // 타일 해석은 전체 범위에서 한 번만 둔다. 표시 이동·확대는 커버를 다시
  // 해석하지 않으므로, 준비된 창과 모자란 창이 바뀌지 않는다.
  const activeViewport = footprint;
  const cover = useMemo(() => resolveMosaicCover(grid, activeViewport), [grid, activeViewport]);
  const coverKey = cover.ok
    ? cover.windows.map((plan) => plan.pixelWindow.join(",")).join(";")
    : `blocked:${cover.reason}`;
  const jobsKey = jobs.map((job) => `${job.jobId}:${job.executionState}:${job.availability}`).join(";");

  const readable = useMemo(() => readableWindowJobs(jobs, assetRef), [jobs, assetRef]);
  const readableMap = useMemo(() => {
    const map = new Map<string, PreparedWindowJob>();
    for (const job of readable) {
      const receipt = job.receipt;
      if (!receipt) continue;
      map.set(pixelKeyOf(receipt.pixelWindow), job);
    }
    return map;
  }, [readable]);
  const failedJobs = useMemo(
    () =>
      jobs.filter(
        (job) =>
          job.assetRef === assetRef &&
          (job.executionState === "FAILED" || job.executionState === "EXPIRED"),
      ),
    [jobs, assetRef],
  );

  const [lane, setLane] = useState<DisplaySchedulerSnapshot | null>(null);
  const [fetchingKeys, setFetchingKeys] = useState<readonly string[]>([]);
  const [failures, setFailures] = useState<Record<string, MosaicFailure>>({});
  const [paintedKeys, setPaintedKeys] = useState<readonly string[]>([]);
  const [paintError, setPaintError] = useState<string | null>(null);
  const [requestNote, setRequestNote] = useState<string | null>(null);
  const [requestBusy, setRequestBusy] = useState(false);
  // 이미 준비된 창의 읽기(GET)는 진입 시 바로 나간다 — 같은 guarded GET+SHA
  // 경로이며 새 바이트 권한을 만들지 않는다. 준비 요청(POST)은 작업자의
  // 명시적 "채우기"에서만 나가며, 진입·이동·확대만으로는 쓰기가 나가지 않는다.
  const [fillTick, setFillTick] = useState(0);
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
              purpose: "GENERAL_DATA_USE",
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
  const [mosaicCache] = useState(() => new MosaicPaintCache(ownerToken));
  const fetchingRef = useRef<Set<string>>(new Set());
  const paintedKeysRef = useRef<readonly string[]>([]);
  const syncPaintedKeys = (next: readonly string[]) => {
    paintedKeysRef.current = next;
    setPaintedKeys(next);
  };

  const geometry = useMemo(
    () => (cover.ok ? mosaicCanvasGeometry(cover.windows) : null),
    [cover],
  );
  const placements = useMemo(
    () => (cover.ok && geometry ? mosaicPlacements(cover.windows, geometry) : []),
    [cover, geometry],
  );

  // S2 — paint 전 재검증에 쓰는 세션 보유 권리 사실. readable 존재 자체가
  // Core 목록 응답의 현행 grant·회수·용도·소유 판정이며, Core 현행 상태가
  // 주인이다. 부실 허용 한계(freshness bound)는 TBD(O-4) — 지어내지 않는다.
  const currentFor = (receipt: {
    outputSha256: string;
    outputSizeBytes: number;
    observedCrsDigest: string;
  }) => ({
    outputSha256: receipt.outputSha256,
    outputSizeBytes: receipt.outputSizeBytes,
    assetRef,
    purpose: "GENERAL_DATA_USE" as const,
    observedCrsDigest: receipt.observedCrsDigest,
    rights: { grantLive: true, notRevoked: true, purposeAllowed: true },
  });

  // 모자란 창을 스케줄러에 건다. 같은 집합의 반복은 새 PREPARE 없이
  // 합류·재입장하며, 뷰포트가 바뀌면 새 집합 밖의 대기열은 버린다.
  // 진입·이동·확대만으로는 나가지 않으며, "채우기"를 눌렀을 때만 간다.
  useEffect(() => {
    if (!cover.ok) return;
    const scheduler = schedulerRef.current;
    if (!scheduler) return;
    const activeFetches = fetchingRef.current;
    let alive = true;
    const controllers = new Map<string, AbortController>();
    void (async () => {
      // 보관과 화면의 현재 상태를 대조한다 — 권리·영수증이 바뀌면 내놓지 않는다.
      const valid = paintedKeysRef.current.filter((key) => {
        const plan = cover.windows.find((item) => pixelKeyOf(item.pixelWindow) === key);
        const match = plan ? readableMap.get(key) : undefined;
        const receipt = match?.receipt;
        if (!plan || !receipt) {
          mosaicCache.evict(key);
          return false;
        }
        const served = mosaicCache.serve(key, currentFor(receipt), ownerToken);
        return served.ok;
      });
      if (valid.length !== paintedKeysRef.current.length) syncPaintedKeys(valid);
      setFailures((previous) => {
        let changed = false;
        const next: Record<string, MosaicFailure> = {};
        for (const [key, failure] of Object.entries(previous)) {
          if (failure.reason === "RIGHTS_UNAVAILABLE" || failure.reason === "RECEIPT_MISMATCH") {
            next[key] = failure;
            continue;
          }
          if (!cover.windows.some((plan) => pixelKeyOf(plan.pixelWindow) === key)) changed = true;
          else next[key] = failure;
        }
        return changed ? next : previous;
      });
      // 쓰기(PREPARE POST)는 명시적 "채우기"에서만 나간다. 읽기는 진입 시에도
      // 나가며, 모자란 창의 준비 요청은 아래 집합에만 건다.
      if (fillTick > 0 && canRequest && observedCrsDigest) {
        // S1 — 중심 가시성 순서로 발행한다(서버 FIFO가 없으므로 클라이언트가 만든다).
        const orderedPlans = orderCoverByVisibilityCentrality(cover.windows, activeViewport);
        const targets = mosaicIssueTargets(
          orderedPlans,
          assetRef,
          observedCrsDigest,
          "GENERAL_DATA_USE",
        );
        const missing = targets.filter(
          (target) =>
            !readableMap.has(pixelKeyOf(target.pixelWindow)) &&
            !scheduler.completedResult(target.key),
        );
        // 이미 읽을 수 있는 창은 준비 요청하지 않는다 — ensure에는 모자란 집합만 건다.
        // S1 — 핀 고정 히스테리시스: 다음 커버 근처의 대기열은 유지한다.
        const retainKeys = selectHysteresisRetainedKeys(
          targets
            .filter((target) => scheduler.snapshot().queued.includes(target.key))
            .map((target) => ({ key: target.key, pixelWindow: target.pixelWindow })),
          cover.windows,
        );
        setLane(scheduler.ensure(missing, { retainKeys }));
        if (missing.length > 0) {
          setRequestBusy(true);
          const settled = await Promise.allSettled(
            missing.map((target) => scheduler.join(target.key) ?? Promise.resolve(null)),
          );
          if (!alive) return;
          setLane(scheduler.snapshot());
          setRequestBusy(false);
          const okCount = settled.filter((item) => item.status === "fulfilled").length;
          const failed = settled.find((item) => item.status === "rejected");
          if (failed && failed.status === "rejected") {
            const message = mosaicFailureMessage(failed.reason).message;
            setRequestNote(
              `창 ${missing.length}개의 준비 요청 중 일부를 만들지 못했습니다. ${message} 준비 상태 다시 확인 뒤에 다시 시도하세요.`,
            );
          } else {
            setRequestNote(
              `창 ${okCount}개의 준비 요청을 만들었습니다. 처리가 끝나면 준비 상태 다시 확인을 눌러 이어 보기를 채우세요. 준비 완료는 정확도나 분석 사용 가능 여부를 보증하지 않습니다.`,
            );
          }
        }
      }
      for (const plan of orderCoverByVisibilityCentrality(cover.windows, activeViewport)) {
        if (!alive) return;
        const key = pixelKeyOf(plan.pixelWindow);
        const match = readableMap.get(key);
        const receipt = match?.receipt;
        if (!match || !receipt || receipt.jobId !== match.jobId) continue;
        const current = currentFor(receipt);
        if (mosaicCache.serve(key, current, ownerToken).ok) continue;
        if (activeFetches.has(key)) continue;
        const controller = new AbortController();
        controllers.set(key, controller);
        activeFetches.add(key);
        setFetchingKeys([...activeFetches]);
        try {
          const bytes = await fetchVerifiedReceiptBytes(
            fileHrefFor(siteId, workAreaId, match.jobId),
            current,
            controller.signal,
          );
          const decoded: DecodedReceiptPreview = await decodeReceiptPreview(bytes, {
            width: receipt.width,
            height: receipt.height,
          });
          if (!alive || controller.signal.aborted) continue;
          mosaicCache.store(
            {
              key,
              outputSha256: receipt.outputSha256,
              outputSizeBytes: receipt.outputSizeBytes,
              width: decoded.width,
              height: decoded.height,
              pixels: decoded.pixels,
              assetRef,
              purpose: "GENERAL_DATA_USE",
              observedCrsDigest: receipt.observedCrsDigest,
            },
            ownerToken,
          );
          if (!paintedKeysRef.current.includes(key)) {
            syncPaintedKeys([...paintedKeysRef.current, key]);
          }
          setFailures((previous) => {
            if (!(key in previous)) return previous;
            const next = { ...previous };
            delete next[key];
            return next;
          });
        } catch (error) {
          if (!alive || controller.signal.aborted) continue;
          const failure = mosaicFailureMessage(error);
          if (failure.reason === "RIGHTS_UNAVAILABLE" || failure.reason === "RECEIPT_MISMATCH") {
            mosaicCache.evict(key);
            syncPaintedKeys(paintedKeysRef.current.filter((item) => item !== key));
          }
          // 이미 그린 바이트가 지금 영수증과 맞으면 둔다 — 일시적 실패가 그린 창을 지우지 않는다.
          const stillOk = mosaicCache.serve(key, current, ownerToken).ok;
          if (!stillOk) {
            syncPaintedKeys(paintedKeysRef.current.filter((item) => item !== key));
            setFailures((previous) => ({ ...previous, [key]: failure }));
          }
        } finally {
          controllers.delete(key);
          activeFetches.delete(key);
          if (alive) setFetchingKeys([...activeFetches]);
        }
      }
    })();
    return () => {
      alive = false;
      for (const controller of controllers.values()) controller.abort();
      activeFetches.clear();
      setFetchingKeys([]);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- cover/readableMap의 동일성은 coverKey/jobsKey 문자열로만 본다. 객체 식별자로는 부모 리렌더마다 같은 집합을 새 요청으로 오인한다
  }, [coverKey, jobsKey, siteId, workAreaId, fillTick]);

  // 그린 창을 한 캔버스에 정수 오프셋으로 둔다. 평활화·혼합·늘이기 없음.
  // 그리기 자체가 외부 시스템 동기화이므로 콜백 ref에서 수행한다.
  const paintMosaicRef = useCallback(
    (canvas: HTMLCanvasElement | null) => {
      if (canvas === null) return;
      if (!cover.ok || !geometry) return;
      try {
        canvas.width = geometry.width;
        canvas.height = geometry.height;
      } catch {
        setPaintError("이 브라우저에서 이어 보기 화면을 만들 수 없습니다. 다운로드는 그대로 받을 수 있습니다.");
        return;
      }
      const context = canvas.getContext("2d");
      if (!context) {
        setPaintError("이 브라우저에서 이어 보기를 그릴 수 없습니다. 다운로드는 그대로 받을 수 있습니다.");
        return;
      }
      try {
        context.imageSmoothingEnabled = false;
        context.clearRect(0, 0, geometry.width, geometry.height);
        for (const placement of mosaicPlacements(cover.windows, geometry)) {
          const key = pixelKeyOf(placement.plan.pixelWindow);
          // 그린 창으로 기록된 것만 둔다 — 보관 대조는 영수증 사실로 다시 한다.
          if (!paintedKeys.includes(key)) continue;
          const match = readableMap.get(key);
          const receipt = match?.receipt;
          if (!receipt) continue;
          const served = mosaicCache.serve(
            key,
            {
              outputSha256: receipt.outputSha256,
              outputSizeBytes: receipt.outputSizeBytes,
              assetRef,
              purpose: "GENERAL_DATA_USE",
              observedCrsDigest: receipt.observedCrsDigest,
              rights: { grantLive: true, notRevoked: true, purposeAllowed: true },
            },
            ownerToken,
          );
          if (!served.ok) continue;
          // 위치는 영수증의 픽셀 창에서 직접 둔다. 계획과 키가 맞아야만
          // 여기까지 오므로, 어긋난 영수증은 그려지지 않는다.
          // S2 — 매 paint 전 재검증: 재검증 불가 적중은 MISS이며 그리지 않는다.
          const dx = receipt.pixelWindow[0] - geometry.originC0;
          const dy = receipt.pixelWindow[2] - geometry.originR0;
          if (
            !Number.isInteger(dx) || !Number.isInteger(dy) || dx < 0 || dy < 0 ||
            dx + receipt.width > geometry.width || dy + receipt.height > geometry.height
          ) {
            continue;
          }
          context.putImageData(
            new ImageData(served.slot.pixels, served.slot.width, served.slot.height),
            dx,
            dy,
          );
        }
        setPaintError(null);
      } catch {
        setPaintError("이 브라우저에서 이어 보기를 그릴 수 없습니다. 다운로드는 그대로 받을 수 있습니다.");
      }
    },
    [cover, geometry, readableMap, mosaicCache, ownerToken, paintedKeys, assetRef],
  );

  // ── 표시 이동·확대 — 같은 버퍼의 CSS 표시만 바꾼다 ──
  // - 버튼·키·드래그·휠이 useDisplayViewState 하나로 같은 규칙을 탄다.
  // - 준비·커버·영수증은 그대로 두며, 어떤 경우에도 새 타일 해석·새 준비·
  //   새 GET 버스트를 만들지 않는다(진입·채우기의 읽기와 같다).
  const edgeNote = (kind: "pan" | "zoom-in" | "zoom-out") => {
    setViewportNote(
      kind === "pan"
        ? "격자 끝이라 더 이상 옮길 수 없습니다. 전체 보기로 돌아가세요."
        : "표시 확대 한계입니다. 전체 보기로 돌아가세요.",
    );
  };

  const clearEdgeNote = () => setViewportNote(null);

  const onControlAction = (action: DisplayControlAction) => {
    switch (action) {
      case "pan-left": if (display.pan(-0.25, 0)) clearEdgeNote(); else edgeNote("pan"); return;
      case "pan-right": if (display.pan(0.25, 0)) clearEdgeNote(); else edgeNote("pan"); return;
      case "pan-up": if (display.pan(0, -0.25)) clearEdgeNote(); else edgeNote("pan"); return;
      case "pan-down": if (display.pan(0, 0.25)) clearEdgeNote(); else edgeNote("pan"); return;
      case "zoom-in": if (display.zoom(1)) clearEdgeNote(); else edgeNote("zoom-in"); return;
      case "zoom-out": if (display.zoom(-1)) clearEdgeNote(); else edgeNote("zoom-out"); return;
      case "reset": display.reset(); clearEdgeNote(); return;
    }
  };

  const cancelLoading = () => {
    fetchingRef.current.clear();
    setFetchingKeys([]);
    setFillTick(0);
    const scheduler = schedulerRef.current;
    if (scheduler) setLane(scheduler.ensure([]));
    setRequestNote("대기 중인 창 요청을 버리고 받는 중이던 바이트를 끊었습니다. 그린 창은 그대로 둡니다.");
  };

  // ── 표시 제스처(드래그·휠·키보드) — 같은 표시 뷰 상태를 쓴다 ──
  // - 드래그는 이동 중에 CSS만 바꾸고(버퍼 다시 읽기 없음), 끝내도 새 요청 없음.
  // - 터치 드래그는 페이지 세로 스크롤을 위해 건드리지 않는다(마우스·펜만).
  // - 휠은 포커스된 보기 안이거나 Ctrl과 함께일 때만 확대한다.
  const viewWrapRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const wheelLastRef = useRef(0);

  const onViewPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    // 터치 드래그는 세로 스크롤을 위해 건드리지 않는다. 합성 환경의
    // button 미지정(언어 명세상 주 버튼)은 주 버튼으로 간주한다.
    if (event.pointerType === "touch") return;
    if (event.button !== undefined && event.button !== 0) return;
    if (!cover.ok) return;
    dragRef.current = { x: event.clientX, y: event.clientY };
    if (typeof event.currentTarget.setPointerCapture === "function") {
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // 캡처 실패해도 같은 요소 위의 이동·종료는 그대로 처리한다.
      }
    }
  };

  const onViewPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = dragRef.current;
    if (!start) return;
    const wrap = viewWrapRef.current;
    const rect = wrap?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return;
    const fractions = displayDragFractions(
      event.clientX - start.x,
      event.clientY - start.y,
      rect.width,
      rect.height,
    );
    if (!fractions) return;
    if (display.pan(fractions.fx, fractions.fy)) clearEdgeNote();
    else edgeNote("pan");
    dragRef.current = { x: event.clientX, y: event.clientY };
  };

  const onViewPointerUp = () => {
    dragRef.current = null;
  };

  const onViewKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.nativeEvent.isComposing) return;
    const action = displayGestureKeyAction(event.key);
    if (!action) return;
    event.preventDefault();
    if (action.kind === "pan") {
      if (display.pan(action.dCol, -action.dRow)) clearEdgeNote();
      else edgeNote("pan");
    } else if (action.kind === "zoom") {
      if (display.zoom(action.factor < 1 ? 1 : -1)) clearEdgeNote();
      else edgeNote(action.factor < 1 ? "zoom-in" : "zoom-out");
    } else {
      display.reset();
      clearEdgeNote();
    }
  };

  // 휠 확대는 non-passive 리스너에서만 preventDefault할 수 있다. 포커스·Ctrl
  // 의도가 아니면 그대로 두어 페이지 스크롤을 가로채지 않는다.
  useEffect(() => {
    const wrap = viewWrapRef.current;
    if (!wrap || !cover.ok) return;
    const onWheel = (event: WheelEvent) => {
      const focused = wrap.contains(document.activeElement);
      if (!isDisplayZoomWheelIntent({ focused, ctrlKey: event.ctrlKey })) return;
      event.preventDefault();
      const now = Date.now();
      if (!displayWheelReady(wheelLastRef.current, now)) return;
      wheelLastRef.current = now;
      if (display.zoom(event.deltaY > 0 ? -1 : 1)) clearEdgeNote();
      else edgeNote(event.deltaY > 0 ? "zoom-out" : "zoom-in");
    };
    wrap.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      wrap.removeEventListener("wheel", onWheel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cover.ok]);

  const cells = cover.ok
    ? cover.windows.map((plan) => {
        const key = pixelKeyOf(plan.pixelWindow);
        const painted = paintedKeys.includes(key);
        if (painted) {
          return mosaicCellView({ key, plan, painted: true, fetching: false, preparing: false, failure: null });
        }
        const failure = failures[key] ?? null;
        if (failure) {
          return mosaicCellView({ key, plan, painted: false, fetching: false, preparing: false, failure });
        }
        const fetching = fetchingKeys.includes(key);
        // 준비 중 여부는 스케줄러의 알림 상태로만 본다 — 렌더 중에 스케줄러를 직접 읽지 않는다.
        const scheduled =
          (lane?.active.includes(key) ?? false) ||
          (lane?.queued.includes(key) ?? false) ||
          (lane?.done.includes(key) ?? false);
        return mosaicCellView({ key, plan, painted: false, fetching, preparing: scheduled, failure: null });
      })
    : [];
  const paintedCount = cells.filter((cell) => cell.phase === "painted").length;
  // 채우기로 새로 가져와야 하는 창 — 준비된 적도 그린 적도 없는 창이다.
  const missingCount = cover.ok
    ? cover.windows.filter((plan) => {
        const key = pixelKeyOf(plan.pixelWindow);
        return !readableMap.has(key) && !paintedKeys.includes(key) && !(failures[key]?.reason === "RIGHTS_UNAVAILABLE");
      }).length
    : 0;
  const pendingFetchCount = cover.ok
    ? cover.windows.filter((plan) => {
        const key = pixelKeyOf(plan.pixelWindow);
        return readableMap.has(key) && !paintedKeys.includes(key) && !failures[key];
      }).length
    : 0;
  const canFillNow =
    cover.ok &&
    (pendingFetchCount > 0 || (canRequest !== false && observedCrsDigest !== null && missingCount > 0));
  // 준비된 출력도 실제 작업도 없으면 거대한 빈 지도 대신 현재 열람 상태를 말한다.
  // 이는 표시 자리의 유무일 뿐, 자료 검사·감사·정량 적합성 판정이 아니다.
  const showViewport = readable.length > 0 || fillTick > 0 || jobs.some((job) =>
    job.assetRef === assetRef && (job.executionState === "QUEUED" || job.executionState === "RUNNING"),
  );

  return (
    <div className="flex flex-col gap-2">
      <p className="sr-only">이어 보기 — 여러 창의 나란한 배치</p>

      {!cover.ok && (
        <p className="text-[12px] leading-5 text-ink-2" role="status">{VIEWPORT_RESOLVE_COPY[cover.reason]}</p>
      )}

      {cover.ok && geometry && !showViewport && (
        <p role="status" className="rounded-md border border-line bg-surface px-3 py-4 text-[12.5px] leading-5 text-ink-2">
          현재 계정에 준비된 표시 자료가 없습니다. 등록 자료가 없다는 뜻은 아닙니다.
          {canRequest
            ? " 아래에서 표시할 자료의 준비를 요청할 수 있습니다."
            : " 표시 준비는 권한 있는 담당자에게 요청하세요. 자료 정보는 아래 상세에서 확인할 수 있습니다."}
        </p>
      )}
      {cover.ok && geometry && showViewport && (
        <>
          <div className="relative flex flex-col gap-2">
          <div
            ref={viewWrapRef}
            tabIndex={0}
            role="group"
            aria-label="이어 보기 화면. 마우스로 끌거나 방향키로 이동하고, + − 키로 확대합니다. 휠은 그림을 선택한 후, 또는 Ctrl과 함께 사용하세요. Home 키는 전체 보기로 돌아갑니다."
            onPointerDown={onViewPointerDown}
            onPointerMove={onViewPointerMove}
            onPointerUp={onViewPointerUp}
            onPointerCancel={onViewPointerUp}
            onKeyDown={onViewKeyDown}
            className="overflow-hidden rounded border border-line bg-sunk/30 focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ touchAction: "pan-y" }}
          >
            <div
              className="relative mx-auto w-full"
              style={{
                maxWidth: `min(100%, calc(52dvh * ${geometry.width / geometry.height}))`,
                transform: displayViewTransform(view),
                transformOrigin: "0 0",
              }}
            >
              <canvas
                ref={paintMosaicRef}
                className="block h-auto w-full"
                style={{ imageRendering: "pixelated" }}
                role="img"
                aria-label={`이어 보기 ${geometry.width} × ${geometry.height} 픽셀 · ${observedCrsIdentifier ?? "위치 기준 확인 불가"}`}
              />
              {placements.map(({ plan, dx, dy }) => {
                const key = pixelKeyOf(plan.pixelWindow);
                if (paintedKeys.includes(key)) return null;
                const failure = failures[key] ?? null;
                const fetching = fetchingKeys.includes(key);
                const scheduled =
                  (lane?.active.includes(key) ?? false) ||
                  (lane?.queued.includes(key) ?? false) ||
                  (lane?.done.includes(key) ?? false);
                return (
                  <div
                    key={key}
                    className="pointer-events-none absolute border border-dashed border-ink-muted/60"
                    style={{
                      left: `${(dx / geometry.width) * 100}%`,
                      top: `${(dy / geometry.height) * 100}%`,
                      width: `${(plan.width / geometry.width) * 100}%`,
                      height: `${(plan.height / geometry.height) * 100}%`,
                    }}
                    aria-hidden="true"
                  >
                    <span className="absolute inset-0 flex items-center justify-center px-1 text-center text-[11px] leading-4 text-ink-2">
                      {failure ? "그리지 않음" : fetching ? "자료 읽는 중" : scheduled ? "준비 중" : "표시 준비 필요"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
          {/* 이동·확대 도구는 그림 바로 옆에 둔다 — 기술 문단 아래가 아니라. */}
          <DisplayControlStrip
            groupLabel="이어 보기 화면 이동·확대"
            onAction={onControlAction}
            zoomInDisabled={view.zoom >= 4}
            zoomOutDisabled={view.zoom <= 1}
          />
          </div>
          {viewportNote && (
            <p className="text-[12px] leading-5 text-ink-2" role="status">{viewportNote}</p>
          )}
          <p className="text-[11.5px] leading-5 text-ink-muted">{DISPLAY_GESTURE_HINT}</p>
          <p className="text-[12px] leading-5 text-ink-2" role="status">
            {mosaicCoverStatusCopy(paintedCount, cells.length)}
            {observedCrsIdentifier ? ` · ${observedCrsIdentifier} 네이티브 평면 ${geometry.width} × ${geometry.height} 픽셀` : null}
          </p>
          {isDisplayViewMoved(view) && (
            <p className="text-[12px] leading-5 text-ink-2" role="status">
              표시 확대 {displayZoomPercent(view)}%
              {view.cx !== 0.5 || view.cy !== 0.5 ? " · 이동한 화면" : ""} · 원본 버퍼는 그대로 둡니다.
            </p>
          )}
          {isDsm && (
            <>
              <p className="text-[12px] leading-5 text-ink-2">{DSM_RELATIVE_SHADING_NOTE}</p>
              <p className="text-[11.5px] leading-5 text-ink-muted">{DSM_WINDOW_STRETCH_NOTE}</p>
            </>
          )}
          <p className="text-[11.5px] leading-5 text-ink-muted">{MOSAIC_VIEWPORT_NOTE}</p>
          {paintError && (
            <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2" role="alert">
              {paintError}
            </p>
          )}
          <p className="text-[11.5px] leading-5 text-ink-muted">
            화면의 이동·확대는 같은 격자의 같은 영역을 같은 창 집합으로 다시 찾습니다. 뒤로 돌아오면 새 준비 요청 없이 그린 창을 둡니다.
          </p>
        </>
      )}

      {lane?.laneCopy && (
        <p role="status" className="text-[12px] leading-5 text-ink-2">{lane.laneCopy}</p>
      )}
      {lane?.retryCopy && (
        <p role="status" className="text-[12px] leading-5 text-ink-2">{lane.retryCopy}</p>
      )}
      {failedJobs.length > 0 && (
        <p className="text-[12px] leading-5 text-ink-2" role="status">
          {`준비에 실패한 요청 ${failedJobs.length}개가 있습니다. 사유는 구역 자료 준비에서 확인하세요. 실패한 창은 빈칸으로 둡니다.`}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {canFillNow && (
          <ResponsiveActionBoundary
            action="SPATIAL_DATA_REQUEST"
            reason="창 준비 요청은 노트북 이상의 화면에서 진행하세요. 준비된 창 보기는 모바일에서도 할 수 있습니다."
          >
            <button
              type="button"
              className="btn btn-primary min-h-11"
              onClick={() => setFillTick((tick) => tick + 1)}
              disabled={requestBusy}
            >
              {missingCount > 0 ? `이어 보기 채우기 (모자란 창 ${missingCount}개)` : "이어 보기 채우기"}
            </button>
          </ResponsiveActionBoundary>
        )}
        <button type="button" className="btn min-h-11" onClick={() => router.refresh()}>
          준비 상태 다시 확인
        </button>
        <button
          type="button"
          className="btn min-h-11"
          onClick={cancelLoading}
          disabled={fetchingKeys.length === 0 && (lane?.queuedCount ?? 0) === 0}
        >
          대기 취소
        </button>
      </div>
      {(!canRequest || !observedCrsDigest) && (
        <p className="text-[12px] leading-5 text-ink-2">
          새 창 준비 요청을 만들 권한 또는 위치 기준 확인값이 없어 이미 준비된 창만 이어 봅니다. 필요한 창과 용도를 담당자에게 알려 주세요.
        </p>
      )}
      {requestBusy && (
        <p className="text-[12px] text-ink-2" role="status">창 준비 요청을 만드는 중…</p>
      )}
      {requestNote && (
        <p role="status" aria-live="polite" className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] leading-5 text-ink-2">
          {requestNote}
          {" 준비 상태 다시 확인은 읽기만 하며 새 요청을 만들지 않습니다."}
        </p>
      )}
      <p className="text-[11.5px] leading-5 text-ink-muted">
        {"같은 계정이 준비한 창만 봅니다. "}
        <a href={requestsHref} className="tap-target underline">구역 자료 준비에서 확인</a>
        {". 이어 붙인 화면은 하나의 검증된 자료가 아니며, 정확도 평가·측량·정산 근거가 아닙니다."}
      </p>
      <details className="text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold">이어 보기 조건·창별 상태</summary>
        <div className="mt-1 flex flex-col gap-1">
          <p className="font-bold">{MOSAIC_ASSEMBLY_HEADING}</p>
          <p className="leading-5">{MOSAIC_ASSEMBLY_LABEL}</p>
          <p className="leading-5 text-ink-muted">{MOSAIC_ASSEMBLY_NOTE}</p>
          <ul className="mt-1 flex flex-col gap-1">
            {cells.map((cell) => (
              <li key={cell.key} className="text-[12px] leading-5">
                <span className="font-mono">[{cell.plan.pixelWindow.join(", ")}]</span>
                {` · ${cell.detail}`}
              </li>
            ))}
          </ul>
        </div>
      </details>
    </div>
  );
}
