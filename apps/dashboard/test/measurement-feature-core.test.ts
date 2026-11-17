import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ fetchWithToken: vi.fn() }));
vi.mock("server-only", () => ({}));
vi.mock("@/lib/core-api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/client")>();
  return { ...actual, coreFetchWithToken: mocked.fetchWithToken, coreFetch: vi.fn() };
});

import { createMeasurementFeatureWithToken, reviseMeasurementFeatureWithToken } from "@/lib/core-api/measurement";

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
    mocked.fetchWithToken.mockResolvedValue({ verdict: "CREATED", revision });
    await expect(createMeasurementFeatureWithToken("site 1", "area/1", body, "key-1", "token")).resolves.toEqual(revision);
    expect(mocked.fetchWithToken).toHaveBeenCalledWith(
      "/v1/sites/site%201/work-areas/area%2F1/measurement-features", "token",
      { method: "POST", body, headers: { "Idempotency-Key": "key-1" } },
    );
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
