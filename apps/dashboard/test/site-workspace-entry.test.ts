import { describe, expect, it } from "vitest";

import {
  compareSlotCandidates,
  matchAnalysisSelectors,
  observationPrecisionOf,
  parseCalendarDate,
  parseWorkspaceMode,
  representativeFacts,
  resolveExplicitComparison,
  resolveExplicitObservation,
  resolveExplicitResult,
  resolveOrdinaryEntry,
  splitCompareCandidates,
  workspaceCaptureLine,
  type WorkspaceObservationFact,
  type WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";

function fact(overrides: Partial<WorkspaceObservationFact> = {}): WorkspaceObservationFact {
  const { assetRef = "test-asset", ...rest } = overrides;
  return {
    observationEpochId: "epoch-1",
    workAreaId: "area-1",
    workOrderId: "w-1",
    submissionRef: "s-1",
    revision: 1,
    kind: "dsm",
    displayReady: true,
    inspectedRasterAvailable: true,
    chronologyCandidate: true,
    captureSourcesAgree: true,
    viewAvailable: true,
    viewUnavailableReason: null,
    viewAssetRef: assetRef,
    newerRevisionPending: false,
    newerRevisionState: null,
    captureStartedAt: "2021-08-17T10:00:00Z",
    captureEndedAt: "2021-08-17T11:00:00Z",
    captureDate: null,
    ...rest,
    assetRef,
  };
}

function facts(overrides: Partial<WorkspaceServerFacts> = {}): WorkspaceServerFacts {
  return {
    siteId: "site-1",
    authorizedWorkAreaIds: ["area-1", "area-2"],
    entryDefault: null,
    observations: [
      fact({ assetRef: "a-2021", observationEpochId: "epoch-2021", submissionRef: "s-2021" }),
      fact({ assetRef: "a-2022", observationEpochId: "epoch-2022", submissionRef: "s-2022", captureStartedAt: "2022-08-24T10:00:00Z", captureEndedAt: "2022-08-24T11:00:00Z", revision: 2 }),
    ],
    analyses: [],
    ...overrides,
  };
}

describe("workspace entry precision", () => {
  it("accepts only real calendar dates and rejects invented ones", () => {
    expect(parseCalendarDate("2021-08-17")).toBe("2021-08-17");
    expect(parseCalendarDate("2021-02-30")).toBeNull();
    expect(parseCalendarDate("2021-8-7")).toBeNull();
    expect(parseCalendarDate("2021-08-17T10:00:00Z")).toBeNull();
    expect(parseCalendarDate(null)).toBeNull();
    expect(parseCalendarDate(undefined)).toBeNull();
    expect(parseCalendarDate(20210817)).toBeNull();
  });

  it("distinguishes exact intervals from calendar-only and unknown captures", () => {
    expect(observationPrecisionOf(fact({}))).toBe("interval");
    expect(observationPrecisionOf(fact({ captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17" }))).toBe("date-only");
    expect(observationPrecisionOf(fact({ captureStartedAt: null, captureEndedAt: null, captureDate: null }))).toBe("unknown");
    expect(observationPrecisionOf(fact({ captureStartedAt: "2021-08-17T10:00:00Z", captureEndedAt: null, captureDate: null }))).toBe("unknown");
    expect(observationPrecisionOf(fact({ captureStartedAt: null, captureEndedAt: null, captureDate: "not-a-date" }))).toBe("unknown");
  });

  it("renders date-only facts as calendar dates with an explicit unknown-time label", () => {
    const line = workspaceCaptureLine(
      fact({ captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17" }),
      { calendarDate: (date) => `CAL:${date}` },
    );
    expect(line).toContain("2021-08-17");
    expect(line).toContain("날짜만 확인");
    expect(line).toContain("시각 미상");
    expect(line).not.toMatch(/\d{1,2}:\d{2}/);
  });

  it("renders unknown facts without any date or time", () => {
    const line = workspaceCaptureLine(fact({ captureStartedAt: null, captureEndedAt: null, captureDate: null }));
    expect(line).toBe("포착 시점을 확인할 수 없습니다");
    expect(line).not.toMatch(/\d{4}/);
  });
});

describe("workspace ordinary entry", () => {
  const readyEntry = {
    observationEpochId: "epoch-2022",
    viewAssetRef: "a-2022",
    reason: "LATEST_EXACT_VIEW_AVAILABLE" as const,
    detail: "Latest view-available observation by exact capture interval.",
    tiedObservationEpochIds: [],
  };

  it("uses only the server-picked observation and display version", () => {
    const resolution = resolveOrdinaryEntry(facts({ entryDefault: readyEntry }));
    expect(resolution).toEqual({
      status: "ready",
      basis: "server-default",
      workAreaId: "area-1",
      observation: expect.objectContaining({ assetRef: "a-2022", observationEpochId: "epoch-2022" }),
    });
  });

  it("never substitutes another observation when the server pick is unresolvable", () => {
    const missing = resolveOrdinaryEntry(facts({
      entryDefault: { ...readyEntry, observationEpochId: "epoch-ghost", viewAssetRef: "ghost" },
    }));
    expect(missing).toMatchObject({ status: "no-server-default", reason: "LATEST_EXACT_VIEW_AVAILABLE", defaultNotOnPage: true });
    const foreign = resolveOrdinaryEntry(facts({
      authorizedWorkAreaIds: ["area-9"],
      entryDefault: readyEntry,
    }));
    expect(foreign).toMatchObject({ status: "no-server-default", defaultNotOnPage: true });
  });

  it("carries each server no-default reason with its detail instead of ranking client-side", () => {
    for (const reason of ["NO_OBSERVATIONS", "NO_VIEW_AVAILABLE_OBSERVATION", "NO_EXACT_CAPTURE_CANDIDATE", "CAPTURE_TIE_AMBIGUOUS"] as const) {
      const tied = reason === "CAPTURE_TIE_AMBIGUOUS" ? ["epoch-2021", "epoch-2022"] : [];
      const resolution = resolveOrdinaryEntry(facts({
        entryDefault: { observationEpochId: null, viewAssetRef: null, reason, detail: `server ${reason}`, tiedObservationEpochIds: tied },
      }));
      expect(resolution).toMatchObject({ status: "no-server-default", reason, detail: `server ${reason}`, defaultNotOnPage: false });
      if (reason === "CAPTURE_TIE_AMBIGUOUS") {
        expect(resolution.status).toBe("no-server-default");
        if (resolution.status === "no-server-default") {
          expect(resolution.tiedObservationEpochIds).toEqual(tied);
        }
      }
    }
    expect(resolveOrdinaryEntry(facts())).toMatchObject({ status: "no-server-default", reason: "NO_PROJECTION" });
  });

  it("parses only known workspace modes", () => {
    expect(parseWorkspaceMode("compare")).toBe("compare");
    expect(parseWorkspaceMode("results")).toBe("results");
    expect(parseWorkspaceMode("explore")).toBe("explore");
    expect(parseWorkspaceMode(undefined)).toBe("explore");
    expect(parseWorkspaceMode("latest")).toBe("explore");
  });
});

describe("workspace explicit observation links", () => {
  it("restores an exact authorized version", () => {
    const resolution = resolveExplicitObservation(facts(), {
      workAreaId: "area-1",
      observationEpochId: "epoch-2022",
      assetRef: "a-2022",
    });
    expect(resolution.status).toBe("ready");
    if (resolution.status === "ready") {
      expect(resolution.observation.assetRef).toBe("a-2022");
      expect(resolution.basis).toBe("explicit");
    }
  });

  it("picks the server display version without an explicit asset ref, never a client first-pick", () => {
    const versioned = facts({
      observations: [
        fact({ assetRef: "v1-old", observationEpochId: "epoch-1", submissionRef: "s-1", revision: 1, displayReady: true, viewAssetRef: "v2-new" }),
        fact({ assetRef: "v2-new", observationEpochId: "epoch-1", submissionRef: "s-1", revision: 2, displayReady: true, viewAssetRef: "v2-new" }),
      ],
    });
    const resolution = resolveExplicitObservation(versioned, { workAreaId: "area-1", observationEpochId: "epoch-1" });
    expect(resolution.status).toBe("ready");
    if (resolution.status === "ready") expect(resolution.observation.assetRef).toBe("v2-new");
  });

  it("fails closed on malformed, foreign, unknown, or unavailable references without falling back", () => {
    const base = facts();
    const malformed = resolveExplicitObservation(base, { workAreaId: "", observationEpochId: "epoch-2021" });
    expect(malformed.status).toBe("unresolvable");
    const foreign = resolveExplicitObservation(base, { workAreaId: "area-9", observationEpochId: "epoch-2021" });
    expect(foreign).toMatchObject({ status: "unresolvable", reason: "foreign-work-area" });
    const unknownEpoch = resolveExplicitObservation(base, { workAreaId: "area-1", observationEpochId: "nope" });
    expect(unknownEpoch).toMatchObject({ status: "unresolvable", reason: "unknown-observation" });
    const unknownAsset = resolveExplicitObservation(base, { workAreaId: "area-1", observationEpochId: "epoch-2021", assetRef: "ghost" });
    expect(unknownAsset).toMatchObject({ status: "unresolvable", reason: "unknown-asset" });
    const notReady = resolveExplicitObservation(
      facts({ observations: [fact({ assetRef: "a-1", observationEpochId: "e1", displayReady: false, viewAvailable: false, viewAssetRef: null })] }),
      { workAreaId: "area-1", observationEpochId: "e1", assetRef: "a-1" },
    );
    expect(notReady).toMatchObject({ status: "unresolvable", reason: "unavailable" });
    const noDisplay = resolveExplicitObservation(
      facts({ observations: [fact({ assetRef: "a-1", observationEpochId: "e1", displayReady: false, viewAvailable: false, viewAssetRef: null })] }),
      { workAreaId: "area-1", observationEpochId: "e1" },
    );
    expect(noDisplay).toMatchObject({ status: "unresolvable", reason: "unavailable" });
    for (const resolution of [malformed, foreign, unknownEpoch, unknownAsset, notReady, noDisplay]) {
      expect(resolution.status).toBe("unresolvable");
      if (resolution.status === "unresolvable") {
        expect(resolution.headline.length).toBeGreaterThan(0);
        expect(resolution.detail).toContain("자동으로");
      }
    }
  });
});

describe("workspace explicit comparison links", () => {
  it("restores two exact display-ready versions of the same work area", () => {
    const resolution = resolveExplicitComparison(facts(), {
      workAreaId: "area-1",
      baselineAssetRef: "a-2021",
      currentAssetRef: "a-2022",
    });
    expect(resolution.status).toBe("ready");
    if (resolution.status === "ready") {
      expect(resolution.baseline.assetRef).toBe("a-2021");
      expect(resolution.current.assetRef).toBe("a-2022");
    }
  });

  it("fails closed on identical, cross-area, unknown, non-display, or non-orderable selectors", () => {
    const base = facts();
    expect(resolveExplicitComparison(base, {
      workAreaId: "area-1", baselineAssetRef: "a-2021", currentAssetRef: "a-2021",
    })).toMatchObject({ status: "unresolvable", reason: "identical-selectors" });
    expect(resolveExplicitComparison(base, {
      workAreaId: "area-2", baselineAssetRef: "a-2021", currentAssetRef: "a-2022",
    })).toMatchObject({ status: "unresolvable", reason: "cross-area-comparison" });
    expect(resolveExplicitComparison(base, {
      workAreaId: "area-1", baselineAssetRef: "a-2021", currentAssetRef: "ghost",
    })).toMatchObject({ status: "unresolvable", reason: "unknown-asset" });
    expect(resolveExplicitComparison(
      facts({ observations: [fact({ assetRef: "a-1", observationEpochId: "e1", displayReady: true }), fact({ assetRef: "a-2", observationEpochId: "e2", displayReady: false })] }),
      { workAreaId: "area-1", baselineAssetRef: "a-1", currentAssetRef: "a-2" },
    )).toMatchObject({ status: "unresolvable", reason: "unavailable" });
    expect(resolveExplicitComparison(
      facts({ observations: [fact({ assetRef: "a-1", observationEpochId: "e1" }), fact({ assetRef: "a-2", observationEpochId: "e2", chronologyCandidate: false, captureStartedAt: null, captureEndedAt: null, captureDate: "2022-08-24" })] }),
      { workAreaId: "area-1", baselineAssetRef: "a-1", currentAssetRef: "a-2" },
    )).toMatchObject({ status: "unresolvable", reason: "unavailable" });
    expect(resolveExplicitComparison(base, {
      workAreaId: "", baselineAssetRef: "a-2021", currentAssetRef: "a-2022",
    })).toMatchObject({ status: "unresolvable", reason: "malformed" });
  });
});

describe("workspace explicit result links", () => {
  const withResult = () => facts({
    analyses: [{
      analysisId: "analysis-1",
      workAreaId: "area-1",
      baseline: { workOrderId: "w1", submissionRef: "s1", revision: 1 },
      current: { workOrderId: "w2", submissionRef: "s2", revision: 1 },
    }],
  });

  it("restores the exact recorded inputs and work area", () => {
    const resolution = resolveExplicitResult(withResult(), { analysisId: "analysis-1" });
    expect(resolution).toEqual({
      status: "ready",
      basis: "explicit",
      analysis: withResult().analyses[0],
    });
  });

  it("fails closed on malformed, unknown, or foreign results without substituting the latest", () => {
    expect(resolveExplicitResult(withResult(), { analysisId: "" })).toMatchObject({ status: "unresolvable", reason: "malformed" });
    expect(resolveExplicitResult(withResult(), { analysisId: "nope" })).toMatchObject({ status: "unresolvable", reason: "unknown-result" });
    expect(resolveExplicitResult(facts(), { analysisId: "analysis-1" })).toMatchObject({ status: "unresolvable", reason: "unknown-result" });
  });

  it("matches recorded selectors to current projection versions by exact triple", () => {
    const matched = matchAnalysisSelectors(
      facts({
        observations: [
          fact({ assetRef: "base-v", observationEpochId: "e-base", workOrderId: "w1", submissionRef: "s1", revision: 1 }),
          fact({ assetRef: "cur-v", observationEpochId: "e-cur", workOrderId: "w2", submissionRef: "s2", revision: 1 }),
        ],
      }),
      {
        analysisId: "analysis-1",
        workAreaId: "area-1",
        baseline: { workOrderId: "w1", submissionRef: "s1", revision: 1 },
        current: { workOrderId: "w2", submissionRef: "s2", revision: 1 },
      },
    );
    expect(matched.baseline?.assetRef).toBe("base-v");
    expect(matched.current?.assetRef).toBe("cur-v");
    const missing = matchAnalysisSelectors(facts(), {
      analysisId: "analysis-1",
      workAreaId: "area-1",
      baseline: { workOrderId: "w1", submissionRef: "s-gone", revision: 9 },
      current: { workOrderId: "w-1", submissionRef: "s-2022", revision: 2 },
    });
    expect(missing.baseline).toBeNull();
    expect(missing.current?.assetRef).toBe("a-2022");
  });
});

describe("workspace compare grouping", () => {
  it("keeps only server-orderable observations as comparable and dedupes versions per epoch", () => {
    const groups = splitCompareCandidates(facts({
      observations: [
        fact({ assetRef: "exact", observationEpochId: "e1" }),
        fact({ assetRef: "exact-v2", observationEpochId: "e1", revision: 2, viewAssetRef: "exact" }),
        fact({ assetRef: "date-only", observationEpochId: "e2", chronologyCandidate: false, captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17", viewAvailable: false, displayReady: false, viewAssetRef: null }),
        fact({ assetRef: "unknown", observationEpochId: "e3", chronologyCandidate: false, captureStartedAt: null, captureEndedAt: null, captureDate: null, viewAvailable: false, displayReady: false, viewAssetRef: null }),
        fact({ assetRef: "other-area", observationEpochId: "e4", workAreaId: "area-2" }),
        fact({ assetRef: "foreign", observationEpochId: "e5", workAreaId: "area-9" }),
      ],
    }), "area-1");
    expect(groups.comparable.map((item) => item.assetRef)).toEqual(["exact"]);
    expect(groups.browsableDateOnly.map((item) => item.assetRef)).toEqual(["date-only"]);
    expect(groups.browsableUnknown.map((item) => item.assetRef)).toEqual(["unknown"]);
  });

  it("separates display-blocked orderable observations from slot candidates", () => {
    const { eligible, blocked } = compareSlotCandidates(facts({
      observations: [
        fact({ assetRef: "ready", observationEpochId: "e1" }),
        fact({ assetRef: "pending", observationEpochId: "e2", displayReady: false, viewAvailable: false, viewAssetRef: null, newerRevisionPending: true }),
      ],
    }), "area-1");
    expect(eligible.map((item) => item.assetRef)).toEqual(["ready"]);
    expect(blocked.map((item) => item.assetRef)).toEqual(["pending"]);
  });

  it("prefers the server display version as the epoch representative", () => {
    const reps = representativeFacts(facts({
      observations: [
        fact({ assetRef: "v1", observationEpochId: "e1", revision: 1, viewAssetRef: "v2" }),
        fact({ assetRef: "v2", observationEpochId: "e1", revision: 2, viewAssetRef: "v2" }),
      ],
    }), "area-1");
    expect(reps.map((item) => item.assetRef)).toEqual(["v2"]);
  });
});
