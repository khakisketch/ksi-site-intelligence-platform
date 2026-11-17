import { describe, expect, it } from "vitest";

import type { ProfileVerticalReference } from "@/lib/core-api/measurement-types";
import { datumLabel, verticalCsvCode, verticalsComparable, verticalText } from "@/lib/measurement-vertical";

const observed = (identifier = "EPSG:5773"): ProfileVerticalReference => ({ provenance: "OBSERVED", observed: { identifier, basis: "b" }, declared: null });
const declared = (datum: "ellipsoidal" | "orthometric_kngeoid2018" = "ellipsoidal"): ProfileVerticalReference => ({
  provenance: "DECLARED", observed: null,
  declared: { declarationId: `vrd-${"1".repeat(32)}`, declarationDigest: `sha256:${"a".repeat(64)}`, datum, unit: "metre", basis: "b", declaredBy: "u", declaredAt: "2026-11-17T00:00:00Z" },
});

describe("verticalText", () => {
  it("출처를 앞에 두고 관측과 선언을 말투로 갈라 쓴다", () => {
    expect(verticalText(observed())).toEqual({ kind: "observed", text: "파일에서 확인 · EPSG:5773" });
    expect(verticalText(declared("orthometric_kngeoid2018"))).toEqual({ kind: "declared", text: "사용자 선언 · 정표고(KNGeoid2018)" });
  });
  it("모르면 모른다고 쓴다", () => {
    expect(verticalText(null)).toEqual({ kind: "unknown", text: "수직 기준 확인 불가" });
    expect(verticalText(undefined).kind).toBe("unknown");
  });
  it("선언을 확인됐다고 쓰지 않는다", () => {
    expect(verticalText(declared()).text).not.toMatch(/확인|검증|정확/);
  });
});

describe("datumLabel", () => {
  it("닫힌 어휘 모두에 한국어 이름이 있다", () => {
    for (const datum of ["ellipsoidal", "ellipsoidal_native", "orthometric_kngeoid2018", "orthometric_kngeoid2024"] as const) {
      expect(datumLabel(datum).length).toBeGreaterThan(2);
    }
  });
});

describe("verticalCsvCode", () => {
  it("기계가 읽는 코드로 출처를 싣는다", () => {
    expect(verticalCsvCode(observed("EPSG:5703"))).toBe("observed:EPSG:5703");
    expect(verticalCsvCode(declared("orthometric_kngeoid2018"))).toBe("declared:orthometric_kngeoid2018");
    expect(verticalCsvCode(null)).toBe("");
  });
});

describe("verticalsComparable", () => {
  it("같은 출처의 같은 기준만 비교해도 된다고 본다", () => {
    expect(verticalsComparable(observed(), observed())).toBe(true);
    expect(verticalsComparable(declared(), declared())).toBe(true);
  });
  it("기준이 다르면 안 된다", () => {
    expect(verticalsComparable(observed("EPSG:5703"), observed("EPSG:5773"))).toBe(false);
    expect(verticalsComparable(declared("ellipsoidal"), declared("orthometric_kngeoid2018"))).toBe(false);
  });
  it("선언과 관측은 이름이 같아 보여도 섞지 않는다", () => {
    expect(verticalsComparable(observed(), declared())).toBe(false);
    expect(verticalsComparable(declared(), observed())).toBe(false);
  });
  it("알 수 없으면 null이다(비교해도 된다고 말하지 않는다)", () => {
    expect(verticalsComparable(null, observed())).toBeNull();
    expect(verticalsComparable(observed(), undefined)).toBeNull();
  });
});
