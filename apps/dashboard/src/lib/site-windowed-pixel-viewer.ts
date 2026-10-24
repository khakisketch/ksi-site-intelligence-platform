import type {
  SpatialDataAvailability,
  SpatialDataExecutionState,
  SpatialDataJobView,
  SpatialDataReceipt,
} from "@/lib/core-api/spatial-data-types";
import {
  MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM,
  nativeBoundsFromInspection,
  resolveBoundedPixelWindow,
  type InspectedRasterGrid,
  type PixelWindowSelection,
} from "@/lib/spatial-data-request";
import { resolveViewportWindows } from "@/lib/spatial-display-viewport";
import { sameDisplayPlane } from "@/app/sites/[siteId]/site-spatial";

/**
 * 창 단위 실제픽셀 보기(임시 시각화 어댑터)의 순수 규칙.
 *
 * - 판정·재계산을 하지 않는다. Core가 준 검사 격자·준비 기록·권리 사실에서
 *   "무엇을 보여줄지"만 고른다.
 * - 좌표 재해석·보정·정량 계산을 하지 않는다. 창→범위 계산은
 *   `resolveBoundedPixelWindow`의 정확한 네이티브 사각형만 쓴다.
 * - 감사 무결성·데이터 검증 적합성·화면 표시 가능성은 한 깃발로 합치지
 *   않는다. 이 모듈은 표시 가능성(viewability)만 다룬다.
 *
 * Invariants: INV-020(면적 어림 금지 — 범위 판정 없음)/INV-024(원본 식별 보존)/
 * INV-053(네이티브 격자 — 좌표 재해석 없음)/INV-060·061(권한·이그레스).
 */

/** 어댑터임을 밝히는 고정 문구 — 검증 대체로 읽히지 않게 한다. */
export const WINDOWED_VIEWER_ADAPTER_LABEL = "임시 시각화 어댑터 · 실제 파일의 준비된 창";
export const WINDOWED_VIEWER_ADAPTER_NOTE =
  "이 보기는 정식 자료 검증·정확도 평가를 대체하지 않습니다. 보여주는 픽셀은 Core 준비 기록과 바이트 전체가 일치할 때만 그립니다.";
export const WINDOWED_VIEWER_READ_LABEL = "이미 준비된 창 보기";
export const WINDOWED_VIEWER_REQUEST_LABEL = "이 구역의 창 준비 요청";

/**
 * 단일 창의 표시용 사실 — 서버가 준 준비 기록 그대로다. 이 화면이 새로
 * 만들거나 보증하는 값이 아니다.
 */
export interface PreparedWindowJob {
  jobId: string;
  assetRef: string;
  executionState: SpatialDataExecutionState;
  availability: SpatialDataAvailability;
  createdAt: string;
  receipt: SpatialDataReceipt | null;
}

export function toPreparedWindowJob(item: SpatialDataJobView): PreparedWindowJob {
  return {
    jobId: item.jobId,
    assetRef: item.assetRef,
    executionState: item.executionState,
    availability: item.availability,
    createdAt: item.createdAt,
    receipt: item.receipt ?? null,
  };
}

/**
 * 같은 관측의 한 레이어(정사영상 또는 DSM)가 화면에 내놓는 사실.
 * 검사·좌표·수직 기준은 Core 확인 사실의 옮김이며, 이 화면의 판정이 아니다.
 */
export interface WindowedViewerLayer {
  assetRef: string;
  observationEpochId: string;
  kind: string;
  kindLabel: string;
  isDsm: boolean;
  fileName: string;
  revision: number;
  submissionRef: string;
  inspectedRaster: InspectedRasterGrid | null;
  observedCrsIdentifier: string | null;
  observedCrsDigest: string | null;
  /** Core 검사 결과(원문 코드) — 화면은 사람 말로만 옮긴다. */
  inspectionOutcome: "MEASURED" | "NOT_APPLICABLE" | "REJECTED" | null;
  verticalReference: string | null;
}

export function inspectionOutcomeLabel(outcome: WindowedViewerLayer["inspectionOutcome"]): string {
  if (outcome === "MEASURED") return "파일 정보 확인됨";
  if (outcome === "REJECTED") return "거부됨";
  if (outcome === "NOT_APPLICABLE") return "적용 대상 아님";
  return "아직 확인되지 않음";
}

