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
});
