import { describe, expect, it } from "vitest";

// RED: 레거시 siteId 409 자동 성공 제거.
// - 2xx 관측 + 같은 payload 뒤의 409라도 계정 일치가 확인되지 않으므로 자동 성공으로
//   승격하지 않는다 — 수동 확인(duplicateUnverified)이다.
// - 타인 ID 첫 409, body 변경, 불명 5xx(code 있음), 불명 뒤 4xx의 이전 결과 구분을
//   실제 판정으로 확인한다.
import {
  buildSitePostAttempt,
  classifyLegacySitePost,
  digestSitePostPayload,
  type SitePostPayloadInput,
} from "@/lib/site-registration/shared";

const DUP = "DUPLICATE_SITE_ID";

function payload(overrides: Partial<SitePostPayloadInput> = {}): SitePostPayloadInput {
  return {
    name: "현장 A",
    aoi: [{ latDeg: 37.5, lonDeg: 127.0 }],
    crs: "EPSG:5186",
    verticalDatum: "KNGeoid2018",
    transformVersion: "1.0.0",
    egressChoice: "unset",
    jurisdiction: "",
    aiEgressAllowed: false,
    ...overrides,
  };
}

describe("레거시 siteId 제출 판정 (자동 성공 없음)", () => {
  it("2xx + 응답 siteId 일치가 success의 유일한 경로다", () => {
    expect(
      classifyLegacySitePost({
        fetchThrew: false,
        status: 201,
        bodyCode: null,
        responseSiteId: "site-A",
        requestedSiteId: "site-A",
        previous: null,
        payloadDigest: digestSitePostPayload(payload()),
      }),
    ).toEqual({ kind: "success" });
  });

  it("2xx라도 응답 siteId가 다르면 unknown이다", () => {
    expect(
      classifyLegacySitePost({
        fetchThrew: false,
        status: 201,
        bodyCode: null,
        responseSiteId: "site-OTHER",
        requestedSiteId: "site-A",
        previous: null,
        payloadDigest: digestSitePostPayload(payload()),
      }),
    ).toEqual({ kind: "unknown" });
  });

  it("관측된 2xx 뒤 같은 payload의 409도 자동 성공이 아니라 수동 확인이다 (계정 미검증)", () => {
    const seen = buildSitePostAttempt("site-A", payload(), true);
    expect(
      classifyLegacySitePost({
        fetchThrew: false,
        status: 409,
        bodyCode: DUP,
        responseSiteId: null,
        requestedSiteId: "site-A",
        previous: seen,
        payloadDigest: digestSitePostPayload(payload()),
      }),
    ).toEqual({ kind: "duplicateUnverified", sameSiteAsPrevious: true, payloadChanged: false });
  });

  it("타인 ID 첫 409는 duplicateUnverified이며 이전 기록이 없다", () => {
    expect(
      classifyLegacySitePost({
        fetchThrew: false,
        status: 409,
        bodyCode: DUP,
        responseSiteId: null,
        requestedSiteId: "site-A",
        previous: null,
        payloadDigest: digestSitePostPayload(payload()),
      }),
    ).toEqual({ kind: "duplicateUnverified", sameSiteAsPrevious: false, payloadChanged: false });
  });

  it("body가 바뀌면 payloadChanged로 표시하고 성공이 아니다", () => {
    const seen = buildSitePostAttempt("site-A", payload(), true);
    expect(
      classifyLegacySitePost({
        fetchThrew: false,
        status: 409,
        bodyCode: DUP,
        responseSiteId: null,
        requestedSiteId: "site-A",
        previous: seen,
        payloadDigest: digestSitePostPayload(payload({ name: "바뀐 이름" })),
      }),
    ).toEqual({ kind: "duplicateUnverified", sameSiteAsPrevious: true, payloadChanged: true });
  });

  it("불명 5xx는 code가 있어도 unknown이다", () => {
    expect(
      classifyLegacySitePost({
        fetchThrew: false,
        status: 503,
        bodyCode: "STORE_UNAVAILABLE",
        responseSiteId: null,
        requestedSiteId: "site-A",
        previous: null,
        payloadDigest: digestSitePostPayload(payload()),
      }),
    ).toEqual({ kind: "unknown" });
  });

  it("검증 실패(422)는 definiteFailure다", () => {
    expect(
      classifyLegacySitePost({
        fetchThrew: false,
        status: 422,
        bodyCode: "INVALID_SITE",
        responseSiteId: null,
        requestedSiteId: "site-A",
        previous: null,
        payloadDigest: digestSitePostPayload(payload()),
      }),
    ).toEqual({ kind: "definiteFailure" });
  });
});
