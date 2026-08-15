import { describe, expect, it } from "vitest";

import { deriveMissionStages } from "@/components/missions/MissionLifecycle";

describe("임무 진행 라벨의 정직성", () => {
  it("커버리지 보고가 없는 상태를 완료나 비행 중으로 추측하지 않는다", () => {
    const stages = deriveMissionStages({
      execution: null,
      coverage: { kind: "not-reported" },
      bundle: null,
      latestJob: null,
      hasComparisonReport: false,
    });

    expect(stages[2]).toMatchObject({ title: "비행 결과", detail: "비행 보고 대기", tone: "waiting" });
    expect(stages.slice(1).map((stage) => stage.tone)).not.toContain("done");
  });

  it("서버가 실행 상태를 주면 하위 산출물로 역추정하지 않는다", () => {
    const stages = deriveMissionStages({
      execution: {
        missionId: "m-1",
        status: "DISPATCHED",
        updatedAt: "2026-08-15T00:00:00Z",
        updatedBy: "op-1",
        detail: null,
        history: [],
      },
      coverage: { kind: "not-reported" },
      bundle: null,
      latestJob: null,
      hasComparisonReport: false,
    });

    expect(stages[1]).toMatchObject({ title: "실행", detail: "기체로 전달됨", tone: "active" });
  });

  it("서버가 실행 상태를 모르면 그 단계를 완료로 칠하지 않는다", () => {
    const stages = deriveMissionStages({
      execution: null,
      coverage: { kind: "not-reported" },
      bundle: null,
      latestJob: null,
      hasComparisonReport: false,
    });

    expect(stages[1]).toMatchObject({ title: "실행", tone: "waiting" });
    expect(stages.slice(1).map((stage) => stage.tone)).not.toContain("done");
  });

  it("취소된 임무를 진행 중으로 보여주지 않는다", () => {
    const stages = deriveMissionStages({
      execution: {
        missionId: "m-1",
        status: "CANCELLED",
        updatedAt: "2026-08-15T00:00:00Z",
        updatedBy: "op-1",
        detail: null,
        history: [],
      },
      coverage: { kind: "not-reported" },
      bundle: null,
      latestJob: null,
      hasComparisonReport: false,
    });

    expect(stages[1]).toMatchObject({ title: "실행", detail: "취소됨", tone: "waiting" });
  });
});
