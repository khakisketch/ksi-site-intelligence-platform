import { describe, expect, it } from "vitest";

import {
  buildSitePreviewDescriptor,
  pickAreaPreviewJob,
  sanitizeSitePreviewDescriptor,
  SITE_PREVIEW_MAX_AREAS,
  SITE_PREVIEW_REQUESTS_PER_AREA,
  type SitePreviewAreaInput,
} from "@/lib/site-preview";
import type { SpatialDataJobView, SpatialDataReceipt } from "@/lib/core-api/spatial-data-types";

function receipt(overrides: Partial<SpatialDataReceipt> = {}): SpatialDataReceipt {
  return {
    jobId: "sdj-v1-00000000-0000-0000-0000-000000000001",
    receiptDigest: `sha256:${"a".repeat(64)}`,
    artifactKind: "ortho",
    outputSizeBytes: 1024,
    outputSha256: `sha256:${"b".repeat(64)}`,
    requestedBounds: [0, 0, 512, 512],
    actualBounds: [0, 0, 512, 512],
    pixelWindow: [0, 0, 512, 512],
    width: 512,
    height: 512,
    observedCrsIdentifier: "EPSG:7850",
    observedCrsDigest: `sha256:${"c".repeat(64)}`,
    accuracyAssessed: false,
    attribution: "Floreat public sample (CC BY 4.0)",
    modificationNotice: "Windowed crop; no reprojection.",
    limitations: [],
    preparedAt: "2026-10-21T00:00:00Z",
    ...overrides,
  };
}

function job(jobId: string, overrides: Partial<SpatialDataJobView> = {}): SpatialDataJobView {
  return {
    jobId,
    assetRef: `ksa-v1-${"a".repeat(64)}`,
    siteId: "site-1",
    workAreaId: "area-1",
    createdAt: "2026-10-21T00:00:00Z",
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    reason: null,
    remediation: [],
    receipt: receipt({ jobId }),
    ...overrides,
  };
}

function area(workAreaId = "area-1", name = "Floreat common-extent"): SitePreviewAreaInput {
  return { workAreaId, name };
}

describe("site preview selection", () => {
  const scope = { siteId: "site-1", workAreaId: "area-1" };
  it("bounds the fanout callers must respect", () => {
    expect(SITE_PREVIEW_MAX_AREAS).toBeLessThanOrEqual(6);
    expect(SITE_PREVIEW_REQUESTS_PER_AREA).toBeLessThanOrEqual(8);
  });

  it("prefers ortho over dsm without ranking by time", () => {
    const newerDsm = job("sdj-v1-00000000-0000-0000-0000-000000000002", {
      receipt: receipt({ artifactKind: "dsm", jobId: "sdj-v1-00000000-0000-0000-0000-000000000002" }),
    });
    const olderOrtho = job("sdj-v1-00000000-0000-0000-0000-000000000001", {
      createdAt: "2020-01-01T00:00:00Z",
      receipt: receipt({ artifactKind: "ortho", jobId: "sdj-v1-00000000-0000-0000-0000-000000000001" }),
    });
    // Core order is dsm-first here; the kind preference still wins, not recency.
    expect(pickAreaPreviewJob([newerDsm, olderOrtho], scope)?.jobId).toBe(olderOrtho.jobId);
    expect(pickAreaPreviewJob([olderOrtho, newerDsm], scope)?.jobId).toBe(olderOrtho.jobId);
  });

  it("keeps Core order within the same kind", () => {
    const first = job("sdj-v1-00000000-0000-0000-0000-000000000001");
    const second = job("sdj-v1-00000000-0000-0000-0000-000000000002");
    expect(pickAreaPreviewJob([first, second], scope)?.jobId).toBe(first.jobId);
    expect(pickAreaPreviewJob([second, first], scope)?.jobId).toBe(second.jobId);
  });

  it.each([
    ["QUEUED", "AVAILABLE"],
    ["RUNNING", "AVAILABLE"],
    ["FAILED", "AVAILABLE"],
    ["CANCELED", "AVAILABLE"],
    ["EXPIRED", "AVAILABLE"],
    ["COMPLETED", "NOT_READY"],
    ["COMPLETED", "ACCESS_REVOKED"],
    ["COMPLETED", "ACCESS_EXPIRED"],
    ["COMPLETED", "RETENTION_EXPIRED"],
    ["COMPLETED", "UNAVAILABLE"],
  ])("skips %s/%s — expired or unrighted bytes are never previewed", (executionState, availability) => {
    const expired = job("sdj-v1-00000000-0000-0000-0000-000000000009", {
      executionState: executionState as SpatialDataJobView["executionState"],
      availability: availability as SpatialDataJobView["availability"],
    });
    expect(pickAreaPreviewJob([expired], scope)).toBeNull();
  });

  it("skips jobs without a receipt", () => {
    expect(pickAreaPreviewJob([job("sdj-v1-00000000-0000-0000-0000-000000000001", { receipt: null })], scope)).toBeNull();
  });

  it("returns null on empty input without claiming anything", () => {
    expect(pickAreaPreviewJob([], scope)).toBeNull();
  });

  it("skips jobs from another site, area, or mismatched receipt", () => {
    const foreign = job("sdj-v1-00000000-0000-0000-0000-000000000001", { siteId: "site-9" });
    expect(pickAreaPreviewJob([foreign], scope)).toBeNull();
    const otherArea = job("sdj-v1-00000000-0000-0000-0000-000000000001", { workAreaId: "area-9" });
    expect(pickAreaPreviewJob([otherArea], scope)).toBeNull();
    const receiptMismatch = job("sdj-v1-00000000-0000-0000-0000-000000000001");
    receiptMismatch.receipt = { ...receiptMismatch.receipt!, jobId: "sdj-v1-00000000-0000-0000-0000-000000000009" };
    expect(pickAreaPreviewJob([receiptMismatch], scope)).toBeNull();
    const weirdKind = job("sdj-v1-00000000-0000-0000-0000-000000000001", {
      receipt: receipt({ artifactKind: "tiles_3d" as never, jobId: "sdj-v1-00000000-0000-0000-0000-000000000001" }),
    });
    expect(pickAreaPreviewJob([weirdKind], scope)).toBeNull();
  });
});

