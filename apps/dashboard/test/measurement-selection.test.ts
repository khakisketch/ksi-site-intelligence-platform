import { describe, expect, it } from "vitest";

import type { MeasurementFeatureRevision, SurfaceProfileJobView } from "@/lib/core-api/measurement-types";
import { captureDateLabel, chooseProfileJobs } from "@/lib/measurement-selection";

const DIGEST = `sha256:${"a".repeat(64)}`;
const OTHER_DIGEST = `sha256:${"b".repeat(64)}`;
const FEATURE_ID = `mf-${"1".repeat(32)}`;

const feature: MeasurementFeatureRevision = {
  featureId: FEATURE_ID,
  siteId: "s",
  workAreaId: "a",
  revision: 2,
  name: "북쪽 경사면",
  kind: "LINE",
  line: { crs: "EPSG:5186", vertices: [[0, 0], [1, 1]] },
  lineDigest: DIGEST,
  createdAt: "2026-11-01T00:00:00Z",
};

const asset = (n: number) => `ksa-v1-${String(n).repeat(64)}`;

function job(n: number, overrides: Partial<SurfaceProfileJobView> = {}): SurfaceProfileJobView {
  return {
    jobId: `spj-${String(n).repeat(32)}`,
    assetRef: asset(n),
    siteId: "s",
    workAreaId: "a",
    feature: { featureId: FEATURE_ID, revision: 2, lineDigest: DIGEST },
    createdAt: `2026-11-1${n}T00:00:00Z`,
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    reason: null,
    ...overrides,
  };
}

const dates: Record<string, string | null> = {
  [asset(1)]: "2026-03-14",
  [asset(2)]: "2026-06-02",
  [asset(3)]: "2026-11-02",
  [asset(4)]: null,
};
const labelOf = (assetRef: string) => ({ label: dates[assetRef] ?? "촬영 시기 미상", date: dates[assetRef] ?? null });

describe("captureDateLabel", () => {
  it("달력 날짜는 그대로, 촬영 시각은 서울 날짜로 바꾼다", () => {
    expect(captureDateLabel({ captureDate: "2026-03-14", captureStartedAt: null })).toBe("2026-03-14");
    // 15:30Z = 서울 다음 날 00:30
    expect(captureDateLabel({ captureDate: null, captureStartedAt: "2026-03-13T15:30:00Z" })).toBe("2026-03-14");
  });
  it("아무것도 없거나 읽을 수 없으면 null이다(날짜를 짐작하지 않는다)", () => {
    expect(captureDateLabel({ captureDate: null, captureStartedAt: null })).toBeNull();
    expect(captureDateLabel({ captureDate: "not-a-date", captureStartedAt: null })).toBeNull();
    expect(captureDateLabel({ captureDate: null, captureStartedAt: "garbage" })).toBeNull();
  });
});

