import type { AnalysisObservationOption } from "@/lib/core-api/analysis";
import { formatKoreanDateTime } from "@/lib/datetime";

/**
 * 사람용 표시 이름 헬퍼 — 표현만 담당한다.
 *
 * - 작업 지시 이름·자산 파일명은 Core가 이미 허가한 목록 응답에서만 가져온다.
 *   이름이 없다고 해서 존재 여부·권한·적합성을 추정하지 않으며, 진단은 Core와
 *   typed blocker가 소유한다.
 * - 기술 식별자(workOrderId, epoch ID, assetRef, jobId 등)는 절대 추측·합성하지
 *   않는다. 충돌할 때만 원문 전체를 그대로 덧붙이고, 항상 펼침(details) 영역에
 *   전체 값을 남긴다.
 * - 이 모듈은 순수 함수만 두며 "server-only" Core 클라이언트를 import하지
 *   않는다. Client Component에서도 그대로 쓸 수 있다.
 */

export type WorkOrderNameMap = Record<string, string>;

export interface CatalogAssetInfo {
  fileName: string;
  kind: string;
}

/** 허가된 작업 지시 목록에서 사람용 이름을 찾는다. 없으면 null — 추정하지 않는다. */
export function resolveWorkName(
  workOrderId: string,
  names: WorkOrderNameMap | null | undefined,
): string | null {
  if (!names || !Object.prototype.hasOwnProperty.call(names, workOrderId)) return null;
  const name = names[workOrderId];
  return typeof name === "string" && name.trim().length > 0 ? name : null;
}

/** 관측 촬영 구간을 사람용 한 줄로 만든다. 기존 analysisObservationLabel과 같은 시각 규율. */
export function formatCaptureInterval(startedAt: string, endedAt: string): string {
  const startDate = formatKoreanDateTime(startedAt, { dateStyle: "short" });
  const endDate = formatKoreanDateTime(endedAt, { dateStyle: "short" });
  const startTime = formatKoreanDateTime(startedAt, { timeStyle: "short" });
  const endTime = formatKoreanDateTime(endedAt, { timeStyle: "short" });
  return startDate === endDate
    ? `${startDate} ${startTime}–${endTime}`
    : `${startDate} ${startTime}–${endDate} ${endTime}`;
}

const UNKNOWN_WORK_NAME = "작업명 확인 불가";

/** 분석 관측 후보 한 줄: 작업명 + 실제 촬영 구간 + 제출 revision. epoch ID는 붙이지 않는다. */
export function observationChoiceLabel(
  option: AnalysisObservationOption,
  workName: string | null,
): string {
  const interval = formatCaptureInterval(option.captureStartedAt, option.captureEndedAt);
  return `${workName ?? UNKNOWN_WORK_NAME} · ${interval} · 제출 revision ${option.selector.revision}`;
}

function findDuplicates(values: readonly string[]): Set<string> {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) duplicates.add(value);
    else seen.add(value);
  }
  return duplicates;
}

/**
 * 후보 목록 전체의 표시 라벨. 작업명·구간·revision이 모두 같은 후보가 둘 이상이면
 * 해당 후보에만 원문 관측 epoch ID 전체를 덧붙여 구분한다. 같은 epoch이 다른
 * selector에 재사용돼 그래도 겹치면, 그 후보에만 정확한 작업 지시 ID·제출 참조·
 * revision 전체를 한 번 더 덧붙인다. 어떤 경우에도 후보를 조용히 합치지 않는다.
 */
export function observationChoiceLabels(
  options: readonly AnalysisObservationOption[],
  names: WorkOrderNameMap | null | undefined,
): string[] {
  const base = options.map((option) =>
    observationChoiceLabel(option, resolveWorkName(option.selector.workOrderId, names)),
  );
  const collisions = findDuplicates(base);
  if (collisions.size === 0) return base;
  const withEpoch = options.map((option, index) =>
    collisions.has(base[index]!)
      ? `${base[index]} · 관측 epoch ${option.observationEpochId}`
      : base[index]!,
  );
  const residual = findDuplicates(withEpoch);
  if (residual.size === 0) return withEpoch;
  return options.map((option, index) => {
    const labeled = withEpoch[index]!;
    if (!residual.has(labeled)) return labeled;
    const selector = option.selector;
    return `${labeled} · 작업 ${selector.workOrderId} · 제출 ${selector.submissionRef} · revision ${selector.revision}`;
  });
}

