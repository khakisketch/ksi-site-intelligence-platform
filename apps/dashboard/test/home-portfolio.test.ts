/** 홈 포트폴리오 표의 **판정 로직** 회귀(Console v2 §1).
 *
 * 이 저장소의 프런트 테스트 규약대로 렌더는 보지 않는다 — 여기서 고정하는 것은
 * "무엇이 검색되는가 · 무엇이 먼저 오는가 · 모르는 값이 0 으로 둔갑하지 않는가"다.
 * 셋 다 표를 눈으로 봐서는 못 잡는 회귀다(정렬이 틀려도 표는 멀쩡해 보인다).
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_PORTFOLIO_SORT,
  derivePortfolio,
  filterPortfolio,
  normalizePortfolioSort,
  sortPortfolio,
  type PortfolioRow,
} from "../src/app/portfolio";

function row(overrides: Partial<PortfolioRow> & Pick<PortfolioRow, "siteId" | "name">): PortfolioRow {
  return {
    status: "PATROL_READY",
    registeredAt: "2026-01-01T00:00:00Z",
    lastMissionAt: null,
    unattendedCount: 0,
    blocked: false,
    ...overrides,
  };
}

const ROWS: PortfolioRow[] = [
  row({ siteId: "S-2411-GJ", name: "광교 A3블록", unattendedCount: 2, registeredAt: "2026-03-01T00:00:00Z", lastMissionAt: "2026-08-10T00:00:00Z" }),
  row({ siteId: "S-2501-DJ", name: "대전 물류센터", unattendedCount: 0, registeredAt: "2026-05-01T00:00:00Z", lastMissionAt: "2026-08-16T00:00:00Z" }),
  row({ siteId: "S-2502-BS", name: "부산 항만", status: "UNMAPPED", blocked: true, unattendedCount: 0, registeredAt: "2026-07-01T00:00:00Z" }),
];

describe("포트폴리오 검색", () => {
  it("빈 검색어는 전부 돌려준다", () => {
    expect(filterPortfolio(ROWS, "   ").map((r) => r.siteId)).toEqual(ROWS.map((r) => r.siteId));
  });

  it("현장명 일부로 찾는다", () => {
    expect(filterPortfolio(ROWS, "광교").map((r) => r.siteId)).toEqual(["S-2411-GJ"]);
  });

  it("현장 ID 로도 찾는다 — 이름을 기억 못 해도 도달할 수 있어야 한다", () => {
    expect(filterPortfolio(ROWS, "2502").map((r) => r.siteId)).toEqual(["S-2502-BS"]);
  });

  it("대소문자와 좌우 공백을 무시한다", () => {
    expect(filterPortfolio(ROWS, "  s-2501-dj  ").map((r) => r.siteId)).toEqual(["S-2501-DJ"]);
  });

  it("일치가 없으면 빈 목록 — 엉뚱한 행을 채우지 않는다", () => {
    expect(filterPortfolio(ROWS, "없는현장")).toEqual([]);
  });

  it("원본 배열을 건드리지 않는다", () => {
    const before = ROWS.map((r) => r.siteId);
    filterPortfolio(ROWS, "광교");
    expect(ROWS.map((r) => r.siteId)).toEqual(before);
  });
});

describe("포트폴리오 정렬", () => {
  it("기본은 순찰을 시작조차 못 하는 현장이 맨 위다", () => {
    expect(sortPortfolio(ROWS, "attention").map((r) => r.siteId)).toEqual([
      "S-2502-BS",
      "S-2411-GJ",
      "S-2501-DJ",
    ]);
  });

  it("미조치 수를 못 구한 행(null)이 미조치 0 을 밀어내지 않는다", () => {
    // null 은 '없음'이 아니라 '세지 못함'이다 — 위로 올려 급한 것처럼 보이게 하면
    // 그건 화면이 지어낸 우선순위다.
    const rows = [
      row({ siteId: "A", name: "가", unattendedCount: null }),
      row({ siteId: "B", name: "나", unattendedCount: 1 }),
      row({ siteId: "C", name: "다", unattendedCount: 0 }),
    ];
    expect(sortPortfolio(rows, "attention").map((r) => r.siteId)).toEqual(["B", "A", "C"]);
  });

  it("최근 임무 순 — 발급 이력이 없는 현장은 항상 뒤다", () => {
    expect(sortPortfolio(ROWS, "recent").map((r) => r.siteId)).toEqual([
      "S-2501-DJ",
      "S-2411-GJ",
      "S-2502-BS",
    ]);
  });

  it("등록일 순은 최신이 위다", () => {
    expect(sortPortfolio(ROWS, "registered").map((r) => r.siteId)).toEqual([
      "S-2502-BS",
      "S-2501-DJ",
      "S-2411-GJ",
    ]);
  });

  it("현장명 순은 한국어 정렬을 쓴다", () => {
    expect(sortPortfolio(ROWS, "name").map((r) => r.name)).toEqual([
      "광교 A3블록",
      "대전 물류센터",
      "부산 항만",
    ]);
  });

  it("동점은 현장명으로 풀어 순서가 새로고침마다 흔들리지 않는다", () => {
    const rows = [
      row({ siteId: "B", name: "나현장", unattendedCount: 3 }),
      row({ siteId: "A", name: "가현장", unattendedCount: 3 }),
    ];
    expect(sortPortfolio(rows, "attention").map((r) => r.siteId)).toEqual(["A", "B"]);
    expect(sortPortfolio([...rows].reverse(), "attention").map((r) => r.siteId)).toEqual(["A", "B"]);
  });

  it("원본 배열을 제자리에서 정렬하지 않는다", () => {
    const before = ROWS.map((r) => r.siteId);
    sortPortfolio(ROWS, "name");
    expect(ROWS.map((r) => r.siteId)).toEqual(before);
  });
});

describe("URL 정렬값 정규화", () => {
  it("아는 값만 받는다", () => {
    expect(normalizePortfolioSort("name")).toBe("name");
    expect(normalizePortfolioSort("recent")).toBe("recent");
  });

  it("모르는 값·빈 값은 조용히 기본값으로 되돌린다 — 오류 화면을 내지 않는다", () => {
    expect(normalizePortfolioSort("plan")).toBe(DEFAULT_PORTFOLIO_SORT);
    expect(normalizePortfolioSort(undefined)).toBe(DEFAULT_PORTFOLIO_SORT);
    expect(normalizePortfolioSort(null)).toBe(DEFAULT_PORTFOLIO_SORT);
    expect(normalizePortfolioSort("__proto__")).toBe(DEFAULT_PORTFOLIO_SORT);
  });
});

describe("검색 + 정렬 합성", () => {
  it("거른 뒤 정렬한다", () => {
    const result = derivePortfolio(ROWS, "S-25", "name");
    expect(result.map((r) => r.siteId)).toEqual(["S-2501-DJ", "S-2502-BS"]);
  });
});
