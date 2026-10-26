/** @vitest-environment jsdom */
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetProvenanceNote } from "@/app/sites/[siteId]/spatial-assets/AssetProvenanceNote";

const firstRef = `ksa-v1-${"a".repeat(64)}`;
const secondRef = `ksa-v1-${"b".repeat(64)}`;

function description(assetRef: string, name: string) {
  return {
    contractVersion: "spatial-asset-description.v1",
    siteId: "site-1",
    workAreaId: "area-1",
    assetRef,
    producer: {
      factClass: "DECLARED",
      producerKnowledge: "DECLARED",
      softwareName: name,
      softwareVersion: null,
      buildIdentifier: null,
      producerRunIdentifier: null,
      completedAt: null,
      sourceNote: null,
    },
    capture: {
      factClass: "DECLARED",
      captureBasis: "UNKNOWN",
      captureStartedAt: null,
      captureEndedAt: null,
      captureDate: null,
      rawMediaStoredByKsi: false,
      originalRetentionLocus: "unknown",
      originalRetentionDetail: null,
      localInputManifestDigest: null,
      imageCount: null,
    },
    raster: null,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function note(assetRef: string) {
  return <AssetProvenanceNote siteId="site-1" workAreaId="area-1" assetRef={assetRef} />;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("asset provenance is bound to the exact current selection", () => {
  it("removes A immediately when B is selected, even when B returns 404", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(description(firstRef, "Producer A")))
      .mockResolvedValueOnce(json({ message: "not found" }, 404));
    vi.stubGlobal("fetch", fetch);
    const view = render(note(firstRef));
    expect(await screen.findByText(/Producer A/)).toBeTruthy();

    view.rerender(note(secondRef));
    expect(screen.queryByText(/Producer A/)).toBeNull();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("region", { name: "제작·촬영·격자 출처" })).toBeNull();
  });

  it("ignores a late A response after B has rendered, even if transport ignores abort", async () => {
    let finishFirst!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finishFirst = resolve; });
    const fetch = vi.fn()
      .mockReturnValueOnce(pending)
      .mockResolvedValueOnce(json(description(secondRef, "Producer B")));
    vi.stubGlobal("fetch", fetch);
    const view = render(note(firstRef));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    view.rerender(note(secondRef));
    expect(await screen.findByText(/Producer B/)).toBeTruthy();

    await act(async () => {
      finishFirst(json(description(firstRef, "Producer A")));
      await Promise.resolve();
    });
    expect(screen.getByText(/Producer B/)).toBeTruthy();
    expect(screen.queryByText(/Producer A/)).toBeNull();
  });

  it.each(["assetRef", "siteId", "workAreaId"] as const)(
    "does not render a mismatched %s echo",
    async (field) => {
      const wrong = {
        ...description(secondRef, "Unbound producer"),
        [field]: field === "assetRef" ? firstRef : "outside-current-scope",
      };
      const fetch = vi.fn().mockResolvedValue(json(wrong));
      vi.stubGlobal("fetch", fetch);
      render(note(secondRef));
      await act(async () => { await Promise.resolve(); });
      expect(fetch).toHaveBeenCalledOnce();
      expect(screen.queryByRole("region", { name: "제작·촬영·격자 출처" })).toBeNull();
      expect(screen.queryByText(/Unbound producer/)).toBeNull();
    },
  );

  it("hides an unusable producer/capture shape instead of crashing or retaining facts", async () => {
    const fetch = vi.fn().mockResolvedValue(json({
      ...description(secondRef, "Unusable"), producer: null, capture: null,
    }));
    vi.stubGlobal("fetch", fetch);
    render(note(secondRef));
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByRole("region", { name: "제작·촬영·격자 출처" })).toBeNull();
  });
});
