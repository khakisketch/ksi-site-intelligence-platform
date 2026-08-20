import { describe, expect, it } from "vitest";

import {
  COMPARISON_ZONE_CRS,
  COMPARISON_ZONE_ID,
  canSubmitComparison,
  comparisonEligibility,
  currentMissionEpochs,
  isTerminalComparisonStatus,
  selectableEpochs,
  toZonePolygon,
  toZonesPayload,
  type ComparisonEpoch,
} from "@/lib/comparison-submit";
import type { SiteProcessingJobSummary } from "@/lib/core-api/types";

// 이 파일이 고정하는 것은 **제출 전 안내 판정**이다. 최종 가부는 Core 가
// 정하지만(comparison_requests._resolve), 화면이 누를 수 없는 조합을 눌 수 있게
// 보여주면 사용자는 422 를 받고 나서야 알게 된다 — 그 갈라짐을 여기서 막는다.

function job(
  overrides: Partial<SiteProcessingJobSummary> & { jobId: string },
): SiteProcessingJobSummary {
  return {
    missionId: "mission-1",
    siteId: "site-1",
    status: "SUCCEEDED",
    issuedAt: "2026-08-01T00:00:00Z",
    detail: null,
    artifacts: [],
    ...overrides,
    captureWindow: overrides.captureWindow ?? {
      status: "INCOMPLETE", capturedFrom: null, capturedTo: null,
    },
  };
}

function epoch(overrides: Partial<ComparisonEpoch> & { jobId: string }): ComparisonEpoch {
  return {
    missionId: "mission-1",
    issuedAt: "2026-08-01T00:00:00Z",
    hasPointCloud: true,
    hasDsm: true,
    ...overrides,
  };
}

describe("selectableEpochs", () => {
  it("성공한 재구성만 후보로 남긴다", () => {
    const result = selectableEpochs([
      job({ jobId: "ok" }),
      job({ jobId: "running", status: "RUNNING" }),
      job({ jobId: "failed", status: "FAILED" }),
      job({ jobId: "queued", status: "QUEUED" }),
    ]);
    expect(result.map((e) => e.jobId)).toEqual(["ok"]);
  });

  it("산출물 종류에서 점군·높이자료 보유 여부를 읽는다", () => {
    const [only] = selectableEpochs([
      job({
        jobId: "a",
        artifacts: [
          { artifactId: "pc", kind: "point_cloud" },
          { artifactId: "ortho", kind: "ortho" },
        ],
      }),
    ]);
    expect(only.hasPointCloud).toBe(true);
    expect(only.hasDsm).toBe(false);
  });

  it("최신이 먼저 오도록 정렬한다", () => {
    const result = selectableEpochs([
      job({ jobId: "old", issuedAt: "2026-08-01T00:00:00Z" }),
      job({ jobId: "new", issuedAt: "2026-08-09T00:00:00Z" }),
      job({ jobId: "mid", issuedAt: "2026-08-05T00:00:00Z" }),
    ]);
    expect(result.map((e) => e.jobId)).toEqual(["new", "mid", "old"]);
  });
});

describe("currentMissionEpochs", () => {
  it("[핵심] 다른 임무 소속 결과는 '비교 시점(이후)' 후보에서 제외한다 — 서버의 MISSION_MISMATCH 와 같은 제약", () => {
    const epochs = [
      epoch({ jobId: "own", missionId: "mission-a" }),
      epoch({ jobId: "other", missionId: "mission-b" }),
    ];
    const result = currentMissionEpochs(epochs, "mission-a");
    expect(result.map((e) => e.jobId)).toEqual(["own"]);
  });

  it("이 임무 소속 결과가 없으면 빈 배열이다", () => {
    const epochs = [epoch({ jobId: "other", missionId: "mission-b" })];
    expect(currentMissionEpochs(epochs, "mission-a")).toEqual([]);
  });
});

