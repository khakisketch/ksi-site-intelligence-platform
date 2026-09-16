import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// StatusBadge(필드 배경 + 사각 모서리)는 사건의 속성(심각도·판정)을, StateBadge(알약 +
// 아웃라인)는 워크플로 진행 상태를 그린다(StatusBadge.tsx 설계 주석). 이벤트 행에서
// severity와 status(observation→…→confirmed/dismissed, 진행 단계)가 같은 StatusBadge
// 모양으로 나란히 붙으면 색만으로 구분해야 한다(F20) — status는 StateBadge여야 한다.
const PAGE = readFileSync(join(process.cwd(), "src/app/events/page.tsx"), "utf8");

describe("event row badge shapes (F20)", () => {
  it("uses StatusBadge only for severity, and StateBadge for status and triage", () => {
    const rowStart = PAGE.indexOf("function EventRow(");
    const rowEnd = PAGE.indexOf("\nexport default", rowStart);
    const row = PAGE.slice(rowStart, rowEnd);

    expect(row).toContain("<StatusBadge label={severity.label}");
    expect(row).toContain("<StateBadge\n            label={EVENT_STATUS_LABEL[event.status].label}");
    expect(row).toContain("<StateBadge\n            label={TRIAGE_STATUS_LABEL[event.triage].label}");
    expect(row).not.toContain("<StatusBadge\n            label={EVENT_STATUS_LABEL[event.status].label}");
  });
});
