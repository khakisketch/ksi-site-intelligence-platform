import { describe, expect, it } from "vitest";
import { resolveSiteAreaNextAction } from "@/app/sites/[siteId]/SiteAreaNextAction";
import { parseVisualBrowsingContext } from "@/lib/operator-journey";

const a = `ksa-v1-${"a".repeat(64)}`, b = `ksa-v1-${"b".repeat(64)}`;
const query = new URLSearchParams({ workAreaId: "area-1", visualAAssetRef: a, visualBAssetRef: b,
  hintBaselineWorkOrderId: "work-a", hintBaselineSubmissionRef: `ers-v1-${"a".repeat(64)}`, hintBaselineRevision: "1",
  hintCurrentWorkOrderId: "work-b", hintCurrentSubmissionRef: `ers-v1-${"b".repeat(64)}`, hintCurrentRevision: "2" });
const input = { sitePath: "/sites/site-1", workAreaId: "area-1", workAreaStatus: "ACTIVE" as const,
  canCreateWorkOrder: false, canCreateAnalysis: true, latestAnalysis: { workAreaId: "area-1", analysisId: "record-1" } };

describe("area actions with an independent pair", () => {
  it("merges one scope while retaining the exact fixed record and return pair", () => {
    const action = resolveSiteAreaNextAction({ ...input, pairQuery: query.toString() });
    const primary = new URL(action.primary.href, "https://console.test");
    expect(primary.searchParams.getAll("workAreaId")).toEqual(["area-1"]);
    expect(primary.searchParams.get("analysisId")).toBe("record-1");
    expect(primary.hash).toBe("");
    expect(parseVisualBrowsingContext(Object.fromEntries(primary.searchParams))).toEqual({
      workAreaId: "area-1", visualAAssetRef: a, visualBAssetRef: b,
    });
    const draft = new URL(action.secondaryCompareHref!, "https://console.test");
    expect(draft.searchParams.getAll("workAreaId")).toEqual(["area-1"]);
    expect(draft.hash).toBe("#new-analysis-request");
    expect(draft.searchParams.has("analysisId")).toBe(false);
    expect(draft.searchParams.get("hintCurrentRevision")).toBe("2");
    const materials = new URL(action.materialsHref!, "https://console.test");
    expect(materials.searchParams.getAll("workAreaId")).toEqual(["area-1"]);
    expect(materials.searchParams.get("visualAAssetRef")).toBe(a);
    expect(materials.searchParams.has("hintCurrentRevision")).toBe(false);
  });

  it("cannot use a browsing query to overwrite a fixed analysis identity", () => {
    const q = new URLSearchParams(query); q.set("analysisId", "other-record"); q.set("returnTo", "https://outside.test");
    const href = resolveSiteAreaNextAction({ ...input, pairQuery: q.toString() }).primary.href;
    const parsed = new URL(href, "https://console.test");
    expect(parsed.searchParams.get("analysisId")).toBe("record-1");
    expect(parsed.searchParams.has("returnTo")).toBe(false);
  });

  it.each([`${query}&workAreaId=area-1`, `${query}&visualAAssetRef=${b}`, query.toString().replace("area-1", "area-2")])(
    "does not propagate repeated or contradictory context: %s", (pairQuery) => {
      const action = resolveSiteAreaNextAction({ ...input, pairQuery });
      expect(action.primary.href).not.toContain("visualAAssetRef");
      expect(action.primary.href).toContain("analysisId=record-1");
    },
  );
});
