import { describe, expect, it } from "vitest";

import {
  assetContextLine,
  assetHeadline,
  duplicateFileNames,
  formatAssetCaptureWindow,
  formatCaptureInterval,
  observationChoiceLabel,
  observationChoiceLabels,
  requestRowPresentations,
  resolveWorkName,
  spatialAssetKindLabel,
} from "@/lib/human-labels";
import type { AnalysisObservationOption } from "@/lib/core-api/analysis";

function observation(overrides: Partial<AnalysisObservationOption> = {}): AnalysisObservationOption {
  return {
    selector: {
      workOrderId: "work-order-a",
      submissionRef: `ers-v1-${"a".repeat(64)}`,
      revision: 2,
    },
    observationEpochId: "epoch-recorded-a",
    captureStartedAt: "2026-09-01T00:00:00Z",
    captureEndedAt: "2026-09-01T00:30:00Z",
    ...overrides,
  };
}

describe("human labels for observation selection", () => {
  it("names the real work with its genuine capture interval and submission version", () => {
    const label = observationChoiceLabel(observation(), "북측 1차 관측");

    expect(label).toContain("북측 1차 관측");
    expect(label).toContain("2026. 9. 1.");
    expect(label).toContain("09:00–09:30");
    expect(label).toContain("제출 revision 2");
    expect(label).not.toContain("epoch-recorded-a");
  });

  it("stays honest when the work name is missing without inventing one", () => {
    expect(resolveWorkName("work-order-a", null)).toBeNull();
    expect(resolveWorkName("work-order-a", {})).toBeNull();
    expect(resolveWorkName("work-order-a", { "work-order-a": "   " })).toBeNull();

    const label = observationChoiceLabel(observation(), null);
    expect(label).toContain("작업명 확인 불가");
    expect(label).toContain("제출 revision 2");
  });

  it("keeps same-time, same-version candidates distinguishable with the recorded epoch ID", () => {
    const first = observation({ observationEpochId: "epoch-first-recorded" });
    const second = observation({ observationEpochId: "epoch-second-recorded" });
    const names = { "work-order-a": "같은 작업" };

    const [firstLabel, secondLabel] = observationChoiceLabels([first, second], names);

    expect(firstLabel).not.toBe(secondLabel);
    expect(firstLabel).toContain("epoch-first-recorded");
    expect(secondLabel).toContain("epoch-second-recorded");
  });

  it("falls back to the exact selector when the same epoch is reused across selectors", () => {
    const first = observation({ observationEpochId: "epoch-reused" });
    const second = observation({
      observationEpochId: "epoch-reused",
      selector: { workOrderId: "work-order-a", submissionRef: `ers-v1-${"c".repeat(64)}`, revision: 2 },
    });
    const names = { "work-order-a": "같은 작업" };

    const [firstLabel, secondLabel] = observationChoiceLabels([first, second], names);

    expect(firstLabel).not.toBe(secondLabel);
    expect(firstLabel).toContain(`ers-v1-${"a".repeat(64)}`);
    expect(secondLabel).toContain(`ers-v1-${"c".repeat(64)}`);
    expect(firstLabel).toContain("작업 work-order-a");
  });

  it("does not attach technical IDs when candidates already differ", () => {
    const first = observation();
    const second = observation({
      selector: { workOrderId: "work-order-a", submissionRef: `ers-v1-${"b".repeat(64)}`, revision: 3 },
      observationEpochId: "epoch-recorded-b",
    });

    const [firstLabel, secondLabel] = observationChoiceLabels([first, second], { "work-order-a": "같은 작업" });

    expect(firstLabel).not.toBe(secondLabel);
    expect(firstLabel).not.toContain("epoch-recorded-a");
    expect(secondLabel).not.toContain("epoch-recorded-b");
  });

  it("formats multi-day capture intervals without dropping either side", () => {
    const interval = formatCaptureInterval("2026-09-01T00:00:00Z", "2026-09-02T00:30:00Z");
    expect(interval).toContain("2026. 9. 1.");
    expect(interval).toContain("2026. 9. 2.");
  });
});

