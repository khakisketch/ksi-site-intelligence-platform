import { describe, expect, it } from "vitest";

import {
  describeVolumeUncertainty,
  formatNetVolumeM3,
  formatVolumeM3,
} from "@/lib/core-api/phase34-labels";

// 서버가 내는 체적 숫자를 화면 문자열로 옮기는 규칙이다. 판정은 여기 없다 —
// cut/fill/net 은 서버 계약이 이미 검증했고, 여기서 다시 계산하지 않는다.

describe("formatVolumeM3", () => {
  it("소수 1자리까지만 보여준다", () => {
    expect(formatVolumeM3(1234.567)).toBe("1,234.6 m³");
  });

  it("0 도 값이다 — 빈 문자열로 만들지 않는다", () => {
    expect(formatVolumeM3(0)).toBe("0 m³");
  });
});

describe("formatNetVolumeM3", () => {
  it("증가에는 방향이 보이게 + 를 붙인다", () => {
    expect(formatNetVolumeM3(70)).toBe("+70 m³");
  });

  it("감소는 부호가 이미 있으므로 그대로 둔다", () => {
    expect(formatNetVolumeM3(-50)).toBe("-50 m³");
  });

  it("변화 없음에는 + 를 붙이지 않는다", () => {
    expect(formatNetVolumeM3(0)).toBe("0 m³");
  });
});

describe("describeVolumeUncertainty", () => {
  it("[핵심] null 은 '미산출'로 말하고 이유를 함께 싣는다 (INV-024)", () => {
    const result = describeVolumeUncertainty(null, "ODM 은 검사점 RMSE 를 내지 않는다");
    expect(result.missing).toBe(true);
    expect(result.text).toContain("미산출");
    expect(result.text).toContain("검사점");
  });

  it("값이 있으면 ± 로 범위를 보여준다", () => {
    const result = describeVolumeUncertainty(12.5, "양쪽 epoch 검사점 검증됨");
    expect(result.missing).toBe(false);
    expect(result.text).toContain("±12.5 m³");
  });

  it("0 은 null 이 아니다 — '오차가 없다'와 '모른다'를 구분한다", () => {
    expect(describeVolumeUncertainty(0, "n").missing).toBe(false);
  });
});
