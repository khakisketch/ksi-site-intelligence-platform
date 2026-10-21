/**
 * 현장 목록 미리보기 선택(presentation-only 순수 판정).
 *
 * Core가 내려준 작업 목록 안에서, 지금 이 자리에서 보여줄 수 있는 준비된
 * 출력 하나를 고른다. 판정 규칙:
 *
 * - 실행 완료(COMPLETED) + 현재 접근 허용(AVAILABLE) + 영수증 보유만 후보가
 *   된다. RETENTION_EXPIRED·ACCESS_REVOKED·ACCESS_EXPIRED·UNAVAILABLE 등
 *   현재 권리가 없는 출력은 고르지 않는다 — 만료·회수된 픽셀을 붙들지 않는다.
 *   실행 중·대기·실패·취소·기한 만료 작업도 후보가 아니다.
 * - 요청한 현장·구역·요청 식별자와 영수증의 귀속이 모두 맞아야 한다.
 *   어긋난 DTO로는 URL을 조립하지 않는다(실패 닫힘).
 * - 종류는 정사영상(ortho) 우선, 높이자료(DSM)는 대체다. Core 반환 순서
 *   안에서 고를 뿐, 등록·작업·준비 시각으로 재정렬하지 않는다 — '최신
 *   촬영' 같은 시간 추론을 하지 않는다.
 * - 작업구역을 합치지 않는다. 대표는 반드시 하나의 구역·하나의 요청이며,
 *   표시와 링크가 같은 자산 참조·구역을 가리킨다.
 * - 대표 미리보기는 언제나 부분 범위다. 단일 준비 창이 전체 현장·전체
 *   자산을 증명할 수는 없으므로, 커버리지가 입증되지 않는 한 '부분 범위'
 *   라벨을 단다. 실제·요청 범위가 같아도 전체 주장으로 바꾸지 않는다
 *   (픽셀 창의 좌표 해석을 화면이 새로 정하지 않는다).
 *
 * 이 모듈은 읽지 않는다(fetch 없음, Core import 없음). 바이트 권한·현재성
 * 검사는 같은 세션 BFF가 매번 다시 수행하고, 표시는 영수증 대조를 통과한
 * 바이트만 디코딩한다.
 */

import type { SpatialDataJobView, SpatialDataReceipt } from "./core-api/spatial-data-types";

/** 한 번의 목록 진입에서 훑는 작업구역 수 상한 — N+1 팬아웃 방지. */
export const SITE_PREVIEW_MAX_AREAS = 6;

/** 구역당 훑는 준비 요청 수 상한 — 같은 bound 안에서 고른다. */
export const SITE_PREVIEW_REQUESTS_PER_AREA = 8;

export interface SitePreviewAreaInput {
  workAreaId: string;
  name: string;
}

export interface SitePreviewPick {
  workArea: SitePreviewAreaInput;
  job: SpatialDataJobView;
  receipt: SpatialDataReceipt;
}

/**
 * 한 구역의 bounded 요청 목록에서 미리보기 후보 하나를 고른다.
 * null이면 이 구역에는 지금 표시할 준비된 출력이 없다(없음이지, 등록 자료
 * 부재가 아니다). Core 반환 순서를 유지하고 시간으로 다시 정렬하지 않는다.
 */
export function pickAreaPreviewJob(
  jobs: readonly SpatialDataJobView[],
  scope: { siteId: string; workAreaId: string },
): SpatialDataJobView | null {
  const usable = (job: SpatialDataJobView): job is SpatialDataJobView & { receipt: SpatialDataReceipt } =>
    job.executionState === "COMPLETED" &&
    job.availability === "AVAILABLE" &&
    job.siteId === scope.siteId &&
    job.workAreaId === scope.workAreaId &&
    job.receipt !== null &&
    job.receipt !== undefined &&
    job.receipt.jobId === job.jobId &&
    (job.receipt.artifactKind === "ortho" || job.receipt.artifactKind === "dsm");
  return (
    jobs.find((job) => usable(job) && job.receipt.artifactKind === "ortho") ??
    jobs.find((job) => usable(job) && job.receipt.artifactKind === "dsm") ??
    null
  );
}

export interface SitePreviewAssetFacts {
  revision: number | null;
  gsdM: number | null;
  captureStartedAt: string | null;
  captureEndedAt: string | null;
  captureDate: string | null;
  attribution: string | null;
  modificationNotice: string | null;
}

