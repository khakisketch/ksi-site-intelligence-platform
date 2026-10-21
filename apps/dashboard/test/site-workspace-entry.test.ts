import { describe, expect, it } from "vitest";

import {
  observationPrecisionOf,
  parseCalendarDate,
  parseWorkspaceMode,
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
  return {
    assetRef: "test-asset",
    observationEpochId: "epoch-1",
    workAreaId: "area-1",
    kind: "dsm",
    revision: 1,
    captureStartedAt: "2021-08-17T10:00:00Z",
    captureEndedAt: "2021-08-17T11:00:00Z",
    captureDate: null,
    viewAvailable: true,
    ...overrides,
  };
}

function facts(overrides: Partial<WorkspaceServerFacts> = {}): WorkspaceServerFacts {
  return {
    siteId: "site-1",
    authorizedWorkAreaIds: ["area-1", "area-2"],
    serverDefault: null,
    observations: [
      fact({ assetRef: "a-2021", observationEpochId: "epoch-2021" }),
      fact({ assetRef: "a-2022", observationEpochId: "epoch-2022", captureStartedAt: "2022-08-24T10:00:00Z", captureEndedAt: "2022-08-24T11:00:00Z", revision: 2 }),
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
    // 한쪽 구간만 있으면 구간이 아니다 — 날짜로도 그리지 않는다.
    expect(observationPrecisionOf(fact({ captureStartedAt: "2021-08-17T10:00:00Z", captureEndedAt: null, captureDate: null }))).toBe("unknown");
    // 깨진 달력 날짜는 미상으로 둔다 — 제출 시각에서 유도하지 않는다.
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

  it("renders exact intervals through the caller title without inventing precision", () => {
    const line = workspaceCaptureLine(fact({}), { intervalTitle: (s, e) => `I:${s}|${e}` });
    expect(line).toBe("I:2021-08-17T10:00:00Z|2021-08-17T11:00:00Z");
  });

  it("keeps only exact-interval observations as chronological comparison candidates", () => {
    const groups = splitCompareCandidates(facts({
      observations: [
        fact({ assetRef: "exact", observationEpochId: "e1" }),
        fact({ assetRef: "date-only", observationEpochId: "e2", captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17" }),
        fact({ assetRef: "unknown", observationEpochId: "e3", captureStartedAt: null, captureEndedAt: null, captureDate: null }),
        fact({ assetRef: "other-area", observationEpochId: "e4", workAreaId: "area-2" }),
        fact({ assetRef: "foreign", observationEpochId: "e5", workAreaId: "area-9" }),
      ],
    }), "area-1");
    expect(groups.comparable.map((item) => item.assetRef)).toEqual(["exact"]);
    expect(groups.browsableDateOnly.map((item) => item.assetRef)).toEqual(["date-only"]);
    expect(groups.browsableUnknown.map((item) => item.assetRef)).toEqual(["unknown"]);
  });
});

describe("workspace ordinary entry", () => {
  it("uses the server-provided default even when it differs from recency", () => {
    const serverDefault = fact({ assetRef: "a-2021", observationEpochId: "epoch-2021" });
    const resolution = resolveOrdinaryEntry(facts({ serverDefault }));
    expect(resolution).toEqual({ status: "ready", basis: "server-default", workAreaId: "area-1", observation: serverDefault });
  });

  it("returns no-server-default instead of computing a client-side latest", () => {
    expect(resolveOrdinaryEntry(facts())).toEqual({ status: "no-server-default" });
    // 서버 기본이 승인 범위를 벗어나면 쓰지 않는다.
    expect(resolveOrdinaryEntry(facts({
      serverDefault: fact({ assetRef: "elsewhere", workAreaId: "area-9" }),
    }))).toEqual({ status: "no-server-default" });
    // 서버 기본이 목록에 없으면 쓰지 않는다.
    expect(resolveOrdinaryEntry(facts({
      serverDefault: fact({ assetRef: "ghost", workAreaId: "area-1" }),
    }))).toEqual({ status: "no-server-default" });
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
  it("restores an exact authorized observation and version", () => {
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
    const unavailable = resolveExplicitObservation(
      facts({ observations: [fact({ assetRef: "a-1", observationEpochId: "e1", viewAvailable: false })] }),
      { workAreaId: "area-1", observationEpochId: "e1", assetRef: "a-1" },
    );
    expect(unavailable).toMatchObject({ status: "unresolvable", reason: "unavailable" });
    // 어느 경우도 기본 관측·목록 첫 항목으로 바꾸지 않는다.
    for (const resolution of [malformed, foreign, unknownEpoch, unknownAsset, unavailable]) {
      expect(resolution.status).toBe("unresolvable");
      if (resolution.status === "unresolvable") {
        expect(resolution.headline.length).toBeGreaterThan(0);
        expect(resolution.detail).toContain("자동으로");
      }
    }
  });
});

describe("workspace explicit comparison links", () => {
  it("restores two exact versions of the same work area", () => {
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

  it("fails closed on identical, cross-area, unknown, or unavailable selectors", () => {
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
});
