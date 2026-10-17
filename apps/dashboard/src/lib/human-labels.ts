import type { AnalysisObservationOption } from "@/lib/core-api/analysis";
import { formatKoreanDateTime } from "@/lib/datetime";
import {
  capturePeriodTitle,
  compactFileName,
  dataKindLabel,
  isSupportedDataKind,
  registrationVersionLabel,
} from "@/lib/operator-language";

/**
 * 사람용 표시 이름 헬퍼 — 표현만 담당한다.
 *
 * - 작업 지시 이름·자산 파일명은 Core가 이미 허가한 목록 응답에서만 가져온다.
 *   이름이 없다고 해서 존재 여부·권한·적합성을 추정하지 않으며, 진단은 Core와
 *   typed blocker가 소유한다.
 * - 업무 제목(종류 + 실제 촬영 구간)은 `@/lib/operator-language`와 같은
 *   규칙을 쓴다. 원본 파일명·정확한 revision·기계 식별자는 펼침에 원문 그대로
 *   남긴다.
 * - 기술 식별자(workOrderId, epoch ID, assetRef, jobId 등)는 절대 추측·합성하지
 *   않는다. 충돌할 때만 원문 전체를 그대로 덧붙이고, 항상 펼침(details) 영역에
 *   전체 값을 남긴다.
 * - revision은 등록 버전일 뿐 촬영 회수·원본 여부·주기 번호가 아니다.
 *   '등록 버전 N'으로만 부른다.
 * - 날짜는 촬영 구간·신고 시각·분석 기록 생성·계산 시각을 서로 바꿔 부르지
 *   않으며, revision을 주기 번호처럼 쓰지 않는다.
 * - 이 모듈은 순수 함수만 두며 "server-only" Core 클라이언트를 import하지
 *   않는다. Client Component에서도 그대로 쓸 수 있다.
 */

export type WorkOrderNameMap = Record<string, string>;

export interface CatalogAssetInfo {
  fileName: string;
  kind: string;
  captureStartedAt?: string | null;
  captureEndedAt?: string | null;
}

