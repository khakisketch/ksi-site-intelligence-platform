import { describe, expect, it } from "vitest";

import { resolveInitialMissionType } from "@/lib/core-api/surveyEntryPreset";

/**
 * `/sites/[siteId]/surveys/new?purpose=...` 의 화이트리스트 — 이 쿼리 파라미터는
 * 사용자가 URL 을 직접 편집할 수 있는 신뢰 경계 밖 입력이다. 화이트리스트 밖 값을
 * 임무타입으로 그대로 믿으면 안 되고, 조용히 무시(빈 위저드로 시작)해야 한다.
 */
describe("resolveInitialMissionType", () => {
  it("SPATIAL_REFRESH 는 그대로 통과한다(M2 폐루프 진입점)", () => {
    expect(resolveInitialMissionType("SPATIAL_REFRESH")).toBe("SPATIAL_REFRESH");
  });

  it("화이트리스트 밖 값은 null — 임의 문자열", () => {
    expect(resolveInitialMissionType("BASELINE_MAPPING")).toBeNull();
    expect(resolveInitialMissionType("<script>alert(1)</script>")).toBeNull();
    expect(resolveInitialMissionType("")).toBeNull();
  });

  it("파라미터 부재는 null", () => {
    expect(resolveInitialMissionType(undefined)).toBeNull();
  });
});
