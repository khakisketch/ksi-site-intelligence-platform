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
