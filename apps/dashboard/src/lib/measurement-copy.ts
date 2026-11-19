/** 단면 화면의 사람용 문구. Core 사유 코드를 업무 말로 바꾼다. 모르는 코드는 일반 문구로 접는다. */
import type { ProfileAvailability } from "@/lib/core-api/measurement-types";

const FAILURE_TEXT: Record<string, string> = {
  LINE_OUTSIDE_SURFACE: "이 선이 등록된 범위에 닿지 않았습니다.",
  HEIGHT_NOT_ELIGIBLE: "높이를 읽어도 되는 자료로 확인되지 않았습니다.",
  SOURCE_NOT_MEASURED: "이 자료는 아직 파일 검사가 끝나지 않았습니다.",
  UNSUPPORTED_RASTER: "이 자료의 형식은 읽을 수 없습니다.",
  UNSUPPORTED_CRS: "이 자료의 좌표계는 읽을 수 없습니다.",
  SOURCE_BYTES_MISMATCH: "자료 파일 확인에 실패했습니다.",
  SOURCE_MEASUREMENTS_MISMATCH: "자료 파일 확인에 실패했습니다.",
  INTEGRITY_MISMATCH: "자료 파일 확인에 실패했습니다.",
  TOO_MANY_SAMPLES: "선이 너무 길어 읽을 수 없습니다.",
  LINE_TOO_LONG: "선이 너무 길어 읽을 수 없습니다.",
  WINDOW_TOO_LARGE: "읽을 범위가 한도를 넘었습니다.",
  SOURCE_BLOCK_TOO_LARGE: "이 자료는 한 번에 읽을 수 있는 크기를 넘었습니다.",
  RESOURCE_LIMIT_EXCEEDED: "처리 한도를 넘었습니다.",
  DEADLINE_EXCEEDED: "처리 시간이 지났습니다.",
  STORAGE_UNAVAILABLE: "자료 저장소에 연결하지 못했습니다.",
  SOURCE_UNAVAILABLE: "자료를 가져오지 못했습니다.",
};

export function failureText(reason: string | null): string {
  return (reason && FAILURE_TEXT[reason]) || "단면을 읽지 못했습니다.";
}

const AVAILABILITY_TEXT: Partial<Record<ProfileAvailability, string>> = {
  ACCESS_REVOKED: "접근 권한이 철회되어 표시하지 않습니다.",
  ACCESS_EXPIRED: "접근 기한이 지나 표시하지 않습니다.",
  RETENTION_EXPIRED: "보관 기한이 지나 표시하지 않습니다.",
  UNAVAILABLE: "지금은 표시할 수 없습니다.",
  NOT_READY: "아직 준비되지 않았습니다.",
};

/** 완료된 작업이어도 지금 읽을 수 없는 경우의 안내. 읽을 수 있으면 null이다. */
export function availabilityText(availability: ProfileAvailability): string | null {
  return availability === "AVAILABLE" ? null : (AVAILABILITY_TEXT[availability] ?? "지금은 표시할 수 없습니다.");
}

/** 결과를 읽는 요청이 실패했을 때의 안내. 수치를 대신 만들지 않고 이유만 말한다. */
export function resultErrorText(status: number): string {
  if (status === 403) return "접근 권한이 없어 표시하지 않습니다.";
  if (status === 404) return "결과를 찾을 수 없습니다.";
  if (status === 409) return "결과가 아직 준비되지 않았습니다.";
  if (status === 410) return "보관 기한이 지나 표시하지 않습니다.";
  return "일시적으로 불러오지 못했습니다.";
}

const SAVE_REFUSALS: Record<string, string> = {
  REVISION_CONFLICT: "다른 사람이 먼저 이 선을 고쳤습니다. 화면을 새로 열어 최신 선을 확인한 뒤 다시 고치세요.",
  WORK_AREA_NOT_ACTIVE: "보관된 작업구역에는 선을 저장할 수 없습니다.",
  TOO_MANY_FEATURES: "이 작업구역의 측정 선이 한도에 닿았습니다. 쓰지 않는 선이 있는지 담당자에게 확인하세요.",
  TOO_MANY_REVISIONS: "이 선의 고친 횟수가 한도에 닿았습니다. 새 선으로 저장하세요.",
  IDEMPOTENCY_CONFLICT: "같은 요청이 다른 내용으로 이미 처리되었습니다. 화면을 새로 연 뒤 다시 하세요.",
  UNKNOWN_FEATURE: "고치려는 선을 찾을 수 없습니다. 화면을 새로 열어 확인하세요.",
  UNKNOWN_WORK_AREA: "작업구역을 찾을 수 없거나 접근 권한이 없습니다.",
  INVALID: "선의 내용을 확인해 주세요.",
};

/** 측정 선 저장이 거부됐을 때의 사람용 문구. 모르는 코드는 상태로 접는다. */
export function saveLineErrorText(status: number, code: string | undefined): string {
  if (code && Object.prototype.hasOwnProperty.call(SAVE_REFUSALS, code)) return SAVE_REFUSALS[code]!;
  if (status === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (status === 403) return "측정 선을 저장할 권한이 없습니다.";
  if (status === 404) return "작업구역을 찾을 수 없거나 접근 권한이 없습니다.";
  if (status === 422 || status === 400) return "선의 내용을 확인해 주세요.";
  if (status === 503) return "지금은 저장할 수 없습니다. 잠시 후 다시 시도하세요.";
  return "선을 저장하지 못했습니다. 잠시 후 다시 시도하세요.";
}

const REQUEST_REFUSALS: Record<string, string> = {
  GRANT_REQUIRED: "선택한 자료에서 선 주변의 높이를 읽을 수 있는 범위를 담당자에게 확인해 주세요.",
  NOT_A_DSM: "높이 단면은 지표면 높이 자료(DSM)에서만 읽을 수 있습니다.",
  EXTERNAL_RECONSTRUCTION_NOT_SEALED: "이 자료는 아직 등록이 끝나지 않았습니다.",
  EXTERNAL_WORKFLOW_CLOSED: "이 작업이 닫혀 있어 새 단면을 요청할 수 없습니다.",
  IDEMPOTENCY_CONFLICT: "같은 요청이 다른 내용으로 이미 처리되었습니다. 화면을 새로 열어 확인한 뒤 다시 요청하세요.",
  TOO_MANY_JOBS: "이 작업구역의 단면 요청이 한도에 닿았습니다. 끝난 요청이 정리된 뒤 다시 요청하세요.",
  INVALID: "요청 내용을 확인해 주세요. 화면을 새로 열어 다시 시도하세요.",
};

/** 단면 요청이 거부됐을 때의 사람용 문구. Core 거부 사유는 단면 실패 문구와 같은 말로 옮긴다. */
export function requestErrorText(status: number, code: string | undefined): string {
  if (code && Object.prototype.hasOwnProperty.call(REQUEST_REFUSALS, code)) return REQUEST_REFUSALS[code]!;
  if (code && Object.prototype.hasOwnProperty.call(FAILURE_TEXT, code)) return FAILURE_TEXT[code]!;
  if (status === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (status === 403) return "단면을 요청할 권한이 없습니다.";
  if (status === 404) return "자료나 측정 선을 찾을 수 없거나 접근 권한이 없습니다.";
  if (status === 422 || status === 400) return "요청 내용을 확인해 주세요.";
  if (status === 503) return "지금은 요청할 수 없습니다. 잠시 후 다시 시도하세요.";
  return "단면을 요청하지 못했습니다. 잠시 후 다시 시도하세요.";
}
