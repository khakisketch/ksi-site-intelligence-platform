import { describe, expect, it } from "vitest";

import { CoreApiError } from "@/lib/core-api/client";

// 서버 오류를 사람 말로 바꾸는 첫 단계 — verdict 코드 추출. 독립 재검토 2차 P1-D 에서
// 문장 중간의 대문자 값(예: "AUTONOMOUS_PATROL 는 ...")을 코드로 오인해 엉뚱한 안내를
// 띄우던 것이 잡혔고, 그때 검증은 node 로 5개 케이스를 손으로 돌린 게 전부였다.
// 정규식은 조용히 넓어지는 종류의 코드라 여기 고정한다.

describe("verdict 필드가 있는 응답(Site/Event API)", () => {
  it("verdict 를 그대로 코드로 쓴다", () => {
    const error = new CoreApiError(409, { verdict: "DUPLICATE_SITE_ID", detail: "이미 있다" });
    expect(error.code).toBe("DUPLICATE_SITE_ID");
    expect(error.serverMessage).toBe("이미 있다");
    expect(error.status).toBe(409);
  });
});

describe("처리 자원 한도 하위 사유", () => {
  it("Core가 준 stable reasonCode를 보존해 Dashboard route handler로 넘긴다", () => {
    const error = new CoreApiError(422, {
      verdict: "RESOURCE_LIMIT_EXCEEDED",
      reasonCode: "TOTAL_MEGAPIXELS_LIMIT_EXCEEDED",
      detail: "총 촬영 화소량이 정책 상한을 넘었다",
    });
    expect(error.code).toBe("RESOURCE_LIMIT_EXCEEDED");
    expect(error.reasonCode).toBe("TOTAL_MEGAPIXELS_LIMIT_EXCEEDED");
  });

  it("reasonCode가 문자열이 아니면 화면 행동 선택에 쓰지 않는다", () => {
    expect(new CoreApiError(422, { verdict: "RESOURCE_LIMIT_EXCEEDED", reasonCode: 42 }).reasonCode).toBeUndefined();
  });
});

describe("typed spatial-data refusal envelope", () => {
  const envelope = { reason: "PRIVATE_WORKSPACE_UNAVAILABLE", message: "Spatial data request unavailable.",
    retryable: true, remediation: ["CONTACT_OPERATOR"] };
  it("preserves Core's safe refusal reason without forwarding arbitrary message text", () => {
    const error = new CoreApiError(503, envelope);
    expect(error.code).toBe("PRIVATE_WORKSPACE_UNAVAILABLE");
    expect(error.status).toBe(503);
    expect(error.serverMessage).toBeUndefined();
  });
  it("does not override an existing verdict", () => {
    expect(new CoreApiError(503, { ...envelope, verdict: "CURRENTNESS_UNAVAILABLE" }).code).toBe("CURRENTNESS_UNAVAILABLE");
  });
  it.each([
    { reason: "not a decision code" }, { retryable: "true" }, { remediation: [] },
    { remediation: ["https://outside.test/repair"] }, { message: null },
  ])("does not infer a code from an untyped/invalid reason payload: %j", (patch) => {
    expect(new CoreApiError(503, { ...envelope, ...patch }).code).toBeUndefined();
  });
});

describe("detail 하나에만 코드를 싣는 응답(Mission Records/Plans API)", () => {
  it("코드 단독", () => {
    const error = new CoreApiError(404, { detail: "UNKNOWN_SITE" });
    expect(error.code).toBe("UNKNOWN_SITE");
    expect(error.serverMessage).toBeUndefined();
  });

  it("코드 — 설명", () => {
    const error = new CoreApiError(422, { detail: "COVERAGE_BELOW_MINIMUM — 커버리지가 부족하다" });
    expect(error.code).toBe("COVERAGE_BELOW_MINIMUM");
    expect(error.serverMessage).toBe("커버리지가 부족하다");
  });

  it("코드: 설명", () => {
    const error = new CoreApiError(422, { detail: "MISSION_ID_CONFLICT: 다른 요청과 충돌" });
    expect(error.code).toBe("MISSION_ID_CONFLICT");
    expect(error.serverMessage).toBe("다른 요청과 충돌");
  });
});

describe("코드로 오인하지 않아야 하는 것", () => {
  it("문장 중간의 대문자 토큰은 코드가 아니다", () => {
    const error = new CoreApiError(422, {
      detail: "임무 유형 AUTONOMOUS_PATROL 는 lawnmower 패턴과 함께 쓸 수 없다",
    });
    expect(error.code).toBeUndefined();
    expect(error.serverMessage).toBe("임무 유형 AUTONOMOUS_PATROL 는 lawnmower 패턴과 함께 쓸 수 없다");
  });

  it("소문자로 시작하는 토큰은 코드가 아니다", () => {
    const error = new CoreApiError(500, { detail: "internal error" });
    expect(error.code).toBeUndefined();
  });

  it("너무 짧은 대문자 토큰은 코드로 보지 않는다", () => {
    expect(new CoreApiError(400, { detail: "AB" }).code).toBeUndefined();
  });
});

describe("FastAPI 요청검증 422", () => {
  it("detail 배열의 msg 들을 사람이 읽을 한 문장으로 합친다", () => {
    const error = new CoreApiError(422, {
      detail: [
        { loc: ["body", "siteId"], msg: "field required", type: "missing" },
        { loc: ["body", "name"], msg: "string too short", type: "too_short" },
      ],
    });
    expect(error.serverMessage).toBe("field required / string too short");
  });

  it("msg 가 없는 항목은 건너뛴다", () => {
    const error = new CoreApiError(422, { detail: [{ loc: ["body"] }, { msg: "bad" }] });
    expect(error.serverMessage).toBe("bad");
  });
});

describe("본문이 없거나 형태를 벗어난 응답", () => {
  it("본문이 null 이어도 예외를 던지지 않는다", () => {
    const error = new CoreApiError(503, null);
    expect(error.code).toBeUndefined();
    expect(error.serverMessage).toBeUndefined();
    expect(error.status).toBe(503);
  });

  it("detail 이 객체면 문장으로 쓰지 않는다", () => {
    const error = new CoreApiError(500, { detail: { nested: "value" } });
    expect(error.serverMessage).toBeUndefined();
  });
});
