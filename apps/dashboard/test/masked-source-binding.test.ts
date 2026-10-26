import { describe, expect, it } from "vitest";

import type { AnalysisEvidencePage, AnalysisView } from "@/lib/core-api/analysis";
import { boundMaskedSourceIdentity } from "@/lib/masked-source-binding";

const digest = (letter: string) => `sha256:${letter.repeat(64)}`;
const view = { analysisId: "analysis-a", siteId: "site-a", workAreaId: "area-a",
  executionState: "FAILED", result: null, evidenceRevision: 3, evidenceDigest: digest("a") } as AnalysisView;
const page = { analysisId: "analysis-a", evidenceRevision: 3, evidenceDigest: digest("a"),
  items: [{ kind: "AUTHORITY_REFERENCE", referenceName: "calculationIdentityDigest",
    sourceDigest: digest("b"), digest: digest("c"), recordId: "ref-a", limitationCodes: [] }],
  nextCursor: null } satisfies AnalysisEvidencePage;

describe("masked calculation source binding", () => {
  it("uses the selected current AP identity without requiring a completed V2 numeric result", () => {
    expect(view.result).toBeNull();
    expect(boundMaskedSourceIdentity(view, [page])).toBe(digest("b"));
  });

  it.each(["analysis", "revision", "evidence", "missing", "ambiguous", "bad-digest"])(
    "rejects %s source facts rather than borrowing or inventing them", (change) => {
      const current = structuredClone(page);
      if (change === "analysis") current.analysisId = "another-analysis";
      if (change === "revision") current.evidenceRevision = 2;
      if (change === "evidence") current.evidenceDigest = digest("f");
      if (change === "missing") current.items = [];
      if (change === "ambiguous") current.items.push({ ...current.items[0]!, sourceDigest: digest("d") });
      if (change === "bad-digest") current.items[0]!.sourceDigest = "not-a-digest";
      expect(boundMaskedSourceIdentity(view, [current])).toBeNull();
    },
  );

  it("accepts repeated identical authority references but not a mixed-revision second page", () => {
    expect(boundMaskedSourceIdentity(view, [page, page])).toBe(digest("b"));
    expect(boundMaskedSourceIdentity(view, [page, { ...page, evidenceRevision: 4 }])).toBeNull();
    expect(boundMaskedSourceIdentity(view, [])).toBeNull();
  });
});
