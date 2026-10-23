import { describe, expect, it } from "vitest";

import {
  applyCatalogFilters,
  catalogCounts,
  groupAssetsByObservation,
  isViewableRasterKind,
  materialsHref,
  needsCatalogAttention,
  normalizeCatalogFilters,
  observationGroupDateLine,
  resolveVisualSelection,
  shortKindLabel,
} from "@/app/sites/[siteId]/spatial-assets/materials-visual";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";

const ref = (letter: string) => `ksa-v1-${letter.repeat(64)}`;

function item(
  assetRef: string,
  overrides: Partial<SpatialAssetCatalogItem> = {},
): SpatialAssetCatalogItem {
  return {
    assetRef,
    siteId: "site-1",
    workAreaId: "area-1",
    workOrderId: "order-1",
    observationEpochId: "epoch-1",
    submissionRef: `ers-v1-${"b".repeat(64)}`,
    revision: 2,
    artifactId: "artifact-1",
    kind: "dsm",
    lifecycleState: "SEALED",
    declared: {
      factClass: "DECLARED",
      fileName: "north-dsm.tif",
      format: "GeoTIFF",
      contentType: "image/tiff",
      sha256: "c".repeat(64),
      sizeBytes: 1234,
      crs: "EPSG:32652",
      verticalReference: null,
      gsdM: 0.05,
      submittedAt: "2026-09-30T01:00:00Z",
      producerCompletedAt: null,
      captureStartedAt: null,
      captureEndedAt: null,
    },
    observed: null,
    inspection: {
      state: "COMPLETED",
      outcome: "MEASURED",
      reason: null,
      reportDigest: null,
      inspectorBuildDigest: null,
      raster: null,
    },
    dataAccess: "NOT_AVAILABLE_FROM_CATALOG",
    analysisStatus: "NOT_EVALUATED",
    supportedActions: ["VIEW_METADATA"],
    ...overrides,
  } as unknown as SpatialAssetCatalogItem;
}

describe("materials visual selection", () => {
  const first = item(ref("a"));
  const second = item(ref("c"), { kind: "ortho" });

  it("defaults to the deterministic first catalog entry without preselecting B", () => {
    const selection = resolveVisualSelection({ pool: [first, second], visualARaw: undefined, visualBRaw: undefined });
    expect(selection.sideA?.assetRef).toBe(first.assetRef);
    expect(selection.sideB).toBeNull();
    expect(selection.mode).toBe("single");
    expect(selection.defaultedA).toBe(true);
  });

  it("reads the legacy assetRef as an explicit A without claiming a default", () => {
    const selection = resolveVisualSelection({
      pool: [first, second],
      visualARaw: undefined,
      visualBRaw: undefined,
      legacyRef: second.assetRef,
    });
    expect(selection.sideA?.assetRef).toBe(second.assetRef);
    expect(selection.legacyMapped).toBe(true);
    expect(selection.defaultedA).toBe(false);
  });

  it("resolves an exact A/B pair into independent compare mode", () => {
    const selection = resolveVisualSelection({
      pool: [first, second],
      visualARaw: first.assetRef,
      visualBRaw: second.assetRef,
    });
    expect(selection.mode).toBe("compare");
    expect(selection.sideA?.assetRef).toBe(first.assetRef);
    expect(selection.sideB?.assetRef).toBe(second.assetRef);
  });

  it("fails a malformed A closed without substituting another asset", () => {
    const selection = resolveVisualSelection({
      pool: [first, second],
      visualARaw: "not-a-ref",
      visualBRaw: undefined,
    });
    expect(selection.sideA).toBeNull();
    expect(selection.notices.invalidA).toBe(true);
    expect(selection.defaultedA).toBe(false);
  });

  it("fails a foreign B closed and keeps the valid A single", () => {
    const selection = resolveVisualSelection({
      pool: [first, second],
      visualARaw: first.assetRef,
      visualBRaw: ref("f"),
    });
    expect(selection.mode).toBe("single");
    expect(selection.sideA?.assetRef).toBe(first.assetRef);
    expect(selection.sideB).toBeNull();
    expect(selection.notices.foreignB).toBe(true);
  });

  it("fails a foreign legacy ref closed instead of defaulting silently", () => {
    const selection = resolveVisualSelection({
      pool: [first, second],
      visualARaw: undefined,
      visualBRaw: undefined,
      legacyRef: ref("f"),
    });
    expect(selection.sideA).toBeNull();
    expect(selection.notices.foreignA).toBe(true);
    expect(selection.defaultedA).toBe(false);
  });

  it("collapses an identical A/B pair to single with a notice", () => {
    const selection = resolveVisualSelection({
      pool: [first, second],
      visualARaw: first.assetRef,
      visualBRaw: first.assetRef,
    });
    expect(selection.mode).toBe("single");
    expect(selection.sideB).toBeNull();
    expect(selection.notices.samePair).toBe(true);
  });

  it("treats repeated query values as malformed, not as the first value", () => {
    const selection = resolveVisualSelection({
      pool: [first, second],
      visualARaw: [first.assetRef, second.assetRef],
      visualBRaw: undefined,
    });
    expect(selection.sideA).toBeNull();
    expect(selection.notices.invalidA).toBe(true);
  });
});

