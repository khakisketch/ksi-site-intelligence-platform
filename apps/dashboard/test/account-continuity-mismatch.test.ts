import { describe, expect, it } from "vitest";

import {
  ACCOUNT_CONTINUITY_MISMATCH,
  isAccountContinuityMismatch,
  readResponseCode,
} from "@/lib/account-continuity-mismatch";
import { ACCOUNT_CONTINUITY_MISMATCH as SERVER_CODE } from "@/lib/core-api/work-order-continuity";

describe("account-continuity-mismatch", () => {
  it("공유 상수가 서버 전용 모듈의 코드와 같은 값이다", () => {
    expect(ACCOUNT_CONTINUITY_MISMATCH).toBe(SERVER_CODE);
  });

  it("409 + 코드에서만 참이다", () => {
    expect(isAccountContinuityMismatch(409, { code: "ACCOUNT_CONTINUITY_MISMATCH" })).toBe(true);
    expect(isAccountContinuityMismatch(409, { code: "OTHER" })).toBe(false);
    expect(isAccountContinuityMismatch(400, { code: "ACCOUNT_CONTINUITY_MISMATCH" })).toBe(false);
    expect(isAccountContinuityMismatch(409, null)).toBe(false);
    expect(isAccountContinuityMismatch(409, { code: 409 })).toBe(false);
  });

  it("본문에서 code를 읽는다", () => {
    expect(readResponseCode({ code: "X" })).toBe("X");
    expect(readResponseCode(null)).toBe("");
    expect(readResponseCode("X")).toBe("");
    expect(readResponseCode({})).toBe("");
  });
});
