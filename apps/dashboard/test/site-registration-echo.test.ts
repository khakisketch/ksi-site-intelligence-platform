import { describe, expect, it } from "vitest";

// 2xx 응답 결속(verifySitePostEcho) — siteId만 같아서는 성공이 아니다.
// Core는 저장 필드를 정규화하지 않고 그대로 저장하므로(비공백 검사만)
// 응답의 저장 필드는 보낸 값과 엄격 일치해야 한다.
import {
  verifySitePostEcho,
  type SitePostEchoExpectation,
} from "@/lib/site-registration/shared";

const AOI = [
  { latDeg: 37.5, lonDeg: 127 },
  { latDeg: 37.51, lonDeg: 127 },
  { latDeg: 37.51, lonDeg: 127.01 },
  { latDeg: 37.5, lonDeg: 127.01 },
];

function legacyExpectation(
  overrides: Partial<SitePostEchoExpectation> = {},
): SitePostEchoExpectation {
  return {
    requestedSiteId: "site-A",
    name: "현장 A",
    siteFrame: {
      crs: "EPSG:5186",
      verticalDatum: "KNGeoid2018",
      unit: "meter",
      transformVersion: "1.0.0",
    },
    aoiVertices: AOI,
    dataResidency: undefined,
    aiEgressAllowed: false,
    ...overrides,
  };
}

function legacyEcho(overrides: Record<string, unknown> = {}): unknown {
  return {
    siteId: "site-A",
    name: "현장 A",
    siteFrame: {
      crs: "EPSG:5186",
      verticalDatum: "KNGeoid2018",
      unit: "meter",
      transformVersion: "1.0.0",
    },
    aoi: { vertices: structuredClone(AOI) },
    dataResidency: null,
    aiEgressAllowed: false,
    ...overrides,
  };
}