describe("comparisonEligibility", () => {
  it("두 시점을 다 고르기 전에는 제출할 수 없다", () => {
    const result = comparisonEligibility(null, epoch({ jobId: "b" }), true);
    expect(canSubmitComparison(result)).toBe(false);
    expect(result.blockedReason).toContain("두 시점");
  });

  it("[핵심] 같은 결과끼리의 비교를 막는다 — 0 으로 나와 정상처럼 보이기 때문이다", () => {
    const same = epoch({ jobId: "same" });
    const result = comparisonEligibility(same, same, true);
    expect(canSubmitComparison(result)).toBe(false);
    expect(result.blockedReason).toContain("같은 결과");
  });

  it("양쪽에 점군이 있으면 변화 비교가 가능하다", () => {
    const result = comparisonEligibility(
      epoch({ jobId: "a", hasDsm: false }),
      epoch({ jobId: "b", hasDsm: false }),
      false,
    );
    expect(result.changeDetection).toBe(true);
    expect(result.volumeChange).toBe(false);
    expect(canSubmitComparison(result)).toBe(true);
  });

  it("[핵심] 구역을 확정하지 않으면 높이자료가 있어도 부피 비교는 시도되지 않는다", () => {
    const result = comparisonEligibility(
      epoch({ jobId: "a" }),
      epoch({ jobId: "b" }),
      false,
    );
    expect(result.volumeChange).toBe(false);
    // 점군은 있으므로 제출 자체는 가능하다(부분 비교).
    expect(result.changeDetection).toBe(true);
    expect(canSubmitComparison(result)).toBe(true);
  });

  it("구역을 확정하면 부피 비교도 가능해진다", () => {
    const result = comparisonEligibility(epoch({ jobId: "a" }), epoch({ jobId: "b" }), true);
    expect(result.volumeChange).toBe(true);
    expect(result.changeDetection).toBe(true);
  });

  it("잴 수 있는 것이 하나도 없으면 왜인지 말한다(서버의 NOTHING_TO_COMPARE 와 같은 자리)", () => {
    const result = comparisonEligibility(
      epoch({ jobId: "a", hasPointCloud: false, hasDsm: false }),
      epoch({ jobId: "b", hasPointCloud: false, hasDsm: false }),
      true,
    );
    expect(canSubmitComparison(result)).toBe(false);
    expect(result.blockedReason).toBeTruthy();
  });

  it("한쪽만 점군이 없어도 변화 비교는 불가다", () => {
    const result = comparisonEligibility(
      epoch({ jobId: "a", hasPointCloud: false, hasDsm: false }),
      epoch({ jobId: "b", hasDsm: false }),
      true,
    );
    expect(result.changeDetection).toBe(false);
    expect(canSubmitComparison(result)).toBe(false);
  });

  it("[핵심] 점군만 없고 높이자료·구역은 멀쩡하면 **제출은 된다**(부피만 비교)", () => {
    // 이 조합이 막다른 길이 아니라는 것이 요점이다 — 예전 사유 문구에는
    // "한쪽에 높이자료가 없어 부피 비교를 할 수 없습니다" 갈래가 있었는데,
    // 그 갈래에 닿으려면 이 조합이 '제출 불가'여야 했다. 실제로는 부분 비교가
    // 되므로 그 문구는 영영 나올 수 없었다.
    const result = comparisonEligibility(
      epoch({ jobId: "a", hasPointCloud: false }),
      epoch({ jobId: "b", hasPointCloud: false }),
      true,
    );
    expect(canSubmitComparison(result)).toBe(true);
    expect(result.changeDetection).toBe(false);
    expect(result.volumeChange).toBe(true);
  });

  it("점군도 없고 구역도 확정 안 했으면 둘 다 말한다", () => {
    const result = comparisonEligibility(
      epoch({ jobId: "a", hasPointCloud: false }),
      epoch({ jobId: "b", hasPointCloud: false }),
      false,
    );
    expect(canSubmitComparison(result)).toBe(false);
    expect(result.blockedReason).toContain("점군이 없어");
    expect(result.blockedReason).toContain("구역을 확정하지 않아");
  });

  it("점군·높이자료가 둘 다 없으면 그렇게 말한다", () => {
    const result = comparisonEligibility(
      epoch({ jobId: "a", hasPointCloud: false, hasDsm: false }),
      epoch({ jobId: "b", hasPointCloud: false, hasDsm: false }),
      true,
    );
    expect(canSubmitComparison(result)).toBe(false);
    expect(result.blockedReason).toContain("모두 없음");
  });
});

