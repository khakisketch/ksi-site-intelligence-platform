import { describe, expect, it } from "vitest";

import {
  resolveExactAnalysisSelectorHints,
  parseVisualBrowsingContext,
  visualBrowsingReturnHref,
} from "@/lib/operator-journey";
import {
  resolveExplicitComparison,
  resolveExplicitVisualPair,
  type WorkspaceObservationFact,
  type WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";
import {
  analysisHandoffHref,
  exactAnalysisHintParams,
  pairQueryString,
  visualLayersForExactSubmission,
  visualPairCatalogOptions,
} from "@/app/sites/[siteId]/site-visual-pair";

const ref = (digit: string) => `ksa-v1-${digit.repeat(64)}`;
const SUB_A = `ers-v1-${"a".repeat(64)}`;
const SUB_B = `ers-v1-${"b".repeat(64)}`;

function fact(overrides: Partial<WorkspaceObservationFact> = {}): WorkspaceObservationFact {
  const { assetRef = ref("1"), ...rest } = overrides;
  return {
    observationEpochId: "epoch-1",
    workAreaId: "area-1",
    workOrderId: "w-1",
    submissionRef: SUB_A,
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
      fact({ assetRef: ref("1"), observationEpochId: "epoch-2021", submissionRef: SUB_A }),
      fact({ assetRef: ref("2"), observationEpochId: "epoch-2022", submissionRef: SUB_B, captureStartedAt: "2022-08-24T10:00:00Z", captureEndedAt: "2022-08-24T11:00:00Z", revision: 2 }),
    ],
    analyses: [],
    ...overrides,
  };
}

