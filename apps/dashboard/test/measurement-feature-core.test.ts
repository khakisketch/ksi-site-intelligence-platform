import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ fetchWithToken: vi.fn(), fetch: vi.fn() }));
vi.mock("server-only", () => ({}));
vi.mock("@/lib/core-api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/client")>();
  return { ...actual, coreFetchWithToken: mocked.fetchWithToken, coreFetch: mocked.fetch };
});

import { createMeasurementFeatureWithToken, listSurfaceProfileJobs, reviseMeasurementFeatureWithToken } from "@/lib/core-api/measurement";

const DIGEST = `sha256:${"a".repeat(64)}`;
const FEATURE_ID = `mf-${"1".repeat(32)}`;
const revision = {
  featureId: FEATURE_ID, siteId: "site-1", workAreaId: "area-1", revision: 1, name: "북쪽", kind: "LINE",
  line: { crs: "EPSG:4326", vertices: [[127, 37], [127.001, 37]] }, lineDigest: DIGEST, createdAt: "2026-11-17T00:00:00Z",
};
const body = { workAreaId: "area-1", name: "북쪽", line: { crs: "EPSG:4326" as const, vertices: [[127, 37], [127.001, 37]] as [number, number][] } };

beforeEach(() => vi.resetAllMocks());

describe("측정 선 쓰기(Core 호출)", () => {
  it("저장은 구역 경로에 키와 토큰을 싣고 개정을 돌려준다", async () => {
    const entered = { ...body, workAreaId: "area/1" };
    const saved = { ...revision, siteId: "site 1", workAreaId: entered.workAreaId };
    mocked.fetchWithToken.mockResolvedValue({ verdict: "CREATED", revision: saved });
    await expect(createMeasurementFeatureWithToken("site 1", "area/1", entered, "key-1", "token")).resolves.toEqual(saved);
    expect(mocked.fetchWithToken).toHaveBeenCalledWith(
      "/v1/sites/site%201/work-areas/area%2F1/measurement-features", "token",
      { method: "POST", body: entered, headers: { "Idempotency-Key": "key-1" } },
    );
  });

  it("저장 응답에서 다른 구역이나 다른 선 개정은 수락하지 않는다", async () => {
    mocked.fetchWithToken.mockResolvedValue({ revision: { ...revision, workAreaId: "old-area" } });
    await expect(createMeasurementFeatureWithToken("site-1", "area-1", body, "k", "t")).rejects.toMatchObject({ status: 502 });
    const edit = { expectedRevision: 1, name: "북쪽", line: body.line };
    for (const wrong of [revision, { ...revision, revision: 2, featureId: `mf-${"3".repeat(32)}` }]) {
      mocked.fetchWithToken.mockResolvedValue({ revision: wrong });
      await expect(reviseMeasurementFeatureWithToken("site-1", "area-1", FEATURE_ID, edit, "k", "t")).rejects.toMatchObject({ status: 502 });
    }
  });

  it("고치기는 선 식별자 아래 개정 경로로 보낸다", async () => {
    mocked.fetchWithToken.mockResolvedValue({ verdict: "REVISED", revision: { ...revision, revision: 2 } });
    const out = await reviseMeasurementFeatureWithToken("site-1", "area-1", FEATURE_ID, { expectedRevision: 1, name: "n", line: body.line }, "key-2", "token");
    expect(out.revision).toBe(2);
    expect(mocked.fetchWithToken.mock.calls[0]![0]).toBe(`/v1/sites/site-1/work-areas/area-1/measurement-features/${FEATURE_ID}/revisions`);
  });

  it("계약을 어긴 응답은 성공으로 보지 않는다(502)", async () => {
    for (const bad of [{ revision: { ...revision, kind: "POLYGON" } }, { revision: null }, {}, "x", null]) {
      mocked.fetchWithToken.mockResolvedValue(bad);
      await expect(createMeasurementFeatureWithToken("site-1", "area-1", body, "k", "t")).rejects.toMatchObject({ status: 502 });
    }
  });
});

import { cancelSurfaceProfileJobWithToken, issueSurfaceProfileJobWithToken, requestAssetHeightDecisionWithToken } from "@/lib/core-api/measurement";

const JOB = {
  jobId: `spj-${"2".repeat(32)}`, assetRef: `ksa-v1-${"3".repeat(64)}`, siteId: "site-1", workAreaId: "area-1",
  feature: { featureId: FEATURE_ID, revision: 1, lineDigest: DIGEST }, createdAt: "2026-11-17T00:00:00Z",
  executionState: "QUEUED", availability: "NOT_READY", reason: null,
};

