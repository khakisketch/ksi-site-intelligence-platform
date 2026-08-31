import { describe, expect, it } from "vitest";

import { CSV_BOM, designProgressToCsv, siteReportToCsv } from "@/lib/report-csv";
import type { DesignProgress } from "@/lib/core-api/types";
import type { CompleteReportCoverageEvidence } from "@/lib/reports/coverage-evidence";

// 골든 텍스트 비교 — 이 파일이 렌더링과 분리된 순수 함수라는 것 자체가 테스트
// 대상이다(design-conformance.test.ts 와 같은 규율, jsdom 없이 문자열만 본다).

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

function coverage(): CompleteReportCoverageEvidence {
  return {
    status: "REPORTED",
    missionId: "mission-1",
    report: {
      missionId: "mission-1",
      reportCount: 2,
      latest: {
        missionId: "mission-1",
        siteId: "SITE-1",
        timestamp: "2026-08-12T01:00:00Z",
        cells: [
          { cellId: "cell-1", state: "OBSERVED_HIGH_CONFIDENCE" },
          { cellId: "cell-2", state: "TIME_LIMITED" },
        ],
        summary: {
          mandatoryHazardRatio: 1,
          mandatoryAssetRatio: 1,
          accessibleGeneralRatio: 0.96,
          completionState: "COMPLETED_WITH_GAPS",
        },
      },
      reportedBy: "edge-1",
      recoveryRecommended: true,
      ratioAttributionNote: "이 세 비율은 기체가 계산해 신고한 값입니다.",
      plannedGeneralCoverageRatio: 0.98,
      plannedGeneralCoverageUnavailableReason: null,
    },
    rejections: {
      missionId: "mission-1",
      rejectionCount: 1,
      rejections: [
        {
          verdict: "UNSUPPORTED_COMPLETION",
          detail: "완료 임계 미달",
          reportedBy: "edge-1",
          rejectedAt: "2026-08-12T00:30:00Z",
        },
      ],
    },
  };
}

describe("CSV_BOM", () => {
  it("UTF-8 BOM 한 글자다 — Excel 한글 깨짐 방지, 지우면 재발한다", () => {
    expect(CSV_BOM).toBe("﻿");
  });
});