/** 자산 목록의 촬영 구간. 신고값이 비어 있으면 비어 있다고 말한다. */
export function formatAssetCaptureWindow(
  startedAt: string | null,
  endedAt: string | null,
): string {
  if (startedAt && endedAt) return formatCaptureInterval(startedAt, endedAt);
  if (startedAt) return `${formatKoreanDateTime(startedAt, { dateStyle: "medium", timeStyle: "short" })} (종료 미기재)`;
  if (endedAt) return `${formatKoreanDateTime(endedAt, { dateStyle: "medium", timeStyle: "short" })} (시작 미기재)`;
  return "촬영 구간 미기재";
}

/** 자산 목록·상세의 사람용 맥락 한 줄: 작업명 + 구역명 + 촬영 구간 + 버전. */
export function assetContextLine(parts: {
  workName: string | null;
  areaName: string;
  captureWindow: string;
  revision: number;
}): string {
  return `${parts.workName ?? UNKNOWN_WORK_NAME} · ${parts.areaName} · ${parts.captureWindow} · 제출 revision ${parts.revision}`;
}

/**
 * 같은 파일명이 한 페이지에 여러 건이면 제목에 revision을 붙여 구분한다.
 * 그래도 같은 항목(동일 파일명·revision)은 상세의 자산 참조 전체로 가른다.
 */
export function assetHeadline(fileName: string, revision: number, nameIsDuplicated: boolean): string {
  return nameIsDuplicated ? `${fileName} · revision ${revision}` : fileName;
}

export function duplicateFileNames(fileNames: readonly string[]): Set<string> {
  return findDuplicates(fileNames);
}

const SPATIAL_ASSET_KIND_LABELS: Record<string, string> = {
  point_cloud: "포인트 클라우드",
  camera_poses: "카메라 자세 자료",
  ortho: "정사영상",
  dsm: "DSM 지표면 모델",
  dtm: "DTM 지면 모델",
  mesh: "3D Mesh",
  tiles_3d: "3D 타일",
  report: "처리 보고서",
};

/** 카탈로그 종류의 사람용 이름. 모르는 종류는 원문 그대로 두어 추정하지 않는다. */
export function spatialAssetKindLabel(kind: string): string {
  return Object.prototype.hasOwnProperty.call(SPATIAL_ASSET_KIND_LABELS, kind)
    ? SPATIAL_ASSET_KIND_LABELS[kind]!
    : kind;
}

export interface RequestRowPresentation {
  /** 행의 주 링크 문구: 구역명 · 요청 시각 · 원본 파일 정보. */
  title: string;
  /** 원본 파일 한 줄. 카탈로그를 못 읽으면 그 사실만 말한다. */
  sourceLine: string;
  /** 카탈로그 정보를 썼는지. false면 삭제·부재를 뜻하지 않는다. */
  hasCatalogInfo: boolean;
}

/**
 * 공간 데이터 요청 행의 사람용 표시. 충돌은 분 단위 시각이 아니라 전체 의미 제목
 * (구역명·요청 시각·원본 파일명)으로만 판정한다. 호출자는 초 단위 시각
 * (timeStyle medium)을 넘겨 분만 같은 요청을 먼저 가르고, 그래도 제목이 겹치는
 * 행에만 원문 요청 ID 전체를 덧붙인다. 카탈로그 조회 실패는 "확인 불가"로만
 * 말하고 원본 삭제로 해석하지 않는다. 전체 ID는 항상 펼침 영역에도 남는다.
 */
export function requestRowPresentations(
  items: readonly { jobId: string; createdAt: string; assetRef: string }[],
  formatCreatedAt: (iso: string) => string,
  assets: Record<string, CatalogAssetInfo> | null | undefined,
  areaName: string,
): RequestRowPresentation[] {
  const baseTitles = items.map((item) => {
    const info = assets?.[item.assetRef] ?? null;
    const file = info ? info.fileName : "원본 파일명 확인 불가";
    return `${areaName} · ${formatCreatedAt(item.createdAt)} 요청 · ${file}`;
  });
  const collisions = findDuplicates(baseTitles);
  return items.map((item, index) => {
    const info = assets?.[item.assetRef] ?? null;
    const hasCatalogInfo = info !== null;
    const sourceLine = info
      ? `원본 · ${spatialAssetKindLabel(info.kind)}`
      : "원본 파일명 확인 불가 · 현재 조회한 카탈로그에서 확인되지 않음 · 삭제를 뜻하지 않음";
    const titleCore = baseTitles[index]!;
    const title = collisions.has(titleCore) ? `${titleCore} · 요청 ${item.jobId}` : titleCore;
    return { title, sourceLine, hasCatalogInfo };
  });
}
