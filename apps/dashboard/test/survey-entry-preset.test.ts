import { describe, expect, it } from "vitest";

import {
  describeCaptureUnavailableReason,
  resolveInitialMissionType,
  resolveReobservationCapturePreset,
} from "@/lib/core-api/surveyEntryPreset";
import type { SpatialRefreshDraftResponse } from "@/lib/core-api/types";

function draft(overrides: Partial<SpatialRefreshDraftResponse> = {}): SpatialRefreshDraftResponse {
  return {
    verdict: "DRAFT_READY",
    aoi: { vertices: [] },
    hullOvercaptureRatio: null,
    regionAreaM2: null,
    netM3: null,
    cutM3: null,
    fillM3: null,
    unmeasurableRatio: null,
    siteUnmeasurableCellRatio: null,
    captureGrade: null,
    captureAltitudeM: null,
    captureFrontOverlap: null,
    captureSideOverlap: null,
    captureIntervalM: null,
    captureGsdM: null,
    baselineGsdM: null,
    captureSignalToNoise: null,
    captureRationale: [],
    captureUnavailableReason: null,
    detail: null,
    ...overrides,
  };
}

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

describe("resolveReobservationCapturePreset", () => {
  it("초안이 촬영 조건을 주면 값을 그대로 옮긴다 — 지어내지 않는다", () => {
    const preset = resolveReobservationCapturePreset(
      draft({
        captureGrade: "DETAILED",
        captureAltitudeM: 56,
        captureFrontOverlap: 0.8,
        captureSideOverlap: 0.7,
        captureIntervalM: 8.4,
        captureRationale: ["평균 표고 변화가 노이즈 바닥의 1.2배"],
      }),
    );

    expect(preset).toMatchObject({
      grade: "DETAILED",
      altitudeM: 56,
      frontOverlap: 0.8,
      sideOverlap: 0.7,
      captureIntervalM: 8.4,
    });
    expect(preset?.rationale).toHaveLength(1);
    expect(preset?.unavailableReason).toBeNull();
  });

  it("촬영 조건을 모르면 값을 지어내지 않고 사유만 넘긴다", () => {
    const preset = resolveReobservationCapturePreset(
      draft({ captureUnavailableReason: "BASELINE_CAPTURE_UNKNOWN" }),
    );

    expect(preset?.altitudeM).toBeNull();
    expect(preset?.frontOverlap).toBeNull();
    expect(preset?.grade).toBeNull();
    expect(preset?.unavailableReason).toBe("BASELINE_CAPTURE_UNKNOWN");
  });

  it("AOI 가 없으면(발급 실패 형태) null이다", () => {
    expect(resolveReobservationCapturePreset(draft({ verdict: "ERROR", aoi: null }))).toBeNull();
  });
});

describe("describeCaptureUnavailableReason", () => {
  it("알려진 코드를 한국어 문장으로 바꾼다 — 코드를 화면에 그대로 내지 않는다", () => {
    const text = describeCaptureUnavailableReason("BASELINE_CAPTURE_UNKNOWN");
    expect(text).not.toContain("BASELINE_CAPTURE_UNKNOWN");
    expect(text).toContain("직전 촬영 조건");
  });

  it("null·모르는 코드는 null", () => {
    expect(describeCaptureUnavailableReason(null)).toBeNull();
    expect(describeCaptureUnavailableReason("SOME_NEW_CODE")).toBeNull();
  });
});
