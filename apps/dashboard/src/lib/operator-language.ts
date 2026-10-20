import { formatKoreanDate, formatKoreanDateTime } from "@/lib/datetime";

/**
 * 현장 작업어(Operator language) — 표현만 담당한다.
 *
 * - 이 모듈은 순수 함수만 두며 "server-only" Core 클라이언트를 import하지
 *   않는다. Client Component에서도 그대로 쓸 수 있다.
 * - 제목은 언제나 업무 의미(자료 종류 + 실제 촬영 구간, 분석 기록 생성일)를
 *   먼저 둔다. 연도를 생략하지 않는다. 연도가 다르면 같은 월·일·시각도
 *   다른 기록이다. 원본 파일명·정확한 revision·기계 ID·digest는
 *   '파일 정보'·'처리 상세' 펼침에 원문 그대로 남긴다. 파일명에서 의미를
 *   추측해 다시 이름 붙이지 않는다.
 * - revision은 등록 버전일 뿐 촬영 회수·원본 여부·주기 번호가 아니다.
 *   '등록 버전 N'으로만 부르고 '회차·촬영회수·원본·최초촬영'으로 부르지 않는다.
 * - 날짜는 촬영 구간·신고 시각·분석 기록 생성·계산 시각을 서로 바꿔 부르지
 *   않는다. revision을 주기 번호처럼 쓰지 않는다.
 * - Core·epoch·selector·digest·footprint는 첫 화면 언어로 쓰지 않는다.
 *   TECH_TERM_LABELS의 사람용 이름을 쓰고, 원문 값은 펼침에 그대로 둔다.
 * - 모르는 종류·모르는 구간은 있는 그대로 말한다. 조용히 합치거나
 *   그럴듯한 지리·이름·정확도를 지어내지 않는다.
 */

export function registrationVersionLabel(revision: number): string {
  return `등록 버전 ${revision}`;
}

export type SubmissionLifecycleState = "UNSEALED" | "SEALED" | "SUPERSEDED";

/**
 * Core 등록 상태의 사람용 이름. SEALED는 봉인된 제출(바이트 제출 완료)이지
 * 검사 통과·정확도 검증·분석 적합성이 아니다. 그 판단은 검사·평가·검토가
 * 따로 말한다. 계약에 없는 상태는 첫 화면에 코드를 그대로 두지 않고
 * '상태 확인 필요'로만 말하며, 원문은 '파일 정보'·'처리 상세' 펼침이 맡는다.
 */
export function assetLifecycleLabel(state: string): string {
  if (state === "SEALED") return "파일 제출 완료";
  if (state === "SUPERSEDED") return "이전 등록 자료";
  if (state === "UNSEALED") return "파일 제출 미완료";
  return "상태 확인 필요";
}

const DATA_KIND_LABELS: Record<string, string> = {
  point_cloud: "포인트 클라우드",
  camera_poses: "카메라 자세 자료",
  ortho: "정사영상",
  dsm: "지표면 높이 자료(DSM)",
  dtm: "지형 높이 자료(DTM)",
  mesh: "3D Mesh",
  tiles_3d: "3D 타일",
  report: "처리 보고서",
};

/** 카탈로그 종류의 사람용 이름. 모르는 종류는 첫 화면에 코드를 그대로 두지 않는다. */
export function dataKindLabel(kind: string): string {
  return Object.prototype.hasOwnProperty.call(DATA_KIND_LABELS, kind)
    ? DATA_KIND_LABELS[kind]!
    : "자료 종류 확인 필요";
}

/** 계약된 자료 종류인지. 아니면 첫 화면은 중립 문구, 원문은 펼침이 맡는다. */
export function isSupportedDataKind(kind: string): kind is keyof typeof DATA_KIND_LABELS {
  return Object.prototype.hasOwnProperty.call(DATA_KIND_LABELS, kind);
}

/** 계약된 등록 상태인지. 아니면 첫 화면은 중립 문구, 원문은 펼침이 맡는다. */
export function isSupportedLifecycleState(state: string): state is SubmissionLifecycleState {
  return state === "UNSEALED" || state === "SEALED" || state === "SUPERSEDED";
}

/**
 * '2026. 10. 9. 14:00' — 제목용 서울 시각. 연도를 생략하지 않는다.
 * 파싱 불가면 null.
 */
function fullDateTime(iso: string, seconds: boolean): string | null {
  const rendered = formatKoreanDateTime(
    iso,
    seconds ? { dateStyle: "medium", timeStyle: "medium" } : { dateStyle: "medium", timeStyle: "short" },
  );
  if (rendered === iso) return null;
  return /^\d+\. \d+\. \d+\. \d{1,2}:\d{2}(:\d{2})?$/.test(rendered) ? rendered : null;
}