describe("단면 요청(Core 호출)", () => {
  it("판정은 자료 참조 경로에 키와 토큰을 싣고 판정을 돌려준다", async () => {
    const decision = { decisionId: "external-use-decision-1", verdict: "BLOCKED", reasons: ["VERTICAL_REFERENCE_UNKNOWN"], remediations: ["OBSERVE_VERTICAL_REFERENCE"], extra: 1 };
    mocked.fetchWithToken.mockResolvedValue({ decision });
    const out = await requestAssetHeightDecisionWithToken("site 1", "area/1", `ksa-v1-${"3".repeat(64)}`, "k:height", "token");
    expect(out.verdict).toBe("BLOCKED");
    expect(mocked.fetchWithToken).toHaveBeenCalledWith(
      `/v1/sites/site%201/work-areas/area%2F1/spatial-assets/ksa-v1-${"3".repeat(64)}/height-decision`, "token",
      { method: "POST", headers: { "Idempotency-Key": "k:height" } },
    );
  });

  it("작업 발급은 구역 경로에 본문과 키를 싣고 작업을 돌려준다", async () => {
    mocked.fetchWithToken.mockResolvedValue(JOB);
    const request = { assetRef: JOB.assetRef, feature: JOB.feature, heightDecisionId: "d", sampleSpacingM: 2.5 };
    await expect(issueSurfaceProfileJobWithToken("site-1", "area-1", request, "k:job", "token")).resolves.toEqual(JOB);
    expect(mocked.fetchWithToken).toHaveBeenCalledWith("/v1/sites/site-1/work-areas/area-1/surface-profile-jobs", "token", { method: "POST", body: request, headers: { "Idempotency-Key": "k:job" } });
  });

  it("취소는 작업 경로에 본문 없이 보낸다", async () => {
    mocked.fetchWithToken.mockResolvedValue({ ...JOB, executionState: "CANCELED" });
    await cancelSurfaceProfileJobWithToken("site-1", "area-1", JOB.jobId, "token");
    expect(mocked.fetchWithToken).toHaveBeenCalledWith(`/v1/sites/site-1/work-areas/area-1/surface-profile-jobs/${JOB.jobId}/cancel`, "token", { method: "POST" });
  });

  it("계약을 어긴 판정·작업 응답은 성공으로 보지 않는다(502)", async () => {
    for (const bad of [{ decision: { decisionId: "", verdict: "ELIGIBLE", reasons: [], remediations: [] } }, { decision: { decisionId: "d", verdict: "MAYBE", reasons: [], remediations: [] } }, { decision: { decisionId: "d", verdict: "ELIGIBLE", reasons: [1], remediations: [] } }, {}, null]) {
      mocked.fetchWithToken.mockResolvedValue(bad);
      await expect(requestAssetHeightDecisionWithToken("s", "a", `ksa-v1-${"3".repeat(64)}`, "k", "t")).rejects.toMatchObject({ status: 502 });
    }
    for (const bad of [{ ...JOB, jobId: "x" }, {}, null, "x"]) {
      mocked.fetchWithToken.mockResolvedValue(bad);
      await expect(issueSurfaceProfileJobWithToken("s", "a", { assetRef: JOB.assetRef, feature: JOB.feature, heightDecisionId: "d" }, "k", "t")).rejects.toMatchObject({ status: 502 });
      await expect(cancelSurfaceProfileJobWithToken("s", "a", JOB.jobId, "t")).rejects.toMatchObject({ status: 502 });
    }
  });
});

describe("단면 작업 목록", () => {
  it("선을 지정하면 Core에 선 식별자를 함께 보내고, 지정하지 않으면 보내지 않는다", async () => {
    mocked.fetch.mockResolvedValue({ items: [] });
    await listSurfaceProfileJobs("site-1", "area-1", { limit: 8, featureId: FEATURE_ID });
    expect(mocked.fetch).toHaveBeenLastCalledWith("/v1/sites/site-1/work-areas/area-1/surface-profile-jobs", { query: { limit: 8, feature_id: FEATURE_ID } });
    await listSurfaceProfileJobs("site-1", "area-1", { limit: 8 });
    expect(mocked.fetch).toHaveBeenLastCalledWith("/v1/sites/site-1/work-areas/area-1/surface-profile-jobs", { query: { limit: 8, feature_id: undefined } });
  });

  it("자료·선 개정의 완료 작업만 골라 현재 필터에 맞는 응답인지 확인한다", async () => {
    mocked.fetch.mockResolvedValue({ items: [JOB] });
    await expect(listSurfaceProfileJobs("site-1", "area-1", {
      limit: 12, featureId: FEATURE_ID, featureRevision: 2, assetRef: JOB.assetRef, executionGroup: "COMPLETED",
    })).rejects.toMatchObject({ status: 502 });
    expect(mocked.fetch).toHaveBeenCalledWith("/v1/sites/site-1/work-areas/area-1/surface-profile-jobs", {
      query: {
        limit: 12,
        feature_id: FEATURE_ID,
        asset_ref: JOB.assetRef,
        feature_revision: 2,
        execution_group: "COMPLETED",
      },
    });

    mocked.fetch.mockResolvedValue({ items: [{
      ...JOB,
      executionState: "COMPLETED",
      feature: { ...JOB.feature, revision: 2 },
    }] });
    await expect(listSurfaceProfileJobs("site-1", "area-1", {
      limit: 12, featureId: FEATURE_ID, featureRevision: 2, assetRef: JOB.assetRef, executionGroup: "COMPLETED",
    })).resolves.toMatchObject({ items: [{ executionState: "COMPLETED", feature: { revision: 2 } }] });

    mocked.fetch.mockResolvedValue({ items: [{ ...JOB, assetRef: `ksa-v1-${"b".repeat(64)}` }] });
    await expect(listSurfaceProfileJobs("site-1", "area-1", {
      limit: 12, featureId: FEATURE_ID, assetRef: JOB.assetRef,
    })).rejects.toMatchObject({ status: 502 });

    mocked.fetch.mockResolvedValue({ items: [{ ...JOB, siteId: "another-site" }] });
    await expect(listSurfaceProfileJobs("site-1", "area-1", { limit: 12 })).rejects.toMatchObject({ status: 502 });

    mocked.fetch.mockResolvedValue({ items: [{ ...JOB, workAreaId: "another-area" }] });
    await expect(listSurfaceProfileJobs("site-1", "area-1", { limit: 12 })).rejects.toMatchObject({ status: 502 });
  });
});
