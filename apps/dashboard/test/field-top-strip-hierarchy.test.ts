import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 상단 세 갈래(관측 작업·받은 업무·팀 관리)가 같은 무게의 버튼으로 나란히 있으면
// 우선순위가 없다(F18). 이 화면의 유일한 새 작업 시작 동작인 "관측 자료 등록"이
// 1차 액션이어야 하고, 보기 전환은 탭(현재 보기만 강조)으로 물러난다.
const PAGE = readFileSync(join(process.cwd(), "src/app/field/page.tsx"), "utf8");
const NAV = readFileSync(join(process.cwd(), "src/app/field/FieldWorkNav.tsx"), "utf8");

function stripAround(source: string, marker: string): string {
  const index = source.indexOf(marker);
  expect(index).toBeGreaterThan(-1);
  const end = source.indexOf("</Link>", index);
  expect(end).toBeGreaterThan(index);
  return source.slice(index, end);
}

function stripAroundHref(source: string, href: string): string {
  const index = source.indexOf(href);
  expect(index).toBeGreaterThan(-1);
  const end = source.indexOf("</Link>", index);
  expect(end).toBeGreaterThan(index);
  return source.slice(index, end);
}

describe("field page top action strip (F18)", () => {
  it("makes 관측 자료 등록 the one primary action", () => {
    const link = stripAround(PAGE, 'href="/field/new"');
    expect(link).toContain("btn-primary");
  });

  it("keeps view switching to tabs without primary-button weight", () => {
    expect(PAGE).toContain("<FieldWorkNav");
    const inbox = stripAroundHref(NAV, '"/field/inbox"');
    const team = stripAroundHref(NAV, '"/field/team"');
    expect(inbox).not.toContain("btn-primary");
    expect(team).not.toContain("btn-primary");
    expect(inbox).toContain("aria-current");
  });

  it("gates 관측 자료 등록 on WORK_ORDERS_WRITE with on-demand viewer guidance", () => {
    expect(PAGE).toContain("WORK_ORDERS_WRITE");
    expect(PAGE).toContain('<ActionUnavailable label="관측 자료 등록"');
    expect(PAGE).toContain("현재 계정으로는 관측 자료를 등록할 수 없습니다. 작업 등록 권한이 있는 담당자에게 문의하세요.");
  });
});
