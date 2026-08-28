import { describe, expect, it } from "vitest";

import {
  collectSiteReportData,
  matchLatestConformanceReport,
  resolveOrthophotoArtifactId,
} from "@/lib/reports/collect-site-report-data";
import type {
  DesignConformanceEntry,
  DesignConformanceListView,
  DesignProgress,
  DesignProgressResponse,
  ProcessingJobArtifactsView,
} from "@/lib/core-api/types";

// 이 파일이 지키는 것: **id 로 못 찾은 리포트를 0번째로 넘겨짚지 않는가.**
// 렌더링은 vitest 대상이 아니다(jsdom 없음, design-conformance.test.ts 와 같은 규율) —
// 여기서는 세 응답을 조립하는 순수 판정만 본다.

function progress(overrides: Partial<DesignProgress> = {}): DesignProgress {
  return {
    schemaVersion: "1.0",
    siteId: "SITE-1",
    designSurfaceId: "SITE-1-ds1",
    designSurfaceSha256: "a".repeat(64),
    baselineDesignConformanceId: "dc-baseline",
    baselineComputedAt: "2026-08-01T00:00:00Z",
    latestDesignConformanceId: "dc-latest",
    latestComputedAt: "2026-08-12T00:00:00Z",
    thresholdM: 0.05,
    zones: [
      {
        zoneId: "zone-1",
        zoneName: "A공구",
        plannedCutM3: 1000,
        plannedFillM3: 200,
        remainingCutM3: 400,
        remainingFillM3: 50,
        doneCutM3: 600,
        doneFillM3: 150,
        cutProgressRatio: 0.6,
        fillProgressRatio: 0.75,
        basis: "작업구역 zone-1 기준",
      },
    ],
    ...overrides,
  };
}

function progressResponse(
  overrides: Partial<DesignProgressResponse> = {},
): DesignProgressResponse {
  return {
    progress: progress(),
    reason: null,
    unmatchedZoneIds: [],
    areaMismatchZoneIds: [],
    detail: null,
    latestMissionId: "mission-1",
    ...overrides,
  };
}

function conformanceEntry(designConformanceId: string): DesignConformanceEntry {
  return {
    report: {
      schemaVersion: "1.0",
      designConformanceId,
      designSurfaceRef: { designSurfaceId: "SITE-1-ds1", sha256: "a".repeat(64) },
      current: { jobId: "job-1", artifactId: "artifact-1" },
      crs: "EPSG:5186",
      verticalReference: {
        datum: "ellipsoidal",
        basis: "설계사 제공 도면 표제부에 타원체고 명시",
        source: "user_declared",
      },
      zones: [
        {
          zoneId: "zone-1",
          cutM3: 400,
          fillM3: 50,
          netM3: -350,
          areaM2: 1200,
          thresholdM: 0.05,
          uncertaintyM3: null,
          uncertaintyNote: "검사점 RMSE 미보고",
        },
      ],
      policy: {
        schemaVersion: "1.0",
        policyVersion: "policy-2026-08",
        distanceThresholdM: 0.05,
        volumeThresholdM: 0.05,
        revisitRatioThreshold: 0.1,
      },
      diffRaster: {
        diffRasterId: "diff-1",
        digest: "b".repeat(64),
        format: "geotiff",
        crs: "EPSG:5186",
        verticalReference: {
          datum: "ellipsoidal",
          basis: "설계사 제공 도면 표제부에 타원체고 명시",
          source: "user_declared",
        },
        width: 100,
        height: 100,
        pixelSizeXM: 0.1,
        pixelSizeYM: 0.1,
        transform: [0, 0.1, 0, 0, 0, -0.1],
        nodataEncoding: "nan",
        thresholdM: 0.05,
        sizeBytes: 1024,
        coreVerifiedDigestAt: "2026-08-12T00:00:00Z",
      },
      computedAt: "2026-08-12T00:00:00Z",
    },
    reportedBy: "operator-1",
    recordedAt: "2026-08-12T00:00:05Z",
    coreRecomputedDigest: "b".repeat(64),
  };
}

function conformanceList(
  entries: DesignConformanceEntry[],
  latestTotalNetM3: number | null = -350,
): DesignConformanceListView {
  return {
    missionId: "mission-1",
    reportCount: entries.length,
    latestTotalNetM3,
    reports: entries,
  };
}

function jobArtifacts(kinds: string[]): ProcessingJobArtifactsView {
  return {
    jobId: "job-1",
    status: "SUCCEEDED",
    artifacts: kinds.map((kind, index) => ({ artifactId: `artifact-${index}`, kind })),
  };
}