describe("partial labeling", () => {
  it("always marks the representative window as partial coverage", () => {
    for (const bounds of [
      [0, 0, 512, 512],
      [0, 0, 512, 256],
    ]) {
      const picked = buildSitePreviewDescriptor({
        siteId: "site-1",
        area: area(),
        job: job("sdj-v1-00000000-0000-0000-0000-000000000001"),
        receipt: receipt({ actualBounds: bounds as [number, number, number, number] }),
        asset: null,
      });
      expect(picked.partial).toBe(true);
    }
  });

  it("survives the client-side binding check as partial", () => {
    const picked = buildSitePreviewDescriptor({
      siteId: "site-1",
      area: area(),
      job: job("sdj-v1-00000000-0000-0000-0000-000000000001"),
      receipt: receipt(),
      asset: null,
    });
    const roundTripped = sanitizeSitePreviewDescriptor(JSON.parse(JSON.stringify(picked)), "site-1");
    expect(roundTripped?.partial).toBe(true);
    expect(roundTripped?.siteHref).toBe(picked.siteHref);
    expect(roundTripped?.fileHref).toBe(picked.fileHref);
  });
});

describe("site preview descriptor", () => {
  it("builds same-origin guarded paths and the exact site link", () => {
    const picked = buildSitePreviewDescriptor({
      siteId: "site-1",
      area: area(),
      job: job("sdj-v1-00000000-0000-0000-0000-000000000001"),
      receipt: receipt(),
      asset: {
        revision: 3,
        gsdM: 0.05,
        captureStartedAt: "2021-08-17T00:00:00Z",
        captureEndedAt: "2021-08-17T00:10:00Z",
        captureDate: "2021-08-17",
        attribution: "Floreat public sample (CC BY 4.0)",
      },
    });
    expect(picked.available).toBe(true);
    expect(picked.fileHref).toBe(
      "/api/sites/site-1/work-areas/area-1/spatial-data-requests/sdj-v1-00000000-0000-0000-0000-000000000001/file",
    );
    expect(picked.siteHref).toContain("/sites/site-1?workAreaId=area-1&assetRef=");
    expect(picked.siteHref).toContain(encodeURIComponent(`ksa-v1-${"a".repeat(64)}`));
    expect(picked.asset.revision).toBe(3);
  });

  it("marks partial output instead of claiming full-site coverage", () => {
    for (const bounds of [
      [0, 0, 512, 512],
      [0, 0, 512, 256],
    ]) {
      const picked = buildSitePreviewDescriptor({
        siteId: "site-1",
        area: area(),
        job: job("sdj-v1-00000000-0000-0000-0000-000000000001"),
        receipt: receipt({ actualBounds: bounds as [number, number, number, number] }),
        asset: null,
      });
      // Actual bounds equal to requested still does not prove whole asset/site.
      expect(picked.partial).toBe(true);
    }
  });

  it("degrades labels when asset detail is unreadable without inventing facts", () => {
    const picked = buildSitePreviewDescriptor({
      siteId: "site-1",
      area: area(),
      job: job("sdj-v1-00000000-0000-0000-0000-000000000001"),
      receipt: receipt(),
      asset: null,
    });
    expect(picked.asset.revision).toBeNull();
    expect(picked.asset.gsdM).toBeNull();
    expect(picked.asset.captureDate).toBeNull();
    // Attribution falls back to the receipt the job already carries.
    expect(picked.asset.attribution).toBe("Floreat public sample (CC BY 4.0)");
    // Bytes/identity stay intact — only labels degrade.
    expect(picked.outputSha256).toBe(`sha256:${"b".repeat(64)}`);
    expect(picked.outputSizeBytes).toBe(1024);
  });

  it("exposes no storage keys, signed URLs, or tokens", () => {
    const picked = buildSitePreviewDescriptor({
      siteId: "site-1",
      area: area(),
      job: job("sdj-v1-00000000-0000-0000-0000-000000000001"),
      receipt: receipt(),
      asset: null,
    });
    const serialized = JSON.stringify(picked);
    expect(picked.fileHref.startsWith("/api/")).toBe(true);
    expect(serialized).not.toMatch(/s3|signed|token|secret|key/i);
    expect(new URL(picked.fileHref, "https://console.local").origin).toBe("https://console.local");
  });
});

