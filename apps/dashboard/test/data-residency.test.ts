import { describe, expect, it } from "vitest";

import { buildDataResidencyInput } from "@/lib/data-residency";

// INV-050 회귀 방지: 등록 시점에 이 질문에 답하지 않은 현장은 dataResidency 키
// 자체가 요청 바디에 없어야 한다(서버가 그것을 fail-closed 로 해석한다) — 화면이
// 실수로 { egressAllowed: false } 같은 절반짜리 값을 보내면 "안 물어봤다"와
// "물어봤고 거부했다"가 서버 관점에서 구분되지 않게 된다.
describe("buildDataResidencyInput", () => {
  it("미응답(unset)이면 undefined — 요청 바디에 키 자체가 없어야 한다", () => {
    expect(buildDataResidencyInput("unset", "")).toBeUndefined();
    expect(buildDataResidencyInput("unset", "KR")).toBeUndefined();
  });

  it("반출 허용 + 법역을 입력하면 그대로 실린다", () => {
    expect(buildDataResidencyInput("allow", "KR")).toEqual({
      egressAllowed: true,
      jurisdiction: "KR",
    });
  });

  it("반출 거부를 명시해도 egressAllowed:false 와 jurisdiction 이 함께 실린다", () => {
    expect(buildDataResidencyInput("deny", "KR")).toEqual({
      egressAllowed: false,
      jurisdiction: "KR",
    });
  });

  it("법역 앞뒤 공백은 trim 된다", () => {
    expect(buildDataResidencyInput("allow", "  KR  ")).toEqual({
      egressAllowed: true,
      jurisdiction: "KR",
    });
  });

  it("allow/deny 를 골랐는데 법역이 비어 있으면(공백만 포함) 절반짜리 객체를 보내지 않는다", () => {
    expect(buildDataResidencyInput("allow", "")).toBeUndefined();
    expect(buildDataResidencyInput("allow", "   ")).toBeUndefined();
    expect(buildDataResidencyInput("deny", "")).toBeUndefined();
  });
});
