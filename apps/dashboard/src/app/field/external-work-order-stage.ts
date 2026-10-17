import type { Tone } from "@/lib/core-api/labels";
import type { ExternalResultSummaryView } from "@/lib/core-api/types";

export type ExternalStage = "CLOSED" | "REGISTER" | "SEAL" | "DECIDE" | "REVIEW" | "PROPOSE" | "DONE";

export type ExternalStageInput = {
  planningOnly: boolean;
  workflowClosed: boolean;
  sealedSubmissionCount: number;
  registeredSubmissionCount: number;
  /** Latest external result of THIS work order; the caller passes null for other orders. */
  latestResult: ExternalResultSummaryView | null;
};

export type ExternalStagePresentation = {
  stage: ExternalStage;
  label: string;
  detail: string;
  tone: Tone;
  anchor: string;
};

/**
 * Derives the operator's next action for an external-reconstruction work order
 * from retained facts only. It never infers processing, flight or device state.
 */
export function deriveExternalWorkOrderStage(input: ExternalStageInput): ExternalStagePresentation {
  if (input.workflowClosed) {
    return {
      stage: "CLOSED",
      label: "업무 종료",
      detail: "이 작업은 종료되었습니다. 새 산출물 등록과 비교·검토 요청은 시작할 수 없으며, 이미 등록한 파일과 결과는 계속 확인할 수 있습니다.",
      tone: "neutral",
      anchor: "external-submissions",
    };
  }
  const result = input.latestResult;
  if (result && result.approvedProposalCount > 0) {
    return {
      stage: "DONE",
      label: "후속 관측 계획됨",
      detail: "검토와 재관측 승인이 끝났습니다. 승인된 후속 작업에서 다음 산출물을 등록합니다.",
      tone: "positive",
      anchor: "external-volume",
    };
  }
  if (result && result.reviewRef) {
    return {
      stage: "PROPOSE",
      label: "재관측 필요 여부 결정",
      detail: "결과 검토가 기록되었습니다. 부족한 구역이 있으면 재관측 제안을 만들고 승인하세요.",
      tone: "warning",
      anchor: "external-volume",
    };
  }
  if (result) {
    return {
      stage: "REVIEW",
      label: "결과와 근거 검토",
      detail: "상대 물량 결과가 준비되었습니다. 수치·범위·불확도를 확인하고 검토를 기록하세요.",
      tone: "warning",
      anchor: "external-volume",
    };
  }
  if (input.sealedSubmissionCount > 0) {
    return {
      stage: "DECIDE",
      label: "검사와 비교 판정",
      detail: "제출한 자료의 파일 검사 결과를 확인하고, 기준 자료와 비교를 준비하세요.",
      tone: "progress",
      anchor: "external-submissions",
    };
  }
  if (input.registeredSubmissionCount > 0) {
    return {
      stage: "SEAL",
      label: "업로드와 봉인 완료",
      detail: "등록한 산출물의 파일 업로드를 마치고 봉인해야 검사가 시작됩니다.",
      tone: "progress",
      anchor: "external-submissions",
    };
  }
  return input.planningOnly
    ? {
        stage: "REGISTER",
        label: "승인된 재관측 산출물 등록",
        detail: "승인된 재관측에 필요한 산출물을 등록하세요. 이 작업에서는 비행이나 장비를 실행하지 않습니다.",
        tone: "progress",
        anchor: "external-submissions",
      }
    : {
        stage: "REGISTER",
        label: "외부 산출물 등록 준비",
        detail: "촬영 시각과 재구성 정보를 확인한 뒤 산출물을 등록하세요. 비행이나 장비 실행은 이 작업에서 시작하지 않습니다.",
        tone: "progress",
        anchor: "external-submissions",
      };
}
