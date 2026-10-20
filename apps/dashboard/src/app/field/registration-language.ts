/**
 * 현장 등록 흐름의 실무 표시 문구. 업무 규칙은 `@/lib/operator-language`와
 * 같은 것을 쓰고, 현장 흐름에서만 필요한 판정·선택 문구를 덧붙인다.
 *
 * - revision은 등록된 제출의 순서(등록 버전)일 뿐 촬영 횟수·이벤트 횟수가 아니다.
 *   '등록 버전 N'으로만 부른다.
 * - Core·epoch·digest·footprint는 첫 화면 언어로 쓰지 않는다. 원문 값은
 *   '파일 정보'·'처리 상세' 펼침에 그대로 둔다.
 * - 이 모듈은 순수 함수만 두며 "server-only" Core 클라이언트를 import하지
 *   않는다. Client Component에서도 그대로 쓸 수 있다.
 */

export { registrationVersionLabel as formatRegistrationVersion } from "@/lib/operator-language";
export { dataKindLabel } from "@/lib/operator-language";
export { TECH_TERM_LABELS } from "@/lib/operator-language";
import { dataKindLabel, registrationVersionLabel } from "@/lib/operator-language";

export type ArtifactLike = {
  kind?: string | null;
  fileName?: string | null;
};

const SHORT_KIND_LABELS: Record<string, string> = {
  ortho: "정사영상",
  dsm: "DSM",
};

/** 좁은 선택 목록·단추용 짧은 종류 이름. 모르는 종류는 공용 이름 그대로 쓴다. */
export function shortArtifactKindLabel(kind: string | null | undefined): string {
  if (!kind) return "산출물";
  return SHORT_KIND_LABELS[kind] ?? dataKindLabel(kind);
}

/** '정사영상 + DSM' — 등록된 산출물 묶음의 짧은 종류 표시. */
export function describeArtifactKinds(artifacts: readonly ArtifactLike[] | undefined): string {
  const kinds = new Set(
    (artifacts ?? [])
      .map((item) => item.kind ?? "")
      .filter((kind) => kind === "ortho" || kind === "dsm"),
  );
  if (kinds.has("ortho") && kinds.has("dsm")) return "정사영상 + DSM";
  if (kinds.has("ortho")) return "정사영상";
  if (kinds.has("dsm")) return "DSM";
  return "산출물";
}

export function submissionStateLabel(state: "REGISTERED" | "SEALED"): string {
  return state === "SEALED" ? "파일 제출 완료" : "파일 제출 준비 중";
}

/**
 * 구역 스냅샷의 버전. 제출 revision('등록 버전')과 다른 계열이므로
 * '등록 버전'으로 부르지 않는다. 결과·근거 버전도 같은 이유로 별도 이름을 쓴다.
 */
export function zoneVersionLabel(revision: number): string {
  return `구역 버전 ${revision}`;
}

/** '정사영상 + DSM · 등록 버전 N · 파일 제출 완료' — 종류 우선, 버전·상태 뒤. 파일명은 별도 줄에 둔다. */
export function formatSealedTargetLabel(
  revision: number,
  artifacts: readonly ArtifactLike[] | undefined,
): string {
  return `${describeArtifactKinds(artifacts)} · ${registrationVersionLabel(revision)} · 파일 제출 완료`;
}

export interface SealedTargetIdentity {
  submissionRef: string;
  revision: number;
  artifacts: readonly ArtifactLike[] | undefined;
}

/**
 * 같은 작업에 제출 참조가 여럿 있을 수 있어(새 시도는 새 참조를 받고
 * revision은 1부터 다시 센다) 겹치는 보기 라벨이 생길 수 있다. 조용히
 * 합치지 않고, 겹치는 라벨에만 전체 제출 식별자를 덧붙여 고른다.
 * 파일명이 다르면 라벨이 이미 다르므로 충돌이 아니다.
 */
export function sealedTargetSubjectKey(identity: Pick<SealedTargetIdentity, "submissionRef" | "revision">): string {
  return `${identity.submissionRef}:${identity.revision}`;
}

function sealedTargetVisibleBase(identity: Pick<SealedTargetIdentity, "revision" | "artifacts">): string {
  const fileNames = (identity.artifacts ?? []).map((artifact) => artifact.fileName ?? "").join(",");
  return `${describeArtifactKinds(identity.artifacts)}|${identity.revision}|${fileNames}`;
}

/** 겹치는 보기 라벨을 가진 대상의 전체 식별 키 모음. 겹치지 않으면 비어 있다. */
export function duplicateSealedTargetKeys(targets: readonly SealedTargetIdentity[]): Set<string> {
  const counts = new Map<string, number>();
  for (const target of targets) {
    const base = sealedTargetVisibleBase(target);
    counts.set(base, (counts.get(base) ?? 0) + 1);
  }
  const duplicates = new Set<string>();
  for (const target of targets) {
    if ((counts.get(sealedTargetVisibleBase(target)) ?? 0) > 1) {
      duplicates.add(sealedTargetSubjectKey(target));
    }
  }
  return duplicates;
}