describe("materials href scope", () => {
  it("keeps work area, pair, legacy ref, filters and cursor in one key set", () => {
    const href = materialsHref("site-1", "area-1", {
      visualA: ref("a"),
      visualB: ref("c"),
      assetRef: ref("a"),
      q: "북측",
      kind: "dsm",
      state: "inspected",
      cursor: "opaque",
    });
    expect(href).toContain("workAreaId=area-1");
    expect(href).toContain(`visualAAssetRef=${ref("a")}`);
    expect(href).toContain(`visualBAssetRef=${ref("c")}`);
    expect(href).toContain(`assetRef=${ref("a")}`);
    expect(href).toContain("cursor=opaque");
    expect(href).toContain("kind=dsm");
    expect(href).toContain("state=inspected");
  });

  it("drops empty scopes instead of writing blank keys", () => {
    expect(materialsHref("site-1", "area-1")).toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
  });
});

describe("materials epoch grouping", () => {
  it("keeps Core order and isolates unidentified bundles", () => {
    const secondEpoch = item(ref("c"), { observationEpochId: "epoch-2" });
    const unidentified = item(ref("d"), { observationEpochId: "" });
    const groups = groupAssetsByObservation([secondEpoch, unidentified, item(ref("a"))]);
    expect(groups.map((group) => group.epochId)).toEqual(["epoch-2", "", "epoch-1"]);
    expect(groups[1]?.items).toHaveLength(1);
  });

  it("speaks a shared capture line only when the bundle agrees", () => {
    const dated = item(ref("a"), {
      declared: { ...item(ref("a")).declared, captureStartedAt: "2026-09-29T23:30:00Z", captureEndedAt: "2026-09-30T00:30:00Z" },
    });
    expect(observationGroupDateLine([dated, dated])).toContain("2026. 9. 30.");
    expect(observationGroupDateLine([dated, item(ref("c"))])).toBeNull();
  });

  it("marks only ortho and dsm as pixel-viewable", () => {
    expect(isViewableRasterKind("ortho")).toBe(true);
    expect(isViewableRasterKind("dsm")).toBe(true);
    expect(isViewableRasterKind("report")).toBe(false);
    expect(isViewableRasterKind("point_cloud")).toBe(false);
  });

  it("names rail kinds short without inventing unknown kinds", () => {
    expect(shortKindLabel("ortho")).toBe("정사영상");
    expect(shortKindLabel("dsm")).toBe("DSM");
    expect(shortKindLabel("dtm")).toBe("DTM");
    expect(shortKindLabel("report")).toBe("보고서");
    expect(shortKindLabel("point_cloud")).toBe("포인트 클라우드");
    expect(shortKindLabel("mystery-kind")).toBe("자료 종류 확인 필요");
  });
});

describe("materials catalog filtering", () => {
  const dsm = item(ref("a"));
  const ortho = item(ref("b"), {
    kind: "ortho",
    declared: { ...item(ref("b")).declared, fileName: "north-ortho.tif" },
  });
  const failed = item(ref("c"), {
    inspection: { ...item(ref("c")).inspection, state: "FAILED", outcome: "REJECTED", reason: "검사 정책 불일치" },
  });

  it("normalizes unsupported filter values to empty instead of echoing them", () => {
    expect(normalizeCatalogFilters({ q: "x".repeat(100), kind: "mystery", state: "bogus" })).toEqual({
      q: "x".repeat(80),
      kind: "",
      state: "",
    });
    expect(normalizeCatalogFilters({ kind: "ortho", state: "inspected" })).toEqual({
      q: "",
      kind: "ortho",
      state: "inspected",
    });
  });

  it("applies kind, inspection and text filters inside the loaded page only", () => {
    expect(applyCatalogFilters([dsm, ortho], normalizeCatalogFilters({ kind: "ortho" }))).toEqual([ortho]);
    expect(applyCatalogFilters([dsm, failed], normalizeCatalogFilters({ state: "inspected" }))).toEqual([dsm]);
    expect(applyCatalogFilters([dsm, ortho], normalizeCatalogFilters({ q: "ORTHO" }))).toEqual([ortho]);
    expect(applyCatalogFilters([dsm, ortho], normalizeCatalogFilters({ q: "없는파일" }))).toEqual([]);
    expect(applyCatalogFilters([dsm, ortho], normalizeCatalogFilters({}))).toEqual([dsm, ortho]);
  });

  it("treats failed and uninspected records as needing attention without blocking metadata", () => {
    const pending = item(ref("d"), {
      inspection: { ...item(ref("d")).inspection, state: "INSPECTION_PENDING", outcome: null },
    });
    expect(needsCatalogAttention(failed)).toBe(true);
    expect(needsCatalogAttention(pending)).toBe(true);
    expect(needsCatalogAttention(dsm)).toBe(false);
    expect(applyCatalogFilters([dsm, failed, pending], normalizeCatalogFilters({ state: "attention" }))).toEqual([failed, pending]);
  });

  it("counts the loaded page independent of the active filter", () => {
    expect(catalogCounts([dsm, ortho, failed])).toEqual({ total: 3, inspected: 2, attention: 1 });
    expect(catalogCounts([])).toEqual({ total: 0, inspected: 0, attention: 0 });
  });
});