describe("designProgressToCsv", () => {
  it("메타 행 + 빈 줄 + 헤더 + 구역 행 순서의 정확한 문자열을 낸다(골든)", () => {
    const csv = designProgressToCsv(progress());
    const expected =
      "﻿" +
      "현장 ID,SITE-1\r\n" +
      "설계 기준면 ID,SITE-1-ds1\r\n" +
      "기준(원지형) 계산 시각(UTC),2026-08-01T00:00:00Z\r\n" +
      "최신 계산 시각(UTC),2026-08-12T00:00:00Z\r\n" +
      "집계 제외 문턱(m),0.05\r\n" +
      "\r\n" +
      "구역ID,구역명,계획 절토(m³),완료 절토(m³),잔여 절토(m³),절토 진척률(%),계획 성토(m³),완료 성토(m³),잔여 성토(m³),성토 진척률(%),산정 근거\r\n" +
      "zone-1,A공구,1000,600,400,60.0,200,150,50,75.0,작업구역 zone-1 기준\r\n";
    expect(csv).toBe(expected);
  });

  it("zoneName 이 null 이면 빈 칸이다(zoneId 로 대체하지 않는다 — 화면과 다른 표기를 만들지 않는다)", () => {
    const csv = designProgressToCsv(
      progress({ zones: [{ ...progress().zones[0], zoneName: null }] }),
    );
    expect(csv).toContain("zone-1,,1000,");
  });

  it("진척률이 null 이면 '해당 없음'이다 — 0%(그 방향 계획이 없는데 다 했다는 뜻)와 다른 값", () => {
    const csv = designProgressToCsv(
      progress({
        zones: [
          { ...progress().zones[0], cutProgressRatio: null, fillProgressRatio: null },
        ],
      }),
    );
    expect(csv).toContain(",해당 없음,");
    const ratioFields = csv.split("\r\n")[7].split(",");
    expect(ratioFields).toContain("해당 없음");
  });

  it("구역명·근거에 쉼표가 있으면 따옴표로 감싼다(RFC4180)", () => {
    const csv = designProgressToCsv(
      progress({
        zones: [{ ...progress().zones[0], zoneName: "A공구, 1구간" }],
      }),
    );
    expect(csv).toContain('"A공구, 1구간"');
  });

  it("필드에 따옴표가 있으면 두 배로 이스케이프한다", () => {
    const csv = designProgressToCsv(
      progress({
        zones: [{ ...progress().zones[0], basis: '기준선 "A" 참조' }],
      }),
    );
    expect(csv).toContain('"기준선 ""A"" 참조"');
  });

  it("구역이 여러 개면 각각 한 행씩이다", () => {
    const twoZones = progress({
      zones: [
        { ...progress().zones[0], zoneId: "zone-1" },
        { ...progress().zones[0], zoneId: "zone-2", zoneName: "B공구" },
      ],
    });
    const csv = designProgressToCsv(twoZones);
    expect(csv).toContain("zone-1,");
    expect(csv).toContain("zone-2,B공구,");
    expect(csv.match(/\r\n/g)?.length).toBe(9); // 메타 5 + 빈줄 1 + 헤더 1 + 구역 2
  });

  it("구역이 0개면 헤더까지만 낸다 — 빈 표를 숨기지 않는다", () => {
    const csv = designProgressToCsv(progress({ zones: [] }));
    expect(csv.endsWith("산정 근거\r\n")).toBe(true);
  });
});

describe("siteReportToCsv", () => {
  it("기체 신고 귀속·계획 대사·거부 이력을 진척 표 앞에 함께 기록한다", () => {
    const csv = siteReportToCsv(progress(), coverage());
    expect(csv).toContain("커버리지 근거 임무 ID,mission-1\r\n");
    expect(csv).toContain("커버리지 보고 상태,접수됨 — 최신 서버 수용 보고 기준\r\n");
    expect(csv).toContain("커버리지 비율 귀속,이 세 비율은 기체가 계산해 신고한 값입니다.\r\n");
    expect(csv).toContain(
      "계획 대비 대사,대사 보류 — 미완료 종료 보고는 완료 판정의 계획 상한 검사 대상이 아님\r\n",
    );
    expect(csv).toContain("서버가 거부한 커버리지 주장 수,1\r\n");
    expect(csv).toContain("UNSUPPORTED_COMPLETION | 완료 임계 미달 | edge-1");
    expect(csv.indexOf("커버리지 근거 임무 ID")).toBeLessThan(csv.indexOf("구역ID,구역명"));
  });

  it("수용 보고가 없으면 0이나 완료로 꾸미지 않고 미보고 상태를 기록한다", () => {
    const noReport: CompleteReportCoverageEvidence = {
      status: "NOT_REPORTED",
      missionId: "mission-2",
      report: null,
      rejections: { missionId: "mission-2", rejectionCount: 0, rejections: [] },
    };
    const csv = siteReportToCsv(progress(), noReport);
    expect(csv).toContain("접수 없음 — 비행 전/미전송 여부는 구분 불가");
    expect(csv).toContain("계획 대비 대사,수행하지 않음 — 수용된 커버리지 보고 없음");
  });

  it("COMPLETED 수용 보고만 계획 상한 검사 완료라고 기록한다", () => {
    const completed = coverage();
    if (completed.status !== "REPORTED") throw new Error("fixture must be reported");
    completed.report.latest.summary.completionState = "COMPLETED";
    expect(siteReportToCsv(progress(), completed)).toContain(
      "계획 대비 대사,서버 확인: 발급 시점 계획 추정 상한 이내\r\n",
    );
  });
});
