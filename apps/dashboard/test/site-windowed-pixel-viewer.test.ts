import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import type { SpatialDataJobView } from "@/lib/core-api/spatial-data-types";
import {
  AUDIT_STATE_NOTE,
  NO_COMPOSITE_FLAG_COPY,
  VALIDATION_STATE_NOTE,
  VIEWABILITY_STATE_NOTE,
  adjacentWindowSelection,
  formatNativeWindowExtent,
  readableWindowJobs,
  sharedPlaneForCompare,
  toPreparedWindowJob,
  windowOptionLabel,
  windowSizeWithinLimit,
  type PreparedWindowJob,
} from "@/lib/site-windowed-pixel-viewer";

/** 검사된 네이티브 격자 — 1022×915, 0.25 m, EPSG:7850 북위(north-up) 형태. */
const grid = { transform: [0.25, 0, 382389.2296, 0, -0.25, 6467541.575], width: 1022, height: 915 };

function jobView(overrides: Partial<SpatialDataJobView> = {}): SpatialDataJobView {
  return {
    jobId: "sdj-v1-00000000-0000-0000-0000-000000000001",
    assetRef: `ksa-v1-${"b".repeat(64)}`,
    siteId: "site-1",
    workAreaId: "area-1",
    createdAt: "2026-10-21T00:00:00Z",
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    reason: null,
    remediation: [],
    receipt: null,
    ...overrides,
  };
}

function receiptFor(jobId: string, pixelWindow: [number, number, number, number]) {
  return {
    jobId,
    receiptDigest: null,
    artifactKind: "ortho" as const,
    outputSizeBytes: 100,
    outputSha256: `sha256:${"a".repeat(64)}`,
    requestedBounds: [382389.2296, 6467413.575, 382517.2296, 6467541.575] as [number, number, number, number],
    actualBounds: [382389.2296, 6467413.575, 382517.2296, 6467541.575] as [number, number, number, number],
    pixelWindow,
    width: 512,
    height: 512,
    observedCrsIdentifier: "EPSG:7850",
    observedCrsDigest: `sha256:${"c".repeat(64)}`,
    accuracyAssessed: false as const,
    attribution: "attr",
    modificationNotice: "mod",
    limitations: [],
    preparedAt: "2026-10-21T00:00:00Z",
  };
}