describe("human labels for spatial assets", () => {
  it("connects work name, area, capture window and version in one context line", () => {
    const line = assetContextLine({
      workName: "북측 1차 관측",
      areaName: "북측 작업구역",
      captureWindow: formatAssetCaptureWindow("2026-09-29T23:30:00Z", "2026-09-30T00:30:00Z"),
      revision: 2,
    });

    expect(line).toContain("북측 1차 관측");
    expect(line).toContain("북측 작업구역");
    expect(line).toContain("제출 revision 2");
    expect(line).toContain("2026. 9. 30.");
  });

  it("reports a missing capture window instead of guessing one", () => {
    expect(formatAssetCaptureWindow(null, null)).toBe("촬영 구간 미기재");
    expect(formatAssetCaptureWindow("2026-09-30T01:00:00Z", null)).toContain("종료 미기재");
  });

  it("distinguishes duplicate file names by revision while keeping unique names short", () => {
    expect(assetHeadline("north-dsm.tif", 2, false)).toBe("north-dsm.tif");
    expect(assetHeadline("north-dsm.tif", 2, true)).toContain("revision 2");
    expect(duplicateFileNames(["a.tif", "b.tif", "a.tif"])).toEqual(new Set(["a.tif"]));
    expect(duplicateFileNames(["a.tif", "b.tif"]).size).toBe(0);
  });

  it("labels known asset kinds without rewriting unknown ones", () => {
    expect(spatialAssetKindLabel("dsm")).toBe("DSM 지표면 모델");
    expect(spatialAssetKindLabel("ortho")).toBe("정사영상");
    expect(spatialAssetKindLabel("future-kind")).toBe("future-kind");
  });
});

describe("human labels for spatial data requests", () => {
  const items = [
    { jobId: "sdj-v1-11111111-1111-1111-1111-111111111111", createdAt: "2026-10-14T10:40:09Z", assetRef: `ksa-v1-${"a".repeat(64)}` },
    { jobId: "sdj-v1-22222222-2222-2222-2222-222222222222", createdAt: "2026-10-14T10:40:09Z", assetRef: `ksa-v1-${"b".repeat(64)}` },
  ];
  const assets = {
    [`ksa-v1-${"a".repeat(64)}`]: { fileName: "north-dsm.tif", kind: "dsm" },
    [`ksa-v1-${"b".repeat(64)}`]: { fileName: "north-ortho.tif", kind: "ortho" },
  };

  it("titles rows with request time, source file and work-area context", () => {
    const [first] = requestRowPresentations([items[0]!], (iso) => iso, assets, "북측 작업구역");

    expect(first!.title).toContain("북측 작업구역");
    expect(first!.title).toContain("2026-10-14T10:40:09Z");
    expect(first!.title).toContain("north-dsm.tif");
    expect(first!.sourceLine).toBe("원본 · DSM 지표면 모델");
    expect(first!.hasCatalogInfo).toBe(true);
  });

  it("keeps distinct filenames at the same time free of raw IDs", () => {
    const [first, second] = requestRowPresentations(items, (iso) => iso, assets, "북측 작업구역");

    expect(first!.title).not.toBe(second!.title);
    expect(first!.title).not.toContain(items[0]!.jobId);
    expect(second!.title).not.toContain(items[1]!.jobId);
    expect(first!.title).toContain("north-dsm.tif");
    expect(second!.title).toContain("north-ortho.tif");
  });

  it("exposes the full request ID only when whole titles still collide", () => {
    const sameSource = [
      { ...items[0]! },
      { ...items[0]!, jobId: "sdj-v1-33333333-3333-3333-3333-333333333333" },
    ];
    const [first, second] = requestRowPresentations(sameSource, (iso) => iso, assets, "북측 작업구역");

    expect(first!.title).not.toBe(second!.title);
    expect(first!.title).toContain(sameSource[0]!.jobId);
    expect(second!.title).toContain(sameSource[1]!.jobId);
  });

  it("never implies a deleted source when the catalog is unavailable", () => {
    const [first] = requestRowPresentations([items[0]!], (iso) => iso, null, "북측 작업구역");

    expect(first!.title).toContain("원본 파일명 확인 불가");
    expect(first!.sourceLine).toContain("원본 파일명 확인 불가");
    expect(first!.sourceLine).toContain("현재 조회한 카탈로그에서 확인되지 않음");
    expect(first!.sourceLine).toContain("뜻하지 않음");
    expect(first!.sourceLine).not.toContain("삭제됐");
    expect(first!.sourceLine).not.toContain("권한");
    expect(first!.hasCatalogInfo).toBe(false);
  });
});
