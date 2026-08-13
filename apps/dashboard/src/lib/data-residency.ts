import type { DataResidency } from "@/lib/core-api/types";

// 현장 등록 Wizard가 데이터 반출 선언(INV-050)을 묻는 질문의 답 3가지.
// "unset" 은 사용자가 이 질문에 답하지 않기로 선택한 상태다 — 스키마상 선택
// 필드이므로 이 값은 유효한 최종 상태다(contracts/api/openapi-core.yaml
// dataResidency 설명: "생략은 반출 불가를 뜻한다" — 관대한 기본값이 아니다).
export type EgressChoice = "unset" | "allow" | "deny";

/**
 * Wizard 입력을 POST /v1/sites 요청 바디의 `dataResidency` 필드로 바꾼다.
 *
 * `choice` 가 "unset" 이면 `undefined` 를 돌려준다 — 호출부가 그대로 스프레드하면
 * 요청 바디에 `dataResidency` 키 자체가 실리지 않고, 등록 이후 변경 경로가 없는
 * 서버가 여전히 fail-closed(미선언 = 반출 불가)로 처리한다. 스키마가
 * `required: [egressAllowed, jurisdiction]` 이므로 jurisdiction 이 빈 문자열이면
 * (Wizard 검증을 우회한 호출 등) 마찬가지로 `undefined` 를 돌려 절반짜리 객체를
 * 보내지 않는다.
 */
export function buildDataResidencyInput(
  choice: EgressChoice,
  jurisdiction: string,
): DataResidency | undefined {
  if (choice === "unset") return undefined;
  const trimmed = jurisdiction.trim();
  if (trimmed.length === 0) return undefined;
  return { egressAllowed: choice === "allow", jurisdiction: trimmed };
}
