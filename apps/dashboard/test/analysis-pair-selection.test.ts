import { describe, expect, it } from "vitest";

import {
  describePairSelection,
  isKnownBadPairSelection,
  shouldAutoSuggestBaseline,
} from "@/app/sites/[siteId]/analysis/pair-selection";

const area = "area-1";
const morning = { captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T00:30:00Z" };
const weekLater = { captureStartedAt: "2026-09-08T00:00:00Z", captureEndedAt: "2026-09-08T00:30:00Z" };

describe("describePairSelection", () => {
  it("names the missing piece in selection order", () => {
    expect(describePairSelection({ workAreaId: "", baseline: null, current: null, sameSelection: false }).kind).toBe("missing-area");
    expect(describePairSelection({ workAreaId: area, baseline: null, current: weekLater, sameSelection: false }).kind).toBe("missing-baseline");
    expect(describePairSelection({ workAreaId: area, baseline: morning, current: null, sameSelection: false }).kind).toBe("missing-current");
  });

  it("rejects the same observation even when its interval is valid", () => {
    const issue = describePairSelection({ workAreaId: area, baseline: morning, current: morning, sameSelection: true });
    expect(issue.kind).toBe("same");
    expect(issue.message).toContain("서로 다른 두 관측");
  });

  it("gates a time-reversed pair before POST without certifying fit", () => {
    const issue = describePairSelection({ workAreaId: area, baseline: weekLater, current: morning, sameSelection: false });
    expect(issue.kind).toBe("reversed");
    expect(issue.message).toContain("시간 역전");
    expect(issue.message).toContain("Core");
  });

  it("gates overlapping intervals while accepting a strictly earlier baseline", () => {
    const overlap = describePairSelection({
      workAreaId: area,
      baseline: { captureStartedAt: "2026-09-01T00:00:00Z", captureEndedAt: "2026-09-01T01:00:00Z" },
      current: { captureStartedAt: "2026-09-01T00:30:00Z", captureEndedAt: "2026-09-01T01:30:00Z" },
      sameSelection: false,
    });
    expect(overlap.kind).toBe("overlap");

    const tied = describePairSelection({ workAreaId: area, baseline: morning, current: { ...morning }, sameSelection: false });
    expect(tied.kind).toBe("overlap");

    const ready = describePairSelection({ workAreaId: area, baseline: morning, current: weekLater, sameSelection: false });
    expect(ready.kind).toBe("ready");
    expect(ready.message).toBe("");
  });

  it("treats unparsable or inverted capture windows as unknown, not as comparable", () => {
    for (const broken of [
      { baseline: { captureStartedAt: "not-a-time", captureEndedAt: "2026-09-01T00:30:00Z" }, current: weekLater },
      { baseline: morning, current: { captureStartedAt: "2026-09-08T00:30:00Z", captureEndedAt: "2026-09-08T00:00:00Z" } },
    ]) {
      const issue = describePairSelection({ workAreaId: area, baseline: broken.baseline, current: broken.current, sameSelection: false });
      expect(issue.kind).toBe("invalid-capture");
      expect(issue.message).toContain("촬영 구간을 확인하지 못했습니다");
    }
  });

  it("only gates known-bad chronology, never readiness itself", () => {
    expect(isKnownBadPairSelection("same")).toBe(true);
    expect(isKnownBadPairSelection("reversed")).toBe(true);
    expect(isKnownBadPairSelection("overlap")).toBe(true);
    expect(isKnownBadPairSelection("invalid-capture")).toBe(true);
    expect(isKnownBadPairSelection("ready")).toBe(false);
    expect(isKnownBadPairSelection("missing-area")).toBe(false);
    expect(isKnownBadPairSelection("missing-baseline")).toBe(false);
    expect(isKnownBadPairSelection("missing-current")).toBe(false);
  });

  it("auto-suggests a baseline only while none is chosen", () => {
    expect(shouldAutoSuggestBaseline("")).toBe(true);
    expect(shouldAutoSuggestBaseline("1")).toBe(false);
  });
});