describe("site preview descriptor binding validation", () => {
  function validRaw() {
    return JSON.parse(JSON.stringify(buildSitePreviewDescriptor({
      siteId: "site-1",
      area: area(),
      job: job("sdj-v1-00000000-0000-0000-0000-000000000001"),
      receipt: receipt(),
      asset: null,
    })));
  }

  it("accepts the locally built shape", () => {
    const checked = sanitizeSitePreviewDescriptor(validRaw(), "site-1");
    expect(checked?.requestId).toBe("sdj-v1-00000000-0000-0000-0000-000000000001");
  });

  it("rejects foreign area, ref, request, digest, and shape", () => {
    const base = validRaw();
    expect(sanitizeSitePreviewDescriptor({ ...base, siteId: "site-9" }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor({ ...base, workAreaId: "area-9" }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor({ ...base, requestId: "sdj-v1-00000000-0000-0000-0000-000000000009" }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor({ ...base, assetRef: `ksa-v1-${"9".repeat(64)}` }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor({ ...base, artifactKind: "tiles_3d" }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor({ ...base, outputSha256: "sha256:xyz" }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor({ ...base, width: 0 }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor({ ...base, partial: "yes" }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor({ ...base, asset: null }, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor(null, "site-1")).toBeNull();
    expect(sanitizeSitePreviewDescriptor([], "site-1")).toBeNull();
  });

  it("rejects swapped URLs instead of trusting private paths", () => {
    const base = validRaw();
    const swappedFile = {
      ...base,
      fileHref: "/api/sites/site-9/work-areas/area-9/spatial-data-requests/sdj-v1-00000000-0000-0000-0000-000000000009/file",
    };
    expect(sanitizeSitePreviewDescriptor(swappedFile, "site-1")).toBeNull();
    const swappedSite = { ...base, siteHref: "/sites/other?x=1" };
    expect(sanitizeSitePreviewDescriptor(swappedSite, "site-1")).toBeNull();
    const absolute = { ...base, fileHref: "https://evil.invalid/f.tif", siteHref: "https://evil.invalid/" };
    expect(sanitizeSitePreviewDescriptor(absolute, "site-1")).toBeNull();
  });

  it("rebuilds hrefs from validated ids instead of trusting received strings", () => {
    const checked = sanitizeSitePreviewDescriptor(validRaw(), "site-1")!;
    expect(checked.fileHref).toBe(
      "/api/sites/site-1/work-areas/area-1/spatial-data-requests/sdj-v1-00000000-0000-0000-0000-000000000001/file",
    );
    expect(checked.siteHref.startsWith("/sites/site-1?workAreaId=area-1&assetRef=")).toBe(true);
  });
});

describe("site preview slot bounding", () => {
  it("allows two concurrent loads and queues the rest", async () => {
    const { acquirePreviewSlot, previewSlotState } = await import("@/lib/site-preview");
    const releases: Array<() => void> = [];
    releases.push(await acquirePreviewSlot());
    releases.push(await acquirePreviewSlot());
    expect(previewSlotState()).toEqual({ active: 2, queued: 0 });
    let thirdResolved = false;
    const third = acquirePreviewSlot().then((release) => {
      thirdResolved = true;
      return release;
    });
    await Promise.resolve();
    expect(thirdResolved).toBe(false);
    expect(previewSlotState()).toEqual({ active: 2, queued: 1 });
    releases.forEach((release) => release());
    const thirdRelease = await third;
    expect(thirdResolved).toBe(true);
    thirdRelease();
    expect(previewSlotState()).toEqual({ active: 0, queued: 0 });
  });

  it("removes a cancelled waiter immediately instead of leaking the queue", async () => {
    const { acquirePreviewSlot, previewSlotState } = await import("@/lib/site-preview");
    const hold = [await acquirePreviewSlot(), await acquirePreviewSlot()];
    const controller = new AbortController();
    let settled = "";
    const waiting = acquirePreviewSlot(controller.signal).then(
      () => { settled = "fired"; },
      () => { settled = "cancelled"; },
    );
    await Promise.resolve();
    expect(previewSlotState().queued).toBe(1);
    controller.abort();
    await waiting;
    expect(settled).toBe("cancelled");
    expect(previewSlotState()).toEqual({ active: 2, queued: 0 });
    // A fresh waiter still works after the cancellation.
    let freshResolved = false;
    const fresh = acquirePreviewSlot().then((release) => {
      freshResolved = true;
      return release;
    });
    hold.forEach((release) => release());
    const freshRelease = await fresh;
    expect(freshResolved).toBe(true);
    expect(previewSlotState().queued).toBe(0);
    freshRelease();
    expect(previewSlotState()).toEqual({ active: 0, queued: 0 });
  });
});
