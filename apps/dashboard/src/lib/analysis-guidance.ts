import type { AnalysisEvidenceItem, AnalysisObservationOption } from "@/lib/core-api/analysis";
import { formatKoreanDateTime } from "@/lib/datetime";
import { dataKindLabel } from "@/lib/operator-language";

export type AnalysisGuidanceDestination = "work-areas" | "spatial-assets";

export type AnalysisIssueGuidance = {
  label: string;
  owner: string;
  nextStep: string;
  destination?: AnalysisGuidanceDestination;
};

const ISSUE_GUIDANCE: Record<string, AnalysisIssueGuidance> = {
  REASSESSMENT_REQUIRED: {
    label: "현장 적합성 재평가 필요",
    owner: "관측·평가 담당자",
    nextStep: "현재 적용 가능한 관측·평가 근거를 담당자가 다시 확인해야 합니다. 원인을 확인하기 전에는 같은 분석을 반복 요청하지 마세요.",
  },
  ASSESSMENT_RECOVERY_REQUIRED: {
    label: "분석 평가 기록 확인 필요",
    owner: "분석 운영 담당자",
    nextStep: "평가 기록을 현재 조회할 수 없습니다. 이 분석 ID와 Core 설명을 운영 담당자에게 전달해 기록 복구 여부를 확인하세요. 중복 요청으로 대체하지 마세요.",
  },
  CALCULATION_IDENTITY_MISMATCH: {
    label: "분석 계산 기록 연결 확인 필요",
    owner: "분석 운영 담당자",
    nextStep: "계산과 분석 요청의 기록 연결을 확인해야 합니다. 제공된 근거와 기술 정보를 운영 담당자에게 전달하고, 원인 확인 전 재요청하지 마세요.",
  },
  CHECKPOINT_EVIDENCE_REJECTED: {
    label: "검사점 근거가 확인되지 않음",
    owner: "해당 근거를 등록한 담당자",
    nextStep: "근거를 등록한 담당자가 해당 파일과 연결된 관측 자료를 함께 확인해야 합니다. 거부된 기록을 통과로 간주하거나 다른 파일의 digest로 바꾸지 마세요.",
  },
  CHECKPOINT_EVIDENCE_PENDING: {
    label: "검사점 근거 확인 대기",
    owner: "근거 검증 담당자",
    nextStep: "Core의 검증이 아직 끝나지 않았습니다. 검증 담당자가 처리 상태를 확인한 뒤 분석 상세를 다시 조회하세요. 같은 요청을 중복 생성할 필요는 없습니다.",
  },
  EVIDENCE_CONTEXT_UNAVAILABLE: {
    label: "근거 검증 상태를 확인할 수 없음",
    owner: "근거 검증 담당자",
    nextStep: "현재 근거의 검증 맥락을 확인할 수 없습니다. 담당자가 근거 등록·검증 기록을 확인하기 전까지 승인이나 적합성을 추정하지 마세요.",
  },
  CHECKPOINT_EVIDENCE_ABSENT: {
    label: "독립 검사점 근거 없음",
    owner: "정확도 평가가 필요한 경우 현장 측정 담당자",
    nextStep: "독립 검사점 평가 근거가 기록되지 않았습니다. 이 사실만으로 모든 사용이 차단되는 것은 아니며, 정확도 근거가 필요한 업무라면 별도 평가 절차를 담당자와 확인하세요.",
  },
  CHECKPOINT_NOT_INDEPENDENT: {
    label: "독립성이 확인되지 않은 검사점 근거",
    owner: "정확도 평가 담당자",
    nextStep: "현재 근거는 독립 평가 근거로 확인되지 않았습니다. 평가 담당자가 근거의 출처와 독립성을 확인해야 하며, 등록 사실만으로 정확도를 주장하지 마세요.",
  },
  CHECKPOINT_EVIDENCE_VALIDATED: {
    label: "검사점 근거 검증됨",
    owner: "결과를 사용하는 담당자",
    nextStep: "Core가 해당 근거 기록을 검증했습니다. 이것만으로 물량 정확도·측량·정산 승인을 뜻하지는 않으므로 결과의 제한 사항도 함께 확인하세요.",
  },
  WORK_AREA_UNAVAILABLE: {
    label: "작업구역을 사용할 수 없음",
    owner: "현장 작업구역 담당자",
    nextStep: "선택한 작업구역의 현재 상태와 현장 소속을 확인해야 합니다. 작업구역 담당자가 유효한 구역인지 확인한 뒤 다시 선택하세요.",
    destination: "work-areas",
  },
  ESSENTIAL_INPUT_UNAVAILABLE: {
    label: "필수 관측 자료를 확인할 수 없음",
    owner: "외부 관측 자료 담당자",
    nextStep: "선택한 제출본에서 분석에 필요한 자료를 확인할 수 없습니다. 담당자가 해당 제출 revision과 KSI 검사 상태를 확인하세요.",
    destination: "spatial-assets",
  },
  RECONSTRUCTION_NOT_SEALED: {
    label: "등록된 재구성 결과 확인 필요",
    owner: "외부 관측 자료 담당자",
    nextStep: "선택한 재구성 결과가 분석 입력으로 확인되지 않습니다. 담당자가 정확한 제출 revision의 등록·검사 상태를 확인하세요.",
    destination: "spatial-assets",
  },
  SUBMISSION_NOT_SEALED: {
    label: "제출 revision 확인 필요",
    owner: "외부 관측 자료 담당자",
    nextStep: "선택한 제출 revision이 분석 입력으로 확인되지 않습니다. 담당자가 해당 revision의 등록 상태를 확인하세요. 다른 revision이나 원본으로 추정하지 마세요.",
    destination: "spatial-assets",
  },
  NO_COMMON_ARTIFACT_FAMILY: {
    label: "두 관측에 공통 분석 자료가 없음",
    owner: "외부 관측 자료 담당자",
    nextStep: "두 선택 자료에 요청된 분석 입력 종류가 함께 있는지 확인하세요. 상대 물량 분석에는 지원되는 DSM 자료가 필요하며, 정사영상 등록만으로 대체되지 않습니다.",
    destination: "spatial-assets",
  },
  ANALYSIS_NOT_READY: {
    label: "관측 자료의 분석 준비가 확인되지 않음",
    owner: "외부 관측 자료 담당자",
    nextStep: "Core가 필요한 분석 준비 조건을 확인하지 못했습니다. 선택한 revision의 검사·자료 상태를 담당자가 확인하고 부족한 근거를 보완해야 합니다.",
    destination: "spatial-assets",
  },
  PROCESSING_PROFILE_UNKNOWN: {
    label: "자료 처리 프로필을 확인할 수 없음",
    owner: "재구성 자료 제공자",
    nextStep: "자료의 처리 프로필이 확인되지 않습니다. 제공자가 실제 처리 이력을 확인하고 정확한 출처 정보를 제출해야 합니다. 프로필을 추측하거나 재명명하지 마세요.",
    destination: "spatial-assets",
  },
  PROCESSING_PROFILE_MISMATCH: {
    label: "두 관측의 처리 프로필이 다름",
    owner: "재구성 자료 제공자",
    nextStep: "두 관측이 호환되는 처리 프로필을 사용했는지 확인하세요. 서로 다르면 검증된 호환 근거가 있는 자료 조합을 담당자와 선택해야 합니다.",
    destination: "spatial-assets",
  },
  SOURCE_LINEAGE_GAP: {
    label: "자료 출처 계보가 불완전함",
    owner: "재구성 자료 제공자",
    nextStep: "파생 자료와 원본 사이의 출처 연결을 확인할 수 없습니다. 제공자가 정확한 계보 정보를 보완해야 하며 파일명만으로 출처를 추정하지 마세요.",
    destination: "spatial-assets",
  },
  HORIZONTAL_CRS_UNAVAILABLE_OR_MISMATCH: {
    label: "수평 좌표 기준을 확인할 수 없거나 서로 다름",
    owner: "공간 자료 담당자",
    nextStep: "작업구역과 두 관측의 기록된 좌표 기준을 확인하세요. 기준을 UI에서 임의로 바꾸거나 좌표를 추정해 맞추지 마세요.",
    destination: "spatial-assets",
  },
  CRS_MISMATCH: {
    label: "관측 좌표 기준이 서로 다름",
    owner: "공간 자료 담당자",
    nextStep: "각 관측의 기록된 좌표 기준과 변환 근거를 확인하세요. 호환성이 확인될 때까지 수치 비교를 사용하지 마세요.",
    destination: "spatial-assets",
  },
  VERTICAL_REFERENCE_MISMATCH: {
    label: "높이 기준이 서로 다름",
    owner: "공간 자료 담당자",
    nextStep: "두 관측의 기록된 수직 기준과 단위를 담당자가 확인해야 합니다. 높이를 임의로 변환하거나 같은 기준으로 간주하지 마세요.",
    destination: "spatial-assets",
  },
  EMPTY_COMMON_VALID_COVERAGE: {
    label: "두 관측에서 함께 유효한 범위 없음",
    owner: "공간 자료 담당자",
    nextStep: "확인된 자료에는 두 시점이 함께 유효한 범위가 없습니다. 담당자가 실제 관측 범위와 작업구역을 확인하고 다른 기록된 조합이 있는지 검토하세요. 좌표를 추정해 옮기지 마세요.",
    destination: "spatial-assets",
  },
  INSUFFICIENT_COMMON_VALID_COVERAGE: {
    label: "공통 유효 범위가 분석 조건에 미달함",
    owner: "공간 자료 담당자",
    nextStep: "공통으로 유효한 범위가 현재 분석 조건을 충족하지 않습니다. 담당자가 자료와 작업구역을 검토한 뒤 다른 관측 조합을 확인하세요.",
    destination: "spatial-assets",
  },
  EPOCH_SUBJECT_NOT_DISTINCT: {
    label: "기준·현재 관측이 서로 다르지 않음",
    owner: "분석 요청자",
    nextStep: "기준과 현재에 서로 다른 관측 제출본을 선택하세요. 날짜가 달라도 같은 제출 revision이면 서로 다른 관측으로 볼 수 없습니다.",
  },
  CAPTURE_CHRONOLOGY_INVALID: {
    label: "촬영 시점 순서를 확인할 수 없음",
    owner: "외부 관측 자료 담당자",
    nextStep: "촬영 구간이 겹치거나 기준·현재 순서가 유효하지 않습니다. 제공자가 기록된 촬영 시각을 확인한 뒤, 겹치지 않는 실제 관측을 선택하세요.",
  },
  EPOCH_SITE_MISMATCH: {
    label: "관측이 같은 현장에 속하지 않음",
    owner: "현장·관측 자료 담당자",
    nextStep: "같은 현장에 등록된 관측 선택지를 사용하세요. 문제가 계속되면 자료의 Site 연결을 담당자가 확인해야 합니다.",
  },
  SUBJECT_OUT_OF_SCOPE: {
    label: "현재 권한 범위에서 관측을 확인할 수 없음",
    owner: "조직 관리자",
    nextStep: "인증 조직과 현장 권한 범위를 확인하세요. 권한이 없는 자료의 존재 여부를 추정하거나 다른 조직으로부터 전달받으려 하지 마세요.",
  },
  DESIGN_SURFACE_NOT_VERIFIED: {
    label: "설계면 검증이 확인되지 않음",
    owner: "설계 자료 담당자",
    nextStep: "설계면의 등록·검증 근거를 담당자가 확인해야 합니다. 검증 전에는 설계 대비 분석에 사용할 수 있다고 가정하지 마세요.",
    destination: "spatial-assets",
  },
  DESIGN_NORMALIZATION_MISMATCH: {
    label: "설계면 정규화 기준이 서로 다름",
    owner: "설계 자료 담당자",
    nextStep: "설계면 revision과 정규화 근거가 같은 기준인지 확인해야 합니다. 불일치를 숨기거나 기존 결과의 의미를 바꾸지 마세요.",
    destination: "spatial-assets",
  },
  EXECUTION_DEADLINE_EXPIRED: {
    label: "분석 실행 기한 만료",
    owner: "분석 운영 담당자",
    nextStep: "실행 가능 시간이 끝났습니다. 운영 담당자가 기록된 작업 상태를 확인한 뒤 재실행 가능 여부를 결정해야 합니다. 같은 요청을 자동으로 반복하지 마세요.",
  },
  EXECUTION_RETRY_EXHAUSTED: {
    label: "분석 실행 재시도 한도 도달",
    owner: "분석 운영 담당자",
    nextStep: "Core의 재시도 한도에 도달했습니다. 운영 담당자가 실패 기록을 확인한 뒤 다음 조치를 결정해야 합니다. 같은 요청을 계속 반복하지 마세요.",
  },
  ANALYSIS_EXECUTION_FAILED: {
    label: "분석 실행 실패",
    owner: "분석 운영 담당자와 자료 담당자",
    nextStep: "Core가 계산을 완료하지 못했습니다. 원문 실패 정보와 자료 상태를 담당자가 확인한 뒤 해결 여부를 판단하세요. 결과를 0으로 해석하거나 같은 요청을 바로 반복하지 마세요.",
  },
  PROVISIONAL_ACCURACY_UNVERIFIED: {
    label: "정확도 평가 미확인",
    owner: "결과를 사용하는 담당자",
    nextStep: "이 제한은 정확도 평가가 확인되지 않았다는 뜻입니다. 계산 결과만으로 정확도·측량·정산 승인을 주장하지 마세요.",
  },
  INSPECTION_LIMITED: {
    label: "자료 검사에 제한 있음",
    owner: "외부 관측 자료 담당자",
    nextStep: "자료 검사에서 확인되지 않은 조건이 있습니다. 해당 revision의 검사 결과와 제한 사항을 함께 확인하세요.",
    destination: "spatial-assets",
  },
};

