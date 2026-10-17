import type { CoreApiError } from "@/lib/core-api/client";

/**
 * 팀 목록 읽기 실패의 화면 안내 — 원인 분류만 담당한다.
 *
 * - 401/403/404/5xx를 중립 원인으로 구분한다. 404에서 구성 누락을 단정하지
 *   않으며, 권한·조직 정책은 완화하지 않는다(서버가 최종 판정, INV-060).
 * - 재시도 버튼은 일시 장애(408/429/5xx)에만 준다. 권한·세션·부재에는 작업
 *   복귀 경로를 준다.
 */

export interface TeamReadErrorPresentation {
  message: string;
  detail?: string;
  retryable: boolean;
  retryAfterSeconds?: number;
  tone: "crit" | "high" | "idle";
  action: { label: string; href: string };
}

const BACK_TO_FIELD = { label: "작업으로 돌아가기", href: "/field" } as const;

export function describeTeamReadError(error: CoreApiError): TeamReadErrorPresentation {
  if (error.status === 401) {
    return {
      message: "세션이 만료되었습니다. 다시 로그인한 뒤 팀 관리를 다시 여세요.",
      retryable: false,
      tone: "high",
      action: { ...BACK_TO_FIELD },
    };
  }
  if (error.status === 403) {
    return {
      message: "팀원 정보를 조회할 권한이 없습니다. 권한 있는 조직 담당자에게 확인을 요청하세요.",
      detail: "이 안내는 현재 계정의 조회 가능 여부만 말합니다.",
      retryable: false,
      tone: "high",
      action: { ...BACK_TO_FIELD },
    };
  }
  if (error.status === 404) {
    return {
      message: "요청한 팀원 목록을 확인할 수 없습니다. 목록이 비었다는 뜻은 아닙니다.",
      detail: "원인을 단정하지 않습니다. 다시 시도하거나 작업 목록에서 이어가세요.",
      retryable: true,
      tone: "idle",
      action: { ...BACK_TO_FIELD },
    };
  }
  if (error.status === 408 || error.status === 429 || error.status >= 500) {
    return {
      message: "팀원 정보를 불러오지 못했습니다. 잠시 후 다시 시도하세요.",
      retryable: true,
      ...(error.retryAfterSeconds !== undefined ? { retryAfterSeconds: error.retryAfterSeconds } : {}),
      tone: "crit",
      action: { ...BACK_TO_FIELD },
    };
  }
  return {
    message: "팀원 정보를 불러오지 못했습니다. 다시 시도하거나 작업 목록에서 이어가세요.",
    retryable: true,
    tone: "crit",
    action: { ...BACK_TO_FIELD },
  };
}
