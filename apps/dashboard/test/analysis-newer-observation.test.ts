import { describe, expect, it } from "vitest";

import {
  deriveNewerObservationNotice,
  findEpochCaptureEndedAt,
  type NewerAnalysisCandidate,
  type NewerObservationCandidate,
} from "@/lib/analysis-newer-observation";
import type { AnalysisSelector } from "@/lib/core-api/analysis";

const selector = (workOrderId: string, digit: string): AnalysisSelector => ({
  workOrderId,
  submissionRef: `ers-v1-${digit.repeat(64)}`,
  revision: 1,
});

const BASELINE = selector("work-baseline", "a");
const CURRENT = selector("work-current", "b");
const NEWER = selector("work-newer", "c");
const NEWEST = selector("work-newest", "d");

function observation(
  selectorValue: AnalysisSelector,
  captureEndedAt: string,
  workAreaIds: readonly string[] = ["area-1"],
): NewerObservationCandidate {
  return {
    selector: selectorValue,
    captureStartedAt: "2026-09-01T00:00:00Z",
    captureEndedAt,
    workAreaIds,
  };
}

function analysis(
  analysisId: string,
  currentSelector: AnalysisSelector,
  hasResult: boolean,
  workAreaId = "area-1",
): NewerAnalysisCandidate {
  return { analysisId, workAreaId, currentSelector, hasResult };
}

const baseArgs = {
  workAreaId: "area-1",
  currentSelector: CURRENT,
  currentCaptureEndedAt: "2026-09-08T00:30:00Z",
};

