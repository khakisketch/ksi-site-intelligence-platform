import type { VerticalDatum } from "@/lib/core-api/measurement-types";

/** 수직 기준 선언 화면의 사람용 문구. Core 거부 코드를 업무 말로 바꾼다. 모르는 코드는 일반 문구로 접는다. */

export const DATUM_CHOICES: { datum: VerticalDatum; label: string; hint: string }[] = [
  { datum: "orthometric_kngeoid2018", label: "정표고 (KNGeoid2018)", hint: "지오이드 높이를 반영한 해발고. 국내 측량에서 흔히 쓰는 높이입니다." },
  { datum: "orthometric_kngeoid2024", label: "정표고 (KNGeoid2024)", hint: "KNGeoid2024 모델을 적용한 해발고입니다." },
  { datum: "ellipsoidal", label: "타원체고", hint: "GNSS(RTK)가 내는 원시 높이입니다. 지오이드 보정 전의 값입니다." },
  { datum: "ellipsoidal_native", label: "타원체고 (변환 없이 그대로)", hint: "재구성 소프트웨어가 낸 높이를 변환하지 않고 그대로 쓴 경우입니다." },
];

const REFUSALS: Record<string, string> = {
  OBSERVED_REFERENCE_PRESENT: "이 파일은 이미 수직 기준을 담고 있어 선언이 필요 없습니다. 화면을 새로 고쳐 확인하세요.",
  NOT_MEASURED: "파일 검사가 아직 끝나지 않았습니다. 검사가 끝난 뒤 선언하세요.",
  NOT_A_DSM: "수직 기준은 지표면 높이 자료(DSM)에만 선언합니다.",
  SEQUENCE_CONFLICT: "다른 사람이 먼저 선언을 바꿨습니다. 화면을 새로 고쳐 최신 선언을 확인한 뒤 다시 하세요.",
  NOTHING_TO_WITHDRAW: "철회할 선언이 없습니다. 화면을 새로 고쳐 확인하세요.",
  TOO_MANY_DECLARATIONS: "이 자료의 선언 기록이 한도에 닿았습니다. 관리자에게 문의하세요.",
  IDEMPOTENCY_CONFLICT: "같은 요청이 다른 내용으로 이미 처리되었습니다. 화면을 새로 고친 뒤 다시 하세요.",
  INVALID: "입력을 확인해 주세요.",
};

export function declarationErrorText(status: number, code: string | undefined): string {
  if (code && Object.prototype.hasOwnProperty.call(REFUSALS, code)) return REFUSALS[code]!;
  if (status === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (status === 403) return "수직 기준을 선언할 권한이 없습니다.";
  if (status === 404) return "자료를 찾을 수 없거나 접근 권한이 없습니다.";
  if (status === 422 || status === 400) return "입력을 확인해 주세요.";
  if (status === 503) return "지금은 저장할 수 없습니다. 잠시 후 다시 시도하세요.";
  return "선언을 저장하지 못했습니다. 잠시 후 다시 시도하세요.";
}