describe("2xx 응답 결속 (성공은 전체 일치뿐)", () => {
  it("보낸 원본과 완전히 일치하면 성공이다", () => {
    expect(verifySitePostEcho(legacyEcho(), legacyExpectation())).toEqual({
      ok: true,
      siteId: "site-A",
    });
  });

  it("다른 siteId는 성공이 아니다", () => {
    expect(
      verifySitePostEcho(legacyEcho({ siteId: "site-OTHER" }), legacyExpectation()),
    ).toEqual({ ok: false });
  });

  it("다른 이름은 성공이 아니다", () => {
    expect(
      verifySitePostEcho(legacyEcho({ name: "다른 현장" }), legacyExpectation()),
    ).toEqual({ ok: false });
  });

  it("다른 좌표계·높이 기준·버전은 성공이 아니다", () => {
    expect(
      verifySitePostEcho(
        legacyEcho({ siteFrame: { crs: "EPSG:5186", verticalDatum: "KNGeoid2024", unit: "meter", transformVersion: "1.0.0" } }),
        legacyExpectation(),
      ),
    ).toEqual({ ok: false });
  });

  it("다른 현장 범위는 성공이 아니다", () => {
    expect(
      verifySitePostEcho(
        legacyEcho({ aoi: { vertices: [{ latDeg: 0, lonDeg: 0 }] } }),
        legacyExpectation(),
      ),
    ).toEqual({ ok: false });
  });

  it("꼭짓점 좌표 하나라도 다르면 성공이 아니다", () => {
    const vertices = structuredClone(AOI);
    vertices[2]!.lonDeg = 127.02;
    expect(verifySitePostEcho(legacyEcho({ aoi: { vertices } }), legacyExpectation())).toEqual({
      ok: false,
    });
  });

  it("범위가 없으면(null) 성공이 아니다", () => {
    expect(verifySitePostEcho(legacyEcho({ aoi: null }), legacyExpectation())).toEqual({
      ok: false,
    });
  });

  it("생략한 반출 선언에 객체가 오면 성공이 아니다", () => {
    expect(
      verifySitePostEcho(
        legacyEcho({ dataResidency: { egressAllowed: true, jurisdiction: "KR" } }),
        legacyExpectation(),
      ),
    ).toEqual({ ok: false });
  });

  it("선언한 반출과 다르면 성공이 아니다", () => {
    const expectation = legacyExpectation({
      dataResidency: { egressAllowed: false, jurisdiction: "KR" },
    });
    expect(
      verifySitePostEcho(
        legacyEcho({ dataResidency: { egressAllowed: true, jurisdiction: "KR" } }),
        expectation,
      ),
    ).toEqual({ ok: false });
    expect(
      verifySitePostEcho(
        legacyEcho({ dataResidency: { egressAllowed: false, jurisdiction: "KR" } }),
        expectation,
      ),
    ).toEqual({ ok: true, siteId: "site-A" });
  });

  it("선언했는데 null이 오면 성공이 아니다", () => {
    expect(
      verifySitePostEcho(
        legacyEcho({ dataResidency: null }),
        legacyExpectation({ dataResidency: { egressAllowed: false, jurisdiction: "KR" } }),
      ),
    ).toEqual({ ok: false });
  });

  it("미선언이어도 필드 자체가 빠진 불완전 본문은 성공이 아니다", () => {
    // Core SiteView는 dataResidency None을 wire에 null로 싣는다(응답 모델이
    // None을 포함 직렬화한다). 따라서 키 누락은 "미선언"이 아니라 비정상 본문이며
    // unknown으로 남긴다 — null과 누락을 혼동하지 않는다.
    const full = legacyEcho() as Record<string, unknown>;
    const { dataResidency: absent, ...withoutKey } = full;
    expect(absent).toBeNull();
    const site = { ...withoutKey } as Record<string, unknown>;
    expect("dataResidency" in site).toBe(false);
    expect(verifySitePostEcho(site, legacyExpectation())).toEqual({ ok: false });
    expect(
      verifySitePostEcho(site, legacyExpectation({ dataResidency: { egressAllowed: false, jurisdiction: "KR" } })),
    ).toEqual({ ok: false });
  });

  it("AI 반출 동의가 다르면 성공이 아니다", () => {
    expect(
      verifySitePostEcho(legacyEcho({ aiEgressAllowed: true }), legacyExpectation()),
    ).toEqual({ ok: false });
  });

  it("불완전·비정상 본문은 성공이 아니다", () => {
    const expectation = legacyExpectation();
    for (const broken of [null, undefined, 42, "site-A", [], {}, { site: null }, { site: [] }, { other: 1 }]) {
      expect(verifySitePostEcho(broken, expectation)).toEqual({ ok: false });
    }
    expect(verifySitePostEcho({ site: {} }, expectation)).toEqual({ ok: false });
    expect(verifySitePostEcho({ site: { siteId: "" } }, expectation)).toEqual({ ok: false });
  });

  it("mapped bootstrap은 서버 발급 모양만 받고 원본 대조는 동일하다", () => {
    const expectation = legacyExpectation({ requestedSiteId: null });
    const issued = `site-${"f".repeat(8)}-${"f".repeat(4)}-${"f".repeat(4)}-${"f".repeat(4)}-${"f".repeat(12)}`;
    expect(
      verifySitePostEcho(legacyEcho({ siteId: issued }), expectation),
    ).toEqual({ ok: true, siteId: issued });
    // 발급 모양이 아니면(빈 값·다른 체계) 성공이 아니다.
    // ("site-"는 패턴상 유효하므로 모양 검사가 아니라 원본 대조가 막는다.)
    for (const bad of ["", "other-1", "SITE-A"]) {
      expect(verifySitePostEcho(legacyEcho({ siteId: bad }), expectation)).toEqual({
        ok: false,
      });
    }
    // 이름이 다르면 발급 ID라도 성공이 아니다.
    expect(
      verifySitePostEcho(legacyEcho({ siteId: issued, name: "바뀐 이름" }), expectation),
    ).toEqual({ ok: false });
  });
});