const UNKNOWN_ISSUE: AnalysisIssueGuidance = {
  label: "세부 원인 확인 필요",
  owner: "자료 담당자 또는 조직 관리자",
  nextStep: "이 사유에 대한 화면 안내가 없습니다. 기술 코드·Core 설명·근거 참조를 담당자와 검토한 뒤 다음 조치를 정하세요. 원인을 확인하기 전에는 같은 분석을 반복 요청하지 마세요.",
};

export function getAnalysisIssueGuidance(code: string): AnalysisIssueGuidance {
  return Object.prototype.hasOwnProperty.call(ISSUE_GUIDANCE, code)
    ? ISSUE_GUIDANCE[code]!
    : UNKNOWN_ISSUE;
}

export function analysisObservationLabel(option: AnalysisObservationOption): string {
  const startDate = formatKoreanDateTime(option.captureStartedAt, { dateStyle: "short" });
  const endDate = formatKoreanDateTime(option.captureEndedAt, { dateStyle: "short" });
  const startTime = formatKoreanDateTime(option.captureStartedAt, { timeStyle: "short" });
  const endTime = formatKoreanDateTime(option.captureEndedAt, { timeStyle: "short" });
  const interval = startDate === endDate
    ? `${startDate} ${startTime}–${endTime}`
    : `${startDate} ${startTime}–${endDate} ${endTime}`;
  return `${interval} · 등록 버전 ${option.selector.revision} · ${option.observationEpochId}`;
}