/** 같은 날 구간의 끝 시각만. 파싱 불가면 null. */
function shortClock(iso: string, seconds: boolean): string | null {
  const rendered = formatKoreanDateTime(iso, seconds ? { timeStyle: "medium" } : { timeStyle: "short" });
  if (rendered === iso) return null;
  return seconds
    ? (/^\d{1,2}:\d{2}:\d{2}$/.test(rendered) ? rendered : null)
    : (/^\d{1,2}:\d{2}$/.test(rendered) ? rendered : null);
}

/**
 * 실제 촬영 구간의 제목용 한 줄. '2026. 10. 9. 14:00–14:30 촬영'.
 * 연도를 생략하지 않는다. 한쪽만 있거나 파싱이 안 되면 있는 그대로 말한다.
 * seconds가 true면 초 단위까지 표시한다. 분 단위 제목이 겹치는 선택지를
 * 가를 때만 쓴다.
 */
export function capturePeriodTitle(
  startedAt: string | null,
  endedAt: string | null,
  options?: { seconds?: boolean },
): string {
  const seconds = options?.seconds ?? false;
  if (startedAt && endedAt) {
    const start = fullDateTime(startedAt, seconds);
    const end = fullDateTime(endedAt, seconds);
    if (!start || !end) return "촬영 구간 확인 불가";
    if (formatKoreanDate(startedAt) === formatKoreanDate(endedAt)) {
      const endTime = shortClock(endedAt, seconds);
      return endTime ? `${start}–${endTime} 촬영` : `${start} – ${end} 촬영`;
    }
    return `${start} – ${end} 촬영`;
  }
  if (startedAt || endedAt) {
    const known = fullDateTime((startedAt ?? endedAt)!, seconds);
    if (!known) return "촬영 구간 확인 불가";
    return `${known} 촬영 (${startedAt ? "종료 미기재" : "시작 미기재"})`;
  }
  return "촬영 구간 미기재";
}

/** 자산 목록·상세·Site 타임라인이 공유하는 제목 입력. 파일명은 충돌 때만 식별용으로 원문 그대로 덧붙이며, 촬영 사실로는 해석하지 않는다. */
export interface AssetBusinessTitleInput {
  kind: string;
  revision: number;
  declared: {
    fileName: string;
    captureStartedAt: string | null;
    captureEndedAt: string | null;
  };
}

/**
 * 자산의 업무 제목: '정사영상 · 2026. 10. 9. 14:00–14:30 촬영'.
 * 종류 + 실제 촬영 구간(연도 포함)이 앞에 오고, 파일명·등록 버전은 기본
 * 제목에 두지 않는다. 원본 파일명·정확한 revision·기계 ID는 '파일 정보'·
 * '처리 상세' 펼침이 원문 그대로 맡는다.
 */
export function assetBusinessTitle(
  asset: AssetBusinessTitleInput,
  options?: { seconds?: boolean },
): string {
  return `${dataKindLabel(asset.kind)} · ${capturePeriodTitle(asset.declared.captureStartedAt, asset.declared.captureEndedAt, options)}`;
}

export interface AssetBusinessTitleItem extends AssetBusinessTitleInput {
  assetRef: string;
}

function findDuplicateValues(values: readonly string[]): Set<string> {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) duplicates.add(value);
    else seen.add(value);
  }
  return duplicates;
}

/**
 * 충돌 안전한 자산 제목표. 분 단위 기본 제목이 겹치는 항목에만 먼저 실제
 * 초 단위 촬영 구간을 보여주고, 그래도 겹치는 항목에만 실제 등록 버전을
 * 덧붙이며, 그래도 겹치면 신고된 파일명 원문을 덧붙이고, 파일명까지 겹칠
 * 때만 짧은 결정적 식별자(자산 참조 끝 8자리)를 덧붙인다. 파일명은
 * 식별용으로만 그대로 옮기며 촬영 사실로 해석하지 않는다. 전체 자산 참조는
 * '파일 정보' 펼침과 목록·상세 링크에 그대로 남는다.
 * 어떤 경우에도 항목을 조용히 합치지 않으며, assetRef 키는 모두 남긴다.
 */
