import { CoreApiError } from "@/lib/core-api/client";

export type WorkAreaListFailure = {
  message: string;
  tone: "crit" | "high" | "idle";
  retryable: boolean;
  retryAfterSeconds?: number;
};

export function workAreaListFailure(error: unknown): WorkAreaListFailure {
  if (error instanceof CoreApiError) {
    if (error.status === 401) {
      return { message: "영역 목록을 보려면 다시 로그인한 뒤 확인하세요.", tone: "high", retryable: false };
    }
    if (error.status === 403) {
      return { message: "영역 목록을 조회할 권한이 없습니다. 프로젝트 담당자에게 조회 권한을 요청하세요.", tone: "high", retryable: false };
    }
    if (error.status === 404) {
      return { message: "현장 영역 목록을 확인할 수 없습니다. 프로젝트 담당자에게 접근 권한과 영역 설정을 확인해 달라고 요청하세요.", tone: "idle", retryable: false };
    }
    if (error.status >= 500) {
      return { message: "Core에서 영역 목록을 일시적으로 불러오지 못했습니다.", tone: "crit", retryable: true, retryAfterSeconds: error.retryAfterSeconds };
    }
    return { message: "영역 목록 요청을 처리할 수 없습니다. 현장 정보와 접근 권한을 확인하세요.", tone: "high", retryable: false };
  }
  return { message: "영역 목록을 불러오지 못했습니다. 다시 시도하세요.", tone: "crit", retryable: true };
}
