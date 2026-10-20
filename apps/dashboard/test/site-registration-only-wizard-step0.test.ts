import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 현장 등록 첫 단계는 사람이 읽는 "현장 이름"보다 기계 식별자 "현장 ID"가 먼저 왔고
// (F16), 비어 있어 다음 버튼이 막힌 이유는 어디에도 쓰여 있지 않았다.
const WIZARD = readFileSync(
  join(process.cwd(), "src/app/sites/new/SiteRegistrationOnlyWizard.tsx"),
  "utf8",
);

describe("site registration step 0 hierarchy (F16)", () => {
  it("shows 현장 이름 before the machine 현장 ID field", () => {
    const nameIndex = WIZARD.indexOf('label="현장 이름"');
    const idIndex = WIZARD.indexOf('label="현장 ID"');
    expect(nameIndex).toBeGreaterThan(-1);
    expect(idIndex).toBeGreaterThan(-1);
    expect(nameIndex).toBeLessThan(idIndex);
  });

  it("names what blocks the disabled next button on step 0", () => {
    expect(WIZARD).toContain("nextDisabledReason=");
    expect(WIZARD).toContain("현장 이름을 입력하세요");
  });

  // 2026-10-20 베타 참가자 드라이브: 2단계에서 경계만 그리고 좌표계·높이 기준을
  // 비우면 "다음"이 이유 설명 없이 비활성이었다. 같은 F16 원칙을 2단계에도 적용한다.
  it("names what blocks the disabled next button on step 1", () => {
    expect(WIZARD).toContain("step1DisabledReason");
    expect(WIZARD).toContain("지도에서 조사 구역을 그리세요");
    expect(WIZARD).toContain("현장 좌표계를 입력하세요");
    expect(WIZARD).toContain("높이 기준을 입력하세요");
    expect(WIZARD).toContain("currentStep === 1 ? step1DisabledReason");
  });
});
