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
  analysisLabel: string;
  analysisDetail: string;
  analysisTone: Tone;
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
      analysisLabel: "분석 준비 확인 불가",
      analysisDetail: "분석 단계의 진행 여부를 확인하지 못했습니다.",
      analysisTone: "warning",
    };
  }
  const succeeded = progress.gateway.succeededCapabilities.length;
  const activeContractOffline =
    progress.contractActivation.state === "ACTIVATED" && !progress.readiness.readyForMissionIssue;
  const analysis = analysisSummary(progress);
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
    ...analysis,
  };
}

function stageTone(stage: AcquisitionRunStage): Tone {
  if (stage === "REVIEW_READY" || stage === "READY_FOR_FLIGHT") return "positive";
  if (stage === "BLOCKED" || stage === "WAITING_READINESS") return "warning";
  if (stage === "WAITING_PLAN") return "caution";
  return "progress";
}

function analysisSummary(
  progress: AcquisitionProgressView,
): Pick<AcquisitionProgressPresentation, "analysisLabel" | "analysisDetail" | "analysisTone"> {
  const readiness = progress.analysisReadiness;
  if (!readiness) {
    return {
      analysisLabel: "분석 준비 확인 불가",
      analysisDetail: "Core의 evidence-derived Analysis Readiness를 읽지 못했습니다.",
      analysisTone: "warning",
    };
  }

  const summary = ANALYSIS_READINESS_PRESENTATION[readiness.status];
  return {
    analysisLabel: summary.label,
    analysisDetail: readiness.detail,
    analysisTone: summary.tone,
  };
}

const ANALYSIS_READINESS_PRESENTATION: Record<
  NonNullable<AcquisitionProgressView["analysisReadiness"]>["status"],
  { label: string; tone: Tone }
> = {
  EVIDENCE_NOT_ASSEMBLED: { label: "분석 준비 확인 불가", tone: "warning" },
  WAITING_MISSION: { label: "비행 임무 대기", tone: "caution" },
  WAITING_COVERAGE: { label: "범위 증거 대기", tone: "caution" },
  COVERAGE_GAP: { label: "범위 충족 필요", tone: "warning" },
  WAITING_CAPTURE_QUALITY: { label: "촬영 품질 보고 대기", tone: "caution" },
  CAPTURE_QUALITY_GAP: { label: "촬영 품질 보완 필요", tone: "warning" },
  WAITING_MEDIA: { label: "원본 증거 대기", tone: "caution" },
  INTEGRITY_GAP: { label: "원본 무결성 확인 필요", tone: "warning" },
  CAPTURE_TIME_INCOMPLETE: { label: "촬영시각 확인 필요", tone: "warning" },
  TEMPORAL_POLICY_UNDECLARED: { label: "촬영 시간 기준 미선언", tone: "warning" },
  TEMPORAL_COHERENCE_GAP: { label: "촬영 시간 범위 초과", tone: "warning" },
  WAITING_PROCESSING: { label: "분석 처리 대기", tone: "caution" },
  PROCESSING_FAILED: { label: "분석 처리 실패", tone: "warning" },
  READY: { label: "분석 준비 완료", tone: "positive" },
};