/** 허가된 작업 지시 목록에서 사람용 이름을 찾는다. 없으면 null — 추정하지 않는다. */
export function resolveWorkName(
  workOrderId: string | null | undefined,
  names: WorkOrderNameMap | null | undefined,
): string | null {
  if (!workOrderId || !names || !Object.prototype.hasOwnProperty.call(names, workOrderId)) return null;
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

/**
 * 분석 관측 후보 한 줄: 작업명 + 실제 촬영 구간(연도 포함). 등록 버전은
 * 기본 제목에 두지 않는다 — 분 단위 제목이 겹치는 후보에만 초 단위 구간을,
 * 그래도 겹치면 observationChoiceLabels가 등록 버전·관측 기록·정확한
 * selector를 덧붙인다. epoch ID는 붙이지 않는다.
 */
export function observationChoiceLabel(
  option: AnalysisObservationOption,
  workName: string | null,
  labelOptions?: { seconds?: boolean },
): string {
  return `${workName ?? UNKNOWN_WORK_NAME} · ${capturePeriodTitle(option.captureStartedAt, option.captureEndedAt, labelOptions)}`;
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
 * 후보 목록 전체의 표시 라벨. 작업명·구간이 같은 후보가 둘 이상이면 먼저
 * 실제 초 단위 촬영 구간을 보여주고, 그래도 겹치면 실제 등록 버전을,
 * 그래도 겹치면 관측 기록 ID 전체를, 같은 관측 기록이 다른 selector에
 * 재사용돼 또 겹치면 정확한 작업 지시 ID·제출 참조·등록 버전 전체를 한 번
 * 더 덧붙인다. 어떤 경우에도 후보를 조용히 합치지 않는다.
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
  const withSeconds = options.map((option, index) =>
    collisions.has(base[index]!)
      ? observationChoiceLabel(option, resolveWorkName(option.selector.workOrderId, names), { seconds: true })
      : base[index]!,
  );
  const secondResidual = findDuplicates(withSeconds);
  const withVersion = options.map((option, index) => {
    if (!collisions.has(base[index]!)) return base[index]!;
    if (!secondResidual.has(withSeconds[index]!)) return withSeconds[index]!;
    return `${base[index]} · ${registrationVersionLabel(option.selector.revision)}`;
  });
  const residual = findDuplicates(withVersion);
  if (residual.size === 0) return withVersion;
  const withEpoch = options.map((option, index) =>
    residual.has(withVersion[index]!)
      ? `${withVersion[index]} · 관측 기록 ${option.observationEpochId}`
      : withVersion[index]!,
  );
  const epochResidual = findDuplicates(withEpoch);
  if (epochResidual.size === 0) return withEpoch;
  return options.map((option, index) => {
    const labeled = withEpoch[index]!;
    if (!epochResidual.has(labeled)) return labeled;
    const selector = option.selector;
    return `${labeled} · 작업 ${selector.workOrderId} · 제출 ${selector.submissionRef} · ${registrationVersionLabel(selector.revision)}`;
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

/** 자산 목록·상세의 사람용 맥락 한 줄: 작업명 + 구역명 + 촬영 구간 + 등록 버전. */
export function assetContextLine(parts: {
  workName: string | null;
  areaName: string;
  captureWindow: string;
  revision: number;
}): string {
  return `${parts.workName ?? UNKNOWN_WORK_NAME} · ${parts.areaName} · ${parts.captureWindow} · ${registrationVersionLabel(parts.revision)}`;
}

/**
 * 레이아웃용 짧은 파일명. 원문 전체는 '파일 정보' 펼침에 그대로 둔다.
 * 같은 파일명이 한 페이지에 여러 건이면 등록 버전을 덧붙여 구분한다.
 */
export function assetHeadline(fileName: string, revision: number, nameIsDuplicated: boolean): string {
  const short = compactFileName(fileName);
  return nameIsDuplicated ? `${short} · ${registrationVersionLabel(revision)}` : short;
}

export function duplicateFileNames(fileNames: readonly string[]): Set<string> {
  return findDuplicates(fileNames);
}

/** 카탈로그 종류의 사람용 이름. 모르는 종류는 '자료 종류 확인 필요'로만 말한다. */
export function spatialAssetKindLabel(kind: string): string {
  return dataKindLabel(kind);
}

export interface RequestRowPresentation {
  /** 행의 주 링크 문구: 구역명 · 요청 시각 · 원본 종류와 촬영 구간. */
  title: string;
  /** 원본 파일 한 줄. 카탈로그를 못 읽으면 그 사실만 말한다. */
  sourceLine: string;
  /** 카탈로그 정보를 썼는지. false면 삭제·부재를 뜻하지 않는다. */
  hasCatalogInfo: boolean;
  /** 계약에 없는 원본 종류의 원문. 첫 화면에는 쓰지 않고 펼침이 맡는다. */
  rawSourceKind: string | null;
}

/**
 * 공간 데이터 요청 행의 사람용 표시. 제목은 구역명·요청 시각·원본 종류·
 * 촬영 구간으로 만들고, 원본 파일명은 바로 아래 줄에 둔다. 충돌은 전체
 * 의미 제목으로만 판정한다. 호출자는 초 단위 시각(timeStyle medium)을
 * 넘겨 분만 같은 요청을 먼저 가르고, 그래도 제목이 겹치는 행에만 원문
 * 요청 ID 전체를 덧붙인다. 카탈로그 조회 실패는 "원본 정보 확인 불가"로만
 * 말하고 원본 삭제로 해석하지 않는다. 전체 ID는 항상 펼침 영역에도 남는다.
 */
export function requestRowPresentations(
  items: readonly { jobId: string; createdAt: string; assetRef: string }[],
  formatCreatedAt: (iso: string) => string,
  assets: Record<string, CatalogAssetInfo> | null | undefined,
  areaName: string,
): RequestRowPresentation[] {
  const sourceTitleFor = (assetRef: string): string => {
    const info = assets?.[assetRef] ?? null;
    if (!info) return "원본 정보 확인 불가";
    return `${dataKindLabel(info.kind)} · ${capturePeriodTitle(info.captureStartedAt ?? null, info.captureEndedAt ?? null)}`;
  };
  const baseTitles = items.map((item) =>
    `${areaName} · ${formatCreatedAt(item.createdAt)} 요청 · ${sourceTitleFor(item.assetRef)}`,
  );
  const collisions = findDuplicates(baseTitles);
  return items.map((item, index) => {
    const info = assets?.[item.assetRef] ?? null;
    const hasCatalogInfo = info !== null;
    const sourceLine = info
      ? `원본 파일 · ${info.fileName}`
      : "원본 정보 확인 불가 · 현재 조회한 카탈로그에서 확인되지 않음 · 삭제를 뜻하지 않음";
    const titleCore = baseTitles[index]!;
    const title = collisions.has(titleCore) ? `${titleCore} · 요청 ${item.jobId}` : titleCore;
    const rawSourceKind = info && !isSupportedDataKind(info.kind) ? info.kind : null;
    return { title, sourceLine, hasCatalogInfo, rawSourceKind };
  });
}