describe("toZonePolygon", () => {
  it("[핵심] GeoJSON 은 경도·위도 순이다 — 뒤집히면 구역이 지구 반대편으로 간다", () => {
    const polygon = toZonePolygon([
      { latDeg: 37.5, lonDeg: 127.0 },
      { latDeg: 37.5, lonDeg: 127.1 },
      { latDeg: 37.6, lonDeg: 127.1 },
    ]);
    expect(polygon).not.toBeNull();
    const ring = (polygon as { coordinates: number[][][] }).coordinates[0];
    // 첫 좌표가 [경도, 위도] 여야 한다(위도가 먼저면 127 이 위도 자리에 온다).
    expect(ring[0]).toEqual([127.0, 37.5]);
  });

  it("링을 첫 점으로 닫는다(GeoJSON 요구사항)", () => {
    const polygon = toZonePolygon([
      { latDeg: 37.5, lonDeg: 127.0 },
      { latDeg: 37.5, lonDeg: 127.1 },
      { latDeg: 37.6, lonDeg: 127.1 },
    ]);
    const ring = (polygon as { coordinates: number[][][] }).coordinates[0];
    expect(ring).toHaveLength(4);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
  });

  it("이미 닫힌 링을 두 번 닫지 않는다", () => {
    const polygon = toZonePolygon([
      { latDeg: 37.5, lonDeg: 127.0 },
      { latDeg: 37.5, lonDeg: 127.1 },
      { latDeg: 37.6, lonDeg: 127.1 },
      { latDeg: 37.5, lonDeg: 127.0 },
    ]);
    const ring = (polygon as { coordinates: number[][][] }).coordinates[0];
    expect(ring).toHaveLength(4);
  });

  it("정점이 3개 미만이면 폴리곤이 될 수 없다", () => {
    expect(toZonePolygon([])).toBeNull();
    expect(toZonePolygon([{ latDeg: 37.5, lonDeg: 127.0 }])).toBeNull();
    expect(
      toZonePolygon([
        { latDeg: 37.5, lonDeg: 127.0 },
        { latDeg: 37.5, lonDeg: 127.1 },
      ]),
    ).toBeNull();
  });
});

describe("toZonesPayload", () => {
  it("서버가 받는 모양(zoneId 로 감싼 dict + 좌표계)으로 만든다", () => {
    const payload = toZonesPayload([
      { latDeg: 37.5, lonDeg: 127.0 },
      { latDeg: 37.5, lonDeg: 127.1 },
      { latDeg: 37.6, lonDeg: 127.1 },
    ]);
    expect(payload).not.toBeNull();
    expect(Object.keys(payload!.zones)).toEqual([COMPARISON_ZONE_ID]);
    expect(payload!.zoneCrs).toBe(COMPARISON_ZONE_CRS);
  });

  it("확정할 폴리곤이 없으면 null — 호출부가 '구역 미확정'으로 다룬다", () => {
    expect(toZonesPayload([])).toBeNull();
  });
});

describe("isTerminalComparisonStatus", () => {
  it("끝난 상태에서만 폴링을 멈춘다", () => {
    expect(isTerminalComparisonStatus("SUCCEEDED")).toBe(true);
    expect(isTerminalComparisonStatus("FAILED")).toBe(true);
    expect(isTerminalComparisonStatus("QUEUED")).toBe(false);
    expect(isTerminalComparisonStatus("RUNNING")).toBe(false);
  });
});