export function assetBusinessTitles(
  assets: readonly AssetBusinessTitleItem[],
): Map<string, string> {
  const labeled = new Map<string, string>();
  if (assets.length === 0) return labeled;
  const base = assets.map((asset) => assetBusinessTitle(asset));
  const collisions = findDuplicateValues(base);
  if (collisions.size === 0) {
    assets.forEach((asset, index) => labeled.set(asset.assetRef, base[index]!));
    return labeled;
  }
  const withSeconds = assets.map((asset, index) =>
    collisions.has(base[index]!) ? assetBusinessTitle(asset, { seconds: true }) : base[index]!,
  );
  const secondResidual = findDuplicateValues(withSeconds);
  const withVersion = assets.map((asset, index) => {
    if (!collisions.has(base[index]!)) return base[index]!;
    if (!secondResidual.has(withSeconds[index]!)) return withSeconds[index]!;
    return `${base[index]} · ${registrationVersionLabel(asset.revision)}`;
  });
  const versionResidual = findDuplicateValues(withVersion);
  const withFileName = assets.map((asset, index) => {
    if (!versionResidual.has(withVersion[index]!)) return withVersion[index]!;
    const fileName = asset.declared.fileName;
    return fileName.length > 0 ? `${withVersion[index]} · ${fileName}` : withVersion[index]!;
  });
  const fileResidual = findDuplicateValues(withFileName);
  const withBriefId = assets.map((asset, index) => {
    const title = withFileName[index]!;
    return fileResidual.has(title) ? `${title} · #${asset.assetRef.slice(-8)}` : title;
  });
  const briefResidual = findDuplicateValues(withBriefId);
  assets.forEach((asset, index) => {
    // 짧은 참조도 겹칠 수 있으므로, 그때만 완전한 식별자로 구분한다.
    labeled.set(
      asset.assetRef,
      briefResidual.has(withBriefId[index]!)
        ? `${withFileName[index]} · ${asset.assetRef}`
        : withBriefId[index]!,
    );
  });
  return labeled;
}

/** '10월 15일 분석 결과' — createdAt은 분석 기록 생성일(촬영이 아님). 파싱 불가면 '분석 결과'. */
export function analysisResultTitle(createdAt: string): string {
  const rendered = formatKoreanDateTime(createdAt, { dateStyle: "medium" });
  if (rendered === createdAt) return "분석 결과";
  const match = /^(\d+)\. (\d+)\. (\d+)\./.exec(rendered);
  if (!match) return "분석 결과";
  return `${match[2]}월 ${match[3]}일 분석 결과`;
}

/** '10월 14일 데이터 요청 기록' — createdAt은 요청 기록 생성일(촬영이 아님). */
export function dataRequestTitle(createdAt: string): string {
  const rendered = formatKoreanDateTime(createdAt, { dateStyle: "medium" });
  if (rendered === createdAt) return "데이터 요청 기록";
  const match = /^(\d+)\. (\d+)\. (\d+)\./.exec(rendered);
  if (!match) return "데이터 요청 기록";
  return `${match[2]}월 ${match[3]}일 데이터 요청 기록`;
}

const MAX_DISPLAY_FILENAME = 48;

/**
 * 레이아웃용 짧은 파일명. 의미를 추측해 고치지 않으며, 원문 전체는
 * '파일 정보' 펼침에 그대로 둔다. 유니코드·긴 이름도 깨지지 않게 줄인다.
 */
export function compactFileName(fileName: string, maxLength = MAX_DISPLAY_FILENAME): string {
  const chars = [...fileName];
  if (chars.length <= maxLength) return fileName;
  const dot = fileName.lastIndexOf(".");
  const ext = dot > 0 ? fileName.slice(dot) : "";
  const extChars = [...ext];
  if (dot <= 0 || extChars.length === 0 || extChars.length > 12) {
    return `${chars.slice(0, maxLength - 1).join("")}…`;
  }
  const headLength = maxLength - extChars.length - 1;
  if (headLength <= 0) return `${chars.slice(0, maxLength - 1).join("")}…`;
  return `${chars.slice(0, headLength).join("")}…${ext}`;
}

/**
 * 기계 용어의 사람용 이름. 원문 코드·ID·digest 값은 번역하지 않고
 * 펼침에 그대로 둔다.
 */
export const TECH_TERM_LABELS = {
  /** observation epoch ID */
  epochRecord: "관측 기록",
  /** analysis selector (workOrderId·submissionRef·revision) */
  selectionInfo: "선택 자료 정보",
  /** sha256/manifest digest */
  fileDigest: "파일 확인값(해시)",
  /** footprint WKT */
  coverageFootprint: "파일 포함 범위",
  /** Core 계산·실행 환경 */
  analysisSystem: "분석 시스템",
  /** captureStartedAt/EndedAt */
  captureRecord: "촬영 기록",
} as const;