describe("explicit visual pair (independent inspection)", () => {
  it("puts two date-only records side by side without claiming chronological order", () => {
    const base = facts({
      observations: [
        fact({ assetRef: ref("1"), observationEpochId: "epoch-d1", submissionRef: SUB_A, chronologyCandidate: false, displayReady: true, viewAvailable: true, captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17" }),
        fact({ assetRef: ref("2"), observationEpochId: "epoch-d2", submissionRef: SUB_B, chronologyCandidate: false, displayReady: true, viewAvailable: true, captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-18" }),
      ],
    });
    // Strict quantitative comparison still refuses date-only records.
    expect(resolveExplicitComparison(base, {
      workAreaId: "area-1",
      baselineAssetRef: ref("1"),
      currentAssetRef: ref("2"),
    })).toMatchObject({ status: "unresolvable" });
    // The visual pair resolves them exactly as the user's explicit A/B choice.
    const visual = resolveExplicitVisualPair(base, {
      workAreaId: "area-1",
      visualAAssetRef: ref("1"),
      visualBAssetRef: ref("2"),
    });
    expect(visual).toMatchObject({ status: "ready", basis: "explicit-visual", sideA: { assetRef: ref("1") }, sideB: { assetRef: ref("2") } });
  });

  it("puts unknown-capture records side by side without inventing timestamps", () => {
    const base = facts({
      observations: [
        fact({ assetRef: ref("3"), observationEpochId: "epoch-u1", submissionRef: SUB_A, chronologyCandidate: false, captureStartedAt: null, captureEndedAt: null, captureDate: null }),
        fact({ assetRef: ref("4"), observationEpochId: "epoch-u2", submissionRef: SUB_B, chronologyCandidate: false, captureStartedAt: null, captureEndedAt: null, captureDate: null }),
      ],
    });
    const visual = resolveExplicitVisualPair(base, {
      workAreaId: "area-1",
      visualAAssetRef: ref("3"),
      visualBAssetRef: ref("4"),
    });
    expect(visual.status).toBe("ready");
  });

  it("stays ready for sealed/unviewable records without substituting them", () => {
    const base = facts({
      observations: [
        fact({ assetRef: ref("5"), observationEpochId: "epoch-s", submissionRef: SUB_A, displayReady: false, viewAvailable: false, viewUnavailableReason: "봉인 전" }),
        fact({ assetRef: ref("6"), observationEpochId: "epoch-o", submissionRef: SUB_B }),
      ],
    });
    const visual = resolveExplicitVisualPair(base, {
      workAreaId: "area-1",
      visualAAssetRef: ref("5"),
      visualBAssetRef: ref("6"),
    });
    // Candidate exists != pixels available: identities stay, the guarded
    // viewer alone reports actual prepared-output readability.
    expect(visual).toMatchObject({ status: "ready", sideA: { assetRef: ref("5") }, sideB: { assetRef: ref("6") } });
  });

  it("fails closed on repeated, foreign, cross-area, unknown, and repeated-array selectors", () => {
    const base = facts();
    expect(resolveExplicitVisualPair(base, {
      workAreaId: "area-1", visualAAssetRef: ref("1"), visualBAssetRef: ref("1"),
    })).toMatchObject({ status: "unresolvable", reason: "identical-selectors" });
    expect(resolveExplicitVisualPair(base, {
      workAreaId: "nope", visualAAssetRef: ref("1"), visualBAssetRef: ref("2"),
    })).toMatchObject({ status: "unresolvable", reason: "foreign-work-area" });
    expect(resolveExplicitVisualPair(base, {
      workAreaId: "area-1", visualAAssetRef: ref("1"), visualBAssetRef: ref("9"),
    })).toMatchObject({ status: "unresolvable", reason: "unknown-asset" });
    expect(resolveExplicitVisualPair(base, {
      workAreaId: "area-1", visualAAssetRef: "", visualBAssetRef: ref("2"),
    })).toMatchObject({ status: "unresolvable", reason: "malformed" });
    // Repeated query arrays are never collapsed to a first value.
    expect(resolveExplicitVisualPair(base, {
      workAreaId: "area-1", visualAAssetRef: [ref("1"), ref("2")], visualBAssetRef: ref("2"),
    })).toMatchObject({ status: "unresolvable", reason: "malformed" });
    const crossArea = facts({
      observations: [
        fact({ assetRef: ref("7"), observationEpochId: "epoch-x", workAreaId: "area-1", submissionRef: SUB_A }),
        fact({ assetRef: ref("8"), observationEpochId: "epoch-y", workAreaId: "area-2", submissionRef: SUB_B }),
      ],
    });
    expect(resolveExplicitVisualPair(crossArea, {
      workAreaId: "area-1", visualAAssetRef: ref("7"), visualBAssetRef: ref("8"),
    })).toMatchObject({ status: "unresolvable", reason: "cross-area-comparison" });
  });
});

describe("visual layer pinning (exact workArea/workOrder/epoch/submission/version)", () => {
  const catalog = [
    { assetRef: ref("1"), workAreaId: "area-1", workOrderId: "w-1", observationEpochId: "epoch-1", kind: "ortho", submissionRef: SUB_A, revision: 1, declared: { fileName: "o1.tif" }, inspection: { raster: null, outcome: "PASS" } },
    { assetRef: ref("2"), workAreaId: "area-1", workOrderId: "w-1", observationEpochId: "epoch-1", kind: "dsm", submissionRef: SUB_A, revision: 1, declared: { fileName: "d1.tif" }, inspection: { raster: null, outcome: "PASS" } },
    { assetRef: ref("3"), workAreaId: "area-1", workOrderId: "w-1", observationEpochId: "epoch-1", kind: "ortho", submissionRef: SUB_B, revision: 2, declared: { fileName: "o2.tif" }, inspection: { raster: null, outcome: "PASS" } },
    { assetRef: ref("4"), workAreaId: "area-2", workOrderId: "w-9", observationEpochId: "epoch-1", kind: "ortho", submissionRef: SUB_A, revision: 1, declared: { fileName: "o3.tif" }, inspection: { raster: null, outcome: "PASS" } },
  ] as never;

  it("never substitutes another revision, area, or work order when switching layers", () => {
    const layers = visualLayersForExactSubmission(catalog, fact({ workAreaId: "area-1", workOrderId: "w-1", submissionRef: SUB_A, revision: 1, kind: "ortho" }));
    expect(layers.map((item) => item.assetRef).toSorted()).toEqual([ref("1"), ref("2")]);
    expect(layers.some((item) => item.assetRef === ref("3"))).toBe(false);
    expect(layers.some((item) => item.assetRef === ref("4"))).toBe(false);
  });

  it("refuses contradictory revision facts for an equal opaque reference", () => {
    const catalog = [
      { assetRef: "disp-2022", workAreaId: "tiny-1", workOrderId: "w1", observationEpochId: "epoch-2021", kind: "dsm", submissionRef: "s1", revision: 2, declared: { fileName: "tile.tif" }, inspection: { raster: null, outcome: "PASS" } },
    ] as never;
    const selected = fact({ assetRef: "disp-2022", workAreaId: "tiny-1", workOrderId: "w1", observationEpochId: "epoch-2021", submissionRef: "s1", revision: 1, kind: "dsm" });
    const layers = visualLayersForExactSubmission(catalog, selected);
    expect(layers).toEqual([]);
    expect(visualLayersForExactSubmission(catalog, { ...selected, revision: 2 }).map((item) => item.assetRef)).toEqual(["disp-2022"]);
  });

  it("builds one canonical handoff carrying hints and return refs together", () => {
    const params = exactAnalysisHintParams(
      fact({ workOrderId: "w-a", submissionRef: SUB_A, revision: 3 }),
      fact({ workOrderId: "w-b", submissionRef: SUB_B, revision: 1 }),
    );
    expect(params).toMatchObject({
      hintBaselineWorkOrderId: "w-a",
      hintBaselineSubmissionRef: SUB_A,
      hintBaselineRevision: "3",
      hintCurrentWorkOrderId: "w-b",
    });
    const href = analysisHandoffHref("/sites/s1", "area-1",
      fact({ workOrderId: "w-a", assetRef: ref("1"), submissionRef: SUB_A, revision: 3 }),
      fact({ workOrderId: "w-b", assetRef: ref("2"), submissionRef: SUB_B, revision: 1 }));
    expect(href).toContain("workAreaId=area-1");
    expect(href).toContain("hintBaselineSubmissionRef=");
    expect(new URL(href, "https://console.test").hash).toBe("#new-analysis-request");
    expect(href).toContain(`visualAAssetRef=${encodeURIComponent(ref("1"))}`);
    expect(href).toContain(`visualBAssetRef=${encodeURIComponent(ref("2"))}`);
    expect(href).not.toContain("assetRef=%2F");
    expect(href).not.toContain("returnTo");
    expect(pairQueryString("area-1", fact({ assetRef: ref("1") }), fact({ assetRef: ref("2") }))).toContain("visualAAssetRef=");
  });
});

describe("visual pair catalog options (all bound revisions, never replaced)", () => {
  const catalog = [
    { ...fact({ assetRef: ref("1"), kind: "ortho" }), declared: { fileName: "o1.tif" }, inspection: { raster: { width: 4, height: 4 }, outcome: "PASS" } },
    { ...fact({ assetRef: ref("2"), kind: "dsm" }), declared: { fileName: "d1.tif" }, inspection: { raster: { width: 4, height: 4 }, outcome: "PASS" } },
    { ...fact({ assetRef: ref("3"), kind: "ortho", revision: 2 }), declared: { fileName: "o2.tif" }, inspection: { raster: { width: 4, height: 4 }, outcome: "PASS" } },
  ] as never;

  it("lists every bound revision instead of one representative per observation", () => {
    const groups = visualPairCatalogOptions({
      facts: [
        fact({ assetRef: ref("1"), observationEpochId: "epoch-1", revision: 1, kind: "ortho" }),
        fact({ assetRef: ref("2"), observationEpochId: "epoch-1", revision: 1 }),
        fact({ assetRef: ref("3"), observationEpochId: "epoch-1", revision: 2, kind: "ortho" }),
      ],
      workAreaId: "area-1",
      catalogAssets: catalog,
      selectedRefs: [],
    });
    const total = groups.reduce((count, group) => count + group.options.length, 0);
    expect(total).toBe(3);
  });

  it("does not turn an unbound requested reference into a selectable current asset", () => {
    const groups = visualPairCatalogOptions({
      facts: [fact({ assetRef: ref("1"), observationEpochId: "epoch-1", kind: "ortho" }), fact({ assetRef: ref("9"), observationEpochId: "epoch-9" })],
      workAreaId: "area-1",
      catalogAssets: catalog,
      selectedRefs: [ref("9")],
    });
    const total = groups.reduce((count, group) => count + group.options.length, 0);
    expect(total).toBe(1);
    expect(groups.some((group) => group.options.some((item) => item.assetRef === ref("9")))).toBe(false);
  });
});

describe("visual browsing context round-trip", () => {
  it("accepts a canonical pair and restores it on return", () => {
    const context = parseVisualBrowsingContext({
      workAreaId: "area-1",
      visualAAssetRef: ref("1"),
      visualBAssetRef: ref("2"),
    });
    expect(context).not.toBeNull();
    const href = visualBrowsingReturnHref("/sites/s1", context, "area-1");
    expect(href).toContain("mode=compare");
    expect(href).toContain("visualAAssetRef=");
    expect(href).toContain("visualBAssetRef=");
  });

  it("resets the pair transparently when the area changes", () => {
    const context = parseVisualBrowsingContext({
      workAreaId: "area-1",
      visualAAssetRef: ref("1"),
      visualBAssetRef: ref("2"),
    });
    const href = visualBrowsingReturnHref("/sites/s1", context, "area-2");
    expect(href).toBe("/sites/s1?mode=compare&workAreaId=area-2");
    expect(href).not.toContain("visualAAssetRef");
  });

  it("rejects repeated, malformed, non-wire-shaped, and partial refs", () => {
    expect(parseVisualBrowsingContext({ workAreaId: "area-1", visualAAssetRef: ref("1"), visualBAssetRef: ref("1") })).toBeNull();
    expect(parseVisualBrowsingContext({ workAreaId: "", visualAAssetRef: ref("1"), visualBAssetRef: ref("2") })).toBeNull();
    expect(parseVisualBrowsingContext({ workAreaId: "area-1", visualAAssetRef: "http://evil/x", visualBAssetRef: ref("2") })).toBeNull();
    expect(parseVisualBrowsingContext({ workAreaId: "area-1", visualAAssetRef: "a-1", visualBAssetRef: ref("2") })).toBeNull();
    expect(parseVisualBrowsingContext({ workAreaId: "area-1", visualAAssetRef: [ref("1")], visualBAssetRef: ref("2") })).toBeNull();
    expect(parseVisualBrowsingContext({ workAreaId: "area-1", visualAAssetRef: ref("1") })).toBeNull();
    expect(visualBrowsingReturnHref("/sites/s1", null, "area-1")).toBe("/sites/s1?mode=compare&workAreaId=area-1");
  });
});

describe("exact analysis selector hints (no WorkOrder approximation)", () => {
  const candidates = [
    { selector: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 }, workAreaIds: ["area-1"] },
    { selector: { workOrderId: "w-b", submissionRef: SUB_B, revision: 2 }, workAreaIds: ["area-1"] },
    { selector: { workOrderId: "w-c", submissionRef: SUB_A, revision: 1 }, workAreaIds: ["area-2"] },
  ];

  it("preselects only on an exact triple match in the same area", () => {
    const resolved = resolveExactAnalysisSelectorHints({
      candidates,
      workAreaId: "area-1",
      rawBaseline: { workOrderId: "w-a", submissionRef: SUB_A, revision: "1" },
      rawCurrent: { workOrderId: "w-b", submissionRef: SUB_B, revision: 2 },
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(resolved.notice).toBeNull();
    expect(resolved.baseline).toMatchObject({ workOrderId: "w-a", revision: 1 });
    expect(resolved.current).toMatchObject({ workOrderId: "w-b", revision: 2 });
  });

  it("leaves the form unset with a notice for non-candidates, wrong area, and ambiguity", () => {
    const missing = resolveExactAnalysisSelectorHints({
      candidates,
      workAreaId: "area-1",
      rawBaseline: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 },
      rawCurrent: { workOrderId: "w-ghost", submissionRef: SUB_B, revision: 2 },
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(missing.baseline).toBeNull();
    expect(missing.current).toBeNull();
    expect(missing.notice).toMatch(/확인하지 못했|직접 선택/);

    const foreignArea = resolveExactAnalysisSelectorHints({
      candidates,
      workAreaId: "area-1",
      rawBaseline: { workOrderId: "w-c", submissionRef: SUB_A, revision: 1 },
      rawCurrent: undefined,
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(foreignArea.baseline).toBeNull();
    expect(foreignArea.notice).toMatch(/맞지 않|직접 선택/);

    const ambiguousCandidates = [
      { selector: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 }, workAreaIds: ["area-1"] },
      { selector: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 }, workAreaIds: ["area-1", "area-9"] },
    ];
    const ambiguous = resolveExactAnalysisSelectorHints({
      candidates: ambiguousCandidates,
      workAreaId: "area-1",
      rawBaseline: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 },
      rawCurrent: undefined,
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(ambiguous.baseline).toBeNull();
    expect(ambiguous.notice).toMatch(/자동으로 고르지/);
  });

  it("never prefills on malformed hints, identical pairs, deep links, or pending attempts", () => {
    const malformed = resolveExactAnalysisSelectorHints({
      candidates,
      workAreaId: "area-1",
      rawBaseline: { workOrderId: "w-a", submissionRef: "not-a-ref", revision: 1 },
      rawCurrent: undefined,
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(malformed.baseline).toBeNull();
    expect(malformed.notice).not.toBeNull();

    // Repeated query arrays are invalid, never collapsed.
    const repeated = resolveExactAnalysisSelectorHints({
      candidates,
      workAreaId: "area-1",
      rawBaseline: { workOrderId: ["w-a", "w-b"], submissionRef: SUB_A, revision: 1 },
      rawCurrent: undefined,
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(repeated.baseline).toBeNull();
    expect(repeated.notice).not.toBeNull();

    // No hint fields at all: ordinary visit, no missing-selection warning.
    const ordinary = resolveExactAnalysisSelectorHints({
      candidates,
      workAreaId: "area-1",
      rawBaseline: undefined,
      rawCurrent: undefined,
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(ordinary).toEqual({ baseline: null, current: null, notice: null });

    const identical = resolveExactAnalysisSelectorHints({
      candidates: [
        ...candidates,
        { selector: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 }, workAreaIds: ["area-1"] },
      ],
      workAreaId: "area-1",
      rawBaseline: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 },
      rawCurrent: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 },
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(identical.baseline).toBeNull();
    expect(identical.current).toBeNull();

    for (const flags of [{ hasPendingAttempt: true, hasAnalysisDeepLink: false }, { hasPendingAttempt: false, hasAnalysisDeepLink: true }]) {
      const frozen = resolveExactAnalysisSelectorHints({
        candidates,
        workAreaId: "area-1",
        rawBaseline: { workOrderId: "w-a", submissionRef: SUB_A, revision: 1 },
        rawCurrent: { workOrderId: "w-b", submissionRef: SUB_B, revision: 2 },
        ...flags,
      });
      expect(frozen).toEqual({ baseline: null, current: null, notice: null });
    }
  });
});