describe("chooseProfileJobs", () => {
  it("가장 이른 날짜를 기준, 가장 늦은 날짜를 현재로 고른다", () => {
    const pick = chooseProfileJobs({ jobs: [job(3), job(1), job(2)], feature, labelOf });
    expect(pick.options.map((option) => option.label)).toEqual(["2026-03-14", "2026-06-02", "2026-11-02"]);
    expect(pick.curJobId).toBe(job(3).jobId);
    expect(pick.refJobId).toBe(job(1).jobId);
  });

  it("결과가 하나면 기준 없이 현재만 둔다", () => {
    const pick = chooseProfileJobs({ jobs: [job(2)], feature, labelOf });
    expect(pick.curJobId).toBe(job(2).jobId);
    expect(pick.refJobId).toBeNull();
  });

  it("날짜를 모르는 자료는 순서를 매기지 않고 뒤에 둔다", () => {
    const pick = chooseProfileJobs({ jobs: [job(4), job(1), job(3)], feature, labelOf });
    expect(pick.options.map((option) => option.label)).toEqual(["2026-03-14", "2026-11-02", "촬영 시기 미상"]);
    expect(pick.curJobId).toBe(job(3).jobId);
  });

  it("요청한 작업이 목록에 있을 때만 따른다", () => {
    const pick = chooseProfileJobs({ jobs: [job(1), job(2), job(3)], feature, labelOf, requestedRef: job(2).jobId, requestedCur: job(1).jobId });
    expect(pick.refJobId).toBe(job(2).jobId);
    expect(pick.curJobId).toBe(job(1).jobId);
    const bogus = chooseProfileJobs({ jobs: [job(1), job(3)], feature, labelOf, requestedRef: "spj-" + "9".repeat(32), requestedCur: "x" });
    expect(bogus.refJobId).toBe(job(1).jobId);
    expect(bogus.curJobId).toBe(job(3).jobId);
  });

  it("기준을 빈 값으로 요청하면 기준 없이 본다", () => {
    const pick = chooseProfileJobs({ jobs: [job(1), job(3)], feature, labelOf, requestedRef: "" });
    expect(pick.refJobId).toBeNull();
  });

  it("다른 개정(선 모양이 다른)의 결과는 섞지 않고 개수만 센다", () => {
    const old = job(2, { feature: { featureId: FEATURE_ID, revision: 1, lineDigest: OTHER_DIGEST } });
    const pick = chooseProfileJobs({ jobs: [old, job(3)], feature, labelOf });
    expect(pick.options.map((option) => option.jobId)).toEqual([job(3).jobId]);
    expect(pick.otherRevisionCount).toBe(1);
  });

  it("선 모양 digest가 같아도 다른 개정의 결과는 선택하지 않는다", () => {
    const old = job(2, { feature: { featureId: FEATURE_ID, revision: 1, lineDigest: DIGEST } });
    const pick = chooseProfileJobs({ jobs: [old, job(3)], feature, labelOf });
    expect(pick.options.map((option) => option.jobId)).toEqual([job(3).jobId]);
    expect(pick.otherRevisionCount).toBe(1);
  });

  it("다른 측정 선의 작업은 아예 무시한다", () => {
    const other = job(2, { feature: { featureId: `mf-${"2".repeat(32)}`, revision: 1, lineDigest: DIGEST } });
    const pick = chooseProfileJobs({ jobs: [other, job(3)], feature, labelOf });
    expect(pick.options.map((option) => option.jobId)).toEqual([job(3).jobId]);
    expect(pick.otherRevisionCount).toBe(0);
  });

  it("같은 자료의 결과가 여럿이면 가장 최근 완료만 쓴다", () => {
    const older = job(3, { jobId: `spj-${"7".repeat(32)}`, createdAt: "2026-11-01T00:00:00Z" });
    const pick = chooseProfileJobs({ jobs: [older, job(3)], feature, labelOf });
    expect(pick.options).toHaveLength(1);
    expect(pick.options[0]!.jobId).toBe(job(3).jobId);
  });

  it("완료되지 않았거나 실패한 작업은 선택지가 아니다. 실패는 이유와 함께 알린다", () => {
    const failed = job(2, { executionState: "FAILED", availability: "UNAVAILABLE", reason: "LINE_OUTSIDE_SURFACE" });
    const running = job(4, { executionState: "RUNNING", availability: "NOT_READY" });
    const pick = chooseProfileJobs({ jobs: [failed, running, job(3)], feature, labelOf });
    expect(pick.options.map((option) => option.jobId)).toEqual([job(3).jobId]);
    expect(pick.failures).toEqual([{ label: "2026-06-02", reason: "LINE_OUTSIDE_SURFACE" }]);
    expect(pick.pendingCount).toBe(1);
  });

  it("명시적으로 선택한 재요청은 완료될 때까지 같은 날짜 작업으로 유지한다", () => {
    const active = job(1, { jobId: `spj-${"9".repeat(32)}`, executionState: "RUNNING", availability: "NOT_READY" });
    const pick = chooseProfileJobs({ jobs: [active, job(1), job(3)], feature, labelOf, requestedRef: active.jobId, requestedCur: job(3).jobId });
    expect(pick.refJobId).toBe(active.jobId);
    expect(pick.curJobId).toBe(job(3).jobId);
    expect(pick.options.find((option) => option.jobId === active.jobId)?.label).toContain("단면 처리 중");
  });

  it("같은 자료가 나중에 성공했다면 이전 실패는 알리지 않는다", () => {
    const failed = job(3, { jobId: `spj-${"8".repeat(32)}`, executionState: "FAILED", availability: "UNAVAILABLE", reason: "NODATA", createdAt: "2026-11-01T00:00:00Z" });
    const pick = chooseProfileJobs({ jobs: [failed, job(3)], feature, labelOf });
    expect(pick.failures).toEqual([]);
  });

  it("날짜가 같은 자료가 둘이면 자료 참조 끝자리로 가른다", () => {
    const same = { ...dates, [asset(5)]: "2026-03-14" };
    const pick = chooseProfileJobs({
      jobs: [job(1), job(5, { createdAt: "2026-11-15T00:00:00Z" })],
      feature,
      labelOf: (ref) => ({ label: same[ref] ?? "촬영 시기 미상", date: same[ref] ?? null }),
    });
    expect(new Set(pick.options.map((option) => option.label)).size).toBe(2);
    expect(pick.options.every((option) => option.label.startsWith("2026-03-14"))).toBe(true);
  });

  it("자료에서 시작하면 그 자료의 단면만 현재로 고정하고 기준은 비운다", () => {
    const pick = chooseProfileJobs({
      jobs: [job(1), job(3)], feature, labelOf, sourceAssetRef: asset(1),
    });
    expect(pick.curJobId).toBe(job(1).jobId);
    expect(pick.refJobId).toBeNull();
  });

  it("고른 자료의 완료 단면이 없으면 다른 현재와 기준을 자동으로 대신 선택하지 않는다", () => {
    const running = job(1, { executionState: "RUNNING", availability: "NOT_READY" });
    const pick = chooseProfileJobs({
      jobs: [running, job(3)], feature, labelOf, sourceAssetRef: asset(1), requestedRef: job(3).jobId,
    });
    expect(pick.curJobId).toBeNull();
    expect(pick.refJobId).toBeNull();
    expect(pick.options.map((option) => option.jobId)).toEqual([job(3).jobId]);
  });

  it("자료 모드에서는 현재 자료를 기준으로 지정하지 않고 선택한 다른 자료만 기준에 둔다", () => {
    const pick = chooseProfileJobs({
      jobs: [job(1), job(2), job(3)], feature, labelOf,
      sourceAssetRef: asset(3), requestedRef: job(1).jobId,
    });
    expect(pick.curJobId).toBe(job(3).jobId);
    expect(pick.refJobId).toBe(job(1).jobId);

    const explicit = chooseProfileJobs({
      jobs: [job(1), job(3)], feature, labelOf,
      sourceAssetRef: asset(3), requestedRef: job(1).jobId, requestedCur: job(3).jobId,
    });
    expect(explicit.curJobId).toBe(job(3).jobId);
    expect(explicit.refJobId).toBe(job(1).jobId);

    const sameSource = chooseProfileJobs({
      jobs: [job(1), job(3)], feature, labelOf, sourceAssetRef: asset(3), requestedRef: job(3).jobId,
    });
    expect(sameSource.curJobId).toBe(job(3).jobId);
    expect(sameSource.refJobId).toBeNull();
  });

  it("선택 자료에 속하지 않는 명시적 현재 결과는 양쪽 선택을 닫는다", () => {
    const pick = chooseProfileJobs({
      jobs: [job(1), job(2), job(3)], feature, labelOf,
      sourceAssetRef: asset(3), requestedRef: job(1).jobId, requestedCur: job(2).jobId,
    });
    expect(pick.curJobId).toBeNull();
    expect(pick.refJobId).toBeNull();
  });

  it("선택 자료의 명시적 과거 완료 결과를 유지한다", () => {
    const older = job(3, { jobId: "spj-" + "8".repeat(32), createdAt: "2026-11-01T00:00:00Z" });
    const pick = chooseProfileJobs({
      jobs: [older, job(3), job(1)], feature, labelOf,
      sourceAssetRef: asset(3), requestedRef: job(1).jobId, requestedCur: older.jobId,
    });
    expect(pick.curJobId).toBe(older.jobId);
    expect(pick.refJobId).toBe(job(1).jobId);
  });

  it("알 수 없거나 미완료인 명시적 현재 결과는 양쪽 선택을 닫는다", () => {
    const running = job(3, { jobId: "spj-" + "9".repeat(32), executionState: "RUNNING", availability: "NOT_READY" });
    const unknown = chooseProfileJobs({
      jobs: [job(1), job(3)], feature, labelOf,
      sourceAssetRef: asset(3), requestedRef: job(1).jobId, requestedCur: "spj-" + "7".repeat(32),
    });
    const pending = chooseProfileJobs({
      jobs: [job(1), job(3), running], feature, labelOf,
      sourceAssetRef: asset(3), requestedRef: job(1).jobId, requestedCur: running.jobId,
    });
    expect(unknown.curJobId).toBeNull();
    expect(unknown.refJobId).toBeNull();
    expect(pending.curJobId).toBeNull();
    expect(pending.refJobId).toBeNull();
  });

  it("자료 모드에서는 선택 자료와 명시 기준의 상태만 요약한다", () => {
    const failedSource = job(3, { jobId: "spj-" + "8".repeat(32), executionState: "FAILED", availability: "UNAVAILABLE", reason: "NODATA" });
    const failedOther = job(2, { jobId: "spj-" + "6".repeat(32), executionState: "FAILED", availability: "UNAVAILABLE", reason: "OUTSIDE" });
    const waitingOther = job(1, { jobId: "spj-" + "5".repeat(32), executionState: "RUNNING", availability: "NOT_READY" });
    const sourceOnly = chooseProfileJobs({
      jobs: [failedSource, failedOther, waitingOther, job(2)], feature, labelOf, sourceAssetRef: asset(3),
    });
    expect(sourceOnly.failures).toEqual([{ label: "2026-11-02", reason: "NODATA" }]);
    expect(sourceOnly.pendingCount).toBe(0);

    const withBaseline = chooseProfileJobs({
      jobs: [job(3), failedOther, waitingOther], feature, labelOf,
      sourceAssetRef: asset(3), requestedRef: failedOther.jobId,
    });
    expect(withBaseline.failures).toEqual([{ label: "2026-06-02", reason: "OUTSIDE" }]);
    expect(withBaseline.pendingCount).toBe(0);
  });

  it("선택 자료의 과거 작업 링크가 현재 자료를 과거 결과에 고정하지 않는다", () => {
    const older = job(1, { jobId: "spj-" + "8".repeat(32), createdAt: "2026-11-01T00:00:00Z" });
    const pick = chooseProfileJobs({
      jobs: [older, job(1)], feature, labelOf, sourceAssetRef: asset(1), requestedRef: older.jobId,
    });
    expect(pick.curJobId).toBe(job(1).jobId);
    expect(pick.refJobId).toBeNull();
  });
});