export function analysisEvidenceKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    EPOCH_IDENTITY: "관측 식별",
    CALCULATION_IDENTITY: "분석 조건",
    EVALUATION: "독립 근거 평가",
    CHECKPOINT_FACT: "검사점 근거",
    AUTHORITY_REFERENCE: "분석 기준 기록",
    SOURCE_REFERENCE: "출처 연결",
    NUMERIC_RESULT: "수치 결과 기록",
    LIMITATION: "사용 제한",
  };
  return Object.prototype.hasOwnProperty.call(labels, kind) ? labels[kind]! : "추가 근거 기록";
}

export function analysisEvidenceSummary(item: AnalysisEvidenceItem): string {
  switch (item.kind) {
    case "EPOCH_IDENTITY": {
      const epoch = item.epoch === "BASELINE" ? "기준" : "현재";
      return `${epoch} 관측 · ${dataKindLabel(item.artifactId)}`;
    }
    case "CALCULATION_IDENTITY":
      return "고정 분석 조건";
    case "EVALUATION": {
      const outcome = item.outcome === "PASS" ? "통과" : item.outcome === "FAIL" ? "거부" : item.outcome === "UNASSESSED" ? "평가 전" : "확인 불가";
      return `${item.epoch === "BASELINE" ? "기준" : "현재"} 관측 평가 · ${outcome}`;
    }
    case "CHECKPOINT_FACT":
      return `검사점 근거 · ${item.coreVerdict === "VALIDATED" ? "검증됨" : "거부됨"}`;
    case "AUTHORITY_REFERENCE":
      return "분석 기준 기록 연결";
    case "SOURCE_REFERENCE":
      return "출처 기록 연결";
    case "NUMERIC_RESULT":
      return "계산 결과와 연결된 기록";
    case "LIMITATION":
      return `사용 제한 · ${getAnalysisIssueGuidance(String(item.code)).label}`;
    default:
      return "추가 근거 기록";
  }
}

export function analysisEvidenceReasonLine(code: string): string {
  return `${getAnalysisIssueGuidance(code).label} · Core 코드 ${code}`;
}
