import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 상단 세 액션(받은 업무·팀 관리·새 관측 시작)이 같은 .btn 모양으로 나란히 있으면
// 우선순위가 없다(F18). 이 화면의 유일한 새 작업 시작 동작인 "새 관측 시작"이
// 1차 액션이어야 하고, 나머지 둘은 낮은 무게의 텍스트 링크로 물러난다.
const PAGE = readFileSync(join(process.cwd(), "src/app/field/page.tsx"), "utf8");

function stripAround(marker: string): string {
  const index = PAGE.indexOf(marker);
  expect(index).toBeGreaterThan(-1);
  const end = PAGE.indexOf("</Link>", index);
  expect(end).toBeGreaterThan(index);
  return PAGE.slice(index, end);
}

describe("field page top action strip (F18)", () => {
  it("makes 새 관측 시작 the one primary action", () => {
    const link = stripAround('href="/field/new"');
    expect(link).toContain("btn-primary");
  });

  it("demotes 받은 업무 and 팀 관리 below btn-primary weight", () => {
    const inbox = stripAround('href="/field/inbox"');
    const team = stripAround('href="/field/team"');
    expect(inbox).not.toContain("btn-primary");
    expect(team).not.toContain("btn-primary");
  });
});
