import type { Tone } from "@/lib/core-api/labels";
import type { AcquisitionProgressView, AcquisitionRunStage } from "@/lib/core-api/types";

const GROUPS = ["준비", "발급·전달", "계약", "원본", "분석", "검토"] as const;

const STAGE_GROUP: Record<AcquisitionRunStage, number> = {
  WAITING_READINESS: 1,
  WAITING_PLAN: 1,
  MISSION_ISSUED: 2,
  WAYLINE_PENDING: 2,
  CONTRACT_PENDING: 3,
  READY_FOR_FLIGHT: 3,
  MEDIA_SYNCING: 4,
  MEDIA_VERIFYING: 4,
  PROCESSING: 5,
  REVIEW_READY: 6,
  BLOCKED: 1,
};

const STAGE_LABEL: Record<AcquisitionRunStage, string> = {
  WAITING_READINESS: "장비 준비 확인 중",
  WAITING_PLAN: "비행 계획 필요",
  MISSION_ISSUED: "비행 임무 발급 완료",
  WAYLINE_PENDING: "경로 전달 중",
  CONTRACT_PENDING: "계약 활성화 대기",
  READY_FOR_FLIGHT: "비행 준비 완료",
  MEDIA_SYNCING: "원본 동기화 중",
  MEDIA_VERIFYING: "원본 검증 중",
  PROCESSING: "공간 분석 중",
  REVIEW_READY: "결과 검토 가능",
  BLOCKED: "확인 필요",
};

export interface AcquisitionProgressPresentation {
  label: string;
  detail: string;
  tone: Tone;
  currentGroup: number;
  groups: readonly string[];
  gatewayReceiptSummary: string;
  activeContractOfflineWarning: string | null;
}

export function presentAcquisitionProgress(
  progress: AcquisitionProgressView | null,
): AcquisitionProgressPresentation {
  if (!progress) {
    return {
      label: "진행상태 확인 불가",
      detail: "Core에서 취득 진행상태를 읽지 못했습니다. 준비 완료로 판단하지 마세요.",
      tone: "warning",
      currentGroup: 1,
      groups: GROUPS,
      gatewayReceiptSummary: "이번 비행 임무의 전달 기록을 확인할 수 없음",
      activeContractOfflineWarning: null,
    };
  }
  const succeeded = progress.gateway.succeededCapabilities.length;
  const activeContractOffline =
    progress.contractActivation.state === "ACTIVATED" && !progress.readiness.readyForMissionIssue;
  return {
    label: STAGE_LABEL[progress.stage],
    detail: progress.detail,
    tone: stageTone(progress.stage),
    currentGroup: STAGE_GROUP[progress.stage],
    groups: GROUPS,
    gatewayReceiptSummary: `이번 비행 임무 전달 기록 ${succeeded}/5`,
    activeContractOfflineWarning: activeContractOffline
      ? "RC 연결 경고가 있지만 이미 활성화된 계약은 유효합니다. 인터넷 단절만으로 비행을 자동 중단하지 않습니다."
      : null,
  };
}

function stageTone(stage: AcquisitionRunStage): Tone {
  if (stage === "REVIEW_READY" || stage === "READY_FOR_FLIGHT") return "positive";
  if (stage === "BLOCKED" || stage === "WAITING_READINESS") return "warning";
  if (stage === "WAITING_PLAN") return "caution";
  return "progress";
}
