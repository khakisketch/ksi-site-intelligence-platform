import type {
  ProcessingResourcePolicyListView,
  ProcessingResourcePolicyView,
} from "@/lib/core-api/types";

/** Client로 넘기는 최소 정책 상태. 원장·테넌트·원본 정보는 포함하지 않는다. */
export type ProcessingResourcePolicyState =
  | { kind: "ready"; policy: ProcessingResourcePolicyView }
  | { kind: "unavailable"; reason: "POLICY_READ_FAILED" | "CURRENT_POLICY_UNDECLARED" | "CURRENT_POLICY_UNKNOWN" };

/**
 * Core가 지정한 currentPolicyId만 쓴다. 목록 첫 번째를 임의로 고르면 신규 정책을
 * 추가한 배포에서 발급 기준이 화면과 달라질 수 있으므로, 선언 누락도 막는다.
 */
export function resolveCurrentProcessingResourcePolicy(
  response: ProcessingResourcePolicyListView,
): ProcessingResourcePolicyState {
  const currentPolicyId = response.currentPolicyId;
  if (!currentPolicyId) return { kind: "unavailable", reason: "CURRENT_POLICY_UNDECLARED" };
  const policy = response.policies.find((candidate) => candidate.resourcePolicyId === currentPolicyId);
  if (!policy) return { kind: "unavailable", reason: "CURRENT_POLICY_UNKNOWN" };
  return { kind: "ready", policy };
}

export const PROCESSING_RESOURCE_POLICY_UNAVAILABLE_MESSAGE =
  "처리 자원 정책을 확인할 수 없어 새 재구성 발급을 시작하지 않았습니다. 잠시 후 화면을 새로고침하세요.";

export function formatProcessingResourceBytes(bytes: number): string {
  const gib = 1024 ** 3;
  const tib = 1024 ** 4;
  if (bytes >= tib) return `${formatNumber(bytes / tib, 1)} TiB`;
  if (bytes >= gib) return `${formatNumber(bytes / gib, 1)} GiB`;
  return `${formatNumber(bytes / (1024 ** 2), 0)} MiB`;
}

export function formatProcessingResourceMegapixels(megapixels: number): string {
  return `${formatNumber(megapixels, 0)} MP`;
}

function formatNumber(value: number, maximumFractionDigits: number): string {
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits }).format(value);
}

/** Core의 안정된 한도 코드 → 개인정보 없는 다음 행동. 알 수 없는 코드는 숨기지 않는다. */
export function processingResourceLimitNextAction(reasonCode: string | null | undefined): string {
  switch (reasonCode) {
    case "SOURCE_MEDIA_FILES_LIMIT_EXCEEDED":
      return "사진 묶음을 촬영 회차 또는 구역으로 나눠 새 임무에서 다시 봉인하세요.";
    case "SOURCE_MEDIA_FILE_BYTES_LIMIT_EXCEEDED":
      return "원본 한 장의 크기가 상한을 넘었습니다. 카메라 출력 설정과 원본 파일을 확인하세요.";
    case "SOURCE_BUNDLE_BYTES_LIMIT_EXCEEDED":
      return "총 원본 용량이 상한을 넘었습니다. 촬영 회차 또는 구역을 나눠 새 임무에서 다시 봉인하세요.";
    case "TOTAL_MEGAPIXELS_LIMIT_EXCEEDED":
      return "총 촬영 화소량이 상한을 넘었습니다. 촬영 회차 또는 구역을 나눠 새 임무에서 다시 봉인하세요.";
    case "ACTIVE_PROCESSING_JOBS_PER_ORGANIZATION_LIMIT_EXCEEDED":
      return "조직의 처리 대기열이 상한에 도달했습니다. 진행 중인 작업이 끝난 뒤 다시 시도하세요.";
    default:
      return "정책 한도에 맞는 봉인 사진 묶음인지 확인한 뒤 다시 시도하세요.";
  }
}
