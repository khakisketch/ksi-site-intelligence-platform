import { describe, expect, it } from "vitest";

import {
  isFeatureList,
  isJobPage,
  isProfileResult,
  isProfileResultView,
} from "@/lib/core-api/measurement-types";

const DIGEST = `sha256:${"a".repeat(64)}`;
const FEATURE = { featureId: `mf-${"1".repeat(32)}`, revision: 2, lineDigest: DIGEST };
const JOB = {
  jobId: `spj-${"2".repeat(32)}`,
  assetRef: `ksa-v1-${"3".repeat(64)}`,
  siteId: "site-a",
  workAreaId: "area-a",
  feature: FEATURE,
  createdAt: "2026-11-17T01:00:00Z",
  executionState: "COMPLETED",
  availability: "AVAILABLE",
  reason: null,
};

function result(overrides: Record<string, unknown> = {}) {
  return {
    assetRef: JOB.assetRef,
    lineDigest: DIGEST,
    feature: FEATURE,
    horizontalCrs: "EPSG:5186",
    lineLengthM: 2,
    sampleSpacingM: 1,
    samples: [
      { index: 0, distanceM: 0, x: 1, y: 1, elevationM: 10, invalidReason: null },
      { index: 1, distanceM: 1, x: 2, y: 1, elevationM: null, invalidReason: "NODATA" },
      { index: 2, distanceM: 2, x: 3, y: 1, elevationM: 11, invalidReason: null },
    ],
    validCount: 2,
    unknownCount: 1,
    minimumM: 10,
    maximumM: 11,
    ...overrides,
  };
}

describe("isProfileResult", () => {
  it("계약대로의 결과를 받는다", () => {
    expect(isProfileResult(result())).toBe(true);
  });

  it.each([
    ["높이와 이유가 둘 다 있다", { samples: [
      { index: 0, distanceM: 0, x: 1, y: 1, elevationM: 10, invalidReason: "NODATA" },
      { index: 1, distanceM: 1, x: 2, y: 1, elevationM: 11, invalidReason: null },
    ], validCount: 2, unknownCount: 0 }],
    ["높이도 이유도 없다", { samples: [
      { index: 0, distanceM: 0, x: 1, y: 1, elevationM: null, invalidReason: null },
      { index: 1, distanceM: 1, x: 2, y: 1, elevationM: 11, invalidReason: null },
    ], validCount: 1, unknownCount: 1 }],
    ["모르는 이유 코드", { samples: [
      { index: 0, distanceM: 0, x: 1, y: 1, elevationM: null, invalidReason: "WHATEVER" },
      { index: 1, distanceM: 1, x: 2, y: 1, elevationM: 11, invalidReason: null },
    ], validCount: 1, unknownCount: 1 }],
    ["높이가 유한하지 않다", { samples: [
      { index: 0, distanceM: 0, x: 1, y: 1, elevationM: Number.NaN, invalidReason: null },
      { index: 1, distanceM: 1, x: 2, y: 1, elevationM: 11, invalidReason: null },
    ], validCount: 2, unknownCount: 0 }],
    ["번호가 0부터 이어지지 않는다", { samples: [
      { index: 1, distanceM: 0, x: 1, y: 1, elevationM: 10, invalidReason: null },
      { index: 2, distanceM: 1, x: 2, y: 1, elevationM: 11, invalidReason: null },
    ] }],
    ["거리가 0에서 시작하지 않는다", { samples: [
      { index: 0, distanceM: 0.5, x: 1, y: 1, elevationM: 10, invalidReason: null },
      { index: 1, distanceM: 1, x: 2, y: 1, elevationM: 11, invalidReason: null },
    ] }],
    ["거리가 늘지 않는다", { samples: [
      { index: 0, distanceM: 0, x: 1, y: 1, elevationM: 10, invalidReason: null },
      { index: 1, distanceM: 0, x: 2, y: 1, elevationM: 11, invalidReason: null },
    ] }],
    ["유효 개수가 맞지 않는다", { validCount: 3, unknownCount: 0 }],
    ["지점이 하나뿐이다", { samples: [{ index: 0, distanceM: 0, x: 1, y: 1, elevationM: 10, invalidReason: null }], validCount: 1, unknownCount: 0 }],
    ["선 길이가 0 이하", { lineLengthM: 0 }],
    ["좌표계 형식 오류", { horizontalCrs: "5186" }],
    ["자료 참조 형식 오류", { assetRef: "asset-1" }],
  ])("형식이 어긋나면 거부한다: %s", (_name, overrides) => {
    expect(isProfileResult(result(overrides))).toBe(false);
  });
});

describe("isProfileResultView", () => {
  it("작업과 결과가 함께 맞아야 한다", () => {
    expect(isProfileResultView({ job: JOB, result: result() })).toBe(true);
    expect(isProfileResultView({ job: { ...JOB, jobId: "x" }, result: result() })).toBe(false);
    expect(isProfileResultView({ job: JOB, result: null })).toBe(false);
  });
});

describe("isJobPage", () => {
  it("모든 항목이 유효해야 한다", () => {
    expect(isJobPage({ items: [JOB] })).toBe(true);
    expect(isJobPage({ items: [JOB, { ...JOB, executionState: "DONE" }] })).toBe(false);
    expect(isJobPage({ items: [{ ...JOB, availability: "MAYBE" }] })).toBe(false);
    expect(isJobPage({ items: [{ ...JOB, feature: { ...FEATURE, revision: 0 } }] })).toBe(false);
  });
});

describe("isFeatureList", () => {
  const feature = {
    featureId: FEATURE.featureId,
    siteId: "site-a",
    workAreaId: "area-a",
    revision: 1,
    name: "북쪽 경사면",
    kind: "LINE",
    line: { crs: "EPSG:5186", vertices: [[1, 2], [3, 4]] },
    lineDigest: DIGEST,
    createdAt: "2026-11-17T01:00:00Z",
  };
  it("저장된 선의 모양을 확인한다", () => {
    expect(isFeatureList({ features: [feature] })).toBe(true);
    expect(isFeatureList({ features: [{ ...feature, line: { crs: "EPSG:5186", vertices: [[1, 2]] } }] })).toBe(false);
    expect(isFeatureList({ features: [{ ...feature, line: { crs: "EPSG:5186", vertices: [[1, "2"], [3, 4]] } }] })).toBe(false);
    expect(isFeatureList({ features: [{ ...feature, name: "" }] })).toBe(false);
    expect(isFeatureList({ features: [{ ...feature, kind: "POLYGON" }] })).toBe(false);
  });
});