export interface SitePreviewDescriptor {
  available: true;
  siteId: string;
  workAreaId: string;
  workAreaName: string;
  requestId: string;
  assetRef: string;
  artifactKind: "ortho" | "dsm";
  /** 같은 세션 BFF의 준비 파일 경로 — 서명 URL·원본 키가 아니다. */
  fileHref: string;
  outputSha256: string;
  outputSizeBytes: number;
  width: number;
  height: number;
  preparedAt: string;
  asset: SitePreviewAssetFacts;
  partial: boolean;
  /** 미리보기 클릭이 여는 정확한 현장 주소(구역+자산 참조 고정). */
  siteHref: string;
}

export type SitePreviewLookup =
  | SitePreviewDescriptor
  | { available: false; reason: "no-output" | "unknown" };

/**
 * BFF가 Core에서 읽어 온 구역·요청·자산 사실을 표시 기술서로 접는다.
 * 자산 상세를 못 읽었으면(거부·없음) 라벨만 미상으로 접고 픽셀 자격에는
 * 손대지 않는다 — 바이트는 BFF가 어차피 다시 대조한다.
 */
export function buildSitePreviewDescriptor(input: {
  siteId: string;
  area: SitePreviewAreaInput;
  job: SpatialDataJobView;
  receipt: SpatialDataReceipt;
  asset: {
    revision: number;
    gsdM: number | null;
    captureStartedAt: string | null;
    captureEndedAt: string | null;
    captureDate?: string | null;
    attribution: string | null;
  } | null;
}): SitePreviewDescriptor {
  const { siteId, area, job, receipt, asset } = input;
  const fileHref =
    `/api/sites/${encodeURIComponent(siteId)}` +
    `/work-areas/${encodeURIComponent(area.workAreaId)}` +
    `/spatial-data-requests/${encodeURIComponent(job.jobId)}/file`;
  const siteHref =
    `/sites/${encodeURIComponent(siteId)}` +
    `?workAreaId=${encodeURIComponent(area.workAreaId)}` +
    `&assetRef=${encodeURIComponent(job.assetRef)}`;
  return {
    available: true,
    siteId,
    workAreaId: area.workAreaId,
    workAreaName: area.name,
    requestId: job.jobId,
    assetRef: job.assetRef,
    artifactKind: receipt.artifactKind,
    fileHref,
    outputSha256: receipt.outputSha256,
    outputSizeBytes: receipt.outputSizeBytes,
    width: receipt.width,
    height: receipt.height,
    preparedAt: receipt.preparedAt,
    asset: {
      revision: asset?.revision ?? null,
      gsdM: asset?.gsdM ?? null,
      captureStartedAt: asset?.captureStartedAt ?? null,
      captureEndedAt: asset?.captureEndedAt ?? null,
      captureDate: asset?.captureDate ?? null,
      attribution: asset?.attribution ?? receipt.attribution,
      modificationNotice: receipt.modificationNotice,
    },
    // 대표 미리보기는 언제나 부분 범위다. 단일 준비 창이 전체 현장·전체
    // 자산을 증명할 수는 없으므로, 커버리지가 입증되지 않는 한 부분 라벨을
    // 단다. 실제·요청 범위가 같아도 전체 주장으로 바꾸지 않는다.
    partial: true,
    siteHref,
  };
}