/**
 * 알려진 선택 출력 만료 — 같은 자산 참조의 읽은 준비 기록이 1건 이상 있고
 * 그 모두가 보관 만료(RETENTION_EXPIRED)일 때만 true. 읽을 수 있는 창·
 * 진행 중·실패·알 수 없는 상태가 하나라도 있으면 false를 둔다. 기록이
 * 없으면(스캔하지 않은 부재) false다. false일 때는 뷰어의 기존 판정에 맡긴다.
 * 판정은 호출자가 이미 읽은 목록 범위 안에서만 하며, 바이트 권한이나
 * 원본 유무를 새로 단정하지 않는다.
 */
export function isKnownExpiredAsset(
  jobs: readonly PreparedWindowJob[],
  assetRef: string,
): boolean {
  const scoped = jobs.filter((job) => job.assetRef === assetRef);
  return scoped.length > 0 && scoped.every((job) => job.availability === "RETENTION_EXPIRED");
}

/**
 * 지금 바로 그릴 수 있는 준비된 창 — COMPLETED + 출력 정보 + 접근 허용.
 * "볼 수 있음"은 이 창의 표시 가능성에 대한 말이지, 검증·적합성 판정이 아니다.
 */
export function readableWindowJobs(
  jobs: readonly PreparedWindowJob[],
  assetRef: string,
): PreparedWindowJob[] {
  return jobs.filter(
    (job) =>
      job.assetRef === assetRef &&
      job.executionState === "COMPLETED" &&
      job.availability === "AVAILABLE" &&
      job.receipt !== null &&
      job.receipt.jobId === job.jobId,
  );
}

/**
 * 레일 썸네일용 첫 번째 그릴 수 있는 창 — 같은 정확한 자료의 준비 기록 중
 * 가장 먼저 확인된 하나만 둔다. 없으면 null이며, 다른 자료의 화면을
 * 가져오지 않는다. N+1 조회를 만들지 않는다(호출자가 이미 읽은 목록에서 고른다).
 */
export function firstReadableWindowJob(
  jobs: readonly PreparedWindowJob[],
  assetRef: string,
): PreparedWindowJob | null {
  return readableWindowJobs(jobs, assetRef)[0] ?? null;
}

/** 이미 준비된 부분 출력도 보여준다. 타일망과 다르다고 자료가 없는 것은 아니다. */
export function preparedWindowFallback(
  grid: InspectedRasterGrid | null,
  jobs: readonly PreparedWindowJob[],
  assetRef: string,
): PreparedWindowJob | null {
  const readable = readableWindowJobs(jobs, assetRef);
  const bounds = grid ? nativeBoundsFromInspection(grid) : null;
  const cover = bounds ? resolveViewportWindows(grid, bounds) : null;
  if (cover?.ok && readable.some((job) => cover.windows.some((window) =>
    window.pixelWindow.every((value, index) => value === job.receipt!.pixelWindow[index]),
  ))) return null;
  return readable[0] ?? null;
}

/** 창 선택기의 사람이 읽는 한 줄 — 픽셀 크기와 네이티브 범위만 둔다. */
export function windowOptionLabel(job: PreparedWindowJob): string {
  const receipt = job.receipt;
  if (!receipt) return `요청 ${job.jobId}`;
  return `${receipt.width} × ${receipt.height} 픽셀 · 범위 [${receipt.actualBounds.join(", ")}]`;
}

/** 표시 범위의 사람용 한 줄 — 반올림·변환 없이 원문 수치 그대로 둔다. */
export function formatNativeWindowExtent(
  actualBounds: readonly number[],
  observedCrsIdentifier: string,
): string {
  return `${observedCrsIdentifier} · [${actualBounds.join(", ")}]`;
}

/**
 * 이웃 창 선택 — 현재 창에서 행·열 방향으로 반 창씩 옮기고 격자 안에
 * 고정한다. 유효하지 않으면 null이다(요청을 만들지 않는다).
 */
