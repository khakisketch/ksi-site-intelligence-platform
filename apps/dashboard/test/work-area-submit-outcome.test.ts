import { describe, expect, it } from "vitest";

// `classifyWorkAreaSubmitOutcome`의 material 경계.
// 1) 코드가 있는 5xx도 확정 실패가 아니다 — Core commit 뒤 upstream 응답 유실이면
//    프록시/BFF 오류 코드가 실려 올 수 있다. 증명된 거부만 definitive.
// 2) 408/429·알 수 없는 4xx도 status만으로 '쓰기 안 됨'이 입증되지 않는다.
// 3) 2xx는 보낸 원본(name·crs·polygon·supersedes + Site)과 응답의 대조가 맞아야
//    success다. `{}`·다른 site·바뀐 값·엉뚱한 상태/verdict는 모두 unknown이다.
// 4) 목록 파서는 화면이 실제로 읽는 필드까지 검증한다.
import {
  classifyWorkAreaSubmitOutcome,
  parseWorkAreaList,
} from "@/lib/work-areas";
import { ACCOUNT_CONTINUITY_MISMATCH } from "@/lib/core-api/work-order-continuity";

const SITE = "site-1";
const POLYGON = {
  type: "Polygon",
  coordinates: [
    [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 0],
    ],
  ],
};

function request(overrides: Record<string, unknown> = {}) {
  return { name: "3공구", crs: "EPSG:4326", polygon: POLYGON, supersedes: null, ...overrides };
}

function validArea(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: "1",
    workAreaId: `wa-${SITE}-0001`,
    siteId: SITE,
    name: "3공구",
    polygon: POLYGON,
    crs: "EPSG:4326",
    status: "ACTIVE",
    supersedes: null,
    createdAt: "2026-10-28T00:00:00Z",
    ...overrides,
  };
}

function call(
  status: number | null,
  body: unknown,
  opts: { fetchThrew?: boolean; siteId?: string; request?: ReturnType<typeof request> } = {},
) {
  return classifyWorkAreaSubmitOutcome({
    fetchThrew: opts.fetchThrew ?? false,
    status,
    body,
    siteId: opts.siteId ?? SITE,
    request: opts.request ?? request(),
  });
}