const PATH_SEGMENT = /^[^/\\?#\s\x00-\x1f\x7f@]+$/;
const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/;
const REQUEST_ID_PATTERN = /^sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ASSET_REF_PATTERN = /^ksa-v1-[0-9a-f]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * BFF 기술서의 런타임 바인딩 검증 — 받은 URL을 믿지 않고, 검증된 식별자로
 * 기대 경로를 로컬에서 다시 조립해 받은 값과 비교한다. 서명 URL·원본 키·
 * 외부 리다이렉트는 구조상 들어올 수 없다. 실패하면 null(미확인 취급)이다.
 */
export function sanitizeSitePreviewDescriptor(
  raw: unknown,
  siteId: string,
): SitePreviewDescriptor | null {
  if (!isRecord(raw) || raw.available !== true) return null;
  const workAreaId = raw.workAreaId;
  const requestId = raw.requestId;
  const assetRef = raw.assetRef;
  if (typeof siteId !== "string" || !PATH_SEGMENT.test(siteId)) return null;
  if (typeof workAreaId !== "string" || !PATH_SEGMENT.test(workAreaId)) return null;
  if (typeof requestId !== "string" || !REQUEST_ID_PATTERN.test(requestId)) return null;
  if (typeof assetRef !== "string" || !ASSET_REF_PATTERN.test(assetRef)) return null;
  if (raw.siteId !== siteId || raw.workAreaId !== workAreaId || raw.requestId !== requestId || raw.assetRef !== assetRef) {
    return null;
  }
  if (raw.artifactKind !== "ortho" && raw.artifactKind !== "dsm") return null;
  const expectedFileHref =
    `/api/sites/${encodeURIComponent(siteId)}` +
    `/work-areas/${encodeURIComponent(workAreaId)}` +
    `/spatial-data-requests/${encodeURIComponent(requestId)}/file`;
  const expectedSiteHref =
    `/sites/${encodeURIComponent(siteId)}` +
    `?workAreaId=${encodeURIComponent(workAreaId)}` +
    `&assetRef=${encodeURIComponent(assetRef)}`;
  if (raw.fileHref !== expectedFileHref || raw.siteHref !== expectedSiteHref) return null;
  if (typeof raw.outputSha256 !== "string" || !SHA256_PATTERN.test(raw.outputSha256.toLowerCase())) return null;
  if (!Number.isSafeInteger(raw.outputSizeBytes) || (raw.outputSizeBytes as number) < 1) return null;
  for (const dimension of [raw.width, raw.height]) {
    if (!Number.isSafeInteger(dimension) || (dimension as number) < 1 || (dimension as number) > 4096) return null;
  }
  if (typeof raw.preparedAt !== "string" || raw.preparedAt.length === 0) return null;
  if (typeof raw.workAreaName !== "string" || raw.workAreaName.length === 0) return null;
  if (typeof raw.partial !== "boolean") return null;
  const asset = raw.asset;
  if (!isRecord(asset)) return null;
  const { revision, gsdM, captureStartedAt, captureEndedAt, captureDate, attribution, modificationNotice } = asset;
  if (revision !== null && (!Number.isSafeInteger(revision) || (revision as number) < 0)) return null;
  if (gsdM !== null && (typeof gsdM !== "number" || !Number.isFinite(gsdM) || gsdM < 0)) return null;
  for (const moment of [captureStartedAt, captureEndedAt, captureDate]) {
    if (moment !== null && typeof moment !== "string") return null;
  }
  if (typeof attribution !== "string" || typeof modificationNotice !== "string") return null;
  return {
    available: true,
    siteId,
    workAreaId,
    workAreaName: raw.workAreaName,
    requestId,
    assetRef,
    artifactKind: raw.artifactKind,
    fileHref: expectedFileHref,
    outputSha256: raw.outputSha256,
    outputSizeBytes: raw.outputSizeBytes as number,
    width: raw.width as number,
    height: raw.height as number,
    preparedAt: raw.preparedAt,
    asset: {
      revision: revision as number | null,
      gsdM: gsdM as number | null,
      captureStartedAt: captureStartedAt as string | null,
      captureEndedAt: captureEndedAt as string | null,
      captureDate: captureDate as string | null,
      attribution,
      modificationNotice,
    },
    partial: raw.partial,
    siteHref: expectedSiteHref,
  };
}

/**
 * 미리보기 표시 체인의 bounded 슬롯 — 기술서 조회부터 바이트·디코딩까지
 * 같은 한도 안에서 돈다. 목록 진입의 느린 미리보기가 이름·행동을 막지
 * 않게 최대 2개만 동시에 진행한다. 취소된 대기는 즉시 큐에서 빠진다.
 */
export const SITE_PREVIEW_MAX_CONCURRENT_LOADS = 2;

let activePreviewLoads = 0;

type PreviewSlotWaiter = {
  fire: () => void;
  cancel: () => void;
};

const previewSlotWaiters: PreviewSlotWaiter[] = [];

export function acquirePreviewSlot(signal?: AbortSignal): Promise<() => void> {
  if (activePreviewLoads < SITE_PREVIEW_MAX_CONCURRENT_LOADS) {
    activePreviewLoads += 1;
    return Promise.resolve(releasePreviewSlot);
  }
  return new Promise<() => void>((resolve, reject) => {
    const waiter: PreviewSlotWaiter = {
      fire() {
        activePreviewLoads += 1;
        resolve(releasePreviewSlot);
      },
      cancel() {
        const index = previewSlotWaiters.indexOf(waiter);
        if (index >= 0) previewSlotWaiters.splice(index, 1);
        reject(new DOMException("Aborted", "AbortError"));
      },
    };
    previewSlotWaiters.push(waiter);
    signal?.addEventListener("abort", () => waiter.cancel(), { once: true });
  });
}

export function releasePreviewSlot(): void {
  activePreviewLoads = Math.max(0, activePreviewLoads - 1);
  const next = previewSlotWaiters.shift();
  if (next) next.fire();
}

/** 진단·회귀용 슬롯 계측 — 표시에 쓰지 않는다. */
export function previewSlotState(): { active: number; queued: number } {
  return { active: activePreviewLoads, queued: previewSlotWaiters.length };
}
