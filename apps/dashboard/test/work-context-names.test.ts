import { describe, expect, it } from "vitest";

import {
  SITE_NAME_UNAVAILABLE,
  splitInboxItemContext,
  formatHomeReviewTechnicalRef,
  formatWorkAreaSummary,
  formatWorkAreaTechnicalRefs,
  formatWorkQueueRowContext,
  homeAnalysisReviewCardText,
  indexWorkAreaNames,
  indexWorkAreaNamesBySite,
  isWorkQueueContextMissing,
  orderWorkQueueGroupsForDisplay,
  selectWorkAreaDisplayNames,
  selectWorkQueueRowsNeedingTechnicalRef,
} from "@/lib/work-context-names";

const AREA_MAP = new Map([
  ["area-1", "동측 구역"],
  ["area-2", "서측 구역"],
  ["area-archived", "보관된 북측 구역"],
]);

describe("작업 맥락 이름 표시", () => {
  it("알려진 구역은 이름으로, 모르는 구역은 개수에만 두고 정직하게 둔다", () => {
    expect(formatWorkAreaSummary(["area-1"], AREA_MAP)).toBe("동측 구역");
    expect(formatWorkAreaSummary(["area-1", "area-2"], AREA_MAP)).toBe("동측 구역 · 서측 구역");
    expect(formatWorkAreaSummary(["area-1", "area-2", "area-3"], AREA_MAP)).toBe("동측 구역 · 서측 구역 외 1개 구역");
    expect(formatWorkAreaSummary(["missing-1", "missing-2"], AREA_MAP)).toBe("2개 구역 (구역 이름 확인 불가)");
    expect(formatWorkAreaSummary([], AREA_MAP)).toBe("구역 지정 없음");
  });

  it("보관된 구역 이름도 맥락에 쓴다", () => {
    const indexed = indexWorkAreaNames([
      { workAreaId: "area-archived", name: "보관된 북측 구역" },
    ]);
    expect(formatWorkAreaSummary(["area-archived"], indexed)).toBe("보관된 북측 구역");
    expect(selectWorkAreaDisplayNames(["area-archived", "gone"], indexed)).toEqual({
      known: ["보관된 북측 구역"],
      unknownCount: 1,
    });
  });

  it("큐 행은 현장·구역·정식 회차·갱신 시각을 이름 우선으로 둔다", () => {
    const line = formatWorkQueueRowContext({
      siteName: "한강 현장",
      workAreaIds: ["area-1", "area-2"],
      nameById: AREA_MAP,
      cycleNumber: 7,
      updatedAt: "2026-10-15T12:31:00Z",
    });
    expect(line).toContain("한강 현장");
    expect(line).toContain("동측 구역 · 서측 구역");
    expect(line).toContain("7회차");
    expect(line).toContain("갱신 ");
    expect(line).not.toContain("2026-10-15T12:31:00Z");
  });

  it("이름에 t2가 있어도 회차는 원장 cycleNumber만 쓴다", () => {
    const line = formatWorkQueueRowContext({
      siteName: "현장",
      workAreaIds: [],
      nameById: AREA_MAP,
      cycleNumber: 1,
      updatedAt: "2026-10-15T12:31:00Z",
    });
    expect(line).toContain("1회차");
    expect(line).not.toMatch(/t2|2회차/);
  });

  it("같은 이름의 작업도 현장·구역 맥락으로 가른다", () => {
    const first = formatWorkQueueRowContext({
      siteName: "한강 현장", workAreaIds: ["area-1"], nameById: AREA_MAP, cycleNumber: 1, updatedAt: "2026-10-15T12:31:00Z",
    });
    const second = formatWorkQueueRowContext({
      siteName: "낙동 현장", workAreaIds: ["area-2"], nameById: AREA_MAP, cycleNumber: 1, updatedAt: "2026-10-15T12:31:00Z",
    });
    expect(first).not.toBe(second);
    expect(first).toContain("한강 현장");
    expect(second).toContain("낙동 현장");
  });

  it("이름을 모르면 ID를 지어내지 않고 확인 불가로 둔다", () => {
    const line = formatWorkQueueRowContext({
      siteName: null, workAreaIds: ["wa-unknown"], nameById: AREA_MAP, cycleNumber: 3, updatedAt: "2026-10-15T12:31:00Z",
    });
    expect(line).toContain(SITE_NAME_UNAVAILABLE);
    expect(line).not.toContain("wa-unknown");
    expect(line).toContain("3회차");
  });

  it("빈 이름은 미확인으로 두되 공백 아닌 이름은 정확히 보존한다", () => {
    const indexed = indexWorkAreaNames([
      { workAreaId: "blank", name: "   " },
      { workAreaId: "empty", name: "" },
      { workAreaId: "spaced", name: "  동측 구역  " },
    ]);
    expect(indexed.has("blank")).toBe(false);
    expect(indexed.has("empty")).toBe(false);
    expect(indexed.get("spaced")).toBe("  동측 구역  ");
    expect(formatWorkAreaSummary(["blank", "empty"], indexed)).toBe("2개 구역 (구역 이름 확인 불가)");
    expect(selectWorkAreaDisplayNames(["blank"], new Map([["blank", " "]]))).toEqual({ known: [], unknownCount: 1 });
  });

  it("같은 구역 ID라도 현장이 다르면 이름을 섞지 않는다", () => {
    const bySite = indexWorkAreaNamesBySite([
      { siteId: "site-a", workAreas: [{ workAreaId: "area-1", name: "한강 동측" }] },
      { siteId: "site-b", workAreas: [{ workAreaId: "area-1", name: "낙동 서측" }] },
    ]);
    expect(formatWorkAreaSummary(["area-1"], bySite.get("site-a") ?? new Map())).toBe("한강 동측");
    expect(formatWorkAreaSummary(["area-1"], bySite.get("site-b") ?? new Map())).toBe("낙동 서측");
    expect(formatWorkAreaSummary(["area-1"], bySite.get("site-unknown") ?? new Map())).toBe("1개 구역 (구역 이름 확인 불가)");
  });

  it("이름이 겹쳐 접혀도 구역 ID는 기술 참조에 모두 남는다", () => {
    const dupes = new Map([["area-1", "같은 구역"], ["area-2", "같은 구역"]]);
    expect(formatWorkAreaSummary(["area-1", "area-2"], dupes)).toBe("같은 구역 외 1개 구역");
    const refs = formatWorkAreaTechnicalRefs(["area-1", "area-2"]);
    expect(refs).toContain("area-1");
    expect(refs).toContain("area-2");
    expect(formatWorkAreaTechnicalRefs([])).toBe("지정 없음");
  });

  it("빈 그룹은 뒤로 보내되 소속과 건수는 그대로 둔다", () => {
    const ordered = orderWorkQueueGroupsForDisplay([
      { key: "decisionRequired", rows: [] },
      { key: "inFlight", rows: [{ id: 1 }, { id: 2 }] },
      { key: "operationsUnavailable", rows: [] },
      { key: "completed", rows: [{ id: 3 }] },
    ]);
    expect(ordered.map((group) => group.key)).toEqual([
      "inFlight",
      "completed",
      "decisionRequired",
      "operationsUnavailable",
    ]);
    expect(ordered.find((group) => group.key === "inFlight")?.rows).toHaveLength(2);
    expect(ordered.find((group) => group.key === "decisionRequired")?.rows).toHaveLength(0);
  });

  it("Home 검토 카드는 할 일을 앞세우고 실제 구역 이름을 대상 맥락에 보존한다", () => {
    const known = homeAnalysisReviewCardText({ siteName: "F-03 현장", workAreaId: "wa-1", areaName: "동측 구역" });
    expect(known.title).toBe("분석 결과를 검토하세요.");
    expect(known.title).not.toContain("wa-1");
    expect(known.detail).toBe("대상 구역 · 동측 구역. 현재 결과의 검토 기록이 없습니다. 결과와 근거를 확인하세요.");
    expect(known.detail).not.toContain("F-03 현장");
    expect(known.detail).toContain("동측 구역");

    const missing = homeAnalysisReviewCardText({ siteName: null, workAreaId: "wa-1", areaName: null });
    expect(missing.title).not.toContain("wa-1");
    expect(missing.detail).toContain(SITE_NAME_UNAVAILABLE);
    expect(missing.detail).toContain("구역 이름");
  });

  it("긴 구역 이름도 자르거나 유도하지 않고 그대로 둔다", () => {
    const longName = "한강 하류 좌안 제방 보강 구간 동측 3공구 야적장 진입로";
    const card = homeAnalysisReviewCardText({ siteName: "현장", workAreaId: "wa-1", areaName: longName });
    expect(card.title).toBe("분석 결과를 검토하세요.");
    expect(card.detail).toContain(longName);
    expect(formatHomeReviewTechnicalRef("analysis-1", "wa-1")).toContain("wa-1");
  });

  it("받은 업무 맥락은 작업·현장을 별도 줄로 나눠 긴 이름도 현장을 가리지 않는다", () => {
    expect(splitInboxItemContext("WORK_ORDER_ASSIGNED", { workName: "t2 관측", siteName: "한강 현장" })).toEqual({ title: "t2 관측", siteLine: "한강 현장" });
    expect(splitInboxItemContext("WORK_ORDER_ASSIGNED", { workName: "t2 관측", siteName: null })).toEqual({ title: "t2 관측", siteLine: null });
    expect(splitInboxItemContext("WORK_ORDER_ASSIGNED", { workName: null, siteName: null })).toEqual({ title: null, siteLine: null });
    expect(splitInboxItemContext("EXTERNAL_REPORT_SHARED", { workName: null, siteName: "한강 현장" })).toEqual({ title: null, siteLine: "한강 현장의 공유 결과" });
    expect(splitInboxItemContext("EXTERNAL_REPORT_SHARED", { workName: null, siteName: null })).toEqual({ title: null, siteLine: null });
  });

  it("유일한 행은 펼침 없이 두고 겹치거나 빠진 행만 가린다", () => {
    const areaMap = new Map([["area-1", "동측 구역"]]);
    const line = "한강 현장 · 동측 구역 · 1회차 · 갱신 2026. 10. 15. 18:31";
    expect(selectWorkQueueRowsNeedingTechnicalRef([
      { rowKey: "wo-1", name: "관측 A", contextLine: line, missingContext: false },
      { rowKey: "wo-2", name: "관측 B", contextLine: `${line}분`, missingContext: false },
    ]).size).toBe(0);

    // 이름+맥락이 겹치면 양쪽 모두 가린다.
    expect(selectWorkQueueRowsNeedingTechnicalRef([
      { rowKey: "wo-1", name: "관측 A", contextLine: line, missingContext: false },
      { rowKey: "wo-2", name: "관측 A", contextLine: line, missingContext: false },
    ])).toEqual(new Set(["wo-1", "wo-2"]));

    // 이름이 비었거나 현장·구역 이름을 모르면 가린다.
    expect(isWorkQueueContextMissing({ name: "  ", siteName: "현장", workAreaIds: [], nameById: areaMap })).toBe(true);
    expect(isWorkQueueContextMissing({ name: "관측", siteName: null, workAreaIds: [], nameById: areaMap })).toBe(true);
    expect(isWorkQueueContextMissing({ name: "관측", siteName: "현장", workAreaIds: ["gone"], nameById: areaMap })).toBe(true);
    expect(isWorkQueueContextMissing({ name: "관측", siteName: "현장", workAreaIds: ["area-1"], nameById: areaMap })).toBe(false);
    expect(isWorkQueueContextMissing({ name: "관측", siteName: "현장", workAreaIds: [], nameById: areaMap })).toBe(false);
  });
});
