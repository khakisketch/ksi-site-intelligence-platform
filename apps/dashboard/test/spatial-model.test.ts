import { describe, expect, it } from "vitest";

import { MISSION_EXECUTION_STATUS_LABEL, spatialModelSummary } from "@/lib/core-api/labels";
import { MISSION_EXECUTION_STATUSES, SPATIAL_MODEL_STATES } from "@/lib/core-api/types";

describe("공간모델 상태 표시의 정직성", () => {
  it("노후 기준 미선언을 '최신'으로 표시하지 않는다", () => {
    const summary = spatialModelSummary({
      state: "AGE_POLICY_UNDECLARED",
      ageDays: 400,
      maxAgeDays: null,
      siteStatusMatchesModel: true,
    });

    expect(summary.label).not.toContain("최신");
    expect(summary.detail).toContain("기준");
    expect(summary.tone).not.toBe("positive");
  });

  it("현장 상태와 모델 유무가 어긋나면 그 모순을 먼저 보여준다", () => {
    const summary = spatialModelSummary({
      state: "ABSENT",
      ageDays: null,
      maxAgeDays: 30,
      siteStatusMatchesModel: false,
    });

    expect(summary.tone).toBe("warning");
    expect(summary.label).toContain("어긋");
  });

  it("모델이 없는 현장을 경고로 표시하지 않는다", () => {
    // 아직 매핑 전인 현장은 정상이다 — 경고로 칠하면 실제 문제가 묻힌다.
    const summary = spatialModelSummary({
      state: "ABSENT",
      ageDays: null,
      maxAgeDays: 30,
      siteStatusMatchesModel: true,
    });

    expect(summary.tone).toBe("neutral");
  });

  it("최신·오래됨은 며칠인지와 기준을 함께 말한다", () => {
    const fresh = spatialModelSummary({
      state: "FRESH",
      ageDays: 3.4,
      maxAgeDays: 30,
      siteStatusMatchesModel: true,
    });
    const stale = spatialModelSummary({
      state: "STALE",
      ageDays: 45.9,
      maxAgeDays: 30,
      siteStatusMatchesModel: true,
    });

    expect(fresh.detail).toContain("3일");
    expect(fresh.detail).toContain("30일");
    expect(stale.detail).toContain("45일");
    expect(stale.tone).toBe("warning");
  });

  it("모든 상태에 라벨이 있다 — 빠진 값이 화면에 코드로 새지 않는다", () => {
    for (const state of SPATIAL_MODEL_STATES) {
      const summary = spatialModelSummary({
        state,
        ageDays: 1,
        maxAgeDays: 30,
        siteStatusMatchesModel: true,
      });
      expect(summary.label).toBeTruthy();
      expect(summary.detail).toBeTruthy();
    }
  });
});

describe("임무 실행 상태 라벨", () => {
  it("모든 상태에 한국어 라벨이 있다", () => {
    for (const status of MISSION_EXECUTION_STATUSES) {
      expect(MISSION_EXECUTION_STATUS_LABEL[status].label).toBeTruthy();
    }
  });

  it("내부 상태값을 화면에 그대로 내지 않는다", () => {
    for (const status of MISSION_EXECUTION_STATUSES) {
      expect(MISSION_EXECUTION_STATUS_LABEL[status].label).not.toBe(status);
    }
  });
});
