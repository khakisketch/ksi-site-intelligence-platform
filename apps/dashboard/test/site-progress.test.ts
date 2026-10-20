/** 현장 진행 단계·상태 묶음의 **판정 로직** 회귀(Console v2 §2).
 *
 * 여기서 고정하는 것은 화면 모양이 아니라 세 가지 주장이다: 본선 순서가 도메인
 * 전이표와 같은가 · 본선 밖 상태를 본선 위에 올려놓지 않는가 · 어떤 상태도 묶음
 * 필터에서 새지 않는가. 셋 다 눈으로 보면 멀쩡해 보이는 종류의 회귀다.
 */

import { describe, expect, it } from "vitest";

import {
  PATROLLABLE_SITE_STATUSES,
  SITE_GROUPS,
  SITE_PROGRESS_STAGES,
  normalizeSiteGroup,
  siteGroupCoverage,
  siteGroupStatuses,
  siteNextAction,
  siteProgress,
} from "../src/lib/core-api/site-progress";
import { SITE_STATUSES } from "../src/lib/core-api/types";

describe("진행 단계 본선", () => {
  it("도메인 전이표의 본선 순서를 그대로 쓴다", () => {
    // ksi_domain.enums._ALLOWED_SITE_TRANSITIONS 의 유일한 전진 경로.
    // 이 배열이 흔들리면 화면이 "어디까지 왔나"를 제 마음대로 말하게 된다.
    expect(SITE_PROGRESS_STAGES.map((s) => s.status)).toEqual([
      "UNMAPPED",
      "BASELINE_MAPPING",
      "MODEL_PROCESSING",
      "MODEL_VALIDATION",
      "PROVISIONAL_AUTONOMY",
      "PATROL_READY",
      "PATROL_ACTIVE",
    ]);
  });

  it("본선 위 상태는 자기 자리만 현재로 찍는다", () => {
    const { cells, note } = siteProgress("MODEL_VALIDATION");
    expect(cells).toEqual(["done", "done", "done", "current", "todo", "todo", "todo"]);
    expect(note).toBe("");
  });

  it("첫 단계와 마지막 단계도 같은 규칙을 따른다", () => {
    expect(siteProgress("UNMAPPED").cells[0]).toBe("current");
    expect(siteProgress("UNMAPPED").cells.filter((c) => c === "done")).toHaveLength(0);
    const last = siteProgress("PATROL_ACTIVE").cells;
    expect(last[last.length - 1]).toBe("current");
    expect(last.filter((c) => c === "todo")).toHaveLength(0);
  });
});

describe("본선 밖 상태", () => {
  it("모델 노후는 '거의 다 왔음'이 아니라 **모델 처리부터 다시**로 찍힌다", () => {
    // 진행률로 환산하면 PATROL_READY 직전(5/7)처럼 보인다 — 그건 앞으로 가는 중이라는
    // 거짓말이다. 되돌아간 지점이 표시돼야 한다.
    const { cells, note } = siteProgress("MODEL_STALE");
    expect(cells.indexOf("rework")).toBe(2);
    expect(cells).not.toContain("current");
    expect(note).toContain("모델 처리부터");
  });

  it("재매핑 필요는 초기 매핑부터 다시로 찍힌다", () => {
    expect(siteProgress("REMAP_REQUIRED").cells.indexOf("rework")).toBe(1);
  });

  it("운영 중단은 위치를 지어내지 않는다", () => {
    const { cells, note } = siteProgress("SUSPENDED");
    expect(new Set(cells)).toEqual(new Set(["unknown"]));
    expect(note).toContain("직전 단계");
  });

  it("모든 상태가 막대 수만큼의 칸을 돌려준다 — 빈 배열이 없다", () => {
    for (const status of SITE_STATUSES) {
      expect(siteProgress(status).cells).toHaveLength(SITE_PROGRESS_STAGES.length);
    }
  });
});

describe("다음 할 일", () => {
  it("10개 상태 전부에 답이 있다", () => {
    for (const status of SITE_STATUSES) {
      expect(siteNextAction(status).label.length).toBeGreaterThan(0);
    }
  });

  it("조사부터 걸어야 하는 상태에만 조사 진입점을 준다", () => {
    expect(siteNextAction("UNMAPPED")).toEqual({ label: "자료·작업 확인", survey: false, actionable: false });
    expect(siteNextAction("REMAP_REQUIRED").survey).toBe(true);
    // 시스템이 처리 중인 동안에는 사람이 걸 것이 없다 — 링크를 주면 막다른 길이다.
    expect(siteNextAction("MODEL_PROCESSING").survey).toBe(false);
    expect(siteNextAction("MODEL_PROCESSING").actionable).toBe(false);
  });
});

describe("상태 묶음", () => {
  it("10개 상태를 빠짐없이 한 번씩 덮는다", () => {
    // 새 상태가 추가됐을 때 어느 묶음에도 안 들어가면 그 현장은 칩을 눌러 찾을 수 없다.
    const { uncovered, duplicated } = siteGroupCoverage(SITE_STATUSES);
    expect(uncovered).toEqual([]);
    expect(duplicated).toEqual([]);
  });

  it("'순찰 가능'은 화이트리스트다 — 준비 중·노후·운영 중단을 포함하지 않는다", () => {
    expect([...PATROLLABLE_SITE_STATUSES].sort()).toEqual([
      "PATROL_ACTIVE",
      "PATROL_READY",
      "PROVISIONAL_AUTONOMY",
    ]);
    for (const status of ["SUSPENDED", "MODEL_STALE", "MODEL_PROCESSING"] as const) {
      expect(PATROLLABLE_SITE_STATUSES.has(status)).toBe(false);
    }
  });

  it("전체 묶음은 거르지 않는다", () => {
    expect(siteGroupStatuses("all")).toBeNull();
  });

  it("모르는 묶음 값은 조용히 전체로 되돌린다", () => {
    expect(normalizeSiteGroup("존재하지않음")).toBe("all");
    expect(normalizeSiteGroup(undefined)).toBe("all");
    expect(normalizeSiteGroup("patrol")).toBe("patrol");
  });

  it("등록된 외부 관측 현장은 근거 없는 조치 필요 대신 중립 묶음에 둔다", () => {
    expect(SITE_GROUPS.map((g) => g.key)).toEqual([
      "all",
      "registered",
      "attention",
      "preparing",
      "patrol",
      "suspended",
    ]);
    expect(SITE_GROUPS.find((group) => group.key === "attention")?.label).toBe("확인 필요");
    expect(siteGroupStatuses("registered")?.has("UNMAPPED")).toBe(true);
    expect(siteGroupStatuses("attention")?.has("UNMAPPED")).toBe(false);
  });
});