const USE_LABELS: Record<string, string> = {
  DISPLAY: "화면 표시",
  HEIGHT: "높이 확인",
  VISUAL_COMPARISON: "눈으로 비교",
  RELATIVE_VOLUME: "변화 분석(두 시점 비교)",
  SINGLE_VOLUME: "한 시점 측정",
};

const VERDICT_LABELS: Record<string, string> = {
  ELIGIBLE: "사용 가능",
  RESTRICTED: "제한적 사용",
  BLOCKED: "사용 불가",
  VALIDATED: "사용 가능",
};

export function decisionUseLabel(use: string): string {
  return USE_LABELS[use] ?? use;
}

export function decisionVerdictLabel(verdict: string): string {
  return VERDICT_LABELS[verdict] ?? verdict;
}

/**
 * V3 미상 접수 표시. 발행자가 신고한 달력 날짜를 그대로 옮긴다 — Date 파싱·
 * 시간대 변환·자정 시각 추정을 하지 않는다. 날짜가 확인된 기록에는
 * '촬영시각없음'을 쓰지 않고 '촬영 시각 미상'을 쓴다.
 */
export function formatPublisherCalendarDate(value: string | null | undefined): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!Number.isSafeInteger(year) || !Number.isSafeInteger(month) || !Number.isSafeInteger(day)) return null;
  if (year < 1) return null;
  const probe = new Date(0);
  probe.setUTCFullYear(year, month - 1, day);
  probe.setUTCHours(0, 0, 0, 0);
  if (probe.getUTCFullYear() !== year || probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) return null;
  return `${year}. ${month}. ${day}.`;
}

export type ReconstructionProducerView = {
  producerKnowledge?: string | null;
  softwareName?: string | null;
  softwareVersion?: string | null;
  sourceNote?: string | null;
};

export type ReconstructionCaptureView = {
  captureBasis?: string | null;
  captureStartedAt?: string | null;
  captureEndedAt?: string | null;
  captureDate?: string | null;
};

/** V3 producerKnowledge가 없으면 V1 기록으로 보고 기존 표시를 그대로 둔다. */
export function describeProducerLine(producer: ReconstructionProducerView | null | undefined): string | null {
  if (!producer) return null;
  if (producer.producerKnowledge === undefined || producer.producerKnowledge === null) {
    return producer.softwareName ? `재구성 소프트웨어: ${producer.softwareName}${producer.softwareVersion ? ` ${producer.softwareVersion}` : ""}` : null;
  }
  if (producer.producerKnowledge === "UNKNOWN") return "재구성 소프트웨어: 미상 (등록 시 확인되지 않음)";
  if (producer.producerKnowledge === "PARTIAL") {
    return producer.softwareName ? `재구성 소프트웨어: ${producer.softwareName} (버전 미상)` : "재구성 소프트웨어: 미상 (등록 시 확인되지 않음)";
  }
  return producer.softwareName && producer.softwareVersion
    ? `재구성 소프트웨어: ${producer.softwareName} ${producer.softwareVersion}`
    : "재구성 소프트웨어: 미상 (등록 시 확인되지 않음)";
}

/**
 * V3 captureBasis 표시. 작업지시 제목 같은 다른 출처를 촬영 진실로 해석하지
 * 않는다 — 입력 신고(inputDeclaration)에 있을 때만 표시하고, V1 기록(판정
 * 없음)에는 아무것도 덧붙이지 않는다.
 */
export function describeCaptureLine(
  input: (ReconstructionCaptureView & { originalRetentionLocus?: string | null; originalRetentionDetail?: string | null }) | null | undefined,
  formatInterval: (startedAt: string, endedAt: string) => string,
): string | null {
  if (!input || input.captureBasis === undefined || input.captureBasis === null) return null;
  if (input.captureBasis === "DATE_ONLY") {
    const date = formatPublisherCalendarDate(input.captureDate);
    return date ? `촬영 시점: ${date} · 촬영 시각 미상 (발행자 신고 날짜)` : "촬영 시점: 날짜 확인 필요";
  }
  if (input.captureBasis === "UNKNOWN") return "촬영 시점: 미상 (등록 시 확인되지 않음)";
  if (input.captureStartedAt && input.captureEndedAt) return `촬영 시점: ${formatInterval(input.captureStartedAt, input.captureEndedAt)}`;
  return "촬영 시점: 확인 필요";
}

const RETENTION_LOCUS_LABEL: Record<string, string> = {
  customer_workstation: "고객 작업 장비",
  upstream_source: "공개 출처(신고)",
  unknown: "미상",
};

/** 원본 보관 위치 신고. 공개 출처라고 해서 원본 보유를 단정하지 않는다. */
export function describeRetentionLine(input: { originalRetentionLocus?: string | null; originalRetentionDetail?: string | null } | null | undefined): string | null {
  if (!input || input.originalRetentionLocus === undefined || input.originalRetentionLocus === null) return null;
  const locus = RETENTION_LOCUS_LABEL[input.originalRetentionLocus] ?? "확인 필요";
  return `원본 보관: ${locus}${input.originalRetentionDetail ? ` · ${input.originalRetentionDetail}` : ""} (원본 사진은 요청하지 않습니다)`;
}
