import { afterEach, describe, expect, it, vi } from "vitest";

import {
  exportIdForAttempt,
  recordBeforeBrowserExport,
  reportExportSnapshotMatches,
  requestReportExportAudit,
} from "@/components/reports/ReportExportControls";
import type {
  DesignProgress,
  ReportExportCreateResponse,
  ReportExportSnapshot,
} from "@/lib/core-api/types";
import type { CompleteReportCoverageEvidence } from "@/lib/reports/coverage-evidence";

function progress(): DesignProgress {
  return {
    schemaVersion: "1.0",
    siteId: "site-1",
    designSurfaceId: "surface-1",
    designSurfaceSha256: "b".repeat(64),
    baselineDesignConformanceId: "baseline-1",
    baselineComputedAt: "2026-08-01T00:00:00Z",
    latestDesignConformanceId: "latest-1",
    latestComputedAt: "2026-08-30T00:00:00Z",
    thresholdM: 0.05,
    zones: [],
  };
}

function coverage(): CompleteReportCoverageEvidence {
  return {
    status: "REPORTED",
    missionId: "mission-latest",
    report: {
      missionId: "mission-latest",
      reportCount: 1,
      latest: {
        missionId: "mission-latest",
        siteId: "site-1",
        timestamp: "2026-08-30T00:00:00Z",
        cells: [{ cellId: "cell-1", state: "OBSERVED_HIGH_CONFIDENCE" }],
        summary: {
          mandatoryHazardRatio: 1,
          mandatoryAssetRatio: 1,
          accessibleGeneralRatio: 0.96,
          completionState: "COMPLETED",
        },
      },
      reportedBy: "edge-1",
      recoveryRecommended: false,
      ratioAttributionNote: "기체 신고값",
      plannedGeneralCoverageRatio: 0.98,
      plannedGeneralCoverageUnavailableReason: null,
    },
    rejections: { missionId: "mission-latest", rejectionCount: 0, rejections: [] },
  };
}

function snapshot(): ReportExportSnapshot {
  const source = (designConformanceId: string) => ({
    designConformanceId,
    reportDigest: `sha256:${"c".repeat(64)}`,
    missionId: designConformanceId === "latest-1" ? "mission-latest" : "mission-baseline",
    requestId: `request-${designConformanceId}`,
    computedAt:
      designConformanceId === "latest-1"
        ? "2026-08-30T00:00:00Z"
        : "2026-08-01T00:00:00Z",
    currentJobId: `job-${designConformanceId}`,
    currentArtifactId: `artifact-${designConformanceId}`,
    diffRasterId: `diff-${designConformanceId}`,
    diffRasterDigest: `sha256:${"d".repeat(64)}`,
    coreRecomputedDiffRasterDigest: `sha256:${"d".repeat(64)}`,
    processingProfileDigest: `sha256:${"e".repeat(64)}`,
    sourceBundleDigest: `sha256:${"f".repeat(64)}`,
  });
  return {
    schemaVersion: "1.1",
    siteId: "site-1",
    designSurfaceId: "surface-1",
    designSurfaceRevision: "Rev.A",
    designSurfaceSha256: "b".repeat(64),
    designNormalizationProfile: "ksi-tin-raster-0.5m-v1",
    designNormalizationDigest: "a".repeat(64),
    baseline: source("baseline-1"),
    latest: source("latest-1"),
    coverage: {
      missionId: "mission-latest",
      availability: "REPORTED",
      reportCount: 1,
      reportDigest: `sha256:${"9".repeat(64)}`,
      reportedBy: "edge-1",
      reportTimestamp: "2026-08-30T00:00:00Z",
      completionState: "COMPLETED",
      mandatoryHazardRatio: 1,
      mandatoryAssetRatio: 1,
      accessibleGeneralRatio: 0.96,
      unobservedCellCount: 0,
      recoveryRecommended: false,
      ratioAttributionNote: "기체 신고값",
      plannedGeneralCoverageRatio: 0.98,
      plannedGeneralCoverageUnavailableReason: null,
      rejectionCount: 0,
      rejections: [],
    },
  };
}

function expectation() {
  return { siteId: "site-1", progress: progress(), coverage: coverage() };
}

function recorded(overrides: Partial<ReportExportCreateResponse> = {}): ReportExportCreateResponse {
  return {
    verdict: "RECORDED",
    exportId: "export-1",
    recordedAt: "2026-08-30T02:00:00Z",
    snapshotDigest: `sha256:${"a".repeat(64)}`,
    contentProducedByServer: false,
    snapshot: snapshot(),
    detail: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("report export audit before browser output", () => {
  it.each(["PDF", "CSV"] as const)("%s 출력은 감사 기록 뒤에만 시작한다", async (format) => {
    const sequence: string[] = [];

    await recordBeforeBrowserExport(
      async () => {
        sequence.push("audit");
        return recorded();
      },
      () => sequence.push(format === "PDF" ? "print" : "blob"),
      expectation(),
    );

    expect(sequence).toEqual(["audit", format === "PDF" ? "print" : "blob"]);
  });

  it("감사 요청 실패면 인쇄/Blob 출력을 시작하지 않는다", async () => {
    const produce = vi.fn();

    await expect(
      recordBeforeBrowserExport(async () => {
        throw new Error("Core unavailable");
      }, produce, expectation()),
    ).rejects.toThrow("Core unavailable");

    expect(produce).not.toHaveBeenCalled();
  });

  it("서버가 파일을 만들었다는 응답이나 미완전한 snapshot은 출력하지 않는다", async () => {
    const produce = vi.fn();

    await expect(
      recordBeforeBrowserExport(
        async () => recorded({ contentProducedByServer: true }),
        produce,
        expectation(),
      ),
    ).rejects.toThrow("내보내기를 시작하지 않았습니다");

    expect(produce).not.toHaveBeenCalled();
  });

  it("BFF로 site와 불변 report ID만 보낸다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(recorded()), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await requestReportExportAudit("site / 1", {
      exportId: "export-1",
      exportFormat: "CSV",
      baselineDesignConformanceId: "baseline-1",
      latestDesignConformanceId: "latest-1",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/sites/site%20%2F%201/report-exports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exportId: "export-1",
        exportFormat: "CSV",
        baselineDesignConformanceId: "baseline-1",
        latestDesignConformanceId: "latest-1",
      }),
    });
  });

  it("응답 유실 뒤 같은 형식 재시도는 보존한 action ID를 쓴다", () => {
    expect(exportIdForAttempt("export-retry")).toBe("export-retry");
  });

  it("화면 커버리지와 Core snapshot이 다르면 브라우저 출력을 막는다", async () => {
    const produce = vi.fn();
    const mismatched = snapshot();
    if (mismatched.coverage) mismatched.coverage.rejectionCount = 1;

    expect(reportExportSnapshotMatches(expectation(), mismatched)).toBe(false);
    await expect(
      recordBeforeBrowserExport(
        async () => recorded({ snapshot: mismatched }),
        produce,
        expectation(),
      ),
    ).rejects.toThrow("내보내기를 시작하지 않았습니다");
    expect(produce).not.toHaveBeenCalled();
  });

  it("조회 본문이 다른 임무를 가리키면 snapshot 숫자가 같아도 출력을 막는다", () => {
    const wrongMission = expectation();
    if (wrongMission.coverage.status === "REPORTED") {
      wrongMission.coverage.report.latest.missionId = "mission-other";
    }

    expect(reportExportSnapshotMatches(wrongMission, snapshot())).toBe(false);
  });
});
