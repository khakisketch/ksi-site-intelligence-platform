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