export function adjacentWindowSelection(
  grid: InspectedRasterGrid,
  current: PixelWindowSelection,
  dCol: number,
  dRow: number,
): PixelWindowSelection | null {
  if (!Number.isInteger(dCol) || !Number.isInteger(dRow)) return null;
  const stepCol = Math.max(1, Math.floor(current.width / 2));
  const stepRow = Math.max(1, Math.floor(current.height / 2));
  const col = Math.min(
    Math.max(0, current.col + dCol * stepCol),
    Math.max(0, grid.width - current.width),
  );
  const row = Math.min(
    Math.max(0, current.row + dRow * stepRow),
    Math.max(0, grid.height - current.height),
  );
  const candidate: PixelWindowSelection = { width: current.width, height: current.height, col, row };
  const resolved = resolveBoundedPixelWindow(grid, candidate);
  return resolved.ok ? candidate : null;
}

/** 한 변 상한(512) 안에서 현재 창 크기를 그대로 두는지 확인한다. */
export function windowSizeWithinLimit(width: number, height: number): boolean {
  return (
    Number.isInteger(width) &&
    Number.isInteger(height) &&
    width >= 1 &&
    height >= 1 &&
    width <= MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM &&
    height <= MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM
  );
}

export type SharedPlaneVerdict =
  | { ok: true; crs: string }
  | { ok: false; notice: string };

/**
 * 두 시점 비교의 같은 화면 평면 여부 — 같은 좌표계 표기일 때만 나란히 둔다.
 * 위치 맞춤(정합) 확인이 아니며, 다르면 동기화 비교를 막고 이유만 밝힌다.
 */
export function sharedPlaneForCompare(
  baselineCrs: string | null,
  currentCrs: string | null,
): SharedPlaneVerdict {
  if (!baselineCrs || !currentCrs) {
    return {
      ok: false,
      notice:
        "두 자료의 위치 기준을 확인하지 못해 동기화된 공간 비교를 하지 않습니다. 각 자료는 따로 볼 수 있습니다.",
    };
  }
  if (!sameDisplayPlane(baselineCrs, currentCrs)) {
    return {
      ok: false,
      notice:
        "두 자료의 위치 기준이 달라 동기화된 공간 비교를 하지 않습니다. 각 자료는 따로 볼 수 있습니다. 화면을 겹쳐도 분석 근거가 되지 않습니다.",
    };
  }
  return { ok: true, crs: baselineCrs };
}

/** DSM 상대 음영의 고정 문구 — 절대 높이·측정값으로 읽히지 않게 한다. */
export const DSM_RELATIVE_SHADING_NOTE =
  "단일 밴드를 명암으로 표시합니다(화면용 상대 음영). 이 미리보기는 수직 기준 적합성·높이 정확도를 판정하지 않습니다.";
export const DSM_RELATIVE_LEGEND_LABEL = "어두움 — 밝음 · 상대 음영이며 측정값이 아님";
/** 창마다 늘이기가 다시 계산되므로 창 간 밝기 비교가 높낮이 차이가 아님을 밝힌다. */
export const DSM_WINDOW_STRETCH_NOTE =
  "각 창의 명암은 그 창 안에서만 늘이기한 상대 음영입니다. 창이 다르면 밝기가 달라도 높이 차이로 읽지 마세요.";

/** 세 상태의 분리 문구 — 합성 깃발을 두지 않는다. */
export const AUDIT_STATE_NOTE =
  "감사 추적: 이 화면은 감사 판정을 하지 않습니다. 감사·무결성 확인은 Core 기록이 맡습니다.";
export const VALIDATION_STATE_NOTE =
  "데이터 검증 적합성: 아래 Core 확인 사실이 근거이며, 이 화면이 다시 판정하지 않습니다. 볼 수 있다는 뜻이 쓸 수 있다는 뜻이 아닙니다.";
export const VIEWABILITY_STATE_NOTE =
  "공간 표시 가능 여부: 이 창의 바이트를 지금 그릴 수 있는지만 말합니다.";

export const NO_COMPOSITE_FLAG_COPY =
  "이 화면은 종합 판정(준비됨·검증됨 같은 하나의 깃발)을 두지 않습니다.";

/** 다른 주체의 창은 존재 자체를 드러내지 않는다 — 404/403 모두 같은 문구다. */
export const FOREIGN_WINDOW_COPY =
  "요청을 찾을 수 없거나 현재 조회할 수 없습니다. 다른 계정이 준비한 창은 이 화면에서 열 수 없습니다.";
