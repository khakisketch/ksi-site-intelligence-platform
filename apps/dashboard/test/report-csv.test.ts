import { describe, expect, it } from "vitest";

import { CSV_BOM, designProgressToCsv } from "@/lib/report-csv";
import type { DesignProgress } from "@/lib/core-api/types";

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
