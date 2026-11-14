/**
 * BFF 계정 연속성 거부(409 + ACCOUNT_CONTINUITY_MISMATCH)의 클라이언트 측 탐지.
 *
 * 서버 전용 `core-api/work-order-continuity`(server-only)를 클라이언트 컴포넌트에
 * 들여올 수 없어, 각 패널이 같은 문자열·추출식을 복제하고 있었다. 이 모듈은 그
 * 탐지만 한 곳에 둔다. 안내 문구·후속 상태 처리는 각 화면의 책임으로 남긴다 —
 * 거부 시 보여줄 말과 동결 방식은 화면마다 다르므로 통일하지 않는다.
 * 이는 중복 방지 가드 탐지일 뿐 권한·범위 판단이 아니다.
 */

export const ACCOUNT_CONTINUITY_MISMATCH = "ACCOUNT_CONTINUITY_MISMATCH";

/** 응답 본문에서 `code` 문자열을 읽는다. 없거나 객체가 아니면 빈 문자열. */
export function readResponseCode(value: unknown): string {
  return value && typeof value === "object" && "code" in value
    ? String((value as { code?: unknown }).code ?? "")
    : "";
}

/** BFF가 Core 변이 없이 끊은 계정 연속성 거부인지 판정한다. */
export function isAccountContinuityMismatch(status: number, payload: unknown): boolean {
  return status === 409 && readResponseCode(payload) === ACCOUNT_CONTINUITY_MISMATCH;
}