describe("site windowed pixel viewer helpers", () => {
  it("moves to an adjacent window and clamps at the grid edge", () => {
    const current = { width: 512, height: 512, col: 255, row: 201 };
    const right = adjacentWindowSelection(grid, current, 1, 0);
    // 반 창(256) 이동 후 격자 끝(1022-512=510)에 고정된다.
    expect(right).toEqual({ width: 512, height: 512, col: 510, row: 201 });
    const left = adjacentWindowSelection(grid, { width: 512, height: 512, col: 0, row: 0 }, -1, 0);
    expect(left).toEqual({ width: 512, height: 512, col: 0, row: 0 });
    const down = adjacentWindowSelection(grid, current, 0, 1);
    expect(down).toEqual({ width: 512, height: 512, col: 255, row: 403 });
    expect(adjacentWindowSelection(grid, current, 0.5, 0)).toBeNull();
  });

  it("derives the exact native window without hand-typed bounds", () => {
    // 좌측 상단 512×512 창의 네이티브 사각형 — y축은 t[4](음수)·t[5] 기준이다.
    const moved = adjacentWindowSelection(grid, { width: 512, height: 512, col: 0, row: 0 }, 0, 0);
    expect(moved).toEqual({ width: 512, height: 512, col: 0, row: 0 });
    expect(windowSizeWithinLimit(512, 512)).toBe(true);
    expect(windowSizeWithinLimit(513, 1)).toBe(false);
    expect(windowSizeWithinLimit(0, 512)).toBe(false);
  });

  it("exposes only completed, available, receipt-matched windows as viewable", () => {
    const assetRef = `ksa-v1-${"b".repeat(64)}`;
    const left = toPreparedWindowJob(jobView({
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000001",
      assetRef,
      receipt: receiptFor("sdj-v1-00000000-0000-0000-0000-000000000001", [0, 0, 512, 512]),
    }));
    const running = toPreparedWindowJob(jobView({
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000002",
      assetRef,
      executionState: "RUNNING",
      availability: "NOT_READY",
      receipt: null,
    }));
    const mismatched = toPreparedWindowJob(jobView({
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000003",
      assetRef,
      receipt: receiptFor("sdj-v1-00000000-0000-0000-0000-000000000099", [510, 0, 512, 512]),
    }));
    const revoked = toPreparedWindowJob(jobView({
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000004",
      assetRef,
      availability: "ACCESS_REVOKED",
      receipt: receiptFor("sdj-v1-00000000-0000-0000-0000-000000000004", [0, 0, 512, 512]),
    }));
    const otherAsset = toPreparedWindowJob(jobView({
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000005",
      assetRef: `ksa-v1-${"d".repeat(64)}`,
      receipt: receiptFor("sdj-v1-00000000-0000-0000-0000-000000000005", [0, 0, 512, 512]),
    }));
    const jobs: PreparedWindowJob[] = [left, running, mismatched, revoked, otherAsset];
    expect(readableWindowJobs(jobs, assetRef)).toEqual([left]);
  });

  it("keeps the shared-plane verdict to display co-location, never alignment", () => {
    expect(sharedPlaneForCompare("EPSG:7850", "EPSG:7850")).toEqual({ ok: true, crs: "EPSG:7850" });
    const different = sharedPlaneForCompare("EPSG:7850", "EPSG:5186");
    expect(different.ok).toBe(false);
    if (!different.ok) expect(different.notice).toMatch(/위치 기준이 달라/);
    const unknown = sharedPlaneForCompare(null, "EPSG:7850");
    expect(unknown.ok).toBe(false);
  });

  it("formats the native extent and window labels without reinterpretation", () => {
    expect(formatNativeWindowExtent([1, 2, 3, 4], "EPSG:7850")).toBe("EPSG:7850 · [1, 2, 3, 4]");
    const job = toPreparedWindowJob(jobView({ receipt: receiptFor(jobView().jobId, [0, 0, 512, 512]) }));
    expect(windowOptionLabel(job)).toBe("512 × 512 픽셀 · 범위 [382389.2296, 6467413.575, 382517.2296, 6467541.575]");
  });

  it("keeps the three states in separate words and never a composite flag", () => {
    expect(AUDIT_STATE_NOTE).toMatch(/감사 판정/);
    expect(VALIDATION_STATE_NOTE).toMatch(/볼 수 있다는 뜻이 쓸 수 있다는 뜻이 아닙니다/);
    expect(VIEWABILITY_STATE_NOTE).toMatch(/그릴 수 있는지/);
    expect(NO_COMPOSITE_FLAG_COPY).toMatch(/종합 판정/);
    for (const note of [AUDIT_STATE_NOTE, VALIDATION_STATE_NOTE, VIEWABILITY_STATE_NOTE, NO_COMPOSITE_FLAG_COPY]) {
      expect(note).not.toMatch(/검증 완료/);
    }
  });

  it("never pulls a geographic basemap or tile path into the viewer bundle", () => {
    const viewer = readFileSync(
      fileURLToPath(new URL("../src/app/sites/[siteId]/SiteWindowedPixelViewer.tsx", import.meta.url)),
      "utf8",
    );
    const helpers = readFileSync(
      fileURLToPath(new URL("../src/lib/site-windowed-pixel-viewer.ts", import.meta.url)),
      "utf8",
    );
    for (const source of [viewer, helpers]) {
      expect(source).not.toMatch(/from ["']leaflet["']/);
      expect(source).not.toMatch(/from ["']react-leaflet["']/);
      expect(source).not.toMatch(/proj4/);
      expect(source).not.toMatch(/ImageOverlay/);
    }
    // geotiff-overlay의 WGS84 전용 경로는 그대로 둔다 — EPSG:7850을
    // 억지로 올리지 않으며, 그 거부도 바꾸지 않는다.
    const overlay = readFileSync(
      fileURLToPath(new URL("../src/lib/geo/geotiff-overlay.ts", import.meta.url)),
      "utf8",
    );
    expect(overlay).toMatch(/지원하지 않는 GeoTIFF 좌표 기준/);
  });
});