describe("matchLatestConformanceReport", () => {
  it("latestMissionId 가 없으면 애초에 조회할 임무가 없다 — no-mission", () => {
    expect(matchLatestConformanceReport(null, "dc-latest", null)).toEqual({ kind: "no-mission" });
  });

  it("목록 조회 자체가 없으면(404·오류) no-reports", () => {
    expect(matchLatestConformanceReport("mission-1", "dc-latest", null)).toEqual({
      kind: "no-reports",
    });
  });

  it("목록은 있지만 latestDesignConformanceId 가 그 안에 없으면 id-not-found — 0번째로 넘겨짚지 않는다", () => {
    const list = conformanceList([conformanceEntry("dc-other-1"), conformanceEntry("dc-other-2")]);
    expect(matchLatestConformanceReport("mission-1", "dc-latest", list)).toEqual({
      kind: "id-not-found",
    });
  });

  it("id 가 목록 중간에 있어도(0번째가 아니어도) 정확히 찾는다", () => {
    const target = conformanceEntry("dc-latest");
    const list = conformanceList([conformanceEntry("dc-newer"), target, conformanceEntry("dc-older")]);
    const result = matchLatestConformanceReport("mission-1", "dc-latest", list);
    expect(result.kind).toBe("matched");
    if (result.kind === "matched") {
      expect(result.entry).toBe(target);
      expect(result.totalNetM3).toBe(-350);
    }
  });
});

describe("resolveOrthophotoArtifactId", () => {
  it("작업물 조회가 없으면 null", () => {
    expect(resolveOrthophotoArtifactId(null)).toBeNull();
  });

  it("ortho 산출물이 없으면 null — 있는 것만 찾는다", () => {
    expect(resolveOrthophotoArtifactId(jobArtifacts(["dsm", "point_cloud"]))).toBeNull();
  });

  it("ortho 산출물의 artifactId 를 그대로 돌려준다", () => {
    const view = jobArtifacts(["dsm", "ortho", "point_cloud"]);
    expect(resolveOrthophotoArtifactId(view)).toBe(view.artifacts[1].artifactId);
  });
});

describe("collectSiteReportData", () => {
  it("progress 가 null 이면 매칭을 시도조차 하지 않는다 — 구역 표 자체가 없다", () => {
    const response = progressResponse({
      progress: null,
      detail: "원지형 기준이 지정되지 않았습니다.",
    });
    const result = collectSiteReportData(response, null, null);
    expect(result.progress).toBeNull();
    expect(result.detail).toBe("원지형 기준이 지정되지 않았습니다.");
    expect(result.conformance).toEqual({ kind: "no-progress" });
    expect(result.orthophotoArtifactId).toBeNull();
  });

  it("id 불일치면 cut/fill/net 만 생략되고 진척 표(progress)는 그대로 살아남는다", () => {
    const response = progressResponse();
    const list = conformanceList([conformanceEntry("dc-completely-different")]);
    const result = collectSiteReportData(response, list, null);
    expect(result.progress).not.toBeNull();
    expect(result.progress?.zones).toHaveLength(1);
    expect(result.conformance).toEqual({ kind: "id-not-found" });
    expect(result.orthophotoArtifactId).toBeNull();
  });

  it("매칭되면 리포트와 정사영상 artifactId 를 함께 실어 낸다", () => {
    const response = progressResponse();
    const entry = conformanceEntry("dc-latest");
    const list = conformanceList([entry]);
    const jobs = jobArtifacts(["dsm", "ortho"]);
    const result = collectSiteReportData(response, list, jobs);
    expect(result.conformance).toEqual({ kind: "matched", entry, totalNetM3: -350 });
    expect(result.orthophotoArtifactId).toBe(jobs.artifacts[1].artifactId);
  });

  it("매칭됐지만 정사영상이 없으면 자리표시자 판단에 쓸 null 을 낸다(침묵 생략 아님)", () => {
    const response = progressResponse();
    const entry = conformanceEntry("dc-latest");
    const list = conformanceList([entry]);
    const jobs = jobArtifacts(["dsm"]);
    const result = collectSiteReportData(response, list, jobs);
    expect(result.conformance.kind).toBe("matched");
    expect(result.orthophotoArtifactId).toBeNull();
  });

  it("id 매칭 실패 시에는 작업물을 조회했더라도 정사영상을 찾지 않는다", () => {
    const response = progressResponse();
    const list = conformanceList([conformanceEntry("dc-other")]);
    const jobs = jobArtifacts(["ortho"]);
    const result = collectSiteReportData(response, list, jobs);
    expect(result.conformance).toEqual({ kind: "id-not-found" });
    expect(result.orthophotoArtifactId).toBeNull();
  });

  it("unmatchedZoneIds/areaMismatchZoneIds 를 그대로 통과시킨다 — 화면의 두 문단 근거", () => {
    const response = progressResponse({
      unmatchedZoneIds: ["zone-2"],
      areaMismatchZoneIds: ["zone-3"],
    });
    const result = collectSiteReportData(response, null, null);
    expect(result.unmatchedZoneIds).toEqual(["zone-2"]);
    expect(result.areaMismatchZoneIds).toEqual(["zone-3"]);
  });
});
