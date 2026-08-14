import { describe, expect, it } from "vitest";

import { deriveMissionStages } from "@/components/missions/MissionLifecycle";

describe("임무 진행 라벨의 정직성", () => {
  it("커버리지 보고가 없는 상태를 완료나 비행 중으로 추측하지 않는다", () => {
    const stages = deriveMissionStages({
      coverage: { kind: "not-reported" },
      bundle: null,
      latestJob: null,
      hasComparisonReport: false,
    });

    expect(stages[1]).toMatchObject({ title: "비행 결과", detail: "비행 보고 대기", tone: "waiting" });
    expect(stages.slice(1).map((stage) => stage.tone)).not.toContain("done");
  });
});