describe("deriveNewerObservationNotice", () => {
  it("returns null when there are no candidates", () => {
    expect(
      deriveNewerObservationNotice({ ...baseArgs, observations: [], analyses: [] }),
    ).toBeNull();
  });

  it("returns null when every candidate ended earlier", () => {
    expect(
      deriveNewerObservationNotice({
        ...baseArgs,
        observations: [observation(BASELINE, "2026-09-01T00:30:00Z")],
        analyses: [],
      }),
    ).toBeNull();
  });

  it("does not treat the same capture time as newer", () => {
    expect(
      deriveNewerObservationNotice({
        ...baseArgs,
        observations: [observation(NEWER, "2026-09-08T00:30:00Z")],
        analyses: [],
      }),
    ).toBeNull();
  });

  it("ignores candidates from a different WorkArea", () => {
    expect(
      deriveNewerObservationNotice({
        ...baseArgs,
        observations: [observation(NEWER, "2026-09-15T00:30:00Z", ["area-2"])],
        analyses: [],
      }),
    ).toBeNull();
  });

  it("ignores the current observation itself even when listed again", () => {
    expect(
      deriveNewerObservationNotice({
        ...baseArgs,
        observations: [observation(CURRENT, "2026-09-08T00:30:00Z")],
        analyses: [],
      }),
    ).toBeNull();
  });

  it("reports the newer observation without a link when no newer analysis has a result", () => {
    const notice = deriveNewerObservationNotice({
      ...baseArgs,
      observations: [observation(NEWER, "2026-09-15T00:30:00Z")],
      analyses: [],
    });
    expect(notice).toEqual({
      captureEndedAt: "2026-09-15T00:30:00Z",
      workOrderId: "work-newer",
      submissionRef: NEWER.submissionRef,
      revision: 1,
      analysisId: null,
    });
  });

  it("links only to a newer analysis that actually has a result", () => {
    const withoutResult = deriveNewerObservationNotice({
      ...baseArgs,
      observations: [observation(NEWER, "2026-09-15T00:30:00Z")],
      analyses: [analysis("analysis-new", NEWER, false)],
    });
    expect(withoutResult?.analysisId).toBeNull();

    const withResult = deriveNewerObservationNotice({
      ...baseArgs,
      observations: [observation(NEWER, "2026-09-15T00:30:00Z")],
      analyses: [analysis("analysis-new", NEWER, true)],
    });
    expect(withResult?.analysisId).toBe("analysis-new");
  });

  it("does not link an analysis whose current observation is not a newer one", () => {
    const notice = deriveNewerObservationNotice({
      ...baseArgs,
      observations: [observation(NEWER, "2026-09-15T00:30:00Z")],
      // 같은 구역의 완료 분석이지만 현재 관측이 더 새 관측이 아니다.
      analyses: [analysis("analysis-other", BASELINE, true)],
    });
    expect(notice?.analysisId).toBeNull();
    expect(notice?.captureEndedAt).toBe("2026-09-15T00:30:00Z");
  });

  it("does not link an analysis from a different WorkArea", () => {
    const notice = deriveNewerObservationNotice({
      ...baseArgs,
      observations: [observation(NEWER, "2026-09-15T00:30:00Z")],
      analyses: [analysis("analysis-foreign", NEWER, true, "area-2")],
    });
    expect(notice?.analysisId).toBeNull();
  });

  it("shows the latest newer observation and links its completed analysis", () => {
    const notice = deriveNewerObservationNotice({
      ...baseArgs,
      observations: [
        observation(NEWER, "2026-09-15T00:30:00Z"),
        observation(NEWEST, "2026-09-22T00:30:00Z"),
      ],
      analyses: [
        analysis("analysis-new", NEWER, true),
        analysis("analysis-newest", NEWEST, true),
      ],
    });
    expect(notice?.captureEndedAt).toBe("2026-09-22T00:30:00Z");
    expect(notice?.analysisId).toBe("analysis-newest");
  });

  it("returns null when the current capture time cannot be compared", () => {
    expect(
      deriveNewerObservationNotice({
        ...baseArgs,
        currentCaptureEndedAt: "not-a-time",
        observations: [observation(NEWER, "2026-09-15T00:30:00Z")],
        analyses: [],
      }),
    ).toBeNull();
  });

  it("skips candidates with unreadable capture times", () => {
    expect(
      deriveNewerObservationNotice({
        ...baseArgs,
        observations: [observation(NEWER, "not-a-time")],
        analyses: [],
      }),
    ).toBeNull();
  });

  it("carries no suitability, execution or numeric judgment and leaves the earlier result untouched", () => {
    const earlierResult = {
      resultId: "result-core-1",
      metrics: { cutM3: 12, fillM3: 20, netM3: 8 },
      suitabilityState: "EVALUATED",
      executionState: "COMPLETED",
    };
    const snapshot = JSON.parse(JSON.stringify(earlierResult));
    const notice = deriveNewerObservationNotice({
      ...baseArgs,
      observations: [observation(NEWER, "2026-09-15T00:30:00Z")],
      analyses: [analysis("analysis-new", NEWER, true)],
    });
    // 더 새 관측이 있다는 사실만 말할 뿐, 이전 결과의 수치·판정을 바꾸거나
    // 암시하는 필드를 내놓지 않는다.
    expect(notice && Object.keys(notice).sort()).toEqual(
      ["analysisId", "captureEndedAt", "revision", "submissionRef", "workOrderId"],
    );
    expect(earlierResult).toEqual(snapshot);
  });

  it("does not require the current epoch to sit in the area-attributed candidate list", () => {
    // 실제 재현 귀속(F-03): 결과의 현재 epoch은 구역 귀속 목록에 없고,
    // 구역에는 더 늦은 관측이 있다. 시각만 알면 알림은 나와야 한다.
    const notice = deriveNewerObservationNotice({
      ...baseArgs,
      observations: [observation(NEWER, "2026-09-15T00:30:00Z")],
      analyses: [],
    });
    expect(
      [observation(NEWER, "2026-09-15T00:30:00Z")].some((option) =>
        option.selector.workOrderId === CURRENT.workOrderId
        && option.selector.submissionRef === CURRENT.submissionRef
        && option.selector.revision === CURRENT.revision,
      ),
    ).toBe(false);
    expect(notice?.captureEndedAt).toBe("2026-09-15T00:30:00Z");
    expect(notice?.analysisId).toBeNull();
  });
});

describe("findEpochCaptureEndedAt", () => {
  const siteList = [
    { selector: BASELINE, captureEndedAt: "2026-09-01T00:30:00Z" },
    // 귀속 없는 epoch: 선택자 일치만으로 시각을 찾는다.
    { selector: CURRENT, captureEndedAt: "2026-09-08T00:30:00Z" },
  ];

  it("resolves the epoch time by selector match regardless of area attribution", () => {
    expect(findEpochCaptureEndedAt(siteList, CURRENT)).toBe("2026-09-08T00:30:00Z");
  });

  it("returns null without guessing when the epoch is absent site-wide", () => {
    expect(findEpochCaptureEndedAt(siteList, NEWER)).toBeNull();
    expect(findEpochCaptureEndedAt([], CURRENT)).toBeNull();
  });

  it("does not match a different revision of the same work order", () => {
    const otherRevision = { ...CURRENT, revision: 2 };
    expect(findEpochCaptureEndedAt(siteList, otherRevision)).toBeNull();
  });
});
