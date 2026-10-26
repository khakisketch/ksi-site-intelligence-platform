"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

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
import { nativeBoundsFromInspection } from "@/lib/spatial-data-request";
import { planeUnitForCrs, sameDisplayPlane } from "./site-spatial";
import { SiteMosaicAbsentDiagram } from "./SiteMosaicAbsentDiagram";
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
  /** 준비 요청 폼이 정보 서랍에 있을 때 그 자리로 가는 링크 — 만료 회복을 이력 페이지로 보내지 않는다. */
  prepareHref?: string;
  /** 같은 네이티브 평면의 작업구역 링 — 같은 평면일 때만 범위 도식에 겹친다. */
  workAreaRing?: Array<[number, number]> | null;
  /** 작업구역 링의 위치 기준 표기 — observedCrsIdentifier와 같을 때만 겹친다. */
  workAreaCrs?: string | null;
  /**
   * 시각 탐색 무대용 — 큰 픽셀을 먼저 두고 긴 안내·범례·진단은 펼침에 둔다.
   * 기본값 "default"는 기존 화면 그대로이며, 바이트 검증·읽기 흐름을 바꾸지 않는다.
   */
  presentation?: "default" | "canvas";
  /**
   * 작업환경 정보 서랍 안 숨김 자리 식별자 — 주면 접힌 상세를 무대가 아니라
   * 서랍으로 포털한다. 무대에는 매체 상태와 1차 회복만 둔다. 서랍이 닫혀도
   * 자리는 유지되므로 포털이 사라지지 않는다. 없으면 기존 자리 펼침을 둔다.
   */
  detailsTargetId?: string | null;
  /**
   * 시각 탐색 기본 본문용 — 미리보기 준비/다시 준비 요청 버튼을 숨긴다.
   * 읽기(준비 상태 다시 확인·구역 자료 준비 길)와 접힌 진단은 그대로 둔다.
   */
  hidePrepareActions?: boolean;
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
  prepareHref,
  workAreaRing = null,
  workAreaCrs = null,
  hidePrepareActions = false,
  presentation = "default",
  detailsTargetId = null,
}: MosaicViewportProps) {
  const canvasMode = presentation === "canvas";
  const router = useRouter();
  const ownerToken = useId();
  const footprint = useMemo<DisplayViewportBounds>(() => {
    const [a, , c, , e, f] = grid.transform;
    return [c, f + e * grid.height, c + a * grid.width, f];
  }, [grid]);
  // 직접 조작 표시 — 이미 그린 버퍼의 CSS 표시만 바꾼다. 준비·커버·영수증·
  // 원본 격자는 그대로 두며, 새 타일 해석·새 네트워크 요청을 만들지 않는다.
  // 이어 보기·낱창·부분 출력이 같은 훅 하나로 같은 규칙을 탄다.
  const viewport = useDirectViewport();
  const view = viewport.view;
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
              `창 ${okCount}개의 준비 요청을 만들었습니다. 처리가 끝나면 준비 상태 다시 확인을 눌러 미리보기를 채우세요.`,
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

  const cancelLoading = () => {
    fetchingRef.current.clear();
    setFetchingKeys([]);
    setFillTick(0);
    const scheduler = schedulerRef.current;
    if (scheduler) setLane(scheduler.ensure([]));
    setRequestNote("대기 중인 창 요청을 버리고 받는 중이던 바이트를 끊었습니다. 그린 창은 그대로 둡니다.");
  };

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
    !hidePrepareActions &&
    cover.ok &&
    (pendingFetchCount > 0 || (canRequest !== false && observedCrsDigest !== null && missingCount > 0));
  // 아래 compact/showCanvas 분기는 디코딩된 바이트 유무로만 가른다. 준비
  // 기록·작업 상태는 바이트가 아니며, 자료 검사·정량 적합성 판정도 아니다.


  // 픽셀이 없을 때의 범위 도식 사실 — Core 검사 격자에서 유도한 파일 전체
  // 사각형과 같은 평면의 작업구역 링만 둔다. 재투영·유효 픽셀 단정을 하지
  // 않으며, 사각형은 파일 끝을 잰 값일 뿐 빈틈 없는 범위가 아니다.
  const absentFileBounds = nativeBoundsFromInspection(grid);
  const absentFileRing: Array<[number, number]> | null = absentFileBounds
    ? [
        [absentFileBounds[0], absentFileBounds[1]],
        [absentFileBounds[2], absentFileBounds[1]],
        [absentFileBounds[2], absentFileBounds[3]],
        [absentFileBounds[0], absentFileBounds[3]],
      ]
    : null;
  const absentOverlaid =
    workAreaRing !== null &&
    workAreaRing.length >= 3 &&
    observedCrsIdentifier !== null &&
    workAreaCrs !== null &&
    sameDisplayPlane(workAreaCrs, observedCrsIdentifier);
  const absentOverlayNote = !workAreaRing || workAreaRing.length < 3
    ? "작업구역 경계를 확인하지 못해 파일 범위만 단독으로 둡니다."
    : !observedCrsIdentifier || !workAreaCrs
      ? "위치 기준을 확인하지 못해 작업구역 경계를 겹쳐 표시하지 않았습니다. 파일 범위만 단독으로 둡니다."
      : !absentOverlaid
        ? "위치 기준이 달라 작업구역 경계를 겹쳐 표시하지 않았습니다. 파일 범위만 단독으로 둡니다."
        : null;
  const absentCrsLabel = observedCrsIdentifier ?? "확인 불가";

  // 같은 관측(같은 assetRef)의 현재 작업 기록에서만 상태를 말한다. 한 층의
  // 만료로 다른 층까지 만료되었다고 말하지 않는다.
  const assetJobs = jobs.filter((job) => job.assetRef === assetRef);
  const hasRetentionExpired = assetJobs.some(
    (job) => job.availability === "RETENTION_EXPIRED",
  );
  const hasRightsBlock = assetJobs.some(
    (job) => job.availability === "ACCESS_REVOKED" || job.availability === "ACCESS_EXPIRED",
  );
  const hasCanceled = assetJobs.some((job) => job.executionState === "CANCELED");
  const hasDeadlineExpired = assetJobs.some((job) => job.executionState === "EXPIRED");
  const hasFailed = assetJobs.some((job) => job.executionState === "FAILED");
  const hasUnknownOutput = assetJobs.some(
    (job) => job.availability === "UNAVAILABLE" || job.availability === "NOT_READY",
  );
  const absentKind: "expired" | "rights" | "failed" | "canceled" | "deadline" | "unavailable" | "empty" =
    hasRetentionExpired ? "expired"
      : hasRightsBlock ? "rights"
        : hasFailed ? "failed"
          : hasCanceled ? "canceled"
            : hasDeadlineExpired ? "deadline"
          : hasUnknownOutput ? "unavailable"
            : "empty";
  const absentCopy: { headline: string; recovery: string } =
    absentKind === "expired"
      ? {
          headline: "미리보기 보관 기간이 끝났습니다.",
          recovery: hidePrepareActions && prepareHref
            ? "선택 자료 정보에서 다시 요청하거나, 준비 상태 다시 확인을 누르세요."
            : "구역 자료 준비에서 다시 요청하거나, 준비 상태 다시 확인을 누르세요.",
        }
      : absentKind === "rights"
        ? {
            headline: "이 관측의 준비된 창을 볼 권한이 없습니다.",
            recovery: "필요한 창과 용도를 담당자에게 알려 주세요.",
          }
        : absentKind === "failed"
          ? {
              headline: "창 준비에 실패했습니다.",
              recovery: "구역 자료 준비에서 사유를 확인한 뒤 다시 준비하세요.",
            }
          : absentKind === "canceled"
            ? {
                headline: "표시 준비 요청이 취소됐습니다.",
                recovery: "다시 준비하거나, 구역 자료 준비에서 요청 이력을 확인하세요.",
              }
          : absentKind === "deadline"
            ? {
                  headline: "표시 준비 요청이 기한을 넘겼습니다.",
                  recovery: "다시 준비하거나, 구역 자료 준비에서 요청 이력을 확인하세요.",
                }
          : absentKind === "unavailable"
            ? {
                headline: "준비된 출력 상태를 확인할 수 없습니다.",
                recovery: "준비 상태 다시 확인을 누르거나 구역 자료 준비에서 확인하세요.",
              }
            : {
                headline: "준비된 표시 자료가 없습니다.",
                 recovery: canRequest
                   ? hidePrepareActions
                     ? "구역 자료 준비에서 미리보기 준비 상태와 요청 이력을 확인하세요."
                     : "아래에서 미리보기를 준비할 수 있습니다."
                  : "표시 준비는 권한 있는 담당자에게 요청하세요.",
              };

  // 큰 화면은 실제로 디코딩된 바이트가 있을 때만 둔다. 준비 기록·작업
  // 상태(available/queued)는 바이트가 아니다 — 같은 guarded GET+SHA 경로로
  // 받고 디코딩·캐시까지 통과한 창이 하나라도 있어야 캔버스를 펼친다.
  // 그 전까지는 빈 캔버스를 두지 않고 짧은 현재 상태만 둔다. NoData 투명
  // 타일은 정상 디코딩이면 그린 것으로 보며, 알파 0으로 실패를 단정하지 않는다.
  const hasPaintedPixels = paintedCount > 0 && paintError === null;
  const showCanvas = cover.ok && geometry !== null && hasPaintedPixels;
  // 현재 커버에 남은 읽기 실패 — 보관 만료·준비 작업 실패와 섞지 않고
  // 따로 말한다. 한 창의 실패를 모든 출력의 실패로 단정하지 않는다.
  const currentFailedKeys = cover.ok
    ? cover.windows
        .map((plan) => pixelKeyOf(plan.pixelWindow))
        .filter((key) => failures[key])
    : [];
  const firstReadFailure =
    currentFailedKeys.length > 0 ? (failures[currentFailedKeys[0]!] ?? null) : null;
  const hasQueuedOrRunning =
    jobs.some(
      (job) => job.assetRef === assetRef && (job.executionState === "QUEUED" || job.executionState === "RUNNING"),
    ) ||
    (lane?.active.length ?? 0) > 0 ||
    (lane?.queued.length ?? 0) > 0 ||
    requestBusy;
  const isReading = fetchingKeys.length > 0 || pendingFetchCount > 0;
  const compactKind: "paintFailure" | "loading" | "readFailure" | "preparing" | "absent" =
    paintError !== null
      ? "paintFailure"
      : isReading
        ? "loading"
        : firstReadFailure !== null
          ? "readFailure"
          : hasQueuedOrRunning
            ? "preparing"
            : "absent";
  const compactCopy: { headline: string; recovery: string; detail: string | null } =
    compactKind === "paintFailure"
      ? {
          headline: "미리보기를 표시하지 못했습니다.",
          recovery: "페이지를 새로고침하거나 다른 관측을 선택해 보세요.",
          detail: paintError,
        }
      : compactKind === "loading"
        ? {
            headline: "자료 읽는 중…",
            recovery: "",
            detail: null,
          }
        : compactKind === "readFailure" && firstReadFailure !== null
          ? firstReadFailure.reason === "RIGHTS_UNAVAILABLE"
            ? {
                headline: "이 관측의 준비된 창을 볼 권한이 없습니다.",
                recovery: "필요한 창과 용도를 담당자에게 알려 주세요.",
                detail: firstReadFailure.message,
              }
            : firstReadFailure.reason === "RECEIPT_MISMATCH"
              ? {
                  headline:
                    currentFailedKeys.length > 1
                      ? `창 ${currentFailedKeys.length}개를 표시하지 않습니다.`
                      : "창을 표시하지 않습니다.",
                  recovery: "받은 자료가 준비 기록과 다릅니다. 구역 자료 준비에서 다운로드로 다시 받으세요.",
                  detail: firstReadFailure.message,
                }
              : {
                  headline: "미리보기를 불러오지 못했습니다.",
                  recovery: "잠시 후 준비 상태를 다시 확인하세요.",
                  detail: null,
                }
          : compactKind === "preparing"
            ? {
                headline: "표시 자료를 준비 중입니다.",
                recovery: "준비가 끝나면 준비 상태 다시 확인을 누르세요.",
                detail: null,
              }
            : { headline: absentCopy.headline, recovery: absentCopy.recovery,
                detail: absentKind === "expired"
                  ? "준비된 적이 있으나 보관 기간이 지나 지금은 볼 수 없습니다. 등록된 자료와 검사 기록은 그대로입니다."
                  : null };

  const hasActiveWait = fetchingKeys.length > 0 || (lane?.queuedCount ?? 0) > 0;
  const supportCopy = requestNote ?? (failedJobs.length > 0
    ? `준비에 실패한 요청 ${failedJobs.length}개가 있습니다. 사유는 구역 자료 준비에서 확인하세요.`
    : null);

  // 무대용 간결 상태 — 사유 한 줄과 하나의 1차 회복만 둔다. 진입·읽기 흐름은
  // 그대로이며, 명시적 다시 준비(쓰기)는 아래 접힌 상세로만 둔다.
  const expiredInInspector = hidePrepareActions && prepareHref !== undefined;
  const canvasRequestsLink = (
    <a
      href={expiredInInspector && absentKind === "expired" ? prepareHref : requestsHref}
      className={compactKind === "absent" && absentKind === "expired"
        ? "btn btn-primary min-h-11"
        : "btn min-h-11 border-white/25 bg-sidebar-active font-semibold text-sidebar-active-ink"}
    >
      {expiredInInspector && absentKind === "expired"
        ? <>
            <span className="lg:hidden">준비 요청 방법 보기</span>
            <span className="hidden lg:inline">선택 자료 정보에서 준비 요청</span>
          </>
        : "구역 자료 준비에서 확인"}
    </a>
  );
  const canvasMediaAction = compactKind === "loading" || hasActiveWait ? (
    <button
      type="button"
      className="btn min-h-11 border-white/25 bg-sidebar-active font-semibold text-sidebar-active-ink"
      onClick={cancelLoading}
    >
      대기 취소
    </button>
  ) : compactKind === "preparing" ? (
    <WorkbenchRefreshButton />
  ) : compactKind === "readFailure" ? (
    firstReadFailure?.reason === "RIGHTS_UNAVAILABLE" ? null
      : firstReadFailure?.reason === "RECEIPT_MISMATCH" ? canvasRequestsLink
        : <WorkbenchRefreshButton />
  ) : compactKind === "paintFailure" ? (
    <WorkbenchRefreshButton />
  ) : absentKind === "rights" ? null
    : absentKind === "expired" || absentKind === "failed" || absentKind === "canceled" || absentKind === "deadline" ? (
      canvasRequestsLink
    ) : (
      <WorkbenchRefreshButton />
    );
  // 권한 없음은 사람 행동(담당자 요청)이 회복이므로 단추를 두지 않고 안내만 둔다.
  const canvasMediaHint =
    (compactKind === "readFailure" && firstReadFailure?.reason === "RIGHTS_UNAVAILABLE") || (compactKind === "absent" && absentKind === "rights")
      ? compactCopy.recovery
      : null;
  const canvasMediaAlert = compactKind !== "loading" && compactKind !== "preparing" && !(compactKind === "absent" && absentKind === "empty");

  const canvasDetailBody = (
    <div className="mt-2 flex min-w-0 flex-col gap-2 text-[12px] leading-5 text-ink-2">
      {requestBusy && <p role="status">창 준비 요청을 만드는 중…</p>}
      {supportCopy && <p role="status">{supportCopy}</p>}
      {canFillNow && (
        <div className="flex flex-col gap-1.5">
          <ResponsiveActionBoundary
            action="SPATIAL_DATA_REQUEST"
            reason="창 준비 요청은 노트북 이상의 화면에서 진행하세요."
            inlineNotice={false}
          >
            <button
              type="button"
              className="btn btn-primary min-h-11"
              onClick={() => setFillTick((tick) => tick + 1)}
              disabled={requestBusy}
            >
              {hasRetentionExpired ? "미리보기 다시 준비" : "미리보기 준비"}
            </button>
          </ResponsiveActionBoundary>
          <p className="text-[11.5px] leading-5 text-ink-muted lg:hidden">창 준비 요청은 노트북에서 할 수 있습니다.</p>
        </div>
      )}
      {absentFileRing && (
        <section aria-label="자료 범위">
          <p className="font-bold">자료 범위</p>
          <div className="mt-1">
            <SiteMosaicAbsentDiagram
              fileRing={absentFileRing}
              workAreaRing={workAreaRing}
              overlaid={absentOverlaid}
              overlayNote={absentOverlayNote}
              crsLabel={absentCrsLabel}
              planeUnit={observedCrsIdentifier ? planeUnitForCrs(observedCrsIdentifier) : "unknown"}
              filePixelSize={{ width: grid.width, height: grid.height }}
              fileExtentLabel={observedCrsIdentifier ? `${observedCrsIdentifier} 네이티브 평면 ${grid.width} × ${grid.height} 픽셀` : null}
            />
          </div>
        </section>
      )}
      <section aria-label="준비 과정·상세 상태">
        <p className="font-bold">준비 과정·상세 상태</p>
        <div className="mt-1 flex flex-col gap-1">
          {lane?.laneCopy && <p role="status" className="leading-5">{lane.laneCopy}</p>}
          {lane?.retryCopy && <p role="status" className="leading-5">{lane.retryCopy}</p>}
          {(!canRequest || !observedCrsDigest) && (
            <p className="leading-5">새 창 준비 요청을 만들 권한 또는 위치 기준 확인값이 없어 이미 준비된 창만 이어 봅니다.</p>
          )}
          <p className="leading-5">
            {"같은 계정이 준비한 창만 봅니다. "}
            <a href={requestsHref} className="tap-target underline">구역 자료 준비</a>
            {" · 준비 상태 다시 확인은 읽기만 하며 새 요청을 만들지 않습니다."}
          </p>
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
      </section>
    </div>
  );

  return (
    <div className="flex flex-col gap-2">
      <p className="sr-only">이어 보기 — 여러 창의 나란한 배치</p>

      {!cover.ok && (
        <p className="text-[12px] leading-5 text-ink-2" role="status">{VIEWPORT_RESOLVE_COPY[cover.reason]}</p>
      )}

      {cover.ok && geometry && !showCanvas && (canvasMode ? (
        <div className="flex w-full min-w-0 flex-col gap-1.5">
          <WorkbenchMediaState
            headline={compactCopy.headline}
            detail={compactCopy.detail}
            hint={canvasMediaHint}
            action={canvasMediaAction}
            alert={canvasMediaAlert}
            tone={compactKind === "absent" && absentKind === "expired" ? "absence" : "media"}
          />
          {detailsTargetId ? (
            <DetailsPortal targetId={detailsTargetId}>
              <details className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
                <summary className="tap-target cursor-pointer font-semibold">이어 보기 상세</summary>
                {canvasDetailBody}
              </details>
            </DetailsPortal>
          ) : (
            <details className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
              <summary className="tap-target cursor-pointer font-semibold">상세·준비</summary>
              {canvasDetailBody}
            </details>
          )}
        </div>
      ) : (
        <div className="flex w-full flex-col gap-2">
          <p role="status" className="text-[12.5px] leading-5 font-semibold text-ink-1">
            {compactCopy.headline}
          </p>
          {compactCopy.detail !== null && (
            <p className="text-[12px] leading-5 text-ink-2">{compactCopy.detail}</p>
          )}
          {compactCopy.recovery && <p className="text-[12px] leading-5 text-ink-2">{compactCopy.recovery}</p>}
          <div className="flex flex-wrap gap-2">
            {hidePrepareActions && <a href={requestsHref} className="btn min-h-11">구역 자료 준비</a>}
            {canFillNow && (
              <ResponsiveActionBoundary
                action="SPATIAL_DATA_REQUEST"
                reason="창 준비 요청은 노트북 이상의 화면에서 진행하세요."
                inlineNotice={false}
              >
                <button
                  type="button"
                  className="btn btn-primary min-h-11"
                  onClick={() => setFillTick((tick) => tick + 1)}
                  disabled={requestBusy}
                >
                  {hasRetentionExpired ? "미리보기 다시 준비" : "미리보기 준비"}
                </button>
              </ResponsiveActionBoundary>
            )}
            <button type="button" className="btn min-h-11" onClick={() => router.refresh()}>
              준비 상태 다시 확인
            </button>
            {hasActiveWait && (
              <button type="button" className="btn min-h-11" onClick={cancelLoading}>
                대기 취소
              </button>
            )}
          </div>
          {canFillNow && (
            <p className="text-[11.5px] leading-5 text-ink-muted lg:hidden">창 준비 요청은 노트북에서 할 수 있습니다.</p>
          )}
          {requestBusy && (
            <p className="text-[12px] text-ink-2" role="status">창 준비 요청을 만드는 중…</p>
          )}
          {supportCopy && (
            <p role="status" aria-live="polite" className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] leading-5 text-ink-2">
              {supportCopy}
            </p>
          )}
          {absentFileRing && (
            <details className="rounded-lg border border-line bg-sunk/40 px-3 py-2 text-[12px] text-ink-2">
              <summary className="tap-target cursor-pointer font-semibold">자료 범위 보기</summary>
              <div className="mt-2">
                <SiteMosaicAbsentDiagram
                  fileRing={absentFileRing}
                  workAreaRing={workAreaRing}
                  overlaid={absentOverlaid}
                  overlayNote={absentOverlayNote}
                  crsLabel={absentCrsLabel}
                  planeUnit={observedCrsIdentifier ? planeUnitForCrs(observedCrsIdentifier) : "unknown"}
                  filePixelSize={{ width: grid.width, height: grid.height }}
                  fileExtentLabel={observedCrsIdentifier ? `${observedCrsIdentifier} 네이티브 평면 ${grid.width} × ${grid.height} 픽셀` : null}
                />
              </div>
            </details>
          )}
          <details className="text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer font-semibold">준비 과정·상세 상태</summary>
            <div className="mt-1 flex flex-col gap-1">
              {lane?.laneCopy && <p role="status" className="leading-5">{lane.laneCopy}</p>}
              {lane?.retryCopy && <p role="status" className="leading-5">{lane.retryCopy}</p>}
              {(!canRequest || !observedCrsDigest) && (
                <p className="leading-5">새 창 준비 요청을 만들 권한 또는 위치 기준 확인값이 없어 이미 준비된 창만 이어 봅니다.</p>
              )}
              <p className="leading-5">
                {"같은 계정이 준비한 창만 봅니다. "}
                <a href={requestsHref} className="tap-target underline">구역 자료 준비에서 확인</a>
                {" · 준비 상태 다시 확인은 읽기만 하며 새 요청을 만들지 않습니다."}
              </p>
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
      ))}
      {showCanvas && (
        <>
          <div
            {...viewport.frameProps}
            aria-label="이어 보기 화면. 직접 끌어서 보고, 휠·두 손가락·두 번 두드리기로 확대합니다. 그림을 선택하면 방향키·Home 키도 쓸 수 있습니다."
            className={canvasMode
              ? "relative mx-auto w-full cursor-grab overflow-hidden rounded border border-line bg-sunk/30 focus-visible:outline-2 focus-visible:outline-offset-2 active:cursor-grabbing"
              : "relative w-full cursor-grab overflow-hidden rounded border border-line bg-sunk/30 focus-visible:outline-2 focus-visible:outline-offset-2 active:cursor-grabbing"}
            style={canvasMode
              ? { ...viewport.frameProps.style, aspectRatio: `${geometry.width} / ${geometry.height}`, maxWidth: `min(100%, calc((100dvh - 280px) * ${geometry.width / geometry.height}))` }
              : { ...viewport.frameProps.style, aspectRatio: `${geometry.width} / ${geometry.height}` }}
          >
            <div
              {...viewport.contentProps}
              className="relative h-full w-full"
            >
              <canvas
                ref={paintMosaicRef}
                className="block h-auto w-full"
                style={{ imageRendering: "pixelated" }}
                role="img"
                aria-label={`이어 보기 ${geometry.width} × ${geometry.height} 픽셀 · ${observedCrsIdentifier ?? "위치 기준 확인 불가"}`}
              />
            </div>
            <ViewportResetButton onReset={viewport.reset} />
          </div>
          <p className="text-[12px] leading-5 text-ink-2" role="status">
            {mosaicCoverStatusCopy(paintedCount, cells.length)}
            {observedCrsIdentifier ? ` · ${observedCrsIdentifier} 네이티브 평면 ${geometry.width} × ${geometry.height} 픽셀` : null}
          </p>
          {isDsm && (
            <p className={canvasMode ? "text-[11.5px] leading-5 text-ink-muted" : "text-[12px] leading-5 text-ink-2"}>{DSM_RELATIVE_SHADING_NOTE}</p>
          )}
          {paintError && (
            <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2" role="alert">
              {paintError}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {canFillNow && !canvasMode && (
              <ResponsiveActionBoundary
                action="SPATIAL_DATA_REQUEST"
                reason="창 준비 요청은 노트북 이상의 화면에서 진행하세요."
                inlineNotice={false}
              >
                <button
                  type="button"
                  className="btn btn-primary min-h-11"
                  onClick={() => setFillTick((tick) => tick + 1)}
                  disabled={requestBusy}
                >
                  미리보기 다시 준비
                </button>
              </ResponsiveActionBoundary>
            )}
            <button type="button" className="btn min-h-11" onClick={() => router.refresh()}>
              준비 상태 다시 확인
            </button>
            {hasActiveWait && (
              <button type="button" className="btn min-h-11" onClick={cancelLoading}>
                대기 취소
              </button>
            )}
          </div>
          {canFillNow && !canvasMode && (
            <p className="text-[11.5px] leading-5 text-ink-muted lg:hidden">창 준비 요청은 노트북에서 할 수 있습니다.</p>
          )}
          {requestBusy && !canvasMode && (
            <p className="text-[12px] text-ink-2" role="status">창 준비 요청을 만드는 중…</p>
          )}
          {supportCopy && !canvasMode && (
            <p role="status" aria-live="polite" className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] leading-5 text-ink-2">
              {supportCopy}
            </p>
          )}
          {detailsTargetId ? (
          <DetailsPortal targetId={detailsTargetId}>
            <details className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
              <summary className="tap-target cursor-pointer font-semibold">이어 보기 상세</summary>
              {canvasDetailBody}
            </details>
          </DetailsPortal>
          ) : canvasMode ? (
          <details className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer font-semibold">상세·준비</summary>
            {canvasDetailBody}
          </details>
          ) : (
          <details className="text-[12px] text-ink-2">
            <summary className="tap-target cursor-pointer font-semibold">준비 과정·상세 상태</summary>
            <div className="mt-1 flex flex-col gap-1">
              {isDisplayViewMoved(view) && (
                <p className="leading-5" role="status">
                  표시 확대 {displayZoomPercent(view)}%
                  {view.cx !== 0.5 || view.cy !== 0.5 ? " · 이동한 화면" : ""} · 원본 버퍼는 그대로 둡니다.
                </p>
              )}
              {viewport.note && <p className="leading-5" role="status">{viewport.note}</p>}
              <ViewportGestureHint />
              {isDsm && <p className="leading-5 text-ink-muted">{DSM_WINDOW_STRETCH_NOTE}</p>}
              <p className="leading-5 text-ink-muted">{MOSAIC_VIEWPORT_NOTE}</p>
              {lane?.laneCopy && <p role="status" className="leading-5">{lane.laneCopy}</p>}
              {lane?.retryCopy && <p role="status" className="leading-5">{lane.retryCopy}</p>}
              {(!canRequest || !observedCrsDigest) && (
                <p className="leading-5">새 창 준비 요청을 만들 권한 또는 위치 기준 확인값이 없어 이미 준비된 창만 이어 봅니다.</p>
              )}
              <p className="leading-5 text-ink-muted">
                {"같은 계정이 준비한 창만 봅니다. "}
                <a href={requestsHref} className="tap-target underline">구역 자료 준비에서 확인</a>
                {" · 준비 상태 다시 확인은 읽기만 하며 새 요청을 만들지 않습니다."}
              </p>
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
          )}
        </>
      )}
    </div>
  );
}
