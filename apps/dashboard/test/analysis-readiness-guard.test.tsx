import { describe, expect, it } from "vitest";

import {
  isAnalysisReadinessView,
  isAnalysisReadinessViewFor,
  type AnalysisReadinessViewV1,
} from "@/lib/analysis-readiness";

const selectorA = { workOrderId: "work-a", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 };
const selectorB = { workOrderId: "work-b", submissionRef: `ers-v1-${"b".repeat(64)}`, revision: 2 };

function view(overrides: Record<string, unknown> = {}) {
  return {
    contractVersion: "analysis-readiness.v1",
    siteId: "site-1",
    workAreaId: "area-1",
    baseline: { ...selectorA },
    current: { ...selectorB },
    suitabilityState: "BLOCKED",
    blockers: [{ code: "READINESS_DSM_UNAVAILABLE", epoch: "BASELINE", evidenceRef: null, detail: null }],
    limitationCodes: [],
    checkedAt: "2026-10-20T00:00:00Z",
    calculationIdentityDigest: null,
    coverageCheck: "REQUIRES_WORKER_VALIDATION",
    ...overrides,
  };
}

describe("analysis readiness guard", () => {
  it("accepts a well-formed blocked view", () => {
    expect(isAnalysisReadinessView(view())).toBe(true);
  });

  it("accepts a provisional view carrying limitations", () => {
    expect(isAnalysisReadinessView(view({
      suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED",
      blockers: [],
      limitationCodes: ["PROVISIONAL_ACCURACY_UNVERIFIED"],
    }))).toBe(true);
  });

  it.each([
    ["wrong contract", { contractVersion: "analysis-readiness.v0" }],
    ["missing site", { siteId: "" }],
    ["unknown state", { suitabilityState: "READY" }],
    ["overlong blockers", { blockers: Array.from({ length: 129 }, () => ({ code: "X", epoch: null, evidenceRef: null, detail: null })) }],
    ["malformed blocker code", { blockers: [{ code: "lowercase", epoch: null, evidenceRef: null, detail: null }] }],
    ["malformed blocker epoch", { blockers: [{ code: "READINESS_DSM_UNAVAILABLE", epoch: "MIDDLE", evidenceRef: null, detail: null }] }],
    ["overlong blocker detail", { blockers: [{ code: "READINESS_DSM_UNAVAILABLE", epoch: null, evidenceRef: null, detail: "x".repeat(513) }] }],
    ["non-UTC checkedAt", { checkedAt: "2026-10-20T09:00:00+09:00" }],
    ["unparseable checkedAt", { checkedAt: "not-a-time" }],
    ["malformed digest", { calculationIdentityDigest: "sha256:zzz" }],
    ["wrong coverage check", { coverageCheck: "VERIFIED" }],
  ])("rejects %s", (_label, overrides) => {
    expect(isAnalysisReadinessView(view(overrides))).toBe(false);
  });

  it.each([
    ["blocked without blockers", "BLOCKED", [], []],
    ["remediation without blockers", "REMEDIATION_REQUIRED", [], []],
    ["reassessment without blockers", "REASSESSMENT_REQUIRED", [], []],
    ["evaluated with blockers", "EVALUATED", [{ code: "READINESS_DSM_UNAVAILABLE", epoch: null, evidenceRef: null, detail: null }], []],
    ["provisional with blockers", "PROVISIONAL_ACCURACY_UNVERIFIED", [{ code: "READINESS_DSM_UNAVAILABLE", epoch: null, evidenceRef: null, detail: null }], []],
    ["non-provisional with limitations", "BLOCKED", [{ code: "READINESS_DSM_UNAVAILABLE", epoch: null, evidenceRef: null, detail: null }], ["PROVISIONAL_ACCURACY_UNVERIFIED"]],
  ])("rejects cross-field mismatch %s", (_label, suitabilityState, blockers, limitationCodes) => {
    expect(isAnalysisReadinessView(view({ suitabilityState, blockers, limitationCodes }))).toBe(false);
  });

  it("verifies the echoed pair before display", () => {
    const ready = view({
      suitabilityState: "EVALUATED",
      blockers: [],
    }) as unknown as AnalysisReadinessViewV1;
    expect(isAnalysisReadinessView(ready)).toBe(true);
    const expected = { siteId: "site-1", workAreaId: "area-1", baseline: selectorA, current: selectorB };
    expect(isAnalysisReadinessViewFor(ready, expected)).toBe(true);
    expect(isAnalysisReadinessViewFor(ready, { ...expected, siteId: "site-other" })).toBe(false);
    expect(isAnalysisReadinessViewFor(ready, { ...expected, workAreaId: "area-2" })).toBe(false);
    expect(isAnalysisReadinessViewFor(ready, { ...expected, current: { ...selectorB, revision: 9 } })).toBe(false);
  });
});
