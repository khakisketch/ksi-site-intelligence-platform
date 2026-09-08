import { civilBlockerGuidance } from "@/lib/comparison-submit";
import type { Tone } from "@/lib/core-api/labels";
import type { CivilReadinessView } from "@/lib/core-api/types";

export interface CivilReadinessPresentation {
  label: string;
  detail: string;
  tone: Tone;
  pairLabel: string;
  designSurfaceLabel: string;
}

/**
 * Translate the durable projection without recomputing its decision.
 *
 * A compatible pair remains a candidate: this function must never turn it
 * into a field-acceptance, survey-accuracy, or comparison-result claim.
 */
export function presentCivilReadiness(
  readiness: CivilReadinessView | null,
): CivilReadinessPresentation {
  if (readiness === null) {
    return {
      label: "토목 준비 상태 확인 불가",
      detail: "처리·설계 원장을 확인하지 못했습니다. 비교 가능으로 추정하지 않습니다.",
      tone: "warning",
      pairLabel: "두 시점 판정 확인 불가",
      designSurfaceLabel: "설계 기준면 확인 불가",
    };
  }

  const designSurfaceLabel = designSurfaceSummary(readiness.designSurface.status);
  switch (readiness.status) {
    case "SYSTEM_UNAVAILABLE":
      return {
        label: "토목 준비 상태 확인 불가",
        detail: readiness.pair.detail,
        tone: "warning",
        pairLabel: "두 시점 판정 확인 불가",
        designSurfaceLabel,
      };
    case "FIRST_EPOCH_REQUIRED":
      return {
        label: "첫 조사 시점 필요",
        detail: readiness.pair.detail,
        tone: "neutral",
        pairLabel: "완료된 처리 시점 없음",
        designSurfaceLabel,
      };
    case "SECOND_EPOCH_REQUIRED":
      return {
        label: "두 번째 조사 시점 필요",
        detail: readiness.pair.detail,
        tone: "caution",
        pairLabel: "완료된 처리 시점 1개",
        designSurfaceLabel,
      };
    case "PAIR_BLOCKED": {
      const guidance = civilBlockerGuidance(readiness.pair);
      return {
        label: "두 시점 비교 차단",
        detail: guidance?.message ?? readiness.pair.detail,
        tone: "warning",
        pairLabel: guidance ? `차단 · ${guidance.code}` : "두 시점 비교 차단",
        designSurfaceLabel,
      };
    }
    case "PAIR_COMPATIBLE":
      return compatiblePresentation(readiness, designSurfaceLabel);
  }
}

function compatiblePresentation(
  readiness: CivilReadinessView,
  designSurfaceLabel: string,
): CivilReadinessPresentation {
  switch (readiness.designSurface.status) {
    case "VERIFIED_AVAILABLE":
      return {
        label: "두 시점 비교 후보 준비",
        detail:
          "두 최신 처리 시점은 같은 정량 비교 기준을 통과했습니다. 실제 비교 요청은 선택한 " +
          "입력을 Core가 다시 검증한 뒤에만 생성됩니다.",
        tone: "positive",
        pairLabel: "두 최신 시점 호환 후보",
        designSurfaceLabel,
      };
    case "NOT_REGISTERED":
      return {
        label: "두 시점 확인 · 설계면 필요",
        detail:
          "두 최신 처리 시점은 호환 후보입니다. 설계 대비 절토·성토 잔량을 계산하려면 " +
          "검증 가능한 설계 기준면을 등록하세요.",
        tone: "caution",
        pairLabel: "두 최신 시점 호환 후보",
        designSurfaceLabel,
      };
    case "VERIFICATION_REQUIRED":
      return {
        label: "두 시점 확인 · 설계면 검증 대기",
        detail:
          "두 최신 처리 시점은 호환 후보입니다. 봉인만 된 설계 기준면은 정량 비교 입력이 " +
          "될 수 없습니다.",
        tone: "caution",
        pairLabel: "두 최신 시점 호환 후보",
        designSurfaceLabel,
      };
    case "SYSTEM_UNAVAILABLE":
      return {
        label: "두 시점 확인 · 설계면 확인 불가",
        detail:
          "두 최신 처리 시점은 호환 후보이지만 설계 기준면 원장을 확인할 수 없습니다. " +
          "설계 대비 수량은 시작하지 않습니다.",
        tone: "warning",
        pairLabel: "두 최신 시점 호환 후보",
        designSurfaceLabel,
      };
  }
}

function designSurfaceSummary(status: CivilReadinessView["designSurface"]["status"]): string {
  switch (status) {
    case "NOT_REGISTERED":
      return "등록된 설계 기준면 없음";
    case "VERIFICATION_REQUIRED":
      return "설계 기준면 검증 대기";
    case "VERIFIED_AVAILABLE":
      return "검증된 설계 기준면 있음";
    case "SYSTEM_UNAVAILABLE":
      return "설계 기준면 확인 불가";
  }
}