describe("작업구역 제출 결과 분류 (strict)", () => {
  it("코드 있는 5xx도 unknown이다 (commit 뒤 upstream 유실 가능)", () => {
    expect(call(503, { code: "STORE_UNAVAILABLE", detail: null, workArea: null })).toEqual({
      kind: "unknown",
    });
    expect(call(502, { code: "CORE_UNAVAILABLE" })).toEqual({ kind: "unknown" });
    expect(call(500, {})).toEqual({ kind: "unknown" });
  });

  it("408/429와 알 수 없는 4xx 코드는 unknown이다", () => {
    for (const status of [408, 429, 418]) {
      expect(call(status, {})).toEqual({ kind: "unknown" });
    }
    expect(call(409, { code: "SOMETHING_NEW" })).toEqual({ kind: "unknown" });
    // 레거시 등록 경로가 낼 수 없는 404가 아니라도, 이 경로의 404는 범위 확인이라 확정이다
    expect(call(404, {})).toEqual({ kind: "definiteFailure", code: null });
  });

  it("증명된 거부만 definiteFailure다", () => {
    expect(call(403, {})).toEqual({ kind: "definiteFailure", code: null });
    expect(call(409, { verdict: "TOO_MANY_ACTIVE" })).toEqual({
      kind: "definiteFailure",
      code: "TOO_MANY_ACTIVE",
    });
    expect(call(422, { code: "INVALID_WORK_AREA" })).toEqual({
      kind: "definiteFailure",
      code: "INVALID_WORK_AREA",
    });
  });

  it("BFF 계정 가드 거부(409)는 이 요청이 쓰지 않았다는 확정이다", () => {
    // 공유 파일의 코드와 같은 값임이 아래 pin 테스트로 고정된다.
    expect(call(409, { code: ACCOUNT_CONTINUITY_MISMATCH })).toEqual({
      kind: "definiteFailure",
      code: ACCOUNT_CONTINUITY_MISMATCH,
    });
  });

  it("공유 파일의 가드 코드와 같은 값을 쓴다 (미러 pin)", () => {
    expect("ACCOUNT_CONTINUITY_MISMATCH").toBe(ACCOUNT_CONTINUITY_MISMATCH);
  });

  it("2xx라도 본문이 비었으면 unknown이다", () => {
    expect(call(201, {})).toEqual({ kind: "unknown" });
  });

  it("2xx라도 다른 siteId·빈 workAreaId면 unknown이다", () => {
    expect(call(201, { workArea: validArea({ siteId: "site-2" }) })).toEqual({ kind: "unknown" });
    expect(call(201, { workArea: validArea({ workAreaId: "" }) })).toEqual({ kind: "unknown" });
  });

  it("2xx라도 화면 필수 필드가 깨지면 unknown이다 (createdAt·polygon·status)", () => {
    expect(
      call(201, { verdict: "REGISTERED", workArea: validArea({ createdAt: "" }) }),
    ).toEqual({ kind: "unknown" });
    const noCreatedAt = validArea();
    delete (noCreatedAt as Record<string, unknown>).createdAt;
    expect(call(201, { verdict: "REGISTERED", workArea: noCreatedAt })).toEqual({ kind: "unknown" });
    expect(
      call(201, { verdict: "REGISTERED", workArea: validArea({ polygon: null }) }),
    ).toEqual({ kind: "unknown" });
    expect(call(201, { verdict: "REGISTERED", workArea: validArea({ status: "DELETED" }) })).toEqual(
      { kind: "unknown" },
    );
    expect(call(201, { verdict: "REGISTERED", workArea: validArea({ supersedes: 123 }) })).toEqual({
      kind: "unknown",
    });
  });

  it("2xx라도 보낸 원본과 다르면 unknown이다 (name·crs·polygon·supersedes)", () => {
    expect(call(201, { verdict: "REGISTERED", workArea: validArea({ name: "다른 이름" }) })).toEqual(
      { kind: "unknown" },
    );
    expect(call(201, { verdict: "REGISTERED", workArea: validArea({ crs: "EPSG:5186" }) })).toEqual(
      { kind: "unknown" },
    );
    expect(
      call(201, {
        verdict: "REGISTERED",
        workArea: validArea({ polygon: { type: "Polygon", coordinates: [] } }),
      }),
    ).toEqual({ kind: "unknown" });
    expect(
      call(201, { verdict: "REGISTERED", workArea: validArea({ supersedes: "wa-site-1-0000" }) }),
    ).toEqual({ kind: "unknown" });
  });

  it("2xx라도 상태·verdict가 다르면 unknown이다", () => {
    expect(
      call(201, { verdict: "REGISTERED", workArea: validArea({ status: "ARCHIVED" }) }),
    ).toEqual({ kind: "unknown" });
    expect(call(201, { verdict: "ARCHIVED", workArea: validArea() })).toEqual({ kind: "unknown" });
  });

  it("2xx + 같은 Site + 원본 대조 일치면 success다", () => {
    const outcome = call(201, { verdict: "REGISTERED", detail: null, workArea: validArea() });
    expect(outcome.kind).toBe("success");
  });

  it("네트워크 예외는 unknown이다", () => {
    expect(
      classifyWorkAreaSubmitOutcome({
        fetchThrew: true,
        status: null,
        body: null,
        siteId: SITE,
        request: request(),
      }),
    ).toEqual({ kind: "unknown" });
  });
});

describe("parseWorkAreaList (화면 계약 검증)", () => {
  it("ID·site만 있고 화면 필드가 깨지면 null이다 (이전 상태 보존)", () => {
    expect(parseWorkAreaList({ workAreas: [{ siteId: SITE, workAreaId: "wa-1" }] }, SITE)).toBeNull();
    expect(
      parseWorkAreaList({ workAreas: [validArea({ createdAt: "" })] }, SITE),
    ).toBeNull();
    expect(
      parseWorkAreaList({ workAreas: [validArea({ status: "DELETED" })] }, SITE),
    ).toBeNull();
    expect(parseWorkAreaList({ workAreas: [validArea({ supersedes: 1 })] }, SITE)).toBeNull();
  });

  it("다른 현장 ID 항목이 섞이면 null이다", () => {
    expect(parseWorkAreaList({ workAreas: [validArea(), validArea({ siteId: "site-2" })] }, SITE)).toBeNull();
  });

  it("비배열·깨진 본문은 null이다", () => {
    expect(parseWorkAreaList({ workAreas: "x" }, SITE)).toBeNull();
    expect(parseWorkAreaList({}, SITE)).toBeNull();
  });

  it("계약대로면 배열을 돌려준다", () => {
    expect(parseWorkAreaList({ workAreas: [validArea()] }, SITE)).toHaveLength(1);
  });
});
