/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetProvenanceNote } from "@/app/sites/[siteId]/spatial-assets/AssetProvenanceNote";

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

const description = {
  contractVersion: "spatial-asset-description.v1",
  assetRef: `ksa-v1-${"a".repeat(64)}`,
  siteId: "site-1",
  workAreaId: "area-1",
  producer: {
    factClass: "DECLARED",
    producerKnowledge: "PARTIAL",
    softwareName: "Pix4D",
    softwareVersion: "4.8",
    buildIdentifier: null,
    producerRunIdentifier: null,
    completedAt: null,
    sourceNote: null,
  },
  capture: {
    factClass: "DECLARED",
    captureBasis: "EXACT_INTERVAL",
    captureStartedAt: "2026-10-06T00:00:00Z",
    captureEndedAt: "2026-10-06T01:00:00Z",
    captureDate: null,
    rawMediaStoredByKsi: false,
    originalRetentionLocus: "customer_workstation",
    originalRetentionDetail: null,
    localInputManifestDigest: null,
    imageCount: 12,
  },
  raster: {
    factClass: "INSPECTED",
    sourceReportDigest: `sha256:${"1".repeat(64)}`,
    inspectorBuildDigest: `sha256:${"2".repeat(64)}`,
    bandCount: 1,
    dtype: "float32",
    layout: "GTiff",
    nodataRepresentation: "FINITE",
    nodataValue: -9999,
    validPixelCount: 900,
    horizontalUnits: "metre",
  },
};

function renderNote() {
  return render(<AssetProvenanceNote siteId="site-1" workAreaId="area-1" assetRef={description.assetRef} />);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("asset provenance note", () => {
  it("shows producer, capture and grid facts with digests tucked in details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(description)));
    renderNote();
    expect(await screen.findByText(/Pix4D 4.8 · 일부 정보만 제출/)).toBeTruthy();
    expect(screen.getByText(/원본 보관 고객 작업장/)).toBeTruthy();
    expect(screen.getByText(/1밴드 · float32 · GTiff · NoData 값 -9999 · 유효 픽셀 900/)).toBeTruthy();
    // 확인값은 펼침에만 둔다.
    const details = screen.getByText("확인값 보기").closest("details")!;
    expect(details.hasAttribute("open")).toBe(false);
    fireEvent.click(screen.getByText("확인값 보기"));
    expect(details.textContent).toContain(description.raster.sourceReportDigest);
  });

  it("hides the block when the description endpoint is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ message: "no route" }, 404)));
    const { container } = renderNote();
    await vi.waitFor(() => expect(vi.mocked(globalThis.fetch)).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("states unknown capture without inventing a time", async () => {
    const unknownCapture = {
      ...description,
      capture: { ...description.capture, captureBasis: "UNKNOWN", captureStartedAt: null, captureEndedAt: null },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(unknownCapture)));
    renderNote();
    expect(await screen.findByText(/관측 시점 미상 · 원본 보관 고객 작업장/)).toBeTruthy();
  });
});
