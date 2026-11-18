import { describe, expect, it } from "vitest";

import type { SurfaceProfileJobView } from "@/lib/core-api/measurement-types";
import { hasActiveRequest, requestRows } from "@/lib/measurement-requests";

const DIGEST = `sha256:${"a".repeat(64)}`;
const FEATURE = { featureId: `mf-${"1".repeat(32)}`, revision: 2, lineDigest: DIGEST };
const asset = (n: number) => `ksa-v1-${String(n).repeat(64)}`;
const job = (n: number, id: number, overrides: Partial<SurfaceProfileJobView> = {}): SurfaceProfileJobView => ({
  jobId: `spj-${String(id).repeat(32)}`, assetRef: asset(n), siteId: "site-1", workAreaId: "area-1", feature: FEATURE,
  createdAt: `2026-11-1${id}T00:00:00Z`, executionState: "COMPLETED", availability: "AVAILABLE", reason: null, ...overrides,
});
const assets = [{ assetRef: asset(1), label: "2026-03-14" }, { assetRef: asset(2), label: "2026-11-02" }];
const rows = (jobs: SurfaceProfileJobView[]) => requestRows({ assets, jobs, feature: FEATURE });

describe("requestRows", () => {
  it("요청이 없으면 none이다", () => {
    expect(rows([])).toEqual([
      { assetRef: asset(1), label: "2026-03-14", state: "none", jobId: null, reason: null },
      { assetRef: asset(2), label: "2026-11-02", state: "none", jobId: null, reason: null },
    ]);
  });

  it("완료되어 읽을 수 있으면 done이고, 읽을 수 없으면 이유와 함께 unavailable이다", () => {
    expect(rows([job(1, 1)])[0]).toMatchObject({ state: "done", jobId: `spj-${"1".repeat(32)}` });
    expect(rows([job(1, 1, { availability: "ACCESS_REVOKED" })])[0]).toMatchObject({ state: "unavailable", reason: "ACCESS_REVOKED" });
  });

  it("진행 중이면 active이고 완료된 이전 결과보다 앞선다(중복 요청을 막는다)", () => {
    const result = rows([job(1, 1), job(1, 2, { executionState: "RUNNING", availability: "NOT_READY" })]);
    expect(result[0]).toMatchObject({ state: "active", jobId: `spj-${"2".repeat(32)}` });
    expect(hasActiveRequest(result)).toBe(true);
    expect(rows([job(1, 1, { executionState: "QUEUED", availability: "NOT_READY" })])[0]!.state).toBe("active");
  });

  it("실패·취소·만료는 다시 요청할 수 있는 상태로 사유를 싣는다", () => {
    expect(rows([job(1, 1, { executionState: "FAILED", availability: "UNAVAILABLE", reason: "LINE_OUTSIDE_SURFACE" })])[0]).toMatchObject({ state: "failed", reason: "LINE_OUTSIDE_SURFACE" });
    expect(rows([job(1, 1, { executionState: "CANCELED", availability: "UNAVAILABLE" })])[0]).toMatchObject({ state: "canceled", reason: null });
    expect(rows([job(1, 1, { executionState: "EXPIRED", availability: "UNAVAILABLE" })])[0]!.state).toBe("failed");
  });

  it("실패 뒤에 완료된 작업이 있으면 완료가 이긴다", () => {
    expect(rows([job(1, 1, { executionState: "FAILED", availability: "UNAVAILABLE", reason: "X" }), job(1, 2)])[0]!.state).toBe("done");
  });

  it("같은 선의 다른 개정·다른 모양·다른 선의 작업은 세지 않는다", () => {
    const other = (feature: Partial<typeof FEATURE>) => job(1, 1, { feature: { ...FEATURE, ...feature } });
    expect(rows([other({ revision: 1 })])[0]!.state).toBe("none");
    expect(rows([other({ lineDigest: `sha256:${"b".repeat(64)}` })])[0]!.state).toBe("none");
    expect(rows([other({ featureId: `mf-${"2".repeat(32)}` })])[0]!.state).toBe("none");
  });

  it("다른 자료의 작업은 그 자료 줄에만 붙는다", () => {
    const result = rows([job(2, 1, { executionState: "RUNNING", availability: "NOT_READY" })]);
    expect(result[0]!.state).toBe("none");
    expect(result[1]!.state).toBe("active");
    expect(hasActiveRequest(rows([]))).toBe(false);
  });

  it("같은 날짜의 자료는 자료 참조 끝자리로 구분하고, 겹치지 않으면 날짜만 쓴다", () => {
    const same = requestRows({ assets: [{ assetRef: asset(1), label: "2026-11-18" }, { assetRef: asset(2), label: "2026-11-18" }, { assetRef: asset(3), label: "2026-11-27" }], jobs: [], feature: FEATURE });
    expect(same.map((row) => row.label)).toEqual([`2026-11-18 · #${"1".repeat(4)}`, `2026-11-18 · #${"2".repeat(4)}`, "2026-11-27"]);
  });

  it("같은 시각이면 식별자 순서가 일정하다", () => {
    const a = job(1, 1, { createdAt: "2026-11-01T00:00:00Z", executionState: "FAILED", availability: "UNAVAILABLE", reason: "A" });
    const b = job(1, 2, { createdAt: "2026-11-01T00:00:00Z", executionState: "FAILED", availability: "UNAVAILABLE", reason: "B" });
    expect(rows([a, b])[0]!.reason).toBe(rows([b, a])[0]!.reason);
  });
});

import { parseProfileRequestBody } from "@/lib/measurement-requests";

describe("parseProfileRequestBody", () => {
  const ok = { assetRef: asset(1), feature: FEATURE };
  it("자료와 선 개정만 받는다", () => {
    expect(parseProfileRequestBody(ok)).toEqual(ok);
  });
  it.each([
    ["판정 식별자를 싣는 시도", { ...ok, heightDecisionId: "d" }],
    ["자료 참조 형식", { ...ok, assetRef: "x" }],
    ["선 식별자 형식", { ...ok, feature: { ...FEATURE, featureId: "x" } }],
    ["개정 0", { ...ok, feature: { ...FEATURE, revision: 0 } }],
    ["개정 상한 초과", { ...ok, feature: { ...FEATURE, revision: 101 } }],
    ["digest 형식", { ...ok, feature: { ...FEATURE, lineDigest: "x" } }],
    ["선 참조에 모르는 필드", { ...ok, feature: { ...FEATURE, extra: 1 } }],
    ["선 참조가 배열", { ...ok, feature: [] }],
    ["선 참조가 없다", { assetRef: asset(1) }],
    ["객체가 아니다", "x"],
    ["배열", []],
  ])("거부한다: %s", (_name, value) => {
    expect(parseProfileRequestBody(value)).toBeNull();
  });
});
