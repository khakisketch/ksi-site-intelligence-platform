import { describe, expect, it } from "vitest";

import {
  isFeatureList,
  isJobPage,
  isProfileResult,
  isProfileVerticalReference,
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

const OBSERVED = { provenance: "OBSERVED", observed: { identifier: "EPSG:5773", basis: "EGM96 height" }, declared: null };
const DECLARED = {
  provenance: "DECLARED",
  observed: null,
  declared: {
    declarationId: `vrd-${"1".repeat(32)}`, declarationDigest: DIGEST, datum: "ellipsoidal", unit: "metre",
    basis: "RTK 타원체고", declaredBy: "operator-1", declaredAt: "2026-11-17T00:00:00Z",
  },
};

describe("isProfileVerticalReference", () => {
  it("관측과 선언을 각각 계약대로 받는다", () => {
    expect(isProfileVerticalReference(OBSERVED)).toBe(true);
    expect(isProfileVerticalReference(DECLARED)).toBe(true);
    // 값이 없는 쪽을 생략해도 된다(JSON null 생략).
    expect(isProfileVerticalReference({ provenance: "OBSERVED", observed: OBSERVED.observed })).toBe(true);
  });

  it.each([
    ["출처가 없다", {}],
    ["모르는 출처", { ...OBSERVED, provenance: "ASSUMED" }],
    ["관측인데 관측값이 없다", { provenance: "OBSERVED", observed: null, declared: null }],
    ["관측인데 선언이 함께 있다", { ...OBSERVED, declared: DECLARED.declared }],
    ["선언인데 선언이 없다", { provenance: "DECLARED", observed: null, declared: null }],
    ["선언인데 관측값이 함께 있다", { ...DECLARED, observed: OBSERVED.observed }],
    ["단위가 미터가 아니다", { ...DECLARED, declared: { ...DECLARED.declared, unit: "foot" } }],
    ["모르는 기준", { ...DECLARED, declared: { ...DECLARED.declared, datum: "EGM96" } }],
    ["선언 식별자 형식", { ...DECLARED, declared: { ...DECLARED.declared, declarationId: "x" } }],
    ["선언 digest 형식", { ...DECLARED, declared: { ...DECLARED.declared, declarationDigest: "abc" } }],
    ["관측 식별자가 비었다", { ...OBSERVED, observed: { identifier: "", basis: "x" } }],
  ])("거부한다: %s", (_name, value) => {
    expect(isProfileVerticalReference(value)).toBe(false);
  });

  it("영수증이 있는 작업은 출처가 맞을 때만 받는다", () => {
    expect(isJobPage({ items: [{ ...JOB, receipt: { verticalReference: DECLARED } }] })).toBe(true);
    expect(isJobPage({ items: [{ ...JOB, receipt: null }] })).toBe(true);
    expect(isJobPage({ items: [JOB] })).toBe(true);
    expect(isJobPage({ items: [{ ...JOB, receipt: { verticalReference: { provenance: "DECLARED" } } }] })).toBe(false);
    expect(isJobPage({ items: [{ ...JOB, receipt: {} }] })).toBe(false);
  });

  it("출처가 어긋난 영수증이 붙은 결과 보기는 통째로 받지 않는다(선언을 관측으로 읽지 않는다)", () => {
    const bad = { provenance: "DECLARED", observed: OBSERVED.observed, declared: null };
    expect(isProfileResultView({ job: { ...JOB, receipt: { verticalReference: DECLARED } }, result: result() })).toBe(true);
    expect(isProfileResultView({ job: { ...JOB, receipt: { verticalReference: bad } }, result: result() })).toBe(false);
  });
});
