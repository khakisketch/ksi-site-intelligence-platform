import type { ObservationWorkOrderExecutionMode, ObservationWorkOrderStatus } from "@/lib/core-api/types";
import type { Tone } from "@/lib/core-api/labels";

export type WorkOrderPrimaryAction =
  | "APPROVE"
  | "APPROVE_REOBSERVATION"
  | "OPEN_RESULTS"
  | "REFRESH"
  | "NONE";

export interface WorkOrderPresentation {
  step: 1 | 2 | 3 | 4 | 5;
  label: string;
  detail: string;
  tone: Tone;
  action: WorkOrderPrimaryAction;
  actionLabel: string | null;
}

export function presentWorkOrder(
  status: ObservationWorkOrderStatus,
  executionMode: ObservationWorkOrderExecutionMode | null = null,
): WorkOrderPresentation {
  if (status === "APPROVED" && executionMode === "EXTERNAL_RECONSTRUCTION") {
    return {
      step: 2,
      label: "자료 등록·검사 확인",
      detail: "관측 작업이 승인되었습니다. 제출된 자료와 검사 상태는 작업을 열어 확인하세요. 승인만으로 자료 등록이나 분석 완료를 뜻하지 않으며 비행이나 장비 실행을 시작하지 않습니다.",
      tone: "progress",
      action: "REFRESH",
      actionLabel: "등록 상태 확인",
    };
  }
  switch (status) {
    case "DRAFT":
    case "AWAITING_APPROVAL":
      return {
        step: 1,
        label: "승인 대기",
        detail: "범위와 작업 목적을 확인하면 자동 전달 준비가 시작됩니다.",
        tone: "warning",
        action: "APPROVE",
        actionLabel: "작업 승인",
      };
    case "APPROVED":
    case "DISPATCHED":
      return {
        step: 2,
        label: status === "APPROVED" ? "비행 계획 준비" : "기체로 전달됨",
        detail:
          status === "APPROVED"
            ? "장비 준비를 확인한 뒤 WorkOrder 정보가 채워진 비행 계획을 사람이 검토합니다."
            : "경로와 서명 계약 전달 사실이 확인됐습니다. 파일을 직접 옮길 필요가 없습니다.",
        tone: status === "APPROVED" ? "progress" : "positive",
        action: "REFRESH",
        actionLabel: "상태 새로고침",
      };
    case "START_REPORTED":
    case "MEDIA_RECEIVING":
      return {
        step: 3,
        label: status === "START_REPORTED" ? "촬영 중" : "사진 회수 중",
        detail: "기체와 KSI가 수집·전송을 진행합니다. 현장에서는 안전 운용에 집중하세요.",
        tone: "progress",
        action: "REFRESH",
        actionLabel: "상태 새로고침",
      };
    case "PROCESSING":
      return {
        step: 4,
        label: "분석 중",
        detail: "공간모델과 시점 간 변화·상대 물량을 계산하고 있습니다.",
        tone: "progress",
        action: "REFRESH",
        actionLabel: "상태 새로고침",
      };
    case "REVIEW_READY":
    case "COMPLETED":
      return {
        step: 5,
        label: status === "COMPLETED" ? "완료" : "결과 준비",
        detail: "근거와 정확도 범위를 확인하고 필요한 내용을 질문할 수 있습니다.",
        tone: "positive",
        action: "OPEN_RESULTS",
        actionLabel: "결과와 근거 보기",
      };
    case "REOBSERVATION_PENDING":
      return {
        step: 5,
        label: "재관측 승인 대기",
        detail: "부족한 근거와 추가 촬영 범위를 확인한 뒤 사람이 승인합니다.",
        tone: "warning",
        action: "APPROVE_REOBSERVATION",
        actionLabel: "재관측 승인",
      };
    case "BLOCKED":
      return {
        step: 4,
        label: "확인 필요",
        detail: "자동 처리가 멈췄습니다. 사유를 확인하고 지원 또는 복구 경로를 사용하세요.",
        tone: "warning",
        action: "REFRESH",
        actionLabel: "다시 확인",
      };
    case "CANCELLED":
      return {
        step: 1,
        label: "취소됨",
        detail: "이 작업은 실행되지 않습니다.",
        tone: "neutral",
        action: "NONE",
        actionLabel: null,
      };
  }
}
